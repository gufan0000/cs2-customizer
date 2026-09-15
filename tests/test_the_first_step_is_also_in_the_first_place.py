# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-597：**「那一颗紫的必须是当下的第一步」这条裁定，原来只做了颜色那一半。**

批 44（RN-450）立的裁定逐字写在 `_sync_first_step()` 的文档字符串里，
而它做的只有 `style_as_primary_button` / `style_as_secondary_button` ——
**按钮的排列顺序从头到尾没动过**。于是体检发现问题之后，
紫的是第二颗，第一个位置上仍然是「立即体检」。

⭐⭐⭐ **同一条裁定，做了一半；而做掉的那一半（颜色）正好是能被外审看见的那一半，
于是它看起来像做完了。**

批 79 的 A/B（判断题「你会不会先点最左边那一颗」，完整 + 紧凑各 3 发）：

| 候选 | 票数 |
|---|---|
| A 原样 | **6/6「不会」** |
| B 把「立即体检」改名成「重新体检」 | **6/6「不会」** —— 改善为零 |
| **C 把「一键修复」前移到第一位** | **6/6「会」** |

地板页（`utility`，三组图逐字节相同）**9/9 一致** ⇒ 本轮噪声为 0。

这支判据钉三件事：
① 发现问题时，**排在第一位的就是那颗主按钮**（不只是颜色）；
② 健康时顺序**换回去**（否则就成了「一个位置固定、含义会变」的按钮，RN-506）；
③ **焦点链跟着走** —— `insertWidget` 改布局顺序，而 Tab 顺序走构造顺序
   （批 38 / RN-063）。⭐ 这一条是 A/B 那六张图上**看不见**的。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_first_step_is_also_in_the_first_place.py`）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture(scope="module")
def page():
    app = QApplication.instance() or QApplication([])
    from pages.audio_health_page import AudioHealthPage

    # ⚠ RN-646（批 97）顺带：构造函数起一个后台线程扫盘，报告回来得比用例晚 ——
    #   真实报告（隔离目录里资源是空的 ⇒ ok=False）把「顺序换回去」那一步又翻回来。
    #   这条以前绿，是因为被污染的测试配置让那场竞速碰巧输给用例（conftest 清掉
    #   config.json 之后当场红、HEAD 副本照旧绿）。用产品自带的工装档同步扫完再开始。
    os.environ[AudioHealthPage.SYNC_SCAN_ENV] = "1"
    widget = AudioHealthPage()
    app.processEvents()
    try:
        yield widget, app
    finally:
        widget.close()
        os.environ.pop(AudioHealthPage.SYNC_SCAN_ENV, None)


def _row_texts(widget):
    row = widget._actions_row
    return [row.itemAt(i).widget().text()
            for i in range(row.count())
            if row.itemAt(i).widget() is not None]


def _report(ok: bool, missing: int = 0):
    """造一份体检结果。⚠ 只喂 `_sync_first_step` / `_sync_action_bar` 读的那几格。"""
    return {"summary": {"ok": ok, "missing_directories": missing,
                        "invalid_config_refs": 0, "empty_style_dirs": 0}}


def test_when_something_is_broken_the_fix_button_comes_first(page):
    """⭐ 发现问题 ⇒ 第一位就是「一键修复」，**不只是它变紫**。"""
    widget, app = page
    widget._sync_action_bar(_report(ok=False, missing=17))
    app.processEvents()

    texts = _row_texts(widget)
    # ⭐ 分母守卫：这一排本来就该有四颗；塌了的话下面那条断言会空转着变绿。
    assert len(texts) == 4, f"「体检与修复」那一排不是四颗按钮，而是 {texts}"
    assert texts[0] == widget.fix_btn.text(), (
        f"发现问题时排第一的是 {texts[0]!r}，而当下的第一步是 "
        f"{widget.fix_btn.text()!r} —— RN-597 说的就是这件事")


def test_when_everything_is_fine_the_order_goes_back(page):
    """⛔ 顺序必须**换得回去**。

    ⚠ 只往前挪、不挪回来的话，「一键修复」就变成一颗**位置固定、含义随状态变**
      的按钮 —— 那正是 RN-506 记过的、比两颗按钮更难防的那一种。
    """
    widget, app = page
    widget._sync_action_bar(_report(ok=True))
    app.processEvents()

    texts = _row_texts(widget)
    assert len(texts) == 4, f"分母塌了：{texts}"
    assert texts[0] == widget.check_btn.text(), (
        f"资源健康时排第一的是 {texts[0]!r}，而这一档的第一步是再体检一次")


def test_the_focus_chain_follows_what_the_eye_sees(page):
    """⛔⛔ **焦点链走构造顺序，改布局顺序一个字都不改它**（批 38 / RN-063）。

    ⭐ 不串这一遍，屏幕上第一颗是「一键修复」而 Tab 的第一站还是「立即体检」——
      而 A/B 那六张截图上**看不见**这件事，只有这条断言看得见。
    """
    widget, app = page
    widget._sync_action_bar(_report(ok=False, missing=17))
    app.processEvents()

    first = widget.fix_btn
    assert _row_texts(widget)[0] == first.text(), "前提不成立：第一位不是「一键修复」"
    assert first.nextInFocusChain() is not None

    # 从第一颗出发沿焦点链往下走，四颗按钮出现的先后必须和眼睛看到的一致。
    wanted = [widget.fix_btn, widget.check_btn, widget.open_btn, widget.export_btn]
    seen, node, guard = [], first, 0
    while guard < 400:
        if node in wanted and node not in seen:
            seen.append(node)
            if len(seen) == len(wanted):
                break
        node = node.nextInFocusChain()
        guard += 1

    assert seen == wanted, (
        "焦点链顺序是 " + " → ".join(b.text() for b in seen)
        + "，而屏幕上是 " + " → ".join(b.text() for b in wanted))
