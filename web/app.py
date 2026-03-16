"""
TRADE4ME Web Dashboard - Flask backend.
"""

import sys
import os
import site
from pathlib import Path

# Ensure user site-packages are available
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

# Ensure project root is on sys.path so 'src' imports work
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import json
import threading
import time
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv

from src.exchange.client import ExchangeClient
from src.exchange.multi_exchange import MultiExchangeScanner
from src.data.fetcher import DataFetcher
from src.indicators.technical import add_all_indicators
from src.strategies.base import Signal
from src.strategies.scalp_ema import ScalpEMAStrategy
from src.strategies.scalp_rsi import ScalpRSIStrategy
from src.strategies.scalp_momentum import ScalpMomentumStrategy
from src.execution.order_manager import OrderManager
from src.execution.position_tracker import PositionTracker
from src.risk.manager import RiskManager
from src.utils.logger import setup_logger

load_dotenv()

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# State shared between bot thread and web server
state = {
    "running": False,
    "mode": "paper",
    "capital": 10000.0,
    "initial_capital": 10000.0,
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "timeframe": "1m",
    "prices": {},
    "positions": [],
    "closed_trades": [],
    "signals": [],
    "equity_curve": [],
    "cycle": 0,
    "started_at": None,
    "error": None,
}

# Arbitrage scanner state
arb_state = {
    "scanning": False,
    "opportunities": [],
    "last_scan": None,
    "error": None,
    "total_tokens": 0,
    "total_exchanges": 0,
    "scanned_count": 0,
    "scan_progress": "",
}

# Bot components (initialized on start)
bot_components = {}
bot_thread = None
arb_scanner = None
arb_thread = None


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
    strat_path = os.path.join(os.path.dirname(__file__), "..", "config", "strategies.yaml")
    with open(config_path) as f:
        settings = yaml.safe_load(f)
    with open(strat_path) as f:
        strat_config = yaml.safe_load(f)
    return settings, strat_config


def init_bot():
    """Initialize bot components."""
    settings, strat_config = load_config()
    setup_logger("trade4me", "INFO")

    client = ExchangeClient(
        exchange_name=os.getenv("EXCHANGE_NAME", settings["exchange"]["name"]),
        api_key=os.getenv("EXCHANGE_API_KEY"),
        api_secret=os.getenv("EXCHANGE_API_SECRET"),
        sandbox=settings["exchange"].get("sandbox", True),
    )

    strategies = []
    if strat_config.get("scalp_ema", {}).get("enabled"):
        strategies.append(ScalpEMAStrategy(strat_config["scalp_ema"]))
    if strat_config.get("scalp_rsi", {}).get("enabled"):
        strategies.append(ScalpRSIStrategy(strat_config["scalp_rsi"]))
    if strat_config.get("scalp_momentum", {}).get("enabled"):
        strategies.append(ScalpMomentumStrategy(strat_config["scalp_momentum"]))

    bot_components["client"] = client
    bot_components["fetcher"] = DataFetcher(client)
    bot_components["order_manager"] = OrderManager(client, paper_mode=True)
    bot_components["position_tracker"] = PositionTracker()
    bot_components["risk_manager"] = RiskManager(settings.get("risk", {}))
    bot_components["strategies"] = strategies
    bot_components["settings"] = settings

    state["symbols"] = settings.get("trading", {}).get("symbols", ["BTC/USDT"])
    state["timeframe"] = settings.get("trading", {}).get("timeframe", "1m")
    state["capital"] = 10000.0
    state["initial_capital"] = 10000.0
    bot_components["risk_manager"].set_capital(10000.0)


