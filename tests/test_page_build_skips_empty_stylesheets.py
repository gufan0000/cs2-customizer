# SPDX-License-Identifier: GPL-3.0-or-later
"""P3：建页清内联样式时，本来就空的不再 setStyleSheet("")。

setStyleSheet 不会短路，空设一遍也要重算样式；一页五六百个控件，首开中位 117 → 60 ms。
"""
from PySide6.QtWidgets import QWidget

from ui_style_applier import StyleApplier


class _Counting(QWidget):
    calls = []

    def setStyleSheet(self, sheet):
        _Counting.calls.append(self.objectName())
        super().setStyleSheet(sheet)


def _tree():
    _Counting.calls = []
    root = _Counting()
    root.setObjectName("root")
    for name in ("empty1", "empty2", "inline", "kept"):
        child = _Counting(root)
        child.setObjectName(name)
    root.findChild(QWidget, "inline").setStyleSheet("color: red;")
    kept = root.findChild(QWidget, "kept")
    kept.setStyleSheet("color: blue;")
    kept.setProperty(StyleApplier.KEEP_STYLE_PROPERTY, True)
    _Counting.calls = []
    return root


def test_only_widgets_with_an_inline_style_are_touched(qapp):
    root = _tree()
    StyleApplier().clear_all_styles(root, clear_root=True)
    assert _Counting.calls == ["inline"]
    assert root.findChild(QWidget, "inline").styleSheet() == ""
    assert root.findChild(QWidget, "kept").styleSheet() == "color: blue;"


def test_a_root_with_its_own_style_is_still_cleared(qapp):
    root = _tree()
    root.setStyleSheet("background: black;")
    _Counting.calls = []
    StyleApplier().clear_all_styles(root, clear_root=True)
    assert root.styleSheet() == ""
    assert sorted(_Counting.calls) == ["inline", "root"]
    _Counting.calls = []
    StyleApplier().clear_all_styles(root, clear_root=True)
    assert _Counting.calls == []  # 第二遍什么都不用做
