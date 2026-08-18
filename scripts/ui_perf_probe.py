#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""UI 性能优化专项 —— 基线探针。

从运行日志里把「启动相位 / 主线程卡顿 / 页面构建 / 退出耗时」四类客观指标捞出来，
输出一段可直接粘进 docs/ui-perf/01_基线与度量.md 的 Markdown 表格。

用法:
    python scripts/ui_perf_probe.py                # 扫描默认日志目录，全量统计
    python scripts/ui_perf_probe.py --last 5       # 只看最近 5 次启动
    python scripts/ui_perf_probe.py --json         # 输出 JSON(供脚本比对回归)
    python scripts/ui_perf_probe.py --baseline docs/ui-perf/baseline.json --compare

存在的意义:每一轮优化前后各跑一次,把数字贴进执行日志。
没有数字的"感觉变流畅了"在本专项里不算验收通过。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys                      # RN-071：下面 stdout.reconfigure 要它，缺了会静默失效
from dataclasses import dataclass, field
from pathlib import Path

# ==================== 日志行匹配规则 ====================
# 口径来源:main_widget.py 的 [启动相位]、gui_widget.py 的 [主窗相位]、
# core/utils/jank_monitor.py 的 [卡顿]、gui_widget.py 退出链路的 [退出步骤]。
RE_TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
RE_BOOT_PHASE = re.compile(r"\[启动相位\]\s*(.+?):\s*\+(\d+)ms\s*\(累计\s*(\d+)ms\)")
RE_WIN_PHASE = re.compile(r"\[主窗相位\]\s*(.+?):\s*\+(\d+)ms")
RE_JANK = re.compile(r"\[卡顿\]\s*主线程停顿\s*(\d+)ms\s*\(启动后\s*([\d.]+)s\)")
RE_PAGE_CREATE = re.compile(r"\[懒加载\]\s*创建页面:\s*(\S+)")
RE_EXIT_SLOW = re.compile(r"退出步骤\[(.+?)\]偏慢:\s*([\d.]+)s")
RE_EXIT_TOTAL = re.compile(r"退出清理完成[,，]?\s*共\s*(\d+)\s*步[,，]?\s*总耗时\s*([\d.]+)s")
RE_SESSION_START = re.compile(r"CS2 Customizer.*?- Widget版")
RE_QSS_LEN = re.compile(r"样式表总长度:\s*(\d+)\s*字符")
RE_THEME_CB = re.compile(r"已注册主题变化回调")
# UP-003 内存采样(core/utils/mem_monitor.py)。改动须同步 tests/test_mem_monitor.py
RE_MEM = re.compile(r"\[内存\]\s*rss=(\d+)MB\s+priv=(\d+)MB\s*\(启动后\s*([\d.]+)s\)")
# UP-002 逐页构建耗时(gui_widget.py:_load_page)。给 R2 定位"哪一页最慢"
RE_PAGE_COST = re.compile(r"\[懒加载\]\s*页面\s*(\S+)\s*加载完成\s*\((\d+)ms\)")
# UP-004 起 logger 每次启动记录本份日志的写入级别（DEBUG 类埋点是否可用的判据）
RE_LOG_LEVEL = re.compile(r"\[日志\]\s*文件日志级别\s*=\s*(\w+)")

# 卡顿分期口径:启动期 = 启动后 15s 内(静默预载队列跑完之前)
STARTUP_WINDOW_S = 15.0
# jank_monitor 的告警阈值,与 core/utils/jank_monitor.py 的 _THRESHOLD_MS 保持一致
JANK_THRESHOLD_MS = 120

