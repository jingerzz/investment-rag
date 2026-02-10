"""Ollama embedding wrapper for ChromaDB."""

import httpx
from chromadb import EmbeddingFunction, Documents, Embeddings


class OllamaEmbedder(EmbeddingFunction):
    def __init__(self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def __call__(self, input: Documents) -> Embeddings:
        resp = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": input},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]
