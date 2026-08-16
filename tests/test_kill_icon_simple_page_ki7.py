# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-7：击杀图标设置页的「简单层」。

**KI-6 做对了功能，但把编辑器当成了首页。** 那一版把五个击杀等级摊成一块
清单板摆在页面正中，只想"下载一套图标、拖进去、开着"的人一进来就要面对
30 多个可操作控件和七八个概念。用户的原话是「有点复杂有点乱，我自己都不是
很有耐心去研究」。

这一层只回答三件事：**用哪一套 · 放在屏幕哪儿 · 开没开**。
其余整块搬进素材工坊（判据见 `test_kill_icon_workshop_ki7.py`）。

所以这份文件里最要紧的不是"某个功能能不能用"，而是**这一页有没有再胖回去**
——复杂度是会自己长回来的，它需要一条棘轮看着。

⚠ 不许 `exec()` 任何对话框：模态框在测试进程里是**卡死不是失败**。
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QSlider, QWidget
)

import pages.kill_icon_page as page_module
from config import config
from core.kill_icon_library import LEVELS
from kill_icon_overlay import KillIconAnimation

#: 这一页允许露在外面的「本页自有的可操作控件」上限。
#:
#: KI-6 那一版实测同口径 25 个（五个格子各一条滑条 + 两个按钮 = 15，
#: 加上风格下拉、导入包、导出包、打开目录、保存播放设置、高级导入、
#: 位置三滑条、重置、预览、两个勾选）。这个数**只许减不许增**，
#: 而且必须贴着实测值——留富余的棘轮不是棘轮（QA-025 那轮的教训）。
#:
#: 口径（`_operable`）刻意排除三类，它们不是"这一页的复杂度"：
#:   · 帮助按钮与帮助面板 —— 28 个页面都有，属于外壳；
#:   · 动作栏 —— 同上，而且它复述的就是页内已有的动作；
#:   · 提示条 / 进度条 —— 只在导入之后才出现的临时反馈。
#: 折叠起来的"调整位置和大小"里的三条滑条**算在内**：它们只是默认不可见，
#: 一点就出来，仍然是这一页的复杂度。
MAX_VISIBLE_CONTROLS = 10


class _StubPlayer:
    def __init__(self, frames=30, fps=30):
        self._frames = frames
        self._fps = fps
        self.loaded_styles = []
        self.play_calls = []
        self.preview_calls = []
        self.enabled = []
        self.position_updates = []
        self.scale_updates = []

    def load_style(self, style):
        self.loaded_styles.append(style)
        return True

    def get_style_fps(self, _style, _kills):
        return self._fps

    def get_style_frame_count(self, _style, _kills):
        return self._frames

    def play_icon(self, kills, fps=None):
        self.play_calls.append((kills, fps))

    def preview_position_and_scale(self, kills, seconds):
        self.preview_calls.append((kills, seconds))

    def enable_kill_icons(self):
        self.enabled.append(True)

    def disable_kill_icons(self):
        self.enabled.append(False)

    def update_position_offset(self, x, y):
        self.position_updates.append((x, y))

    def update_scale(self, scale):
        self.scale_updates.append(scale)


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(page_module.ResourceManager, "list_kill_icon_styles",
                        lambda: ["默认", "霓虹"])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_icon_style", "默认", raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_x", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_y", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_scale", 1.0, raising=False)
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)
    monkeypatch.setattr(page_module, "style_summary",
                        lambda style, *a, **k: {"levels": list(LEVELS), "missing": [],
                                                "headshot_levels": [], "frames": 100})

    widget = page_module.KillIconPage()
    yield widget
    widget.deleteLater()


def _chip_texts(status_bar):
    """状态条上可见的那些 chip 的文案。"""
    from PySide6.QtWidgets import QLabel

    layout = status_bar.layout()
    if layout is None:
        return []
    out = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget() if item else None
        if (isinstance(widget, QLabel)
                and widget.objectName() == "audioStatusChip"
                and not widget.isHidden()):
            out.append(widget.text())
    return out


