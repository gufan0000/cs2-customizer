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

# RN-032：配置目录走共享工装。这条对耗时基线尤其要紧 ——
# 个人配置里 37 把武器配着风格，建页要做的活比全新用户多得多，
# 拿它当基线等于把"棘轮"钉在一个别人复现不出的数上。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pristine_config import use_pristine_config_dir  # noqa: E402

_bench_tmp = use_pristine_config_dir("cs2customizer_bench")


# 只测"构造时不起线程/设备/子进程"的页面。那些页构造即起热键/音频设备/子进程,
# 在基准脚本里构造会真的占设备、注册全局热键——那就是"打扰前台"了。
# RN-005/RN-059：**能不能测**这件事由共享中和表说，不再等同于
# `DEVICE_OWNING_PAGES`。这一处是那张表的**第 7 份副本**，
# 后果是建页耗时基线里从来没有 flash / viewmodel / voice_output / music 的数。
# `_audit_neutralize` 与 `core.page_traits` 一样不依赖 Qt，
# 导入它不会把本脚本要测的东西提前捂热。
from _audit_neutralize import (  # noqa: E402
    apply as neutralize_apply,
    block_modal_dialogs,
    blocked_dialogs,
    enable_audit_mode,
    unsafe_pages,
)
from _audit_sandbox import sandbox_external_writes  # noqa: E402

enable_audit_mode()   # 必须在 import 产品页面之前

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
    # RN-061：以下 9 页以前**根本不在这份清单里** —— 于是建页耗时棘轮
    # 长期只盯 18/28 页。前 6 页是设备页，RN-005/RN-059 解除盲区之后才测得了；
    # 后 3 页纯粹是加页的时候漏了，而漏了不报错（判据在
    # tests/test_audit_can_see_every_page.py 里补上了）。
    ("flash", "pages.flash_page", "FlashPage"),
    ("viewmodel", "pages.viewmodel_page", "ViewmodelPage"),
    ("voice_output", "pages.voice_output_page", "VoiceOutputPage"),
    ("music", "pages.music_page", "MusicPage"),
    ("magnifier", "pages.magnifier_page", "MagnifierPage"),
    ("kill_icon", "pages.kill_icon_page", "KillIconPage"),
    ("fun_afterlife", "pages.fun_page", "FunPage"),
    ("audio_import_wizard", "pages.audio_import_wizard_page", "AudioImportWizardPage"),
    ("audio_task_panel", "pages.audio_task_panel_page", "AudioTaskPanelPage"),
]


#: 少数页的构造函数要参数。**口径以 `gui_widget` 里真正的构造点为准**，
#: 别照类签名猜 —— `MagnifierPage(self.config)` 传的是 config 单例本身。
_CTOR_ARGS = {"magnifier": lambda: (__import__("config").config,)}


def _ensure_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    app = app if app is not None else QApplication([])
    # RN-072：必须在构造任何页面之前。`advanced` 页构造期弹模态框，
    # 离屏下不可见但照样阻塞 —— 本脚本整跑因此从来没跑完过。
    block_modal_dialogs()
    return app


def _build_once(module_path: str, class_name: str, page_id: str = ""):
    """构造一个页面并返回耗时(ms)。构造失败返回 None。"""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    t0 = time.perf_counter()
    page = cls(*_CTOR_ARGS.get(page_id, tuple)())
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
    # RN-073：第二层中和以前**只 import 了没调用** —— 表在这个脚本里等于没接上。
    # 判据当时只验了 import，验不出这件事（见 test_audit_can_see_every_page）。
    import config as _config_mod

    neutralize_apply(_config_mod.config, {pid for pid, _, _ in specs})
    # RN-072：本脚本以前**没有沙箱化游戏目录** —— 实测它在动用户真实的
    # `Steam/.../csgo/cfg/`（GSI cfg / cs2customizer.cfg / autoexec.cfg 三个文件）。
    # 成因：`advanced` 页构造期跑「首次运行自动配置」，而隔离配置里
    # `csgo_dir` 永远是空的 ⇒ 探测器扫到真机上的 CS2 安装。
    # ⚠ UP-090 的这套机制早就在了，只是 R9-A 那条判据**只认构造
    # `MainWindow` 的脚本**，而本脚本是动态构造单个页类的 —— 判据的分母
    # 不含出事的那个（同 RN-032 / RN-059 一模一样的病）。
    sandbox_external_writes(verbose=False)
    results = {}
    for page_id, module_path, class_name in specs:
        samples = []
        before = len(blocked_dialogs())
        try:
            if warmup:
                # 第一次含模块 import 与各种一次性初始化,不计入——我们要测的是
                # "构建这堆控件"本身,不是"第一次 import 这个模块"。
                _build_once(module_path, class_name, page_id)
            for _ in range(repeat):
                samples.append(_build_once(module_path, class_name, page_id))
        except Exception as exc:
            results[page_id] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        results[page_id] = {
            "中位ms": round(statistics.median(samples), 1),
            "最小ms": round(min(samples), 1),
            "最大ms": round(max(samples), 1),
            "样本数": len(samples),
        }
        # RN-072：构造期弹框是缺陷，不是噪声 —— 挡下来还要报出来是谁弹的。
        popped = blocked_dialogs()[before:]
        if popped:
            results[page_id]["构造期模态框"] = sorted(set(popped))
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
    # RN-072：这一段是**发现通道**。构造一个页面不该弹任何框——
    # 离屏下它不可见但照样阻塞，整支脚本会挂死在这里。
    popped = {pid: v["构造期模态框"] for pid, v in results.items() if v.get("构造期模态框")}
    if popped:
        lines.append("")
        lines.append(f"⚠ 构造期弹了模态框（已被审计闸门挡下，{len(popped)} 页）：")
        for pid, what in sorted(popped.items()):
            lines.append(f"  - {pid}: {', '.join(what)}")
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
        unsafe = wanted & unsafe_pages()
        if unsafe:
            print(f"拒绝测量 {sorted(unsafe)}：目前没有可用的中和条件，会打扰前台。"
                  f"在 scripts/_audit_neutralize.py 里给出条件后再来。")
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
