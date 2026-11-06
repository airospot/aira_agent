"""
Repository for conversation_memory data access.
CRUD operations only - no business logic.

Structured-memory tables (``extracted_memory``, ``memory_event_log``) use the
SQLAlchemy shell in ``structured_memory_repository.py`` (Phase 1 CRUD only;
no extraction). DDL/migration remains a separate team decision.
"""
from typing import List, Dict, Any
from psycopg2.extras import RealDictCursor
import psycopg2
import json
import logging

logger = logging.getLogger(__name__)


class ConversationMemoryRepository:
    """Repository for conversation_memory table - CRUD only"""
    
    def __init__(self, connection_string: str):
        """Initialize repository with database connection string
        
        Args:
            connection_string: Database connection string (required)
            
        Raises:
            ValueError: If connection_string is None or empty
        """
        if not connection_string:
            raise ValueError("connection_string is required and cannot be None or empty")
        
        self.connection_string = connection_string
        logger.debug(f"ConversationMemoryRepository initialized with connection string: {connection_string[:50]}...")
    
    def _get_connection(self):
        """Get database connection"""
        conn = psycopg2.connect(self.connection_string)
        # Set timezone to UTC
        with conn.cursor() as cursor:
            cursor.execute("SET timezone = 'UTC'")
        return conn
    
    def list_conversations(self, customer_id: int, user_id: int, page_type: str = 'chat', limit: int = 10) -> List[Dict[str, Any]]:
        """List all conversations grouped by session_id
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            page_type: Page type filter ('chat' or 'agent_tools')
            limit: Maximum number of conversations to return
            
        Returns:
            List of conversation summaries with session_id, title, dates
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            logger.info(f"🔍 [REPO] list_conversations: customer_id={customer_id}, user_id={user_id}, page_type={page_type}, limit={limit}")
            logger.info(f"🔍 [REPO] Connection string: {self.connection_string[:50]}...")
            
            # DEBUG: Check total records first
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM conversation_memory
                WHERE customer_id = %s 
                  AND user_id = %s 
                  AND page_type = %s
            """, (customer_id, user_id, page_type))
            total_count = cursor.fetchone()['total']
            logger.info(f"🔍 [REPO] Total records in DB (before grouping): {total_count}")
            
            # Get session IDs with metadata (grouped by session_id)
            cursor.execute("""
                SELECT 
                    session_id,
                    MIN(created_at) as created_at,
                    MAX(created_at) as last_message_at
                FROM conversation_memory
                WHERE customer_id = %s 
                  AND user_id = %s 
                  AND page_type = %s
                GROUP BY session_id
                ORDER BY MAX(created_at) DESC
                LIMIT %s
            """, (customer_id, user_id, page_type, limit))
            
            sessions = cursor.fetchall()
            logger.info(f"🔍 [REPO] Found {len(sessions)} sessions for page_type={page_type} (total records: {total_count})")
            conversations = []
            
            for session_row in sessions:
                session_id = session_row['session_id']
                
                # Get first user message for this session (for title)
                cursor.execute("""
                    SELECT message_content
                    FROM conversation_memory
                    WHERE customer_id = %s 
                      AND user_id = %s 
                      AND session_id = %s
                      AND page_type = %s
                      AND message_type = 'user'
                    ORDER BY sequence_number ASC NULLS LAST, created_at ASC
                    LIMIT 1
                """, (customer_id, user_id, session_id, page_type))
                
                first_user_msg = cursor.fetchone()
                
                # Get title from first user message (first 50 chars)
                if first_user_msg and first_user_msg.get('message_content'):
                    title = first_user_msg['message_content'].strip()
                    if len(title) > 50:
                        title = title[:50] + "..."
                else:
                    title = "Yeni Konuşma"
                
                conversations.append({
                    "session_id": session_id,
                    "title": title,
                    "preview": title,
                    "created_at": session_row['created_at'].isoformat() if session_row['created_at'] else None,
                    "last_message_at": session_row['last_message_at'].isoformat() if session_row['last_message_at'] else None
                })
            
            return conversations
        finally:
            cursor.close()
            conn.close()
    
    def get_conversation_messages(self, customer_id: int, user_id: int, session_id: str, page_type: str = 'chat') -> List[Dict[str, Any]]:
        """Get all messages for a specific conversation session
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            session_id: Session ID
            page_type: Page type filter
            
        Returns:
            List of messages ordered by id (ekleme sırası)
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT 
                    id,
                    message_type,
                    message_content,
                    created_at,
                    metadata
                FROM conversation_memory
                WHERE customer_id = %s 
                  AND user_id = %s 
                  AND session_id = %s
                  AND page_type = %s
                ORDER BY id ASC
            """, (customer_id, user_id, session_id, page_type))
            
            messages = cursor.fetchall()
            
            formatted_messages = []
            for msg in messages:
                # Parse metadata JSONB
                metadata = msg.get('metadata') or {}
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                
                formatted_messages.append({
                    "id": msg['id'],
                    "type": msg['message_type'],
                    "content": msg['message_content'],
                    "created_at": msg['created_at'].isoformat() if msg['created_at'] else None,
                    "metadata": metadata
                })
            
            return formatted_messages
        finally:
            cursor.close()
            conn.close()
    
    def delete_conversation(self, customer_id: int, user_id: int, session_id: str, page_type: str = 'chat') -> int:
        """Delete all messages for a conversation session
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            session_id: Session ID
            page_type: Page type filter
            
        Returns:
            Number of deleted messages
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM conversation_memory
                WHERE customer_id = %s 
                  AND user_id = %s 
                  AND session_id = %s
                  AND page_type = %s
            """, (customer_id, user_id, session_id, page_type))
            
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
        finally:
            cursor.close()
            conn.close()
