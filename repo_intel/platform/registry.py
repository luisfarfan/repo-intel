from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from repo_intel.platform.home import ensure_repo_intel_home, workspaces_registry_path


class WorkspaceRegistryError(ValueError):
    pass


class RegisteredWorkspace(BaseModel):
    name: str
    path: str
    enabled: bool = True
    created_at: str
    updated_at: str


class WorkspaceRegistry(BaseModel):
    workspaces: list[RegisteredWorkspace] = Field(default_factory=list)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_workspace_name(name: str) -> str:
    normalized = name.strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", normalized):
        raise WorkspaceRegistryError(
            "Workspace name must start with a letter or number and contain only letters, "
            "numbers, hyphens, or underscores."
        )
    return normalized


def load_registry() -> WorkspaceRegistry:
    ensure_repo_intel_home()
    path = workspaces_registry_path()
    if not path.exists():
        return WorkspaceRegistry()
    data = json.loads(path.read_text(encoding="utf-8"))
    return WorkspaceRegistry.model_validate(data)


def save_registry(registry: WorkspaceRegistry) -> None:
    ensure_repo_intel_home()
    path = workspaces_registry_path()
    payload = registry.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_workspace(name: str, path: Path, enabled: bool = True) -> RegisteredWorkspace:
    workspace_name = validate_workspace_name(name)
    workspace_path = path.expanduser().resolve()
    if not workspace_path.exists():
        raise WorkspaceRegistryError(f"Workspace path does not exist: {workspace_path}")
    if not workspace_path.is_dir():
        raise WorkspaceRegistryError(f"Workspace path is not a directory: {workspace_path}")

    registry = load_registry()
    now = utc_iso()
    existing = next((item for item in registry.workspaces if item.name == workspace_name), None)
    if existing:
        existing.path = str(workspace_path)
        existing.enabled = enabled
        existing.updated_at = now
        workspace = existing
    else:
        workspace = RegisteredWorkspace(
            name=workspace_name,
            path=str(workspace_path),
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        registry.workspaces.append(workspace)

    registry.workspaces.sort(key=lambda item: item.name)
    save_registry(registry)
    return workspace


def remove_workspace(name: str) -> RegisteredWorkspace | None:
    workspace_name = validate_workspace_name(name)
    registry = load_registry()
    removed = next((item for item in registry.workspaces if item.name == workspace_name), None)
    if not removed:
        return None
    registry.workspaces = [item for item in registry.workspaces if item.name != workspace_name]
    save_registry(registry)
    return removed


def get_workspace(name: str) -> RegisteredWorkspace | None:
    registry = load_registry()
    return next((item for item in registry.workspaces if item.name == name), None)


def list_workspaces() -> list[RegisteredWorkspace]:
    return load_registry().workspaces


def registry_as_dict() -> dict[str, Any]:
    return load_registry().model_dump(mode="json")
