"""Tests for the repo-intel MCP layer.

These run without a knowledge store: the service is stubbed, so what is under
test is the MCP contract (tool names, schemas, shaping, guards) rather than
retrieval quality.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from repo_intel.mcp_server import server as mcp_server


class StubService:
    def __init__(self, rows=None, ask=None, status=None):
        self._rows = rows if rows is not None else []
        self._ask = ask or {}
        self._status = status or {}
        self.query_calls: list[tuple[str, int]] = []
        self.ask_calls: list[tuple[str, int | None]] = []

    def query(self, question, limit=8):
        self.query_calls.append((question, limit))
        return self._rows

    def ask(self, question, limit=None):
        self.ask_calls.append((question, limit))
        return self._ask

    def status(self):
        return self._status


@pytest.fixture
def stub(monkeypatch):
    service = StubService()
    monkeypatch.setattr(mcp_server, "_current_service", lambda: service)
    return service


def call(tool_name: str, **kwargs):
    """Invoke a tool through a real MCP client session (in-memory transport)."""

    async def _run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool(tool_name, kwargs)

    return asyncio.run(_run())


def list_tools():
    async def _run():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()

    return asyncio.run(_run())


# --- registration -----------------------------------------------------------


def test_expected_tools_are_registered():
    names = {tool.name for tool in list_tools()}
    assert {"search_docs", "ask_docs", "knowledge_status"} <= names


def test_every_tool_has_a_description():
    # An undescribed tool is invisible to a model choosing between servers.
    for tool in list_tools():
        assert tool.description, f"{tool.name} has no description"


def test_search_docs_schema_exposes_documented_params():
    tool = next(t for t in list_tools() if t.name == "search_docs")
    assert set(tool.inputSchema["properties"]) == {"query", "k", "max_chars"}
    assert tool.inputSchema.get("required") == ["query"]


# --- workspace resolution ---------------------------------------------------


def test_workspace_prefers_env_over_argv(monkeypatch):
    monkeypatch.setenv("REPO_INTEL_WORKSPACE", "/from/env")
    monkeypatch.setattr(mcp_server.sys, "argv", ["server", "/from/argv"])
    assert mcp_server._workspace_target() == "/from/env"


def test_workspace_falls_back_to_argv_then_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("REPO_INTEL_WORKSPACE", raising=False)
    monkeypatch.setattr(mcp_server.sys, "argv", ["server", "/from/argv"])
    assert mcp_server._workspace_target() == "/from/argv"

    monkeypatch.setattr(mcp_server.sys, "argv", ["server", "--flag"])
    monkeypatch.chdir(tmp_path)
    assert mcp_server._workspace_target() == str(tmp_path)


def test_unknown_workspace_raises_actionable_error(monkeypatch):
    monkeypatch.setenv("REPO_INTEL_WORKSPACE", "definitely-not-a-workspace")
    mcp_server._service.cache_clear()
    with pytest.raises(ValueError, match="workspace add"):
        mcp_server._current_service()


# --- shaping ----------------------------------------------------------------


def test_clip_truncates_and_flags():
    text, truncated = mcp_server._clip("a" * 50, 10)
    assert truncated and text.endswith("[…]") and len(text) < 50

    text, truncated = mcp_server._clip("short", 10)
    assert (text, truncated) == ("short", False)

    # 0 disables truncation rather than emptying the chunk.
    text, truncated = mcp_server._clip("a" * 50, 0)
    assert (len(text), truncated) == (50, False)


def test_shape_hit_inverts_distance_into_score():
    hit = mcp_server._shape_hit(
        {
            "id": "chunk-1",
            "text": "body",
            "distance": 0.25,
            "metadata": {"repo": "proxima-api", "path": "openspec/specs/x/spec.md"},
        },
        max_chars=100,
    )
    assert hit["distance"] == 0.25
    assert hit["score"] == 0.75  # lower distance must mean higher score
    assert hit["repo"] == "proxima-api"
    assert hit["path"] == "openspec/specs/x/spec.md"


def test_shape_hit_survives_missing_metadata_and_distance():
    hit = mcp_server._shape_hit({"text": "body"}, max_chars=100)
    assert hit["score"] is None
    assert hit["repo"] == "" and hit["path"] == ""


# --- search_docs ------------------------------------------------------------


def test_search_docs_returns_path_and_score(stub):
    stub._rows = [
        {"id": "c1", "text": "x", "distance": 0.1, "metadata": {"repo": "r", "path": "p.md"}}
    ]
    result = call("search_docs", query="stock")
    assert result.structured_content["count"] == 1
    hit = result.structured_content["results"][0]
    assert hit["path"] == "p.md" and hit["score"] == 0.9


def test_search_docs_clamps_k(stub):
    call("search_docs", query="q", k=999)
    call("search_docs", query="q", k=0)
    assert [limit for _, limit in stub.query_calls] == [mcp_server.MAX_SEARCH_K, 1]


def test_search_docs_rejects_blank_query(stub):
    with pytest.raises(Exception, match="must not be empty"):
        call("search_docs", query="   ")
    assert stub.query_calls == []  # guard fires before any retrieval work


# --- ask_docs ---------------------------------------------------------------


def test_ask_docs_passes_through_answer_and_sources(stub):
    stub._ask = {
        "answer": "inventory_balances",
        "sources": [{"index": 1, "repo": "proxima-api", "path": "spec.md"}],
        "intent": "default",
        "cached": True,
    }
    result = call("ask_docs", question="fuente de verdad del stock")
    payload = result.structured_content
    assert payload["answer"] == "inventory_balances"
    assert payload["cached"] is True
    assert payload["sources"][0]["repo"] == "proxima-api"


def test_ask_docs_rejects_blank_question(stub):
    with pytest.raises(Exception, match="must not be empty"):
        call("ask_docs", question="")
    assert stub.ask_calls == []


# --- knowledge_status -------------------------------------------------------


def test_knowledge_status_reports_counts_and_last_run(stub):
    stub._status = {
        "workspace": "/ws",
        "counts": {"documents": 933, "embeddings": 7848},
        "latest_run": {"id": "run:1", "finished_at": "2026-07-20T09:24:40"},
    }
    payload = call("knowledge_status").structured_content
    assert payload["counts"]["documents"] == 933
    assert payload["latest_run_id"] == "run:1"
    assert payload["latest_finished_at"] == "2026-07-20T09:24:40"


def test_knowledge_status_without_any_run(stub):
    stub._status = {"workspace": "/ws", "counts": {}}
    payload = call("knowledge_status").structured_content
    assert payload["latest_run_id"] is None
    assert payload["latest_finished_at"] is None
