"""Local TTS stub — returns 501 (ElevenLabs not wired locally)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["tts"])


@router.post("/v2/tts/synthesize")
async def tts_stub() -> JSONResponse:
    return JSONResponse({"error": "tts is not available in local mode"}, status_code=501)
