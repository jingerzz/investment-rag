"""MCP server exposing investment RAG tools to Claude Desktop."""

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import db, chunker
from .parsers import parse_file

# All logging to stderr (stdout is MCP protocol channel)
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("investment-rag")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SEC_DIR = ROOT / "data" / "sec_filings"
TRANSCRIPTS_DIR = ROOT / "data" / "transcripts"
DROP_DIR = ROOT / "data" / "drop"
PROCESSED_DIR = ROOT / "data" / "processed"

mcp = FastMCP("investment-rag")


def _load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


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


# ── Search tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def search_filings(query: str, ticker: str = "", doc_type: str = "") -> str:
    """Search SEC filings in the RAG database.

    Args:
        query: Natural language search query
        ticker: Optional ticker to filter by (e.g. "AAPL")
        doc_type: Optional filing type to filter by (e.g. "10-K", "10-Q")
    """
    where = {}
    if ticker:
        where["ticker"] = ticker.upper()
    if doc_type:
        where["filing_type"] = doc_type
    if len(where) > 1:
        where = {"$and": [{k: v} for k, v in where.items()]}
    elif not where:
        where = None

    results = db.search("sec_filings", query, n_results=8, where=where)
    if not results:
        return "No matching SEC filings found in the database."

    parts = []
    for r in results:
        m = r["metadata"]
        header = f"[{m.get('ticker', '?')} {m.get('filing_type', '')} {m.get('filing_date', '')}]"
        section = f" Section: {m['section']}" if "section" in m else ""
        source = f" Source: {m.get('source_file', '')}"
        parts.append(f"{header}{section}{source}\n{r['document']}")
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def search_transcripts(query: str, ticker: str = "", year: int = 0, quarter: int = 0) -> str:
    """Search earnings call transcripts in the RAG database.

    Args:
        query: Natural language search query
        ticker: Optional ticker to filter by
        year: Optional year to filter by
        quarter: Optional quarter (1-4) to filter by
    """
    where = {}
    if ticker:
        where["ticker"] = ticker.upper()
    if year:
        where["year"] = year
    if quarter:
        where["quarter"] = quarter
    if len(where) > 1:
        where = {"$and": [{k: v} for k, v in where.items()]}
    elif not where:
        where = None

    results = db.search("transcripts", query, n_results=8, where=where)
    if not results:
        return "No matching transcripts found in the database."

    parts = []
    for r in results:
        m = r["metadata"]
        header = f"[{m.get('ticker', '?')} Q{m.get('quarter', '?')} {m.get('year', '')}]"
        source = f" Source: {m.get('source_file', '')}"
        parts.append(f"{header}{source}\n{r['document']}")
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def search_market_data(query: str, ticker: str = "") -> str:
    """Search market/financial data (CSV/Excel imports) in the RAG database.

    Args:
        query: Natural language search query
        ticker: Optional ticker to filter by
    """
    where = {"ticker": ticker.upper()} if ticker else None
    results = db.search("market_data", query, n_results=8, where=where)
    if not results:
        return "No matching market data found in the database."

    parts = []
    for r in results:
        m = r["metadata"]
        header = f"[{m.get('ticker', '?')}]"
        source = f" Source: {m.get('source_file', '')}"
        parts.append(f"{header}{source}\n{r['document']}")
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def list_indexed_documents(collection: str = "") -> str:
    """List all documents indexed in the RAG database.

    Args:
        collection: Optional collection name ("sec_filings", "transcripts", "market_data"). If empty, lists all.
    """
    docs = db.list_documents(collection if collection else None)
    if not any(docs.values()):
        return "The database is empty. No documents have been indexed yet."

    parts = []
    for col_name, items in docs.items():
        if not items:
            parts.append(f"**{col_name}**: (empty)")
            continue
        lines = [f"**{col_name}** ({len(items)} documents):"]
        for item in items:
            lines.append(f"  - {item['source_file']} ({item['chunks']} chunks) [{item.get('ticker', '')}]")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ── Ingestion tools ───────────────────────────────────────────────────────────


@mcp.tool()
def fetch_sec_filings(ticker: str, filing_types: list[str] | None = None, limit: int = 3) -> str:
    """Download and index SEC filings from EDGAR into the RAG database.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "MSFT")
        filing_types: List of filing types to fetch (default: ["10-K", "10-Q"])
        limit: Max number of filings per type to fetch (default: 3)
    """
    from edgar import Company, set_identity

    cfg = _load_config()
    ua = (cfg.get("sec_user_agent") or "").strip()
    if not ua:
        return (
            "SEC User-Agent not configured. Run 'uv run fetch-sec' once to set it up, "
            "or edit config.json and set sec_user_agent to: Your Name (your.email@domain.com)"
        )
    if _is_placeholder_identity(ua):
        return (
            "SEC requires your real name and email and rejects placeholders. "
            "Edit config.json and set sec_user_agent to: Your Name (your.email@domain.com) "
            "with your real name and email, or run 'uv run fetch-sec' to set it interactively."
        )
    set_identity(ua)

    if filing_types is None:
        filing_types = ["10-K", "10-Q"]

    ticker = ticker.upper()
    company = Company(ticker)
    total_indexed = 0
    total_chunks = 0
    errors = []

    for ftype in filing_types:
        filings = company.get_filings(form=ftype)
        for i in range(min(limit, len(filings))):
            f = filings[i]
            try:
                html_content = f.html()
                if not html_content:
                    continue

                ticker_dir = SEC_DIR / ticker
                ticker_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{f.form}_{f.filing_date}_{f.accession_no.replace('-', '')}.html"
                filepath = ticker_dir / filename
                filepath.write_text(html_content, encoding="utf-8")

                text, metadata = parse_file(filepath)
                metadata.update({
                    "ticker": ticker,
                    "filing_type": f.form,
                    "filing_date": str(f.filing_date),
                    "source_file": f"{ticker}/{filename}",
                })
                chunks = chunker.chunk_document(text, metadata)
                if chunks:
                    ids, docs, metas = zip(*chunks)
                    db.add_documents("sec_filings", list(ids), list(docs), list(metas))
                    total_chunks += len(chunks)
                total_indexed += 1
                logger.info(f"Indexed {ticker} {f.form} {f.filing_date} ({len(chunks)} chunks)")
            except Exception as e:
                errors.append(f"{ftype}: {e}")
                logger.error(f"Error indexing {ticker} {ftype}: {e}")

    parts = [f"Indexed {total_indexed} filing(s) for {ticker} ({total_chunks} chunks total)."]
    if errors:
        parts.append("Errors:\n" + "\n".join(f"  - {e}" for e in errors))
    return "\n".join(parts)


