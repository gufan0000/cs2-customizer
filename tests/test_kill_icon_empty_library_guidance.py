# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""风格库空着的时候，这一页得说**该去哪儿拿**，而不是描述一套并不存在的风格
（RN-145）。

## 缺陷长什么样

软件**不内置任何图标素材**（用户 2026-08-21 裁定：不内置，改成引导）。
于是全新用户打开这一页，首屏是这样的：

  · 副标题：「挑一套图标、放到顺眼的位置，就完事了。」—— 没得挑；
  · 大预览：一片空 + 「先导入一套风格」—— 他手上根本没有 zip，
    "导入"这个词对他不成立（说的是**手法**，不是**来源**）；
  · 首屏那颗紫色主按钮：「▶ 在屏幕上试播」—— 没得播；
    而且它还被 `player_ready` 灰着，等于唯一那颗大按钮点都点不动；
  · 底栏：「当前风格：未设置 · 素材 0/5 · 位置 0/0 · 大小 100%」
    —— 四个数**全是在描述一套不存在的东西**。

外审 6/6 票：「新玩家打开后空空如也，无法开箱即用」。

⭐ 这跟 RN-124 是两层：那条问「有没有告诉他怎么办」（引导显不显示），
这条问「告诉他的那件事他做得到吗」。**一条做不到的引导等于没有引导。**

## 修法：一个有名字的条件，五处都问它

`_library_is_empty()`。这是 RN-138 的教训直接换来的写法 ——
RN-133 把同样的条件写成就地的 `getattr`，结果指向那块内容的另外三处
一处都没跟上（一颗点了没反应的 chip + 两句在说看不见的东西的状态文案）。
⇒ **一个条件只要有第二处要问它，它就得有名字。**

## 这份文件里最要紧的两条

1. `test_the_guidance_button_is_not_greyed_out_by_the_player`：
   ⭐ **一颗按钮换了含义，门禁条件要跟着换。** 那颗按钮原来是"试播"，
   所以拿 `player_ready` 灰它是对的；换成"去拿一套"之后再灰它，
   就是拿一个**跟它无关的条件**把用户唯一的出路封死。
2. 反面守卫（`_with_styles`）：上面每一条都能靠"永远显示引导"通过。
   有风格的时候必须变回去，**而且要变回受 `player_ready` 约束的样子**。
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel

import pages.kill_icon_page as page_module
from config import config
from core.kill_icon_library import LEVELS


class _StubPlayer:
    """只要"接上了"这一个性质 —— 这份文件不关心它播了什么。"""

    def load_style(self, style):
        return True

    def play_icon(self, kills, fps=None):
        pass

    def enable_kill_icons(self):
        pass

    def disable_kill_icons(self):
        pass


#: 判据自己钉住的社区地址。**不许读产品里那个常量的实际值** ——
#: 它在开源版是空串（那边没有社区站），于是"点主按钮"这条路会从"开浏览器"
#: 变成"弹选文件对话框"，而**模态框在测试进程里是卡死不是失败**（实测：
#: 同步到开源仓之后这份文件整整挂了 300 秒才被超时砍掉）。
#: ⭐ 判据不许依赖"这个仓库恰好有社区站"这个前置 —— 同 RN-141/142 那一族：
#: **不钉前置状态的判据，绿不绿取决于它跑在哪儿。**
TEST_LIBRARY_URL = "https://example.invalid/category.php?id=7"


