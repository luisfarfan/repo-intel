from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


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
    model: str = "nomic-embed-text:latest"
    base_url: str = "http://192.168.1.12:11434"


class LlmConfig(BaseModel):
    provider: str = "ollama"
    model: str = "phi3:mini"
    base_url: str = "http://192.168.1.12:11434"
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


class AppConfig(BaseModel):
    project_name: str
    docs: DocsConfig = Field(default_factory=DocsConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    brief: BriefConfig = Field(default_factory=BriefConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)

    @classmethod
    def default(cls, workspace: Path) -> "AppConfig":
        return cls(project_name=workspace.name)


def config_path(workspace: Path) -> Path:
    return workspace / ".repo-intel" / "config.toml"


def load_config(workspace: Path) -> AppConfig:
    path = config_path(workspace)
    if not path.exists():
        return AppConfig.default(workspace)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


def write_default_config(workspace: Path) -> Path:
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    cfg = AppConfig.default(workspace)
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
        ]
    )


def resolve_workspace_path(workspace: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else workspace / path
