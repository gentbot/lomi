"""Local /v4/listen WebSocket endpoint.

Drop-in replacement for the production transcribe router's /v4/listen path.
Accepts the same query parameters and emits the same JSON event shapes so both
the iOS Flutter app and macOS Desktop app work without code changes.

Auth: accepts local JWTs (Authorization: Bearer <local_jwt>) or, when
LOCAL_AUTH_BYPASS=true in the environment, any non-empty Bearer token (useful
during dev when the app sends Firebase ID tokens that we can't validate locally
without the firebase-admin SDK).

Audio: raw binary PCM16-LE frames.  8 kHz (pin BLE codec=pcm8) is upsampled
to 16 kHz before Whisper sees it.  16 kHz (Desktop linear16) passes through.
"""

import asyncio
import logging
import os
import time
import uuid
from typing import Optional

import numpy as np
import opuslib
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth.local_auth import AuthError, bypass_uid_from_token, verify_token
from database import vector_db_qdrant as vdb
from database.sql import repository
from utils.llm import post_process
from utils.stt.providers import local_streaming

logger = logging.getLogger(__name__)

router = APIRouter()

_AUTH_BYPASS = os.environ.get("LOCAL_AUTH_BYPASS", "").lower() in ("1", "true", "yes")


# ── helpers ───────────────────────────────────────────────────────────────────


def _authenticate(authorization: str) -> Optional[str]:
    """Return user_id string or None."""
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    if not token:
        return None
    # Try local JWT first.
    try:
        payload = verify_token(token)
        return payload.get("user_id") or payload.get("sub")
    except AuthError:
        pass
    # Fall back to Firebase token bypass (dev/LAN only).
    if _AUTH_BYPASS:
        return bypass_uid_from_token(token)
    return None


def _upsample_8k_to_16k(raw: bytes) -> bytes:
    """Linearly interpolate PCM16-LE from 8 kHz to 16 kHz."""
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    out_len = len(pcm) * 2
    upsampled = np.interp(
        np.linspace(0, len(pcm) - 1, out_len),
        np.arange(len(pcm)),
        pcm,
    ).astype(np.int16)
    return upsampled.tobytes()


# ── endpoint ──────────────────────────────────────────────────────────────────


@router.websocket("/v4/listen")
async def local_listen(
    ws: WebSocket,
    language: str = "en",
    sample_rate: int = 16000,
    codec: str = "linear16",
    channels: int = 1,
    uid: Optional[str] = None,
    include_speech_profile: bool = True,
    source: Optional[str] = None,
    conversation_timeout: int = 120,
    stt_service: Optional[str] = None,
    speaker_auto_assign: str = "disabled",
    vad_gate: str = "",
    custom_stt: str = "disabled",
    onboarding: str = "disabled",
) -> None:
    await ws.accept()

    authorization = ws.headers.get("authorization", "")
    user_id = _authenticate(authorization)
    if user_id is None:
        await ws.send_json({"error": "unauthorized"})
        await ws.close(code=1008)
        return

    session_id = uuid.uuid4().hex
    accumulated_segments: list[dict] = []
    last_audio_at: float = time.monotonic()
    needs_upsample = sample_rate == 8000
    needs_opus_decode = codec == "opus"
    opus_decoder = opuslib.Decoder(16000, 1) if needs_opus_decode else None

    async def _emit(obj: dict) -> None:
        try:
            await ws.send_json(obj)
        except Exception:
            pass

    async def _on_partial(text: str) -> None:
        seg = {
            "id": uuid.uuid4().hex,
            "text": text,
            "speaker": "SPEAKER_00",
            "speaker_id": 0,
            "is_user": True,
            "person_id": None,
            "start": 0.0,
            "end": 0.0,
            "words": [],
            "translations": [],
        }
        accumulated_segments.append(seg)
        await _emit({"type": "transcript_segment", "segments": [seg]})

    async def _finalize() -> None:
        if not accumulated_segments:
            return
        full_text = " ".join(s["text"] for s in accumulated_segments)
        title = full_text[:80] + ("…" if len(full_text) > 80 else "")
        conv_id = uuid.uuid4().hex
        await _emit({"type": "conversation_processing_started", "conversation_id": conv_id})

        conv = await asyncio.to_thread(
            repository.create_conversation,
            user_id,
            conversation_id=conv_id,
            title=title,
            transcript_segments=accumulated_segments,
            structured={"title": title, "overview": full_text[:500],
                        "action_items": [], "category": "other"},
        )

        try:
            await asyncio.to_thread(
                vdb.upsert_conversation_text_vector, user_id, conv["id"], full_text
            )
        except Exception:
            logger.debug("Qdrant upsert skipped for conversation %s", conv["id"])

        asyncio.create_task(post_process.run_post_process(user_id, conv["id"], full_text))

        await _emit({
            "type": "conversation_event",
            "event_type": "new_conversation",
            "conversation": {
                "id": conv["id"],
                "structured": conv.get("structured", {"title": title, "overview": full_text[:500]}),
                "transcript_segments": accumulated_segments,
                "source": source or "omi",
            },
        })
        logger.info("Conversation %s created for user %s (%d segments)",
                    conv["id"], user_id, len(accumulated_segments))

    async def _silence_watchdog() -> None:
        nonlocal session_id, last_audio_at
        while True:
            await asyncio.sleep(5)
            if not accumulated_segments:
                continue
            if time.monotonic() - last_audio_at < conversation_timeout:
                continue
            logger.info("Silence timeout reached for session %s, finalizing", session_id)
            old_session = session_id
            await local_streaming.end_stream(old_session)
            await _finalize()
            accumulated_segments.clear()
            new_session = uuid.uuid4().hex
            await local_streaming.start_stream(new_session, on_partial=_on_partial, sample_rate=16000)
            session_id = new_session
            last_audio_at = time.monotonic()

    await local_streaming.start_stream(session_id, on_partial=_on_partial,
                                       sample_rate=16000)
    watchdog_task = None
    if conversation_timeout > 0:
        watchdog_task = asyncio.create_task(_silence_watchdog())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            raw = msg.get("bytes")
            if raw:
                last_audio_at = time.monotonic()
                if needs_opus_decode:
                    try:
                        audio = bytes(opus_decoder.decode(raw, 320, decode_fec=False))
                    except Exception:
                        logger.debug("Opus frame decode failed (%d bytes), dropping", len(raw))
                        continue
                elif needs_upsample:
                    audio = _upsample_8k_to_16k(raw)
                else:
                    audio = raw
                await local_streaming.push_audio_chunk(session_id, audio)
    except WebSocketDisconnect:
        pass
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()
        final = await local_streaming.end_stream(session_id)
        # end_stream returns the full joined transcript.  Only add it as a
        # segment when no partials were accumulated (audio shorter than one
        # 5-second chunk), to avoid duplicating content already in
        # accumulated_segments.
        if final and not accumulated_segments:
            await _on_partial(final)
        await _finalize()
        try:
            await ws.close()
        except Exception:
            pass
