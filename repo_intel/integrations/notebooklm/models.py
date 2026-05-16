from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class NotebookLmSourceBundle(BaseModel):
    title: str
    path: Path
    content_hash: str
    source_id: str | None = None


class NotebookLmManifest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace: str
    project_name: str
    notebook_title: str
    notebook_id: str | None = None
    last_synced_at: datetime | None = None
    sources: dict[str, NotebookLmSourceBundle] = Field(default_factory=dict)


class NotebookLmSyncResult(BaseModel):
    notebook_id: str | None = None
    generated: int = 0
    uploaded: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: list[str] = Field(default_factory=list)
    dry_run: bool = False

