# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面结构指纹：给重构当安全网（UP-057）。

抽基类这类重构的危险在于**它不该改变任何用户可见的东西**，而单元测试
只覆盖被断言过的那几个点。这里把页面整棵控件树拍成指纹（类型 / objectName /
文案 / 几何 / 启用态），重构前后逐条比对——凡有差异都必须能解释。

用法:
    python scripts/page_fingerprint.py --save docs/ui-perf/fingerprint_before.json
    python scripts/page_fingerprint.py --compare docs/ui-perf/fingerprint_before.json
退出码: 0=无差异, 1=有差异, 2=环境不可信(无真实字体)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
_tmp = Path(tempfile.gettempdir()) / "cs2customizer_fingerprint"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_tmp / "logs"))
os.environ.pop("QT_QPA_PLATFORM", None)  # 要真实字体,否则文案与几何失真(UP-068)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 默认只拍音效页（本工具最初服务于 UP-057 的音效页重构）。
# R9-C 起支持 `--pages all`：PageHeader 落地要动 26 个页面的页头，
# 那种规模的机械重构只有"整棵控件树逐条比对"才守得住。
SOUND_PAGES = ("kill_sound", "kill_voice", "switch_weapon", "reload_sound",
               "death_sound", "special_sound")
TARGET_PAGES = SOUND_PAGES

# 构造即打扰前台的页面（口径同 layout_overflow_audit.UNSAFE_PAGES）。
# magnifier 能靠配置开关中和，其余的拍不了就明说，不静默略过。
UNSAFE_PAGES = {"viewmodel", "flash", "voice_output", "kill_icon", "music"}
NEUTRALIZABLE = {"magnifier": {"magnifier_enabled": False}}


def _describe(widget, root):
    from PySide6.QtCore import QPoint

    entry = {
        "type": type(widget).__name__,
        "name": widget.objectName(),
        "visible": widget.isVisible(),
        "enabled": widget.isEnabled(),
        "size": [widget.width(), widget.height()],
    }
    try:
        pos = widget.mapTo(root, QPoint(0, 0))
        entry["pos"] = [pos.x(), pos.y()]
    except Exception:
        entry["pos"] = None
    for attr in ("text", "currentText", "title", "value"):
        getter = getattr(widget, attr, None)
        if callable(getter):
            try:
                val = getter()
            except Exception:
                continue
            if isinstance(val, (str, int, float)) and str(val) != "":
                entry[attr] = str(val)[:120]
            break
    return entry


def fingerprint(page, root):
    from PySide6.QtWidgets import QWidget

    items = [_describe(page, root)]
    for child in page.findChildren(QWidget):
        items.append(_describe(child, root))
    # 控件遍历顺序在 Qt 里是稳定的,但为了不被无关的建树顺序波动干扰,
    # 按"位置 + 类型 + 名字 + 文案"排序后比对。
    items.sort(key=lambda e: (
        e.get("pos") or [0, 0], e["type"], e["name"], e.get("text", "")
    ))
    return items


def build(page_spec: str = "sound"):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
    if len(QFontDatabase.families()) == 0:
        print("!! 字体库为空,几何与文案都不可信,拒绝出具指纹")
        raise SystemExit(2)

    from config import config
    # UP-090: 见 `_audit_sandbox` —— csgo_dir 是自动探测的，不沙箱化会写到真实游戏目录
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    config.ui_expert_mode = True
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1200, 800)
    win.resize(1200, 800)
    app.processEvents()

    if page_spec == "all":
        for pid, overrides in NEUTRALIZABLE.items():
            for attr, value in overrides.items():
                setattr(config, attr, value)
        total_pages = len(win._page_names)
        targets = [p for p in win._page_names if p not in UNSAFE_PAGES]
        skipped = sorted(p for p in win._page_names if p in UNSAFE_PAGES)
        # UP-096: 覆盖面每次都报。"21 页指纹一致"读起来像全覆盖，实际是 21/27，
        # 而没覆盖的那几页正是历轮缺陷的藏身处。
        if len(targets) == total_pages:
            print(f"   覆盖面: {len(targets)}/{total_pages} 个页面（全覆盖）")
        else:
            print(f"   覆盖面: {len(targets)}/{total_pages} 个页面，"
                  f"**未覆盖 {total_pages - len(targets)} 个**")
        if skipped:
            print(f"   跳过 {len(skipped)} 个构造即打扰前台的页面: {', '.join(skipped)}")
        if NEUTRALIZABLE:
            print(f"   已中和后纳入: {', '.join(NEUTRALIZABLE)}")
    else:
        targets = list(TARGET_PAGES)

    out = {}
    for pid in targets:
        if pid not in win._page_names:
            continue
        win.show_page(pid, animated=False)
        app.processEvents()
        page = win.pages.get(pid)
        if page is None:
            continue
        out[pid] = fingerprint(page, win)
    return out


def _diff_page(pid: str, old: list, new: list) -> list[str]:
    """按**内容**比对，不按下标。

    原来的比法是 `zip(old, new)` 逐位对：只要控件数变了一个，后面全体错位，
    一次纯结构重构能报出两百多处假差异，真差异反而找不着。
    R9-C 把 26 个页面的页头换成 `PageHeader` 时正是这样——多了一层包裹控件，
    比对结果立刻失去意义。

    改成多重集差集：只报**真正多出来的**和**真正少掉的**条目。
    位置/尺寸变了会同时呈现为一少一多，一样看得见。
    """
    from collections import Counter

    def key(e):
        return json.dumps(e, sort_keys=True, ensure_ascii=False)

    ca, cb = Counter(key(e) for e in old), Counter(key(e) for e in new)
    removed = list((ca - cb).elements())
    added = list((cb - ca).elements())
    if not (removed or added):
        return []

    out = [f"[{pid}] 控件数 {len(old)} → {len(new)}；少 {len(removed)} 条、多 {len(added)} 条"]
    for label, items in (("少", removed), ("多", added)):
        for raw in items[:20]:
            e = json.loads(raw)
            out.append(
                f"    {label} {e.get('type')}#{e.get('name')} @{e.get('pos')} "
                f"{e.get('size')} {(e.get('text') or '')[:28]}"
            )
        if len(items) > 20:
            out.append(f"    ...另有 {len(items) - 20} 条{label}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="页面结构指纹")
    ap.add_argument("--save")
    ap.add_argument("--compare")
    ap.add_argument("--pages", default="sound", choices=("sound", "all"),
                    help="sound=只拍音效页(默认) ｜ all=拍全部安全页面(R9-C 用)")
    args = ap.parse_args()

    data = build(args.pages)
    for pid, items in data.items():
        print(f"  {pid:<16} {len(items):>4} 个控件")

    if args.save:
        Path(args.save).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已保存指纹到 {args.save}")
        return 0

    if args.compare:
        old = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        diffs = []
        for pid in sorted(set(old) | set(data)):
            diffs.extend(_diff_page(pid, old.get(pid, []), data.get(pid, [])))
        print()
        if diffs:
            print(f"== 指纹有 {len(diffs)} 处差异 ==")
            for d in diffs[:60]:
                print("  " + d)
            if len(diffs) > 60:
                print(f"  ...另有 {len(diffs) - 60} 处")
            return 1
        print("== 指纹完全一致 ==")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