def _operable(page):
    """这一页**自己**摆出来的可操作控件。口径见 `MAX_VISIBLE_CONTROLS`。"""
    from widgets.kill_icon_style_strip import KillIconStyleAddCard, KillIconStyleCard

    excluded_roots = tuple(
        getattr(page, name) for name in
        ("action_bar", "notice_frame", "progress_frame")
        if getattr(page, name, None) is not None
    )

    out = []
    for child in page.findChildren(QWidget):
        if not isinstance(child, (QAbstractButton, QSlider, QComboBox,
                                  QLineEdit, QAbstractSpinBox)):
            continue
        if type(child).__name__ in ("HelpButton",):
            continue
        node = child.parent()
        skip = False
        while node is not None and node is not page:
            if isinstance(node, (QComboBox, QAbstractSpinBox, QSlider)):
                skip = True     # 复合控件内部的零件
                break
            if isinstance(node, (KillIconStyleCard, KillIconStyleAddCard)):
                skip = True     # 卡片条整体只算一个"挑风格"的动作
                break
            if node in excluded_roots or type(node).__name__ in ("HelpPanel",):
                skip = True
                break
            node = node.parent()
        if not skip:
            out.append(child)
    return out


# ==================================================== 1. 复杂度棘轮


def test_the_page_stays_simple(page):
    """棘轮：这一页露在外面的可操作控件不许再涨。

    KI-6 那一版是 30+。想往这儿加东西的时候先想想：**它是"挑一套图标"
    需要的，还是"做一套图标"需要的？** 后者请加到素材工坊里。
    """
    controls = _operable(page)
    assert len(controls) <= MAX_VISIBLE_CONTROLS, (
        f"设置页上的可操作控件涨到了 {len(controls)} 个"
        f"（上限 {MAX_VISIBLE_CONTROLS}）："
        f"{[c.text() if isinstance(c, QAbstractButton) else type(c).__name__ for c in controls]}\n"
        f"逐等级的编辑属于 dialogs/kill_icon_workshop.py。"
    )


def test_the_editor_did_not_follow_the_page(page):
    """更直接的一条：清单板与逐等级的节奏控件不许出现在这一页上。"""
    from widgets.kill_icon_level_grid import KillIconLevelCell, KillIconLevelGrid

    assert not page.findChildren(KillIconLevelGrid), "清单板又回到设置页上了"
    assert not page.findChildren(KillIconLevelCell)


def test_the_status_strip_is_four_chips_not_seven(page):
    """状态条也是复杂度。

    KI-6 那版有七条，把「时长 · 1.5-5.0s」「预览 · 已连接」这类**只有做素材
    的人才关心**的数摆在了首屏。现在只留：开没开 · 用哪套 · 素材齐不齐 ·
    放在哪儿。退下去的那些进了详情文案（鼠标停在状态条上能看到）。
    """
    page._sync_status_strip()
    chips = _chip_texts(page.status_badge_label)
    assert len(chips) == 4, f"状态条上有 {len(chips)} 条：{chips}"
    assert any(c.startswith("总开关 · ") for c in chips)
    assert any(c.startswith("风格 · ") for c in chips)
    assert any(c.startswith("素材 · ") for c in chips)
    assert any(c.startswith("位置 · ") for c in chips)
    assert not any(c.startswith("时长 · ") for c in chips), "「时长」是工坊的事，不该在首屏"
    assert not any(c.startswith("预览 · ") for c in chips), "「预览组件已连接」是内部管线，不是用户的事"
    # 退下去的信息不是丢掉，是收进详情
    assert "预览组件" in page.status_card.toolTip()


# ==================================================== 2. 风格靠看不靠猜


def test_styles_are_cards_not_a_dropdown(page):
    """挑图标是这一页最主要的动作，却曾经是反馈最差的控件。

    下拉框里全是干巴巴的字符串——名字是用户或图标包作者起的，**换之前根本
    不知道会换成什么样**。
    """
    assert not hasattr(page, "style_combo"), "又退回下拉框了"
    assert set(page.style_strip.cards) == {"默认", "霓虹"}


