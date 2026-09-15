# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""调用点写下的宽度不许是一句死声明（RN-442 / X2）。

## 这条判据在防什么

⭐⭐⭐ 规范的下限写在样式表里（`QPushButton#secondaryButton { min-width: 118px }`），
   调用点的意图写在 `setFixedWidth(72)` 里 —— **Qt 在 min > max 时取 min**，
   于是调用点那一行**不产生任何效果，也不报错**。
   实测批 61：**656 颗按钮里 133 颗 `min > max`**，差 6~46px
   （`gun_sound` 六颗「测试」min=118 / max=72）。

## 修的过程里被推翻过三次（都记在这儿，免得下次再走一遍）

① **立案点名的那一行不是承重的那一行。** RN-442 原文指 `ui_style_applier._style_button`；
   而实测把样式表里那条 `min-width` 临时改成 10px，这些按钮的 min **当场从 118 掉到 72**
   ⇒ 承重的是样式表。Python 侧怎么夹都会被随后的 polish 覆盖回去。
② **「把重复的那一个删掉」只有在剩下那个真的在工作时才成立。** 我删掉样式表那三条
   `min-width`，min>max 当场清零 —— 而全站按钮的下限也一起没了（min 分布从
   「一堵 118 的墙」散成 72/80/84/…），因为 `_style_button` 实测跑不到多数按钮上。
③ **属性选择器压不过 ID 选择器。** `QPushButton[fp_compact="true"]` 敌不过
   `QPushButton#secondaryButton`，必须逐个点名。

⇒ 最后的形状：样式表留下限 + 一条 ID 点名的紧凑变体；
  `ui_style_applier.mark_compact_buttons()` 在**样式表落地之后**统一打属性
  （`gui_widget._apply_style` 与 `_load_page` 各调一次）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QAbstractButton, QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    """⚠⚠ 2026-09-06 批 66 换路：原来走 `ensure_page_loaded` + 一次 `processEvents`，
    **窗口从不 `show()`**。批 63 已经发现两条路量出不同的数
    （那条 0 颗 / `show_page` 14 颗），而判据一直站在没有缺陷的那一条上。

    ⭐⭐⭐ 更要命的是**时机**：`advanced` / `magnifier` 的锚点条由
    `QTimer.singleShot(0, self._build_anchor_chips)` 建，只 `processEvents()` 一次
    量到的是 **样式表还没 polish 上去** 的那一瞬（min=max=26，看起来完全正常），
    多等几拍才是真相（min=34 / max=26）。
    ⇒ 批 66 开工时我拿一支「量早了」的探针，差点把这条活着的 S3 判成不成立。
    ⭐ **RN-547 那句「只要样式表还会再 polish 一次」，对尺子同样成立。**

    ⇒ 现在：真 `show()`、走 `show_page`、每页多转几拍。
    """
    import gui_widget
    from PySide6.QtCore import Qt

    w = gui_widget.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)   # ⛔ 不打扰前台
    w.resize(1280, 800)
    w.show()
    app.processEvents()
    for pid in list(w._page_names):
        try:
            w.show_page(pid, animated=False)
        except Exception:  # noqa: BLE001  某些页在测试环境里建不起来，跳过即可
            pass
        for _ in range(4):     # 懒建的锚点条 / 帮助面板要等 singleShot(0) 那一拍
            app.processEvents()
    yield w
    w._force_exit = True
    w.close()


def _buttons(win):
    out = []
    for pid in list(win._page_names):
        page = win.pages.get(pid)
        if page is None:
            continue
        out.extend((pid, b) for b in page.findChildren(QAbstractButton))
    return out


def test_the_denominator_is_the_whole_app(win):
    """分母守卫：页面建不出来时这条判据必须喊出来，而不是安静地全绿。"""
    btns = _buttons(win)
    assert len(btns) >= 400, (
        f"只量到 {len(btns)} 颗按钮（批 61 实测 656）—— 分母塌了，这条判据在空转")


def test_no_button_is_wider_than_its_caller_declared(win):
    """min > max 的按钮一颗都不许有。"""
    bad = [(pid, b.objectName(), (b.text() or "")[:10],
            b.minimumWidth(), b.maximumWidth())
           for pid, b in _buttons(win)
           if b.minimumWidth() > b.maximumWidth()]
    assert not bad, (
        f"这 {len(bad)} 颗按钮的 min 大于 max，Qt 会取 min —— "
        "调用点写下的宽度是一句死声明：\n  "
        + "\n  ".join(f"[{p}] {name} {txt!r} min={mn} max={mx}"
                      for p, name, txt, mn, mx in bad[:12]))


