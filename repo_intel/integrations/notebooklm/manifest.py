from __future__ import annotations

from pathlib import Path

from repo_intel.integrations.notebooklm.models import NotebookLmManifest


def load_manifest(path: Path, workspace: Path, project_name: str, title: str) -> NotebookLmManifest:
    if not path.exists():
        return NotebookLmManifest(
            workspace=str(workspace),
            project_name=project_name,
            notebook_title=title,
        )
    return NotebookLmManifest.model_validate_json(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: NotebookLmManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

