#!/usr/bin/env python3
"""Copy legacy shared corpus into one tenant corpus (dry-run by default).

Does not delete sources. Does not invent DOCX originals from MD.
Requires explicit --source and --tenant. Use --apply to write.

Example:
  python scripts/migrate_shared_corpus_to_tenant.py \\
    --source data/corpus --tenant 9 --tenant-data-root data/tenants
  python scripts/migrate_shared_corpus_to_tenant.py \\
    --source data/corpus --tenant 9 --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Report:
    copied: list[str] = field(default_factory=list)
    skipped_exists: list[str] = field(default_factory=list)
    original_unavailable: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "copied": list(self.copied),
            "skipped_exists": list(self.skipped_exists),
            "original_unavailable": list(self.original_unavailable),
            "errors": list(self.errors),
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def migrate(
    *,
    source: Path,
    tenant_id: int,
    tenant_data_root: Path,
    apply: bool,
) -> Report:
    report = Report()
    if tenant_id <= 0:
        report.errors.append("tenant_id_invalid")
        return report
    if not source.is_dir():
        report.errors.append(f"source_missing:{source}")
        return report

    dest_corpus = tenant_data_root / str(tenant_id) / "corpus"
    dest_uploads = tenant_data_root / str(tenant_id) / "uploads"

    # Walk files; preserve relative paths under corpus.
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(source).as_posix()
        except ValueError:
            report.errors.append(f"outside_source:{path}")
            continue
        if ".." in Path(rel).parts:
            report.errors.append(f"path_traversal:{rel}")
            continue

        target = dest_corpus / rel
        if target.exists():
            try:
                if target.is_file() and _sha256_file(target) == _sha256_file(path):
                    report.skipped_exists.append(rel)
                    continue
                report.errors.append(f"conflict_different_content:{rel}")
                continue
            except OSError as exc:
                report.errors.append(f"conflict_stat:{rel}:{type(exc).__name__}")
                continue

        # MD under extracted_data without a sibling original DOCX/PPTX/PDF → note only.
        if (
            rel.startswith("extracted_data/")
            and path.name == "content.md"
            and path.parent.is_dir()
        ):
            meta_path = path.parent / "meta.json"
            source_name = ""
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    source_name = str((meta or {}).get("source_filename") or "")
                except (OSError, json.JSONDecodeError):
                    source_name = ""
            # Original office file is not in shared corpus layout — report unavailable.
            if source_name:
                report.original_unavailable.append(
                    f"{rel}:original_unavailable:{source_name}"
                )
            else:
                report.original_unavailable.append(f"{rel}:original_unavailable")

        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        report.copied.append(rel)

    if apply:
        dest_corpus.mkdir(parents=True, exist_ok=True)
        dest_uploads.mkdir(parents=True, exist_ok=True)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Legacy shared corpus dir")
    parser.add_argument("--tenant", required=True, type=int, help="Target customer_id")
    parser.add_argument(
        "--tenant-data-root",
        type=Path,
        default=Path("data/tenants"),
        help="TENANT_DATA_ROOT (default data/tenants)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform copy (default is dry-run)",
    )
    args = parser.parse_args(argv)

    report = migrate(
        source=args.source.resolve(),
        tenant_id=int(args.tenant),
        tenant_data_root=args.tenant_data_root.resolve(),
        apply=bool(args.apply),
    )
    payload = {
        "dry_run": not args.apply,
        "source": str(args.source),
        "tenant": int(args.tenant),
        "tenant_data_root": str(args.tenant_data_root),
        **report.to_dict(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
