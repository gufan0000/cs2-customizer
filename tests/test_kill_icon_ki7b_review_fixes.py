# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-7b：拿异构模型复审 KI-7 之后修掉的那五条。

**这一轮的来路值得记一笔**：KI-7 自带 73 条判据全绿、111 条回退验证全逮、
排版审计三档八主题全清——然后把三张截图和四个源文件交给另一个模型
（Gemini 3.7 Flash，`agy` 通道）看了一遍。它报的两条代码缺陷经核实都是误报，
但**只看截图**指出了下面第一条：一个我全套判据都没覆盖到的静默数据丢失。

教训不是"该多用一个模型"，而是：**我的判据全都长在我自己的心智模型上**。
"滑条改完要点保存"这件事我知道，所以我从没写过"不点保存会怎样"的判据。
只看界面、不知道设计意图的评审者，第一眼看到的就是那两个并排的按钮。

五条：

1. 【真缺陷】工坊点「完成」会**静默丢掉**没保存的播放节奏。滑条一动预览就
   跟着变快了，用户眼里"已经生效"，而 `close_btn` 直接接 `accept`。
2. 【真缺陷】有爆头素材时，那一格的角标从「已就绪」变成「爆头专属」，
   把"有没有素材"这条信息顶掉了，还和设置页的爆头勾选框概念对不上。
3. 【设计缺口】每格的时长滑条**没有名字**，配着下面一行「0.60 秒 · 20 FPS」，
   拖的是时长/帧率/进度三种都说得通。
4. 【设计缺口】工坊里换不了风格，要给另一套补素材得关窗→回页面→再开。
5. 【设计缺口】位置示意图上那个蓝框点不动，等于把唯一有意义的东西做成了装饰。

⚠ 不许 `exec()` 任何对话框：模态框在测试进程里是**卡死不是失败**。
"""
from __future__ import annotations

import contextlib

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QDialog

import dialogs.kill_icon_workshop as workshop_module
import pages.kill_icon_page as page_module
from config import config
from core.kill_icon_library import LEVELS
from widgets.kill_icon_level_grid import KillIconLevelCell
from widgets.kill_icon_preview import KillIconPositionMap


class _StubPlayer:
    def __init__(self, frames=30, fps=30, hold=0.0):
        self._frames = frames
        self._fps = fps
        self._hold = hold
        self.fps_updates = []
        self.hold_updates = []
        self.loaded_styles = []

    def load_style(self, style):
        self.loaded_styles.append(style)
        return True

    def get_style_fps(self, _style, _kills):
        return self._fps

    def get_style_hold(self, _style, _kills):
        return self._hold

    def get_style_frame_count(self, _style, _kills):
        return self._frames

    def update_fps_for_style(self, style, kills, fps):
        self.fps_updates.append((style, kills, fps))
        return True

    def update_hold_for_style(self, style, kills, hold):
        self.hold_updates.append((style, kills, hold))
        return True

    def play_icon(self, kills, fps=None):
        pass


@contextlib.contextmanager
def _pinned_style():
    """把进程级的**样式表和字体**一起按住不动。

    量字宽 / 量像素的判据**不能靠进程当时恰好是什么样**：全量跑的时候，
    前面任何一个文件给 `QApplication` 挂过一张带 `font-size` 的样式表、
    或者调过一次 `setFont`，这里的度量就全变了。表现是**单跑绿、全量红**
    ——最难查的那一种，而且两个出口要一起堵：只堵样式表还是会红（试过了）。
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    previous_qss, previous_font = app.styleSheet(), app.font()
    pinned = QFont(previous_font)
    pinned.setPointSize(9)
    app.setStyleSheet("")
    app.setFont(pinned)
    try:
        yield
    finally:
        app.setFont(previous_font)
        app.setStyleSheet(previous_qss)


class _Entry:
    def __init__(self, frames=30, kind="sheet"):
        self.frames = frames
        self.kind = kind
        self.exists = frames > 0


