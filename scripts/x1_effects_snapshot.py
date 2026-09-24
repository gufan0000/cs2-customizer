# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X1（主窗骨架）的**外部效应快照**：建一个主窗，它对外面做了什么。

## 为什么是「录」而不是「读代码」

静态扫 `gui_widget.py` 得到的是 `get 58 / start 12 / QTimer 4` 这种数 ——
`get` 大半是 `dict.get`、`start` 大半是布局的 —— ⭐ **名字一样不等于是那件事**
（同批 55 量契约面时踩过一次）。
⇒ 改成**跑起来录**：把定时器 / 线程 / 进程 / 网络 / 写盘这几条出口拦住，
记下「谁、什么时候、开了什么」。

## 它守的是什么

总纲 §8 逐字写着「**新增常驻 Timer 一律 B 堆**」——
而在这份快照之前，**没有任何东西数得出主窗到底常驻了几个定时器**。
X1 要动的正是这个容器；动完之后多出一个 30ms 的定时器、多起一个线程，
在测试报告上是看不见的。

用法：`python scripts/x1_effects_snapshot.py [--write]`
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "baselines" / "x1_effects.json"

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def record() -> dict:
    from _pristine_config import use_pristine_config_dir

    # ⭐⭐⭐ RN-632（批 91）：`force=True` 不是可选项 —— 本脚本**只被 pytest 当子进程起**，
    # 于是继承 conftest 那个固定名、**跨文件跨轮次累积**的 `cs2customizer_test_config`。
    # 实测：裸环境录 5/5 都是 3 个常驻定时器，用那个目录录 5/5 都是 4
    # （⚠ 多出来的那个来自该目录里**别的状态文件**，不在 `config.json` 里 ——
    #   真实那份 356 键配置整份喂进去录出来也是 3。我一度写成 `music_show_player`，那是推断不是实测。）
    # ⚠ 而基线当初是在干净配置下冻的 ⇒ **基线和读数取自两种状态**。
    # ⭐⭐ 这条修法逐字写在 `use_pristine_config_dir` 自己的文档里
    # （「那种进程必须无条件钉死……不 force 就等于把 RN-031 的修法整个作废，
    # 而且失效时毫无声响」），而本调用点是 X 系列里唯一漏掉它的。
    use_pristine_config_dir("cs2customizer_x1_effects", force=True)
    os.environ.pop("QT_QPA_PLATFORM", None)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

    import _audit_neutralize as neutral
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()
    from config import config

    neutral.apply(config)

    # ---- 拦住四条出口 ----
    seen: dict[str, list] = {"定时器": [], "线程": [], "进程": [], "写盘": []}

    real_timer_start = QTimer.start
    real_single_shot = QTimer.singleShot

    started_ids: set[int] = set()

    def timer_start(self, *a):
        # ⚠ 批 116：**同一个定时器重启不是新定时器**。窗口构造期间被挪一下，moveEvent 会在
        # 500ms 后重启「玩家 ID 检查」那个 3 秒定时器 —— 挪没挪取决于时序，于是常驻数 3/4 来回跳
        # （实测 4 次里 2 次是 4），而总纲 §8 管的是「常驻了几个」，不是「start 了几次」。
        if id(self) in started_ids:
            return real_timer_start(self, *a)
        started_ids.add(id(self))
        seen["定时器"].append(
            {"间隔ms": (a[0] if a else self.interval()), "单次": bool(self.isSingleShot())})
        return real_timer_start(self, *a)

    def single_shot(msec, *a, **kw):
        seen["定时器"].append({"间隔ms": msec, "单次": True})
        return real_single_shot(msec, *a, **kw)

    QTimer.start = timer_start
    QTimer.singleShot = staticmethod(single_shot)

    real_thread_start = threading.Thread.start

    def thread_start(self):
        target = getattr(self, "_target", None)
        seen["线程"].append({
            "名字": self.name,
            "目标": getattr(target, "__qualname__", str(target))[:60],
            "守护": bool(self.daemon),
        })
        return real_thread_start(self)

    threading.Thread.start = thread_start

    import subprocess

    for attr in ("Popen", "run", "call", "check_output"):
        if hasattr(subprocess, attr):
            orig = getattr(subprocess, attr)

            def make(name, fn):
                def wrapper(*a, **kw):
                    seen["进程"].append({"接口": name, "命令": str(a[0])[:80] if a else ""})
                    return fn(*a, **kw)
                return wrapper
            setattr(subprocess, attr, make(attr, orig))
    if hasattr(os, "startfile"):
        real_startfile = os.startfile

        def startfile(path, *a, **kw):
            seen["进程"].append({"接口": "os.startfile", "命令": str(path)[:80]})
            return real_startfile(path, *a, **kw)
        os.startfile = startfile

    import builtins

    real_open = builtins.open

    def guarded_open(file, mode="r", *a, **kw):
        if any(m in str(mode) for m in ("w", "a", "x", "+")):
            seen["写盘"].append(str(file)[:100])
        return real_open(file, mode, *a, **kw)

    builtins.open = guarded_open

    try:
        import gui_widget

        win = gui_widget.MainWindow(auto_background_preload=False)
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        for _ in range(5):
            app.processEvents()
        win.close()
        app.processEvents()
        # ⚠ 数「还活着的线程」前先给它们一点时间退出——
        #   否则这个数会随机器忙不忙而变，那就不是在量产品，
        #   是在量「机器有多忙」（RN-518 那一族）。
        for t in list(threading.enumerate()):
            if t is not threading.main_thread() and t.is_alive():
                t.join(timeout=2.0)
        alive = [t.name for t in threading.enumerate()
                 if t is not threading.main_thread() and t.is_alive()]
    finally:
        builtins.open = real_open
        QTimer.start = real_timer_start
        QTimer.singleShot = real_single_shot
        threading.Thread.start = real_thread_start

    # 定时器按「间隔 + 单次」归并成种类，别记流水
    kinds: dict[str, int] = {}
    for t in seen["定时器"]:
        key = f"{t['间隔ms']}ms{'·单次' if t['单次'] else '·常驻'}"
        kinds[key] = kinds.get(key, 0) + 1
    repeating = sum(n for k, n in kinds.items() if "常驻" in k)

    return {
        "_说明": "建一个 MainWindow（不预加载页面）时，它对外面做了什么。总纲 §8：新增常驻 Timer 一律 B 堆。",
        "定时器种类": dict(sorted(kinds.items())),
        "常驻定时器个数": repeating,
        "线程": sorted({t["名字"] for t in seen["线程"]}),
        "起线程次数": len(seen["线程"]),
        "还活着的线程": sorted(alive),
        "进程调用": sorted({p["命令"] for p in seen["进程"]}),
        "写盘次数": len(seen["写盘"]),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    data = record()
    print("timers=%d kinds / repeating=%d | threads started=%d alive=%d | procs=%d | writes=%d"
          % (len(data["定时器种类"]), data["常驻定时器个数"], data["起线程次数"],
             len(data["还活着的线程"]), len(data["进程调用"]), data["写盘次数"]))
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print("written", OUT)
