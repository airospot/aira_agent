#!/usr/bin/env python3
"""
Migration: Add embedding column to conversation_memory table
This enables semantic search for long-term memory using pgvector
"""

import psycopg2
import os
import sys

# PostgreSQL connection config
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'database': os.getenv('POSTGRES_DB', 'base_project'),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres')
}

def add_embedding_column():
    """Add embedding column and vector index to conversation_memory table"""
    print("🔄 Adding embedding column to conversation_memory table...")
    
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cursor = conn.cursor()
    
    try:
        # Check if pgvector extension exists
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("  ✅ pgvector extension checked/created")
        
        # Check if embedding column already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'conversation_memory' 
                AND column_name = 'embedding'
            )
        """)
        
        if cursor.fetchone()[0]:
            print("  ⚠️ embedding column already exists, skipping...")
        else:
            print("  📦 Adding embedding column...")
            # Add embedding column (nullable, for existing records)
            cursor.execute("""
                ALTER TABLE conversation_memory 
                ADD COLUMN embedding vector(1536)
            """)
            print("  ✅ embedding column added")
        
        # Check if vector index already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_indexes 
                WHERE tablename = 'conversation_memory' 
                AND indexname = 'idx_conversation_memory_vector'
            )
        """)
        
        if cursor.fetchone()[0]:
            print("  ⚠️ vector index already exists, skipping...")
        else:
            print("  📦 Creating vector index...")
            # Create ivfflat index for vector similarity search
            cursor.execute("""
                CREATE INDEX idx_conversation_memory_vector 
                ON conversation_memory 
                USING ivfflat (embedding vector_cosine_ops) 
                WITH (lists = 100)
                WHERE embedding IS NOT NULL
            """)
            print("  ✅ vector index created")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"  ❌ Error adding embedding column: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    try:
        add_embedding_column()
        print("\n✅ Migration completed successfully!")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)

