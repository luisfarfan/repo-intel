"""Discovery tests -- the corpus-selection layer where the central defect lived.

The production index contained 297 documents and ZERO from openspec/, while 2513
openspec markdown files existed on disk. The cause was `[docs] include`: none of its
patterns matched `openspec/specs/<cap>/spec.md`. These tests pin that fix, plus the
repo allowlist that keeps deprecated repos out of the corpus.

Everything runs against a synthetic workspace on tmp_path. No git, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_intel.core.config import AppConfig
from repo_intel.sdd.discovery import (
    classify_doc,
    discover_repositories,
    discover_sdd_documents,
    iter_sdd_files,
    match_path,
)


def write(path: Path, content: str = "# Title\n\nbody\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A miniature PROXIMA: one active repo, one deprecated repo."""
    api = tmp_path / "proxima-api"
    # README.md is a REPO_MARKER, which makes a depth-1 dir a repository candidate
    # even without .git (the real workspace has such folders).
    write(api / "README.md")
    write(api / "openspec" / "specs" / "saas-billing" / "spec.md", "# Billing spec\n")
    write(api / "openspec" / "specs" / "cms-websites" / "spec.md", "# CMS spec\n")
    write(api / "openspec" / "changes" / "add-plans" / "proposal.md", "# Proposal\n")
    write(api / "openspec" / "changes" / "add-plans" / "tasks.md", "# Tasks\n")
    # Archived changes: superseded history, 70% of the corpus, deliberately excluded.
    write(api / "openspec" / "changes" / "archive" / "old-change" / "proposal.md", "# Old\n")
    write(api / "docs" / "api-conventions.md", "# Conventions\n")
    write(api / "docs" / "architecture" / "inventory-stock.md", "# Inventory\n")
    # Source code must never enter an SDD-only corpus.
    write(api / "src" / "modules" / "notes.md", "# Source note\n")

    qa = tmp_path / "proxima-qa"
    write(qa / "README.md")
    write(qa / "openspec" / "specs" / "qa-flow" / "spec.md", "# QA spec\n")

    return tmp_path


def config_for(workspace: Path, repos: list[str] | None = None) -> AppConfig:
    cfg = AppConfig.default(workspace)
    if repos is not None:
        cfg.repos = repos
    return cfg


def rel_docs(workspace: Path, cfg: AppConfig) -> set[str]:
    repos = discover_repositories(workspace, cfg)
    docs = discover_sdd_documents(workspace, cfg, repos)
    return {doc.relative_path for doc in docs}


# --------------------------------------------------------------------------------------
# 1. The central bug: openspec must be discovered
# --------------------------------------------------------------------------------------


def test_openspec_spec_file_is_discovered(workspace: Path) -> None:
    """REGRESSION: openspec/specs/<cap>/spec.md matched no include pattern, so the
    single most valuable source in the ecosystem was 100% absent from the index."""
    found = rel_docs(workspace, config_for(workspace))
    assert "proxima-api/openspec/specs/saas-billing/spec.md" in found
    assert "proxima-api/openspec/specs/cms-websites/spec.md" in found


def test_openspec_active_change_documents_are_discovered(workspace: Path) -> None:
    found = rel_docs(workspace, config_for(workspace))
    assert "proxima-api/openspec/changes/add-plans/proposal.md" in found
    assert "proxima-api/openspec/changes/add-plans/tasks.md" in found


def test_archived_openspec_changes_are_excluded(workspace: Path) -> None:
    """Archive is superseded near-duplicate history; indexing it would dominate
    retrieval with stale content."""
    found = rel_docs(workspace, config_for(workspace))
    assert not any("changes/archive/" in path for path in found)


def test_openspec_include_pattern_matches_nested_spec_path() -> None:
    """Unit-level guard on the matcher itself, independent of the filesystem."""
    assert match_path("openspec/specs/saas-billing/spec.md", "openspec/**/*.md")


def test_legacy_include_patterns_would_not_have_matched_openspec() -> None:
    """Documents the actual root cause: the pre-fix pattern set was blind to openspec.

    If this ever starts failing, one of the legacy patterns grew openspec coverage and
    the explicit openspec/** entry may no longer be load-bearing.
    """
    legacy = [
        "AI_INDEX.md",
        "AGENT_START_HERE.md",
        "CURSOR_HANDOFF.md",
        "CLAUDE.md",
        "README.md",
        "PRODUCT.md",
        "DESIGN.md",
        "*ARCHITECTURE*.md",
        "*CONTRACT*.md",
        "docs/**/*.md",
        "docs_*/**/*.md",
    ]
    target = "openspec/specs/saas-billing/spec.md"
    assert not any(match_path(target, pattern) for pattern in legacy)


def test_openspec_specs_are_classified_as_spec_documents() -> None:
    doc_type, tags = classify_doc("openspec/specs/saas-billing/spec.md")
    assert doc_type == "sdd-spec"
    assert "spec" in tags


# --------------------------------------------------------------------------------------
# 2. Repo allowlist: deprecated repos stay out
# --------------------------------------------------------------------------------------


def test_deprecated_repo_is_excluded_by_allowlist(workspace: Path) -> None:
    cfg = config_for(workspace, repos=["proxima-api"])
    names = {repo.name for repo in discover_repositories(workspace, cfg)}
    assert names == {"proxima-api"}
    assert "proxima-qa" not in names


