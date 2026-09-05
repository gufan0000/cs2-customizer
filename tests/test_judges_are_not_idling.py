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

## ⚖ 批 42（2026-09-03）：从「棘轮」升级成「必须为 0」

批 35 的裁定是「不逐条修，先配棘轮」（77 只许变少）。
⭐ 收口的理由是**机制性的，不是洁癖**：P5 共享层干的事
（搬控件、换名单、改容器类型）**正好就是清空分母** ——
在页面阶段这 77 条只是隐患，进 P5 它们是必然触发。

⇒ 现在的形状变了，而这个变化本身值得记：

| | 批 35 | 批 42 |
|---|---|---|
| 分母 | 「有空转风险的函数」77 条 | 「**会扫东西且只做否定断言**的函数」（候选，77 条）|
| 断言 | 这个数只许变少 | 候选里**没有一条缺分母守卫** |
| 存在性检查 | `len(风险) >= 20` | `len(候选) >= 60` |

⭐⭐⭐ **旧形状有一个自我瓦解的性质：判据修得越好，它自己的存在性检查越接近失败。**
（`len(every) >= 20` 在风险清零那天会红。）
⇒ **一条棘轮的存在性检查，要钉在「被观察的人群」上，不是钉在「里面的坏人数」上。**

## ⚠⚠ 那个 77 从来不是 77 —— 逐条走一遍才发现的

批 42 逐条核实时，**4 条本来就有分母守卫**，只是这支扫描认不出来：

| 写法 | 例 | 为什么认不出 |
|---|---|---|
| `assert x is not None` | `test_the_setter_does_not_write_config_behind_the_chain` | 只认 `>`/`>=`/`== 正整数` |
| `assert seen == len(cases)` | `test_the_buttons_the_switch_really_governs_still_dim` | 右边是 `Call` 不是常量 |
| `assert len(a) == len(b) >= 20` | `test_the_batch_log_is_one_unbroken_table_in_order` | **链式比较有两个操作符**（批 41 同一个坑）|

⭐⭐ **一张「待核实清单」配上棘轮之后，那个数字会被当成事实引用。**
它在册 33 天，我在三份文档里写过「77 条」，而它一次也没被核过。
⇒ 清单类判据要在注释里写明：**这个数是上限，不是计数。**

## 判别式（⭐ 先说清它能看见什么）

一个测试函数进**候选**，要同时满足两条：

  ① 函数体里有一次**扫描**（glob / rglob / walk / findChildren / `_rows(` …）
     —— 只有「扫出来的集合」才会悄悄变空；
  ② 只做**否定断言**（`assert not X` / `== []` / `len(...) == 0`）。

候选里，满足下面任一条的算**已配守卫**：

  · 调了 `must_scan(...)`（`tests/_denominator.py`，批 42 的公共守卫）；
  · 函数体里有一句正向的分母断言（`>= N` / `> N` / `== 正整数` / `== len(...)`
    / `is not None` / `in`）；
  · docstring 里有一行 `分母：…` —— **它真的没有分母**（命中扫描记号纯属误伤），
    那一行必须**说出理由**，不是写一句「无分母」。

⛔ **看不见的三类，明写出来**：
  1. 分母**非空但错**（批 34 那三次就是这一类）—— 静态看不出来；
  2. 守卫写在**同文件的别的函数**里 ⇒ 会误报 ⇒ 见 A/B 两组；
  3. 分母在 fixture / 模块级算好 ⇒ 认不出。

⛔ **两条不许**：
  · 不许靠收窄 `SCAN_TOKENS` 让这条变绿 —— 那只是把判据从视野里挪走；
  · 不许用 `pytest.skip` 当守卫 —— 跳过和通过在门禁上是同一个颜色。
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

#: 公共分母守卫（`tests/_denominator.py`）。调了它就算配了守卫。
SHARED_GUARD = "must_scan("

#: docstring 里声明「这条真的没有分母」的开头。⭐ 后面必须跟理由。
NO_DENOMINATOR_MARK = "分母："

#: 候选下限：**会扫东西且只做否定断言**的函数至少有这么多。
#: ⭐ 这是这支扫描的存在性检查，钉在**被观察的人群**上 ——
#:   钉在「里面有几个坏人」上的话，判据修好的那天它自己会红。
#: 2026-09-03 批 42 实测 77 条候选。
MIN_CANDIDATES = 60

#: 缺分母守卫的条数上限。**批 42 起就是 0，且不许再放宽。**
#: ⚠ 调大它不是一个选项：新写的判据要么调 `must_scan`，
#:   要么在 docstring 里写一行 `分母：<为什么这条没有分母>`。
MAX_UNGUARDED = 0


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


