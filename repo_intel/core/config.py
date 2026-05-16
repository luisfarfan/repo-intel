from __future__ import annotations

import tomllib
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from repo_intel.platform.home import ensure_repo_intel_home, global_config_path


DEFAULT_INCLUDE = [
    "AI_INDEX.md",
    "AGENT_START_HERE.md",
    "CURSOR_HANDOFF.md",
    "CLAUDE.md",
    "README.md",
    "PRODUCT.md",
    "DESIGN.md",
    "*SPEC*.md",
    "*ARCHITECTURE*.md",
    "*CONTRACT*.md",
    "docs/**/*.md",
    "docs_*/**/*.md",
]

DEFAULT_EXCLUDE = [
    "src/**",
    "app/**",
    "lib/**",
    "packages/*/src/**",
    "tests/**",
    "migrations/**",
    "scripts/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".agents/**",
    ".claude/**",
    ".venv/**",
    "workspace/**",
]


class DocsConfig(BaseModel):
    mode: str = "sdd_only"
    include: list[str] = Field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDE))


class EmbeddingsConfig(BaseModel):
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"


class LlmConfig(BaseModel):
    provider: str = "ollama"
    model: str = "phi3:mini"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.1
    context_chunks: int = 5
    num_predict: int = 700


class BriefConfig(BaseModel):
    provider: str = "openrouter"
    model: str = "meta-llama/llama-3.1-8b-instruct"
    api_key_env: str = "OPENROUTER_API_KEY"
    site_url: str = "http://localhost"
    app_name: str = "repo-intelligence-cli"
    max_input_chars: int = 60000
    max_output_tokens: int = 1800
    temperature: float = 0.2
    fallback_provider: str = "ollama"
    fallback_model: str = "phi3:mini"


class StorageConfig(BaseModel):
    sqlite_path: str = ".repo-intel/knowledge.db"
    chroma_path: str = ".repo-intel/chroma"
    collection: str = "sdd_knowledge"


class ObsidianConfig(BaseModel):
    vault_path: str = ".repo-intel/obsidian-vault"
    generated_root: str = "_repo-intel"
    use_dataview: bool = True
    use_mermaid: bool = True


class NotebookLmConfig(BaseModel):
    enabled: bool = False
    notebook_title: str | None = None
    source_root: str = ".repo-intel/notebooklm/sources"
    manifest_path: str = ".repo-intel/notebooklm/manifest.json"
    cli_command: str = "notebooklm"
    timeout_seconds: int = 300
    max_source_chars: int = 180000


class AppConfig(BaseModel):
    project_name: str
    docs: DocsConfig = Field(default_factory=DocsConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    brief: BriefConfig = Field(default_factory=BriefConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    notebooklm: NotebookLmConfig = Field(default_factory=NotebookLmConfig)

    @classmethod
    def default(cls, workspace: Path) -> "AppConfig":
        return cls(project_name=workspace.name)


def config_path(workspace: Path) -> Path:
    return workspace / ".repo-intel" / "config.toml"


def load_config(workspace: Path) -> AppConfig:
    base = AppConfig.default(workspace).model_dump(mode="json")
    global_data = load_global_config_data()
    global_data.pop("project_name", None)
    merged = deep_merge(base, global_data)

    path = config_path(workspace)
    if path.exists():
        merged = deep_merge(merged, tomllib.loads(path.read_text(encoding="utf-8")))
    merged = apply_env_overrides(merged)
    return AppConfig.model_validate(merged)


def write_default_config(workspace: Path) -> Path:
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    cfg = AppConfig.default(workspace)
    path.write_text(render_config(cfg), encoding="utf-8")
    return path


def load_global_config() -> AppConfig:
    data = load_global_config_file().model_dump(mode="json")
    data = apply_env_overrides(data)
    return AppConfig.model_validate(data)


def load_global_config_file() -> AppConfig:
    data = AppConfig.default(Path("workspace")).model_dump(mode="json")
    data = deep_merge(data, load_global_config_data())
    return AppConfig.model_validate(data)


def load_global_config_data() -> dict[str, Any]:
    path = global_config_path()
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text or text.startswith("# repo-intel global configuration"):
        return {}
    return tomllib.loads(text)


def write_global_config(cfg: AppConfig) -> Path:
    ensure_repo_intel_home()
    path = global_config_path()
    path.write_text(render_config(cfg), encoding="utf-8")
    return path


def render_config(cfg: AppConfig) -> str:
    return "\n".join(
        [
            f'project_name = "{cfg.project_name}"',
            "",
            "[docs]",
            f'mode = "{cfg.docs.mode}"',
            "include = [",
            *[f'  "{item}",' for item in cfg.docs.include],
            "]",
            "exclude = [",
            *[f'  "{item}",' for item in cfg.docs.exclude],
            "]",
            "",
            "[embeddings]",
            f'provider = "{cfg.embeddings.provider}"',
            f'model = "{cfg.embeddings.model}"',
            f'base_url = "{cfg.embeddings.base_url}"',
            "",
            "[llm]",
            f'provider = "{cfg.llm.provider}"',
            f'model = "{cfg.llm.model}"',
            f'base_url = "{cfg.llm.base_url}"',
            f"temperature = {cfg.llm.temperature}",
            f"context_chunks = {cfg.llm.context_chunks}",
            f"num_predict = {cfg.llm.num_predict}",
            "",
            "[brief]",
            f'provider = "{cfg.brief.provider}"',
            f'model = "{cfg.brief.model}"',
            f'api_key_env = "{cfg.brief.api_key_env}"',
            f'site_url = "{cfg.brief.site_url}"',
            f'app_name = "{cfg.brief.app_name}"',
            f"max_input_chars = {cfg.brief.max_input_chars}",
            f"max_output_tokens = {cfg.brief.max_output_tokens}",
            f"temperature = {cfg.brief.temperature}",
            f'fallback_provider = "{cfg.brief.fallback_provider}"',
            f'fallback_model = "{cfg.brief.fallback_model}"',
            "",
            "[storage]",
            f'sqlite_path = "{cfg.storage.sqlite_path}"',
            f'chroma_path = "{cfg.storage.chroma_path}"',
            f'collection = "{cfg.storage.collection}"',
            "",
            "[obsidian]",
            f'vault_path = "{cfg.obsidian.vault_path}"',
            f'generated_root = "{cfg.obsidian.generated_root}"',
            f"use_dataview = {str(cfg.obsidian.use_dataview).lower()}",
            f"use_mermaid = {str(cfg.obsidian.use_mermaid).lower()}",
            "",
            "[notebooklm]",
            f"enabled = {str(cfg.notebooklm.enabled).lower()}",
            f"notebook_title = {toml_string_or_none(cfg.notebooklm.notebook_title)}",
            f'source_root = "{cfg.notebooklm.source_root}"',
            f'manifest_path = "{cfg.notebooklm.manifest_path}"',
            f'cli_command = "{cfg.notebooklm.cli_command}"',
            f"timeout_seconds = {cfg.notebooklm.timeout_seconds}",
            f"max_source_chars = {cfg.notebooklm.max_source_chars}",
            "",
        ]
    )


def resolve_workspace_path(workspace: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else workspace / path


def toml_string_or_none(value: str | None) -> str:
    if value is None:
        return '""'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    env_map = {
        "REPO_INTEL_EMBEDDINGS_PROVIDER": ("embeddings", "provider"),
        "REPO_INTEL_EMBEDDINGS_MODEL": ("embeddings", "model"),
        "REPO_INTEL_EMBEDDINGS_BASE_URL": ("embeddings", "base_url"),
        "REPO_INTEL_LLM_PROVIDER": ("llm", "provider"),
        "REPO_INTEL_LLM_MODEL": ("llm", "model"),
        "REPO_INTEL_LLM_BASE_URL": ("llm", "base_url"),
        "REPO_INTEL_BRIEF_PROVIDER": ("brief", "provider"),
        "REPO_INTEL_BRIEF_MODEL": ("brief", "model"),
        "REPO_INTEL_NOTEBOOKLM_CLI_COMMAND": ("notebooklm", "cli_command"),
    }
    merged = dict(data)
    for env_name, path in env_map.items():
        value = os.getenv(env_name)
        if not value:
            continue
        section, key = path
        section_data = dict(merged.get(section, {}))
        section_data[key] = value
        merged[section] = section_data
    return merged
