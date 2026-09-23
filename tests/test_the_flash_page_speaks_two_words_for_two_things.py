# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-644（批 97）：flash 页有两件事 —— 开关（`flash_enabled`）与后台监听
（`process_manager.is_running`）—— 就只许有**两套词**，每套自己内部一致。

外审（批 96 第二轮 S4 2/3）：「顶部有总开关、底栏又有『启动』按钮，两者逻辑重叠；
同屏状态词三种（未开启 / 未启用 / 待启动），不知道要在游戏里生效到底是拨开关还是点启动」。
RN-192 早已裁定两件事分开（开关管启用、按钮管启动），这一批修的是**说法**：

- 开关这件事：状态卡那颗开关自带的词（`master_switch_link.STATE_ON_TEXT / STATE_OFF_TEXT`），
  「效果 · …」芯片与详情里的「总开关：…」必须用**同一对词**；
- 监听这件事：「运行 · 已启动 / 未启动」，按钮叫「启动监听」，详情写「监听：…」；
- 没开开关时按钮置灰，tooltip 点名那颗总开关，说清先后（⚠ 不点「自定闪光」四个字：那也是本页页名，跨页点名判据会要求接链接）。

⭐ 判据造两个世界（没开、开了且在跑），断言的是**渲染出来的文本**，不是源码。
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest
from PySide6.QtWidgets import QLabel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 这一页只许出现的状态词：开关一对、监听一对。
SWITCH_WORDS = {"已开启", "未开启"}
LISTENER_WORDS = {"已启动", "未启动"}
#: 外审点名的第三种词，以及它们的近亲 —— 一个都不许再回到这四行里。
STRAY_WORDS = {"已启用", "未启用", "待启动", "已就绪", "已关闭", "已运行", "未运行"}


class _DummyProcessManager:
    def __init__(self, _config):
        self.is_running = False
        self.calls = []

    def __getattr__(self, name):        # update_* / load_* 全部吞掉
        if name.startswith(("update_", "load_", "play_")):
            return lambda *a, **k: self.calls.append((name, a, k))
        raise AttributeError(name)

    def start_process(self, width, height):
        self.is_running = True

    def stop_process(self):
        self.is_running = False

    def force_clear_flash(self):
        self.calls.append(("force_clear",))

    def preview_flash(self, intensity, duration):
        self.calls.append(("preview", intensity, duration))


def _chips(status_bar) -> list[str]:
    layout = status_bar.layout()
    out = []
    for idx in range(layout.count() if layout else 0):
        w = layout.itemAt(idx).widget()
        if isinstance(w, QLabel) and w.objectName() == "audioStatusChip" and not w.isHidden():
            out.append(w.text())
    return out


def _make_page(qapp, tmp_path, monkeypatch, *, enabled: bool, running: bool):
    import pages.flash_page as mod

    app_data = tmp_path / "appdata"
    (app_data / "resources" / "flash_images").mkdir(parents=True, exist_ok=True)
    (app_data / "resources" / "flash_audio").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "FlashProcessManager", _DummyProcessManager)
    monkeypatch.setattr(mod, "get_app_data_dir", lambda: str(app_data))
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "flash_enabled", enabled, raising=False)
    page = mod.FlashPage()
    # ⚠ 开关开着时页面构造期会自己把监听拉起来（替身的 start_process 置 True），
    #   所以「开了但没在跑」这个世界要在构造之后**明确钉**出来，不能只靠不去启动。
    page.process_manager.is_running = running
    page._sync_overview_status()
    qapp.processEvents()
    return page


def _state_lines(page) -> dict[str, str]:
    """芯片与详情里关于「开关」「监听」的四行，键 → 那一行的状态词。"""
    lines = {}
    for text in _chips(page.status_badge_label):
        head, _, word = text.partition(" · ")
        if head in ("效果", "运行"):
            lines[f"芯片·{head}"] = word.strip()
    for raw in page.status_card.toolTip().splitlines():
        head, _, word = raw.partition("：")
        if head in ("总开关", "监听"):
            lines[f"详情·{head}"] = word.strip()
    assert set(lines) == {"芯片·效果", "芯片·运行", "详情·总开关", "详情·监听"}, (
        f"四行没齐（判据锚点失效）：{lines}")
    return lines


