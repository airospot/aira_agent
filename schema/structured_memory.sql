-- Derived from app/adapters/db/airacoder/models/structured_memory_tables.py
-- The source tree states these tables have no migration script.
-- Apply after conversation_memory exists.

CREATE TABLE IF NOT EXISTS extracted_memory (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    memory_category VARCHAR(64) NOT NULL,
    memory_text TEXT NOT NULL,
    scope_type VARCHAR(64),
    scope_value VARCHAR(512),
    session_id VARCHAR(512),
    project_id INTEGER,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    confidence DOUBLE PRECISION,
    importance INTEGER NOT NULL DEFAULT 0,
    provenance_json JSONB,
    source_conversation_memory_id INTEGER REFERENCES conversation_memory(id) ON DELETE SET NULL,
    supersedes_id INTEGER REFERENCES extracted_memory(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_extracted_memory_customer_user_status
    ON extracted_memory (customer_id, user_id, status);
CREATE INDEX IF NOT EXISTS ix_extracted_memory_customer_user_project
    ON extracted_memory (customer_id, user_id, project_id);
CREATE INDEX IF NOT EXISTS ix_extracted_memory_customer_session
    ON extracted_memory (customer_id, user_id, session_id);

CREATE TABLE IF NOT EXISTS memory_event_log (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    extracted_memory_id INTEGER REFERENCES extracted_memory(id) ON DELETE SET NULL,
    conversation_memory_id INTEGER REFERENCES conversation_memory(id) ON DELETE SET NULL,
    session_id VARCHAR(512),
    project_id INTEGER,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_memory_event_log_customer_user_created
    ON memory_event_log (customer_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_memory_event_log_customer_project_created
    ON memory_event_log (customer_id, project_id, created_at);
