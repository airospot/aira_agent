#!/usr/bin/env python3
"""Re-embed conversation_memory rows for the current Ollama profile.

Does not delete messages. Default is dry-run. Requires explicit --apply.

  python scripts/backfill_conversation_embeddings.py --dry-run
  python scripts/backfill_conversation_embeddings.py --apply --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

load_dotenv(os.path.join(ROOT, ".env"), override=False)

from app.domain.agents.embeddings.ollama_embed import (  # noqa: E402
    EMBEDDING_DIMENSIONS,
    embed_document,
    embedding_config_from_env,
    profile_metadata,
)


def _dsn() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url
    host = os.environ["POSTGRES_HOST"]
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ["POSTGRES_DB"]
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write embeddings (disables dry-run).",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--customer-id", type=int, default=None)
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument(
        "--include-current-profile",
        action="store_true",
        help="Also re-embed rows already tagged with the current profile.",
    )
    args = parser.parse_args()
    dry = not args.apply
    cfg = embedding_config_from_env()
    profile = cfg["profile"]
    print(f"target_profile={profile} dry_run={dry} limit={args.limit}")

    conn = psycopg2.connect(_dsn())
    cur = conn.cursor(cursor_factory=RealDictCursor)
    where = ["message_content IS NOT NULL", "length(trim(message_content)) > 0"]
    params: list = []
    if args.customer_id is not None:
        where.append("customer_id = %s")
        params.append(args.customer_id)
    if args.user_id is not None:
        where.append("user_id = %s")
        params.append(args.user_id)
    if not args.include_current_profile:
        where.append(
            "(metadata->>'embedding_profile' IS DISTINCT FROM %s OR embedding IS NULL)"
        )
        params.append(profile)
    sql = f"""
        SELECT id, message_content, metadata
        FROM conversation_memory
        WHERE {' AND '.join(where)}
        ORDER BY id ASC
        LIMIT %s
    """
    params.append(max(1, int(args.limit)))
    cur.execute(sql, params)
    rows = cur.fetchall()
    print(f"candidates={len(rows)}")
    updated = 0
    for row in rows:
        text = (row["message_content"] or "").strip()
        if not text:
            continue
        if dry:
            print(f"dry-run would embed id={row['id']} chars={len(text)}")
            continue
        vec = embed_document(text)
        if len(vec) != EMBEDDING_DIMENSIONS:
            raise SystemExit(f"dim mismatch id={row['id']}: {len(vec)}")
        meta = row.get("metadata") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        if not isinstance(meta, dict):
            meta = {}
        meta.update(profile_metadata())
        cur.execute(
            """
            UPDATE conversation_memory
            SET embedding = %s::vector,
                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
            WHERE id = %s
            """,
            (vec, json.dumps(meta), row["id"]),
        )
        updated += 1
        print(f"updated id={row['id']}")
    if not dry:
        conn.commit()
    cur.close()
    conn.close()
    print(f"done updated={updated} dry_run={dry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
