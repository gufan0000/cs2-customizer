# SPDX-License-Identifier: GPL-3.0-or-later
"""Config snapshot manager for safe rollback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List

from config import config, get_config_dir, get_config_path


SNAPSHOT_DIR = "config_snapshots"
INDEX_FILE = "index.json"

# QA-012: 淘汰时**优先**丢掉的 reason 前缀 —— 只有"后台自动、随时能再生"的才列进来。
# 语义是白名单反着用：**没列出的 reason 一律当用户资产保护**，
# 这样将来新增 reason 时默认是安全的一侧。
#
# 为什么需要它：`prune_snapshots` 原本只按时间倒序留最新 N 条，对 reason 一视同仁。
# 而「按地图自动切预设」每换一张图就无条件建一份快照（`preset_center.apply_bundle`），
# 实测：3 张图规则 + 一晚 4 局的用户，**第 5 个晚上**就把
# 手建快照和「恢复前自动建的后悔药」双双挤掉；而挤掉它们的那 20 份自动快照
# 内容 distinct sha256 只有 3 —— 拿三份重复副本换掉了用户仅有的两个还原点。
_EVICT_FIRST_PREFIXES = ("preset_apply_",)


def _is_evict_first(item) -> bool:
    return str(item.get("reason", "")).startswith(_EVICT_FIRST_PREFIXES)


@dataclass
class SnapshotMeta:
    snapshot_id: str
    reason: str
    created_at: str
    file_path: str
    size: int
    sha256: str

    def to_dict(self):
        return asdict(self)


@dataclass
class RestoreResult:
    snapshot_id: str
    ok: bool
    restored_to: str
    error: str = ""
    # 恢复前自动建的"后悔药"快照 id。空串代表没建成（当时没有 config.json，
    # 或建快照本身失败）——调用方据此决定要不要提示用户"此次恢复不可撤销"。
    backup_id: str = ""

    def to_dict(self):
        return asdict(self)


def _snapshot_root() -> str:
    root = os.path.join(get_config_dir(), SNAPSHOT_DIR)
    os.makedirs(root, exist_ok=True)
    return root


def _index_path() -> str:
    return os.path.join(_snapshot_root(), INDEX_FILE)


def _load_index() -> List[dict]:
    path = _index_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
            if isinstance(value, list):
                return value
    except Exception:
        pass
    return []


def _save_index(entries: List[dict]) -> None:
    # 原子写：直接覆盖写在中途崩溃/断电时会截断 index.json，
    # 所有快照虽在盘上却因索引损坏而"消失"（一键回滚能力丢失）
    path = _index_path()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def create_snapshot(reason: str) -> SnapshotMeta:
    cfg_path = get_config_path()
    if not os.path.isfile(cfg_path):
        if hasattr(config, "save_config_now"):
            config.save_config_now()
        else:
            config.save_config()

    if not os.path.isfile(cfg_path):
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    ts = datetime.now()
    snapshot_id = ts.strftime("%Y%m%d_%H%M%S_%f")
    dst_path = os.path.join(_snapshot_root(), f"{snapshot_id}.json")
    shutil.copy2(cfg_path, dst_path)

    meta = SnapshotMeta(
        snapshot_id=snapshot_id,
        reason=str(reason or "manual"),
        created_at=ts.isoformat(timespec="seconds"),
        file_path=dst_path,
        size=os.path.getsize(dst_path),
        sha256=_sha256_file(dst_path),
    )

    entries = _load_index()
    entries.append(meta.to_dict())
    # 次级键用 snapshot_id：created_at 只精确到秒，同秒建的两份快照排序不确定，
    # 而 snapshot_id 带微秒。prune 靠这个顺序决定删谁，排错了会删掉刚建的"后悔药"。
    entries.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("snapshot_id", ""))))
    _save_index(entries)
    return meta


def list_snapshots() -> List[SnapshotMeta]:
    result: List[SnapshotMeta] = []
    for item in _load_index():
        try:
            result.append(
                SnapshotMeta(
                    snapshot_id=str(item.get("snapshot_id", "")),
                    reason=str(item.get("reason", "")),
                    created_at=str(item.get("created_at", "")),
                    file_path=str(item.get("file_path", "")),
                    size=int(item.get("size", 0) or 0),
                    sha256=str(item.get("sha256", "")),
                )
            )
        except Exception:
            continue
    result.sort(key=lambda meta: (meta.created_at, meta.snapshot_id), reverse=True)
    return result


def restore_snapshot(snapshot_id: str) -> RestoreResult:
    snaps = {item.snapshot_id: item for item in list_snapshots()}
    if snapshot_id not in snaps:
        return RestoreResult(snapshot_id=snapshot_id, ok=False, restored_to=get_config_path(), error="snapshot not found")
    snap = snaps[snapshot_id]
    if not os.path.isfile(snap.file_path):
        return RestoreResult(snapshot_id=snapshot_id, ok=False, restored_to=get_config_path(), error="snapshot file missing")

    cfg_path = get_config_path()

    # 覆盖用户配置之前,先确认这份快照**本身是好的**。
    # 原实现只检查了文件存在,于是一份被截断的快照(同步冲突/断电/手改)会被
    # 原样写进 config.json,而函数照样返回 ok=True、页面照样报"恢复成功"——
    # 用好配置换来一份坏配置,还告诉用户成功了。SnapshotMeta 里存了 sha256,
    # 从建库起就没被校验过,现在用起来。
    if snap.sha256:
        try:
            if _sha256_file(snap.file_path) != snap.sha256:
                return RestoreResult(
                    snapshot_id=snapshot_id, ok=False, restored_to=cfg_path,
                    error="snapshot checksum mismatch (文件已损坏或被改动)",
                )
        except Exception as exc:
            return RestoreResult(
                snapshot_id=snapshot_id, ok=False, restored_to=cfg_path,
                error=f"snapshot unreadable: {exc}",
            )
    try:
        with open(snap.file_path, "r", encoding="utf-8") as handle:
            json.load(handle)
    except Exception as exc:
        return RestoreResult(
            snapshot_id=snapshot_id, ok=False, restored_to=cfg_path,
            error=f"snapshot is not valid JSON: {exc}",
        )

    # UP-075: 恢复前先给"当前状态"建一张快照。
    # 此前 restore 直接覆盖 config.json——用户点错一条快照,现有配置就没了,
    # 而这个功能存在的全部意义恰恰是"可回退"。这里让恢复动作自身也可回退。
    # 建不成不阻断恢复(用户明确要求了),但把 backup_id 留空让调用方能如实告知。
    backup_id = ""
    if os.path.isfile(cfg_path):
        try:
            backup_id = create_snapshot(f"before_restore_{snapshot_id}").snapshot_id
        except Exception:
            backup_id = ""

    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        # 原子替换:直接 copy2 到 cfg_path 若中途崩溃/断电会留下截断的 config.json,
        # 那是比"恢复失败"更坏的结局——旧配置没了,新配置也不完整。
        tmp_path = f"{cfg_path}.restore.tmp"
        try:
            shutil.copy2(snap.file_path, tmp_path)
            os.replace(tmp_path, cfg_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    except Exception as exc:
        # 只有"文件替换"这一步失败才算恢复失败——磁盘上的配置没被动过
        return RestoreResult(
            snapshot_id=snapshot_id, ok=False, restored_to=cfg_path, error=str(exc), backup_id=backup_id
        )

    # 到这里 config.json 已经确实换成快照内容了 —— 从此不能再返回 ok=False。
    # 原实现把 load_config() 也包在上面那个 try 里:它一抛异常(比如快照里某个
    # 字段类型变了导致 int() 失败),函数就报"恢复失败",可磁盘上的配置**已经换了**。
    # 用户看到失败提示 → 页面不刷新、后悔药 id 也不告知 → 下一步操作把旧值写回去,
    # 那才是真正丢数据的路径。现在把重载/广播的失败降级为 warning。
    warning = ""
    if hasattr(config, "load_config"):
        try:
            config.load_config()
        except Exception as exc:
            warning = f"配置已替换，但内存重载失败（建议重启软件）: {exc}"
    # UP-035: 内存里的 config 换掉了,但已打开页面上的控件还停在旧值。
    # 不广播的话"恢复快照"在这些页面上等于失效——用户动一下就把旧值写回去。
    try:
        from core.config_reload_bus import notify

        notify("snapshot_restore")
    except Exception:
        pass
    return RestoreResult(
        snapshot_id=snapshot_id, ok=True, restored_to=cfg_path,
        error=warning, backup_id=backup_id,
    )


def prune_snapshots(max_keep: int) -> int:
    keep = max(1, int(max_keep))
    entries = sorted(
        _load_index(),
        key=lambda item: (str(item.get("created_at", "")), str(item.get("snapshot_id", ""))),
        reverse=True,
    )
    removed = 0
    # QA-012: 名额分池发放，而不是一刀切 entries[:keep]。
    #   ① 最新一份无条件保住 —— create_snapshot 刚建的后悔药绝不能被同一次 prune 删掉；
    #   ② 剩下的名额先给"用户资产"（手建 / before_reset_all / before_restore_* / 未知 reason），
    #      再给后台自动生成的；两个池内部都仍按时间倒序。
    # 总量**仍然严格 ≤ keep** —— 不能改成"保护项不计数"，否则快照目录会无限长。
    newest = entries[:1]
    rest = entries[1:]
    protected = [item for item in rest if not _is_evict_first(item)]
    evict_first = [item for item in rest if _is_evict_first(item)]
    budget = max(0, keep - len(newest))
    chosen = protected[:budget]
    chosen += evict_first[: max(0, budget - len(chosen))]
    keep_ids = {id(item) for item in newest} | {id(item) for item in chosen}
    keep_entries = [item for item in entries if id(item) in keep_ids]
    for item in entries:
        if id(item) in keep_ids:
            continue
        path = str(item.get("file_path", ""))
        if path and os.path.isfile(path):
            try:
                os.remove(path)
                removed += 1
            except Exception:
                continue
    _save_index(list(reversed(keep_entries)))
    return removed

