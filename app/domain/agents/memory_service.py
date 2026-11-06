"""
Memory Service for Conversation Memory Management
Handles short-term (last 10 messages) and long-term (unlimited) memory
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from flask import session
from app.adapters.db.agents.models.memory import ConversationMemory
from app.adapters.db.agents.models.base import db
from app.core.config_manager import get_config_manager_for_customer

logger = logging.getLogger(__name__)

# Constants (can be overridden by config)
SHORT_TERM_COUNT = 10  # Last 10 messages (default)
LONG_TERM_ENABLED = True  # Unlimited storage (default)
AUTO_CONTEXT_ENABLED = True  # Auto context enabled (default)

def get_short_term_count() -> int:
    """Get short-term memory count from config"""
    try:
        from app.core.config_manager import get_config_manager_for_customer
        config_manager = get_config_manager_for_customer()
        count = config_manager.get_config('memory_short_term_count')
        return int(count) if count else SHORT_TERM_COUNT
    except:
        return SHORT_TERM_COUNT

def get_long_term_enabled(customer_id: Optional[int] = None, user_id: Optional[int] = None) -> bool:
    """Get long-term memory enabled from config"""
    try:
        from app.core.config_manager import get_config_manager_for_customer
        if customer_id is None:
            try:
                customer_id = get_customer_id()
            except Exception:
                pass
        if user_id is None:
            try:
                user_id = get_user_id()
            except Exception:
                pass
        if customer_id and user_id:
            config_manager = get_config_manager_for_customer(customer_id=customer_id, user_id=user_id)
        else:
            config_manager = get_config_manager_for_customer()
        enabled = config_manager.get_config('memory_long_term_enabled')
        return bool(enabled) if enabled is not None else LONG_TERM_ENABLED
    except:
        return LONG_TERM_ENABLED

def get_auto_context_enabled() -> bool:
    """Get auto context enabled from config"""
    try:
        from app.core.config_manager import get_config_manager_for_customer
        config_manager = get_config_manager_for_customer()
        enabled = config_manager.get_config('memory_auto_context_enabled')
        return bool(enabled) if enabled is not None else AUTO_CONTEXT_ENABLED
    except:
        return AUTO_CONTEXT_ENABLED


def get_customer_id() -> int:
    """Get current customer_id from JWT context (via session hydrated from JWT).
    
    Note: Session is hydrated from JWT in _hydrate_session_from_jwt(), so this is JWT-based.
    
    Raises:
        ValueError: If customer_id not found in JWT context
    """
    # Try JWT context first (preferred)
    try:
        from app.core.context import get_customer_id_from_request
        customer_id = get_customer_id_from_request()
        if customer_id is not None:
            return int(customer_id)
    except Exception:
        pass
    
    # Fallback to session (hydrated from JWT)
    customer_id = session.get('customer_id')
    if customer_id is None:
        raise ValueError("customer_id not found in JWT context. User must be logged in.")
    return int(customer_id)


def get_user_id() -> int:
    """Get current user_id from JWT context (via session hydrated from JWT).
    
    Note: Session is hydrated from JWT in _hydrate_session_from_jwt(), so this is JWT-based.
    
    Raises:
        ValueError: If user_id not found in JWT context
    """
    # Try JWT context first (preferred)
    try:
        from app.core.context import get_user_id_from_request
        user_id = get_user_id_from_request()
        if user_id is not None:
            return int(user_id)
    except Exception:
        pass
    
    # Fallback to session (hydrated from JWT)
    user_id = session.get('user_id')
    if user_id is None:
        raise ValueError("user_id not found in JWT context. User must be logged in.")
    return int(user_id)


def _create_embedding(text: str, customer_id: Optional[int] = None, user_id: Optional[int] = None) -> Optional[List[float]]:
    """
    Create embedding for text using OpenAI (priority) or Ollama (fallback)
    
    Args:
        text: Text to create embedding for
        customer_id: Customer ID (optional, will get from session if not provided)
        user_id: User ID (optional, will get from session if not provided)
    
    Returns:
        List of floats (embedding vector) or None if failed
    """
    try:
        # Get config_manager - handle both request context and non-context cases
        try:
            if customer_id:
                from app.core.config_manager import get_config_manager_for_customer
                config_manager = get_config_manager_for_customer(customer_id=customer_id, user_id=user_id)
            else:
                config_manager = get_config_manager_for_customer()
        except Exception as e:
            # Fallback: try to get customer_id/user_id from session or use default
            try:
                customer_id = get_customer_id()
                user_id = get_user_id()
                from app.core.config_manager import get_config_manager_for_customer
                config_manager = get_config_manager_for_customer(customer_id=customer_id, user_id=user_id)
            except Exception as e2:
                logger.error(f"Could not get config_manager: {e2}")
                # Last resort: use global config_manager
                from app.core.config_manager import config_manager
        
        # Try OpenAI first
        try:
            api_key = config_manager._get_openai_api_key()
            if api_key:
                from langchain_openai import OpenAIEmbeddings
                os.environ['OPENAI_API_KEY'] = api_key
                embeddings_model = OpenAIEmbeddings()
                embedding = embeddings_model.embed_query(text)
                return embedding
        except Exception as e:
            logger.warning(f"OpenAI embedding failed: {e}, trying Ollama...")
        
        # Fallback to Ollama
        try:
            from langchain_community.embeddings import OllamaEmbeddings
            ollama_url = config_manager.get_config('ollama_url') or "http://localhost:11434"
            embeddings_model = OllamaEmbeddings(
                model="nomic-embed-text",
                base_url=ollama_url
            )
            embedding = embeddings_model.embed_query(text)
            
            # Handle Ollama 768-dim embeddings (pad to 1536)
            if len(embedding) == 768:
                embedding = list(embedding) + [0.0] * (1536 - 768)
            
            return embedding
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating embedding: {e}")
        return None


def save_message(
    page_type: str,
    session_id: str,
    message_type: str,
    message_content: str,
    metadata: Optional[Dict[str, Any]] = None,
    memory_type: str = 'short_term',
    create_embedding: bool = False,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> ConversationMemory:
    """
    Save a message to conversation memory
    
    Args:
        page_type: 'Aira', 'AiraCoder', 'chat', 'agent_tools', ...
        session_id: Session identifier (short_term penceresi bu oturum + page_type ile sınırlı)
        message_type: 'user' or 'assistant'
        message_content: Message content
        metadata: Additional metadata (tool_id, project_id, sources, etc.)
        memory_type: 'short_term' or 'long_term'
        create_embedding: Whether to create embedding for semantic search
        customer_id: Customer ID (optional, will be fetched from session if not provided)
        user_id: User ID (optional, will be fetched from session if not provided)
    
    Returns:
        ConversationMemory object
    """
    try:
        # Use provided customer_id/user_id or fetch from session
        if customer_id is None:
            customer_id = get_customer_id()
        if user_id is None:
            user_id = get_user_id()
        
        # Handle short-term memory: ayrı pencere her (user, page_type, session_id) için
        if memory_type == 'short_term':
            short_term_count = get_short_term_count()
            sequence_number = _evict_short_term_to_capacity(
                customer_id=customer_id,
                user_id=user_id,
                page_type=page_type,
                session_id=session_id,
                short_term_count=short_term_count,
            )
            expires_at = None  # Short-term doesn't expire (managed by sequence)
        else:
            # Long-term memory
            sequence_number = None
            expires_at = None  # Unlimited storage
        
        # Create new memory entry.
        # Column Python attr is ``meta_data`` (DB name ``metadata``); SQLAlchemy
        # reserves ``metadata`` on the declarative API, so kwargs named metadata
        # never reach the JSONB column.
        memory = ConversationMemory(
            customer_id=customer_id,
            user_id=user_id,
            page_type=page_type,
            session_id=session_id,
            message_type=message_type,
            message_content=message_content,
            meta_data=metadata or {},
            memory_type=memory_type,
            sequence_number=sequence_number,
            expires_at=expires_at
        )
        
        db.session.add(memory)
        db.session.flush()  # Flush to get memory.id
        
        # Commit main transaction first to ensure memory record exists in database
        db.session.commit()
        
        # Create and store embedding if requested (after commit to ensure memory.id exists)
        if create_embedding:
            try:
                embedding = _create_embedding(message_content, customer_id=customer_id, user_id=user_id)
                if embedding and len(embedding) == 1536:
                    # Store embedding using raw SQL (pgvector type)
                    # Use direct psycopg2 connection to avoid request context issues
                    import psycopg2
                    from app.core.config_manager import get_config_manager_for_customer
                    try:
                        # Try to get config_manager with customer_id
                        try:
                            config_manager = get_config_manager_for_customer(customer_id=customer_id)
                            conn = config_manager._get_connection()
                        except Exception:
                            # Fallback: direct connection
                            import os
                            from dotenv import load_dotenv
                            load_dotenv()
                            conn = psycopg2.connect(
                                host=os.getenv('POSTGRES_HOST', 'localhost'),
                                port=int(os.getenv('POSTGRES_PORT', 5432)),
                                database=os.getenv('POSTGRES_DB', 'base_project'),
                                user=os.getenv('POSTGRES_USER', 'postgres'),
                                password=os.getenv('POSTGRES_PASSWORD', 'postgres')
                            )
                        
                        cursor = conn.cursor()
                        try:
                            cursor.execute("""
                                UPDATE conversation_memory 
                                SET embedding = %s::vector 
                                WHERE id = %s
                            """, (embedding, memory.id))
                            conn.commit()
                        except Exception as e:
                            conn.rollback()
                            logger.error(f"Failed to store embedding for message {memory.id}: {e}")
                        finally:
                            cursor.close()
                            conn.close()
                    except Exception as e:
                        logger.error(f"Failed to get database connection for embedding: {e}")
                else:
                    logger.warning(f"Invalid embedding dimension: {len(embedding) if embedding else 0}")
            except Exception as e:
                logger.error(f"Failed to create embedding: {e}")
        
        logger.info(f"Saved {memory_type} message for user {user_id}, page {page_type}, sequence {sequence_number}")

        # Structured memory (Phase 2): shadow extraction only, after transcript commit.
        # Failures must not affect the persisted conversation row.
        if message_type == "user":
            try:
                from app.domain.services.structured_memory.orchestrator import (
                    process_structured_memory_candidate,
                )

                md = metadata or {}
                process_structured_memory_candidate(
                    conversation_memory_id=memory.id,
                    message_type=message_type,
                    message_content=message_content,
                    customer_id=customer_id,
                    user_id=user_id,
                    page_type=page_type,
                    session_id=session_id,
                    metadata=md,
                )
                logger.info(
                    "structured_memory hook_ok conv_msg_id=%s customer_id=%s user_id=%s "
                    "page_type=%s session_id=%s project_id=%s",
                    memory.id,
                    customer_id,
                    user_id,
                    page_type,
                    session_id,
                    md.get("project_id"),
                )
            except Exception:
                logger.exception(
                    "structured_memory post-commit hook failed (transcript is safe; ignored)"
                )
                try:
                    db.session.rollback()
                except Exception:
                    logger.exception("structured_memory rollback after hook failure")

        return memory
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving message: {e}")
        raise


def _evict_short_term_to_capacity(
    *,
    customer_id: int,
    user_id: int,
    page_type: str,
    session_id: str,
    short_term_count: int,
) -> int:
    """Ensure STM row count < capacity before insert; return next sequence_number.

    Policy:
    - Oldest **user** rows promote to long_term (unchanged product contract).
    - Orphan/old **assistant** rows that fall outside the bounded window are deleted
      (assistants are never promoted to long_term via this path).
    - After eviction, survivors are re-sequenced 1..N chronologically by id.
    """
    st_scope = ConversationMemory.query.filter_by(
        customer_id=customer_id,
        user_id=user_id,
        memory_type='short_term',
        page_type=page_type,
        session_id=session_id,
    )
    # Make room for the incoming row: while count >= cap, evict.
    while st_scope.count() >= short_term_count:
        victim_user = (
            st_scope.filter_by(message_type='user')
            .order_by(ConversationMemory.id.asc())
            .first()
        )
        if victim_user:
            # Drop assistant rows older than this user turn (orphans / prior turn tails).
            orphans = (
                st_scope.filter(
                    ConversationMemory.message_type == 'assistant',
                    ConversationMemory.id < victim_user.id,
                )
                .order_by(ConversationMemory.id.asc())
                .all()
            )
            for orphan in orphans:
                db.session.delete(orphan)
            victim_user.memory_type = 'long_term'
            victim_user.sequence_number = None
            logger.info(
                "Moved oldest short-term user message (ID: %s) to long-term for user %s "
                "session=%s page_type=%s (orphaned assistants removed=%s)",
                victim_user.id,
                user_id,
                session_id,
                page_type,
                len(orphans),
            )
            db.session.flush()
            continue

        # No user left to promote — drop oldest assistant to enforce real capacity.
        victim_asst = (
            st_scope.filter_by(message_type='assistant')
            .order_by(ConversationMemory.id.asc())
            .first()
        )
        if victim_asst:
            db.session.delete(victim_asst)
            logger.info(
                "Removed oldest short-term assistant (ID: %s) to enforce STM cap "
                "session=%s page_type=%s",
                victim_asst.id,
                session_id,
                page_type,
            )
            db.session.flush()
            continue
        break

    survivors = (
        ConversationMemory.query.filter_by(
            customer_id=customer_id,
            user_id=user_id,
            memory_type='short_term',
            page_type=page_type,
            session_id=session_id,
        )
        .order_by(ConversationMemory.id.asc())
        .all()
    )
    for i, msg in enumerate(survivors, start=1):
        msg.sequence_number = i
    db.session.flush()
    return len(survivors) + 1


def get_short_term_memory(
    page_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: Optional[int] = None,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    *,
    strict: bool = False,
) -> List[ConversationMemory]:
    """
    Get short-term memory (last N messages, newest window).

    Returns messages in chronological order (oldest→newest within the window).
    When more than ``limit`` STM rows exist, the **newest** ``limit`` rows are kept
    (not the oldest — prior ASC+limit dropped recent user turns).

    ``strict=True`` re-raises DB/identity errors instead of returning [].
    """
    try:
        if limit is None:
            limit = get_short_term_count()
        
        # Get customer_id and user_id if not provided
        if customer_id is None:
            try:
                customer_id = get_customer_id()
            except Exception:
                logger.error("customer_id not found in JWT context")
                if strict:
                    raise
                return []
        if user_id is None:
            try:
                user_id = get_user_id()
            except Exception:
                logger.error("user_id not found in JWT context")
                if strict:
                    raise
                return []
        
        query = ConversationMemory.query.filter_by(
            customer_id=customer_id,
            user_id=user_id,
            memory_type='short_term'
        )
        
        if page_type:
            query = query.filter_by(page_type=page_type)
        
        if session_id:
            query = query.filter_by(session_id=session_id)
        
        # Newest window first, then chronological for the model/UI.
        newest = (
            query.order_by(
                ConversationMemory.sequence_number.desc().nullslast(),
                ConversationMemory.id.desc(),
            )
            .limit(limit)
            .all()
        )
        messages = list(reversed(newest))
        return messages
        
    except Exception as e:
        logger.error(f"Error getting short-term memory: {e}")
        if strict:
            raise
        return []


def get_long_term_memory(
    page_type: Optional[str] = None,
    session_id: Optional[str] = None,
    days_back: Optional[int] = None,
    limit: int = 50,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    *,
    strict: bool = False,
) -> List[ConversationMemory]:
    """
    Get long-term memory (unlimited storage) - Date-based filtering
    
    Args:
        page_type: Filter by page type ('chat' or 'agent_tools'), None for all
        session_id: Filter by session_id, None for all sessions
        days_back: Number of days to look back, None for all
        limit: Maximum number of messages
        strict: Re-raise errors instead of returning []
    
    Returns:
        List of ConversationMemory objects (ordered by created_at DESC)
    """
    try:
        # Get customer_id and user_id if not provided
        if customer_id is None:
            try:
                customer_id = get_customer_id()
            except Exception:
                logger.error("customer_id not found in JWT context")
                if strict:
                    raise
                return []
        if user_id is None:
            try:
                user_id = get_user_id()
            except Exception:
                logger.error("user_id not found in JWT context")
                if strict:
                    raise
                return []
        
        query = ConversationMemory.query.filter_by(
            customer_id=customer_id,
            user_id=user_id,
            memory_type='long_term'
        )
        
        if page_type:
            query = query.filter_by(page_type=page_type)
        
        if session_id:
            query = query.filter_by(session_id=session_id)
        
        if days_back:
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            query = query.filter(ConversationMemory.created_at >= cutoff_date)
        
        # Order by created_at DESC (newest first)
        messages = query.order_by(ConversationMemory.created_at.desc()).limit(limit).all()
        
        return messages
        
    except Exception as e:
        logger.error(f"Error getting long-term memory: {e}")
        if strict:
            raise
        return []


def get_long_term_memory_semantic(
    query: str,
    page_type: Optional[str] = None,
    exclude_session_id: Optional[str] = None,
    limit: int = 5,
    similarity_threshold: float = 0.7,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    *,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """
    Get long-term memory using semantic search (vector similarity)
    
    Args:
        query: Search query text
        page_type: Filter by page type ('chat' or 'agent_tools'), None for all
        exclude_session_id: Exclude messages from this session_id (to avoid duplicates with short-term)
        limit: Maximum number of results
        similarity_threshold: Minimum similarity score (0.0-1.0)
        strict: Re-raise identity/DB errors (embedding miss still returns [] — product policy)
    
    Returns:
        List of dicts with ConversationMemory objects and similarity scores
        Format: [{'memory': ConversationMemory, 'similarity': float}, ...]
    """
    try:
        # Get customer_id and user_id if not provided
        if customer_id is None:
            try:
                customer_id = get_customer_id()
            except Exception as e:
                logger.error(f"Cannot get customer_id: {e}")
                if strict:
                    raise
                return []
        if user_id is None:
            try:
                user_id = get_user_id()
            except Exception as e:
                logger.error(f"Cannot get user_id: {e}")
                if strict:
                    raise
                return []
        
        # Create query embedding
        query_embedding = _create_embedding(query, customer_id=customer_id, user_id=user_id)
        if not query_embedding or len(query_embedding) != 1536:
            logger.warning(f"Failed to create query embedding or invalid dimension: {len(query_embedding) if query_embedding else 0}")
            # Embedding absent is an empty retrieval result, not a hard DB failure.
            return []
        
        # Get database connection - use direct connection to avoid request context issues
        import psycopg2
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        try:
            config_manager = get_config_manager_for_customer(customer_id=customer_id)
            conn = config_manager._get_connection()
        except Exception:
            # Fallback: direct connection
            conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'localhost'),
                port=int(os.getenv('POSTGRES_PORT', 5432)),
                database=os.getenv('POSTGRES_DB', 'base_project'),
                user=os.getenv('POSTGRES_USER', 'postgres'),
                password=os.getenv('POSTGRES_PASSWORD', 'postgres')
            )
        
        cursor = conn.cursor()
        
        try:
            # Build SQL query with filters
            # Note: Search both short_term and long_term (as short_term records also have embeddings)
            sql = """
                SELECT 
                    id,
                    1 - (embedding <=> %s::vector) as similarity
                FROM conversation_memory
                WHERE customer_id = %s
                  AND user_id = %s
                  AND embedding IS NOT NULL
            """
            params = [query_embedding, customer_id, user_id]
            
            if page_type:
                sql += " AND page_type = %s"
                params.append(page_type)
            
            if exclude_session_id:
                sql += " AND session_id != %s"
                params.append(exclude_session_id)
            
            sql += """
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            params.extend([query_embedding, limit])
            
            cursor.execute(sql, params)
            results = cursor.fetchall()
            
            # Filter by similarity threshold and load ConversationMemory objects
            memory_results = []
            for memory_id, similarity in results:
                if similarity >= similarity_threshold:
                    memory = ConversationMemory.query.get(memory_id)
                    if memory:
                        memory_results.append({
                            'memory': memory,
                            'similarity': float(similarity)
                        })
            
            if memory_results:
                logger.info(f"🔍 [SEMANTIC_SEARCH] Found {len(memory_results)} semantically similar long-term messages (threshold: {similarity_threshold})")
            else:
                logger.debug(f"Found 0 semantically similar long-term messages (threshold: {similarity_threshold})")
            return memory_results
            
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            if strict:
                raise
            return []
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"Error getting long-term memory semantic: {e}")
        if strict:
            raise
        return []


