"""v5 Phase 2: 7 个核心 widget 组件的单元测试.

实际写了 5 个组件(SettingsCard/PageHeader/SettingsRow/AppButton/StatusChip),
其中 AppButton 已在 R8-W5 收口时删除(零引用 + 与 style_as_* 重叠),
其按钮语义断言迁到下方的 style_as_* 用例。
CardHeader/IconLabel 推迟到对应 Phase 用到时再加.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QSlider


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ========== SettingsCard ==========

def test_settings_card_title_only(qapp):
    from widgets.settings_card import SettingsCard
    card = SettingsCard("基础配置")
    assert card.objectName() == "card"
    assert card.title_label is not None
    assert card.title_label.text() == "基础配置"
    # R7/D-02(UP-043): 从 statusLabel 改名 cardTitle。
    # 原因是排版阶梯塌了——#statusLabel 实测 14px，和正文完全同号，等于没有标题。
    # 而全仓 54 处 setObjectName("statusLabel") 里大量是**状态值**而非标题，
    # 所以只能给卡片标题换个专属选择器，不能去改 statusLabel 本身的字号。
    assert card.title_label.objectName() == "cardTitle"
    assert card.description_label is None
    assert card.title_row is not None


def test_settings_card_title_and_description(qapp):
    from widgets.settings_card import SettingsCard
    card = SettingsCard("配置", "这是一段说明.")
    assert card.title_label.text() == "配置"
    assert card.description_label is not None
    assert card.description_label.text() == "这是一段说明."
    assert card.description_label.objectName() == "hintLabel"
    assert card.description_label.wordWrap() is True


def test_settings_card_no_title(qapp):
    from widgets.settings_card import SettingsCard
    card = SettingsCard()
    assert card.title_label is None
    assert card.title_row is None
    assert card.description_label is None
    # body 仍可用
    cb = QCheckBox("test")
    card.add_widget(cb)
    assert card.body.indexOf(cb) >= 0


def test_settings_card_make_returns_pair(qapp):
    """兼容旧 _create_section_card 风格."""
    from widgets.settings_card import SettingsCard
    card, body = SettingsCard.make("标题", "描述")
    assert isinstance(card, SettingsCard)
    assert body is card.body
    cb = QCheckBox("测试")
    body.addWidget(cb)
    assert body.indexOf(cb) >= 0


def test_settings_card_add_title_action(qapp):
    from widgets.settings_card import SettingsCard
    card = SettingsCard("title")
    btn = QCheckBox("?")
    card.add_title_action(btn)
    assert card.title_row.indexOf(btn) >= 0


def test_settings_card_add_title_action_without_title_raises(qapp):
    from widgets.settings_card import SettingsCard
    card = SettingsCard()  # no title
    with pytest.raises(RuntimeError):
        card.add_title_action(QCheckBox("?"))


# ========== PageHeader ==========

def test_page_header_title_only(qapp):
    from widgets.page_header import PageHeader
    h = PageHeader("基础设置")
    assert h.title_label.text() == "基础设置"
    assert h.title_label.objectName() == "titleLabel"
    assert h.description_label is None


def test_page_header_with_description(qapp):
    from widgets.page_header import PageHeader
    h = PageHeader("基础设置", "把常用开关收在一页.")
    assert h.description_label.text() == "把常用开关收在一页."
    assert h.description_label.objectName() == "pageLeadLabel"
    assert h.description_label.wordWrap() is True


def test_page_header_add_title_action(qapp):
    from widgets.page_header import PageHeader
    h = PageHeader("基础")
    btn = QCheckBox("帮助")
    h.add_title_action(btn)
    assert h.title_row.indexOf(btn) >= 0


def test_page_header_set_title(qapp):
    from widgets.page_header import PageHeader
    h = PageHeader("旧")
    h.set_title("新")
    assert h.title_label.text() == "新"


# ========== SettingsRow ==========

def test_settings_row_label_only(qapp):
    from widgets.settings_row import SettingsRow
    row = SettingsRow("启用功能")
    assert row.label_widget.text() == "启用功能"
    assert row.control_widget is None
    assert row.value_widget is None
    assert row.hint_widget is None


def test_settings_row_with_control(qapp):
    from widgets.settings_row import SettingsRow
    cb = QCheckBox()
    row = SettingsRow("启用", control=cb)
    assert row.control_widget is cb


def test_settings_row_with_value_and_hint(qapp):
    from widgets.settings_row import SettingsRow
    sl = QSlider()
    row = SettingsRow("音量", control=sl, value="80%", hint="拖动调整")
    assert row.value_widget is not None
    assert row.value_widget.text() == "80%"
    assert row.value_widget.objectName() == "valueLabel"
    assert row.hint_widget is not None
    assert row.hint_widget.text() == "拖动调整"


def test_settings_row_set_value(qapp):
    from widgets.settings_row import SettingsRow
    sl = QSlider()
    row = SettingsRow("音量", control=sl, value="50%")
    row.set_value("100%")
    assert row.value_widget.text() == "100%"


def test_settings_row_left_align(qapp):
    """control_align='left' 让控件紧贴 label."""
    from widgets.settings_row import SettingsRow
    cb = QCheckBox()
    row = SettingsRow("开关", control=cb, control_align="left")
    # label 在 0,control 在 1,(value 在 2,)stretch 在最后
    assert row.row.indexOf(row.label_widget) == 0
    assert row.row.indexOf(cb) == 1


# ========== 按钮语义（原 AppButton，R8-W5 收口后改为 style_as_* 帮助函数） ==========
#
# AppButton 在删除前实测**零引用**（pages/ dialogs/ 及仓库根目录全无使用），
# 且与既有的 page_theme_helper.style_as_* 帮助函数职责完全重叠。
# 但它是 objectName="ghostButton" 的**唯一生产者**——R8a 为 UP-073 补的
# 整块 #ghostButton QSS 和 ui_contrast_audit 的两条判据都挂在这个名字上。
# 所以语义保留、产出方式换成全站统一惯用法，下面的断言跟着迁移。

def test_style_as_helpers_assign_object_names(qapp):
    from PySide6.QtWidgets import QPushButton
    from page_theme_helper import (
        style_as_primary_button, style_as_secondary_button,
        style_as_danger_button, style_as_ghost_button,
    )

    for helper, expected in (
        (style_as_primary_button, "primaryButton"),
        (style_as_secondary_button, "secondaryButton"),
        (style_as_danger_button, "dangerButton"),
        (style_as_ghost_button, "ghostButton"),
    ):
        btn = QPushButton("x")
        helper(btn)
        assert btn.objectName() == expected


def test_style_as_helpers_keep_pointing_cursor(qapp):
    """UP-080：显式派名会让 _style_button 整段跳过，手型光标必须由帮助函数补上。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    from page_theme_helper import (
        style_as_primary_button, style_as_secondary_button,
        style_as_danger_button, style_as_ghost_button,
    )

    for helper in (style_as_primary_button, style_as_secondary_button,
                   style_as_danger_button, style_as_ghost_button):
        btn = QPushButton("x")
        helper(btn)
        assert btn.cursor().shape() == Qt.PointingHandCursor


