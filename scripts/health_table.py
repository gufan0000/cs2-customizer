# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""体检表 v2：启动 / 内存 / 模块 / 安装包 + 三态空闲 / 进程树 / 逐页首开。

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
    python scripts/health_table.py --check      # 超预算或缺项退出 1
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

from _benchmark_runtime import run_child

ROOT = Path(__file__).resolve().parent.parent
BUDGET_PATH = ROOT / "docs/ui-perf/budget.json"
PAGE_IDS = (
    "basic", "audio_import_wizard", "kill_sound", "kill_voice", "death_sound",
    "gun_sound", "switch_weapon", "reload_sound", "special_sound", "crosshair",
    "kill_icon", "viewmodel", "magnifier", "flash", "hud_color", "screen_effects",
    "music", "voice_output", "fun_afterlife", "account", "utility", "advanced",
    "audio_health", "audio_task_panel", "audio_replay", "config_snapshot",
    "preset_center", "about",
)
STATES = {"shown": "显示（默认页）", "minimized": "最小化", "tray": "隐藏到托盘"}
CPU_SETTLE_SECONDS = 75.0
LEGACY_KEYS = (
    "total_to_show_ms", "rss_after_show_mb", "rss_after_idle_mb",
    "threads_after_idle", "modules_total", "modules_own",
)
PERF_KEYS = tuple(
    f"{state}_{metric}" for state in STATES for metric in (
        "cpu_percent", "ctx_switches_per_s", "tree_rss_mb", "tree_cpu_percent",
    )
) + ("first_page_median_ms", "first_page_max_ms", "reopen_page_median_ms", "reopen_page_max_ms")
PAGE_KEYS = tuple(f"{phase}_{pid}_ms" for phase in ("first", "reopen") for pid in PAGE_IDS)
METRIC_KEYS = LEGACY_KEYS + PERF_KEYS + PAGE_KEYS


def counter_window(snapshot, wait, clock=time.perf_counter):
    """Reject thread turnover (Windows sums live-thread context counters)."""
    reasons = []
    for rejected in range(3):
        before = snapshot(True)
        t0 = clock()
        wait(10.0)
        elapsed = clock() - t0
        after = snapshot(False)
        if (set(before) == set(after) and elapsed >= 10.0
                and all(before[k][3] == after[k][3]
                        and after[k][0] >= before[k][0]
                        and after[k][1] >= before[k][1] for k in before)):
            return before, after, elapsed, rejected
        reasons.append({"seconds": elapsed, "processes_changed": set(before) != set(after),
                        "counters": [(k, before[k][:2], after[k][:2],
                                      sorted(before[k][3] - after[k][3]),
                                      sorted(after[k][3] - before[k][3])) for k in before.keys() & after.keys()]})
    raise RuntimeError(f"no stable 10s process/thread counter window in 3 attempts: {reasons}")


