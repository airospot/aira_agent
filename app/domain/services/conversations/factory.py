"""
Factory for creating conversation service instances
"""
from app.domain.services.conversations.conversation_service import ConversationService
from app.adapters.db.agents.repositories.conversation_memory_repository import ConversationMemoryRepository


def create_conversation_service(connection_string: str) -> ConversationService:
    """Create ConversationService instance
    
    Args:
        connection_string: Database connection string (required)
        
    Returns:
        ConversationService instance
        
    Raises:
        ValueError: If connection_string is None or empty
    """
    conversation_repo = ConversationMemoryRepository(connection_string=connection_string)
    return ConversationService(conversation_repository=conversation_repo)
