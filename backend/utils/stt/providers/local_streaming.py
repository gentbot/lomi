"""Chunked local streaming transcription.

Implements the spec's session API:

    start_stream(session_id)
    push_audio_chunk(session_id, chunk)
    end_stream(session_id) -> str

The first local milestone deliberately *does not* attempt token-level realtime
parity with Deepgram. Instead each session buffers raw PCM bytes; every
``CHUNK_SECONDS`` worth of audio is flushed to local Whisper, partial text is
appended, and ``end_stream`` flushes the remainder and returns the full
transcript.

The model assumes 16 kHz mono PCM16 audio (the format the rest of the backend
already uses for upstream cloud STT). Adjust ``LOCAL_STREAM_SAMPLE_RATE`` /
``LOCAL_STREAM_BYTES_PER_SAMPLE`` env vars if a different format is fed in.
"""

import asyncio
import logging
import os
import tempfile
import wave
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

CHUNK_SECONDS = float(os.environ.get("LOCAL_STREAM_CHUNK_SECONDS", "5"))
SAMPLE_RATE = int(os.environ.get("LOCAL_STREAM_SAMPLE_RATE", "16000"))
BYTES_PER_SAMPLE = int(os.environ.get("LOCAL_STREAM_BYTES_PER_SAMPLE", "2"))
NUM_CHANNELS = int(os.environ.get("LOCAL_STREAM_CHANNELS", "1"))


@dataclass
class _Session:
    buffer: bytearray = field(default_factory=bytearray)
    transcript_parts: List[str] = field(default_factory=list)
    on_partial: Optional[Callable[[str], Awaitable[None]]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sample_rate: int = SAMPLE_RATE


_sessions: Dict[str, _Session] = {}


def _bytes_per_chunk() -> int:
    return int(SAMPLE_RATE * BYTES_PER_SAMPLE * NUM_CHANNELS * CHUNK_SECONDS)


def _write_wav(pcm: bytes, path: str, sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(NUM_CHANNELS)
        wf.setsampwidth(BYTES_PER_SAMPLE)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _transcribe_pcm(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    if not pcm:
        return ""
    from utils.stt.providers.local_whisper_prerecorded import transcribe

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _write_wav(pcm, tmp_path, sample_rate=sample_rate)
        result = transcribe(tmp_path)
        return result.get("text", "")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def start_stream(
    session_id: str,
    on_partial: Optional[Callable[[str], Awaitable[None]]] = None,
    sample_rate: Optional[int] = None,
) -> None:
    if session_id in _sessions:
        logger.warning("Reusing existing local STT session %s", session_id)
    _sessions[session_id] = _Session(on_partial=on_partial,
                                     sample_rate=sample_rate or SAMPLE_RATE)


async def push_audio_chunk(session_id: str, chunk: bytes) -> None:
    sess = _sessions.get(session_id)
    if sess is None:
        raise KeyError(f"Unknown local STT session: {session_id}")

    async with sess.lock:
        sess.buffer.extend(chunk)
        threshold = _bytes_per_chunk()
        if len(sess.buffer) < threshold:
            return
        flushable = bytes(sess.buffer[:threshold])
        del sess.buffer[:threshold]

    text = await asyncio.to_thread(_transcribe_pcm, flushable, sess.sample_rate)
    if text:
        sess.transcript_parts.append(text)
        if sess.on_partial is not None:
            try:
                await sess.on_partial(text)
            except Exception:
                logger.exception("on_partial callback failed for %s", session_id)


async def end_stream(session_id: str) -> str:
    sess = _sessions.pop(session_id, None)
    if sess is None:
        return ""
    leftover = bytes(sess.buffer)
    sess.buffer.clear()
    if leftover:
        tail = await asyncio.to_thread(_transcribe_pcm, leftover, sess.sample_rate)
        if tail:
            sess.transcript_parts.append(tail)
    return " ".join(p.strip() for p in sess.transcript_parts if p).strip()
