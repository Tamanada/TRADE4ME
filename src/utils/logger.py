"""
Logger - Système de logging structuré avec Rich.
"""

import logging
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Thème custom pour le trading
TRADE_THEME = Theme(
    {
        "buy": "bold green",
        "sell": "bold red",
        "hold": "bold yellow",
        "profit": "bold green",
        "loss": "bold red",
        "info": "bold cyan",
    }
)

console = Console(theme=TRADE_THEME)


def setup_logger(name: str = "trade4me", level: str = "INFO") -> logging.Logger:
    """Configure et retourne un logger avec sortie console Rich + fichier."""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    # Handler console avec Rich
    rich_handler = RichHandler(
        console=console,
        show_path=False,
        show_time=True,
        rich_tracebacks=True,
    )
    rich_handler.setLevel(logging.DEBUG)
    logger.addHandler(rich_handler)

    # Handler fichier
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "trade4me.log")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger


def log_trade(action: str, symbol: str, price: float, amount: float, **kwargs):
    """Affiche un trade formaté dans la console."""
    style = "buy" if action.upper() == "BUY" else "sell"
    console.print(
        f"  [{style}]{action.upper()}[/{style}] {symbol} | "
        f"Prix: ${price:,.2f} | Quantité: {amount:.6f}",
        highlight=False,
    )
    if "pnl" in kwargs:
        pnl = kwargs["pnl"]
        pnl_style = "profit" if pnl >= 0 else "loss"
        console.print(
            f"    P&L: [{pnl_style}]{pnl:+.2f} USDT[/{pnl_style}]",
            highlight=False,
        )


def log_signal(signal: str, symbol: str, reason: str):
    """Affiche un signal de trading."""
    style_map = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}
    style = style_map.get(signal.upper(), "info")
    console.print(
        f"  [{style}]{signal.upper()}[/{style}] {symbol} | {reason}",
        highlight=False,
    )
