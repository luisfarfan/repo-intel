from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from repo_intel.integrations.notebooklm.client import NotebookLmCliError
from repo_intel.integrations.notebooklm.sync import NotebookLmSyncService
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


app = typer.Typer(help="Sync repo-intel SDD bundles into NotebookLM through notebooklm-py.")
console = Console()


@app.command()
def login(browser: str | None = None) -> None:
    """Authenticate notebooklm-py with Google NotebookLM."""
    try:
        NotebookLmSyncService(resolve_workspace_path(".")).login(browser=browser)
    except (NotebookLmCliError, WorkspaceResolutionError) as exc:
        console.print("NotebookLM login failed:", style="red")
        console.print(str(exc), markup=False)
        raise typer.Exit(1) from exc


@app.command("auth-check")
def auth_check(target: Annotated[str, typer.Argument()] = ".") -> None:
    """Check notebooklm-py authentication."""
    service = service_for_target(target)
    try:
        data = service.auth_check()
    except NotebookLmCliError as exc:
        console.print("NotebookLM auth check failed:", style="red")
        console.print(str(exc), markup=False)
        raise typer.Exit(1) from exc
    console.print(data)


@app.command()
def init(target: str, dry_run: bool = False) -> None:
    """Generate NotebookLM sources and create a notebook if needed."""
    service = service_for_target(target)
    try:
        result = service.init(dry_run=dry_run)
    except NotebookLmCliError as exc:
        console.print("NotebookLM init failed:", style="red")
        console.print(str(exc), markup=False)
        raise typer.Exit(1) from exc
    render_result("NotebookLM Init", result.model_dump())


@app.command()
def sync(target: str, dry_run: bool = False, force: bool = False) -> None:
    """Upload changed repo-intel NotebookLM source bundles."""
    service = service_for_target(target)
    try:
        result = service.sync(dry_run=dry_run, force=force)
    except NotebookLmCliError as exc:
        console.print("NotebookLM sync failed:", style="red")
        console.print(str(exc), markup=False)
        raise typer.Exit(1) from exc
    render_result("NotebookLM Sync", result.model_dump())
    if result.errors:
        raise typer.Exit(1)


@app.command()
def status(target: str) -> None:
    """Show local NotebookLM manifest status."""
    service = service_for_target(target)
    render_result("NotebookLM Status", service.status())


@app.command("generate-sources")
def generate_sources(target: str) -> None:
    """Generate local NotebookLM markdown bundles without uploading."""
    service = service_for_target(target)
    bundles = service.generate_sources()
    table = Table(title="NotebookLM Sources")
    table.add_column("Title")
    table.add_column("Path")
    table.add_column("Hash")
    for bundle in bundles:
        table.add_row(bundle.title, str(bundle.path), bundle.content_hash[:12])
    console.print(table)


def service_for_target(target: str) -> NotebookLmSyncService:
    try:
        return NotebookLmSyncService(resolve_workspace_path(target))
    except WorkspaceResolutionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def render_result(title: str, data: dict) -> None:
    table = Table(title=title)
    table.add_column("Field")
    table.add_column("Value")
    for key, value in data.items():
        if key == "errors" and value:
            table.add_row(key, "\n".join(value))
        else:
            table.add_row(key, str(value))
    console.print(table)
