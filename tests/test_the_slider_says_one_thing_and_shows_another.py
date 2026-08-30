# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""voice_output：滑块指着一半，数字写着满格（RN-064）——以及另外两件同屏矛盾。

## 一、RN-064：**24 发外审，24 发都报了同一个矛盾**

    主音量:  [————●————]  100%

滑块量程是 `[0, 200]`（支持放大到 200%），值 100 ⇒ **手柄正好在正中间**，
而右边那个数字写着 **100%**。外审 24 发（8 张图 × 3）**全部**答出
「滑块位置约 50~75%，但右侧数字写 100%，两者互相矛盾」——
本工程见过最干净的全票之一。

⚠ 立案（RN-064）说的是**一颗**（主音量），实测是 **六颗**：
主音量 1 颗 + 5 个槽位各 1 颗，全都是 `[0,200]` / 值 100。
⭐ **认出「这是一族」免费，数清「有几个成员」不是**（批 21 那条又中）。

### ⭐⭐ 机制：量程这个信息**已经走到了显示函数的参数表里，然后被丢掉了**

    self.volume_label = QLabel(format_percent(config.voice_output_volume, hi=2.0))
                                                                        ^^^^^^^^
    def format_percent(value, lo=0.0, hi=1.0, fallback=0.0) -> str:
        v = clamp(value, lo, hi, fallback)
        return f"{int(round(v * 100))}%"      # ← hi 只用来夹紧，从不出现在结果里

⭐ **不是没人知道上限是 200%，是知道的那一层没有把它说出来。**

⇒ 判据要求：同一屏要有**可见文字**说出那个上限。

### ⚠⚠ 判据的第一版还要求「滑块自己要有刻度」——**那一条被实测毙掉了**

想法是对的（把「这条轨道有多长」画在控件自己身上），但
`setTickPosition(TicksBelow)` 在本仓这套 QSS 下 **把滑块从 20px 拉到 28px，
而多出来的 y=24..27 四行实测是纯色 `#404252` —— 一个像素都没画**。

⭐⭐ **它占了位置，没占画面。** 而我第一遍是拿「高度变了 + 颜色种类从 76 涨到 106」
当成「画出来了」的 —— 那两个数都真的变了，变的却不是我以为的那件事
（批 26 那一批「我以为那一层就是那一层」的又一例）。
⭐ **一条判据不许去钉一个屏幕上不存在的属性。**

### 为什么这份判据只管「说了没有」，不管「看见没有」

判据跑在 `QT_QPA_PLATFORM=offscreen`（`tests/conftest.py` 第 9 行），
那里 `QFontDatabase.families()` 是 **0** —— 任何基于几何位置的「这句话离滑块够不够近」
都是在量一个用户从没见过的版面（批 26 踩实）。
⇒ **判据管「说了没有」，外审管「看见没有」。** 两条腿分工，谁也替代不了谁。

## 二、驱动「待安装」，底栏却说「就绪」

同一屏上：徽章 `驱动 · 待安装`、卡片 `⚡ VB-Cable 未安装`，
而底栏与状态条写着 **`最近状态：就绪`**。外审多发判**高**
（「底部提示『就绪』与左侧『VB-Cable未安装』相互矛盾」）。

查实：`status_label` 建出来就是字面量 `"就绪"`，只有发生过某个操作才会被改写。
⭐ **「就绪」是一个初始占位符，而它长得像一个判断结果。**
⭐⭐ 「最近状态」这个词同时能读成「最近一次操作的结果」和「现在是否就绪」——
   而它只实现了前者，初值又恰好是一个听起来像后者的词。

## 三、五颗红「删除」，全长在空槽位上

`style_as_danger_button` 的文档第 3 行逐字写着：

> D-06 的口径：仅用于**不可逆的数据丢失**……**红色语义要稀缺才有效；
> 到处都是红的等于没有红的。**

