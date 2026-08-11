"""Audio import wizard helpers (scan + conservative copy)."""

from __future__ import annotations

import os

from core.io_validation import audio_import_rejection_reason
import shutil
from typing import Dict, List, Optional, Sequence

from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS, is_audio_filename


SUPPORTED_AUDIO_ROOTS = (
    "kill_sounds",
    "kill_voices",
    "weapon_kill_sounds",
    "weapon_kill_voices",
    "death",
    "switch_weapons",
    "reload_sounds",
    "grenade_sounds",
    "c4_sounds",
    "health_warning",
    "round_sounds",
    "gun_sounds",
)


ROOT_ALIASES = {
    "kill_sound": "kill_sounds",
    "kill_voice": "kill_voices",
    "weapon_kill_sound": "weapon_kill_sounds",
    "weapon_kill_voice": "weapon_kill_voices",
    "switch_weapon": "switch_weapons",
    "switch_sounds": "switch_weapons",
    "reload_sound": "reload_sounds",
    "grenade_sound": "grenade_sounds",
    "c4_sound": "c4_sounds",
    "round_sound": "round_sounds",
    "gun_sound": "gun_sounds",
}


def _canonical_root_name(raw_name: str) -> Optional[str]:
    key = str(raw_name or "").strip().lower()
    if not key:
        return None
    if key in SUPPORTED_AUDIO_ROOTS:
        return key
    return ROOT_ALIASES.get(key)


def _extract_target_rel_path(source_dir: str, source_file: str) -> Optional[Dict[str, str]]:
    rel_path = os.path.relpath(source_file, source_dir)
    parts = list(os.path.normpath(rel_path).split(os.sep))
    for idx, part in enumerate(parts):
        canonical = _canonical_root_name(part)
        if not canonical:
            continue
        tail = parts[idx + 1 :]
        if not tail:
            return None
        return {
            "root": canonical,
            "target_rel_path": os.path.join(canonical, *tail),
        }
    return None


def scan_audio_import_candidates(
    source_dir: str,
    audio_root: str,
    extensions: Sequence[str] = DEFAULT_AUDIO_EXTENSIONS,
) -> Dict[str, object]:
    """Scan source folder and classify importable audio files."""
    recognized: List[Dict[str, object]] = []
    unrecognized: List[Dict[str, str]] = []
    scanned_audio_files = 0

    source_dir = os.path.abspath(str(source_dir or ""))
    audio_root = os.path.abspath(str(audio_root or ""))

    if not source_dir or not os.path.isdir(source_dir):
        return {
            "source_dir": source_dir,
            "audio_root": audio_root,
            "recognized": recognized,
            "unrecognized": [
                {
                    "source_path": source_dir,
                    "reason": "source directory missing",
                }
            ],
            "summary": {
                "scanned_audio_files": 0,
                "recognized_count": 0,
                "unrecognized_count": 1,
                "conflict_count": 0,
                "importable_count": 0,
                "ok": False,
            },
        }

    for walk_root, _dirs, files in os.walk(source_dir):
        for filename in files:
            if not is_audio_filename(filename, extensions=extensions):
                continue

            scanned_audio_files += 1
            source_path = os.path.join(walk_root, filename)
            _reject = audio_import_rejection_reason(source_path)
            if _reject:
                unrecognized.append({"source_path": source_path, "reason": _reject})
                continue
            extracted = _extract_target_rel_path(source_dir, source_path)
            if not extracted:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "path does not include a supported audio category root",
                    }
                )
                continue

            target_rel_path = extracted["target_rel_path"]
            target_abs_path = os.path.abspath(os.path.join(audio_root, target_rel_path))
            is_within_root = os.path.commonpath([audio_root, target_abs_path]) == audio_root
            if not is_within_root:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "resolved target escapes audio root",
                    }
                )
                continue

            conflict = os.path.exists(target_abs_path)
            recognized.append(
                {
                    "source_path": source_path,
                    "target_rel_path": target_rel_path,
                    "target_abs_path": target_abs_path,
                    "category_root": extracted["root"],
                    "conflict": conflict,
                }
            )

    recognized.sort(key=lambda item: str(item.get("target_rel_path", "")).lower())
    unrecognized.sort(key=lambda item: str(item.get("source_path", "")).lower())

    conflict_count = sum(1 for item in recognized if bool(item.get("conflict")))
    importable_count = max(0, len(recognized) - conflict_count)
    return {
        "source_dir": source_dir,
        "audio_root": audio_root,
        "recognized": recognized,
        "unrecognized": unrecognized,
        "summary": {
            "scanned_audio_files": scanned_audio_files,
            "recognized_count": len(recognized),
            "unrecognized_count": len(unrecognized),
            "conflict_count": conflict_count,
            "importable_count": importable_count,
            "ok": len(recognized) > 0,
        },
    }


def apply_audio_import_plan(
    scan_report: Dict[str, object],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = False,
) -> Dict[str, object]:
    """Apply import plan by copying recognized files into the app audio root."""
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
                }
            )
            continue

        if dry_run:
            copied.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
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
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
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
