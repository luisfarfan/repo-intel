from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from repo_intel.application.use_cases import SddKnowledgeService
from repo_intel.platform.home import repo_intel_home, workspaces_registry_path
from repo_intel.platform.registry import (
    WorkspaceRegistryError,
    add_workspace,
    get_workspace,
    list_workspaces,
    remove_workspace,
)
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


app = typer.Typer(help="Manage named repo-intel workspaces.")
console = Console()


@app.command("add")
def add(name: str, path: Path) -> None:
    """Register or update a named workspace."""
    try:
        workspace = add_workspace(name, path)
    except WorkspaceRegistryError as exc:
        console.print(f"[red]Workspace add failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]Workspace registered:[/green] {workspace.name} -> {workspace.path}")


@app.command("list")
def list_registered() -> None:
    """List registered workspaces."""
    workspaces = list_workspaces()
    table = Table(title=f"repo-intel Workspaces ({workspaces_registry_path()})")
    table.add_column("Name")
    table.add_column("Enabled")
    table.add_column("Path")
    table.add_column("Exists")
    for workspace in workspaces:
        path = Path(workspace.path)
        table.add_row(workspace.name, str(workspace.enabled), workspace.path, str(path.exists()))
    console.print(table)
    if not workspaces:
        console.print(f"[yellow]No workspaces registered in {repo_intel_home()}[/yellow]")


@app.command()
def show(name: str) -> None:
    """Show one registered workspace."""
    workspace = get_workspace(name)
    if not workspace:
        console.print(f"[red]Unknown workspace:[/red] {name}")
        raise typer.Exit(1)
    table = Table(title=f"Workspace: {workspace.name}")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in workspace.model_dump(mode="json").items():
        table.add_row(key, str(value))
    table.add_row("exists", str(Path(workspace.path).exists()))
    table.add_row("has_config", str((Path(workspace.path) / ".repo-intel" / "config.toml").exists()))
    console.print(table)


@app.command("remove")
def remove(name: str) -> None:
    """Remove a workspace from the global registry without deleting local data."""
    removed = remove_workspace(name)
    if not removed:
        console.print(f"[red]Unknown workspace:[/red] {name}")
        raise typer.Exit(1)
    console.print(f"[green]Workspace removed from registry:[/green] {removed.name}")


@app.command()
def status(name: str) -> None:
    """Show registry and knowledge-store status for a workspace."""
    try:
        workspace_path = resolve_workspace_path(name)
    except WorkspaceResolutionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    table = Table(title=f"Workspace Status: {name}")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("path", str(workspace_path))
    table.add_row("exists", str(workspace_path.exists()))
    table.add_row("has_config", str((workspace_path / ".repo-intel" / "config.toml").exists()))

    try:
        data = SddKnowledgeService(workspace_path).status()
        for key, value in data["counts"].items():
            table.add_row(key, str(value))
        latest = data.get("latest_run")
        if latest:
            table.add_row("latest_run", latest["id"])
            table.add_row("latest_finished_at", str(latest.get("finished_at")))
    except Exception as exc:
        table.add_row("knowledge_status", f"unavailable: {exc}")

    console.print(table)
