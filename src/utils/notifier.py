"""
Notifier - Système de notifications (console pour l'instant, extensible vers Telegram/Discord).
"""

from src.utils.logger import console


class Notifier:
    """Envoie des notifications sur les événements importants."""

    def __init__(self):
        self.enabled = True

    def notify_trade(self, action: str, symbol: str, price: float, amount: float):
        """Notification lors d'un trade exécuté."""
        if not self.enabled:
            return
        emoji = "+" if action.upper() == "BUY" else "-"
        console.print(
            f"\n[bold]TRADE EXECUTE[/bold] {emoji} {action.upper()} "
            f"{amount:.6f} {symbol} @ ${price:,.2f}\n",
            style="bold cyan",
        )

    def notify_stop_loss(self, symbol: str, loss_pct: float):
        """Notification stop-loss déclenché."""
        if not self.enabled:
            return
        console.print(
            f"\n[bold red]STOP-LOSS[/bold red] {symbol} | Perte: {loss_pct:.2f}%\n"
        )

    def notify_take_profit(self, symbol: str, profit_pct: float):
        """Notification take-profit atteint."""
        if not self.enabled:
            return
        console.print(
            f"\n[bold green]TAKE-PROFIT[/bold green] {symbol} | Gain: {profit_pct:.2f}%\n"
        )

    def notify_error(self, message: str):
        """Notification d'erreur."""
        console.print(f"\n[bold red]ERREUR[/bold red] {message}\n")

    def notify_bot_status(self, status: str):
        """Notification changement de statut du bot."""
        console.print(f"\n[bold cyan]BOT[/bold cyan] {status}\n")
