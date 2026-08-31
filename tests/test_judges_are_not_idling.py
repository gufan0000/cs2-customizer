# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 35 体检 · **哪些判据是绿的，因为它们没在量东西。**

## 为什么建这条

批 34 一次撞出三件同形的事：
  · 我自己的普查**连造三个错的分母**，每次都产出一张**填满了的**错表；
  · `test_help_copy_names_real_controls` 的空转守卫把错配**写进了 docstring
    却没修** —— 因为那一页当时没有帮助文案、不在分母里，它一直是绿的；
  · 而同一份知识在另一条判据里**早就修好了**。

⭐⭐ **一条为某个缺陷而写的判据，可以在那个缺陷还没进分母的时候，绿着上线。**

## 判别式（⭐ 先说清它能看见什么）

一个测试函数同时满足三条才算「空转风险」：

  ① 函数体里有一次**扫描**（glob / rglob / walk / findChildren / `_rows(` …）
     —— 只有「扫出来的集合」才会悄悄变空；
  ② 只做**否定断言**（`assert not X` / `== []` / `len(...) == 0`）；
  ③ 函数体里**没有任何一句**断言分母不空。

⛔ **看不见的三类，明写出来**：
  1. 分母**非空但错**（批 34 那三次就是这一类）—— 静态看不出来；
  2. 守卫写在**同文件的别的函数**里（本仓很常见）⇒ 会误报 ⇒ 分 A/B 两组；
  3. 分母在 fixture / 模块级算好 ⇒ 认不出。

## ⚠⚠ 这支扫描的第一版，自己的分母就是错的

第一版把「任何只做否定断言的测试函数」都算进来 ⇒ **310 条**，
其中大半是 `assert not controller.preheat()` 这种**根本没有分母**的用例。
⭐⭐⭐ **知道一条教训，和在下一次动手时用上它，是两件事** ——
我是**带着批 34 那条教训**去写这支扫描的，仍然踩了同一个坑。

## 这条判据做什么、不做什么

它是一条**棘轮**：数字只许变少。
⛔ 它**不**说这 77 条都是缺陷 —— 它们是**待核实清单**。
⭐ 逐条核实要花的力气远超一批，而清单不配棘轮就会长回去。
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: 「这一句在扫东西」的记号。只有扫出来的集合才会悄悄变空。
SCAN_TOKENS = (
    "glob(", "rglob(", "iterdir(", "walk(", "findChildren(",
    "ls-files", "_rows(", "_page_ids(", "_page_rows(",
    "_tracked_python_files(", "_named_controls(", "_all_pages(",
    "PAGE_HELP_TEXTS", "read_text(",
)

#: 同文件里有这些名字的函数，就算「这个文件配了空转守卫」。
GUARD_NAME_HINTS = ("not_blind", "actually_sees", "sees_the",
                    "denominator", "is_there", "reaches_its")

#: 空转风险条数上限。**只许调小。**
#: 2026-08-31 批 35 首测：**77** 条（A 组 61 = 同文件里连一条守卫都没有）。
#: ⚠ 调小它的唯一正当方式是**给那几条判据补上分母守卫**，
#:   不是收窄 `SCAN_TOKENS`（那只是把它们从视野里挪走）。
#: ⚠ **本仓库（功能子集）的数不一样**：测试文件比完整产品少几支。
#:   完整产品 77 / A 组 61，这边实测 **76 / 60**。
#:   ⭐ 照闭源版的数字写死，在子集里不是「更严」，是「错」。
MAX_IDLE_RISK = 76

#: A 组（同文件里也没有任何守卫）上限。**只许调小。**
MAX_IDLE_RISK_UNGUARDED = 60


def _is_negative_assert(node: ast.Assert) -> bool:
    t = node.test
    if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
        return True
    if isinstance(t, ast.Compare) and len(t.ops) == 1:
        op, right = t.ops[0], t.comparators[0]
        if isinstance(op, ast.Eq) and isinstance(right, (ast.List, ast.Set)) \
                and not right.elts:
            return True
        if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) and right.value == 0:
            return True
    return False


