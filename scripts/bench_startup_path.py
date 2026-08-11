# -*- coding: utf-8 -*-
"""R8a 度量：show 前关键路径耗时（import + MainWindow 构造 + 首次 show）。

为什么不用 `scripts/live_run.py`：那个会**真的**启动软件——准心覆盖窗上屏、
GSI 占 127.0.0.1:3000、音频设备被初始化、全局热键在这几十秒内生效。
本脚本改用 `WA_DontShowOnScreen`：MainWindow 照常构造、照常布局、照常发出
「主窗相位」埋点，但窗口**永不映射到屏幕**，不打扰前台。

为什么需要它：import 瘦身很容易变成**把成本从 import 挪到调用点**——
pygame 不在导入图里了，但如果 `get_runtime_audio_manager()` 在 show 前的主线程
被调用，用户等待的总时长一点没少。所以必须量"到 show 为止"的总账，
而不只是 `python -X importtime` 的那一段。

用法:
    python scripts/bench_startup_path.py            # 跑 3 轮取中位
    python scripts/bench_startup_path.py --runs 5
    python scripts/bench_startup_path.py --json     # 供 A/B 比对
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 子进程里跑一轮，打印一行 JSON。放子进程是因为 import 计时只有冷模块表才准。
_CHILD = r"""
import json, os, sys, time, tempfile
from pathlib import Path

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
_tmp = Path(tempfile.gettempdir()) / "cs2customizer_startup_bench"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_tmp / "logs"))
sys.path.insert(0, r"__ROOT__")
sys.path.insert(0, os.path.join(r"__ROOT__", "scripts"))

t0 = time.perf_counter()
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtCore import Qt
t_qt = time.perf_counter()

app = QApplication.instance() or QApplication([])
# 原生平台下 MainWindow 会真往托盘塞图标——声明不可用，产品代码有降级分支
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

t1 = time.perf_counter()
import gui_widget
t2 = time.perf_counter()

# UP-090: csgo_dir 是自动探测的，不沙箱化会把用户真实 CS2 目录里的
# cs2customizer.cfg 覆盖成默认配置的内容。见 scripts/_audit_sandbox.py。
# 注意这段是**子进程脚本**（整个 _CHILD 是个字符串），所以父进程的 AST 里
# 看不到这次调用——`tests/test_audit_side_effects_r9a.py` 为此单独解析 _CHILD。
from _audit_sandbox import sandbox_external_writes
sandbox_external_writes(verbose=False)

win = gui_widget.MainWindow(auto_background_preload=False)
win.setAttribute(Qt.WA_DontShowOnScreen, True)
t3 = time.perf_counter()

win.show()
app.processEvents()
t4 = time.perf_counter()

loaded = set(sys.modules)
result = {
    "qt_import_ms": round((t_qt - t0) * 1000, 1),
    "gui_widget_import_ms": round((t2 - t1) * 1000, 1),
    "window_ctor_ms": round((t3 - t2) * 1000, 1),
    "first_show_ms": round((t4 - t3) * 1000, 1),
    "total_to_show_ms": round((t4 - t0) * 1000, 1),
    "heavy_modules": sorted(
        m for m in ("pygame", "numpy", "requests", "pkg_resources", "urllib3")
        if m in loaded
    ),
}
win.close()
win.deleteLater()
app.processEvents()
print("RESULT " + json.dumps(result))
""".replace("__ROOT__", str(ROOT).replace("\\", "\\\\"))


def run_once() -> dict | None:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=str(ROOT), capture_output=True, text=True, errors="replace", timeout=300,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    sys.stderr.write(proc.stdout[-2000:] + "\n" + proc.stderr[-2000:] + "\n")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="show 前关键路径度量")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    samples = [r for r in (run_once() for _ in range(args.runs)) if r]
    if not samples:
        print("!! 全部失败，无数据")
        return 1

    keys = ["qt_import_ms", "gui_widget_import_ms", "window_ctor_ms",
            "first_show_ms", "total_to_show_ms"]
    median = {k: round(statistics.median(s[k] for s in samples), 1) for k in keys}
    heavy = sorted({m for s in samples for m in s["heavy_modules"]})

    if args.json:
        print(json.dumps({"median": median, "runs": samples, "heavy_modules": heavy},
                         ensure_ascii=False, indent=2))
        return 0

    labels = {
        "qt_import_ms": "import PySide6",
        "gui_widget_import_ms": "import gui_widget",
        "window_ctor_ms": "MainWindow 构造",
        "first_show_ms": "首次 show",
        "total_to_show_ms": "合计（到 show 为止）",
    }
    print(f"\n== show 前关键路径 ｜ {len(samples)} 轮中位 ==")
    for k in keys:
        raw = "  ".join(f"{s[k]:>7.1f}" for s in samples)
        print(f"  {labels[k]:<22} {median[k]:>8.1f}ms    [{raw}]")
    # 重模块是否被拖进 show 前——这是"成本有没有只是挪个地方"的判据
    print(f"\n  show 时已加载的重模块: {', '.join(heavy) if heavy else '（无）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
