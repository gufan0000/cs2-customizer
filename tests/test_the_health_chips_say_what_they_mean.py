# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-527①：**资源体检那几颗芯片，读不出它是「正在检查」还是「需要检查」。**

原来两颗写的是「音频 · 检查」「视觉 · 检查」，而且同色 —— 外审两轮各 3/3 判高。
⚠⚠ 而这一页**自己的解释里早就写好了该显示什么**：
`audio_status_badge.CHIP_EXPLAINS["音频"]` 逐字写着
「**「需检查 N」**是指有 N 项对不上」——
⭐⭐⭐ **一句解释，解释的是一个屏幕上根本不存在的标签。**

为什么要单独一支判据（而不是靠结构基线）：那几颗芯片的**状态**是环境相关的
（我这台装着素材、CI runner 是干净的），所以 `_page_structure` 把它们整条脱敏成
`<环境相关>`。脱敏之后**「话说得对不对」就没人看了** ——
⭐ **基线管「结构变没变」，这一支管「话说得对不对」**：拿合成报告喂进去，
每一种状态下的逐字文案都是纯函数，与这台机器无关。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_health_chips_say_what_they_mean.py`）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _report(*, audio_bad: int = 0, visual_bad: int = 0) -> dict:
    """造一份体检报告：音频 N 项对不上、视觉 M 项对不上。"""
    summary = {
        "ok": not (audio_bad or visual_bad),
        "audio_missing_directories": audio_bad,
        "audio_invalid_config_refs": 0,
        "audio_empty_style_dirs": 0,
        "visual_missing_directories": visual_bad,
        "visual_invalid_config_refs": 0,
        "visual_empty_style_dirs": 0,
        "missing_directories": audio_bad + visual_bad,
        "invalid_config_refs": 0,
        "empty_style_dirs": 0,
    }
    return {
        "summary": summary,
        "audio": {"summary": {"ok": not audio_bad}},
        "visual": {"summary": {"ok": not visual_bad}},
    }


@pytest.fixture(scope="module")
def chips_of():
    """把一份报告喂进真页面，回报它那一排芯片的逐字文案。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    sys.path.insert(0, str(REPO / "scripts"))
    from _audit_neutralize import enable_audit_mode

    enable_audit_mode()
    app = QApplication.instance() or QApplication([])
    from pages.audio_health_page import AudioHealthPage

    page = AudioHealthPage()

    def _run(report: dict) -> list[str]:
        page._sync_status_strip(report)
        app.processEvents()
        from PySide6.QtWidgets import QLabel
        return [lab.text() for lab in page.status_badge_label.findChildren(QLabel)
                if lab.objectName() == "audioStatusChip"]

    yield _run
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("audio_bad, visual_bad, expect", [
    (0, 0, ["体检 · 健康", "音频 · 正常", "视觉 · 正常"]),
    (12, 0, ["体检 · 发现问题", "音频 · 需检查 12 项", "视觉 · 正常"]),
    (0, 5, ["体检 · 发现问题", "音频 · 正常", "视觉 · 需检查 5 项"]),
    (3, 7, ["体检 · 发现问题", "音频 · 需检查 3 项", "视觉 · 需检查 7 项"]),
])
def test_each_chip_says_which_state_it_is_in(chips_of, audio_bad, visual_bad, expect):
    """⭐ 「检查」两个字读不出是哪一种状态；**把数说出来**才读得出。"""
    got = chips_of(_report(audio_bad=audio_bad, visual_bad=visual_bad))
    assert got == expect, (
        f"音频 {audio_bad} 项 / 视觉 {visual_bad} 项时，芯片应为\n  {expect}\n实际\n  {got}")


def test_the_explanation_names_a_label_that_exists(chips_of):
    """⭐⭐⭐ **页面自己的解释里引用的那个标签，屏幕上必须真的出现过。**

    ⚠ 这条是本条缺陷的指纹：`CHIP_EXPLAINS["音频"]` 引了「需检查 N」，
    而代码发的是「检查」——**解释和被解释的东西对不上，而两边各自都读得通**。
    """
    from pages.audio_status_badge import CHIP_EXPLAINS

    quoted = CHIP_EXPLAINS.get("音频", "")
    assert "需检查" in quoted, (
        "「音频」那条解释不再引用「需检查」了 —— 那这条判据在守一个不存在的约定，"
        "请连同芯片文案一起重想。")
    chips = chips_of(_report(audio_bad=4))
    assert any("需检查" in c for c in chips), (
        f"解释里说的是「需检查 N」，而屏幕上一颗芯片都没这么写：{chips}")


def test_the_total_is_not_said_twice(chips_of):
    """⚠ 分侧有了数之后，原来那颗「项目 · N 项」就是同一个数的和。

    ⭐ 同 RN-049（「别处说了，它就只是噪音」），也是官网那条
    「**同一个数字出现两次会被读成两笔**」。
    """
    chips = chips_of(_report(audio_bad=3, visual_bad=7))
    assert not any(c.startswith("项目 · ") for c in chips), (
        f"「项目 · N 项」又回来了，而 3 + 7 已经分别写在两颗上：{chips}")
    assert len(chips) == 3, f"这一排应当是三颗（体检 / 音频 / 视觉）：{chips}"


def test_the_one_line_summary_uses_the_same_words(chips_of):
    """⚠ 同一屏上说同一件事的两处，改了一处另一处留在原地 —— RN-508 的形状。

    这一页已经犯过一次（按钮改名而点名它的底栏文案没跟着改）。
    """
    from PySide6.QtWidgets import QApplication

    QApplication.instance()
    from pages.audio_health_page import AudioHealthPage

    page = AudioHealthPage()
    page._sync_status_strip(_report(audio_bad=2, visual_bad=0))
    text = page.summary_label.text()
    assert "待检查" not in text, (
        f"一句话摘要还写着「待检查」，而芯片已经改口成「需检查 N 项」：{text!r}")
    assert "需检查 2 项" in text, f"摘要没跟着说出那个数：{text!r}"
    page.deleteLater()