def _build(qapp, monkeypatch, styles, *, player=None, stale_style="",
           library_url=TEST_LIBRARY_URL):
    # ⚠ 2026-08-21（RN-153）：社区地址不再是本页自己的模块常量了 ——
    # 全仓统一走 `widgets/community_library` 的那张表（同一道
    # 「开源版没有」的守卫只写一次）。所以钉的位置跟着搬到表上。
    # ⭐ 判据要钉**真源**，钉一个已经变成转发的名字只会得到 AttributeError。
    from widgets import community_library

    monkeypatch.setattr(community_library, "COMMUNITY_CATEGORY_URLS",
                        {"kill_icon": library_url} if library_url else {})
    monkeypatch.setattr(page_module.ResourceManager, "list_kill_icon_styles",
                        lambda: list(styles))
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_icon_style",
                        styles[0] if styles else stale_style, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_x", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_y", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_scale", 1.0, raising=False)
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)
    monkeypatch.setattr(page_module, "style_summary",
                        lambda style, *a, **k: {"levels": list(LEVELS), "missing": [],
                                                "headshot_levels": [], "frames": 100})
    widget = page_module.KillIconPage()
    if player is not None:
        widget.kill_icon_player = player
        widget._sync_status_strip()
    qapp.processEvents()
    return widget


@pytest.fixture
def empty_page(qapp, monkeypatch):
    """全新用户：风格库一套都没有。

    ⚠ `kill_icon_style` **刻意留着「默认」这个名字** —— 这就是真实的全新用户
    状态（出厂配置里存着一个名字，而这台机器上没有那套风格）。
    留空的话 `test_the_status_strip_does_not_name_a_style_that_is_not_installed`
    那条判据就**整条空转**：没有名字可以泄漏，它永远绿。
    """
    widget = _build(qapp, monkeypatch, [], stale_style="默认")
    yield widget
    widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def stocked_page(qapp, monkeypatch):
    """反面：装着风格、播放器也接上了。"""
    widget = _build(qapp, monkeypatch, ["默认", "霓虹"], player=_StubPlayer())
    yield widget
    widget.deleteLater()
    qapp.processEvents()


# ============================================== 1. 空库这一路

def test_the_hero_button_offers_a_way_to_get_icons(empty_page):
    """⭐ 空库时首屏主按钮说的是"去拿一套"，不是"试播"。"""
    assert empty_page._library_is_empty()
    assert empty_page.test_btn.text() == page_module.EMPTY_PRIMARY_TEXT, (
        f"风格库是空的，首屏主按钮却还写着 {empty_page.test_btn.text()!r} —— "
        f"没有任何素材的时候「试播」是个走不通的动作")


def test_the_guidance_button_is_not_greyed_out_by_the_player(empty_page):
    """⭐⭐ 那颗按钮换了含义，就不许再被 `player_ready` 灰掉。

    这是这份文件里最容易写漏的一条：`_sync_status_strip` 里原来有一句
    `self.test_btn.setEnabled(player_ready)`，理由是"播放器没接上时试播是个
    空动作"。空库时 `kill_icon_player is None`（本用例就不给它），
    于是那颗**唯一的出路按钮**会被一个跟它毫无关系的条件封死。
    """
    assert empty_page.kill_icon_player is None, "本用例要的就是播放器没接上"
    assert empty_page.test_btn.isEnabled(), (
        "「去拿一套图标包」被 player_ready 灰掉了 —— "
        "用户点不动它，而它是这一页唯一走得通的动作")


def test_clicking_it_actually_opens_the_icon_library(empty_page, monkeypatch):
    """接线守卫：文案对了不等于点下去有事发生。"""
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()) or True)
    empty_page.test_btn.click()
    assert opened, "点了「去拿一套图标包」什么都没发生"
    assert opened[0] == TEST_LIBRARY_URL, (
        f"打开的不是判据钉住的那个社区分类地址：{opened[0]}")


def test_the_action_bar_stops_reciting_numbers_about_nothing(empty_page):
    """底栏那一行不许再报「素材 0/5 · 位置 0/0 · 大小 100%」。"""
    message = empty_page.action_bar.message_label.text()
    assert f"0/{len(LEVELS)}" not in message, (
        f"空库时底栏还在描述一套不存在的风格：{message!r}")
    # ⚠ 这里**不要求**这一行自己给去处。看图实测 + 外审 6/6 票：
    # 页头一句完整引导、底栏再抄一句、风格条里第三句 ——
    # ⭐ 引导说三遍不等于说清楚了。这一行的本职就是报状态。
    assert page_module.EMPTY_LEAD_TEXT != message, "底栏在逐字复述页头那句引导"
    assert empty_page.action_bar.primary_btn.isHidden(), (
        "底栏那颗主按钮跟首屏那颗**是同一个动作、同一句文案** —— "
        "空状态最需要的不是多给几个入口，是只给一个")


