# profit_calc.py — Calcul de rentabilité des opportunités d'arbitrage BSC
import logging
from dataclasses import dataclass
from web3 import Web3

from .config import GAS_PRICE_GWEI, MIN_PROFIT_USD, MAX_GAS_USD
from .price_scanner import PriceScanner, RouteQuote, addr_name

logger = logging.getLogger("bsc.profit")


@dataclass
class ArbOpportunity:
    """Opportunité d'arbitrage avec calcul de profit net."""
    route: RouteQuote
    bnb_price_usd: float
    capital_bnb: float
    capital_usd: float
    gross_profit_bnb: float
    gross_profit_usd: float
    gas_cost_bnb: float
    gas_cost_usd: float
    profit_net_bnb: float
    profit_net_usd: float
    profit_net_pct: float
    viable: bool  # True si profit > seuil après gas

    def __str__(self):
        route_str = " → ".join(self.route.path_names)
        return (
            f"{route_str} | "
            f"Brut: {self.gross_profit_usd:+.4f}$ ({self.route.profit_pct:+.3f}%) | "
            f"Gas: -{self.gas_cost_usd:.4f}$ | "
            f"Net: {self.profit_net_usd:+.4f}$ ({self.profit_net_pct:+.3f}%)"
        )


class ProfitCalculator:
    """Calcule la rentabilité réelle après gas fees."""

    # Gas moyen pour un swap multi-hop sur PancakeSwap V2
    GAS_PER_HOP = 150_000  # ~150k gas par hop

    def __init__(self, w3: Web3, scanner: PriceScanner):
        self.w3 = w3
        self.scanner = scanner
        self._bnb_price_cache: float = 0
        self._cache_block: int = 0

    def get_bnb_price(self) -> float:
        """Prix BNB en USD avec cache par bloc."""
        current_block = self.w3.eth.block_number
        if self._cache_block != current_block or self._bnb_price_cache == 0:
            self._bnb_price_cache = self.scanner.get_bnb_price_usd()
            self._cache_block = current_block
        return self._bnb_price_cache

    def estimate_gas_cost(self, num_hops: int) -> tuple[float, float]:
        """Estime le coût en gas (BNB et USD)."""
        total_gas = self.GAS_PER_HOP * num_hops
        gas_cost_wei = total_gas * self.w3.to_wei(GAS_PRICE_GWEI, "gwei")
        gas_cost_bnb = float(self.w3.from_wei(gas_cost_wei, "ether"))
        gas_cost_usd = gas_cost_bnb * self.get_bnb_price()
        return gas_cost_bnb, gas_cost_usd

    def evaluate(self, quote: RouteQuote, capital_bnb: float) -> ArbOpportunity:
        """Évalue une opportunité avec calcul de profit net."""
        bnb_price = self.get_bnb_price()

        capital_usd = capital_bnb * bnb_price
        gross_profit_bnb = float(self.w3.from_wei(quote.profit_wei, "ether"))
        gross_profit_usd = gross_profit_bnb * bnb_price

        num_hops = len(quote.path) - 1
        gas_cost_bnb, gas_cost_usd = self.estimate_gas_cost(num_hops)

        profit_net_bnb = gross_profit_bnb - gas_cost_bnb
        profit_net_usd = gross_profit_usd - gas_cost_usd
        profit_net_pct = (profit_net_bnb / capital_bnb * 100) if capital_bnb > 0 else 0

        viable = profit_net_usd >= MIN_PROFIT_USD and gas_cost_usd <= MAX_GAS_USD

        return ArbOpportunity(
            route=quote,
            bnb_price_usd=bnb_price,
            capital_bnb=capital_bnb,
            capital_usd=capital_usd,
            gross_profit_bnb=gross_profit_bnb,
            gross_profit_usd=gross_profit_usd,
            gas_cost_bnb=gas_cost_bnb,
            gas_cost_usd=gas_cost_usd,
            profit_net_bnb=profit_net_bnb,
            profit_net_usd=profit_net_usd,
            profit_net_pct=profit_net_pct,
            viable=viable,
        )

    def find_opportunities(
        self, quotes: list[RouteQuote], capital_bnb: float
    ) -> list[ArbOpportunity]:
        """Évalue toutes les quotes et retourne les opportunités viables."""
        opportunities = []
        for quote in quotes:
            opp = self.evaluate(quote, capital_bnb)
            if opp.viable:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.profit_net_usd, reverse=True)
        return opportunities
