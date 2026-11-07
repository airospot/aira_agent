"""DSN host redaction for repository logs."""

from app.adapters.db.agents.repositories.conversation_memory_repository import (
    ConversationMemoryRepository,
)


def test_safe_dsn_host_strips_userinfo():
    dsn = "postgresql://secret_user:s3cretPass@db.internal:5432/NATIVE_FLOW"
    out = ConversationMemoryRepository._safe_dsn_host(dsn)
    assert "s3cretPass" not in out
    assert "secret_user" not in out
    assert "db.internal:5432/NATIVE_FLOW" == out
