"""The agent bridge uses the embedding profile's calibrated retrieval threshold."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.domain.agents import memory_service
from app.domain.agents.flow.memory.bridge import _load_long_term_block


def test_agent_bridge_retains_cross_language_hit_above_profile_threshold():
    score = 0.55
    memory = SimpleNamespace(
        session_id="previous-conversation",
        message_type="user",
        message_content="Uzaktan erişimde çok faktörlü doğrulama zorunludur.",
        created_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
    )

    def retrieve(*, similarity_threshold=memory_service.DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD, **kwargs):
        assert kwargs["exclude_session_id"] == "current-conversation"
        assert kwargs["customer_id"] == 101
        assert kwargs["user_id"] == 11
        return [{"memory": memory, "similarity": score}] if score >= similarity_threshold else []

    with (
        patch.object(memory_service, "get_long_term_enabled", return_value=True),
        patch.object(memory_service, "get_long_term_memory_semantic", side_effect=retrieve),
        patch.object(memory_service, "get_long_term_memory", return_value=[]),
    ):
        block, mode, entries = _load_long_term_block(
            session_id="current-conversation",
            customer_id=101,
            user_id=11,
            query="Is multifactor authentication required for remote access?",
        )

    assert mode == "semantic"
    assert len(entries) == 1
    assert entries[0]["similarity"] == score
    assert memory.message_content in block