# ==================== 度量口径版本 ====================
# 口径变了,跨版本的数字就不能直接比大小。--compare 遇到版本不同会拒绝打
# "改善/劣化"箭头,只并排列数——否则会得出完全相反的结论。
#
# v1 (R0, 2.2.1 及更早):卡顿探测器在 window.show() 之后启动,"启动后 Xs"以探测器
#    构造时刻为起点。主窗构建那 1.9~5.0 秒的停顿测不到。
# v2 (R1, 2.2.2 起,UP-002):探测器提前到 QApplication 之后,以 _BOOT_T0 为起点。
#    因此 v2 每次启动会**多出**一条约 2000ms 的主窗构建停顿——这不是劣化,
#    是原先看不见的那段现在看见了。同时"启动后 Xs"整体左移,启动期/稳态期的
#    15s 分界线含义也随之改变。
METRIC_SCHEMA_VERSION = 2
# 日志里出现这一行 = 该会话由 v2 埋点产生(UP-003 的内存采样与 UP-002 同批上线)
RE_SCHEMA_V2_MARKER = re.compile(r"\[内存\]\s*rss=")


@dataclass
class Session:
    """一次进程生命周期。"""

    log_file: str
    started_at: str = ""
    boot_phases: list = field(default_factory=list)   # [(名称, 增量ms, 累计ms)]
    win_phases: list = field(default_factory=list)    # [(名称, 增量ms)]
    janks: list = field(default_factory=list)         # [(停顿ms, 启动后s)]
    pages_created: list = field(default_factory=list)
    exit_slow_steps: list = field(default_factory=list)  # [(步骤名, 秒)]
    exit_total_s: float = 0.0
    qss_len: int = 0
    theme_cb_count: int = 0
    mem_samples: list = field(default_factory=list)   # [(rssMB, privMB, 启动后s)]
    page_costs: list = field(default_factory=list)    # [(页id, 构建ms)]
    schema_version: int = 1  # 见 METRIC_SCHEMA_VERSION；有内存采样即为 v2
    file_log_level: str = ""  # "DEBUG"/"INFO"/""，决定 DEBUG 类埋点是否可用

    # ---- 派生指标 ----
    @property
    def time_to_visible_ms(self) -> int:
        """进程启动 → 主窗口可见(用户第一眼看到界面)。"""
        for name, _inc, cum in self.boot_phases:
            if "窗口可见" in name:
                return cum
        return 0

    @property
    def time_to_ready_ms(self) -> int:
        """进程启动 → 后台资源全就绪(界面真正不再抖)。"""
        for name, _inc, cum in self.boot_phases:
            if "全就绪" in name:
                return cum
        return 0

    @property
    def startup_janks(self) -> list:
        return [j for j in self.janks if j[1] <= STARTUP_WINDOW_S]

    @property
    def steady_janks(self) -> list:
        return [j for j in self.janks if j[1] > STARTUP_WINDOW_S]

    @property
    def startup_jank_total_ms(self) -> int:
        return sum(j[0] for j in self.startup_janks)


def parse_log(path: Path) -> list:
    """一个日志文件可能含多次启动,按「Widget版」横幅切分成多个 Session。"""
    sessions = []
    cur = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return sessions

    for line in text.splitlines():
        if RE_SESSION_START.search(line):
            cur = Session(log_file=path.name)
            m = RE_TS.match(line)
            if m:
                cur.started_at = m.group(1)
            sessions.append(cur)
            continue
        if cur is None:
            continue

        if m := RE_BOOT_PHASE.search(line):
            cur.boot_phases.append((m.group(1).strip(), int(m.group(2)), int(m.group(3))))
        elif m := RE_WIN_PHASE.search(line):
            cur.win_phases.append((m.group(1).strip(), int(m.group(2))))
        elif m := RE_JANK.search(line):
            cur.janks.append((int(m.group(1)), float(m.group(2))))
        elif m := RE_PAGE_CREATE.search(line):
            cur.pages_created.append(m.group(1))
        elif m := RE_EXIT_SLOW.search(line):
            cur.exit_slow_steps.append((m.group(1), float(m.group(2))))
        elif m := RE_EXIT_TOTAL.search(line):
            cur.exit_total_s = float(m.group(2))
        elif m := RE_QSS_LEN.search(line):
            cur.qss_len = int(m.group(1))
        elif m := RE_MEM.search(line):
            cur.mem_samples.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
            cur.schema_version = 2  # 内存埋点与 UP-002 的卡顿口径同批上线
        elif m := RE_PAGE_COST.search(line):
            cur.page_costs.append((m.group(1), int(m.group(2))))
        elif m := RE_LOG_LEVEL.search(line):
            cur.file_log_level = m.group(1).upper()
        elif RE_THEME_CB.search(line):
            cur.theme_cb_count += 1

    return sessions


