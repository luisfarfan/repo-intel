from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from repo_intel.cli.config import (
    detect_ollama,
    render_doctor_table,
    suggested_chat_model,
    suggested_embedding_model,
    validate_config,
    write_env_value,
)
from repo_intel.core.config import AppConfig, load_global_config_file, write_global_config
from repo_intel.platform.home import ensure_repo_intel_home


console = Console()

PRESETS = {"local", "remote-ollama", "minimal", "proxima"}


@dataclass(frozen=True)
class SetupPreset:
    ollama_url: str
    embedding_model: str
    llm_model: str
    configure_optional: bool = True
    # Chat endpoint. Defaults to the embeddings host (single-Ollama setups); presets
    # that split embeddings and chat across hosts override it.
    llm_url: str | None = None
    llm_provider: str = "ollama"

    @property
    def chat_url(self) -> str:
        return self.llm_url or self.ollama_url


PRESET_VALUES = {
    "local": SetupPreset(
        ollama_url="http://localhost:11434",
        embedding_model="nomic-embed-text",
        llm_model="phi3:mini",
    ),
    "remote-ollama": SetupPreset(
        ollama_url="http://localhost:11434",
        embedding_model="nomic-embed-text",
        llm_model="phi3:mini",
    ),
    "minimal": SetupPreset(
        ollama_url="http://localhost:11434",
        embedding_model="nomic-embed-text",
        llm_model="phi3:mini",
        configure_optional=False,
    ),
    # Embeddings stay local (free, private, no network hop); chat goes to the local
    # cliproxy OpenAI-compatible gateway. The old 192.168.1.12 host is dead.
    "proxima": SetupPreset(
        ollama_url="http://127.0.0.1:11434",
        embedding_model="nomic-embed-text:latest",
        llm_model="gemini-3-flash",
        llm_url="http://127.0.0.1:8317/v1",
        llm_provider="cliproxy",
    ),
}


def run_setup(
    ollama_url: str | None = None,
    embedding_model: str | None = None,
    llm_model: str | None = None,
    openrouter_model: str | None = None,
    non_interactive: bool = False,
    preset: str | None = None,
) -> None:
    """Configure portable global defaults for repo-intel.

    Note the absence of an `openrouter_api_key` parameter: the key is only ever
    collected by the interactive wizard's hidden prompt, so it cannot reach argv (and
    therefore `ps` and shell history). Non-interactive callers use
    `repo-intel config env set OPENROUTER_API_KEY`.
    """
    ensure_repo_intel_home()
    openrouter_api_key: str | None = None
    cfg = load_global_config_file()
    interactive = sys.stdin.isatty() and not non_interactive

    selected_preset = normalize_preset(preset, interactive)
    apply_preset(cfg, selected_preset)

    if interactive:
        console.print(
            Panel.fit(
                "Configure repo-intel once, then reuse it across workspaces.\n"
                "This writes global defaults only; project memory stays inside each workspace.",
                title="repo-intel setup",
                border_style="cyan",
            )
        )
        cfg, openrouter_api_key = run_interactive_wizard(
            cfg,
            selected_preset,
            ollama_url=ollama_url,
            embedding_model=embedding_model,
            llm_model=llm_model,
            openrouter_model=openrouter_model,
        )
    else:
        apply_flag_overrides(
            cfg,
            ollama_url=ollama_url,
            embedding_model=embedding_model,
            llm_model=llm_model,
            openrouter_model=openrouter_model,
        )

    render_summary(cfg, selected_preset)
    config_path = write_global_config(cfg)
    console.print(f"[green]Global config written:[/green] {config_path}")

    if openrouter_api_key:
        env_path = write_env_value(cfg.brief.api_key_env, openrouter_api_key)
        console.print(f"[green]Global env written:[/green] {env_path}")

    console.print()
    render_doctor_table(validate_config(cfg))
    render_next_steps()


def normalize_preset(preset: str | None, interactive: bool) -> str:
    if not preset and not interactive:
        return "minimal"
    if not preset:
        preset = typer.prompt(
            "Choose setup preset (local, remote-ollama, minimal, proxima)",
            default="local",
        )
    normalized = preset.strip().lower()
    if normalized not in PRESETS:
        raise typer.BadParameter(f"Unknown preset: {preset}. Expected one of: {', '.join(sorted(PRESETS))}")
    return normalized


def apply_preset(cfg: AppConfig, preset: str) -> None:
    values = PRESET_VALUES[preset]
    cfg.embeddings.base_url = values.ollama_url
    cfg.llm.base_url = values.chat_url
    cfg.llm.provider = values.llm_provider
    cfg.embeddings.model = values.embedding_model
    cfg.llm.model = values.llm_model


