# SPDX-License-Identifier: GPL-3.0-or-later
import io
import logging
import threading

import pytest


def test_theme_callbacks_follow_parent_destruction_and_stable_dispatch(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QWidget
    from theme_manager import get_theme_manager
    from widgets.weapon_row_widget import WeaponRowWidget
    manager = get_theme_manager()
    baseline = len(manager._theme_changed_callbacks)
    parent = QWidget()
    rows = [WeaponRowWidget(str(i), str(i), ["0"], parent=parent) for i in range(20)]
    assert len(manager._theme_changed_callbacks) == baseline + 20
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert len(manager._theme_changed_callbacks) == baseline
    assert len(rows) == 20  # Still held Python wrappers must not keep subscriptions alive.
    called = []
    def first():
        called.append(1)
        manager.unregister_theme_changed_callback(first)
    def second():
        called.append(2)
    manager.register_theme_changed_callback(first)
    manager.register_theme_changed_callback(second)
    try:
        manager.set_theme(manager.current_theme_name)
        assert called == [1, 2]
    finally:
        manager.unregister_theme_changed_callback(first)
        manager.unregister_theme_changed_callback(second)


def test_audio_refreshes_coalesce_and_stop_cancels_pending(qapp, monkeypatch):
    from core.audio.audio_task_runner import AudioTaskRunner
    runner = AudioTaskRunner()
    entered, release = threading.Event(), threading.Event()
    def blocked(task):
        entered.set()
        assert release.wait(3)
    runner._submit_task("active", "active", blocked)
    assert entered.wait(2)
    ids = {runner.submit_reload_audio_task(str(i)) for i in range(100)}
    assert len(ids) == 1 and len(runner._queue) == 1
    assert runner.stop(timeout=0) is False
    assert len(runner._queue) == 0
    with pytest.raises(RuntimeError, match="取消"):
        runner.submit_reload_audio_task("late")
    release.set()
    assert runner.stop(timeout=2)
    history = runner.get_history()
    assert len(history) == 2 and all(not row["success"] for row in history)


def test_exception_and_stack_text_are_redacted_for_multiple_handlers():
    from core.utils.log_filter import SensitiveFilter
    logger = logging.Logger("redaction-test")
    sinks = [io.StringIO(), io.StringIO()]
    for sink in sinks:
        handler = logging.StreamHandler(sink)
        handler.addFilter(SensitiveFilter())
        logger.addHandler(handler)
    try:
        try:
            raise ValueError("token=INNER_CANARY")
        except ValueError as exc:
            raise RuntimeError("https://example.org/a?key=OUTER_CANARY") from exc
    except RuntimeError:
        logger.exception("download failed")
    for sink in sinks:
        value = sink.getvalue()
        assert "INNER_CANARY" not in value and "OUTER_CANARY" not in value
        assert "ValueError" in value and "RuntimeError" in value and "Traceback" in value


@pytest.mark.parametrize("payload", [[1], "x", 2, True, None])
def test_gsi_rejects_non_objects_without_enqueuing(payload, monkeypatch):
    import gsi_server as mod
    from queue import Queue
    queue = Queue(100)
    monkeypatch.setattr(mod, "data_queue", queue)
    response = mod.flask_app.test_client().post("/", json=payload) if payload is not None else (
        mod.flask_app.test_client().post("/", data="null", content_type="application/json"))
    assert response.status_code == 400 and queue.empty()


def test_gsi_caps_bytes_and_preserves_valid_object_ingestion(monkeypatch):
    import gsi_server as mod
    from queue import Queue
    queue = Queue(100)
    monkeypatch.setattr(mod, "data_queue", queue)
    client = mod.flask_app.test_client()
    assert client.post("/", json={"padding": "x" * (1024 * 1024)}).status_code == 413
    assert queue.empty()
    assert client.post("/", json={"provider": {"name": "Counter-Strike 2"}}).status_code == 200
    assert mod.PACKET_RECV_KEY in queue.get_nowait()


def test_complete_shared_kill_style_is_checked_once_per_collection(tmp_path, monkeypatch):
    import core.audio.audio_resource_health as mod
    monkeypatch.setattr(mod.config, "weapon_kill_sounds", {str(n): "shared" for n in range(39)})
    monkeypatch.setattr(mod.config, "weapon_kill_voices", {})
    monkeypatch.setattr(mod, "_resolve_kill_style_dir", lambda *args, **kw: str(tmp_path))
    calls = []
    def find(*args, **kwargs):
        calls.append(args)
        return "exists.wav"
    monkeypatch.setattr(mod, "find_audio_by_stem", find)
    assert mod._collect_incomplete_kill_styles(str(tmp_path)) == []
    assert len(calls) == len(mod.KILL_LEVELS)


def test_audio_scan_keeps_sort_extensions_and_ignores_directories(tmp_path):
    from core.audio.audio_file_utils import list_audio_files, has_audio_files
    for name in ("b.WAV", "A.mp3", "ignore.txt", "c.ogg"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "directory.wav").mkdir()
    assert list_audio_files(str(tmp_path)) == ["A.mp3", "b.WAV", "c.ogg"]
    assert list_audio_files(str(tmp_path), [" WAV "]) == ["b.WAV"]
    assert has_audio_files(str(tmp_path), ["wav"])
    assert not has_audio_files(str(tmp_path), ["flac"])


def test_icon_cleanup_invalidates_inflight_decode(qapp, monkeypatch):
    from types import SimpleNamespace
    import kill_icon_player as mod
    entered, release = threading.Event(), threading.Event()
    def load(*args):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(frame_count=1, fps=30, frame_width=1, frame_height=1, hold_seconds=0)
    monkeypatch.setattr(mod, "load_level_animation", load)
    monkeypatch.setattr(mod, "scale_animation", lambda *args: ["synthetic frame"])
    player = mod.KillIconPlayer()
    ready = []
    player.assets_ready.connect(ready.append)
    player._start_load("synthetic")
    assert entered.wait(2)
    worker = player._loading_thread
    player.cleanup()
    release.set()
    worker.join(3)
    qapp.processEvents()
    assert not worker.is_alive() and not player._scaled and not ready
    player._start_load("late")
    assert player._loading_thread is None
