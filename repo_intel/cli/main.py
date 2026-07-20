from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from repo_intel.cli import config, notebooklm, obsidian, workspace
from repo_intel.cli.setup import run_setup
from repo_intel.application.use_cases import SddKnowledgeService
from repo_intel.core.env import load_project_env
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


app = typer.Typer(help="SDD-only engineering knowledge ingestion CLI.")
app.add_typer(config.app, name="config")
app.add_typer(notebooklm.app, name="notebooklm")
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
def setup(
    preset: Annotated[
        str | None,
        typer.Option(help="Setup preset: local, remote-ollama, minimal, or proxima."),
    ] = None,
    ollama_url: str | None = None,
    embedding_model: str | None = None,
    llm_model: str | None = None,
    openrouter_model: str | None = None,
    non_interactive: bool = False,
) -> None:
    """Configure portable global defaults for the repo-intel CLI.

    There is deliberately no `--openrouter-api-key` flag. A secret passed as an argv
    element is readable by any local process via `ps` for the lifetime of the command
    and is written verbatim into shell history. The interactive wizard prompts for it
    with `hide_input=True`; for non-interactive use run
    `repo-intel config env set OPENROUTER_API_KEY`, which writes ~/.repo-intel/.env
    with 0600 permissions.
    """
    run_setup(
        preset=preset,
        ollama_url=ollama_url,
        embedding_model=embedding_model,
        llm_model=llm_model,
        openrouter_model=openrouter_model,
        non_interactive=non_interactive,
    )


@app.command()
def scan(target: str) -> None:
    """Discover repositories and SDD/AI documentation without reading source code."""
    service = service_for_target(target)
    repositories, documents = service.scan(persist=True)
    console.print(f"[green]Repositories:[/green] {len(repositories)}")
    console.print(f"[green]SDD documents:[/green] {len(documents)}")
    render_scan_table(repositories, documents)


@app.command()
def ingest(
    target: str,
    full: Annotated[
        bool,
        typer.Option("--full", help="Rebuild every document instead of only changed ones."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", help="One-line summary only; for hooks and scheduled runs."),
    ] = False,
) -> None:
    """Reindex SDD docs into SQLite + Chroma. Incremental unless --full is passed."""
    service = service_for_target(target)
    run = service.ingest(full=full)

    if quiet:
        console.print(
            f"repo-intel {run.mode}: {run.documents_changed} changed, "
            f"{run.documents_removed} removed, {run.embeddings_created} embedded "
            f"({run.embeddings_count}/{run.chunks_count} indexed)"
        )
    else:
        console.print(f"[green]Ingestion run:[/green] {run.id} [dim]({run.mode})[/dim]")
        console.print(f"Repos: {run.repos_count}")
        console.print(f"Docs: {run.docs_count}")
        console.print(f"Chunks: {run.chunks_count}")
        console.print(f"Embeddings: {run.embeddings_count}")
        console.print(
            f"[cyan]This run:[/cyan] {run.documents_changed} document(s) changed, "
            f"{run.documents_removed} removed, {run.chunks_created} chunk(s) rebuilt, "
            f"{run.embeddings_created} embedding(s) created"
        )
        if not run.documents_changed and not run.documents_removed:
            if run.embeddings_created:
                # No document changed, yet work happened: this is the retry path picking
                # up chunks stranded by an earlier failure. Say so rather than printing
                # the reassuring no-op line over a repair.
                console.print(
                    f"[dim]No document changed; recovered {run.embeddings_created} "
                    "chunk(s) left unembedded by an earlier run.[/dim]"
                )
            else:
                console.print("[dim]Index already up to date; nothing re-embedded.[/dim]")

    # Coverage, not just this run's work. A gap here means chunks exist that retrieval
    # cannot reach, which is invisible in every other counter -- "0 changed" reads as
    # reassuring precisely when a hole is present.
    if run.embeddings_count < run.chunks_count:
        missing = run.chunks_count - run.embeddings_count
        console.print(
            f"[yellow]Warning:[/yellow] {missing} chunk(s) have no embedding and are "
            "invisible to search. The next ingest retries them automatically; "
            "`repo-intel ingest <target> --full` rebuilds everything."
        )

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
    console.print(f"[cyan]Cached:[/cyan] {'yes' if result.get('cached') else 'no'}")
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
    # Load ~/.repo-intel/.env and the project .env BEFORE any command builds a config,
    # so REPO_INTEL_* overrides and provider API keys are visible to every subcommand
    # (previously only `doctor` and the OpenRouter client loaded them).
    load_project_env()
    app()


if __name__ == "__main__":
    main()
