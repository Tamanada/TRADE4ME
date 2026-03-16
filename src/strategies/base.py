"""
Base Strategy - Classe abstraite pour toutes les stratégies de trading.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    signal: Signal
    symbol: str
    reason: str
    strength: float = 0.0  # 0.0 à 1.0 - force du signal
    price: float = 0.0


class BaseStrategy(ABC):
    """Classe abstraite que toutes les stratégies doivent implémenter."""

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """
        Analyse les données et retourne un signal de trading.

        Args:
            df: DataFrame avec colonnes OHLCV + indicateurs techniques
            symbol: Paire de trading (ex: BTC/USDT)

        Returns:
            TradeSignal avec BUY, SELL ou HOLD
        """
        pass

    def _validate_data(self, df: pd.DataFrame, min_rows: int = 50) -> bool:
        """Vérifie que le DataFrame a assez de données."""
        return len(df) >= min_rows and not df.empty
