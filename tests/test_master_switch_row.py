# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""状态摆在这儿，开关也得在这儿（RN-144 升级版 + RN-147 + RN-155）。

## 为什么把「去总开关」推翻重做

RN-144 第一版给准心 / 屏幕特效 / 换弹音效三页各加了一颗「去总开关」按钮
——**跳过去**开。改完复跑，外审两轮合计 **15 发 15 中**全部反对：

    「本页无法直接开启功能，必须跳转至「基础设置」开启总开关，操作流程割裂。」

⚠ 要害在于后 6 发**看的是已经装好那颗按钮的画面** —— 它不是没看见跳转，
是看见了仍然判"这不够"。⭐ **一致性到这个量级就不是怀疑清单，是结论。**

⇒ 本轮把跳转换成**就地开关**，并把那颗跳转按钮撤掉（留着就是同屏重复入口）。

## 这份文件里最要紧的三条

1. `test_flipping_the_page_switch_runs_the_real_side_effects`
   ⭐⭐ **这条是整个改动的命门。** `_on_switch_changed` 上挂着一长串副作用：
   准心的 pywin32 前置检查与显隐、开镜放大的启停、死亡刷短视频的预热/收尾、
   屏幕特效的叠加层同步、`sync_legacy_gun_sound_flags`、`save_config`。
   页内开关**只要自己 `setattr(config, key, value)`，这些一个都拿不到** ——
   得到的是"界面显示已开、功能根本没起"，比没有开关糟得多（RN-107 族的最恶形态）。
   ⇒ 判据盯的不是"config 变了没有"，是**那条唯一链路有没有被走过**。

2. `test_a_feature_that_refuses_to_turn_on_snaps_the_page_switch_back`
   ⭐ 准心在缺 pywin32 时会**回滚并提前 return** —— 走不到函数末尾的广播。
   所以页内开关不能只靠广播，必须自己**回读 config 的实际值**。
   ⚠ 那条分支会弹 `QMessageBox` ——**模态框在测试进程里是卡死不是失败**
   （RN-157 刚踩过一次，300 秒挂死）。这份文件里凡是可能走到它的，
   一律先把 `QMessageBox.warning` 换掉。

3. `test_the_old_jump_button_is_gone`
   就地开关落地之后，「去总开关」只剩重复功能。⭐ **修一个问题时留下的旧形态，
   会变成下一个问题**（RN-102 族：同屏重复入口）。

## 空转守卫

`test_the_side_effect_spy_would_actually_notice` —— 上面第 1 条靠一个 spy 判断
"链路走没走过"。**spy 装错地方就永远看不到调用，判据会一直绿。**
所以先证明"不接线的时候它确实是 0 次"。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

REPO = Path(__file__).resolve().parents[1]
# `_audit_neutralize`（设备中和表）住在 scripts/ 里，且只准有一份。
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from widgets import master_switch_link as link  # noqa: E402

#: 音效家族四页 + 这一轮一起收进来的两页，以及它们的 config 键。
#: ⭐ 写死在这儿是故意的：判据要拿一份**独立于产品**的清单去对，
#: 直接读产品的类属性等于拿被测对象当答案（本仓已有过好几条这么假绿的）。
EXPECTED_KEYS = {
    "kill_sound": "kill_sound_enabled",
    "kill_voice": "kill_voice_enabled",
    "switch_weapon": "switch_weapon_sound_enabled",
    "reload_sound": "reload_sound_enabled",
    "crosshair": "crosshair_enabled",
    "screen_effects": "screen_effects_enabled",
    "kill_icon": "kill_icon_enabled",
    # RN-162（批 4）：批 1 当时**故意留下**的那一页。理由是它已关档、已锁基线，
    # 顺手改会让那一轮失去可比的基线。⭐ 但「以后补」只有真的补了才算数 ——
    # 这一行就是那笔账被结清的证据。
    "hud_color": "hud_rules_enabled",
    # RN-189（批 6）：首页 17 颗总开关里当时有 **8 颗**在它自己那一页上拨不到。
    # ⭐ 这一批不是"顺手扩范围"，是**把分母补齐** —— 见
    #   `test_every_home_switch_has_a_page_that_hosts_it` 的说明：
    #   原来那两条判据都遍历本表，而本表是「已经装了的页」，
    #   于是「本该有却没有」对它们结构上不可见。
    "gun_sound": "gun_sound_enabled",
    "death_sound": "death_sound_enabled",
    "magnifier": "magnifier_enabled",
    "flash": "flash_enabled",
    "music": "music_enabled",
    "utility": "utility_guide_enabled",
    "voice_output": "voice_output_enabled",
}


