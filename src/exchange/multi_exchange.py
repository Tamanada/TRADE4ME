"""
Multi-Exchange Price Scanner - Compare les prix sur plusieurs exchanges en temps réel.
Détecte les opportunités d'arbitrage.
"""

import ccxt
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

logger = logging.getLogger("trade4me")

# Top 20 exchanges par volume/sécurité/rapidité (pas besoin de clé API pour lire les prix)
TOP_20_EXCHANGES = [
    "binance",       # #1 mondial, volume massif, rapide
    "bybit",         # #2 dérivés + spot, très rapide
    "okx",           # #3 ex-OKEx, gros volume Asie
    "coinbase",      # #4 régulé US, très sécurisé
    "kucoin",        # #5 "the people's exchange", beaucoup d'altcoins
    "gate",          # #6 gate.io, énorme catalogue de tokens
    "bitget",        # #7 copy trading, croissance rapide
    "mexc",          # #8 listing rapide de nouveaux tokens
    "htx",           # #9 ex-Huobi, historique solide
    "kraken",        # #10 régulé US/EU, très sécurisé
    "bitfinex",      # #11 historique, gros traders
    "poloniex",      # #12 altcoins historique
    "bingx",         # #13 social trading
    "phemex",        # #14 dérivés + spot rapide
    "lbank",         # #15 gros volume altcoins
    "bitmart",       # #16 beaucoup de listings
    "ascendex",      # #17 ex-BitMax
    "whitebit",      # #18 EU-based, rapide
    "probit",        # #19 Corée, tokens variés
    "digifinex",     # #20 Hong Kong, bon volume
]


@dataclass
class ExchangePrice:
    exchange: str
    symbol: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    available: bool = True


@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    buy_price: float
    sell_exchange: str
    sell_price: float
    spread: float
    spread_pct: float
    all_prices: list
    num_exchanges: int = 0  # Nombre d'exchanges où le token est listé


