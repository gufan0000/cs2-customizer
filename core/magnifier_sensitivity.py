"""
开镜放大灵敏度联动辅助
"""

from __future__ import annotations

import os
import tempfile


DEFAULT_SYNC_TRIGGER_KEY = "SCROLLLOCK"


def get_magnifier_runtime_cfg_path(csgo_dir: str) -> str | None:
    if not csgo_dir:
        return None
    return os.path.join(csgo_dir, "game", "csgo", "cfg", "fanpai_magnifier_runtime.cfg")


def compute_zoom_sensitivity(base_sensitivity: float, multiplier: float) -> float:
    return max(0.01, round(float(base_sensitivity) * float(multiplier), 6))


def format_sensitivity_value(value: float) -> str:
    formatted = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return formatted or "0"


def get_keyboard_key_for_sync(sync_key: str) -> str:
    normalized = (sync_key or DEFAULT_SYNC_TRIGGER_KEY).strip().upper()
    mapping = {
        "SCROLLLOCK": "scroll lock",
        "CAPSLOCK": "caps lock",
        "NUMLOCK": "num lock",
    }
    return mapping.get(normalized, normalized.lower().replace("_", " "))


def write_magnifier_runtime_cfg(
    runtime_cfg_path: str,
    base_sensitivity: float,
    multiplier: float,
    active: bool,
) -> None:
    if not runtime_cfg_path:
        return

    cfg_dir = os.path.dirname(runtime_cfg_path)
    os.makedirs(cfg_dir, exist_ok=True)

    target_sensitivity = (
        compute_zoom_sensitivity(base_sensitivity, multiplier)
        if active
        else max(0.01, round(float(base_sensitivity), 6))
    )
    fd, tmp_path = tempfile.mkstemp(dir=cfg_dir, prefix="magnifier_runtime_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("// FanPai magnifier runtime sensitivity\n")
            f.write(f"sensitivity {format_sensitivity_value(target_sensitivity)}\n")
        os.replace(tmp_path, runtime_cfg_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
