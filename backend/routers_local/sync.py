"""WAL sync endpoint — offline audio recovery from the iOS app.

When the iOS app has buffered audio it could not stream to the backend (phone
was on the local network but the WebSocket was unreachable), it uploads the
buffered .bin files here on reconnect via:

    POST /v2/sync-local-files        — accept files, queue a transcription job
    GET  /v2/sync-local-files/{id}   — poll until done

File format (written by local_wal_sync.dart):
    [uint32 LE: frame_length][opus_bytes: frame_length] ... repeated

Audio: Opus 16 kHz mono, 20 ms frames (320 samples).  opuslib decodes each
frame to PCM16-LE before passing to faster-whisper, matching the format that
/v4/listen already expects.
"""

import asyncio
import logging
import struct
import uuid
from typing import Dict, List, Optional

import opuslib
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from auth.router_dep import get_current_user_id_local
from database import vector_db_qdrant as vdb
from database.sql import repository
from utils.llm import post_process
from utils.stt.providers import local_streaming

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory job store ────────────────────────────────────────────────────────
# Each entry: {"status": queued|processing|done|error, "result": dict|None, "error": str|None}
_jobs: Dict[str, dict] = {}

# ── Audio helpers ──────────────────────────────────────────────────────────────

_OPUS_FRAME_SAMPLES = 320   # 20 ms at 16 kHz


def _parse_wal_bin(data: bytes) -> List[bytes]:
    """Decode the [uint32-LE length][opus-bytes] pairs written by local_wal_sync.dart."""
    frames: List[bytes] = []
    pos = 0
    while pos + 4 <= len(data):
        (length,) = struct.unpack_from('<I', data, pos)
        pos += 4
        if length == 0:
            continue
        if pos + length > len(data):
            break
        frames.append(data[pos: pos + length])
        pos += length
    return frames


def _decode_opus_frames(frames: List[bytes]) -> bytes:
    """Decode Opus frames to raw PCM16-LE bytes (16 kHz mono)."""
    decoder = opuslib.Decoder(16000, 1)
    parts: List[bytes] = []
    dropped = 0
    for frame in frames:
        try:
            pcm = decoder.decode(frame, _OPUS_FRAME_SAMPLES, decode_fec=False)
            parts.append(pcm)
        except Exception:
            dropped += 1
    if dropped:
        logger.debug("Opus decode: dropped %d corrupt frame(s)", dropped)
    return b"".join(parts)


