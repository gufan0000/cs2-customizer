# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 74 体检 · **一条断言可以自己把自己短路掉，而它在报告上是绿的。**

## 为什么建这条

回退验证（585/586）逮住 `test_config_snapshot_empty_state.py` 是假绿。
成因不是断错了对象，是我给每条断言都加了一句**免责短路**：

    assert page.empty_hint_label.isVisible() or not page.isVisible()

测试里这一页**从不显示** ⇒ `not page.isVisible()` 恒真 ⇒ **四条断言一条都没在断言**。

⭐⭐⭐ **一条判据查的东西，和它声称查的东西，可以不是一件事** ——
这一次「不是一件事」的载体，是那句我自己加上去、看起来很谨慎的免责。

⚠ 而这条教训本仓**早就写过**：`test_advanced_page_action_bar_and_debug.py:60`
逐字写着「第一版就是这么写的，当场假绿」，并给出了正解 `isVisibleTo(page)`
（问的是「若祖先显示出来它会不会露脸」，**不需要真的显示**，offscreen 下语义是稳的）。
⇒ ⭐⭐ **光写教训不够，要有判据** —— 那句教训躺在另一个文件的注释里，
挡不住我在两页之外再写一遍。

## 普查出来的第二条

同一支扫描还翻出 `test_toast_undo.py` 里一条以 `or True` 结尾的断言
（147 条碰可见性的断言里唯一一条）。作者的顾虑是真的、注释也写了，
但**答案不是短路掉它**，而是换成 offscreen 下语义稳定的那个 API。

（本项目测试逐文件跑：
 `python -m pytest tests/test_no_assert_shorts_itself_out.py`）
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: 可见性三兄弟。`isHidden` 也算进人群 —— 它是同一件事的反面写法。
_VIS = ("isVisible", "isVisibleTo", "isHidden")

#: 免责短路里被短路掉的那一项。**只收 `isVisible`**，理由是本仓特有的：
#: 总纲 §9.1 逐字写过「`isVisible()` 在没 show 过的窗口上**恒假**」，
#: 而判据里的窗口**从不 show** ⇒ `not X.isVisible()` 在这里是**恒真**。
#: ⛔ 不收 `isVisibleTo`：它问的是「若祖先显示出来会不会露脸」，
#:   **是个真的谓词**，`or not X.isVisibleTo(y)` 是一个真的分支。
#: ⛔ 也不收 `isHidden`：同理，控件确实可能被显式隐藏。
_ESCAPE = ("isVisible",)


def _mentions_visibility(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in _VIS for n in ast.walk(node))


def _is_escape_hatch(v: ast.expr) -> str | None:
    """这一项是不是「恒真的免责」？是就返回它的样子，否则 None。"""
    if isinstance(v, ast.Constant) and v.value is True:
        return "or True"
    if (isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not)
            and isinstance(v.operand, ast.Call)
            and isinstance(v.operand.func, ast.Attribute)
            and v.operand.func.attr in _ESCAPE):
        return f"or not ....{v.operand.func.attr}()"
    return None


def _scan() -> tuple[list[str], list[str], list[str]]:
    """→ (人群, 犯规的, 读不动的)。人群 = 碰可见性的 assert。

    ⚠⚠ 第三个返回值是**破坏验证自己逼出来的**：我的第一版把语法错写成
    `except SyntaxError: continue`，于是拿一个语法坏了的文件去试这条判据时，
    它**静默跳过并报绿**。⭐ 那正是「分母守卫」要防的形状 ——
    **一个从分母里悄悄消失的文件，和一个守规矩的文件，在报告上一模一样。**
    """
    population, offenders, unreadable = [], [], []
    for f in sorted(TESTS.glob("test_*.py")):
        try:
            tree = ast.parse(io.open(f, encoding="utf-8").read())
        except SyntaxError as exc:
            unreadable.append(f"{f.name}: {exc}")
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assert) or not _mentions_visibility(n.test):
                continue
            population.append(f"{f.name}:{n.lineno}")
            # ⚠ 走**整棵子树**里的每个 `or`，不只是最外层那个 ——
            #   `assert (A or not p.isVisible()) and B` 一样是被短路掉的，
            #   而只看最外层的版本对它是瞎的（那正是本文件在讲的那件事）。
            for boolop in (x for x in ast.walk(n.test)
                           if isinstance(x, ast.BoolOp)
                           and isinstance(x.op, ast.Or)):
                hit = next((h for v in boolop.values
                            if (h := _is_escape_hatch(v)) is not None), None)
                if hit is not None:
                    offenders.append(f"{f.name}:{n.lineno}  ←  {hit}")
                    break
    return population, offenders, unreadable


def test_the_scan_can_actually_see_the_asserts():
    """⭐ 分母守卫：扫瞎了会全绿，而「扫瞎了」和「一条都没犯」在报告上一模一样。

    实测批 74：**147 条**。门限钉在**被观察的人群**上，不钉在坏人数上
    （批 42 那条：钉坏人数的存在性检查，会在修好的那天自己红）。
    """
    population, _, unreadable = _scan()
    assert not unreadable, (
        "下面这些测试文件 AST 读不动，于是**静默地不在分母里**：\n  "
        + "\n  ".join(unreadable))
    assert len(population) >= 100, (
        f"只扫到 {len(population)} 条碰可见性的断言（批 74 实测 147）—— "
        f"这支扫描多半瞎了，而瞎了的时候它必然全绿")


def test_no_visibility_assert_shorts_itself_out():
    """⛔ 断言里不许出现恒真的免责项。

    要「这一页没显示时别管它」，正解是 `isVisibleTo(祖先)` —— 它不需要真的显示。
    """
    _, offenders, _ = _scan()
    assert not offenders, (
        "下面这些断言给自己留了一条恒真的短路 —— 它们**一个字都没有在断言**：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 改用 `isVisibleTo(祖先)`：问的是「若祖先显示出来会不会露脸」，"
          "不需要真的显示。")