def _make_workshop(monkeypatch, player, style="classic", styles=("classic", "霓虹")):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(workshop_module, "load_level_animation",
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr(workshop_module.ResourceManager, "list_kill_icon_styles",
                        staticmethod(lambda: list(styles)), raising=False)
    return workshop_module.KillIconWorkshop(style, player=player)


@pytest.fixture
def workshop(qapp, monkeypatch):
    player = _StubPlayer()
    dialog = _make_workshop(monkeypatch, player)
    dialog._stub_player = player
    yield dialog
    dialog.level_grid.stop_previews()
    dialog.deleteLater()


def _drag_slider(workshop, kills=1, ticks=25):
    """真去动滑条，而不是直接置 `_dirty`。

    直接置标志位的判据验不到"改动真的存进了 cell"，把 `_apply_timing` 读
    错单元格也照样绿。
    """
    cell = workshop.level_grid.cells[kills]
    cell.duration_slider.setValue(ticks)
    return cell


# ---------------------------------------------------------------- 1. 关窗落盘

def test_closing_the_workshop_saves_pending_timing(workshop):
    """点「完成」不能把改了一半的节奏扔掉。"""
    _drag_slider(workshop)
    assert workshop._dirty is True
    assert workshop._stub_player.fps_updates == []      # 还没落盘

    workshop.done(QDialog.Accepted)

    assert workshop._stub_player.fps_updates, "点完成之后节奏应该已经落盘"
    assert workshop._dirty is False


def test_closing_by_escape_also_saves(qapp, monkeypatch):
    """叉窗口 / 按 Esc 走的是 `reject`，同样不能丢。

    这条单列是因为只拦 `accept` 是很自然的写法——而用户关窗最常用的恰恰
    是右上角那个叉。
    """
    player = _StubPlayer()
    dialog = _make_workshop(monkeypatch, player)
    try:
        dialog.level_grid.cells[2].duration_slider.setValue(31)
        assert dialog._dirty is True
        dialog.done(QDialog.Rejected)
        assert player.fps_updates, "叉掉窗口也应该落盘"
    finally:
        dialog.level_grid.stop_previews()
        dialog.deleteLater()


def test_closing_without_changes_writes_nothing(workshop):
    """没动过就别写盘：每次开关窗都刷一遍配置是另一种毛病。"""
    workshop.done(QDialog.Accepted)
    assert workshop._stub_player.fps_updates == []
    assert workshop._stub_player.hold_updates == []


def test_single_frame_assets_still_save_hold_on_close(qapp, monkeypatch):
    """单帧素材落的是定格时长，关窗这条路上也得走对分支。"""
    player = _StubPlayer(frames=1, hold=1.5)
    dialog = _make_workshop(monkeypatch, player)
    try:
        dialog.level_grid.cells[1].duration_slider.setValue(28)
        dialog.done(QDialog.Accepted)
        assert player.hold_updates, "单帧素材应该落定格时长"
        assert player.fps_updates == [], "单帧素材不该去改帧率"
    finally:
        dialog.level_grid.stop_previews()
        dialog.deleteLater()


# ---------------------------------------------------------------- 2. 爆头角标

def test_headshot_does_not_replace_the_ready_badge(qapp):
    """有爆头素材 ≠ 这一格是爆头专用的。"""
    cell = KillIconLevelCell(3)
    try:
        cell.set_state(_Entry(frames=20), None, has_headshot=True)
        assert cell.badge_label.text() == "已就绪"
        assert "爆头" in cell.info_label.text(), "爆头这条信息不能就此消失"
    finally:
        cell.deleteLater()


def test_no_headshot_says_nothing_about_headshots(qapp):
    cell = KillIconLevelCell(3)
    try:
        cell.set_state(_Entry(frames=20), None, has_headshot=False)
        assert cell.badge_label.text() == "已就绪"
        assert "爆头" not in cell.info_label.text()
    finally:
        cell.deleteLater()


# ---------------------------------------------------------------- 3. 滑条标题

def test_the_duration_slider_says_what_it_does(qapp):
    """一根没有名字的滑条 = 三种猜法。"""
    cell = KillIconLevelCell(1)
    try:
        assert cell.slider_caption.text().strip(), "时长滑条必须有说明文字"
        assert "停留" in cell.slider_caption.text()
    finally:
        cell.deleteLater()


def test_the_caption_sits_above_the_slider(qapp):
    """标题在滑条**上面**：左边要占宽，而一格能被压到 140px。"""
    cell = KillIconLevelCell(1)
    try:
        layout = cell.layout()
        order = {}
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item else None
            if widget is cell.slider_caption:
                order["caption"] = index
            elif widget is cell.duration_slider:
                order["slider"] = index
        assert "caption" in order and "slider" in order
        assert order["caption"] < order["slider"]
    finally:
        cell.deleteLater()


# ---------------------------------------------------------------- 4. 切风格

def test_workshop_has_a_style_switcher(workshop):
    assert workshop.style_combo.currentText() == "classic"
    assert workshop.style_combo.count() >= 2


def test_switching_style_reloads_the_player_and_marks_changed(workshop):
    workshop._on_style_switched("霓虹")
    assert workshop.style_name == "霓虹"
    assert workshop._stub_player.loaded_styles[-1] == "霓虹"
    assert workshop.changed is True, "设置页要靠这个把选中卡片同步过来"
    assert "霓虹" in workshop.windowTitle()


def test_switching_style_flushes_pending_timing_to_the_old_style(workshop):
    """切过去再切回来，改动就找不回来了——所以切之前必须先落。

    而且必须落到**老那一套**头上：先改 `style_name` 再落盘的话，用户在
    classic 上调的节奏会被写进霓虹，两套一起错。
    """
    _drag_slider(workshop, kills=1, ticks=25)
    workshop._on_style_switched("霓虹")
    assert workshop._stub_player.fps_updates, "切风格之前应该先落盘"
    assert all(style == "classic" for style, _k, _f in workshop._stub_player.fps_updates)


def test_current_style_survives_even_if_it_vanished_from_disk(qapp, monkeypatch):
    """当前风格不在库里也得留在下拉里。

    否则 `clear()` 之后 `findText` 落空、下拉静默停在第一项，而 `style_name`
    还是老的——标题栏和下拉从此各说各话，用户以为在编辑 A 其实在编辑 B。
    """
    player = _StubPlayer()
    dialog = _make_workshop(monkeypatch, player, style="幽灵",
                            styles=("classic", "霓虹"))
    try:
        assert dialog.style_combo.currentText() == "幽灵"
        assert dialog.style_name == "幽灵"
    finally:
        dialog.level_grid.stop_previews()
        dialog.deleteLater()


def test_reloading_styles_does_not_fire_a_switch(workshop):
    """回填下拉不是"用户在切"，不许把 changed 弄脏。"""
    before = workshop.changed
    workshop.reload_styles()
    assert workshop.changed == before
    assert workshop.style_name == "classic"


# ---------------------------------------------------------------- 5. 拖蓝框

@pytest.fixture
def position_map(qapp):
    widget = KillIconPositionMap()
    widget.resize(360, 200)
    yield widget
    widget.deleteLater()


def _point_for_offset(widget, offset):
    """算出"图标中心落在这个偏移上"时，蓝框中心在控件里的那个点。"""
    map_x, map_y, ratio = widget.map_geometry()
    x, y, w, h = widget.icon_geometry(offset)
    return QPointF(map_x + (x + w / 2) * ratio, map_y + (y + h / 2) * ratio)


@pytest.mark.parametrize("offset", [(0, 0), (60, -40), (-120, 90)])
def test_dragging_lands_where_the_blue_box_is_drawn(position_map, offset):
    """点到哪儿、框画到哪儿，必须是同一套几何。

    示意图和落点分家是这一块最贵的一类 bug（准心那边栽过）：分家之后画面
    看着没毛病，只有进游戏才发现位置不对。
    """
    got = position_map.offset_for_point(_point_for_offset(position_map, offset))
    assert abs(got[0] - offset[0]) <= 2
    assert abs(got[1] - offset[1]) <= 2


def test_dragging_is_clamped_to_the_slider_range(position_map):
    """拖出界的值滑条表示不了，回填时会被拉回去——表现是"松手往回弹"。"""
    far = QPointF(10_000, 10_000)
    got = position_map.offset_for_point(far)
    assert got == (KillIconPositionMap.OFFSET_LIMIT,
                   KillIconPositionMap.OFFSET_LIMIT)
    near = position_map.offset_for_point(QPointF(-10_000, -10_000))
    assert near == (-KillIconPositionMap.OFFSET_LIMIT,
                    -KillIconPositionMap.OFFSET_LIMIT)


def _isolated_page(monkeypatch):
    """建一张干净的设置页。

    ⚠ **位置那三个字段一定要 monkeypatch**。`config.save_config` 挡不住全部
    落盘路径——第一版没挡，判据里拖出来的 88/-66 真的写进了共享的测试配置
    （`%TEMP%\\cs2customizer_test_config`），于是**下一次跑的时候滑条一建出来就是
    88/-66，拖拽判据把自己喂成了恒绿**：回退验证一刀就砍出来了。
    """
    monkeypatch.setattr(page_module.ResourceManager, "list_kill_icon_styles",
                        lambda: ["默认"])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)
    monkeypatch.setattr(config, "kill_icon_offset_x", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_y", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_scale", 1.0, raising=False)
    return page_module.KillIconPage()


