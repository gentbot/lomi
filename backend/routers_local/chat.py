"""Local chat endpoint backed by Ollama (Phase 1 cutover).

POST /v1/chat        — synchronous chat completion
POST /v1/chat/stream — server-sent stream of incremental tokens
"""

from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.router_dep import get_current_user_id_local
from utils.llm import router as llm_router

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None


class ChatResponse(BaseModel):
    content: str


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user_id_local)) -> ChatResponse:
    payload = [m.model_dump() for m in req.messages]
    return ChatResponse(content=await llm_router.achat(payload))


@router.post("/stream")
def chat_stream(req: ChatRequest, user_id: str = Depends(get_current_user_id_local)) -> StreamingResponse:
    payload = [m.model_dump() for m in req.messages]

    async def gen():
        async for chunk in llm_router.astream(payload):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")