def test_the_spec_floor_still_applies_to_unconstrained_buttons(win):
    """反向守卫：**别把 min>max 修成「谁都没有下限」。**

    修这条时我真的这么干过一版（删掉样式表里的 `min-width`）——
    min>max 当场清零，而全站按钮的下限一起没了。
    ⇒ 没被调用点限宽的命名按钮，必须还站在规范下限上。

    ⚠⚠⚠ **批 67：这条判据原来拿的是一个魔数 `>= 110`，而那个 110 是照着
    「屏幕上那个 118」挑的 —— 也就是照着 RN-551 那个缺陷的量级挑的。**
    RN-551 把单位修对之后（QSS 的 `min-width` 量内容盒，令牌说的是整个控件），
    下限从 118 回到令牌自己的 **80**，这条判据当场判红 **0/24**，
    报的却是「按钮丢了规范下限」—— 而下限一点没丢，是尺子刻在缺陷上。
    ⭐⭐⭐ **一条拿「当前屏幕上是多少」写死的判据，会把缺陷本身固定成验收标准；
      等缺陷修好那天，它报的是一次退步。**（同批 40 那条「绿在我选的参数上」的反面）

    ⚠⚠⚠ **而我第一版的修法（把 110 换成令牌 80）当场被回退验证判成假绿。**
    实测删掉样式表那条下限之后，`secondaryButton` 的 `minimumWidth` 分布是
    **112×7 / 116×2 / 148×1 / 80×6 / 96×1** —— ⭐⭐⭐ **下限没了，按钮是变**宽**的**
    （各自按文字自然宽度散开），于是任何写成「≥ 下限」的断言**结构上永远看不见它**。
    老那个 `110` 只是靠「80 < 110」歪打正着地兜住了剩下那几颗小的。
    ⇒ 真正的不变量不是「有多宽」，是**「是不是一堵墙」**：
      同一个 objectName、没被调用点限过宽的那些按钮，`minimumWidth` 必须
      **压倒性地是同一个数，而那个数就是令牌**。
      有下限：**80 × 17（一堵墙）**；没下限：众数 112 只占 7/17。
    ⭐ **一个「被删掉」的约束，未必让数变小 —— 但一定让它变散。**
    """
    from collections import Counter

    from ui_design_system import get_design_system

    floor_spec = get_design_system().button.primary_min_width
    # ⚠ **逐个 objectName 看**：一个类型的下限被抹掉，会被另外两个的达标率盖过去
    #   （破坏验证第一版就是这么假绿的 —— 只删了 #secondaryButton 那一条，
    #   而 primary/danger 还站着，总体达标率照样过 80%）。
    by_name = {}
    for _pid, b in _buttons(win):
        name = b.objectName()
        if name not in ("primaryButton", "secondaryButton", "dangerButton"):
            continue
        if b.maximumWidth() <= 10000:      # 调用点限过宽的不算
            continue
        by_name.setdefault(name, []).append(b.minimumWidth())
    assert len(by_name) >= 2, f"只找到 {sorted(by_name)} 这几类 —— 分母塌了"
    bad = []
    for name, floors in sorted(by_name.items()):
        if len(floors) < 5:
            continue
        modal, hits = Counter(floors).most_common(1)[0]
        if modal != floor_spec or hits < len(floors) * 0.8:
            bad.append(
                f"{name}: 众数是 {modal}（{hits}/{len(floors)}），而令牌写的是 {floor_spec}"
                f"；实测分布 {dict(sorted(Counter(floors).items()))}")
    assert not bad, (
        "这几类没被限宽的按钮不再是「一堵墙」——规范下限没在起作用：\n  "
        + "\n  ".join(bad)
        + "\n⭐ 别把 min>max 修成「谁都没有下限」（批 62 那一版就是这么错的）。"
        + "\n⚠ 注意方向：下限没了按钮会变**宽**（各自按文字散开），"
        "所以判「有没有下限」要看**散不散**，不能看「够不够宽」。")


#: ⚠⚠ 这里原来挂着「`anchorChip` 存量 14」—— 而**判据走的那条路上它是 0**。
#: 实测两条加载路径量出不同的数：`ensure_page_loaded`（本判据用的）**0 颗**，
#: `show_page`（用户真走的）还剩 **14 颗 `anchorChip`**。
#: ⭐⭐⭐ **两条加载路径量出不同的数，而判据只站在其中一条上。**
#: ⇒ 这里按看得见的那条判 **0**；另一条路上那 14 颗记在 RN-547，归批 64。


def test_no_button_is_taller_than_its_caller_declared(win):
    """RN-547：`min-height > max-height` 的按钮 —— 同一个机制换个轴。

    实测批 62：**161 颗**（比宽度那 133 颗还多），`helpCloseButton` 调用点写 24px
    实际 40px（高 67%）。批 63 把标记**推迟到事件循环下一拍**之后降到 **14**。
    ⭐⭐⭐ 同一个顺序问题绊了四次：`_style_button` / `_load_page` /
    `install_help_panel` / `show_page` —— **只要样式表还会再 polish 一次，
    任何「提前打的标记」都会被覆盖**。⇒ 「什么时候」比「在哪儿」更要紧。
    """
    bad = [(pid, b.objectName(), (b.text() or '')[:8],
            b.minimumHeight(), b.maximumHeight())
           for pid, b in _buttons(win)
           if b.minimumHeight() > b.maximumHeight()]
    assert not bad, (
        f"这 {len(bad)} 颗按钮的 min-height 大于 max-height，Qt 会取 min：\n  "
        + "\n  ".join(f"[{p}] {n} {t!r} min={mn} max={mx}"
                      for p, n, t, mn, mx in bad[:12]))
