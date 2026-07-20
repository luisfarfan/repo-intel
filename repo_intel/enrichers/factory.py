from __future__ import annotations

from typing import Protocol, runtime_checkable

from repo_intel.core.config import AppConfig


@runtime_checkable
class ChatClient(Protocol):
    """The contract every chat backend must satisfy.

    This is the seam that `llm.provider` / `brief.provider` dispatch on. Before this
    existed the provider fields were read but never acted on: the concrete client was
    hardcoded at the call site, so setting provider = "cliproxy" was a silent no-op.
    """

    def generate(self, prompt: str) -> str: ...


# Providers that speak the OpenAI /v1/chat/completions wire format.
OPENAI_COMPATIBLE_PROVIDERS = {"cliproxy", "openrouter", "openai-compatible", "openai_compat"}
NATIVE_OLLAMA_PROVIDERS = {"ollama"}

KNOWN_PROVIDERS = OPENAI_COMPATIBLE_PROVIDERS | NATIVE_OLLAMA_PROVIDERS


class UnknownProviderError(ValueError):
    def __init__(self, setting: str, provider: str) -> None:
        known = ", ".join(sorted(KNOWN_PROVIDERS))
        super().__init__(
            f"Unknown {setting} provider {provider!r}. Known providers: {known}. "
            f"Fix it in config.toml or with: repo-intel config set {setting} <provider>"
        )
        self.provider = provider


ANSWER_SYSTEM_PROMPT = (
    "You answer engineering questions strictly from the supplied SDD documentation "
    "context. If the context does not contain the answer, say so plainly."
)

BRIEF_SYSTEM_PROMPT = (
    "You write concise, accurate engineering product briefs from SDD documentation. "
    "Use only the supplied context."
)


def build_ask_client(config: AppConfig) -> ChatClient:
    """Build the chat client for `repo-intel ask`, dispatching on `[llm] provider`."""
    provider = config.llm.provider.strip().lower()

    if provider in NATIVE_OLLAMA_PROVIDERS:
        from repo_intel.enrichers.ollama_chat import OllamaChatClient

        return OllamaChatClient(
            base_url=config.llm.base_url,
            model=config.llm.model,
            temperature=config.llm.temperature,
            num_predict=config.llm.num_predict,
        )

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        from repo_intel.enrichers.openai_compat_chat import OpenAICompatChatClient

        return OpenAICompatChatClient(
            model=config.llm.model,
            base_url=config.llm.base_url,
            api_key_env=config.llm.api_key_env,
            temperature=config.llm.temperature,
            # Ollama's num_predict has no OpenAI equivalent; max_tokens is the analogue.
            max_tokens=config.llm.num_predict,
            system_prompt=ANSWER_SYSTEM_PROMPT,
        )

    raise UnknownProviderError("llm.provider", config.llm.provider)


def build_brief_client(
    config: AppConfig,
    provider: str | None = None,
    model: str | None = None,
) -> ChatClient:
    """Build the chat client for `repo-intel brief`, dispatching on `[brief] provider`.

    `provider`/`model` override the configured pair; the fallback path uses them.
    """
    effective_provider = (provider or config.brief.provider).strip().lower()
    effective_model = model or config.brief.model

    if effective_provider in NATIVE_OLLAMA_PROVIDERS:
        from repo_intel.enrichers.ollama_chat import OllamaChatClient

        return OllamaChatClient(
            base_url=config.llm.base_url if config.llm.provider == "ollama" else "http://localhost:11434",
            model=effective_model,
            temperature=config.brief.temperature,
            num_predict=config.brief.max_output_tokens,
        )

    if effective_provider in OPENAI_COMPATIBLE_PROVIDERS:
        from repo_intel.enrichers.openai_compat_chat import OpenAICompatChatClient

        # cliproxy shares the [llm] endpoint/credential; openrouter has its own.
        if effective_provider == "cliproxy":
            base_url = config.llm.base_url
            api_key_env = config.llm.api_key_env
        else:
            base_url = config.brief.base_url
            api_key_env = config.brief.api_key_env

        return OpenAICompatChatClient(
            model=effective_model,
            base_url=base_url,
            api_key_env=api_key_env,
            temperature=config.brief.temperature,
            max_tokens=config.brief.max_output_tokens,
            site_url=config.brief.site_url,
            app_name=config.brief.app_name,
            system_prompt=BRIEF_SYSTEM_PROMPT,
        )

    raise UnknownProviderError("brief.provider", effective_provider)
