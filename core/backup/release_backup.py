"""Release-grade project backup with manifest and verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from typing import Dict, List

from config import get_config_dir

BACKUP_SUBDIR = "release_backups"
MANIFEST_NAME = "manifest.json"
PAYLOAD_DIRNAME = "payload"

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".build",
    "build",
    "dist",
    "output",
    "logs",
    "release",
    "tmp",
    "temp",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _sanitize_tag(tag: str) -> str:
    text = str(tag or "").strip()
    if not text:
        text = "release"
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:80] or "release"


def _backup_root() -> str:
    root = os.path.join(get_config_dir(), BACKUP_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def _iter_project_files(project_root: str):
    for current_root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for filename in files:
            if os.path.splitext(filename)[1].lower() in EXCLUDED_SUFFIXES:
                continue
            abs_path = os.path.join(current_root, filename)
            rel_path = os.path.relpath(abs_path, project_root).replace("\\", "/")
            if rel_path.startswith(".tmp_baseline_"):
                continue
            yield abs_path, rel_path


def _manifest_path(backup_dir: str) -> str:
    return os.path.join(backup_dir, MANIFEST_NAME)


def _payload_path(backup_dir: str) -> str:
    return os.path.join(backup_dir, PAYLOAD_DIRNAME)


def _read_manifest(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_manifest(path: str, payload: Dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _list_backup_dirs() -> List[str]:
    root = _backup_root()
    result: List[str] = []
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if os.path.isdir(full) and os.path.isfile(_manifest_path(full)):
            result.append(full)
    result.sort(key=os.path.getmtime, reverse=True)
    return result


def _prune_old_backups(max_keep: int) -> List[str]:
    removed: List[str] = []
    keep = max(1, int(max_keep))
    all_dirs = _list_backup_dirs()
    for directory in all_dirs[keep:]:
        try:
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(os.path.basename(directory))
        except Exception:
            continue
    return removed


def create_release_backup(tag: str, project_root: str, max_keep: int = 10) -> Dict[str, object]:
    """
    Create an immutable release backup snapshot for the given project tree.

    Returns metadata with backup_id/paths/file count/hash summary.
    """
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Project root not found: {root}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_id = f"{timestamp}_{_sanitize_tag(tag)}"
    backup_dir = os.path.join(_backup_root(), backup_id)
    payload_dir = _payload_path(backup_dir)
    os.makedirs(payload_dir, exist_ok=False)

    files_meta: List[Dict[str, object]] = []
    total_bytes = 0
    combined_digest = hashlib.sha256()

    for src_abs, rel_path in _iter_project_files(root):
        dst_abs = os.path.join(payload_dir, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
        shutil.copy2(src_abs, dst_abs)
        file_size = os.path.getsize(dst_abs)
        file_hash = _sha256_file(dst_abs)
        files_meta.append(
            {
                "path": rel_path,
                "size": file_size,
                "sha256": file_hash,
            }
        )
        total_bytes += int(file_size)
        combined_digest.update(rel_path.encode("utf-8", errors="ignore"))
        combined_digest.update(file_hash.encode("ascii"))

    manifest = {
        "backup_id": backup_id,
        "tag": _sanitize_tag(tag),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": root,
        "payload_dir": PAYLOAD_DIRNAME,
        "file_count": len(files_meta),
        "total_bytes": total_bytes,
        "snapshot_sha256": combined_digest.hexdigest(),
        "files": files_meta,
    }
    _write_manifest(_manifest_path(backup_dir), manifest)
    pruned = _prune_old_backups(max_keep=max_keep)

    return {
        "backup_id": backup_id,
        "backup_dir": backup_dir,
        "manifest_path": _manifest_path(backup_dir),
        "file_count": len(files_meta),
        "total_bytes": total_bytes,
        "snapshot_sha256": manifest["snapshot_sha256"],
        "pruned_backups": pruned,
    }


def list_release_backups() -> List[Dict[str, object]]:
    """List existing release backups (newest first)."""
    backups: List[Dict[str, object]] = []
    for directory in _list_backup_dirs():
        manifest_file = _manifest_path(directory)
        try:
            manifest = _read_manifest(manifest_file)
        except Exception:
            continue
        backups.append(
            {
                "backup_id": str(manifest.get("backup_id", os.path.basename(directory))),
                "tag": str(manifest.get("tag", "")),
                "created_at": str(manifest.get("created_at", "")),
                "file_count": int(manifest.get("file_count", 0) or 0),
                "total_bytes": int(manifest.get("total_bytes", 0) or 0),
                "snapshot_sha256": str(manifest.get("snapshot_sha256", "")),
                "backup_dir": directory,
                "manifest_path": manifest_file,
            }
        )
    return backups


def verify_backup(backup_id: str) -> Dict[str, object]:
    """Verify all files in a backup by hash against its manifest."""
    backup_root = _backup_root()
    backup_dir = os.path.join(backup_root, backup_id)
    manifest_file = _manifest_path(backup_dir)
    if not os.path.isfile(manifest_file):
        raise FileNotFoundError(f"Backup manifest not found: {manifest_file}")

    manifest = _read_manifest(manifest_file)
    payload_dir = os.path.join(backup_dir, str(manifest.get("payload_dir", PAYLOAD_DIRNAME)))
    files = manifest.get("files", []) or []

    missing_files: List[str] = []
    hash_mismatches: List[Dict[str, str]] = []
    checked_files = 0
    total_bytes = 0
    combined_digest = hashlib.sha256()

    for item in files:
        rel_path = str((item or {}).get("path", ""))
        expected_hash = str((item or {}).get("sha256", ""))
        if not rel_path:
            continue
        abs_path = os.path.join(payload_dir, rel_path.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            missing_files.append(rel_path)
            continue
        actual_hash = _sha256_file(abs_path)
        checked_files += 1
        total_bytes += os.path.getsize(abs_path)
        combined_digest.update(rel_path.encode("utf-8", errors="ignore"))
        combined_digest.update(actual_hash.encode("ascii"))
        if actual_hash != expected_hash:
            hash_mismatches.append(
                {
                    "path": rel_path,
                    "expected": expected_hash,
                    "actual": actual_hash,
                }
            )

    expected_snapshot_hash = str(manifest.get("snapshot_sha256", ""))
    actual_snapshot_hash = combined_digest.hexdigest()
    snapshot_hash_match = expected_snapshot_hash == actual_snapshot_hash

    ok = not missing_files and not hash_mismatches and snapshot_hash_match
    return {
        "backup_id": backup_id,
        "ok": ok,
        "checked_files": checked_files,
        "expected_files": len(files),
        "total_bytes": total_bytes,
        "missing_files": missing_files,
        "hash_mismatches": hash_mismatches,
        "snapshot_hash_match": snapshot_hash_match,
        "expected_snapshot_sha256": expected_snapshot_hash,
        "actual_snapshot_sha256": actual_snapshot_hash,
    }

