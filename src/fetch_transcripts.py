"""Interactive earnings transcript fetcher via Financial Modeling Prep API."""

import json
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from . import db, chunker
from .parsers.text_parser import parse_text

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
TRANSCRIPTS_DIR = ROOT / "data" / "transcripts"

FMP_BASE = "https://financialmodelingprep.com/api/v3"

console = Console()


def _load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _ensure_api_key() -> str:
    cfg = _load_config()
    if "fmp_api_key" not in cfg:
        console.print("\n[bold]FMP API key required.[/bold]")
        console.print("Get a free key at https://financialmodelingprep.com/\n")
        key = Prompt.ask("Enter your FMP API key")
        cfg["fmp_api_key"] = key
        _save_config(cfg)
    return cfg["fmp_api_key"]


def _fmp_get(endpoint: str, api_key: str, params: dict | None = None) -> list | dict:
    p = {"apikey": api_key}
    if params:
        p.update(params)
    resp = httpx.get(f"{FMP_BASE}/{endpoint}", params=p, timeout=30.0)
    if resp.status_code == 401:
        console.print("[red]FMP API key is invalid or expired.[/red]")
        console.print("Check your key at https://financialmodelingprep.com/")
        console.print("To update, edit config.json and replace the fmp_api_key value.")
        raise SystemExit(1)
    if resp.status_code == 403:
        console.print("[red]403 Forbidden — FMP denied access to this endpoint.[/red]")
        console.print("Earnings call transcripts may require a paid FMP plan (Starter or above).")
        console.print("See https://financialmodelingprep.com/pricing-plans")
        raise SystemExit(1)
    resp.raise_for_status()
    return resp.json()


def _parse_selection(selection: str, max_val: int) -> list[int]:
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


def _index_transcript(filepath: Path, ticker: str, year: int, quarter: int):
    text, metadata = parse_text(filepath)
    metadata.update({
        "ticker": ticker,
        "year": year,
        "quarter": quarter,
        "source_file": f"{ticker}/{filepath.name}",
    })
    chunks = chunker.chunk_document(text, metadata)
    if chunks:
        ids, docs, metas = zip(*chunks)
        db.add_documents("transcripts", list(ids), list(docs), list(metas))
    return len(chunks)


def main():
    api_key = _ensure_api_key()

    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
    else:
        ticker = Prompt.ask("\nEnter ticker symbol").upper()

    console.print(f"\nFetching transcript list for [bold]{ticker}[/bold]...")

    # Get available transcripts
    data = _fmp_get(f"earning_call_transcript/{ticker}", api_key)
    if not data:
        console.print("[red]No transcripts found.[/red]")
        return

    # FMP returns list of (year, quarter) availability
    # Each entry has "year" and "quarter" fields
    transcript_list = data[:20]  # Show up to 20

    table = Table(title=f"Available earnings call transcripts for {ticker}")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Date", width=12)
    table.add_column("Quarter", width=20)

    for i, t in enumerate(transcript_list, 1):
        date = t.get("date", "")
        if isinstance(date, str) and len(date) > 10:
            date = date[:10]
        table.add_row(
            str(i),
            str(date),
            f"Q{t['quarter']} {t['year']}",
        )

    console.print(table)

    selection = Prompt.ask(
        '\nSelect transcripts (e.g. 1,2,3 or "all")',
        default="1",
    )
    indices = _parse_selection(selection, len(transcript_list))
    if not indices:
        console.print("[red]No valid selection.[/red]")
        return

    # Download
    console.print(f"\nDownloading {len(indices)} transcript(s)...")
    downloaded = []
    for idx in indices:
        t = transcript_list[idx - 1]
        year, quarter = t["year"], t["quarter"]
        ticker_dir = TRANSCRIPTS_DIR / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Fetch full transcript
            full = _fmp_get(
                f"earning_call_transcript/{ticker}",
                api_key,
                params={"year": year, "quarter": quarter},
            )
            if full and isinstance(full, list):
                content = full[0].get("content", "")
                filename = f"{ticker}_Q{quarter}_{year}.txt"
                filepath = ticker_dir / filename
                filepath.write_text(content, encoding="utf-8")
                downloaded.append((filepath, year, quarter))
                console.print(f"  [green]✓[/green] {ticker} Q{quarter} {year}")
            else:
                console.print(f"  [yellow]⚠[/yellow] Q{quarter} {year} — no content")
        except Exception as e:
            console.print(f"  [red]✗[/red] Q{quarter} {year} — {e}")

    if not downloaded:
        console.print("[red]No transcripts downloaded.[/red]")
        return

    do_index = Prompt.ask("\nIndex these into the RAG now?", choices=["y", "n"], default="y")
    if do_index.lower() == "y":
        console.print("\nIndexing transcripts...")
        total_chunks = 0
        for filepath, year, quarter in downloaded:
            n = _index_transcript(filepath, ticker, year, quarter)
            total_chunks += n
        console.print(
            f"\n[green]✓ Done.[/green] {len(downloaded)} transcripts indexed ({total_chunks} chunks)."
        )


if __name__ == "__main__":
    main()
