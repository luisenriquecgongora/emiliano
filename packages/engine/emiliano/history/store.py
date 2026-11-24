"""
Chat history storage: chats, messages, projects, and artifacts in a local SQLite database
(~/.emiliano/history.db by default, or EMILIANO_HISTORY_DB).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    root_path: Mapped[str] = mapped_column(String, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    chats: Mapped[List["Chat"]] = relationship(
        back_populates="project", cascade="all", order_by="Chat.updated_at.desc()"
    )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "root_path": self.root_path,
            "system_prompt": self.system_prompt,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "chat_count": len(self.chats) if self.chats else 0,
        }


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String, default=DEFAULT_TITLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Optional[Project]] = relationship(back_populates="chats")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Message.id"
    )
    artifacts: Mapped[List["Artifact"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Artifact.created_at.desc()"
    )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
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
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    chat: Mapped[Chat] = relationship(back_populates="messages")

    def to_dict(self) -> Dict:
        res = {
            "id": self.id,
            "chat_id": self.chat_id,
            "role": self.role,
            "content": self.content,
            "created_at": _iso(self.created_at),
        }
        if self.reasoning:
            res["reasoning"] = self.reasoning
        if self.metrics:
            try:
                res["metrics"] = json.loads(self.metrics)
            except Exception:
                res["metrics"] = self.metrics
        if self.tool_calls:
            try:
                res["tool_calls"] = json.loads(self.tool_calls)
            except Exception:
                res["tool_calls"] = self.tool_calls
        return res


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, default="markdown")  # "code" | "diagram" | "plan" | "diff" | "markdown"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    chat: Mapped[Optional[Chat]] = relationship(back_populates="artifacts")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "project_id": self.project_id,
            "title": self.title,
            "kind": self.kind,
            "content": self.content,
            "file_path": self.file_path,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class HistoryStore:
    """Reads and writes chats, projects, and artifacts. Every method opens its own short database session."""

    def __init__(self, url: Optional[str] = None):
        self.engine = create_engine(url or default_database_url(), connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # SQLite leaves them off by default
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)

        # Non-destructive migration for existing chats & messages tables
        with self.engine.connect() as conn:
            cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(chats)")]
            if "project_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE chats ADD COLUMN project_id TEXT REFERENCES projects(id)")
                conn.commit()
            msg_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(messages)")]
            if "reasoning" not in msg_cols:
                conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN reasoning TEXT")
                conn.commit()
            if "metrics" not in msg_cols:
                conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN metrics TEXT")
                conn.commit()
            if "tool_calls" not in msg_cols:
                conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN tool_calls TEXT")
                conn.commit()

        self._session = sessionmaker(self.engine, expire_on_commit=False)
        self._ensure_seeds()

    def _ensure_seeds(self) -> None:
        """Seeds initial default local projects (Oracliom, PlaatoOS Outreach) and workspace deliverables."""
        try:
            with self._session.begin() as db:
                if not db.get(Project, "oracliom-main"):
                    default_proj = Project(
                        id="oracliom-main",
                        name="Oracliom",
                        description="Autonomous Desktop Cowork & Meta-Harness",
                        root_path=r"C:\Users\artlu\OracliomNew\Oracliom",
                        system_prompt="Autonomous desktop cowoker with high bias for action and PolyForm compliance.",
                    )
                    db.add(default_proj)

                plaatoos_path = Path(r"C:\Users\artlu\OracliomNew\Oracliom\emiliano-cowork-plaatoos")
                if plaatoos_path.exists() and not db.get(Project, "plaatoos-outreach"):
                    plaatoos_proj = Project(
                        id="plaatoos-outreach",
                        name="PlaatoOS Outreach",
                        description="Autonomous lead prospecting, Instagram DM cowork, and B2B email engine",
                        root_path=str(plaatoos_path),
                        system_prompt="PlaatoOS autonomous growth agent. High bias for action, CRM audit logging, and anti-bot humanized delivery.",
                    )
                    db.add(plaatoos_proj)

                job_search_path = Path(r"C:\Users\artlu\OracliomNew\Oracliom\ai-job-search")
                if not db.get(Project, "ai-job-search"):
                    job_proj = Project(
                        id="ai-job-search",
                        name="Autonomous Job Hunter",
                        description="Autonomous AI job search, position diagnostics, ATS-tailored CVs & cover letters, and Chrome cowork autofill",
                        root_path=str(job_search_path),
                        system_prompt=(
                            "Autonomous job search and career engineering agent. Specializes in job position diagnostics, "
                            "zero-hallucination ATS CV tailoring, prompt injection / canary trap neutralization, "
                            "anti-AI detector stylometrics (high burstiness, no clichés), and browser cowork form completion."
                        ),
                    )
                    db.add(job_proj)

                job_plan_file = Path(r"C:\Users\artlu\.gemini\antigravity-cli\brain\341564c4-af40-4a75-af75-ae781c806de9\job_hunter_autonomous_plan.md")
                if not db.get(Artifact, "art-job-hunter-plan"):
                    content = job_plan_file.read_text(encoding="utf-8") if job_plan_file.exists() else "# Autonomous Job Hunter Architecture & State of the Art\n\nPosition diagnostics, ATS tailoring, and Chrome cowork."
                    db.add(Artifact(
                        id="art-job-hunter-plan",
                        project_id="ai-job-search",
                        title="Autonomous Job Hunter Architecture & SOTA Plan",
                        kind="markdown",
                        content=content,
                        file_path=str(job_plan_file) if job_plan_file.exists() else None,
                    ))

                user_cv_file = Path(r"C:\Users\artlu\OracliomNew\Oracliom\JobsApplication\LUIS CASTILLO - RESUME - 2026 - JULY-4.pdf")
                if user_cv_file.exists() and not db.get(Artifact, "art-luis-castillo-cv"):
                    db.add(Artifact(
                        id="art-luis-castillo-cv",
                        project_id="ai-job-search",
                        title="Luis Castillo Master Resume (July 2026)",
                        kind="text",
                        content="Master Candidate Resume for Luis Castillo (Senior Software Engineer, 9+ yrs exp). Located in JobsApplication.",
                        file_path=str(user_cv_file),
                    ))

                tracker_file = job_search_path / "tools" / "job_application_tracker.html"
                if tracker_file.exists() and not db.get(Artifact, "art-job-tracker-crm"):
                    db.add(Artifact(
                        id="art-job-tracker-crm",
                        project_id="ai-job-search",
                        title="Job Applications & CV Variant Tracker CRM",
                        kind="html",
                        content=tracker_file.read_text(encoding="utf-8"),
                        file_path=str(tracker_file),
                    ))

                if not db.get(Artifact, "art-outreach-analysis"):
                    analysis_file = Path(r"C:\Users\artlu\.gemini\antigravity-cli\brain\8fbaa064-7416-4540-8a08-956d9cba103b\state_of_the_art_outreach_analysis.md")
                    content = analysis_file.read_text(encoding="utf-8") if analysis_file.exists() else "# Autonomous B2B Outreach Engine Analysis\n\nPolyForm Shield 1.0.0 compliance and multi-channel architecture."
                    default_art = Artifact(
                        id="art-outreach-analysis",
                        project_id="oracliom-main",
                        title="Autonomous Outreach Architecture & Analysis",
                        kind="markdown",
                        content=content,
                        file_path=str(analysis_file) if analysis_file.exists() else None,
                    )
                    db.add(default_art)

                ext_file = plaatoos_path / "extension.json"
                if ext_file.exists() and not db.get(Artifact, "art-plaatoos-manifest"):
                    ext_content = ext_file.read_text(encoding="utf-8")
                    db.add(Artifact(
                        id="art-plaatoos-manifest",
                        project_id="plaatoos-outreach",
                        title="PlaatoOS Extension Manifest & Capabilities",
                        kind="code",
                        content=ext_content,
                        file_path=str(ext_file),
                    ))

                pipeline_file = plaatoos_path / "pipeline_dashboard.html"
                pipeline_content = pipeline_file.read_text(encoding="utf-8") if pipeline_file.exists() else "<h1>PlaatoOS Pipeline Dashboard</h1>"
                if not db.get(Artifact, "art-plaatoos-pipeline"):
                    db.add(Artifact(
                        id="art-plaatoos-pipeline",
                        project_id="plaatoos-outreach",
                        title="Multi-Channel Outreach Pipeline & Architecture",
                        kind="html",
                        content=pipeline_content,
                        file_path=str(pipeline_file) if pipeline_file.exists() else None,
                    ))
        except Exception:
            pass

    # -------------------------------------------------------------
    # CHATS
    # -------------------------------------------------------------
    def create_chat(self, title: Optional[str] = None, project_id: Optional[str] = None) -> Dict:
        with self._session.begin() as db:
            chat = Chat(
                title=(title or DEFAULT_TITLE).strip()[:TITLE_LENGTH] or DEFAULT_TITLE,
                project_id=project_id,
            )
            db.add(chat)
            db.flush()
            return chat.to_dict()

    def list_chats(self, limit: int = 50, offset: int = 0, project_id: Optional[str] = None) -> List[Dict]:
        with self._session() as db:
            query = select(Chat).order_by(Chat.updated_at.desc())
            if project_id:
                query = query.where(Chat.project_id == project_id)
            chats = db.scalars(query.limit(limit).offset(offset))
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

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        reasoning: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict]:
        """Appends a message; the first user message also becomes the chat's title."""
        with self._session.begin() as db:
            chat = db.get(Chat, chat_id)
            if chat is None:
                return None
            metrics_str = json.dumps(metrics) if metrics else None
            tool_calls_str = json.dumps(tool_calls) if tool_calls else None
            message = Message(
                chat_id=chat_id,
                role=role,
                content=content,
                reasoning=reasoning,
                metrics=metrics_str,
                tool_calls=tool_calls_str,
            )
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

    # -------------------------------------------------------------
    # PROJECTS (Local Workspaces)
    # -------------------------------------------------------------
    def list_projects(self) -> List[Dict]:
        with self._session() as db:
            projects = db.scalars(select(Project).order_by(Project.updated_at.desc()))
            return [p.to_dict() for p in projects]

    def create_project(self, name: str, root_path: str = "", description: str = "", system_prompt: str = "") -> Dict:
        with self._session.begin() as db:
            project = Project(
                name=name.strip(),
                root_path=root_path.strip(),
                description=description.strip(),
                system_prompt=system_prompt.strip(),
            )
            db.add(project)
            db.flush()
            return project.to_dict()

    def get_project(self, project_id: str) -> Optional[Dict]:
        with self._session() as db:
            project = db.get(Project, project_id)
            if project is None:
                return None
            return {
                **project.to_dict(),
                "chats": [c.to_dict() for c in project.chats],
            }

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        root_path: Optional[str] = None,
        description: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[Dict]:
        with self._session.begin() as db:
            project = db.get(Project, project_id)
            if project is None:
                return None
            if name is not None:
                project.name = name.strip()
            if root_path is not None:
                project.root_path = root_path.strip()
            if description is not None:
                project.description = description.strip()
            if system_prompt is not None:
                project.system_prompt = system_prompt.strip()
            project.updated_at = _now()
            db.flush()
            return project.to_dict()

    def delete_project(self, project_id: str) -> bool:
        with self._session.begin() as db:
            project = db.get(Project, project_id)
            if project is None:
                return False
            db.delete(project)
            return True

    # -------------------------------------------------------------
    # ARTIFACTS (Local Persistent Deliverable Registry)
    # -------------------------------------------------------------
    def list_artifacts(
        self,
        chat_id: Optional[str] = None,
        project_id: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[Dict]:
        with self._session() as db:
            query = select(Artifact).order_by(Artifact.created_at.desc())
            if chat_id:
                query = query.where(Artifact.chat_id == chat_id)
            if project_id:
                query = query.where(Artifact.project_id == project_id)
            if kind:
                query = query.where(Artifact.kind == kind)
            artifacts = db.scalars(query)
            return [a.to_dict() for a in artifacts]

    def create_artifact(
        self,
        title: str,
        kind: str,
        content: str,
        chat_id: Optional[str] = None,
        project_id: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Dict:
        with self._session.begin() as db:
            artifact = Artifact(
                title=title.strip(),
                kind=kind.strip(),
                content=content,
                chat_id=chat_id,
                project_id=project_id,
                file_path=file_path,
            )
            db.add(artifact)
            db.flush()
            return artifact.to_dict()

    def get_artifact(self, artifact_id: str) -> Optional[Dict]:
        with self._session() as db:
            artifact = db.get(Artifact, artifact_id)
            return artifact.to_dict() if artifact else None

    def delete_artifact(self, artifact_id: str) -> bool:
        with self._session.begin() as db:
            artifact = db.get(Artifact, artifact_id)
            if artifact is None:
                return False
            db.delete(artifact)
            return True
