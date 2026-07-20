"""End-to-end incremental ingest, with the network stubbed out.

The existing incremental tests exercise the storage primitives (`sync_scan`,
`replace_document_chunks`, `embedded_chunk_ids`) in isolation. They all passed while
the feature was still completely broken in production, because the defect was in the
WIRING: `ingest()` called `scan(persist=True)` -> `upsert_scan()`, which truncated the
chunk and embedding tables *before* `embedded_chunk_ids()` was consulted. The skip set
was therefore always empty and all 7848 chunks were re-embedded on every run.

These tests drive the real `ingest()` against a real SQLite store on tmp_path, with
only the Ollama embedder and the Chroma index replaced by recording fakes. That is the
level at which the defect was observable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_intel.application.use_cases import SddKnowledgeService
from repo_intel.core.config import AppConfig, render_config


class FakeEmbedder:
    """Records every text actually sent for embedding."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        FakeEmbedder.calls.append(self)

    calls: list["FakeEmbedder"] = []
    embedded: list[str] = []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        FakeEmbedder.embedded.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeVectorIndex:
    upserted: list[str] = []
    deleted: list[str] = []

    def __init__(self, *args: object, **kwargs: object) -> None: ...

    def upsert_chunks(self, chunks: list, embeddings: list) -> None:
        FakeVectorIndex.upserted.extend(chunk.id for chunk in chunks)

    def delete_chunks(self, ids: list[str]) -> None:
        FakeVectorIndex.deleted.extend(ids)


@pytest.fixture(autouse=True)
def stub_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing here may touch Ollama or cliproxy."""
    FakeEmbedder.calls.clear()
    FakeEmbedder.embedded.clear()
    FakeVectorIndex.upserted.clear()
    FakeVectorIndex.deleted.clear()
    monkeypatch.setattr(
        "repo_intel.enrichers.ollama_embeddings.OllamaEmbeddingClient", FakeEmbedder
    )
    monkeypatch.setattr("repo_intel.storage.vector.ChromaKnowledgeIndex", FakeVectorIndex)
    monkeypatch.setattr("repo_intel.core.config.load_global_config_data", lambda: {})


FILLER = (
    "The requirement is described here in enough prose to clear the minimum chunk size, "
    "because sections shorter than MIN_CHUNK_CHARS are dropped when a document has more "
    "than one section. Real openspec requirements carry scenarios, rationale and "
    "acceptance criteria, so they comfortably exceed that floor. "
)


def spec_doc(title: str, marker: str) -> str:
    """A markdown spec whose single requirement section survives chunking."""
    return f"# {title}\n\n## Requirement\n\n{marker}\n\n{FILLER}{FILLER}\n"


@pytest.fixture
def service(tmp_path: Path) -> SddKnowledgeService:
    """A workspace with one active repo holding two openspec documents."""
    repo = tmp_path / "proxima-api"
    (repo / "openspec" / "specs" / "billing").mkdir(parents=True)
    (repo / "README.md").write_text("# API\n", encoding="utf-8")
    (repo / "openspec" / "specs" / "billing" / "spec.md").write_text(
        spec_doc("Billing", "Plans are seeded on startup."), encoding="utf-8"
    )
    (repo / "openspec" / "specs" / "cms").mkdir(parents=True)
    (repo / "openspec" / "specs" / "cms" / "spec.md").write_text(
        spec_doc("CMS", "Websites declare section types."), encoding="utf-8"
    )

    cfg_dir = tmp_path / ".repo-intel"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(project_name="proxima")
    cfg.repos = ["proxima-api"]
    (cfg_dir / "config.toml").write_text(render_config(cfg), encoding="utf-8")

    svc = SddKnowledgeService(tmp_path)
    svc.init()
    return svc


def test_first_ingest_embeds_the_openspec_corpus(service: SddKnowledgeService) -> None:
    run = service.ingest()
    assert run.docs_count >= 3  # 2 specs + README
    assert run.embeddings_created > 0
    assert FakeEmbedder.embedded, "first run must actually embed something"
    # The central bug: openspec content must reach the embedder.
    assert any("Plans are seeded on startup" in text for text in FakeEmbedder.embedded)


def test_unchanged_corpus_is_not_reprocessed(service: SddKnowledgeService) -> None:
    """REGRESSION (root defect): the second run used to re-embed the entire corpus
    because upsert_scan truncated the embedding table before the skip was computed."""
    first = service.ingest()
    assert first.embeddings_created > 0

    FakeEmbedder.embedded.clear()
    second = service.ingest()

    assert second.embeddings_created == 0
    assert FakeEmbedder.embedded == []
    assert second.documents_changed == 0
    assert second.chunks_created == 0


def test_unchanged_run_still_reports_full_corpus_coverage(
    service: SddKnowledgeService,
) -> None:
    """A no-op incremental run must report coverage (all chunks indexed), not zero --
    otherwise `status` looks like the index was wiped."""
    first = service.ingest()
    second = service.ingest()
    assert second.chunks_count == first.chunks_count
    assert second.embeddings_count == first.embeddings_count
    assert second.embeddings_count > 0


def test_ingest_does_not_destroy_existing_embeddings(service: SddKnowledgeService) -> None:
    """REGRESSION: measured in production as BEFORE embeddings=7848 -> AFTER=0."""
    service.ingest()
    before = service.store.counts()["embeddings"]
    assert before > 0

    service.ingest()
    assert service.store.counts()["embeddings"] == before


def test_edited_document_is_reembedded(service: SddKnowledgeService) -> None:
    service.ingest()
    FakeEmbedder.embedded.clear()

    target = service.workspace / "proxima-api" / "openspec" / "specs" / "billing" / "spec.md"
    target.write_text(
        spec_doc("Billing", "Plans are seeded from a canonical catalog."), encoding="utf-8"
    )

    run = service.ingest()
    assert run.documents_changed == 1
    assert run.embeddings_created > 0
    assert any("canonical catalog" in text for text in FakeEmbedder.embedded)
    # The untouched sibling spec must NOT be re-embedded.
    assert not any("section types" in text for text in FakeEmbedder.embedded)


def test_new_document_is_embedded_without_touching_the_rest(
    service: SddKnowledgeService,
) -> None:
    service.ingest()
    FakeEmbedder.embedded.clear()

    new_spec = service.workspace / "proxima-api" / "openspec" / "specs" / "orders"
    new_spec.mkdir(parents=True)
    (new_spec / "spec.md").write_text(
        spec_doc("Orders", "Orders capture a payment intent."), encoding="utf-8"
    )

    run = service.ingest()
    assert run.documents_changed == 1
    assert any("payment intent" in text for text in FakeEmbedder.embedded)
    assert not any("section types" in text for text in FakeEmbedder.embedded)


def test_deleted_document_prunes_its_vectors(service: SddKnowledgeService) -> None:
    """Otherwise retrieval keeps citing text that no longer exists on disk."""
    service.ingest()
    FakeVectorIndex.deleted.clear()

    target = service.workspace / "proxima-api" / "openspec" / "specs" / "cms" / "spec.md"
    target.unlink()

    run = service.ingest()
    assert run.documents_removed == 1
    assert FakeVectorIndex.deleted, "orphaned vectors must be deleted from Chroma"


def test_full_flag_rescans_and_rechunks_everything(service: SddKnowledgeService) -> None:
    """What --full demonstrably DOES do today: force every document through scan and
    chunking again. See the xfail below for what it does not do."""
    service.ingest()
    run = service.ingest(full=True)
    assert run.mode == "full"
    assert run.documents_changed == run.docs_count
    assert run.chunks_created > 0


def test_full_flag_forces_reembed_of_everything(service: SddKnowledgeService) -> None:
    """--full is the documented recovery path for a corrupted vector store, so it must
    actually re-embed. It previously did not: content-addressed chunk ids meant a full
    rescan recreated identical ids, no embedding row was ever dropped, and the pending
    set came out empty -- so --full cost a full rescan and bought nothing."""
    first = service.ingest()
    FakeEmbedder.embedded.clear()

    run = service.ingest(full=True)
    assert run.embeddings_created == first.embeddings_created
    assert FakeEmbedder.embedded


def test_changing_the_embedding_model_forces_reembed(service: SddKnowledgeService) -> None:
    """Embedding rows are scoped by model: switching models must invalidate, never
    silently reuse vectors from a different model's space.

    This works because the pending set is derived from the STORE (which knows which
    model each embedding row belongs to) rather than filtered from the current run's
    chunk list. When it was run-scoped, no file had changed, so no chunk was a candidate
    and the model-scoping was unreachable: queries got embedded with the new model and
    matched against the old model's vectors, degrading retrieval silently."""
    service.ingest()
    FakeEmbedder.embedded.clear()

    service.config.embeddings.model = "some-other-embed-model"
    run = service.ingest()
    assert run.embeddings_created > 0
    assert FakeEmbedder.embedded