def _timestamp_from_filename(name: str) -> int:
    """Extract the Unix timestamp embedded in a WAL filename.

    Expected suffix: ..._<timestamp>.bin  (timestamp is a plain integer).
    Returns 0 when the filename doesn't match.
    """
    base = name.rsplit(".", 1)[0]
    try:
        return int(base.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        return 0


# ── Background transcription job ──────────────────────────────────────────────


async def _process_job(
    job_id: str,
    uid: str,
    file_data: List[tuple],   # [(filename, bytes), ...]
) -> None:
    _jobs[job_id]["status"] = "processing"
    try:
        # Sort files oldest-first so the transcript reads in chronological order.
        ordered = sorted(file_data, key=lambda x: _timestamp_from_filename(x[0]))

        # Decode every Opus frame from every file into one PCM stream.
        all_frames: List[bytes] = []
        for filename, data in ordered:
            frames = _parse_wal_bin(data)
            logger.debug("WAL sync: %s — %d Opus frames", filename, len(frames))
            all_frames.extend(frames)

        if not all_frames:
            logger.info("WAL sync job %s: no audio frames found", job_id)
            _jobs[job_id] = {
                "status": "done",
                "result": _empty_result(),
                "error": None,
            }
            return

        pcm = await asyncio.to_thread(_decode_opus_frames, all_frames)
        logger.info(
            "WAL sync job %s: decoded %d frames → %d PCM bytes (%.1fs)",
            job_id, len(all_frames), len(pcm), len(pcm) / (16000 * 2),
        )

        # Feed PCM through the same STT pipeline that /v4/listen uses.
        # Batch processing: don't accumulate per-partial segments — end_stream
        # returns the complete joined transcript, which we store as one segment.
        session_id = uuid.uuid4().hex

        await local_streaming.start_stream(session_id, on_partial=None, sample_rate=16000)

        # Push in 5-second slices so Whisper can process incrementally.
        slice_bytes = 16000 * 2 * 5
        for offset in range(0, len(pcm), slice_bytes):
            await local_streaming.push_audio_chunk(
                session_id, pcm[offset: offset + slice_bytes]
            )

        final_text = await local_streaming.end_stream(session_id)
        segments: List[dict] = []
        if final_text and final_text.strip():
            segments.append(_make_segment(final_text))

        if not segments:
            logger.info("WAL sync job %s: STT produced no transcript", job_id)
            _jobs[job_id] = {
                "status": "done",
                "result": _empty_result(),
                "error": None,
            }
            return

        # Create one conversation covering the entire upload.
        full_text = " ".join(s["text"] for s in segments)
        title = full_text[:80] + ("…" if len(full_text) > 80 else "")
        conv_id = uuid.uuid4().hex

        conv = await asyncio.to_thread(
            repository.create_conversation,
            uid,
            conversation_id=conv_id,
            title=title,
            transcript_segments=segments,
            structured={
                "title": title,
                "overview": full_text[:500],
                "action_items": [],
                "category": "other",
            },
        )

        try:
            await asyncio.to_thread(
                vdb.upsert_conversation_text_vector, uid, conv["id"], full_text
            )
        except Exception:
            logger.debug("Qdrant upsert skipped for conversation %s", conv["id"])

        asyncio.create_task(post_process.run_post_process(uid, conv["id"], full_text))

        logger.info(
            "WAL sync job %s: created conversation %s for user %s (%d file(s), %d segment(s))",
            job_id, conv["id"], uid, len(file_data), len(segments),
        )

        _jobs[job_id] = {
            "status": "done",
            "result": {
                "new_memories": [conv["id"]],
                "updated_memories": [],
                "failed_segments": 0,
                "total_segments": len(segments),
                "errors": [],
            },
            "error": None,
        }

    except Exception as exc:
        logger.exception("WAL sync job %s failed", job_id)
        _jobs[job_id] = {"status": "error", "result": None, "error": str(exc)}


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _empty_result() -> dict:
    return {
        "new_memories": [],
        "updated_memories": [],
        "failed_segments": 0,
        "total_segments": 0,
        "errors": [],
    }


def _make_segment(text: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "text": text.strip(),
        "speaker": "SPEAKER_00",
        "speaker_id": 0,
        "is_user": True,
        "person_id": None,
        "start": 0.0,
        "end": 0.0,
        "words": [],
        "translations": [],
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/v2/sync-local-files", status_code=202)
async def sync_local_files(
    files: List[UploadFile] = File(...),
    conversation_id: Optional[str] = None,
    uid: str = Depends(get_current_user_id_local),
) -> dict:
    """Accept WAL .bin files from the iOS app and queue a transcription job."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    file_data: List[tuple] = []
    for f in files:
        data = await f.read()
        file_data.append((f.filename or "", data))

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "queued", "result": None, "error": None}

    asyncio.create_task(_process_job(job_id, uid, file_data))

    return {
        "job_id": job_id,
        "status": "queued",
        "total_files": len(file_data),
        "total_segments": 0,
        "poll_after_ms": 3000,
    }


@router.get("/v2/sync-local-files/{job_id}")
def get_sync_job_status(
    job_id: str,
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    """Poll a previously submitted sync job for completion."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job["status"]

    if status == "done":
        result = job["result"]
        total = result.get("total_segments", 0)
        return {
            "job_id": job_id,
            "status": "completed",
            "total_segments": total,
            "processed_segments": total,
            "successful_segments": total,
            "failed_segments": 0,
            "result": result,
            "error": None,
        }

    if status == "error":
        return {
            "job_id": job_id,
            "status": "failed",
            "total_segments": 0,
            "processed_segments": 0,
            "successful_segments": 0,
            "failed_segments": 0,
            "result": None,
            "error": job["error"],
        }

    # queued or processing
    return {
        "job_id": job_id,
        "status": "processing",
        "total_segments": 0,
        "processed_segments": 0,
        "successful_segments": 0,
        "failed_segments": 0,
        "result": None,
        "error": None,
    }
