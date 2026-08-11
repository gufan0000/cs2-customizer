# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""导入校验单测(纯逻辑)。"""
import json

import pytest

from core.io_validation import (
    audio_import_rejection_reason,
    load_json_checked,
    validate_crosshair_import,
    validate_voice_config,
)


def _write(tmp_path, name, content_bytes):
    p = tmp_path / name
    p.write_bytes(content_bytes)
    return str(p)


def test_load_json_rejects_oversize(tmp_path):
    p = _write(tmp_path, "big.json", b'{"a":"' + b"x" * (3 * 1024 * 1024) + b'"}')
    with pytest.raises(ValueError):
        load_json_checked(p)


def test_load_json_rejects_non_object(tmp_path):
    p = _write(tmp_path, "arr.json", b"[1,2,3]")
    with pytest.raises(ValueError):
        load_json_checked(p)


def test_load_json_ok(tmp_path):
    p = _write(tmp_path, "ok.json", json.dumps({"k": 1}).encode())
    assert load_json_checked(p) == {"k": 1}


def test_voice_config_rejects_wrong_types():
    ok, cleaned, errors = validate_voice_config({"volume": [1, 2], "slots": "x"})
    assert ok is False and cleaned == {} and errors


def test_voice_config_accepts_valid():
    ok, cleaned, errors = validate_voice_config(
        {"slots": {"1": "a"}, "volume": 0.5, "ptt_enabled": True, "mode": "auto"}
    )
    assert ok is True
    assert cleaned["voice_output_volume"] == 0.5
    assert cleaned["voice_output_ptt_enabled"] is True
    assert cleaned["voice_output_slots"] == {"1": "a"}


def test_voice_config_bool_not_treated_as_number():
    ok, cleaned, errors = validate_voice_config({"volume": True})
    assert ok is False  # True 不算 volume 数字


def test_crosshair_requires_field():
    ok, _, errors = validate_crosshair_import({"foo": 1})
    assert ok is False and errors


def test_crosshair_accepts_list():
    ok, cleaned, _ = validate_crosshair_import({"crosshair_data": [{"x": 1}]})
    assert ok is True and cleaned["crosshair_custom_data"] == [{"x": 1}]


def test_audio_rejects_executable(tmp_path):
    p = _write(tmp_path, "fake.mp3", b"MZ\x90\x00fake exe payload")
    assert audio_import_rejection_reason(p) is not None


def test_audio_rejects_oversize(tmp_path):
    p = _write(tmp_path, "huge.wav", b"RIFF")
    assert audio_import_rejection_reason(p, max_bytes=2) is not None


def test_audio_accepts_small_wavlike(tmp_path):
    p = _write(tmp_path, "ok.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ")
    assert audio_import_rejection_reason(p) is None
