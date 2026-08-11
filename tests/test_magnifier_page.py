# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from config import config


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def magnifier_page(qapp, monkeypatch):
    import pages.magnifier_page as magnifier_page_module

    class _DummyThemeManager:
        def register_theme_changed_callback(self, _callback):
            return None

        def unregister_theme_changed_callback(self, _callback):
            return None

    monkeypatch.setattr(magnifier_page_module, "install_help_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(magnifier_page_module, "get_theme_manager", lambda: _DummyThemeManager())
    monkeypatch.setattr(magnifier_page_module, "magnification_available", True)
    monkeypatch.setattr(magnifier_page_module, "MagInitialize", lambda: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagUninitialize", lambda: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagSetFullscreenTransform", lambda *_args, **_kwargs: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagShowSystemCursor", lambda *_args, **_kwargs: True, raising=False)
    monkeypatch.setattr(magnifier_page_module.user32, "GetSystemMetrics", lambda index: 1920 if index == 0 else 1080, raising=False)
    monkeypatch.setattr(magnifier_page_module.MagnifierPage, "_setup_key_detection", lambda self: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "magnifier_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "magnifier",
        {
            "zoom_factor": 2.0,
            "primary_hotkey": "右键",
            "secondary_hotkey": "右键",
            "trigger_mode": "长按触发",
            "sensitivity_sync_enabled": False,
            "base_sensitivity": 1.0,
            "sensitivity_multiplier": 0.82,
            "sync_trigger_key": "SCROLLLOCK",
            "weapon_settings": {
                "weapon_awp": True,
                "weapon_hegrenade": False,
            },
            "zoom_settings": {},
        },
        raising=False,
    )

    page = magnifier_page_module.MagnifierPage(config)
    yield page
    page.deleteLater()


def test_magnifier_unknown_weapon_fails_safe(magnifier_page):
    magnifier_page.weapon_enabled_vars["weapon_awp"].setChecked(True)

    magnifier_page.update_current_weapon("weapon_awp")
    assert magnifier_page._is_current_weapon_enabled() is True

    magnifier_page.update_current_weapon("")

    assert magnifier_page.current_weapon == ""
    assert magnifier_page.weapon_label.text() == "未识别"
    assert magnifier_page._is_current_weapon_enabled() is False


def test_magnifier_deactivates_when_switching_to_disabled_weapon(magnifier_page, monkeypatch):
    events: list[str] = []

    magnifier_page.is_magnifier_active = True
    magnifier_page.weapon_enabled_vars["weapon_awp"].setChecked(True)
    magnifier_page.weapon_enabled_vars["weapon_hegrenade"].setChecked(False)
    monkeypatch.setattr(magnifier_page, "_deactivate_magnifier", lambda: events.append("deactivate"))

    magnifier_page.update_current_weapon("weapon_awp")
    magnifier_page.update_current_weapon("weapon_hegrenade")

    assert events == ["deactivate"]


def test_magnifier_toggle_mode_uses_click_toggle(magnifier_page, monkeypatch):
    events: list[tuple[str, bool | None]] = []

    magnifier_page.trigger_mode = "单击切换"
    magnifier_page.current_weapon = "weapon_awp"
    magnifier_page.current_active_type = None
    magnifier_page.weapon_enabled_vars["weapon_awp"].setChecked(True)
    monkeypatch.setattr(
        magnifier_page,
        "_activate_primary_magnifier",
        lambda test=False, immediate=False: events.append(("activate", immediate)),
    )
    monkeypatch.setattr(
        magnifier_page,
        "_deactivate_magnifier",
        lambda: events.append(("deactivate", None)),
    )

    magnifier_page._global_primary_key_press()
    magnifier_page._global_primary_key_release()

    assert events == [("activate", True)]

    magnifier_page.is_magnifier_active = True
    magnifier_page.current_active_type = "primary"
    magnifier_page._global_primary_key_press()
    magnifier_page._global_primary_key_release()

    assert events[-1] == ("deactivate", None)


def test_magnifier_activate_and_deactivate_sync_sensitivity(magnifier_page, monkeypatch):
    events: list[tuple[bool, bool]] = []

    monkeypatch.setattr(
        magnifier_page,
        "_sync_magnifier_sensitivity_state",
        lambda active, force=False: events.append((active, force)),
    )

    magnifier_page._do_activate_magnification("primary")
    magnifier_page._do_deactivate_magnification()

    assert events == [(True, True), (False, True)]
