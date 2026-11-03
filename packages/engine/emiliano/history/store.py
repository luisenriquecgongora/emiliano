"""
Chat history storage: chats and their messages in a local SQLite database
(~/.emiliano/history.db by default, or EMILIANO_HISTORY_DB).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DEFAULT_TITLE = "New chat"
TITLE_LENGTH = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    # SQLite returns naive datetimes; they are stored in UTC
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def default_database_url() -> str:
    path = Path(os.environ.get("EMILIANO_HISTORY_DB") or Path.home() / ".emiliano" / "history.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String, default=DEFAULT_TITLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    messages: Mapped[List["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Message.id"
    )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "message_count": self.message_count,
        }


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String)  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    chat: Mapped[Chat] = relationship(back_populates="messages")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "role": self.role,
            "content": self.content,
            "created_at": _iso(self.created_at),
        }


class HistoryStore:
    """Reads and writes chats. Every method opens its own short database session."""

    def __init__(self, url: Optional[str] = None):
        self.engine = create_engine(url or default_database_url(), connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # SQLite leaves them off by default
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    def create_chat(self, title: Optional[str] = None) -> Dict:
        with self._session.begin() as db:
            chat = Chat(title=(title or DEFAULT_TITLE).strip()[:TITLE_LENGTH] or DEFAULT_TITLE)
            db.add(chat)
            db.flush()
            return chat.to_dict()

    def list_chats(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._session() as db:
            chats = db.scalars(select(Chat).order_by(Chat.updated_at.desc()).limit(limit).offset(offset))
            return [c.to_dict() for c in chats]

    def get_chat(self, chat_id: str) -> Optional[Dict]:
        """Returns the chat with its messages, or None if it does not exist."""
        with self._session() as db:
            chat = db.get(Chat, chat_id)
            if chat is None:
                return None
            return {**chat.to_dict(), "messages": [m.to_dict() for m in chat.messages]}

    def delete_chat(self, chat_id: str) -> bool:
        with self._session.begin() as db:
            chat = db.get(Chat, chat_id)
            if chat is None:
                return False
            db.delete(chat)
            return True

    def delete_all(self) -> int:
        with self._session.begin() as db:
            chats = list(db.scalars(select(Chat)))
            for chat in chats:
                db.delete(chat)
            return len(chats)

    def add_message(self, chat_id: str, role: str, content: str) -> Optional[Dict]:
        """Appends a message; the first user message also becomes the chat's title."""
        with self._session.begin() as db:
            chat = db.get(Chat, chat_id)
            if chat is None:
                return None
            message = Message(chat_id=chat_id, role=role, content=content)
            db.add(message)
            chat.message_count += 1
            chat.updated_at = _now()
            if role == "user" and chat.title == DEFAULT_TITLE:
                first_line = " ".join(content.split())
                chat.title = first_line[:TITLE_LENGTH] + ("…" if len(first_line) > TITLE_LENGTH else "")
            db.flush()
            return message.to_dict()

    def conversation(self, chat_id: str) -> List[Dict[str, str]]:
        """The chat's messages as model input: [{"role": ..., "content": ...}, ...]."""
        with self._session() as db:
            chat = db.get(Chat, chat_id)
            return [{"role": m.role, "content": m.content} for m in chat.messages] if chat else []

    def replace_messages(self, chat_id: str, new_messages: List[Dict[str, str]]) -> bool:
        """Replaces all messages in a chat (used by conversation compaction)."""
        with self._session.begin() as db:
            chat = db.get(Chat, chat_id)
            if chat is None:
                return False
            chat.messages.clear()
            for m in new_messages:
                chat.messages.append(Message(chat_id=chat_id, role=m.get("role", "system"), content=m.get("content", "")))
            chat.message_count = len(new_messages)
            chat.updated_at = _now()
            return True
