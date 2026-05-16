from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

import requests
import typer
from rich.console import Console
from rich.table import Table

from repo_intel.core.config import (
    AppConfig,
    load_config,
    load_global_config,
    load_global_config_file,
    write_global_config,
)
from repo_intel.core.env import load_project_env
from repo_intel.platform.home import ensure_repo_intel_home, global_config_path, global_env_path
from repo_intel.platform.workspace import WorkspaceResolutionError, resolve_workspace_path


app = typer.Typer(help="Manage repo-intel global configuration.")
env_app = typer.Typer(help="Manage repo-intel global environment secrets.")
app.add_typer(env_app, name="env")
console = Console()


@app.command()
def show(workspace: str | None = None, json_output: bool = False) -> None:
    """Show global or effective workspace configuration."""
    cfg = effective_config(workspace)
    payload = cfg.model_dump(mode="json")
    if json_output:
        console.print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    render_config_table("repo-intel Configuration", payload)


@app.command("get")
def get_value(key: str, workspace: str | None = None) -> None:
    """Read a dotted config value."""
    payload = effective_config(workspace).model_dump(mode="json")
    value = get_nested(payload, key)
    if value is None:
        console.print(f"[red]Unknown config key:[/red] {key}")
        raise typer.Exit(1)
    console.print(value)


@app.command("set")
def set_value(key: str, value: str) -> None:
    """Set a dotted global config value."""
    cfg = load_global_config_file()
    payload = cfg.model_dump(mode="json")
    if not set_nested(payload, key, parse_value(value)):
        console.print(f"[red]Unknown config key:[/red] {key}")
        raise typer.Exit(1)
    updated = AppConfig.model_validate(payload)
    path = write_global_config(updated)
    console.print(f"[green]Updated global config:[/green] {path}")


@app.command()
def doctor(workspace: str | None = None) -> None:
    """Validate effective configuration and local service connectivity."""
    cfg = effective_config(workspace)
    load_project_env()
    rows = validate_config(cfg, workspace)
    render_doctor_table(rows)


