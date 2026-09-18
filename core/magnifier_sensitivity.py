# SPDX-License-Identifier: GPL-3.0-or-later
"""
开镜放大灵敏度联动辅助
"""

from __future__ import annotations

import os
import tempfile
from core.io_validation import replace_with_retry


DEFAULT_SYNC_TRIGGER_KEY = "SCROLLLOCK"


def get_magnifier_runtime_cfg_path(csgo_dir: str) -> str | None:
    if not csgo_dir:
        return None
    return os.path.join(csgo_dir, "game", "csgo", "cfg", "cs2customizer_magnifier_runtime.cfg")


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


def render_magnifier_runtime_cfg(
    base_sensitivity: float,
    multiplier: float,
    active: bool,
) -> str:
    """算出这个文件该长什么样。单独摆出来是为了让"要不要写"可以先比一遍内容。"""
    target_sensitivity = (
        compute_zoom_sensitivity(base_sensitivity, multiplier)
        if active
        else max(0.01, round(float(base_sensitivity), 6))
    )
    # ⚠ 这行**不许出现品牌名**：开源同步的机械替换会改写它，两边就得靠一个语义补丁去圆
    # （`core__magnifier_sensitivity_py.patch`，已随本次重构删掉）。⭐ 生成物该说「别手改」。
    return (
        "// magnifier runtime sensitivity (generated, do not edit)\n"
        f"sensitivity {format_sensitivity_value(target_sensitivity)}\n"
    )


def write_magnifier_runtime_cfg(
    runtime_cfg_path: str,
    base_sensitivity: float,
    multiplier: float,
    active: bool,
) -> bool:
    """写运行期灵敏度 cfg。**内容和盘上一样就一个字节都不动**，返回是否真写了。

    ⭐ RN-657：这个文件在开镜路径上，而一次开镜会经过两个写点
    （`_ensure_sensitivity_support_files_if_needed` 一次、
    `_sync_magnifier_sensitivity_state` 再一次），后一次往往和前一次写的一模一样。
    开镜是每局上百次的动作，"同样的字节再落一次盘"在这条路上是纯开销。
    """
    if not runtime_cfg_path:
        return False

    content = render_magnifier_runtime_cfg(base_sensitivity, multiplier, active)

    try:
        with open(runtime_cfg_path, "r", encoding="utf-8") as existing:
            if existing.read() == content:
                return False
    except (OSError, UnicodeDecodeError):
        # 不存在 / 读不动 / 编码坏了 —— 都按"要写"处理，让下面的写盘去定胜负
        pass

    cfg_dir = os.path.dirname(runtime_cfg_path)
    os.makedirs(cfg_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=cfg_dir, prefix="magnifier_runtime_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        replace_with_retry(tmp_path, runtime_cfg_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return True
