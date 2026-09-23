# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声页把「它到底读到了什么」讲出来（RN-676，2026-09-21 发布前返修）。

## 两条缺陷，同一个形状：**产品知道，用户不知道**

① **取样数只在帮助面板里。** 一个风格目录里放 7 个文件，只用前 5 个
   （`MAX_GUN_SOUND_VARIANTS`）。那句话逐字写在帮助面板第 2 条 ——
   而放素材的人不会为了放素材去翻帮助。屏幕上看不出「放了几个、用了几个」。

② **枪代号拼错是静默失败。** `_scan_gun_sounds` 按 35 个代号逐个 `join` 去找，
   找不到就当没有。用户建了 `AK-47/我的风格/1.wav`：目录在、文件在、
   页面上那一套素材连影子都不出现，**全程零提示**，他不知道自己错在哪。
   ⭐ RN-675 同族（静默失败），也是 RN-672 同族（分母按「已知代号」划，
   而缺陷正好落在那张表外面）。

## 这里守的六件事

1. 取样 ≥2 时下拉说出数字；**=1 时一个字都不加**（RN-049 刚删掉「每张卡一句」，
   全新安装下那是 18 句一字不差的噪音 —— 常见情形必须零改动）。
2. 超过上限时说「只用前 N 个」，且 **N 取自常量** —— 改常量判据跟着走。
3. ⭐⭐ 改了下拉的**显示文字**不许弄坏它的 **data**：整条存取链
   （`currentData()` → `_on_weapon_style_changed` → 配置）认的是 data。
   带后缀的名字一旦存进配置，风格就解析不出来、这把枪彻底哑掉。
4. 代号不对且**装着素材**的目录要在屏幕上被点名；给得出建议才给。
5. ⛔ 空的野目录**不报** —— 用户随手建一个空目录不是缺陷。
6. ⭐⭐⭐ 那句话要**真的画在屏幕上**（量渲染像素）。RN-673/674 两次栽在
   「字符串对了、像素上没有」：`isVisible()` 为真不等于看得见，
   `setPlaceholderText` 四行只画第一行。判据量字符串、用户看像素。
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from core.gun_sound_profiles import MAX_GUN_SOUND_VARIANTS, unrecognised_gun_dirs


def _wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 200)


@pytest.fixture
def page_on(qapp):
    """把页面的素材根指到一个**自带整个世界**的临时目录。

    ⚠ 不走 `%TEMP%/cs2customizer_test_config`：RN-646 逮到过那条 —— 它跨次持久，
    上一条判据留下的文件会让这一条假绿或假红。⭐ **判据的结果取决于上一条判据
    留下的文件，它就不是判据。**

    ⛔ 这里**不调** `invalidate_style_dirs_cache()`：那个 3s TTL 缓存的 key 含目录路径，
    而每个用例各有自己的 `tmp_path` ⇒ 天然不撞。第一版为了保险 import 了它，
    ⚠ 而 X7 是冻结层 —— 判据的 import 也算外部契约，那等于**为了判据方便把一个内部函数
    抬成契约**。⭐ 冻结层的契约面只该为产品扩，不为判据扩。
    """
    from pages.gun_sound_page import GunSoundPage

    def build(root: Path):
        page = GunSoundPage()
        page.audio_manager.gun_sounds_dir = str(root)
        page._refresh_style_catalog()
        qapp.processEvents()
        return page

    return build


def _labels(page, gun_type: str) -> list[str]:
    combo = page.weapon_rows[gun_type]["style_combo"]
    return [combo.itemText(i) for i in range(combo.count())]


def _data(page, gun_type: str) -> list[str]:
    combo = page.weapon_rows[gun_type]["style_combo"]
    return [combo.itemData(i) for i in range(combo.count())]


# ─────────────────────────── ① 取样数 ───────────────────────────

def test_a_style_with_several_samples_says_how_many(tmp_path, page_on):
    for i in range(3):
        _wav(tmp_path / "ak47" / "三个取样" / f"{i}.wav")
    page = page_on(tmp_path)
    assert any("三个取样" in text and "3 个取样" in text for text in _labels(page, "ak47")), \
        f"下拉里没说出取样数：{_labels(page, 'ak47')}"


def test_one_sample_adds_nothing_at_all(tmp_path, page_on):
    """⛔ 常见情形必须零改动 —— RN-049 删掉的正是「每张卡一句」那种噪音。"""
    _wav(tmp_path / "ak47" / "单个取样" / "a.wav")
    page = page_on(tmp_path)
    labels = _labels(page, "ak47")
    assert "单个取样" in labels, f"风格名被改写了：{labels}"
    assert not any("取样" in text for text in labels if text != "单个取样"), \
        f"只有一个取样却加了话：{labels}"


