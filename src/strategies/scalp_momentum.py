"""
Stratégie Scalping Momentum.

Logique:
- BUY  : MACD croise signal par le haut + prix rebondit sur BB lower + volume élevé
- SELL : MACD croise signal par le bas + prix touche BB upper + volume élevé
- HOLD : Pas de confluence suffisante
"""

import pandas as pd
from src.strategies.base import BaseStrategy, Signal, TradeSignal


class ScalpMomentumStrategy(BaseStrategy):
    def __init__(self, config: dict = None):
        super().__init__("scalp_momentum", config)
        self.min_volume_ratio = self.config.get("min_volume_ratio", 2.0)

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        if not self._validate_data(df):
            return TradeSignal(Signal.HOLD, symbol, "Pas assez de données")

        current = df.iloc[-1]
        previous = df.iloc[-2]

        required = ["macd", "macd_signal", "bb_lower", "bb_upper", "volume_ratio"]
        if not all(col in df.columns for col in required):
            return TradeSignal(Signal.HOLD, symbol, "Indicateurs manquants")

        # MACD crossover
        macd_cross_up = (
            previous["macd"] <= previous["macd_signal"]
            and current["macd"] > current["macd_signal"]
        )
        macd_cross_down = (
            previous["macd"] >= previous["macd_signal"]
            and current["macd"] < current["macd_signal"]
        )

        price = current["close"]
        near_bb_lower = price <= current["bb_lower"] * 1.005  # 0.5% au-dessus de BB lower
        near_bb_upper = price >= current["bb_upper"] * 0.995  # 0.5% en dessous de BB upper
        volume_ok = current["volume_ratio"] >= self.min_volume_ratio

        # BUY: MACD cross up + prix près de BB lower + volume
        if macd_cross_up and near_bb_lower and volume_ok:
            strength = min(1.0, current["volume_ratio"] / 4.0)
            return TradeSignal(
                Signal.BUY,
                symbol,
                f"MACD cross up + BB lower bounce | Vol={current['volume_ratio']:.1f}x",
                strength=strength,
                price=price,
            )

        # SELL: MACD cross down + prix près de BB upper + volume
        if macd_cross_down and near_bb_upper and volume_ok:
            strength = min(1.0, current["volume_ratio"] / 4.0)
            return TradeSignal(
                Signal.SELL,
                symbol,
                f"MACD cross down + BB upper touch | Vol={current['volume_ratio']:.1f}x",
                strength=strength,
                price=price,
            )

        return TradeSignal(Signal.HOLD, symbol, "Pas de confluence momentum")