def validate_config(cfg: AppConfig, workspace: str | None = None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    rows.append(("global_config", "ok" if global_config_path().exists() else "missing", str(global_config_path())))
    rows.append(("global_env", "ok" if global_env_path().exists() else "missing", str(global_env_path())))
    if workspace:
        try:
            workspace_path = resolve_workspace_path(workspace)
            rows.append(("workspace", "ok", str(workspace_path)))
            rows.append(
                (
                    "workspace_config",
                    "ok" if (workspace_path / ".repo-intel" / "config.toml").exists() else "missing",
                    str(workspace_path / ".repo-intel" / "config.toml"),
                )
            )
        except WorkspaceResolutionError as exc:
            rows.append(("workspace", "error", str(exc)))

    models = check_ollama(cfg.embeddings.base_url, rows)
    check_model("embedding_model", cfg.embeddings.model, models, rows)
    check_model("llm_model", cfg.llm.model, models, rows)
    check_openrouter(cfg, rows)
    check_notebooklm(cfg, rows)
    return rows


def render_doctor_table(rows: list[tuple[str, str, str]]) -> None:
    table = Table(title="repo-intel Config Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for name, status, detail in rows:
        style = "green" if status == "ok" else "yellow" if status in {"missing", "skipped"} else "red"
        table.add_row(name, f"[{style}]{status}[/{style}]", detail)
    console.print(table)


@env_app.command("set")
def env_set(key: str, value: str) -> None:
    """Set a secret/value in ~/.repo-intel/.env."""
    path = write_env_value(key, value)
    console.print(f"[green]Updated env:[/green] {path}")


@env_app.command("list")
def env_list() -> None:
    """List configured global env keys without exposing secret values."""
    values = read_env_file()
    table = Table(title=f"repo-intel Env ({global_env_path()})")
    table.add_column("Key")
    table.add_column("Value")
    for key, value in sorted(values.items()):
        table.add_row(key, mask_value(value))
    console.print(table)
    if not values:
        console.print("[yellow]No global env values configured.[/yellow]")


def effective_config(workspace: str | None) -> AppConfig:
    if not workspace:
        return load_global_config()
    try:
        return load_config(resolve_workspace_path(workspace))
    except WorkspaceResolutionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def render_config_table(title: str, payload: dict[str, Any]) -> None:
    table = Table(title=title)
    table.add_column("Key")
    table.add_column("Value")
    for key, value in flatten(payload).items():
        table.add_row(key, json.dumps(value, ensure_ascii=False) if isinstance(value, list | dict) else str(value))
    console.print(table)


def flatten(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key, value in payload.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.update(flatten(value, full_key))
        else:
            rows[full_key] = value
    return rows


def get_nested(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_nested(payload: dict[str, Any], dotted_key: str, value: Any) -> bool:
    parts = dotted_key.split(".")
    current: Any = payload
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    current[parts[-1]] = value
    return True


def parse_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value


def check_ollama(base_url: str, rows: list[tuple[str, str, str]]) -> set[str]:
    status, detail, models = detect_ollama(base_url)
    rows.append(("ollama", status, detail))
    return models


def detect_ollama(base_url: str) -> tuple[str, str, set[str]]:
    normalized_url = base_url.rstrip("/")
    try:
        response = requests.get(f"{normalized_url}/api/tags", timeout=5)
        response.raise_for_status()
        models = {str(item.get("name", "")) for item in response.json().get("models", []) if item.get("name")}
        detail = f"{base_url} ({len(models)} model(s))"
        return "ok", detail, models
    except Exception as exc:
        return "error", f"{base_url}: {exc}", set()


def suggested_embedding_model(models: set[str]) -> str:
    for model in ("nomic-embed-text:latest", "nomic-embed-text"):
        if model_matches(model, models):
            return model
    embed_models = sorted(model for model in models if "embed" in model.lower())
    return embed_models[0] if embed_models else "nomic-embed-text"


def suggested_chat_model(models: set[str]) -> str:
    for model in ("qwen2.5:3b", "phi3:mini"):
        if model_matches(model, models):
            return model
    excluded = ("embed", "nomic")
    chat_models = sorted(model for model in models if not any(word in model.lower() for word in excluded))
    return chat_models[0] if chat_models else "phi3:mini"


def check_model(
    name: str,
    configured_model: str,
    available_models: set[str],
    rows: list[tuple[str, str, str]],
) -> None:
    if not available_models:
        rows.append((name, "skipped", configured_model))
        return
    if model_matches(configured_model, available_models):
        rows.append((name, "ok", configured_model))
        return
    rows.append((name, "error", f'{configured_model} not found. Run: ollama pull {configured_model}'))


def model_matches(model: str, available_models: set[str]) -> bool:
    if model in available_models:
        return True
    if ":" not in model and f"{model}:latest" in available_models:
        return True
    return False


def check_openrouter(cfg: AppConfig, rows: list[tuple[str, str, str]]) -> None:
    api_key = os.getenv(cfg.brief.api_key_env)
    if api_key:
        rows.append(("openrouter", "ok", f"{cfg.brief.api_key_env} is configured"))
    else:
        rows.append(
            (
                "openrouter",
                "skipped",
                f"{cfg.brief.api_key_env} is not set; required only for OpenRouter features",
            )
        )


def check_notebooklm(cfg: AppConfig, rows: list[tuple[str, str, str]]) -> None:
    command = cfg.notebooklm.cli_command
    path = shutil.which(command)
    if path:
        rows.append(("notebooklm", "ok", path))
    else:
        rows.append(("notebooklm", "skipped", f'{command} not installed; required only for notebooklm sync'))


def read_env_file() -> dict[str, str]:
    path = global_env_path()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_env_value(key: str, value: str) -> Path:
    ensure_repo_intel_home()
    path = global_env_path()
    values = read_env_file()
    values[key] = value
    content = "\n".join(f"{item_key}={item_value}" for item_key, item_value in sorted(values.items()))
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"
