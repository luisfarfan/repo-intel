"""Config invariants: no credential ever lands in a committable file, and the
provider wiring resolves to cliproxy with the right endpoint.

The security requirement is explicit: the cliproxy key is referenced by the NAME of an
environment variable (`api_key_env`), never by value. `assert_no_inline_secrets` turns
that convention into an enforced invariant; these tests pin the enforcement itself, not
just one happy-path rendering.

No network. `load_global_config_data` is neutralised wherever a test would otherwise
read the developer's real ~/.repo-intel/config.toml.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_intel.core.config import (
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    AppConfig,
    LlmConfig,
    apply_env_overrides,
    assert_no_inline_secrets,
    load_config,
    render_config,
    write_default_config,
)


@pytest.fixture(autouse=True)
def isolate_global_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic: never merge the developer's real global config into these assertions."""
    monkeypatch.setattr("repo_intel.core.config.load_global_config_data", lambda: {})


# --------------------------------------------------------------------------------------
# The secret invariant
# --------------------------------------------------------------------------------------


class LeakyLlmConfig(LlmConfig):
    """A future LlmConfig that grew a value-bearing credential field."""

    api_key: str = ""


class LeakyAppConfig(AppConfig):
    """Declares the leaky section as its field TYPE.

    This matters: pydantic v2 serializes by declared type, so merely assigning a
    subclass instance to `AppConfig.llm` drops the extra field before model_dump and
    the guard would never see it. The realistic leak -- someone adds `api_key` to the
    config model itself -- looks like this, and IS caught.
    """

    llm: LeakyLlmConfig = LeakyLlmConfig()


def test_inline_api_key_is_refused_by_the_guard() -> None:
    """The whole point of the guard: a literal key must never be serializable."""
    cfg = LeakyAppConfig(
        project_name="t",
        llm=LeakyLlmConfig(api_key="mm-f0000000000000000000000000000000000000"),
    )
    with pytest.raises(ValueError) as exc:
        assert_no_inline_secrets(cfg)
    assert "llm.api_key" in str(exc.value)


def test_render_config_refuses_to_serialize_an_inline_secret() -> None:
    """render_config is the actual write path -- the guard must fire there too."""
    cfg = LeakyAppConfig(project_name="t", llm=LeakyLlmConfig(api_key="mm-fdeadbeef"))
    with pytest.raises(ValueError):
        render_config(cfg)


def test_guard_reads_the_declared_schema_not_the_runtime_instance() -> None:
    """Documents a real limitation rather than hiding it.

    Assigning a subclass instance to a declared-type field hides the extra field from
    model_dump, so the guard cannot see it. That is acceptable because config is always
    built by validating a file into the declared models -- no such instance ever reaches
    the write path -- but it should be a known, asserted property, not a surprise.
    """
    cfg = AppConfig(project_name="t")
    cfg.llm = LeakyLlmConfig(api_key="mm-finvisible")
    assert "api_key" not in cfg.model_dump()["llm"]
    assert_no_inline_secrets(cfg)  # does not raise: the field is not in the dump
    assert "mm-finvisible" not in render_config(cfg)  # and never reaches the file


def test_rendered_config_never_contains_the_key_value() -> None:
    """Belt and braces: even with a real-looking key in the environment, the rendered
    file carries only the variable name."""
    cfg = AppConfig(project_name="t")
    cfg.llm.provider = "cliproxy"
    cfg.llm.base_url = "http://127.0.0.1:8317/v1"
    cfg.llm.model = "gemini-3-flash"
    cfg.llm.api_key_env = "CLIPROXY_API_KEY"

    rendered = render_config(cfg)
    assert 'api_key_env = "CLIPROXY_API_KEY"' in rendered
    assert "mm-f" not in rendered
    for forbidden in ("\napi_key =", "\ntoken =", "\nsecret =", "\npassword ="):
        assert forbidden not in rendered


