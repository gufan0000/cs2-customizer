# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-638（批 97）：术语表（惯例 §5，RN-182）里 ⛔ 的两个用法不许回到用户眼前。

- `special_sound`：「模块已启用 / 模块已关闭」「模块 · n/4」⇒ **功能**；
- `preset_center`：「应用精选包?」⇒ **应用精选预设?**（包 = 流通形态，预设 = 一整套设置的快照）。

判据扫的是 **AST 里的字符串常量**（docstring 与注释不算 —— 那是在讨论这个词，不是给用户看）。
⭐ 一条禁止某种写法的判据，会连同「讨论那种写法」一起禁掉 —— 所以只看会显示出来的常量。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _user_strings(src: str) -> list[str]:
    """会显示出来的字符串常量：排除 docstring（Expr 位置上的 Constant）。"""
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                doc_ids.add(id(node.body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            out.append(node.value)
    return out


@pytest.mark.parametrize("rel, banned", [
    ("pages/special_sound_page.py", "模块"),
    ("pages/preset_center_page.py", "应用精选包"),
])
def test_the_banned_word_is_not_in_any_user_string(rel, banned):
    from _denominator import must_scan

    src = (ROOT / rel).read_text(encoding="utf-8")
    strings = must_scan(_user_strings(src), f"{rel} 里会显示出来的字符串常量", least=30)
    hits = [s for s in strings if banned in s]
    assert not hits, (
        f"{rel} 里还有 {len(hits)} 个会显示出来的字符串含「{banned}」：{hits[:5]}\n"
        "⇒ 术语表（惯例 §5）：模块 ⛔ 不再当用户可见词；包 ≠ 预设（RN-638）")


def test_the_replacement_words_are_really_there():
    """阳性对照：换上去的词得在，不然上面那条可能绿在「整段文案被删了」上。"""
    special = (ROOT / "pages" / "special_sound_page.py").read_text(encoding="utf-8")
    preset = (ROOT / "pages" / "preset_center_page.py").read_text(encoding="utf-8")
    assert "功能已开启" in special and "功能已关闭（配了也不会响）" in special
    assert 'f"功能 · {enabled_modules}/4"' in special
    assert "应用精选预设?" in preset


def test_the_scanner_sees_a_planted_string_but_not_a_docstring():
    """自检：扫描器认得字符串常量、放过 docstring（否则上面那条会连讨论一起禁）。"""
    planted = 'def f():\n    """模块 在 docstring 里"""\n    return "模块 · 1/4"\n'
    assert _user_strings(planted) == ["模块 · 1/4"]
