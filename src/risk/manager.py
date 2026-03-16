"""
Risk Manager - Gestion du risque et protection du capital.
"""

import logging

logger = logging.getLogger("trade4me")


class RiskManager:
    """Gère les limites de risque pour protéger le capital."""

    def __init__(self, config: dict):
        self.max_position_pct = config.get("max_position_pct", 2.0)
        self.stop_loss_pct = config.get("stop_loss_pct", 1.0)
        self.take_profit_pct = config.get("take_profit_pct", 1.5)
        self.max_drawdown_pct = config.get("max_drawdown_pct", 10.0)
        self.max_open_positions = config.get("max_open_positions", 3)

        self.initial_capital: float = 0.0
        self.peak_capital: float = 0.0

    def set_capital(self, capital: float):
        """Définit le capital initial."""
        self.initial_capital = capital
        self.peak_capital = capital

    def calculate_position_size(self, capital: float, price: float) -> float:
        """Calcule la taille de position basée sur le % max du capital."""
        max_amount_usdt = capital * (self.max_position_pct / 100)
        return max_amount_usdt / price if price > 0 else 0.0

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """Calcule le prix du stop-loss."""
        if side == "long":
            return entry_price * (1 - self.stop_loss_pct / 100)
        else:
            return entry_price * (1 + self.stop_loss_pct / 100)

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Calcule le prix du take-profit."""
        if side == "long":
            return entry_price * (1 + self.take_profit_pct / 100)
        else:
            return entry_price * (1 - self.take_profit_pct / 100)

    def can_open_position(self, current_open: int) -> bool:
        """Vérifie si on peut ouvrir une nouvelle position."""
        if current_open >= self.max_open_positions:
            logger.warning(f"Max positions atteint ({self.max_open_positions})")
            return False
        return True

    def check_drawdown(self, current_capital: float) -> bool:
        """
        Vérifie le drawdown. Retourne True si le drawdown max est dépassé.
        """
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital

        if self.peak_capital == 0:
            return False

        drawdown = ((self.peak_capital - current_capital) / self.peak_capital) * 100

        if drawdown >= self.max_drawdown_pct:
            logger.error(
                f"DRAWDOWN MAX ATTEINT: {drawdown:.2f}% >= {self.max_drawdown_pct}% | "
                f"Capital: ${current_capital:,.2f} (pic: ${self.peak_capital:,.2f})"
            )
            return True

        if drawdown > self.max_drawdown_pct * 0.7:
            logger.warning(f"Drawdown élevé: {drawdown:.2f}%")

        return False

    def validate_trade(self, capital: float, price: float, current_open: int) -> dict:
        """
        Valide un trade et retourne les paramètres calculés.
        Retourne None si le trade est refusé.
        """
        if not self.can_open_position(current_open):
            return None

        if self.check_drawdown(capital):
            return None

        amount = self.calculate_position_size(capital, price)
        if amount <= 0:
            return None

        return {
            "amount": amount,
            "stop_loss": self.calculate_stop_loss(price, "long"),
            "take_profit": self.calculate_take_profit(price, "long"),
            "position_value_usdt": amount * price,
            "position_pct": (amount * price / capital * 100) if capital > 0 else 0,
        }