def measure_extended(win, app, proc, started: float, idle: float) -> dict:
    """Only called inside the isolated child; keep Qt out of budget unit tests."""
    import psutil
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from _audit_neutralize import blocked_dialogs

    def wait(seconds):
        loop = QEventLoop()
        timer = QTimer()
        timer.setTimerType(Qt.PreciseTimer)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        deadline = time.perf_counter() + seconds
        while (remaining := deadline - time.perf_counter()) > 0:
            timer.start(math.ceil(remaining * 1000))
            loop.exec()

    def snapshot(starting):
        # CPU boundaries must exclude this process's own process/thread enumeration.
        # In particular, Windows threads() is expensive enough to swamp idle CPU.
        if not starting:
            main_cpu = proc.cpu_times()
            main_ctx = proc.num_ctx_switches()
        values = {}
        for p in [proc, *proc.children(recursive=True)]:
            try:
                with p.oneshot():
                    cpu = p.cpu_times()
                    ctx = p.num_ctx_switches()
                    values[(p.pid, p.create_time())] = (
                        cpu.user + cpu.system, ctx.voluntary + ctx.involuntary,
                        p.memory_info().rss,
                        frozenset(t.id for t in p.threads()),
                    )
            except psutil.NoSuchProcess:
                if p.pid == proc.pid:
                    raise
        if starting:
            main_ctx = proc.num_ctx_switches()
            main_cpu = proc.cpu_times()
        main_key = next(k for k in values if k[0] == proc.pid)
        values[main_key] = (main_cpu.user + main_cpu.system,
                            main_ctx.voluntary + main_ctx.involuntary,
                            *values[main_key][2:])
        return values

    result = {}
    # Preserve RSS-at-idle; allow startup callbacks AND worker-thread retirement to settle.
    win.resize(1280, 800)
    wait(max(0.001, max(CPU_SETTLE_SECONDS, idle) - (time.perf_counter() - started)))
    for state in STATES:
        if state == "shown":
            win.showNormal()
        elif state == "minimized":
            win.showMinimized()
        else:
            win.showNormal()
            win.hide()  # 没有托盘图标时，进托盘那条路径就是存几何 + hide()
        wait(2.0)
        assert win.isMinimized() if state == "minimized" else not win.isMinimized()
        assert win.isVisible() == (state != "tray")
        before, after, elapsed, rejected = counter_window(snapshot, wait)
        main_key = next(k for k in after if k[0] == proc.pid)
        cpu_delta = after[main_key][0] - before[main_key][0]
        ctx_delta = after[main_key][1] - before[main_key][1]
        result.update({
            f"{state}_cpu_percent": round(cpu_delta / elapsed * 100, 3),
            f"{state}_ctx_switches_per_s": round(ctx_delta / elapsed, 3),
            f"{state}_tree_rss_mb": round(sum(v[2] for v in after.values()) / 2**20, 1),
            f"{state}_tree_cpu_percent": round(sum(after[k][0] - before[k][0] for k in after) / elapsed * 100, 3),
            f"{state}_sample_seconds": round(elapsed, 3),
            f"{state}_processes": len(after),
            f"{state}_rejected_windows": rejected,
        })

    win.showNormal()
    app.processEvents()
    if set(win._page_names) != set(PAGE_IDS) or [p for p in PAGE_IDS if win.is_page_loaded(p)] != ["basic"]:
        raise RuntimeError("page set drifted or pages preloaded before first-open measurement")
    for phase in ("first", "reopen"):
        for pid in PAGE_IDS:
            # Always switch away, including basic and the last page of the previous pass.
            other = "about" if pid == "basic" and phase == "reopen" else "basic"
            win.show_page(other, animated=False, force=True)
            app.processEvents()
            t0 = time.perf_counter()
            if not win.ensure_page_loaded(pid):
                raise RuntimeError(f"page not loaded: {pid}")
            win.show_page(pid, animated=False, force=True)
            app.processEvents()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if win.content_stack.currentWidget() is not win.pages[pid]:
                raise RuntimeError(f"page not shown: {pid}")
            result[f"{phase}_{pid}_ms"] = round(elapsed_ms, 1)
        costs = [result[f"{phase}_{pid}_ms"] for pid in PAGE_IDS]
        prefix = "first" if phase == "first" else "reopen"
        result[f"{prefix}_page_median_ms"] = round(statistics.median(costs), 1)
        result[f"{prefix}_page_max_ms"] = max(costs)
    if blocked_dialogs():
        raise RuntimeError(f"modal dialogs during measurement: {blocked_dialogs()}")
    return result

_CHILD = r"""
import json, os, sys, time, tempfile
from pathlib import Path

sys.path.insert(0, r"__ROOT__")
sys.path.insert(0, os.path.join(r"__ROOT__", "scripts"))
from _benchmark_runtime import prepare_environment
prepare_environment()

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
from _audit_neutralize import apply, block_modal_dialogs
import config
apply(config.config)
block_modal_dialogs()
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
from health_table import measure_extended
result.update(measure_extended(win, app, proc, t_show, __IDLE__))
win.close()
win.deleteLater()
app.processEvents()
print("RESULT " + json.dumps(result))
"""


def run_once(idle: float) -> dict | None:
    code = _CHILD.replace("__ROOT__", str(ROOT).replace("\\", "\\\\")).replace("__IDLE__", repr(float(idle)))
    return run_child(code, ROOT, 600)


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


