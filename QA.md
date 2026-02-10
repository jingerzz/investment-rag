# QA Findings — Investment Research RAG

**Date:** 2026-02-10  
**Environment:** Windows 10, PowerShell, Python 3.12+ via uv  
**Scope:** CLI tools, MCP server startup, config, and external dependencies

---

## Executive Summary

- **New features added:** form-type filtering in `fetch-sec` and a `manage-docs` CLI for listing/deleting indexed documents.
- **Ingest CLI** and **MCP server** start and behave as expected (when environment is healthy).
- **SEC filing fetch** and other CLIs are currently blocked by a transient `uv` packaging/lock-file issue on this machine (file-in-use error on `rag-server.exe`).
- **Earnings transcript fetch** is still subject to FMP API key / plan limitations.

---

## 1. Test Results (2026-02-10)

| Component | Command | Result | Notes |
|-----------|---------|--------|--------|
| Config | `config.json` | ⚠️ Partial | Real SEC user-agent and (optional) FMP key must be supplied by the user; repo ships `config.example.json` only. |
| SEC fetch | `uv run fetch-sec AAPL` | ⚠️ Blocked by env | `uv` failed with a file-in-use error on `.venv/.../rag-server.exe`; feature logic reviewed + linted, but end-to-end run could not complete on this machine. |
| Transcript fetch | `uv run fetch-transcripts AAPL` | ⚠️ Depends on FMP plan | Behavior unchanged; requires valid FMP key and sufficient plan to access transcripts. |
| Ingest | `uv run ingest` | ✅ Pass (previous QA) | Exits cleanly when `data/drop` is empty; reports supported file types. |
| MCP server | `uv run rag-server` | ⚠️ Blocked by same env issue | Startup blocked by same `rag-server.exe` file-in-use error when packaging/scripts were re-built. |
| Manage docs | `uv run manage-docs` | ⚠️ Blocked by env | New CLI compiles and passes linting; startup blocked by same `uv`/Windows file lock error. |

---

## 2. Current Blocking Issue — uv / Windows File Lock

### 2.1 Observed Error (affects all `uv run <script>` commands)

```text
error: failed to remove file `C:\Users\jxie0\investment-rag\.venv\Lib\site-packages\../../Scripts/rag-server.exe`: The process cannot access the file because it is being used by another process. (os error 32)
```

This occurs when running:

```powershell
uv run fetch-sec AAPL
uv run manage-docs
uv run rag-server
```

### 2.2 Interpretation

- `uv` is attempting to (re)build and clean up entry-point scripts under `.venv\Scripts\rag-server.exe`.
- On this Windows machine, `rag-server.exe` is locked by another process (likely a previous run or an IDE integration).
- As a result, `uv` exits with code 2 **before** the Python script (`fetch_sec`, `manage_docs`, or `rag-server`) actually starts, so the new logic cannot be exercised end-to-end here.

### 2.3 Suggested Actions

For anyone picking this up:

1. **Stop any running processes** that might be holding `rag-server.exe`:
   - Close Claude Desktop and any terminals that might be running `uv run rag-server` / `python -m src.server`.
   - In Task Manager, kill any stray `rag-server.exe` processes if present.
2. Retry:
   ```powershell
   cd investment-rag
   uv run fetch-sec AAPL
   uv run manage-docs
   ```
3. If the error persists, consider:
   - Removing and recreating the virtual environment (`.venv`) after ensuring no processes are using it.
   - Filing a small repro with `uv` maintainers, since this is a packaging/lock-file behavior on Windows.

---

## 3. New Features (Logic & Linting)

### 3.1 Form-Type Filtering in `fetch-sec`

- **Change:** After entering a ticker, the CLI now prompts:

  ```text
  Filter by form type(s)? (e.g. 10-K,10-Q) [leave blank for all]:
  ```

- Behavior:
  - Blank input → same as before (up to 20 most recent filings of any type).
  - `10-K` → up to 20 most recent 10-K filings.
  - `10-Q` → up to 20 most recent 10-Q filings.
  - `10-K,10-Q` → up to 20 filings whose `form` is either 10-K or 10-Q.
  - If no filings match, the CLI reports that and exits gracefully.
- Implementation details:
  - Uses a simple `set` of uppercased form codes to filter `company.get_filings()`.
  - Preserves the existing integer-indexing pattern to avoid the historical edgartools slice bug.

### 3.2 `manage-docs` CLI (List & Delete Indexed Documents)

- **New script:** `manage-docs = "src.manage_docs:main"` in `pyproject.toml`.
- Capabilities:
  - Choose a collection (`sec_filings`, `transcripts`, `market_data`, or `all`).
  - For each chosen collection:
    - Display a table of documents with `#`, `source_file`, `ticker`, and `chunks`.
  - If a specific collection is chosen:
    - Prompt for one or more indices (e.g. `1,3-5` or `all`) to delete.
    - Confirm with a `"yes"` prompt before deletion.
    - Call `db.remove_by_source(source_file)` to remove all chunks across all collections for that `source_file`.
- The module passes linting and imports cleanly; interactive behavior awaits successful `uv run manage-docs` once the file lock issue is resolved.

---

## 4. What Was Not Fully Tested (This Session)

- **End-to-end SEC fetch / manage-docs / rag-server via `uv run`**  
  Blocked by the Windows file lock on `rag-server.exe` (see Section 2).
- **Ollama / embeddings:** As before, not exercised in this session.
- **MCP tools via Claude Desktop:** Not re-tested; behavior should be unchanged aside from the underlying `db.remove_by_source` also being used by `manage-docs`.

Future QA on a machine without the `uv`/Windows file lock issue should repeat:

```powershell
cd investment-rag
uv sync
uv run fetch-sec AAPL
uv run manage-docs
uv run ingest
uv run rag-server
```

and record results here.
