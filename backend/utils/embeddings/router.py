"""Embeddings router.

Returns a callable / adapter for the embeddings provider selected by env.
Ensures all callers can ask for the embedding *dimension* without instantiating
the underlying model — the Qdrant collection bootstrap relies on this.
"""

from typing import Callable, List

from providers import get_embeddings_provider


def _module():
    if get_embeddings_provider() == "local":
        from utils.embeddings import local_embeddings as impl
    else:
        from utils.embeddings import openai_embeddings as impl
    return impl


def embed(text: str) -> List[float]:
    return _module().embed(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    return _module().embed_batch(texts)


def get_embedder() -> Callable[[str], List[float]]:
    """Return the single-text embed function (preserves the spec's interface)."""
    return _module().embed


def get_embeddings_object():
    """Return a langchain-compatible adapter (``embed_query``/``embed_documents``).

    This is the drop-in replacement for the ``embeddings`` singleton in
    ``utils.llm.clients`` that downstream code imports today.
    """
    if get_embeddings_provider() == "local":
        from utils.embeddings.local_embeddings import LocalEmbeddingsAdapter

        return LocalEmbeddingsAdapter()
    from utils.embeddings.openai_embeddings import OpenAIEmbeddingsAdapter

    return OpenAIEmbeddingsAdapter()


def dimension() -> int:
    return _module().dimension()