def test_too_many_samples_says_only_the_first_few_count(tmp_path, page_on):
    over = MAX_GUN_SOUND_VARIANTS + 2
    for i in range(over):
        _wav(tmp_path / "ak47" / "放多了" / f"{i}.wav")
    page = page_on(tmp_path)
    hit = [text for text in _labels(page, "ak47") if "放多了" in text]
    assert hit, "风格没出现"
    # ⭐ 那个数必须来自常量：硬编码一个 5 的话，上限一改判据还绿，而屏幕上开始说谎。
    assert f"{over} 个取样" in hit[0] and str(MAX_GUN_SOUND_VARIANTS) in hit[0], \
        f"没说清放了几个 / 只用前几个：{hit[0]}"


def test_the_cap_in_the_label_follows_the_constant(monkeypatch, tmp_path, page_on):
    """先验尺子的另一半：把上限改掉，屏幕上那个数要跟着改。

    ⚠ 量的是**页面读到的那个名字**，不是常量本身 —— 上一批的教训：
    判据量被调的方法、而断点改的是调用处，两者擦肩而过。
    """
    import pages.gun_sound_page as mod

    monkeypatch.setattr(mod, "MAX_GUN_SOUND_VARIANTS", 2)
    for i in range(4):
        _wav(tmp_path / "ak47" / "跟着常量" / f"{i}.wav")
    page = page_on(tmp_path)
    hit = [text for text in _labels(page, "ak47") if "跟着常量" in text]
    assert hit and "前 2 个" in hit[0], f"上限改成 2 之后屏幕上没跟着改：{hit}"


def test_the_combo_still_carries_the_bare_style_name_as_data(tmp_path, page_on):
    """⭐⭐ 最重的一条：显示文字可以带后缀，**存取用的 data 必须是裸风格名**。

    带后缀的名字一旦落进配置，`resolve_gun_sound_style` 解析不出目录 ⇒
    这把枪彻底哑掉，而设置页里看起来配得好好的。
    """
    for i in range(3):
        _wav(tmp_path / "ak47" / "裸名字" / f"{i}.wav")
    page = page_on(tmp_path)
    assert "裸名字" in _data(page, "ak47"), \
        f"data 被显示文字污染了：{_data(page, 'ak47')}"


def test_this_ruler_would_catch_the_old_silent_way(tmp_path, page_on, monkeypatch):
    """先验：把标注拿掉（回到改之前的样子），上面那条必须红。"""
    from pages.gun_sound_page import GunSoundPage

    monkeypatch.setattr(GunSoundPage, "_style_label",
                        lambda self, weapon_type, style: style)
    for i in range(3):
        _wav(tmp_path / "ak47" / "三个取样" / f"{i}.wav")
    page = page_on(tmp_path)
    assert not any("3 个取样" in text for text in _labels(page, "ak47")), \
        "先验失败：拿掉标注之后判据还能看到取样数，说明它量的不是这件事"


def test_the_readers_survive_a_page_that_never_scanned(qapp):
    """⭐⭐ 扫描那一步**压根没跑**时，两个只读方也不许炸。

    这不是假想：三条既有判据（`test_gun_special_sound_truth` 1 条、
    `test_tool_pages_ui_polish` 2 条）自己接管了扫描那一步，第一版把两个字典
    只在 `_scan_gun_sounds` 里初始化 ⇒ 当场 `AttributeError`。
    ⭐ RN-675 学到的是「只写一次、在任何 return 之前」；这一条再进一格：
    **写在方法里还不够 —— 那个方法本身可能不跑。**
    """
    from pages.gun_sound_page import GunSoundPage

    fresh = GunSoundPage.__new__(GunSoundPage)   # 连 __init__ 都不走
    assert fresh._style_label("ak47", "某风格") == "某风格"
    assert fresh._unknown_dir_hint() == ""


# ─────────────────────── ② 代号不对的目录 ───────────────────────

def test_a_misspelled_weapon_dir_is_named_on_screen(tmp_path, page_on):
    _wav(tmp_path / "AK-47" / "我的风格" / "a.wav")
    page = page_on(tmp_path)
    hint = page.status_hint_label.text()
    assert "AK-47" in hint, f"拼错的目录没被点名：{hint!r}"
    assert "ak47" in hint, f"给得出建议却没给：{hint!r}"


def test_a_flat_dir_missing_the_style_layer_is_caught_too(tmp_path):
    """层数不对（少了风格那一层）同样不会响 ⇒ 同样要报。

    ⚠ 这一格是 RN-596 那条教训的直接产物：**判据只有两格而世界有三种**。
    """
    _wav(tmp_path / "ak47plus" / "a.wav")
    assert [name for name, _ in unrecognised_gun_dirs(str(tmp_path))] == ["ak47plus"]


def test_an_empty_stray_dir_is_not_reported(tmp_path, page_on):
    """⛔ 空目录不是缺陷。报它就是噪音，而噪音会把真话一起淹掉。"""
    (tmp_path / "随手建的空目录").mkdir()
    _wav(tmp_path / "ak47" / "正常风格" / "a.wav")
    page = page_on(tmp_path)
    assert "随手建的空目录" not in page.status_hint_label.text()
    assert not page.unknown_weapon_dirs


