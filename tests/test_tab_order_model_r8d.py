# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R8d · 焦点巡检判据自身的回归（UP-077）。

**为什么判据需要自己的测试**：改完之后 `tab_order_audit.py` 在 11 个页面上
全报 0。「哪儿都没问题」既可能是页面真没问题，也可能是判据瞎了——
这两种情况在输出上长得一模一样。R8a 已经为此付过一次学费
（对比度判据自己调产品函数现算期望值，改坏了也全绿）。

所以这里正反两面都锁：
  · **抓得到**：把顺序打乱，判据必须报数，且报的数等于真实挪动量；
  · **不误报**：旧判据造出的三类假阳性（并排卡片 / 滚动区内外 /
    行距正好卡在容差上），在新判据下必须是 0。

三类假阳性都不是假设——它们分别对应准心页 7 处、gun_sound 12 处、
voice_output 1 处的实测误报，合计占旧判据 52 处报告里的 50 处。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QRadioButton, QScrollArea, QWidget

REPO = Path(__file__).resolve().parent.parent


def _load_audit():
    """直接按文件加载脚本（scripts/ 不是包）。"""
    spec = importlib.util.spec_from_file_location(
        "tab_order_audit", REPO / "scripts" / "tab_order_audit.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tab_order_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit()


def _page(w=1200, h=900):
    page = QWidget()
    page.setAttribute(Qt.WA_DontShowOnScreen, True)   # 不打扰前台
    page.resize(w, h)
    return page


def _card(parent, x, y, w, h):
    card = QFrame(parent)
    card.setObjectName("card")
    card.setGeometry(x, y, w, h)
    return card


def _btn(parent, x, y, w=80, h=22, text="b"):
    b = QPushButton(text, parent)
    b.setGeometry(x, y, w, h)
    return b


def _flat_order(widgets, page):
    """旧判据的排序方式（`y // 24` 分桶后按 x），只用来对照『结论确实变了』。"""
    def key(w):
        p = w.mapTo(page, w.rect().topLeft())
        return (p.y() // 24, p.x())
    return sorted(widgets, key=key)


def _fixed_tolerance_order(widgets, page, tol=24):
    """「行带 ± 固定像素容差」的排法。

    ⚠ 这**不是**旧脚本实际干的事——它的文档写着"行容差 24px"，代码里却是
    `y // 24` 分桶。两者不等价：分桶下 y=224 与 y=248 落在不同桶（对的），
    而容差聚类会把差 24px 的两行并成一行（错的）。
    这个区别本身就值得记一笔：**文档说的判据和代码里的判据可以是两回事。**
    """
    def pos(w):
        p = w.mapTo(page, w.rect().topLeft())
        return p.x(), p.y()

    rows, cur, base = [], [], None
    for w in sorted(widgets, key=lambda w: (pos(w)[1], pos(w)[0])):
        y = pos(w)[1]
        if base is None or y - base <= tol:
            base = y if base is None else base
            cur.append(w)
        else:
            rows.append(cur)
            cur, base = [w], y
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        out.extend(sorted(row, key=lambda w: pos(w)[0]))
    return out


# ============================================================ 抓得到

def test_scrambled_order_is_detected():
    """顺序打乱必须报数——这是判据存在的全部意义。"""
    page = _page()
    card = _card(page, 0, 0, 400, 300)
    items = [_btn(card, 10, 10 + i * 40, text=f"b{i}") for i in range(5)]
    page.show()

    ideal = audit.reading_order(items, page)
    assert audit.min_moves(items, ideal) == 0, "原样就该是 0"

    scrambled = [items[4]] + items[:4]          # 把最后一个提到最前
    assert audit.min_moves(scrambled, ideal) == 1

    reversed_chain = list(reversed(items))
    assert audit.min_moves(reversed_chain, ideal) == 4
    page.close()


def test_min_moves_reports_the_real_number_not_a_cascade():
    """一个控件插错位置只该报 1，不该把它之后的全算上。

    旧判据是逐位比对：music 页真实 2 个控件不对，它报 16 处。
    照着 16 去找的人会找不到 16 个东西——这种数字不但没用，还消耗信任。
    """
    page = _page()
    card = _card(page, 0, 0, 400, 500)
    items = [_btn(card, 10, 10 + i * 40, text=f"b{i}") for i in range(10)]
    page.show()

    ideal = audit.reading_order(items, page)
    displaced = [items[9]] + items[:9]

    positionwise = sum(1 for a, b in zip(displaced, ideal) if a is not b)
    assert positionwise == 10, "逐位比对会把一处错位放大成十处（这正是要避开的）"
    assert audit.min_moves(displaced, ideal) == 1
    page.close()


# ============================================================ 不误报

def test_side_by_side_cards_are_read_one_card_at_a_time():
    """并排两张卡：右卡内容比左卡高一点，也不该被排到左卡前面。

    准心页实测：「准心样式」的单选在 y=409，「准心颜色」的在 y=384。
    旧判据平铺排序把整张右卡排到左卡前面，于是把**正确的** Tab 顺序
    判成 7 处错位。人读界面是读完一张卡再读下一张，不是横穿整页。
    """
    page = _page()
    left = _card(page, 40, 360, 400, 90)
    right = _card(page, 860, 360, 300, 90)
    left_items = [QRadioButton(f"L{i}", left) for i in range(4)]
    for i, r in enumerate(left_items):
        r.setGeometry(10 + i * 60, 49, 55, 20)          # 页面 y ≈ 409
    right_items = [QRadioButton(f"R{i}", right) for i in range(3)]
    for i, r in enumerate(right_items):
        r.setGeometry(10 + i * 58, 24, 55, 20)          # 页面 y ≈ 384，比左卡高
    page.show()

    chain = left_items + right_items                     # 先走完左卡，再走右卡
    ideal = audit.reading_order(chain, page)
    assert audit.min_moves(chain, ideal) == 0

    # 对照：旧的平铺排序会给出不同答案——证明这条判据确实换了结论，不是恰好都对
    assert _flat_order(chain, page) != ideal
    page.close()


def test_content_inside_a_scroll_area_comes_before_the_bar_below_it():
    """滚动区里的内容（哪怕绝对坐标很大）也排在它下方的动作条**前面**。

    gun_sound 实测：动作条在滚动区外、y=838；滚动区内的内容绝对坐标到 y=1045
    ——那部分早就滚出视口了。拿这两个 y 直接比大小没有意义，
    旧判据因此报 12 处错位，**12 处全是假的**。
    """
    page = _page()
    scroll = QScrollArea(page)
    scroll.setGeometry(0, 80, 1200, 700)
    content = QWidget()
    content.resize(1180, 1400)
    scroll.setWidget(content)
    deep = _btn(content, 100, 1000, text="滚动区深处")     # 页面绝对 y ≈ 1080

    bar = QFrame(page)
    bar.setObjectName("pageActionBar")
    bar.setGeometry(0, 800, 1200, 60)
    bar_btn = _btn(bar, 1000, 18, text="刷新")             # 页面绝对 y ≈ 818
    page.show()

    chain = [deep, bar_btn]
    ideal = audit.reading_order(chain, page)
    assert ideal == [deep, bar_btn], "滚动区内容应排在下方动作条之前"
    assert audit.min_moves(chain, ideal) == 0

    # 旧的平铺排序会把动作条排到前面（818 < 1080）
    assert _flat_order(chain, page) == [bar_btn, deep]
    page.close()


def test_rows_are_decided_by_overlap_not_a_fixed_pixel_tolerance():
    """两行正好差 24px 时，仍然要认成两行。

    voice_output 实测：主音量行 y=224、模式行 y=248，正好差 24。
    改判据的中途我先写了个「±24px 容差聚类」版本，它把这两行并成一行、
    再按 x 排就把顺序排反了（lower 的 x 更小），判出 1 处错位——而页面是对的。
    换成矩形垂直重叠后归零。

    固定容差还有第二个毛病：**不随字号缩放**——1.25 档下行距变大，
    同一个 24px 会从"同行"变"跨行"，结论跟着漂。重叠判据自带缩放不变性。
    """
    page = _page()
    card = _card(page, 560, 200, 400, 120)
    upper = _btn(card, 54, 24, w=200, h=22, text="主音量滑块")   # 页面 y=224，底 246
    lower = _btn(card, 38, 48, w=140, h=32, text="模式下拉")     # 页面 y=248，底 280
    page.show()

    chain = [upper, lower]
    ideal = audit.reading_order(chain, page)
    assert ideal == [upper, lower], "两者矩形不重叠，应认作上下两行"
    assert audit.min_moves(chain, ideal) == 0

    # 「±24px 容差聚类」把它们视作同一行，再按 x 排就反了（lower 的 x 更小）
    assert _fixed_tolerance_order(chain, page) == [lower, upper]
    page.close()


def test_widgets_outside_any_card_do_not_clump_into_one_block():
    """不在卡片里的散控件要**各自成组**，不能并成一个位于 (0,0) 的整块。

    并成一块会让它们整体排到最前面——第一版分组就这么干的，
    music / voice_output 各多出 6 处假错位。
    """
    page = _page()
    top = _btn(page, 1160, 17, w=24, h=24, text="?")
    card = _card(page, 16, 100, 600, 200)
    inner = _btn(card, 20, 40, text="卡内")
    bottom = _btn(page, 900, 700, text="页脚")
    page.show()

    chain = [top, inner, bottom]
    ideal = audit.reading_order(chain, page)
    assert ideal == [top, inner, bottom]
    assert audit.min_moves(chain, ideal) == 0
    page.close()


# ============================================================ 具体缺陷不回退

def test_music_action_bar_is_not_first_in_the_focus_chain():
    """music 页真实缺陷的守门：进页按 Tab，第一站不该是**底部动作条**。

    根因是 `settings_container` 无父创建、直到 addWidget 才入焦点链，
    而那行原先排在 `PageActionBar(self)` **之后**（动作条一创建就带父、当场入链）。
    排版看不出任何异常，坏的只有键盘顺序——所以它一直没被发现。
    """
    from pages.music_page import MusicPage

    page = MusicPage()
    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    page.resize(1200, 900)
    page.show()
    try:
        chain = audit.focusable_chain(page)
        assert chain, "一个可聚焦控件都没抓到，判据失效了"
        bar_buttons = {page.action_bar.secondary_btn, page.action_bar.primary_btn}
        first_three = set(chain[:3])
        assert not (bar_buttons & first_three), (
            "动作条又回到了焦点链最前面——检查 main_layout.addWidget(settings_container) "
            "是不是被挪到了 PageActionBar(self) 之后"
        )
        assert audit.min_moves(chain, audit.reading_order(chain, page)) == 0
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize("page_id", ["crosshair", "gun_sound", "kill_sound"])
def test_previously_false_flagged_pages_are_clean(page_id):
    """这三页旧判据合计报 19 处错位，实测**一处真缺陷都没有**。

    留这条断言是为了存档这个结论：下次看到"焦点顺序有问题"的旧记录时，
    不用重新调查一遍才知道那是判据的错。
    """
    mod_name, cls_name = audit.PAGE_FACTORY[page_id]
    mod = __import__(mod_name, fromlist=[cls_name])
    page = getattr(mod, cls_name)()
    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    page.resize(1200, 900)
    page.show()
    try:
        chain = audit.focusable_chain(page)
        assert audit.min_moves(chain, audit.reading_order(chain, page)) == 0
    finally:
        page.close()
        page.deleteLater()


def test_audit_does_not_reach_the_network():
    """审计工具不该有网络副作用（UP-087）。

    music 页在隔离配置下会当场下载默认曲目「CS的LEMON」——审计每跑一次下一次，
    CI 里也一样。那让结果依赖外网可达性，也把构造耗时绑在一次 HTTP 上。
    这里只守住中和开关还在（真发不发请求由那个开关决定）。
    """
    # RN-005：这张表搬到 `scripts/_audit_neutralize.py` 了（口径不变）。
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from _audit_neutralize import NEUTRALIZE
    assert NEUTRALIZE.get("music", {}).get("music_default_song_added") is True
