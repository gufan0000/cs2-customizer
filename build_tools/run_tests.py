# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""CS2 Customizer 全量测试驱动（正式工具，2026-06-10 固化）。

为什么逐文件子进程隔离：pygame/Qt 等原生库在同一进程跑满全部测试文件会
原生崩溃（历史已知），逐文件隔离后可稳定全量回归（典型 ~45 秒）。

用法：
    python build_tools/run_tests.py            # 全量
    python build_tools/run_tests.py config hud # 只跑文件名含关键词的
退出码：0=全绿，1=有失败（可直接接 CI）。
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

# 本地 GBK 控制台打印 UTF-8 明细(含 U+FFFD)会 UnicodeEncodeError——输出层统一容错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    keywords = [k.lower() for k in sys.argv[1:]]
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
    for tf in tests:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", str(tf), "-q", "--no-header", "-p", "no:cacheprovider"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=300,
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
            timed_out.append(tf.name)
            fails.append((tf.name, "超时（>300s）—— 判据本身没跑完，结论未知"))
            print(f"FAIL {tf.name}: 超时（>300s）")
            print("     ! 这条不是「测出问题」，是「没测完」。")
            print("     ! 常见成因：函数级夹具里建了主窗口，参数化用例又有几十条。")
            continue
        out = (r.stdout or "").strip().splitlines()
        summary = next((line for line in reversed(out) if re.search(r"passed|failed|error", line)), "")
        m = re.search(r"(\d+) passed", summary)
        if m:
            total_cases += int(m.group(1))
        passed = r.returncode == 0 or (
            "passed" in summary and "failed" not in summary and "error" not in summary
        )
        if passed:
            ok += 1
            print(f"OK   {tf.name}: {summary[:80]}")
        else:
            fails.append((tf.name, summary[:90]))
            print(f"FAIL {tf.name}: {summary[:80]}")
            # 失败时吐出尾部明细,否则 CI 上只见 FAIL 不见原因
            tail = out[-30:]
            err_tail = (r.stderr or "").strip().splitlines()[-10:]
            for line in tail:
                print(f"     | {line}")
            for line in err_tail:
                print(f"     ! {line}")

    print("=" * 70)
    print(f"文件 {len(tests)}: OK {ok} / FAIL {len(fails)} | 用例通过 {total_cases} | {time.time()-t0:.0f}s")
    for name, s in fails:
        print(f"  FAIL {name}: {s}")
    if timed_out:
        print(f"  ⚠ 其中 {len(timed_out)} 个是**超时**（结论未知，不是判为不通过）："
              f"{'、'.join(timed_out)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
