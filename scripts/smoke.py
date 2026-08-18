#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""一键冒烟测试：验证优化重构后的关键模块仍工作。

目的：
    在每次提交 / 每次发布前一键确认：
    1. 所有新增单元测试通过
    2. 关键模块（入口、GSI、config、audio）能成功 import
    3. 脱敏日志、单实例、atexit、资源标志、优雅退出 5 项优化仍生效

用法：
    cd H:\\cs_py\\cfg-cs2customizer
    python scripts/smoke.py

退出码：
    0 = 全部通过
    1 = 单元测试有失败
    2 = 关键模块 import 失败
    3 = 优化生效验证失败

设计原则：
    - 不跑需要 Qt UI 环境的测试（留给 C4 完整 CI）
    - 无副作用：不写真实 config，不发网络请求
    - 总耗时 < 5 秒
"""
from __future__ import annotations

import importlib
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# --- 跑哪些测试 ---
UNITTEST_MODULES = [
    "tests.test_log_filter",
    "tests.test_single_instance",
    "tests.test_config_atexit_flush",
    "tests.test_resource_migration_marker",
    "tests.test_shutdown",
]

# --- 关键模块 import 清单 ---
CRITICAL_MODULES = [
    "main_widget",
    "config",
    "resource_manager",
    "gsi_server",
    "gsi_handler_kills",
    "gsi_handler_sounds",
    "gsi_handler_special",
    "gsi_handler_flash",
    "gsi_handler_stats",
    "gsi_handler_music",
    "gsi_handler_utility",
    "gsi_handler_hud_color",
    "music_player",
    "music_control_bar",
    "audio",
    "flash_process_manager",
    "crosshair_animation",
    "kill_icon_player",
    "voice_output_manager",
    "utility_display",
    "core.utils.logger",
    "core.utils.log_filter",
    "core.single_instance",
    "core.shutdown",
    "core.audio.audio_manager",
]


def banner(text: str) -> None:
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


def run_unittest() -> tuple[int, int]:
    """跑 UNITTEST_MODULES。返回 (pass_count, fail_count)。"""
    banner("Step 1/3 · 单元测试")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod in UNITTEST_MODULES:
        try:
            suite.addTests(loader.loadTestsFromName(mod))
        except Exception as e:
            print(f"  [WARN] 加载 {mod} 失败：{e}")
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    return result.testsRun - len(result.failures) - len(result.errors), \
           len(result.failures) + len(result.errors)


def run_imports() -> tuple[int, list[tuple[str, str]]]:
    """import CRITICAL_MODULES。返回 (ok_count, failed_list)。"""
    banner(f"Step 2/3 · 关键模块 import（{len(CRITICAL_MODULES)} 个）")
    ok = 0
    failed: list[tuple[str, str]] = []
    for mod in CRITICAL_MODULES:
        t0 = time.perf_counter()
        try:
            importlib.import_module(mod)
            ok += 1
            dt = (time.perf_counter() - t0) * 1000
            print(f"  [OK]   {mod}  ({dt:.0f} ms)")
        except Exception as e:
            failed.append((mod, str(e)[:120]))
            print(f"  [FAIL] {mod}  {e!s:.120s}")
    return ok, failed


def run_optimization_checks() -> tuple[int, list[str]]:
    """验证 8 个 commit 的关键改动"文件层面"存在。

    这不保证功能完全工作，但能抓到"意外回滚" / "误删" 的情况。
    """
    banner("Step 3/3 · 优化生效验证（文件级）")
    checks: list[tuple[str, callable]] = [
        ("A5 日志脱敏模块存在", lambda: (REPO_ROOT / "core/utils/log_filter.py").is_file()),
        ("A5 logger.py 接入脱敏",
         lambda: "SensitiveFilter" in (REPO_ROOT / "core/utils/logger.py").read_text(encoding="utf-8")),
        ("D2 单实例模块存在", lambda: (REPO_ROOT / "core/single_instance.py").is_file()),
        ("D2 main 接入单实例",
         lambda: "ensure_single_instance" in (REPO_ROOT / "main_widget.py").read_text(encoding="utf-8")),
        ("A3 config atexit 注册",
         lambda: "_atexit_flush" in (REPO_ROOT / "config.py").read_text(encoding="utf-8")),
        ("B3 资源迁移标志",
         lambda: "MIGRATION_MARKER_FILENAME" in (REPO_ROOT / "resource_manager.py").read_text(encoding="utf-8")),
        ("D1 优雅退出模块存在", lambda: (REPO_ROOT / "core/shutdown.py").is_file()),
        ("D1 main 接入信号处理",
         lambda: "install_signal_handlers" in (REPO_ROOT / "main_widget.py").read_text(encoding="utf-8")),
        ("B4 GSI handler logger.exception 升级",
         lambda: "logger.exception" in (REPO_ROOT / "gsi_handler_kills.py").read_text(encoding="utf-8")),
    ]
    ok = 0
    missing: list[str] = []
    for name, check in checks:
        try:
            if check():
                ok += 1
                print(f"  [OK]   {name}")
            else:
                missing.append(name)
                print(f"  [FAIL] {name}")
        except Exception as e:
            missing.append(f"{name} ({e})")
            print(f"  [ERR]  {name}: {e}")
    return ok, missing


def main() -> int:
    t0 = time.perf_counter()

    print(f"仓库: {REPO_ROOT}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")

    # Step 1
    ut_pass, ut_fail = run_unittest()

    # Step 2
    imp_ok, imp_failed = run_imports()

    # Step 3
    opt_ok, opt_missing = run_optimization_checks()

    # 汇总
    banner("汇总")
    elapsed = time.perf_counter() - t0
    print(f"单元测试:      {ut_pass} passed, {ut_fail} failed")
    print(f"关键模块 import: {imp_ok}/{len(CRITICAL_MODULES)} ok")
    print(f"优化生效验证:  {opt_ok}/9 ok")
    print(f"总耗时:        {elapsed:.2f} 秒")

    if ut_fail:
        print("\n[FAIL] 单元测试有失败，详情见上方 traceback")
        return 1
    if imp_failed:
        print("\n[FAIL] 关键模块 import 失败:")
        for m, e in imp_failed:
            print(f"   {m}: {e}")
        return 2
    if opt_missing:
        print("\n[FAIL] 优化验证缺失项:")
        for m in opt_missing:
            print(f"   - {m}")
        return 3

    print("\n[PASS] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
