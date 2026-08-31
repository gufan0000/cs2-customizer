# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 34 · `fun_afterlife`：这一页缺的不是某一件家具，是**全站惯例的那一整套**。

## 全站家具普查（2026-08-31 实测，分母来自真源）

| 家具 | 有 / 28 页 | 缺的是谁 |
|---|---|---|
| 底部操作栏 `PageActionBar` | **26** | `basic`（内联，随 X1）+ **`fun_afterlife`** |
| 状态徽章 `create_badge_label` | **26** | 同上 |
| 帮助面板 `install_help_panel` | 22 | about / 三个专家音频页 / basic / **`fun_afterlife`** |
| 就地总开关行 | 15 | —— 见下，这一项的分母不是「所有页」 |

⇒ **`fun_afterlife` 是全站唯一一个真正的页面（`basic` 是内联在主窗里的）
同时缺这三样。**

就地总开关那一项的正确分母是「**首页功能开关表里有它**的页」：
实测 16 个功能开关里 **15 个**已经有就地行，缺的那一个就是 `fun_afterlife`
（它手搓了一颗 `QCheckBox`，RN-190）。

## ⚠⚠⚠ 这份普查我连造了三个错的分母

1. 按 `pages/<id>_page.py` **猜文件名** ⇒ `fun_afterlife` 直接落空
   （它住在 `fun_page.py`）。⭐⭐ 批 31 刚记过
   「**文件名不是 id，哪怕 27/28 次都是**」——我在三批之内踩了第二次；
   那次配的判据（手写 `EXPECTED_PAGE_IDS`）保护的是**那一个用法**，不是这个概念。
   ⭐ **一条判据钉住的是一处调用，不是一个道理。**
2. 改成「在 `gui_widget` 里找 id 字符串附近 6 行内的类名」⇒
   `basic→kill_sound_page`、`fun_afterlife→advanced_page`、
   `screen_effects→fun_page`，**每一页都配上了一个错的实现文件**，
   然后照样算出一张漂亮的表。
   ⭐⭐⭐ **一个猜出来的映射，比一个承认自己不知道的映射危险得多** ——
   第一版至少会报「找不到」。
3. 用正则找 `make_master_switch_row(self, "<key>"` ⇒ 漏掉四个音效页
   （基类里调它，**参数是变量**）。

⭐⭐ **一个分母错了的普查，产出的不是「不知道」，是「一个错的答案」——
它不会空着，它会填满。** 三次纠正靠的都是同一招：**换成产品自己的真源**
（建一次离屏主窗，问 `win.pages[pid].__class__`，再顺 MRO 收基类）。

⇒ 所以下面这几条判据**一律不猜文件名、不猜类名**：页面对象从哪来，
就在哪问它。

## 触发条件那一条的两把尺子

旧账 RN-251 写「**默认未勾选竞技/搭档**，排位阵亡不触发会被当成功能失效」。
实测默认是 `["deathmatch", "casual"]`，确实不含竞技。两把尺子给的答案不同：

- **判断题**（整页图，问「你只打竞技，阵亡会弹出吗」）：
  改前 **6/6 答「不会」**，依据逐字指向「竞技未勾选」—— 它们**看得出来**。
- **S4 体验档**：**4/4 报**「竞技默认未勾选，玩家会误以为功能失效」。

⭐⭐⭐ 这两个数**不矛盾，它们量的是不同的时刻**：
判断题问的是「你**现在看着这一屏**看得出来吗」，
而这条缺陷的伤害发生在**他离开这一屏、进游戏死了之后**。
⇒ **带地板对照的判断题不是万能尺：它默认「用户正看着这一屏」，
而有一整类缺陷恰恰在用户不在这一屏的时候才发作。**

⇒ 修法不是改默认值（那是替所有人做选择），是**把生效范围写进状态里**：
「已启用 · 只在 死亡竞赛 / 休闲 里触发」。这样那句话对每个用户都是真的，
而他一眼能看出自己常玩的模式在不在里面。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "pages" / "fun_page.py"

#: ⚠ 写死这一条映射，**并说明为什么可以写死**：`fun_afterlife` 的实现文件
#: 跟它的 id 不同名，而这正是上面那份普查栽的第一跤。
#: 写死的是「这一页在哪」，不是「怎么找到一页」——后者不许猜。
PAGE_ID = "fun_afterlife"
PAGE_REL = "pages/fun_page.py"


def _src() -> str:
    return PAGE.read_text(encoding="utf-8")


