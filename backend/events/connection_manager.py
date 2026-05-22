"""Local WebSocket connection manager.

Replaces Pusher when ``EVENT_PROVIDER=websocket``. Maintains a registry of
active connections, optionally keyed by user/topic, and offers ``broadcast``
helpers that mirror the semantics the Pusher publishers used.

The manager is async and event-loop-aware: every method is safe to call from
FastAPI handlers; broadcast errors don't take the whole loop down — failed
sockets are dropped from the registry.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._global: Set[WebSocket] = set()
        self._by_user: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._by_topic: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        *,
        user_id: Optional[str] = None,
        topics: Optional[Iterable[str]] = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._global.add(websocket)
            if user_id:
                self._by_user[user_id].add(websocket)
            for topic in topics or ():
                self._by_topic[topic].add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._global.discard(websocket)
            for bucket in self._by_user.values():
                bucket.discard(websocket)
            for bucket in self._by_topic.values():
                bucket.discard(websocket)

    async def _send_safe(self, ws: WebSocket, payload: Any) -> bool:
        try:
            if isinstance(payload, (dict, list)):
                await ws.send_json(payload)
            else:
                await ws.send_text(str(payload))
            return True
        except Exception as exc:
            logger.warning("WebSocket send failed; dropping connection: %s", exc)
            await self.disconnect(ws)
            return False

    async def broadcast(self, message: Any) -> None:
        async with self._lock:
            targets = list(self._global)
        if not targets:
            return
        await asyncio.gather(*[self._send_safe(ws, message) for ws in targets])

    async def send_to_user(self, user_id: str, message: Any) -> None:
        async with self._lock:
            targets = list(self._by_user.get(user_id, ()))
        if not targets:
            return
        await asyncio.gather(*[self._send_safe(ws, message) for ws in targets])

    async def publish(self, topic: str, message: Any) -> None:
        async with self._lock:
            targets = list(self._by_topic.get(topic, ()))
        if not targets:
            return
        await asyncio.gather(*[self._send_safe(ws, message) for ws in targets])


# Process-wide manager — import this object directly. Each FastAPI worker has
# its own instance; cross-worker fan-out is out of scope for the local
# milestone. (See spec note: optional Redis Pub/Sub fallback later.)
manager = ConnectionManager()
