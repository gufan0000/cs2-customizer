# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression for audit F01-F03: reject external data before publishing state."""
import copy
import json

import pytest

import config as config_mod
from core.presets import preset_center as presets


@pytest.mark.parametrize("raw", ["[]", "null", "123", '"text"', "true", "{bad"])
def test_invalid_config_root_preserves_original_and_recovers(monkeypatch, tmp_path, raw):
    path = tmp_path / "config.json"
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(config_mod, "get_config_path", lambda: str(path))
    monkeypatch.setattr(config_mod.Config, "migrate_old_config", lambda self: None)
    cfg = config_mod.Config()
    assert cfg._load_error
    assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    assert [p.read_text(encoding="utf-8") for p in tmp_path.glob("*.corrupt-*")] == [raw]


def test_unbacked_invalid_config_cannot_be_overwritten_later(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config_mod, "get_config_path", lambda: str(path))
    monkeypatch.setattr(config_mod.Config, "migrate_old_config", lambda self: None)

    def denied(*_args, **_kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(config_mod, "replace_with_retry", denied)
    cfg = config_mod.Config()
    assert "暂停保存" in cfg._load_error
    assert cfg.save_config_now() is False
    cfg.save_config()
    cfg._atexit_flush()
    assert cfg._save_timer is None
    assert path.read_text(encoding="utf-8") == "[]"


def bundle(payload=None, kind="crosshair", version=2):
    return {"schema": presets.SCHEMA_NAME, "schema_version": version,
            "items": [{"type": kind, "payload": payload or {}}]}


@pytest.mark.parametrize("version", [None, [1], [], {}, "bad", "2", True, 2.5])
def test_bad_schema_returns_validation_error(version):
    assert not presets.validate_bundle(bundle(version=version)).ok


@pytest.mark.parametrize("key,value", [
    ("crosshair_size", {}), ("crosshair_size", True), ("crosshair_size", 100000),
    ("crosshair_alpha", -1), ("crosshair_enabled", "false"),
    ("crosshair_custom_data", [None]), ("crosshair_custom_data", [[1, {}]]),
])
def test_invalid_preset_does_not_touch_memory_or_disk(monkeypatch, key, value):
    cfg = presets.config
    monkeypatch.setattr(cfg, "config_snapshot_auto_before_risky_ops", False)
    before = copy.deepcopy(getattr(cfg, key))
    writes = []
    monkeypatch.setattr(cfg, "save_config_now", lambda: writes.append(True))
    result = presets.apply_bundle(bundle({key: value}))
    assert not result.ok
    assert getattr(cfg, key) == before
    assert not writes


def test_all_types_export_validate_and_input_is_not_aliased(monkeypatch):
    cfg = presets.config
    monkeypatch.setattr(cfg, "config_snapshot_auto_before_risky_ops", False)
    monkeypatch.setattr(cfg, "save_config_now", lambda: True)
    assert presets.validate_bundle(presets.export_bundle(sorted(presets.SUPPORTED_TYPES))).ok
    incoming = bundle({"crosshair_custom_data": [[1, 2]]})
    monkeypatch.setattr(cfg, "crosshair_custom_data", [])
    assert presets.apply_bundle(incoming).ok
    incoming["items"][0]["payload"]["crosshair_custom_data"][0][0] = 99
    assert cfg.crosshair_custom_data == [[1, 2]]


def test_bad_second_item_cannot_half_apply(monkeypatch):
    cfg = presets.config
    monkeypatch.setattr(cfg, "crosshair_size", 20)
    incoming = bundle({"crosshair_size": 25})
    incoming["items"].append({"type": "flash", "payload": {"flash_audio_volume": float("nan")}})
    assert not presets.apply_bundle(incoming).ok
    assert cfg.crosshair_size == 20


def test_failed_atomic_save_restores_memory(monkeypatch):
    cfg = presets.config
    monkeypatch.setattr(cfg, "config_snapshot_auto_before_risky_ops", False)
    monkeypatch.setattr(cfg, "crosshair_size", 20)
    monkeypatch.setattr(cfg, "save_config_now", lambda: False)
    assert not presets.apply_bundle(bundle({"crosshair_size": 25})).ok
    assert cfg.crosshair_size == 20
