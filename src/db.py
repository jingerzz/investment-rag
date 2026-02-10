"""ChromaDB setup and query helpers."""

from pathlib import Path
import chromadb
from .embeddings import OllamaEmbedder

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "chromadb_data"

COLLECTIONS = ["sec_filings", "transcripts", "market_data"]

_client = None
_embedder = None


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(DB_PATH))
    return _client


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = OllamaEmbedder()
    return _embedder


def get_collection(name: str):
    if name not in COLLECTIONS:
        raise ValueError(f"Unknown collection: {name}. Must be one of {COLLECTIONS}")
    return _get_client().get_or_create_collection(
        name=name,
        embedding_function=_get_embedder(),
    )


def add_documents(collection_name: str, ids: list[str], documents: list[str], metadatas: list[dict]):
    """Add documents to a collection."""
    col = get_collection(collection_name)
    # ChromaDB has a batch size limit; chunk into batches of 100
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        col.add(
            ids=ids[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )


def search(collection_name: str, query: str, n_results: int = 10, where: dict | None = None):
    """Search a collection. Returns list of {id, document, metadata, distance}."""
    col = get_collection(collection_name)
    if col.count() == 0:
        return []
    kwargs = {"query_texts": [query], "n_results": min(n_results, col.count())}
    if where:
        kwargs["where"] = where
    results = col.query(**kwargs)
    items = []
    for i in range(len(results["ids"][0])):
        items.append({
            "id": results["ids"][0][i],
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return items


def list_documents(collection_name: str | None = None):
    """List unique source files in one or all collections."""
    names = [collection_name] if collection_name else COLLECTIONS
    result = {}
    for name in names:
        col = get_collection(name)
        count = col.count()
        if count == 0:
            result[name] = []
            continue
        all_meta = col.get(include=["metadatas"])
        sources = {}
        for m in all_meta["metadatas"]:
            sf = m.get("source_file", "unknown")
            if sf not in sources:
                sources[sf] = {"source_file": sf, "ticker": m.get("ticker", ""), "chunks": 0}
            sources[sf]["chunks"] += 1
        result[name] = list(sources.values())
    return result


def remove_by_source(source_file: str):
    """Remove all chunks matching a source_file across all collections."""
    removed = 0
    for name in COLLECTIONS:
        col = get_collection(name)
        if col.count() == 0:
            continue
        all_data = col.get(where={"source_file": source_file}, include=[])
        if all_data["ids"]:
            col.delete(ids=all_data["ids"])
            removed += len(all_data["ids"])
    return removed