def test_the_empty_state_does_not_say_the_same_thing_three_times(empty_page):
    """⭐ 一屏之内不许出现三句几乎相同的引导。

    这条是**改完看图**才发现的：我把"去社区拿一套"同时写进了页头、底栏
    和风格条，自己读一遍才意识到这一屏没有重点了。
    判据盯的是"完整引导只说一遍"这条性质，不是某一句具体文案。
    """
    said = [
        empty_page.page_lead_label.text(),
        empty_page.action_bar.message_label.text(),
        empty_page.style_summary_label.text(),
    ]
    full_guidance = [s for s in said if "社区" in s and "工坊" in s]
    assert len(full_guidance) == 1, (
        f"完整引导在一屏里说了 {len(full_guidance)} 遍：{full_guidance}")


def test_the_status_strip_does_not_name_a_style_that_is_not_installed(empty_page):
    """⭐ 空库时状态里不许出现 config 留下的那个风格名。

    `_current_style()` 读的是 config 存的名字，跟"这台机器上有没有这套风格"
    是两回事。全新用户 config 里留着「默认」，于是徽章写「风格 · 默认」、
    详情写「当前风格：默认」，而同一张卡上另一行写着「共 0 套可选」——
    **一屏之内自相矛盾**（同 RN-107 那一族）。

    这条是改完看图才发现的：我修好了预览的占位文案，却漏了另外三处
    同样读 `_current_style()` 的地方。⭐ 同一个错误来源，改一处不算改。
    """
    from config import config

    stale = str(getattr(config, "kill_icon_style", "") or "")
    assert stale, "夹具没留下那个「config 里有、机器上没有」的风格名，这条判据在空转"
    detail = empty_page.summary_label.text()
    summary = empty_page.style_summary_label.text()
    # ⚠ **首屏那颗徽章自己的文字**必须一起判 —— 只判 tooltip 和详情的话，
    # 徽章退回 `风格 · 默认` 这条判据照样绿（回退验证当场逮住过一次 0/1）。
    # ⭐ 判据要盯用户**看得见**的那一处，不是它旁边那些藏起来的副本。
    chips = [lbl.text() for lbl in empty_page.status_badge_label.findChildren(QLabel)
             if lbl.objectName() == "audioStatusChip"]
    assert chips, "一颗徽章都没读到，这条判据在空转"
    assert f"风格 · {stale}" not in chips, (
        f"库是空的，徽章却写着「风格 · {stale}」，而同一张卡上另一行写着"
        f"「共 0 套可选」—— 一屏之内自相矛盾。实际徽章：{chips}")
    assert "共 0 套可选" not in summary, "还在报那三个描述不存在风格的数"
    assert f"当前风格：{stale}" not in detail, (
        f"库是空的，详情却说「当前风格：{stale}」—— 那套风格不在这台机器上")
    assert f"当前风格：{stale}" not in empty_page.status_badge_label.toolTip(), (
        "状态胶囊的 tooltip 也在报那个名字")


def test_the_page_lead_says_where_to_get_one(empty_page):
    """副标题不许再说"挑一套图标" —— 这时候没得挑。"""
    lead = empty_page.page_lead_label.text()
    assert lead == page_module.EMPTY_LEAD_TEXT, f"副标题没跟着换：{lead!r}"
    assert "社区" in lead, "引导里没说去哪儿拿"


