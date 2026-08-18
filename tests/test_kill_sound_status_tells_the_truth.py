# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-026/019/027/028/029：击杀音效页的状态必须和用户看到的一致。

**本轮最重的一条是 RN-026**：状态徽章写着「已配置 · 37 / 手枪 10/10」，
而下面 39 把枪**全部显示「不启用」**。两个数来自两个口径：

- 徽章数的是 `config.weapon_kill_sounds` 里的**原始值**；
- 每一行显示的是 `_get_style_display_text()`，它会把**解析不出来的风格**显示成「不启用」。

于是风格目录一动（改名/删除/换机器），两边就永久对不上，
**而没有任何东西报错**——没有异常、没有日志、没有判据。
既有的 35 个提到 kill_sound 的测试文件，一条都没拦住它。

⚠ 这一组判据的**共同要害**：必须造出「配了、但那个风格不存在」的状态，
否则两个口径给出的数字恰好相同，判据会全绿而毫无意义。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


class _DummyAudioManager:
    """只够把页面建起来的最小替身——不碰真实音频设备。

    关键：`kill_sound_styles` 里**只有 `styleA`**。
    配置里那些指向 `已删除的风格` 的武器，就是"配了但风格不在了"的那一批。
    """

    def __init__(self):
        self.kill_sound_styles = ["styleA"]
        self.weapon_kill_sound_styles = {"weapon_ak47": ["ak-only"]}
        self.weapon_sounds_dir = "sounds/weapon"
        self.kill_sounds_dir = "sounds/common"
        self._sounds = {}
        self.played = []

    def ensure_styles_scanned(self):
        return None

    def scan_kill_sound_styles(self):
        return self.kill_sound_styles

    def scan_weapon_kill_sound_styles(self):
        return self.weapon_kill_sound_styles

    def play_sound(self, key, channel_type=None):
        self.played.append(key)
        return False        # 播不出来，好让失败分支跑起来

    def load_sound(self, *a, **k):
        return True


#: 配置里的 4 把枪：2 把指向现有风格，2 把指向**已经不存在**的风格。
_CONFIG = {
    "weapon_glock": "styleA",        # 有效
    "weapon_ak47": "ak-only",        # 有效（武器专属）
    "weapon_awp": "已删除的风格",       # 失效
    "weapon_deagle": "也删了",         # 失效
}


@pytest.fixture()
def page(qapp, monkeypatch):
    import pages.kill_sound_page as mod

    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: _DummyAudioManager())
    monkeypatch.setattr(
        mod, "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [],
                        "issue_count": 0})
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", dict(_CONFIG), raising=False)
    p = mod.KillSoundPage()
    yield p
    p.deleteLater()
    qapp.processEvents()


# ------------------------------------------------------------ RN-026

def test_the_fixture_really_produces_stale_entries(page):
    """空转守卫：先证明这套夹具真的造出了「配了但风格不在」的状态。

    没有这一条，下面所有判据都可能是在一个"根本没有失效项"的世界里全绿。
    """
    stale = page._stale_weapon_count()
    assert stale == 2, f"夹具没造出预期的 2 个失效项（实际 {stale}），下面的判据会空转"


def _visible_chips(page):
    """徽章条上**当前真正显示着**的那几颗芯片。

    `AudioStatusBadgeBar` 用的是芯片复用池，隐藏的那些还留着上一次渲染的旧文字，
    不排掉就会读到过期内容。
    """
    from PySide6.QtWidgets import QLabel

    return [chip for chip in page.status_badge_label.findChildren(QLabel)
            if not chip.isHidden()]


def _badge_configured_number(page) -> int:
    """从**真正渲染出来的徽章文字**里把「已配置 · N」的 N 抠出来。

    ⚠ 这里刻意**不**去读 `_configured_weapon_count()`。第一版判据就是那么写的，
    回退验证当场逮住：断点改的是徽章实际使用的那个变量，而判据问的是辅助函数，
    两者不相干 —— 缺陷注进去了，判据照样绿。
    **用户看的是屏幕上那行字，判据就得落在那行字上。**
    """
    import re

    text = " ".join(chip.text() for chip in _visible_chips(page))
    m = re.search(r"已配置\s*·\s*(\d+)", text)
    assert m, f"徽章里找不到「已配置 · N」，判据失效了。实际文字：\n{text}"
    return int(m.group(1))


def test_badge_count_matches_what_the_rows_actually_show(page):
    """徽章上的「已配置 N」必须等于列表里真正不是「不启用」的行数。

    这就是 RN-026：两个数以前来自两个口径，风格一丢就永久对不上，
    而用户看到的是"顶部说配了 37 个，下面全是不启用"。
    """
    page._refresh_status_badge()
    rows_enabled = sum(
        1 for row in page.weapon_rows.values()
        if row.get_current_style() != page.DISABLED_STYLE_TEXT)
    shown = _badge_configured_number(page)
    assert shown == rows_enabled, (
        f"徽章上写着「已配置 · {shown}」，而列表里真正启用的只有 {rows_enabled} 行。"
        "两边必须走同一个口径（`_resolved_style`），否则风格一丢就长期自相矛盾。")
    assert rows_enabled == 2, "夹具预期有 2 行真正生效"