def test_the_offset_limit_matches_the_page_sliders(qapp, monkeypatch):
    """两处上限必须是同一个数。写死两份迟早分家。"""
    page = _isolated_page(monkeypatch)
    try:
        assert page.x_slider.maximum() == KillIconPositionMap.OFFSET_LIMIT
        assert page.x_slider.minimum() == -KillIconPositionMap.OFFSET_LIMIT
        assert page.y_slider.maximum() == KillIconPositionMap.OFFSET_LIMIT
        assert page.y_slider.minimum() == -KillIconPositionMap.OFFSET_LIMIT
    finally:
        page.deleteLater()


def test_dragging_emits_the_new_offset(position_map):
    seen = []
    position_map.position_changed.connect(lambda x, y: seen.append((x, y)))
    position_map.set_target(0, 0, 1.0)
    position_map._drag_to(_point_for_offset(position_map, (70, -50)))
    assert seen, "拖动要把新偏移发出去"
    assert abs(seen[-1][0] - 70) <= 2 and abs(seen[-1][1] + 50) <= 2


def test_dragging_to_the_same_place_stays_quiet(position_map):
    """没变就别发信号：每次 mouseMove 都发一枪会把配置写盘打满。"""
    position_map.set_target(40, 30, 1.0)
    seen = []
    position_map.position_changed.connect(lambda x, y: seen.append((x, y)))
    position_map._drag_to(_point_for_offset(position_map, (40, 30)))
    assert seen == []


