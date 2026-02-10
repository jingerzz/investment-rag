"""Interactive SEC filing browser and downloader using edgartools."""

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from edgar import Company, set_identity

from . import db, chunker
from .parsers import parse_file

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SEC_DIR = ROOT / "data" / "sec_filings"

console = Console()


def _load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _is_placeholder_identity(ua: str) -> bool:
    """SEC rejects placeholder identities; require real name and email."""
    if not ua or not ua.strip():
        return True
    ua_lower = ua.lower()
    return (
        "example.com" in ua_lower
        or "your.email" in ua_lower
        or "research@local" in ua_lower
        or "@local" in ua_lower
    )


def _ensure_identity():
    cfg = _load_config()
    ua = cfg.get("sec_user_agent", "").strip()
    if not ua or _is_placeholder_identity(ua):
        console.print("\n[bold]SEC EDGAR requires your real name and email.[/bold]")
        console.print("Format: Your Name (your.email@domain.com)")
        console.print("SEC rejects placeholders like research@local or example.com.\n")
        ua = Prompt.ask("Enter your SEC User-Agent")
        cfg["sec_user_agent"] = ua
        _save_config(cfg)
    set_identity(cfg["sec_user_agent"])


def _index_filing(filepath: Path, ticker: str, filing_type: str, filing_date: str):
    """Parse, chunk, and index a single filing."""
    text, metadata = parse_file(filepath)
    metadata.update({
        "ticker": ticker,
        "filing_type": filing_type,
        "filing_date": filing_date,
        "source_file": f"{ticker}/{filepath.name}",
    })
    chunks = chunker.chunk_document(text, metadata)
    if chunks:
        ids, docs, metas = zip(*chunks)
        db.add_documents("sec_filings", list(ids), list(docs), list(metas))
    return len(chunks)


def _parse_selection(selection: str, max_val: int) -> list[int]:
    """Parse user selection like '1,3,5' or '1-5' or 'all'."""
    if selection.strip().lower() == "all":
        return list(range(1, max_val + 1))
    result = []
    for part in selection.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            result.extend(range(int(a), int(b) + 1))
        else:
            result.append(int(part))
    return [i for i in result if 1 <= i <= max_val]


def main():
    _ensure_identity()

    # Accept ticker as argument or prompt
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
    else:
        ticker = Prompt.ask("\nEnter ticker symbol").upper()

    # Optional filter by form type (e.g. 10-K,10-Q)
    form_filter_raw = Prompt.ask(
        "\nFilter by form type(s)? (e.g. 10-K,10-Q) [leave blank for all]",
        default="",
    ).strip()
    form_filters: set[str] | None = None
    if form_filter_raw:
        form_filters = {
            part.strip().upper()
            for part in form_filter_raw.split(",")
            if part.strip()
        }

    console.print(f"\nFetching filings for [bold]{ticker}[/bold]...")

    company = Company(ticker)
    filings = company.get_filings()

    # Get recent filings (up to 20), optionally filtered by form type.
    # Use integer indexing to avoid edgartools slice bug (ChunkedArray.as_py()).
    filing_list = []
    max_to_show = 20
    for i in range(len(filings)):
        f = filings[i]
        if form_filters and f.form.upper() not in form_filters:
            continue
        filing_list.append(f)
        if len(filing_list) >= max_to_show:
            break

    if not filing_list:
        if form_filters:
            console.print(
                f"[red]No filings found matching form type(s): "
                f"{', '.join(sorted(form_filters))}.[/red]"
            )
        else:
            console.print("[red]No filings found.[/red]")
        return

    # Display table
    table = Table(title=f"Recent SEC filings for {company.name} ({ticker})")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Date", width=12)
    table.add_column("Type", width=12)
    table.add_column("Description", width=50)

    for i, f in enumerate(filing_list, 1):
        table.add_row(
            str(i),
            str(f.filing_date),
            f.form,
            f.primary_doc_description or "",
        )

    console.print(table)

    # Selection
    selection = Prompt.ask(
        '\nSelect filings (e.g. 1,3,6 or 1-5 or "all")',
        default="1",
    )
    indices = _parse_selection(selection, len(filing_list))
    if not indices:
        console.print("[red]No valid selection.[/red]")
        return

    # Download
    console.print(f"\nDownloading {len(indices)} filing(s)...")
    downloaded = []
    for idx in indices:
        f = filing_list[idx - 1]
        ticker_dir = SEC_DIR / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        try:
            html_content = f.html()
            if html_content:
                filename = f"{f.form}_{f.filing_date}_{f.accession_no.replace('-', '')}.html"
                filepath = ticker_dir / filename
                filepath.write_text(html_content, encoding="utf-8")
                downloaded.append((filepath, f.form, str(f.filing_date)))
                console.print(f"  [green]✓[/green] {f.form}  {f.filing_date}")
            else:
                console.print(f"  [yellow]⚠[/yellow] {f.form}  {f.filing_date} — no HTML content available")
        except Exception as e:
            console.print(f"  [red]✗[/red] {f.form}  {f.filing_date} — {e}")

    if not downloaded:
        console.print("[red]No filings downloaded.[/red]")
        return

    # Index prompt
    do_index = Prompt.ask("\nIndex these into the RAG now?", choices=["y", "n"], default="y")
    if do_index.lower() == "y":
        console.print("\nIndexing filings...")
        total_chunks = 0
        for filepath, form, date in downloaded:
            n = _index_filing(filepath, ticker, form, date)
            total_chunks += n
        console.print(
            f"\n[green]✓ Done.[/green] {len(downloaded)} documents indexed ({total_chunks} chunks)."
        )


if __name__ == "__main__":
    main()
