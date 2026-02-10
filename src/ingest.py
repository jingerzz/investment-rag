"""Interactive drop-folder ingestion script."""

import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from . import db, chunker
from .parsers import parse_file, PARSERS

ROOT = Path(__file__).resolve().parent.parent
DROP_DIR = ROOT / "data" / "drop"
PROCESSED_DIR = ROOT / "data" / "processed"

COLLECTION_CHOICES = {
    "1": "sec_filings",
    "2": "transcripts",
    "3": "market_data",
}

console = Console()


def _detect_ticker(filename: str) -> str | None:
    """Try to detect ticker from filename."""
    import re
    m = re.match(r"^([A-Z]{1,5})[\s_\-]", filename, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _get_files() -> list[Path]:
    """Get all supported files in the drop folder."""
    files = []
    for path in sorted(DROP_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in PARSERS:
            files.append(path)
    return files


def main():
    DROP_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = _get_files()
    if not files:
        console.print(f"\nNo supported files found in [bold]{DROP_DIR}[/bold]")
        console.print(f"Supported types: {', '.join(PARSERS.keys())}")
        return

    # Show file table
    table = Table(title=f"Found {len(files)} new file(s) in data\\drop\\")
    table.add_column("#", style="cyan", width=4)
    table.add_column("File", width=45)
    table.add_column("Type", width=10)

    type_names = {
        ".pdf": "PDF", ".htm": "HTML", ".html": "HTML",
        ".csv": "CSV", ".xlsx": "Excel", ".xls": "Excel",
        ".txt": "Text", ".md": "Markdown",
    }
    for i, f in enumerate(files, 1):
        table.add_row(str(i), f.name, type_names.get(f.suffix.lower(), f.suffix))

    console.print(table)
    console.print()

    processed = 0
    for i, filepath in enumerate(files, 1):
        console.print(f"[bold]Processing file {i} of {len(files)}:[/bold] {filepath.name}")

        # Detect ticker
        detected = _detect_ticker(filepath.name)
        if detected:
            console.print(f"  Detected ticker: {detected} (from filename)")
            ticker = Prompt.ask("  Ticker symbol", default=detected)
        else:
            ticker = Prompt.ask("  Ticker symbol")
        ticker = ticker.upper()

        # Collection type
        console.print("  Document type? [1] SEC Filing  [2] Transcript  [3] Market Data")
        doc_choice = Prompt.ask("  Choice", choices=["1", "2", "3"], default="1")
        collection = COLLECTION_CHOICES[doc_choice]

        # Extra metadata based on type
        extra_meta = {"ticker": ticker}
        if collection == "sec_filings":
            filing_type = Prompt.ask("  Filing type (e.g. 10-K, 10-Q, 8-K)", default="10-K")
            extra_meta["filing_type"] = filing_type

        # Parse and index
        try:
            text, metadata = parse_file(filepath)
            metadata.update(extra_meta)
            metadata["source_file"] = f"{ticker}/{filepath.name}"

            chunks = chunker.chunk_document(text, metadata)
            if chunks:
                ids, docs, metas = zip(*chunks)
                db.add_documents(collection, list(ids), list(docs), list(metas))

            console.print(f"  [green]✓[/green] Indexed ({len(chunks)} chunks)")

            # Move to processed
            dest = PROCESSED_DIR / filepath.name
            if dest.exists():
                dest = PROCESSED_DIR / f"{filepath.stem}_{i}{filepath.suffix}"
            shutil.move(str(filepath), str(dest))
            processed += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] Error: {e}")

        console.print()

    console.print(
        f"[green]✓ All done.[/green] {processed} file(s) processed, moved to data\\processed\\"
    )


if __name__ == "__main__":
    main()
