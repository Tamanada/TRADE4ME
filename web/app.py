"""
TRADE4ME Web Dashboard - Flask backend.
"""

import sys
import os
from pathlib import Path

# Ensure user site-packages are available (skip if not supported)
try:
    import site
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.insert(0, user_site)
except Exception:
    pass

# Ensure project root is on sys.path so 'src' imports work
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import json
import threading
import time
from collections import deque
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

from src.exchange.client import ExchangeClient
from src.exchange.client_pool import MultiExchangeClientPool
from src.exchange.multi_exchange import MultiExchangeScanner
from src.execution.arb_executor import ArbitrageExecutor
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

# Auto-execution state
auto_exec_state = {
    "enabled": False,
    "min_net_spread_pct": 1.0,
    "cooldown_sec": 30,
    "max_per_cycle": 3,
    "last_exec_time": 0,            # timestamp (time.time())
    "cycle_exec_count": 0,
    "last_scan_id": None,
    "executed_pairs": deque(maxlen=20),  # recent (symbol, buy_ex, sell_ex)
    "total_auto_executions": 0,
    "total_auto_profit": 0.0,
    "auto_exec_log": deque(maxlen=50),   # recent auto-execution results
}
auto_exec_lock = threading.Lock()

# Bot components (initialized on start)
bot_components = {}
bot_thread = None
arb_scanner = None
arb_thread = None
arb_executor = None
arb_client_pool = None


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
            "buy_fee_pct": round(r.buy_fee_pct, 3),
            "sell_fee_pct": round(r.sell_fee_pct, 3),
            "total_fees_pct": round(r.total_fees_pct, 3),
            "net_spread_pct": round(r.net_spread_pct, 3),
            "all_prices": r.all_prices,
            "num_exchanges": r.num_exchanges,
            "rsi": r.rsi,
            "ema_trend": r.ema_trend,
            "ema_9": r.ema_9,
            "ema_21": r.ema_21,
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
            batch_size = 25

            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                for i in range(0, len(tokens), batch_size):
                    if not arb_state["scanning"]:
                        break
                    batch = tokens[i:i + batch_size]
                    arb_state["scanned_count"] = min(i + batch_size, len(tokens))
                    arb_state["scan_progress"] = f"Scan {arb_state['scanned_count']}/{len(tokens)} tokens..."

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

                    all_results.sort(key=lambda r: r.net_spread_pct, reverse=True)
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
        batch_size = 25

        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            for i in range(0, len(tokens), batch_size):
                if not arb_state["scanning"]:
                    break  # Allow stopping mid-scan

                batch = tokens[i:i + batch_size]
                arb_state["scanned_count"] = min(i + batch_size, len(tokens))
                arb_state["scan_progress"] = f"Scan {arb_state['scanned_count']}/{len(tokens)} tokens..."

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
                all_results.sort(key=lambda r: r.net_spread_pct, reverse=True)
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


# ─── Arbitrage Execution Routes ──────────────────────

def _init_arb_executor():
    """Initialise l'exécuteur d'arbitrage (lazy, au premier appel)."""
    global arb_executor, arb_client_pool
    if arb_executor is not None:
        return

    settings, _ = load_config()
    arb_config = settings.get("arbitrage", {})
    exchanges_config = settings.get("exchanges", [])

    arb_client_pool = MultiExchangeClientPool(exchanges_config)
    arb_executor = ArbitrageExecutor(arb_client_pool, arb_config)


@app.route("/api/arbitrage/exec-state")
def get_arb_exec_state():
    """Retourne l'état de l'exécuteur (mode, exchanges configurés)."""
    _init_arb_executor()
    settings, _ = load_config()
    arb_config = settings.get("arbitrage", {})
    return jsonify({
        "mode": "paper" if arb_executor.paper_mode else "live",
        "live_confirmed": arb_executor.live_confirmed,
        "configured_exchanges": arb_client_pool.get_configured_exchanges(),
        "max_trade_usdt": arb_config.get("max_trade_usdt", 100),
        "min_spread_pct": arb_config.get("min_spread_pct", 0.3),
    })


@app.route("/api/arbitrage/execute", methods=["POST"])
def execute_arbitrage():
    """Exécute un trade d'arbitrage simultané."""
    _init_arb_executor()

    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "error": "No data provided"}), 400

    symbol = data.get("symbol")
    buy_exchange = data.get("buy_exchange")
    buy_price = data.get("buy_price", 0)
    sell_exchange = data.get("sell_exchange")
    sell_price = data.get("sell_price", 0)
    spread_pct = data.get("spread_pct", 0)
    buy_fee_pct = data.get("buy_fee_pct", 0)
    sell_fee_pct = data.get("sell_fee_pct", 0)

    if not all([symbol, buy_exchange, sell_exchange]):
        return jsonify({"status": "error", "error": "Missing fields"}), 400

    # Exécution (rapide en paper, un peu plus lent en live)
    result = arb_executor.execute(
        symbol=symbol,
        buy_exchange=buy_exchange,
        buy_price=float(buy_price),
        sell_exchange=sell_exchange,
        sell_price=float(sell_price),
        spread_pct=float(spread_pct),
        buy_fee_pct=float(buy_fee_pct),
        sell_fee_pct=float(sell_fee_pct),
    )

    return jsonify({"status": "ok", "execution": result.to_dict()})


@app.route("/api/arbitrage/executions")
def get_executions():
    """Retourne l'historique des exécutions."""
    _init_arb_executor()
    return jsonify({
        "executions": [r.to_dict() for r in reversed(arb_executor.execution_history[-50:])]
    })


