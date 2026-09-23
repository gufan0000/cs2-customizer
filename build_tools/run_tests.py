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
    # ⚠⚠ RN-608（批 82）：这一条**不是怕抢 CPU，是怕抢同一个目录**。
    #   审计沙箱 `%TEMP%/cs2customizer_audit_game_sandbox` 是一个**固定路径**
    #   （那条判据自己的文档第 20 行逐字写着，当初正是为了「可复现」才选的固定），
    #   而它的做法是「自己造一份 stale 产物 → 调沙箱化 → 断言被清掉」。
    #   6 路并行时另一路的清理会抢先把它造的 stale 清掉，或在它断言前又写一份。
    #   实测：并行全量 1 红 → 单跑 22/22 绿 → 再跑一次并行全量 284/284 绿。
    #   ⭐⭐⭐ **间歇红的门禁比一直红更贵**：一直红会被修，
    #   间歇红会被当成「再跑一次就好了」—— 而下一个**真红**也会被这么对待。
    "test_the_sandbox_does_not_remember_yesterday.py",
    # VOX（2026-09-22 社区报障）：`test_cancelled_playback_stops_within_a_beat...`
    #   量的是「播放被取消后多久收尾」—— 阈值 2 秒，而被测的等待循环本身
    #   就是按墙钟走的。6 路抢 CPU 时这个数说明不了代码好坏。RN-518 同类。
    "test_voice_ptt_release_and_mix_fallback.py",
    # RN-624（批 87）：`test_the_exit_retry_budget_is_bounded_and_it_says_so`
    #   量的是「退出时同步重试有没有超预算」—— 预算只有 3 × (0.2 + 1.0) 秒，
    #   而它跑的是真的 `os.replace` 失败 + `time.sleep`。6 路抢 CPU 时这个阈值会假红。
    "test_a_write_at_exit_is_not_scheduled_into_a_future_that_never_comes.py",
    # ⚠⚠ 批 87：它**原地不动地**在这一批第一次撞上 300s 超时，而单跑只要 77s。
    #   它把 `ci.yml` 里那几道门的命令行原样取出来跑（RN-567），全是子进程 ——
    #   RN-525 那条「拿子进程互相比、要和另外 5 路 pytest 抢 CPU」的同一类。
    #   ⭐⭐⭐ 触发它的不是它自己：**本批新增两个判据文件（288 → 290），
    #   把它推过了那条线。** 一个新判据的成本不只是它自己那几秒。
    # RN-627（批 88）：D4 四层的 import 期效应是**真的起 19 个子进程各 import 两遍**
    #   录出来的（静态扫不行 —— X1 那份的文档写着「名字一样不等于是那件事」）。
    #   单跑 16s，而它和 6 路 pytest 抢的是同一批进程槽 ⇒ RN-525 同类。
    # ⚠⚠ 批 88：它**原地不动地**在这一批第一次红 ——「常驻定时器 3 → 4」。
    #   空载连跑 5 次全是 3（`H:/tmp/b88_x1_timer_variance.py`），并行全量里才出现 4：
    #   它在子进程里建一整个 MainWindow，只给 5 轮 `processEvents` 的窗口数定时器，
    #   机器一忙就多数到一个。⇒ 产品没变，**是这把尺子对 CPU 敏感**（RN-518 一族）。
    #   ⭐⭐⭐ 连续两批同一个形状（上一批是 `..._walks_every_blocking_door` 超时）：
    #   **一个新判据的成本不只是它自己那几秒 —— 它还把别的判据往悬崖边推一格。**
    "test_x1_external_effects_are_frozen.py",
    # ⭐⭐⭐ RN-633（批 91）：这两个**一直**在拿墙钟当判据，只是形状不同 ——
    #   时钟藏在轮询 helper 里（`_wait_until(timeout=12.0)` / `_wait_routed(timeout=3.0)`），
    #   阈值是**参数**而不是 `<` 断言，于是上面那条「谁新写墙钟断言谁自动进分母」的
    #   守卫**看不见它们**。而 `test_a_failed_config_write...` 在批 90/91 的并行全量里
    #   真的连着红，单跑必绿。⇒ 识别器已加宽（`_deadline_wait_test_files`，实测 0 误报）。
    "test_a_failed_config_write_is_retried_not_dropped.py",
    "test_voice_local_monitor_device.py",
    # RN-628（批 89）：D5 四层的 import 期效应要起 **72 个子进程**（36 个模块各两遍），
    #   外加一份真的走一遍 cfg 编译的产物快照。单跑 31s，同 RN-525 一类。
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
    #: 每个文件的墙钟（见 `run_one` 的文档）。dict 赋值在 CPython 下是原子的，
    #: 而且每个键只被它自己那条线程写一次 ⇒ 不需要另配一把锁。
    elapsed: dict[str, float] = {}
    phase_secs: dict[str, float] = {}
    print_lock = threading.Lock()

    # jobs==1 时不换 TEMP、不并行 —— 与批 47 之前逐字节同行为。
    slots: queue.Queue[int] | None = None
    if jobs > 1:
        slots = queue.Queue()
        for i in range(jobs):
            slots.put(i)

    def run_one(tf: Path) -> tuple[Path, str, str, int, list[str], list[str]]:
        """跑一个测试文件。返回 (文件, 结局, 摘要, 用例数, 明细尾, stderr 尾)。

        ⭐⭐⭐ RN-629（批 91）：**这支工装以前只打一个总秒数。**
        于是「全量从 ~500s 涨到 ~2000s」这件事，连续三晚都只能靠猜 ——
        我先归因给「别的桌面程序抢 CPU」，量了空载才发现只有 6%，解释不了 4 倍。
        ⭐ **一个说得通的原因，和一个验过的原因，不是一回事** ——
          而分辨这两者需要的不是更用力地想，是一把量得到「哪里慢」的尺子。
        ⇒ 每个文件的墙钟记在 `elapsed[]` 里，汇总行后面打**最慢的 15 个**
          以及**并行段 / 串行尾巴各自的墙钟**。这只是打印，不改任何结论。
        """
        slot = slots.get() if slots is not None else None
        t_file = time.time()
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
            # ⭐ 记在 `finally` 里而不是两个 return 前面：超时那条也是一次读数，
            #   而「哪个文件吃掉 300 秒」恰恰是最该被记下来的那一个。
            elapsed[tf.name] = time.time() - t_file
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
        t_par = time.time()
        with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            pending = [pool.submit(run_one, tf) for tf in _order(parallel)]
            for fut in futures.as_completed(pending):
                report(fut.result())
        phase_secs["并行段"] = time.time() - t_par
        # 池子已经排空（`with` 退出时 join 过了）⇒ 下面这些独占这台机器。
        if tail:
            t_tail = time.time()
            print(f"--- 串行尾巴（{len(tail)} 个文件量的是墙钟，不许和别人抢 CPU）", flush=True)
            for tf in tail:
                report(run_one(tf))
            phase_secs["串行尾巴"] = time.time() - t_tail

    print("=" * 70)
    print(f"文件 {len(tests)}: OK {ok} / FAIL {len(fails)} | 用例通过 {total_cases} "
          f"| {time.time()-t0:.0f}s" + (f" | 并行 {jobs}" if jobs > 1 else ""))
    for name, s in sorted(fails):
        print(f"  FAIL {name}: {s}")
    if timed_out:
        print(f"  ⚠ 其中 {len(timed_out)} 个是**超时**（结论未知，不是判为不通过）："
              f"{'、'.join(sorted(timed_out))}")

    # ⭐⭐⭐ 时间账（RN-629）。只打印，不参与退出码 —— 它是给人看的尺子，不是门。
    if phase_secs:
        print("--- 分段墙钟：" + "、".join(
            f"{k} {v:.0f}s" for k, v in phase_secs.items()))
        tail_secs = phase_secs.get("串行尾巴", 0.0)
        total = sum(phase_secs.values()) or 1.0
        print(f"    ⚠ 串行尾巴占全场 {tail_secs / total * 100:.0f}%"
              f"（{len(SERIAL_TAIL)} 个文件，**它不随 --jobs 变快**）")
    if elapsed:
        top = sorted(elapsed.items(), key=lambda kv: -kv[1])[:15]
        print(f"--- 最慢的 {len(top)} 个文件（★ = 在串行尾巴里）：")
        for name, sec in top:
            print(f"    {sec:7.1f}s  {'★' if name in SERIAL_TAIL else ' '} {name}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
