"""
Indicateurs techniques pour le scalping crypto.
Utilise la librairie 'ta' pour les calculs.
"""

import pandas as pd
import ta


def add_all_indicators(df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
    """Ajoute tous les indicateurs techniques au DataFrame OHLCV."""
    df = df.copy()
    df = add_ema(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger(df)
    df = add_volume_indicators(df)
    return df


def add_ema(
    df: pd.DataFrame, fast: int = 9, slow: int = 21, trend: int = 50
) -> pd.DataFrame:
    """Ajoute les EMA (Exponential Moving Averages)."""
    df[f"ema_{fast}"] = ta.trend.ema_indicator(df["close"], window=fast)
    df[f"ema_{slow}"] = ta.trend.ema_indicator(df["close"], window=slow)
    df[f"ema_{trend}"] = ta.trend.ema_indicator(df["close"], window=trend)
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Ajoute le RSI (Relative Strength Index)."""
    df["rsi"] = ta.momentum.rsi(df["close"], window=period)
    return df


def add_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """Ajoute le MACD (Moving Average Convergence Divergence)."""
    macd = ta.trend.MACD(
        df["close"], window_fast=fast, window_slow=slow, window_sign=signal
    )
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()
    return df


def add_bollinger(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Ajoute les Bandes de Bollinger."""
    bb = ta.volatility.BollingerBands(df["close"], window=period, window_dev=std)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = bb.bollinger_wband()
    return df


def add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les indicateurs de volume."""
    df["volume_sma"] = df["volume"].rolling(window=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma"]
    return df
