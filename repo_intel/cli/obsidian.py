from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from repo_intel.core.config import load_config
from repo_intel.obsidian.sync import ObsidianSyncService
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


app = typer.Typer(help="Generate and maintain an Obsidian cognitive layer.")
console = Console()


@app.command("init")
def init_vault(target: str) -> None:
    """Create the Obsidian vault skeleton."""
    workspace = resolve_target_or_exit(target)
    service = ObsidianSyncService(workspace, load_config(workspace))
    vault = service.init_vault()
    console.print(f"[green]Obsidian vault initialized:[/green] {vault}")


@app.command()
def sync(target: str) -> None:
    """Regenerate Obsidian markdown from repo-intel machine memory."""
    workspace = resolve_target_or_exit(target)
    service = ObsidianSyncService(workspace, load_config(workspace))
    result = service.sync()
    console.print(f"[green]Obsidian sync complete:[/green] {result['vault']}")
    console.print(f"Files written: {result['written']}")
    console.print(f"Repositories: {result['repositories']}")
    console.print(f"Documents: {result['documents']}")
    console.print(f"Chunks: {result['chunks']}")
    console.print(f"Topics: {result['topics']}")


@app.command()
def status(target: str) -> None:
    """Show Obsidian vault status."""
    workspace = resolve_target_or_exit(target)
    service = ObsidianSyncService(workspace, load_config(workspace))
    data = service.status()
    table = Table(title="Obsidian Cognitive Layer")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Vault", data["vault"])
    table.add_row("Exists", str(data["exists"]))
    manifest = data.get("last_sync") or {}
    table.add_row("Last synced", str(manifest.get("synced_at", "never")))
    counts = manifest.get("counts") or {}
    for key, value in counts.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def watch(target: str, interval: int = 10, once: bool = False) -> None:
    """Watch repo-intel artifacts and refresh Obsidian when they change."""
    workspace = resolve_target_or_exit(target)
    service = ObsidianSyncService(workspace, load_config(workspace))
    console.print(f"[green]Watching repo-intel sources every {interval}s[/green]")
    service.watch(interval_seconds=interval, once=once)


def resolve_target_or_exit(target: str):
    try:
        return resolve_workspace_path(target)
    except WorkspaceResolutionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
