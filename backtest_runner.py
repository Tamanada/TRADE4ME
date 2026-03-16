"""
TRADE4ME - Backtesting Runner.

Usage:
    python backtest_runner.py                    # Backtest avec données live de Binance
    python backtest_runner.py --file data/btc.csv # Backtest avec fichier CSV
"""

import argparse
import yaml

from src.exchange.client import ExchangeClient
from src.data.fetcher import DataFetcher
from src.strategies.scalp_ema import ScalpEMAStrategy
from src.strategies.scalp_rsi import ScalpRSIStrategy
from src.strategies.scalp_momentum import ScalpMomentumStrategy
from backtest.engine import BacktestEngine
from backtest.report import print_backtest_report
from src.utils.logger import setup_logger, console

import pandas as pd


def main():
    parser = argparse.ArgumentParser(description="TRADE4ME - Backtesting")
    parser.add_argument("--file", help="Fichier CSV avec données OHLCV")
    parser.add_argument("--symbol", default="BTC/USDT", help="Paire de trading")
    parser.add_argument("--timeframe", default="5m", help="Timeframe (1m, 5m, 15m, 1h)")
    parser.add_argument("--limit", type=int, default=500, help="Nombre de bougies")
    parser.add_argument("--capital", type=float, default=10000.0, help="Capital initial")
    args = parser.parse_args()

    setup_logger("trade4me", "INFO")

    # Charger les configs
    with open("config/strategies.yaml") as f:
        strat_config = yaml.safe_load(f)
    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)

    # Récupérer les données
    if args.file:
        console.print(f"Chargement des données depuis {args.file}...")
        df = pd.read_csv(args.file, parse_dates=["timestamp"], index_col="timestamp")
    else:
        console.print(f"Récupération de {args.limit} bougies {args.symbol} ({args.timeframe}) depuis Binance...")
        client = ExchangeClient(exchange_name="binance", sandbox=False)
        fetcher = DataFetcher(client)
        df = fetcher.get_candles(args.symbol, args.timeframe, args.limit)

    console.print(f"Données: {len(df)} bougies du {df.index[0]} au {df.index[-1]}\n")

    # Moteur de backtest
    engine = BacktestEngine(
        initial_capital=args.capital,
        risk_config=settings.get("risk", {}),
    )

    # Tester chaque stratégie
    strategies = []
    if strat_config.get("scalp_ema", {}).get("enabled"):
        strategies.append(ScalpEMAStrategy(strat_config["scalp_ema"]))
    if strat_config.get("scalp_rsi", {}).get("enabled"):
        strategies.append(ScalpRSIStrategy(strat_config["scalp_rsi"]))
    if strat_config.get("scalp_momentum", {}).get("enabled"):
        strategies.append(ScalpMomentumStrategy(strat_config["scalp_momentum"]))

    if not strategies:
        console.print("[red]Aucune stratégie activée dans strategies.yaml![/red]")
        return

    for strategy in strategies:
        console.print(f"[cyan]Backtesting: {strategy.name}...[/cyan]")
        result = engine.run(strategy, df, args.symbol, args.timeframe)
        print_backtest_report(result)


if __name__ == "__main__":
    main()
