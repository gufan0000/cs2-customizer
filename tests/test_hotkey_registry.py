# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""热键注册中心契约测试（P2.1）。

不依赖 keyboard/mouse 真实库——测的是注册表/冲突检测/注销的逻辑层。
declare_interest 不挂底层钩子，因此在无库环境也能跑。
"""
from __future__ import annotations

import pytest

from core.hotkeys import registry as r


@pytest.fixture(autouse=True)
def _clean_registry():
    # 每个用例前后清空注册表，避免相互污染
    for row in list(r.list_bindings()):
        r.unregister_owner(row["owner"])
    yield
    for row in list(r.list_bindings()):
        r.unregister_owner(row["owner"])


def test_declare_and_list():
    t = r.declare_interest("放大镜", ["f2", "f3"], note="测试")
    assert t is not None
    rows = r.list_bindings()
    assert len(rows) == 1
    assert rows[0]["owner"] == "放大镜"
    assert "f2" in rows[0]["key"]


def test_conflict_detection_cross_owner():
    r.declare_interest("放大镜", ["f2"])
    r.declare_interest("音板", ["f2", "f4"])
    # f2 被两个 owner 占用
    owners = r.find_conflicts("f2")
    assert set(owners) == {"放大镜", "音板"}
    # 排除自己后只剩对方
    assert r.find_conflicts("f2", exclude_owner="音板") == ["放大镜"]
    # f4 只有音板
    assert r.find_conflicts("f4") == ["音板"]
    # 没人用的键
    assert r.find_conflicts("f9") == []


def test_unregister_owner_removes_all():
    r.declare_interest("音板", ["f2"])
    r.declare_interest("音板", ["f4"])
    r.declare_interest("瞄点", ["="])
    assert len(r.list_bindings()) == 3
    removed = r.unregister_owner("音板")
    assert removed == 2
    rows = r.list_bindings()
    assert len(rows) == 1
    assert rows[0]["owner"] == "瞄点"


def test_key_normalization():
    r.declare_interest("放大镜", ["  F2  "])
    # 查询大小写/空格不敏感
    assert r.find_conflicts("f2") == ["放大镜"]
    assert r.find_conflicts("F2") == ["放大镜"]


def test_empty_keys_ignored():
    assert r.declare_interest("x", []) is None
    assert r.declare_interest("x", ["", "  "]) is None
    assert len(r.list_bindings()) == 0


def test_game_critical_hotkey_detection():
    """含游戏常用键(修饰键/移动键/武器键)的热键应被判定为游戏关键——
    音板据此决定不 suppress，避免蹲键延迟/吞键(2.2.1 ctrl 延迟修复)。"""
    # 修饰键组合(延迟元凶)
    assert r.hotkey_has_game_critical_key("ctrl+1") is True
    assert r.hotkey_has_game_critical_key("ctrl") is True
    assert r.hotkey_has_game_critical_key("shift+g") is True
    assert r.hotkey_has_game_critical_key("alt+f") is True
    # 移动/动作/武器键
    assert r.hotkey_has_game_critical_key("w") is True
    assert r.hotkey_has_game_critical_key("space") is True
    assert r.hotkey_has_game_critical_key("2") is True
    # 大小写/空格不敏感
    assert r.hotkey_has_game_critical_key(" CTRL+1 ") is True
    # 游戏用不到的键 → 可安全 suppress
    assert r.hotkey_has_game_critical_key("f1") is False
    assert r.hotkey_has_game_critical_key("f12") is False
    assert r.hotkey_has_game_critical_key("=") is False
