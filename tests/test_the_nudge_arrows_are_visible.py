# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-573：**那 8 颗方向键有文字，可 `padding` 把它们的文字区挤成了负数。**

外审 S3 两个视口各 3/3 **全票**报「『微调』与『大幅』右侧各有 4 个空白方框按钮，
缺少方向图标或文字标识」。这条判据的由来有两个弯路，两个都得记下来：

## ⭐ 弯路一：查「有没有内容」的探针，答不了「看不看得见」

我第一版探针查「有没有既无文字又无图标的按钮」—— **答案是没有**
（它们有 `<` `>` `^` `v`），差一步就把这 6 票判成假报。
去**看那张图**才知道它是对的。

## ⭐⭐⭐ 弯路二：一个真实的测量，可以支持一个错误的成因

看图之后我认定是**对比度**，并用 WCAG 实算拿到了很硬的数：

    禁用态 `text_disabled` vs 卡片底色  1.65:1（暗）/ 1.62:1（亮）
    启用态 `accent_primary` vs 卡片底色 2.88:1（暗）/ 2.94:1（亮）

改完配色、重新出图 —— **渲染结果逐字节没变**（md5 相同）。
数是真的，可它不是这条缺陷的答案。

真成因量出来是这个：全站 QSS 给 `QPushButton` 的左右内边距，撞上这里
30px 的固定宽度 ⇒ **文字可用区 = -4px**（那一个字要 11px），
Qt 于是一个像素都不画（连省略号都放不下）。⇒ `padding: 0` ⇒ 可用区 28px。

