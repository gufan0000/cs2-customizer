# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面说明文案必须是**写给玩家看的**，不是写给做界面的人看的（2026-08-16）。

外审在 8 个页面上独立指出同一件事：副标题写的是**版面决策**而不是功能。
例如「击杀音效页保持列表式效率，把分类切换和快速试听留在一屏里」——
玩家读完既不知道这功能干什么，也不知道第一步该做什么。
这类句子是设计笔记漏进了产品界面，属于客观错误，不是审美偏好。

判据用**词表**而不是人工复核：这类话有很稳定的说法
（"收在首屏"、"保持列表式效率"、"更省空间"、"像工具面板一样"…）。
词表命中即红，改文案的人自然会绕开这些说法。

⚠ 词表只加**描述版面/实现决策**的词，不要加正常功能词。
判据宁可漏也不能误伤——一条会误伤的判据，下一个人会直接把它删掉。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

#: 这些说法描述的是"界面怎么排"，不是"功能是什么"。
#: 每一条都来自真实出现过的文案，不是想象出来的。
LAYOUT_JARGON = (
    "收在首屏",
    "压在首屏",
    "留在首屏",
    "收进同一块",
    "收进一张",
    "保持列表式效率",
    "走紧凑列表",
    "更省空间",
    "像工具面板一样",
    "首屏判断会更直接",
    "卡片层级",
    "拆成清晰卡片",
    "压缩在首屏",
    "都在首屏完成",
)

#: 只看这些"面向用户的说明文案"参数/常量，不看普通字符串，避免误伤注释和内部文案。
COPY_KEYWORDS = ("description", "PAGE_LEAD", "PAGE_DESC", "subtitle")


def _iter_page_copy():
    """产出 (文件名, 行号, 文案)。只取 `description=`、`PAGE_LEAD = ` 这类。"""
    for path in sorted((ROOT / "pages").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                       # 语法坏了是别的判据的事
            continue
        for node in ast.walk(tree):
            # description="..." 这类关键字实参
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (kw.arg in COPY_KEYWORDS
                            and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)):
                        yield path.name, kw.value.lineno, kw.value.value
            # PAGE_LEAD = "..." 这类模块/类级常量
            elif isinstance(node, ast.Assign):
                name = getattr(node.targets[0], "id", "") or getattr(
                    node.targets[0], "attr", "")
                if (name in COPY_KEYWORDS
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    yield path.name, node.value.lineno, node.value.value


def test_page_copy_has_no_layout_jargon():
    offenders = []
    for filename, lineno, text in _iter_page_copy():
        hits = [w for w in LAYOUT_JARGON if w in text]
        if hits:
            offenders.append(f"{filename}:{lineno} 命中{hits} → {text[:46]}…")
    assert not offenders, (
        "这些页面说明写的是版面决策，不是功能说明。玩家读完不知道这功能干什么、"
        "第一步该做什么：\n  " + "\n  ".join(offenders))


def test_the_jargon_list_itself_still_matches_something():
    """⚠ 词表判据最容易烂掉的方式，是词表本身跟产品文案彻底脱节后
    **永远绿着**，看起来有人在看、其实什么都没看。

    这里拿一段真实出现过的原文做锚：它必须仍被词表逮住。
    """
    historical = "击杀音效页保持列表式效率，把分类切换和快速试听留在一屏里，适合高频逐项排查。"
    assert any(w in historical for w in LAYOUT_JARGON), (
        "词表已经逮不住当初那批文案了，说明它被改空或改跑偏了")


def test_page_copy_does_not_point_at_a_nonexistent_page():
    """文案里提到的页面名，必须真的在侧栏里存在。

    实测「…可先刷新风格列表再回首页启用」出现在 **5 个页面**，
    而侧栏里**从来没有叫「首页」的东西**（那一页叫「基础设置」）。
    """
    nav_titles = _sidebar_titles()
    ghosts = []
    for path in sorted((ROOT / "pages").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"回首页|去首页|首页启用", text):
            line = text[: m.start()].count("\n") + 1
            ghosts.append(f"{path.name}:{line}")
    assert "首页" not in nav_titles, "侧栏现在真有「首页」了，请更新本判据"
    assert not ghosts, (
        "这些文案让用户「回首页」，但侧栏里没有叫「首页」的页面"
        f"（应为「基础设置」）：{ghosts}")


def _sidebar_titles():
    """从 `gui_widget.py` 的 nav_groups 里静态取出侧栏显示名。

    走 AST 而不是跑 GUI：这条判据只关心文案与导航名对不对得上，
    没必要为此建一个主窗口。
    """
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    titles = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", "") == "nav_groups":
            for group in node.value.elts:
                for item in group.elts[1].elts:
                    titles.add(item.elts[1].value)
    assert titles, "没能从 gui_widget.nav_groups 解析出侧栏条目，判据失效了"
    return titles
