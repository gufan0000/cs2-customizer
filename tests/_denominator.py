# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""分母守卫：**先证明扫到了东西，再去断言「没问题」。**

## 为什么有这个文件（RN-469，批 35 立案 → 批 42 收口）

批 34 一次撞出三件同形的事，批 35 把它们扫成了一张 **77 条**的清单：
一个测试函数扫出一个集合、只对它做否定断言（`assert not offenders`），
**却没有任何一句话说这个集合不空**。

⭐⭐ **一条为某个缺陷而写的判据，可以在那个缺陷还没进分母的时候，绿着上线。**
而「分母为空」和「真的没问题」在测试报告上**一模一样**。

批 35 当时的裁定是「不逐条修，先配棘轮」（77 只许变少）。
⭐ 批 42 收口的理由是**机制性的，不是洁癖**：P5 共享层干的事
（搬控件、换名单、改容器类型）**正好就是清空分母** ——
在页面阶段这 77 条只是隐患，进 P5 它们是必然触发。

## 怎么用

```python
from _denominator import must_scan

def test_no_page_promises_what_it_cannot_do():
    pages = must_scan(sorted(PAGES.glob("*_page.py")), "pages/*_page.py")
    offenders = [p for p in pages if ...]
    assert not offenders, ...
```

⭐ 守卫要**贴着扫描写**，不要写在函数末尾 —— 分母空了就该在做任何判断之前停住。

## ⛔ 两条不许

1. ⛔ **不许**用 `if not seq: return` / `pytest.skip` 来"处理"空分母。
   跳过和通过在门禁上是同一个颜色 —— 那正是这条判据要防的东西。
2. ⛔ **不许**为了让 `test_judges_are_not_idling` 变绿而收窄它的 `SCAN_TOKENS`，
   那只是把判据从视野里挪走，不是给它补分母。

## 真的没有分母怎么办

有些函数命中扫描记号纯属误伤（比如它 `read_text()` 读一个**固定的单文件**，
根本没有"集合"这回事）。这时**不要**硬塞一个守卫，改成在函数 docstring 里
写一行以 `分母：` 开头的声明，说清为什么这条没有分母。
`test_judges_are_not_idling` 认这个声明。
⭐ 声明是给人读的，所以它必须**说出理由**，不是一句"无分母"。
"""
from __future__ import annotations

from typing import Iterable, TypeVar

T = TypeVar("T")


def must_scan(items: Iterable[T], what: str, least: int = 1) -> list[T]:
    """断言这次扫描**真的扫到了东西**，然后把它原样交回去。

    Args:
        items: 扫出来的集合（glob / walk / findChildren / 解析出的表行 …）。
        what:  它是什么，出错时要能让人立刻看懂**哪个分母空了**。
        least: 至少几个。默认 1；知道确切下界时给确切的数更好
               —— ⭐ `>= 1` 挡得住"全空"，挡不住"只剩一个"。

    Returns:
        `list(items)`（原顺序）。生成器也能安全地用两次。
        ⚠ **返回的是 list，不是原类型。** 需要 dict / set 的语义时，
        把它当成一句副作用来调（`must_scan(rows, "…")`），别拿返回值覆盖原变量 ——
        实测这一条当场踩了两次：`rows.items()` 变成 `list.items()`，
        以及下面那个更阴的字符串。
    """
    # ⛔ 字符串**永远不是分母**。它是可迭代的，所以 `must_scan("语音输出", …)`
    #   会"成功"，返回一串单字，并且把 `least=5` 读成「至少 5 个字」——
    #   一句 5 个字的文案就能让它通过，而调用方拿回去的已经不是那句话了。
    # ⭐⭐ **一个把「明显用错」变成「静静通过」的守卫，比没有守卫更糟** ——
    #   没有守卫至少不会伪造一个合格的分母。
    if isinstance(items, (str, bytes)):
        raise TypeError(
            f"must_scan 收到了一个字符串（{what}）—— 字符串不是分母。\n"
            "⇒ 要量的多半是「切出来的词/行/控件」，先切再交给它。")
    got = list(items)
    assert len(got) >= least, (
        f"分母为空：{what} —— 只扫到 {len(got)} 个，至少要有 {least} 个。\n"
        "⭐ 这条判据接下来要做的是否定断言，分母一空它必然全绿，\n"
        "  而「分母为空」和「真的没问题」在测试报告上一模一样。\n"
        "⇒ 先查扫描路径/过滤条件对不对，**不要**把这句守卫删掉。"
    )
    return got