@pytest.fixture
def main_window(qapp, monkeypatch):
    """一个离屏主窗口。**铁律：不许弹真窗口、不许弹模态框。**"""
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    config.compact_mode = False
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    # ⚠ RN-157：模态框在测试进程里是**卡死**不是失败。准心缺 pywin32 那条
    # 分支会弹 warning，这里先换掉——不换的话这份文件会挂 300 秒而不是红。
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    qapp.processEvents()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _page_with_row(win, qapp, page_id):
    """把页面切出来，并把它的总开关行取回来。"""
    win.ensure_page_loaded(page_id)
    win.show_page(page_id, animated=False, force=True)
    qapp.processEvents()
    page = win.pages[page_id]
    row = getattr(page, "master_switch_row", None)
    assert row is not None, f"{page_id} 页没有总开关行"
    return page, row


# ====================================== 1. 命门：副作用那条唯一链路

def test_flipping_the_page_switch_runs_the_real_side_effects(
        main_window, qapp, monkeypatch):
    """⭐⭐ 页内拨开关，必须走 `_on_switch_changed` 那条唯一链路。

    不走的话得到的是"显示开了、功能没起"——而这件事**不会有任何一处报错**。
    """
    seen = []
    original = main_window._on_switch_changed

    def spy(key, checked):
        seen.append((key, checked))
        return original(key, checked)

    monkeypatch.setattr(main_window, "_on_switch_changed", spy)

    page, row = _page_with_row(main_window, qapp, "screen_effects")
    # ⚠ **拨到当前值的反面**，不写死 True：写死的话，夹具里这一项恰好已经是
    # True 的那天，这条判据就变成"什么都没拨"而照样绿
    # （RN-141/142 那一族：不钉前置状态的判据，绿不绿取决于前面跑过谁）。
    target = not row.is_checked()
    row.set_checked_by_user(target)
    qapp.processEvents()

    assert ("screen_effects_enabled", target) in seen, (
        "页内开关没有走 _on_switch_changed —— 它自己写了 config。\n"
        "那样的话叠加层同步 / save_config / 各页的特殊处理**一个都不会跑**，"
        "而界面会显示「已开启」。")


def test_the_side_effect_spy_would_actually_notice(main_window, qapp, monkeypatch):
    """空转守卫：证明上面那个 spy 装对了地方。

    ⭐ **一个"某某被调用过"的判据，必须先证明它在没被调用时是红的**，
    否则 spy 挂错位置就会变成一条永远绿的判据（本仓九种判据错法之一）。
    """
    seen = []
    original = main_window._on_switch_changed
    monkeypatch.setattr(
        main_window, "_on_switch_changed",
        lambda key, checked: (seen.append((key, checked)), original(key, checked))[1])

    # 什么都不做的时候，它必须是 0 次。
    qapp.processEvents()
    assert seen == [], f"还没拨开关就已经记到调用了：{seen}"

    # 直接拨首页那颗开关，spy 必须看得见——证明它挂在真正的链路上。
    # ⚠ 用 `toggle()` 不用 `setChecked()`：后者**不发信号**（见
    # `gui_widget.set_feature_enabled` 的注释），拿它做空转守卫会永远是空的，
    # 那这条守卫自己就先假红/假绿了。`toggle()` 才是鼠标点击走的那条。
    toggle = main_window._find_feature_switch("screen_effects_enabled")
    assert toggle is not None
    toggle.toggle()
    qapp.processEvents()
    assert seen, "spy 连首页开关自己的信号都看不见 —— 它挂错地方了"


