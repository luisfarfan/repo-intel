"""The reindex must be incremental, and incremental must mean *cheap*.

These pin the fix for the defect that made auto-update impossible: `ingest` called
`scan(persist=True)` -> `upsert_scan`, which truncated `embeddings` and
`semantic_chunks` before the "skip already-embedded chunks" check ran. The skip therefore
always saw an empty table and every run re-embedded the whole corpus (~6.5 min), which
is far too expensive to hang off a git hook.

The contract now: an unchanged corpus re-embeds nothing, a one-document edit re-embeds
one document, and a deleted document is pruned from SQLite *and* handed back for pruning
from the vector store.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repo_intel.domain.models import (
    EmbeddingRecord,
    GitDocumentMetadata,
    RepositoryRecord,
    SddDocumentRecord,
    SemanticChunkRecord,
)
from repo_intel.storage.sqlite import KnowledgeStore

MODEL = "nomic-embed-text:latest"


@pytest.fixture()
def store(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.db")
    store.init_schema()
    return store


def repo(repo_id: str = "repo:1") -> RepositoryRecord:
    return RepositoryRecord(
        id=repo_id, name="proxima-api", path="/w/proxima-api", relative_path="proxima-api"
    )


def doc(doc_id: str, content_hash: str, repo_id: str = "repo:1") -> SddDocumentRecord:
    return SddDocumentRecord(
        id=doc_id,
        repository_id=repo_id,
        path=f"/w/proxima-api/docs/{doc_id}.md",
        relative_path=f"proxima-api/docs/{doc_id}.md",
        repo_relative_path=f"docs/{doc_id}.md",
        title=doc_id,
        doc_type="sdd-doc",
        content_hash=content_hash,
        size_bytes=10,
        git=GitDocumentMetadata(branch="main", last_modified_commit="abc123"),
    )


def chunk(chunk_id: str, document_id: str, repo_id: str = "repo:1") -> SemanticChunkRecord:
    return SemanticChunkRecord(
        id=chunk_id,
        document_id=document_id,
        repository_id=repo_id,
        text="text",
        content_hash="hash",
    )


def embedding(chunk_id: str) -> EmbeddingRecord:
    return EmbeddingRecord(
        id=f"embedding:{chunk_id}:{MODEL}",
        chunk_id=chunk_id,
        provider="ollama",
        model=MODEL,
        vector_store_id=chunk_id,
        indexed_at=datetime.now(timezone.utc),
    )


def seed(store: KnowledgeStore) -> None:
    """One repo, two documents, one embedded chunk each -- i.e. a COMPLETED ingest.

    `mark_documents_indexed` is part of that completion, not bookkeeping: the change gate
    reads `indexed_hash`, which only ingest may advance and only after the chunks are
    committed. Seeding with `sync_scan` alone would describe a workspace that was scanned
    but never indexed, and such documents are supposed to come back as changed.
    """
    store.sync_scan([repo()], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b")])
    store.replace_document_chunks(
        {"doc:a", "doc:b"},
        [chunk("chunk:a1", "doc:a"), chunk("chunk:b1", "doc:b")],
    )
    store.mark_documents_indexed({"doc:a": "hash-a", "doc:b": "hash-b"})
    for chunk_id in ("chunk:a1", "chunk:b1"):
        store.upsert_embedding(embedding(chunk_id))


def test_a_scanned_but_never_indexed_document_stays_changed(store):
    """The inverse of `seed`: scanning alone must never satisfy the gate, or a plain
    `scan` would convince the next ingest that unchunked documents are already done."""
    store.sync_scan([repo()], [doc("doc:a", "hash-a")])
    diff = store.sync_scan([repo()], [doc("doc:a", "hash-a")])

    assert diff.changed_document_ids == {"doc:a"}


# --- the regression that mattered -------------------------------------------------


def test_sync_scan_does_not_destroy_the_index(store):
    """The whole bug in one assertion: persisting a scan must not wipe embeddings."""
    seed(store)
    store.sync_scan([repo()], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b")])

    assert store.counts()["embeddings"] == 2
    assert store.counts()["chunks"] == 2
    assert store.embedded_chunk_ids(MODEL) == {"chunk:a1", "chunk:b1"}


def test_unchanged_corpus_reports_nothing_to_do(store):
    seed(store)
    diff = store.sync_scan([repo()], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b")])

    assert diff.changed_document_ids == set()
    assert diff.removed_document_ids == set()
    assert diff.is_empty


# --- change detection --------------------------------------------------------------


def test_only_the_edited_document_is_marked_changed(store):
    seed(store)
    diff = store.sync_scan([repo()], [doc("doc:a", "hash-a-EDITED"), doc("doc:b", "hash-b")])

    assert diff.changed_document_ids == {"doc:a"}
    assert diff.removed_document_ids == set()


def test_new_document_is_marked_changed(store):
    seed(store)
    diff = store.sync_scan(
        [repo()], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b"), doc("doc:c", "hash-c")]
    )

    assert diff.changed_document_ids == {"doc:c"}


def test_vanished_document_is_marked_removed_and_deleted(store):
    seed(store)
    diff = store.sync_scan([repo()], [doc("doc:a", "hash-a")])

    assert diff.removed_document_ids == {"doc:b"}
    assert {d.id for d in store.all_documents()} == {"doc:a"}


def test_force_marks_every_document_changed(store):
    """`--full` must rebuild everything without falling back to the destructive path."""
    seed(store)
    diff = store.sync_scan(
        [repo()], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b")], force=True
    )

    assert diff.changed_document_ids == {"doc:a", "doc:b"}


def test_repository_dropped_from_the_allowlist_is_pruned(store):
    seed(store)
    store.sync_scan([repo(), repo("repo:2")], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b")])
    assert len(store.all_repositories()) == 2

    store.sync_scan([repo()], [doc("doc:a", "hash-a"), doc("doc:b", "hash-b")])
    assert {r.id for r in store.all_repositories()} == {"repo:1"}


# --- chunk/embedding lifecycle -----------------------------------------------------


def test_rechunking_one_document_leaves_the_other_untouched(store):
    seed(store)
    store.replace_document_chunks({"doc:a"}, [chunk("chunk:a2", "doc:a")])

    # doc:b keeps its chunk AND its embedding; only doc:a's were rebuilt.
    assert {c.id for c in store.all_chunks()} == {"chunk:a2", "chunk:b1"}
    assert store.embedded_chunk_ids(MODEL) == {"chunk:b1"}


def test_replaced_chunks_report_orphans_for_vector_pruning(store):
    """Stale vectors must be returned, or retrieval keeps citing deleted text."""
    seed(store)
    orphans = store.replace_document_chunks({"doc:a"}, [chunk("chunk:a2", "doc:a")])

    assert orphans == {"chunk:a1"}


def test_surviving_chunk_ids_are_not_reported_as_orphans(store):
    """Chunk ids are content-addressed: an untouched section keeps its id and its vector."""
    seed(store)
    orphans = store.replace_document_chunks(
        {"doc:a"}, [chunk("chunk:a1", "doc:a"), chunk("chunk:a2", "doc:a")]
    )

    assert orphans == set()
    # chunk:a1's embedding must survive so it is never needlessly re-embedded.
    assert "chunk:a1" in store.embedded_chunk_ids(MODEL)


def test_removing_a_document_orphans_all_its_chunks(store):
    seed(store)
    store.sync_scan([repo()], [doc("doc:a", "hash-a")])
    orphans = store.replace_document_chunks({"doc:b"}, [])

    assert orphans == {"chunk:b1"}
    assert {c.id for c in store.all_chunks()} == {"chunk:a1"}
    assert store.embedded_chunk_ids(MODEL) == {"chunk:a1"}


def test_chunked_never_exceeds_the_bind_parameter_batch(store):
    """The unit under test is `chunked` itself.

    A corpus-sized delete alone proves nothing here: the bundled SQLite reports
    SQLITE_LIMIT_VARIABLE_NUMBER = 250000, so a few thousand unbatched ids would succeed
    comfortably and the assertion would pass with the batching removed. Assert the split
    directly instead.
    """
    from repo_intel.storage.sqlite import chunked

    batches = chunked([f"chunk:{i}" for i in range(5000)])

    assert all(len(batch) <= 400 for batch in batches)
    assert sum(len(batch) for batch in batches) == 5000
    assert [item for batch in batches for item in batch] == [f"chunk:{i}" for i in range(5000)]


def test_a_corpus_sized_delete_is_issued_in_multiple_statements(store):
    """And that the batching is actually wired into the delete path, not just available."""
    from sqlalchemy import event

    store.sync_scan([repo()], [doc(f"doc:{i}", f"hash-{i}") for i in range(1200)])
    chunks = [chunk(f"chunk:{i}", f"doc:{i}") for i in range(1200)]
    store.replace_document_chunks({f"doc:{i}" for i in range(1200)}, chunks)
    assert store.counts()["chunks"] == 1200

    widest = 0

    def record(conn, cursor, statement, parameters, context, executemany):
        nonlocal widest
        widest = max(widest, len(parameters or ()))

    event.listen(store.engine, "before_cursor_execute", record)
    try:
        orphans = store.replace_document_chunks({f"doc:{i}" for i in range(1200)}, [])
    finally:
        event.remove(store.engine, "before_cursor_execute", record)

    assert len(orphans) == 1200
    assert store.counts()["chunks"] == 0
    assert widest <= 400, f"a single statement bound {widest} parameters; batching is bypassed"
