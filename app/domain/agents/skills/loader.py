"""Safe file-backed skill loader (repo-rooted; no request/cwd derivation)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.domain.agents.skills.catalog import (
    FILE_BACKED_SKILL_IDS,
    STANDARD_SKILL_ID,
    normalize_skill_id,
)
from app.domain.agents.skills.errors import SkillError
from app.domain.agents.skills.schema import SKILL_METADATA_SCHEMA
from app.domain.agents.skills.snapshot import SkillResource, SkillSnapshot

_INSTRUCTIONS_NAME = "SKILL.md"
_METADATA_NAME = "skill.json"


def package_skills_root() -> Path:
    """``<repo>/agent_skills`` — derived from this package file, not cwd/request."""
    # app/domain/agents/skills/loader.py → parents[4] = repo root
    return Path(__file__).resolve().parents[4] / "agent_skills"


def parse_skill_max_bytes(config: Mapping[str, Any] | None) -> int:
    """AGENT_SKILL_MAX_BYTES — required positive int; no code numeric fallback."""
    cfg = dict(config or {})
    raw = cfg.get("AGENT_SKILL_MAX_BYTES")
    if raw is None or str(raw).strip() == "":
        raw = os.environ.get("AGENT_SKILL_MAX_BYTES")
    if raw is None or str(raw).strip() == "":
        raise SkillError(
            "skill_config_invalid",
            "AGENT_SKILL_MAX_BYTES gerekli (kodda numeric fallback yok).",
        )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise SkillError(
            "skill_config_invalid",
            f"Geçersiz AGENT_SKILL_MAX_BYTES={raw!r}",
        ) from exc
    if value < 1:
        raise SkillError(
            "skill_config_invalid",
            f"AGENT_SKILL_MAX_BYTES pozitif olmalı, got {value}",
        )
    return value


def _digest_payload(
    *,
    metadata: Mapping[str, Any],
    instructions: str,
    resources: list[tuple[str, str]],
) -> str:
    payload = {
        "metadata": dict(metadata),
        "instructions": instructions,
        "resources": [
            {"name": name, "content": content}
            for name, content in sorted(resources, key=lambda item: item[0])
        ],
    }
    raw = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _assert_contained(root: Path, candidate: Path) -> Path:
    root_res = root.resolve()
    if candidate.exists() and candidate.is_symlink():
        raise SkillError(
            "skill_path_escape",
            "Skill dosyasında symlink kabul edilmez.",
        )
    try:
        cand_res = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise SkillError(
            "skill_resource_missing",
            f"Skill dosyası yok: {candidate.name}",
        ) from exc
    try:
        cand_res.relative_to(root_res)
    except ValueError as exc:
        raise SkillError(
            "skill_path_escape",
            "Skill yolu skill kökü dışında veya symlink kaçışı.",
        ) from exc
    return cand_res


def _resolve_relative(skill_root: Path, relative: str) -> Path:
    text = str(relative or "").strip()
    if not text:
        raise SkillError("skill_path_escape", "Boş skill relative path.")
    path = Path(text)
    if path.is_absolute():
        raise SkillError("skill_path_escape", "Absolute skill path reddedildi.")
    if ".." in path.parts or path.parts[:1] == ("/",):
        raise SkillError("skill_path_escape", "Traversal skill path reddedildi.")
    return _assert_contained(skill_root, skill_root / path)


def _read_limited(path: Path, *, max_bytes: int, label: str) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise SkillError(
            "skill_too_large",
            f"{label} {size} byte; AGENT_SKILL_MAX_BYTES={max_bytes} aşıldı.",
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise SkillError(
            "skill_too_large",
            f"{label} okuma sonrası limit aşıldı.",
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError(
            "skill_invalid",
            f"{label} UTF-8 değil.",
        ) from exc


def load_skill_snapshot(
    skill_id: object,
    *,
    config: Mapping[str, Any] | None,
    skills_root: Path | None = None,
) -> SkillSnapshot | None:
    """Load immutable snapshot or None for standard. Raises SkillError on failure."""
    normalized = normalize_skill_id(skill_id)
    if normalized == STANDARD_SKILL_ID:
        return None
    if normalized not in FILE_BACKED_SKILL_IDS:
        raise SkillError("unknown_skill_id", f"Dosya tabanlı skill değil: {normalized}")

    max_bytes = parse_skill_max_bytes(config)
    root = (skills_root or package_skills_root()).resolve()
    skill_dir = root / normalized
    if not skill_dir.is_dir():
        raise SkillError(
            "skill_missing",
            f"Skill dizini yok: {normalized}",
        )
    # Ensure skill_dir itself is under root (no symlink root escape).
    try:
        skill_dir.resolve(strict=True).relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise SkillError(
            "skill_path_escape",
            "Skill dizini kök dışında.",
        ) from exc

    meta_path = _resolve_relative(skill_dir, _METADATA_NAME)
    instructions_path = _resolve_relative(skill_dir, _INSTRUCTIONS_NAME)

    # Cap individual reads; also enforce total across metadata+instructions+resources.
    meta_text = _read_limited(meta_path, max_bytes=max_bytes, label=_METADATA_NAME)
    try:
        metadata = json.loads(meta_text)
    except json.JSONDecodeError as exc:
        raise SkillError("skill_invalid", "skill.json bozuk JSON.") from exc
    if not isinstance(metadata, dict):
        raise SkillError("skill_invalid", "skill.json nesne olmalı.")

    try:
        Draft202012Validator(SKILL_METADATA_SCHEMA).validate(metadata)
    except ValidationError as exc:
        raise SkillError(
            "skill_invalid",
            f"skill.json şema hatası: {exc.message}",
        ) from exc

    if str(metadata.get("id") or "") != normalized:
        raise SkillError(
            "skill_invalid",
            "skill.json id allowlist/dizin ile eşleşmiyor.",
        )

    allowed = frozenset(str(x) for x in metadata["allowed_tools"])
    required = frozenset(str(x) for x in metadata["required_tools"])
    if not required <= allowed:
        raise SkillError(
            "skill_invalid",
            "required_tools, allowed_tools alt kümesi olmalı.",
        )

    instructions = _read_limited(
        instructions_path, max_bytes=max_bytes, label=_INSTRUCTIONS_NAME
    )
    total = len(meta_text.encode("utf-8")) + len(instructions.encode("utf-8"))

    resource_rows: list[SkillResource] = []
    resource_pairs: list[tuple[str, str]] = []
    for entry in metadata.get("resources") or []:
        name = str(entry["name"])
        rel = str(entry["path"])
        res_path = _resolve_relative(skill_dir, rel)
        # Reject paths that resolve into another skill directory.
        try:
            res_path.relative_to(skill_dir.resolve())
        except ValueError as exc:
            raise SkillError(
                "skill_path_escape",
                "Resource başka skill köküne çıkıyor.",
            ) from exc
        content = _read_limited(res_path, max_bytes=max_bytes, label=rel)
        total += len(content.encode("utf-8"))
        if total > max_bytes:
            raise SkillError(
                "skill_too_large",
                f"Skill toplam boyutu AGENT_SKILL_MAX_BYTES={max_bytes} aşıldı.",
            )
        resource_rows.append(
            SkillResource(name=name, relative_path=rel, content=content)
        )
        resource_pairs.append((name, content))

    digest = _digest_payload(
        metadata=metadata,
        instructions=instructions,
        resources=resource_pairs,
    )
    completion = metadata.get("completion_requirements") or {}
    requires_read = bool(
        isinstance(completion, dict)
        and completion.get("content_answer_requires_file_read")
    )
    return SkillSnapshot(
        skill_id=normalized,
        version=str(metadata["version"]),
        description=str(metadata["description"]),
        instructions=instructions,
        allowed_tools=allowed,
        required_tools=required,
        resources=tuple(resource_rows),
        content_digest=digest,
        content_answer_requires_file_read=requires_read,
    )


def bind_skill_tools(
    snapshot: SkillSnapshot | None,
    *,
    server_permitted: frozenset[str],
    registry_names: frozenset[str],
) -> frozenset[str]:
    """Intersect skill allowed_tools with server permission; require required_tools."""
    if snapshot is None:
        return frozenset(server_permitted)
    effective = frozenset(server_permitted) & snapshot.allowed_tools
    missing_registry = snapshot.required_tools - registry_names
    if missing_registry:
        raise SkillError(
            "skill_not_ready",
            "Skill için gerekli araç registry'de yok: "
            + ", ".join(sorted(missing_registry)),
        )
    missing_perm = snapshot.required_tools - effective
    if missing_perm:
        raise SkillError(
            "skill_not_ready",
            "Skill için gerekli araç sunucu izninde yok: "
            + ", ".join(sorted(missing_perm)),
        )
    return effective
