# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""一句点名某颗按钮的话，**它的名字必须从那颗按钮上读**，不许硬编码。

## 缺陷

批 48 把 `audio_health` 的「一键修复（保守）」改名成「一键修复（只补不删）」，
而底栏那句「确认后再点…「一键修复（保守）」」**留在原地** ——
屏幕上同时出现了两个名字，指的是同一颗按钮。外审改完复跑一发逐字点破。

⭐⭐ 这是批 45「我撤掉一颗按钮，让它旁边那句话变成了假话」的**同一形态第二次**：
上次是撤按钮，这次是改按钮名，而**引用它的那句话都不会跟着动**。
⇒ 别让同一个名字在代码里存在两份。引用按钮就 `btn.text()`。

## 分母

`pages/*.py` 里所有 `set_message(...)` / `setText(...)` 的**字面量**参数，
只要里面用「」括着一段文字，而那段文字**恰好等于本文件里某颗按钮的字面文案**，
就是一处硬编码引用。⭐ 分母是扫出来的：新写一句照样进。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGES = REPO / "pages"

#: 「…」里那一段
QUOTED = re.compile(r"「([^」]{2,24})」")


def _module_string_constants(tree: ast.AST) -> dict[str, str]:
    """模块级 `NAME = "…"`。

    ⭐⭐ RN-519 清存量时才发现这条路非补不可：有 5 处的文案**建在按钮之前**
    （卡片 `description` / 页头副标题），读不到 `btn.text()`；
    ⛔ 又不能把按钮挪到前面 —— 焦点链走的是控件构造顺序（批 38 / RN-481）。
    ⇒ 修法是把名字收成**一份模块级常量**，按钮和那句话都引用它。

    ⚠ 而那一刀顺手会**把那颗按钮从本判据的分母里拿走**：
    `QPushButton(TEST_BUTTON_TEXT)` 里没有字面量，识别器就看不见它了，
    之后谁再往同一页抄一份名字都不会红。
    ⭐ 这正是 RN-522 那一族（按记号划分母）—— **修法本身缩小了分母**。
    """
    out = {}
    for node in tree.body:                       # 只认模块级，不进函数体
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def _button_literals(tree: ast.AST) -> set[str]:
    """本文件里 `QPushButton(…)` 用到的文案：字面量，或模块级常量解出来的值。"""
    consts = _module_string_constants(tree)
    out = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "QPushButton" and node.args):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.add(arg.value)
        elif isinstance(arg, ast.Name) and arg.id in consts:
            out.add(consts[arg.id])
    return out


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """模块 / 类 / 函数的首条字符串 —— 那是文档，不是屏幕上的话。"""
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _quoted_in_user_facing_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """全文件的字符串字面量里，用「」点名的那些串。

    ⚠⚠ 第一版只扫 `set_message(...)` 的**实参**，而真实写法是先拼进变量
    （`action_message = f"…"`）再传进去 —— 字面量根本不在实参里，
    破坏验证当场判它假绿。⭐ **判据把被测的形态想窄了，就只测得到那个窄形态。**
    ⇒ 改成扫全文件，只排掉 docstring（注释本来就不在 AST 里）。
    """
    skip = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip):
            for name in QUOTED.findall(node.value):
                hits.append((getattr(node, "lineno", 0), name))
    return hits


#: ⚠⚠ **存量债表。** 判据一放宽就逮出全站 **13 处**同形 —— 它们都在**已关档的页**上，
#: 改那些文案要连带重审那几页，不属于批 48 的范围。
#: ⇒ 照本工程既有做法做成棘轮：**存量入册、新增一律拒绝、只许变少**。
#: ⭐ 批 46 那条教训在这里同样成立：**债表能防止事情变坏，但它不会让事情变好** ——
#:   所以另立 RN-519 挂 C6 回扫，别指望这张表自己清空。
#: ⛔ 往这张表里加行 = 新写了一处硬编码 = 判据该红的时候你把它按住了。
KNOWN_HARDCODED: set[tuple[str, str]] = set()
#: ⭐ **空了。** 批 48 立表时 12 处（全在已关档页上），批 51 逐条清完：
#:   · 5 处文案建在按钮之后 ⇒ 直接 `f"…「{self.xxx_btn.text()}」"`；
#:   · 5 处文案建在按钮之前 ⇒ 名字收成模块级常量，两边都引用它；
#:   · `magnifier` / `utility` 那两颗原本是局部变量 ⇒ 挂到 `self` 上再读；
#:   · `advanced` 那一处的预填**根本不会被看到**（同函数末尾就把它覆盖了）
#:     ⇒ 换成中性占位，不点名按钮。
#: ⛔ 往这张表里加行 = 新写了一处硬编码 = 判据该红的时候你把它按住了。


def _offenders() -> set[tuple[str, str]]:
    found = set()
    scanned = 0
    for path in sorted(PAGES.glob("*_page.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        buttons = _button_literals(tree)
        if not buttons:
            continue
        scanned += 1
        for _lineno, quoted in _quoted_in_user_facing_literals(tree):
            if quoted in buttons:
                found.add((path.name, quoted))
    assert scanned >= 10, (
        f"只扫到 {scanned} 个建按钮的页面 —— 识别器多半瞎了，而不是真的这么少。")
    return found


def test_no_new_page_hardcodes_the_text_of_its_own_button():
    """新增一处就红。"""
    new = sorted(_offenders() - KNOWN_HARDCODED)
    assert not new, (
        "这些提示文案把按钮名**抄了一份**，改按钮名时它们不会跟着动：\n  "
        + "\n  ".join(f"{f} 「{q}」" for f, q in new)
        + "\n⇒ 改成从按钮读：`f\"…点「{self.xxx_btn.text()}」\"`。\n"
          "（批 48 实测：改了「一键修复（保守）」→「一键修复（只补不删）」，"
          "底栏那句留在原地，屏幕上同时出现两个名字指同一颗按钮。）")


def test_the_debt_table_does_not_rot():
    """⭐ 反向断言：修好了就得从表里删掉，否则这张表会变成博物馆。"""
    healed = sorted(KNOWN_HARDCODED - _offenders())
    assert not healed, (
        f"这些已经不再硬编码了，把它们从 `KNOWN_HARDCODED` 里删掉：{healed}\n"
        "（棘轮只许收紧 —— 留着等于给未来的回归留了一个免检位。）")
