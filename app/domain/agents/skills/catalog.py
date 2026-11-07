"""Server allowlist for selectable skill ids (form/GET only)."""

from __future__ import annotations

from app.domain.agents.skills.errors import SkillError

STANDARD_SKILL_ID = "standard"
DOCUMENT_REVIEW_SKILL_ID = "document-review"

# Only these ids may appear on the wire. Version/tools never come from the client.
ALLOWED_SKILL_IDS = frozenset({STANDARD_SKILL_ID, DOCUMENT_REVIEW_SKILL_ID})

# Skills that load files under agent_skills/<id>/
FILE_BACKED_SKILL_IDS = frozenset({DOCUMENT_REVIEW_SKILL_ID})


def normalize_skill_id(raw: object) -> str:
    text = str(raw if raw is not None else "").strip().lower()
    if not text:
        return STANDARD_SKILL_ID
    if text not in ALLOWED_SKILL_IDS:
        raise SkillError(
            "unknown_skill_id",
            f"Bilinmeyen skill_id: {text!r}. İzin verilenler: standard, document-review.",
        )
    return text
