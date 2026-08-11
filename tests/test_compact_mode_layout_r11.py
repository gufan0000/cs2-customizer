# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R11 / UP-100 / UP-102：紧凑模式下修好的三处，判据钉住结构。

排版审计（`scripts/layout_overflow_audit.py --compact`）已经能量出这三处缺陷，
但它跑一次要建 26 个页面 × 8 主题 × 3 字号，进不了逐文件的单测矩阵。
所以这里用结构判据做**快门**：审计负责发现，判据负责别让它回来。

三处的来历都写在各自的测试里，一句话版：紧凑模式（860×640，用户点一下界面上的
「切换紧凑/完整模式」按钮就进）的内容可视区只有 590px，比完整模式少 160px，
而 R0~R10 十一轮从没跑过这一档。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tree(rel: str) -> ast.Module:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree(rel)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{rel} 里找不到 {name}")


def _calls_named(node: ast.AST, name: str) -> list[ast.Call]:
    """名字（或点号末段）等于 `name` 的调用节点。

    走 AST 不看文本：这个项目已经因为"用子串判断调用"栽过 5 次，
    最近一次就是 R11 自己——判据被产品代码 docstring 里引用的旧实现骗了。
    """
    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        got = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if got == name:
            out.append(sub)
    return out


# ------------------------------------------------------- UP-100 「我的预设」


def test_my_presets_row_can_switch_direction():
    """那一行必须是能换向的 `QBoxLayout`，而不是钉死的 `QHBoxLayout`。

    实测：下拉框钉了 220px 下限 + 5 个按钮，这一行最小宽 **883px**；
    紧凑模式的内容视口只有 854px，于是 `preset_center` 整页横向滚动，
    8 主题 × 3 字号 **24 个组合全中**，溢出 58~61px。
    """
    fn = _func("widgets/my_presets_section.py", "build_my_presets_card")
    boxes = _calls_named(fn, "QBoxLayout")
    assert boxes, (
        "「我的预设」那一行不再用 QBoxLayout —— 换不了向，"
        "紧凑模式下 883px 的一行会把 854px 的视口顶穿（UP-100）"
    )


def test_my_presets_has_a_direction_switcher_and_the_page_calls_it():
    """光有 QBoxLayout 不够——还得真有人在 resize 时切它。

    ⚠ `preset_center` 早就有 `_update_compact_layout`，但它**只切了工作台三列**，
    漏了「我的预设」这一行。所以这条断言的是"两处都切"，不是"有换向逻辑"。
    """
    mixin = _tree("widgets/my_presets_section.py")
    names = {n.name for n in ast.walk(mixin) if isinstance(n, ast.FunctionDef)}
    assert "_update_my_presets_layout" in names, "mixin 里没有换向方法"

    page_fn = _func("pages/preset_center_page.py", "_update_compact_layout")
    assert _calls_named(page_fn, "_update_my_presets_layout"), (
        "preset_center 的 _update_compact_layout 没有调 _update_my_presets_layout——"
        "工作台切了、「我的预设」没切，正是 UP-100 的原样"
    )
    resize = _func("pages/preset_center_page.py", "resizeEvent")
    assert _calls_named(resize, "_update_compact_layout"), (
        "resizeEvent 不再调换向逻辑，等于换向永远不会发生"
    )


# ------------------------------------------------- UP-100 special_sound 页签


def test_special_sound_tabs_have_a_single_scroll_root():
    """四个页签的内容都必须在滚动区**里面**，不许把头部卡钉在外面。

    「回合」「投掷物」两个页签原本是 `layout.addWidget(header_card)` 后再放滚动区。
    完整模式下看不出问题（可视 750px 富余），紧凑模式下页签内容区只剩 186px，
    而「回合」的头部卡自己最小高就是 169px（1.25 档 188px）——
    滚动区被挤成**视口只有 62px 的舷窗**，里面装着 542px 的内容。
    审计报的"超出 71px"读起来像"滚一下就好"，实际是没法用。

    另外两个页签（C4 / 血量警告）本来就是这个形状，所以这也是把四个页签拉齐。
    """
    src = (ROOT / "pages" / "special_sound_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for name in ("_create_grenade_tab", "_create_c4_tab",
                 "_create_health_tab", "_create_round_tab"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        # 页签根布局（变量名 layout / outer）上不许再挂 header_card
        for call in _calls_named(fn, "addWidget"):
            f = call.func
            owner = getattr(f.value, "id", "") if isinstance(f, ast.Attribute) else ""
            arg = call.args[0] if call.args else None
            argname = getattr(arg, "id", "")
            if owner in ("layout", "outer") and argname.endswith("header_card"):
                offenders.append(f"{name}:{call.lineno}")
    assert not offenders, (
        "这些页签又把头部卡挂回了滚动区外面：" + ", ".join(offenders) +
        "。紧凑模式下它会把滚动区挤成几十像素的舷窗（UP-100）。"
    )


# ------------------------------------------------------- UP-102 flash Tab 序


def test_flash_basic_tab_order_is_pinned():
    """flash 页「基础设置」的 Tab 顺序必须显式钉死。

    网格里「过渡方式」在第 0 行第 3 列、「背景不透明度」在第 1 行，
    但**创建顺序**是 颜色 → 不透明度 → 过渡，而 Qt 的默认焦点链跟的是创建顺序、
    不是网格位置。于是按 Tab 会从「背景颜色」跳到下一行的滑块，再跳回上一行的
    两个复选框。排版毫无异常，坏的只有键盘顺序——和 R8d 在 music 页查出的
    那 2 处是同一类。

    ⚠ 顺带钉住位置：`setTabOrder` 必须排在 `addLayout(controls_grid)` **之后**。
    写在前面时这些控件还没有父控件，等布局挂到卡片上会按插入顺序**重建焦点链**，
    把 setTabOrder 的结果冲掉——第一版就是这么写的，判据照旧报红。
    """
    fn = _func("pages/flash_page.py", "_create_basic_tab")
    orders = _calls_named(fn, "setTabOrder")
    assert len(orders) >= 3, (
        f"flash 页「基础设置」的 setTabOrder 只剩 {len(orders)} 处（应 ≥3）——"
        "Tab 顺序会退回按创建顺序跳行（UP-102）"
    )
    add_grid = [
        c for c in _calls_named(fn, "addLayout")
        if c.args and getattr(c.args[0], "id", "") == "controls_grid"
    ]
    assert add_grid, "找不到 addLayout(controls_grid) —— 判据的前提变了，先去看代码"
    assert min(c.lineno for c in orders) > add_grid[0].lineno, (
        "setTabOrder 写在了 addLayout(controls_grid) 之前。"
        "那时控件还没有父控件，reparent 会重建焦点链把它冲掉——等于没写。"
    )
