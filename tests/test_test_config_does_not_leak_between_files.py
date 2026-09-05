# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""判据的前置状态不许由**文件的字母顺序**决定（RN-142）。

## 缺陷

`conftest.py` 把测试的配置目录钉在一个**固定路径**上（`%TEMP%/cs2customizer_test_config`），
为的是 `csgo_dir` 可复现。代价没人算过：那个目录**跨文件、跨轮次累积** ——
而 `build_tools/run_tests.py` 是逐文件起独立进程跑的，
于是**前一个文件写进配置的东西，后一个文件原样接着用**。

界面模式就是这么漏的：`test_search_jump_r13` / `test_design_w5` /
`test_ui_expert_mode_smoke` 等好几支会把 `ui_expert_mode = True` 存盘。
结果：

  · `test_advanced_page_ui_polish`（字母序靠前，看到的是初始值）
    断言 4 颗状态徽章 —— RN-138 之后普通模式只剩 3 颗，**CI 当场红**；
  · `test_ui_visual_r1_fixes`（字母序靠后，看到的是被污染后的 True）
    的空转守卫要求「≥20 项导航」—— 普通模式只有 16 项，
    它**一直靠前面那些文件的污染才绿**。

⭐ **一条不钉前置状态的判据，绿不绿取决于同一次运行里前面跑过谁。**
这比"本机绿 CI 红"更难查：同一台机器上，单跑绿、全量红，或者反过来。

## 修法

两层，都要：

  ① `conftest.py` 在**每个进程启动时**把界面模式按回产品默认（连同 `csgo_dir`）——
     这样跨文件的漏就断了；
  ② 需要专家模式的判据**自己钉**（已改：`test_ui_visual_r1_fixes`、
     `test_tool_pages_ui_polish`、`test_advanced_page_ui_polish`）。

本文件判的是 ①，而且是**端到端**判：先在子进程里跑一支已知会存盘专家模式的测试，
再起一个新进程看它读到什么。不去读 conftest 的源码 ——
那只能证明"字面量还在"，证明不了"这件事真的成立"。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: ⚠⚠ 批 47：这里原来写死 `gettempdir()/"cs2customizer_test_config"`，**抄了 conftest 一份**。
#: 并行化给配置目录加上工作槽位后缀（`cs2customizer_test_config_w3`）之后，这条判据
#: 就在读**另一个文件** —— 它照样绿，因为它污染的和它检查的是同一个（错的）文件。
#: 回退验证逮到：撤掉修复它**仍然绿**（346/348 里的那一条）。
#: ⭐ **别抄真源，去读真源。** `conftest` 把最终路径放在 `CS2C_CONFIG_DIR` 里，
#:   那就是唯一的答案；抄一份就等于多一个会各自漂移的副本。
SEED = (Path(os.environ["CS2C_CONFIG_DIR"]) if os.environ.get("CS2C_CONFIG_DIR")
        else Path(tempfile.gettempdir()) / "cs2customizer_test_config") / "config.json"

#: 污染**直接写进种子文件**，不去赌"哪支测试碰巧会存盘"。
#:
#: ⚠ 第一版就是这么赌的：挑了 `test_ui_expert_mode_smoke.py` 当污染源，
#: 而那支测试用的是**自己造的假 config 类**，一个字都不落盘 ——
#: 于是判据在回退验证里当场露馅（把修复撤掉它照样绿，0/1）。
#: ⭐ **判据要直接制造它要防的那个状态**，别指望别人替你制造。
_PROBE = (
    "import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests');"
    " import conftest;"          # conftest 的钉桩就在模块级
    " from config import config;"
    " print('EXPERT=' + str(bool(getattr(config, 'ui_expert_mode', False))))"
)


def test_the_current_process_starts_in_the_product_default_mode():
    """本进程读到的界面模式必须是产品默认（普通）。"""
    from config import config

    assert getattr(config, "ui_expert_mode", None) is False, (
        "测试进程一启动就处在专家模式 —— 那么任何不自己钉模式的判据，"
        "判的都是「碰巧攒成这样」的软件。\n"
        "conftest 应当在每个进程启动时把它按回产品默认，见本文件说明。")


def _ask_a_fresh_process() -> str:
    """新起一个进程问它读到什么 —— 这就是"下一个测试文件"看到的东西。"""
    probe = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO, capture_output=True, text=True, env=dict(os.environ),
        encoding="utf-8", errors="replace", timeout=600)
    blob = (probe.stdout or "") + (probe.stderr or "")
    for line in blob.splitlines():
        if line.startswith("EXPERT="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"探针没吐出结果：\n{blob[-1500:]}")


def test_a_polluted_seed_does_not_change_what_the_next_process_sees():
    """端到端：种子文件里被写进专家模式，下一个进程仍然看到普通模式。"""
    if not SEED.exists():
        pytest.skip("还没有测试种子配置（全新环境，conftest 还没写过）")

    backup = SEED.read_text(encoding="utf-8")
    try:
        data = json.loads(backup)
        data["ui_expert_mode"] = True          # 模拟"前一个文件把它存了盘"
        SEED.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        # 先确认污染真的落进去了，否则下面那句断言是空转。
        assert json.loads(SEED.read_text(encoding="utf-8"))["ui_expert_mode"] is True

        got = _ask_a_fresh_process()
    finally:
        # ⚠ 改了共享文件就必须在 finally 里还原 —— 崩在中间会把污染留给后面所有测试，
        # 而那正是本判据要防的病。（同 RN-093：探针不还原，等于自己造了个新缺陷。）
        SEED.write_text(backup, encoding="utf-8")

    assert got == "False", (
        "种子配置里被写进专家模式之后，下一个进程读到的还是**专家模式**。\n"
        "⇒ 配置在文件之间漏了：判据的前置状态由字母顺序决定（RN-142）。\n"
        "conftest 要在每个进程启动时把界面模式按回产品默认。")


def test_the_seed_file_on_disk_is_pinned_too():
    """落盘的那份种子配置也得是产品默认 —— 否则 ① 只是本进程内的假象。"""
    if not SEED.exists():
        pytest.skip("还没有测试种子配置（多半是全新环境，conftest 还没写过）")
    data = json.loads(SEED.read_text(encoding="utf-8"))
    assert data.get("ui_expert_mode") is False, (
        f"落盘的测试配置里 ui_expert_mode = {data.get('ui_expert_mode')!r}。\n"
        "conftest 只在内存里改是不够的：`run_tests.py` 逐文件起独立进程，"
        "下一个进程读的是**这个文件**。")
