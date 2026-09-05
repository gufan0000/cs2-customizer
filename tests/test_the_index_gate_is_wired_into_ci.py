# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-023：搜索索引的同步原来**只靠我记着**，而那句话活了 18 天。

## 立案那天说的话，到批 45 仍然逐字成立

M0（2026-08-17）的原文：

    `build_search_index.py --check` **不在 CI 里**（CI 只跑 ruff + run_tests）。
    改了页面控件文案就必须重跑索引，这条规则只写在记忆里 ⇒ 一天之内就漏了一次：
    RN-016 给 kill_voice 加「近战」分类后没重跑，索引一直是脏的，
    **没有任何东西报错**。

中间补了两样东西，**都不是这一道**：

| 补了什么 | 它证明了什么 | 它没证明什么 |
|---|---|---|
| `tests/test_search_index_check_exit_code.py`（16 条）| `--check` 的**退出码可信**（不会被产品退出链路洗成 0）| 真索引到底同不同步 |
| 收工七件套第 ⑦ 格 | 有人写下了「要跑它」 | **有人真的跑了它** |

⭐⭐ 第二行正是批 35 判过的那一族：**一条只在「我想起来」时才生效的制度，
等于没有这条制度。** 而它比那一条更隐蔽 —— 清单里**确实有这一格**，
所以每次收工汇报都能诚实地写「已跑」，而漏掉的那一次不会有任何痕迹。

## 批 45 的修法与它的前提

⇒ 两仓 CI 各加一道**阻断级**步骤跑 `--check`。

⭐ 这个修法的前提是那 16 条退出码判据：**没有它们，这个门禁读到的可能是一个
被产品退出链路洗过的 0** —— 那时候接进 CI 反而更坏（一道永远绿的门）。
⭐⭐ **一道门禁能不能接上，取决于它交出来的那个数可不可信** ——
   而「可不可信」本身是另一批人用 16 条判据挣来的。

⛔ 不许拿 `run_tests` 里的某条判据替代它：那条只能比「重新生成是否逐字节一致」，
看不见「有一条根本没进去」（批 40 实测：文案里一个标点就让控件掉出索引，全站 6 条）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"

#: 这道门禁要跑的那个命令。⚠ 只认 `--check`：不带它的那一支是**重新生成**，
#: 在 CI 里跑重新生成等于让门禁自己把不同步改成同步。
CHECK_CMD = "build_search_index.py --check"

#: CI 里已有的那几道审计 —— 用来证明「这个仓的 CI 是完整那一套」。
#: ⚠ 这一格是为了不在派生子集里假红：如果哪天开源仓把审计整层砍掉，
#:   那它就不该被要求有第六道（同 RN-188：照闭源版写死的断言在子集里是**错**）。
SIBLING_AUDITS = ("tab_order_audit.py", "layout_overflow_audit.py")


def _workflow_text() -> str:
    """CI 工作流的文本，**去掉注释行**。

    ⚠⚠ 这一格是被我自己写的注释咬出来的：那道新步骤上面有一段说明，
    里面逐字写着「`build_search_index.py --check` **不在 CI 里**」——
    于是判据 `text.index(CHECK_CMD)` 找到的是**注释里那一处**，
    从那儿往后 900 字符正好被下一个 `- name:` 切掉，读不到 `LASTEXITCODE`。
    ⭐⭐ **一个字符串出现过，不等于那件事发生过**（批 10 那条，
      而这次它出现在*解释这件事*的注释里）—— 同 RN-401：扫文本先去注释。
    """
    if not WORKFLOWS.is_dir():
        pytest.skip("这个仓没有 .github/workflows —— 本条只在有 CI 的仓里可比")
    files = must_scan(sorted(WORKFLOWS.glob("*.yml")), ".github/workflows/*.yml")
    lines = []
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith("#"):
                continue
            lines.append(line)
    return "\n".join(lines)


