# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 127：体检表 —— 启动耗时 / 启动后内存 / 启动期模块数 / 安装包构成，一条命令出一张表。

为什么要有它：「大优化」优没优化，要拿数说；而这几个数自批 92 之后就没人量过。
⛔ 只在发版前或优化批前后跑，不进日常门禁（量墙钟的东西放进并行全量会被 CPU 争用带偏，RN-518）。

做法：
- 启动：沿用 `bench_startup_path.py` 的子进程（离屏 `WA_DontShowOnScreen`、沙箱化外部写入），
  多量三样：show 之后的 RSS、空闲 N 秒后的 RSS、`sys.modules` 个数（总数 / 本仓自己的）。
  ⚠ 离屏下闪光子进程、准心覆盖窗不会起 ⇒ 内存是**主进程下界**，表里写明。
- 安装包：读最近一次 `.build/release-*/dist` 的产物，按顶层目录 / 大文件排前 N。

用法：
    python scripts/health_table.py               # 3 轮取中位 + 安装包
    python scripts/health_table.py --idle 20     # 空闲多少秒后再量一次内存
    python scripts/health_table.py --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CHILD = r"""
import json, os, sys, time, tempfile
from pathlib import Path

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
_tmp = Path(tempfile.gettempdir()) / "cs2customizer_health_table"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_tmp / "logs"))
sys.path.insert(0, r"__ROOT__")
sys.path.insert(0, os.path.join(r"__ROOT__", "scripts"))

import psutil
proc = psutil.Process()
t0 = time.perf_counter()
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtCore import Qt, QTimer, QEventLoop
app = QApplication.instance() or QApplication([])
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
import gui_widget
from _audit_sandbox import sandbox_external_writes
sandbox_external_writes(verbose=False)
win = gui_widget.MainWindow(auto_background_preload=False)
win.setAttribute(Qt.WA_DontShowOnScreen, True)
win.show()
app.processEvents()
t_show = time.perf_counter()
rss_show = proc.memory_info().rss
mods = list(sys.modules)
root = os.path.normcase(os.path.normpath(r"__ROOT__"))
own = 0
for name in mods:
    f = getattr(sys.modules.get(name), "__file__", None) or ""
    if f and os.path.normcase(os.path.normpath(f)).startswith(root) and "site-packages" not in f.lower():
        own += 1
loop = QEventLoop()
QTimer.singleShot(int(__IDLE__ * 1000), loop.quit)
loop.exec()
rss_idle = proc.memory_info().rss
threads = proc.num_threads()
result = {
    "total_to_show_ms": round((t_show - t0) * 1000, 1),
    "rss_after_show_mb": round(rss_show / 2**20, 1),
    "rss_after_idle_mb": round(rss_idle / 2**20, 1),
    "threads_after_idle": threads,
    "modules_total": len(mods),
    "modules_own": own,
}
win.close()
win.deleteLater()
app.processEvents()
print("RESULT " + json.dumps(result))
"""


def run_once(idle: float) -> dict | None:
    code = _CHILD.replace("__ROOT__", str(ROOT).replace("\\", "\\\\")).replace("__IDLE__", repr(float(idle)))
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
                          text=True, errors="replace", timeout=600)
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    sys.stderr.write(proc.stdout[-2000:] + "\n" + proc.stderr[-2000:] + "\n")
    return None


def _dir_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def package_table(top: int = 15) -> dict | None:
    builds = sorted((ROOT / ".build").glob("release-*/dist"))
    if not builds:
        return None
    dist = builds[-1]
    apps = [d for d in dist.iterdir() if d.is_dir()]
    base = apps[0] if len(apps) == 1 else dist
    entries = []
    for child in base.iterdir():
        entries.append((child.name, _dir_size(child)))
    internal = base / "_internal"
    if internal.is_dir():
        entries = [e for e in entries if e[0] != "_internal"]
        entries += [("_internal/" + c.name, _dir_size(c)) for c in internal.iterdir()]
    entries.sort(key=lambda e: -e[1])
    # 安装包本体：同一次构建目录下名字里带 setup 的 exe（找不到就空着，不猜）
    setups = sorted((p for p in dist.parent.rglob("*.exe") if "setup" in p.name.lower()),
                    key=lambda p: p.stat().st_mtime)
    total = sum(s for _, s in entries)
    return {
        "dist": str(base.relative_to(ROOT)),
        "installer_mb": round(setups[-1].stat().st_size / 2**20, 1) if setups else None,
        "total_mb": round(total / 2**20, 1),
        "top": [(n, round(s / 2**20, 2)) for n, s in entries[:top]],
        "files": sum(1 for f in base.rglob("*") if f.is_file()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="体检表")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--idle", type=float, default=10.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    samples = [r for r in (run_once(args.idle) for _ in range(args.runs)) if r]
    if not samples:
        print("!! 启动全部失败，无数据")
        return 1
    keys = list(samples[0].keys())
    median = {k: statistics.median(s[k] for s in samples) for k in keys}
    pkg = package_table()
    if args.json:
        print(json.dumps({"median": median, "runs": samples, "package": pkg}, ensure_ascii=False, indent=2))
        return 0
    labels = {
        "total_to_show_ms": "启动到主窗 show（ms）",
        "rss_after_show_mb": "show 后主进程内存（MB）",
        "rss_after_idle_mb": f"空闲 {args.idle:g}s 后主进程内存（MB）",
        "threads_after_idle": "空闲后线程数",
        "modules_total": "启动期模块数（全部）",
        "modules_own": "启动期模块数（本仓）",
    }
    print(f"| 项 | 中位（{len(samples)} 轮） | 各轮 |")
    print("|---|---|---|")
    for k in keys:
        print(f"| {labels.get(k, k)} | {median[k]} | {', '.join(str(s[k]) for s in samples)} |")
    print("\n⚠ 离屏量：闪光子进程 / 准心覆盖窗没起，内存是主进程下界。")
    if pkg:
        setup = f"安装包 {pkg['installer_mb']} MB；" if pkg.get("installer_mb") else "（这次构建目录里没找到安装包）；"
        print(f"\n{setup}安装目录 `{pkg['dist']}`：合计 {pkg['total_mb']} MB，{pkg['files']} 个文件。"
              f"最大的 {len(pkg['top'])} 项：\n")
        print("| 项 | MB |")
        print("|---|---|")
        for name, mb in pkg["top"]:
            print(f"| {name} | {mb} |")
    else:
        print("\n（没有找到 .build/release-*/dist，安装包一栏空着）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
