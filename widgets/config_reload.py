# SPDX-License-Identifier: GPL-3.0-or-later
"""把配置投影回控件时，不把控件的量化值再次写回配置。"""
from contextlib import contextmanager

from PySide6.QtCore import QObject, QSignalBlocker


@contextmanager
def block_control_signals(page):
    blockers = [QSignalBlocker(obj) for obj in [page, *page.findChildren(QObject)]]
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
    return True