@app.route("/api/arbitrage/confirm-live", methods=["POST"])
def confirm_live_mode():
    """Confirme le passage en mode live (nécessite 'OUI JE CONFIRME')."""
    _init_arb_executor()
    data = request.get_json() or {}
    confirmation = data.get("confirmation", "")

    if confirmation == "OUI JE CONFIRME":
        arb_executor.live_confirmed = True
        arb_executor.paper_mode = False
        return jsonify({"status": "ok", "mode": "live"})
    else:
        return jsonify({"status": "error", "error": "Confirmation incorrecte"}), 403


# ─── Auto-Execution Routes ────────────────────────────

@app.route("/api/arbitrage/auto-exec-state")
def get_auto_exec_state():
    """Retourne l'état de l'auto-exécution."""
    with auto_exec_lock:
        return jsonify({
            "enabled": auto_exec_state["enabled"],
            "min_net_spread_pct": auto_exec_state["min_net_spread_pct"],
            "cooldown_sec": auto_exec_state["cooldown_sec"],
            "max_per_cycle": auto_exec_state["max_per_cycle"],
            "total_auto_executions": auto_exec_state["total_auto_executions"],
            "total_auto_profit": round(auto_exec_state["total_auto_profit"], 4),
            "cycle_exec_count": auto_exec_state["cycle_exec_count"],
            "log": list(auto_exec_state["auto_exec_log"]),
        })


@app.route("/api/arbitrage/auto-exec-config", methods=["POST"])
def update_auto_exec_config():
    """Met à jour la configuration de l'auto-exécution."""
    _init_arb_executor()
    data = request.get_json() or {}

    with auto_exec_lock:
        if "enabled" in data:
            # Safety: auto-exec only in paper mode
            if data["enabled"] and not arb_executor.paper_mode:
                return jsonify({
                    "status": "error",
                    "error": "Auto-exec uniquement disponible en paper mode"
                }), 403
            auto_exec_state["enabled"] = bool(data["enabled"])
            if data["enabled"]:
                # Reset cycle counter when enabling
                auto_exec_state["cycle_exec_count"] = 0
                auto_exec_state["executed_pairs"] = deque(maxlen=20)

        if "min_net_spread_pct" in data:
            auto_exec_state["min_net_spread_pct"] = max(0.1, float(data["min_net_spread_pct"]))
        if "cooldown_sec" in data:
            auto_exec_state["cooldown_sec"] = max(5, int(data["cooldown_sec"]))
        if "max_per_cycle" in data:
            auto_exec_state["max_per_cycle"] = max(1, min(20, int(data["max_per_cycle"])))

    return jsonify({"status": "ok"})


@app.route("/api/arbitrage/auto-execute", methods=["POST"])
def auto_execute_arbitrage():
    """Exécution automatique sécurisée avec safeguards."""
    _init_arb_executor()

    data = request.get_json()
    if not data:
        return jsonify({"status": "skipped", "reason": "No data"}), 400

    now = time.time()

    with auto_exec_lock:
        # 1. Check enabled
        if not auto_exec_state["enabled"]:
            return jsonify({"status": "skipped", "reason": "Auto-exec désactivé"})

        # 2. Paper mode only
        if not arb_executor.paper_mode:
            auto_exec_state["enabled"] = False
            return jsonify({"status": "skipped", "reason": "Mode live détecté — auto-exec désactivé"})

        # 3. Cooldown
        elapsed = now - auto_exec_state["last_exec_time"]
        if elapsed < auto_exec_state["cooldown_sec"]:
            remaining = int(auto_exec_state["cooldown_sec"] - elapsed)
            return jsonify({"status": "skipped", "reason": f"Cooldown ({remaining}s restantes)"})

        # 4. Reset cycle count if new scan
        current_scan = arb_state.get("last_scan")
        if current_scan != auto_exec_state["last_scan_id"]:
            auto_exec_state["cycle_exec_count"] = 0
            auto_exec_state["last_scan_id"] = current_scan

        # 5. Max per cycle
        if auto_exec_state["cycle_exec_count"] >= auto_exec_state["max_per_cycle"]:
            return jsonify({"status": "skipped", "reason": f"Max {auto_exec_state['max_per_cycle']} trades/cycle atteint"})

        # 6. Duplicate prevention
        pair_key = (data.get("symbol"), data.get("buy_exchange"), data.get("sell_exchange"))
        if pair_key in auto_exec_state["executed_pairs"]:
            return jsonify({"status": "skipped", "reason": f"Déjà exécuté: {pair_key[0]}"})

        # All checks passed — execute
        auto_exec_state["last_exec_time"] = now

    # Execute outside lock (may take time)
    result = arb_executor.execute(
        symbol=data["symbol"],
        buy_exchange=data["buy_exchange"],
        buy_price=float(data.get("buy_price", 0)),
        sell_exchange=data["sell_exchange"],
        sell_price=float(data.get("sell_price", 0)),
        spread_pct=float(data.get("spread_pct", 0)),
        buy_fee_pct=float(data.get("buy_fee_pct", 0)),
        sell_fee_pct=float(data.get("sell_fee_pct", 0)),
    )

    # Update state after execution
    with auto_exec_lock:
        auto_exec_state["cycle_exec_count"] += 1
        auto_exec_state["total_auto_executions"] += 1
        auto_exec_state["total_auto_profit"] += result.net_profit_usdt
        auto_exec_state["executed_pairs"].append(pair_key)
        auto_exec_state["auto_exec_log"].appendleft({
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": data["symbol"],
            "buy_exchange": data["buy_exchange"],
            "sell_exchange": data["sell_exchange"],
            "net_spread_pct": round(float(data.get("net_spread_pct", 0)), 3),
            "net_profit_usdt": round(result.net_profit_usdt, 4),
            "status": result.status,
        })

    return jsonify({"status": "ok", "execution": result.to_dict()})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
