"""Frozen v1 contracts for structured memory."""

# Append-only memory_event_log.event_type (v1)
MEMORY_EVENT_TYPES_V1 = frozenset(
    {
        "CREATED",
        "MERGED",
        "REJECTED_SENSITIVE",
        "REJECTED_LOW_CONFIDENCE",
        "SKIPPED_DISABLED",
        "SKIPPED_NON_USER",
        "SUPERSEDED",
        "EXPIRED",
        "USER_FORGOTTEN",
    }
)
