"""
Position Tracker - Suivi des positions ouvertes et P&L.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("trade4me")


@dataclass
class Position:
    symbol: str
    side: str  # "long" or "short"
    entry_price: float
    amount: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def cost(self) -> float:
        return self.entry_price * self.amount

    def unrealized_pnl(self, current_price: float) -> float:
        """Calcule le P&L non réalisé."""
        if self.side == "long":
            return (current_price - self.entry_price) * self.amount
        else:
            return (self.entry_price - current_price) * self.amount

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """P&L en pourcentage."""
        if self.entry_price == 0:
            return 0.0
        if self.side == "long":
            return ((current_price - self.entry_price) / self.entry_price) * 100
        else:
            return ((self.entry_price - current_price) / self.entry_price) * 100

    def should_stop_loss(self, current_price: float) -> bool:
        """Vérifie si le stop-loss est atteint."""
        if self.stop_loss <= 0:
            return False
        if self.side == "long":
            return current_price <= self.stop_loss
        else:
            return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        """Vérifie si le take-profit est atteint."""
        if self.take_profit <= 0:
            return False
        if self.side == "long":
            return current_price >= self.take_profit
        else:
            return current_price <= self.take_profit


class PositionTracker:
    """Gère les positions ouvertes."""

    def __init__(self):
        self.open_positions: list[Position] = []
        self.closed_positions: list[dict] = []
        self.total_realized_pnl: float = 0.0

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        amount: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> Position:
        """Ouvre une nouvelle position."""
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            amount=amount,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self.open_positions.append(pos)
        logger.info(
            f"Position ouverte: {side.upper()} {amount:.6f} {symbol} @ ${entry_price:,.2f} "
            f"| SL=${stop_loss:,.2f} TP=${take_profit:,.2f}"
        )
        return pos

    def close_position(self, position: Position, exit_price: float) -> float:
        """Ferme une position et retourne le P&L réalisé."""
        pnl = position.unrealized_pnl(exit_price)
        self.total_realized_pnl += pnl

        self.closed_positions.append({
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "amount": position.amount,
            "pnl": pnl,
            "pnl_pct": position.unrealized_pnl_pct(exit_price),
            "opened_at": position.opened_at,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })

        self.open_positions.remove(position)
        logger.info(
            f"Position fermée: {position.symbol} | P&L: {pnl:+.2f} USDT ({position.unrealized_pnl_pct(exit_price):+.2f}%)"
        )
        return pnl

    def get_position(self, symbol: str) -> Position | None:
        """Trouve une position ouverte par symbole."""
        for pos in self.open_positions:
            if pos.symbol == symbol:
                return pos
        return None

    def has_position(self, symbol: str) -> bool:
        """Vérifie si une position est ouverte pour un symbole."""
        return any(p.symbol == symbol for p in self.open_positions)

    def check_exits(self, symbol: str, current_price: float) -> str | None:
        """Vérifie si une position doit être fermée (SL/TP)."""
        pos = self.get_position(symbol)
        if pos is None:
            return None
        if pos.should_stop_loss(current_price):
            return "stop_loss"
        if pos.should_take_profit(current_price):
            return "take_profit"
        return None

    @property
    def stats(self) -> dict:
        """Statistiques globales."""
        if not self.closed_positions:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
            }

        wins = [t for t in self.closed_positions if t["pnl"] > 0]
        losses = [t for t in self.closed_positions if t["pnl"] <= 0]

        return {
            "total_trades": len(self.closed_positions),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(self.closed_positions) * 100,
            "total_pnl": self.total_realized_pnl,
            "open_positions": len(self.open_positions),
        }