@pytest.mark.parametrize("field", ["api_key", "auth_token", "client_secret", "db_password"])
def test_guard_catches_every_secret_shaped_field_name(field: str) -> None:
    """The pattern is (api_key|secret|token|password)$ -- a future field named any of
    these must not slip through."""

    section = type("LeakySection", (LlmConfig,), {"__annotations__": {field: str}, field: ""})
    app = type(
        "LeakyApp", (AppConfig,), {"__annotations__": {"llm": section}, "llm": section()}
    )
    cfg = app(project_name="t", llm=section(**{field: "leaked-value"}))

    with pytest.raises(ValueError) as exc:
        assert_no_inline_secrets(cfg)
    assert field in str(exc.value)


def test_guard_allows_env_indirection_fields() -> None:
    """`*_env` holds a NAME, not a value -- it must never trip the guard."""
    cfg = AppConfig(project_name="t")
    cfg.llm.api_key_env = "CLIPROXY_API_KEY"
    cfg.brief.api_key_env = "OPENROUTER_API_KEY"
    assert_no_inline_secrets(cfg)  # must not raise


def test_guard_ignores_empty_secret_field() -> None:
    """An unset field is not a leak; only a populated one is."""

    class LeakyLlmConfig(LlmConfig):
        api_key: str = ""

    cfg = AppConfig(project_name="t")
    cfg.llm = LeakyLlmConfig(api_key="")
    assert_no_inline_secrets(cfg)  # must not raise


# --------------------------------------------------------------------------------------
# cliproxy wiring resolves correctly through a real config file
# --------------------------------------------------------------------------------------


def test_cliproxy_config_round_trips_through_toml(tmp_path: Path) -> None:
    """End-to-end: what render_config writes is what load_config reads back."""
    cfg_dir = tmp_path / ".repo-intel"
    cfg_dir.mkdir(parents=True)

    source = AppConfig(project_name="proxima")
    source.llm.provider = "cliproxy"
    source.llm.base_url = "http://127.0.0.1:8317/v1"
    source.llm.model = "gemini-3-flash"
    source.llm.api_key_env = "CLIPROXY_API_KEY"
    source.embeddings.base_url = "http://127.0.0.1:11434"
    source.embeddings.model = "nomic-embed-text:latest"
    (cfg_dir / "config.toml").write_text(render_config(source), encoding="utf-8")

    loaded = load_config(tmp_path)
    assert loaded.llm.provider == "cliproxy"
    assert loaded.llm.base_url == "http://127.0.0.1:8317/v1"
    assert loaded.llm.model == "gemini-3-flash"
    assert loaded.llm.api_key_env == "CLIPROXY_API_KEY"
    # Embeddings stay local and separate -- they must NOT follow chat to cliproxy.
    assert loaded.embeddings.provider == "ollama"
    assert loaded.embeddings.base_url == "http://127.0.0.1:11434"


