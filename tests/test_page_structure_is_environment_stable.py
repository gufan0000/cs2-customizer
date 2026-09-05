# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""结构指纹里有一小块是**跨环境不稳定**的，而它一直被当成稳定的。

## 怎么撞到的（2026-09-04 批 45）

`config_snapshot` 关档时新取了结构基线，本机 `run_tests` **238/238 全绿**，
推上去之后 **CI 红**：

    「config_snapshot」的结构与已关档基线对不上（2 处）：
      + 多出: {"type": "QAbstractButton", "name": "qt_tableview_cornerbutton", …}
      - 少了: {"type": "QAbstractButton", "name": "", …}

同一颗控件（`QTableWidget` 的角落按钮），**本机拿到空串、CI 上拿到 Qt 给的内部名**。

## ⭐⭐⭐ 为什么这一条值得单独立一个文件

本工程一直把指纹分成两半：**几何是环境相关的**（所以
`test_archived_pages_still_match_their_fingerprint` 配了环境签名守卫，
不是采基线那台机器就 skip），**结构是跨机器稳定的**（所以它没有那道守卫）。

这次证明**结构也有一小块不是**。
⭐⭐⭐ **一条「这一半是稳定的」的判断，可以在很久之后被一个内部控件推翻。**

⛔ 修法**不是**给结构判据也加环境守卫 —— 那会让它在 CI 上整个 skip，
而 CI 正是它最该说话的地方（本仓已有过「本机绿 / CI 红」三次，RN-135/140/141/142）。
⇒ 只把这一小块**归一**：`QAbstractButton` 是抽象基类，产品代码不会直接实例化它，
所以凡是这个类型的条目必然是 Qt 自己造的内部件。

## ⚠ 它为什么不在 `test_renovation_baselines.py` 里

那五个 `test_renovation_*` 文件按批次规划 v4 §四-2 **冻结新增测试函数**
（它们保护的是账本，不是产品）。这一条守的是**结构指纹机制本身在 CI 上还成不成立**，
不是账本 —— 我第一版顺手写进了那个文件，写完才想起自己定的规矩。
⭐ **一条规矩最容易被它的作者破，因为破它的那一刻看起来只是"顺手放在最近的地方"。**
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
BASELINES = REPO / "tests" / "baselines" / "renovation"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_qt_internal_widget_names_are_normalised():
    """那段归一化必须还在 —— 删掉它，下次就又是**本机绿 / CI 红**。"""
    import _page_structure as ps

    assert "QAbstractButton" in ps._QT_INTERNAL_TYPES, (
        "`QAbstractButton` 从 `_QT_INTERNAL_TYPES` 里没了 —— "
        "那颗表格角落按钮的 objectName 会重新进入结构基线，"
        "而它在本机是空串、在 CI 上是 `qt_tableview_cornerbutton`。\n"
        "⭐ 症状是**本机绿 / CI 红**，而那种失败最难在本机复现。")


def test_the_normalisation_does_not_swallow_product_widgets():
    """⭐ 反向守卫：归一化只该盖住 Qt 自己造的控件。

    ⚠ 没有这一条，上面那条可以靠「把 `_QT_INTERNAL_TYPES` 扩到 `QWidget`」变绿 ——
    而那等于把整份结构指纹的 `name` 字段挖空。
    ⭐ **一条要求「某段代码还在」的判据，需要一条反向守卫说清它允许到哪儿为止。**
    """
    import _page_structure as ps

    if not BASELINES.is_dir():
        pytest.skip("还没有任何结构基线")

    files = must_scan(sorted(BASELINES.glob("*/structure.json")),
                      "已入库的结构基线", least=10)
    normalised = []
    for f in files:
        for entry in json.loads(f.read_text(encoding="utf-8")):
            if entry.get("name") == "<Qt内部>":
                normalised.append((f.parent.name, entry.get("type")))

    stray = sorted({t for _p, t in normalised if t not in ps._QT_INTERNAL_TYPES})
    assert not stray, (
        f"这些类型的条目被归一成了 `<Qt内部>`，而它们不在名单里：{stray}\n"
        "⭐ 归一化只该盖住 Qt 自己造的控件；盖住产品控件就是把结构指纹挖了个洞。")

    # ⭐ 名单本身要收得住：它只该收**抽象基类 / Qt 内部件**，不许收产品在用的类型。
    产品在用 = set()
    for f in files:
        for entry in json.loads(f.read_text(encoding="utf-8")):
            if entry.get("name") not in ("", "<Qt内部>"):
                产品在用.add(entry.get("type"))
    overlap = sorted(set(ps._QT_INTERNAL_TYPES) & 产品在用)
    assert not overlap, (
        f"`_QT_INTERNAL_TYPES` 收了产品正在用的类型：{overlap}\n"
        "⭐ 那些类型的 objectName 是产品自己派的，归一掉就再也看不出它们变没变。")
