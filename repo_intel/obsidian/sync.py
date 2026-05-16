from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from repo_intel.core.config import AppConfig, resolve_workspace_path
from repo_intel.obsidian.models import ObsidianSourceState
from repo_intel.obsidian.render import render_all
from repo_intel.obsidian.source import load_obsidian_source


class ObsidianSyncService:
    def __init__(self, workspace: Path, config: AppConfig) -> None:
        self.workspace = workspace.resolve()
        self.config = config
        self.vault_path = resolve_workspace_path(self.workspace, config.obsidian.vault_path)
        self.generated_root = config.obsidian.generated_root

    def init_vault(self) -> Path:
        self.vault_path.mkdir(parents=True, exist_ok=True)
        (self.vault_path / ".obsidian").mkdir(parents=True, exist_ok=True)
        self.write_obsidian_app_config()
        self.write_readme()
        return self.vault_path

    def sync(self) -> dict:
        self.init_vault()
        state = load_obsidian_source(self.workspace, self.config)
        files = render_all(state, self.generated_root)
        written = []
        for relative_path, content in files.items():
            target = self.vault_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.rstrip() + "\n", encoding="utf-8")
            written.append(str(relative_path))
        self.write_sync_manifest(state, written)
        return {
            "vault": str(self.vault_path),
            "written": len(written),
            "repositories": len(state.repositories),
            "documents": len(state.documents),
            "chunks": len(state.chunks),
            "topics": len(state.topics),
        }

    def status(self) -> dict:
        source_mtime = source_signature(self.workspace)
        manifest = self.read_sync_manifest()
        return {
            "vault": str(self.vault_path),
            "exists": self.vault_path.exists(),
            "source_signature": source_mtime,
            "last_sync": manifest,
        }

    def watch(self, interval_seconds: int = 10, once: bool = False) -> None:
        previous = None
        while True:
            current = source_signature(self.workspace)
            if current != previous:
                self.sync()
                previous = current
            if once:
                return
            time.sleep(interval_seconds)

    def write_obsidian_app_config(self) -> None:
        app_json = self.vault_path / ".obsidian" / "app.json"
        if not app_json.exists():
            app_json.write_text(
                json.dumps(
                    {
                        "alwaysUpdateLinks": True,
                        "newFileLocation": "current",
                        "showLineNumber": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def write_readme(self) -> None:
        readme = self.vault_path / "README.md"
        if not readme.exists():
            readme.write_text(
                "# repo-intel Obsidian Vault\n\nGenerated from repo-intel machine memory. Start at [[Home]].\n",
                encoding="utf-8",
            )

    def write_sync_manifest(self, state: ObsidianSourceState, written: list[str]) -> None:
        manifest_path = self.vault_path / self.generated_root / "99 System" / "sync-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "synced_at": state.synced_at.isoformat(),
                    "workspace": state.workspace,
                    "project": state.project_name,
                    "written": written,
                    "counts": {
                        "repositories": len(state.repositories),
                        "documents": len(state.documents),
                        "chunks": len(state.chunks),
                        "topics": len(state.topics),
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def read_sync_manifest(self) -> dict | None:
        manifest_path = self.vault_path / self.generated_root / "99 System" / "sync-manifest.json"
        if not manifest_path.exists():
            return None
        return json.loads(manifest_path.read_text(encoding="utf-8"))


def source_signature(workspace: Path) -> dict[str, float | None]:
    paths = {
        "knowledge_db": workspace / ".repo-intel" / "knowledge.db",
        "project_brief": workspace / ".repo-intel" / "briefs" / "project-brief.md",
        "repositories_artifact": workspace / ".repo-intel" / "artifacts" / "repositories.json",
        "documents_artifact": workspace / ".repo-intel" / "artifacts" / "documents.json",
        "chunks_artifact": workspace / ".repo-intel" / "artifacts" / "chunks.json",
    }
    return {name: path.stat().st_mtime if path.exists() else None for name, path in paths.items()}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

