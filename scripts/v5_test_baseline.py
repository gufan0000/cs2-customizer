# SPDX-License-Identifier: GPL-3.0-or-later
"""
v5 测试基线 — 按文件单独 subprocess 跑全 322 测试

为啥按文件跑:多个 PySide6 UI 测试合并跑会触发 STATUS_STACK_BUFFER_OVERRUN
(Windows 0xC0000409),原因是 QApplication 资源未完全释放。
分文件跑可隔离进程,稳定可靠。

用法:
    python scripts/v5_test_baseline.py [--label v4]

输出:
    artifacts/v5_baseline/<label>/tests.log     合并所有文件的输出
    artifacts/v5_baseline/<label>/tests.json    汇总:passed/failed/duration
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_one_file(test_file: Path) -> dict:
    cmd = [
        sys.executable, "-m", "pytest", str(test_file),
        "-q", "--no-header", "--tb=line",
        "-p", "no:cacheprovider",
    ]
    t0 = time.time()
    try:
        r = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        out = r.stdout
        err = r.stderr
        exit_code = r.returncode
    except subprocess.TimeoutExpired:
        out = ""
        err = "TIMEOUT after 180s"
        exit_code = -1
    duration = time.time() - t0

    # 解析最后一行 e.g. "7 passed, 1 warning in 0.10s" / "5 passed, 2 failed in 1.2s"
    summary_match = re.search(
        r"(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?(?:,\s+(\d+)\s+error)?",
        out
    )
    passed = failed = skipped = errors = 0
    if summary_match:
        passed = int(summary_match.group(1) or 0)
        failed = int(summary_match.group(2) or 0)
        skipped = int(summary_match.group(3) or 0)
        errors = int(summary_match.group(4) or 0)

    # 也匹配只有 fail/error 的情况(无 passed)
    if not summary_match:
        m2 = re.search(r"(\d+)\s+failed", out)
        if m2:
            failed = int(m2.group(1))
        m3 = re.search(r"(\d+)\s+error", out)
        if m3:
            errors = int(m3.group(1))

    return {
        "file": str(test_file.name),
        "exit_code": exit_code,
        "duration_s": round(duration, 2),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "stdout": out,
        "stderr": err,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="v4")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "artifacts" / "v5_baseline"))
    args = parser.parse_args()

    out_dir = Path(args.out) / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "tests.log"
    json_path = out_dir / "tests.json"

    test_files = sorted((PROJECT_ROOT / "tests").glob("test_*.py"))
    print(f"[tests] running {len(test_files)} test files")

    results = []
    log_lines = []
    total_passed = total_failed = total_skipped = total_errors = 0
    overall_t0 = time.time()

    for i, tf in enumerate(test_files, 1):
        r = run_one_file(tf)
        results.append(r)
        total_passed += r["passed"]
        total_failed += r["failed"]
        total_skipped += r["skipped"]
        total_errors += r["errors"]

        status = "OK"
        if r["exit_code"] != 0 or r["failed"] > 0 or r["errors"] > 0:
            status = "FAIL" if r["failed"] > 0 or r["errors"] > 0 else f"EXIT={r['exit_code']}"
        print(f"  [{i:2d}/{len(test_files)}] {r['file']:50s} {r['duration_s']:6.2f}s  "
              f"passed={r['passed']:3d}  status={status}")

        log_lines.append(f"\n{'='*70}\n[{r['file']}] exit={r['exit_code']} duration={r['duration_s']}s\n{'='*70}")
        log_lines.append(r["stdout"])
        if r["stderr"]:
            log_lines.append(f"--- stderr ---\n{r['stderr']}")

    overall_duration = time.time() - overall_t0

    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    summary = {
        "label": args.label,
        "measured_at": datetime.now().isoformat(),
        "duration_s": round(overall_duration, 2),
        "files_total": len(test_files),
        "passed": total_passed,
        "failed": total_failed,
        "skipped": total_skipped,
        "errors": total_errors,
        "total": total_passed + total_failed + total_skipped + total_errors,
        "files_with_issues": [
            {"file": r["file"], "exit_code": r["exit_code"],
             "failed": r["failed"], "errors": r["errors"]}
            for r in results
            if r["exit_code"] != 0 or r["failed"] > 0 or r["errors"] > 0
        ],
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[tests] === SUMMARY ===")
    print(f"  total time: {overall_duration:.1f}s")
    print(f"  passed:     {total_passed}")
    print(f"  failed:     {total_failed}")
    print(f"  skipped:    {total_skipped}")
    print(f"  errors:     {total_errors}")
    print(f"  files with issues: {len(summary['files_with_issues'])}")
    if summary["files_with_issues"]:
        for x in summary["files_with_issues"]:
            print(f"    - {x['file']}: exit={x['exit_code']} failed={x['failed']} errors={x['errors']}")
    print(f"  log     -> {log_path}")
    print(f"  summary -> {json_path}")

    return 0 if total_failed == 0 and total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