def test_app_button_is_gone():
    """删干净了——留个哨兵，免得日后有人凭记忆把它 import 回来。"""
    import pytest as _pytest
    with _pytest.raises(ImportError):
        from widgets.app_button import AppButton  # noqa: F401


# ========== StatusChip ==========

def test_status_chip_default(qapp):
    from widgets.status_chip import StatusChip
    chip = StatusChip("主题・深色")
    assert chip.text() == "主题・深色"
    assert chip.objectName() == "audioStatusChip"
    assert chip.level == "info"
    assert chip.property("level") == "info"


def test_status_chip_set_level(qapp):
    from widgets.status_chip import StatusChip
    chip = StatusChip("配置・已保存", level="info")
    chip.set_level("success")
    assert chip.level == "success"
    assert chip.property("level") == "success"


def test_status_chip_invalid_level(qapp):
    from widgets.status_chip import StatusChip
    with pytest.raises(ValueError):
        StatusChip("x", level="unknown")
    chip = StatusChip("y", level="info")
    with pytest.raises(ValueError):
        chip.set_level("nope")


def test_status_chip_all_valid_levels(qapp):
    from widgets.status_chip import StatusChip
    for lvl in ("info", "success", "positive", "warning", "error", "neutral"):
        chip = StatusChip("test", level=lvl)
        assert chip.level == lvl


