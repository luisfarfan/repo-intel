"""The index must never develop a silent, permanent hole.

Every test here pins a failure mode that was *invisible in the happy-path counters*: the
run reports "ok, 0 changed", `status` looks consistent, and the corpus is quietly missing
text that `ask` will then answer around. That combination -- confident answers over a
corpus with unreportable gaps -- is what destroys trust in a knowledge base, and it is
what killed the previous incarnation of this tool.

The shared theme of the fixes: a document's "indexed" state may only advance when the
work actually landed, and any deferred cleanup must be durable rather than held in a
local variable that a transient exception discards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_intel.application.use_cases import SddKnowledgeService
from repo_intel.core.config import AppConfig, render_config


FILLER = (
    "The requirement is described here in enough prose to clear the minimum chunk size, "
    "because sections shorter than MIN_CHUNK_CHARS are dropped when a document has more "
    "than one section. Real openspec requirements carry scenarios, rationale and "
    "acceptance criteria, so they comfortably exceed that floor. "
)


def spec_doc(title: str, marker: str) -> str:
    return f"# {title}\n\n## Requirement\n\n{marker}\n\n{FILLER}{FILLER}\n"


class FakeEmbedder:
    embedded: list[str] = []
    fail_next: bool = False

    def __init__(self, **kwargs: object) -> None: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if FakeEmbedder.fail_next:
            raise RuntimeError("ollama is restarting")
        FakeEmbedder.embedded.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeVectorIndex:
    deleted: list[str] = []
    fail_delete: bool = False

    def __init__(self, *args: object, **kwargs: object) -> None: ...

    def upsert_chunks(self, chunks: list, embeddings: list) -> None: ...

    def delete_chunks(self, ids: list[str]) -> None:
        if FakeVectorIndex.fail_delete:
            raise RuntimeError("chroma is locked")
        FakeVectorIndex.deleted.extend(ids)


@pytest.fixture(autouse=True)
def stub_network(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeEmbedder.embedded.clear()
    FakeEmbedder.fail_next = False
    FakeVectorIndex.deleted.clear()
    FakeVectorIndex.fail_delete = False
    monkeypatch.setattr(
        "repo_intel.enrichers.ollama_embeddings.OllamaEmbeddingClient", FakeEmbedder
    )
    monkeypatch.setattr("repo_intel.storage.vector.ChromaKnowledgeIndex", FakeVectorIndex)
    monkeypatch.setattr("repo_intel.core.config.load_global_config_data", lambda: {})


@pytest.fixture
def service(tmp_path: Path) -> SddKnowledgeService:
    repo = tmp_path / "proxima-api"
    (repo / "openspec" / "specs" / "billing").mkdir(parents=True)
    (repo / "README.md").write_text("# API\n", encoding="utf-8")
    (repo / "openspec" / "specs" / "billing" / "spec.md").write_text(
        spec_doc("Billing", "Plans are seeded on startup."), encoding="utf-8"
    )

    cfg_dir = tmp_path / ".repo-intel"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(project_name="proxima")
    cfg.repos = ["proxima-api"]
    (cfg_dir / "config.toml").write_text(render_config(cfg), encoding="utf-8")

    svc = SddKnowledgeService(tmp_path)
    svc.init()
    return svc


def new_spec(service: SddKnowledgeService, name: str, marker: str) -> Path:
    path = service.workspace / "proxima-api" / "openspec" / "specs" / name
    path.mkdir(parents=True, exist_ok=True)
    target = path / "spec.md"
    target.write_text(spec_doc(name, marker), encoding="utf-8")
    return target


def test_scan_before_ingest_does_not_hide_a_new_document(
    service: SddKnowledgeService,
) -> None:
    """`scan` is documented as discovery and reads as harmless, so it is the first thing
    anyone runs to check whether a file was picked up. It used to poison the very next
    ingest: sync_scan advanced content_hash, ingest then computed an empty diff, and the
    document stayed in the corpus with zero chunks -- invisible to retrieval, reported as
    'Index already up to date', and never self-repairing on any later run."""
    service.ingest()
    new_spec(service, "inventory", "KRELLNIX_STALL alerts drain the audit queue.")

    service.scan(persist=True)
    run = service.ingest()

    assert run.documents_changed == 1
    assert any("KRELLNIX_STALL" in text for text in FakeEmbedder.embedded)


def test_scan_before_ingest_does_not_hide_an_edit(service: SddKnowledgeService) -> None:
    """The same poisoning, but worse: the document keeps its OLD chunks, so retrieval
    confidently serves text that no longer exists in the file."""
    service.ingest()
    target = service.workspace / "proxima-api" / "openspec" / "specs" / "billing" / "spec.md"
    target.write_text(spec_doc("Billing", "Plans are now seeded by a migration."), "utf-8")
    FakeEmbedder.embedded.clear()

    service.scan(persist=True)
    run = service.ingest()

    assert run.documents_changed == 1
    assert any("seeded by a migration" in text for text in FakeEmbedder.embedded)


def test_repeated_scans_never_advance_the_indexed_state(
    service: SddKnowledgeService,
) -> None:
    """Discovery is idempotent with respect to indexing, however often it runs."""
    service.ingest()
    new_spec(service, "shipping", "Carriers are resolved per destination zone.")

    for _ in range(3):
        service.scan(persist=True)
    run = service.ingest()

    assert run.documents_changed == 1
    assert any("Carriers are resolved" in text for text in FakeEmbedder.embedded)


def test_failed_embedding_batch_is_retried_on_the_next_run(
    service: SddKnowledgeService,
) -> None:
    """Ollama is a local process on a laptop that sleeps. A hook or hourly sweep firing
    while it restarts must cost a retry, not a permanent hole: the document is unchanged
    on every later scan, so a run-scoped retry set could never reach it again."""
    FakeEmbedder.fail_next = True
    first = service.ingest()
    assert first.errors, "a failed batch must be reported, not swallowed"
    assert first.embeddings_created == 0

    FakeEmbedder.fail_next = False
    second = service.ingest()

    assert second.embeddings_created > 0
    assert not second.errors
    assert any("Plans are seeded on startup" in text for text in FakeEmbedder.embedded)


def test_a_failed_batch_does_not_starve_the_documents_around_it(
    service: SddKnowledgeService,
) -> None:
    """Recovery must be corpus-wide, not limited to whatever the failing run touched."""
    service.ingest()
    new_spec(service, "returns", "Refunds settle against the original tender.")
    FakeEmbedder.fail_next = True
    service.ingest()
    FakeEmbedder.embedded.clear()

    FakeEmbedder.fail_next = False
    service.ingest()

    assert any("Refunds settle" in text for text in FakeEmbedder.embedded)


def test_failed_vector_prune_is_retried_instead_of_losing_the_ids(
    service: SddKnowledgeService,
) -> None:
    """Once the chunk rows are deleted, SQLite can no longer recompute the orphan ids. If
    the prune failure discards them, the vectors of deleted text live in Chroma forever
    and `ask` keeps citing a document that exists nowhere -- while every SQLite-derived
    count looks perfectly consistent."""
    service.ingest()
    target = new_spec(service, "legacy", "This capability was withdrawn.")
    service.ingest()
    target.unlink()

    FakeVectorIndex.fail_delete = True
    failed = service.ingest()
    assert failed.errors, "a failed prune must be reported"
    assert not FakeVectorIndex.deleted

    FakeVectorIndex.fail_delete = False
    recovered = service.ingest()

    assert FakeVectorIndex.deleted, "the queued orphans must be pruned on a later run"
    assert not recovered.errors
    assert service.store.pending_vector_deletions() == []


def test_successful_prune_drains_the_queue(service: SddKnowledgeService) -> None:
    """The queue must not accumulate, or every run would re-delete the whole history."""
    service.ingest()
    target = new_spec(service, "temporary", "Short lived capability.")
    service.ingest()
    target.unlink()

    service.ingest()

    assert FakeVectorIndex.deleted
    assert service.store.pending_vector_deletions() == []


# --- documents must not vanish into the chunk-size floor ---------------------------


def test_a_document_of_only_short_sections_is_still_indexed(
    service: SddKnowledgeService,
) -> None:
    """MIN_CHUNK_CHARS drops sections under 200 chars, which is right for boilerplate but
    wrong when it drops every section: the document then sits in the corpus with zero
    chunks -- counted by `status`, unreachable by retrieval, reported by nothing. Terse
    openspec specs hit this precisely because they are well written."""
    path = service.workspace / "proxima-api" / "openspec" / "specs" / "terse"
    path.mkdir(parents=True)
    (path / "spec.md").write_text(
        "# Terse\n\n## Requirement: Zone\n\nThe system SHALL resolve carriers per zone.\n\n"
        "## Requirement: Tender\n\nRefunds SHALL settle against the original tender.\n",
        encoding="utf-8",
    )

    service.ingest()

    assert any("SHALL resolve carriers per zone" in text for text in FakeEmbedder.embedded)


def test_rich_documents_still_drop_their_boilerplate_sections(
    service: SddKnowledgeService,
) -> None:
    """The fallback must not become a licence to index every stub heading: it applies
    only when a document would otherwise produce nothing at all."""
    path = service.workspace / "proxima-api" / "openspec" / "specs" / "mixed"
    path.mkdir(parents=True)
    (path / "spec.md").write_text(
        f"# Mixed\n\n## Status\n\ndraft\n\n## Requirement\n\nSubstantial.\n\n{FILLER}{FILLER}\n",
        encoding="utf-8",
    )

    service.ingest()

    assert not any(text.strip().endswith("draft") for text in FakeEmbedder.embedded)
