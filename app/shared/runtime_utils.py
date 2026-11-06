import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4


SECRET_FIELD_HINTS = {"secret", "password", "token", "api_key", "apikey", "credential"}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix):
    return f"{prefix}:{uuid4()}"


def stable_hash(value):
    payload = json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# Keys excluded from review/materialization baseline hash (UI/group projection noise).
_BASELINE_HASH_EXCLUDE = frozenset(
    {
        "primary_group_id",
        "group_ids",
        "group_labels",
        "editable_fields",
        "evidence_cards",
        "reason_options",
        "field_truth_labels",
        "recommendations",
    }
)


def canonical_baseline_definition(definition):
    """Single canonical current-state projection for review hash + materialization base.

    Must be used by both KnowledgeEditService review creation and
    MaterializationService._current_definition — never hash full UI projection in one
    place and narrow current_state in another.
    """
    if not isinstance(definition, dict):
        return {}
    return {
        key: value
        for key, value in definition.items()
        if key not in _BASELINE_HASH_EXCLUDE and not str(key).startswith("_")
    }


def canonical_baseline_hash(definition):
    return stable_hash(canonical_baseline_definition(definition))


def redact_secrets(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if is_secret_field(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def is_secret_field(field_name):
    normalized = (field_name or "").lower()
    return any(hint in normalized for hint in SECRET_FIELD_HINTS)


def require_actor(actor):
    forbidden = {"", "user:placeholder", "browser:user", "user:local"}
    text = str(actor or "").strip()
    if text in forbidden:
        raise ValueError("Authenticated actor zorunludur.")
    return text

