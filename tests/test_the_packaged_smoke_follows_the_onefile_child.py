# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-636（批 93）：打包冒烟必须追到**真正跑应用的那个进程**，而不是 `Popen` 交回来的那个。

## 它守的是什么

PyInstaller onefile 先起一个引导进程（解包），再起一个同名**子进程**跑应用。
批 92 第一次在 onefile 产物上跑 `smoke_packaged.py`：五条产品判据全绿，
而「优雅退出」两条红 —— 因为 WM_CLOSE 发给了引导进程（它没有窗口），
随后的「强杀」只打印了一句，**两个进程都还活着**，主窗留在用户桌面上。
⭐⭐⭐ **一道门禁测的对象和它以为的对象不是同一个进程**（RN-097 同族：那次是挑错了 exe）。

## 怎么验

不打包、不起 Qt：造一个「引导进程」（一个只会再起一个子进程然后等着的 python 脚本），
问 `_resolve_app_pid(引导 pid)` 拿回来的是不是**子进程**的 pid —— 子进程把自己的 pid
写进一个文件，两边对得上才算。⛔ 不用 `-c`，脚本先落盘（RN-602）。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "scripts" / "smoke_packaged.py"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="用的是 Win32 进程树")


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_packaged", SMOKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHILD = """
import os, sys, time
open(sys.argv[1], "w").write(str(os.getpid()))
time.sleep(60)
"""

PARENT = """
import subprocess, sys, time
p = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])
time.sleep(60)
"""


def test_it_resolves_to_the_child_not_the_launcher(tmp_path):
    smoke = _load_smoke()
    child_py = tmp_path / "child.py"
    parent_py = tmp_path / "parent.py"
    pid_file = tmp_path / "child_pid.txt"
    child_py.write_text(CHILD, encoding="utf-8")
    parent_py.write_text(PARENT, encoding="utf-8")

    launcher = subprocess.Popen(
        [sys.executable, str(parent_py), str(child_py), str(pid_file)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline and not pid_file.exists():
            time.sleep(0.2)
        assert pid_file.exists(), "子进程 30 秒内没起来 —— 这台机器上连对照都造不出，别往下断言"
        child_pid = int(pid_file.read_text(encoding="utf-8").strip() or "0")
        assert child_pid and child_pid != launcher.pid, "对照造坏了：子进程 pid 和引导进程一样"

        got = smoke._resolve_app_pid(launcher.pid, wait_seconds=20.0)
        assert got == child_pid, (
            f"⛔ 冒烟把 {got} 当成应用进程，而真正跑应用的是子进程 {child_pid}"
            f"（引导进程 {launcher.pid}）。\n"
            "⇒ WM_CLOSE 会发给一个没有窗口的进程，「强杀」也只杀引导进程 —— "
            "批 92 实测：主窗留在桌面上、GSI 端口继续占着，而冒烟报告只说「无可见顶层窗口」。")
    finally:
        for pid in {launcher.pid, int(pid_file.read_text(encoding="utf-8") or "0")
                    if pid_file.exists() else 0}:
            if pid:
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                f"Stop-Process -Force -ErrorAction SilentlyContinue -Id {pid}"],
                               capture_output=True, timeout=30)
        assert not smoke._still_alive([launcher.pid]), "对照进程没清干净"


PARENT_WITH_FORK_HELPER = """
import subprocess, sys, time
p = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], "--multiprocessing-fork", "parent_pid=1"])
time.sleep(60)
"""


def test_a_multiprocessing_helper_child_is_not_mistaken_for_the_app(tmp_path):
    """RN-645（批 96）：应用自己起的 `--multiprocessing-fork` 助手不是应用。
    批 96 实测 onedir 产物：主窗在父进程，第一个子进程是 fork 助手 ⇒ 原逻辑追错方向。"""
    smoke = _load_smoke()
    child_py = tmp_path / "child.py"
    parent_py = tmp_path / "parent.py"
    pid_file = tmp_path / "child_pid.txt"
    child_py.write_text(CHILD, encoding="utf-8")
    parent_py.write_text(PARENT_WITH_FORK_HELPER, encoding="utf-8")
    launcher = subprocess.Popen([sys.executable, str(parent_py), str(child_py), str(pid_file)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            time.sleep(0.2)
        child_pid = int(pid_file.read_text().strip())
        got = smoke._resolve_app_pid(launcher.pid, wait_seconds=3.0)
        assert got == launcher.pid, f"把 fork 助手 {child_pid} 当成了应用（返回 {got}，应返回父 {launcher.pid}）"
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(launcher.pid)], capture_output=True)


def test_the_pure_choice_covers_the_three_shapes_seen_on_real_builds():
    """RN-645：三种实测形状各一格，纯判断、不起进程。
    ① onefile 0.8s：引导进程只有 Tk 启动画面（标题 "tk"）、子进程还没出现 ⇒ 还没法定（不许退回父）；
    ② onefile 稍后：子进程有主窗 ⇒ 子；
    ③ onedir：没有非助手子进程、父有主窗 ⇒ 父。"""
    smoke = _load_smoke()
    assert smoke._choose_app_pid(1, [], {1: ["tk"]}) is None
    assert smoke._choose_app_pid(1, [2], {1: ["tk"], 2: []}) is None
    assert smoke._choose_app_pid(1, [2], {1: ["tk"], 2: ["CS2 Customizer v2.2.4"]}) == 2
    assert smoke._choose_app_pid(1, [], {1: ["CS2 Customizer v2.2.4"]}) == 1


def test_a_process_with_no_child_resolves_to_itself(tmp_path):
    """onedir 没有引导进程 —— 等不到子进程就用原 pid，别把冒烟挂在一个永远不来的孩子上。"""
    smoke = _load_smoke()
    lone = tmp_path / "lone.py"
    lone.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(lone)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert smoke._resolve_app_pid(proc.pid, wait_seconds=2.0) == proc.pid
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_the_smoke_closes_and_kills_the_resolved_pid_not_the_launcher():
    """文本守卫：主流程里 `_close_windows(...)` 收的是 `app_pid`，善后核对的集合里也带着它。"""
    src = SMOKE.read_text(encoding="utf-8")
    assert "_close_windows(app_pid)" in src, "WM_CLOSE 又发回引导进程了"
    assert "_still_alive(sorted({proc.pid, app_pid} | set(tree)))" in src, "杀完没回头核对整棵树（RN-645）"
    assert "tree = sorted({proc.pid, app_pid} | set(_descendants(proc.pid)))" in src, \
        "整棵树要在它们都活着时先记下来（引导一死孙进程就改挂别处）"