def test_clicking_a_card_switches_the_style(page):
    player = _StubPlayer()
    page.set_kill_icon_player(player)

    page.style_strip.style_selected.emit("霓虹")

    assert config.kill_icon_style == "霓虹"
    assert player.loaded_styles[-1] == "霓虹"
    assert page.style_strip.cards["霓虹"].selected is True
    assert page.style_strip.cards["默认"].selected is False


def test_the_selected_card_is_visibly_selected(page):
    """选中态必须**看得出来**——那一排卡片是"当前用的是哪一套"的唯一答案。

    只验 `selected` 这个 Python 属性是不够的（那是接线不是行为），所以连
    QSS 属性一起验：主题里 `QFrame#card[selected="true"]` 靠它上色。
    """
    page.style_strip.set_selected("霓虹")
    assert page.style_strip.cards["霓虹"].property("selected") == "true"
    assert page.style_strip.cards["默认"].property("selected") == "false"


def test_the_card_strip_is_tall_enough_to_show_the_whole_card(page):
    """卡片条的高度要跟着**真实卡片**走。

    建页那一刻条上只有「＋ 导入」那一张，风格卡是 `load_settings` 之后才塞进去
    的。在建页时把高度写死，就会把真卡片的最后一行（「素材齐全」/「2/5 个等级」）
    裁掉——而那一行恰恰是"切换之前就知道缺不缺素材"的全部信息。
    """
    card = page.style_strip.cards["默认"]
    needed = card.sizeHint().height()
    assert page.style_scroll.height() >= needed, (
        f"卡片条只有 {page.style_scroll.height()}px 高，装不下 {needed}px 的卡片"
    )


def test_each_card_says_whether_the_style_is_complete(page, monkeypatch):
    """"这套风格缺哪几个等级"必须在**切换之前**就看得见。"""
    monkeypatch.setattr(page_module, "style_summary",
                        lambda style, *a, **k: (
                            {"levels": [1, 2], "missing": [3, 4, 5],
                             "headshot_levels": [], "frames": 10}
                            if style == "霓虹" else
                            {"levels": list(LEVELS), "missing": [],
                             "headshot_levels": [], "frames": 99}))
    page._sync_status_strip()
    assert page.style_strip.cards["默认"].state_label.text() == "素材齐全"
    assert page.style_strip.cards["霓虹"].state_label.text() == "2/5 个等级"


def test_thumbnails_do_not_decode_whole_animations(page, monkeypatch):
    """缩略图只取第一帧。

    `load_level_animation` 会把整套帧切出来，而用户真实的默认风格整套 519 帧。
    风格库里有几套就要装几次——全在建页那一下同步做的话，页面打开会顿住，
    顿多久由用户素材大小决定。KI-3 已经为同款问题挨过一次（46 帧 41ms）。
    """

    heavy = []
    monkeypatch.setattr(page_module, "load_level_animation",
                        lambda *a, **k: heavy.append(a))

    seen = []

    def _thumb(style, kills, variant=""):
        seen.append((style, kills))
        return QImage(8, 6, QImage.Format_ARGB32)

    monkeypatch.setattr("kill_icon_overlay.load_level_thumbnail", _thumb)
    page.style_strip.load_all_thumbnails_now()

    assert seen, "缩略图一张都没装"
    assert all(k == 5 for _s, k in seen), "缩略图该优先取 5 杀（ACE 最能代表一套风格）"
    assert heavy == [], "缩略图走了整套解码那条路"
    assert page.style_strip.cards["默认"].thumb.has_image is True


def test_thumbnails_load_one_at_a_time(page):
    """逐张装，不是一口气装完——把开销摊到事件循环里。

    这条量的是**排队机制真的在**：一次 `_load_next_thumbnail` 只落一张。
    """
    page.style_strip._pending = ["默认", "霓虹"]
    page.style_strip._load_next_thumbnail()
    assert len(page.style_strip._pending) == 1, "一次装了不止一张"


# ==================================================== 3. 试播


def test_test_button_plays_the_real_thing(page):
    """点一下就在屏幕上真播一次。

    "改了不知道效果"是复杂感的一半来源。有了试播，用户不需要理解参数——
    看一眼就知道行不行。
    """
    player = _StubPlayer()
    page.set_kill_icon_player(player)
    page._test_current()
    assert player.play_calls, "试播没有真的播"
    assert player.play_calls[-1][0] == 5, "有素材时该播 5 杀（ACE）"