而全新用户打开这一页看到的是 **5 颗高饱和红**（`rgb(239,68,68)`，全页唯一的饱和色），
每一颗管的都是「删掉一个什么都没有的行」。外审整页图 **6/6** 在
「这一屏最扎眼的是什么」和「哪个按钮会把你设好的东西弄没」两问上**都**答「删除」。

⭐ 而**同一行里的「试听」已经知道自己该禁用**（`preview_button.setEnabled(bool(audio))`）——
   门早就在那儿，只是没给「删除」也接上。
⭐⭐ **判别标准写在注释里，只会被应用到写它的人当时正在看的那一处**（第 N 次）。

⚠ **不禁用它**：槽位数由用户决定（初始 5、上限 50），删掉一个空槽位是正当动作。
   改的只是**警报级别**：红色跟着「有没有东西可丢」走。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QSlider

# ⚠ 主窗夹具用共享那一份，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

main_window = _shared_main_window

PAGE = "voice_output"


def _open_page(main_window, qapp, page_id=PAGE):
    main_window.ensure_page_loaded(page_id)
    main_window.show_page(page_id, animated=False, force=True)
    for _ in range(4):
        qapp.processEvents()
    page = main_window.pages.get(page_id)
    assert page is not None, f"打不开 {page_id} —— 判据在空转"
    return page


def _visible(page, cls):
    return [w for w in page.findChildren(cls) if w.isVisibleTo(page)]


def _visible_text(page):
    """页面上所有可见文字拼起来（标签 + 按钮）。"""
    parts = [lb.text() for lb in _visible(page, QLabel)]
    parts += [b.text() for b in _visible(page, QPushButton)]
    return "\n".join(parts)


def _scale_explained_near(slider, page, all_odd):
    """从滑块自己往上走祖先链，看有没有哪一层里写着它的量程上限。

    ## ⚠⚠ 这个函数改过两版，第二版是被回退验证判假绿之后改的

    **第一版**：「页面上任意一处出现 `200%` 即可」——
      主音量那句话和槽位图例各说了一次，**删掉任意一个，判据照样绿**。

    **第二版**：「沿祖先链找，走到页面根就停」——
      *仍然假绿*。因为**页面根的下一层就已经覆盖整页**
      （`content_widget` 同时装着播放路由卡和整个页签），
      于是删掉其中任意一句，另一句都会在那一层被找到。
      ⭐⭐ **我以为「不许走到根」是一段距离，其实那根本不是距离** ——
        层数少一层，覆盖面可以一点都不少。

    **第三版（现在）**：解释必须住在一个**不覆盖全部 odd 滑块**的容器里。
      · 主音量那句话在「播放路由」卡里 —— 那张卡只装 1/6 条 ⇒ 算数
      · 槽位图例在页签那一层 —— 它装 5/6 条 ⇒ 算数
      · 而 `content_widget` / 页面根装 6/6 ⇒ **不算**
      ⭐ **一句「页面某处写过」的解释，和一句「就在这一块里」的解释，
        区别不在层数，在它覆盖了多少个需要它的人。**
    """
    needle = f"{slider.maximum()}%"
    node = slider.parentWidget()
    while node is not None and node is not page:
        covered = sum(1 for s in all_odd if node.isAncestorOf(s))
        if covered < len(all_odd):
            for lb in node.findChildren(QLabel):
                if lb.isVisibleTo(node) and needle in lb.text():
                    return True
        node = node.parentWidget()
    return False


# ======================================================== 一、防空转 / 分母守卫


def test_the_page_really_has_what_this_file_talks_about(main_window, qapp):
    page = _open_page(main_window, qapp)
    sliders = _visible(page, QSlider)
    assert len(sliders) >= 6, (
        f"可见滑块只有 {len(sliders)} 个 —— 判据在空转（应有主音量 1 + 槽位 5）")
    slots = getattr(page, "soundboard_slots", None)
    assert isinstance(slots, dict) and len(slots) >= 5, (
        f"槽位只有 {0 if not slots else len(slots)} 个 —— 下面几条会空转")
    for slot in slots.values():
        for key in ("audio", "preview_button", "volume_slider"):
            assert key in slot, f"槽位结构变了，缺 {key}"