def check_budget(readings: dict, path: Path = BUDGET_PATH) -> list[str]:
    """Fail closed on missing/invalid limits or readings, including schema drift."""
    budget = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(budget, dict) or set(budget) != set(METRIC_KEYS):
        missing = set(METRIC_KEYS) - set(budget) if isinstance(budget, dict) else set(METRIC_KEYS)
        extra = set(budget) - set(METRIC_KEYS) if isinstance(budget, dict) else set()
        raise ValueError(f"budget keys invalid: missing={sorted(missing)}, extra={sorted(extra)}")
    exceeded = []
    for key in METRIC_KEYS:
        value, limit = readings.get(key), budget[key]
        for label, number in (("reading", value), ("budget", limit)):
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                raise ValueError(f"invalid {label}: {key}={number!r}")
        if value > limit:
            exceeded.append(f"{key}: {value} > {limit}")
    return exceeded


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="体检表")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--idle", type=float, default=10.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="超预算退出 1；预算缺项或无效也报错")
    ap.add_argument("--budget", type=Path, default=BUDGET_PATH)
    args = ap.parse_args(argv)
    if args.runs < 1 or not math.isfinite(args.idle) or args.idle <= 0:
        ap.error("--runs 必须 >=1，--idle 必须为有限正数")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    samples = []
    for _ in range(args.runs):
        sample = run_once(args.idle)
        if not sample:
            break
        samples.append(sample)
    if args.runs < 1 or len(samples) != args.runs:
        print(f"!! 样本不完整：{len(samples)}/{args.runs}，不生成性能结论")
        return 1
    keys = list(METRIC_KEYS)
    if any(not set(keys) <= set(s) for s in samples):
        print("!! 读数缺项，不生成性能结论")
        return 1
    median = {k: statistics.median(s[k] for s in samples) for k in keys}
    pkg = package_table()
    exceeded = []
    error = None
    if args.check:
        try:
            exceeded = check_budget(median, args.budget)
        except (OSError, ValueError) as exc:
            error = str(exc)
    status = int(bool(exceeded) or error is not None)
    if args.json:
        result = {"median": median, "runs": samples, "package": pkg}
        if args.check:
            result["check"] = {"exceeded": exceeded, "error": error, "passed": status == 0}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return status
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
    for k in LEGACY_KEYS:
        print(f"| {labels.get(k, k)} | {median[k]} | {', '.join(str(s[k]) for s in samples)} |")
    print("\n⚠ 离屏量：闪光子进程 / 准心覆盖窗没起，内存是主进程下界。")
    print(f"\n1280×800，默认页；启动满至少 {max(CPU_SETTLE_SECONDS, args.idle):g}s，各状态另等 2s，再采样 10s。CPU 100%=一个核。")
    print("上下文切换/秒是主进程的调度计数，不等同于硬件唤醒次数；RSS 单位均为 MiB。")
    print("\n| 状态 | 主进程 CPU % | 上下文切换/s | 进程树 RSS MiB | 进程树 CPU % | 进程数（各轮） | 实际秒（各轮） | 丢弃窗口（各轮） |")
    print("|---|---|---|---|---|---|---|---|")
    for state, label in STATES.items():
        values = [median[f"{state}_{m}"] for m in ("cpu_percent", "ctx_switches_per_s", "tree_rss_mb", "tree_cpu_percent")]
        counts = ", ".join(str(s[f"{state}_processes"]) for s in samples)
        seconds = ", ".join(str(s[f"{state}_sample_seconds"]) for s in samples)
        rejected = ", ".join(str(s[f"{state}_rejected_windows"]) for s in samples)
        print(f"| {label} | " + " | ".join(map(str, values)) + f" | {counts} | {seconds} | {rejected} |")
    print("\n⚠ 进程树=主进程+存活子孙进程的 RSS/CPU 合计；离屏下闪光子进程不起，是下界。")
    print("托盘状态是隐藏窗口（无托盘图标时进托盘只做 hide）；不创建系统托盘图标。进程/线程集合变化或计数倒退则丢弃窗口，最多尝试 3 次。")
    print("\n| 开页（ensure_page_loaded + show_page + processEvents，无切页动画） | 中位 ms | 最大 ms |")
    print("|---|---|---|")
    for phase, label in (("first", "首开"), ("reopen", "再开")):
        print(f"| {label} | {median[f'{phase}_page_median_ms']} | {median[f'{phase}_page_max_ms']} |")
    for phase, label in (("first", "首开"), ("reopen", "再开")):
        slow = [f"{pid}={median[f'{phase}_{pid}_ms']}ms" for pid in PAGE_IDS if median[f"{phase}_{pid}_ms"] > 200]
        print(f"{label} >200ms：" + (", ".join(slow) or "无"))
    print("\nbasic 在启动时已建好，首开栏是导航成本；其构建已计入启动耗时。其余 27 页各冷建一次。")
    print("\n| 页面 | 首开中位 ms | 再开中位 ms |")
    print("|---|---|---|")
    for pid in PAGE_IDS:
        print(f"| {pid} | {median[f'first_{pid}_ms']} | {median[f'reopen_{pid}_ms']} |")
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
    if args.check:
        if error:
            print(f"\n❌ 预算错误：{error}")
        elif exceeded:
            print("\n❌ 超预算：\n" + "\n".join(f"- {row}" for row in exceeded))
        else:
            print("\n✅ 预算检查通过")
    return status


if __name__ == "__main__":
    sys.exit(main())
