from __future__ import annotations

import requests


# nomic-embed-text has a 2048-token context. Markdown/code averages well under
# 4 chars/token, so a chunk can be under any token-ish heuristic and still overflow.
# A real 7544-char chunk from the PROXIMA corpus returned
#   400 {"error":"the input length exceeds the context length"}
# and aborted the whole ingest. This cap is the proactive guard; embed() also
# retries reactively so a different model's smaller window can't wedge us either.
MAX_EMBED_CHARS = 6000


# Nomic's embedding models are trained with task prefixes and expect them at inference:
# stored passages get "search_document: ", the query gets "search_query: ". Leaving them out
# does not fail — it silently collapses the score spread, which is far worse than an error
# because retrieval keeps "working" while ranking near-randomly.
#
# Measured on this corpus, query "reglas para elegir el revision id de una migración de
# Alembic, patrón hex secuencial", comparing the AGENTS.md guardrail that answers it against
# an unrelated doc about section variants:
#     without prefixes:  0.7559 vs 0.7494  -> margin +0.0065  (noise; ranking is a coin flip)
#     with prefixes:     0.7443 vs 0.6814  -> margin +0.0629  (~10x the separation)
# The guardrail was unreachable in practice because of this, not because of chunk size.
#
# Applied per model: a model not trained with these prefixes would be hurt by them, so only
# the nomic family gets them.
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "


class OllamaEmbeddingClient:
    def __init__(self, base_url: str, model: str, max_chars: int = MAX_EMBED_CHARS) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_chars = max_chars

    @property
    def uses_task_prefixes(self) -> bool:
        return "nomic" in self.model.lower()

    def _prefixed(self, text: str, prefix: str) -> str:
        # Truncate FIRST, then prefix: prefixing first would let a long chunk push the
        # prefix past max_chars, which is exactly the case where it must survive.
        body = text[: self.max_chars]
        return f"{prefix}{body}" if self.uses_task_prefixes else body

    def embed(self, text: str) -> list[float]:
        """Embed a stored passage. Use `embed_query` for the retrieval side."""
        return self._embed_with_backoff(self._prefixed(text, DOCUMENT_PREFIX))

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query. Must pair with `embed` — mixing the two collapses scores."""
        return self._embed_with_backoff(self._prefixed(text, QUERY_PREFIX))

    def _embed_with_backoff(self, text: str) -> list[float]:
        """Embed, halving the input on context-length overflow.

        Truncating loses the tail of an outsized chunk, which is strictly better than
        the previous behaviour: a single overflowing chunk raised, and the caller's
        batch loop stopped, leaving every later chunk unembedded.
        """
        attempt = text
        while True:
            try:
                return self._embed_once(attempt)
            except requests.HTTPError as exc:
                overflow = (
                    exc.response is not None
                    and exc.response.status_code == 400
                    and "context length" in ollama_error(exc.response).lower()
                )
                if not overflow or len(attempt) <= 256:
                    raise
                attempt = attempt[: len(attempt) // 2]

    def _embed_once(self, text: str) -> list[float]:
        response = requests.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": text},
            timeout=120,
        )
        if response.status_code == 404:
            message = ollama_error(response)
            if "not found" in message.lower() and self.model in message:
                raise RuntimeError(
                    f'Ollama embedding model "{self.model}" is not installed. '
                    f"Run: ollama pull {self.model}"
                )
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=120,
            )
            if response.status_code == 404:
                message = ollama_error(response)
                if "not found" in message.lower() and self.model in message:
                    raise RuntimeError(
                        f'Ollama embedding model "{self.model}" is not installed. '
                        f"Run: ollama pull {self.model}"
                    )
            response.raise_for_status()
            return response.json()["embedding"]
        response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings")
        if embeddings:
            return embeddings[0]
        embedding = data.get("embedding")
        if embedding:
            return embedding
        raise ValueError("Ollama embedding response did not include an embedding")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def ollama_error(response: requests.Response) -> str:
    try:
        return str(response.json().get("error", ""))
    except Exception:
        return response.text
