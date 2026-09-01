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
#: ⭐ 批 37（`account` 关档）⇒ **18**。而这一页清掉的**不止**这一份：
#:   同一页上还有两枚 `header_badge` / `connection_badge`，形态一模一样
#:   （构造期 `hide()`、全仓无人 `show()`、由三条路径持续 `setText` + 换 tone），
#:   而这条棘轮**一枚都没数过** —— 它按属性名找 `*summary_label*`，那两枚叫「徽章」。
#:   ⭐⭐ RN-458（`music_summary_label` 靠改名躲开）之后，同一件事换了个方式又发生一次：
#:   **上次是同一个东西改了名，这次是同一个病换了个器官。**
#:   ⇒ 批 37 另配了一条**按屏幕**判的：不问它叫什么、怎么造出来的，
#:     只问「它在屏幕上吗、它身上有字吗」。两条都留 ——
#:     这一条查的是**全仓静态分布**（含从没被构造过的页），
#:     那一条查的是**运行时的那一屏**，谁也不包含谁。
#:     ⚠ 这里**故意不点那条判据的文件名**：它住在账号页那一组里，
#:       而账号页不在派生的功能子集里 ⇒ 点了名，子集仓就会多一句
#:       指着不存在文件的话。⭐ 同批 38 那一页的主题：**一句话在哪儿为真，
#:       取决于它周围有什么** —— 而同步管道会把它搬到一个周围不一样的地方。
#: ⭐ 批 38（`preset_center` 动刀）⇒ **17**。这一份的活法和 music 那一份同形：
#:   `test_tool_pages_ui_polish` 里两条断言按着它（一条要求它 `isHidden()`，
#:   另一条逐字规定了它的 tooltip 里得有「覆盖」两个字）。
#:   ⭐⭐ **一个死控件活下来的机制，是有人给它写了判据** —— 这是第三个实例
#:   （RN-084 → account 两枚徽章 → 这一份），而三次的形态完全一样：
#:   判据不是拦住了它，是**替它续了命**。
MAX_REMAINING = 17


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
