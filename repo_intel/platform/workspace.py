from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repo_intel.platform.registry import get_workspace


class WorkspaceResolutionError(ValueError):
    def __init__(self, target: str) -> None:
        self.target = target
        super().__init__(
            f"Unknown workspace target: {target}\n"
            "Register it with:\n"
            f"  repo-intel workspace add {target} /path/to/workspace"
        )


@dataclass(frozen=True)
class ResolvedWorkspace:
    name: str | None
    path: Path
    source: str


def resolve_workspace_target(target: str | Path) -> ResolvedWorkspace:
    target_text = str(target)
    registered = get_workspace(target_text)
    if registered:
        return ResolvedWorkspace(
            name=registered.name,
            path=Path(registered.path).expanduser().resolve(),
            source="registry",
        )

    candidate = Path(target_text).expanduser()
    if candidate.exists():
        return ResolvedWorkspace(name=None, path=candidate.resolve(), source="path")

    raise WorkspaceResolutionError(target_text)


def resolve_workspace_path(target: str | Path) -> Path:
    return resolve_workspace_target(target).path
