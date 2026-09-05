# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""专家音频四页：**同一个动作，同屏好几个入口**（RN-102 家族）。

## 实测（2026-09-04 批 46，四页各出一张图数出来的）

| 页 | 重复 |
|---|---|
| `audio_health` | 「立即体检」×2（卡内 + 底栏）、「一键修复（保守）」×2 |
| `audio_import_wizard` | 「扫描目录」×2、「打开资源目录」×2 |
| `audio_task_panel` | 「刷新」（卡内） vs 「刷新历史」（底栏）|
| `audio_replay` | 刷新 **×3**（筛选卡 / 底栏 / 空状态）、「导出 JSON」×2 |

⭐ 债表 `BAR_CARD_DUPLICATE_ACTIONS` 早就把这四页记全了（11 处），
而它是一条**只许变少**的棘轮 —— 它不会催人去清，只会拦住变多。
⭐⭐ **一张存量债表能防止事情变坏，但它不会让事情变好。**

## ⚠⚠ 这份判据第一版按**文案词**判重复，当场误报

第一版把按钮文案归一到动作词（「导入」「刷新」…），于是
`audio_import_wizard` 的「一键导入（保守）」和「把未识别音频导入为新风格…」
被判成重复 —— 而后者绑的是 `_classify_unrecognized`，**是另一个动作**。

⭐⭐ **一个名字同时属于两个完全不同的东西时，按名字分类必然出错**
（批 45 刚记过一次：`critical` 同时是 `logger` 和 `QMessageBox` 的方法名）——
而我在下一批的判据里又犯了同一个错。
⇒ 改成按**绑定的方法**判：方法名是精确的，文案不是。

## 分工（⭐ 两条判据看见的是不同的半边）

- 「**底栏 vs 卡内**」那一半由 `test_one_action_one_entrance.py` 的债表判据管
  （它已经是按方法判的）—— 这里**不重复造第二条**。
- 这份文件管它看不见的两半：
  ① **卡内自己**的重复（`audio_replay` 实测刷新有三个入口，全在卡内）；
  ② 底栏那颗主按钮**随状态变身**（RN-506 那个形态，四页全中）。

## ⭐ 空状态那颗按钮答非所问

`audio_replay` 空状态的文案是「当前筛选条件下还没有音频事件结果，
**可以先放宽筛选条件**或等待新的事件写入」，而它下面那颗按钮写的是「立即刷新事件」
—— 一个**第三个**刷新入口，且不是那句话点名的出路。
⇒ 换成「清空筛选条件」：**空状态该给的是那句文案自己点名的动作。**
⛔ 不是撤掉了事（批 3 的空库引导先例：空状态要有直接出路，不能只留一段话）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
FAMILY = ("audio_health", "audio_import_wizard", "audio_task_panel", "audio_replay")


def _bound_methods_in_cards(page_id: str) -> dict[str, int]:
    """卡内每个 `clicked.connect(self._foo)` 绑的方法 → 出现次数。

    ⚠ 只认**直接写出方法引用**的那一形（同债表判据的口径）：
      lambda / partial 认不出的一律不算重复 —— 失效方向朝「不报」那边倒，
      因为这条判据的后果是「去删一颗按钮」，误报的代价比漏报大。
    ⚠ 底栏那几颗走 `configure_primary/secondary`，不在这里 —— 它们由债表判据管。
    """
    src = REPO / "pages" / f"{page_id}_page.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "connect" and len(n.args) == 1):
            continue
        owner = n.func.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == "clicked"):
            continue
        arg = n.args[0]
        if isinstance(arg, ast.Attribute):
            seen[arg.attr] = seen.get(arg.attr, 0) + 1
    return seen


@pytest.mark.parametrize("page_id", FAMILY)
def test_no_action_has_two_buttons_inside_the_cards(page_id):
    """① 卡内自己不许重复 —— `audio_replay` 实测刷新有**三个**入口。

    ⚠ 这条和债表那条分开：债表比的是「底栏 vs 卡内」，
      看不见**同在卡内**的那两颗。
    ⭐ **一条判据的分母写成「两个容器之间」时，容器里面的重复它看不见。**
    """
    bound = must_scan(_bound_methods_in_cards(page_id),
                      f"{page_id} 卡内 clicked.connect 绑的方法", least=1)
    dup = {m: n for m, n in dict(_bound_methods_in_cards(page_id)).items() if n > 1}
    assert not dup, (
        f"{page_id}：同一个方法在卡内被绑了多次：{dup}\n"
        "⭐ 「刷新」「立即刷新事件」是同一个动作的两种说法 —— "
        "按文案找重复的判据看不见它们，按方法找的看得见。\n"
        f"（本页卡内共绑了 {len(bound)} 个方法）"
    )


