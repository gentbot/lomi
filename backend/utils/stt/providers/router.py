"""STT router — selects prerecorded/streaming implementations by env."""

from typing import Any, Dict

from providers import get_stt_provider


def transcribe(file_path: str) -> Dict[str, Any]:
    if get_stt_provider() == "local":
        from utils.stt.providers.local_whisper_prerecorded import transcribe as _local

        return _local(file_path)
    # Cloud (Deepgram) path — call sites should keep using the existing
    # ``utils.stt.pre_recorded`` helpers directly until they are migrated.
    raise NotImplementedError(
        "Cloud STT path is owned by utils.stt.pre_recorded; this router only "
        "redirects to the local provider for now."
    )


def start_stream(*args, **kwargs):
    if get_stt_provider() == "local":
        from utils.stt.providers.local_streaming import start_stream as _local

        return _local(*args, **kwargs)
    raise NotImplementedError("Use utils.stt.streaming directly for the cloud path.")


def push_audio_chunk(*args, **kwargs):
    from utils.stt.providers.local_streaming import push_audio_chunk as _local

    return _local(*args, **kwargs)


def end_stream(*args, **kwargs):
    from utils.stt.providers.local_streaming import end_stream as _local

    return _local(*args, **kwargs)
