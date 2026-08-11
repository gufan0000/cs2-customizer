import hashlib
import json
import os
import shutil
from datetime import datetime

from config import get_config_dir


EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    "release",
    "logs",
}


def _sha256_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _collect_source_files(project_root):
    files = []
    for root, dirs, names in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in names:
            if not name.lower().endswith(".py"):
                continue
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, project_root)
            files.append(rel_path.replace("\\", "/"))
    files.sort()
    return files


def _load_json(path, default_value):
    if not os.path.exists(path):
        return default_value
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_value


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _build_snapshot_fingerprint(project_root, rel_files):
    file_entries = []
    combined = hashlib.sha256()
    for rel_path in rel_files:
        abs_path = os.path.join(project_root, rel_path)
        if not os.path.isfile(abs_path):
            continue
        file_hash = _sha256_file(abs_path)
        combined.update(rel_path.encode("utf-8", errors="ignore"))
        combined.update(file_hash.encode("ascii"))
        file_entries.append({"path": rel_path, "hash": file_hash})
    return combined.hexdigest(), file_entries


def run_startup_source_backup(logger=None, project_root=None, max_snapshots=30):
    project_root = project_root or os.path.dirname(os.path.abspath(__file__))
    backup_root = os.path.join(get_config_dir(), "source_backups")
    state_path = os.path.join(backup_root, "state.json")

    try:
        rel_files = _collect_source_files(project_root)
        if not rel_files:
            return None

        snapshot_hash, file_entries = _build_snapshot_fingerprint(project_root, rel_files)
        if not file_entries:
            return None

        state = _load_json(state_path, {"snapshots": [], "last_snapshot_hash": ""})
        if state.get("last_snapshot_hash") == snapshot_hash:
            return None

        snapshot_name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        snapshot_dir = os.path.join(backup_root, snapshot_name)
        os.makedirs(snapshot_dir, exist_ok=True)

        for entry in file_entries:
            rel_path = entry["path"]
            src = os.path.join(project_root, rel_path)
            dst = os.path.join(snapshot_dir, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        manifest = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "project_root": project_root,
            "file_count": len(file_entries),
            "snapshot_hash": snapshot_hash,
            "files": file_entries,
        }
        _save_json(os.path.join(snapshot_dir, "manifest.json"), manifest)

        snapshots = []
        for name in state.get("snapshots", []):
            full = os.path.join(backup_root, name)
            if os.path.isdir(full):
                snapshots.append(name)
        snapshots.append(snapshot_name)

        while len(snapshots) > max(1, int(max_snapshots)):
            old_name = snapshots.pop(0)
            old_dir = os.path.join(backup_root, old_name)
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir, ignore_errors=True)

        state["snapshots"] = snapshots
        state["last_snapshot_hash"] = snapshot_hash
        state["last_backup_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_snapshot"] = snapshot_name
        _save_json(state_path, state)

        if logger:
            logger.info(
                f"[SourceBackup] Auto snapshot created: {snapshot_name} ({len(file_entries)} files)"
            )
        return snapshot_dir
    except Exception as e:
        if logger:
            logger.warning(f"[SourceBackup] Auto snapshot failed: {e}")
        return None