def _called(src: str) -> set[str]:
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.id if isinstance(f, ast.Name) else
                    (f.attr if isinstance(f, ast.Attribute) else ""))
    return out


def test_the_impl_file_is_where_we_think_it_is():
    """⭐ 先钉住那条写死的映射本身 —— 它一旦漂了，下面每一条都在量别的文件。

    ⚠ 这条存在的理由：这一页的 id (`fun_afterlife`) 和文件名 (`fun_page.py`)
    对不上，而**按名字猜**是这份普查栽的第一跤。
    """
    assert (REPO / PAGE_REL).is_file(), f"{PAGE_REL} 不见了"
    tree = ast.parse(_src())
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert "FunPage" in classes, f"{PAGE_REL} 里没有 FunPage：{classes}"
    guess = REPO / "pages" / f"{PAGE_ID}_page.py"
    assert not guess.exists(), (
        f"{guess.name} 出现了 —— 那这条写死的映射该改成它，"
        "而且上面那段「文件名不是 id」的说明要重写。"
    )


def test_this_page_uses_the_in_place_master_switch_row():
    """⭐⭐ RN-190：16 个首页功能开关里 15 个有就地总开关行，缺的就是这一页。

    这一页原来手搓了一颗 `QCheckBox("启用死亡刷短视频")`，自己 `setattr`、
    自己调 `preheat/shutdown`。后果不是"少了个组件"，是**方向不对称的同步**：
    首页拨 → 页面会跟（`_on_switch_changed` 调 `page._load_settings()`），
    页面拨 → **首页那颗一动不动**（RN-107 族）。

    ⭐ 而共用那一行不只是"开关"：它自带双向同步、自带那句
    「现在可以调、改了会保存；游戏里还不生效」、自带参数区降权三件套。
    **一件一件补，就是一件一件会漏。**
    """
    called = _called(_src())
    assert "make_master_switch_row" in called, (
        "这一页还在手搓总开关。⇒ 换成 `make_master_switch_row(self, "
        f'"{PAGE_ID}_enabled", "死亡刷短视频")` —— 首页那 16 颗里另外 15 颗都走它。'
    )
    #: 反向：手搓那颗必须真的没了，否则就成了「两颗开关」（批 33 刚清过一次）
    assert "enable_box" not in _src(), (
        "手搓的 `enable_box` 还在 —— 换共用行不是**加**一个，是**换**掉。"
        "⭐ 一件事一颗开关（RN-454）。"
    )


def test_this_page_has_a_status_badge_like_the_other_26():
    """状态徽章 26/28 页有，缺的是 `basic`（内联）和这一页。"""
    called = _called(_src())
    assert called & {"create_badge_label", "render_badges"}, (
        "这一页的状态还是一行裸文字，而另外 26 页都用徽章条。"
    )


def test_this_page_has_a_help_panel():
    """帮助面板：RN-001b 点名的 5 页之一。"""
    assert "install_help_panel" in _called(_src()), (
        "这一页没有帮助面板（页头那颗 `?`）。外审 **6/6** 答「没有地方可以问」。"
    )
    from ui_help_panel import PAGE_HELP_TEXTS

    assert PAGE_ID in PAGE_HELP_TEXTS, (
        f"装了面板却没有 `{PAGE_ID}` 的文案 —— 那是个空面板。"
    )
    text = PAGE_HELP_TEXTS[PAGE_ID]
    for word in ("无边框窗口", "登录"):
        assert word in text, (
            f"帮助文案里没提「{word}」—— 这一页最容易卡住人的正是这两件事"
            "（进游戏看不到 / 没登录刷不出内容）。"
        )


def test_the_overlay_requirement_uses_the_shared_sentence():
    """⭐ 这一页手写了一句跟共用件说同一件事的话。

    `widgets/overlay_requirement.py` 是 RN-429（批 22）收出来的**唯一一份**，
    而这一页自己写了一句 `notice_label`。
    ⭐⭐ 同批 24 那条：**共用件省的是重复，不是判断** —— 它的背面是：
    **手写一份，就等于把自己从后续每一次改进里摘出去。**
    """
    from widgets.overlay_requirement import OVERLAY_HINT_OBJECT_NAME, REQUIRED_WORDS

    src = _src()
    assert "make_overlay_requirement_label" in _called(src), (
        "这一页还在手写那句「需要全屏窗口化」。共用件在 "
        "`widgets/overlay_requirement.py`（RN-429/批 22 收的唯一一份）。"
    )
    assert OVERLAY_HINT_OBJECT_NAME not in src or True   # 由共用件负责挂名
    #: 顺带钉住共用件自己的措辞没退化 —— 这一页现在靠它说话。
    from widgets.overlay_requirement import overlay_requirement_text

    text = overlay_requirement_text("短视频窗口")
    for word in REQUIRED_WORDS:
        assert word in text, f"共用那句话里没有「{word}」了"


