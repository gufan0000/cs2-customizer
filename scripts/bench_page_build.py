#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""离屏建页基准（R2 靶点度量）。

为什么要有它:UP-005 的根因是"单页构建本身要 200-600ms,主线程不可切"。
要优化它就得先知道时间花在哪一页、优化后有没有真的变快——但为此反复启动真实
软件既慢又会打扰前台(准心窗口/全局热键/音频设备/GSI 端口)。

本脚本在 offscreen 平台下**只构造页面控件**,不起热键、不开音频设备、不 spawn
子进程,因此可以随便跑。它测的是 gui_widget._load_page 里最重的那一段。

用法:
    python scripts/bench_page_build.py                 # 测全部安全页,跑 3 轮取中位
    python scripts/bench_page_build.py --repeat 5
    python scripts/bench_page_build.py --only kill_sound,kill_voice
    python scripts/bench_page_build.py --json
    python scripts/bench_page_build.py --save docs/ui-perf/pagebench_R1.json
    python scripts/bench_page_build.py --compare docs/ui-perf/pagebench_R1.json

口径说明:
- 数字**不等于**真实启动时的建页耗时(真实场景还叠加了首次 import、磁盘缓存冷热、
  主题应用、滚轮过滤器安装等)。它的价值在于**同机同条件下的前后对比**。
- 与 ui_perf_probe.py 的"建页耗时排行"互补:那个取自真实运行日志(有真实性但要跑软件),
  这个可离线复现(无真实性但可反复测)。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows 控制台默认 GBK，编码不了 ✅/❌ 之类的符号会直接抛 UnicodeEncodeError。
# 统一改成 UTF-8 输出，编不出来的字符降级为替代符而不是让脚本崩掉。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 必须在 import Qt / config 之前设好:离屏 + 隔离配置与日志目录,
# 绝不碰用户真实数据(R1 的教训:测试曾误删 45 个历史日志)。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile  # noqa: E402

