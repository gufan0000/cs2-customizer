from __future__ import annotations

import time

from core.audio.audio_task_runner import AudioTaskRunner


class _DummyManager:
    def __init__(self):
        self._styles_scanned = True
        self.ensure_called = 0
        self.load_called = 0

    def ensure_styles_scanned(self):
        self.ensure_called += 1

    def load_all_enabled_sounds(self):
        self.load_called += 1


def test_audio_task_runner_executes_reload_task(monkeypatch):
    runner = AudioTaskRunner()
    mgr = _DummyManager()
    monkeypatch.setattr("core.audio.audio_task_runner.get_runtime_audio_manager", lambda: mgr)
    monkeypatch.setattr("core.audio.audio_task_runner.config.save_config_now", lambda: None, raising=False)

    task_id = runner.submit_reload_audio_task("unit_test")
    assert task_id

    deadline = time.time() + 3.0
    while time.time() < deadline:
        history = runner.get_history(limit=10)
        if history:
            break
        time.sleep(0.05)

    history = runner.get_history(limit=10)
    assert history
    last = history[-1]
    assert last["task_type"] == "reload_audio"
    assert last["success"] is True
    assert mgr.ensure_called >= 1
    assert mgr.load_called >= 1