def test_the_big_preview_placeholder_states_the_fact_and_nothing_else(empty_page):
    """大预览的占位文案只说"这儿为什么是空的"，不再复述那颗按钮的名字。

    ⚠ 第一版写的是「还没有图标，点下面「去拿一套图标包」」—— 外审 6/6 票
    数出同一句话在这一屏出现了 **3 次**（首屏按钮 / 这句 / 底栏按钮）。
    ⭐ 占位文案离那颗按钮只有 20px，不需要再指一次。
    """
    placeholder = empty_page.hero_preview._placeholder
    assert placeholder != "先导入一套风格", (
        "大预览还在说「先导入一套风格」—— 全新用户手上没有 zip，"
        "这句话对他不成立")
    assert page_module.EMPTY_PRIMARY_TEXT not in placeholder, (
        f"占位文案又把按钮名复述了一遍：{placeholder!r}")


def test_the_call_to_action_appears_exactly_once(empty_page):
    """⭐ 空状态里"去拿一套"这个动作，整屏只许出现一次。

    ⚠ 判据数的是**用户看得见的文字**，不是控件个数 —— 第一版三处
    （hero 按钮 / 预览占位 / 底栏按钮）里有两处是文案、一处是按钮，
    只数按钮的话漏一处、只数文案的话漏两处。
    """
    from PySide6.QtWidgets import QAbstractButton

    seen = []
    for widget in empty_page.findChildren(QLabel) + empty_page.findChildren(QAbstractButton):
        try:
            if widget.isHidden():
                continue
            text = widget.text()
        except Exception:
            continue
        if page_module.EMPTY_PRIMARY_TEXT in str(text or ""):
            seen.append(f"{type(widget).__name__}:{text}")
    seen.append(f"placeholder:{empty_page.hero_preview._placeholder}"
                if page_module.EMPTY_PRIMARY_TEXT in empty_page.hero_preview._placeholder
                else None)
    seen = [s for s in seen if s]
    assert len(seen) == 1, f"「{page_module.EMPTY_PRIMARY_TEXT}」在这一屏出现了 {len(seen)} 次：{seen}"


# ============================ 1b. 没有社区站的发行版（开源版走这条）

def test_a_build_without_a_community_site_still_offers_a_first_step(
        qapp, monkeypatch):
    """⭐ 开源版没有社区站 —— 按钮不许留在那儿指向一个空地址。

    `cs2-customizer` 的 `service_urls.py` **归它自己所有**，里面没有社区站
    （那是闭源商业版的运营资产）。所以这一页的顶层 import 是 `try/except`，
    拿不到就退成空串。这条判据钉的是那条**退路本身**：
    主按钮换成「导入图标包…」、点它走选文件，而不是打开一个空 URL。

    ⚠ 这不是"开源版的小差异"：一个顶层 import 失败会让**整页 import 不进去**，
    而同步管道的机械步骤完全看不出来（它只比文件差异）。
    """
    widget = _build(qapp, monkeypatch, [], stale_style="默认", library_url="")
    try:
        assert widget._icon_library_url() == ""
        assert widget.test_btn.text() == page_module.EMPTY_PRIMARY_TEXT_NO_LIBRARY
        assert widget.test_btn.isEnabled()
        assert "社区" not in widget.page_lead_label.text(), (
            "没有社区站的版本还在让用户「去社区拿一套」")

        opened, chosen = [], []
        monkeypatch.setattr(QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()) or True)
        monkeypatch.setattr(widget, "_choose_file_to_import",
                            lambda: chosen.append(1))
        widget.test_btn.click()
        assert not opened, f"没有社区站却打开了浏览器：{opened}"
        assert chosen, "没有社区站时那颗按钮点了什么也没发生"
    finally:
        widget.deleteLater()
        qapp.processEvents()


