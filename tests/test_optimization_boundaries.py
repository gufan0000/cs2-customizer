# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for the 2026-10 offline audit's failing boundaries."""
import json
from pathlib import Path
import subprocess
import threading

import pytest


@pytest.mark.parametrize("returncode,stdout,valid", [
    (0, 'RESULT {"ms": 1}\n', True),
    (0xC0000005, 'RESULT {"ms": 1}\n', False),
    (0, 'RESULT {}\n', False), (0, 'RESULT []\n', False),
    (0, 'RESULT {"ms": NaN}\n', False),
    (0, 'RESULT {"ms": 1}\nRESULT {"ms": 2}\n', False),
])
def test_benchmark_needs_clean_exit_and_one_finite_result(returncode, stdout, valid):
    from _benchmark_runtime import read_result
    proc = subprocess.CompletedProcess([], returncode, stdout, "")
    assert (read_result(proc) is not None) == valid


def test_release_import_parser_sees_absolute_windows_entry_scripts():
    from build_tools.build_release import missing_project_imports
    text = "missing module named mouse - imported by 'H:\\stage dir\\main_widget.py' (top-level)"
    assert missing_project_imports(text, {"main_widget"}) == ["mouse"]


def test_sandbox_does_not_delete_from_a_sibling_prefix(tmp_path, monkeypatch):
    import _audit_sandbox as mod
    temp = tmp_path / "temp"
    sibling = tmp_path / "temp-neighbor"
    cfg = sibling / "game/csgo/cfg"
    cfg.mkdir(parents=True)
    canary = cfg / "autoexec.cfg"
    canary.write_text("keep")
    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(temp))
    assert mod.reset_sandbox_game_dir(sibling) == []
    assert canary.read_text() == "keep"


def test_pristine_profile_rejects_an_outside_cleanup_target(tmp_path, monkeypatch):
    import _pristine_config as mod
    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(ValueError):
        mod.use_pristine_config_dir("../neighbor", force=True)


@pytest.fixture
def snapshot_env(tmp_path, monkeypatch):
    from core import config_snapshot_manager as mod
    path = tmp_path / "config.json"
    class Config:
        def __init__(self):
            self._save_lock = threading.RLock()
            self._save_timer = None
            self.value = "old"
        def save_config_now(self):
            path.write_text(json.dumps({"value": self.value}))
            return True
        def load_config(self):
            self.value = json.loads(path.read_text())["value"]
    obj = Config()
    monkeypatch.setattr(mod, "config", obj)
    monkeypatch.setattr(mod, "get_config_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mod, "get_config_path", lambda: str(path))
    obj.save_config_now()
    return mod, obj, path


def test_snapshot_flushes_current_state_and_restore_serializes_save(snapshot_env):
    mod, obj, path = snapshot_env
    obj.value = "pending"
    snap = mod.create_snapshot("manual")
    assert json.loads(Path(snap.file_path).read_text())["value"] == "pending"
    obj.value = "changed"
    entered = threading.Event()
    saved = threading.Event()
    worker = None
    load = obj.load_config
    def reload():
        nonlocal worker
        def concurrent_save():
            entered.set()
            with obj._save_lock:
                obj.save_config_now()
                saved.set()
        worker = threading.Thread(target=concurrent_save)
        worker.start()
        assert entered.wait(2)
        assert not saved.wait(.03)
        load()
    obj.load_config = reload
    assert mod.restore_snapshot(snap.snapshot_id).ok
    worker.join(2)
    assert saved.is_set()
    assert obj.value == json.loads(path.read_text())["value"] == "pending"


def test_snapshot_index_cannot_restore_or_prune_an_outside_file(snapshot_env, tmp_path):
    mod, obj, path = snapshot_env
    snap = mod.create_snapshot("manual")
    outside = tmp_path / "outside.json"
    outside.write_text('{"value":"must keep"}')
    entries = mod._load_index()
    entries.insert(0, {**entries[0], "snapshot_id": "bad", "created_at": "1900",
                       "file_path": str(outside), "sha256": ""})
    mod._save_index(entries)
    assert not mod.restore_snapshot("bad").ok
    mod.prune_snapshots(1)
    assert outside.exists()
    assert Path(snap.file_path).exists()


def test_snapshot_restore_rolls_back_a_failed_reload(snapshot_env):
    mod, obj, path = snapshot_env
    snap = mod.create_snapshot("manual")
    obj.value = "current"
    def broken():
        obj.value = "partially loaded"
        raise RuntimeError("cannot reload")
    obj.load_config = broken
    result = mod.restore_snapshot(snap.snapshot_id)
    assert not result.ok and "rolled back" in result.error
    assert obj.value == json.loads(path.read_text())["value"] == "current"


def test_future_fields_survive_save_and_invalid_scalars_have_safe_defaults(tmp_path, monkeypatch):
    import config as mod
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(mod.Config, "migrate_old_config", lambda self: None)
    monkeypatch.setattr(mod.Config, "_register_atexit_flush", lambda self: None)
    path = tmp_path / "config.json"
    unknown = {"nested": [{"new": 1}]}
    path.write_text(json.dumps({"config_schema_version": 999, "future_settings": unknown,
                               "kill_sound_enabled": "false", "voice_output_volume": [],
                               "kill_icon_scale": "bad", "window_geometry": [0, 0, float("inf"), 10]}))
    cfg = mod.Config()
    assert cfg.kill_sound_enabled is False
    assert isinstance(cfg.voice_output_volume, (int, float))
    assert isinstance(cfg.kill_icon_scale, (int, float))
    assert cfg.window_geometry == []
    assert cfg.save_config_now()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["future_settings"] == unknown
    assert data["config_schema_version"] == 999


def test_page_benchmark_destroys_cpp_widgets_and_rejects_missing_pages(qapp, monkeypatch):
    import sys
    from types import SimpleNamespace
    import shiboken6
    from PySide6.QtWidgets import QWidget
    import bench_page_build as bench
    created = []
    def build():
        obj = QWidget()
        created.append(obj)
        return obj
    monkeypatch.setitem(sys.modules, "synthetic_page", SimpleNamespace(Page=build))
    assert bench._build_once("synthetic_page", "Page") >= 0
    assert not shiboken6.isValid(created[0])
    assert "不可比" in bench.compare({"a": {"中位ms": 5}}, {})
    import build_search_index
    indexed_window = QWidget()
    build_search_index.teardown((indexed_window, qapp))
    assert not shiboken6.isValid(indexed_window)