⇒ 本文件盯**两件事**：① 文字放得下（真成因）；② 两个颜色够看得见
（那两个数确实不合格，顺手收下，但它不是答案）。
⚠ 而**总开关默认关着**，所以「一片空白方框」正是新用户的第一眼。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_nudge_arrows_are_visible.py`）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: 正文文字的门槛（14px bold 不算 WCAG 的「大字」）。
MIN_ENABLED = 4.5
#: 禁用态的门槛：它该读得出是个箭头，但不必和启用态一样抢眼。
MIN_DISABLED = 3.0
#: 两态之间至少要有的对比度差 —— 否则「禁用」这件事就没被画出来。
MIN_GAP = 2.0

THEMES = ("dark", "light")


def _rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _lum(color: tuple[int, int, int]) -> float:
    out = []
    for channel in color:
        s = channel / 255
        out.append(s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(fg: str, bg: str) -> float:
    a, b = _lum(_rgb(fg)), _lum(_rgb(bg))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_the_formula_matches_a_known_pair():
    """先证明这把尺子是准的（黑白应当正好 21:1），再拿它去判别人。"""
    assert round(contrast("#ffffff", "#000000"), 2) == 21.0


@pytest.fixture(scope="module")
def tokens():
    """按主题取出这几颗按钮真正用到的三个颜色（从产品代码里解析，不写第二份）。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from theme_manager import get_color, get_theme_manager

    src = (REPO / "pages" / "magnifier_page.py").read_text(encoding="utf-8")
    body = src.split("def _get_arrow_button_style")[1].split("\n    def ")[0]
    used = re.findall(r"get_color\('([a-z_]+)'\)", body)
    assert used, "解析不到 `_get_arrow_button_style` 用了哪些颜色 —— 判据在空转"

    manager = get_theme_manager()
    out = {}
    for theme in THEMES:
        manager.set_theme(theme)
        out[theme] = {name: get_color(name) for name in set(used)}
    manager.set_theme("dark")
    return out, body


@pytest.mark.parametrize("theme", THEMES)
def test_the_enabled_arrow_is_readable(tokens, theme):
    colors, body = tokens
    enabled = re.search(r"font-weight: bold;\s*\n\s*color: \{get_color\('([a-z_]+)'\)\}",
                        body)
    assert enabled, "认不出启用态用的是哪个颜色 —— 判据在空转"
    ratio = contrast(colors[theme][enabled.group(1)],
                     colors[theme]["bg_tertiary"])
    assert ratio >= MIN_ENABLED, (
        f"[{theme}] 启用态箭头 `{enabled.group(1)}` 对卡片底色只有 {ratio:.2f}:1，"
        f"低于 {MIN_ENABLED}（14px bold 不算大字）。\n"
        f"⭐ 外审 6/6 报「空白方框」时，这里是 `accent_primary` 的 2.88:1。")


@pytest.mark.parametrize("theme", THEMES)
def test_the_disabled_arrow_is_still_an_arrow(tokens, theme):
    """⭐ 总开关**默认关着** —— 禁用态就是新用户打开这一页的第一眼。"""
    colors, body = tokens
    disabled = re.search(
        r"background-color: transparent;\s*\n\s*color: \{get_color\('([a-z_]+)'\)\}",
        body)
    assert disabled, "认不出禁用态用的是哪个颜色 —— 判据在空转"
    ratio = contrast(colors[theme][disabled.group(1)],
                     colors[theme]["bg_tertiary"])
    assert ratio >= MIN_DISABLED, (
        f"[{theme}] 禁用态箭头 `{disabled.group(1)}` 对卡片底色只有 {ratio:.2f}:1，"
        f"低于 {MIN_DISABLED} —— 玩家看到的是 8 个空方框。\n"
        f"⚠ 立案时它是 `text_disabled` 的 1.65:1（暗）/ 1.62:1（亮）。")


@pytest.mark.parametrize("theme", THEMES)
def test_disabled_still_looks_disabled(tokens, theme):
    """反向绊线：把禁用态直接调成正文色，上面两条都满分通过 ——
    而那样一来「能不能点」这件事就不再被画出来了。"""
    colors, body = tokens
    # ⚠ 批 73 补正：这两处原来直接 `.group(1)` —— 正则一认不出就抛 AttributeError，
    #   报告上看起来像「判据逮住了缺陷」，实际是**判据自己在空转**。
    #   ⭐ 隔壁那条 `test_the_disabled_arrow_is_still_an_arrow` 用的是同一个正则、
    #     且有「判据在空转」的守卫，这一处却没有 ——
    #     **同一个正则在同一个文件里，一处有守卫、一处没有。**
    enabled_at = re.search(
        r"font-weight: bold;\s*\n\s*color: \{get_color\('([a-z_]+)'\)\}", body)
    assert enabled_at, "认不出启用态用的是哪个颜色 —— 判据在空转"
    disabled_at = re.search(
        r"background-color: transparent;\s*\n\s*color: \{get_color\('([a-z_]+)'\)\}",
        body)
    assert disabled_at, "认不出禁用态用的是哪个颜色 —— 判据在空转"
    enabled, disabled = enabled_at.group(1), disabled_at.group(1)
    assert enabled != disabled, "两态用了同一个颜色 —— 禁用没有被画出来"
    bg = colors[theme]["bg_tertiary"]
    gap = contrast(colors[theme][enabled], bg) / contrast(colors[theme][disabled], bg)
    assert gap >= MIN_GAP, (
        f"[{theme}] 启用/禁用两态的对比度只差 {gap:.2f} 倍（要 ≥{MIN_GAP}）——"
        f"看起来一样亮，玩家分不出哪些现在能点。")


def test_the_arrows_really_do_carry_text():
    """⚠ 别把这条缺陷读成「按钮没内容」。

    ⭐⭐⭐ 我第一版探针查的正是「有没有既无文字又无图标的按钮」，答案是**没有** ——
    差一步就把外审那 6/6 判成假报。**一个查「有没有内容」的探针，
    答不了「看不看得见」这个问题。**
    """
    src = (REPO / "pages" / "magnifier_page.py").read_text(encoding="utf-8")
    assert '("<", \'x\'' in src or '"<"' in src, (
        "方向键的文字没了 —— 那这条缺陷就换成真的「按钮没内容」了，"
        "上面几条颜色判据一条都拦不住它。")


# ─────────────────── 真成因：文字放不放得下（这一条才是答案）───────────────────

@pytest.fixture(scope="module")
def arrow_buttons():
    """按 `layout_overflow_audit.py` 同一档建窗，取那 8 颗方向键。"""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    sys.path.insert(0, str(REPO / "scripts"))
    import _audit_neutralize as neutralize
    import _ui_mode as ui_mode

    neutralize.enable_audit_mode()
    app = QApplication.instance() or QApplication([])
    from config import config

    neutralize.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    app.processEvents()
    ui_mode.goto(win, "magnifier")
    app.processEvents()
    page = win.pages.get("magnifier")
    assert page is not None, "拿不到 magnifier 页"
    buttons = list(getattr(page, "_arrow_buttons", []))
    assert len(buttons) == 8, (
        f"只拿到 {len(buttons)} 颗方向键（应为 8）—— 判据在空转")
    yield buttons
    win.close()


def test_every_arrow_has_room_for_its_glyph(arrow_buttons):
    """⭐⭐⭐ **这一条才是 RN-573 的答案。**

    量的是「样式给的文字可用区」对「这一个字要多宽」——
    立案时实测 **-4px vs 11px**：可用区是**负数**，Qt 一个像素都不画，
    而按钮本身、边框、背景全都正常，所以看起来就是一排空白方框。

    ⚠ 这条判据必须量**样式算出来的可用区**（`SE_PushButtonContents`），
    不能量 `contentsRect()` —— 后者报的是 30x34（满格），
    ⭐ **一个听起来很像的量，会给出一个看起来很像通过的答案**（同 RN-196 那次）。
    """
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    tight = []
    for button in arrow_buttons:
        option = QStyleOptionButton()
        option.initFrom(button)
        option.text = button.text()
        room = button.style().subElementRect(
            QStyle.SE_PushButtonContents, option, button).width()
        need = QFontMetrics(button.font()).horizontalAdvance(button.text())
        assert need > 0, f"「{button.text()}」量出来宽 0 —— 判据在空转"
        if room < need:
            tight.append((button.text(), room, need))

    assert not tight, (
        "这些方向键的文字可用区比字还窄，Qt 会一个像素都不画：\n  "
        + "\n  ".join(f"「{t}」可用 {r}px / 需 {n}px（差 {n - r}px）"
                      for t, r, n in tight)
        + "\n⭐ 成因是全站 QSS 的 `padding` 撞上这里 30px 的固定宽度。"
          "⇒ 这几颗要显式 `padding: 0`。\n"
          "⚠ 别去改配色 —— 那条路我走过，改完渲染结果 md5 一模一样。")


def test_the_style_keeps_its_padding_override(arrow_buttons):
    """反向绊线：`padding: 0` 被删掉时，上面那条要能红。

    ⭐ 单独列一条是因为上面那条依赖**当前**的全站 QSS 内边距值 ——
    哪天全站把 padding 调小到刚好放得下，上面那条会变绿，
    而这几颗按钮仍然处在「随时会被别人的内边距挤没」的状态。
    """
    src = (REPO / "pages" / "magnifier_page.py").read_text(encoding="utf-8")
    body = src.split("def _get_arrow_button_style")[1].split("\n    def ")[0]
    # ⚠⚠ **只看它 return 出去的那段 CSS，不看方法的文档字符串。**
    #   第一版查 `"padding: 0" in body`，而**文档字符串里就写着这四个字**
    #   ⇒ 把 CSS 里那一行删掉，判据照样绿（破坏验证当场逮住）。
    #   ⭐ 同批 71 那条：**一个词出现过，和它真的在起作用，是两件事。**
    assert 'return f"""' in body, "认不出样式表从哪里开始 —— 判据在空转"
    css = body.split('return f"""', 1)[1]
    # ⚠ 批 73 补正：**被注释掉的声明也含这个子串。**
    #   `/* padding: 0; */` 对布局一点作用都没有，而 `in css` 照样为真 ——
    #   而那正是隔壁那个几何断点用的编辑形状。
    #   ⭐ 本批第 N 次：**一个词出现过，和它真的在起作用，是两件事。**
    #   ⇒ 先把 CSS 注释整段抠掉再查。
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "padding: 0;" in css, (
        "`_get_arrow_button_style` 返回的那段 CSS 里，`padding: 0;` 没了 —— "
        "这几颗 30px 宽的按钮又回到「全站内边距说了算」的状态。\n"
        "⚠ 立案时那个状态下文字可用区是 **-4px**（字要 11px）。")
