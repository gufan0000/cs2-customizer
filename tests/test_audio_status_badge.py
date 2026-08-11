# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from pages.audio_status_badge import (
    AudioStatusBadgeBar,
    build_health_detail_tooltip,
    create_badge_bar,
    create_badge_label,
    render_badges,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _visible_chip_widgets(bar: AudioStatusBadgeBar) -> list[QLabel]:
    layout = bar.layout()
    if layout is None:
        return []
    chips: list[QLabel] = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            chips.append(widget)
    return chips


def test_create_badge_alias_returns_bar(qapp):
    bar = create_badge_label()
    assert isinstance(bar, AudioStatusBadgeBar)
    bar.deleteLater()


def test_render_badges_reuses_chip_widgets_and_sets_level(qapp):
    bar = create_badge_bar()
    render_badges(
        bar,
        [
            ("success", "开关: 已启用"),
            ("info", "已配置样式: 4"),
            ("danger", "资源目录: 异常 1"),
        ],
        detail_tooltip="缺失目录: resources/audio/gun_sounds",
    )

    chips = _visible_chip_widgets(bar)
    assert len(chips) == 3
    first_round_ids = [id(chip) for chip in chips]
    assert chips[0].property("level") == "success"
    assert chips[1].property("level") == "info"
    assert chips[2].property("level") == "danger"
    assert chips[2].toolTip() == "缺失目录: resources/audio/gun_sounds"

    render_badges(
        bar,
        [
            ("warn", "开关: 未启用"),
            ("info", "已配置样式: 0"),
            ("success", "资源目录: 正常"),
        ],
    )
    chips_after = _visible_chip_widgets(bar)
    assert len(chips_after) == 3
    assert [id(chip) for chip in chips_after] == first_round_ids
    assert chips_after[0].property("level") == "warn"
    assert chips_after[2].toolTip() == ""

    bar.deleteLater()


def test_build_health_detail_tooltip_summary():
    health = {
        "ok": False,
        "missing": ["C:/audio/kill_sounds"],
        "invalid": [
            {
                "key": "weapon_switch_sounds.weapon_ak47",
                "reason": "style directory missing",
                "expected_path": "C:/audio/switch_weapons/weapon_ak47/classic",
            }
        ],
        "empty": [],
    }
    text = build_health_detail_tooltip(health)
    assert "缺失目录" in text
    assert "失效引用" in text
