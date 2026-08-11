# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio resource health checks for diagnostics and support."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List

from config import config
from resource_manager import ResourceManager
from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_audio_by_stem,
    has_audio_files,
)


REQUIRED_AUDIO_DIRS = [
    "kill_sounds",
    "kill_voices",
    "weapon_kill_sounds",
    "weapon_kill_voices",
    "death",
    "switch_weapons",
    "reload_sounds",
    "grenade_sounds",
    "c4_sounds",
    "health_warning",
    "round_sounds",
    "gun_sounds",
]


def _make_issue(key: str, value: str, path: str, reason: str) -> Dict[str, str]:
    return {
        "key": key,
        "value": value,
        "expected_path": path,
        "reason": reason,
    }


def _style_dir_has_audio(path: str) -> bool:
    return bool(path and os.path.isdir(path) and has_audio_files(path, DEFAULT_AUDIO_EXTENSIONS))


KILL_LEVELS = (1, 2, 3, 4, 5)


def _resolve_kill_style_dir(audio_root: str, weapon: str, style: str, *, voice: bool = False) -> str:
    """按加载优先级解析击杀音效/语音风格目录：武器专属优先，回退全局风格。"""
    weapon_root = "weapon_kill_voices" if voice else "weapon_kill_sounds"
    global_root = "kill_voices" if voice else "kill_sounds"
    weapon_dir = os.path.join(audio_root, weapon_root, weapon, style)
    if os.path.isdir(weapon_dir):
        return weapon_dir
    return os.path.join(audio_root, global_root, style)


def _collect_incomplete_kill_styles(audio_root: str) -> List[Dict[str, object]]:
    """v2.2.1: 完整性检查——被 config 引用的击杀风格目录里 1-5 连杀文件缺哪些。

    这是"我导入的音效为什么不响"的直接答案：目录存在但缺 3.mp3 时，
    3 连杀会回退到通用音效或静音，旧体检只查目录存在查不出来。
    按风格目录去重，列出引用它的武器数。
    """
    results: Dict[str, Dict[str, object]] = {}
    for config_key, is_voice in (("weapon_kill_sounds", False), ("weapon_kill_voices", True)):
        style_map = getattr(config, config_key, {}) or {}
        if not isinstance(style_map, dict):
            continue
        for weapon, style in style_map.items():
            if style in ("0", "", None):
                continue
            style_dir = _resolve_kill_style_dir(audio_root, str(weapon), str(style), voice=is_voice)
            if not os.path.isdir(style_dir):
                continue  # 目录缺失由 invalid_config_refs 负责报告
            entry = results.get(style_dir)
            if entry is None:
                missing = [
                    level for level in KILL_LEVELS
                    if not find_audio_by_stem(style_dir, str(level), extensions=DEFAULT_AUDIO_EXTENSIONS)
                ]
                if not missing:
                    continue  # 1-5 全齐，无需报告
                entry = {
                    "style_dir": style_dir,
                    "style": str(style),
                    "kind": "kill_voice" if is_voice else "kill_sound",
                    "missing_levels": missing,
                    "referenced_by": [],
                }
                results[style_dir] = entry
            entry["referenced_by"].append(f"{config_key}.{weapon}")
    return [e for e in results.values() if e["missing_levels"]]


def check_gsi_cfg_match_stats() -> Dict[str, str]:
    """v2.2.1: 检查游戏内 GSI cfg 是否包含 player_match_stats 组件。

    缺失时回合结束补枪的严格校验无法工作（运行时已有降级，但修好 cfg 更彻底）。
    只读检查，不改动游戏目录。
    """
    csgo_dir = str(getattr(config, "csgo_dir", "") or "").strip()
    if not csgo_dir:
        return {"status": "not_configured", "detail": "未设置 CS2 目录，无法检查 GSI 配置文件"}
    cfg_path = os.path.join(csgo_dir, "game", "csgo", "cfg", "gamestate_integration_cs2customizer.cfg")
    if not os.path.isfile(cfg_path):
        return {"status": "missing", "detail": f"GSI 配置文件不存在: {cfg_path}", "path": cfg_path}
    try:
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as exc:
        return {"status": "unreadable", "detail": f"无法读取 GSI 配置文件: {exc}", "path": cfg_path}
    if "player_match_stats" not in content:
        return {
            "status": "missing_match_stats",
            "detail": "GSI 配置缺少 player_match_stats 组件（回合结束补枪音效判定受限），重启软件或重选 CS2 目录可自动重写",
            "path": cfg_path,
        }
    return {"status": "ok", "detail": "GSI 配置包含 player_match_stats", "path": cfg_path}


