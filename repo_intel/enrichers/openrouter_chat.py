from __future__ import annotations

from repo_intel.enrichers.openai_compat_chat import OpenAICompatChatClient

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

BRIEF_SYSTEM_PROMPT = (
    "You write concise, accurate engineering product briefs from SDD documentation. "
    "Use only the supplied context."
)


class OpenRouterChatClient(OpenAICompatChatClient):
    """Back-compat shim.

    OpenRouter is just one OpenAI-compatible endpoint among several. The behaviour now
    lives in OpenAICompatChatClient; this subclass only pins the OpenRouter base URL so
    existing imports keep working. New code should go through
    repo_intel.enrichers.factory instead.
    """

    def __init__(
        self,
        model: str,
        api_key_env: str,
        site_url: str,
        app_name: str,
        temperature: float = 0.2,
        max_tokens: int = 1800,
        base_url: str = OPENROUTER_BASE_URL,
    ) -> None:
        super().__init__(
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
            site_url=site_url,
            app_name=app_name,
            system_prompt=BRIEF_SYSTEM_PROMPT,
        )
