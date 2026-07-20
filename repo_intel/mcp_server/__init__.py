"""MCP (Model Context Protocol) surface for repo-intel.

Exposes the already-indexed SDD/OpenSpec knowledge base to MCP clients
(Claude Code, etc.) as tools. Read-only: this package never mutates the
knowledge store — ingestion stays in the CLI.
"""

from __future__ import annotations

__all__ = ["build_server", "main"]


def __getattr__(name: str):  # pragma: no cover - thin lazy re-export
    if name in __all__:
        from repo_intel.mcp_server import server

        return getattr(server, name)
    raise AttributeError(name)
