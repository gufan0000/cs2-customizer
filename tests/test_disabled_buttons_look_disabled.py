# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-150：一颗禁用的主按钮，看上去仍然是「可以点的品牌色」。

外审原话：「同一屏里两颗**都禁用**的按钮长得一个能点一个不能点」
（`screen_effects` 底栏「预览击杀」透明 / 「预览爆头」紫色填充）。

定点实测（`accent_primary=#7c3aed`，`bg_card=#1a1d27`）：

    次按钮 预览击杀   禁用 = (0, 0, 0)        ← 透明，露出底色
    主按钮 预览爆头   禁用 = (61, 36, 112)    ← #3d2470，一块紫色填充

而 `theme_manager` 里对**危险按钮**早就写过同一条原则（R7/D-06）：

> 红色的语义是「点下去会毁数据」，禁用的语义是「你点不了」，
> 两者同时出现是自相矛盾的。

⇒ 那条原则从来没有铺到主按钮。品牌色的语义是「这是主要动作，点它」，
和「你点不了」同样自相矛盾。

## ⭐⭐⭐ 这条判据是**第五把尺子**，前四把各给了一个不同的数

| 尺子 | 答案 | 它错在哪 |
|---|---|---|
| ① 禁用前后**像素变没变** | 30 颗主按钮里只有 1 颗没变 ⇒「几乎不成立」| **变了不等于变对了** —— 饱和紫变暗紫也是变 |
| ② 绝对饱和度 S>0.25 = 彩色 | 41 颗 | 深色主题的**底色本身** S≈0.34，被判成彩色 |
| ③ 取按钮**中心**像素 | 14 颗主按钮「启用却中性」| 中心往往是**文字**（白，S=0），量的不是填充 |
| ④ 到底色 / 到品牌色的 **RGB 欧氏距离** | 1 颗 | 把「暗」当成了「中性」：`#3d2470` 离黑底 81、离品牌 142，于是它判「没问题」—— **而那是一块紫色** |

> ⭐⭐⭐ **我连续造了四把尺子量同一件事，四个不同的数；
> 而每一把在被造出来的那一刻，我都觉得它是对的。**
> ⭐⭐ 尤其第三把：它给出的答案（「14 颗主按钮被降权成中性」）
> **恰好符合我当时正在找的那个故事**（批 16~20 的降权有副作用），
> 我当场就为那个错数编好了解释 —— 直到发现 `about` / `config_snapshot`
> 那几页**压根没有总开关**。
> ⭐ **一个错的测量最危险的时候，是它给出的答案恰好符合我正在找的故事。**

⇒ 第五把尺子的两个改进：
  ① 量的是**整块众数**（填充），不是中心（文字）；
  ② 阈值**由本主题的中性底色实算**，不是我拍的数字 ——
     深色主题 `bg_card` S≈0.33、`bg_tertiary` S≈0.36，而品牌色 S≈0.76。
     ⭐ **「中性」不是一个绝对值，是一个相对位置。**
