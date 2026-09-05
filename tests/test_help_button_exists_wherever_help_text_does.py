# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-001b：**一份写好的帮助文案，不会自己长出那颗「?」。**

## 我是怎么撞到这一条的

批 45 要补 `about` 的帮助文案（RN-001b：28 页里 4 页没有）。
第一步往 `ui_help_panel.PAGE_HELP_TEXTS` 里加了 `about` 的一整段 ——
`test_ui_help_panel_texts` 绿、`test_help_copy_names_real_controls` 绿、
帮助文案覆盖面从 24 页涨到 25 页。**而屏幕上那颗「?」根本没出现。**

成因：帮助面板不是按表自动装的，是**每一页自己调一次**
`install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["<page>"])`。
表里多一条键，只是多了一段没人读的文本。

⭐⭐⭐ **一个"补齐清单"的动作，可能只补齐了清单，而没有补齐它指向的那件事。**
⭐ 而这次是**出图看了一眼**才发现的 —— 三条相关判据没有一条会红，
  因为它们量的都是**那张表**，没有一条量屏幕。
  （同批 44 那条：判据算的是一个和屏幕无关的量。）

## 这条判据的形状

分母是 `PAGE_HELP_TEXTS` 的键（**表说有，就必须真有**），
断言落在**真窗里那一页上有没有一颗 `HelpButton`**。
⇒ 方向是从「声明」指向「事实」，而不是反过来 ——
反过来那一向（有按钮却没文案）装不出来，`install_help_panel` 要求传文案。

⚠ 缺文案的那 3 页（`audio_import_wizard` / `audio_task_panel` / `audio_replay`）
**不在分母里**：它们的键还没进表，本条对它们无话可说 —— 那是批 46~48 的活。
⭐ **明写出来，不粉饰**：这条判据管的是「已声明的那些页」，不是「所有页」。
"""
from __future__ import annotations

import pytest

from _denominator import must_scan

# ⚠ 主窗夹具用共享那一份，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

main_window = _shared_main_window


def _declared_pages(main_window):
    from ui_help_panel import PAGE_HELP_TEXTS

    keys = must_scan(sorted(PAGE_HELP_TEXTS), "PAGE_HELP_TEXTS 里声明了帮助文案的页",
                     least=20)
    # `basic` 内联在 gui_widget 里、没有独立页类，主窗的页表里认不到它 ⇒ 不在分母。
    registered = set(main_window._page_names)
    return [k for k in keys if k in registered]


def test_every_page_with_help_text_shows_the_question_mark(main_window, qapp):
    """表里有这一页的帮助文案 ⇒ 那一页上必须真有一颗「?」。"""
    from ui_help_panel import HelpButton

    pages = must_scan(_declared_pages(main_window),
                      "既声明了帮助文案、又在主窗里注册了的页", least=20)
    missing, checked = [], 0
    for pid in pages:
        try:
            main_window.ensure_page_loaded(pid)
            main_window.show_page(pid, animated=False, force=True)
            qapp.processEvents()
        except Exception:                                  # noqa: BLE001
            continue                                       # 构造即起设备的页，跳过
        page = main_window.pages.get(pid)
        if page is None:
            continue
        checked += 1
        if not page.findChildren(HelpButton):
            missing.append(pid)

    assert checked >= 20, (
        f"只量到 {checked} 页 —— 分母塌了，这条判据在空转")
    assert not missing, (
        "这几页**声明了**帮助文案，而屏幕上没有那颗「?」：\n  "
        + "\n  ".join(missing)
        + "\n⭐ 帮助面板不是按表自动装的 —— 那一页得自己调一次 "
          "`install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS[<page>])`。\n"
        + "⭐⭐⭐ 一份写好的帮助文案，不会自己长出那颗按钮。"
    )


def test_the_coverage_number_only_grows(main_window):
    """⭐ 棘轮：帮助文案的覆盖面只许变多。

    ⚠ 下界取**当下实测值**，不取一个宽松的数 —— 批 45 刚踩过：
      一个比实际值低的下界，等于允许悄悄少掉几个。
    ⚠ 剩下 3 页（专家音频家族）归批 46~48 的 C4；那一批做完这个数应当变成 25。

    ⚠⚠ **第一版数的是 `len(PAGE_HELP_TEXTS)`，破坏验证当场判它假绿**：
    把键 `"about"` 改名成 `"about_disabled"`，**字典长度一个不少**，
    而那一页的帮助文案实际上已经没人认领了
    （下面那条按 `_page_names` 过滤的判据会把它静默丢掉）。
    ⭐⭐ **一条只数个数的棘轮，可以被「改个名字」满足** ——
      同批 41 那条「判据可以被写错格子满足」：**它数的东西和它想守的东西不是一回事。**
    ⇒ 改成数「**真的对应一个已注册页面**的键」。
    """
    from ui_help_panel import PAGE_HELP_TEXTS

    registered = set(main_window._page_names)
    # `basic` 内联在 gui_widget 里、没有独立页类 ⇒ 它的键对得上产品但不在页表里。
    real = {k for k in PAGE_HELP_TEXTS if k in registered or k == "basic"}
    orphans = sorted(set(PAGE_HELP_TEXTS) - real)
    assert not orphans, (
        f"这些帮助文案的键对不上任何页面：{orphans}\n"
        "⭐ 一段没人认领的帮助文案不会报错 —— 它只是让那一页的「?」安静消失。")
    assert len(real) >= 25, (
        f"帮助文案只剩 {len(real)} 页（批 45 实测 25 页，含 basic）——\n"
        "⭐ RN-001b 的分母是 28 页；少掉一页不会有任何东西报错。"
    )


def test_the_three_pages_still_owed_are_named(main_window):
    """⭐ 把「还欠哪几页」写成机器读得到的东西，而不是留在档案里。

    ⚠ 这一条**故意会在补完的那天变红** —— 那时候把它改成 0，
      或者换成「28 页全覆盖」的正面断言。
    ⭐ 一个明确会过期的断言，比一句「还剩几页」的散文更难被忘掉。
    """
    from ui_help_panel import PAGE_HELP_TEXTS

    registered = must_scan(sorted(main_window._page_names), "主窗注册的页面", least=20)
    owed = sorted(set(registered) - set(PAGE_HELP_TEXTS))
    expected = ["audio_import_wizard", "audio_replay", "audio_task_panel"]
    if owed == expected:
        pytest.skip(f"仍欠这 3 页（归批 46~48 的专家音频家族）：{owed}")
    assert not owed, (
        f"欠帮助文案的页变了：现在是 {owed}，而在册的是 {expected}。\n"
        "⭐ 变多了 ⇒ 有人删掉了某一页的文案；\n"
        "  变少了 ⇒ 补上了，把这条判据改成正面断言（28 页全覆盖）并删掉这段 skip。"
    )