def test_no_module_imports_the_community_urls_without_a_guard():
    """⭐ 开源版的 `service_urls` 里没有社区站 —— 无守卫的顶层 import
    会让**整个模块 import 不进去**。

    ⚠ 2026-08-21（RN-153）：这道守卫**搬家了**。原来它写在
    `pages/kill_icon_page.py` 里，本轮统一收进 `widgets/community_library`
    —— 因为音效家族四页也要用同一个地址表，
    ⭐ **同一道守卫散成 N 份，就是 N 个各自会漏的地方**（RN-157 漏了一处，
    判据同步到开源仓之后挂死 300 秒）。

    所以这条判据不再盯"某一个文件里有没有 try"，而是盯那条**不变量**：
    **全仓凡是顶层 import 社区地址的，都必须带 ImportError 守卫。**
    """
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    COMMUNITY_NAMES = {"COMMUNITY_CATEGORY_URLS", "COMMUNITY_CATEGORY_IDS",
                       "COMMUNITY_KILL_ICON_URL", "COMMUNITY_WEBSITE_URL"}

    guarded_somewhere = False
    offenders = []
    for path in sorted(repo.glob("*.py")) + sorted(repo.glob("pages/*.py"))             + sorted(repo.glob("widgets/*.py")):
        if path.name == "service_urls.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 被 try/except ImportError 包住的那些 import 节点
        safe = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not any(isinstance(h.type, ast.Name) and h.type.id == "ImportError"
                       for h in node.handlers):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom):
                    safe.add(id(inner))
        for node in tree.body:            # **只看顶层** —— 函数里的延迟 import 不算
            if not (isinstance(node, ast.ImportFrom) and node.module == "service_urls"):
                continue
            names = {a.name for a in node.names}
            if not (names & COMMUNITY_NAMES):
                continue
            if id(node) in safe:
                guarded_somewhere = True
            else:
                offenders.append((path.name, node.lineno, sorted(names)))
        # try 里的也算数（它们不在 tree.body 里）
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "service_urls"                     and id(node) in safe and {a.name for a in node.names} & COMMUNITY_NAMES:
                guarded_somewhere = True

    assert not offenders, (
        "这些地方顶层 import 了社区地址却**没有 ImportError 守卫**：\n"
        + "\n".join(f"  {n}:{ln}  {names}" for n, ln, names in offenders)
        + "\n开源版的 service_urls 里没有这些名字 —— 少一道守卫就是整页 import 不进去。")
    assert guarded_somewhere, (
        "全仓一处带守卫的社区地址 import 都没有 —— 这条判据多半已经空转了")


# ============================================== 2. 反面守卫（有风格的时候）

def test_a_stocked_library_gets_the_test_button_back(stocked_page):
    """反面：有风格了就得变回"试播"，否则上面每一条都能靠"永远引导"通过。"""
    assert not stocked_page._library_is_empty()
    assert stocked_page.test_btn.text() == page_module.NORMAL_PRIMARY_TEXT
    assert stocked_page.test_btn.isEnabled(), "播放器接上了却还灰着"
    assert stocked_page.page_lead_label.text() == page_module.NORMAL_LEAD_TEXT


def test_a_stocked_library_still_greys_the_button_without_a_player(
        qapp, monkeypatch):
    """反面之二：**原来那条约束不许被顺手删掉。**

    修 RN-145 最省事的写法是把 `setEnabled(player_ready)` 整句删了 ——
    那样空库这条过了，代价是"播放器没就绪时试播点了没反应"回来了。
    """
    widget = _build(qapp, monkeypatch, ["默认"])
    try:
        assert widget.kill_icon_player is None
        assert not widget._library_is_empty()
        assert not widget.test_btn.isEnabled(), (
            "有风格但播放器没接上，「在屏幕上试播」还是亮的 —— "
            "点下去是个空动作")
    finally:
        widget.deleteLater()
        qapp.processEvents()


def test_clicking_a_stocked_page_does_not_open_a_browser(stocked_page, monkeypatch):
    """反面之三：接线是**一个槽两条分支**，别把有风格时也导到浏览器上去。"""
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()) or True)
    played = []
    monkeypatch.setattr(stocked_page, "_test_current", lambda: played.append(1))
    stocked_page.test_btn.click()
    assert not opened, f"有风格时点主按钮却打开了浏览器：{opened}"
    assert played, "有风格时点主按钮没有试播"
