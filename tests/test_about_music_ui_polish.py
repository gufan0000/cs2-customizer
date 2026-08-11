from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from config import VERSION, config
import pages.about_page as about_page_module
import pages.music_page as music_page_module


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _visible_audio_status_chip_texts(status_bar) -> list[str]:
    layout = status_bar.layout()
    if layout is None:
        return []
    texts: list[str] = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            texts.append(widget.text())
    return texts


class _DummyPlayer:
    def __init__(self):
        self.current_playlist_name = "默认列表"
        self.current_index = 0
        self.is_playing = True
        self.is_paused = False
        self.play_mode_calls: list[str] = []
        self.playlist = [
            {"title": "Demo Track", "artist": "Tester", "duration": 75},
        ]
        self.on_playlist_update = None
        self.on_playlist_change = None

    def get_playlist(self):
        return list(self.playlist)

    def get_all_playlists(self):
        return ["默认列表"]

    def switch_playlist(self, name):
        self.current_playlist_name = name
        return True

    def set_play_mode(self, mode):
        self.play_mode_calls.append(mode)


def test_about_page_uses_lead_and_badges(qapp):
    page = about_page_module.AboutPage()

    assert page.page_lead_label.objectName() == "pageLeadLabel"
    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    # 开源版没有账号体系，原来那枚「账号 · 联动已接入」换成了许可证徽标。
    # 数量仍然写死：少一枚说明状态条被人顺手删空了，那是缺陷不是简化。
    assert len(chips) == 3
    assert f"版本 · v{VERSION}" in chips
    assert "渠道 · 桌面工具" in chips
    assert f"许可证 · {about_page_module.PROJECT_LICENSE}" in chips
    assert about_page_module.PROJECT_REPO_URL in page.summary_label.toolTip()
    assert about_page_module.PROJECT_REPO_URL in page.status_card.toolTip()
    assert about_page_module.PROJECT_LICENSE in page.info_label.text()
    assert page.action_bar.secondary_btn.text() == "打开项目仓库"
    assert page.action_bar.primary_btn.text() == "查看发布记录"
    assert f"当前版本：v{VERSION}" in page.action_bar.message_label.text()
    # 开源版不做在线更新检查（也不该让 fork 出去的客户端继续打原作者的服务器）：
    # 关于页上不许再冒出「检查更新」这类入口。
    assert not hasattr(page, "check_update_button")

    page.deleteLater()
    qapp.processEvents()


def test_music_page_overview_badges_sync(qapp, monkeypatch):
    dummy_player = _DummyPlayer()
    monkeypatch.setattr(music_page_module, "get_music_player", lambda: dummy_player)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_death_action", "play", raising=False)
    monkeypatch.setattr(config, "music_death_volume_custom", False, raising=False)
    monkeypatch.setattr(config, "music_death_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.4, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_fade_out_duration", 0.5, raising=False)
    monkeypatch.setattr(config, "music_play_mode", "shuffle", raising=False)
    monkeypatch.setattr(config, "music_current_playlist", "默认列表", raising=False)

    page = music_page_module.MusicPage()

    assert page.page_lead_label.objectName() == "pageLeadLabel"
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    assert any(text == "联动 · 已启用" for text in chips)
    assert any(text == "模式 · 随机播放" for text in chips)
    assert any(text == "列表 · 默认列表" for text in chips)
    assert any(text == "曲目 · 1 首" for text in chips)
    assert any(text == "播放 · 播放中" for text in chips)
    play_mode_chips = _visible_audio_status_chip_texts(page.play_mode_badge_label)
    assert play_mode_chips == ["当前 · 随机播放", "范围 · 底部播放器"]
    assert "当前默认模式为随机播放" in page.play_mode_hint_label.text()
    assert page.music_summary_label.isHidden() is True
    assert "游戏联动：已启用" in page.music_summary_label.text()
    assert "当前曲目：Demo Track" in page.music_summary_label.text()
    assert "播放状态：播放中" in page.music_summary_label.toolTip()
    assert "淡出效果：已启用 · 0.5 秒" in page.status_card.toolTip()

    page.play_mode_group.button(3).click()
    assert dummy_player.play_mode_calls[-1] == "repeat_all"
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "模式 · 列表循环" for text in chips)
    play_mode_chips = _visible_audio_status_chip_texts(page.play_mode_badge_label)
    assert play_mode_chips == ["当前 · 列表循环", "范围 · 底部播放器"]
    assert "当前默认模式为列表循环" in page.play_mode_hint_label.text()
    assert "播放模式：列表循环" in page.music_summary_label.text()

    page.game_link_checkbox.setChecked(False)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "联动 · 已关闭" for text in chips)
    assert "游戏联动：已关闭" in page.music_summary_label.text()

    page.deleteLater()
    qapp.processEvents()