def _guards_denominator(node: ast.Assert, toplevel: bool) -> bool:
    """这一句在说「分母不空 / 至少看见了 N 个 / 锚点还在」吗。

    ⚠ **链式比较要逐段看**（`a == b >= 300`）：第一版只看 `len(t.ops) == 1`，
    于是批 41 那条写成链式的守卫**它自己看不见**，棘轮当场从 77 顶到 78。
    ⭐ 省下来的那一行，代价是让扫描器看不见这道守卫。

    ⚠ `is not None` 与 `== len(...)` 这两种**只在函数顶层**才算守卫 ——
    它们是「锚点还在 / 全都量到了」的写法，写在循环体里说的是别的事
    （实测：`test_archived_pages_still_match_their_fingerprint` 循环里那句
    `assert got is not None` 管的是单页，而它的分母 `pages` 靠 skip 兜着，
    那不是守卫）。⭐ **守卫要贴着扫描写，不是写在循环里。**
    """
    t = node.test
    if isinstance(t, ast.Compare):
        for op, right in zip(t.ops, t.comparators):
            if isinstance(op, (ast.GtE, ast.Gt)):
                return True
            if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) \
                    and isinstance(right.value, int) and right.value > 0:
                return True
            if isinstance(op, ast.Eq) and isinstance(right, (ast.List, ast.Set)) and right.elts:
                return True
            if toplevel and isinstance(op, ast.IsNot) \
                    and isinstance(right, ast.Constant) and right.value is None:
                return True
            if toplevel and isinstance(op, ast.Eq) and isinstance(right, ast.Call) \
                    and getattr(right.func, "id", "") == "len":
                return True
        if any(isinstance(o, ast.In) for o in t.ops):
            return True
        return False
    if isinstance(t, (ast.Call, ast.Name, ast.Attribute)):
        return True
    return False


def _scan() -> tuple[list[str], list[str], list[str]]:
    """(候选, 缺守卫的, 缺守卫且同文件也没守卫的)。"""
    candidates: list[str] = []
    unguarded: list[str] = []
    unguarded_lonely: list[str] = []
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
            tag = f"{path.name}::{fn.name}"
            candidates.append(tag)

            if SHARED_GUARD in seg:
                continue
            doc = ast.get_docstring(fn) or ""
            if any(line.strip().startswith(NO_DENOMINATOR_MARK)
                   for line in doc.splitlines()):
                continue
            top = {id(s) for s in fn.body if isinstance(s, ast.Assert)}
            if any(_guards_denominator(a, id(a) in top) for a in asserts):
                continue
            unguarded.append(tag)
            if not file_guarded:
                unguarded_lonely.append(tag)
    return candidates, unguarded, unguarded_lonely


def test_the_scan_actually_finds_something():
    """⭐ 先证明它看得见东西，再让它去做否定断言（RN-169）。

    ⚠ 这条判据自己就是那一族要防的东西的反例：它**先断言分母不空**，
    再去做否定断言。
    ⭐ 而分母取的是**候选**（会扫东西且只做否定断言的函数），
    不是「里面有几个没配守卫」—— 后者是它要压到 0 的东西，
    拿它当存在性证据，就成了「拿盲区还在当自己活着的证据」（RN-499 那个形状）。
    """
    candidates, _, _ = _scan()
    assert len(candidates) >= MIN_CANDIDATES, (
        f"只扫出 {len(candidates)} 条候选（会扫东西且只做否定断言的判据）—— "
        "这支扫描多半自己瞎了（`SCAN_TOKENS` 改坏了？测试目录挪了？）。"
    )


def test_every_scanning_judge_guards_its_denominator():
    """**RN-469 收口**：会扫东西的否定断言，必须先说清分母不空。

    三种合格写法（见模块头）：`must_scan(...)` / 正向分母断言 /
    docstring 里一行 `分母：<理由>`。
    """
    _, unguarded, _ = _scan()
    assert len(unguarded) <= MAX_UNGUARDED, (
        f"有 {len(unguarded)} 条判据会扫一个集合、只对它做否定断言，"
        "却没有任何一句说这个集合不空：\n"
        + "\n".join("  " + t for t in unguarded)
        + "\n\n⭐ 分母一空它必然全绿，而「分母为空」和「真的没问题」"
        "在测试报告上一模一样。\n"
        "⇒ 三选一：① `from _denominator import must_scan` 把扫描包起来；\n"
        "         ② 在函数**顶层**加一句正向断言（`>= N` / `is not None` / `== len(...)`）；\n"
        "         ③ 它真的没有分母 —— 在 docstring 里写一行 `分母：<为什么没有>`。\n"
        "⛔ 不许收窄 `SCAN_TOKENS`，也不许拿 `pytest.skip` 当守卫。"
    )


def test_the_guard_requirement_is_not_quietly_relaxed():
    """⭐ 分母守卫的守卫：`MAX_UNGUARDED` 不许被调大。

    ⚠ 这一条是拿批 41 换来的：那一批我给一条新棘轮做破坏实验，
    把上限从 0 放宽到 99 —— **判据照样绿**（当前值就是 0，0 ≤ 99）。
    ⭐⭐ **一条棘轮当前值为 0 时，放宽上限是测不出来的。**
    ⇒ 所以这里正面钉住那个常量本身。
    """
    assert MAX_UNGUARDED == 0, (
        f"`MAX_UNGUARDED` 被改成了 {MAX_UNGUARDED}。\n"
        "RN-469 已于 2026-09-03 批 42 收口为 **0**，理由是机制性的：\n"
        "P5 共享层干的事（搬控件、换名单、改容器类型）正好就是清空分母。\n"
        "⇒ 新判据请配守卫，不要放宽这个数。"
    )