def test_the_setter_does_not_write_config_behind_the_chain():
    """AST：`set_feature_enabled` 不许自己给 config 赋值。

    ⭐ 上面那条行为判据只覆盖 screen_effects 一页。这一条守的是**写法**：
    只要函数体里出现 `setattr(self.config, ...)` 或 `self.config.<key> = ...`，
    就说明有人绕开了那条唯一链路 —— 哪怕当时那一页碰巧看不出毛病。
    """
    tree = ast.parse((REPO / "gui_widget.py").read_text(encoding="utf-8"))
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "set_feature_enabled":
            target = node
            break
    assert target is not None, "gui_widget 里找不到 set_feature_enabled —— 判据锚点已失效"

    offenders = []
    for node in ast.walk(target):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "setattr":
            offenders.append(("setattr", node.lineno))
        for tgt in (node.targets if isinstance(node, ast.Assign) else []):
            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Attribute) \
                    and tgt.value.attr == "config":
                offenders.append((tgt.attr, node.lineno))
    assert not offenders, (
        f"set_feature_enabled 自己写了 config：{offenders}\n"
        "它必须去拨首页那颗开关，让 _on_switch_changed 把副作用跑完。")


# ====================================== 2. 双向同步

def test_flipping_the_page_switch_moves_the_home_switch(main_window, qapp):
    """页内 → 首页。"""
    page, row = _page_with_row(main_window, qapp, "reload_sound")
    home = main_window._find_feature_switch("reload_sound_enabled")
    assert home is not None

    row.set_checked_by_user(not home.isChecked())
    qapp.processEvents()
    assert row.is_checked() == home.isChecked(), (
        "页内开关和首页那颗对不上 —— 同一件事有了两个显示，"
        "下一次 save_config 落谁的值取决于谁最后被碰过（RN-079 的老账）")


def test_flipping_the_home_switch_moves_the_page_switch(main_window, qapp):
    """首页 → 页内。**这个方向靠广播，最容易漏。**

    用户在功能页开了开关，切回首页关掉，再切回来 —— 页内那颗必须已经跟上。
    """
    page, row = _page_with_row(main_window, qapp, "reload_sound")
    home = main_window._find_feature_switch("reload_sound_enabled")

    home.toggle()       # 模拟用户在首页点了它（setChecked 不发信号）
    qapp.processEvents()
    assert row.is_checked() == home.isChecked(), (
        "在首页拨了开关，功能页那颗没跟上 —— 广播没接或者注册表没登记")


def test_a_feature_that_refuses_to_turn_on_snaps_the_page_switch_back(
        main_window, qapp, monkeypatch):
    """⭐ 开不起来的功能，页内开关必须自己弹回去。

    准心在缺 pywin32 时会把 `config.crosshair_enabled` 回滚成 False
    并**提前 return** —— 走不到函数末尾的广播。
    ⇒ 页内开关不能只靠广播，必须回读 config 的**实际值**。

    ⭐ 这正是"不信任自己写进去的值"的价值：写进去的是 True，实际是 False。
    """
    from config import config

    monkeypatch.setattr(main_window, "_crosshair_win32_available", False, raising=False)
    monkeypatch.setattr(config, "crosshair_enabled", False, raising=False)

    page, row = _page_with_row(main_window, qapp, "crosshair")
    row.set_checked_by_user(True)
    qapp.processEvents()

    assert bool(getattr(config, "crosshair_enabled", False)) is False, (
        "前置不满足却把 config 写成了开 —— 那是三态不一致的起点")
    assert row.is_checked() is False, (
        "功能没开起来，页内开关却停在「开」的位置 —— "
        "用户会以为已经生效，进游戏发现没有")


def test_the_row_snaps_back_when_nothing_actually_happened(
        main_window, qapp, monkeypatch):
    """⭐ 拨了但**根本没生效**时，开关必须自己弹回去。

    ⚠ 这条是补出来的，补的是上面那条 `..._snaps_the_page_switch_back`
    的一个盲区 —— **回退验证 0/1 当场逮到**：
    我给准心那条回滚分支也加了一次广播，于是"自己回读"这条路被广播兜住了，
    砍掉它判据照样绿。
    ⭐ **两条路互为兜底时，单独砍掉任何一条，判据都逮不住** ——
    冗余是好设计，但它会让判据失去分辨力。⇒ 要测哪一条，就得造一个
    **只有那一条能救**的场景。

    这里的场景是：首页压根没有那颗开关（`set_feature_enabled` 回报 False）
    ⇒ 整条链路一步都没走 ⇒ 没有任何广播 ⇒ 只剩"自己回读 config"。
    """
    page, row = _page_with_row(main_window, qapp, "reload_sound")
    before = row.is_checked()
    monkeypatch.setattr(main_window, "set_feature_enabled",
                        lambda key, enabled: False)

    row.set_checked_by_user(not before)
    qapp.processEvents()
    assert row.is_checked() is before, (
        "什么都没发生，开关却停在了新位置 —— 用户会以为已经生效")


