# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-009：建出来就 `hide()`、再也没人显示的 `summary_label`，只许变少。

**它是怎么活下来的**：每一页都在状态卡里放一个 `summary_label`，
`__init__` 里 `hide()` 一次，此后每次状态同步都给它 `setText(detail_text)`
（40~98 个字）—— 但**全仓没有任何一处**让它再显示回来。
离屏实测 6 个页面，`isVisible()` 全是 False。

Qt 的 `hide()` 是"显式隐藏"：此后父窗口再 `show()` 也不会把它带出来。
所以那行 `setText` 从写下那天起就没有任何人看得到 —— 它不报错、不崩溃、
不影响功能，只是白算。这类东西**只能靠扫描发现**，读代码时它看着完全正常。

判据做成**棘轮**而不是一刀切：21 处不可能在一个提交里安全清完，
而逐页翻新时顺手清掉自己那一份是最稳的。所以这里只钉死"只许变少"，
并拦住新页面再抄这个写法。

⚠ 名单减少时**必须同步改小 `MAX_REMAINING`**，否则棘轮就松了。
判据自己会提醒（数比上限小就报"该收紧了"）—— 棘轮不收紧等于没有棘轮。
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: 还没清理的页面数上限。**只许调小。**
#: 2026-08-17 起点 21，screen_effects 翻新时清掉 1 → 20，
#: M3-b 清掉 viewmodel + flash → 18。
#:
#: ⭐⭐⭐ **2026-08-31 批 32：这条棘轮从来就没数过 `music`。**
#: 它按属性名**精确匹配** `summary_label`，而 music 那一个叫
#: `self.music_summary_label`（另起了个名字，再 `self.summary_label = ` 别名一下）——
#: 于是「建了」认得出（别名那一行），「hide 了」认不出（hide 调在真名上），
#: 三个条件凑不齐 ⇒ **它一天都没进过分母**。
#: ⭐ **一个按名字找的判据，被一次改名绕开了；而改名的人并不是想绕开它。**
#:
#: ⇒ 分母改成「以 `summary_label` 结尾的属性」，重新实测起点 = **20**，
#:   而多出来的两页是 `music` 和 —— **`crosshair`，一个批 27 已经关档的页**。
#:   ⭐⭐⭐ 关档时核对过它名下还有没有在册条目，**从没核对过
#:   「那些按名字找的判据，找不找得到它」**。⇒ 批 32 清掉 music ⇒ **19**。
#: ⚠ 这个 19 比改之前那个 18 **大**，而这不是退步：分母换了，
#:   多出来的那一个（crosshair）是原来就在、只是没人看得见的。
#:   ⭐ **一条棘轮放宽分母之后数字变大，那个增量是它以前的盲区，不是新债。**
#: ⛔ crosshair 那一份不在本批动刀（它是别的页的账），但它现在**在分母里**了。
#:
#: ⚠ 另一半也是真的：music 那一个身上**挂着三条判据**（逐字断言它里面写了什么），
#:   删它要连着改三个测试文件。⭐⭐ **一个控件躲开了专门数它的那条判据，
#:   却被三条不为它而设的判据牢牢钉住** —— 数它的那条按**名字**找，找不到；
#:   钉住它的那三条按**用途**找，找得到。
#: ⚠ **本仓库（功能子集）的数不一样**：`account_page.py` 整个不在这里，
#:   所以完整产品的 19 在这边是 **18**。
#:   ⭐ 照闭源版的数字写死，在子集里不是「更严」，是「错」。
MAX_REMAINING = 18


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO,
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("拿不到 git 跟踪清单，跳过（宁可跳过也不假绿）")
    return [REPO / line for line in out.stdout.splitlines() if line.strip()]


def _is_summary_attr(attr: str) -> bool:
    """⚠ 批 32 之前这里是 `attr == "summary_label"`，于是 `music_summary_label`
    整整躲了两个月。**按名字找的判据，分母要按后缀收，不按全等收。**
    """
    return attr == "summary_label" or attr.endswith("_summary_label")


def _invisible_summary_labels() -> list[str]:
    """找出"建了、hide 了、却没人 show"的 `self.*summary_label`。

    ⚠ 三个条件要**逐个名字**分别成立，不许跨名字凑：
    music 那一份就是「`summary_label` 建了（别名那一行）+ `music_summary_label`
    hide 了」，全等匹配下两个条件挂在两个名字上，谁也凑不齐。
    """
    found = []
    for path in _tracked_python_files():
        try:
            src = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "summary_label" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        created: set[str] = set()
        hidden: set[str] = set()
        shown: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Attribute) and _is_summary_attr(t.attr):
                        created.add(t.attr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Attribute) and _is_summary_attr(owner.attr):
                    if node.func.attr == "hide":
                        hidden.add(owner.attr)
                    elif node.func.attr in ("show", "setVisible"):
                        shown.add(owner.attr)
        if (created & hidden) - shown:
            found.append(path.relative_to(REPO).as_posix())
    return sorted(found)


def test_invisible_summary_label_count_only_shrinks():
    remaining = _invisible_summary_labels()
    assert len(remaining) <= MAX_REMAINING, (
        f"又多了永不可见的 summary_label：现在 {len(remaining)} 处，上限 {MAX_REMAINING}。\n"
        "这个控件建出来就 hide()、全仓没人再让它显示，而每次状态同步还照给它算文本。\n"
        "状态详情已经由徽章 tooltip 和状态卡 tooltip 给出了，别再加一份看不见的。\n"
        + "\n".join("  " + p for p in remaining))


def test_ratchet_is_tightened_when_pages_are_cleaned():
    """清干净了就得把上限收紧——**棘轮不收紧等于没有棘轮**。

    这条是给"顺手清了却忘了改上限"兜底的：真实数掉到上限以下时它会红，
    逼着你把 `MAX_REMAINING` 改成新的真实数。
    """
    remaining = _invisible_summary_labels()
    assert len(remaining) == MAX_REMAINING, (
        f"实际只剩 {len(remaining)} 处，而上限还写着 {MAX_REMAINING} —— "
        f"请把 MAX_REMAINING 改成 {len(remaining)}，否则这道棘轮就白留了 "
        f"{MAX_REMAINING - len(remaining)} 格空档。")
