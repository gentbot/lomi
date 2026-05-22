"""ORM models for the local SQL persistence layer.

Mirrors the document shapes the Firestore-backed code stored. Field choices
prioritize compatibility with existing Pydantic models in ``models/`` over
strict normalization — JSON columns capture nested structures (segments,
people, etc.) so the local mode can round-trip records without a schema
migration for every nested shape.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import JSON

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    extra = Column(JSON, default=dict, nullable=False)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("Memory", back_populates="user", cascade="all, delete-orphan")
    action_items = relationship("ActionItem", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title = Column(String, nullable=True)
    status = Column(String, default="completed", nullable=False)
    language = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    transcript_segments = Column(JSON, default=list, nullable=False)
    structured = Column(JSON, default=dict, nullable=False)
    extra = Column(JSON, default=dict, nullable=False)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role = Column(String, nullable=False)  # "user" | "assistant" | "system"
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    extra = Column(JSON, default=dict, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


Index("ix_messages_conv_seq", Message.conversation_id, Message.sequence)


class Memory(Base):
    __tablename__ = "memories"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=True, index=True)
    visibility = Column(String, default="private", nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    extra = Column(JSON, default=dict, nullable=False)

    user = relationship("User", back_populates="memories")


class ChatMessage(Base):
    """Standalone desktop chat messages (not tied to a Conversation)."""

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    text = Column(Text, nullable=False)
    sender = Column(String, nullable=False)  # "human" | "ai"
    app_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    rating = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    metadata_ = Column("metadata", Text, nullable=True)

    user = relationship("User")


class UserSettings(Base):
    """Key/value store for per-user settings (assistant prefs, etc.)."""

    __tablename__ = "user_settings"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    assistant_settings = Column(JSON, default=dict, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User")


class ChatSession(Base):
    """Desktop chat sessions — each represents a named conversation thread."""

    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title = Column(String, default="New Chat", nullable=False)
    preview = Column(String, nullable=True)
    app_id = Column(String, nullable=True, index=True)
    message_count = Column(Integer, default=0, nullable=False)
    starred = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User")


class StagedTask(Base):
    """Conversation-extracted tasks awaiting promotion to the main action-items list."""

    __tablename__ = "staged_tasks"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    description = Column(Text, nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    indent_level = Column(Integer, default=0, nullable=False)
    conversation_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    extra = Column(JSON, default=dict, nullable=False)

    user = relationship("User")


class ActionItem(Base):
    __tablename__ = "action_items"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    description = Column(Text, nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True)
    score = Column(Float, default=0.0, nullable=False)
    conversation_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    extra = Column(JSON, default=dict, nullable=False)

    user = relationship("User", back_populates="action_items")
