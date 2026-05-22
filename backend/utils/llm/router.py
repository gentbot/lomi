"""LLM router — entry point for migrated call sites.

Routes chat/generate/stream/extract_actions to either the local Ollama provider
or the existing OpenAI-backed adapter depending on ``LLM_PROVIDER``.

Unmigrated call sites still import directly from ``utils.llm.clients``; that is
intentional. New code should prefer this router so a single env var flip moves
the call to local inference.
"""

import asyncio
from typing import Iterator, List, Dict

from providers import get_llm_provider


def _impl():
    if get_llm_provider() == "ollama":
        from utils.llm.providers import ollama_client as impl
    else:
        from utils.llm.providers import openai_client as impl
    return impl


def generate(prompt: str) -> str:
    return _impl().generate(prompt)


def chat(messages: List[Dict[str, str]]) -> str:
    return _impl().chat(messages)


async def achat(messages: List[Dict[str, str]]) -> str:
    """Async chat — uses provider's native async path when available, otherwise offloads to thread."""
    impl = _impl()
    if hasattr(impl, "achat"):
        return await impl.achat(messages)
    return await asyncio.to_thread(impl.chat, messages)


def stream(messages: List[Dict[str, str]]) -> Iterator[str]:
    yield from _impl().stream(messages)


def extract_actions(text: str) -> dict:
    return _impl().extract_actions(text)


async def astream(messages: List[Dict[str, str]]):
    """Async streaming for FastAPI handlers; falls back to threaded sync stream
    when the provider does not implement an async path."""
    impl = _impl()
    if hasattr(impl, "astream"):
        async for chunk in impl.astream(messages):
            yield chunk
        return
    # Synchronous fallback — tolerable for the OpenAI adapter where the
    # langchain client already streams via httpx under the hood.
    for chunk in impl.stream(messages):
        yield chunk
