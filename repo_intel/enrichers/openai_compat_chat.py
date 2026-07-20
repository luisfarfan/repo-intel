from __future__ import annotations

import os

import requests

from repo_intel.core.env import load_project_env


DEFAULT_SYSTEM_PROMPT = (
    "You write concise, accurate engineering answers from SDD documentation. "
    "Use only the supplied context."
)


class OpenAICompatChatClient:
    """Chat client for any OpenAI-compatible ``/v1/chat/completions`` endpoint.

    Covers OpenRouter, the local cliproxy gateway, and anything else that speaks the
    same wire format. The credential is always resolved at call-construction time from
    the environment variable *named* by ``api_key_env`` -- the value itself never lives
    in config.toml or in source.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str,
        temperature: float = 0.2,
        max_tokens: int = 1800,
        site_url: str | None = None,
        app_name: str | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        timeout: int = 180,
        require_api_key: bool = True,
    ) -> None:
        load_project_env()
        api_key = os.getenv(api_key_env)
        if not api_key and require_api_key:
            raise RuntimeError(
                f"Missing API key: environment variable {api_key_env} is not set. "
                f"Set it in ~/.repo-intel/.env (chmod 600) or export it in your shell. "
                f"See README section 'LLM providers'."
            )
        self.api_key = api_key or ""
        self.api_key_env = api_key_env
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.site_url = site_url
        self.app_name = app_name
        self.system_prompt = system_prompt
        self.timeout = timeout

    def headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter attribution headers. Harmless for other gateways, so they are
        # sent whenever configured rather than branched on provider.
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name
        return headers

    def generate(self, prompt: str) -> str:
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers(),
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            timeout=self.timeout,
        )
        if response.status_code in {401, 402, 403}:
            raise RuntimeError(
                f"Chat authentication/billing failed ({response.status_code}) for "
                f"{self.base_url}. Update {self.api_key_env} in ~/.repo-intel/.env."
            )
        if response.status_code == 404:
            raise RuntimeError(
                f"Chat endpoint not found: {self.base_url}/chat/completions returned 404. "
                "For an OpenAI-compatible gateway the base_url must include the /v1 "
                "suffix (e.g. http://127.0.0.1:8317/v1)."
            )
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            # Truncate: this body comes from an external gateway and lands in logs and
            # stack traces. The top-level keys are what actually identify the shape
            # problem; the payload behind them is unbounded and not ours to spill.
            shape = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
            preview = repr(data)[:200]
            raise ValueError(
                f"Unexpected chat response shape from {self.base_url} "
                f"(model={self.model}, keys={shape}): {preview}"
            ) from exc
        if not content:
            raise ValueError(f"Empty chat completion from {self.base_url} (model={self.model})")
        return content.strip()
