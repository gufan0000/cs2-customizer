# SPDX-License-Identifier: GPL-3.0-or-later
"""把配置投影回控件时，不把控件的量化值再次写回配置。"""
from contextlib import contextmanager

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSlider, QAbstractSpinBox, QButtonGroup, QComboBox, QLineEdit,
)

_INPUT_TYPES = (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QButtonGroup, QComboBox, QLineEdit)


@contextmanager
def block_control_signals(page):
    # 只挡输入控件：下拉框的模型、页签栏到页面栈这些 Qt 内部连接挡了，控件自身状态就错了。
    controls = [obj for obj in page.findChildren(QObject)
                if isinstance(obj, _INPUT_TYPES) and not obj.objectName().startswith("qt_")]
    blockers = [QSignalBlocker(obj) for obj in [page, *controls]]
    try:
        yield
    finally:
        for blocker in reversed(blockers):
            blocker.unblock()


def reload_page_settings(page):
    loader = getattr(page, "load_settings", None) or getattr(page, "_load_settings", None)
    if not callable(loader):
        return False
    with block_control_signals(page):
        loader()
    # 信号挡住时回调不跑，标签和运行中的对象由页面在这里补同步（不写配置）。
    after = getattr(page, "sync_after_config_reload", None)
    if callable(after):
        after()
    return True
