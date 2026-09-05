# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""CS2 Customizer 全量测试驱动（正式工具，2026-06-10 固化；2026-09-04 批 47 加并行）。

为什么逐文件子进程隔离：pygame/Qt 等原生库在同一进程跑满全部测试文件会
原生崩溃（历史已知），逐文件隔离后可稳定全量回归。

用法：
    python build_tools/run_tests.py            # 全量（并行，默认 min(6, cpu//2)）
    python build_tools/run_tests.py config hud # 只跑文件名含关键词的
    python build_tools/run_tests.py --jobs 1   # 串行，与批 47 之前逐字节同行为
退出码：0=全绿，1=有失败（可直接接 CI）。
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent import futures
from pathlib import Path

# 本地 GBK 控制台打印 UTF-8 明细(含 U+FFFD)会 UnicodeEncodeError——输出层统一容错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

#: ⭐ 批 47：**并行不是「同时跑」那么简单，因为 `tests/conftest.py` 把配置目录、
#: 日志目录、游戏沙箱三个东西钉在 `tempfile.gettempdir()` 下的**固定名**上
#: （RN-141 / RN-473：固定路径是为了 `csgo_dir` 与结构指纹可复现）。
#: 几个 pytest 进程同时跑，前两个会互相覆盖。
#:
#: ⚠⚠ **第一版我把整个 TEMP 换掉了（三个目录一起搬），等价验收当场红。**
#: 根因：那个游戏沙箱路径**被 `advanced` 页原样显示在屏幕上**，而结构指纹钉着它
#: —— conftest 第 35 行逐字写着这件事。⇒ **换隔离手段之前，先问这个路径会不会被人看见。**
#:
#: 现在的做法：只传一个后缀 `CS2C_TEST_WORKER=_w{i}`，conftest 把它**只**加在
#: 配置目录和日志目录上；游戏沙箱几路共用，是有意为之。
WORKER_ENV = "CS2C_TEST_WORKER"

#: 调度提示：把已知最慢的排在队首（LPT）。**这只影响快慢，不影响结论**——
#: 名单腐烂（文件改名/删掉）最坏就是退回字母序，不会让任何判据漏跑。
#: 秒数是 2026-09-04 批 46 那次全量实测的。
SLOW_FIRST = [
    "test_master_switch_row.py",                  # 84 s
    "test_master_switch_effect_is_honest.py",     # 49 s
    "test_audit_measures_the_whole_page.py",      # 36 s
    "test_status_chips_do_not_look_clickable.py",  # 32 s
    "test_renovation_baselines.py",               # 23 s
    "test_ui_mode_sampling.py",                   # 20 s
    "test_ui_visual_r1_fixes.py",                 # 18 s
    "test_disabled_buttons_look_disabled.py",     # 11 s
]

#: ⭐⭐⭐ **串行尾巴：拿墙钟当判据的文件不许和别人抢 CPU。**
#:
#: 批 47 首推之后 CI 当场红：`test_search_stays_within_frame_budget` 报
#: 「最慢的查询要 **14.2ms**，一帧都放不下了」（上限 12ms）。
#: 代码一个字没改 —— 变的是**它旁边还跑着另一个 pytest 进程**，
#: 而私有仓的 runner 只有 2 核。
#: ⚠ **本机 16 核跑 6 路都没争出来**，等价验收全绿 ——
#:   ⭐⭐ 「在我的机器上测不出来」不是「不存在」，是「我的机器不够挤」。
#:
#: ⛔ 修法不是把上限从 12ms 抬到 16ms：那是拿判据的灵敏度换我的速度，
#:   而这条判据存在的全部意义就是「别再涨一个量级」。
#: ⇒ 这些文件**排到最后、一个一个跑**，跑它们的时候池子里没有别人。
#:   它们量的是「一台不忙的机器上要多久」，那就得真给它一台不忙的机器。
#:
#: 名单由 `tests/test_gates_run_in_parallel_without_losing_anything.py` 的
#: `test_every_wall_clock_judge_runs_alone` 盯着：**谁新写一条测墙钟的断言，
#: 谁就自动进这个分母**，漏加当场红。
SERIAL_TAIL = [
    # ⚠⚠ RN-525（批 50）：这两个**不是**时钟阈值判据，但同样怕挤 ——
    #   它们拿多份**子进程 UI 快照**互相比，而子进程要和另外 5 路 pytest 抢 CPU。
    #   实测：串行全量 248/248 绿、单跑连过两次，而并行全量里
    #   `hud_color` 同模式复跑差 2 处。⭐ 同 RN-518 的形态，
    #   但那条判据的分母只认「时钟调用 + `<` 断言」，认不出这一类。
    "test_ui_mode_sampling.py",
    "test_renovation_baselines.py",
    "test_search_r14.py",                     # search_stays_within_frame_budget
    "test_utility_display_nonblocking_r11.py",  # 构造不许阻塞 >1s
    "test_idle_watcher.py",                   # seconds_since_input() < 1.0
    "test_jank_monitor.py",                   # before <= _t0 <= after
]


