# SPDX-License-Identifier: GPL-3.0-or-later
"""随包界面字体（批 145）。

族名是私有的，不和用户电脑上装的字体串。文件缺了不报错：样式表里排在后面的雅黑接手。
要在第一次取样式表之前加载，否则已经 polish 过的控件不会换字体。
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFontDatabase

UI_FONT_FAMILY = "Sail Sans SC"
#: 一行字的高度 / 字号，= `build_tools/make_ui_fonts.py` 里 (ASCENT + DESCENT) / 1000
UI_FONT_LINE_EM = 1.36
_FILES = ("SailSansSC-Regular.ttf", "SailSansSC-Medium.ttf", "SailSansSC-Bold.ttf")
_loaded = False


def load_ui_fonts() -> bool:
    """幂等。QApplication 还没建时什么都不做，下一次再试。"""
    global _loaded
    if _loaded:
        return True
    if QCoreApplication.instance() is None:
        return False
    from resource_manager import ResourceManager  # 它 import 时会初始化配置，这个文件只是被取一下族名的时候不该带上

    results = [
        QFontDatabase.addApplicationFont(ResourceManager.get_exe_resource_path(f"fonts/{name}"))
        for name in _FILES
    ]
    _loaded = all(font_id >= 0 for font_id in results)
    return _loaded