@pytest.mark.parametrize("enabled, running", [(False, False), (True, True)])
def test_only_two_pairs_of_words_are_on_the_card(qapp, tmp_path, monkeypatch, enabled, running):
    page = _make_page(qapp, tmp_path, monkeypatch, enabled=enabled, running=running)
    try:
        lines = _state_lines(page)
        stray = {k: v for k, v in lines.items() if v in STRAY_WORDS
                 or v not in SWITCH_WORDS | LISTENER_WORDS}
        assert not stray, f"这几行用了第三种词（RN-644）：{stray}"
        assert lines["芯片·效果"] == lines["详情·总开关"], "同一件事（开关）两处说法不同"
        assert lines["芯片·运行"] == lines["详情·监听"], "同一件事（监听）两处说法不同"
        assert lines["芯片·效果"] in SWITCH_WORDS and lines["芯片·运行"] in LISTENER_WORDS
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_effect_chip_uses_the_switch_rows_own_word(qapp, tmp_path, monkeypatch):
    """「效果 · X」与它正上方那颗开关自带的状态词必须是同一个 X —— 两处相邻，一字之差就是矛盾。"""
    from widgets import master_switch_link as msl

    for enabled in (False, True):
        page = _make_page(qapp, tmp_path, monkeypatch, enabled=enabled, running=False)
        try:
            expected = msl.STATE_ON_TEXT if enabled else msl.STATE_OFF_TEXT
            assert _state_lines(page)["芯片·效果"] == expected
            row_word = page.master_switch_row._state_label.text()
            assert row_word == expected, "夹具：开关行没同步到 config（判据在错的世界里）"
        finally:
            page.deleteLater()
            qapp.processEvents()


def test_the_button_names_the_second_step_and_points_at_the_first(qapp, tmp_path, monkeypatch):
    """开着没在跑（启动失败）时补救按钮叫「启动监听」；没开开关时底栏**不摆**它。

    ⚖ 2026-09-23 改：以前关着时摆一颗灰的「启动监听」、tooltip 说「先开总开关再点这里」——
    外审第三次 6/6 仍判「两个入口」。根因是开关没做完它该做的事：现在拨开开关就启动监听
    （下一条判据），那句「先…再…」描述的第二步已经不存在了。
    """
    page = _make_page(qapp, tmp_path, monkeypatch, enabled=False, running=False)
    try:
        assert page.action_bar.primary_btn.isHidden(), (
            f"总开关关着，底栏还摆着「{page.action_bar.primary_btn.text()}」—— 第二个入口")
    finally:
        page.deleteLater()
        qapp.processEvents()

    page = _make_page(qapp, tmp_path, monkeypatch, enabled=True, running=False)
    try:
        btn = page.action_bar.primary_btn
        assert btn.text() == "启动监听" and btn.isEnabled() and btn.toolTip() == ""
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_switch_itself_starts_and_clears_the_listener(qapp, tmp_path, monkeypatch):
    """⭐ 开关就是启动：拨开 ⇒ 后台监听起来；拨关 ⇒ 正在显示的白屏当场清掉。

    以前拨开只写 config —— 界面说「已开启」，游戏里没闪光，直到用户发现还得点底栏
    「启动监听」或重启软件。外审三次判「两个入口」，前两次都只改了按钮和词。
    """
    page = _make_page(qapp, tmp_path, monkeypatch, enabled=False, running=False)
    try:
        monkeypatch.setattr(config, "flash_enabled", True, raising=False)
        page.on_master_switch_synced()        # 首页或本页那颗开关拨完，走的就是这一下
        assert page.process_manager.is_running, (
            "总开关拨开了，后台监听没起来 —— 界面说已开启，游戏里却没有闪光")
        assert page.action_bar.primary_btn.text() == "前往效果预览"

        page.process_manager.calls.clear()
        monkeypatch.setattr(config, "flash_enabled", False, raising=False)
        page.on_master_switch_synced()
        assert ("force_clear",) in page.process_manager.calls, (
            "总开关关了，正在显示的白屏没清 —— GSI 那头关了就不再处理，它会停在屏幕上")
        # 关掉只清屏、不停进程（改前也是这样）⇒ 底栏回到「前往效果预览」这颗导航；
        # 要守的是**不出现第二个开启入口**，不是底栏必须空着。
        btn = page.action_bar.primary_btn
        assert btn.isHidden() or btn.text() != "启动监听", "总开关关着，底栏又摆出了「启动监听」"
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_third_word_is_not_in_the_source_either():
    """文本守卫：`flash_page.py` 的字符串常量里不许再有「待启动」「已就绪」。"""
    from _denominator import must_scan

    src = (ROOT / "pages" / "flash_page.py").read_text(encoding="utf-8")
    strings = must_scan([n for n in ast.walk(ast.parse(src))
                         if isinstance(n, ast.Constant) and isinstance(n.value, str)],
                        "flash_page.py 里的字符串常量", least=50)
    hits = sorted({n.value for n in strings
                   if any(w in n.value for w in ("待启动", "已就绪"))
                   and not n.value.lstrip().startswith(("RN-", "⚠", "⭐"))
                   and "\n" not in n.value})   # docstring 里讨论它不算
    assert not hits, f"flash 页源码里又出现第三种词：{hits}"