def bot_loop():
    """Main bot loop running in background thread."""
    fetcher = bot_components["fetcher"]
    strategies = bot_components["strategies"]
    order_manager = bot_components["order_manager"]
    position_tracker = bot_components["position_tracker"]
    risk_manager = bot_components["risk_manager"]
    settings = bot_components["settings"]
    timeframe = settings.get("trading", {}).get("timeframe", "1m")
    candle_limit = settings.get("trading", {}).get("candle_limit", 100)
    interval = settings.get("bot", {}).get("loop_interval_sec", 10)

    while state["running"]:
        state["cycle"] += 1

        for symbol in state["symbols"]:
            try:
                # Fetch candles
                df = fetcher.get_candles(symbol, timeframe, candle_limit)
                df = add_all_indicators(df)
                current_price = float(df.iloc[-1]["close"])
                state["prices"][symbol] = current_price

                # Check SL/TP for open positions
                if position_tracker.has_position(symbol):
                    exit_reason = position_tracker.check_exits(symbol, current_price)
                    if exit_reason:
                        pos = position_tracker.get_position(symbol)
                        pnl = position_tracker.close_position(pos, current_price)
                        order_manager.place_market_order(symbol, "sell", pos.amount, current_price)
                        state["capital"] += pnl
                        _sync_state(position_tracker)
                        state["signals"].append({
                            "time": datetime.now(timezone.utc).isoformat(),
                            "symbol": symbol,
                            "signal": "SELL",
                            "reason": f"{exit_reason} @ ${current_price:,.2f} | P&L: {pnl:+.2f}",
                        })
                        continue

                # Analyze with strategies
                for strategy in strategies:
                    signal = strategy.analyze(df, symbol)

                    if signal.signal == Signal.HOLD:
                        continue

                    state["signals"].append({
                        "time": datetime.now(timezone.utc).isoformat(),
                        "symbol": symbol,
                        "signal": signal.signal.value,
                        "reason": signal.reason,
                    })
                    # Keep only last 50 signals
                    state["signals"] = state["signals"][-50:]

                    if signal.signal == Signal.BUY and not position_tracker.has_position(symbol):
                        trade_params = risk_manager.validate_trade(
                            state["capital"], signal.price,
                            len(position_tracker.open_positions),
                        )
                        if trade_params:
                            order = order_manager.place_market_order(
                                symbol, "buy", trade_params["amount"], signal.price,
                            )
                            if order.status == "filled":
                                position_tracker.open_position(
                                    symbol=symbol, side="long",
                                    entry_price=order.filled_price,
                                    amount=trade_params["amount"],
                                    stop_loss=trade_params["stop_loss"],
                                    take_profit=trade_params["take_profit"],
                                )
                                state["capital"] -= trade_params["position_value_usdt"]
                                _sync_state(position_tracker)
                        break

                    elif signal.signal == Signal.SELL and position_tracker.has_position(symbol):
                        pos = position_tracker.get_position(symbol)
                        pnl = position_tracker.close_position(pos, signal.price)
                        order_manager.place_market_order(symbol, "sell", pos.amount, signal.price)
                        state["capital"] += pnl
                        _sync_state(position_tracker)
                        break

            except Exception as e:
                state["error"] = str(e)

        # Update equity curve
        total = state["capital"]
        for pos_data in state["positions"]:
            symbol = pos_data["symbol"]
            if symbol in state["prices"]:
                total += pos_data["amount"] * state["prices"][symbol]
        state["equity_curve"].append({
            "time": datetime.now(timezone.utc).isoformat(),
            "value": round(total, 2),
        })
        # Keep last 500 points
        state["equity_curve"] = state["equity_curve"][-500:]

        time.sleep(interval)


def _sync_state(position_tracker: PositionTracker):
    """Sync position tracker state to shared state dict."""
    state["positions"] = [
        {
            "symbol": p.symbol,
            "side": p.side,
            "entry_price": p.entry_price,
            "amount": p.amount,
            "stop_loss": p.stop_loss,
            "take_profit": p.take_profit,
            "opened_at": p.opened_at,
        }
        for p in position_tracker.open_positions
    ]
    state["closed_trades"] = position_tracker.closed_positions[-50:]


# ─── Routes ──────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/state")
def get_state():
    """Return full bot state as JSON."""
    # Add unrealized P&L to positions
    positions_with_pnl = []
    for pos in state["positions"]:
        p = dict(pos)
        current = state["prices"].get(pos["symbol"], pos["entry_price"])
        p["current_price"] = current
        p["pnl"] = (current - pos["entry_price"]) * pos["amount"]
        p["pnl_pct"] = ((current - pos["entry_price"]) / pos["entry_price"] * 100) if pos["entry_price"] > 0 else 0
        positions_with_pnl.append(p)

    # Calculate total equity
    total_equity = state["capital"]
    for p in positions_with_pnl:
        total_equity += p["amount"] * p["current_price"]

    stats = bot_components.get("position_tracker", None)
    tracker_stats = stats.stats if stats else {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0}

    return jsonify({
        "running": state["running"],
        "mode": state["mode"],
        "capital": round(state["capital"], 2),
        "total_equity": round(total_equity, 2),
        "initial_capital": state["initial_capital"],
        "pnl_total": round(total_equity - state["initial_capital"], 2),
        "pnl_pct": round((total_equity - state["initial_capital"]) / state["initial_capital"] * 100, 2),
        "symbols": state["symbols"],
        "timeframe": state["timeframe"],
        "prices": state["prices"],
        "positions": positions_with_pnl,
        "closed_trades": state["closed_trades"][-20:],
        "signals": state["signals"][-20:],
        "equity_curve": state["equity_curve"][-200:],
        "cycle": state["cycle"],
        "started_at": state["started_at"],
        "stats": tracker_stats,
        "error": state["error"],
    })


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread
    if state["running"]:
        return jsonify({"status": "already_running"})

    init_bot()
    state["running"] = True
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    state["cycle"] = 0
    state["error"] = None

    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    state["running"] = False
    return jsonify({"status": "stopped"})


# ─── Arbitrage Scanner Routes ────────────────────────

@app.route("/arbitrage")
def arbitrage_page():
    return render_template("arbitrage.html")


