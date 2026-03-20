# price_scanner.py — Scanner de prix PancakeSwap V2 on-chain
import logging
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from web3 import Web3

from .config import (
    PANCAKESWAP_V2_ROUTER,
    ROUTER_ABI,
    WBNB,
    TOKEN_LIST,
    TRIANGULAR_ROUTES,
)

logger = logging.getLogger("bsc.scanner")

# Résolution nom token depuis adresse
ADDR_TO_NAME = {v.lower(): k for k, v in TOKEN_LIST.items()}


def addr_name(addr: str) -> str:
    return ADDR_TO_NAME.get(addr.lower(), addr[:8] + "...")


@dataclass
class RouteQuote:
    """Quote pour un chemin multi-hop sur PancakeSwap."""
    path: list[str]           # Adresses du chemin
    path_names: list[str]     # Noms lisibles
    amount_in: int            # Wei d'entrée
    amounts_out: list[int]    # Montants à chaque hop
    final_amount: int         # Montant final en wei
    profit_wei: int           # Profit en wei (final - initial)
    profit_pct: float         # Profit en %
    gas_estimate: int = 0     # Gas estimé


class PriceScanner:
    """Scanne les prix PancakeSwap V2 via getAmountsOut."""

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.router = w3.eth.contract(
            address=Web3.to_checksum_address(PANCAKESWAP_V2_ROUTER),
            abi=ROUTER_ABI,
        )
        logger.info(f"PriceScanner initialisé | Router: {PANCAKESWAP_V2_ROUTER[:10]}...")

    def get_amounts_out(self, amount_in_wei: int, path: list[str]) -> list[int] | None:
        """Appelle router.getAmountsOut() pour un chemin donné."""
        try:
            checksum_path = [Web3.to_checksum_address(addr) for addr in path]
            amounts = self.router.functions.getAmountsOut(
                amount_in_wei, checksum_path
            ).call()
            return amounts
        except Exception as e:
            logger.debug(f"getAmountsOut échoué pour {[addr_name(a) for a in path]}: {e}")
            return None

    def quote_route(self, path: list[str], amount_in_wei: int) -> RouteQuote | None:
        """Obtient un quote complet pour un chemin triangulaire."""
        amounts = self.get_amounts_out(amount_in_wei, path)
        if not amounts or len(amounts) < len(path):
            return None

        final_amount = amounts[-1]
        profit_wei = final_amount - amount_in_wei
        profit_pct = (profit_wei / amount_in_wei * 100) if amount_in_wei > 0 else 0

        return RouteQuote(
            path=path,
            path_names=[addr_name(a) for a in path],
            amount_in=amount_in_wei,
            amounts_out=amounts,
            final_amount=final_amount,
            profit_wei=profit_wei,
            profit_pct=profit_pct,
        )

    def scan_all_routes(self, capital_bnb: float = 0.5) -> list[RouteQuote]:
        """
        Scanne toutes les routes triangulaires configurées.
        Retourne les quotes triées par profit décroissant.
        """
        amount_in_wei = self.w3.to_wei(capital_bnb, "ether")
        quotes: list[RouteQuote] = []

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(self.quote_route, route, amount_in_wei): route
                for route in TRIANGULAR_ROUTES
            }
            for future in as_completed(futures, timeout=10):
                try:
                    result = future.result(timeout=5)
                    if result:
                        quotes.append(result)
                except Exception:
                    pass

        # Tri par profit décroissant
        quotes.sort(key=lambda q: q.profit_pct, reverse=True)
        return quotes

    def scan_all_pairs(self) -> list[RouteQuote]:
        """Alias pour compatibilité avec bot_engine."""
        return self.scan_all_routes()

    def get_bnb_price_usd(self) -> float:
        """Estime le prix BNB en USD via WBNB→BUSD."""
        try:
            from .config import BUSD
            amounts = self.get_amounts_out(
                self.w3.to_wei(1, "ether"),
                [WBNB, BUSD],
            )
            if amounts and len(amounts) >= 2:
                return float(self.w3.from_wei(amounts[1], "ether"))
        except Exception:
            pass
        return 600.0  # Fallback