def test_a_missing_home_switch_reports_instead_of_pretending(main_window):
    """反面：找不到那颗开关时回报 False，不许静悄悄地"成功"。"""
    assert main_window.set_feature_enabled("crosshair_enabled", True) is True
    assert main_window.set_feature_enabled("no_such_switch_enabled", True) is False


# ====================================== 3. 铺开面与位置

@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_every_page_that_shows_master_state_offers_the_switch(
        main_window, qapp, page_id):
    """七页都要有，且**开关就在状态卡里**。

    "就在状态卡里"是要害 —— 摆到页尾就等于没摆
    （网站那轮实测：解释性文字放在困惑发生的位置之后 = 没放）。
    """
    page, row = _page_with_row(main_window, qapp, page_id)
    card = getattr(page, "status_card", None)
    assert card is not None, f"{page_id} 页没有 status_card"
    assert card.isAncestorOf(row), (
        f"{page_id} 页的总开关行不在状态卡里 —— 状态在一处、动作在另一处，等于没修")


@pytest.mark.parametrize("page_id,key", sorted(EXPECTED_KEYS.items()))
def test_the_config_key_each_page_declares_really_exists_at_home(
        main_window, qapp, page_id, key):
    """每页填的 config 键必须真的对应首页一颗开关，**而且是对的那一颗**。

    ⭐ 填错一个字母的后果是**静默空转**：开关照样画得出来、点得动，
    只是拨的是另一个功能。这条判据把"填错"从运行时变成红灯。

    ⚠ **第一版是假绿的，回退验证当场 0/1。** 它写的是
    `_find_feature_switch(key)`——`key` 来自本文件的 `EXPECTED_KEYS`，
    也就是说它拿**我自己的答案**去问首页，压根没看页面声明了什么。
    把页面的键改成另一个真实存在的键（`kill_icon_headshot_enabled`），
    它照样绿。
    ⭐ **判据必须去读被测对象的实际值，不能只校验自己那份期望表** ——
    否则测的是"我抄得对不对"，不是"产品对不对"。
    """
    page, row = _page_with_row(main_window, qapp, page_id)
    assert row.config_key == key, (
        f"{page_id} 页的总开关行拨的是 {row.config_key!r}，应该是 {key!r} —— "
        f"填错键不会报错，只会静默地拨错功能")
    assert main_window._find_feature_switch(row.config_key) is not None, (
        f"{page_id} 声明的总开关键 {row.config_key!r} 在首页「功能开关」里不存在")


def test_the_kill_icon_master_switch_is_not_buried_among_sub_options(
        main_window, qapp):
    """RN-155：「开启击杀图标」不许还留在子选项那一堆里。

    原样是一个普通 QCheckBox，夹在「入场淡入」「爆头用专属图标」中间、默认未勾选。
    外审 5/6 票："导入素材后极易因没开开关而在局内失效"。
    ⭐ **层级要靠位置和分量表达，不能靠文案。**
    """
    from PySide6.QtWidgets import QCheckBox

    page, row = _page_with_row(main_window, qapp, "kill_icon")
    strays = [cb for cb in page.findChildren(QCheckBox)
              if "开启击杀图标" in cb.text()]
    assert not strays, (
        "「开启击杀图标」还是一个混在子选项里的复选框："
        f"{[cb.text() for cb in strays]}\n它已经有了状态卡上的总开关行，"
        "留着旧的就是同一件事两个开关（RN-107 族）")