def test_no_suggestion_is_better_than_a_wrong_one(tmp_path):
    """像不出任何代号时给空串 —— ⛔ 不许瞎猜一个。

    猜错的代号比不给建议更糟：用户会照着改，改完还是不响。
    """
    _wav(tmp_path / "完全不像枪的名字" / "某风格" / "a.wav")
    found = unrecognised_gun_dirs(str(tmp_path))
    assert found and found[0][1] == "", f"给了一个瞎猜的建议：{found}"


def test_a_real_weapon_dir_is_never_flagged(tmp_path):
    """阳性对照的反面：35 个真代号一个都不许被报上来。"""
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_WEAPON_TYPES

    for gun in SUPPORTED_GUN_SOUND_WEAPON_TYPES:
        _wav(tmp_path / gun / "某风格" / "a.wav")
    assert unrecognised_gun_dirs(str(tmp_path)) == []


def test_the_stale_message_is_not_silently_swallowed(tmp_path, page_on, monkeypatch):
    """屏幕上那一行是**择一**的 ⇒ 被压掉的那条必须另有出口。

    ⭐ 代号不对排最前（它是「你以为装好了」），而「N 项失效」在徽章里有 warn 色；
    ⛔ 若哪天把 stale 的徽章去掉，这条判据要红 —— 那时它就成了静默失败。
    """
    from pages.gun_sound_page import GunSoundPage

    monkeypatch.setattr(GunSoundPage, "_stale_names", lambda self: ["AK-47"])
    _wav(tmp_path / "AK-47" / "我的风格" / "a.wav")
    page = page_on(tmp_path)
    assert "AK-47" in page.status_hint_label.text()
    # ⚠ `status_badge_label` 是 `AudioStatusBadgeBar`（一排 QLabel 芯片），不是 QLabel ——
    #   我的第一版对它调 `.text()`，尺子自己错了。读芯片池里真正那几行字。
    badges = " ".join(chip.text() for chip in page.status_badge_label._chip_pool)
    assert "失效" in badges, f"stale 被屏幕那一行压掉了，而徽章里也没有：{badges!r}"
    # 详情里永远写全 —— 择一只发生在屏幕那一行上。
    assert "不是任何一把枪的代号" in page.summary_label.toolTip()


def test_the_resource_badge_does_not_say_normal_while_a_dir_is_unreadable(tmp_path, page_on):
    """⭐⭐⭐ 同屏两处不许打架（RN-107 族）—— 这条是**外审改后复跑逮到的**。

    我加了提示行说「有个目录读不到」，而旁边那颗徽章还写「资源 · 正常」。
    ⚠ 改前没有这个矛盾（两处都不说）⇒ **是加提示行这个动作自己造出来的。**
    ⛔ 修法不许动 `resource_badge()`（七个音效页共用一份，RN-035），只在本页降级。
    """
    _wav(tmp_path / "AK-47" / "我的风格" / "a.wav")
    page = page_on(tmp_path)
    chips = [chip.text() for chip in page.status_badge_label._chip_pool]
    joined = " ".join(chips)
    assert "读不到" in joined, f"徽章没跟着提示行走：{chips}"
    assert "资源 · 正常" not in joined, f"提示行说读不到，徽章却说正常：{chips}"


def test_a_healthy_library_still_says_normal(tmp_path, page_on):
    """阳性对照的反面：没有认不出的目录时，那颗徽章不许被我改坏。"""
    _wav(tmp_path / "ak47" / "正常风格" / "a.wav")
    page = page_on(tmp_path)
    joined = " ".join(chip.text() for chip in page.status_badge_label._chip_pool)
    assert "读不到" not in joined, f"库是干净的，徽章却在报读不到：{joined}"


def test_the_hint_is_actually_painted_on_screen(tmp_path, page_on):
    """⭐⭐⭐ 量**渲染出来的像素**，不是量字符串。

    RN-673：`isVisible()` 为真而控件在折叠线以下，用户找不到。
    RN-674：`setPlaceholderText` 给了四行、屏幕上只画第一行。
    ⇒ 两次都是「判据量字符串、用户看像素」。这一条把那把尺子换成像素。
    """
    _wav(tmp_path / "AK-47" / "我的风格" / "a.wav")
    page = page_on(tmp_path)
    label = page.status_hint_label
    assert label.isVisible() or not label.isHidden(), "提示行被隐藏了"

    size = label.sizeHint()
    assert size.width() > 0 and size.height() > 0, f"提示行没有尺寸：{size}"
    label.resize(max(size.width(), 420), max(size.height(), 20))

    image = QImage(label.size(), QImage.Format_RGB32)
    image.fill(0)
    label.render(image)

    ink = sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).value() > 24
    )
    assert ink > 60, f"提示行渲染出来几乎是空白（着墨 {ink} 像素）"

    # ⭐ 还要确认画出来的**不止第一行** —— RN-674 那条就是只画了第一行。
    rows = {
        y
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).value() > 24
    }
    assert len(rows) >= 8, f"着墨只占 {len(rows)} 行，这句话没被画完"
