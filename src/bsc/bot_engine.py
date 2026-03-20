# bot_engine.py — Orchestrateur principal du bot d'arbitrage BSC
import time
import logging
import sys
from datetime import datetime, timezone
from web3 import Web3

from .config import BSC_RPC_URL, SCAN_INTERVAL_MS, DRY_RUN
from .price_scanner import PriceScanner
from .profit_calc import ProfitCalculator
from .tx_builder import TxBuilder

logger = logging.getLogger("bsc.engine")


class ArbBot:
    """
    Boucle principale du bot d'arbitrage PancakeSwap BSC.
    Cycle :
      1. Scan des prix toutes les SCAN_INTERVAL_MS ms
      2. Calcul des opportunités rentables
      3. Exécution de la meilleure opportunité (si profit > seuil)
      4. Log du résultat
    """

    def __init__(self):
        logger.info("=== Démarrage du bot d'arbitrage BSC/PancakeSwap ===")
        if DRY_RUN:
            logger.warning("MODE DRY_RUN actif — aucune transaction réelle ne sera envoyée")

        # Connexion BSC
        self.w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL))
        if not self.w3.is_connected():
            raise ConnectionError(f"Impossible de se connecter à {BSC_RPC_URL}")

        self.block_number = self.w3.eth.block_number
        logger.info(f"Connecté à BSC | Bloc courant : {self.block_number}")

        # Modules
        self.scanner = PriceScanner(self.w3)
        self.calc = ProfitCalculator(self.w3, self.scanner)
        self.tx_builder = TxBuilder(self.w3)

        # Stats
        self.scans_count = 0
        self.trades_count = 0
        self.total_profit = 0.0
        self.running = False

        # Historique pour l'UI
        self.last_quotes: list = []
        self.last_opportunities: list = []
        self.trade_history: list = []  # [{time, route, profit, tx_hash, status}]
        self.last_scan_time: str = ""
        self.bnb_price_usd: float = 0.0

    def run_cycle(self, capital_bnb: float = 0.5) -> dict:
        """
        Exécute un seul cycle de scan + analyse + (trade).
        Retourne un résumé du cycle pour l'UI.
        """
        self.scans_count += 1
        start = time.time()

        try:
            # 1. Refresh block + BNB price
            self.block_number = self.w3.eth.block_number
            self.bnb_price_usd = self.scanner.get_bnb_price_usd()

            # 2. Scan des prix
            quotes = self.scanner.scan_all_routes(capital_bnb)
            self.last_quotes = quotes
            self.last_scan_time = datetime.now(timezone.utc).isoformat()

            if not quotes:
                return {"status": "no_data", "scan": self.scans_count}

            # 3. Recherche d'opportunités
            opportunities = self.calc.find_opportunities(quotes, capital_bnb)
            self.last_opportunities = opportunities

            if not opportunities:
                return {
                    "status": "no_opportunity",
                    "scan": self.scans_count,
                    "routes_scanned": len(quotes),
                    "best_pct": quotes[0].profit_pct if quotes else 0,
                }

            # 4. Exécution de la meilleure
            best = opportunities[0]
            tx_hash = self.tx_builder.execute_arb(best)

            trade_entry = {
                "time": datetime.now(timezone.utc).isoformat(),
                "route": " → ".join(best.route.path_names),
                "profit_net_usd": best.profit_net_usd,
                "profit_net_pct": best.profit_net_pct,
                "gas_usd": best.gas_cost_usd,
                "capital_bnb": capital_bnb,
                "tx_hash": tx_hash or "",
                "status": "success" if tx_hash else "failed",
                "dry_run": DRY_RUN,
            }

            if tx_hash:
                self.trades_count += 1
                self.total_profit += best.profit_net_usd
                self.trade_history.append(trade_entry)
                # Garder les 100 derniers trades
                if len(self.trade_history) > 100:
                    self.trade_history = self.trade_history[-100:]

            elapsed_ms = (time.time() - start) * 1000
            return {
                "status": "traded" if tx_hash else "trade_failed",
                "scan": self.scans_count,
                "elapsed_ms": round(elapsed_ms, 1),
                "trade": trade_entry,
            }

        except Exception as e:
            logger.error(f"Erreur cycle: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "scan": self.scans_count}

    def run_loop(self, capital_bnb: float = 0.5):
        """Boucle continue pour le threading."""
        self.running = True
        logger.info(f"Boucle BSC démarrée | Capital: {capital_bnb} BNB | Intervalle: {SCAN_INTERVAL_MS}ms")

        while self.running:
            start = time.time()
            self.run_cycle(capital_bnb)
            elapsed = (time.time() - start) * 1000
            sleep_ms = max(0, SCAN_INTERVAL_MS - elapsed)
            time.sleep(sleep_ms / 1000)

        logger.info("Boucle BSC arrêtée")

    def stop(self):
        """Arrête la boucle."""
        self.running = False

    def get_state(self) -> dict:
        """Retourne l'état complet pour l'API."""
        return {
            "connected": self.w3.is_connected(),
            "block_number": self.block_number,
            "bnb_price_usd": self.bnb_price_usd,
            "running": self.running,
            "dry_run": DRY_RUN,
            "scans_count": self.scans_count,
            "trades_count": self.trades_count,
            "total_profit": round(self.total_profit, 4),
            "last_scan": self.last_scan_time,
            "wallet_balance": self.tx_builder.get_balance_bnb() if self.tx_builder.wallet else 0,
            "wallet_configured": bool(self.tx_builder.wallet),
            "routes": [
                {
                    "path": " → ".join(q.path_names),
                    "profit_pct": round(q.profit_pct, 4),
                    "amount_in_bnb": float(self.w3.from_wei(q.amount_in, "ether")),
                    "amount_out_bnb": float(self.w3.from_wei(q.final_amount, "ether")),
                }
                for q in self.last_quotes[:20]
            ],
            "opportunities": [
                {
                    "route": " → ".join(o.route.path_names),
                    "profit_net_usd": round(o.profit_net_usd, 4),
                    "profit_net_pct": round(o.profit_net_pct, 4),
                    "gross_usd": round(o.gross_profit_usd, 4),
                    "gas_usd": round(o.gas_cost_usd, 4),
                    "capital_usd": round(o.capital_usd, 2),
                }
                for o in self.last_opportunities[:10]
            ],
            "trade_history": self.trade_history[-20:],
        }
