# QA Findings — Investment Research RAG

**Date:** 2025-02-09  
**Environment:** Windows 10, PowerShell, Python 3.12+ via uv  
**Scope:** CLI tools, MCP server startup, config, and external dependencies

---

## Executive Summary

- **Ingest CLI** and **MCP server** start and behave as expected.
- **SEC filing fetch** fails due to an edgartools/pyarrow compatibility bug.
- **Earnings transcript fetch** fails with 401 Unauthorized (FMP API key).
- **Entry-point scripts** (`fetch-sec`, `fetch-transcripts`, `ingest`) are not installed because the project is not packaged.

---

## 1. Test Results

| Component | Command | Result | Notes |
|-----------|---------|--------|--------|
| Config | `config.json` | ⚠️ Partial | Had `fmp_api_key` only; `sec_user_agent` was missing (added for testing). |
| SEC fetch | `uv run python -m src.fetch_sec AAPL` | ❌ Fail | See Section 2.1. |
| Transcript fetch | `uv run python -m src.fetch_transcripts AAPL` | ❌ Fail | See Section 2.2. |
| Ingest | `uv run python -m src.ingest` | ✅ Pass | Exits cleanly when `data/drop` is empty; reports supported file types. |
| MCP server | `uv run python -m src.server` | ✅ Pass | Starts and exits 0; expects stdio client (e.g. Claude Desktop). |
| Entry points | `uv run fetch-sec` | ❌ Fail | "program not found" — scripts not installed. |

---

## 2. Failures and Root Cause

### 2.1 SEC Filing Fetch — edgartools / pyarrow

**Observed:**

```text
File "...\edgar\entity\filings.py", line 209, in get_filing_at
    form=self.data['form'][item].as_py(),
AttributeError: 'pyarrow.lib.ChunkedArray' object has no attribute 'as_py'
```

**Interpretation:**  
`edgartools` is calling `.as_py()` on a PyArrow value. In current PyArrow, `ChunkedArray` does not have `.as_py()` (that method exists on scalar types, not on array/chunked types). This is a **dependency/API compatibility issue** between `edgartools` and `pyarrow`.

**Suggested actions for coding agent:**

1. Check `edgartools` and `pyarrow` versions in `pyproject.toml` / `uv.lock`; consult edgartools changelog and PyArrow migration notes.
2. Pin or upgrade to a known-good pair (e.g. newer edgartools that supports current PyArrow, or older pyarrow if edgartools expects it).
3. If the bug is inside edgartools and unfixed upstream, consider a local patch or wrapping the filings iteration (e.g. convert ChunkedArray to a list of scalars and call `.as_py()` per element, or use the API edgartools expects) until upstream is fixed.

---

### 2.2 Earnings Transcript Fetch — FMP 401 Unauthorized

**Observed:**

```text
httpx.HTTPStatusError: Client error '401 Unauthorized' for url
'https://financialmodelingprep.com/api/v3/earning_call_transcript/AAPL?apikey=...'
```

**Interpretation:**  
The FMP API key in `config.json` is rejected (expired, invalid, or insufficient plan for this endpoint).

**Suggested actions for coding agent:**

1. Verify the key at FMP (dashboard, plan limits, endpoint access).
2. Do not commit real API keys; use env vars (e.g. `FMP_API_KEY`) or a local-only config and document in README.
3. Add a small health check or preflight (e.g. one allowed FMP request) and surface a clear error if key is missing or invalid.

---

## 3. Entry Points Not Installed

**Observed:**

```text
uv run fetch-sec
error: Failed to spawn: `fetch-sec`
  Caused by: program not found
```

With:

```text
warning: Skipping installation of entry points (`project.scripts`) because this project is not packaged;
to install entry points, set `tool.uv.package = true` or define a `build-system`
```

**Interpretation:**  
`[project.scripts]` in `pyproject.toml` defines `rag-server`, `fetch-sec`, `fetch-transcripts`, `ingest`, but uv does not install them when the project is not packaged.

**Suggested actions for coding agent:**

1. Either:
   - Add `tool.uv.package = true` (and optionally a `build-system`) so entry points are installed and `uv run fetch-sec` etc. work, or
   - Keep current setup and document that the supported way to run is `uv run python -m src.fetch_sec` (and similarly for `src.fetch_transcripts`, `src.ingest`, `src.server`).
2. Align README and any scripts/docs with the chosen run method.

---

## 4. Config and First-Run Behavior

- **Before QA:** `config.json` contained only `fmp_api_key`; no `sec_user_agent`.
- **During QA:** A placeholder `sec_user_agent` was added so SEC CLI could run without interactive prompt: `"Investment Research <research@local>"`.
- SEC requires a User-Agent; the code correctly prompts on first run when `sec_user_agent` is missing. In non-interactive environments this causes `EOFError` if no value is provided.

**Suggested actions for coding agent:**

1. Document required config keys and format (e.g. in README or QA).
2. Optionally support env override for SEC User-Agent (e.g. `SEC_USER_AGENT`) so CI/automation can run without editing `config.json`.
3. If keeping interactive prompt, document that first-time SEC setup must be done in an interactive terminal.

---

## 5. What Was Not Tested

- **Ollama / embeddings:** No check that Ollama is running or that `nomic-embed-text` is available; ingest and RAG indexing depend on it.
- **ChromaDB:** No documents were indexed; DB creation and query path were not exercised.
- **MCP tools from Claude Desktop:** Server was only started standalone; no end-to-end test of tools (e.g. `search_filings`, `fetch_sec_filings`) from a real MCP client.
- **Parsers:** No PDF/HTML/CSV files were placed in `data/drop`; parser and chunker paths were not tested.
- **`rag-server` as entry point:** Same “not installed” behavior as other scripts; when packaged, `uv run rag-server` should be verified.

---

## 6. Recommended Fix Order (for Coding Agent)

1. **Entry points:** Decide packaged vs non-packaged; add `tool.uv.package = true` or document `uv run python -m src.*` and update README.
2. **edgartools/pyarrow:** Resolve SEC fetch (version pin, upgrade, or minimal workaround) so `fetch_sec` runs without `AttributeError`.
3. **FMP:** Validate key and optionally move to env; add clear error message or preflight for invalid/missing key.
4. **Config:** Document `sec_user_agent` and optional env override; keep or remove placeholder in `config.json` per project policy.
5. **Optional:** Add a small “smoke” script or section in README that checks Ollama and (if key present) FMP, so future QA can quickly confirm environment.

---

## 7. Commands Used During QA

```powershell
cd C:\Users\jxie0\investment-rag
uv sync
uv run python -m src.fetch_sec AAPL
uv run python -m src.fetch_transcripts AAPL
uv run python -m src.ingest
uv run python -m src.server
```

(On Windows PowerShell, use `;` instead of `&&` for chaining commands.)
