"""OpenAI embeddings adapter.

Phase 2 keeps the existing ``OpenAIEmbeddings`` instance living inside
``utils.llm.clients`` (where BYOK proxy + caching already exist). This module
exists so the embeddings router can hand back a uniform object regardless of
provider, without forcing the cloud path through a refactor.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def _embeddings():
    from utils.llm.clients import embeddings as cloud_embeddings

    return cloud_embeddings


def embed(text: str) -> List[float]:
    return _embeddings().embed_query(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    return _embeddings().embed_documents(texts)


def dimension() -> int:
    # text-embedding-3-large default. Override via env if a different OpenAI
    # model is used.
    import os

    return int(os.environ.get("OPENAI_EMBEDDINGS_DIM", "3072"))


class OpenAIEmbeddingsAdapter:
    """Mirrors LocalEmbeddingsAdapter so the router returns a consistent shape."""

    def embed_query(self, text: str) -> List[float]:
        return embed(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return embed_batch(texts)
