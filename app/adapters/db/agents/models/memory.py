"""
Conversation Memory Model
Handles long-term and short-term memory for chat and agent-tools pages
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector

from app.adapters.db.agents.models.base import db


class ConversationMemory(db.Model):
    """Conversation memory table - Multi-tenant"""
    __tablename__ = 'conversation_memory'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False)
    # No FK to users: local baseline has no auth user table.
    user_id = db.Column(db.Integer, nullable=False)
    page_type = db.Column(db.String(50), nullable=False)  # 'chat', 'agent_tools', 'Agent', ...
    session_id = db.Column(db.String(255), nullable=False)
    message_type = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    message_content = db.Column(db.Text, nullable=False)
    meta_data = db.Column('metadata', db.JSON, default=dict)  # JSONB in PostgreSQL (column name: metadata)
    memory_type = db.Column(db.String(20), nullable=False, default='short_term')  # 'short_term' or 'long_term'
    sequence_number = db.Column(db.Integer)  # For short-term ordering (1-10)
    # DB column is pgvector; Text/VARCHAR bind broke NULL inserts (DatatypeMismatch).
    embedding = db.Column(Vector(1536), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)  # NULL for long-term (unlimited)

    def __repr__(self):
        return f'<ConversationMemory {self.id} - {self.page_type} - {self.message_type}>'
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'user_id': self.user_id,
            'page_type': self.page_type,
            'session_id': self.session_id,
            'message_type': self.message_type,
            'message_content': self.message_content,
            'metadata': self.meta_data or {},
            'memory_type': self.memory_type,
            'sequence_number': self.sequence_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }


# Register structured-memory ORM (Phase 1 shell). No runtime hooks here.
from app.adapters.db.agents.models.structured_memory_tables import (  # noqa: E402, F401
    ExtractedMemory,
    MemoryEventLog,
)

