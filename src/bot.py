"""
Bot Engine - Le coeur de TRADE4ME.
Boucle principale: fetch data → analyze → decide → execute → log
"""

import time
import logging
import yaml
from pathlib import Path
from dotenv import load_dotenv
import os

from src.exchange.client import ExchangeClient
from src.data.fetcher import DataFetcher
from src.indicators.technical import add_all_indicators
from src.strategies.base import Signal
from src.strategies.scalp_ema import ScalpEMAStrategy
from src.strategies.scalp_rsi import ScalpRSIStrategy
from src.strategies.scalp_momentum import ScalpMomentumStrategy
from src.execution.order_manager import OrderManager
from src.execution.position_tracker import PositionTracker
from src.risk.manager import RiskManager
from src.utils.logger import setup_logger, log_signal, console
from src.utils.notifier import Notifier

logger = logging.getLogger("trade4me")


class TradingBot:
    """Le bot de trading principal."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        load_dotenv()

        # Charger la configuration
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        strat_path = Path("config/strategies.yaml")
        with open(strat_path) as f:
            self.strat_config = yaml.safe_load(f)

        # Setup logger
        log_level = self.config.get("bot", {}).get("log_level", "INFO")
        setup_logger("trade4me", log_level)

        # Mode de trading
        self.paper_mode = self.config.get("trading", {}).get("mode", "paper") == "paper"

        # Connexion exchange
        self.client = ExchangeClient(
            exchange_name=os.getenv("EXCHANGE_NAME", self.config["exchange"]["name"]),
            api_key=os.getenv("EXCHANGE_API_KEY"),
            api_secret=os.getenv("EXCHANGE_API_SECRET"),
            sandbox=self.config["exchange"].get("sandbox", True),
        )

        # Composants
        self.fetcher = DataFetcher(self.client)
        self.order_manager = OrderManager(self.client, paper_mode=self.paper_mode)
        self.position_tracker = PositionTracker()
        self.risk_manager = RiskManager(self.config.get("risk", {}))
        self.notifier = Notifier()

        # Stratégies
        self.strategies = self._load_strategies()

        # Configuration trading
        self.symbols = self.config.get("trading", {}).get("symbols", ["BTC/USDT"])
        self.timeframe = self.config.get("trading", {}).get("timeframe", "1m")
        self.candle_limit = self.config.get("trading", {}).get("candle_limit", 100)
        self.loop_interval = self.config.get("bot", {}).get("loop_interval_sec", 10)

        # État
        self.running = False
        self.paper_capital = 10000.0  # Capital simulé en USDT

    def _load_strategies(self) -> list:
        """Charge les stratégies activées."""
        strategies = []

        if self.strat_config.get("scalp_ema", {}).get("enabled", False):
            strategies.append(ScalpEMAStrategy(self.strat_config["scalp_ema"]))
            logger.info("Stratégie chargée: Scalp EMA")

        if self.strat_config.get("scalp_rsi", {}).get("enabled", False):
            strategies.append(ScalpRSIStrategy(self.strat_config["scalp_rsi"]))
            logger.info("Stratégie chargée: Scalp RSI")

        if self.strat_config.get("scalp_momentum", {}).get("enabled", False):
            strategies.append(ScalpMomentumStrategy(self.strat_config["scalp_momentum"]))
            logger.info("Stratégie chargée: Scalp Momentum")

        if not strategies:
            logger.warning("Aucune stratégie activée!")

        return strategies

    def _get_capital(self) -> float:
        """Retourne le capital disponible."""
        if self.paper_mode:
            return self.paper_capital
        balance = self.client.get_balance("USDT")
        return balance["free"]

    def _process_symbol(self, symbol: str):
        """Traite une paire de trading: fetch → analyze → decide → execute."""

        # 1. Récupérer les données
        try:
            df = self.fetcher.get_candles(symbol, self.timeframe, self.candle_limit)
        except Exception as e:
            logger.error(f"Erreur fetch {symbol}: {e}")
            return

        # 2. Ajouter les indicateurs
        df = add_all_indicators(df)

        # 3. Vérifier les sorties (SL/TP) pour les positions existantes
        if self.position_tracker.has_position(symbol):
            current_price = df.iloc[-1]["close"]
            exit_reason = self.position_tracker.check_exits(symbol, current_price)

            if exit_reason:
                position = self.position_tracker.get_position(symbol)
                pnl = self.position_tracker.close_position(position, current_price)
                self.order_manager.place_market_order(
                    symbol, "sell", position.amount, current_price
                )

                if self.paper_mode:
                    self.paper_capital += pnl

                if exit_reason == "stop_loss":
                    self.notifier.notify_stop_loss(symbol, position.unrealized_pnl_pct(current_price))
                else:
                    self.notifier.notify_take_profit(symbol, position.unrealized_pnl_pct(current_price))
                return

        # 4. Analyser avec chaque stratégie
        for strategy in self.strategies:
            signal = strategy.analyze(df, symbol)

            if signal.signal == Signal.HOLD:
                continue

            log_signal(signal.signal.value, symbol, signal.reason)

            # 5. Exécuter si conditions remplies
            if signal.signal == Signal.BUY and not self.position_tracker.has_position(symbol):
                capital = self._get_capital()
                trade_params = self.risk_manager.validate_trade(
                    capital, signal.price, len(self.position_tracker.open_positions)
                )

                if trade_params is None:
                    logger.debug(f"Trade refusé par le risk manager: {symbol}")
                    continue

                # Placer l'ordre
                order = self.order_manager.place_market_order(
                    symbol, "buy", trade_params["amount"], signal.price
                )

                if order.status == "filled":
                    self.position_tracker.open_position(
                        symbol=symbol,
                        side="long",
                        entry_price=order.filled_price,
                        amount=trade_params["amount"],
                        stop_loss=trade_params["stop_loss"],
                        take_profit=trade_params["take_profit"],
                    )
                    if self.paper_mode:
                        self.paper_capital -= trade_params["position_value_usdt"]

                    self.notifier.notify_trade("BUY", symbol, order.filled_price, trade_params["amount"])
                break  # Un seul trade par cycle par symbole

            elif signal.signal == Signal.SELL and self.position_tracker.has_position(symbol):
                position = self.position_tracker.get_position(symbol)
                pnl = self.position_tracker.close_position(position, signal.price)
                self.order_manager.place_market_order(
                    symbol, "sell", position.amount, signal.price
                )

                if self.paper_mode:
                    self.paper_capital += pnl

                self.notifier.notify_trade("SELL", symbol, signal.price, position.amount)
                break

    def _print_status(self):
        """Affiche le statut actuel du bot."""
        stats = self.position_tracker.stats
        capital = self._get_capital()

        console.print("\n" + "=" * 60)
        mode_str = "[bold yellow]PAPER[/bold yellow]" if self.paper_mode else "[bold red]LIVE[/bold red]"
        console.print(f"  TRADE4ME | Mode: {mode_str} | Capital: [bold]${capital:,.2f}[/bold]")
        console.print(
            f"  Trades: {stats['total_trades']} | "
            f"Win Rate: {stats['win_rate']:.1f}% | "
            f"P&L: {'[green]' if stats['total_pnl'] >= 0 else '[red]'}"
            f"${stats['total_pnl']:+,.2f}{'[/green]' if stats['total_pnl'] >= 0 else '[/red]'}"
        )
        console.print(
            f"  Positions ouvertes: {stats.get('open_positions', 0)} | "
            f"Symboles: {', '.join(self.symbols)}"
        )
        console.print("=" * 60 + "\n")

    def run(self):
        """Boucle principale du bot."""
        self.running = True
        self.risk_manager.set_capital(self._get_capital())

        console.print("\n[bold cyan]" + "=" * 60)
        console.print("   TRADE4ME - Bot de Trading Crypto")
        console.print("=" * 60 + "[/bold cyan]")
        mode = "PAPER TRADING (simulation)" if self.paper_mode else "LIVE TRADING"
        console.print(f"  Mode: [bold]{mode}[/bold]")
        console.print(f"  Exchange: {self.client.exchange_name}")
        console.print(f"  Paires: {', '.join(self.symbols)}")
        console.print(f"  Timeframe: {self.timeframe}")
        console.print(f"  Stratégies: {len(self.strategies)} actives")
        console.print(f"  Capital: ${self._get_capital():,.2f}")
        console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]\n")

        logger.info("Bot démarré!")

        try:
            cycle = 0
            while self.running:
                cycle += 1
                logger.debug(f"--- Cycle {cycle} ---")

                for symbol in self.symbols:
                    self._process_symbol(symbol)

                # Afficher le statut tous les 6 cycles (~1 min avec 10s d'intervalle)
                if cycle % 6 == 0:
                    self._print_status()

                # Vérifier le drawdown
                if self.risk_manager.check_drawdown(self._get_capital()):
                    console.print("[bold red]BOT ARRETE - DRAWDOWN MAX ATTEINT[/bold red]")
                    self.stop()
                    break

                time.sleep(self.loop_interval)

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Arrêt du bot (Ctrl+C)...[/bold yellow]")
            self.stop()

    def stop(self):
        """Arrête le bot proprement."""
        self.running = False
        self._print_status()
        self.notifier.notify_bot_status("Bot arrêté")
        logger.info("Bot arrêté.")
