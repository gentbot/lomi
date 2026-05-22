"""Local WebSocket broadcast endpoint (Phase 8 cutover).

Connects clients to the process-wide ``ConnectionManager`` so transcript and
chat events emitted via ``events.router.broadcast(...)`` reach them in
realtime.
"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from auth.local_auth import AuthError, verify_token
from events.connection_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query("")) -> None:
    user_id = None
    if token:
        try:
            payload = verify_token(token)
            user_id = payload["user_id"]
        except AuthError:
            await ws.accept()
            await ws.send_json({"error": "invalid token"})
            await ws.close(code=1008)
            return

    await manager.connect(ws, user_id=user_id)
    try:
        while True:
            # Accept and discard inbound frames; this endpoint is broadcast-out.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