# Windows 控制台默认 GBK，编码不了 ✅/❌ 之类的符号会直接抛 UnicodeEncodeError。
# ⚠ RN-071：这一段曾经**整块恒失效** —— 本文件没有 `import sys`，抛的是 NameError，
# 被下面这个 `except Exception: pass` 一口吞掉。29 个用同一写法的脚本里只有它缺。
# 这就是「兜底把自己的失败也兜掉了」：本文件打 ✅×5 / ❌×3 / ⚠×1，
# GBK 控制台上本该必崩，而没人看见过它崩，是因为大家都在 UTF-8 终端里跑。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def default_log_dirs() -> list:
    """默认只扫用户运行时日志目录。

    仓库里的 cfg-cs2customizer/logs/ 躺着 2025 年的历史日志,口径与现在完全不同,
    无条件合并进来会把两个时代的会话混进同一组中位数。要看它们请显式
    `--logs <path>`。
    """
    dirs = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "CS2Customizer" / "logs")
    if not dirs:  # 没有 LOCALAPPDATA 的环境才回退到仓库内 logs/
        dirs.append(Path(__file__).resolve().parent.parent / "logs")
    return [d for d in dirs if d.is_dir()]


def _stat(values, key=lambda v: v):
    """返回 (n, 中位, P90, 最大)。空集合返回全 0。"""
    xs = sorted(key(v) for v in values)
    if not xs:
        return 0, 0, 0, 0
    p90 = xs[min(len(xs) - 1, int(len(xs) * 0.9))]
    return len(xs), statistics.median(xs), p90, xs[-1]


