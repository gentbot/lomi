"""Thin repository helpers used by the migrated database/* modules.

Each function operates within ``session_scope`` so callers don't need to manage
sessions directly. Functions return plain dicts (mirroring the Firestore
modules' return shapes) so call sites stay unchanged.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session

from database.sql.db import session_scope
from database.sql.models import (
    ActionItem,
    ChatMessage,
    ChatSession,
    Conversation,
    Memory,
    Message,
    StagedTask,
    User,
    UserSettings,
)


def _to_dict(obj) -> Dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


# --- Users ----------------------------------------------------------------


def get_user(session: Session, user_id: str) -> Optional[User]:
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def create_user(email: str, password_hash: str, *, display_name: Optional[str] = None) -> Dict[str, Any]:
    with session_scope() as session:
        user = User(
            id=str(uuid4()),
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )
        session.add(user)
        session.flush()
        return _to_dict(user)


def list_all_users() -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(select(User).order_by(User.created_at.desc()))
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


# Sentinel that distinguishes "caller did not pass display_name" from
# "caller explicitly wants to clear it (None)".
_UNSET: object = object()


def update_user(
    user_id: str,
    *,
    email: Optional[str] = None,
    display_name: Any = _UNSET,
) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return None
        if email is not None:
            user.email = email
        if display_name is not _UNSET:
            # None clears the field; any string sets it
            user.display_name = display_name
        session.flush()
        return _to_dict(user)


def update_user_password(user_id: str, new_password_hash: str) -> bool:
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return False
        user.password_hash = new_password_hash
        session.flush()
        return True


def delete_user(user_id: str) -> bool:
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return False
        session.delete(user)
        return True


# --- Conversations --------------------------------------------------------


def create_conversation(
    user_id: str,
    *,
    conversation_id: Optional[str] = None,
    title: Optional[str] = None,
    structured: Optional[dict] = None,
    transcript_segments: Optional[list] = None,
    extra: Optional[dict] = None,
) -> Dict[str, Any]:
    with session_scope() as session:
        conv = Conversation(
            id=conversation_id or str(uuid4()),
            user_id=user_id,
            title=title,
            transcript_segments=transcript_segments or [],
            structured=structured or {},
            extra=extra or {},
        )
        session.add(conv)
        session.flush()
        return _to_dict(conv)


def get_conversation(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return None
        return _to_dict(conv)


def list_conversations(user_id: str, *, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


def update_conversation(
    user_id: str,
    conversation_id: str,
    *,
    title: Optional[str] = None,
    structured: Optional[dict] = None,
    status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return None
        if title is not None:
            conv.title = title
        if structured is not None:
            conv.structured = structured
        if status is not None:
            conv.status = status
        session.flush()
        return _to_dict(conv)


def append_message(
    conversation_id: str,
    role: str,
    text: str,
    *,
    extra: Optional[dict] = None,
) -> Dict[str, Any]:
    with session_scope() as session:
        # Sequence number = current count of messages in the conversation.
        next_seq = (
            session.execute(
                select(Message).where(Message.conversation_id == conversation_id)
            )
            .scalars()
            .all()
        )
        msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            text=text,
            sequence=len(next_seq),
            extra=extra or {},
        )
        session.add(msg)
        session.flush()
        return _to_dict(msg)


def list_messages(conversation_id: str) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence.asc())
            )
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


# --- Memories -------------------------------------------------------------


def create_memory(
    user_id: str, content: str, category: Optional[str] = None, *, memory_id: Optional[str] = None
) -> Dict[str, Any]:
    with session_scope() as session:
        memo = Memory(
            id=memory_id or str(uuid4()),
            user_id=user_id,
            content=content,
            category=category,
        )
        session.add(memo)
        session.flush()
        return _to_dict(memo)


def get_memory(user_id: str, memory_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        memo = session.get(Memory, memory_id)
        if memo is None or memo.user_id != user_id:
            return None
        return _to_dict(memo)


def list_memories(user_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


# --- Action items ---------------------------------------------------------


def create_action_item(
    user_id: str,
    description: str,
    *,
    action_item_id: Optional[str] = None,
    due_at: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    with session_scope() as session:
        item = ActionItem(
            id=action_item_id or str(uuid4()),
            user_id=user_id,
            description=description,
            due_at=due_at.astimezone(timezone.utc) if due_at else None,
            conversation_id=conversation_id,
        )
        session.add(item)
        session.flush()
        return _to_dict(item)


def list_action_items(user_id: str, *, include_completed: bool = False) -> List[Dict[str, Any]]:
    with session_scope() as session:
        stmt = select(ActionItem).where(ActionItem.user_id == user_id)
        if not include_completed:
            stmt = stmt.where(ActionItem.completed.is_(False))
        rows = session.execute(stmt.order_by(ActionItem.created_at.desc())).scalars().all()
        return [_to_dict(r) for r in rows]


def get_action_item(user_id: str, item_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        item = session.get(ActionItem, item_id)
        if item is None or item.user_id != user_id:
            return None
        return _to_dict(item)


def update_action_item(
    user_id: str,
    item_id: str,
    *,
    completed: Optional[bool] = None,
    description: Optional[str] = None,
    due_at: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        item = session.get(ActionItem, item_id)
        if item is None or item.user_id != user_id:
            return None
        if completed is not None:
            item.completed = completed
        if description is not None:
            item.description = description
        if due_at is not None:
            item.due_at = due_at.astimezone(timezone.utc)
        session.flush()
        return _to_dict(item)


def delete_action_item(user_id: str, item_id: str) -> bool:
    with session_scope() as session:
        item = session.get(ActionItem, item_id)
        if item is None or item.user_id != user_id:
            return False
        session.delete(item)
        return True


# --- Chat messages --------------------------------------------------------


def save_chat_message(
    user_id: str,
    text: str,
    sender: str,
    *,
    message_id: Optional[str] = None,
    app_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[str] = None,
) -> Dict[str, Any]:
    with session_scope() as session:
        msg = ChatMessage(
            id=message_id or str(uuid4()),
            user_id=user_id,
            text=text,
            sender=sender,
            app_id=app_id,
            session_id=session_id,
            metadata_=metadata,
        )
        session.add(msg)
        session.flush()
        return _to_dict(msg)


def list_chat_messages(
    user_id: str,
    *,
    app_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with session_scope() as session:
        stmt = select(ChatMessage).where(ChatMessage.user_id == user_id)
        if app_id is not None:
            stmt = stmt.where(ChatMessage.app_id == app_id)
        if session_id is not None:
            stmt = stmt.where(ChatMessage.session_id == session_id)
        rows = (
            session.execute(stmt.order_by(ChatMessage.created_at.asc()).limit(limit).offset(offset))
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


def delete_chat_messages(
    user_id: str,
    *,
    app_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> int:
    with session_scope() as session:
        stmt = sa_delete(ChatMessage).where(ChatMessage.user_id == user_id)
        if app_id is not None:
            stmt = stmt.where(ChatMessage.app_id == app_id)
        if session_id is not None:
            stmt = stmt.where(ChatMessage.session_id == session_id)
        result = session.execute(stmt)
        return result.rowcount


def update_chat_message_rating(user_id: str, message_id: str, rating: int) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        msg = session.get(ChatMessage, message_id)
        if msg is None or msg.user_id != user_id:
            return None
        msg.rating = rating
        session.flush()
        return _to_dict(msg)


# --- User settings --------------------------------------------------------


def get_user_settings(user_id: str) -> Dict[str, Any]:
    with session_scope() as session:
        settings = session.get(UserSettings, user_id)
        if settings is None:
            return {"user_id": user_id, "assistant_settings": {}}
        return _to_dict(settings)


def upsert_user_settings(user_id: str, assistant_settings: dict) -> Dict[str, Any]:
    with session_scope() as session:
        settings = session.get(UserSettings, user_id)
        if settings is None:
            settings = UserSettings(user_id=user_id, assistant_settings=assistant_settings)
            session.add(settings)
        else:
            settings.assistant_settings = {**settings.assistant_settings, **assistant_settings}
        session.flush()
        return _to_dict(settings)


# --- Conversation count ---------------------------------------------------


def count_conversations(user_id: str, *, statuses: Optional[List[str]] = None) -> int:
    with session_scope() as session:
        stmt = select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
        if statuses:
            stmt = stmt.where(Conversation.status.in_(statuses))
        return session.execute(stmt).scalar_one()


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    with session_scope() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return False
        session.delete(conv)
        return True


def search_conversations(user_id: str, query: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .where(Conversation.title.ilike(f"%{query}%"))
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


# --- Memories extended ----------------------------------------------------


def update_memory(user_id: str, memory_id: str, *, content: Optional[str] = None, visibility: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        memo = session.get(Memory, memory_id)
        if memo is None or memo.user_id != user_id:
            return None
        if content is not None:
            memo.content = content
        if visibility is not None:
            memo.visibility = visibility
        session.flush()
        return _to_dict(memo)


def delete_memory(user_id: str, memory_id: str) -> bool:
    with session_scope() as session:
        memo = session.get(Memory, memory_id)
        if memo is None or memo.user_id != user_id:
            return False
        session.delete(memo)
        return True


def delete_all_memories(user_id: str) -> int:
    with session_scope() as session:
        stmt = sa_delete(Memory).where(Memory.user_id == user_id)
        result = session.execute(stmt)
        return result.rowcount


def delete_all_conversations(user_id: str) -> int:
    with session_scope() as session:
        stmt = sa_delete(Conversation).where(Conversation.user_id == user_id)
        result = session.execute(stmt)
        return result.rowcount


def delete_all_action_items(user_id: str) -> int:
    with session_scope() as session:
        stmt = sa_delete(ActionItem).where(ActionItem.user_id == user_id)
        result = session.execute(stmt)
        return result.rowcount


# --- Chat sessions --------------------------------------------------------


def create_chat_session(
    user_id: str,
    *,
    session_id: Optional[str] = None,
    title: Optional[str] = None,
    app_id: Optional[str] = None,
) -> Dict[str, Any]:
    with session_scope() as session:
        sess = ChatSession(
            id=session_id or str(uuid4()),
            user_id=user_id,
            title=title or "New Chat",
            app_id=app_id,
        )
        session.add(sess)
        session.flush()
        return _to_dict(sess)


def get_chat_session(user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        sess = session.get(ChatSession, session_id)
        if sess is None or sess.user_id != user_id:
            return None
        return _to_dict(sess)


def list_chat_sessions(
    user_id: str,
    *,
    app_id: Optional[str] = None,
    starred: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with session_scope() as session:
        stmt = select(ChatSession).where(ChatSession.user_id == user_id)
        if app_id is not None:
            stmt = stmt.where(ChatSession.app_id == app_id)
        if starred is not None:
            stmt = stmt.where(ChatSession.starred == starred)
        rows = (
            session.execute(stmt.order_by(ChatSession.updated_at.desc()).limit(limit).offset(offset))
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


def update_chat_session(
    user_id: str,
    session_id: str,
    *,
    title: Optional[str] = None,
    starred: Optional[bool] = None,
    preview: Optional[str] = None,
    message_count: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        sess = session.get(ChatSession, session_id)
        if sess is None or sess.user_id != user_id:
            return None
        if title is not None:
            sess.title = title
        if starred is not None:
            sess.starred = starred
        if preview is not None:
            sess.preview = preview
        if message_count is not None:
            sess.message_count = message_count
        session.flush()
        return _to_dict(sess)


def delete_chat_session(user_id: str, session_id: str) -> bool:
    with session_scope() as session:
        sess = session.get(ChatSession, session_id)
        if sess is None or sess.user_id != user_id:
            return False
        session.delete(sess)
        return True


# --- Staged tasks ---------------------------------------------------------


def create_staged_task(
    user_id: str,
    description: str,
    *,
    task_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    score: float = 0.0,
) -> Dict[str, Any]:
    with session_scope() as session:
        task = StagedTask(
            id=task_id or str(uuid4()),
            user_id=user_id,
            description=description,
            score=score,
            conversation_id=conversation_id,
        )
        session.add(task)
        session.flush()
        return _to_dict(task)


def list_staged_tasks(user_id: str, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(StagedTask)
                .where(StagedTask.user_id == user_id)
                .where(StagedTask.completed.is_(False))
                .order_by(StagedTask.score.desc(), StagedTask.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [_to_dict(r) for r in rows]


def delete_staged_task(user_id: str, task_id: str) -> bool:
    with session_scope() as session:
        task = session.get(StagedTask, task_id)
        if task is None or task.user_id != user_id:
            return False
        session.delete(task)
        return True


def promote_top_staged_task(user_id: str) -> Optional[Dict[str, Any]]:
    """Move the highest-scored staged task into action_items and return the new item."""
    with session_scope() as session:
        task = (
            session.execute(
                select(StagedTask)
                .where(StagedTask.user_id == user_id)
                .where(StagedTask.completed.is_(False))
                .order_by(StagedTask.score.desc(), StagedTask.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if task is None:
            return None
        item = ActionItem(
            id=str(uuid4()),
            user_id=user_id,
            description=task.description,
            conversation_id=task.conversation_id,
            score=task.score,
        )
        session.add(item)
        session.delete(task)
        session.flush()
        return _to_dict(item)