#: **破坏性**动作：点下去会覆盖 / 删掉用户已有的东西。
#: ⭐ 判「主按钮能不能变身」的真正边界在这里 —— 不在「变不变」。
DESTRUCTIVE = ("恢复", "覆盖", "删除", "重置", "清空", "还原")


def _primary_labels(page_id: str) -> list[str]:
    """这一页给底栏主按钮派过的所有**文案字面量**（AST 扫，不跑页面）。

    ⚠⚠ 第一版是**运行时**判的（选中一行前后比文案），实测 **4 页里 2 页直接 skip**
    —— `audio_health` 与 `audio_import_wizard` 根本没有列表。
    ⭐⭐ **一条只在某个状态下才说话的判据，如果那个状态默认拿不到，
      它在门禁里就是沉默的** —— 而沉默和通过在报告上是同一个颜色。
    ⭐⭐⭐ **能用结构表达的不变量，别拿运行时去凑**（批 43 那条）。
    """
    src = REPO / "pages" / f"{page_id}_page.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    out: list[str] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "configure_primary" and n.args):
            continue
        first = n.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if first.value.strip():
                out.append(first.value.strip())
        else:
            out.append("<按状态算出来的>")
    return out


@pytest.mark.parametrize("page_id", FAMILY)
def test_the_primary_never_crosses_the_safe_destructive_line(page_id):
    """② 主按钮**可以**随状态换动作，但不许跨越「安全 ↔ 破坏性」那条线。

    ## ⚠⚠ 这条判据的命题在批 46 之内被推翻了一次，过程值得记

    第一版写的是「**主按钮的文案至多一种**」——照 RN-506（批 45 `config_snapshot`
    那颗把「创建快照」和「恢复选中」放在同一个像素上的按钮）直接推出来的。
    于是我把这四页的底栏主按钮全撤掉、在卡内各挑一颗「第一步」升为主按钮，
    **恒定不变**。

    **外审改完复跑 24 发全判高，逐页指出我挑错了：**

    | 页 | 我挑的 | 外审逐字说的 |
    |---|---|---|
    | `audio_task_panel` | 刷新 | 「最抢眼的紫色主按钮是**无实质产出的**『刷新』，点后毫无反馈」——空状态刷了还是空 |
    | `audio_import_wizard` | 扫描目录 | 「未选目录时『扫描目录』却是唯一高亮，极易诱导玩家开局盲点导致报错」|
    | `audio_health` | 立即体检 | 「已检出 17 项问题但主视觉仍高亮『立即体检』」|

    ⭐⭐⭐ **我把「这一页的第一步」当成了一个静态属性，而它取决于当前状态。**
      为了躲开「变身」，我用**恒定**换掉了**正确**。

    ⇒ 回到批 44 RN-450 的裁定：**那一颗紫的必须是当下的第一步**。
      而 RN-506 的要害从来不是「变身」本身，是它变成了一个**方向相反**的动作
      （多存一份 ↔ 覆盖当前全部设置）。
    ⭐⭐⭐ **规则不是「主按钮不许变」，是「它不许在安全和破坏之间变」。**
    """
    labels = must_scan(_primary_labels(page_id) or ["<没有底栏主按钮>"],
                       f"{page_id} 给底栏主按钮派过的文案", least=1)
    kinds = {any(w in t for w in DESTRUCTIVE) for t in labels
             if t != "<没有底栏主按钮>"}
    assert len(kinds) <= 1, (
        f"{page_id}：底栏那颗主按钮在**安全动作**和**破坏性动作**之间变身：{labels}\n"
        "⭐⭐⭐ 肌肉记忆记的是位置 —— 一个刚点过安全动作的人，"
        "在同一个位置按下去会按到破坏性的那一个（RN-506）。\n"
        "⚠ 而**在几个安全动作之间**跟着状态换，是对的：那一颗必须是当下的第一步。"
    )
