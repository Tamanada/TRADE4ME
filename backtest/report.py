"""
Rapport de backtesting - Affiche les résultats de manière claire.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from backtest.engine import BacktestResult

console = Console()


def print_backtest_report(result: BacktestResult):
    """Affiche un rapport de backtest complet."""

    # Header
    console.print()
    console.print(Panel.fit(
        f"[bold cyan]Backtest Report: {result.strategy_name}[/bold cyan]\n"
        f"Symbole: {result.symbol} | Timeframe: {result.timeframe}",
        border_style="cyan",
    ))

    # Métriques principales
    table = Table(title="Performance", show_header=True, header_style="bold")
    table.add_column("Métrique", style="cyan")
    table.add_column("Valeur", justify="right")

    pnl_style = "green" if result.total_pnl >= 0 else "red"

    table.add_row("Total Trades", str(result.total_trades))
    table.add_row("Wins / Losses", f"{result.wins} / {result.losses}")
    table.add_row("Win Rate", f"{result.win_rate:.1f}%")
    table.add_row("P&L Total", f"[{pnl_style}]${result.total_pnl:+,.2f}[/{pnl_style}]")
    table.add_row("Gain Moyen", f"[green]${result.avg_win:+,.2f}[/green]")
    table.add_row("Perte Moyenne", f"[red]${result.avg_loss:+,.2f}[/red]")
    table.add_row("Profit Factor", f"{result.profit_factor:.2f}")
    table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    table.add_row("Max Drawdown", f"[red]{result.max_drawdown:.2f}%[/red]")

    console.print(table)

    # Derniers trades
    if result.trades:
        trade_table = Table(title="Derniers Trades (max 20)", show_header=True, header_style="bold")
        trade_table.add_column("#", justify="right")
        trade_table.add_column("Entrée $", justify="right")
        trade_table.add_column("Sortie $", justify="right")
        trade_table.add_column("P&L", justify="right")
        trade_table.add_column("%", justify="right")
        trade_table.add_column("Raison")

        for i, trade in enumerate(result.trades[-20:], 1):
            style = "green" if trade.pnl > 0 else "red"
            trade_table.add_row(
                str(i),
                f"${trade.entry_price:,.2f}",
                f"${trade.exit_price:,.2f}",
                f"[{style}]${trade.pnl:+,.2f}[/{style}]",
                f"[{style}]{trade.pnl_pct:+.2f}%[/{style}]",
                trade.reason,
            )

        console.print(trade_table)

    console.print()
