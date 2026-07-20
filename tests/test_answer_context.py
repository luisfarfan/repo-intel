"""Overview questions must still consult the index.

"What is proxima-runtime?" is the most natural onboarding question there is, and it was
the one question that never reached retrieval: the deterministic block (project brief +
overview chunks) was given the entire context budget, so the semantic results were
appended and then truncated away by the final slice. The visible symptom was `ask`
replying "the indexed documents do not contain enough information" about a repository
whose README was sitting in the index, while a plain `query` with the same terms returned
it as the top hit.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from repo_intel.application.answer_engine import (
    QuestionIntent,
    build_answer_context,
    build_retrieval_plan,
    load_project_brief_context,
)


def artifact_chunk(chunk_id: str, repo: str, path: str, text: str) -> dict:
    return {
        "id": chunk_id,
        "text": text,
        "metadata": {
            "repo": repo,
            "path": path,
            "section": "Overview",
            "doc_type": "readme",
            "last_modified_commit": "abc",
        },
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    artifacts = tmp_path / ".repo-intel" / "artifacts"
    artifacts.mkdir(parents=True)
    overview = [
        artifact_chunk(f"chunk:overview-{i}", "proxima-admin", "PRODUCT.md", "Admin product.")
        for i in range(12)
    ]
    (artifacts / "chunks.json").write_text(json.dumps(overview), encoding="utf-8")
    return tmp_path


def semantic_candidates() -> list[dict]:
    return [
        {
            "id": "chunk:runtime-readme",
            "text": "proxima-runtime handles storefront routing and durability.",
            "metadata": {
                "repo": "proxima-runtime",
                "path": "README.md",
                "section": "Overview",
                "doc_type": "readme",
            },
            "distance": 0.45,
        }
    ]


def overview_plan(limit: int = 6):
    return build_retrieval_plan(
        QuestionIntent(name="overview", confidence=0.82, signals=["what-is"]),
        requested_limit=limit,
        default_limit=limit,
    )


def test_semantic_results_survive_the_deterministic_block(workspace: Path) -> None:
    """The regression in one assertion: the retrieved document must be in the context."""
    results = build_answer_context(
        workspace, "what is proxima-runtime?", semantic_candidates(), overview_plan()
    )

    assert any(item["id"] == "chunk:runtime-readme" for item in results)


def test_deterministic_block_cannot_consume_the_whole_budget(workspace: Path) -> None:
    plan = overview_plan(limit=6)
    results = build_answer_context(
        workspace, "what is proxima-runtime?", semantic_candidates(), plan
    )

    deterministic = [item for item in results if item["metadata"]["repo"] != "proxima-runtime"]
    assert len(results) <= plan.final_limit
    assert len(deterministic) < plan.final_limit


def test_smallest_budget_still_leaves_room_for_retrieval(workspace: Path) -> None:
    """final_limit floors at 3; even there the index must get a seat."""
    results = build_answer_context(
        workspace, "what is proxima-runtime?", semantic_candidates(), overview_plan(limit=3)
    )

    assert any(item["id"] == "chunk:runtime-readme" for item in results)


# --- the stale brief ---------------------------------------------------------------


def write_brief(workspace: Path, text: str = "# Brief\n\nOld ecosystem.\n") -> Path:
    briefs = workspace / ".repo-intel" / "briefs"
    briefs.mkdir(parents=True, exist_ok=True)
    path = briefs / "project-brief.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_brief_newer_than_the_index_is_used(workspace: Path) -> None:
    brief = write_brief(workspace)
    os.utime(brief, (time.time() + 10, time.time() + 10))

    assert load_project_brief_context(workspace) is not None


def test_a_brief_older_than_the_index_is_dropped(workspace: Path) -> None:
    """Nothing regenerates the brief during ingest, so a months-old file describing a
    dead ecosystem was being injected as source #1 with a perfect 0.0000 distance --
    outranking every real document while looking like the most authoritative citation in
    the answer."""
    brief = write_brief(workspace)
    os.utime(brief, (time.time() - 3600, time.time() - 3600))

    assert load_project_brief_context(workspace) is None


def test_a_stale_brief_does_not_reach_the_answer_context(workspace: Path) -> None:
    brief = write_brief(workspace)
    os.utime(brief, (time.time() - 3600, time.time() - 3600))

    results = build_answer_context(
        workspace, "what is proxima-runtime?", semantic_candidates(), overview_plan()
    )

    assert all(item["id"] != "brief:project" for item in results)