def summarize(sessions: list) -> dict:
    """把多次会话压成一组可比对的基线指标。"""
    valid = [s for s in sessions if s.time_to_visible_ms > 0]
    all_janks = [j for s in sessions for j in s.janks]
    start_janks = [j for s in sessions for j in s.startup_janks]
    steady_janks = [j for s in sessions for j in s.steady_janks]

    n_v, med_v, p90_v, max_v = _stat(valid, key=lambda s: s.time_to_visible_ms)
    ready = [s for s in sessions if s.time_to_ready_ms > 0]
    n_r, med_r, p90_r, max_r = _stat(ready, key=lambda s: s.time_to_ready_ms)
    _, med_j, p90_j, max_j = _stat(all_janks, key=lambda j: j[0])

    # 单次启动平均要经历几次卡顿 —— 这是"启动期能不能用"的核心指标
    jank_per_boot = round(len(start_janks) / len(valid), 1) if valid else 0.0
    jank_ms_per_boot = round(
        sum(j[0] for j in start_janks) / len(valid)
    ) if valid else 0

    exits = [s for s in sessions if s.exit_total_s > 0]
    _, med_e, p90_e, max_e = _stat(exits, key=lambda s: s.exit_total_s)

    # 退出慢步骤按累计耗时排名 —— 直接告诉你关窗口时是谁在卡
    slow_agg = {}
    for s in sessions:
        for name, sec in s.exit_slow_steps:
            slow_agg.setdefault(name, []).append(sec)

    theme_cbs = [s.theme_cb_count for s in sessions if s.theme_cb_count]
    qss = [s.qss_len for s in sessions if s.qss_len]

    # ---- 内存(UP-003)----
    # 三条口径,都是被复核纠正过的:
    # 1. 用 priv(PrivateUsage)算斜率,不用 rss(WorkingSet)。本软件常驻托盘,窗口
    #    hide 后 Windows 会裁剪无可见窗口进程的工作集,rss 会假性下降,能算出
    #    "内存不但没涨还降了"的荒谬结论;priv 不受裁剪影响。
    # 2. 丢弃启动爬坡段。第一个采样点在主窗/页面/GSI/音频/QSS 全部加载之前,
    #    比稳态低一大截;那是一次性台阶不是速率,除以 span_h 会把它放大成
    #    "泄漏"——同样零泄漏的版本,11 分钟会话报出的斜率能比 2 小时会话高 10 倍。
    # 3. 斜率用全部样本做最小二乘回归,不用首尾两点(中间有峰值再回落时首尾法失真)。
    _WARMUP_S = 120.0        # 启动后 120 秒内的采样一律不参与斜率
    _MIN_SPAN_H = 0.5        # 至少跨 30 分钟才谈"增长速率"

    mem_sessions = [s for s in sessions if len(s.mem_samples) >= 2]
    starts, peaks, slopes, spans = [], [], [], []
    for s in mem_sessions:
        starts.append(s.mem_samples[0][1])          # priv 起始
        peaks.append(max(m[1] for m in s.mem_samples))  # priv 峰值
        steady = [m for m in s.mem_samples if m[2] >= _WARMUP_S]
        if len(steady) < 3:
            continue
        span_h = (steady[-1][2] - steady[0][2]) / 3600.0
        if span_h < _MIN_SPAN_H:
            continue
        xs = [m[2] / 3600.0 for m in steady]   # 小时
        ys = [m[1] for m in steady]            # priv MB
        n = len(xs)
        mean_x, mean_y = sum(xs) / n, sum(ys) / n
        denom = sum((x - mean_x) ** 2 for x in xs)
        if denom <= 0:
            continue
        slopes.append(sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom)
        spans.append(span_h)

    # ---- 逐页构建耗时(UP-002):R2 拿它定位"哪一页最该优化" ----
    page_agg = {}
    for s in sessions:
        for pid, ms in s.page_costs:
            page_agg.setdefault(pid, []).append(ms)

    # 会话的口径版本：只要有一个 v2 会话就按 v2 报（混合时另有提示）
    versions = {s.schema_version for s in sessions}
    schema_version = max(versions) if versions else 1
    # 文件日志级别：INFO 级下 DEBUG 类埋点（如主题回调注册）根本不写盘，
    # 相关指标必须显式标注"不可用"，不能静默显示 0 让人误以为问题已解决。
    debug_sessions = sum(1 for s in sessions if s.file_log_level == "DEBUG")

    return {
        "会话数": len(sessions),
        "有效启动数": len(valid),
        "口径版本": schema_version,
        "口径版本混合": len(versions) > 1,
        "DEBUG级会话数": debug_sessions,
        "启动_到窗口可见_ms": {"中位": med_v, "P90": p90_v, "最大": max_v, "样本": n_v},
        "启动_到全就绪_ms": {"中位": med_r, "P90": p90_r, "最大": max_r, "样本": n_r},
        "卡顿_总次数": len(all_janks),
        "卡顿_启动期次数": len(start_janks),
        "卡顿_稳态期次数": len(steady_janks),
        "卡顿_每次启动平均次数": jank_per_boot,
        "卡顿_每次启动累计停顿ms": jank_ms_per_boot,
        "卡顿_单次时长_ms": {"中位": med_j, "P90": p90_j, "最大": max_j},
        "退出_总耗时_s": {"中位": med_e, "P90": p90_e, "最大": max_e, "样本": len(exits)},
        "退出_慢步骤": {
            k: {"次数": len(v), "最大s": max(v), "中位s": round(statistics.median(v), 2)}
            for k, v in sorted(slow_agg.items(), key=lambda kv: -sum(kv[1]))
        },
        "主题回调注册数_单次会话": {
            "中位": statistics.median(theme_cbs) if theme_cbs else 0,
            "最大": max(theme_cbs) if theme_cbs else 0,
        },
        "QSS长度_字符": {"中位": statistics.median(qss) if qss else 0},
        "内存_MB": {
            "样本会话数": len(mem_sessions),
            "口径": "priv(PrivateUsage)，斜率丢弃启动后 120s 内的爬坡段并做最小二乘回归",
            # 无样本时一律写 None，**不要写 0**。
            # 0 会被 --compare 当成真实数值参与计算，把"这次没采到内存样本"
            # 报成"内存峰值 733 → 0，改善 ✅"——凭空捏造的改善比没有数字更糟。
            # 内存埋点每 60s 采一次，跑 50s 的会话必然一个样本都没有。
            "起始_中位": round(statistics.median(starts)) if starts else None,
            "峰值_中位": round(statistics.median(peaks)) if peaks else None,
            "峰值_最大": max(peaks) if peaks else None,
            "增长斜率_MB每小时_中位": round(statistics.median(slopes), 1) if slopes else None,
            "斜率样本数": len(slopes),
            "斜率样本跨度_小时_中位": round(statistics.median(spans), 1) if spans else 0,
        },
        "建页耗时_ms": {
            pid: {
                "次数": len(v),
                "中位": round(statistics.median(v)),
                "最大": max(v),
            }
            for pid, v in sorted(
                page_agg.items(), key=lambda kv: -statistics.median(kv[1])
            )
        },
    }


