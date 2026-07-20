from __future__ import annotations

import json
import re
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
    "DECISIONS.md",
    # NOTE: match_path falls back to fnmatch, whose "*" crosses "/". That makes
    # "docs/**/*.md" behave recursively BUT still require at least one intermediate
    # directory -- so a flat "docs/api-conventions.md" matched NOTHING. That silently
    # dropped most canonical per-repo docs. "docs/*.md" is the fix; keep both.
    "docs/*.md",
    "docs/**/*.md",
    # Same two shapes for docs/ nested under a subproject (e.g. "harness/docs/...").
    "**/docs/*.md",
    "docs_*/**/*.md",
    # OpenSpec is the primary source of truth for this ecosystem: living capability
    # specs plus the active (non-archived) change proposals. The archive is excluded
    # in DEFAULT_EXCLUDE -- see the comment there.
    "openspec/**/*.md",
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
    # Archived OpenSpec changes are superseded history: 1777 of the 2528 openspec
    # markdown files in this ecosystem (70%). They are near-duplicates of the living
    # specs in embedding space and would dominate retrieval with stale content.
    # Living truth (openspec/specs/**) and active proposals (openspec/changes/<name>/**)
    # stay indexed. Remove this line if you deliberately want historical recall.
    "openspec/changes/archive/**",
]

# Repositories to index. Empty list means "index everything discovered", which is the
# back-compatible behaviour. The PROXIMA workspace pins this to the active repos only.
DEFAULT_REPOS: list[str] = []


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
    # NAME of the environment variable holding the API key -- never the key itself.
    # The value lives in ~/.repo-intel/.env (chmod 600) or the process environment.
    api_key_env: str = "CLIPROXY_API_KEY"
    temperature: float = 0.1
    context_chunks: int = 5
    num_predict: int = 700


class BriefConfig(BaseModel):
    provider: str = "openrouter"
    model: str = "meta-llama/llama-3.1-8b-instruct"
    # OpenAI-compatible base URL, i.e. including the /v1 suffix. Only used when the
    # provider is openrouter; provider = "cliproxy" reuses the [llm] endpoint.
    base_url: str = "https://openrouter.ai/api/v1"
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
    repos: list[str] = Field(default_factory=lambda: list(DEFAULT_REPOS))
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
        file_data = tomllib.loads(path.read_text(encoding="utf-8"))
        # Guard the READ path too, not just render_config's write path. A config.toml
        # can be hand-edited or arrive via a commit, and a write-only check never sees
        # those. Validate the file's own contents, before env overrides are layered in
        # -- resolved env values are legitimately secret and must not trip the guard.
        assert_no_inline_secrets_data(file_data, source=str(path))
        merged = deep_merge(merged, file_data)
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


SECRET_FIELD_PATTERN = re.compile(r"(api_key|secret|token|password)$", re.IGNORECASE)


def assert_no_inline_secrets_data(data: dict[str, Any], source: str) -> None:
    """Same rule as `assert_no_inline_secrets`, applied to raw parsed TOML.

    Operates on the dict rather than a validated AppConfig so that it also catches
    secrets under keys the model does not declare -- an undeclared `[llm] api_key = "..."`
    is dropped by pydantic and would otherwise be invisible to a model-based check while
    still sitting in plaintext in the file.
    """
    for name, value in data.items():
        if isinstance(value, dict):
            for field, inner in value.items():
                if not field.endswith("_env") and SECRET_FIELD_PATTERN.search(field) and inner:
                    raise ValueError(
                        f"{source} contains an inline secret at '{name}.{field}'. Replace it "
                        f"with '{field}_env = \"<ENV_VAR_NAME>\"' and put the value in "
                        "~/.repo-intel/.env."
                    )
        elif not name.endswith("_env") and SECRET_FIELD_PATTERN.search(name) and value:
            raise ValueError(
                f"{source} contains an inline secret at '{name}'. Replace it with "
                f"'{name}_env = \"<ENV_VAR_NAME>\"' and put the value in ~/.repo-intel/.env."
            )


def assert_no_inline_secrets(cfg: AppConfig) -> None:
    """Fail loudly if a literal credential ever reaches a committable config file.

    The convention is indirection: config.toml stores `*_env` (the NAME of an
    environment variable), never the value. This enforces it in code rather than
    by discipline, so a future field named `api_key` cannot silently leak.
    """
    def check(qualified_name: str, field: str, value: object) -> None:
        if field.endswith("_env"):
            return
        if SECRET_FIELD_PATTERN.search(field) and value:
            raise ValueError(
                f"Refusing to handle secret-bearing field '{qualified_name}' in a config "
                "file. Store the variable NAME in a '*_env' field and keep the value in "
                "~/.repo-intel/.env instead."
            )

    for name, value in cfg.model_dump().items():
        if isinstance(value, dict):
            for field, inner in value.items():
                check(f"{name}.{field}", field, inner)
        else:
            # Top-level scalars were previously skipped by the `isinstance(dict)` guard,
            # so a secret sitting at the same level as `project_name` passed unnoticed.
            check(name, name, value)


def render_config(cfg: AppConfig) -> str:
    assert_no_inline_secrets(cfg)
    return "\n".join(
        [
            f'project_name = "{cfg.project_name}"',
            "# Repositories to index. Empty list = index everything discovered.",
            f"repos = {json.dumps(cfg.repos)}",
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
            f'api_key_env = "{cfg.llm.api_key_env}"',
            f"temperature = {cfg.llm.temperature}",
            f"context_chunks = {cfg.llm.context_chunks}",
            f"num_predict = {cfg.llm.num_predict}",
            "",
            "[brief]",
            f'provider = "{cfg.brief.provider}"',
            f'model = "{cfg.brief.model}"',
            f'base_url = "{cfg.brief.base_url}"',
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
        "REPO_INTEL_LLM_API_KEY_ENV": ("llm", "api_key_env"),
        "REPO_INTEL_BRIEF_PROVIDER": ("brief", "provider"),
        "REPO_INTEL_BRIEF_MODEL": ("brief", "model"),
        "REPO_INTEL_BRIEF_BASE_URL": ("brief", "base_url"),
        "REPO_INTEL_BRIEF_API_KEY_ENV": ("brief", "api_key_env"),
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
