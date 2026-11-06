"""
SQLAlchemy ORM shell for structured memory tables (Phase 1).

**No migrations in this PR.** Tables must be created via your agreed migration
path before INSERT/SELECT against these models will succeed in production.

Column set is a minimal persistence shell; extraction (Phase 2+) fills semantics.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index

from app.adapters.db.agents.models.base import db


class ExtractedMemory(db.Model):
    """
    Normalized / structured memory row (PROPOSED table name ``extracted_memory``).

    ``user_id`` is the JWT/RequestContext user id (integer); no FK to ``users`` in
    reference DDL (deployments without a local users table).
    """

    __tablename__ = "extracted_memory"
    __table_args__ = (
        Index(
            "ix_extracted_memory_customer_user_status",
            "customer_id",
            "user_id",
            "status",
        ),
        Index(
            "ix_extracted_memory_customer_user_project",
            "customer_id",
            "user_id",
            "project_id",
        ),
        Index(
            "ix_extracted_memory_customer_session",
            "customer_id",
            "user_id",
            "session_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    memory_category = db.Column(
        db.String(64),
        nullable=False,
        doc="e.g. user_preference, user_constraint, project_decision, resolved_issue",
    )
    memory_text = db.Column(db.Text, nullable=False)
    scope_type = db.Column(db.String(64), nullable=True)
    scope_value = db.Column(db.String(512), nullable=True)
    session_id = db.Column(
        db.String(512),
        nullable=True,
        doc="Transcript/chat session at capture (denormalized for audit and analytics).",
    )
    project_id = db.Column(
        db.Integer,
        nullable=True,
        doc="Project id from message metadata when present (denormalized).",
    )
    status = db.Column(db.String(32), nullable=False, default="active")
    confidence = db.Column(db.Float, nullable=True)
    importance = db.Column(db.Integer, nullable=False, default=0)
    provenance_json = db.Column(db.JSON, nullable=True)
    source_conversation_memory_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_memory.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_id = db.Column(
        db.Integer,
        db.ForeignKey("extracted_memory.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<ExtractedMemory {self.id} {self.memory_category!r}>"


class MemoryEventLog(db.Model):
    """
    Append-only audit log for structured memory (PROPOSED ``memory_event_log``).

    ``event_type`` must be one of ``MEMORY_EVENT_TYPES_V1`` in
    ``app.domain.services.structured_memory`` (enforced in business layer later).
    """

    __tablename__ = "memory_event_log"
    __table_args__ = (
        Index(
            "ix_memory_event_log_customer_user_created",
            "customer_id",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_memory_event_log_customer_project_created",
            "customer_id",
            "project_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    event_type = db.Column(db.String(64), nullable=False)
    extracted_memory_id = db.Column(
        db.Integer,
        db.ForeignKey("extracted_memory.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_memory_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_memory.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id = db.Column(db.String(512), nullable=True)
    project_id = db.Column(db.Integer, nullable=True)
    payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<MemoryEventLog {self.id} {self.event_type!r}>"