# ============================== 二、RN-064：满格不是 100% 的滑块，必须自己说清楚


def test_a_slider_whose_full_scale_is_not_100_percent_says_so(main_window, qapp):
    """⭐ 分母自己算出来：扫可见滑块，凡 `maximum() != 100` 的都要过这一关。

    不点名「主音量」——哪天有人加了第七条 0~200 的滑块，它一样会红。
    """
    page = _open_page(main_window, qapp)
    sliders = _visible(page, QSlider)
    odd = [s for s in sliders if s.maximum() != 100]
    assert odd, (
        "一个「满格不是 100%」的滑块都没有 —— 要么这一页改了量程（那本条可以删），"
        "要么判据没找到滑块。**别让它静默通过。**")

    # ⚠⚠ 第一版写的是「页面上任意一处出现 `200%` 即可」—— **太弱**：
    #   主音量那句话和槽位列表那行图例各说了一次，**删掉其中任意一个，
    #   判据照样绿**，而被删掉的那一处正是离另外五条滑块最近的解释。
    # ⭐ 改成沿**祖先链**找，且**不许一路走到页面根** ——
    #   「这一屏某处写过」不等于「解释放在困惑发生的地方」（批 27 那条）。
    missing = [s for s in odd if not _scale_explained_near(s, page, odd)]

    assert not missing, (
        f"{len(missing)}/{len(odd)} 条滑块的量程上限（{odd[0].maximum()}%）"
        "在**它自己所在的那一块**里一个字都没写。\n"
        "⭐ 手柄停在正中间而数字写 100% —— 外审 24/24 全票报「互相矛盾」。\n"
        "⚠ `format_percent(..., hi=2.0)` 已经把上限收进参数表了，"
        "只是从没让它出现在结果里。\n"
        "⚠ 写在页面另一头不算：解释要放在困惑发生的位置，不是页尾。")


def test_no_slider_pretends_to_have_ticks_that_do_not_draw(main_window, qapp):
    """⚠ 反向守卫：不许再拿 `setTickPosition` 当解释手段。

    实测（批 29）：它在本仓这套 QSS 下把滑块从 **20px 拉到 28px**，
    而多出来的 y=24..27 四行是**纯色 `#404252`，一个像素都没画**。
    ⭐⭐ **它占了位置，没占画面。**
    ⚠ 而我第一遍是拿「高度变了 + 颜色种类从 76 涨到 106」当成「画出来了」的 ——
      那两个数都真的变了，变的却不是我以为的那件事。

    留着它只会让下一个人以为「刻度已经有了，不用再写字」——
    而那句字正是唯一真正在解释量程的东西。
    """
    page = _open_page(main_window, qapp)
    ticked = [s for s in _visible(page, QSlider) if s.tickPosition() != QSlider.NoTicks]
    assert not ticked, (
        f"{len(ticked)} 条滑块开了刻度，而这套 QSS 根本不画刻度 —— "
        "它只会白占 8px，并让人以为量程已经解释过了。\n"
        "要解释量程请写字（见上一条判据）。")


# ==================================== 三、驱动没就绪时，这一屏不许有人说「就绪」


