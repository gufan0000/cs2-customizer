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
    for tf in tests:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(tf), "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=300,
            # 钉死 UTF-8:GitHub runner/非中文区 Windows 默认 cp1252,
            # 子进程输出含中文会让 reader 线程 UnicodeDecodeError(CI #5 实锤)
            encoding="utf-8", errors="replace",
        )
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
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
