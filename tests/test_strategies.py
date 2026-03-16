"""Tests pour les stratégies de trading."""

import pandas as pd
import numpy as np
import pytest

from src.strategies.base import Signal
from src.strategies.scalp_ema import ScalpEMAStrategy
from src.strategies.scalp_rsi import ScalpRSIStrategy
from src.indicators.technical import add_all_indicators


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    np.random.seed(42)
    close = 50000 + np.cumsum(np.random.randn(n) * 100)
    df = pd.DataFrame({
        "open": close - np.random.rand(n) * 50,
        "high": close + np.random.rand(n) * 100,
        "low": close - np.random.rand(n) * 100,
        "close": close,
        "volume": np.random.rand(n) * 1000 + 500,
    })
    return add_all_indicators(df)


class TestScalpEMAStrategy:
    def test_returns_trade_signal(self):
        strategy = ScalpEMAStrategy({"ema_fast": 9, "ema_slow": 21, "min_volume_ratio": 0.0})
        df = _make_ohlcv()
        signal = strategy.analyze(df, "BTC/USDT")
        assert signal.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)
        assert signal.symbol == "BTC/USDT"

    def test_hold_with_insufficient_data(self):
        strategy = ScalpEMAStrategy()
        df = _make_ohlcv(10)  # Trop peu de données
        signal = strategy.analyze(df, "BTC/USDT")
        assert signal.signal == Signal.HOLD

    def test_has_reason(self):
        strategy = ScalpEMAStrategy()
        df = _make_ohlcv()
        signal = strategy.analyze(df, "BTC/USDT")
        assert len(signal.reason) > 0


class TestScalpRSIStrategy:
    def test_returns_trade_signal(self):
        strategy = ScalpRSIStrategy()
        df = _make_ohlcv()
        signal = strategy.analyze(df, "ETH/USDT")
        assert signal.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)

    def test_hold_with_insufficient_data(self):
        strategy = ScalpRSIStrategy()
        df = _make_ohlcv(10)
        signal = strategy.analyze(df, "ETH/USDT")
        assert signal.signal == Signal.HOLD