def test_nothing_claims_ready_while_the_driver_is_not(main_window, qapp):
    """同屏矛盾：徽章说「驱动 · 待安装」，底栏说「最近状态：就绪」。

    ⭐ 判据不写死「就绪」出现在哪个控件上 —— 它扫**这一屏所有可见文字**，
      因为矛盾是「同一屏两处说法不一致」，不是「某个控件写错了」。
    """
    page = _open_page(main_window, qapp)
    driver_ready = bool(getattr(page, "vb_cable_installed", False))
    if driver_ready:
        pytest.skip("这台机器装了 VB-Cable —— 本条要的是「没装」那一态")

    # ⚠ 第一版的词表**太宽**，把一句真话报成了假话：
    #   「先确认 VB-Cable 是否就绪，再决定是否需要打开说明或手动安装驱动。」——
    #   那是一句**提问**，不是一句断言。
    #   ⭐ 同批 25 那条：一张过宽的词表会把「这套风格还没有素材」这种真话也逮进来。
    # ⇒ 只认**断言式**的说法：整句就是「就绪」，或者出现「状态：就绪 / 状态 就绪」。
    def _asserts_ready(text: str) -> bool:
        if text == "就绪":
            return True
        return "状态：就绪" in text or "状态 就绪" in text

    offenders = [lb.text().strip() for lb in _visible(page, QLabel)
                 if _asserts_ready(lb.text().strip())]

    assert not offenders, (
        "驱动还没装，而这一屏上有人在说「就绪」：\n  "
        + "\n  ".join(f"「{t}」" for t in offenders)
        + "\n⭐ 查实：`status_label` 建出来就是字面量「就绪」，只有发生过操作才会改写 —— "
          "**它是一个初始占位符，却长得像一个判断结果。**")


# ==================================== 四、红色跟着「有没有东西可丢」走


def _is_muted(button):
    """这颗「删除」现在是不是「没什么可丢」的那一档。

    ⚠ 判据认的是**属性**不是 objectName —— 因为换 objectName 会改尺寸
    （见 `test_switching_alarm_level_costs_no_pixels`）。
    """
    return button.property("nothingToLose") == "true"


def _delete_button_of(page, slot_id):
    """槽位行里那颗「删除」。⚠ 槽位字典里没存它，按行找。"""
    slot = page.soundboard_slots[slot_id]
    frame = slot["frame"]
    hits = [b for b in frame.findChildren(QPushButton) if b.text().strip() == "删除"]
    assert len(hits) == 1, f"槽位 #{slot_id + 1} 里找到 {len(hits)} 颗「删除」"
    return hits[0]


def test_an_empty_slot_does_not_get_the_scarce_red(main_window, qapp):
    page = _open_page(main_window, qapp)
    reds = []
    for slot_id, slot in page.soundboard_slots.items():
        if slot.get("audio"):
            continue
        btn = _delete_button_of(page, slot_id)
        if not _is_muted(btn):
            reds.append(slot_id + 1)
    assert not reds, (
        f"这些**空**槽位的「删除」仍然是危险红：#{reds}\n"
        "⭐ `style_as_danger_button` 的文档第 3 行就写着「红色语义要稀缺才有效；"
        "到处都是红的等于没有红的」—— 而全新用户打开这一页看到的是 5 颗红，"
        "每一颗管的都是「删掉一个什么都没有的行」。\n"
        "外审整页图 6/6 在「最扎眼的是什么」和「哪个按钮会弄没东西」两问上都答「删除」。")


def test_a_slot_with_audio_does_get_the_red(main_window, qapp):
    """⭐⭐ 阳性对照：给一个槽位装上音频，那颗「删除」必须**变红**。

    少了这一条，上一条可以靠「把红色整个删掉」全绿 —— 而那会把
    一个真正不可逆的操作降级成普通按钮，比现在更糟。
    """
    page = _open_page(main_window, qapp)
    slot_id = sorted(page.soundboard_slots)[0]
    slot = page.soundboard_slots[slot_id]
    before = dict(audio=slot.get("audio"), name=slot.get("name"))
    try:
        page._load_slot_config(slot_id, {"audio": "C:/tmp/fake.wav", "name": "测试"})
        qapp.processEvents()
        btn = _delete_button_of(page, slot_id)
        assert not _is_muted(btn), (
            "槽位里已经有音频了（那是一次真正不可逆的丢失：文件路径 + 热键绑定 + "
            "音量 + 名称，且当场落盘），而「删除」不是危险红")
        assert slot["preview_button"].isEnabled(), (
            "装上音频之后「试听」没被打开 —— 那条门是本判据的参照物，它坏了这条也不算数")
    finally:
        slot["audio"] = before["audio"]
        slot["name"] = before["name"]
        slot["audio_label"].setText("未选择")
        slot["preview_button"].setEnabled(bool(before["audio"]))
        page._sync_slot_affordance(slot_id)
        qapp.processEvents()