def test_repo_allowlist_round_trips_through_toml(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".repo-intel"
    cfg_dir.mkdir(parents=True)

    source = AppConfig(project_name="proxima")
    source.repos = ["proxima-api", "proxima-admin", "proxima-infra"]
    (cfg_dir / "config.toml").write_text(render_config(source), encoding="utf-8")

    assert load_config(tmp_path).repos == ["proxima-api", "proxima-admin", "proxima-infra"]


def test_repos_renders_as_a_single_editable_line() -> None:
    """Requirement: the repo list stays on ONE line so it is trivially editable."""
    cfg = AppConfig(project_name="t")
    cfg.repos = ["proxima-api", "proxima-admin"]
    repo_lines = [ln for ln in render_config(cfg).splitlines() if ln.startswith("repos =")]
    assert repo_lines == ['repos = ["proxima-api", "proxima-admin"]']


def test_env_var_overrides_llm_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_INTEL_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("REPO_INTEL_LLM_PROVIDER", "cliproxy")
    monkeypatch.setenv("REPO_INTEL_LLM_API_KEY_ENV", "OTHER_KEY_VAR")

    merged = apply_env_overrides(AppConfig(project_name="t").model_dump(mode="json"))
    cfg = AppConfig.model_validate(merged)
    assert cfg.llm.base_url == "http://127.0.0.1:9999/v1"
    assert cfg.llm.provider == "cliproxy"
    assert cfg.llm.api_key_env == "OTHER_KEY_VAR"


def test_env_override_carries_a_name_not_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is deliberately no REPO_INTEL_LLM_API_KEY: the key has no config path at
    all, only the variable name does."""
    monkeypatch.setenv("REPO_INTEL_LLM_API_KEY", "mm-fleaked")
    merged = apply_env_overrides(AppConfig(project_name="t").model_dump(mode="json"))
    assert "api_key" not in merged["llm"]
    assert merged["llm"]["api_key_env"] == "CLIPROXY_API_KEY"


# --------------------------------------------------------------------------------------
# Default corpus configuration
# --------------------------------------------------------------------------------------


def test_default_config_includes_openspec(tmp_path: Path) -> None:
    """REGRESSION: the shipped default must index openspec out of the box."""
    write_default_config(tmp_path)
    cfg = load_config(tmp_path)
    assert "openspec/**/*.md" in cfg.docs.include


def test_default_config_excludes_openspec_archive(tmp_path: Path) -> None:
    write_default_config(tmp_path)
    cfg = load_config(tmp_path)
    assert "openspec/changes/archive/**" in cfg.docs.exclude


def test_default_include_covers_flat_and_nested_docs() -> None:
    """REGRESSION: `docs/**/*.md` alone dropped flat files like docs/api-conventions.md."""
    assert "docs/*.md" in DEFAULT_INCLUDE
    assert "docs/**/*.md" in DEFAULT_INCLUDE


def test_source_directories_are_excluded_by_default() -> None:
    for pattern in ("src/**", "node_modules/**", "tests/**"):
        assert pattern in DEFAULT_EXCLUDE


def test_default_repos_is_empty_for_backwards_compatibility() -> None:
    """Shipping a non-empty default would silently blank out existing workspaces."""
    assert AppConfig(project_name="t").repos == []


# --------------------------------------------------------------------------------------
# The inline-secret guard must cover the whole file, and the read path too
# --------------------------------------------------------------------------------------


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".repo-intel" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_guard_catches_a_secret_at_the_top_level_of_the_file(tmp_path: Path) -> None:
    """The guard used to skip every non-dict value, so a secret sitting at the same level
    as `project_name` -- outside any [section] -- was never inspected at all."""
    write_config(tmp_path, 'project_name = "t"\napi_key = "mm-fleaked"\n')

    with pytest.raises(ValueError, match="inline secret"):
        load_config(tmp_path)


def test_guard_runs_on_the_read_path_not_only_on_write(tmp_path: Path) -> None:
    """A hand-edited or committed config.toml never passes through render_config, so a
    write-only check is blind to exactly the file a reviewer would care about."""
    write_config(tmp_path, 'project_name = "t"\n\n[llm]\napi_key = "mm-fleaked"\n')

    with pytest.raises(ValueError, match="inline secret"):
        load_config(tmp_path)


def test_guard_catches_secrets_under_undeclared_keys(tmp_path: Path) -> None:
    """Checking a validated AppConfig cannot see these: pydantic drops the unknown field
    while the plaintext value stays in the file. The guard reads the raw TOML instead."""
    write_config(tmp_path, 'project_name = "t"\n\n[whatever]\naccess_token = "mm-fleaked"\n')

    with pytest.raises(ValueError, match="inline secret"):
        load_config(tmp_path)


def test_guard_allows_the_env_indirection(tmp_path: Path) -> None:
    """The whole point: the NAME of the variable is safe to commit, the value is not."""
    write_config(tmp_path, 'project_name = "t"\n\n[llm]\napi_key_env = "CLIPROXY_API_KEY"\n')

    assert load_config(tmp_path).llm.api_key_env == "CLIPROXY_API_KEY"


def test_resolved_env_secrets_do_not_trip_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard inspects the file's own contents, before env overrides are layered in.
    A secret resolved from the environment at runtime is legitimate and must load."""
    monkeypatch.setenv("CLIPROXY_API_KEY", "mm-freal-key-value")
    write_config(tmp_path, 'project_name = "t"\n\n[llm]\napi_key_env = "CLIPROXY_API_KEY"\n')

    assert load_config(tmp_path).project_name == "t"
