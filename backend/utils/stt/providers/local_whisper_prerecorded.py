"""Local prerecorded transcription via faster-whisper.

Returns the spec's normalized shape:

    {"text": str, "segments": [{"start", "end", "text", "speaker"}], "language": str}

Diarization is not produced here — when ``ENABLE_DIARIZATION=false`` the
``speaker`` field is set to ``"SPEAKER_0"`` for every segment so downstream
consumers that grouped on speaker still get a stable label.

faster-whisper is preferred over openai-whisper because it ships CTranslate2
weights (CPU-friendly) and exposes word timestamps via the same API.
"""

import logging
import os
from threading import Lock
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

LOCAL_WHISPER_MODEL = os.environ.get("LOCAL_WHISPER_MODEL", "base")
LOCAL_WHISPER_DEVICE = os.environ.get("LOCAL_WHISPER_DEVICE", "cpu")
LOCAL_WHISPER_COMPUTE_TYPE = os.environ.get("LOCAL_WHISPER_COMPUTE_TYPE", "int8")

_model = None
_model_lock = Lock()


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed. Add 'faster-whisper' to "
                    "requirements.txt to use STT_PROVIDER=local."
                ) from exc
            logger.info(
                "Loading local Whisper model: %s (%s/%s)",
                LOCAL_WHISPER_MODEL,
                LOCAL_WHISPER_DEVICE,
                LOCAL_WHISPER_COMPUTE_TYPE,
            )
            _model = WhisperModel(
                LOCAL_WHISPER_MODEL,
                device=LOCAL_WHISPER_DEVICE,
                compute_type=LOCAL_WHISPER_COMPUTE_TYPE,
            )
    return _model


def transcribe(file_path: str) -> Dict[str, Any]:
    from providers import diarization_enabled

    model = _get_model()
    segments_iter, info = model.transcribe(file_path, word_timestamps=True)

    speaker_label = "SPEAKER_0"  # see module docstring
    diarized = diarization_enabled()

    segments: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    for seg in segments_iter:
        words = []
        for word in seg.words or []:
            words.append(
                {
                    "start": float(word.start) if word.start is not None else None,
                    "end": float(word.end) if word.end is not None else None,
                    "word": word.word,
                    "speaker": speaker_label if not diarized else None,
                }
            )
        segments.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
                "speaker": speaker_label if not diarized else None,
                "words": words,
            }
        )
        text_parts.append(seg.text.strip())

    return {
        "text": " ".join(text_parts).strip(),
        "segments": segments,
        "language": getattr(info, "language", None) or "en",
    }