def test_test_falls_back_to_the_landing_box_when_there_are_no_assets(page, monkeypatch):
    """一帧素材都没有时，点了不能跟没点一样。

    退回"画一下落点"——总得让用户看见图标会出现在哪儿，否则比灰掉还费解。
    """
    monkeypatch.setattr(page, "_ready_levels", lambda style=None: [])
    player = _StubPlayer(frames=0)
    page.set_kill_icon_player(player)
    page._test_current()
    assert player.play_calls == []
    assert player.preview_calls, "既没播也没画落点，等于点了没反应"


def test_test_button_is_greyed_out_without_a_player(page):
    """播放器没接上时试播是个空动作，灰掉比点了没反应强。"""
    page.set_kill_icon_player(None)
    assert page.test_btn.isEnabled() is False
    page.set_kill_icon_player(_StubPlayer())
    assert page.test_btn.isEnabled() is True


def test_test_uses_a_level_that_actually_has_assets(page, monkeypatch):
    """5 杀没素材就往下找，别对着空格子播。"""
    monkeypatch.setattr(page, "_ready_levels", lambda style=None: [1, 3])
    player = _StubPlayer()
    page.set_kill_icon_player(player)
    page._test_current()
    assert player.play_calls[-1][0] == 3


# ==================================================== 4. 位置默认折叠


def test_position_sliders_start_collapsed(page):
    """绝大多数人一次都不会动位置。默认摊开三条滑条纯粹是噪音。"""
    assert page.adjust_frame.isHidden() is True
    page.adjust_toggle_btn.setChecked(True)
    assert page.adjust_frame.isHidden() is False
    assert "⌃" in page.adjust_toggle_btn.text()
    page.adjust_toggle_btn.setChecked(False)
    assert page.adjust_frame.isHidden() is True


def test_the_expanded_state_still_fits_the_narrowest_window(page):
    """展开之后也不许横向溢出。

    排版审计只按**默认状态**建页——折叠区里的三条滑条 + 落点示意图它一次都
    没量过。而紧凑模式的内容可视区只有 590px（860 窗口 − 侧栏 − 边距），
    KI-6 那版就是在这个宽度上溢出了 352px。
    """
    COMPACT_CONTENT_WIDTH = 590

    page.adjust_toggle_btn.setChecked(True)
    content = page.scroll_area.widget()
    needed = content.minimumSizeHint().width()
    assert needed <= COMPACT_CONTENT_WIDTH, (
        f"展开「调整位置和大小」之后内容最小宽 {needed}px，"
        f"超过紧凑模式的可视区 {COMPACT_CONTENT_WIDTH}px"
    )


def test_collapsed_sliders_still_work(page):
    """折叠只改可见性，不该把接线一起藏掉。"""
    player = _StubPlayer()
    page.set_kill_icon_player(player)
    page.x_slider.setValue(40)
    page.scale_slider.setValue(150)
    assert player.position_updates[-1][0] == 40
    assert player.scale_updates[-1] == pytest.approx(1.5)
    assert page.position_map._offset[0] == 40


# ==================================================== 5. 工坊入口


def test_the_workshop_is_reachable_from_the_page(page):
    """能力一条没删，只是挪了地方——那就必须有明显的门。"""
    assert page.workshop_btn.text() == "打开素材工坊"
    assert page.action_bar.secondary_btn.text() == "打开素材工坊"


def test_the_page_reloads_after_the_workshop_changed_something(page, monkeypatch):
    """在工坊里删了/换了素材，回到页面必须看得出来。"""
    class _FakeWorkshop:
        def __init__(self, *_args, **_kwargs):
            self.changed = True
            # 工坊 KI-7b 起能换风格，页面要读它最后停在哪一套。
            # 替身缺这个字段就是**替身不像真身**，会把判据变成在验替身。
            self.style_name = "默认"

        def exec(self):
            return 1

    monkeypatch.setattr("dialogs.kill_icon_workshop.KillIconWorkshop", _FakeWorkshop)
    reloaded = []
    monkeypatch.setattr(page, "_reload_after_import",
                        lambda style=None: reloaded.append(style))
    page._open_workshop()
    assert reloaded, "工坊改过东西，页面却没刷新"


