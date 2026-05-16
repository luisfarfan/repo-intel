from __future__ import annotations

import requests


class OllamaChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.1,
        num_predict: int = 700,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict

    def generate(self, prompt: str) -> str:
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.num_predict,
                },
            },
            timeout=240,
        )
        if response.status_code == 404:
            message = ollama_error(response)
            if "not found" in message.lower() and self.model in message:
                raise RuntimeError(
                    f'Ollama LLM model "{self.model}" is not installed. '
                    f"Run: ollama pull {self.model}"
                )
        response.raise_for_status()
        data = response.json()
        text = data.get("response")
        if not text:
            raise ValueError("Ollama generate response did not include text")
        return text.strip()


def ollama_error(response: requests.Response) -> str:
    try:
        return str(response.json().get("error", ""))
    except Exception:
        return response.text
