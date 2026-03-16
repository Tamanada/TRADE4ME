"""Tests pour les indicateurs techniques."""

import pandas as pd
import numpy as np
import pytest

from src.indicators.technical import add_ema, add_rsi, add_macd, add_bollinger, add_volume_indicators, add_all_indicators


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Génère un DataFrame OHLCV de test."""
    np.random.seed(42)
    close = 50000 + np.cumsum(np.random.randn(n) * 100)
    return pd.DataFrame({
        "open": close - np.random.rand(n) * 50,
        "high": close + np.random.rand(n) * 100,
        "low": close - np.random.rand(n) * 100,
        "close": close,
        "volume": np.random.rand(n) * 1000 + 500,
    })


class TestEMA:
    def test_adds_ema_columns(self):
        df = add_ema(_make_ohlcv(), fast=9, slow=21, trend=50)
        assert "ema_9" in df.columns
        assert "ema_21" in df.columns
        assert "ema_50" in df.columns

    def test_ema_values_are_floats(self):
        df = add_ema(_make_ohlcv())
        assert df["ema_9"].dtype == np.float64


class TestRSI:
    def test_adds_rsi_column(self):
        df = add_rsi(_make_ohlcv())
        assert "rsi" in df.columns

    def test_rsi_range(self):
        df = add_rsi(_make_ohlcv())
        valid = df["rsi"].dropna()
        assert valid.min() >= 0
        assert valid.max() <= 100


class TestMACD:
    def test_adds_macd_columns(self):
        df = add_macd(_make_ohlcv())
        assert "macd" in df.columns
        assert "macd_signal" in df.columns
        assert "macd_histogram" in df.columns


class TestBollinger:
    def test_adds_bb_columns(self):
        df = add_bollinger(_make_ohlcv())
        assert "bb_upper" in df.columns
        assert "bb_middle" in df.columns
        assert "bb_lower" in df.columns

    def test_bb_order(self):
        df = add_bollinger(_make_ohlcv())
        valid = df.dropna()
        assert (valid["bb_upper"] >= valid["bb_middle"]).all()
        assert (valid["bb_middle"] >= valid["bb_lower"]).all()


class TestVolumeIndicators:
    def test_adds_volume_columns(self):
        df = add_volume_indicators(_make_ohlcv())
        assert "volume_sma" in df.columns
        assert "volume_ratio" in df.columns


class TestAllIndicators:
    def test_adds_all(self):
        df = add_all_indicators(_make_ohlcv())
        expected = ["ema_9", "ema_21", "rsi", "macd", "bb_upper", "volume_ratio"]
        for col in expected:
            assert col in df.columns
