"""LLM post-processing pipeline for completed conversations.

Called as a fire-and-forget asyncio task at end of each conversation.
Updates the conversation record with LLM-generated title/summary/category,
creates action items and memories from the transcript, and pushes real-time
events to connected WebSocket clients.
"""

import asyncio
import json
import logging
from typing import Optional

from database import vector_db_qdrant as vdb
from database.sql import repository
from events.router import push_event
from utils.llm import router as llm

logger = logging.getLogger(__name__)


def process_conversation(transcript: str) -> Optional[dict]:
    """Call the LLM to extract structured data from a transcript.

    Returns a dict with keys: title, overview, category, action_items, facts.
    Returns None on failure so callers can skip the update gracefully.
    Run via asyncio.to_thread — this is a synchronous function.
    """
    if not transcript or not transcript.strip():
        return None
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You extract structured information from conversation transcripts. "
                    "Respond ONLY with valid JSON. No markdown fences, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this transcript and return a JSON object with these keys:\n"
                    "- title: concise title, max 10 words\n"
                    "- overview: brief summary, 2-4 sentences\n"
                    "- category: one of personal / work / health / education / entertainment / other\n"
                    "- action_items: list of strings (tasks mentioned; empty list if none)\n"
                    "- facts: list of strings (key personal facts or preferences to remember; empty list if none)\n\n"
                    f"Transcript:\n{transcript}"
                ),
            },
        ]
        raw = llm.chat(messages)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning("post_process: LLM response contains no JSON object")
            return None
        return json.loads(raw[start:end])
    except Exception as exc:
        logger.warning("post_process: LLM call failed — %s", exc)
        return None


async def run_post_process(uid: str, conv_id: str, full_text: str) -> None:
    """Orchestrate the full post-processing pipeline for one conversation.

    Intended to be launched with asyncio.create_task() so it never blocks
    the endpoint that created the conversation.
    """
    result = await asyncio.to_thread(process_conversation, full_text)
    if not result:
        logger.debug("post_process: no result for conversation %s", conv_id)
        return

    structured = {
        "title": result.get("title", ""),
        "overview": result.get("overview", ""),
        "category": result.get("category", "other"),
        "action_items": [],
    }
    await asyncio.to_thread(
        repository.update_conversation,
        uid,
        conv_id,
        title=result.get("title") or None,
        structured=structured,
    )

    for desc in result.get("action_items", []):
        desc = desc.strip()
        if not desc:
            continue
        item = await asyncio.to_thread(
            repository.create_action_item, uid, desc, conversation_id=conv_id
        )
        try:
            await asyncio.to_thread(vdb.upsert_action_item_vector, uid, item["id"], desc)
        except Exception:
            pass
        try:
            await push_event(uid, {"type": "new_action_item", "action_item": item})
        except Exception:
            pass

    for fact in result.get("facts", []):
        fact = fact.strip()
        if not fact:
            continue
        try:
            existing = await asyncio.to_thread(vdb.check_memory_duplicate, uid, fact)
            if existing:
                continue
        except Exception:
            pass
        memo = await asyncio.to_thread(repository.create_memory, uid, fact)
        try:
            await asyncio.to_thread(vdb.upsert_memory_vector, uid, memo["id"], fact, "")
        except Exception:
            pass
        try:
            await push_event(uid, {"type": "new_memory_created", "memory": memo})
        except Exception:
            pass

    logger.info("post_process: completed for conversation %s", conv_id)
