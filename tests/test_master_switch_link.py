# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""状态摆在这儿，动作也得在这儿（RN-144）。

## 缺陷长什么样

准心 / 屏幕特效 / 换弹音效三页，首屏都写着总开关开没开：

    「显示 · 未启用」   「特效 · 未启用」   「开关 · 未启用」

**而这三页既不能就地开、也没有任何入口。** 总开关在「基础设置」页
那张「功能开关」卡里 —— 22 项导航里的一项，17 颗开关里的一颗。
外审两档 6/6 票：「玩家调完准心进游戏不显示，会以为软件坏了」。

⭐ **把状态摆出来而不给动作，比不摆更糟。** 不摆的话玩家不知道有这回事；
摆出来 = 明确告诉他"有个东西没开"，然后让他自己去翻。
它制造了一个玩家解决不了的问题。

与 RN-108 同一片区但机制不同：RN-108 修的是「基础设置」在侧栏里找不到，
这条说的是**状态在这儿、开关不在这儿**。

## 这份文件里最要紧的三条

1. `test_the_link_lands_on_the_right_switch_row`：跳过去**并且指对行**。
   ⚠ 刻意不走搜索那条按文案模糊匹配的路 —— 拿"准心"两个字去页面上找，
   命中的可能是另一处同名文案。**定位错行比不定位更糟。**
2. `test_the_tooltip_always_spells_out_the_manual_path`：
   ⭐ 引导的兜底不该是"失败了弹一句话"，而是"那句话本来就一直在"。
   跳转这条路整条坏掉时，tooltip 里的手动路径仍然是一条走得通的路。
3. `test_the_page_name_in_the_copy_is_not_a_hand_written_literal`：
   文案里点名的页面名必须跟真源走 —— 三页各抄一份"基础设置"，
   哪天那一页改名就有三处对不上，而且**一处都不会报错**。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

REPO = Path(__file__).resolve().parents[1]
# `_audit_neutralize`（设备中和表）住在 scripts/ 里，且只准有一份。
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from widgets import master_switch_link as link  # noqa: E402


# ============================================== 1. 三页都有这颗按钮

@pytest.fixture
def crosshair_page(qapp, monkeypatch):
    from pages.crosshair_page import CrosshairPage

    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    widget = CrosshairPage()
    yield widget
    widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def screen_effects_page(qapp, monkeypatch):
    from pages.screen_effects_page import ScreenEffectsPage

    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    widget = ScreenEffectsPage(None)
    yield widget
    widget.deleteLater()
    qapp.processEvents()


def test_the_three_pages_that_show_the_state_also_offer_the_action(
        crosshair_page, screen_effects_page):
    """准心 / 屏幕特效：状态卡上必须有那颗按钮，且就在状态卡里。

    "就在状态卡里"是要害 —— 摆到页尾就等于没摆
    （网站那轮实测：解释性文字放在困惑发生的位置之后 = 没放）。
    """
    for page, name in ((crosshair_page, "准心"), (screen_effects_page, "屏幕特效")):
        button = getattr(page, "master_switch_btn", None)
        assert button is not None, f"{name} 页没有「去总开关」"
        assert button.text() == link.LINK_TEXT
        card = getattr(page, "status_card", None)
        assert card is not None and button.isAncestorOf is not None
        assert card.isAncestorOf(button), (
            f"{name} 页那颗按钮不在状态卡里 —— 状态在一处、动作在另一处，"
            f"等于没修")


def test_the_sound_family_page_really_builds_the_button(qapp):
    """换弹音效那一页走的是基类骨架，钩子填了不等于按钮真的建出来了。

    ⚠ 这条和上面那条是**两件事**：类属性对 ≠ `_build_sound_page_ui` 真去读它。
    只判类属性的话，基类里那段 `if self.MASTER_SWITCH_KEY:` 被删掉也照样绿。
    """
    from pages.reload_sound_page import ReloadSoundPage

    page = ReloadSoundPage()
    try:
        button = getattr(page, "master_switch_btn", None)
        assert button is not None, "换弹音效页填了钩子，按钮却没建出来"
        assert page.status_card.isAncestorOf(button)
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_sound_family_only_wires_the_page_the_ruling_covered():
    """裁定范围 = 改动范围。

    换弹音效填了 `MASTER_SWITCH_KEY`，另外三个音效页**故意留空** ——
    它们是同一个机制，但要在自己那一轮里补（登记册 RN-147）。
    ⭐ 这条守的不是功能，是**别顺手扩大改动面**：四页一起改的话，
    另外三页就跳过了各自的开档流程、基线和外审。
    """
    from pages.kill_sound_page import KillSoundPage
    from pages.kill_voice_page import KillVoicePage
    from pages.reload_sound_page import ReloadSoundPage
    from pages.switch_weapon_page import SwitchWeaponPage

    assert ReloadSoundPage.MASTER_SWITCH_KEY == "reload_sound_enabled"
    for cls in (KillSoundPage, KillVoicePage, SwitchWeaponPage):
        assert cls.MASTER_SWITCH_KEY == "", (
            f"{cls.__name__} 也接上了「去总开关」—— RN-144 的裁定没覆盖它，"
            f"要走自己那一轮")


