# -*- coding: utf-8 -*-
"""QA-013：应用预设前的"自动快照"失败，不能既不记日志也不告诉用户。

原实现是 `except Exception: pass`，而且整个 `preset_center.py` 连 logger 都没 import。
后果：快照没建成 → `apply_bundle` 照样返回 ok=True → UI 照样弹
「已应用「XXX」，可在配置快照页回滚」。用户信了这句话去回滚，才发现根本没有还原点。

三段判据，缺一不可：
1. **健康对照** —— 正常时快照真的建了、且**不许**报警（防"永远报警"式蒙混）；
2. **create 失败** —— 还原点确实不存在、warnings 有话、日志有 WARNING（这段负责翻红）；
3. **只有 prune 失败** —— 还原点是在的，**不许**报「无法回滚」（防假警报）。
"""
from __future__ import annotations

import json
import logging

import pytest

from core import config_snapshot_manager as snap_mod
from core.presets import preset_center


class _CfgObj:
    def __init__(self):
        self.config_snapshot_auto_before_risky_ops = True
        self.config_snapshot_max_keep = 20

    def save_config_now(self):
        return None

    def load_config(self):
        return None


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({"a": 0}), encoding="utf-8")
    cfg_obj = _CfgObj()
    monkeypatch.setattr(snap_mod, "config", cfg_obj)
    monkeypatch.setattr(snap_mod, "get_config_dir", lambda: str(cfg_dir))
    monkeypatch.setattr(snap_mod, "get_config_path", lambda: str(cfg_file))
    monkeypatch.setattr(preset_center, "config", cfg_obj)
    return cfg_dir


def _bundle():
    return {
        "schema": preset_center.SCHEMA_NAME,
        "schema_version": preset_center.SCHEMA_VERSION,
        "items": [{"type": next(iter(preset_center.SUPPORTED_TYPES)), "payload": {}}],
    }


def test_healthy_apply_creates_snapshot_and_warns_about_nothing(env):
    before = len(snap_mod.list_snapshots())
    result = preset_center.apply_bundle(_bundle(), mode="merge")
    assert result.ok
    assert len(snap_mod.list_snapshots()) == before + 1, "正常路径下快照没建成"
    assert result.warnings == [], f"正常路径下不该报警：{result.warnings}"


def test_snapshot_failure_is_reported_not_swallowed(env, monkeypatch, caplog):
    """create_snapshot 失败：还原点不存在 + warnings 有话 + 日志有 WARNING。"""
    def _boom(*_a, **_kw):
        raise OSError("快照目录不可写")

    monkeypatch.setattr(snap_mod, "create_snapshot", _boom)

    before = len(snap_mod.list_snapshots())
    with caplog.at_level(logging.WARNING):
        result = preset_center.apply_bundle(_bundle(), mode="merge")

    # a. 先证明还原点确实不存在 —— 判据自己不许靠猜
    assert len(snap_mod.list_snapshots()) == before, "快照居然建成了，判据前提不成立"
    # b. 调用方拿得到警告
    assert result.warnings, "快照建失败却一句话都没往上传（QA-013）"
    joined = "；".join(result.warnings)
    assert ("快照" in joined) or ("回滚" in joined), f"警告文案没说清问题：{joined}"
    # c. 日志里留了痕
    assert any(rec.levelno >= logging.WARNING for rec in caplog.records), \
        "快照建失败连一条 WARNING 都没记"


def test_prune_failure_alone_must_not_cry_wolf(env, monkeypatch):
    """只有 prune 失败时，还原点是**在**的，不许报「无法回滚」。

    把 create 和 prune 合在一个 try 里图省事就会踩这条：用户被假警报骗过一次，
    以后真出事的提示他也不信了，比不提示更糟。
    """
    def _boom(*_a, **_kw):
        raise OSError("索引写不动")

    monkeypatch.setattr(snap_mod, "prune_snapshots", _boom)

    before = len(snap_mod.list_snapshots())
    result = preset_center.apply_bundle(_bundle(), mode="merge")

    assert len(snap_mod.list_snapshots()) == before + 1, "还原点应该是建成了的"
    assert result.warnings == [], f"prune 失败不该报「无法回滚」：{result.warnings}"
