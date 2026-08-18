# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-093：回退验证被杀掉之后，**不许把改坏的产品文件留在工作区**。

**真事**（2026-08-18）：我用 `timeout 900 python scripts/revert_verify.py --only RN`
跑这台自检，900 秒到点时它正把 `gui_widget.py` 的
`_snap_nav_scroll_to_item_boundary(...)` 换成 `pass`（RN-060 的断点）。
SIGTERM **不会**走 Python 的 `finally`，于是那行改坏的代码原样留在树上。

后果一路滚下去：

1. 我随手跑 `tests/test_audit_can_see_every_page.py`，RN-060 那条判据当场红，
   报「20 处导航项被切一半」—— 我差一点当成真的回归去查；
2. 下一轮回退验证的**失效体检**把这条好端端的断点报成「锚点出现 0 次，已失效」——
   误诊套误诊；
3. 最坏的那条没发生但完全可能：**它被 `git add -A` 一起提交上去** ——
   一次没跑完的自检，反手把产品改坏了。

⇒ 内存里的 `finally` 只挡得住异常，挡不住信号。**原文必须落盘**，
下一次启动先收拾上一轮的烂摊子。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_rv():
    spec = importlib.util.spec_from_file_location(
        "revert_verify_under_test", REPO / "scripts" / "revert_verify.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_killed_run_is_cleaned_up_on_the_next_start(tmp_path, monkeypatch):
    """造一个"上一轮被杀掉"的现场，确认下一次启动能还原。"""
    rv = _load_rv()

    victim = tmp_path / "product.py"
    original = b"def f():\n    return correct_thing()\n"
    victim.write_bytes(original)

    snap_dir = tmp_path / ".snap"
    monkeypatch.setattr(rv, "ROOT", tmp_path)
    monkeypatch.setattr(rv, "SNAPSHOT_DIR", snap_dir)
    monkeypatch.setattr(rv, "MANIFEST", snap_dir / "manifest.json")

    rv.save_snapshot({victim: original})
    # …这里进程被 SIGTERM 杀掉，改坏的内容留在树上
    victim.write_bytes(b"def f():\n    pass\n")

    restored = rv.restore_from_disk()

    assert restored == ["product.py"], f"没还原：{restored}"
    assert victim.read_bytes() == original, "文件内容没回到改坏之前"


def test_restoring_is_a_no_op_when_the_previous_run_finished_cleanly(tmp_path, monkeypatch):
    """没有残留时不许乱动文件 —— 否则它自己就成了一个改文件的东西。"""
    rv = _load_rv()
    snap_dir = tmp_path / ".snap"
    monkeypatch.setattr(rv, "ROOT", tmp_path)
    monkeypatch.setattr(rv, "SNAPSHOT_DIR", snap_dir)
    monkeypatch.setattr(rv, "MANIFEST", snap_dir / "manifest.json")

    victim = tmp_path / "product.py"
    victim.write_bytes(b"whatever\n")
    assert rv.restore_from_disk() == []
    assert victim.read_bytes() == b"whatever\n"


def test_clear_snapshot_removes_the_marker(tmp_path, monkeypatch):
    """跑完必须把标记清掉，否则下一轮启动会一直喊"上一轮没跑完"。"""
    rv = _load_rv()
    snap_dir = tmp_path / ".snap"
    monkeypatch.setattr(rv, "ROOT", tmp_path)
    monkeypatch.setattr(rv, "SNAPSHOT_DIR", snap_dir)
    monkeypatch.setattr(rv, "MANIFEST", snap_dir / "manifest.json")

    victim = tmp_path / "product.py"
    victim.write_bytes(b"x\n")
    rv.save_snapshot({victim: b"x\n"})
    assert (snap_dir / "manifest.json").exists()
    rv.clear_snapshot()
    assert not snap_dir.exists()


def test_the_snapshot_dir_is_git_ignored():
    """快照目录绝不能被 `git add -A` 收进提交。"""
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".revert_verify_snapshot" in ignore, (
        "`.revert_verify_snapshot/` 没进 .gitignore —— "
        "一次被杀掉的自检会把产品文件的旧副本带进提交。")
