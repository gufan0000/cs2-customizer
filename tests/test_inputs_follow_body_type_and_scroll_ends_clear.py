# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 161：输入框跟上正文字号、卡片顶边看得出、滚到底不贴底栏、排版审计从最大一档起步再量一遍。

B160 留下的四条候选，各钉住一条行为。
"""
from __future__ import annotations

import pytest


def test_inputs_and_combos_use_the_body_size():
    """批 160 正文改 15，输入框、多行框、下拉框还停在 14，同一行里框里的字比标签小一号。"""
    from ui_design_system import FontSize, InputSpec

    spec, body = InputSpec(), FontSize().md
    assert (spec.text_font_size, spec.textarea_font_size, spec.combobox_font_size) == (body, body, body)
    assert body == 15


@pytest.mark.parametrize("scale", [1.0, 1.1, 1.25])
def test_the_bigger_input_type_does_not_make_the_boxes_taller(scale):
    """字大一号，上下内边距让出 1px：内容盒装下一行字的同时，框的高度不比改前（内边距 5、字 14）高。"""
    from PySide6.QtGui import QFont, QFontMetrics

    from core.utils.app_fonts import UI_FONT_FAMILY, load_ui_fonts
    from ui_design_system import InputSpec, apply_font_scale, get_design_system

    assert load_ui_fonts()
    apply_font_scale(scale)
    try:
        spec = get_design_system().input
        size = spec.combobox_font_size
    finally:
        apply_font_scale(1.0)
    font = QFont(UI_FONT_FAMILY)
    font.setPixelSize(size)
    old = QFont(UI_FONT_FAMILY)
    old.setPixelSize(max(9, round(14 * scale)))
    base = InputSpec()
    for pad in (base.text_padding_vertical, base.combobox_padding_vertical):
        now = QFontMetrics(font).height() + 2 * pad
        before = QFontMetrics(old).height() + 2 * 5
        assert now <= before, f"x{scale}：字 {size}px、内边距 {pad} 要 {now}px，改前 {before}px"


def test_the_card_top_edge_is_bright_enough_to_see():
    """批 160 叠 14/255 的白（#25272e → #313339），外审整窗图 12/12 看不出这一级。"""
    from theme_manager import ThemeManager

    dark = ThemeManager().themes["dark"]
    edge, side = dark._card_top_edge(), dark.colors.border_secondary
    diff = [int(edge[i:i + 2], 16) - int(side[i:i + 2], 16) for i in (1, 3, 5)]
    assert min(diff) >= 18, (edge, side, diff)
    assert max(diff) <= 40, f"亮成一条线了：{edge} 对 {side}"


def test_scrolled_to_the_end_the_last_row_clears_the_bottom_bar(qapp, monkeypatch):
    """预设中心滚动内容末尾 0px，滚到底最后一行贴着底栏的分隔线；放得下时不许因此多出可滚的几像素。"""
    from PySide6.QtWidgets import QMessageBox, QWidget

    import gui_widget
    import pages.preset_center_page as mod
    from widgets.page_width import SCROLL_END_GAP, page_level_scrolls

    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: 0)
    page = mod.PresetCenterPage()

    class _Win:
        def _normalize_layout_metrics(self, *args, **kwargs):
            return gui_widget.MainWindow._normalize_layout_metrics(self, *args, **kwargs)

    def settle():
        for _ in range(4):
            qapp.processEvents()

    try:
        gui_widget.MainWindow._harmonize_page_chrome(_Win(), page)
        scroll = max(page_level_scrolls(page), key=lambda s: s.widget().height() if s.widget() else 0)
        content = scroll.widget()
        page.resize(1100, 700)
        page.show()
        settle()
        bar = scroll.verticalScrollBar()
        assert bar.maximum() > 0, "这一档本来就要滚，判据没测到"
        bar.setValue(bar.maximum())
        settle()
        rows = [w for w in content.findChildren(QWidget)
                if w.parentWidget() is content and w.isVisible() and w.objectName() != "scrollEndGap"]
        last = max(w.geometry().bottom() for w in rows)
        assert content.height() - 1 - last >= SCROLL_END_GAP, (content.height(), last)

        page.resize(1100, 3000)
        settle()
        assert bar.maximum() == 0, f"放得下时还多出 {bar.maximum()}px 可滚"
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_layout_audit_also_starts_at_the_largest_scale(monkeypatch, capsys):
    """顺序跑时页面按 1.0 建、再换档；用户设 1.25 再启动，页面按 1.25 建。B160 有两处只在单跑 1.25 时出现。"""
    import subprocess
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import layout_overflow_audit as audit

    calls = []

    class _Done:
        stdout = "== 完整模式 ==\nRESULT layout rc=1\n"
        stderr = ""

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["layout_overflow_audit.py", "--compact", "--themes", "dark,light",
                                      "--scales=1.0,1.1,1.25", "--require-fonts"])
    assert audit._start_at_largest_scale((1.0, 1.1, 1.25), ("dark", "light")) == 1, "起步那一遍红了要传上来"
    argv = calls[-1][2:]
    assert argv[argv.index("--scales") + 1] == "1.25" and argv.count("--scales") == 1
    assert argv[argv.index("--themes") + 1] == "dark" and argv.count("--themes") == 1
    assert "--compact" in argv and "--require-fonts" in argv
    out = capsys.readouterr().out
    assert "RESULT" not in out, "子进程的裁定行原样转出，会顶掉本进程的那一行"

    calls.clear()
    assert audit._start_at_largest_scale((1.25,), ("dark",)) == 0 and not calls, "只量一档时不再起一遍"

    import ast
    import inspect

    tree = ast.parse(inspect.getsource(audit.main).lstrip())
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "_start_at_largest_scale" in called, "main() 没接上起步那一遍"