def test_the_old_jump_button_is_gone(main_window, qapp):
    """就地开关落地后，「去总开关」是重复入口，必须撤掉。

    ⭐ **修一个问题时留下的旧形态，会变成下一个问题**
    （RN-154 就是这么冒出来的：去掉重复文案之后露出三个并列入口）。
    """
    for page_id in sorted(EXPECTED_KEYS):
        page, _row = _page_with_row(main_window, qapp, page_id)
        assert getattr(page, "master_switch_btn", None) is None, (
            f"{page_id} 页还留着「去总开关」按钮 —— 和就地开关重复")
    assert not hasattr(link, "make_master_switch_button"), (
        "widgets/master_switch_link.py 里那颗按钮的工厂还在 —— "
        "没有调用者的公共 API 就是死代码（RN-009 那个建出来就 hide 的控件同族）")


def test_the_badge_follows_the_switch_it_describes(main_window, qapp):
    """⭐ 拨了开关，那条描述它的徽章必须跟着改（RN-107 族）。

    击杀图标页顶部写着「显示 · 未开启」。开关就在同一行的右边 ——
    **拨过去之后那句话还说"未开启"，是同屏之内的自相矛盾**，
    而且它比"没有开关"更让人confused：用户明明看见自己拨了。

    ⚠ 这条专治一个很容易写出来的优化：`refresh()` 里"值没变就早退"。
    用户拨的就是这一颗时，开关早就是新值了 —— 一早退，页面就永远收不到通知。
    """
    from PySide6.QtWidgets import QLabel

    page, row = _page_with_row(main_window, qapp, "kill_icon")

    def badge_texts():
        chip = getattr(page, "status_badge_label", None)
        assert chip is not None
        return [lab.text() for lab in chip.findChildren(QLabel)]

    row.set_checked_by_user(not row.is_checked())
    qapp.processEvents()
    after = " / ".join(badge_texts())
    wanted = "已开启" if row.is_checked() else "未开启"
    assert f"显示 · {wanted}" in after, (
        f"开关现在是 {row.is_checked()}，徽章却写着：{after}\n"
        "同一张卡上两处说法不一致 —— 用户明明看见自己拨了")


def test_the_kill_icon_player_is_driven_from_the_one_chain(main_window, qapp):
    """⭐ 首页拨击杀图标的总开关，素材也要预热 / 收尾。

    **这条补的是一个既有的不对称**：击杀图标页上那颗复选框一直会调
    `enable_kill_icons()` / `disable_kill_icons()`，而首页那颗**同名的总开关
    只写 config**。同一个开关从两个地方拨，效果不一样，谁都不报错。

    ⭐ **同一件事有两条链路时，短的那条一定缺东西。**
    """
    calls = []

    class _SpyPlayer:
        def enable_kill_icons(self):
            calls.append("enable")

        def disable_kill_icons(self):
            calls.append("disable")

    main_window.kill_icon_player = _SpyPlayer()
    home = main_window._find_feature_switch("kill_icon_enabled")
    assert home is not None

    home.toggle()          # 模拟用户在**首页**点它
    qapp.processEvents()
    assert calls, (
        "在首页拨了击杀图标总开关，播放器一点反应都没有 —— "
        "开完素材不预热、关掉时正在播的那张不停")
    assert calls[-1] == ("enable" if home.isChecked() else "disable"), (
        f"拨到 {home.isChecked()} 却调了 {calls[-1]}")


# ====================================== 4. 文案

def test_the_row_spells_out_that_it_is_the_same_switch_as_home(main_window, qapp):
    """⭐ 兜底不是"失败了弹一句话"，是"那句话本来就一直在"。

    页内这颗和首页那颗是**同一个开关**。不说清楚的话，用户会以为
    这是一个"本页专用"的开关，而它其实是全局的。
    """
    page, row = _page_with_row(main_window, qapp, "crosshair")
    tip = row.toolTip()
    assert link.MASTER_SWITCH_PAGE_NAME in tip, f"tooltip 没说它和哪一页同源：{tip!r}"
    assert link.MASTER_SWITCH_CARD_NAME in tip, f"tooltip 没说在哪张卡：{tip!r}"