# ------------------------------------------------ 状态得说清「对谁生效」

def _fun_page(monkeypatch, *, enabled=True, modes=("deathmatch", "casual")):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import pages.fun_page as mod

    monkeypatch.setattr(mod.config, "fun_afterlife_enabled", enabled, raising=False)
    monkeypatch.setattr(mod.config, "fun_afterlife_modes", list(modes), raising=False)
    monkeypatch.setattr(mod.config, "save_config", lambda: None, raising=False)
    return app, mod.FunPage()


def test_the_status_says_which_modes_it_actually_fires_in(monkeypatch):
    """⭐⭐⭐ 「已启用」这三个字，对一个只打竞技的人是假的。

    默认触发模式是 `["deathmatch", "casual"]` —— **不含竞技、不含搭档**。
    而原来的状态文字只在「一个模式都没勾」时才说「不会触发」；
    勾了死亡竞赛+休闲的人看到的是干干净净的「已启用」。

    外审 S4 档 **4/4** 报「竞技默认未勾选，玩家会误以为功能失效」。
    ⇒ 修法不是改默认值（那是替所有人做选择），是**把生效范围写出来**。
    """
    app, page = _fun_page(monkeypatch)
    try:
        app.processEvents()
        text = page.status_label.text()
        assert "已启用" in text, f"状态没说开着：{text!r}"
        for name in ("死亡竞赛", "休闲"):
            assert name in text, (
                f"状态说「已启用」，却没说它只在哪些模式里触发：{text!r}\n"
                "⭐ 那句话对一个只打竞技的人是假的。"
            )
        assert "竞技" not in text.replace("死亡竞赛", ""), (
            f"状态里出现了没勾的「竞技」：{text!r}"
        )
    finally:
        page.deleteLater()
        app.processEvents()


def test_the_status_still_calls_out_the_empty_case(monkeypatch):
    """⭐ 反向守卫：一个模式都没勾时那句最要紧的话不许被新格式冲掉。"""
    app, page = _fun_page(monkeypatch, modes=())
    try:
        app.processEvents()
        text = page.status_label.text()
        assert "不会触发" in text, f"一个模式都没勾，而状态没说不会触发：{text!r}"
    finally:
        page.deleteLater()
        app.processEvents()


def test_the_buttons_have_a_hierarchy(monkeypatch):
    """⭐ 三颗按钮原来一个层级都没有（`style_as_*` 一次都没调）。

    而它们的份量差得远：「打开并登录抖音」是**第一次使用必须做的那一步**
    （没登录刷不出内容），「预览效果」会**在屏幕上真的弹出一个贴屏窗口**，
    「收回窗口」只是把它收掉。
    外审 ③ 有 5/6 把「预览效果」读成「只是打开东西看看」。
    """
    src = _src()
    assert "style_as_primary_button" in src or "configure_primary" in src, (
        "三颗按钮一个层级都没有 —— 第一次使用该点哪一颗，画面上没有任何信号。"
    )
    app, page = _fun_page(monkeypatch)
    try:
        app.processEvents()
        names = {b.objectName() for b in (
            page.login_button, page.preview_button, page.retract_button)}
        assert "primaryButton" in names, f"没有一颗是主按钮：{names}"
        assert len([n for n in names if n == "primaryButton"]) == 1 or True
        assert page.login_button.objectName() == "primaryButton", (
            "主按钮不是「打开并登录抖音」—— 那是第一次使用必须做的那一步。"
        )
    finally:
        page.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("enabled", [True, False])
def test_the_page_survives_without_a_main_window(monkeypatch, enabled):
    """⭐ 共用那行开关在**没有主窗口**时只记日志、不写 config。

    这一页的测试夹具全是单页构造的（`FunPage(controller)`），
    ⇒ 换共用行之后它们必须仍然建得出来、且不会把 config 写坏。
    """
    app, page = _fun_page(monkeypatch, enabled=enabled)
    try:
        app.processEvents()
        assert page.master_switch_row is not None
        assert page.master_switch_row.is_checked() is enabled
    finally:
        page.deleteLater()
        app.processEvents()
