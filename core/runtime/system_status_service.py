# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect lightweight runtime status for UI/system diagnostics."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict

from core.audio.audio_resource_health import collect_audio_resource_health


@dataclass
class RuntimeStatus:
    gsi: Dict[str, Any]
    audio_health: Dict[str, Any]
    config_dirty: bool
    last_error: str
    level: str
    gsi_link: str = ""                 # 批 116：gsi_link_state 的结果
    gsi_cfg: Dict[str, Any] = field(default_factory=dict)

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
    status = {
        "available": True,
        "running": bool(getattr(gsi_server, "_running", False)),
        "flask_thread_alive": bool(flask_thread and flask_thread.is_alive()),
        "startup_error": startup_error,
        "handler_count": len(getattr(gsi_server, "handlers", []) or []),
    }
    # 批 116：CS2 到底有没有在推。只读已经加载的模块 —— 这里 import 会把 flask 拖进启动路径。
    server_module = sys.modules.get("gsi_server")
    if server_module is not None:
        try:
            status.update(server_module.get_receive_stats())
            status["port"] = int(server_module.get_active_port())
        except Exception:
            pass
    return status


#: CS2 心跳 15 秒（cfg_utils.CFG_TEMPLATE）⇒ 四个心跳都没来才算断了。
GSI_FRESH_S = 60.0
GSI_CFG_NAME = "gamestate_integration_cs2customizer.cfg"


def check_gsi_cfg(csgo_dir: str, active_port) -> Dict[str, Any]:
    """游戏里的联动配置装没装、端口对不对。status: ok / not_configured / missing / unreadable / port_mismatch。"""
    csgo_dir = str(csgo_dir or "").strip()
    if not csgo_dir:
        return {"status": "not_configured"}
    path = os.path.join(csgo_dir, "game", "csgo", "cfg", GSI_CFG_NAME)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return {"status": "missing", "path": path}
    except OSError:
        return {"status": "unreadable", "path": path}
    m = re.search(r'"uri"\s*"http://127\.0\.0\.1:(\d+)/?"', text)
    port = int(m.group(1)) if m else None
    if active_port and port and int(port) != int(active_port):
        return {"status": "port_mismatch", "path": path, "port": port}
    return {"status": "ok", "path": path, "port": port}


def gsi_link_state(gsi: Dict[str, Any], cfg: Dict[str, Any], game_running) -> str:
    """「断在哪一环」：failed / stopped / connected / cfg_missing / cfg_port / silent / no_game。

    顺序就是排障顺序：服务起没起 → 数据在不在来（来了就一切都对，别的不用看）→
    配置装没装 → 游戏开着却没推（`game_running` 为 None = 判断不出来，按没开算，不报警）。
    """
    if gsi.get("startup_error"):
        return "failed"
    if not gsi.get("running"):
        return "stopped"
    age = gsi.get("last_post_age_s")
    if age is not None and age <= GSI_FRESH_S:
        return "connected"
    cfg_status = (cfg or {}).get("status")
    if cfg_status == "port_mismatch":
        return "cfg_port"
    if cfg_status in ("not_configured", "missing", "unreadable"):
        return "cfg_missing"
    return "silent" if game_running else "no_game"


#: 徽章词（与「GSI · 」拼成徽章，**一律三个字**，与原来的「运行中」等宽）+ 级别 + 那一句修法。
GSI_LINK_TEXT = {
    "connected": ("已连接", "positive", "正在收到 CS2 的数据，联动正常。"),
    "no_game": ("等游戏", "info", "联动服务已就绪 —— 开 CS2 进一局（训练场也行），这里会变成「已连接」。"),
    # ⚠ 首页运行面板那张卡在这句折行时不会长高，下一排按钮会被切 ⇒ 一律不比音频那句长
    "silent": ("没收到", "warning",
               "CS2 开着却一分钟没收到数据 —— 刚装好配置就重启一次 CS2；开着加速器或代理的，把 127.0.0.1 设为直连。"),
    "cfg_missing": ("未装好", "warning", "游戏里的联动配置没装上 —— 去「高级设置」选一次 CS2 目录。"),
    "cfg_port": ("未装好", "warning", "游戏里的联动配置还写着旧端口 —— 重启本软件会自动重写，之后重启一次 CS2。"),
    "failed": ("启动失败", "danger", ""),          # 修法是 startup_error 本身
    "stopped": ("未运行", "info", "联动服务还没起来（软件启动时会自动起）。"),
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

    # 批 116：断在哪一环（服务 → 配置 → 游戏在不在推）
    from config import config
    from core.foreground_game import game_is_running

    gsi_cfg = check_gsi_cfg(getattr(config, "csgo_dir", ""), gsi.get("port"))
    gsi_link = gsi_link_state(gsi, gsi_cfg, game_is_running())

    last_error = ""
    level = "ok"

    if startup_error:
        level = "error"
        last_error = startup_error
    elif gsi_link in ("silent", "cfg_missing", "cfg_port"):
        level = "warn"
        last_error = GSI_LINK_TEXT[gsi_link][2]
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
        gsi_link=gsi_link,
        gsi_cfg=gsi_cfg,
    )