def _format_results(results):
    """Format scan results for JSON response."""
    return [
        {
            "symbol": r.symbol,
            "buy_exchange": r.buy_exchange,
            "buy_price": r.buy_price,
            "sell_exchange": r.sell_exchange,
            "sell_price": r.sell_price,
            "spread": round(r.spread, 6),
            "spread_pct": round(r.spread_pct, 3),
            "all_prices": r.all_prices,
            "num_exchanges": r.num_exchanges,
        }
        for r in results
    ]


def _arb_scan_loop():
    """Background loop that continuously scans for arbitrage."""
    global arb_scanner
    if arb_scanner is None:
        arb_scanner = MultiExchangeScanner()
        arb_state["scan_progress"] = "Decouverte des tokens..."
        arb_scanner.discover_tokens(min_exchanges=3)
        arb_state["total_tokens"] = len(arb_scanner.get_token_list())
        arb_state["total_exchanges"] = len(arb_scanner.exchanges)

    while arb_state["scanning"]:
        try:
            tokens = arb_scanner.get_token_list()
            all_results = []
            batch_size = 10

            for i in range(0, len(tokens), batch_size):
                if not arb_state["scanning"]:
                    break
                batch = tokens[i:i + batch_size]
                arb_state["scanned_count"] = min(i + batch_size, len(tokens))
                arb_state["scan_progress"] = f"Scan {arb_state['scanned_count']}/{len(tokens)} tokens..."

                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = {
                        executor.submit(arb_scanner.scan_token, symbol): symbol
                        for symbol in batch
                    }
                    for future in as_completed(futures, timeout=60):
                        try:
                            result = future.result(timeout=15)
                            if result:
                                all_results.append(result)
                        except Exception:
                            pass

                all_results.sort(key=lambda r: r.spread_pct, reverse=True)
                arb_state["opportunities"] = _format_results(all_results)

            arb_state["last_scan"] = datetime.now(timezone.utc).isoformat()
            arb_state["error"] = None
            arb_state["scan_progress"] = ""
        except Exception as e:
            arb_state["error"] = str(e)

        time.sleep(60)  # Wait before next scan cycle


@app.route("/api/arbitrage/start", methods=["POST"])
def start_arb_scan():
    global arb_thread
    if arb_state["scanning"]:
        return jsonify({"status": "already_scanning"})

    arb_state["scanning"] = True
    arb_state["error"] = None
    arb_thread = threading.Thread(target=_arb_scan_loop, daemon=True)
    arb_thread.start()
    return jsonify({"status": "started"})


@app.route("/api/arbitrage/stop", methods=["POST"])
def stop_arb_scan():
    arb_state["scanning"] = False
    return jsonify({"status": "stopped"})


@app.route("/api/arbitrage/state")
def get_arb_state():
    return jsonify(arb_state)


def _scan_once_worker():
    """Background worker for single scan."""
    global arb_scanner
    try:
        if arb_scanner is None:
            arb_scanner = MultiExchangeScanner()

        # Discover tokens if not yet done
        if not arb_scanner._discovered_tokens and arb_scanner.tokens is None:
            arb_state["scan_progress"] = "Decouverte des tokens..."
            arb_scanner.discover_tokens(min_exchanges=3)

        arb_state["total_tokens"] = len(arb_scanner.get_token_list())
        arb_state["total_exchanges"] = len(arb_scanner.exchanges)

        # Scan with progressive updates
        tokens = arb_scanner.get_token_list()
        all_results = []
        batch_size = 10

        for i in range(0, len(tokens), batch_size):
            if not arb_state["scanning"]:
                break  # Allow stopping mid-scan

            batch = tokens[i:i + batch_size]
            arb_state["scanned_count"] = min(i + batch_size, len(tokens))
            arb_state["scan_progress"] = f"Scan {arb_state['scanned_count']}/{len(tokens)} tokens..."

            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {
                    executor.submit(arb_scanner.scan_token, symbol): symbol
                    for symbol in batch
                }
                for future in as_completed(futures, timeout=60):
                    try:
                        result = future.result(timeout=15)
                        if result:
                            all_results.append(result)
                    except Exception:
                        pass

            # Update results progressively after each batch
            all_results.sort(key=lambda r: r.spread_pct, reverse=True)
            arb_state["opportunities"] = _format_results(all_results)

        arb_state["last_scan"] = datetime.now(timezone.utc).isoformat()
        arb_state["error"] = None
        arb_state["scan_progress"] = ""
    except Exception as e:
        arb_state["error"] = str(e)
    finally:
        arb_state["scanning"] = False


@app.route("/api/arbitrage/scan-once", methods=["POST"])
def scan_once():
    """Single scan - runs in background thread, returns immediately."""
    global arb_thread
    if arb_state["scanning"]:
        return jsonify({"status": "already_scanning"})

    arb_state["scanning"] = True
    arb_state["error"] = None
    arb_state["scanned_count"] = 0
    arb_state["scan_progress"] = "Initialisation..."
    arb_thread = threading.Thread(target=_scan_once_worker, daemon=True)
    arb_thread.start()
    return jsonify({"status": "started"})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
