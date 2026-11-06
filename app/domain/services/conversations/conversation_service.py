"""
Conversation Service
Domain service for conversation management.
Business logic and validation - no HTTP/DB details.
"""
from typing import Optional, List, Dict, Any
import logging
from app.adapters.db.agents.repositories.conversation_memory_repository import ConversationMemoryRepository

logger = logging.getLogger(__name__)


class ConversationService:
    """Domain service for conversation management
    
    Responsibilities:
    - Business logic for conversation operations
    - Business validation
    - Business rules
    
    NOT Responsibilities:
    - HTTP handling (API layer)
    - Database queries (Repository layer)
    """
    
    def __init__(self, conversation_repository: ConversationMemoryRepository):
        """Initialize conversation service
        
        Args:
            conversation_repository: ConversationMemoryRepository instance
        """
        self.conversation_repository = conversation_repository
    
    def list_conversations(self, customer_id: int, user_id: int, page_type: str = 'chat', limit: int = 10) -> List[Dict[str, Any]]:
        """List conversations for user
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            page_type: Page type filter
            limit: Maximum number of conversations
            
        Returns:
            List of conversation summaries
        """
        # Business validation
        if not customer_id or not user_id:
            raise ValueError("customer_id and user_id are required")
        
        if page_type not in ['Aira', 'AiraCoder', 'chat', 'agent_tools', 'Agent']:
            raise ValueError(
                f"Invalid page_type: {page_type}. "
                "Must be 'Aira', 'AiraCoder', 'chat', 'agent_tools', or 'Agent'"
            )
        
        if limit < 1 or limit > 100:
            raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 100")
        
        # Repository call
        conversations = self.conversation_repository.list_conversations(
            customer_id=customer_id,
            user_id=user_id,
            page_type=page_type,
            limit=limit
        )
        
        logger.debug(f"Retrieved {len(conversations)} conversations for user {user_id}")
        return conversations
    
    def get_conversation_messages(self, customer_id: int, user_id: int, session_id: str, page_type: str = 'chat') -> List[Dict[str, Any]]:
        """Get all messages for a conversation session
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            session_id: Session ID
            page_type: Page type filter
            
        Returns:
            List of messages
            
        Raises:
            ValueError: If conversation not found
        """
        # Business validation
        if not customer_id or not user_id:
            raise ValueError("customer_id and user_id are required")
        
        if not session_id:
            raise ValueError("session_id is required")
        
        if page_type not in ['Aira', 'AiraCoder', 'chat', 'agent_tools', 'Agent']:
            raise ValueError(
                f"Invalid page_type: {page_type}. "
                "Must be 'Aira', 'AiraCoder', 'chat', 'agent_tools', or 'Agent'"
            )
        
        # Repository call
        messages = self.conversation_repository.get_conversation_messages(
            customer_id=customer_id,
            user_id=user_id,
            session_id=session_id,
            page_type=page_type
        )
        
        if not messages:
            raise ValueError(f"Conversation '{session_id}' not found")
        
        logger.debug(f"Retrieved {len(messages)} messages for session {session_id}")
        return messages
    
    def delete_conversation(self, customer_id: int, user_id: int, session_id: str, page_type: str = 'chat') -> int:
        """Delete a conversation session
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            session_id: Session ID
            page_type: Page type filter
            
        Returns:
            Number of deleted messages
            
        Raises:
            ValueError: If validation fails
        """
        # Business validation
        if not customer_id or not user_id:
            raise ValueError("customer_id and user_id are required")
        
        if not session_id:
            raise ValueError("session_id is required")
        
        if page_type not in ['Aira', 'AiraCoder', 'chat', 'agent_tools', 'Agent']:
            raise ValueError(
                f"Invalid page_type: {page_type}. "
                "Must be 'Aira', 'AiraCoder', 'chat', 'agent_tools', or 'Agent'"
            )
        
        # Repository call
        deleted_count = self.conversation_repository.delete_conversation(
            customer_id=customer_id,
            user_id=user_id,
            session_id=session_id,
            page_type=page_type
        )
        
        if deleted_count == 0:
            raise ValueError(f"Conversation '{session_id}' not found or already deleted")
        
        logger.info(f"Deleted {deleted_count} messages for session {session_id}")
        return deleted_count