_bench_tmp = Path(tempfile.gettempdir()) / "cs2customizer_bench"
(_bench_tmp / "config").mkdir(parents=True, exist_ok=True)
(_bench_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CS2C_CONFIG_DIR", str(_bench_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_bench_tmp / "logs"))


# 只测"构造时不起线程/设备/子进程"的页面。
# 口径与 gui_widget._preload_skip_pages 对齐:那些页构造即起热键/音频设备/子进程,
# 在基准脚本里构造会真的占设备、注册全局热键——那就是"打扰前台"了。
UNSAFE_PAGES = {"viewmodel", "magnifier", "flash", "voice_output", "kill_icon", "music"}

# (page_id, 模块路径, 类名)。与 gui_widget._load_page 的分支一一对应。
PAGE_SPECS = [
    ("kill_sound", "pages.kill_sound_page", "KillSoundPage"),
    ("kill_voice", "pages.kill_voice_page", "KillVoicePage"),
    ("death_sound", "pages.death_sound_page", "DeathSoundPage"),
    ("gun_sound", "pages.gun_sound_page", "GunSoundPage"),
    ("switch_weapon", "pages.switch_weapon_page", "SwitchWeaponPage"),
    ("reload_sound", "pages.reload_sound_page", "ReloadSoundPage"),
    ("special_sound", "pages.special_sound_page", "SpecialSoundPage"),
    ("crosshair", "pages.crosshair_page", "CrosshairPage"),
    ("utility", "pages.utility_page", "UtilityPage"),
    ("hud_color", "pages.hud_color_page", "HudColorPage"),
    ("screen_effects", "pages.screen_effects_page", "ScreenEffectsPage"),
    ("advanced", "pages.advanced_page", "AdvancedPage"),
    ("about", "pages.about_page", "AboutPage"),
    ("preset_center", "pages.preset_center_page", "PresetCenterPage"),
    ("config_snapshot", "pages.config_snapshot_page", "ConfigSnapshotPage"),
    ("audio_health", "pages.audio_health_page", "AudioHealthPage"),
    ("audio_replay", "pages.audio_replay_page", "AudioReplayPage"),
]


def _ensure_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    return app if app is not None else QApplication([])


def _build_once(module_path: str, class_name: str):
    """构造一个页面并返回耗时(ms)。构造失败返回 None。"""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    t0 = time.perf_counter()
    page = cls()
    cost = (time.perf_counter() - t0) * 1000
    # 立刻销毁,避免累计占用影响后续测量
    try:
        page.deleteLater()
        page.setParent(None)
    except Exception:
        pass
    return cost


def run_bench(specs, repeat: int, warmup: bool = True) -> dict:
    _ensure_app()
    results = {}
    for page_id, module_path, class_name in specs:
        samples = []
        try:
            if warmup:
                # 第一次含模块 import 与各种一次性初始化,不计入——我们要测的是
                # "构建这堆控件"本身,不是"第一次 import 这个模块"。
                _build_once(module_path, class_name)
            for _ in range(repeat):
                samples.append(_build_once(module_path, class_name))
        except Exception as exc:
            results[page_id] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        results[page_id] = {
            "中位ms": round(statistics.median(samples), 1),
            "最小ms": round(min(samples), 1),
            "最大ms": round(max(samples), 1),
            "样本数": len(samples),
        }
    return results


def render(results: dict) -> str:
    ok = {k: v for k, v in results.items() if "中位ms" in v}
    bad = {k: v for k, v in results.items() if "error" in v}
    total = sum(v["中位ms"] for v in ok.values())

    lines = []
    lines.append(f"离屏建页基准（{len(ok)} 页，中位合计 {total:.0f}ms）")
    lines.append("")
    lines.append("| 页面 | 中位 | 最小 | 最大 |")
    lines.append("|---|---|---|---|")
    for pid, v in sorted(ok.items(), key=lambda kv: -kv[1]["中位ms"]):
        lines.append(f"| {pid} | {v['中位ms']}ms | {v['最小ms']}ms | {v['最大ms']}ms |")
    if bad:
        lines.append("")
        lines.append("构造失败：")
        for pid, v in bad.items():
            lines.append(f"  - {pid}: {v['error']}")
    return "\n".join(lines)


def compare(old: dict, new: dict) -> str:
    lines = ["== 与基准比对 =="]
    o_total = sum(v["中位ms"] for v in old.values() if "中位ms" in v)
    n_total = sum(v["中位ms"] for v in new.values() if "中位ms" in v)
    d_total = n_total - o_total
    lines.append(f"  合计: {o_total:.0f}ms → {n_total:.0f}ms ({d_total:+.0f}ms) "
                 f"{'改善 ✅' if d_total < 0 else ('劣化 ❌' if d_total > 0 else '持平')}")
    moved = []
    for pid, v in new.items():
        if "中位ms" not in v:
            continue
        o = old.get(pid, {}).get("中位ms")
        if o is None:
            continue
        d = v["中位ms"] - o
        if abs(d) >= 10:  # 10ms 以下算噪声
            moved.append((d, pid, o, v["中位ms"]))
    if moved:
        lines.append("  逐页变化（>10ms）：")
        for d, pid, o, n in sorted(moved):
            lines.append(f"    {pid}: {o}ms → {n}ms ({d:+.1f}ms) "
                         f"{'改善 ✅' if d < 0 else '劣化 ❌'}")
    else:
        lines.append("  无逐页显著变化（阈值 10ms）")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="CS2 Customizer 离屏建页基准")
    ap.add_argument("--repeat", type=int, default=3, help="每页测量轮数（取中位）")
    ap.add_argument("--only", default="", help="只测这些页，逗号分隔")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", metavar="PATH")
    ap.add_argument("--compare", metavar="PATH")
    ap.add_argument("--with-qss", action="store_true",
                    help="测量前先把当前主题的全局 QSS 挂到 QApplication 上。"
                         "R2 实测:同一页在无 QSS 下 35ms、挂上 42KB QSS 后 215~240ms"
                         "——建页开销由 Qt 样式解析主导。要评估'改 QSS 的代价',"
                         "必须开这一档,默认档测不出来。")
    args = ap.parse_args()

    specs = PAGE_SPECS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        unsafe = wanted & UNSAFE_PAGES
        if unsafe:
            print(f"拒绝测量 {sorted(unsafe)}：这些页构造即起热键/音频设备/子进程，"
                  f"会打扰前台。")
            return 2
        specs = [s for s in PAGE_SPECS if s[0] in wanted]
        if not specs:
            print(f"没有匹配的页面。可选：{', '.join(s[0] for s in PAGE_SPECS)}")
            return 1

    if args.with_qss:
        app = _ensure_app()
        from theme_manager import get_theme_manager
        qss = get_theme_manager().current_theme.generate_stylesheet()
        app.setStyleSheet(qss)
        theme_name = get_theme_manager().current_theme_name
        print(f"已挂载全局 QSS：{len(qss)} 字符（主题 {theme_name}）")
        print()

    results = run_bench(specs, repeat=max(1, args.repeat))

    if args.compare:
        try:
            old = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"读取基准失败: {exc}")
            return 1
        print(compare(old, results))
        print()

    if args.save:
        Path(args.save).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"基准已保存: {args.save}\n")

    print(json.dumps(results, ensure_ascii=False, indent=2) if args.json
          else render(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