def test_the_page_routes_the_drag_through_its_sliders(qapp, monkeypatch):
    """拖出来的值只能走滑条一条路，不许另存一份。

    直接写 config 的话位置就有两个真源：拖完滑条还停在老位置，下次动滑条
    又把拖的结果覆盖掉。
    """
    page = _isolated_page(monkeypatch)
    try:
        # 先钉死起点：不验"值变了"而验"从 0 变成了 88"，否则配置里恰好
        # 存着 88 的时候这条判据什么都验不到（真发生过，见 `_isolated_page`）。
        page.x_slider.setValue(0)
        page.y_slider.setValue(0)
        assert (page.x_slider.value(), page.y_slider.value()) == (0, 0)

        page.position_map.position_changed.emit(88, -66)
        assert page.x_slider.value() == 88
        assert page.y_slider.value() == -66
    finally:
        page.deleteLater()


def test_the_map_advertises_that_it_can_be_dragged(position_map):
    """能拖但看不出来能拖，等于不能拖。"""
    assert "拖" in position_map.toolTip()
    assert "拖" in KillIconPositionMap.CAPTION


def test_the_caption_never_gets_painted_past_the_edge(position_map):
    """底下那行字是 `drawText` 画上去的——**排版审计一个字都量不到**。

    审计量的是控件几何：文字画出边界只是被裁掉，控件本身没溢出，全绿。
    第一版加了"可拖动"三个字，一上来就把这行两头都截掉了，是渲染成图
    肉眼看才发现的。

    这条**不量绝对像素**：测试环境的字体库是空的，字宽和用户机器上不是
    一回事，量出来的数只代表这台机器。量的是行为——放不下就打省略号。
    """
    from PySide6.QtGui import QFontMetrics

    with _pinned_style():
        metrics = QFontMetrics(position_map.font())
        full = metrics.horizontalAdvance(position_map.CAPTION)
        # 窄宽度**按当前字体算出来**，不写死像素：写死 60px 的话，
        # 前面有测试把字号调小之后整句就塞得下了，这条判据什么都验不到。
        for width in (full // 4, full // 2, full - 4, full + 40):
            text = position_map.caption_for_width(width)
            assert metrics.horizontalAdvance(text) <= width, (
                f"{width}px 宽里画了一行 {metrics.horizontalAdvance(text)}px 的字")

        assert position_map.caption_for_width(full + 400) == position_map.CAPTION, \
            "宽度够的时候不许无缘无故省略"
        assert position_map.caption_for_width(full // 2) != position_map.CAPTION


# --------------------------------------- 7. 预览框里的占位文字不许画到框外

def test_the_placeholder_never_spills_out_of_the_preview_box(qapp):
    """这条是**异构模型在一张干净截图上 3/3 报出来的**，我一条判据都没有。

    「这套风格还没有素材，拖一个图标包进来」在 220px 的预览框里两头各被切掉
    一个字，而且画在圆角边框外面。`drawText` + `AlignCenter` 只管居中不管
    装不装得下，排版审计量的是控件几何，画出界一个字都不会红。

    ⚠ 判据读的是 `placeholder_draw_spec`——**和 `paintEvent` 同一份决策**，
    再拿 `QFontMetrics.boundingRect` 算这一笔真正会占多大地方
    （`boundingRect` 会诚实地返回**比给定矩形还大**的结果，这正是要抓的）。

    走过两条错路，都被回退验证砍出来了：
    ① 量"换行之后的包围盒宽度 ≤ 控件宽度"——`TextWordWrap` 本来就保证这点，恒绿；
    ② 渲染成图数像素——离屏平台上前面创建过大量控件之后，新控件 `render()`
       出来是空图，于是**单跑绿、全量红**，红的理由还跟缺陷无关。
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFontMetrics
    from widgets.kill_icon_preview import KillIconPreview

    with _pinned_style():
        for width, height in ((220, 140), (168, 108), (120, 80)):
            preview = KillIconPreview(box=(width, height))
            try:
                preview.set_animation(None, "这套风格还没有素材，拖一个图标包进来")
                preview.resize(width, height)
                rect = QRect(0, 0, width - 1, height - 1)
                box, flags, text = preview.placeholder_draw_spec(rect)
                painted = QFontMetrics(preview.font()).boundingRect(box, flags, text)
                assert rect.left() <= painted.left(), f"{width}x{height}：画到了左边框外"
                assert rect.top() <= painted.top(), f"{width}x{height}：画到了上边框外"
                assert painted.right() <= rect.right(), (
                    f"{width}x{height}：文字要到 {painted.right()}，框只到 {rect.right()}")
                assert painted.bottom() <= rect.bottom(), (
                    f"{width}x{height}：文字要到 {painted.bottom()}，框只到 {rect.bottom()}")
            finally:
                preview.deleteLater()


def test_the_placeholder_is_not_shortened_when_it_fits(qapp):
    """够宽就别无缘无故省略——省略号本身也是噪音。"""
    from widgets.kill_icon_preview import KillIconPreview

    preview = KillIconPreview(box=(220, 140))
    try:
        preview.set_animation(None, "拖素材到这里")
        assert preview.placeholder_for_box(600, 300) == "拖素材到这里"
    finally:
        preview.deleteLater()


def test_the_placeholder_box_keeps_away_from_the_border(qapp):
    """文字要离边框有点距离，贴着画同样像渲染坏了。"""
    from PySide6.QtCore import QRect
    from widgets.kill_icon_preview import KillIconPreview

    preview = KillIconPreview(box=(220, 140))
    try:
        box = preview.placeholder_box(QRect(0, 0, 220, 140))
        assert box.width() < 220 and box.height() < 140
        assert preview.PLACEHOLDER_PADDING > 0
    finally:
        preview.deleteLater()


# ------------------------------------------------ 6. 按钮不许被卡片切掉

def test_cell_buttons_stay_inside_the_card(qapp):
    """`setFixedHeight` 打不过 QSS 的 `min-height`——Qt 在 min > max 时取 min。

    症状是按钮的下边框被卡片边缘齐齐切掉一道。几何上"没有溢出"（布局按
    写死的 28 算），排版审计也够不着（只走 pages/），是渲染成 PNG 放大看
    才发现的。所以这条判据量的是**按钮的真实盒子**，不是布局以为的那个。
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    # 存回去而不是清成空串：把整个进程的样式表洗掉，后面每一个测试都跟着
    # 换了个主题跑——这是进程级副作用，坏在别的文件里、单跑还查不出来。
    previous = app.styleSheet()
    app.setStyleSheet(_theme_qss())
    cell = KillIconLevelCell(1)
    try:
        cell.set_frame_count(12, "sheet")
        cell.resize(279, cell.sizeHint().height())
        cell.show()
        QApplication.processEvents()
        bottom_margin = cell.layout().contentsMargins().bottom()
        limit = cell.height() - bottom_margin
        for button in (cell.test_btn, cell.menu_btn):
            got = button.y() + button.height()
            assert got <= limit, (
                f"「{button.text()}」的下边落在 {got}，而这一格只到 {limit}")
    finally:
        cell.hide()
        cell.deleteLater()
        app.setStyleSheet(previous)


def _theme_qss():
    """判据必须**带着主题样式表**跑：这个缺陷就是 QSS 造成的，不加载等于没测。"""
    from theme_manager import get_theme_manager

    return get_theme_manager().get_stylesheet()


# ------------------------------------------------------------ 搬家不许掉东西

def test_the_explicit_save_button_still_works(workshop):
    """关窗会兜底，但显式按钮不能因此退化成摆设。"""
    _drag_slider(workshop, kills=4, ticks=22)
    workshop._save_timing()
    assert workshop._stub_player.fps_updates
    assert workshop._dirty is False
    assert workshop.save_fps_btn.text() == "保存播放设置"
    assert "已保存" in workshop.notice_label.text()


def test_every_level_with_assets_gets_saved(workshop):
    """一次落盘要覆盖五个等级，不是只落用户最后动的那一格。"""
    _drag_slider(workshop, kills=2, ticks=18)
    workshop.done(QDialog.Accepted)
    saved = {kills for _style, kills, _fps in workshop._stub_player.fps_updates}
    assert saved == set(LEVELS)
