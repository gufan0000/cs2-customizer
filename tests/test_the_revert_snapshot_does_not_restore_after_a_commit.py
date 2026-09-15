# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-637（批 93）：回退验证的「善后还原」不许把一份过期快照当成新鲜的。

## 它守的是什么

RN-093 给回退验证加了「改坏原文落盘，下次启动自动还原」。它只问一个问题：
**现在的文件和快照里的一不一样** —— 而这个问题在几小时后必然答「不一样」。
批 93 实测：09:55 一次回退验证被 App 重启砍断，快照留在盘上；之后提交了两批、
改了十几个文件；23 点跑一次 `--stale-only`，启动时把 **130 个文件静默写回 09:55**，
已提交的判据、没提交的修法一起没了，报告里只有一行「已自动还原」。
⭐⭐⭐ **一条为了防事故写的善后，自己成了事故；它和一次成功的善后在日志上长得一模一样。**

## 怎么验

在临时目录里造一份快照 + 一个「被改过」的文件，把 `ROOT / SNAPSHOT_DIR / MANIFEST /
_git_head` 全部换成临时的：HEAD 不同 ⇒ 必须拒绝且文件一个字节不动；HEAD 相同且新鲜
⇒ 照旧还原。⛔ 不碰真仓库的快照目录。
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RV = REPO / "scripts" / "revert_verify.py"


def _load_rv():
    spec = importlib.util.spec_from_file_location("revert_verify_under_test", RV)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stage(tmp_path, monkeypatch, *, head_then: str, head_now: str, age_seconds: float):
    rv = _load_rv()
    root = tmp_path / "repo"
    snap = root / ".revert_verify_snapshot"
    snap.mkdir(parents=True)
    target = root / "product.py"
    target.write_text("x = 2  # 后来改的\n", encoding="utf-8")
    (snap / "000.bak").write_text("x = 1  # 快照里的原文\n", encoding="utf-8")
    (snap / "manifest.json").write_text(json.dumps({
        "head": head_then, "saved_at": time.time() - age_seconds,
        "files": {"product.py": "000.bak"}}), encoding="utf-8")
    monkeypatch.setattr(rv, "ROOT", root)
    monkeypatch.setattr(rv, "SNAPSHOT_DIR", snap)
    monkeypatch.setattr(rv, "MANIFEST", snap / "manifest.json")
    monkeypatch.setattr(rv, "_git_head", lambda: head_now)
    return rv, target, snap


def test_a_snapshot_from_another_head_is_refused_and_touches_nothing(tmp_path, monkeypatch):
    rv, target, snap = _stage(tmp_path, monkeypatch,
                              head_then="aaaa1111", head_now="bbbb2222", age_seconds=60)
    before = target.read_bytes()
    reason = rv.snapshot_is_stale()
    assert reason and "HEAD" in reason, f"HEAD 变了却没判成过期：{reason!r}"
    assert rv.restore_from_disk() == [], "过期快照还是被拿来还原了"
    assert target.read_bytes() == before, (
        "⛔ 中间提交过，树上的差异是人改的，而善后把它当成「改坏」写回去了 —— "
        "批 93 就这样丢了 130 个文件的改动")
    assert snap.exists(), "拒绝还原时快照要留着给人看，不许顺手删掉"


def test_an_old_snapshot_is_refused_even_on_the_same_head(tmp_path, monkeypatch):
    rv, target, _ = _stage(tmp_path, monkeypatch,
                           head_then="same", head_now="same",
                           age_seconds=3 * 3600)
    assert rv.SNAPSHOT_MAX_AGE_SECONDS <= 2 * 3600, "上限被放宽了 —— 三小时前的快照不该再被信任"
    before = target.read_bytes()
    assert rv.snapshot_is_stale(), "几小时前的快照没判成过期"
    assert rv.restore_from_disk() == [] and target.read_bytes() == before


def test_a_fresh_snapshot_on_the_same_head_still_restores(tmp_path, monkeypatch):
    """反向：别把 RN-093 的功能一起修没了 —— 刚被砍断的那种，照旧还原。"""
    rv, target, _ = _stage(tmp_path, monkeypatch,
                           head_then="same", head_now="same", age_seconds=30)
    assert rv.snapshot_is_stale() is None
    assert rv.restore_from_disk() == ["product.py"]
    assert target.read_text(encoding="utf-8") == "x = 1  # 快照里的原文\n"


def test_the_legacy_manifest_shape_is_treated_as_unknown(tmp_path, monkeypatch):
    """旧格式清单（平铺的 rel→bak，没记 HEAD）来路不明 ⇒ 同样不动手。"""
    rv, target, snap = _stage(tmp_path, monkeypatch,
                              head_then="same", head_now="same", age_seconds=30)
    (snap / "manifest.json").write_text(json.dumps({"product.py": "000.bak"}), encoding="utf-8")
    before = target.read_bytes()
    assert rv.snapshot_is_stale()
    assert rv.restore_from_disk() == [] and target.read_bytes() == before