def test_preview_and_delete_read_the_same_gate(main_window, qapp):
    """⭐ 钉住机制本身：两颗按钮必须由**同一个条件**驱动。

    这条缺陷的形状不是「删除按钮颜色不对」，是
    **同一行里，「试听」知道自己没东西可播，而「删除」不知道自己没东西可删** ——
    门早就在那儿（`preview_button.setEnabled(bool(audio))`），只是没给它也接上。
    """
    page = _open_page(main_window, qapp)
    for slot_id, slot in page.soundboard_slots.items():
        has_audio = bool(slot.get("audio"))
        btn = _delete_button_of(page, slot_id)
        assert slot["preview_button"].isEnabled() == has_audio, (
            f"槽位 #{slot_id + 1}：「试听」的可用性和「有没有音频」对不上了")
        assert (not _is_muted(btn)) == has_audio, (
            f"槽位 #{slot_id + 1}：「删除」的警报级别和「有没有音频」对不上了 —— "
            "两颗按钮必须读同一个条件")
        assert btn.objectName() == "dangerButton", (
            f"槽位 #{slot_id + 1}：「删除」的 objectName 被换掉了。"
            "⚠⚠ 换名会改尺寸：`dangerButton` 最小宽 116、`secondaryButton` 118 —— "
            "2px 就足以把同一行那个 Expanding 的「未选择」标签从 43px 挤到 41px（需 42）"
            "⇒ 折行，排版审计当场 11 → 16。"
            "⭐⭐ **改「警报级别」不许付出像素。** 警报级别走属性，几何一律不动。")


def test_switching_alarm_level_costs_no_pixels(main_window, qapp):
    """⭐⭐ **改「警报级别」不许付出像素。**

    第一版修法是把空槽位的「删除」从 `dangerButton` 换成 `secondaryButton`。
    实测：`dangerButton` 最小宽 **116**、`secondaryButton` **118** ——
    换名等于给这一行凭空加 2px，而同一行里那个 `Expanding` 的「未选择」标签
    本来就只剩 43px，一挤就变成 **41px / 需 42px** ⇒ 折行。
    `squeezed_label_audit --compact` 当场从 11 涨到 **16**（多出来的 5 条全是它）。

    ⭐⭐ **我改的是「警报级别」，付出的却是两个像素，
      而代价落在同一行另一个控件上**（批 26 那条「改『其余那些』和改『那一个』
      是等价的破坏」的又一形态）。

    ⇒ 现在两档只差一个属性，几何必须完全一致。
    """
    page = _open_page(main_window, qapp)
    slot_id = sorted(page.soundboard_slots)[0]
    btn = _delete_button_of(page, slot_id)
    slot = page.soundboard_slots[slot_id]
    before = dict(audio=slot.get("audio"), name=slot.get("name"))
    geo_muted = (btn.minimumWidth(), btn.minimumHeight(), btn.sizeHint())
    try:
        page._load_slot_config(slot_id, {"audio": "C:/tmp/fake.wav", "name": "x"})
        qapp.processEvents()
        geo_loud = (btn.minimumWidth(), btn.minimumHeight(), btn.sizeHint())
    finally:
        slot["audio"] = before["audio"]
        slot["name"] = before["name"]
        slot["audio_label"].setText("未选择")
        page._sync_slot_affordance(slot_id)
        qapp.processEvents()
    assert geo_muted == geo_loud, (
        f"两档的几何不一样：静音档 {geo_muted} vs 警报档 {geo_loud}。"
        "⭐ 警报级别只该换颜色。哪怕只差 2px，也会把同一行里那个只剩 43px 的"
        "文件名列挤到折行。")
