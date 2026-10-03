# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 129：**每一个控件拨一下，看它接没接上** —— 全站控件普查（离屏，不进游戏）。

## 为什么要有它

已有的离屏审计量的都是「长什么样」（排版 / 焦点 / 对比度 / 挤压），
`x3_save_load_roundtrip` 量的是「配置键存得进读得回」—— **中间那一段没人量**：
用户在界面上拨一个开关、换一个下拉、拖一个滑块之后，
① 会不会抛异常（界面上看不出来，只在日志里）；
② 配置里到底变了哪几个键（一个也没变 = 控件没接上，或者是预览类控件，要人看）；
③ 拨回去之后配置能不能回到原样（回不去 = 来回一次就把用户设置改掉了）。

## 怎么做

离屏（`QT_QPA_PLATFORM=offscreen` + `WA_DontShowOnScreen`）、隔离配置、禁止落盘、
沙箱化游戏目录、音频走 SDL dummy、不注册全局热键、模态框一律拦下 —— 与现有审计同一套中和。
在此之上再加一层**系统副作用闸门**：子进程 / 多进程 / 打开网址或文件夹 / 开机自启写注册表 /
提权 / 模拟按键鼠标 / 全屏放大 / 音频流 / 网络连接，一律**只记账不执行**，报在表里。

逐页把**有状态的输入控件**（开关、勾选、单选、下拉、滑块、数值框）各拨一次再拨回，
每一下前后对比配置对象的公开属性。⛔ 不点普通按钮（按钮的副作用太宽，留给清单里的人工 / L2 项）。

用法：
    python scripts/control_census.py                  # 全部页面
    python scripts/control_census.py --pages flash,hud_color
    python scripts/control_census.py --inventory      # 只列控件，不拨
    python scripts/control_census.py --out H:/tmp/census.md

退出码：0 = 没有异常、没有回不去的控件；1 = 有（明细在报告里）。「没接上配置」只报不判红。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _pristine_config import use_pristine_config_dir  # noqa: E402

use_pristine_config_dir("cs2customizer_control_census")
from _audit_neutralize import enable_audit_mode  # noqa: E402

enable_audit_mode()

# ---------------------------------------------------------------- 系统副作用闸门
SIDE_EFFECTS: list[str] = []
_CURRENT = {"where": "启动"}


def _record(what: str):
    SIDE_EFFECTS.append(f"{_CURRENT['where']} → {what}")