# ========== widgets/__init__ 导出 ==========

def test_widgets_package_exports():
    """所有新组件可从 widgets 顶层 import."""
    from widgets import (
        IconLabel, PageHeader, SettingsCard, SettingsRow, StatusChip,
        ResponsiveGrid, FlashPreviewWidget, PageActionBar, WeaponRowWidget,
        DirtyPageMixin,
    )
    assert all([
        IconLabel, PageHeader, SettingsCard, SettingsRow, StatusChip,
        ResponsiveGrid, FlashPreviewWidget, PageActionBar, WeaponRowWidget,
        DirtyPageMixin,
    ])


# ========== Phase 5: Icon 系统 ==========

def test_icon_provider_available(qapp):
    from widgets.icon_provider import is_available
    assert is_available() is True


def test_icon_provider_get_icon(qapp):
    from widgets.icon_provider import get_icon
    icon = get_icon("mdi.cog-outline", color="#7c3aed")
    assert not icon.isNull()


def test_icon_provider_themed_icon(qapp):
    from widgets.icon_provider import get_themed_icon
    icon = get_themed_icon("mdi.crosshairs", role="primary")
    assert not icon.isNull()


def test_icon_provider_26_pages_have_icons(qapp):
    """26 个页面 ID 全部能拿到 icon（开源版去掉账号页后是 26 不是 27）."""
    from widgets.icon_provider import PAGE_ICON_MAP, get_page_icon
    expected_pages = [
        "basic", "kill_sound", "kill_voice", "death_sound", "gun_sound",
        "switch_weapon", "reload_sound", "special_sound", "crosshair",
        "kill_icon", "viewmodel", "magnifier", "flash", "hud_color",
        "screen_effects", "music", "voice_output", "utility",
        "advanced", "audio_health", "audio_import_wizard", "audio_task_panel",
        "audio_replay", "config_snapshot", "preset_center", "about",
    ]
    for page in expected_pages:
        assert page in PAGE_ICON_MAP, f"missing icon for {page}"
        icon = get_page_icon(page)
        assert not icon.isNull(), f"null icon for {page}"


def test_icon_provider_unknown_page_returns_null(qapp):
    from widgets.icon_provider import get_page_icon
    icon = get_page_icon("nonexistent_page")
    assert icon.isNull()


def test_icon_provider_cache(qapp):
    """同一参数应返回同一对象(缓存生效)."""
    from widgets.icon_provider import get_icon, clear_cache
    clear_cache()
    a = get_icon("mdi.flash", color="#ffffff")
    b = get_icon("mdi.flash", color="#ffffff")
    assert a is b


def test_icon_label_creates_with_text(qapp):
    from widgets.icon_label import IconLabel
    lbl = IconLabel("mdi.cog-outline", "设置")
    assert lbl.text_label.text() == "设置"
    assert lbl.text_label.isVisibleTo(lbl)


def test_icon_label_no_text(qapp):
    from widgets.icon_label import IconLabel
    lbl = IconLabel("mdi.flash")
    assert lbl.text_label.text() == ""


def test_icon_label_set_icon(qapp):
    from widgets.icon_label import IconLabel
    lbl = IconLabel("mdi.cog-outline")
    lbl.set_icon("mdi.target")
    assert lbl._icon_name == "mdi.target"


def test_settings_card_with_icon(qapp):
    from widgets.settings_card import SettingsCard
    card = SettingsCard("测试", icon="mdi.cog-outline")
    assert card._icon_label is not None
    # 没 icon 时 _icon_label 为 None
    card2 = SettingsCard("测试")
    assert card2._icon_label is None


def test_page_header_with_icon(qapp):
    from widgets.page_header import PageHeader
    h = PageHeader("基础设置", icon="mdi.cog-outline")
    assert h._icon_label is not None
