"""Ingest must be resumable and incremental.

Before `embedded_chunk_ids` existed, every `ingest` re-embedded the entire corpus
(7848 chunks, ~90 min on local Ollama). An interruption partway through therefore
threw away the whole pass, and a re-run after archiving a single OpenSpec change
cost a full re-embed. These tests pin the skip behaviour that fixes both.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repo_intel.domain.models import EmbeddingRecord
from repo_intel.storage.sqlite import KnowledgeStore


MODEL = "nomic-embed-text:latest"


@pytest.fixture()
def store(tmp_path):
    return KnowledgeStore(tmp_path / "knowledge.db")


def embedding(chunk_id: str, model: str = MODEL) -> EmbeddingRecord:
    return EmbeddingRecord(
        id=f"embedding:{chunk_id}:{model}",
        chunk_id=chunk_id,
        provider="ollama",
        model=model,
        vector_store_id=chunk_id,
        indexed_at=datetime.now(timezone.utc),
    )


def test_empty_store_reports_nothing_embedded(store):
    assert store.embedded_chunk_ids(MODEL) == set()


def test_returns_chunk_ids_embedded_with_that_model(store):
    store.upsert_embedding(embedding("chunk:a"))
    store.upsert_embedding(embedding("chunk:b"))

    assert store.embedded_chunk_ids(MODEL) == {"chunk:a", "chunk:b"}


def test_scoped_by_model_so_switching_model_forces_reembed(store):
    """Changing embeddings.model must invalidate, not silently reuse, old vectors."""
    store.upsert_embedding(embedding("chunk:a", model="nomic-embed-text:latest"))

    assert store.embedded_chunk_ids("mxbai-embed-large:latest") == set()
    assert store.embedded_chunk_ids("nomic-embed-text:latest") == {"chunk:a"}


def test_upsert_is_idempotent(store):
    store.upsert_embedding(embedding("chunk:a"))
    store.upsert_embedding(embedding("chunk:a"))

    assert store.embedded_chunk_ids(MODEL) == {"chunk:a"}


def test_pending_set_is_the_difference(store):
    """The exact filter ingest applies: only unseen chunk ids get embedded."""
    store.upsert_embedding(embedding("chunk:done"))
    corpus = ["chunk:done", "chunk:new-1", "chunk:new-2"]

    already = store.embedded_chunk_ids(MODEL)
    pending = [cid for cid in corpus if cid not in already]

    assert pending == ["chunk:new-1", "chunk:new-2"]


def test_fully_indexed_corpus_leaves_nothing_pending(store):
    """A no-op re-run must embed zero chunks -- the incremental win."""
    corpus = ["chunk:a", "chunk:b", "chunk:c"]
    for chunk_id in corpus:
        store.upsert_embedding(embedding(chunk_id))

    already = store.embedded_chunk_ids(MODEL)

    assert [cid for cid in corpus if cid not in already] == []
