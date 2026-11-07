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
        logger.debug(
            "ConversationMemoryRepository initialized (dsn_host=%s)",
            self._safe_dsn_host(connection_string),
        )

    @staticmethod
    def _safe_dsn_host(dsn: str) -> str:
        """Log-safe DSN fragment — never emit userinfo/password."""
        raw = str(dsn or "").strip()
        if not raw:
            return "?"
        try:
            from urllib.parse import urlparse

            parsed = urlparse(raw)
            host = parsed.hostname or "?"
            port = parsed.port or 5432
            db = (parsed.path or "/").lstrip("/") or "?"
            return f"{host}:{port}/{db}"
        except Exception:  # noqa: BLE001
            return "unparsed"
    
    def _get_connection(self):
        """Get database connection"""
        conn = psycopg2.connect(self.connection_string)
        # Set timezone to UTC
        with conn.cursor() as cursor:
            cursor.execute("SET timezone = 'UTC'")
        return conn
    
    def list_conversations(
        self,
        customer_id: int,
        user_id: int,
        page_type: str = "chat",
        limit: int = 10,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List conversations grouped by session_id with parameterized OFFSET.
        
        Args:
            customer_id: Customer ID
            user_id: User ID
            page_type: Page type filter ('chat' or 'agent_tools')
            limit: Maximum number of conversations to return
            offset: Non-negative row offset (validated)
            
        Returns:
            List of conversation summaries with session_id, title, dates
        """
        try:
            offset_n = int(offset)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid offset: {offset!r}") from exc
        if offset_n < 0:
            raise ValueError(f"Invalid offset: {offset_n}. Must be >= 0")
        try:
            limit_n = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid limit: {limit!r}") from exc
        if limit_n < 1 or limit_n > 100:
            raise ValueError(f"Invalid limit: {limit_n}. Must be between 1 and 100")

        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            logger.info(
                "list_conversations customer_id=%s user_id=%s page_type=%s limit=%s offset=%s dsn=%s",
                customer_id,
                user_id,
                page_type,
                limit_n,
                offset_n,
                self._safe_dsn_host(self.connection_string),
            )
            
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
            
            # Get session IDs with metadata (grouped by session_id).
            # Tie-break with session_id for stable pagination across equal timestamps.
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
                ORDER BY MAX(created_at) DESC, session_id ASC
                LIMIT %s OFFSET %s
            """, (customer_id, user_id, page_type, limit_n, offset_n))
            
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
