# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声「整套套用」按套系配（2026-09-17 批 101，`core/gun_sound_series`）。

## 缺陷

枪声的风格是 per-gun 目录，素材作者给每把枪起的名字天生不同：真实素材包里同一套
「离子」是 `ak47/离子AK`、`negev/离子战神`、`awp/离子大狙`、`deagle/离子正义`。
旧的「整套套用」按名字取并集再「配给能用它的枪」，用户看到的是
「把选中的风格一次配给能用它的 **1** 把武器」—— 和逐把下拉没有区别（用户截图原话）。

## 这里守的

1. 名字开头相同的归一套（`离子AK / 离子战神 / 离子大狙` ⇒「离子」），各枪各配各的；
2. ⚠ 同一把枪自己带的两个近名（`ssg08/PUBGAWM` 与 `ssg08/PUBG消音AWM`、「判据风格甲 / 乙」）
   是**可选项**，不是一套 —— 没有这一条，击杀音那种「甲 / 乙」两个全局风格会被并成一个；
3. 下拉里每一项都说覆盖几把；提示句和确认框逐把说「谁配哪个」；
4. 落盘仍走每张卡的下拉（`test_apply_one_style_to_every_weapon` 钉着「不另造一条路」）。

（本项目测试逐文件跑：`python -m pytest tests/test_gun_sound_series.py`）
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtWidgets import QMessageBox

from core.gun_sound_series import (
    MIN_ASCII_PREFIX_CHARS,
    MIN_PREFIX_CHARS,
    find_series,
    group_style_series,
    prefix_links,
)

# 取自一份真实素材包的目录名（照抄的，不是造的）—— 造的名字不会有这种前缀分布。
COMPETITOR_CATALOG = {
    "ak47": ["CSGOAK", "火麒麟", "离子AK", "紫金AK"],
    "galilar": ["威龙AK", "火麒麟", "离子AK", "紫金AK"],
    "m4a1": ["离子AK"],
    "mp9": ["离子AK"],
    "negev": ["离子战神", "边陲奥丁"],
    "m249": ["离子战神", "边陲奥丁"],
    "awp": ["三角洲AWM", "归零大狙", "毁灭", "离子大狙", "起源大狙"],
    "deagle": ["离子正义"],
    "cz75a": ["离子狂怒"],
    "usp": ["威龙鬼魅"],
    "ssg08": ["98K", "PUBGAWM", "PUBG消音AWM", "消音98K", "消音M24", "边陲飞将"],
}


def _by_key(series):
    return {s.key: s for s in series}


# ------------------------------------------------ ① 名字开头相同的归一套，各枪各配各的

def test_the_competitor_pack_groups_into_the_series_its_author_meant():
    series = _by_key(group_style_series(COMPETITOR_CATALOG))
    lizi = series["离子"]
    assert lizi.picks == {
        "ak47": "离子AK", "galilar": "离子AK", "m4a1": "离子AK", "mp9": "离子AK",
        "negev": "离子战神", "m249": "离子战神", "awp": "离子大狙",
        "deagle": "离子正义", "cz75a": "离子狂怒",
    }
    assert series["边陲"].picks == {"negev": "边陲奥丁", "m249": "边陲奥丁", "ssg08": "边陲飞将"}
    assert series["威龙"].picks == {"galilar": "威龙AK", "usp": "威龙鬼魅"}
    # 名字完全相同的（击杀音那种全局风格的退化情形）也是一套，套系名就是那个名字
    assert series["火麒麟"].picks == {"ak47": "火麒麟", "galilar": "火麒麟"}


def test_the_label_says_series_only_when_the_names_differ():
    series = _by_key(group_style_series(COMPETITOR_CATALOG))
    assert series["离子"].label == "离子 系列 · 9 把"
    assert series["火麒麟"].label == "火麒麟 · 2 把"
    assert series["98K"].label == "98K · 1 把"


def test_series_are_ordered_by_how_many_guns_they_cover():
    keys = [s.key for s in group_style_series(COMPETITOR_CATALOG)]
    assert keys[:2] == ["离子", "边陲"], keys
    counts = [s.gun_count for s in group_style_series(COMPETITOR_CATALOG)]
    assert counts == sorted(counts, reverse=True)


# ------------------------------------------------ ② 同一把枪的两个近名是可选项，不是一套

def test_two_near_names_on_the_same_gun_are_choices_not_a_series():
    """`ssg08/PUBGAWM` 与 `ssg08/PUBG消音AWM` 开头相同、却在同一把枪上 ⇒ 两个选项。"""
    series = _by_key(group_style_series(COMPETITOR_CATALOG))
    assert "PUBGAWM" in series and "PUBG消音AWM" in series
    assert "PUBG" not in series
    assert "消音98K" in series and "消音M24" in series and "消音" not in series