def get_conversation_context(
    page_type: Optional[str] = None,
    session_id: Optional[str] = None,
    include_long_term: bool = True,
    use_semantic_search: bool = True,
    query: Optional[str] = None,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Get formatted conversation context for LLM
    
    Args:
        page_type: Filter by page type, None for all
        session_id: Filter by session_id, None for all sessions
        include_long_term: Include long-term memory in context
        use_semantic_search: Use semantic search for long-term memory (if True and query provided)
        query: Current user query for semantic search (optional, uses last user message if not provided)
        metadata: Optional scope hints for structured memory (e.g. ``project_id``).
    
    Returns:
        Formatted context string for LLM
    """
    try:
        context_parts = []
        
        # Get customer_id and user_id if not provided
        if customer_id is None:
            try:
                customer_id = get_customer_id()
            except Exception:
                customer_id = None
        if user_id is None:
            try:
                user_id = get_user_id()
            except Exception:
                user_id = None

        # Phase 3: structured block first (only when enabled and not shadow-only)
        if customer_id is not None and user_id is not None:
            try:
                from app.domain.services.structured_memory.settings import (
                    load_structured_memory_flags,
                    should_inject_structured_into_prompt,
                )
                from app.domain.services.structured_memory.lifecycle import (
                    expire_due_extracted_memories,
                )
                from app.domain.services.structured_memory import retrieval as sm_retrieval

                flags = load_structured_memory_flags(int(customer_id), int(user_id))
                if flags.enabled:
                    try:
                        expire_due_extracted_memories(int(customer_id), int(user_id))
                    except Exception as ex:
                        logger.warning(
                            "structured_memory expiry failed customer_id=%s user_id=%s: %s",
                            customer_id,
                            user_id,
                            ex,
                            exc_info=True,
                        )
                if should_inject_structured_into_prompt(flags):
                    block = sm_retrieval.build_structured_context_block(
                        customer_id=int(customer_id),
                        user_id=int(user_id),
                        session_id=session_id,
                        query=query,
                        metadata=metadata,
                        flags=flags,
                    )
                    if block:
                        context_parts.append(block)
            except Exception as e:
                logger.warning(
                    "structured_memory read path skipped customer_id=%s user_id=%s: %s",
                    customer_id,
                    user_id,
                    e,
                    exc_info=True,
                )
        
        # Get short-term memory (last 10 messages)
        short_term = get_short_term_memory(
            page_type=page_type,
            session_id=session_id,
            customer_id=customer_id,
            user_id=user_id
        )
        if short_term:
            context_parts.append("=== Recent Conversation (Short-term Memory) ===")
            for msg in short_term:
                role = "User" if msg.message_type == 'user' else "Assistant"
                context_parts.append(f"[{role}]: {msg.message_content}")
                if msg.meta_data:
                    # Add relevant metadata
                    if 'tool_id' in msg.meta_data:
                        context_parts.append(f"  (Tool: {msg.meta_data.get('tool_id')})")
                    if 'project_id' in msg.meta_data:
                        context_parts.append(f"  (Project ID: {msg.meta_data.get('project_id')})")
            context_parts.append("")
        
        # Get long-term memory (if enabled)
        if include_long_term and get_long_term_enabled(customer_id=customer_id, user_id=user_id):
            # Use semantic search if enabled and query provided
            if use_semantic_search and query:
                semantic_results = get_long_term_memory_semantic(
                    query=query,
                    page_type=page_type,
                    exclude_session_id=session_id,  # Exclude current session to avoid duplicates
                    limit=5,
                    similarity_threshold=0.7,
                    customer_id=customer_id,
                    user_id=user_id
                )
                if semantic_results:
                    logger.info(f"🔍 [SEMANTIC_SEARCH] Found {len(semantic_results)} relevant past conversations")
                if semantic_results:
                    context_parts.append("=== Relevant Past Conversations (Long-term Memory - Semantic Search) ===")
                    for result in semantic_results:
                        msg = result['memory']
                        similarity = result['similarity']
                        role = "User" if msg.message_type == 'user' else "Assistant"
                        date_str = msg.created_at.strftime("%Y-%m-%d") if msg.created_at else "Unknown"
                        context_parts.append(f"[{date_str}] [{role}] (Similarity: {similarity:.1%}): {msg.message_content[:200]}...")
                    context_parts.append("")
            else:
                # Fallback to date-based filtering
                long_term = get_long_term_memory(
                    page_type=page_type,
                    session_id=session_id,
                    days_back=30,
                    limit=5,
                    customer_id=customer_id,
                    user_id=user_id
                )
                if long_term:
                    context_parts.append("=== Relevant Past Conversations (Long-term Memory) ===")
                    for msg in long_term[:5]:  # Limit to 5 most relevant
                        role = "User" if msg.message_type == 'user' else "Assistant"
                        date_str = msg.created_at.strftime("%Y-%m-%d") if msg.created_at else "Unknown"
                        context_parts.append(f"[{date_str}] [{role}]: {msg.message_content[:200]}...")  # Truncate long messages
                    context_parts.append("")
        
        if context_parts:
            return "\n".join(context_parts)
        else:
            return ""
            
    except Exception as e:
        logger.error(f"Error getting conversation context: {e}")
        return ""


def cleanup_expired_memory():
    """
    Cleanup expired short-term memory (if expires_at is set)
    This is a background task that can be run periodically
    """
    try:
        # Delete messages where expires_at < now
        deleted = ConversationMemory.query.filter(
            ConversationMemory.expires_at.isnot(None),
            ConversationMemory.expires_at < datetime.utcnow()
        ).delete()
        
        db.session.commit()
        logger.info(f"Cleaned up {deleted} expired memory entries")
        return deleted
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cleaning up expired memory: {e}")
        return 0

