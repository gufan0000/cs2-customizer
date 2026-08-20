# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""被**挤**到折行的标签审计（RN-121）。

## 它查的不是"空间不够"

排版审计（`layout_overflow_audit.py`）查的是溢出与截断 —— 那是"放不下"。
这一支查的是另一件事：**放得下，却还是折了行**。

    crosshair 标题行的提示：拿到 120px、需要 156px，而同一行空着 928px
      ⇒ 断在「统 / 一」中间，外审改前 1 发、改版后 3 发（版面变了它更显眼）

机制：**折行的 `QLabel` 在横排布局里会把自己的宽度报小**，布局就照那个窄宽给它。
⭐ **折行往往不是"空间不够"的结果，是"我说我能折行"的结果。**
所以它躲得过一切"有没有溢出/有没有截断"的判据 —— 那些判据眼里它一切正常。

## 不算数的那一类

`QLabel#hintLabel` 有 `max-width: {hint_max_width}px`（UP-053，实测 2200px 窗口下
单行提示会拉到 1936px，远超舒适行长）。**撞到那个上限而折行是设计意图**，不是缺陷。
所以判定要减掉这一类：只报"既没撞上限、父容器又还有空"的。
"""
from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ui_mode  # noqa: E402
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_squeezed_audit")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FULL_SIZE = (1280, 800)
COMPACT_SIZE = (860, 640)


def audit(compact: bool, expert: bool, scale: float) -> list[dict]:
    os.environ.pop("QT_QPA_PLATFORM", None)      # 要真实字体，否则宽度全是假的
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QLabel, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
    if len(QFontDatabase.families()) == 0:
        print("!! 字体库为空 —— 文字宽度全是假的，拒绝出结论")
        raise SystemExit(2)

    from _audit_neutralize import apply as neutralize_apply
    from _audit_neutralize import unsafe_pages
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()
    from config import config
    from ui_design_system import apply_font_scale, get_design_system

    _ui_mode.apply(config, expert)
    config.compact_mode = bool(compact)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    w, h = COMPACT_SIZE if compact else FULL_SIZE
    win.setMinimumSize(w, h)
    win.resize(w, h)
    apply_font_scale(scale)
    app.processEvents()

    hint_cap = get_design_system().container.hint_max_width
    pages = [p for p in win._page_names if p not in unsafe_pages()]
    neutralize_apply(config, pages)

    found = []
    for pid in pages:
        _ui_mode.goto(win, pid)
        for _ in range(3):
            app.processEvents()
        page = win.pages.get(pid)
        if page is None:
            continue
        for lb in page.findChildren(QLabel):
            if not lb.isVisibleTo(page) or not lb.wordWrap():
                continue
            text = lb.text().strip()
            if not text or lb.width() <= 0:
                continue
            need = lb.fontMetrics().horizontalAdvance(text)
            if need <= lb.width():
                continue
            # UP-053：撞到 hintLabel 的限宽而折行是设计意图，不算缺陷。
            if lb.width() >= hint_cap - 1:
                continue
            parent = lb.parentWidget()
            spare = (parent.width() - lb.width()) if parent is not None else 0
            if need > lb.width() + spare:
                continue                     # 真的放不下 —— 那是排版审计的活
            found.append({
                "page": pid, "name": lb.objectName() or "-",
                "width": lb.width(), "need": need,
                "parent": parent.width() if parent is not None else 0,
                "text": text[:40],
            })
    win.close()
    win.deleteLater()
    app.processEvents()
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="被挤到折行的标签审计（RN-121）")
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0)
    _ui_mode.add_expert_argument(ap)
    args = ap.parse_args()

    found = audit(args.compact, args.expert, args.scale)
    mode = "紧凑" if args.compact else "完整"
    print(f"== {mode}档 · 字号 {args.scale} · 界面 {_ui_mode.describe(args.expert)} ==")
    for f in found:
        print(f"  {f['page']:<18} {f['name']:<14} 宽{f['width']:>4} 需{f['need']:>4} "
              f"父宽{f['parent']:>5}  {f['text']}")
    print(f"  被挤到折行（空间其实够）：{len(found)} 个")
    # ⚠ 退出码走进程级，别只看这行字（门禁退出码被洗过，见 CLAUDE.md）。
    print(f"RESULT squeezed rc={1 if found else 0}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
