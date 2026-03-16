"""
Stratégie Scalping RSI Bounce.

Logique:
- BUY  : RSI en survente (< seuil) + prix au-dessus EMA tendance + volume élevé
- SELL : RSI en surachat (> seuil) + prix en dessous EMA tendance + volume élevé
- HOLD : RSI en zone neutre
"""

import pandas as pd
from src.strategies.base import BaseStrategy, Signal, TradeSignal


class ScalpRSIStrategy(BaseStrategy):
    def __init__(self, config: dict = None):
        super().__init__("scalp_rsi", config)
        self.rsi_entry = self.config.get("rsi_entry", 25)
        self.rsi_exit = self.config.get("rsi_exit", 70)
        self.ema_trend = self.config.get("ema_trend", 50)
        self.min_volume_ratio = self.config.get("min_volume_ratio", 1.2)

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        if not self._validate_data(df):
            return TradeSignal(Signal.HOLD, symbol, "Pas assez de données")

        current = df.iloc[-1]
        ema_trend_col = f"ema_{self.ema_trend}"

        required = ["rsi", ema_trend_col, "volume_ratio"]
        if not all(col in df.columns for col in required):
            return TradeSignal(Signal.HOLD, symbol, "Indicateurs manquants")

        rsi = current["rsi"]
        price = current["close"]
        ema_val = current[ema_trend_col]
        volume_ok = current["volume_ratio"] >= self.min_volume_ratio

        # BUY: RSI en survente + tendance haussière (prix > EMA)
        if rsi <= self.rsi_entry and price > ema_val and volume_ok:
            strength = min(1.0, (self.rsi_entry - rsi) / self.rsi_entry + 0.3)
            return TradeSignal(
                Signal.BUY,
                symbol,
                f"RSI survente ({rsi:.1f} < {self.rsi_entry}) | Prix > EMA{self.ema_trend} | Vol={current['volume_ratio']:.1f}x",
                strength=strength,
                price=price,
            )

        # SELL: RSI en surachat + tendance baissière (prix < EMA)
        if rsi >= self.rsi_exit and price < ema_val and volume_ok:
            strength = min(1.0, (rsi - self.rsi_exit) / (100 - self.rsi_exit) + 0.3)
            return TradeSignal(
                Signal.SELL,
                symbol,
                f"RSI surachat ({rsi:.1f} > {self.rsi_exit}) | Prix < EMA{self.ema_trend} | Vol={current['volume_ratio']:.1f}x",
                strength=strength,
                price=price,
            )

        return TradeSignal(Signal.HOLD, symbol, f"RSI neutre ({rsi:.1f})")
