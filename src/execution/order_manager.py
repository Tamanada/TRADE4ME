"""
Order Manager - Gestion des ordres de trading.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from src.exchange.client import ExchangeClient
from src.utils.logger import log_trade

logger = logging.getLogger("trade4me")


@dataclass
class Order:
    id: str
    symbol: str
    side: str  # "buy" or "sell"
    order_type: str  # "market" or "limit"
    amount: float
    price: float
    status: str = "pending"  # pending, filled, cancelled, failed
    filled_price: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OrderManager:
    """Gère le passage et le suivi des ordres."""

    def __init__(self, client: ExchangeClient, paper_mode: bool = True):
        self.client = client
        self.paper_mode = paper_mode
        self.orders: list[Order] = []

    def place_market_order(self, symbol: str, side: str, amount: float, price: float = 0.0) -> Order:
        """Place un ordre au marché (réel ou simulé)."""
        order_id = f"paper_{len(self.orders)}" if self.paper_mode else ""

        if self.paper_mode:
            # Simulation - pas d'appel à l'exchange
            order = Order(
                id=order_id,
                symbol=symbol,
                side=side,
                order_type="market",
                amount=amount,
                price=price,
                status="filled",
                filled_price=price,
            )
            logger.info(f"[PAPER] {side.upper()} {amount:.6f} {symbol} @ ${price:,.2f}")
        else:
            # Ordre réel
            try:
                if side == "buy":
                    result = self.client.create_market_buy(symbol, amount)
                else:
                    result = self.client.create_market_sell(symbol, amount)

                order = Order(
                    id=result.get("id", "unknown"),
                    symbol=symbol,
                    side=side,
                    order_type="market",
                    amount=amount,
                    price=result.get("average", price),
                    status="filled",
                    filled_price=result.get("average", price),
                )
                logger.info(f"[LIVE] {side.upper()} {amount:.6f} {symbol} @ ${order.filled_price:,.2f}")
            except Exception as e:
                logger.error(f"Erreur ordre {side} {symbol}: {e}")
                order = Order(
                    id="failed",
                    symbol=symbol,
                    side=side,
                    order_type="market",
                    amount=amount,
                    price=price,
                    status="failed",
                )

        self.orders.append(order)
        log_trade(side, symbol, order.filled_price or price, amount)
        return order

    def get_recent_orders(self, limit: int = 10) -> list[Order]:
        """Retourne les ordres récents."""
        return self.orders[-limit:]