def test_stale_styles_are_named_not_silently_counted_as_configured(page):
    """失效项必须被**说出来**，不能静默算进「已配置」。

    ⚠ 这里断言的是「已失效」这个说法出现在用户读得到的文字里，
    而不是只断言数字变小了 —— 数字变小用户只会觉得"我的配置怎么少了"。
    """
    page._refresh_status_badge()

    # ① 徽章上要看得见「N 项失效」
    badge = " ".join(
        chip.text() for chip in _visible_chips(page))
    assert "失效" in badge, f"徽章上没提失效项。实际：{badge}"
    assert "2" in badge, "没说清有几项失效"

    # ② ⚠ 「怎么修」必须落在**可见**的那一行上。
    #    只写进 `summary_label` 是不算的 —— 它是 RN-009 那个建出来就 hide 的死控件，
    #    写进去等于没写（外审复跑时报的「醒目报错却无修复引导」就是这个）。
    visible_hint = page.category_overview_hint_label.text()
    assert "已经不在了" in visible_hint or "失效" in visible_hint, (
        f"可见的提示行里没说失效这件事，用户看到两个红黄警告却不知道怎么办。"
        f"实际：{visible_hint}")
    assert "重新选" in visible_hint, f"没告诉用户怎么修。实际：{visible_hint}"


# ------------------------------------------------------------ RN-028

def test_category_lookup_survives_a_renamed_tab(page):
    """分类名按下标取，不拿页签**文字**当字典键。

    页签文案哪天加个计数后缀（「手枪 10/10」这类），拿文字查表会静默返回 `[]`，
    分类徽章变成 `0/0` 而不报错。与 kill_voice 的 RN-020 同形。
    """
    page.tab_widget.setCurrentIndex(0)
    original = page._get_current_category_name()
    assert original in page.CATEGORIES

    page.tab_widget.setTabText(0, f"{original} 10/10")
    assert page._get_current_category_name() == original, (
        "页签文案一加后缀，分类就查不到了 —— 说明还在拿显示文字当数据键")
    assert page._get_current_category_weapons(), "分类武器列表退化成空了"


# ------------------------------------------------------------ RN-029

def test_a_vanished_style_is_not_reported_as_a_broken_sound_card(page, monkeypatch):
    """配的风格没了 ⇒ 说「风格已经不在了」，**不能**说「音频设备不可用」。

    ⚠ 断言的是两条路径给的**不同措辞**，不是"有没有提示"——
    两条路径都会给提示，只断言"有反应"的判据会全绿（RN-012/017 那次的教训）。
    """
    said = []
    import widgets.preview_feedback as pf
    monkeypatch.setattr(pf, "report_preview_failure",
                        lambda page_, reason, detail="", **k: said.append(reason))
    import pages.kill_sound_page as mod
    monkeypatch.setattr(mod, "report_preview_failure",
                        lambda page_, reason, detail="", **k: said.append(reason))

    # 让下拉框停在一个两张表里都没有的风格上 —— 别的页删掉风格、本页还没刷新
    row = page.weapon_rows["weapon_glock"]
    row.update_style_options([page.DISABLED_STYLE_TEXT, "styleA", "风格没了"])
    row.set_current_style("风格没了")

    page._test_weapon_sound("weapon_glock", 1)

    assert said, "试听一个已消失的风格，一声不吭"
    assert said[-1] == pf.PreviewFailure.STALE_STYLE, (
        f"报的是 {said[-1]!r}，不是「风格已不在」。"
        "报成 DEVICE 会把用户支去查声卡和驱动，而真实原因是那个风格被删了。")
    assert not page.audio_manager.played, "风格都没了还去播，等于拿失败当诊断依据"


# ------------------------------------------------------------ RN-019 / RN-027

def test_status_badge_computes_the_configured_names_once(page):
    hits = []
    original = page._configured_weapon_names

    def spy(*a, **kw):
        hits.append(1)
        return original(*a, **kw)

    page._configured_weapon_names = spy
    page._refresh_status_badge()

    assert hits, "一次都没算，判据在空转"
    assert len(hits) == 1, (
        f"`_configured_weapon_names()` 在一次状态刷新里被算了 {len(hits)} 遍；"
        "两次之间没有任何东西改变它的输入，结果必然逐字相同（RN-019）。")


def test_managing_styles_touches_each_weapon_row_exactly_once(page, qapp):
    calls = []
    for weapon, row in page.weapon_rows.items():
        original = row.set_current_style

        def spy(value, _w=weapon, _orig=original):
            calls.append(_w)
            return _orig(value)

        row.set_current_style = spy

    page._on_styles_managed()
    qapp.processEvents()

    assert calls, "刷新之后一把武器都没被更新，判据在空转"
    duplicated = sorted({w for w in calls if calls.count(w) > 1})
    assert not duplicated, (
        f"这些武器的下拉框被重复设置了：{duplicated}\n"
        "`_refresh_style_catalog()` 已经逐把设过一遍，后面别再跟 `load_settings()`（RN-027）。")