def _docstring_nodes(tree) -> set:
    """模块/类/函数的 docstring 节点 —— **它们不是用户看得见的文案**。

    ⚠ 不排除的话，`flash` 的「创建基础设置标签页」和 `utility` 的
    「创建基础设置选项卡」这两句 docstring 会被当成「把用户支去基础设置」报上来。
    判据管的是屏幕上的字，不是源码里的字。
    （⚠ 顺带一条：**docstring 里别再写三引号** —— 上一版就是这么把自己截断的。）
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(body[0].value)
    return out


def _own_tab_titles(tree) -> set:
    """这一页**自己那些页签的名字**（`addTab(widget, "…")` 的第二个实参）。

    ⭐⭐ 这条排除是 RN-075 那个陷阱打到判据自己身上：
    **「基础设置」既是首页的名字，也是 `flash` / `utility` 页里一个页签的名字。**
    `flash_page.py` 有一句 `self.tab_widget.addTab(tab, "基础设置")` ——
    那是个**标签**，不是"去那儿开开关"的**指路**。
    一条只比字符串的判据分不出这两者，于是把页签名字也报成缺陷。

    ⇒ 排除的依据取自源码自身（谁真的被 addTab 过），不是一份手抄名单。
    """
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "addTab" and len(node.args) >= 2):
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.add(arg.value.strip())
    return out

def test_no_page_with_its_own_switch_still_sends_the_user_away():
    """⭐ 有了就地开关的页，不许还写着「总开关在「基础设置」里」。

    本轮实测：这七页里一共**13 处**文案在说"去别处开" ——
    页头副标题 ×4、底栏提示 ×4、准心的标题行提示 ×1、准心的两个 tooltip、
    一个 QMessageBox、屏幕特效的状态文案。开关搬过来的那一刻，
    **这 13 句同时变成假的，而它们自己不会知道**。

    ⭐ 与 RN-138 完全同一个形状（那次是把卡片藏了，指向它的三处一处没跟上）：
    **一处改动不会去通知描述它的文案。** 所以这件事只能靠判据扫。

    ⚠ 判据故意扫的是「基础设置」这个**页面名**而不是某句具体的话 ——
    扫具体句子的话，换个说法就绕过去了。

    ⚠⚠ **页面清单原来是手抄的七页，2026-08-22（批 4）改成从 `EXPECTED_KEYS` 推导。**
    RN-162 给 `hud_color` 装上就地开关时，那一页那句
    「总开关在"基础设置 -> 动态HUD"」**原封不动地活着**，而这条判据看不见它 ——
    因为它不在那份手抄清单里。回退验证当场判这条断点**假绿**。
    ⭐⭐ **一份"哪些页适用"的手抄清单，就是一个会随着加页而扩大的盲区** ——
    而它扩大的时候不报错。清单必须跟"谁真的有开关"长在同一个地方。
    """
    offenders = []
    for page_id in sorted(EXPECTED_KEYS):
        path = REPO / "pages" / f"{page_id}_page.py"
        assert path.exists(), (
            f"{page_id} 推不出页面文件（{path.name} 不存在）—— "
            "页面 id 和文件名对不上时这一页会被静默跳过，判据对它就是瞎的")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstring_nodes(tree)
        own_tabs = _own_tab_titles(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if node in skip:
                continue
            # ⚠ 按**取值精确相等**放行页签名，不按节点身份 ——
            # `utility` 的 `_current_tab_text()` 里有一句 `return "基础设置"`
            # 作兜底，它同样是这一页页签的名字，却不是 `addTab` 的实参。
            # ⭐ 整句里**嵌着**这四个字的照样报（那才是指路），
            #   只有"整个字符串就等于某个页签名"才算标签。
            if node.value.strip() in own_tabs:
                continue
            if link.MASTER_SWITCH_PAGE_NAME in node.value:
                offenders.append((path.name, node.lineno, node.value[:50]))
    assert not offenders, (
        f"这些页有自己的总开关了，文案却还在把用户支去「{link.MASTER_SWITCH_PAGE_NAME}」：\n"
        + "\n".join(f"  {n}:{ln}  {t}" for n, ln, t in offenders)
        + "\n⭐ 开关搬过来的那一刻这些话就变成假的了，而它们自己不会知道。")


def test_no_copy_about_the_master_switch_describes_where_it_sits():
    """⭐⭐ 说到总开关的文案，**不许描述它在哪儿**。

    这条是本轮踩了**两次**才写出来的：

    1. 开关从「基础设置」搬到本页 ⇒ 13 处「总开关在「基础设置」里」同时变成假的。
       我修完，并写了 `..._still_sends_the_user_away` 扫「基础设置」这个页面名。
    2. **下一稿**又把开关从状态行右端挪到卡片第一行 ⇒ 我为第 1 步写的新文案
       「右上角那颗总开关」**又全部变成假的**，而那条新判据一条都扫不到 ——
       它锁的是上一次那个形状（页面名），不是这类问题。

    ⭐⭐ **给"上次那个 bug"写的判据，挡不住"同一类的下一个 bug"。**
    位置词是会过期的：控件一挪，所有描述它位置的话同时作废，
    而它们分散在 7 个文件的副标题 / tooltip / 弹框 / 状态文案里。

    ⇒ 唯一稳的做法是**根本不描述位置** —— 说它是什么、管什么，别说它在哪儿。
    """
    position_words = ("右上角", "左上角", "右下角", "左下角",
                      "顶部", "底部", "上面那", "下面那", "旁边那颗")
    offenders = []
    for path in sorted((REPO / "pages").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # ⚠ **文档字符串要摘掉。** 第一版没摘，当场逮到 `flash_page.py` 里
        # 一句讲历史的 docstring —— 那是写给人看的记录，**本来就该描述位置**。
        # ⭐ 一条判据扫得太宽，代价不是"多报几条"，是**它会逼人把对的东西改错**。
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = node.body[0] if node.body else None
                if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) \
                        and isinstance(doc.value.value, str):
                    docstrings.add(id(doc.value))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings:
                continue
            text = node.value
            if link.ROW_LABEL_TEXT not in text:
                continue
            for word in position_words:
                if word in text:
                    offenders.append((path.name, node.lineno, word, text[:44]))
    assert not offenders, (
        "这些文案在描述总开关的位置：\n"
        + "\n".join(f"  {n}:{ln}  含「{w}」  {t}" for n, ln, w, t in offenders)
        + "\n⭐ 控件一挪，这些话同时作废，而且没有任何一处会报错。"
        "\n说它管什么，别说它在哪儿。")


def test_the_status_chip_does_not_repeat_the_word_next_to_it():
    """⭐ 徽章说状态、开关给动作 —— 别在一行里把「总开关」说两遍。

    实测：kill_icon 与 screen_effects 的状态条原来各有一颗「总开关 · …」徽章，
    而 RN-144 升级版之后**同一行的右端就是那颗总开关**。
    ⭐ 同屏重复不只是啰嗦 —— 它让人以为那是两件不同的事。

    ⚠ 这条只管**状态条上的徽章**，不管别处正常提到总开关的句子。
    """
    offenders = []
    for name in ("kill_icon_page.py", "screen_effects_page.py",
                 "crosshair_page.py", "sound_page_base.py"):
        path = REPO / "pages" / name
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if link.ROW_LABEL_TEXT + " · " in stripped:
                offenders.append((name, lineno, stripped[:60]))
    assert not offenders, (
        f"状态条徽章里还写着「{link.ROW_LABEL_TEXT} · 」，"
        f"而同一行右端就是那颗{link.ROW_LABEL_TEXT}：{offenders}")


def test_the_page_name_in_the_copy_is_not_a_hand_written_literal():
    """各页不许自己抄一份「功能开关」。

    ⭐ 文案里点名的目标名要跟真正的目标走。抄成字面量之后，
    那一页改名的当天就有好几处对不上，而且**一处都不会报错**。
    """
    offenders = []
    for name in ("crosshair_page.py", "screen_effects_page.py",
                 "reload_sound_page.py", "kill_icon_page.py", "sound_page_base.py"):
        path = REPO / "pages" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if link.MASTER_SWITCH_CARD_NAME in node.value:
                offenders.append((name, node.lineno, node.value))
    assert not offenders, (
        f"这几页自己抄了「{link.MASTER_SWITCH_CARD_NAME}」这个卡片名：{offenders}\n"
        "统一从 widgets/master_switch_link.py 取。")


# ==================================================== 覆盖面：谁**本该**有就地开关

#: 首页「功能开关」里**不对应任何页面**的开关，写明理由。
#: ⭐ 每一条都要有依据 —— 一张没有理由的豁免表，跟没有判据是一回事。
NO_PAGE_OF_ITS_OWN = {
    "spectator": "「观战静音」是全局行为（观战时压低音量），没有属于它的功能页；"
                 "它只在首页那张卡里出现，不存在"
                 "「用户站在某一页上却找不到开关」这个局面。",
}

#: 页面**已经**能就地拨这个开关，但用的不是共用的 `MasterSwitchRow`。
#: ⚠ 这不是豁免"能不能拨"，是记下"它走的是第二条链路"这笔账。
HOSTS_IT_WITH_ITS_OWN_CONTROL = {
    "fun_afterlife":
        "`fun_page.py` 有一张标题就叫「总开关」的卡，里面是手搓的 QCheckBox。"
        "⚠ 它 `setattr(config, ...)` **自己写**，再自己调 preheat/shutdown —— "
        "而首页那颗开关的 `_on_switch_changed` 也做同一串事。"
        "⭐ 同一个开关两条链路，短的那条缺的是「同步首页那颗的显示」"
        "（RN-155 在 kill_icon 上踩过一模一样的）。"
        "⇒ 改成共用行要连带改 `FunPage(controller)` 的独立构造用法与它的判据，"
        "那是这一页自己翻新时的活，记在 **RN-190**。",
}


def _home_switch_configs() -> list[tuple[str, str, str]]:
    """首页「功能开关」卡里那张表 —— (switch_id, 显示名, config 键)。

    从 `gui_widget.py` 的 AST 里取，因为它是**产品事实**：
    首页上真的画出了这么多颗开关。判据要的正是这个分母。
    """
    tree = ast.parse((REPO / "gui_widget.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "switch_configs"):
            return [(e.elts[0].value, e.elts[1].value, e.elts[2].value)
                    for e in node.value.elts]
    raise AssertionError(
        "在 gui_widget.py 里找不到 `switch_configs` —— 判据的锚点过期了。"
        "这份表是「首页有哪些总开关」的唯一真相源，别在判据里另抄一份。")


def test_every_home_switch_has_a_page_that_hosts_it():
    """⭐⭐ 首页上有的总开关，它那一页就得能就地拨。

    ⚠⚠ **这条判据补的是上面两条判据的分母。**
    `test_no_page_with_its_own_switch_still_sends_the_user_away` 和
    `test_no_copy_about_the_master_switch_describes_where_it_sits`
    都遍历 `EXPECTED_KEYS` —— 而那是**"已经装了就地开关的页"**。
    于是一页「本该有却没有」，对它们**结构上不可见**：
    它们能确认现状不倒退，**永远发现不了现状本身就是缺的**。

    ⭐⭐ **一条只遍历"已合规对象"的判据，它的分母是由结论决定的。**
      读起来是"这条规则在生效"，实际是"凡是符合的都符合"。

    实测（2026-08-22）：首页 **17 颗**开关，只有 **8** 页装了就地开关，
    **9 颗缺**（其中 `spectator` 没有属于它的页面，见 `NO_PAGE_OF_ITS_OWN`）。
    而 `magnifier` / `utility` 两页的副标题还在**无条件**写
    「先去「基础设置」打开总开关」—— 那正是 RN-034 一直没结干净的那一笔。

    分母取首页那张 `switch_configs`：**首页真的画了几颗开关，就是几颗**。
    """
    switches = _home_switch_configs()
    assert len(switches) >= 15, (
        f"只读到 {len(switches)} 颗首页开关 —— 判据在空转，先修取表那一段")

    missing = []
    for switch_id, name, config_key in switches:
        if switch_id in NO_PAGE_OF_ITS_OWN:
            continue
        if switch_id in HOSTS_IT_WITH_ITS_OWN_CONTROL:
            continue
        if config_key in set(EXPECTED_KEYS.values()):
            continue
        missing.append(f"{switch_id}（{name} / {config_key}）")

    assert not missing, (
        f"首页有 {len(switches)} 颗总开关，其中 {len(missing)} 颗**在它自己那一页上拨不到**：\n  "
        + "\n  ".join(missing)
        + "\n⭐ 用户站在功能页上，却要被支去另一页才能开这个功能。\n"
        "  要么给那一页装上 `make_master_switch_row(...)` 并把 EXPECTED_KEYS 补齐，\n"
        "  要么在 NO_PAGE_OF_ITS_OWN 里写明它为什么不该有 —— **别把这一行删掉了事**。")