def collect_audio_resource_health() -> Dict[str, object]:
    """
    Build a lightweight health report for audio resources and config references.
    """
    audio_root = ResourceManager.get_app_data_path("resources/audio")
    missing_directories: List[str] = []
    invalid_config_refs: List[Dict[str, str]] = []
    empty_style_dirs: List[str] = []

    for rel in REQUIRED_AUDIO_DIRS:
        full_path = os.path.join(audio_root, rel)
        if not os.path.isdir(full_path):
            missing_directories.append(full_path)

    # death style
    death_style = getattr(config, "death_sound_style", "0")
    if death_style not in ("0", "", None):
        death_path = find_audio_by_stem(
            os.path.join(audio_root, "death"),
            str(death_style),
            extensions=DEFAULT_AUDIO_EXTENSIONS,
        )
        if not death_path:
            invalid_config_refs.append(
                _make_issue(
                    "death_sound_style",
                    str(death_style),
                    os.path.join(audio_root, "death"),
                    "style file not found",
                )
            )

    # grenade styles
    grenade_styles = getattr(config, "grenade_sound_styles", {}) or {}
    for grenade_type, style in grenade_styles.items():
        if style in ("0", "", None):
            continue
        style_dir = os.path.join(audio_root, "grenade_sounds", grenade_type, str(style))
        if not os.path.isdir(style_dir):
            invalid_config_refs.append(
                _make_issue(
                    f"grenade_sound_styles.{grenade_type}",
                    str(style),
                    style_dir,
                    "style directory missing",
                )
            )
            continue
        if not _style_dir_has_audio(style_dir):
            empty_style_dirs.append(style_dir)
            invalid_config_refs.append(
                _make_issue(
                    f"grenade_sound_styles.{grenade_type}",
                    str(style),
                    style_dir,
                    "style directory has no supported audio files",
                )
            )

    # c4 / health
    for key, rel_dir in (
        ("c4_sound_style", "c4_sounds"),
        ("health_warning_style", "health_warning"),
    ):
        style = getattr(config, key, "0")
        if style in ("0", "", None):
            continue
        style_dir = os.path.join(audio_root, rel_dir, str(style))
        if not os.path.isdir(style_dir):
            invalid_config_refs.append(
                _make_issue(key, str(style), style_dir, "style directory missing")
            )
            continue
        if not _style_dir_has_audio(style_dir):
            empty_style_dirs.append(style_dir)
            invalid_config_refs.append(
                _make_issue(
                    key,
                    str(style),
                    style_dir,
                    "style directory has no supported audio files",
                )
            )

    # round styles
    for round_type, key in (
        ("start", "round_start_style"),
        ("action", "round_action_style"),
        ("win", "round_win_style"),
        ("lose", "round_lose_style"),
        ("mvp", "round_mvp_style"),
    ):
        style = getattr(config, key, "0")
        if style in ("0", "", None):
            continue
        style_dir = os.path.join(audio_root, "round_sounds", round_type, str(style))
        if not os.path.isdir(style_dir):
            invalid_config_refs.append(
                _make_issue(key, str(style), style_dir, "style directory missing")
            )
            continue
        if not _style_dir_has_audio(style_dir):
            empty_style_dirs.append(style_dir)
            invalid_config_refs.append(
                _make_issue(
                    key,
                    str(style),
                    style_dir,
                    "style directory has no supported audio files",
                )
            )

    # switch/reload style maps
    for key, rel_dir in (
        ("weapon_switch_sounds", "switch_weapons"),
        ("weapon_reload_sounds", "reload_sounds"),
    ):
        style_map = getattr(config, key, {}) or {}
        for weapon, style in style_map.items():
            if style in ("0", "", None):
                continue
            style_dir = os.path.join(audio_root, rel_dir, str(weapon), str(style))
            if not os.path.isdir(style_dir):
                invalid_config_refs.append(
                    _make_issue(f"{key}.{weapon}", str(style), style_dir, "style directory missing")
                )
                continue
            if not _style_dir_has_audio(style_dir):
                empty_style_dirs.append(style_dir)
                invalid_config_refs.append(
                    _make_issue(
                        f"{key}.{weapon}",
                        str(style),
                        style_dir,
                        "style directory has no supported audio files",
                    )
                )

    incomplete_styles = _collect_incomplete_kill_styles(audio_root)
    gsi_cfg = check_gsi_cfg_match_stats()

    summary = {
        "ok": not missing_directories and not invalid_config_refs,
        "missing_directories": len(missing_directories),
        "invalid_config_refs": len(invalid_config_refs),
        "empty_style_dirs": len(empty_style_dirs),
        # 完整性/GSI 检查是提示性信息，不影响 ok 判定（保持既有语义与既有测试）
        "incomplete_styles": len(incomplete_styles),
        "gsi_cfg_status": gsi_cfg.get("status", "unknown"),
    }

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "audio_root": audio_root,
        "supported_extensions": list(DEFAULT_AUDIO_EXTENSIONS),
        "missing_directories": missing_directories,
        "empty_style_dirs": sorted(set(empty_style_dirs), key=str.lower),
        "invalid_config_refs": invalid_config_refs,
        "incomplete_styles": incomplete_styles,
        "gsi_cfg": gsi_cfg,
        "summary": summary,
    }


