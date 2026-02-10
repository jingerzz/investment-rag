# Investment Research RAG

Local document ingestion pipeline + ChromaDB vector store + MCP server that gives Claude Desktop tools to search and ingest SEC filings, earnings transcripts, and market data. Runs entirely on local hardware using Ollama for embeddings.

## Architecture

```
Claude Desktop ←(MCP/stdio)→ server.py ←→ ChromaDB (local, embedded)
                                  ↕
                            Ollama embeddings (nomic-embed-text, local)
```

**Three data collections:**
- `sec_filings` — 10-K, 10-Q, 8-K, proxy statements, etc.
- `transcripts` — Earnings call transcripts with speaker labels
- `market_data` — Price/financial CSV/Excel imports

**Two ways to manage data:**
1. **CLI scripts** — Interactive terminal tools for bulk operations
2. **MCP tools** — Claude Desktop can fetch/index on the fly during conversations

## Directory Structure

```
investment-rag/
├── pyproject.toml              # Dependencies + script entry points
├── config.example.json         # Template; copy/edit to create config.json
├── src/
│   ├── server.py               # MCP server (8 tools)
│   ├── embeddings.py           # Ollama embedding wrapper for ChromaDB
│   ├── db.py                   # ChromaDB setup + query helpers
│   ├── chunker.py              # 1000-char chunks, 200-char overlap, section-aware
│   ├── ingest.py               # CLI: interactive drop-folder ingestion
│   ├── fetch_sec.py            # CLI: browse & pick SEC filings
│   ├── fetch_transcripts.py    # CLI: fetch earnings transcripts via FMP API
│   └── parsers/
│       ├── pdf_parser.py       # pypdf extraction
│       ├── html_parser.py      # BeautifulSoup for SEC HTML filings
│       ├── csv_parser.py       # pandas → natural language sentences
│       └── text_parser.py      # Plain text with ticker/quarter detection
├── data/                       # Created at runtime (not committed)
│   ├── drop/                   # Put files here → run ingest → they get indexed
│   ├── sec_filings/            # Auto-downloaded EDGAR filings (by ticker)
│   ├── transcripts/            # Auto-downloaded earnings transcripts (by ticker)
│   └── processed/              # Files moved here after ingestion
└── chromadb_data/              # Vector DB storage (auto-created, not committed)
```

## Prerequisites

- **Python 3.12+** managed by [uv](https://docs.astral.sh/uv/)
- **Ollama** running locally with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`)
- **(Optional)** **FMP API key** from https://financialmodelingprep.com/ if you want to use the transcripts tools (availability depends on your FMP plan)

## Setup

```bash
cd investment-rag

# Install dependencies (handled automatically by uv on first run)
uv sync

# First run — sets up SEC user-agent in config.json
uv run fetch-sec

# (Optional) First run — sets up FMP API key in config.json if you have FMP access
uv run fetch-transcripts
```

## CLI Tools

### Fetch SEC Filings

```bash
uv run fetch-sec           # Prompts for ticker interactively
uv run fetch-sec AAPL      # Skip the ticker prompt
```

Displays a table of recent filings, lets you select which to download, and optionally indexes them into the RAG.

On each run you can also [optionally] filter by form type before the table is shown, e.g.:

- `10-K` to see only 10-Ks
- `10-Q` to see only 10-Qs
- `10-K,10-Q` to see both

### Fetch Earnings Transcripts

```bash
uv run fetch-transcripts        # Prompts for ticker
uv run fetch-transcripts NVDA   # Skip the ticker prompt
```

Lists available earnings call transcripts from FMP, lets you pick which to download and index.

### Ingest Drop Folder

```bash
uv run ingest
```

Processes any supported files placed in `data/drop/`. Walks through each file interactively — auto-detects ticker from filename, asks for document type, indexes into ChromaDB, then moves files to `data/processed/`.

**Supported file types:** PDF, HTML, CSV, XLSX, XLS, TXT, MD

### Manage Indexed Documents (List & Delete)

```bash
uv run manage-docs
```

Lets you:

- List documents currently indexed in `sec_filings`, `transcripts`, or `market_data`
- See the `source_file`, ticker, and chunk count for each
- Interactively select one or more documents to delete (removes all associated chunks)

## MCP Server (Claude Desktop Integration)

The MCP server is configured in Claude Desktop's config at `%APPDATA%\Claude\claude_desktop_config.json`. Restart Claude Desktop after any config changes.

### 8 Tools Exposed to Claude

**Search (read-only):**
| Tool | Description |
|------|-------------|
| `search_filings(query, ticker?, doc_type?)` | Search SEC filings |
| `search_transcripts(query, ticker?, year?, quarter?)` | Search earnings transcripts |
| `search_market_data(query, ticker?)` | Search price/financial CSV data |
| `list_indexed_documents(collection?)` | List what's in the database |

**Ingestion (Claude can populate the database mid-conversation):**
| Tool | Description |
|------|-------------|
| `fetch_sec_filings(ticker, filing_types?, limit?)` | Download + index SEC filings from EDGAR |
| `fetch_earnings_transcript(ticker, year?, quarter?)` | Fetch + index earnings transcript via FMP |
| `ingest_drop_folder()` | Process files in `data/drop/` |
| `remove_document(source_file)` | Remove a document and all its chunks |

### Example Claude Desktop Prompts

- "What documents are in my research database?"
- "Pull NVIDIA's last 3 10-K filings into my database"
- "Search Apple's filings for revenue recognition policy"
- "Get the latest AAPL earnings transcript"
- "I dropped some files in the drop folder, index them"

## Config File

Copy `config.example.json` to `config.json`, then fill in your own values, or let the first CLI runs create/update it for you.

`config.json` stores API credentials:

```json
{
  "sec_user_agent": "Your Name (your.email@domain.com)",
  "fmp_api_key": "your-api-key-here"
}
```

**SEC EDGAR:** Use your **real name and email** in `sec_user_agent`. SEC rejects placeholders (e.g. `example.com`, `research@local`). Format: `Your Name (you@yourdomain.com)`.

## Key Technical Details

- **Embeddings:** Ollama `nomic-embed-text` (768-dim), called locally at `http://localhost:11434`
- **Chunking:** 1000-char chunks with 200-char overlap. Section-aware for SEC filings (splits on ITEM/PART headers)
- **ChromaDB:** Embedded persistent client, no separate server needed
- **CSV handling:** Rows are converted to natural language sentences for semantic search
- **All server logging goes to stderr** (stdout is reserved for MCP stdio protocol)
