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
所以判定要减掉这一类：只报"既没撞上限、同一格里又还有空"的。

## ⚠ RN-505（2026-09-05 批 51）：它从上线那天起就是红的

上线时报的 2 条（`kill_icon` / `screen_effects`）**都是假的** ——
它原来拿 `parentWidget().width()` 当可用宽度，而一个标签能不能变宽
**由它所在那一格说了算**。竖排里的标签本来就占满整列，这么量必然全报。
量尺搬到 `_squeeze_room.py`，并有判据钉住（`tests/test_squeeze_audit_measures_the_right_room.py`）。
⭐⭐ **一道长期 rc=1 的门禁，跑的人会开始把红当成常态** —— 那时它再逮到新问题也没人看得出来。
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


def _squeezed_labels(container, page_id: str, hint_cap: int) -> tuple[list[dict], int]:
    """在一个容器（页面或对话框）里找被挤到折行的标签。返回 (命中, 进了判定的标签数)。

    ⭐ RN-672 抽出来的：对话框那一段要跑**一模一样**的判定。
    ⛔ 不许在对话框那边另抄一份 —— 两份判定一定会漂，而漂了不报错
      （这支审计自己就栽过：量错对象，从上线那天起红了 51 批）。

    ⚠ 第二个返回值是**分母**。这支审计的分母是「可见 + `wordWrap` 的 QLabel」，
      一个没有就意味着「0 个」这句话什么都没说 —— 而它和真的全绿长得一模一样
      （UP-071/UP-072 那一族）。所以把数报出来。
    """
    from PySide6.QtWidgets import QLabel

    from _squeeze_room import declared_own_width, owning_layout, room_in_cell

    found = []
    examined = 0
    for lb in container.findChildren(QLabel):
        if not lb.isVisibleTo(container) or not lb.wordWrap():
            continue
        examined += 1
        text = lb.text().strip()
        if not text or lb.width() <= 0:
            continue
        need = lb.fontMetrics().horizontalAdvance(text)
        if need <= lb.width():
            continue
        if lb.width() >= hint_cap - 1:
            continue
        if declared_own_width(lb):
            continue
        spare = room_in_cell(owning_layout(container, lb))
        if need > lb.width() + spare:
            continue                     # 真的放不下 —— 那是排版审计的活
        parent = lb.parentWidget()
        found.append({
            "page": page_id, "name": lb.objectName() or "-",
            "width": lb.width(), "need": need, "spare": spare,
            "parent": parent.width() if parent is not None else 0,
            "text": text[:40],
        })
    return found, examined


def audit(compact: bool, expert: bool, scale: float) -> tuple[list[dict], list[tuple[str, str]]]:
    """返回 (被挤到折行的清单, 建不起来的对话框)。

    ⚠ 第二项是 RN-672 加的，而它必须是**返回值**不是打印：只打印的话
    「这一个没量成」会混在日志里，退出码照样是 0 —— 那正是"静默少测被读成全绿"。
    """
    os.environ.pop("QT_QPA_PLATFORM", None)      # 要真实字体，否则宽度全是假的
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

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
        # 判定整段搬去 `_squeezed_labels`（RN-672：对话框要跑一模一样的那一份）。
        # UP-053 的 hint 限宽豁免、RN-505 的「量它所在那一格」都在那里面。
        hits, _seen = _squeezed_labels(page, pid, hint_cap)
        found += hits

    # —— RN-672：对话框。`dialogs/` 下 8 个 QDialog 此前不在任何审计的遍历里 ——
    # ⚠ 「被挤到折行」在对话框上只会更常见：它们比页面窄得多（最窄 346px），
    #   而一句说明文案该多宽跟容器宽没关系。
    import _audit_dialogs as _dlgs

    dialog_failed = []
    dialog_labels = 0
    for spec, dlg, err in _dlgs.build_all(win, app):
        if dlg is None:
            dialog_failed.append((spec.key, err))
            continue
        try:
            hits, seen = _squeezed_labels(dlg, f"对话框:{spec.key}", hint_cap)
            found += hits
            dialog_labels += seen
        finally:
            dlg.close()
            dlg.deleteLater()
            app.processEvents()
    for key, err in dialog_failed:
        # ⛔ 建不起来要**看得见**：静默少测会被读成"这一个没问题"。
        print(f"  !! 对话框 [{key}] 建不起来，**它没有结论**: {err}")
    have, gone = _dlgs.available_dialogs(), _dlgs.missing_dialogs()
    print(f"  对话框覆盖面: {len(have) - len(dialog_failed)}/{len(have)} 个，"
          f"其中 {dialog_labels} 个会折行的标签进了判定")
    if gone:
        # ⭐ 功能子集里没有的要说出来（开源版裁掉了音乐链路 ⇒ 没有「添加在线音乐」）。
        print(f"     ℹ 本检出里没有 {len(gone)} 个（功能子集，不计失败）: "
              + ", ".join(s.key for s in gone))
    if dialog_labels == 0:
        # ⭐ 分母为 0 时那句「0 个」什么都没说，必须自己喊出来。
        print("  !! 对话框里一个 `wordWrap` 标签都没量到 —— 这一档的『0 个』是空的")

    win.close()
    win.deleteLater()
    app.processEvents()
    return found, dialog_failed


def main() -> int:
    ap = argparse.ArgumentParser(description="被挤到折行的标签审计（RN-121）")
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0)
    _ui_mode.add_expert_argument(ap)
    args = ap.parse_args()

    found, dialog_failed = audit(args.compact, args.expert, args.scale)
    mode = "紧凑" if args.compact else "完整"
    print(f"== {mode}档 · 字号 {args.scale} · 界面 {_ui_mode.describe(args.expert)} ==")
    for f in found:
        print(f"  {f['page']:<22} {f['name']:<14} 宽{f['width']:>4} 需{f['need']:>4} "
              f"同格空着{f['spare']:>5}  {f['text']}")
    print(f"  被挤到折行（空间其实够）：{len(found)} 个")
    # RN-672：对话框建不起来 = 那一个没有结论，照样判红。
    rc = 1 if (found or dialog_failed) else 0
    # ⚠ 退出码走进程级，别只看这行字（门禁退出码被洗过，见 CLAUDE.md）。
    print(f"RESULT squeezed rc={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
