"""Local Voice Activity Detection.

Goal: a dependency-light ``detect_speech(audio_chunk: bytes) -> bool`` that
works for the local-mode pipeline without pulling Modal/Deepgram VAD into
local builds.

Strategy:
- Default: RMS energy heuristic on PCM16 mono audio. Fast, zero deps, good
  enough to chunk a streaming session.
- Optional: if ``LOCAL_VAD_BACKEND=silero`` and ``torch`` + ``silero-vad`` are
  installed, use the model-based detector. Loaded lazily and cached.

Diarization is intentionally not produced here. With ``ENABLE_DIARIZATION=false``
the local STT path labels every segment with a single speaker.
"""

import logging
import math
import os
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

VAD_BACKEND = os.environ.get("LOCAL_VAD_BACKEND", "energy").strip().lower()
VAD_RMS_THRESHOLD = float(os.environ.get("LOCAL_VAD_RMS_THRESHOLD", "300"))
VAD_SILERO_THRESHOLD = float(os.environ.get("LOCAL_VAD_SILERO_THRESHOLD", "0.5"))
VAD_SAMPLE_RATE = int(os.environ.get("LOCAL_VAD_SAMPLE_RATE", "16000"))

_silero_model = None
_silero_lock = Lock()


def _rms_energy_pcm16(audio_chunk: bytes) -> float:
    if not audio_chunk or len(audio_chunk) < 2:
        return 0.0
    # PCM16 little-endian, mono. Compute RMS without numpy to keep the local
    # mode importable in environments that haven't installed it.
    n_samples = len(audio_chunk) // 2
    if n_samples == 0:
        return 0.0
    total = 0
    for i in range(0, len(audio_chunk) - 1, 2):
        sample = int.from_bytes(audio_chunk[i : i + 2], byteorder="little", signed=True)
        total += sample * sample
    return math.sqrt(total / n_samples)


def _silero_detect(audio_chunk: bytes) -> Optional[bool]:
    global _silero_model
    try:
        import torch
    except ImportError:
        return None
    if _silero_model is None:
        with _silero_lock:
            if _silero_model is None:
                try:
                    model, _ = torch.hub.load(
                        repo_or_dir="snakers4/silero-vad",
                        model="silero_vad",
                        trust_repo=True,
                    )
                    _silero_model = model
                except Exception as exc:
                    logger.warning("silero-vad load failed; falling back to RMS: %s", exc)
                    return None
    if _silero_model is None:
        return None
    try:
        import numpy as np

        samples = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return False
        tensor = torch.from_numpy(samples)
        prob = float(_silero_model(tensor, VAD_SAMPLE_RATE).item())
        return prob >= VAD_SILERO_THRESHOLD
    except Exception as exc:
        logger.warning("silero-vad inference failed; falling back to RMS: %s", exc)
        return None


def detect_speech(audio_chunk: bytes) -> bool:
    """Return True if the chunk plausibly contains speech."""
    if VAD_BACKEND == "silero":
        result = _silero_detect(audio_chunk)
        if result is not None:
            return result
    return _rms_energy_pcm16(audio_chunk) >= VAD_RMS_THRESHOLD
