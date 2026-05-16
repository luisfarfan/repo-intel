from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from repo_intel.core.config import load_config, resolve_workspace_path
from repo_intel.integrations.notebooklm.bundles import generate_notebooklm_bundles
from repo_intel.integrations.notebooklm.client import NotebookLmCli, NotebookLmCliError
from repo_intel.integrations.notebooklm.manifest import load_manifest, save_manifest
from repo_intel.integrations.notebooklm.models import NotebookLmManifest, NotebookLmSyncResult
from repo_intel.storage.sqlite import KnowledgeStore


class NotebookLmSyncService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.config = load_config(self.workspace)
        self.store = KnowledgeStore(resolve_workspace_path(self.workspace, self.config.storage.sqlite_path))
        self.source_root = resolve_workspace_path(self.workspace, self.config.notebooklm.source_root)
        self.manifest_path = resolve_workspace_path(self.workspace, self.config.notebooklm.manifest_path)
        self.client = NotebookLmCli(
            command=self.config.notebooklm.cli_command,
            timeout=self.config.notebooklm.timeout_seconds,
        )

    @property
    def notebook_title(self) -> str:
        configured = (self.config.notebooklm.notebook_title or "").strip()
        if configured:
            return configured
        return f"{self.config.project_name} Engineering Brain"

    def login(self, browser: str | None = None) -> None:
        self.client.login(browser=browser)

    def auth_check(self) -> dict:
        return self.client.auth_check()

    def generate_sources(self) -> list:
        repositories = self.store.all_repositories()
        documents = self.store.all_documents()
        chunks = self.store.all_chunks()
        return generate_notebooklm_bundles(
            workspace=self.workspace,
            project_name=self.config.project_name,
            source_root=self.source_root,
            repositories=repositories,
            documents=documents,
            chunks=chunks,
            max_source_chars=self.config.notebooklm.max_source_chars,
        )

    def init(self, dry_run: bool = False) -> NotebookLmSyncResult:
        bundles = self.generate_sources()
        manifest = self.load_manifest()
        result = NotebookLmSyncResult(generated=len(bundles), dry_run=dry_run)
        if dry_run:
            return result
        if not manifest.notebook_id:
            manifest.notebook_id = self.client.create_notebook(self.notebook_title)
        manifest.notebook_title = self.notebook_title
        save_manifest(self.manifest_path, manifest)
        result.notebook_id = manifest.notebook_id
        return result

    def sync(self, dry_run: bool = False, force: bool = False) -> NotebookLmSyncResult:
        bundles = self.generate_sources()
        manifest = self.load_manifest()
        result = NotebookLmSyncResult(
            notebook_id=manifest.notebook_id,
            generated=len(bundles),
            dry_run=dry_run,
        )

        if not manifest.notebook_id:
            if dry_run:
                result.uploaded = len(bundles)
                return result
            manifest.notebook_id = self.client.create_notebook(self.notebook_title)
            result.notebook_id = manifest.notebook_id

        for bundle in bundles:
            previous = manifest.sources.get(bundle.title)
            unchanged = previous and previous.content_hash == bundle.content_hash
            if unchanged and not force:
                result.skipped += 1
                continue
            if dry_run:
                result.uploaded += 1
                continue
            try:
                if previous:
                    self.client.delete_source_by_title(manifest.notebook_id, bundle.title)
                    result.deleted += 1
                bundle.source_id = self.client.add_file_source(
                    manifest.notebook_id,
                    bundle.path,
                    bundle.title,
                )
                manifest.sources[bundle.title] = bundle
                result.uploaded += 1
            except NotebookLmCliError as exc:
                result.errors.append(f"{bundle.title}: {exc}")

        if not dry_run:
            manifest.last_synced_at = datetime.now(timezone.utc)
            manifest.notebook_title = self.notebook_title
            save_manifest(self.manifest_path, manifest)
        return result

    def status(self) -> dict:
        manifest = self.load_manifest()
        return {
            "workspace": str(self.workspace),
            "notebook_title": manifest.notebook_title,
            "notebook_id": manifest.notebook_id,
            "manifest_path": str(self.manifest_path),
            "source_root": str(self.source_root),
            "sources": len(manifest.sources),
            "last_synced_at": manifest.last_synced_at.isoformat()
            if manifest.last_synced_at
            else None,
        }

    def load_manifest(self) -> NotebookLmManifest:
        return load_manifest(
            self.manifest_path,
            workspace=self.workspace,
            project_name=self.config.project_name,
            title=self.notebook_title,
        )
