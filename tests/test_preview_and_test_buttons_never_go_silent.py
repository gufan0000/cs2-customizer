# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-011 / RN-012 / RN-017：点了没反应的按钮，必须至少说一句话。

这三条是同一类缺陷的三个实例，也是这轮翻新里最常见的一类：
**功能没坏、没崩、日志也写了，但用户点下去屏幕上什么都没发生。**
用户唯一能得出的结论是"这软件坏了"，而开发者永远收不到有效反馈。

- RN-012：屏幕特效页的两个预览按钮在 `overlay_manager is None` 时静默 return。
  而它**只在主窗构造特效管理器失败时**才是 None —— 恰恰是软件真出问题的时候，
  用户连个提示都没有。
- RN-011：同一页的提示文案承诺「底部工具栏**会保留**预览」，
  而取消勾选时那两个按钮就被禁用了。**文案承诺了一件代码不做的事。**
- RN-017：击杀语音页的「测试」按钮，2~5 连杀找不到文件时会给提示，
  **第 1 连杀却是静默 return**。同一个按钮，不同档位两种脾气。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


# ------------------------------------------------------------------ 屏幕特效页

@pytest.fixture()
def effects_page(qapp, monkeypatch):
    import pages.screen_effects_page as mod

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "screen_effects_enabled", True, raising=False)
    monkeypatch.setattr(config, "screen_edge_flash_enabled", True, raising=False)
    # ⚠ 故意不给 overlay_manager —— 这正是要测的那个状态。
    page = mod.ScreenEffectsPage(overlay_manager=None)
    qapp.processEvents()
    yield page
    page.deleteLater()
    qapp.processEvents()


def _message_after(page, qapp, call):
    page.action_bar.set_message("")
    call()
    qapp.processEvents()
    return page.action_bar.message_label.text().strip()


def test_preview_without_overlay_manager_says_something_specific(effects_page, qapp):
    """组件没起来 和 预览炸了，必须是**两句不同的话**。

    ⚠ **只断言"有话说"是假绿的** —— 回退验证当场逮到：把 `overlay_manager is None`
    这道判断去掉之后，`None.preview()` 抛的 AttributeError 会被同一个函数里的
    兜底 `except` 接住、照样给一句"预览播放失败"，于是判据依旧全绿。
    **我在同一次修复里加的兜底，把自己前一条判据的判别力吃掉了。**
    ⇒ 有兜底分支时，判据必须断言到能把两条路径区分开的那一层。
    """
    none_msg = _message_after(effects_page, qapp, effects_page._preview_normal)
    assert none_msg, (
        "特效管理器没起来时点「预览击杀」，界面上一个字都没有 —— "
        "而这恰恰是软件真出问题的时候，用户只会以为按钮是坏的")
    assert "预览不可用" in none_msg, (
        f"提示没说清「组件没启动」这件事，用户不知道该怎么办：{none_msg!r}")

    head_msg = _message_after(effects_page, qapp, effects_page._preview_headshot)
    assert head_msg == none_msg, "「预览爆头」同样不许静默，且该给同一句解释"

    class _Boom:
        def preview(self, is_headshot=False):
            raise RuntimeError("显卡罢工了")

    effects_page.overlay_manager = _Boom()
    boom_msg = _message_after(effects_page, qapp, effects_page._preview_normal)
    assert boom_msg, "预览抛异常时被吞掉了，用户看不到任何东西"
    assert boom_msg != none_msg, (
        "「组件没启动」和「预览炸了」给的是同一句话 —— "
        "说明有一条路径其实是掉进兜底 except 里了，不是被正经处理的")


def test_trigger_tip_does_not_promise_what_the_code_undoes(effects_page, qapp):
    """文案与行为必须一致：勾选框一取消，预览按钮就没了，文案不能说"会保留"。"""
    from PySide6.QtWidgets import QLabel

    effects_page.enable_edge_flash_checkbox.setChecked(False)
    qapp.processEvents()
    # 先确认行为确实是"按钮被禁用"，否则下面查文案就是无的放矢
    assert not effects_page.action_bar.primary_btn.isEnabled(), (
        "取消勾选后预览按钮居然还是可用的，这条判据的前提不成立")

    tips = [w.text() for w in effects_page.findChildren(QLabel)
            if w.objectName() == "hintLabel" and "预览" in w.text()]
    assert tips, "找不到那句关于预览的提示文案，判据在空转"
    for text in tips:
        assert "保留" not in text, (
            f"文案仍在承诺预览「会保留」，而实际会被禁用：{text!r}")


# ------------------------------------------------------------------ 击杀语音页

class _DummyAudio:
    def __init__(self):
        self.kill_voice_styles = ["styleV"]
        self.weapon_kill_voice_styles = {}
        self.weapon_voices_dir = "H:/tmp/__不存在的目录__/weapon"
        self.kill_voices_dir = "H:/tmp/__不存在的目录__/common"
        self._sounds = {}

    def ensure_styles_scanned(self):
        return None

    def scan_kill_voice_styles(self):
        return self.kill_voice_styles

    def scan_weapon_kill_voice_styles(self):
        return self.weapon_kill_voice_styles


@pytest.mark.parametrize("level,expect", [
    # ⚠ 这里必须断言到**能区分路径**的那句话，只查"有没有话"是假绿的：
    # 回退验证当场逮到 —— 把第 1 档的分支改回去之后，流程会往下掉进
    # "文件读不到"那条兜底提示，照样有话说，判据照样绿。
    (1, "没有可用的语音文件"),
    (2, "连杀"),
    (5, "连杀"),
])
def test_test_button_reports_missing_audio_at_every_level(qapp, monkeypatch, level, expect):
    """1 连杀和 2~5 连杀必须一视同仁 —— 原先只有 >1 档会说话。"""
    import pages.kill_voice_page as mod

    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: _DummyAudio())
    monkeypatch.setattr(
        mod, "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [],
                        "issue_count": 0})
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {"weapon_glock": "styleV"},
                        raising=False)

    page = mod.KillVoicePage()
    qapp.processEvents()
    try:
        page.action_bar.set_message("")
        page._test_weapon_voice("weapon_glock", level)
        qapp.processEvents()
        msg = page.action_bar.message_label.text().strip()
        assert msg, (
            f"第 {level} 连杀试听找不到音频文件时，界面上一个字都没有。"
            "同一个「测试」按钮不能有的档位说话、有的档位装死。")
        assert expect in msg, (
            f"第 {level} 连杀给的提示不对路（期望包含 {expect!r}）：{msg!r}。"
            "多半是掉进了别的兜底分支，而不是这一档自己该走的那条路。")
    finally:
        page.deleteLater()
        qapp.processEvents()
