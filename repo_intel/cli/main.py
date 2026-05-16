from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from repo_intel.cli import obsidian, workspace
from repo_intel.application.use_cases import SddKnowledgeService
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


app = typer.Typer(help="SDD-only engineering knowledge ingestion CLI.")
app.add_typer(obsidian.app, name="obsidian")
app.add_typer(workspace.app, name="workspace")
console = Console()


@app.command()
def init(target: str) -> None:
    """Create .repo-intel config, SQLite schema, and local storage folders."""
    service = service_for_target(target)
    path = service.init()
    console.print(f"[green]Initialized[/green] {path}")


@app.command()
def scan(target: str) -> None:
    """Discover repositories and SDD/AI documentation without reading source code."""
    service = service_for_target(target)
    repositories, documents = service.scan(persist=True)
    console.print(f"[green]Repositories:[/green] {len(repositories)}")
    console.print(f"[green]SDD documents:[/green] {len(documents)}")
    render_scan_table(repositories, documents)


@app.command()
def ingest(target: str) -> None:
    """Parse SDD docs, create semantic chunks, persist SQLite metadata, and index Chroma."""
    service = service_for_target(target)
    run = service.ingest()
    console.print(f"[green]Ingestion run:[/green] {run.id}")
    console.print(f"Repos: {run.repos_count}")
    console.print(f"Docs: {run.docs_count}")
    console.print(f"Chunks: {run.chunks_count}")
    console.print(f"Embeddings: {run.embeddings_count}")
    if run.errors:
        console.print("[yellow]Errors:[/yellow]")
        for error in run.errors:
            console.print(f"- {error}")
        raise typer.Exit(1)


@app.command()
def query(target: str, question: str, limit: int = 8) -> None:
    """Run semantic retrieval over indexed SDD chunks."""
    service = service_for_target(target)
    try:
        results = service.query(question, limit=limit)
    except Exception as exc:
        console.print(f"[red]Query failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    if not results:
        console.print("[yellow]No results.[/yellow]")
        return
    for index, result in enumerate(results, start=1):
        metadata = result["metadata"]
        console.rule(f"{index}. {metadata.get('repo', 'unknown')} / {metadata.get('path', '')}")
        console.print(f"[cyan]Section:[/cyan] {metadata.get('section', '')}")
        console.print(f"[cyan]Type:[/cyan] {metadata.get('doc_type', '')}")
        console.print(f"[cyan]Distance:[/cyan] {result.get('distance')}")
        console.print(result["text"][:1600].strip())


@app.command()
def ask(target: str, question: str, limit: int | None = None) -> None:
    """Answer a question using retrieved SDD context and the configured local LLM."""
    service = service_for_target(target)
    try:
        result = service.ask(question, limit=limit)
    except Exception as exc:
        console.print(f"[red]Ask failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Answer")
    console.print(f"[cyan]Intent:[/cyan] {result.get('intent', 'unknown')}")
    console.print(result["answer"])
    console.rule("Sources")
    table = Table()
    table.add_column("#", justify="right")
    table.add_column("Repo")
    table.add_column("Path")
    table.add_column("Section")
    table.add_column("Distance")
    for source in result["sources"]:
        table.add_row(
            str(source["index"]),
            source["repo"],
            source["path"],
            source["section"],
            f"{source['distance']:.4f}" if source["distance"] is not None else "",
        )
    console.print(table)


@app.command()
def brief(target: str, refresh_scan: bool = False) -> None:
    """Generate a human-oriented project brief using OpenRouter over SDD overview docs."""
    service = service_for_target(target)
    try:
        output_path = service.brief(refresh_scan=refresh_scan)
    except Exception as exc:
        console.print(f"[red]Brief failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]Brief written:[/green] {output_path}")


@app.command()
def status(target: str) -> None:
    """Show local knowledge store status."""
    service = service_for_target(target)
    data = service.status()
    table = Table(title="SDD Knowledge Status")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Workspace", data["workspace"])
    for key, value in data["counts"].items():
        table.add_row(key, str(value))
    latest = data.get("latest_run")
    if latest:
        table.add_row("latest_run", latest["id"])
        table.add_row("latest_finished_at", str(latest.get("finished_at")))
    console.print(table)


@app.command()
def export(target: str) -> None:
    """Export indexed SDD chunks as markdown and JSONL bundles."""
    service = service_for_target(target)
    export_dir = service.export()
    console.print(f"[green]Exported[/green] {export_dir}")


@app.command()
def reset(target: str) -> None:
    """Reset generated SQLite and Chroma stores."""
    service = service_for_target(target)
    service.reset()
    console.print("[green]Reset complete.[/green]")


def service_for_target(target: str) -> SddKnowledgeService:
    try:
        return SddKnowledgeService(resolve_workspace_path(target))
    except WorkspaceResolutionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def render_scan_table(repositories, documents) -> None:
    docs_by_repo = {}
    for document in documents:
        docs_by_repo[document.repository_id] = docs_by_repo.get(document.repository_id, 0) + 1
    table = Table(title="Discovered SDD Repositories")
    table.add_column("Repo")
    table.add_column("Branch")
    table.add_column("Git")
    table.add_column("Docs", justify="right")
    table.add_column("Path")
    for repo in repositories:
        table.add_row(
            repo.name,
            repo.branch or "",
            repo.git_status,
            str(docs_by_repo.get(repo.id, 0)),
            repo.relative_path,
        )
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
