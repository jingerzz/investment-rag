"""CLI tool to inspect and delete documents from the RAG database."""

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from . import db

console = Console()


def _parse_selection(selection: str, max_val: int) -> list[int]:
    """Parse user selection like '1,3,5' or '1-5' or 'all'."""
    selection = selection.strip().lower()
    if selection == "all":
        return list(range(1, max_val + 1))
    result: list[int] = []
    for part in selection.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            result.extend(range(int(a), int(b) + 1))
        else:
            result.append(int(part))
    return [i for i in result if 1 <= i <= max_val]


def _choose_collection() -> str | None:
    console.print(
        "\n[bold]Which collection do you want to inspect?[/bold]\n"
        "1) sec_filings\n"
        "2) transcripts\n"
        "3) market_data\n"
        "4) all (read-only listing)\n"
    )
    choice = Prompt.ask("Enter choice", choices=["1", "2", "3", "4"], default="1")
    mapping = {"1": "sec_filings", "2": "transcripts", "3": "market_data", "4": "all"}
    return mapping.get(choice)


def _list_documents(collection: str | None):
    docs = db.list_documents(None if collection == "all" else collection)
    if not any(docs.values()):
        console.print("[yellow]The database is empty. No documents have been indexed yet.[/yellow]")
        return {}

    for col_name, items in docs.items():
        table = Table(title=f"Documents in {col_name}")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Source file", width=60)
        table.add_column("Ticker", width=10)
        table.add_column("Chunks", width=8, justify="right")

        for idx, item in enumerate(items, 1):
            table.add_row(
                str(idx),
                item["source_file"],
                item.get("ticker", ""),
                str(item.get("chunks", 0)),
            )

        console.print(table)

    return docs


def main():
    collection = _choose_collection()
    if not collection:
        return

    docs = _list_documents(collection)
    if not docs:
        return

    # If viewing all collections, treat as read-only (no deletes).
    if collection == "all":
        console.print(
            "\n[bold]Read-only mode:[/bold] Re-run and choose a specific collection "
            "if you want to delete documents."
        )
        return

    items = docs.get(collection, [])
    if not items:
        console.print(f"[yellow]{collection} is empty.[/yellow]")
        return

    selection = Prompt.ask(
        "\nSelect documents to delete by index (e.g. 1,3-5) or 'none' to cancel",
        default="none",
    ).strip()
    if selection.lower() in ("none", "n", ""):
        console.print("[green]No documents deleted.[/green]")
        return

    indices = _parse_selection(selection, len(items))
    if not indices:
        console.print("[red]No valid selection.[/red]")
        return

    console.print(
        f"\nYou are about to delete [bold]{len(indices)}[/bold] document(s) "
        f"from [bold]{collection}[/bold]. This removes all associated chunks."
    )
    confirm = Prompt.ask("Type 'yes' to confirm", default="no")
    if confirm.lower() != "yes":
        console.print("[green]Aborted. No documents deleted.[/green]")
        return

    total_removed = 0
    for idx in indices:
        item = items[idx - 1]
        sf = item["source_file"]
        removed = db.remove_by_source(sf)
        total_removed += removed
        console.print(f"  Removed {removed} chunk(s) for [bold]{sf}[/bold].")

    console.print(
        f"\n[green]Done.[/green] Removed a total of [bold]{total_removed}[/bold] chunk(s)."
    )


if __name__ == "__main__":
    main()