def _default_jobs() -> int:
    """默认并行度。

    ⚠ 下限是 **2** 不是 1：私有仓的 GitHub Windows runner 只有 **2 核**，
    `cpu // 2` 算出来正好是 1 ⇒ CI 上等于没并行（批 47 首推实测：本机 304s，
    CI 仍是 1147s，汇总行连 `| 并行 N` 都没打）。
    ⭐ 而这里超订一点是划算的：241 个文件里 **195 个跑不到 1.5 秒**，
    时间大头是解释器启动与 import，不是 CPU。
    """
    return min(6, max(2, (os.cpu_count() or 2) // 2))


def _parse_args(argv: list[str]) -> tuple[int, list[str]]:
    """抠出 `--jobs N`，其余原样当关键词（保持老的调用方式不变）。"""
    jobs, keywords, i = None, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--jobs":
            i += 1
            if i >= len(argv):
                raise SystemExit("--jobs 后面要跟一个数字")
            jobs = int(argv[i])
        elif a.startswith("--jobs="):
            jobs = int(a.split("=", 1)[1])
        else:
            keywords.append(a.lower())
        i += 1
    if jobs is None:
        jobs = _default_jobs()
    if jobs < 1:
        raise SystemExit("--jobs 至少是 1")
    return jobs, keywords


def _worker_env(slot: int | None) -> dict[str, str] | None:
    """给一个工作槽位配独立的配置/日志目录；`None` 表示原样继承（串行档）。"""
    if slot is None:
        return None
    env = dict(os.environ)
    env[WORKER_ENV] = f"_w{slot}"
    return env


def _order(tests: list[Path]) -> list[Path]:
    rank = {name: i for i, name in enumerate(SLOW_FIRST)}
    return sorted(tests, key=lambda p: (rank.get(p.name, len(SLOW_FIRST)), p.name))


def main() -> int:
    jobs, keywords = _parse_args(sys.argv[1:])
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    if keywords:
        tests = [t for t in tests if any(k in t.name.lower() for k in keywords)]
    if not tests:
        print("没有匹配的测试文件")
        return 1

    t0 = time.time()
    ok = 0
    fails: list[tuple[str, str]] = []
    total_cases = 0
    timed_out: list[str] = []
    print_lock = threading.Lock()

    # jobs==1 时不换 TEMP、不并行 —— 与批 47 之前逐字节同行为。
    slots: queue.Queue[int] | None = None
    if jobs > 1:
        slots = queue.Queue()
        for i in range(jobs):
            slots.put(i)

    def run_one(tf: Path) -> tuple[Path, str, str, int, list[str], list[str]]:
        """跑一个测试文件。返回 (文件, 结局, 摘要, 用例数, 明细尾, stderr 尾)。"""
        slot = slots.get() if slots is not None else None
        try:
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pytest", str(tf), "-q", "--no-header",
                     "-p", "no:cacheprovider"],
                    cwd=str(ROOT), capture_output=True, text=True, timeout=300,
                    env=_worker_env(slot),
                    # 钉死 UTF-8:GitHub runner/非中文区 Windows 默认 cp1252,
                    # 子进程输出含中文会让 reader 线程 UnicodeDecodeError(CI #5 实锤)
                    encoding="utf-8", errors="replace",
                )
            except subprocess.TimeoutExpired:
                # ⚠⚠ 2026-08-27（批 16）：这里原来**不接** `TimeoutExpired` ——
                # 一个跑过 300 秒的判据文件会让整台门禁**当场抛异常退出**，
                # 连「文件 N: OK x / FAIL y」那行汇总都打不出来。
                # ⭐⭐ **一条跑不完的判据，坏的不是它自己，是它把别的判据的结论一起带走了。**
                #   而且现场看到的是一段 subprocess 回溯，读起来像工装坏了，
                #   不像「有个测试太慢」—— 归因方向直接被带偏。
                # ⇒ 超时现在记成**一条红**，剩下的文件照跑完。
                return (tf, "timeout", "超时（>300s）—— 判据本身没跑完，结论未知", 0, [], [])
        finally:
            if slots is not None:
                slots.put(slot)

        out = (r.stdout or "").strip().splitlines()
        summary = next((ln for ln in reversed(out)
                        if re.search(r"passed|failed|error", ln)), "")
        m = re.search(r"(\d+) passed", summary)
        cases = int(m.group(1)) if m else 0
        passed = r.returncode == 0 or (
            "passed" in summary and "failed" not in summary and "error" not in summary
        )
        if passed:
            return (tf, "ok", summary, cases, [], [])
        return (tf, "fail", summary, cases, out[-30:],
                (r.stderr or "").strip().splitlines()[-10:])

    def report(res) -> None:
        """打印一个文件的结局。只在主线程调用；锁是防手改成多线程打印时绞在一起。"""
        nonlocal ok, total_cases
        tf, verdict, summary, cases, tail, err_tail = res
        total_cases += cases
        with print_lock:
            if verdict == "timeout":
                timed_out.append(tf.name)
                fails.append((tf.name, summary))
                print(f"FAIL {tf.name}: 超时（>300s）")
                print("     ! 这条不是「测出问题」，是「没测完」。")
                print("     ! 常见成因：函数级夹具里建了主窗口，参数化用例又有几十条。")
            elif verdict == "ok":
                ok += 1
                print(f"OK   {tf.name}: {summary[:80]}")
            else:
                fails.append((tf.name, summary[:90]))
                print(f"FAIL {tf.name}: {summary[:80]}")
                # 失败时吐出尾部明细,否则 CI 上只见 FAIL 不见原因
                for line in tail:
                    print(f"     | {line}")
                for line in err_tail:
                    print(f"     ! {line}")
            sys.stdout.flush()

    if jobs == 1:
        for tf in tests:
            report(run_one(tf))
    else:
        tail = [t for t in tests if t.name in SERIAL_TAIL]
        parallel = [t for t in tests if t.name not in SERIAL_TAIL]
        # ⭐ 用 as_completed 而不是 pool.map：map 按提交顺序交付，
        # 而队首那个恰恰是最慢的（LPT），会让整整 84 秒一行输出都没有。
        with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            pending = [pool.submit(run_one, tf) for tf in _order(parallel)]
            for fut in futures.as_completed(pending):
                report(fut.result())
        # 池子已经排空（`with` 退出时 join 过了）⇒ 下面这些独占这台机器。
        if tail:
            print(f"--- 串行尾巴（{len(tail)} 个文件量的是墙钟，不许和别人抢 CPU）", flush=True)
            for tf in tail:
                report(run_one(tf))

    print("=" * 70)
    print(f"文件 {len(tests)}: OK {ok} / FAIL {len(fails)} | 用例通过 {total_cases} "
          f"| {time.time()-t0:.0f}s" + (f" | 并行 {jobs}" if jobs > 1 else ""))
    for name, s in sorted(fails):
        print(f"  FAIL {name}: {s}")
    if timed_out:
        print(f"  ⚠ 其中 {len(timed_out)} 个是**超时**（结论未知，不是判为不通过）："
              f"{'、'.join(sorted(timed_out))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