def _install_side_effect_gates() -> None:
    import subprocess
    import webbrowser
    import multiprocessing
    import socket

    class _NoPopen:
        def __init__(self, args, *a, **kw):
            _record(f"subprocess.Popen({str(args)[:80]})")
            raise OSError("control_census: 子进程已拦截")

    subprocess.Popen = _NoPopen
    os.startfile = lambda path, *a, **kw: _record(f"os.startfile({str(path)[:80]})")
    webbrowser.open = lambda url, *a, **kw: (_record(f"webbrowser.open({str(url)[:80]})"), True)[1]

    def _no_start(self):
        _record(f"multiprocessing.Process.start({getattr(self, 'name', '?')})")

    multiprocessing.Process.start = _no_start

    _orig_connect = socket.socket.connect

    def _connect(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if str(host) in ("127.0.0.1", "localhost", "::1"):
            return _orig_connect(self, address)
        _record(f"socket.connect({address})")
        raise OSError("control_census: 外网连接已拦截")

    socket.socket.connect = _connect

    try:
        import keyboard

        for name in ("press", "release", "send", "write", "press_and_release"):
            if hasattr(keyboard, name):
                setattr(keyboard, name, lambda *a, _n=name, **kw: _record(f"keyboard.{_n}{a[:2]}"))
    except Exception:
        pass
    try:
        import mouse

        for name in ("press", "release", "click", "double_click", "move", "wheel"):
            if hasattr(mouse, name):
                setattr(mouse, name, lambda *a, _n=name, **kw: _record(f"mouse.{_n}{a[:2]}"))
    except Exception:
        pass
    try:
        import sounddevice

        class _NoStream:
            def __init__(self, *a, **kw):
                _record("sounddevice 开流")
                raise OSError("control_census: 音频流已拦截")

        for name in ("Stream", "InputStream", "OutputStream", "RawStream", "RawInputStream", "RawOutputStream"):
            if hasattr(sounddevice, name):
                setattr(sounddevice, name, _NoStream)
    except Exception:
        pass
    try:
        from core.utils import autostart

        autostart.set_enabled = lambda enabled, *a, **kw: (_record(f"autostart.set_enabled({enabled})"), True)[1]
    except Exception:
        pass
    try:
        from core.utils import elevation

        for name in dir(elevation):
            if name.startswith(("relaunch", "request", "restart", "run_as")):
                setattr(elevation, name, lambda *a, _n=name, **kw: (_record(f"elevation.{_n}"), False)[1])
    except Exception:
        pass
    try:
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl = staticmethod(lambda url: (_record(f"QDesktopServices.openUrl({url.toString()[:80]})"), True)[1])
    except Exception:
        pass


def _gate_magnifier() -> None:
    """放大页 import 之后再拦：它在模块级就把 DLL 函数取进了模块属性。"""
    try:
        import pages.magnifier_page as mp

        if hasattr(mp, "MagSetFullscreenTransform"):
            mp.MagSetFullscreenTransform = lambda *a: (_record(f"MagSetFullscreenTransform{a}"), True)[1]
    except Exception:
        pass


# ---------------------------------------------------------------- 异常与错误日志收集
ERRORS: list[str] = []


class _ErrorLog(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            msg = record.getMessage()
            if "退出时配置写盘" in msg:          # 沙箱掐了落盘，这一句是工装噪声
                return
            ERRORS.append(f"{_CURRENT['where']} → [{record.name}] {msg[:200]}")


def _excepthook(tp, val, tb):
    ERRORS.append(f"{_CURRENT['where']} → 未捕获 {tp.__name__}: {val}  @ "
                  + " | ".join(traceback.format_tb(tb)[-2:]).replace("\n", " ")[:300])


# ---------------------------------------------------------------- 配置快照
def _snapshot(config) -> dict:
    out = {}
    for k, v in vars(config).items():
        if k.startswith("_"):
            continue
        try:
            out[k] = json.loads(json.dumps(v, default=str))
        except Exception:
            out[k] = repr(v)
    return out


def _diff(a: dict, b: dict) -> list[str]:
    keys = set(a) | set(b)
    return sorted(k for k in keys if a.get(k, "<无>") != b.get(k, "<无>"))


# ---------------------------------------------------------------- 控件
def _label_of(w) -> str:
    from PySide6.QtWidgets import QAbstractButton, QComboBox

    text = ""
    if isinstance(w, QAbstractButton):
        text = w.text()
    elif isinstance(w, QComboBox):
        text = w.currentText()
    text = (text or w.accessibleName() or w.toolTip() or "").strip()
    if not text:
        # 开关 / 滑块自己没有字：取同一行里离它最近的那个标签（往上找三层）
        from PySide6.QtWidgets import QLabel

        parent = w.parentWidget()
        for _ in range(3):
            if parent is None:
                break
            labels = [lb.text() for lb in parent.findChildren(QLabel) if lb.text().strip()
                      and "<" not in lb.text()]
            if labels:
                text = labels[0]
                break
            parent = parent.parentWidget()
    text = text or w.objectName() or ""
    return " ".join(str(text).split())[:40] or f"<{type(w).__name__}>"


def _controls(page):
    from PySide6.QtWidgets import (QAbstractSlider, QAbstractSpinBox, QCheckBox, QComboBox,
                                   QRadioButton, QAbstractButton)
    from ui_toggle_switch import ToggleSwitch

    found = []
    for w in page.findChildren(object):
        if not hasattr(w, "isVisibleTo"):
            continue
        try:
            if not w.isVisibleTo(page) or not w.isEnabled():
                continue
        except Exception:
            continue
        if isinstance(w, ToggleSwitch):
            found.append(("toggle", w))
        elif isinstance(w, QRadioButton):
            found.append(("radio", w))
        elif isinstance(w, QCheckBox) or (isinstance(w, QAbstractButton) and w.isCheckable()
                                          and type(w).__name__ not in ("QTabBar",)):
            found.append(("check", w))
        elif isinstance(w, QComboBox) and w.count() > 1 and not w.isEditable():
            found.append(("combo", w))
        elif isinstance(w, QAbstractSlider) and w.maximum() > w.minimum():
            if type(w).__name__ == "QScrollBar":
                continue
            found.append(("slider", w))
        elif isinstance(w, QAbstractSpinBox):
            found.append(("spin", w))
    return found


def _pump(app, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def _flip(kind, w):
    """拨一下，返回能把它拨回去的函数。走用户那条路（点击 / 选中 / 拖动）。"""
    if kind == "toggle":
        w.toggle()
        return lambda: w.toggle()
    if kind == "check":
        w.click()
        return lambda: w.click()
    if kind == "radio":
        group = w.group()
        siblings = group.buttons() if group else [b for b in w.parentWidget().findChildren(type(w))
                                                   if b.parentWidget() is w.parentWidget()]
        before = next((b for b in siblings if b.isChecked()), None)
        if w.isChecked():
            other = next((b for b in siblings if b is not w and b.isEnabled()), None)
            if other is None:
                return None
            other.click()
            return lambda: w.click()
        w.click()
        return (lambda: before.click()) if before is not None else None
    if kind == "combo":
        old = w.currentIndex()
        new = (old + 1) % w.count()
        w.setCurrentIndex(new)
        w.activated.emit(new)

        def back():
            w.setCurrentIndex(old)
            w.activated.emit(old)
        return back
    if kind == "slider":
        old = w.value()
        step = max(w.singleStep(), (w.maximum() - w.minimum()) // 10, 1)
        new = old + step if old + step <= w.maximum() else old - step
        w.setValue(new)
        w.sliderReleased.emit()

        def back():
            w.setValue(old)
            w.sliderReleased.emit()
        return back
    if kind == "spin":
        old = w.value()
        w.stepUp()
        if w.value() == old:
            w.stepDown()
        if hasattr(w, "editingFinished"):
            w.editingFinished.emit()

        def back():
            w.setValue(old)
            if hasattr(w, "editingFinished"):
                w.editingFinished.emit()
        return back
    return None


#: 普查时不拨的控件（拨了会改到普查自己依赖的环境）。每一条写清为什么。
SKIP_LABELS = {
    # 切界面模式会重建导航、把专家页收起来 —— 普查靠 `_ui_mode.goto(force=True)` 进页，不受影响，
    # 但重建过程会把当前页换掉，后面的控件全部失效。单独在清单里人工查。
    "专家模式",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="全站控件普查（离屏）")
    ap.add_argument("--pages", default="")
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--settle", type=float, default=0.35, help="每拨一下等多久（秒）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    _install_side_effect_gates()
    sys.excepthook = _excepthook
    logging.getLogger().addHandler(_ErrorLog())

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
    from _audit_neutralize import NEUTRALIZE, block_modal_dialogs, blocked_dialogs
    from _audit_sandbox import sandbox_external_writes
    from _ui_mode import goto

    block_modal_dialogs()
    import gui_widget
    from config import config

    sandbox_external_writes(verbose=False)
    for values in NEUTRALIZE.values():
        for k, v in values.items():
            setattr(config, k, v)
    _gate_magnifier()

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    _pump(app, 0.5)

    # ⚠ 分母取导航表（`_page_names`），不取 `win.pages` —— 后者是**已经加载过**的页，懒加载下开局只有 basic。
    all_ids = list(dict.fromkeys(["basic", *getattr(win, "_page_names", {}).keys()]))
    page_ids = [p for p in (args.pages.split(",") if args.pages else all_ids) if p]
    rows = []           # (page, kind, label, keys, revert_ok)
    started = time.perf_counter()
    for pid in page_ids:
        _CURRENT["where"] = f"{pid}（进页）"
        try:
            goto(win, pid)
        except Exception as exc:
            ERRORS.append(f"{pid} → 进页失败 {exc!r}")
            continue
        _gate_magnifier()
        _pump(app, 0.4)
        page = win.pages.get(pid)
        if page is None:
            continue
        controls = _controls(page)
        for kind, w in controls:
            label = _label_of(w)
            _CURRENT["where"] = f"{pid} · {label}〔{kind}〕"
            if args.inventory or label in SKIP_LABELS:
                rows.append((pid, kind, label, None, None))
                continue
            try:
                before = _snapshot(config)
                back = _flip(kind, w)
                _pump(app, args.settle)
                mid = _snapshot(config)
                changed = _diff(before, mid)
                ok = None
                if back is not None:
                    back()
                    _pump(app, args.settle)
                    after = _snapshot(config)
                    residue = _diff(before, after)
                    ok = not residue
                    if residue:
                        changed = changed + [f"⚠拨回后仍不同:{','.join(residue[:6])}"]
                rows.append((pid, kind, label, changed, ok))
            except RuntimeError as exc:          # 控件在拨的过程中被页面重建删掉了
                rows.append((pid, kind, label, [f"控件已被重建:{exc}"[:80]], None))
            except Exception as exc:
                ERRORS.append(f"{_CURRENT['where']} → 拨动时异常 {exc!r}")
                rows.append((pid, kind, label, ["异常"], False))

    # ⚠ 不关窗：拨过编辑器的页（hud_color 等「要点保存」的页）会以「有未保存修改」拦下关窗，
    #   而普查只要报告，进程最后直接 `os._exit`（同 RN-194：退出链路的退出码本来就不可信）。
    _CURRENT["where"] = "退出"

    # 闸门连带：子进程被拦下之后，产品照实报「进程起不来」—— 那是工装造成的，不是缺陷。
    gated_wheres = {s.split(" → ", 1)[0] for s in SIDE_EFFECTS}
    induced = [e for e in ERRORS if e.split(" → ", 1)[0] in gated_wheres and "进程" in e]
    for e in induced:
        ERRORS.remove(e)
    total = len(rows)
    flipped = [r for r in rows if r[3] is not None]
    dead = [r for r in flipped if not r[3]]
    stuck = [r for r in flipped if r[4] is False]
    lines = [
        "# 全站控件普查（离屏）",
        "",
        f"页面 {len(page_ids)} 个，控件 {total} 个，拨过 {len(flipped)} 个，用时 {time.perf_counter() - started:.0f}s。",
        f"异常 / 错误日志 **{len(ERRORS)}** 条；拨回去配置回不到原样 **{len(stuck)}** 个；"
        f"拨了配置一个键都没变 {len(dead)} 个（要人看：预览类控件正常，否则是没接上）；"
        f"被拦下的系统副作用 {len(SIDE_EFFECTS)} 次（由此连带的「进程起不来」错误日志 {len(induced)} 条已剔除）；"
        f"被拦下的模态框 {len(blocked_dialogs())} 次。",
        "",
        "## 异常与错误日志",
        "",
        *([f"- {e}" for e in ERRORS] or ["（无）"]),
        "",
        "## 拨回去回不到原样",
        "",
        *([f"- `{r[0]}` · {r[2]}〔{r[1]}〕：{', '.join(r[3])}" for r in stuck] or ["（无）"]),
        "",
        "## 被拦下的系统副作用",
        "",
        *([f"- {s}" for s in SIDE_EFFECTS] or ["（无）"]),
        "",
        "## 被拦下的模态框",
        "",
        *([f"- {d}" for d in blocked_dialogs()] or ["（无）"]),
        "",
        "## 逐控件",
        "",
        "| 页 | 类型 | 控件 | 变了哪些配置键 | 拨回 |",
        "|---|---|---|---|---|",
    ]
    for pid, kind, label, keys, ok in rows:
        shown = "（只列）" if keys is None else (", ".join(keys) if keys else "**无**")
        mark = "" if ok is None else ("✓" if ok else "✗")
        lines.append(f"| {pid} | {kind} | {label.replace('|', '/')} | {shown} | {mark} |")
    report = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8", newline="\n")
        print(f"报告：{args.out}")
    else:
        print(report)
    bad = bool(ERRORS) or bool(stuck)
    print(f"RESULT control_census rc={1 if bad else 0} controls={total} errors={len(ERRORS)} "
          f"stuck={len(stuck)} dead={len(dead)} side_effects={len(SIDE_EFFECTS)}")
    sys.stdout.flush()
    os._exit(1 if bad else 0)


if __name__ == "__main__":
    main()
