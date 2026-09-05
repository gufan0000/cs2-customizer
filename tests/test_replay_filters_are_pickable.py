# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-508：`audio_replay` 的筛选是**选出来的**，不是让用户拼内部记号。

## 缺陷

三个筛选原来是自由输入框，提示语写着 `play/drop/preempt/load`、
`kill/headshot/c4/...`、「按 key 子串过滤」。

⚠⚠ **而中间那条给的例子一行都匹配不上。** `event_type` 的真实取值是
`kill_voice` / `load` / `round_sounds` / `health_warning` 这一类，
筛选做的是**精确比较** —— 照着提示语输 `kill` 或 `c4`，永远返回 0 条。
⭐⭐⭐ 而「筛选不出东西」看起来完全像「本来就没有这种事件」，
所以这个缺陷可以一直存在而不被任何人报告。

## 这里守的三件事

1. **动作筛选是闭集下拉**，而且它的选项 = 代码里真会记录的那几种动作
   （分母从 `_record_timeline_event(action=...)` 的字面实参扫出来）。
2. **事件筛选的选项来自真有的记录** —— 选不出一个匹配不上的值。
3. **屏幕上不许再出现内部记号**：芯片、底栏回执、表格里都得是人话。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QComboBox, QMessageBox

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.audio.audio_event_timeline import AudioEvent, get_audio_event_timeline  # noqa: E402
from core.audio_event_text import ACTION_LABELS  # noqa: E402

RUNNER = REPO / "core" / "audio" / "audio_manager.py"


def _recorded_actions() -> set[str]:
    """代码里真会记录的动作 —— 这条判据的分母，不是我记得的那几个。"""
    src = RUNNER.read_text(encoding="utf-8")
    found = set()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "_record_timeline_event"):
            continue
        for kw in node.keywords:
            if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                found.add(str(kw.value.value))
    return found


def test_every_action_the_code_records_is_pickable():
    actions = _recorded_actions()
    assert actions, "一个动作字面值都没扫到 —— 识别器瞎了，而不是真的没有"
    missing = sorted(actions - set(ACTION_LABELS))
    assert not missing, (
        f"这些动作会出现在事件表里，却没有中文、也选不出来：{missing}\n"
        "⇒ 补进 `core/audio_event_text.ACTION_LABELS`。")
    stale = sorted(set(ACTION_LABELS) - actions)
    assert not stale, (
        f"`ACTION_LABELS` 里这些动作代码已经不记录了：{stale} —— "
        "下拉里会出现一个永远筛不出东西的选项。")


@pytest.fixture
def page(qapp, monkeypatch):
    import pages.audio_replay_page as mod

    timeline = get_audio_event_timeline()
    timeline.clear()
    timeline.record(AudioEvent(timestamp=1.0, action="play", key="kill-1",
                               channel_type="kill_voice", event_type="kill_voice"))
    timeline.record(AudioEvent(timestamp=2.0, action="drop", key="reload-ak",
                               channel_type="reload_sounds", event_type="reload_sounds"))
    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: object())
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    p = mod.AudioReplayPage()
    qapp.processEvents()
    yield p
    p.deleteLater()
    timeline.clear()
    qapp.processEvents()


def test_the_action_filter_is_a_closed_list_not_free_text(page):
    """动作筛选必须是下拉 —— 自由输入就意味着可以输入一个匹配不上的值。"""
    assert isinstance(page.action_combo, QComboBox), (
        "动作筛选又变回自由输入框了。自由输入的代价是：用户得先知道内部拼写，"
        "而拼错的结果和「真的没有这种事件」长得一模一样。")
    values = {page.action_combo.itemData(i) for i in range(page.action_combo.count())}
    assert "" in values, "下拉里没有「全部」这一项"
    assert set(ACTION_LABELS) <= values, (
        f"下拉少了这些动作：{sorted(set(ACTION_LABELS) - values)}")


def test_the_event_filter_only_offers_values_that_exist(page):
    """事件筛选的选项来自**真有的记录** —— 选不出一个匹配不上的值。"""
    offered = {page.event_combo.itemData(i) for i in range(page.event_combo.count())}
    offered.discard("")
    assert offered == {"kill_voice", "reload_sounds"}, (
        f"事件下拉给出的选项与记录里真有的对不上：{sorted(offered)}")

    for value in sorted(offered):
        index = page.event_combo.findData(value)
        page.event_combo.setCurrentIndex(index)
        page._refresh_events()
        assert page._events, (
            f"选了「{page.event_combo.currentText()}」却筛出 0 条 —— "
            "下拉里出现了一个匹配不上的值，这正是 RN-508 要根除的那件事。")


def test_no_internal_token_is_left_on_screen(page):
    """芯片 / 底栏回执 / 表格里都不许再出现内部记号。"""
    page.action_combo.setCurrentIndex(page.action_combo.findData("play"))
    page._refresh_events()
    qtexts = [page.action_bar.message_label.text(),
              page.summary_label.text(),
              page.summary_label.toolTip()]
    for row in range(page.table.rowCount()):
        for col in range(page.table.columnCount()):
            item = page.table.item(row, col)
            if item is not None:
                qtexts.append(item.text())

    banned = ("play", "drop", "preempt", "kill_voice", "reload_sounds",
              "OK", "FAIL", "audio_not_loaded")
    hits = sorted({b for b in banned for t in qtexts if b in t})
    assert not hits, f"屏幕上还留着内部记号：{hits}\n实际文本：{qtexts}"