def test_documents_from_deprecated_repo_never_reach_the_corpus(workspace: Path) -> None:
    """The allowlist has to prune documents, not just the repository listing."""
    cfg = config_for(workspace, repos=["proxima-api"])
    found = rel_docs(workspace, cfg)
    assert not any(path.startswith("proxima-qa/") for path in found)
    assert "proxima-api/openspec/specs/saas-billing/spec.md" in found


def test_empty_allowlist_indexes_every_discovered_repo(workspace: Path) -> None:
    """Back-compat: `repos = []` must keep pre-allowlist workspaces working."""
    cfg = config_for(workspace, repos=[])
    names = {repo.name for repo in discover_repositories(workspace, cfg)}
    assert {"proxima-api", "proxima-qa"} <= names


def test_allowlist_entry_for_absent_repo_is_harmless(workspace: Path) -> None:
    cfg = config_for(workspace, repos=["proxima-api", "proxima-does-not-exist"])
    names = {repo.name for repo in discover_repositories(workspace, cfg)}
    assert names == {"proxima-api"}


def test_allowlist_tolerates_whitespace_and_blank_entries(workspace: Path) -> None:
    cfg = config_for(workspace, repos=["  proxima-api  ", "", "   "])
    names = {repo.name for repo in discover_repositories(workspace, cfg)}
    assert names == {"proxima-api"}


# --------------------------------------------------------------------------------------
# 3. Include/exclude shape regressions
# --------------------------------------------------------------------------------------


def test_flat_docs_file_is_discovered(workspace: Path) -> None:
    """REGRESSION: `docs/**/*.md` under fnmatch required an intermediate directory, so
    flat files like docs/api-conventions.md silently matched nothing."""
    found = rel_docs(workspace, config_for(workspace))
    assert "proxima-api/docs/api-conventions.md" in found


def test_nested_docs_file_is_discovered(workspace: Path) -> None:
    found = rel_docs(workspace, config_for(workspace))
    assert "proxima-api/docs/architecture/inventory-stock.md" in found


def test_source_tree_markdown_is_excluded(workspace: Path) -> None:
    found = rel_docs(workspace, config_for(workspace))
    assert not any("/src/" in path for path in found)


def test_discovery_yields_no_duplicates(workspace: Path) -> None:
    """Several include patterns overlap (docs/*.md and docs/**/*.md both hit flat
    files); the seen-set in iter_sdd_files must collapse them."""
    cfg = config_for(workspace)
    repos = discover_repositories(workspace, cfg)
    docs = discover_sdd_documents(workspace, cfg, repos)
    paths = [doc.relative_path for doc in docs]
    assert len(paths) == len(set(paths))


def test_iter_sdd_files_returns_only_files(workspace: Path) -> None:
    cfg = config_for(workspace)
    for path in iter_sdd_files(workspace / "proxima-api", cfg):
        assert path.is_file()


def test_document_ids_are_stable_across_runs(workspace: Path) -> None:
    """Chunk/doc ids are content-addressed; instability would force a full re-embed."""
    cfg = config_for(workspace, repos=["proxima-api"])
    repos = discover_repositories(workspace, cfg)
    first = {d.relative_path: d.id for d in discover_sdd_documents(workspace, cfg, repos)}
    second = {d.relative_path: d.id for d in discover_sdd_documents(workspace, cfg, repos)}
    assert first == second


# --------------------------------------------------------------------------------------
# 4. Git metadata reuse (the scan-time optimisation)
# --------------------------------------------------------------------------------------


def test_unchanged_document_reuses_cached_git_metadata(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git log -1 -- <path>` per document dominated scan time. When the content hash
    is unchanged the previous record's metadata must be reused instead."""
    from repo_intel.sdd import discovery as discovery_module

    cfg = config_for(workspace, repos=["proxima-api"])
    repos = discover_repositories(workspace, cfg)
    baseline = discover_sdd_documents(workspace, cfg, repos)
    reuse = {doc.id: doc for doc in baseline}

    calls: list[str] = []
    original = discovery_module.GitMetadataProvider.document_metadata

    def counting(self: object, path: Path):  # type: ignore[no-untyped-def]
        calls.append(str(path))
        return original(self, path)

    monkeypatch.setattr(discovery_module.GitMetadataProvider, "document_metadata", counting)

    discover_sdd_documents(workspace, cfg, repos, reuse=reuse)
    assert calls == []


def test_changed_document_recomputes_git_metadata(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repo_intel.sdd import discovery as discovery_module

    cfg = config_for(workspace, repos=["proxima-api"])
    repos = discover_repositories(workspace, cfg)
    baseline = discover_sdd_documents(workspace, cfg, repos)
    reuse = {doc.id: doc for doc in baseline}

    target = workspace / "proxima-api" / "openspec" / "specs" / "saas-billing" / "spec.md"
    target.write_text("# Billing spec\n\nrewritten body\n", encoding="utf-8")

    calls: list[str] = []
    original = discovery_module.GitMetadataProvider.document_metadata

    def counting(self: object, path: Path):  # type: ignore[no-untyped-def]
        calls.append(str(path))
        return original(self, path)

    monkeypatch.setattr(discovery_module.GitMetadataProvider, "document_metadata", counting)

    refreshed = discover_sdd_documents(workspace, cfg, repos, reuse=reuse)
    assert calls == [str(target)]

    new_hash = {d.relative_path: d.content_hash for d in refreshed}
    old_hash = {d.relative_path: d.content_hash for d in baseline}
    changed = "proxima-api/openspec/specs/saas-billing/spec.md"
    assert new_hash[changed] != old_hash[changed]
    # Everything else keeps its hash, which is what gates the incremental re-embed.
    del new_hash[changed], old_hash[changed]
    assert new_hash == old_hash
