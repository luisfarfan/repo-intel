from __future__ import annotations


class LocalLLMEnricher:
    """Placeholder boundary for optional local LLM enrichment.

    The MVP intentionally does not depend on an LLM. This class marks the extension point
    where Ollama, llama.cpp, or another local runtime can add summaries, tags, and relationship
    hints after deterministic scanning has produced auditable source data.
    """

    enabled = False