def _guards_denominator(node: ast.Assert) -> bool:
    """这一句在说「分母不空 / 至少看见了 N 个 / 恰好是这几个」吗。"""
    t = node.test
    if isinstance(t, ast.Compare) and len(t.ops) == 1:
        op, right = t.ops[0], t.comparators[0]
        if isinstance(op, (ast.GtE, ast.Gt)):
            return True
        if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) \
                and isinstance(right.value, int) and right.value > 0:
            return True
        if isinstance(op, ast.Eq) and isinstance(right, (ast.List, ast.Set)) and right.elts:
            return True
    if isinstance(t, (ast.Call, ast.Name, ast.Attribute)):
        return True
    if isinstance(t, ast.Compare) and any(isinstance(o, ast.In) for o in t.ops):
        return True
    return False


def _idle_risk() -> tuple[list[str], list[str]]:
    """(全部候选, A 组候选)。"""
    every, unguarded = [], []
    for path in sorted(TESTS.glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        file_guarded = any(
            isinstance(n, ast.FunctionDef)
            and any(k in n.name for k in GUARD_NAME_HINTS)
            for n in ast.walk(tree))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("test_"):
                continue
            seg = ast.get_source_segment(src, fn) or ""
            if not any(tok in seg for tok in SCAN_TOKENS):
                continue
            asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
            if not any(_is_negative_assert(a) for a in asserts):
                continue
            if any(_guards_denominator(a) for a in asserts):
                continue
            tag = f"{path.name}::{fn.name}"
            every.append(tag)
            if not file_guarded:
                unguarded.append(tag)
    return every, unguarded


def test_the_scan_actually_finds_something():
    """⭐ 先证明它看得见东西，再让它去断言「没变多」（RN-169）。

    ⚠ 这条判据自己就是那 77 条要防的东西的反例：它**先断言分母不空**，
    再去做否定断言。
    """
    every, _ = _idle_risk()
    assert len(every) >= 20, (
        f"只扫出 {len(every)} 条空转风险 —— 这支扫描多半自己瞎了"
        "（`SCAN_TOKENS` 改坏了？测试目录挪了？）。"
    )


def test_idle_risk_only_shrinks():
    """棘轮：空转风险的条数只许变少。"""
    every, _ = _idle_risk()
    assert len(every) <= MAX_IDLE_RISK, (
        f"空转风险从 {MAX_IDLE_RISK} 涨到了 {len(every)} 条。\n"
        "新写的判据请**先断言分母不空**，再去做否定断言 ——\n"
        "⭐ 一条只做 `assert not offenders` 的判据，在分母为空时必然全绿，\n"
        "  而「分母为空」和「真的没问题」在结果上一模一样。\n"
        + "\n".join("  " + t for t in every[-12:])
    )
    assert len(every) >= MAX_IDLE_RISK, (
        f"实际只剩 {len(every)} 条，把 MAX_IDLE_RISK 收到这个数 —— "
        "棘轮不收紧等于没有棘轮。"
    )


def test_unguarded_idle_risk_only_shrinks():
    """A 组棘轮：连**同文件**里都没有一条空转守卫的那些。

    ⭐ 分成两组是因为 B 组多半是误报（守卫写在同文件的别的函数里），
    而 A 组是**这个文件里没有任何人在管分母**。
    """
    _, unguarded = _idle_risk()
    assert len(unguarded) <= MAX_IDLE_RISK_UNGUARDED, (
        f"A 组（同文件里连一条空转守卫都没有）从 {MAX_IDLE_RISK_UNGUARDED} "
        f"涨到了 {len(unguarded)} 条：\n"
        + "\n".join("  " + t for t in unguarded[-12:])
    )
    assert len(unguarded) >= MAX_IDLE_RISK_UNGUARDED, (
        f"实际只剩 {len(unguarded)} 条，把 MAX_IDLE_RISK_UNGUARDED 收到这个数。"
    )
