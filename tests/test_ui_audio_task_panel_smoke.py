from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from core.audio.audio_task_runner import AudioTaskRunner


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _DummyManager:
    def __init__(self):
        self._styles_scanned = False

    def ensure_styles_scanned(self):
        return None

    def load_all_enabled_sounds(self):
        return None


def test_audio_task_panel_page_smoke(qapp, monkeypatch):
    import pages.audio_task_panel_page as page_module

    runner = AudioTaskRunner()
    monkeypatch.setattr(page_module, "get_audio_task_runner", lambda: runner)
    monkeypatch.setattr("core.audio.audio_task_runner.get_runtime_audio_manager", lambda: _DummyManager())
    monkeypatch.setattr("core.audio.audio_task_runner.config.save_config_now", lambda: None, raising=False)

    page = page_module.AudioTaskPanelPage()
    runner.submit_reload_audio_task("ui_smoke")

    deadline = time.time() + 3.0
    while time.time() < deadline:
        page._reload_history()
        if page.table.rowCount() > 0:
            break
        time.sleep(0.05)

    page._reload_history()
    assert page.table.rowCount() >= 1
    assert "任务" in page.status_label.text()
    page.deleteLater()