def render_markdown(summary: dict, sessions: list) -> str:
    L = []
    A = L.append
    A(f"> 样本：{summary['会话数']} 次会话 / {summary['有效启动数']} 次有效启动")
    A("")
    A("| 指标 | 中位 | P90 | 最大 | 判读 |")
    A("|---|---|---|---|---|")
    v = summary["启动_到窗口可见_ms"]
    A(f"| 启动→窗口可见 | {v['中位']:.0f}ms | {v['P90']:.0f}ms | {v['最大']:.0f}ms | 用户第一眼看到界面 |")
    r = summary["启动_到全就绪_ms"]
    A(f"| 启动→全就绪 | {r['中位']:.0f}ms | {r['P90']:.0f}ms | {r['最大']:.0f}ms | 界面真正不再抖 |")
    j = summary["卡顿_单次时长_ms"]
    A(f"| 单次卡顿时长 | {j['中位']:.0f}ms | {j['P90']:.0f}ms | {j['最大']:.0f}ms | 阈值 {JANK_THRESHOLD_MS}ms |")
    e = summary["退出_总耗时_s"]
    A(f"| 退出总耗时 | {e['中位']:.2f}s | {e['P90']:.2f}s | {e['最大']:.2f}s | 关窗到进程消失 |")
    A("")
    A("| 卡顿分布 | 值 |")
    A("|---|---|")
    A(f"| 每次启动平均卡顿次数 | **{summary['卡顿_每次启动平均次数']}** 次 |")
    A(f"| 每次启动累计停顿 | **{summary['卡顿_每次启动累计停顿ms']}**ms |")
    A(f"| 启动期(≤{STARTUP_WINDOW_S:.0f}s)卡顿 | {summary['卡顿_启动期次数']} 次 |")
    A(f"| 稳态期(>{STARTUP_WINDOW_S:.0f}s)卡顿 | {summary['卡顿_稳态期次数']} 次 |")
    total = summary["卡顿_总次数"] or 1
    A(f"| 启动期占比 | {summary['卡顿_启动期次数'] / total * 100:.1f}% |")
    A("")
    if summary["退出_慢步骤"]:
        A("**退出慢步骤排行**（关窗口时是谁在卡）：")
        A("")
        A("| 步骤 | 出现次数 | 中位 | 最大 |")
        A("|---|---|---|---|")
        for k, s in list(summary["退出_慢步骤"].items())[:8]:
            A(f"| {k} | {s['次数']} | {s['中位s']}s | {s['最大s']}s |")
        A("")
    mem = summary["内存_MB"]
    if mem["样本会话数"]:
        A("| 内存 | 值 |")
        A("|---|---|")
        A(f"| 起始（中位） | {mem['起始_中位']}MB |")
        A(f"| 峰值（中位 / 最大） | {mem['峰值_中位']}MB / {mem['峰值_最大']}MB |")
        if mem["斜率样本数"]:
            A(f"| **增长斜率（中位）** | **{mem['增长斜率_MB每小时_中位']} MB/h**"
              f"（{mem['斜率样本数']} 个长会话） |")
        else:
            A("| 增长斜率 | 样本不足（需要 >10 分钟的会话） |")
        A("")
    else:
        A("> 内存指标暂无数据：需要软件在装有 UP-003 埋点的版本上运行至少一次。")
        A("")

    pc = summary["建页耗时_ms"]
    if pc:
        A("**建页耗时排行**（R2 的优化靶点，按中位降序）：")
        A("")
        A("| 页面 | 次数 | 中位 | 最大 |")
        A("|---|---|---|---|")
        for pid, s in list(pc.items())[:12]:
            A(f"| {pid} | {s['次数']} | {s['中位']}ms | {s['最大']}ms |")
        A("")

    tc = summary["主题回调注册数_单次会话"]
    if tc["最大"]:
        A(f"**主题变化回调注册数**：单次会话中位 {tc['中位']:.0f} / 最大 {tc['最大']}"
          f"（注册数持续增长 = 存在未反注册的监听，切主题成本随使用时长线性上升）")
        A("")
    elif summary.get("DEBUG级会话数", 0) == 0:
        # 绝不能静默不打印:R0 唯一测到的回调泄漏证据(最大 12425 次注册)是 DEBUG 级,
        # UP-004 降级后它不再写盘。不说明的话,读到"没有这一节"会误以为泄漏已解决。
        A("> **主题变化回调注册数：指标不可用**（该埋点是 DEBUG 级，而所有样本会话都是"
          " INFO 级日志）。要复现 R0 的回调泄漏证据，需设 `CS2C_DEBUG_LOG=1` 后跑一次。")
        A("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="CS2 Customizer UI 性能基线探针")
    ap.add_argument("--logs", nargs="*", help="日志目录(默认自动探测 %%LOCALAPPDATA%%/CS2Customizer/logs 与 ./logs)")
    ap.add_argument("--last", type=int, default=0, help="只统计最近 N 次会话")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--save", metavar="PATH", help="把 JSON 快照存盘(供下一轮 --compare)")
    ap.add_argument("--compare", metavar="PATH", help="与指定快照比对,输出变化量")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.logs] if args.logs else default_log_dirs()
    if not dirs:
        print("未找到日志目录。请用 --logs 指定。")
        return 1

    files = sorted(
        (f for d in dirs for f in d.glob("cs2customizer_*.log")),
        key=lambda p: p.stat().st_mtime,
    )
    sessions = [s for f in files for s in parse_log(f)]
    if not sessions:
        print(f"在 {[str(d) for d in dirs]} 中没解析到任何会话。")
        return 1
    if args.last:
        sessions = sessions[-args.last:]

    summary = summarize(sessions)

    if args.compare:
        try:
            old = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"读取基线快照失败: {exc}")
            return 1
        print("== 与基线比对 ==")

        old_ver = old.get("口径版本", 1)
        new_ver = summary.get("口径版本", 1)
        cross_schema = old_ver != new_ver
        if cross_schema:
            print(f"  ⚠ 口径版本不同（基线 v{old_ver} → 当前 v{new_ver}），"
                  f"卡顿类指标不可直接比大小，只并排列数、不判改善/劣化。")
            print("    原因：v2 起卡顿探测器提前到 QApplication 之后（UP-002），"
                  "每次启动会多出一条约 2000ms 的主窗构建停顿——")
            print("    那不是劣化，是原先测不到的那段现在测到了。请以 v2 的首个快照为新起点。")
            print()

        def _cmp(label, o, n, unit="", jank_related=False, fmt="{:.0f}"):
            if o is None or n is None:
                return
            delta = n - o
            if jank_related and cross_schema:
                arrow = "（跨口径，不判定）"
            elif delta == 0:
                arrow = "持平"
            else:
                arrow = "改善 ✅" if delta < 0 else "劣化 ❌"
            print(f"  {label}: {fmt.format(o)} → {fmt.format(n)} "
                  f"({delta:+.1f}{unit}) {arrow}")

        # 卡顿类：受 UP-002 口径变更影响
        _cmp("每次启动平均卡顿次数",
             old.get("卡顿_每次启动平均次数"), summary.get("卡顿_每次启动平均次数"),
             " 次", jank_related=True, fmt="{:.1f}")
        _cmp("每次启动累计停顿",
             old.get("卡顿_每次启动累计停顿ms"), summary.get("卡顿_每次启动累计停顿ms"),
             "ms", jank_related=True)
        # 启动/退出/内存类：口径未变，可直接比
        for key, label, unit, fmt in (
            ("启动_到窗口可见_ms", "启动→窗口可见(中位)", "ms", "{:.0f}"),
            ("启动_到全就绪_ms", "启动→全就绪(中位)", "ms", "{:.0f}"),
            ("退出_总耗时_s", "退出总耗时(中位)", "s", "{:.2f}"),
        ):
            _cmp(label, old.get(key, {}).get("中位"), summary.get(key, {}).get("中位"),
                 unit, fmt=fmt)
        for sub, label in (("峰值_中位", "内存峰值(中位)"),
                           ("增长斜率_MB每小时_中位", "内存增长斜率(中位)")):
            o = old.get("内存_MB", {}).get(sub)
            n = summary.get("内存_MB", {}).get(sub)
            unit = "MB" if "峰值" in label else "MB/h"
            # 只有两边都有数才比。原来写的是 `o or 0, n or 0`——
            # 一侧缺数就被当成 0 参与计算，于是"这次没采到内存样本"会被报成
            # "内存峰值 733 → 0，改善 ✅"。凭空捏造的改善比没有数字更糟。
            # 内存埋点每 60s 采一次，跑 50s 的会话必然一个样本都没有。
            if o is not None and n is not None:
                _cmp(label, o, n, unit, fmt="{:.1f}")
            elif o is not None or n is not None:
                have, miss = ("基线", "本次") if o is not None else ("本次", "基线")
                val = o if o is not None else n
                print(f"  {label}: 无法比对（{miss}无数据，{have} {val:.1f}{unit}）"
                      f" —— 内存埋点每 60s 采样一次，会话太短就采不到")

        # 建页耗时：逐页比对，只打印变化超过 30ms 的
        old_pages = old.get("建页耗时_ms", {})
        new_pages = summary.get("建页耗时_ms", {})
        moved = []
        for pid, cur in new_pages.items():
            o = old_pages.get(pid, {}).get("中位")
            if o is None:
                continue
            d = cur["中位"] - o
            if abs(d) >= 30:
                moved.append((d, pid, o, cur["中位"]))
        if moved:
            print("  建页耗时变化（>30ms）：")
            for d, pid, o, n in sorted(moved):
                arrow = "改善 ✅" if d < 0 else "劣化 ❌"
                print(f"    {pid}: {o}ms → {n}ms ({d:+}ms) {arrow}")
        print()

    if args.save:
        Path(args.save).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"快照已保存: {args.save}\n")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(summary, sessions))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
