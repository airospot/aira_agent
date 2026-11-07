"""OFFSET pagination: Service → Repository (two tenants / pages)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters.db.agents.repositories.conversation_memory_repository import (
    ConversationMemoryRepository,
)
from app.domain.services.conversations.conversation_service import ConversationService


def test_service_rejects_negative_offset():
    repo = MagicMock(spec=ConversationMemoryRepository)
    svc = ConversationService(repo)
    with pytest.raises(ValueError, match="offset"):
        svc.list_conversations(customer_id=1, user_id=1, page_type="Agent", offset=-1)


def test_service_passes_offset_to_repo_for_two_pages():
    repo = MagicMock(spec=ConversationMemoryRepository)
    repo.list_conversations.side_effect = [
        [{"session_id": "s0", "title": "a"}],
        [{"session_id": "s1", "title": "b"}],
    ]
    svc = ConversationService(repo)

    page0 = svc.list_conversations(
        customer_id=10, user_id=20, page_type="Agent", limit=1, offset=0
    )
    page1 = svc.list_conversations(
        customer_id=10, user_id=20, page_type="Agent", limit=1, offset=1
    )

    assert page0[0]["session_id"] == "s0"
    assert page1[0]["session_id"] == "s1"
    assert repo.list_conversations.call_args_list[0].kwargs["offset"] == 0
    assert repo.list_conversations.call_args_list[1].kwargs["offset"] == 1
    assert repo.list_conversations.call_args_list[0].kwargs["customer_id"] == 10


def test_service_isolates_tenant_filters_across_offsets():
    repo = MagicMock(spec=ConversationMemoryRepository)
    repo.list_conversations.return_value = []
    svc = ConversationService(repo)

    svc.list_conversations(
        customer_id=1, user_id=2, page_type="chat", limit=5, offset=0
    )
    svc.list_conversations(
        customer_id=99, user_id=88, page_type="Agent", limit=5, offset=10
    )

    c0 = repo.list_conversations.call_args_list[0].kwargs
    c1 = repo.list_conversations.call_args_list[1].kwargs
    assert (c0["customer_id"], c0["user_id"], c0["page_type"], c0["offset"]) == (
        1,
        2,
        "chat",
        0,
    )
    assert (c1["customer_id"], c1["user_id"], c1["page_type"], c1["offset"]) == (
        99,
        88,
        "Agent",
        10,
    )


def test_repo_rejects_invalid_offset_before_sql():
    repo = ConversationMemoryRepository("postgresql://u:p@127.0.0.1:5432/db")
    with pytest.raises(ValueError, match="offset"):
        repo.list_conversations(1, 1, offset=-3)
