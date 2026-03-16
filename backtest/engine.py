"""
Backtesting Engine - Teste les stratégies sur données historiques.
"""

import logging
import pandas as pd
from dataclasses import dataclass, field

from src.indicators.technical import add_all_indicators
from src.strategies.base import BaseStrategy, Signal
from src.risk.manager import RiskManager

logger = logging.getLogger("trade4me")


@dataclass
class BacktestTrade:
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    amount: float
    side: str
    pnl: float
    pnl_pct: float
    reason: str


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    timeframe: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)


class BacktestEngine:
    """Moteur de backtesting pour tester les stratégies."""

    def __init__(self, initial_capital: float = 10000.0, risk_config: dict = None):
        self.initial_capital = initial_capital
        risk_config = risk_config or {
            "max_position_pct": 2.0,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 1.5,
            "max_drawdown_pct": 10.0,
            "max_open_positions": 1,
        }
        self.risk_manager = RiskManager(risk_config)

    def run(
        self,
        strategy: BaseStrategy,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str = "1m",
    ) -> BacktestResult:
        """
        Exécute le backtest d'une stratégie sur un DataFrame historique.
        """
        # Ajouter les indicateurs
        df = add_all_indicators(df)
        df = df.dropna()

        result = BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            timeframe=timeframe,
        )

        capital = self.initial_capital
        self.risk_manager.set_capital(capital)
        position = None
        peak_capital = capital
        max_drawdown = 0.0
        equity_curve = [capital]

        # Itérer bougie par bougie
        for i in range(50, len(df)):
            window = df.iloc[:i + 1]
            current_price = df.iloc[i]["close"]

            # Vérifier SL/TP si position ouverte
            if position:
                sl_price = position["stop_loss"]
                tp_price = position["take_profit"]

                exit_price = None
                reason = ""

                if current_price <= sl_price:
                    exit_price = sl_price
                    reason = "stop_loss"
                elif current_price >= tp_price:
                    exit_price = tp_price
                    reason = "take_profit"

                if exit_price:
                    pnl = (exit_price - position["entry_price"]) * position["amount"]
                    pnl_pct = ((exit_price - position["entry_price"]) / position["entry_price"]) * 100
                    capital += pnl

                    result.trades.append(BacktestTrade(
                        entry_idx=position["entry_idx"],
                        exit_idx=i,
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        amount=position["amount"],
                        side="long",
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        reason=reason,
                    ))
                    position = None

            # Analyser si pas de position
            if position is None:
                signal = strategy.analyze(window, symbol)

                if signal.signal == Signal.BUY:
                    trade_params = self.risk_manager.validate_trade(capital, current_price, 0)
                    if trade_params:
                        position = {
                            "entry_idx": i,
                            "entry_price": current_price,
                            "amount": trade_params["amount"],
                            "stop_loss": trade_params["stop_loss"],
                            "take_profit": trade_params["take_profit"],
                        }
                        capital -= trade_params["position_value_usdt"]

            # Equity curve
            total_value = capital
            if position:
                total_value += position["amount"] * current_price
            equity_curve.append(total_value)

            # Drawdown
            if total_value > peak_capital:
                peak_capital = total_value
            dd = ((peak_capital - total_value) / peak_capital) * 100 if peak_capital > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        # Fermer la position finale
        if position:
            final_price = df.iloc[-1]["close"]
            pnl = (final_price - position["entry_price"]) * position["amount"]
            capital += pnl
            result.trades.append(BacktestTrade(
                entry_idx=position["entry_idx"],
                exit_idx=len(df) - 1,
                entry_price=position["entry_price"],
                exit_price=final_price,
                amount=position["amount"],
                side="long",
                pnl=pnl,
                pnl_pct=((final_price - position["entry_price"]) / position["entry_price"]) * 100,
                reason="end_of_data",
            ))

        # Calculer les statistiques
        result.equity_curve = equity_curve
        result.total_trades = len(result.trades)
        result.max_drawdown = max_drawdown

        if result.total_trades > 0:
            wins = [t for t in result.trades if t.pnl > 0]
            losses = [t for t in result.trades if t.pnl <= 0]
            result.wins = len(wins)
            result.losses = len(losses)
            result.win_rate = (len(wins) / result.total_trades) * 100
            result.total_pnl = sum(t.pnl for t in result.trades)
            result.avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
            result.avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
            total_loss = abs(sum(t.pnl for t in losses)) if losses else 0
            total_gain = sum(t.pnl for t in wins) if wins else 0
            result.profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")

            # Sharpe Ratio simplifié
            pnls = pd.Series([t.pnl for t in result.trades])
            if pnls.std() > 0:
                result.sharpe_ratio = (pnls.mean() / pnls.std()) * (252 ** 0.5)

        return result