def apply_flag_overrides(
    cfg: AppConfig,
    ollama_url: str | None,
    embedding_model: str | None,
    llm_model: str | None,
    openrouter_model: str | None,
) -> None:
    if ollama_url:
        cfg.embeddings.base_url = ollama_url
        cfg.llm.base_url = ollama_url
    if embedding_model:
        cfg.embeddings.model = embedding_model
    if llm_model:
        cfg.llm.model = llm_model
    if openrouter_model:
        cfg.brief.model = openrouter_model


def run_interactive_wizard(
    cfg: AppConfig,
    preset: str,
    ollama_url: str | None,
    embedding_model: str | None,
    llm_model: str | None,
    openrouter_model: str | None,
) -> tuple[AppConfig, str | None]:
    openrouter_api_key: str | None = None
    console.print(f"[cyan]Preset:[/cyan] {preset}")

    configured_url = ollama_url or cfg.embeddings.base_url
    if preset == "remote-ollama":
        configured_url = typer.prompt("Remote Ollama URL", default=configured_url)
    elif preset != "minimal":
        configured_url = typer.prompt("Ollama URL", default=configured_url)

    cfg.embeddings.base_url = configured_url
    # Only follow the embeddings host for chat when the preset does not point chat
    # somewhere else (e.g. the cliproxy gateway).
    if PRESET_VALUES[preset].llm_url is None:
        cfg.llm.base_url = configured_url

    status, detail, models = detect_ollama(configured_url)
    render_ollama_detection(status, detail, models)

    if models and PRESET_VALUES[preset].llm_url is None:
        cfg.embeddings.model = suggested_embedding_model(models)
        cfg.llm.model = suggested_chat_model(models)
    elif models:
        cfg.embeddings.model = suggested_embedding_model(models)
    cfg.embeddings.model = typer.prompt(
        "Embedding model",
        default=embedding_model or cfg.embeddings.model,
    )
    cfg.llm.model = typer.prompt("Chat LLM model", default=llm_model or cfg.llm.model)

    if PRESET_VALUES[preset].configure_optional:
        configure_openrouter = typer.confirm("Configure OpenRouter for richer briefs?", default=False)
        if configure_openrouter:
            cfg.brief.model = typer.prompt(
                "OpenRouter brief model",
                default=openrouter_model or cfg.brief.model,
            )
            openrouter_api_key = typer.prompt(
                "OpenRouter API key",
                default="",
                hide_input=True,
                show_default=False,
            )
    elif openrouter_model:
        cfg.brief.model = openrouter_model

    render_notebooklm_detection()
    return cfg, openrouter_api_key


def render_ollama_detection(status: str, detail: str, models: set[str]) -> None:
    style = "green" if status == "ok" else "yellow"
    console.print(Panel(detail, title="Ollama detection", border_style=style))
    if not models:
        console.print(
            "[yellow]No Ollama models detected. You can continue and run `repo-intel config doctor` later.[/yellow]"
        )
        return
    table = Table(title="Detected Ollama Models")
    table.add_column("#", justify="right")
    table.add_column("Model")
    for index, model in enumerate(sorted(models), start=1):
        table.add_row(str(index), model)
    console.print(table)


def render_notebooklm_detection() -> None:
    path = shutil.which("notebooklm")
    if path:
        console.print(f"[green]NotebookLM CLI detected:[/green] {path}")
    else:
        console.print(
            "[yellow]NotebookLM CLI not found.[/yellow] "
            'Install optional support with: uv tool install --editable . --with "notebooklm-py[browser]"'
        )


def render_summary(cfg: AppConfig, preset: str) -> None:
    table = Table(title="Setup Summary")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("preset", preset)
    table.add_row("embeddings.base_url", cfg.embeddings.base_url)
    table.add_row("embeddings.model", cfg.embeddings.model)
    table.add_row("llm.base_url", cfg.llm.base_url)
    table.add_row("llm.model", cfg.llm.model)
    table.add_row("brief.model", cfg.brief.model)
    table.add_row("notebooklm.cli_command", cfg.notebooklm.cli_command)
    console.print(table)


def render_next_steps() -> None:
    console.print(
        Panel.fit(
            "Next steps:\n"
            "  repo-intel workspace add <name> <path>\n"
            "  repo-intel ingest <name>\n"
            '  repo-intel ask <name> "Que es este proyecto?"\n'
            "  repo-intel config doctor --workspace <name>",
            title="Ready",
            border_style="green",
        )
    )