def test_short_sections_are_dropped_from_multi_section_documents(
    service: SddKnowledgeService,
) -> None:
    """Characterisation of MIN_CHUNK_CHARS (200), which cost real coverage while writing
    these tests: in a multi-section document, any section under 200 characters is
    silently discarded. Terse openspec requirements ('The system SHALL ...') fall under
    that floor and never become retrievable. Not filed as a defect -- the threshold is
    deliberate -- but it must be a known, asserted property."""
    repo = service.workspace / "proxima-api"
    terse = repo / "openspec" / "specs" / "terse"
    terse.mkdir(parents=True)
    (terse / "spec.md").write_text(
        "# Terse\n\n## Requirement\n\nThe system SHALL emit a receipt.\n\n"
        f"## Long\n\n{FILLER}{FILLER}\n",
        encoding="utf-8",
    )

    service.ingest()
    assert not any("SHALL emit a receipt" in text for text in FakeEmbedder.embedded)
    assert any(FILLER.strip() in text for text in FakeEmbedder.embedded)


def test_plain_scan_does_not_wipe_the_index(service: SddKnowledgeService) -> None:
    """REGRESSION: scan(persist=True) went through upsert_scan, so merely running
    `repo-intel scan` discarded the whole vector index."""
    service.ingest()
    before = service.store.counts()

    service.scan(persist=True)
    after = service.store.counts()
    assert after["embeddings"] == before["embeddings"]
    assert after["chunks"] == before["chunks"]


def test_deprecated_repo_contributes_nothing_to_the_index(
    service: SddKnowledgeService,
) -> None:
    """The allowlist must hold at ingest time, not just in `discover_repositories`."""
    qa = service.workspace / "proxima-qa"
    (qa / "openspec" / "specs" / "qa").mkdir(parents=True)
    (qa / "README.md").write_text("# QA\n", encoding="utf-8")
    (qa / "openspec" / "specs" / "qa" / "spec.md").write_text(
        spec_doc("QA", "Deprecated repo content."), encoding="utf-8"
    )

    service.ingest()
    assert not any("Deprecated repo content" in text for text in FakeEmbedder.embedded)