def test_the_page_does_not_reload_when_nothing_changed(page, monkeypatch):
    """没改就别重扫——重扫会把所有风格的缩略图和当前风格的整套帧再解一遍。"""
    class _FakeWorkshop:
        def __init__(self, *_args, **_kwargs):
            self.changed = False
            self.style_name = "默认"       # 没换风格：和页面当前那套一致

        def exec(self):
            return 1

    monkeypatch.setattr("dialogs.kill_icon_workshop.KillIconWorkshop", _FakeWorkshop)
    reloaded = []
    monkeypatch.setattr(page, "_reload_after_import",
                        lambda style=None: reloaded.append(style))
    page._open_workshop()
    assert reloaded == []


# ==================================================== 6. 帮助文案


def test_the_help_text_describes_the_page_that_actually_exists():
    """帮助面板说的必须是**用户真会看到的那一页**。

    ⚠ 这条是从一个真实的死代码里长出来的：`ui_help_panel` 有两张表，
    后一张 `PAGE_HELP_TEXTS.update({...})` 会覆盖前一张。KI-6 那轮把
    kill_icon 的文案写进了**前一张**——写得挺好，但一个字都没显示过；
    用户实际看到的一直是 KI-4 之前的老文案「仅支持 Sprite Sheet（精灵图）格式」，
    而那时候拖 GIF、拖文件夹、拖 zip 早就都支持了。

    所以这里既验"只有一处定义"（结构），也验"说的是现在这一页"（内容）。
    """
    import ast
    from collections import Counter
    from pathlib import Path

    from ui_help_panel import PAGE_HELP_TEXTS

    source = (Path(__file__).resolve().parent.parent /
              "ui_help_panel.py").read_text(encoding="utf-8")
    keys = [k.value for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Dict)
            for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    assert Counter(keys)["kill_icon"] == 1, (
        "kill_icon 的帮助文案被定义了不止一次——后面那张表会覆盖前面的，"
        "改错地方就是白改（KI-6 那轮就白改了一次，用户看了半年老文案）"
    )

    text = PAGE_HELP_TEXTS["kill_icon"]
    assert "仅支持 Sprite Sheet" not in text, "还在说只支持精灵图，早就不是了"
    for phrase in ("工坊", "试播", "风格库", "zip", "WebP"):
        assert phrase in text, f"帮助里没提「{phrase}」，说的不是现在这一页"


# ==================================================== 7. 大预览


def test_the_hero_preview_is_actually_visible(page, qapp):
    """预览必须真的占到地方。

    第一版这块是**看不见的**：`KillIconPreview` 没有 `sizeHint`（QWidget 默认
    报 -1），而我把它的 `minimumWidth` 放到了 0（怕窄窗口溢出），它所在的
    水平布局又只给了 0 拉伸——三件事凑一起，Qt 把它收成 0 宽。
    布局没溢出、没报错、判据全绿，只是页面上**那块什么都没有**。
    是渲染出来一张图肉眼看才发现的。
    """
    page.resize(1180, 780)
    page.show()
    qapp.processEvents()
    try:
        assert page.hero_preview.width() >= 140, (
            f"大预览被压成了 {page.hero_preview.width()}px 宽——页面上看不到它"
        )
        assert page.hero_preview.height() >= 100
    finally:
        page.hide()


def test_the_hero_preview_shows_the_current_style(page, monkeypatch):
    """页面上方那块预览就是"你会看到的样子"，必须走运行时那个装载器。"""
    animation = KillIconAnimation(
        frames=(QImage(10, 8, QImage.Format_ARGB32),), fps=20,
        frame_width=10, frame_height=8,
    )
    calls = []
    monkeypatch.setattr(page_module, "load_level_animation",
                        lambda style, level, *a, **k: calls.append((style, level)) or animation)
    page._refresh_preview()
    assert calls[-1] == ("默认", 5)
    assert page.preview_widget.has_frames is True
