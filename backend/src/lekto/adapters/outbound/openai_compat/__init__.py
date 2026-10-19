"""Language model and embeddings adapter: OpenAI-compatible API (Ollama, cloud)."""

from lekto.adapters.outbound.openai_compat.client import (
    OpenAiCompatEmbeddings,
    OpenAiCompatLanguageModel,
)

__all__ = ["OpenAiCompatEmbeddings", "OpenAiCompatLanguageModel"]
