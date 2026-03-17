"""
Multi-Exchange Price Scanner - Compare les prix sur plusieurs exchanges en temps réel.
Détecte les opportunités d'arbitrage.
"""

import ccxt
import logging
import statistics
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

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
    suspended: bool = False  # Trading suspendu sur cet exchange
    suspend_reason: str = ""  # Raison de la suspension


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
    # Frais de trading (taker fees en %)
    buy_fee_pct: float = 0.0
    sell_fee_pct: float = 0.0
    total_fees_pct: float = 0.0
    net_spread_pct: float = 0.0  # spread_pct - total_fees_pct
    # Indicateurs techniques (RSI + EMA trend)
    rsi: float | None = None
    ema_trend: str = ""  # "BULLISH", "BEARISH", or ""
    ema_9: float | None = None
    ema_21: float | None = None
    # Suspension info
    suspended_exchanges: list = field(default_factory=list)  # [{exchange, reason}]


class MultiExchangeScanner:
    """Scanne plusieurs exchanges pour trouver les meilleurs prix."""

    # Frais taker par défaut (%) si CCXT ne fournit pas l'info
    DEFAULT_TAKER_FEES = {
        "binance": 0.10, "bybit": 0.10, "okx": 0.10, "coinbase": 0.40,
        "kucoin": 0.10, "gate": 0.15, "bitget": 0.10, "mexc": 0.00,
        "htx": 0.20, "kraken": 0.26, "bitfinex": 0.20, "poloniex": 0.20,
        "bingx": 0.10, "phemex": 0.10, "lbank": 0.10, "bitmart": 0.25,
        "ascendex": 0.10, "whitebit": 0.10, "probit": 0.20, "digifinex": 0.20,
    }
    FALLBACK_FEE = 0.20  # Fee par défaut si exchange inconnu

    def __init__(self, exchanges: list[str] = None, tokens: list[str] = None):
        self.exchange_names = exchanges or TOP_20_EXCHANGES
        self.tokens = tokens  # None = auto-discover
        self.exchanges: dict[str, ccxt.Exchange] = {}
        self.exchange_markets: dict[str, set] = {}  # Marchés par exchange
        self._discovered_tokens: list[str] = []
        self._fee_cache: dict[str, float] = {}  # exchange_name -> taker fee %
        self._suspended_pairs: dict[str, dict[str, str]] = {}  # exchange -> {symbol: reason}
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
            usdt_pairs = set()
            suspended = {}

            for symbol, market in ex.markets.items():
                if not symbol.endswith("/USDT"):
                    continue
                if not market.get("spot", True):
                    continue

                # Détection de suspension de trading
                is_active = market.get("active", True)
                info = market.get("info", {}) or {}
                suspend_reason = self._detect_suspension(exchange_name, info, is_active)

                if suspend_reason:
                    suspended[symbol] = suspend_reason
                    # On inclut quand même dans les marchés pour pouvoir afficher le warning
                    usdt_pairs.add(symbol)
                elif is_active:
                    usdt_pairs.add(symbol)

            self.exchange_markets[exchange_name] = usdt_pairs
            self._suspended_pairs[exchange_name] = suspended

            # Cache les frais taker de cet exchange
            try:
                fee = (ex.fees or {}).get("trading", {}).get("taker")
                if fee and fee > 0:
                    self._fee_cache[exchange_name] = fee * 100  # Convertir en %
                else:
                    self._fee_cache[exchange_name] = self.DEFAULT_TAKER_FEES.get(
                        exchange_name, self.FALLBACK_FEE
                    )
            except Exception:
                self._fee_cache[exchange_name] = self.DEFAULT_TAKER_FEES.get(
                    exchange_name, self.FALLBACK_FEE
                )

            susp_count = len(suspended)
            logger.info(
                f"{exchange_name}: {len(usdt_pairs)} paires USDT "
                f"(fee: {self._fee_cache.get(exchange_name, '?')}%"
                f"{f', {susp_count} suspendues' if susp_count else ''})"
            )
            return usdt_pairs
        except Exception as e:
            logger.warning(f"Erreur chargement marchés {exchange_name}: {e}")
            return set()

    @staticmethod
    def _detect_suspension(exchange_name: str, info: dict, is_active: bool) -> str:
        """
        Détecte si le trading est suspendu pour une paire sur un exchange.
        Retourne la raison de la suspension ou "" si le trading est actif.
        Chaque exchange expose cette info différemment dans market['info'].
        """
        if not is_active:
            return "trading inactive"

        # ── HTX (ex-Huobi) ──
        # info['state'] = 'online' | 'suspend' | 'offline'
        if exchange_name == "htx":
            state = str(info.get("state", "") or info.get("status", "")).lower()
            if state in ("suspend", "suspended", "offline"):
                return f"trading {state}"

        # ── Gate.io ──
        # info['trade_disabled'] = True/False
        if exchange_name == "gate":
            if info.get("trade_disabled"):
                return "trade disabled"
            if str(info.get("trade_status", "")).lower() == "untradable":
                return "untradable"

        # ── KuCoin ──
        # info['enableTrading'] = True/False
        if exchange_name == "kucoin":
            if info.get("enableTrading") is False:
                return "trading disabled"

        # ── OKX ──
        # info['state'] = 'live' | 'suspend' | 'preopen'
        if exchange_name == "okx":
            state = str(info.get("state", "")).lower()
            if state in ("suspend", "suspended"):
                return f"trading {state}"

        # ── Binance ──
        # info['status'] = 'TRADING' | 'HALT' | 'BREAK'
        if exchange_name == "binance":
            status = str(info.get("status", "")).upper()
            if status in ("HALT", "BREAK"):
                return f"trading {status.lower()}"

        # ── Bybit ──
        # info['status'] = 'Trading' | 'Settling' | 'Closed'
        if exchange_name == "bybit":
            status = str(info.get("status", "")).lower()
            if status in ("settling", "closed"):
                return f"trading {status}"

        # ── MEXC ──
        if exchange_name == "mexc":
            state = str(info.get("state", "")).lower()
            if state in ("suspend", "suspended"):
                return f"trading {state}"

        # ── Bitget ──
        if exchange_name == "bitget":
            status = str(info.get("status", "")).lower()
            if status == "offline":
                return "trading offline"

        # ── Générique: champs communs ──
        for key in ("tradingEnabled", "trade_status", "trading"):
            val = info.get(key)
            if val is False:
                return "trading disabled"
            if isinstance(val, str) and val.lower() in ("disabled", "suspended", "halt"):
                return f"trading {val.lower()}"

        return ""

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

    def get_fee(self, exchange_name: str) -> float:
        """Retourne le taker fee (%) pour un exchange."""
        return self._fee_cache.get(
            exchange_name,
            self.DEFAULT_TAKER_FEES.get(exchange_name, self.FALLBACK_FEE),
        )

    def is_suspended(self, exchange_name: str, symbol: str) -> tuple[bool, str]:
        """Vérifie si une paire est suspendue sur un exchange. Retourne (suspended, reason)."""
        susp = self._suspended_pairs.get(exchange_name, {})
        reason = susp.get(symbol, "")
        return (bool(reason), reason)

    def _fetch_ticker(self, exchange_name: str, symbol: str) -> ExchangePrice | None:
        """Récupère le prix d'un token sur un exchange."""
        # Skip si on sait que le token n'est pas listé
        if exchange_name in self.exchange_markets:
            if symbol not in self.exchange_markets[exchange_name]:
                return None

        ex = self.exchanges.get(exchange_name)
        if not ex:
            return None

        # Vérifier suspension
        is_susp, susp_reason = self.is_suspended(exchange_name, symbol)

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
                suspended=is_susp,
                suspend_reason=susp_reason,
            )
        except (ccxt.BadSymbol, ccxt.BadRequest):
            return None
        except Exception:
            return None

    @staticmethod
    def _filter_outlier_prices(prices: list["ExchangePrice"]) -> list["ExchangePrice"]:
        """
        Filtre les prix aberrants (faux positifs).
        Un même ticker (ex: S/USDT) peut correspondre à des tokens différents
        sur différents exchanges. On détecte ça via l'écart au prix médian.
        """
        if len(prices) < 3:
            return prices

        # Calcul du prix médian (basé sur 'last')
        last_prices = [p.last for p in prices if p.last > 0]
        if len(last_prices) < 2:
            return prices

        median_price = statistics.median(last_prices)
        if median_price <= 0:
            return prices

        # Garder seulement les prix dans un facteur 3x du médian
        # (un vrai arbitrage ne dépasse quasi jamais 5-10%, donc 3x = très généreux)
        filtered = []
        for p in prices:
            ratio = p.last / median_price if median_price > 0 else 1
            if 0.33 <= ratio <= 3.0:
                filtered.append(p)
            else:
                logger.debug(
                    f"Prix aberrant filtré: {p.symbol} sur {p.exchange} "
                    f"(last={p.last}, médian={median_price}, ratio={ratio:.1f}x)"
                )

        return filtered

    @staticmethod
    def _filter_low_volume(prices: list["ExchangePrice"], min_volume_usd: float = 1000) -> list["ExchangePrice"]:
        """
        Filtre les prix avec un volume 24h trop faible.
        Un spread élevé sur un exchange sans volume = pas exploitable.
        """
        return [p for p in prices if p.volume_24h >= min_volume_usd]

    def _fetch_indicators(self, exchange_name: str, symbol: str) -> dict:
        """
        Récupère RSI(14) + EMA 9/21 pour un token sur un exchange.
        Utilise les candles 1h (50 dernières) pour avoir assez de données.
        """
        try:
            ex = self.exchanges.get(exchange_name)
            if not ex or not ex.has.get("fetchOHLCV", False):
                return {}

            ohlcv = ex.fetch_ohlcv(symbol, timeframe="1h", limit=50)
            if not ohlcv or len(ohlcv) < 21:
                return {}

            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

            # RSI(14)
            import ta as ta_lib
            rsi_val = ta_lib.momentum.rsi(df["close"], window=14)
            rsi = round(float(rsi_val.iloc[-1]), 1) if not rsi_val.iloc[-1] != rsi_val.iloc[-1] else None

            # EMA 9 & 21
            ema_9 = ta_lib.trend.ema_indicator(df["close"], window=9)
            ema_21 = ta_lib.trend.ema_indicator(df["close"], window=21)

            ema_9_val = float(ema_9.iloc[-1])
            ema_21_val = float(ema_21.iloc[-1])

            # Trend direction
            if ema_9_val > ema_21_val:
                trend = "BULLISH"
            else:
                trend = "BEARISH"

            return {
                "rsi": rsi,
                "ema_trend": trend,
                "ema_9": round(ema_9_val, 8),
                "ema_21": round(ema_21_val, 8),
            }
        except Exception as e:
            logger.debug(f"Indicateurs non disponibles pour {symbol} sur {exchange_name}: {e}")
            return {}

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
            for future in as_completed(futures, timeout=10):
                try:
                    result = future.result(timeout=3)
                    if result and result.available and result.ask > 0 and result.bid > 0:
                        prices.append(result)
                except Exception:
                    pass

        if len(prices) < 2:
            return None

        # ── Anti faux-positifs ──
        # 1. Filtrer les prix aberrants (même ticker = tokens différents)
        prices = self._filter_outlier_prices(prices)
        if len(prices) < 2:
            return None

        # 2. Filtrer le volume trop faible (spread non exploitable)
        prices_with_volume = self._filter_low_volume(prices, min_volume_usd=1000)
        # On garde les prix sans volume seulement si tous ont du volume filtré
        if len(prices_with_volume) >= 2:
            prices = prices_with_volume

        if len(prices) < 2:
            return None

        # ── Collecter les suspensions pour info ──
        suspended_exchanges = []
        for p in prices:
            if p.suspended:
                suspended_exchanges.append({
                    "exchange": p.exchange,
                    "reason": p.suspend_reason,
                })

        # ── Séparer les prix actifs des suspendus ──
        active_prices = [p for p in prices if not p.suspended]
        suspended_prices = [p for p in prices if p.suspended]

        # Si moins de 2 exchanges actifs, pas d'arbitrage possible
        if len(active_prices) < 2:
            return None

        # ── Calcul d'arbitrage sur les exchanges actifs uniquement ──
        best_buy = min(active_prices, key=lambda p: p.ask)
        best_sell = max(active_prices, key=lambda p: p.bid)

        spread = best_sell.bid - best_buy.ask
        spread_pct = (spread / best_buy.ask * 100) if best_buy.ask > 0 else 0

        # Ignorer les spreads négatifs ou aberrants (> 50% = suspect)
        if spread_pct > 50:
            logger.debug(
                f"Spread suspect ignoré: {symbol} {spread_pct:.1f}% "
                f"({best_buy.exchange} → {best_sell.exchange})"
            )
            return None

        all_prices_data = [
            {
                "exchange": p.exchange,
                "bid": p.bid,
                "ask": p.ask,
                "last": p.last,
                "volume_24h": p.volume_24h,
                "suspended": p.suspended,
                "suspend_reason": p.suspend_reason,
            }
            for p in sorted(active_prices + suspended_prices, key=lambda p: p.ask)
        ]

        # ── Frais de trading ──
        buy_fee_pct = self.get_fee(best_buy.exchange)
        sell_fee_pct = self.get_fee(best_sell.exchange)
        total_fees_pct = buy_fee_pct + sell_fee_pct
        net_spread_pct = spread_pct - total_fees_pct

        # ── Indicateurs techniques (RSI + EMA trend) ──
        # Skip si spread net trop faible (economise ~2-3s par token)
        indicators = {}
        if net_spread_pct > 0.1:
            indicators = self._fetch_indicators(best_buy.exchange, symbol)

        return ArbitrageOpportunity(
            symbol=symbol,
            buy_exchange=best_buy.exchange,
            buy_price=best_buy.ask,
            sell_exchange=best_sell.exchange,
            sell_price=best_sell.bid,
            spread=spread,
            spread_pct=spread_pct,
            all_prices=all_prices_data,
            num_exchanges=len(active_prices),
            buy_fee_pct=buy_fee_pct,
            sell_fee_pct=sell_fee_pct,
            total_fees_pct=total_fees_pct,
            net_spread_pct=net_spread_pct,
            rsi=indicators.get("rsi"),
            ema_trend=indicators.get("ema_trend", ""),
            ema_9=indicators.get("ema_9"),
            ema_21=indicators.get("ema_21"),
            suspended_exchanges=suspended_exchanges,
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

        # Trier par spread NET % décroissant (après frais)
        results.sort(key=lambda r: r.net_spread_pct, reverse=True)
        return results
