# config.py — Configuration du bot d'arbitrage BSC/PancakeSwap
import os

# ── RPC BSC ───────────────────────────────────────────────────────────────────
BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed1.binance.org")

# ── Wallet ────────────────────────────────────────────────────────────────────
WALLET_ADDRESS = os.getenv("BSC_WALLET_ADDRESS", "")
PRIVATE_KEY = os.getenv("BSC_PRIVATE_KEY", "")

# ── Trading ───────────────────────────────────────────────────────────────────
DRY_RUN = os.getenv("BSC_DRY_RUN", "true").lower() == "true"
SCAN_INTERVAL_MS = int(os.getenv("BSC_SCAN_INTERVAL_MS", "2000"))
MIN_PROFIT_USD = float(os.getenv("BSC_MIN_PROFIT_USD", "0.50"))
SLIPPAGE_PCT = float(os.getenv("BSC_SLIPPAGE_PCT", "0.5"))  # 0.5%
GAS_PRICE_GWEI = float(os.getenv("BSC_GAS_PRICE_GWEI", "3"))
MAX_GAS_USD = float(os.getenv("BSC_MAX_GAS_USD", "0.50"))

# ── Adresses contrats BSC ─────────────────────────────────────────────────────
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
BUSD = "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56"
USDT = "0x55d398326f99059fF775485246999027B3197955"
USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
DAI  = "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3"
CAKE = "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"
ETH  = "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"
BTC  = "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c"

# ── DEX Routers ───────────────────────────────────────────────────────────────
PANCAKESWAP_V2_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
PANCAKESWAP_V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"

# ABI minimal pour le router PancakeSwap V2
ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
        ],
        "name": "getAmountsOut",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactETHForTokens",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactTokensForETH",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# ERC20 ABI minimal (approve + balanceOf + decimals)
ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "spender", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"}
        ],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ── Paires de tokens pour l'arbitrage triangulaire ────────────────────────────
# Chemins : WBNB → Token → Stable → WBNB (triangulaire)
TOKEN_LIST = {
    "WBNB": WBNB,
    "BUSD": BUSD,
    "USDT": USDT,
    "USDC": USDC,
    "DAI": DAI,
    "CAKE": CAKE,
    "ETH": ETH,
    "BTC": BTC,
}

# Routes triangulaires à scanner
TRIANGULAR_ROUTES = [
    # WBNB → Token → Stable → WBNB
    [WBNB, CAKE, BUSD, WBNB],
    [WBNB, CAKE, USDT, WBNB],
    [WBNB, ETH, BUSD, WBNB],
    [WBNB, ETH, USDT, WBNB],
    [WBNB, BTC, BUSD, WBNB],
    [WBNB, BTC, USDT, WBNB],
    [WBNB, BUSD, USDT, WBNB],
    [WBNB, BUSD, USDC, WBNB],
    [WBNB, USDT, USDC, WBNB],
    [WBNB, USDT, DAI, WBNB],
    [WBNB, BUSD, DAI, WBNB],
    [WBNB, CAKE, USDC, WBNB],
]
