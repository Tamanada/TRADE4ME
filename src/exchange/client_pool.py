"""
Multi-Exchange Client Pool — Gère plusieurs ExchangeClient authentifiés
pour l'exécution d'arbitrage simultané.
"""

import os
import logging
from src.exchange.client import ExchangeClient

logger = logging.getLogger("trade4me")


class MultiExchangeClientPool:
    """
    Pool de clients Exchange authentifiés.
    Chaque exchange nécessite des clés API dans .env:
      {EXCHANGE_NAME}_API_KEY, {EXCHANGE_NAME}_API_SECRET
      (+ {EXCHANGE_NAME}_PASSPHRASE pour KuCoin, OKX)
    """

    # Exchanges qui nécessitent un passphrase en plus de key/secret
    PASSPHRASE_EXCHANGES = {"kucoin", "okx"}

    def __init__(self, exchanges_config: list[dict]):
        self.clients: dict[str, ExchangeClient] = {}
        self._init_clients(exchanges_config)

    def _init_clients(self, exchanges_config: list[dict]):
        """Initialise les clients pour chaque exchange configuré avec des clés API."""
        for ex_config in exchanges_config:
            name = ex_config.get("name", "").lower()
            if not name:
                continue

            env_prefix = name.upper()
            api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
            api_secret = os.getenv(f"{env_prefix}_API_SECRET", "").strip()

            if not api_key or not api_secret:
                logger.info(f"Pas de clés API pour {name} — skip")
                continue

            # Passphrase pour KuCoin, OKX
            password = None
            if name in self.PASSPHRASE_EXCHANGES:
                password = os.getenv(f"{env_prefix}_PASSPHRASE", "").strip() or None

            sandbox = ex_config.get("sandbox", True)

            try:
                client = ExchangeClient(
                    exchange_name=name,
                    api_key=api_key,
                    api_secret=api_secret,
                    password=password,
                    sandbox=sandbox,
                )
                self.clients[name] = client
                logger.info(f"Client authentifié créé: {name} (sandbox={sandbox})")
            except Exception as e:
                logger.warning(f"Impossible de créer le client pour {name}: {e}")

    def get_client(self, exchange_name: str) -> ExchangeClient | None:
        """Retourne le client authentifié pour un exchange, ou None."""
        return self.clients.get(exchange_name.lower())

    def has_client(self, exchange_name: str) -> bool:
        """Vérifie si un client est configuré pour cet exchange."""
        return exchange_name.lower() in self.clients

    def get_configured_exchanges(self) -> list[str]:
        """Retourne la liste des exchanges avec des clés API configurées."""
        return list(self.clients.keys())
