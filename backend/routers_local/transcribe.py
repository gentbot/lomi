"""Local prerecorded + streaming transcription (Phase 4 cutover).

POST /v1/transcribe          — upload audio file, returns normalized transcript
WS   /v1/transcribe/stream   — chunked PCM streaming session

The streaming endpoint expects the client to send raw PCM16 mono frames at
``LOCAL_STREAM_SAMPLE_RATE`` (16 kHz default). Send a text frame ``"END"`` to
flush the buffer and receive the final transcript.

Set ``AUTO_PERSIST_TRANSCRIPTS=true`` to automatically create a Conversation row
in SQLite and index the transcript text in Qdrant after each transcription.
"""

import asyncio
import logging
import os
import tempfile
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, UploadFile, WebSocket, WebSocketDisconnect

from auth.local_auth import AuthError, verify_token
from auth.router_dep import get_current_user_id_local
from database import vector_db_qdrant as vdb
from database.sql import repository
from utils.stt.providers import local_streaming, local_whisper_prerecorded

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/transcribe", tags=["transcribe"])

_AUTO_PERSIST = os.environ.get("AUTO_PERSIST_TRANSCRIPTS", "").lower() in ("1", "true", "yes")


async def _persist_transcript(user_id: str, text: str, segments: list) -> None:
    """Create a Conversation row in SQLite and index its text in Qdrant."""
    if not text:
        return
    title = text[:80] + ("…" if len(text) > 80 else "")
    try:
        conv = await asyncio.to_thread(
            repository.create_conversation,
            user_id,
            title=title,
            transcript_segments=segments,
        )
        await asyncio.to_thread(vdb.upsert_conversation_text_vector, user_id, conv["id"], text)
        logger.info("Auto-persisted transcript as conversation %s for user %s", conv["id"], user_id)
    except Exception:
        logger.exception("Auto-persist transcript failed for user %s — transcript was returned normally", user_id)


@router.post("")
async def transcribe(
    audio: UploadFile = File(...), user_id: str = Depends(get_current_user_id_local)
) -> Dict[str, Any]:
    suffix = os.path.splitext(audio.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name
    try:
        result = await asyncio.to_thread(local_whisper_prerecorded.transcribe, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if _AUTO_PERSIST:
        await _persist_transcript(user_id, result.get("text", ""), result.get("segments", []))

    return result


@router.websocket("/stream")
async def stream_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    # Auth via subprotocol or initial JSON handshake — keep it simple: first
    # text message must be the JWT.
    try:
        token = await ws.receive_text()
    except WebSocketDisconnect:
        return
    try:
        token_data = verify_token(token)
    except AuthError:
        await ws.send_json({"error": "invalid token"})
        await ws.close(code=1008)
        return

    user_id = token_data["user_id"]
    session_id = uuid.uuid4().hex

    async def on_partial(text: str) -> None:
        try:
            await ws.send_json({"type": "partial", "text": text})
        except Exception:
            pass

    await local_streaming.start_stream(session_id, on_partial=on_partial)
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                await local_streaming.push_audio_chunk(session_id, msg["bytes"])
            elif "text" in msg and msg["text"]:
                if msg["text"].strip().upper() == "END":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        final = await local_streaming.end_stream(session_id)
        try:
            await ws.send_json({"type": "final", "text": final})
            await ws.close()
        except Exception:
            pass

    if _AUTO_PERSIST and final:
        await _persist_transcript(user_id, final, [])
