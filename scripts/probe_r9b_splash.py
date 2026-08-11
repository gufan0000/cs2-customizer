#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UP-088 最小复现器：`QSplashScreen.show()` 会不会触发首次机会异常 0x8001010d。

**为什么要单独做一个**：整软件启动一次要十几秒，而这个问题要试好几种窗口标志组合。
这里把启动路径剥到只剩「建 QApplication → 建闪屏 → show → processEvents」，
一轮不到两秒，且能把 faulthandler 的输出隔离到临时文件里，不碰用户的
`native_crash.log`。

用法：
    python scripts/probe_r9b_splash.py                 # 跑全部变体各 3 次
    python scripts/probe_r9b_splash.py --variant plain --runs 5

⚠ 会在屏幕上闪一下（闪屏本来就是要显示的）。每次只显示约 0.2s。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 每个变体 = 一组要试的窗口标志/属性。子进程里按名字分发。
VARIANTS = (
    "plain",                  # 现状：QSplashScreen(pixmap, WindowStaysOnTopHint) + show()
    "no_activate",            # + WA_ShowWithoutActivating
    "no_focus",               # + WindowDoesNotAcceptFocus
    "no_activate_no_focus",   # 两者都加
    "tool_window",            # + Qt.Tool（不进任务栏、不参与激活链）
    "plain_widget",           # 换成裸 QWidget 画 pixmap，绕开 QSplashScreen
    "accessibility_off",      # QT_ACCESSIBILITY=0：怀疑是 UIA 桥在首个窗口上初始化 COM
    "two_windows",            # 连开两个窗口：只出一次 ⇒ 是一次性初始化，不是闪屏的错
    "offscreen_first",        # 先开一个 WA_DontShowOnScreen 的窗口，看异常会不会挪过去
)

_CHILD = r'''
import faulthandler, json, os, sys, time
from pathlib import Path

out = Path(sys.argv[1])
variant = sys.argv[2]
img = sys.argv[3]

fp = open(out, "w", encoding="utf-8", buffering=1)
faulthandler.enable(file=fp, all_threads=True)

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

app = QApplication.instance() or QApplication([])
pixmap = QPixmap(img)

if variant == "offscreen_first":
    warmup = QWidget()
    warmup.setAttribute(Qt.WA_DontShowOnScreen, True)
    warmup.show()
    app.processEvents()

if variant in ("plain_widget", "offscreen_first"):
    class _Splash(QWidget):
        def __init__(self, pm):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self._pm = pm
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setFixedSize(pm.size())
        def paintEvent(self, _):
            QPainter(self).drawPixmap(0, 0, self._pm)
    splash = _Splash(pixmap)
    scr = app.primaryScreen().geometry()
    splash.move(scr.center().x() - pixmap.width() // 2,
                scr.center().y() - pixmap.height() // 2)
else:
    flags = Qt.WindowStaysOnTopHint
    if variant == "tool_window":
        flags |= Qt.Tool
    splash = QSplashScreen(pixmap, flags)
    if variant in ("no_activate", "no_activate_no_focus"):
        splash.setAttribute(Qt.WA_ShowWithoutActivating, True)
    if variant in ("no_focus", "no_activate_no_focus"):
        splash.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)

splash.show()
app.processEvents()
time.sleep(0.2)
app.processEvents()

if variant == "two_windows":
    second = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    second.show()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    second.close()

visible = bool(splash.isVisible())
geo = splash.geometry()
splash.close()
app.processEvents()
fp.flush()
print("PROBE " + json.dumps({
    "visible": visible,
    "w": geo.width(), "h": geo.height(),
}))
'''


def _resolve_splash_image() -> str | None:
    for name in ("splash.png", "logo.png", "icon.png"):
        for sub in ("", "assets", "resources", "images"):
            p = ROOT / sub / name if sub else ROOT / name
            if p.exists():
                return str(p)
    return None


def run_variant(variant: str, runs: int, img: str) -> dict:
    hits, shown, sizes = 0, 0, set()
    for _ in range(runs):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tf:
            log = Path(tf.name)
        env = dict(os.environ)
        if variant == "accessibility_off":
            env["QT_ACCESSIBILITY"] = "0"
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, str(log), variant, img],
            cwd=str(ROOT), capture_output=True, text=True, errors="replace",
            timeout=120, env=env,
        )
        text = log.read_text(encoding="utf-8", errors="replace")
        # 数**出现次数**而不是有没有出现：two_windows 变体要靠它区分
        # 「一次性初始化」和「每开一个窗口撞一次」
        hits += text.count("0x8001010d")
        for line in proc.stdout.splitlines():
            if line.startswith("PROBE "):
                d = json.loads(line[6:])
                shown += int(bool(d["visible"]))
                sizes.add((d["w"], d["h"]))
        log.unlink(missing_ok=True)
    return {"variant": variant, "runs": runs, "exceptions": hits,
            "visible": shown, "sizes": sorted(sizes)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    img = _resolve_splash_image()
    if not img:
        print("!! 找不到闪屏图片，无法复现")
        return 2
    print(f"闪屏图片: {img}\n")

    todo = VARIANTS if args.variant == "all" else (args.variant,)
    print(f"{'变体':<24}{'异常/轮次':>12}{'显示成功':>10}  尺寸")
    worst = 0
    for v in todo:
        r = run_variant(v, args.runs, img)
        worst = max(worst, r["exceptions"])
        mark = "❌" if r["exceptions"] else "✅"
        print(f"{v:<24}{r['exceptions']}/{r['runs']:<10}{r['visible']:>10}  {r['sizes']}  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
