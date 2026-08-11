# -*- coding: utf-8 -*-
"""QA-012：后台自动快照不许把用户手建的快照和"恢复后悔药"挤掉。

链路：开了「按地图自动切预设」的用户，每换一张图就走
`core/presets/map_rules.py` → `preset_center.apply_bundle` →
无条件 `create_snapshot("preset_apply_*") + prune_snapshots(20)`；
而 `prune_snapshots` 原本只按时间倒序留最新 20 条、**对 reason 一视同仁**。

实测过的现实节奏：3 张图规则 + 一晚 4 局，**第 5 个晚上**（第 20 次 apply）
用户仅有的两个还原点就双双被删；而挤掉它们的 20 份自动快照
distinct sha256 只有 3 —— 拿三份重复副本换掉了唯一的后悔药。
更糟的是 `config_snapshot_max_keep` **没有任何 UI 写入口**，用户想调大都没地方调。

判据是纯行为的：真建真删真读盘，不看源码字符串。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import config_snapshot_manager as snap_mod


class _CfgObj:
    def __init__(self):
        self.config_snapshot_auto_before_risky_ops = True
        self.config_snapshot_max_keep = 20

    def save_config_now(self):
        return None

    def load_config(self):
        return None


@pytest.fixture
def snap_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({"a": 0}), encoding="utf-8")
    monkeypatch.setattr(snap_mod, "config", _CfgObj())
    monkeypatch.setattr(snap_mod, "get_config_dir", lambda: str(cfg_dir))
    monkeypatch.setattr(snap_mod, "get_config_path", lambda: str(cfg_file))
    return cfg_dir, cfg_file


def test_auto_preset_flood_never_evicts_user_snapshots(snap_env):
    """25 次自动快照洪水之后，用户的两个还原点必须都还在。"""
    cfg_dir, cfg_file = snap_env

    manual = snap_mod.create_snapshot("manual_page").snapshot_id
    restore_point = snap_mod.create_snapshot(
        "before_restore_20260101_000000_000000").snapshot_id

    newest = ""
    for i in range(25):
        # 每轮内容都不同：不许靠"内容相同就不新建"之类的去重蒙混过关
        cfg_file.write_text(json.dumps({"a": i + 1}), encoding="utf-8")
        newest = snap_mod.create_snapshot("preset_apply_merge").snapshot_id
        snap_mod.prune_snapshots(20)

    items = snap_mod.list_snapshots()
    ids = {it.snapshot_id for it in items}
    by_id = {it.snapshot_id: it for it in items}

    # a. 两个用户还原点：索引和磁盘都要在（只留索引不留文件是历史上的假绿套路）
    assert manual in ids, "用户手建的快照被自动快照挤掉了"
    assert restore_point in ids, "「恢复前自动建的后悔药」被自动快照挤掉了"
    for sid in (manual, restore_point):
        assert Path(by_id[sid].file_path).is_file(), f"{sid} 索引还在但文件没了"

    # b. 最新一份永不被同一次 prune 删掉
    assert newest in ids, "刚建的快照被同一次 prune 删了"

    # c. 上限没有被放弃
    assert len(items) <= 20, f"总量突破上限，快照目录会无限长：{len(items)}"

    # d. 自动池确实被裁了 —— 保住用户资产不是靠"干脆不删"换来的
    autos = [it for it in items if it.reason.startswith("preset_apply_")]
    assert len(autos) == 18, f"自动快照份数不对（应为 20-2）：{len(autos)}"

    # e. 磁盘上没有孤儿文件
    on_disk = sorted((cfg_dir / snap_mod.SNAPSHOT_DIR).glob("*.json"))
    on_disk = [p for p in on_disk if p.name != snap_mod.INDEX_FILE]
    assert len(on_disk) == len(items), (
        f"磁盘 {len(on_disk)} 个文件 vs 索引 {len(items)} 条，有孤儿")


def test_preset_apply_emits_the_reason_prefix_the_pruner_protects_against(snap_env, monkeypatch):
    """真跑一次 apply_bundle，确认它写进索引的 reason 确实带保护逻辑认得的前缀。

    专治"文案一改前缀匹配静默失效、判据照样绿"这种假绿：
    reason 是 f-string 拼出来的，只在 prune 层面自造 reason 测是不够的。
    """
    from core.presets import preset_center

    cfg_dir, cfg_file = snap_env
    monkeypatch.setattr(preset_center, "config", snap_mod.config, raising=False)

    # 直接引用模块常量而不是抄字面量：schema 名字改了这条判据要跟着走，
    # 而不是悄悄变成"bundle 非法 → 提前 return → 一份快照都没建 → 判据自己失效"。
    bundle = {
        "schema": preset_center.SCHEMA_NAME,
        "schema_version": preset_center.SCHEMA_VERSION,
        "items": [{"type": next(iter(preset_center.SUPPORTED_TYPES)), "payload": {}}],
    }
    result = preset_center.apply_bundle(bundle, mode="merge")
    assert result.ok, f"apply_bundle 没跑通，判据前提不成立：{result.errors}"

    items = snap_mod.list_snapshots()
    assert items, "apply_bundle 一份快照都没建，判据前提不成立"
    newest = max(items, key=lambda it: (it.created_at, it.snapshot_id))
    assert snap_mod._is_evict_first({"reason": newest.reason}), (
        f"apply_bundle 写的 reason 是 {newest.reason!r}，"
        f"不在 prune 的优先淘汰前缀 {snap_mod._EVICT_FIRST_PREFIXES} 里 —— "
        "保护逻辑已经静默失效")
