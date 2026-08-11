# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect lightweight runtime status for UI/system diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict

from core.audio.audio_resource_health import collect_audio_resource_health


@dataclass
class RuntimeStatus:
    gsi: Dict[str, Any]
    audio_health: Dict[str, Any]
    config_dirty: bool
    last_error: str
    level: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def collect_gsi_status(main_window) -> Dict[str, Any]:
    """GSI 运行态的**唯一**取值点（QA-011）。

    以前「关于」页的诊断信息自己手写了一份：`from gsi_server import get_gsi_server`
    —— 那个名字在 `gsi_server.py` 里**根本不存在**，于是 100% 抛 ImportError、
    被裸 except 吞成「GSI: 未知」。用户复制诊断信息发给客服，最该看的那一行永远没内容。
    就算把 import 修对，`is_running` 这个属性名也不存在（真实是 `_running`），
    会恒报「未运行」—— 比「未知」更能把排障带偏。
    所以运行态的属性名只允许在这里出现一次，别处一律复用本函数。
    """
    gsi_server = getattr(main_window, "gsi_server", None)
    if gsi_server is None:
        return {
            "available": False,
            "running": False,
            "flask_thread_alive": False,
            "startup_error": "",
            "handler_count": 0,
        }

    flask_thread = getattr(gsi_server, "flask_thread", None)
    startup_error = str(getattr(gsi_server, "startup_error", "") or "")
    return {
        "available": True,
        "running": bool(getattr(gsi_server, "_running", False)),
        "flask_thread_alive": bool(flask_thread and flask_thread.is_alive()),
        "startup_error": startup_error,
        "handler_count": len(getattr(gsi_server, "handlers", []) or []),
    }


def _collect_config_dirty(main_window) -> bool:
    pages = getattr(main_window, "pages", {}) or {}
    for page in pages.values():
        is_dirty = getattr(page, "is_dirty", None)
        if callable(is_dirty):
            try:
                if bool(is_dirty()):
                    return True
            except Exception:
                pass
        if bool(getattr(page, "_dirty", False)):
            return True
    return False


def collect_runtime_status(main_window) -> RuntimeStatus:
    """
    Aggregate runtime status used by homepage/system health strip.

    `level` values:
    - `ok`: all healthy
    - `warn`: non-fatal issues (dirty config or recoverable warnings)
    - `error`: hard errors (e.g. GSI startup failure)
    """
    gsi = collect_gsi_status(main_window)
    health_report = collect_audio_resource_health()
    health_summary = health_report.get("summary", {}) if isinstance(health_report, dict) else {}
    config_dirty = _collect_config_dirty(main_window)

    startup_error = str(gsi.get("startup_error", "") or "")
    audio_ok = bool(health_summary.get("ok", False))
    has_audio_issues = not audio_ok

    last_error = ""
    level = "ok"

    if startup_error:
        level = "error"
        last_error = startup_error
    elif has_audio_issues:
        level = "warn"
        last_error = (
            "audio: "
            f"missing={health_summary.get('missing_directories', 0)}, "
            f"invalid={health_summary.get('invalid_config_refs', 0)}, "
            f"empty={health_summary.get('empty_style_dirs', 0)}"
        )
    elif config_dirty:
        level = "warn"
        last_error = "存在未保存配置修改"

    return RuntimeStatus(
        gsi=gsi,
        audio_health=health_summary,
        config_dirty=config_dirty,
        last_error=last_error,
        level=level,
    )