# ============================================== 2. 跳转真的落到那一行

def test_the_link_lands_on_the_right_switch_row(qapp, monkeypatch):
    """⭐ 端到端：真起一个主窗口，点那颗按钮，看高亮落在哪儿。

    这条判据要的是**对象级**的正确，不是"跳到了 basic 页"就算数：
    高亮目标必须是准心那颗开关所在的行。
    """
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    config.compact_mode = False

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)   # 铁律：不许弹真窗口
        win.show()
        qapp.processEvents()

        win.ensure_page_loaded("crosshair")
        win.show_page("crosshair", animated=False, force=True)
        qapp.processEvents()
        page = win.pages["crosshair"]

        button = getattr(page, "master_switch_btn", None)
        assert button is not None, "准心页没有「去总开关」"
        button.click()
        qapp.processEvents()

        assert win._current_page_id == link.MASTER_SWITCH_PAGE_ID, (
            f"点了「去总开关」却停在 {win._current_page_id}")

        toggle = win.switches["crosshair"]
        target = getattr(win, "_search_hit_target", None)
        assert target is not None, "跳过去了但没有指给用户看 —— 17 颗开关里他还得自己找"
        # ⚠ 这里刻意**不写** `target.isAncestorOf(toggle)`：那样写的话，
        # 高亮退化成"整页"或"整张卡"时判据照样绿（页面也是那颗开关的祖先）。
        # ⭐ 一条"落点对不对"的判据，宽到把所有落点都算对，就等于没有。
        assert target is toggle or target is toggle.parentWidget(), (
            f"高亮落在了 {type(target).__name__}（不是那颗开关所在的行）—— "
            f"定位错行比不定位更糟")
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_an_unknown_config_key_reports_instead_of_pretending(qapp, monkeypatch):
    """反面：找不到那颗开关时必须回报 False，不许静悄悄地"成功"了。

    静默成功的后果很具体：按钮照常能点、页面照常跳到基础设置，
    只是**什么都没高亮**，而没有任何一处会知道这条路已经空转。
    """
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        assert win.reveal_feature_switch("crosshair_enabled") is True
        assert win.reveal_feature_switch("no_such_switch_enabled") is False
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


# ============================================== 3. 文案与兜底

def test_the_tooltip_always_spells_out_the_manual_path(crosshair_page):
    """⭐ 兜底不是"失败了弹一句话"，是"那句话本来就一直在"。"""
    tip = crosshair_page.master_switch_btn.toolTip()
    assert link.MASTER_SWITCH_PAGE_NAME in tip, f"tooltip 没说去哪一页：{tip!r}"
    assert link.MASTER_SWITCH_CARD_NAME in tip, f"tooltip 没说在哪张卡：{tip!r}"
    assert "准心" in tip, f"tooltip 没说是哪个功能的总开关：{tip!r}"


def test_the_page_name_in_the_copy_is_not_a_hand_written_literal():
    """三页不许各抄一份「基础设置」。

    ⭐ 文案里点名的目标名要跟真正的目标走。抄成字面量之后，
    那一页改名的当天就有三处对不上，而且**一处都不会报错**。
    """
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    offenders = []
    for name in ("crosshair_page.py", "screen_effects_page.py", "reload_sound_page.py"):
        path = repo / "pages" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if link.MASTER_SWITCH_CARD_NAME in node.value:
                offenders.append((name, node.lineno, node.value))
    assert not offenders, (
        f"这几页自己抄了「{link.MASTER_SWITCH_CARD_NAME}」这个卡片名："
        f"{offenders}\n统一从 widgets/master_switch_link.py 取。")


def test_the_button_text_does_not_flip_with_the_switch_state(
        crosshair_page, monkeypatch):
    """按钮文案不随开关状态改。

    「总开关不在这一页」是这一页的一条**常驻事实**，不是只在关着时才成立的
    提示。文案随状态跳变会让用户以为按钮的作用变了，而它一直是同一个动作。
    """
    from config import config

    before = crosshair_page.master_switch_btn.text()
    monkeypatch.setattr(config, "crosshair_enabled", True, raising=False)
    crosshair_page._sync_overview_status()
    assert crosshair_page.master_switch_btn.text() == before
    monkeypatch.setattr(config, "crosshair_enabled", False, raising=False)
    crosshair_page._sync_overview_status()
    assert crosshair_page.master_switch_btn.text() == before