def test_kill_sound_style_pairs_like_jia_and_yi_stay_separate():
    """「判据风格甲 / 乙」共同前缀 4 个字、且每把枪都有这两个 ⇒ 必须仍是两套。"""
    catalog = {g: ["判据风格甲", "判据风格乙"] for g in ("ak47", "awp", "glock")}
    series = _by_key(group_style_series(catalog))
    assert set(series) == {"判据风格甲", "判据风格乙"}
    assert all(s.gun_count == 3 for s in series.values())


def test_a_third_name_can_chain_two_choices_and_then_the_gun_keeps_both():
    """经第三把枪串起来时，一把枪有两个候选：取与套系名相同的，否则最短；候选都记下来。"""
    catalog = {"ssg08": ["PUBGAWM", "PUBG消音AWM"], "awp": ["PUBGM24"]}
    series = _by_key(group_style_series(catalog))
    assert set(series) == {"PUBG"}
    assert series["PUBG"].picks == {"ssg08": "PUBGAWM", "awp": "PUBGM24"}
    assert series["PUBG"].alternatives == {"ssg08": ("PUBGAWM", "PUBG消音AWM")}


# ------------------------------------------------ ③ 前缀门槛

@pytest.mark.parametrize("a, b, linked", [
    ("离子AK", "离子战神", True),
    ("起源", "起源大狙", True),
    ("PUBGAWM", "PUBGM24", True),        # ASCII 4 个字符
    ("CSGOAK", "CS起源", False),         # ASCII 只有 2 个：说明不了什么
    ("离火", "离子", False),             # 只有 1 个字
    ("威龙AK", "威龙AK", True),
])
def test_prefix_threshold(a, b, linked):
    assert MIN_PREFIX_CHARS == 2 and MIN_ASCII_PREFIX_CHARS == 3
    assert prefix_links(a, b) is linked


def test_empty_and_blank_catalogs_group_to_nothing():
    assert group_style_series({}) == []
    assert group_style_series({"ak47": [], "awp": ["", "  "]}) == []
    assert find_series([], "离子") is None


# ------------------------------------------------ ④ 页面：下拉说把数、提示说谁配哪个、确认框逐把列

@pytest.fixture
def series_on_disk(tmp_path):
    """往音效库里造一套「试离子」（三把枪三个名字）+ 一把枪上的两个近名。"""
    import wave
    from pathlib import Path

    from resource_manager import ResourceManager

    root = Path(ResourceManager.get_app_data_path("resources/audio/gun_sounds"))
    made = []

    def make(gun, style):
        p = root / gun / style / "a.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 400)
        made.append(p)

    plan = {"ak47": "试离子AK", "awp": "试离子大狙", "deagle": "试离子正义"}
    for gun, style in plan.items():
        make(gun, style)
    make("ssg08", "试PUBGAWM")
    make("ssg08", "试PUBG消音AWM")

    from core.audio.runtime_audio import get_runtime_audio_manager

    manager = get_runtime_audio_manager()
    manager._styles_scanned = False
    manager.ensure_styles_scanned()
    yield plan
    for p in made:
        p.unlink(missing_ok=True)
        try:
            p.parent.rmdir()
        except OSError:
            pass
    manager._styles_scanned = False
    manager.ensure_styles_scanned()


def _page(qapp):
    from pages.gun_sound_page import GunSoundPage

    page = GunSoundPage()
    page.resize(1200, 800)
    page._refresh_style_catalog()
    qapp.processEvents()
    return page


