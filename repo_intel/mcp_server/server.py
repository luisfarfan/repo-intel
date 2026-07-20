"""FastMCP server exposing the repo-intel knowledge base as MCP tools.

Design notes
------------
* Read-only. The ingest pipeline is owned by the CLI (`repo-intel ingest`);
  this server only reads what is already in SQLite + Chroma. It never writes
  to the knowledge store, so it is safe to run concurrently with an ingest.
* stdio transport: MCP frames travel on stdout, so nothing here may print to
  stdout. All diagnostics go to stderr.
* The workspace is resolved once, lazily, on the first tool call — importing
  this module must stay cheap and must not fail if the store is missing, or
  the MCP client sees a dead server instead of a readable error.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from repo_intel.core.env import load_project_env
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


DEFAULT_SEARCH_K = 8
MAX_SEARCH_K = 40
DEFAULT_MAX_CHARS = 1200

mcp = FastMCP(
    name="repo-intel",
    instructions=(
        "Semantic search over the Proxima engineering knowledge base: OpenSpec "
        "specs and changes, ADRs, architecture docs and agent guides across the "
        "active repos (proxima-api, admin, builder, storefront-v2, "
        "intelligence-v2, pos, infra, runtime, hub, engineering).\n\n"
        "Use `search_docs` to retrieve raw documentation chunks with their file "
        "paths — prefer it when you want to read the source of truth yourself. "
        "Use `ask_docs` for a synthesized, cited answer to a natural-language "
        "question. Use `knowledge_status` to check how fresh the index is.\n\n"
        "This is documentation, not code: for 'what calls X' use graphify."
    ),
)


def _log(message: str) -> None:
    """Diagnostics must never touch stdout under the stdio transport."""
    print(f"[repo-intel-mcp] {message}", file=sys.stderr, flush=True)


def _workspace_target() -> str:
    """Workspace to serve: explicit env, then CLI arg, then cwd."""
    from_env = os.environ.get("REPO_INTEL_WORKSPACE")
    if from_env:
        return from_env
    argv = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if argv:
        return argv[0]
    return str(Path.cwd())


@lru_cache(maxsize=4)
def _service(target: str):
    """Build (and memoize) the knowledge service for a workspace.

    Imported lazily: SddKnowledgeService pulls in chromadb/sqlalchemy, which is
    seconds of import time we do not want to pay on a server that may only ever
    be asked for `knowledge_status`.
    """
    from repo_intel.application.use_cases import SddKnowledgeService

    try:
        path = resolve_workspace_path(target)
    except WorkspaceResolutionError as exc:
        raise ValueError(str(exc)) from exc
    return SddKnowledgeService(path)


def _current_service():
    return _service(_workspace_target())


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    text = (text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + " […]", True


def _shape_hit(row: dict[str, Any], max_chars: int) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    distance = row.get("distance")
    text, truncated = _clip(str(row.get("text", "")), max_chars)
    return {
        "repo": metadata.get("repo", ""),
        "path": metadata.get("path", ""),
        "section": metadata.get("section", ""),
        "doc_type": metadata.get("doc_type", ""),
        # Chroma returns a cosine *distance*: lower is closer. `score` is the
        # inverted convenience value so callers can sort descending as usual.
        "distance": distance,
        "score": round(1.0 - distance, 4) if isinstance(distance, (int, float)) else None,
        "text": text,
        "truncated": truncated,
        "chunk_id": row.get("id", ""),
    }


@mcp.tool
def search_docs(
    query: str,
    k: int = DEFAULT_SEARCH_K,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Semantic search over indexed SDD/OpenSpec documentation.

    Returns the matching documentation chunks with their repo, file path and
    similarity score, so you can open the cited files yourself. No LLM call is
    made — this is pure retrieval and is fast and free.

    Args:
        query: Natural-language search query (Spanish or English both work).
        k: How many chunks to return (1-40).
        max_chars: Truncate each chunk's text to this many characters
            (0 = no truncation) to keep the response small.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")
    k = max(1, min(int(k), MAX_SEARCH_K))

    service = _current_service()
    rows = service.search(query, limit=k)
    return {
        "query": query,
        "count": len(rows),
        "results": [_shape_hit(row, max_chars) for row in rows],
    }


@mcp.tool
def ask_docs(question: str, limit: int | None = None) -> dict[str, Any]:
    """Answer a question from the documentation, with citations.

    Retrieves relevant chunks and synthesizes an answer with the configured
    LLM. Slower and not free (one LLM call), and answers are cached per
    question + index fingerprint. When you want the primary source rather than
    a summary, use `search_docs` instead.

    Args:
        question: The question to answer.
        limit: Optional override for how many chunks to feed the model.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")

    service = _current_service()
    result = service.ask(question, limit=limit)
    return {
        "question": question,
        "answer": result.get("answer", ""),
        "intent": result.get("intent"),
        "cached": bool(result.get("cached")),
        "sources": result.get("sources", []),
    }


@mcp.tool
def knowledge_status() -> dict[str, Any]:
    """Report index freshness: workspace, document/chunk/embedding counts, last run.

    Use this when an answer looks stale or a doc seems missing — it tells you
    whether the index has been rebuilt since that doc was written.
    """
    service = _current_service()
    data = service.status()
    latest = data.get("latest_run") or {}
    return {
        "workspace": data.get("workspace"),
        "counts": data.get("counts", {}),
        "latest_run_id": latest.get("id"),
        "latest_finished_at": str(latest.get("finished_at")) if latest else None,
    }


def build_server() -> FastMCP:
    """Return the configured server (used by tests and by `main`)."""
    return mcp


def main() -> None:
    load_project_env()
    target = _workspace_target()
    _log(f"serving workspace: {target}")
    mcp.run()


if __name__ == "__main__":
    main()