class MultiExchangeScanner:
    """Scanne plusieurs exchanges pour trouver les meilleurs prix."""

    def __init__(self, exchanges: list[str] = None, tokens: list[str] = None):
        self.exchange_names = exchanges or TOP_20_EXCHANGES
        self.tokens = tokens  # None = auto-discover
        self.exchanges: dict[str, ccxt.Exchange] = {}
        self.exchange_markets: dict[str, set] = {}  # Marchés par exchange
        self._discovered_tokens: list[str] = []
        self._init_exchanges()

    def _init_exchanges(self):
        """Initialise les connexions aux exchanges (lecture seule, pas de clé API)."""
        for name in self.exchange_names:
            try:
                exchange_class = getattr(ccxt, name, None)
                if exchange_class:
                    ex = exchange_class({
                        "enableRateLimit": True,
                        "timeout": 10000,
                    })
                    self.exchanges[name] = ex
                    logger.info(f"Exchange initialisé: {name}")
            except Exception as e:
                logger.warning(f"Impossible d'initialiser {name}: {e}")

    def _load_markets(self, exchange_name: str) -> set:
        """Charge les marchés d'un exchange et retourne les paires USDT."""
        ex = self.exchanges.get(exchange_name)
        if not ex:
            return set()
        try:
            ex.load_markets()
            usdt_pairs = {
                symbol for symbol in ex.markets
                if symbol.endswith("/USDT")
                and ex.markets[symbol].get("active", True)
                and ex.markets[symbol].get("spot", True)
            }
            self.exchange_markets[exchange_name] = usdt_pairs
            logger.info(f"{exchange_name}: {len(usdt_pairs)} paires USDT")
            return usdt_pairs
        except Exception as e:
            logger.warning(f"Erreur chargement marchés {exchange_name}: {e}")
            return set()

    def discover_tokens(self, min_exchanges: int = 3) -> list[str]:
        """
        Découvre tous les tokens listés sur au moins `min_exchanges` exchanges.
        Retourne la liste triée par nombre d'exchanges (les plus communs d'abord).
        """
        logger.info("Découverte des tokens sur tous les exchanges...")

        # Charger les marchés de chaque exchange en parallèle
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self._load_markets, name): name
                for name in self.exchanges
            }
            for future in as_completed(futures, timeout=60):
                try:
                    future.result(timeout=15)
                except Exception:
                    pass

        # Compter sur combien d'exchanges chaque token est listé
        token_count: dict[str, int] = {}
        for exchange_name, pairs in self.exchange_markets.items():
            for pair in pairs:
                token_count[pair] = token_count.get(pair, 0) + 1

        # Garder seulement les tokens sur >= min_exchanges
        common_tokens = [
            token for token, count in token_count.items()
            if count >= min_exchanges
        ]

        # Trier par nombre d'exchanges décroissant
        common_tokens.sort(key=lambda t: token_count[t], reverse=True)

        self._discovered_tokens = common_tokens
        logger.info(
            f"Tokens découverts: {len(common_tokens)} tokens listés sur >= {min_exchanges} exchanges"
        )
        return common_tokens

    def get_token_list(self) -> list[str]:
        """Retourne la liste des tokens à scanner."""
        if self.tokens:
            return self.tokens
        if self._discovered_tokens:
            return self._discovered_tokens
        return self.discover_tokens(min_exchanges=3)

    def _fetch_ticker(self, exchange_name: str, symbol: str) -> ExchangePrice | None:
        """Récupère le prix d'un token sur un exchange."""
        # Skip si on sait que le token n'est pas listé
        if exchange_name in self.exchange_markets:
            if symbol not in self.exchange_markets[exchange_name]:
                return None

        ex = self.exchanges.get(exchange_name)
        if not ex:
            return None

        try:
            ticker = ex.fetch_ticker(symbol)
            return ExchangePrice(
                exchange=exchange_name,
                symbol=symbol,
                bid=ticker.get("bid") or 0,
                ask=ticker.get("ask") or 0,
                last=ticker.get("last") or 0,
                volume_24h=ticker.get("quoteVolume") or 0,
                available=True,
            )
        except (ccxt.BadSymbol, ccxt.BadRequest):
            return None
        except Exception:
            return None

    def scan_token(self, symbol: str) -> ArbitrageOpportunity | None:
        """Scanne un token sur tous les exchanges et retourne l'opportunité d'arbitrage."""
        prices: list[ExchangePrice] = []

        # Ne scanner que les exchanges qui ont ce token
        target_exchanges = []
        for name in self.exchanges:
            if name in self.exchange_markets:
                if symbol in self.exchange_markets[name]:
                    target_exchanges.append(name)
            else:
                target_exchanges.append(name)  # Pas de cache, on essaie

        if len(target_exchanges) < 2:
            return None

        with ThreadPoolExecutor(max_workers=len(target_exchanges)) as executor:
            futures = {
                executor.submit(self._fetch_ticker, name, symbol): name
                for name in target_exchanges
            }
            for future in as_completed(futures, timeout=20):
                try:
                    result = future.result(timeout=5)
                    if result and result.available and result.ask > 0 and result.bid > 0:
                        prices.append(result)
                except Exception:
                    pass

        if len(prices) < 2:
            return None

        best_buy = min(prices, key=lambda p: p.ask)
        best_sell = max(prices, key=lambda p: p.bid)

        spread = best_sell.bid - best_buy.ask
        spread_pct = (spread / best_buy.ask * 100) if best_buy.ask > 0 else 0

        all_prices_data = [
            {
                "exchange": p.exchange,
                "bid": p.bid,
                "ask": p.ask,
                "last": p.last,
                "volume_24h": p.volume_24h,
            }
            for p in sorted(prices, key=lambda p: p.ask)
        ]

        return ArbitrageOpportunity(
            symbol=symbol,
            buy_exchange=best_buy.exchange,
            buy_price=best_buy.ask,
            sell_exchange=best_sell.exchange,
            sell_price=best_sell.bid,
            spread=spread,
            spread_pct=spread_pct,
            all_prices=all_prices_data,
            num_exchanges=len(prices),
        )

    def scan_all(self, max_tokens: int = 0) -> list[ArbitrageOpportunity]:
        """
        Scanne tous les tokens découverts.
        max_tokens=0 scanne tout, sinon limite aux N premiers.
        """
        tokens = self.get_token_list()
        if max_tokens > 0:
            tokens = tokens[:max_tokens]

        logger.info(f"Scan de {len(tokens)} tokens sur {len(self.exchanges)} exchanges...")

        results = []

        # Scanner par lots de 10 tokens pour éviter de surcharger
        batch_size = 10
        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]

            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {
                    executor.submit(self.scan_token, symbol): symbol
                    for symbol in batch
                }
                for future in as_completed(futures, timeout=60):
                    try:
                        result = future.result(timeout=15)
                        if result:
                            results.append(result)
                    except Exception:
                        pass

        # Trier par spread % décroissant
        results.sort(key=lambda r: r.spread_pct, reverse=True)
        return results
