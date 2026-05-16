from __future__ import annotations

import os

import requests

from repo_intel.core.env import load_project_env


class OpenRouterChatClient:
    def __init__(
        self,
        model: str,
        api_key_env: str,
        site_url: str,
        app_name: str,
        temperature: float = 0.2,
        max_tokens: int = 1800,
    ) -> None:
        load_project_env()
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing OpenRouter API key env var: {api_key_env}")
        self.api_key = api_key
        self.model = model
        self.site_url = site_url
        self.app_name = app_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str) -> str:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": self.site_url,
                "X-Title": self.app_name,
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You write concise, accurate engineering product briefs from SDD "
                            "documentation. Use only the supplied context."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            timeout=180,
        )
        if response.status_code in {401, 402, 403}:
            raise RuntimeError(
                f"OpenRouter authentication/billing failed ({response.status_code}). "
                "Update OPENROUTER_API_KEY in .env."
            )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

