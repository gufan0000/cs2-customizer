# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from types import SimpleNamespace

from core.runtime import system_status_service


def test_collect_runtime_status_warn_when_audio_unhealthy(monkeypatch):
    monkeypatch.setattr(
        system_status_service,
        "collect_audio_resource_health",
        lambda: {"summary": {"ok": False, "missing_directories": 1, "invalid_config_refs": 2, "empty_style_dirs": 0}},
    )
    page = SimpleNamespace(_dirty=True)
    main_window = SimpleNamespace(
        gsi_server=SimpleNamespace(_running=True, flask_thread=None, startup_error="", handlers=[1, 2]),
        pages={"p": page},
    )

    status = system_status_service.collect_runtime_status(main_window)
    assert status.level == "warn"
    assert status.gsi["running"] is True
    assert status.config_dirty is True
    assert "audio" in status.last_error


def test_collect_runtime_status_error_when_gsi_startup_error(monkeypatch):
    monkeypatch.setattr(
        system_status_service,
        "collect_audio_resource_health",
        lambda: {"summary": {"ok": True, "missing_directories": 0, "invalid_config_refs": 0, "empty_style_dirs": 0}},
    )
    main_window = SimpleNamespace(
        gsi_server=SimpleNamespace(_running=False, flask_thread=None, startup_error="port in use", handlers=[]),
        pages={},
    )
    status = system_status_service.collect_runtime_status(main_window)
    assert status.level == "error"
    assert status.last_error == "port in use"

