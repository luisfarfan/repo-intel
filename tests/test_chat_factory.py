from __future__ import annotations

import pytest

from repo_intel.core.config import AppConfig
from repo_intel.enrichers.factory import (
    UnknownProviderError,
    build_ask_client,
    build_brief_client,
)
from repo_intel.enrichers.ollama_chat import OllamaChatClient
from repo_intel.enrichers.openai_compat_chat import OpenAICompatChatClient


def make_config(**llm: object) -> AppConfig:
    cfg = AppConfig(project_name="t")
    for key, value in llm.items():
        setattr(cfg.llm, key, value)
    return cfg


def test_ollama_provider_builds_native_client() -> None:
    cfg = make_config(provider="ollama", base_url="http://127.0.0.1:11434", model="phi3:mini")
    client = build_ask_client(cfg)
    assert isinstance(client, OllamaChatClient)
    assert client.base_url == "http://127.0.0.1:11434"


def test_cliproxy_provider_builds_openai_compatible_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPROXY_API_KEY", "test-key")
    cfg = make_config(
        provider="cliproxy",
        base_url="http://127.0.0.1:8317/v1",
        model="gemini-3-flash",
        api_key_env="CLIPROXY_API_KEY",
    )
    client = build_ask_client(cfg)
    assert isinstance(client, OpenAICompatChatClient)
    assert client.base_url == "http://127.0.0.1:8317/v1"
    assert client.model == "gemini-3-flash"


def test_unknown_provider_raises_instead_of_silently_using_ollama() -> None:
    cfg = make_config(provider="definitely-not-a-provider")
    with pytest.raises(UnknownProviderError) as exc:
        build_ask_client(cfg)
    assert "definitely-not-a-provider" in str(exc.value)


def test_missing_api_key_raises_with_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # The client calls load_project_env(), which reads ~/.repo-intel/.env. Without
    # stubbing that out this test passes or fails depending on whether the developer
    # happens to have a real key on disk -- it silently started failing the moment a
    # global .env existed. Neutralise the dotenv load so the assertion is hermetic.
    monkeypatch.setattr("repo_intel.enrichers.openai_compat_chat.load_project_env", lambda: None)
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    cfg = make_config(provider="cliproxy", base_url="http://127.0.0.1:8317/v1", api_key_env="CLIPROXY_API_KEY")
    with pytest.raises(RuntimeError) as exc:
        build_ask_client(cfg)
    assert "CLIPROXY_API_KEY" in str(exc.value)


def test_num_predict_maps_to_max_tokens_on_openai_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPROXY_API_KEY", "test-key")
    cfg = make_config(provider="cliproxy", base_url="http://x/v1", api_key_env="CLIPROXY_API_KEY", num_predict=1234)
    assert build_ask_client(cfg).max_tokens == 1234


def test_brief_cliproxy_reuses_llm_endpoint_and_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPROXY_API_KEY", "test-key")
    cfg = make_config(provider="cliproxy", base_url="http://127.0.0.1:8317/v1", api_key_env="CLIPROXY_API_KEY")
    cfg.brief.provider = "cliproxy"
    cfg.brief.model = "gemini-3-flash"
    client = build_brief_client(cfg)
    assert isinstance(client, OpenAICompatChatClient)
    assert client.base_url == "http://127.0.0.1:8317/v1"


def test_brief_openrouter_uses_its_own_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = make_config(provider="cliproxy", base_url="http://127.0.0.1:8317/v1")
    cfg.brief.provider = "openrouter"
    client = build_brief_client(cfg)
    assert client.base_url == "https://openrouter.ai/api/v1"


def test_openai_response_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPROXY_API_KEY", "test-key")
    client = OpenAICompatChatClient(
        model="m", base_url="http://x/v1", api_key_env="CLIPROXY_API_KEY"
    )

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "  hello  "}}]}

    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("repo_intel.enrichers.openai_compat_chat.requests.post", fake_post)
    assert client.generate("q") == "hello"
    assert captured["url"] == "http://x/v1/chat/completions"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer test-key"


def test_401_is_translated_to_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPROXY_API_KEY", "bad")
    client = OpenAICompatChatClient(
        model="m", base_url="http://x/v1", api_key_env="CLIPROXY_API_KEY"
    )

    class FakeResponse:
        status_code = 401

    monkeypatch.setattr(
        "repo_intel.enrichers.openai_compat_chat.requests.post",
        lambda url, **kwargs: FakeResponse(),
    )
    with pytest.raises(RuntimeError) as exc:
        client.generate("q")
    assert "CLIPROXY_API_KEY" in str(exc.value)


def test_config_never_serializes_a_literal_key() -> None:
    from repo_intel.core.config import render_config

    cfg = AppConfig(project_name="t")
    cfg.llm.provider = "cliproxy"
    cfg.llm.api_key_env = "CLIPROXY_API_KEY"
    rendered = render_config(cfg)
    assert 'api_key_env = "CLIPROXY_API_KEY"' in rendered
    # the NAME is serialized, never a value-bearing `api_key = ...`
    assert "\napi_key =" not in rendered
