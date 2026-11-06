#!/usr/bin/env python3
"""Migration: Create agent_submissions table for propose idempotency."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from migrations._db import connect  # noqa: E402


def create_agent_submissions_table() -> None:
    print("🔄 Creating agent_submissions table...")
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agent_submissions'
            )
            """
        )
        if cursor.fetchone()[0]:
            print("  ⚠️ agent_submissions table already exists, skipping...")
            return

        cursor.execute(
            """
            CREATE TABLE agent_submissions (
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                submission_id VARCHAR(64) NOT NULL,
                session_id VARCHAR(255),
                request_hash VARCHAR(64) NOT NULL,
                status VARCHAR(20) NOT NULL,
                result_json JSONB,
                error TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP WITH TIME ZONE,
                PRIMARY KEY (customer_id, user_id, submission_id),
                CONSTRAINT agent_submissions_status_chk
                    CHECK (status IN ('processing', 'completed', 'failed'))
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_agent_submissions_status_created
            ON agent_submissions (status, created_at)
            """
        )
        conn.commit()
        print("  ✅ agent_submissions table created")
        print("\n✅ Migration completed successfully!")
    except Exception as exc:
        conn.rollback()
        print(f"  ❌ Error creating agent_submissions table: {exc}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    try:
        create_agent_submissions_table()
    except Exception as exc:
        print(f"\n❌ Migration failed: {exc}")
        sys.exit(1)
