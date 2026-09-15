# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import os
import shutil
from datetime import datetime

from config import get_config_dir


#: RN-630（批 91）：一条**规则**（点/下划线开头 = 工装、产物或别人的工作区）
#: 加两张小表。分根层 / 全深度两格，是因为 `os.walk` 的剪枝按名字在**任意深度**
#: 匹配 —— 老表里那个 `release` 本意指顶层产物目录，却把 `scripts/release/`
#: 的真源码一起剪掉了。叙事、实测数字与双向断言见
#: `tests/test_the_source_backup_backs_up_the_source.py`。
EXCLUDED_AT_ROOT = {
    "release",
    "logs",
    "output",
    "artifacts",
    "dist",
    "build",
    "tmp",
    "temp",
}
EXCLUDED_ANYWHERE = {
    "node_modules",
    "site-packages",
    "venv",
}

#: 天花板：收到这个数以上就不是我的源码树了，宁可不写。防的是「规则又漏一格」。
MAX_SOURCE_FILES = 2000


def _is_excluded_dir(name, at_root=False):
    """`at_root` = 这个目录是否直接挂在项目根下（产物目录只在根那一层算数）。"""
    if name.startswith(".") or name.startswith("_"):
        return True
    if name in EXCLUDED_ANYWHERE:
        return True
    return at_root and name in EXCLUDED_AT_ROOT


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
    root_abs = os.path.abspath(project_root)
    for root, dirs, names in os.walk(project_root):
        at_root = os.path.abspath(root) == root_abs
        dirs[:] = [d for d in dirs if not _is_excluded_dir(d, at_root=at_root)]
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


#: RN-635（批 91）：工装/测试用的关闭开关。置任意非空值 ⇒ 直接早退。
#: 此前三个工装各自抄了一份「把它换成空函数」（`build_search_index` /
#: `probe_search_popup_render` / `build_cs2customizer_local_manual`），而**最大的消费者
#: —— 295 个判据文件、每个用例建一次主窗口 —— 一份都没有**，
#: 代价是 `%TEMP%` 里 130 GB。理由与实测见
#: `tests/test_the_source_backup_backs_up_the_source.py`。
SKIP_ENV = "CS2C_SKIP_SOURCE_BACKUP"


def run_startup_source_backup(logger=None, project_root=None, max_snapshots=30):
    if os.environ.get(SKIP_ENV):
        return None
    project_root = project_root or os.path.dirname(os.path.abspath(__file__))
    backup_root = os.path.join(get_config_dir(), "source_backups")
    state_path = os.path.join(backup_root, "state.json")

    try:
        rel_files = _collect_source_files(project_root)
        if not rel_files:
            return None

        # RN-630：收多了就别抄，而且要**出声** —— 以前它安静地抄了 6 GB。
        if len(rel_files) > MAX_SOURCE_FILES:
            top = {}
            for rel in rel_files:
                head = rel.split("/")[0] if "/" in rel else "(根目录)"
                top[head] = top.get(head, 0) + 1
            worst = sorted(top.items(), key=lambda kv: -kv[1])[:5]
            if logger:
                logger.warning(
                    f"[源码备份] 收到 {len(rel_files)} 个 .py，超过上限 "
                    f"{MAX_SOURCE_FILES} ⇒ 本次跳过。这通常意味着排除规则漏了一个目录。"
                    f"占比最大的：{'、'.join(f'{k} {v} 个' for k, v in worst)}"
                )
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

        # RN-631（批 91）：名单从**盘上**取，不从 `state.json` 取。
        # 老写法只认 state 里记着的名字 ⇒ 任何没进 state 的快照目录永远清不掉
        # （实测：上限 30，盘上躺着 43 份 / 6.11 GB）。目录名是可排序的时间戳。
        snapshots = sorted(
            name for name in os.listdir(backup_root)
            if name.startswith("snapshot_")
            and os.path.isdir(os.path.join(backup_root, name))
        )

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
