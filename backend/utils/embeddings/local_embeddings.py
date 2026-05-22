"""Local sentence-transformers embeddings.

Default model: ``sentence-transformers/all-MiniLM-L6-v2`` (384 dims). Override
via ``LOCAL_EMBEDDINGS_MODEL`` and keep ``LOCAL_EMBEDDINGS_DIM`` in sync —
the Qdrant collection setup reads the same env var.

The model is loaded lazily on first use so import-time cost stays at zero in
contexts that never hit embeddings (e.g. unit tests of unrelated modules).
"""

import logging
import os
from threading import Lock
from typing import List, Optional

logger = logging.getLogger(__name__)

LOCAL_MODEL_NAME = os.environ.get("LOCAL_EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
LOCAL_DIM = int(os.environ.get("LOCAL_EMBEDDINGS_DIM", "384"))

_model = None
_model_lock = Lock()


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading local embeddings model: %s", LOCAL_MODEL_NAME)
            _model = SentenceTransformer(LOCAL_MODEL_NAME)
    return _model


def dimension() -> int:
    """Return the embedding dimension. Used by the vector DB layer to set up
    Qdrant collections without forcing a model load."""
    return LOCAL_DIM


def embed(text: str) -> List[float]:
    vec = _get_model().encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: List[str], *, batch_size: Optional[int] = None) -> List[List[float]]:
    if not texts:
        return []
    kwargs = {"normalize_embeddings": True}
    if batch_size is not None:
        kwargs["batch_size"] = batch_size
    vecs = _get_model().encode(texts, **kwargs)
    return [v.tolist() for v in vecs]


# Langchain-compatible adapter — lets local embeddings stand in for the
# ``OpenAIEmbeddings`` symbol that the rest of the backend imports today.
class LocalEmbeddingsAdapter:
    """Implements the methods utils.llm.clients.embeddings is used for:
    ``embed_query`` and ``embed_documents``."""

    def embed_query(self, text: str) -> List[float]:
        return embed(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return embed_batch(texts)
