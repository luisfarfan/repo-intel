"""Regression tests for the embedding-overflow failure.

A real 7544-char chunk in the PROXIMA corpus made Ollama return
    400 {"error": "the input length exceeds the context length"}
The exception propagated into the ingest batch loop, which did `break` -- so a single
oversized chunk left 808 of 7848 chunks (~10% of the corpus) unembedded, reported only
as a one-line warning. These tests pin both halves of the fix.
"""

from __future__ import annotations

import pytest
import requests

from repo_intel.enrichers.ollama_embeddings import (
    DOCUMENT_PREFIX,
    MAX_EMBED_CHARS,
    QUERY_PREFIX,
    OllamaEmbeddingClient,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


def install_fake_post(monkeypatch: pytest.MonkeyPatch, handler) -> list[str]:
    """Route requests.post through `handler`, recording every input sent."""
    seen: list[str] = []

    def fake_post(url: str, json: dict, timeout: int) -> FakeResponse:  # noqa: A002
        seen.append(json["input"])
        return handler(json["input"])

    monkeypatch.setattr(requests, "post", fake_post)
    return seen


def ok_response(_: str) -> FakeResponse:
    return FakeResponse(200, {"embeddings": [[0.1, 0.2, 0.3]]})


def overflow_above(limit: int):
    """Succeed only when the input is at or below `limit` chars."""

    def handler(text: str) -> FakeResponse:
        if len(text) > limit:
            return FakeResponse(400, {"error": "the input length exceeds the context length"})
        return ok_response(text)

    return handler


def test_oversized_input_is_capped_before_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = install_fake_post(monkeypatch, ok_response)
    client = OllamaEmbeddingClient("http://x", "nomic-embed-text")

    client.embed("a" * 50_000)

    # The BODY is what the cap applies to. nomic models also carry a task prefix, and the
    # prefix must survive truncation (truncate first, then prefix) — a cap that ate the
    # prefix would silently drop the model back to its un-prefixed, near-random ranking.
    assert seen[0].startswith(DOCUMENT_PREFIX)
    assert len(seen[0]) == len(DOCUMENT_PREFIX) + MAX_EMBED_CHARS


def test_query_and_document_get_different_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mixing the two sides is the failure mode this exists to prevent."""
    seen = install_fake_post(monkeypatch, ok_response)
    client = OllamaEmbeddingClient("http://x", "nomic-embed-text")

    client.embed("passage")
    client.embed_query("question")

    assert seen[0] == f"{DOCUMENT_PREFIX}passage"
    assert seen[1] == f"{QUERY_PREFIX}question"


def test_non_nomic_model_gets_no_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prefixes are nomic-specific; a model not trained with them would be hurt."""
    seen = install_fake_post(monkeypatch, ok_response)
    client = OllamaEmbeddingClient("http://x", "mxbai-embed-large")

    client.embed("passage")
    client.embed_query("question")

    assert seen == ["passage", "question"]


def test_context_overflow_is_retried_with_halved_input(monkeypatch: pytest.MonkeyPatch) -> None:
    # Model window smaller than the proactive cap -> the reactive path must engage.
    seen = install_fake_post(monkeypatch, overflow_above(1000))
    client = OllamaEmbeddingClient("http://x", "nomic-embed-text")

    vector = client.embed("a" * 50_000)

    assert vector == [0.1, 0.2, 0.3]
    assert len(seen) > 1, "expected at least one retry"
    assert [len(s) for s in seen] == sorted((len(s) for s in seen), reverse=True)
    assert len(seen[-1]) <= 1000


def test_non_overflow_400_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only context-length overflow is recoverable; other 400s must surface."""
    seen = install_fake_post(monkeypatch, lambda _: FakeResponse(400, {"error": "bad model"}))
    client = OllamaEmbeddingClient("http://x", "nomic-embed-text")

    with pytest.raises(requests.HTTPError):
        client.embed("hello")

    assert len(seen) == 1, "a non-overflow error must not trigger the halving loop"


def test_halving_gives_up_instead_of_looping_forever(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = install_fake_post(monkeypatch, overflow_above(0))
    client = OllamaEmbeddingClient("http://x", "nomic-embed-text")

    with pytest.raises(requests.HTTPError):
        client.embed("a" * 50_000)

    assert len(seen) < 40, "halving must terminate, not spin"
    assert len(seen[-1]) <= 256