"""
from __future__ import annotations

import colorsys
import sys
from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ⚠ 复用那份离屏主窗夹具（含设备页中和、拦模态框、开关快照还原）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

main_window = _shared_main_window

#: 禁用态允许比「本主题最饱和的那个中性底色」再高多少。
#: ⚠ 留 0.10 是给 QSS 半透明合成留的余量，不是给品牌色留的 ——
#:   实测品牌色 S≈0.76、底色 S≈0.36，中间隔着 0.40，这个余量不会让它蒙混过关。
SATURATION_HEADROOM = 0.10


def _saturation(hex_or_rgb) -> float:
    if isinstance(hex_or_rgb, str):
        h = hex_or_rgb.lstrip("#")
        rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        rgb = hex_or_rgb
    return colorsys.rgb_to_hsv(*(v / 255 for v in rgb))[1]


def _fill_rgb(widget):
    """按钮**填充色** = 整块像素的众数。

    ⚠ 不取中心：中心往往是文字（白色），量到的就不是填充。
    ⚠ QImage 必须先落到变量上再取 `constBits()` —— 链式写法是悬空指针（RN-433）。
    """
    image = widget.grab().toImage()
    if image.width() < 6 or image.height() < 6:
        return None
    counter: Counter = Counter()
    for x in range(0, image.width(), 2):
        for y in range(0, image.height(), 2):
            counter[image.pixelColor(x, y).rgb()] += 1
    v = max(counter, key=counter.get)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def _pixels(widget) -> bytes:
    """整块像素。⚠ QImage 先落到变量再取 `constBits()`（RN-433 悬空指针）。"""
    image = widget.grab().toImage()
    return image.constBits().tobytes()


def _threshold() -> float:
    from theme_manager import get_theme_manager

    c = get_theme_manager().current_theme.colors
    neutral = max(_saturation(getattr(c, "bg_card", c.bg_secondary)),
                  _saturation(c.bg_tertiary))
    return neutral + SATURATION_HEADROOM


def _sweep(main_window, qapp):
    """把每一页每一颗可见按钮**强制禁用**，记下它的填充色。

    ⚠ 定点实测确认过：`setEnabled(False)` 之后不 repolish 也已经是新样式
    （未重算 / 重算后两个数逐字节相同）—— 所以这里不额外 repolish，
    免得多一步就多一个可疑的变量。
    """
    out = []
    for page_id in list(main_window._page_names.keys()):
        try:
            main_window.ensure_page_loaded(page_id)
            main_window.show_page(page_id, animated=False, force=True)
            qapp.processEvents()
        except Exception:
            continue
        page = main_window.pages.get(page_id)
        if page is None:
            continue
        for btn in page.findChildren(QPushButton):
            if not btn.isVisibleTo(page):
                continue
            was = btn.isEnabled()
            btn.setEnabled(True)
            qapp.processEvents()
            on, on_px = _fill_rgb(btn), _pixels(btn)
            btn.setEnabled(False)
            qapp.processEvents()
            off, off_px = _fill_rgb(btn), _pixels(btn)
            btn.setEnabled(was)
            qapp.processEvents()
            if on is None or off is None:
                continue
            out.append((page_id, btn.objectName() or "(无 objectName)",
                        btn.text()[:20], on, off, on_px, off_px))
    return out


@pytest.fixture(scope="module")
def swept(main_window, qapp):
    return _sweep(main_window, qapp)


def test_the_sweep_actually_sees_the_buttons(swept):
    """⭐ 分母守卫：先证明它看得见东西，再让下面几条断言「没问题」。

    ⚠ 这条是拿一次真事故换来的：第一版按 `win.pages.keys()` 枚举页面，
    那时只有 1 页加载过 —— **量到 7 颗按钮，而全站有 247 颗**，
    而它不报错。⭐ 一个算错分母的扫描器，长得和「这份界面很干净」一模一样。
    """
    assert len(swept) >= 200, (
        f"只量到 {len(swept)} 颗按钮 —— 分母塌了。"
        "页面名单的真源是 `win._page_names`，别用 `win.pages`（那只有加载过的）。"
    )


def test_a_disabled_button_stops_looking_like_the_brand_colour(swept):
    """禁用之后，填充色不许还停在品牌色那一带。"""
    limit = _threshold()
    bad = [
        f"{pid} · {name} · {text!r}：禁用态填充 {off}，饱和度 "
        f"{_saturation(off):.2f} > {limit:.2f}"
        for pid, name, text, on, off, _on_px, _off_px in swept
        if _saturation(off) > limit
    ]
    assert not bad, (
        "这些按钮禁用之后，看上去仍然是「可以点的品牌色」：\n  "
        + "\n  ".join(bad)
        + "\n⭐ 品牌色的语义是「这是主要动作，点它」，和「你点不了」自相矛盾 ——"
          "`dangerButton` 早就按这条原则退成中性了（R7/D-06），主按钮没有。"
    )


def test_a_disabled_button_still_looks_like_a_button(swept):
    """⚠ 反方向的守卫：禁用态不许和**启用态**完全一样。

    ⭐ 上面那条只说「别再像品牌色」。如果照着它一路改到底，
    最省事的做法是把禁用态调成和卡片底色一模一样 ——
    那时按钮在屏幕上**消失**了，而上面那条判据全绿。
    ⇒ 两条一起，才框得住「既看得出是按钮、又看得出点不了」。
    """
    # ⚠ 量的是**整块像素**，不是填充众数。第一版量填充众数，当场把
    # 一堆 `secondaryButton` 报成缺陷 —— 它们启用/禁用都是「透明露底」，
    # 填充众数当然相同，差别在**文字色和边框色**上。
    # ⭐ 一个只看填充的度量，看不见「靠文字和描边表达的禁用」。
    # ⚠ 已知例外，**逐条声明、带理由**，不许靠调阈值放过去：
    #   `helpButton` / `anchorChip` —— 产品里**从不禁用**，禁用态是个不会发生的状态；
    #   `magnifier` 那 8 颗微调按钮（`< > ^ v`）—— **RN-435**：它们带
    #     `fp_keep_style` + 写死的内联十六进制色（`background-color: #1c1f2c`…），
    #     完全绕开主题 QSS ⇒ 换主题不变、禁用也不变。那是另一条缺陷，
    #     修法要先弄清「它们当初为什么要 keep_style」，不在本批范围。
    #   ⭐ 例外写成数据 + 理由，将来它被修好时这张表会自己变成噪音，
    #     而不是一个谁都不敢动的免检区。
    EXEMPT_OBJECT_NAMES = ("helpButton", "anchorChip")
    EXEMPT_TEXTS = ("<", ">", "^", "v")
    same = [
        f"{pid} · {name} · {text!r}"
        for pid, name, text, on, off, on_px, off_px in swept
        if on_px == off_px
        and name not in EXEMPT_OBJECT_NAMES
        and not (pid == "magnifier" and text in EXEMPT_TEXTS)
    ]
    assert not same, (
        "这些按钮禁用前后填充色**完全相同**，玩家看不出它点不了：\n  "
        + "\n  ".join(same[:12])
    )


def test_the_secondary_buttons_are_the_positive_control(swept):
    """⭐ 阳性对照：次按钮（全站最多的一类）本来就合格。

    少了这一条，上面那条判据可能只是「我改过的那一类被我改过了」。
    ⚠ 它同时是**分母的第二重守卫**：次按钮一旦扫不到，说明扫描器瞎了。
    """
    limit = _threshold()
    secondary = [r for r in swept if r[1] == "secondaryButton"]
    assert len(secondary) >= 100, (
        f"只扫到 {len(secondary)} 颗次按钮 —— 全站实测有 150 颗，扫描器八成瞎了。"
    )
    offenders = [f"{r[0]} · {r[2]!r}" for r in secondary
                 if _saturation(r[4]) > limit]
    assert not offenders, (
        "阳性对照自己都不合格了，说明这条判据量的东西不对：\n  "
        + "\n  ".join(offenders)
    )
