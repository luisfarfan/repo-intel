from __future__ import annotations

import requests


class OllamaEmbeddingClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed(self, text: str) -> list[float]:
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