def test_ci_runs_the_search_index_check():
    """RN-023：CI 必须真的跑 `build_search_index.py --check`。

    ⚠ 分母守卫在前：先证明这个仓的 CI 是「完整那一套审计」，
      再要求它有第六道 —— 否则在派生子集里这会是一条假红。
    """
    text = _workflow_text()
    present = [a for a in SIBLING_AUDITS if a in text]
    if len(present) < len(SIBLING_AUDITS):
        pytest.skip(
            f"这个仓的 CI 不是完整那一套审计（只有 {present}）—— "
            "不要求它有搜索索引那一道")
    assert CHECK_CMD in text, (
        "CI 里没有跑 `build_search_index.py --check`。\n"
        "⭐ RN-023：改了页面控件文案就必须重跑索引，而这条规则原来只写在"
        "收工清单里 —— **一条只在「我想起来」时才生效的制度，等于没有这条制度**。\n"
        "⛔ 别用 `run_tests` 里的判据替代：那条看不见「有一条根本没进去」。"
    )


def test_the_ci_step_reads_the_exit_code_not_the_words():
    """⭐ 它必须按**退出码**判定，不许只把输出打出来。

    ⚠ 这一条是 RN-194 那族的直接搬用：`--check` 曾经把
    「索引与代码不同步」一字不差地打印出来、**进程却按 0 退出**。
    ⭐ **文案是给人看的，退出码才是给 CI 看的** —— 两者不一致时门禁等于不存在。
    """
    text = _workflow_text()
    if CHECK_CMD not in text:
        pytest.skip("上一条会先红")
    # 取那一步的 run: 块（到下一个 `- name:` 为止）
    idx = text.index(CHECK_CMD)
    tail = text[idx: idx + 900]
    tail = tail.split("- name:")[0]
    # ⚠⚠ 第一版这里还收 `exit 1`，**破坏验证当场判它假绿**：
    #   把 `if ($LASTEXITCODE -ne 0)` 改成 `if ($false)` 之后，
    #   那句 `exit 1` **还在**（只是永远走不到），判据照样绿。
    # ⭐⭐ **一条判据收的记号越宽，它越容易被「留着形状、抽掉内容」满足。**
    # ⇒ 只收真正能读到那个码的两种写法。
    assert re.search(r"LASTEXITCODE|verdict\.ps1", tail), (
        "那一步只是把 `--check` 的输出打出来，没有按退出码阻断。\n"
        "⭐ 一道不读退出码的门禁，和没有这道门禁在结果上一样。\n"
        "⛔ 光有一句 `exit 1` 不算 —— 它可能挂在一个永远不成立的条件下面。"
    )


def test_the_exit_code_contract_is_still_under_judgement():
    """⭐⭐ **这道门禁能接上，全靠另一支判据保证那个退出码可信。**

    ⚠ 没有 `test_search_index_check_exit_code.py` 那 16 条，
    CI 读到的可能是一个**被产品退出链路洗成 0** 的码
    （`gui_widget._run_shutdown_steps` 的看门狗 `os._exit(0)`、
    `core/shutdown` 兜底的 `sys.exit(0)`）——
    那时候接进 CI 反而更坏：一道**永远绿**的门。
    ⇒ 这一条把那个依赖写成机器读得到的东西。
    """
    contract = REPO / "tests" / "test_search_index_check_exit_code.py"
    assert contract.is_file(), (
        f"{contract.name} 不见了 —— 而 CI 那道搜索索引门禁的全部可信度来自它。\n"
        "⭐ 一道门禁能不能接上，取决于它交出来的那个数可不可信。")
    src = contract.read_text(encoding="utf-8")
    cases = must_scan(re.findall(r"^def (test_\w+)", src, re.M),
                      "退出码合约判据", least=10)
    assert len(cases) >= 10, f"退出码合约只剩 {len(cases)} 条判据（实测应有 16 条）"
