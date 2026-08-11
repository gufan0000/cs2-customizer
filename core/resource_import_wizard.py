# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic resource import helpers for audio + visual assets."""

from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

from core.resource_catalog import build_spec_lookup, iter_resource_specs, resolve_import_domain


def _normalize_extension(filename: str) -> str:
    _stem, ext = os.path.splitext(str(filename or ""))
    return ext.strip().lower()


def _extract_target_rel_path(source_dir: str, source_file: str, domain: str) -> Optional[Dict[str, str]]:
    rel_path = os.path.relpath(source_file, source_dir)
    parts = list(os.path.normpath(rel_path).split(os.sep))
    spec_lookup = build_spec_lookup(resolve_import_domain(domain))
    for idx, part in enumerate(parts):
        spec = spec_lookup.get(str(part or "").strip().lower())
        if not spec:
            continue
        tail = parts[idx + 1 :]
        if not tail:
            return None
        return {
            "spec_key": spec.key,
            "spec_label": spec.label,
            "target_rel_path": os.path.join(spec.target_rel_root, *tail),
            "domain": spec.domain,
        }
    return None


def scan_resource_import_candidates(
    source_dir: str,
    resources_root: str,
    domain: str = "audio",
) -> Dict[str, object]:
    recognized: List[Dict[str, object]] = []
    unrecognized: List[Dict[str, str]] = []
    scanned_resource_files = 0

    source_dir = os.path.abspath(str(source_dir or ""))
    resources_root = os.path.abspath(str(resources_root or ""))
    selected_specs = iter_resource_specs(resolve_import_domain(domain))
    allowed_exts = {ext.lower() for spec in selected_specs for ext in spec.extensions}

    if not source_dir or not os.path.isdir(source_dir):
        return {
            "source_dir": source_dir,
            "resources_root": resources_root,
            "domain": domain,
            "recognized": recognized,
            "unrecognized": [
                {
                    "source_path": source_dir,
                    "reason": "source directory missing",
                }
            ],
            "summary": {
                "scanned_resource_files": 0,
                "recognized_count": 0,
                "unrecognized_count": 1,
                "conflict_count": 0,
                "importable_count": 0,
                "ok": False,
            },
        }

    for walk_root, _dirs, files in os.walk(source_dir):
        for filename in files:
            if _normalize_extension(filename) not in allowed_exts:
                continue

            scanned_resource_files += 1
            source_path = os.path.join(walk_root, filename)
            extracted = _extract_target_rel_path(source_dir, source_path, domain)
            if not extracted:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "path does not include a supported resource category root",
                    }
                )
                continue

            spec = next((item for item in selected_specs if item.key == extracted["spec_key"]), None)
            if spec is None:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "resource category not supported in current mode",
                    }
                )
                continue

            if _normalize_extension(filename) not in {ext.lower() for ext in spec.extensions}:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": f"unsupported file extension for {spec.label}",
                    }
                )
                continue

            target_rel_path = str(extracted["target_rel_path"])
            target_abs_path = os.path.abspath(os.path.join(resources_root, target_rel_path))
            is_within_root = os.path.commonpath([resources_root, target_abs_path]) == resources_root
            if not is_within_root:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "resolved target escapes resources root",
                    }
                )
                continue

            conflict = os.path.exists(target_abs_path)
            recognized.append(
                {
                    "source_path": source_path,
                    "target_rel_path": target_rel_path,
                    "target_abs_path": target_abs_path,
                    "spec_key": spec.key,
                    "spec_label": spec.label,
                    "domain": spec.domain,
                    "conflict": conflict,
                }
            )

    recognized.sort(key=lambda item: str(item.get("target_rel_path", "")).lower())
    unrecognized.sort(key=lambda item: str(item.get("source_path", "")).lower())

    conflict_count = sum(1 for item in recognized if bool(item.get("conflict")))
    importable_count = max(0, len(recognized) - conflict_count)
    category_counts: Dict[str, int] = {}
    for item in recognized:
        key = str(item.get("spec_key", ""))
        category_counts[key] = category_counts.get(key, 0) + 1

    return {
        "source_dir": source_dir,
        "resources_root": resources_root,
        "domain": domain,
        "recognized": recognized,
        "unrecognized": unrecognized,
        "summary": {
            "scanned_resource_files": scanned_resource_files,
            "recognized_count": len(recognized),
            "unrecognized_count": len(unrecognized),
            "conflict_count": conflict_count,
            "importable_count": importable_count,
            "ok": len(recognized) > 0,
            "category_counts": category_counts,
        },
    }


def apply_resource_import_plan(
    scan_report: Dict[str, object],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = False,
) -> Dict[str, object]:
    recognized = list(scan_report.get("recognized", []) or [])
    copied: List[Dict[str, str]] = []
    skipped_conflicts: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []

    for item in recognized:
        source_path = str(item.get("source_path", ""))
        target_abs_path = str(item.get("target_abs_path", ""))
        target_rel_path = str(item.get("target_rel_path", ""))
        if not source_path or not target_abs_path:
            failed.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "reason": "invalid plan item",
                }
            )
            continue

        exists = os.path.exists(target_abs_path)
        if exists and not overwrite_existing:
            skipped_conflicts.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                }
            )
            continue

        if dry_run:
            copied.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                }
            )
            continue

        try:
            os.makedirs(os.path.dirname(target_abs_path), exist_ok=True)
            shutil.copy2(source_path, target_abs_path)
            copied.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                    "reason": str(exc),
                }
            )

    return {
        "dry_run": bool(dry_run),
        "overwrite_existing": bool(overwrite_existing),
        "copied": copied,
        "skipped_conflicts": skipped_conflicts,
        "failed": failed,
        "summary": {
            "copied_count": len(copied),
            "skipped_conflicts_count": len(skipped_conflicts),
            "failed_count": len(failed),
            "ok": len(failed) == 0,
        },
    }
