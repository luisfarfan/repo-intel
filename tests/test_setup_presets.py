"""Setup presets: the `proxima` preset must not resurrect the dead embeddings host,
and must keep chat and embeddings on separate endpoints.

REGRESSION: the preset hardcoded http://192.168.1.12:11434 for BOTH embeddings and
chat. That machine stopped responding, which took repo-intel down entirely -- no
embeddings, therefore no ingest and no query. The fix points embeddings at local Ollama
and chat at the local cliproxy gateway, which requires the two to be decoupled.
"""

from __future__ import annotations

import pytest

from repo_intel.cli.setup import PRESET_VALUES, PRESETS, SetupPreset, apply_preset
from repo_intel.core.config import AppConfig

DEAD_HOST = "192.168.1.12"


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_no_preset_references_the_dead_host(name: str) -> None:
    """REGRESSION: this host is unreachable; any preset pointing at it is broken."""
    preset = PRESET_VALUES[name]
    assert DEAD_HOST not in preset.ollama_url
    assert DEAD_HOST not in preset.chat_url


def test_proxima_preset_keeps_embeddings_local() -> None:
    """Embeddings stay on local Ollama: free, private, and no network hop."""
    cfg = AppConfig(project_name="proxima")
    apply_preset(cfg, "proxima")
    assert cfg.embeddings.base_url == "http://127.0.0.1:11434"
    assert cfg.embeddings.model == "nomic-embed-text:latest"
    assert cfg.embeddings.provider == "ollama"


def test_proxima_preset_points_chat_at_cliproxy() -> None:
    cfg = AppConfig(project_name="proxima")
    apply_preset(cfg, "proxima")
    assert cfg.llm.provider == "cliproxy"
    assert cfg.llm.base_url == "http://127.0.0.1:8317/v1"
    assert cfg.llm.model == "gemini-3-flash"


def test_proxima_preset_decouples_chat_from_embeddings() -> None:
    """REGRESSION: apply_preset forced one URL onto both, so a preset could not put
    chat on a different host than embeddings -- which is exactly the cliproxy setup."""
    cfg = AppConfig(project_name="proxima")
    apply_preset(cfg, "proxima")
    assert cfg.llm.base_url != cfg.embeddings.base_url


def test_cliproxy_base_url_carries_the_v1_suffix() -> None:
    """The gateway is OpenAI-compatible: the client appends /chat/completions, so a
    base_url without /v1 yields a 404. This is the single most common misconfiguration."""
    assert PRESET_VALUES["proxima"].chat_url.endswith("/v1")


def test_preset_never_carries_an_api_key() -> None:
    """Presets are code; a credential here would be committed. The key is resolved at
    runtime from the env var named by config.llm.api_key_env."""
    fields = SetupPreset.__dataclass_fields__
    assert not any("key" in name or "secret" in name or "token" in name for name in fields)


def test_proxima_preset_leaves_api_key_env_indirection_intact() -> None:
    cfg = AppConfig(project_name="proxima")
    apply_preset(cfg, "proxima")
    assert cfg.llm.api_key_env == "CLIPROXY_API_KEY"


def test_single_host_presets_default_chat_to_the_ollama_url() -> None:
    """Back-compat: presets that do not split hosts keep the old single-endpoint shape."""
    for name in ("local", "minimal", "remote-ollama"):
        preset = PRESET_VALUES[name]
        assert preset.chat_url == preset.ollama_url
        assert preset.llm_provider == "ollama"


def test_local_preset_does_not_silently_become_cliproxy() -> None:
    cfg = AppConfig(project_name="t")
    apply_preset(cfg, "local")
    assert cfg.llm.provider == "ollama"
    assert cfg.llm.base_url == "http://localhost:11434"


# --------------------------------------------------------------------------------------
# Secrets must never be reachable through argv
# --------------------------------------------------------------------------------------


def test_setup_exposes_no_api_key_flag() -> None:
    """A secret passed as a CLI argument is readable by any local process via `ps` for
    the lifetime of the command, and is written verbatim into shell history. The safe
    path already exists (hidden prompt + a 0600 .env), so the flag was purely an
    alternative insecure route to something already done correctly."""
    import inspect

    from repo_intel.cli.main import setup

    assert "openrouter_api_key" not in inspect.signature(setup).parameters


def test_run_setup_accepts_no_api_key_argument() -> None:
    """Closing the flag at the CLI layer is not enough if the callee still takes one --
    the next person to add a command would wire it straight back up."""
    import inspect

    from repo_intel.cli.setup import run_setup

    assert "openrouter_api_key" not in inspect.signature(run_setup).parameters