def _set_config_ref_to_zero(config_key: str) -> bool:
    """
    Reset a config key path to \"0\".

    Supports:
    - top-level field, e.g. death_sound_style
    - one-level dict field, e.g. weapon_switch_sounds.weapon_ak47
    """
    if "." not in config_key:
        old_value = getattr(config, config_key, None)
        if str(old_value) == "0":
            return False
        setattr(config, config_key, "0")
        return True

    root, leaf = config_key.split(".", 1)
    container = getattr(config, root, None)
    if not isinstance(container, dict):
        return False
    if str(container.get(leaf, "0")) == "0":
        return False
    container[leaf] = "0"
    return True


def apply_conservative_audio_fix() -> Dict[str, object]:
    """
    Conservative one-click fix:
    1. create missing required directories
    2. reset invalid style references to \"0\"
    3. save config now
    4. trigger style rescan
    5. return before/after report
    """
    snapshot_id = ""
    if bool(getattr(config, "config_snapshot_auto_before_risky_ops", True)):
        try:
            from core.config_snapshot_manager import create_snapshot, prune_snapshots

            snapshot = create_snapshot("audio_health_conservative_fix")
            snapshot_id = snapshot.snapshot_id
            prune_snapshots(int(getattr(config, "config_snapshot_max_keep", 20) or 20))
        except Exception:
            snapshot_id = ""

    before = collect_audio_resource_health()
    audio_root = before.get("audio_root", ResourceManager.get_app_data_path("resources/audio"))

    created_dirs: List[str] = []
    for rel in REQUIRED_AUDIO_DIRS:
        full_path = os.path.join(audio_root, rel)
        if not os.path.isdir(full_path):
            os.makedirs(full_path, exist_ok=True)
            created_dirs.append(full_path)

    reset_keys: List[str] = []
    for issue in before.get("invalid_config_refs", []) or []:
        key = issue.get("key", "")
        if key and _set_config_ref_to_zero(key):
            reset_keys.append(key)

    if reset_keys or created_dirs:
        save_now = getattr(config, "save_config_now", None)
        if callable(save_now):
            save_now()
        else:
            config.save_config()

    # force runtime style rescan
    try:
        from core.audio.runtime_audio import get_runtime_audio_manager

        manager = get_runtime_audio_manager()
        if hasattr(manager, "_styles_scanned"):
            manager._styles_scanned = False
        manager.ensure_styles_scanned()
    except Exception:
        # keep conservative behavior: fix should not fail hard on rescan errors
        pass

    after = collect_audio_resource_health()
    return {
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_id": snapshot_id,
        "created_directories": created_dirs,
        "reset_config_keys": reset_keys,
        "before": before,
        "after": after,
    }


def format_audio_resource_health(report: Dict[str, object]) -> str:
    summary = report.get("summary", {})
    lines = [
        "[Audio Health]",
        f"checked_at: {report.get('checked_at', '')}",
        f"audio_root: {report.get('audio_root', '')}",
        f"ok: {summary.get('ok', False)}",
        f"missing_directories: {summary.get('missing_directories', 0)}",
        f"invalid_config_refs: {summary.get('invalid_config_refs', 0)}",
        f"empty_style_dirs: {summary.get('empty_style_dirs', 0)}",
    ]

    missing = report.get("missing_directories", []) or []
    if missing:
        lines.append("missing:")
        lines.extend([f"- {path}" for path in missing])

    issues = report.get("invalid_config_refs", []) or []
    if issues:
        lines.append("invalid_refs:")
        for issue in issues:
            lines.append(
                f"- {issue.get('key')}={issue.get('value')} -> {issue.get('reason')} ({issue.get('expected_path')})"
            )

    incomplete = report.get("incomplete_styles", []) or []
    if incomplete:
        lines.append("incomplete_styles:")
        for item in incomplete:
            missing = ",".join(str(x) for x in item.get("missing_levels", []))
            refs = len(item.get("referenced_by", []) or [])
            lines.append(
                f"- [{item.get('kind')}] 风格 {item.get('style')} 缺 {missing} 连杀文件"
                f"（{refs} 把武器引用，触发时将回退或静音）: {item.get('style_dir')}"
            )

    gsi_cfg = report.get("gsi_cfg", {}) or {}
    if gsi_cfg.get("status") not in ("ok", None, ""):
        lines.append(f"gsi_cfg: [{gsi_cfg.get('status')}] {gsi_cfg.get('detail', '')}")

    return "\n".join(lines)
