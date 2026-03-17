"""
Arbitrage Executor — Exécute des trades d'arbitrage simultanés sur 2 exchanges.
Achète sur l'exchange le moins cher, vend sur le plus cher, en même temps.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from src.exchange.client_pool import MultiExchangeClientPool

logger = logging.getLogger("trade4me")


@dataclass
class ArbLegResult:
    """Résultat d'une jambe (leg) d'arbitrage."""
    exchange: str
    side: str               # "buy" or "sell"
    symbol: str
    intended_price: float
    filled_price: float     # 0 si échec
    amount: float
    status: str             # "filled", "paper_filled", "failed"
    order_id: str
    error: str | None
    timestamp: str


@dataclass
class ArbExecutionResult:
    """Résultat complet d'une exécution d'arbitrage (2 legs)."""
    id: str                         # UUID unique
    symbol: str
    buy_leg: ArbLegResult
    sell_leg: ArbLegResult
    intended_spread_pct: float      # Spread du scan
    actual_spread_pct: float        # Spread réel (prix remplis)
    gross_profit_usdt: float        # Profit brut (avant frais)
    net_profit_usdt: float          # Profit net (après frais)
    buy_fee_pct: float              # Frais taker buy (%)
    sell_fee_pct: float             # Frais taker sell (%)
    total_fees_usdt: float          # Total frais en USDT
    trade_amount_usdt: float        # Montant tradé
    status: str                     # "success", "partial", "failed"
    paper_mode: bool
    executed_at: str

    def to_dict(self) -> dict:
        """Sérialise en dict pour JSON."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "buy_leg": {
                "exchange": self.buy_leg.exchange,
                "side": self.buy_leg.side,
                "intended_price": self.buy_leg.intended_price,
                "filled_price": self.buy_leg.filled_price,
                "amount": self.buy_leg.amount,
                "status": self.buy_leg.status,
                "order_id": self.buy_leg.order_id,
                "error": self.buy_leg.error,
            },
            "sell_leg": {
                "exchange": self.sell_leg.exchange,
                "side": self.sell_leg.side,
                "intended_price": self.sell_leg.intended_price,
                "filled_price": self.sell_leg.filled_price,
                "amount": self.sell_leg.amount,
                "status": self.sell_leg.status,
                "order_id": self.sell_leg.order_id,
                "error": self.sell_leg.error,
            },
            "intended_spread_pct": round(self.intended_spread_pct, 3),
            "actual_spread_pct": round(self.actual_spread_pct, 3),
            "gross_profit_usdt": round(self.gross_profit_usdt, 4),
            "net_profit_usdt": round(self.net_profit_usdt, 4),
            "buy_fee_pct": round(self.buy_fee_pct, 3),
            "sell_fee_pct": round(self.sell_fee_pct, 3),
            "total_fees_usdt": round(self.total_fees_usdt, 4),
            "trade_amount_usdt": round(self.trade_amount_usdt, 2),
            "status": self.status,
            "paper_mode": self.paper_mode,
            "executed_at": self.executed_at,
        }


