from core.magnifier_sensitivity import (
    compute_zoom_sensitivity,
    format_sensitivity_value,
    get_keyboard_key_for_sync,
    write_magnifier_runtime_cfg,
)


def test_compute_zoom_sensitivity_uses_multiplier():
    assert compute_zoom_sensitivity(1.2, 0.82) == 0.984


def test_get_keyboard_key_for_sync_normalizes_scrolllock():
    assert get_keyboard_key_for_sync("SCROLLLOCK") == "scroll lock"


def test_write_magnifier_runtime_cfg_switches_between_zoom_and_default(tmp_path):
    runtime_cfg_path = tmp_path / "cs2customizer_magnifier_runtime.cfg"

    write_magnifier_runtime_cfg(str(runtime_cfg_path), 1.2, 0.82, True)
    active_content = runtime_cfg_path.read_text(encoding="utf-8")
    assert f"sensitivity {format_sensitivity_value(0.984)}" in active_content

    write_magnifier_runtime_cfg(str(runtime_cfg_path), 1.2, 0.82, False)
    default_content = runtime_cfg_path.read_text(encoding="utf-8")
    assert f"sensitivity {format_sensitivity_value(1.2)}" in default_content