@mcp.tool()
def fetch_earnings_transcript(ticker: str, year: int = 0, quarter: int = 0) -> str:
    """Fetch and index an earnings call transcript via FMP API.

    Args:
        ticker: Stock ticker symbol
        year: Year of the transcript (0 = most recent)
        quarter: Quarter 1-4 (0 = most recent)
    """
    import httpx

    cfg = _load_config()
    api_key = cfg.get("fmp_api_key")
    if not api_key:
        return "FMP API key not configured. Run 'uv run fetch-transcripts' once to set it up."

    ticker = ticker.upper()
    base = "https://financialmodelingprep.com/api/v3"

    try:
        if year == 0 or quarter == 0:
            # Fetch list to find most recent
            resp = httpx.get(
                f"{base}/earning_call_transcript/{ticker}",
                params={"apikey": api_key},
                timeout=30.0,
            )
            resp.raise_for_status()
            available = resp.json()
            if not available:
                return f"No earnings transcripts found for {ticker}."
            latest = available[0]
            year = latest["year"]
            quarter = latest["quarter"]

        # Fetch transcript
        resp = httpx.get(
            f"{base}/earning_call_transcript/{ticker}",
            params={"apikey": api_key, "year": year, "quarter": quarter},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return f"No transcript found for {ticker} Q{quarter} {year}."

        content = data[0].get("content", "")
        if not content:
            return f"Transcript for {ticker} Q{quarter} {year} has no content."

        # Save
        ticker_dir = TRANSCRIPTS_DIR / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{ticker}_Q{quarter}_{year}.txt"
        filepath = ticker_dir / filename
        filepath.write_text(content, encoding="utf-8")

        # Index
        from .parsers.text_parser import parse_text
        text, metadata = parse_text(filepath)
        metadata.update({
            "ticker": ticker,
            "year": year,
            "quarter": quarter,
            "source_file": f"{ticker}/{filename}",
        })
        chunks = chunker.chunk_document(text, metadata)
        if chunks:
            ids, docs, metas = zip(*chunks)
            db.add_documents("transcripts", list(ids), list(docs), list(metas))

        return f"Indexed {ticker} Q{quarter} {year} earnings transcript ({len(chunks)} chunks)."

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "FMP API key is invalid or expired. Update the key in config.json or run 'uv run fetch-transcripts' to reconfigure."
        if e.response.status_code == 403:
            return (
                "403 Forbidden — FMP denied access. Earnings call transcripts may require a paid FMP plan (Starter or above). "
                "See https://financialmodelingprep.com/pricing-plans"
            )
        return f"FMP API error: {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"Error fetching transcript: {e}"


@mcp.tool()
def ingest_drop_folder() -> str:
    """Process and index any files in the data/drop/ folder with auto-detected metadata."""
    from .parsers import PARSERS

    DROP_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = [f for f in sorted(DROP_DIR.iterdir()) if f.is_file() and f.suffix.lower() in PARSERS]
    if not files:
        return "No supported files found in the drop folder."

    results = []
    for filepath in files:
        try:
            text, metadata = parse_file(filepath)
            # Auto-detect ticker from filename
            import re
            m = re.match(r"^([A-Z]{1,5})[\s_\-]", filepath.stem, re.IGNORECASE)
            ticker = m.group(1).upper() if m else "UNKNOWN"
            metadata["ticker"] = ticker
            metadata["source_file"] = f"{ticker}/{filepath.name}"

            # Guess collection based on content/extension
            collection = "market_data" if filepath.suffix.lower() in (".csv", ".xlsx", ".xls") else "sec_filings"

            chunks = chunker.chunk_document(text, metadata)
            if chunks:
                ids, docs, metas = zip(*chunks)
                db.add_documents(collection, list(ids), list(docs), list(metas))

            # Move to processed
            import shutil
            dest = PROCESSED_DIR / filepath.name
            if dest.exists():
                dest = PROCESSED_DIR / f"{filepath.stem}_{id(filepath)}{filepath.suffix}"
            shutil.move(str(filepath), str(dest))

            results.append(f"✓ {filepath.name} → {collection} ({len(chunks)} chunks, ticker: {ticker})")
        except Exception as e:
            results.append(f"✗ {filepath.name} — Error: {e}")

    return f"Processed {len(files)} file(s):\n" + "\n".join(results)


@mcp.tool()
def remove_document(source_file: str) -> str:
    """Remove a document and all its chunks from the database.

    Args:
        source_file: The source_file identifier (e.g. "AAPL/10-K_2024-11-01_000032019324.html")
    """
    removed = db.remove_by_source(source_file)
    if removed:
        return f"Removed {removed} chunks for '{source_file}'."
    return f"No chunks found for '{source_file}'."


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