class ArbitrageExecutor:
    """
    Exécute des arbitrages simultanés sur 2 exchanges.
    Paper mode par défaut — live mode nécessite confirmation explicite.
    """

    def __init__(self, client_pool: MultiExchangeClientPool, config: dict):
        self.client_pool = client_pool
        self.paper_mode = config.get("mode", "paper") == "paper"
        self.max_trade_usdt = config.get("max_trade_usdt", 100)
        self.min_spread_pct = config.get("min_spread_pct", 0.3)
        self.max_slippage_pct = config.get("max_slippage_pct", 0.5)
        self.live_confirmed = False  # Doit être True pour exécuter en live
        self.execution_history: list[ArbExecutionResult] = []

    def validate(self, symbol: str, buy_exchange: str, sell_exchange: str,
                 spread_pct: float) -> tuple[bool, str]:
        """Valide qu'un arbitrage peut être exécuté."""
        # 1. Spread minimum
        if spread_pct < self.min_spread_pct:
            return False, f"Spread {spread_pct:.3f}% < minimum {self.min_spread_pct}%"

        # 2. En mode paper, pas besoin de clés API
        if self.paper_mode:
            return True, "OK (paper mode)"

        # 3. En mode live, vérifier la confirmation
        if not self.live_confirmed:
            return False, "Mode live non confirmé. Tapez 'OUI JE CONFIRME'"

        # 4. Vérifier les clés API
        if not self.client_pool.has_client(buy_exchange):
            return False, f"Pas de clés API pour {buy_exchange}"
        if not self.client_pool.has_client(sell_exchange):
            return False, f"Pas de clés API pour {sell_exchange}"

        return True, "OK"

    def _execute_leg(self, exchange_name: str, symbol: str, side: str,
                     amount: float, expected_price: float) -> ArbLegResult:
        """Exécute une jambe (buy ou sell) sur un exchange."""
        now = datetime.now(timezone.utc).isoformat()

        # ── Paper mode : simulation instantanée ──
        if self.paper_mode:
            return ArbLegResult(
                exchange=exchange_name,
                side=side,
                symbol=symbol,
                intended_price=expected_price,
                filled_price=expected_price,
                amount=amount,
                status="paper_filled",
                order_id=f"paper_{uuid.uuid4().hex[:8]}",
                error=None,
                timestamp=now,
            )

        # ── Live mode : ordre réel via CCXT ──
        client = self.client_pool.get_client(exchange_name)
        if not client:
            return ArbLegResult(
                exchange=exchange_name, side=side, symbol=symbol,
                intended_price=expected_price, filled_price=0, amount=amount,
                status="failed", order_id="",
                error=f"Client non configuré pour {exchange_name}",
                timestamp=now,
            )

        try:
            if side == "buy":
                order = client.create_market_buy(symbol, amount)
            else:
                order = client.create_market_sell(symbol, amount)

            filled_price = order.get("average") or order.get("price") or expected_price

            return ArbLegResult(
                exchange=exchange_name,
                side=side,
                symbol=symbol,
                intended_price=expected_price,
                filled_price=float(filled_price),
                amount=amount,
                status="filled",
                order_id=str(order.get("id", "")),
                error=None,
                timestamp=now,
            )
        except Exception as e:
            logger.error(f"Erreur exécution {side} {symbol} sur {exchange_name}: {e}")
            return ArbLegResult(
                exchange=exchange_name, side=side, symbol=symbol,
                intended_price=expected_price, filled_price=0, amount=amount,
                status="failed", order_id="", error=str(e),
                timestamp=now,
            )

    def execute(self, symbol: str, buy_exchange: str, buy_price: float,
                sell_exchange: str, sell_price: float,
                spread_pct: float,
                buy_fee_pct: float = 0.0, sell_fee_pct: float = 0.0) -> ArbExecutionResult:
        """
        Exécute un arbitrage simultané : BUY sur un exchange, SELL sur l'autre.
        Les 2 ordres sont lancés en parallèle via ThreadPoolExecutor.
        """
        exec_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Validation
        ok, reason = self.validate(symbol, buy_exchange, sell_exchange, spread_pct)
        if not ok:
            failed_leg = ArbLegResult(
                exchange="", side="", symbol=symbol,
                intended_price=0, filled_price=0, amount=0,
                status="failed", order_id="", error=reason,
                timestamp=now,
            )
            result = ArbExecutionResult(
                id=exec_id, symbol=symbol,
                buy_leg=failed_leg, sell_leg=failed_leg,
                intended_spread_pct=spread_pct, actual_spread_pct=0,
                gross_profit_usdt=0, net_profit_usdt=0,
                buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
                total_fees_usdt=0, trade_amount_usdt=0,
                status="failed", paper_mode=self.paper_mode,
                executed_at=now,
            )
            self.execution_history.append(result)
            return result

        # Calcul du montant
        amount = self.max_trade_usdt / buy_price if buy_price > 0 else 0
        trade_usdt = self.max_trade_usdt

        logger.info(
            f"Exécution arbitrage {symbol}: "
            f"BUY {buy_exchange} @ {buy_price} → SELL {sell_exchange} @ {sell_price} "
            f"(spread: {spread_pct:.3f}%, montant: {amount:.6f}, "
            f"{'PAPER' if self.paper_mode else 'LIVE'})"
        )

        # ── Exécution simultanée des 2 legs ──
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_buy = executor.submit(
                self._execute_leg, buy_exchange, symbol, "buy", amount, buy_price
            )
            future_sell = executor.submit(
                self._execute_leg, sell_exchange, symbol, "sell", amount, sell_price
            )

            buy_leg = future_buy.result(timeout=30)
            sell_leg = future_sell.result(timeout=30)

        # Calcul du spread réel + frais
        if buy_leg.filled_price > 0 and sell_leg.filled_price > 0:
            actual_spread = sell_leg.filled_price - buy_leg.filled_price
            actual_spread_pct = (actual_spread / buy_leg.filled_price * 100)
            gross_profit = actual_spread * amount

            # Frais: buy_fee sur le montant acheté, sell_fee sur le montant vendu
            buy_fee_usdt = (buy_fee_pct / 100) * buy_leg.filled_price * amount
            sell_fee_usdt = (sell_fee_pct / 100) * sell_leg.filled_price * amount
            total_fees_usdt = buy_fee_usdt + sell_fee_usdt
            net_profit = gross_profit - total_fees_usdt
        else:
            actual_spread_pct = 0
            gross_profit = 0
            total_fees_usdt = 0
            net_profit = 0

        # Status global
        if buy_leg.status in ("filled", "paper_filled") and sell_leg.status in ("filled", "paper_filled"):
            status = "success"
        elif buy_leg.status == "failed" and sell_leg.status == "failed":
            status = "failed"
        else:
            status = "partial"

        result = ArbExecutionResult(
            id=exec_id,
            symbol=symbol,
            buy_leg=buy_leg,
            sell_leg=sell_leg,
            intended_spread_pct=spread_pct,
            actual_spread_pct=actual_spread_pct,
            gross_profit_usdt=gross_profit,
            net_profit_usdt=net_profit,
            buy_fee_pct=buy_fee_pct,
            sell_fee_pct=sell_fee_pct,
            total_fees_usdt=total_fees_usdt,
            trade_amount_usdt=trade_usdt,
            status=status,
            paper_mode=self.paper_mode,
            executed_at=now,
        )

        self.execution_history.append(result)
        # Garder les 100 dernières exécutions
        if len(self.execution_history) > 100:
            self.execution_history = self.execution_history[-100:]

        logger.info(
            f"Arbitrage {exec_id[:8]}: {status} | "
            f"Spread prévu: {spread_pct:.3f}% → réel: {actual_spread_pct:.3f}% | "
            f"Brut: ${gross_profit:.4f} - Frais: ${total_fees_usdt:.4f} = Net: ${net_profit:.4f}"
        )

        return result