def test_the_dropdown_says_how_many_guns_each_series_covers(qapp, series_on_disk):
    page = _page(qapp)
    try:
        items = {page.apply_all_combo.itemData(i): page.apply_all_combo.itemText(i)
                 for i in range(page.apply_all_combo.count())}
        # 第 0 项是占位：没选就不预览、按钮不亮（外审批 101 第二轮 3/3「以为已经配上了」）
        assert page.apply_all_combo.itemData(0) is None
        assert page.apply_all_combo.itemText(0) == page.APPLY_ALL_PLACEHOLDER
        assert page.apply_all_combo.currentIndex() == 0
        assert not page.apply_all_btn.isEnabled()
        assert "不点按钮不会写入" in page.apply_all_hint.text(), page.apply_all_hint.text()
        items.pop(None, None)
        # 名字不同的一套写「系列」；名字全同的（试PUBGAWM 只有一把）不写
        assert items.get("试离子") == "试离子 系列 · 3 把", items
        # 同一把枪上的两个近名各自成项，且都写着 1 把
        assert items.get("试PUBGAWM") == "试PUBGAWM · 1 把", items
        assert items.get("试PUBG消音AWM") == "试PUBG消音AWM · 1 把", items
        assert "试PUBG" not in items
        for label in items.values():
            assert re.search(r" · \d+ 把$", label), f"下拉项没说覆盖几把：{label!r}"
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_hint_names_who_gets_which_style(qapp, series_on_disk):
    page = _page(qapp)
    try:
        page.apply_all_combo.setCurrentIndex(page.apply_all_combo.findData("试离子"))
        qapp.processEvents()
        hint = page.apply_all_hint.text()
        assert page.apply_all_btn.isEnabled()
        # 外审批 101：句子先答「配没配上」再预告；点名按钮（第一版写「点右边按钮」—— 按钮在提示句左边）
        assert hint.startswith("还没配上。点「应用到全部武器」会给 3 把配上："), hint
        # 选了一套 ⇒ 这一页此刻有一件事要点按钮：共用回执让位，底栏说「还没写入」
        from widgets.master_switch_effect import saves_automatically

        assert saves_automatically(page) is False
        bar_text = page.action_bar.message_label.text()
        assert "还没写入" in bar_text and "点「应用到全部武器」" in bar_text, bar_text
        assert "自动保存" not in bar_text.split("——")[0], bar_text
        assert "AK-47→试离子AK" in hint and "AWP→试离子大狙" in hint, hint
        assert "其余 32 把" in hint and "保持原样" in hint, hint
        # 当前页签（手枪）里的枪先举：Desert Eagle 排在 AK-47 前
        assert hint.index("Desert Eagle→") < hint.index("AK-47→"), hint
        # 完整映射在 tooltip 里
        assert "Desert Eagle → 试离子正义" in page.apply_all_hint.toolTip()
        # 切到步枪页签 ⇒ AK-47 先举（看步枪的人要看得到 AK）
        rifle_tab = [i for i, (name, _w) in enumerate(page._tab_groups) if name == "步枪"][0]
        page.tab_widget.setCurrentIndex(rifle_tab)
        qapp.processEvents()
        assert page.apply_all_hint.text().startswith("还没配上。点「应用到全部武器」会给 3 把配上：AK-47→试离子AK"), page.apply_all_hint.text()
        # 例子里名字不重复：造一套三把同名 + 一把异名，三个例子必须把异名那把带上
        from core.gun_sound_series import StyleSeries

        fake = StyleSeries(key="试同名", picks={"ak47": "试同名AK", "m4a1": "试同名AK",
                                                "famas": "试同名AK", "negev": "试同名机枪"})
        text = page._describe_series(fake)
        assert "Negev→试同名机枪" in text and text.count("→") == 3, text
        # 只覆盖一把的套系：说清「只会给谁配」，别写「1 把都配上」
        page.apply_all_combo.setCurrentIndex(page.apply_all_combo.findData("试PUBGAWM"))
        qapp.processEvents()
        assert page.apply_all_hint.text().startswith("还没配上。点「应用到全部武器」只会给 SSG 08 配上「试PUBGAWM」"), page.apply_all_hint.text()
        # 回到占位 ⇒ 共用回执回来
        page.apply_all_combo.setCurrentIndex(0)
        qapp.processEvents()
        assert saves_automatically(page) is True
        assert "还没写入" not in page.action_bar.message_label.text()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_applying_a_series_gives_each_gun_its_own_name(qapp, monkeypatch, series_on_disk):
    page = _page(qapp)
    try:
        plan = series_on_disk
        disabled = page.DISABLED_STYLE_TEXT
        for gun in plan:
            page._on_weapon_style_changed(gun, disabled)
        qapp.processEvents()
        page.apply_all_combo.setCurrentIndex(page.apply_all_combo.findData("试离子"))

        asked = {}
        monkeypatch.setattr(QMessageBox, "question",
                            lambda _p, _t, text, *a, **k: (asked.update(text=text) or QMessageBox.Yes))
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
        page._apply_style_to_all_weapons()
        qapp.processEvents()

        text = asked.get("text", "")
        assert "配给 3 把武器" in text, text
        for gun, style in plan.items():
            name = page.weapon_configs[gun].display_name
            assert f"{name} → {style}" in text, f"确认框没逐把列出谁配哪个：{text!r}"
        assert "另有 32 把武器没有这一套的素材" in text, text
        for gun, style in plan.items():
            assert page._effective_style(page.weapon_configs[gun]) == style, gun
        # 没在这一套里的枪一把都没动
        assert page._effective_style(page.weapon_configs["ssg08"]) == "0"
        # 动作做完 ⇒ 下拉回到占位、底栏回到共用回执
        assert page.apply_all_combo.currentIndex() == 0
        assert not page.apply_all_btn.isEnabled()
        assert "还没写入" not in page.action_bar.message_label.text()
    finally:
        for gun in series_on_disk:
            page._on_weapon_style_changed(gun, page.DISABLED_STYLE_TEXT)
        page.deleteLater()
        qapp.processEvents()
