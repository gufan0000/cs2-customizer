# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 162：可编辑下拉框里的字不再贴着框底；输入框和同排按钮一样高。

B161 外审两版都报「预设中心 `de_dust2` 下拉框字偏下」（B153 起挂着）。原生实测 1.0 倍字上留 15.2px、下留 2.2px：
统一样式给每个 QLineEdit 设最小高 32，连下拉框里内嵌的那个也撑到 32，塞进 32 高的框里从 y=5 开始，下半截出框。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout, QWidget


@pytest.mark.parametrize("entry", ["apply_unified_styles", "fix_text_display"])
def test_the_box_inside_an_editable_combo_is_not_stretched(qapp, entry):
    """两条路都给 QLineEdit 设过最小高 32（递归的统一样式、逐个控件的修字）。"""
    from ui_style_applier import get_style_applier

    host = QWidget()
    lay = QVBoxLayout(host)
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("de_dust2")
    plain = QLineEdit("分享码")
    lay.addWidget(combo)
    lay.addWidget(plain)
    try:
        apply = getattr(get_style_applier(), entry)
        for widget in ((host,) if entry == "apply_unified_styles" else (combo.lineEdit(), plain)):
            apply(widget)
        assert combo.lineEdit().minimumHeight() < 32, combo.lineEdit().minimumHeight()
        assert plain.minimumHeight() >= 32, "普通输入框的最小高别跟着丢了"
    finally:
        host.deleteLater()


def test_the_inner_box_carries_no_frame_of_its_own():
    """内嵌框再吃一遍全局 QLineEdit 规则：多一层边框和内边距，字又被往下推。"""
    from theme_manager import ThemeManager

    qss = ThemeManager().themes["dark"].generate_stylesheet()
    rule = next(line for line in qss.splitlines() if line.strip().startswith("QComboBox QLineEdit"))
    for part in ("QComboBox QLineEdit:focus", "border: none", "padding: 0px", "min-height: 0px"):
        assert part in rule, (part, rule)


_NATIVE_ROW_PROBE = r'''
import json, os, sys
sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "scripts")]
from _pristine_config import use_pristine_config_dir
use_pristine_config_dir("b162_native_row")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QWidget
app = QApplication([])
from core.utils.app_fonts import load_ui_fonts
from theme_manager import ThemeManager
from ui_design_system import apply_font_scale
load_ui_fonts()
out = {}
for scale in (1.0, 1.1, 1.25):
    apply_font_scale(scale)
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    host.setStyleSheet(ThemeManager().themes["dark"].generate_stylesheet())
    row = QHBoxLayout(host)
    edit, combo, button = QLineEdit("分享码 gjpqy"), QComboBox(), QPushButton("导入")
    combo.addItem("1. 官匹竞技")
    button.setObjectName("secondaryButton")
    for w in (edit, combo, button):
        row.addWidget(w)
    host.show()
    app.processEvents()
    out[str(scale)] = [w.sizeHint().height() for w in (edit, combo, button)]
    host.close()
print(json.dumps(out))
sys.stdout.flush()
os._exit(0)
'''


@pytest.mark.skipif(__import__("os").name != "nt", reason="原生字体度量只在 Windows 上量")
def test_a_line_edit_is_as_tall_as_the_buttons_beside_it(tmp_path):
    """QLineEdit 自带上下各 1px，同样的内边距它比按钮、下拉框高 1px（导入向导、开镜放大：33 对 32、38 对 37）。

    ⚠ 在原生平台量：offscreen 是另一套字体库，下拉框和输入框的高在那边差 1px，量不出用户看到的。
    """
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    probe = tmp_path / "native_row_probe.py"
    probe.write_text(_NATIVE_ROW_PROBE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    root = str(Path(__file__).resolve().parents[1])
    out = subprocess.run([sys.executable, str(probe), root], capture_output=True, text=True,
                         timeout=120, env=env, check=True, encoding="utf-8", errors="replace")
    data = json.loads(out.stdout.strip().splitlines()[-1])
    # ⚠ 1.1 倍还差 1px：按钮是 500 字重（Medium 文件），行高和输入框的 Regular 在 16px / 19px 下差 1，
    #   样式表里算不出来；1.0 和 1.25 两档对齐，1.1 记候选（档案 B162）。下拉框在页面里由排钉高，不在这里比。
    for scale, (edit, _combo, button) in data.items():
        slack = 1 if scale == "1.1" else 0
        assert 0 <= edit - button <= slack, f"x{scale}：输入框 {edit}、按钮 {button}"
