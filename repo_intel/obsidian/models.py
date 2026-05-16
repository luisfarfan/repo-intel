from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ObsidianSourceState:
    workspace: str
    project_name: str
    synced_at: datetime
    repositories: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    project_brief: str | None = None
    topics: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    exports: list[dict[str, Any]] = field(default_factory=list)
    last_answer_plan: dict[str, Any] | None = None
