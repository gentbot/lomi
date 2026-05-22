"""Event-system router.

Returns the active broadcaster: either the local WebSocket manager or a thin
Pusher passthrough. New code should call ``broadcast(message)`` here so a
single env-var flip moves the publish path off Pusher.
"""

from typing import Any

from providers import get_event_provider


async def broadcast(message: Any) -> None:
    if get_event_provider() == "websocket":
        from events.connection_manager import manager

        await manager.broadcast(message)
        return
    # Pusher fall-through: existing publishers under backend/pusher/ remain the
    # source of truth for cloud mode. New code should not import them
    # directly — import this router so local mode is reachable.
    raise NotImplementedError(
        "Pusher publish lives under backend/pusher/; route via this module only "
        "when EVENT_PROVIDER=websocket."
    )


async def send_to_user(user_id: str, message: Any) -> None:
    if get_event_provider() == "websocket":
        from events.connection_manager import manager

        await manager.send_to_user(user_id, message)
        return
    raise NotImplementedError(
        "Pusher publish lives under backend/pusher/; route via this module only "
        "when EVENT_PROVIDER=websocket."
    )


async def push_event(user_id: str, event: Any) -> None:
    """Convenience wrapper — dispatches a per-user event through the active provider."""
    await send_to_user(user_id, event)
