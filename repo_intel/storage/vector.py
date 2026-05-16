from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from repo_intel.domain.models import SemanticChunkRecord


class ChromaKnowledgeIndex:
    def __init__(self, path: Path, collection_name: str) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(collection_name)

    def upsert_chunks(
        self,
        chunks: list[SemanticChunkRecord],
        embeddings: list[list[float]],
    ) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[chunk.id for chunk in chunks],
            embeddings=embeddings,
            documents=[chunk.text for chunk in chunks],
            metadatas=[sanitize_metadata(chunk.metadata) for chunk in chunks],
        )

    def query(self, embedding: list[float], n_results: int = 8) -> dict[str, Any]:
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    sanitized: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if isinstance(value, str | int | float | bool):
            sanitized[key] = value
        elif value is None:
            sanitized[key] = ""
        else:
            sanitized[key] = str(value)
    return sanitized

