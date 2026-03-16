"""
TRADE4ME - Point d'entrée principal.

Usage:
    python main.py              # Démarre en mode paper trading
    python main.py --live       # Démarre en mode live (ATTENTION!)
"""

import argparse
import sys

from src.bot import TradingBot
from src.utils.logger import console


def main():
    parser = argparse.ArgumentParser(description="TRADE4ME - Bot de Trading Crypto")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Mode live trading (argent réel!) - Défaut: paper trading",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Chemin vers le fichier de configuration",
    )
    args = parser.parse_args()

    if args.live:
        console.print("\n[bold red]" + "!" * 60)
        console.print("  ATTENTION: MODE LIVE TRADING")
        console.print("  Vous allez trader avec de l'argent REEL!")
        console.print("!" * 60 + "[/bold red]\n")

        confirm = input("Tapez 'OUI JE CONFIRME' pour continuer: ")
        if confirm != "OUI JE CONFIRME":
            console.print("[yellow]Annulé. Le bot n'a pas été lancé.[/yellow]")
            sys.exit(0)

    bot = TradingBot(config_path=args.config)

    if args.live:
        bot.paper_mode = False
        bot.order_manager.paper_mode = False

    bot.run()


if __name__ == "__main__":
    main()
