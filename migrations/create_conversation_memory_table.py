#!/usr/bin/env python3
"""
Migration: Create conversation_memory table
This enables long-term and short-term memory for chat and agent-tools pages
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from migrations._db import connect  # noqa: E402

def create_table_if_not_exists(cursor):
    """Create conversation_memory table if it doesn't exist"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'conversation_memory'
        )
    """)
    
    if not cursor.fetchone()[0]:
        print("  📦 Creating conversation_memory table...")
        
        # Create table
        cursor.execute("""
            CREATE TABLE conversation_memory (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                page_type VARCHAR(50) NOT NULL,
                session_id VARCHAR(255) NOT NULL,
                message_type VARCHAR(20) NOT NULL,
                message_content TEXT NOT NULL,
                metadata JSONB DEFAULT '{}',
                memory_type VARCHAR(20) NOT NULL DEFAULT 'short_term',
                sequence_number INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITH TIME ZONE
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_customer_user 
            ON conversation_memory(customer_id, user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_session 
            ON conversation_memory(session_id, created_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_page_type 
            ON conversation_memory(page_type, created_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_memory_type 
            ON conversation_memory(memory_type, created_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_sequence 
            ON conversation_memory(customer_id, user_id, memory_type, sequence_number)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_expires 
            ON conversation_memory(expires_at) WHERE expires_at IS NOT NULL
        """)
        
        print("  ✅ conversation_memory table created successfully")
        return True
    return False

def create_conversation_memory_table():
    """Create conversation_memory table"""
    print("🔄 Creating conversation_memory table...")

    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Create table if it doesn't exist
        table_created = create_table_if_not_exists(cursor)
        if table_created:
            conn.commit()
            print("\n✅ Migration completed successfully!")
            return
        
        print("  ⚠️ conversation_memory table already exists, skipping...")
        
    except Exception as e:
        conn.rollback()
        print(f"  ❌ Error creating conversation_memory table: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    try:
        create_conversation_memory_table()
        print("\n✅ Migration completed successfully!")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)

