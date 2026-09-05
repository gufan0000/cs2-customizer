# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from core.audio.audio_event_timeline import AudioEvent, get_audio_event_timeline


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _DummyAudioManager:
    def play_sound(self, *_args, **_kwargs):
        return True


def test_audio_replay_page_smoke(qapp, monkeypatch):
    import pages.audio_replay_page as replay_module

    timeline = get_audio_event_timeline()
    timeline.clear()
    timeline.record(AudioEvent(timestamp=1.0, action="play", key="kill-1", channel_type="kill_sound", event_type="kill"))
    timeline.record(AudioEvent(timestamp=2.0, action="drop", key="reload-ak", channel_type="reload", event_type="reload"))

    monkeypatch.setattr(replay_module, "get_runtime_audio_manager", lambda: _DummyAudioManager())
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)

    page = replay_module.AudioReplayPage()
    page._refresh_events()
    assert page.table.rowCount() == 2

    # 批 48（RN-508）：动作筛选改成闭集下拉
    page.action_combo.setCurrentIndex(page.action_combo.findData("play"))
    page._refresh_events()
    assert page.table.rowCount() == 1

    page.table.selectRow(0)
    page._replay_selected()
    page.deleteLater()

