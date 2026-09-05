# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-146：`audio_health` 建完页之后的样子**不许取决于扫盘扫了多久**。

## 缺陷

这一页在 `__init__` 里就起一个后台线程去扫资源目录。扫描完成得比取样早还是晚，
决定了屏幕上是「正在扫描…」（按钮置灰、状态芯片还没算）还是结果列表 ——
于是**同一份配置复跑，这一页的控件树会变**（CI 上实测 18 条差异）。

⚠⚠ **本机复现不了。** 我这台机器上扫得快，六次取样六次一样；
CI runner 上才炸。⇒ 「本机三次一致」**证明不了任何事**，
它只说明我这台机器不够慢（同批 47 RN-518 那条：我的机器不够挤）。

⇒ 这条判据**自己把机器变慢**：把扫描换成一个会睡的假实现，于是那场竞速
在任何机器上都必然发生。然后问两件事：
  · 关掉同步开关 ⇒ 建完页拿到的是**占位文案**（竞速窗口真实存在）；
  · 打开同步开关 ⇒ 建完页拿到的是**结果**，而且和慢不慢无关。
"""
from __future__ import annotations

import time

import pytest

PLACEHOLDER = "正在扫描"


@pytest.fixture
def health_module(monkeypatch):
    import pages.audio_health_page as mod

    slow_report = {
        "checked_at": "2026-09-05T01:00:00",
        "summary": {"ok": False, "missing_directories": 2,
                    "invalid_config_refs": 0, "empty_style_dirs": 0},
        "audio": {"audio_root": "", "summary": {"ok": False, "missing_directories": 2,
                                                "invalid_config_refs": 0, "empty_style_dirs": 0},
                  "missing_directories": ["a", "b"], "invalid_config_refs": []},
        "visual": {"resource_root": "", "summary": {"ok": True, "missing_directories": 0,
                                                    "invalid_config_refs": 0, "empty_style_dirs": 0},
                   "missing_directories": [], "invalid_config_refs": []},
    }

    def slow_collect():
        # ⭐ 把机器变慢的是判据自己，不是运气。
        time.sleep(0.4)
        return slow_report

    monkeypatch.setattr(mod, "collect_resource_system_health", slow_collect)
    return mod


def _build(mod, qapp):
    page = mod.AudioHealthPage()
    qapp.processEvents()
    return page


def test_without_the_switch_the_page_is_still_scanning_right_after_build(
        health_module, qapp, monkeypatch):
    """先证明**竞速窗口真的存在** —— 否则下一条就是在证明一件本来就成立的事。

    ⚠ 这是阳性对照。批 43 的教训：一个对照组先要证明它真的是对照。
    """
    monkeypatch.delenv(health_module.AudioHealthPage.SYNC_SCAN_ENV, raising=False)
    page = _build(health_module, qapp)
    try:
        assert PLACEHOLDER in page.report_text.toPlainText(), (
            "关掉同步开关、且扫描要跑 0.4 秒，建完页却已经拿到结果了 —— "
            "那说明这一页不再有异步扫描，这条判据失去了对象。")
        assert page.check_btn.isEnabled() is False
    finally:
        page.deleteLater()


def test_with_the_switch_the_page_is_settled_right_after_build(
        health_module, qapp, monkeypatch):
    """开着同步开关，建完页拿到的必须是**结果态**，与扫描快慢无关。"""
    monkeypatch.setenv(health_module.AudioHealthPage.SYNC_SCAN_ENV, "1")
    page = _build(health_module, qapp)
    try:
        text = page.report_text.toPlainText()
        assert PLACEHOLDER not in text, (
            "开了同步开关，建完页还停在「正在扫描」—— 那道开关没接上，"
            "基线仍然会拍到随机的一态（RN-146）。")
        assert "资源体检报告" in text
        assert page.check_btn.isEnabled() is True
    finally:
        page.deleteLater()


def test_two_builds_with_the_switch_look_exactly_the_same(
        health_module, qapp, monkeypatch):
    """同一份配置建两次，控件树投影必须逐字节相同。"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from _page_structure import structure

    monkeypatch.setenv(health_module.AudioHealthPage.SYNC_SCAN_ENV, "1")
    shots = []
    for _ in range(2):
        page = _build(health_module, qapp)
        shots.append(structure(page))
        page.deleteLater()
        qapp.processEvents()
    assert shots[0] == shots[1], "两次建页的控件树投影不同 —— RN-146 没修好"


def test_the_tooling_actually_turns_the_switch_on():
    """⭐ 开关修好了，但**没人打开它**的话等于没修。

    分母：采基线那条路（`renovation_baseline.structure_of`）与出图那条路
    （`ui_shot_capture` 走 `enable_audit_mode`）。少一条就会有一类产物仍然随机。
    """
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    env = "CS2C_SYNC_HEALTH_SCAN"
    baseline = (repo / "scripts" / "renovation_baseline.py").read_text(encoding="utf-8")
    neutralize = (repo / "scripts" / "_audit_neutralize.py").read_text(encoding="utf-8")
    assert env in baseline, f"采基线那条路没打开 {env} —— 结构基线仍会拍到随机的一态"
    assert env in neutralize, f"`enable_audit_mode()` 没打开 {env} —— 截图仍会拍到随机的一态"
