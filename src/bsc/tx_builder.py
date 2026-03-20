# tx_builder.py — Construction et envoi de transactions d'arbitrage BSC
import time
import logging
from web3 import Web3

from .config import (
    WALLET_ADDRESS,
    PRIVATE_KEY,
    PANCAKESWAP_V2_ROUTER,
    ROUTER_ABI,
    ERC20_ABI,
    WBNB,
    GAS_PRICE_GWEI,
    SLIPPAGE_PCT,
    DRY_RUN,
)
from .profit_calc import ArbOpportunity

logger = logging.getLogger("bsc.tx")


class TxBuilder:
    """Construit et envoie les transactions d'arbitrage sur BSC."""

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.router = w3.eth.contract(
            address=Web3.to_checksum_address(PANCAKESWAP_V2_ROUTER),
            abi=ROUTER_ABI,
        )

        if WALLET_ADDRESS:
            self.wallet = Web3.to_checksum_address(WALLET_ADDRESS)
        else:
            self.wallet = None

        self.private_key = PRIVATE_KEY
        logger.info(
            f"TxBuilder initialisé | Wallet: {self.wallet[:10] + '...' if self.wallet else 'NON CONFIGURÉ'}"
        )

    def _check_wallet(self) -> bool:
        """Vérifie que le wallet est configuré."""
        if not self.wallet or not self.private_key:
            logger.error("Wallet non configuré — BSC_WALLET_ADDRESS et BSC_PRIVATE_KEY requis")
            return False
        return True

    def get_balance_bnb(self) -> float:
        """Retourne le solde BNB du wallet."""
        if not self.wallet:
            return 0.0
        balance_wei = self.w3.eth.get_balance(self.wallet)
        return float(self.w3.from_wei(balance_wei, "ether"))

    def execute_arb(self, opp: ArbOpportunity) -> str | None:
        """
        Exécute un trade d'arbitrage.
        En DRY_RUN, simule seulement.
        Retourne le tx hash ou None.
        """
        route = opp.route
        path = route.path
        path_names = " → ".join(route.path_names)

        if DRY_RUN:
            logger.info(
                f"[DRY_RUN] Simulation trade: {path_names} | "
                f"Capital: {opp.capital_bnb} BNB | "
                f"Profit net estimé: ${opp.profit_net_usd:.4f}"
            )
            return f"DRY_RUN_{int(time.time())}"

        if not self._check_wallet():
            return None

        try:
            # Le chemin commence par WBNB — on utilise swapExactETHForTokens pour le premier swap
            # puis swapExactTokensForETH pour le retour
            # Pour simplifier, on fait un seul swap multi-hop
            amount_in = route.amount_in
            min_out = int(route.final_amount * (1 - SLIPPAGE_PCT / 100))
            deadline = int(time.time()) + 300  # 5 minutes

            checksum_path = [Web3.to_checksum_address(addr) for addr in path]

            # Si le chemin commence ET finit par WBNB → swap payable
            if path[0].lower() == WBNB.lower():
                tx = self.router.functions.swapExactETHForTokens(
                    min_out,
                    checksum_path,
                    self.wallet,
                    deadline,
                ).build_transaction({
                    "from": self.wallet,
                    "value": amount_in,
                    "gas": 500_000,
                    "gasPrice": self.w3.to_wei(GAS_PRICE_GWEI, "gwei"),
                    "nonce": self.w3.eth.get_transaction_count(self.wallet),
                })
            else:
                # Approve d'abord si nécessaire
                self._approve_token(path[0], amount_in)
                tx = self.router.functions.swapExactTokensForTokens(
                    amount_in,
                    min_out,
                    checksum_path,
                    self.wallet,
                    deadline,
                ).build_transaction({
                    "from": self.wallet,
                    "value": 0,
                    "gas": 500_000,
                    "gasPrice": self.w3.to_wei(GAS_PRICE_GWEI, "gwei"),
                    "nonce": self.w3.eth.get_transaction_count(self.wallet),
                })

            # Signer et envoyer
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            logger.info(f"Transaction envoyée: {tx_hash_hex}")

            # Attendre confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt["status"] == 1:
                logger.info(f"Transaction confirmée ! Gas utilisé: {receipt['gasUsed']}")
                return tx_hash_hex
            else:
                logger.error(f"Transaction échouée (revert) | tx: {tx_hash_hex}")
                return None

        except Exception as e:
            logger.error(f"Erreur exécution trade: {e}", exc_info=True)
            return None

    def _approve_token(self, token_address: str, amount: int):
        """Approve un token pour le router si nécessaire."""
        token = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )
        try:
            tx = token.functions.approve(
                Web3.to_checksum_address(PANCAKESWAP_V2_ROUTER),
                amount,
            ).build_transaction({
                "from": self.wallet,
                "gas": 100_000,
                "gasPrice": self.w3.to_wei(GAS_PRICE_GWEI, "gwei"),
                "nonce": self.w3.eth.get_transaction_count(self.wallet),
            })
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            logger.info(f"Approve confirmé pour {token_address[:10]}...")
        except Exception as e:
            logger.warning(f"Approve échoué pour {token_address[:10]}...: {e}")
