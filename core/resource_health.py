# SPDX-License-Identifier: GPL-3.0-or-later
"""System resource health helpers for audio + visual assets."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List

from config import config
from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS, has_audio_files
from core.audio.audio_resource_health import (
    apply_conservative_audio_fix,
    collect_audio_resource_health,
    format_audio_resource_health,
)
from core.health_report_text import (
    label_dir,
    label_for_key,
    label_for_reason,
    relative_path,
    shorten_path,
)
from core.resource_catalog import CROSSHAIR_EXTENSIONS, IMAGE_EXTENSIONS
from resource_manager import ResourceManager


def _human_time(iso: object) -> str:
    """`2026-09-05T00:42:11` → `2026-09-05 00:42`。认不出来就原样交出去。"""
    text = str(iso or "")
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return text


def _make_issue(key: str, value: str, path: str, reason: str) -> Dict[str, str]:
    return {
        "key": key,
        "value": value,
        "expected_path": path,
        "reason": reason,
    }


def _style_dir_has_images(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    for name in os.listdir(path):
        full_path = os.path.join(path, name)
        if os.path.isfile(full_path) and name.lower().endswith(IMAGE_EXTENSIONS):
            return True
    return False


def _dir_has_crosshair_files(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    for name in os.listdir(path):
        full_path = os.path.join(path, name)
        if os.path.isfile(full_path) and name.lower().endswith(CROSSHAIR_EXTENSIONS):
            return True
    return False


def collect_visual_resource_health() -> Dict[str, object]:
    resource_root = ResourceManager.get_app_data_path("resources")
    missing_directories: List[str] = []
    invalid_config_refs: List[Dict[str, str]] = []
    empty_style_dirs: List[str] = []

    required_dirs = {
        "kill_icons": ResourceManager.get_app_data_path("resources/kill_icons"),
        "flash_images": ResourceManager.get_app_data_path("resources/flash_images"),
        "flash_audio": ResourceManager.get_app_data_path("resources/flash_audio"),
        "utility_guides": ResourceManager.get_app_data_path("resources/utility_guides"),
        "crosshair": ResourceManager.get_app_data_path("resources/crosshair"),
    }
    for _key, full_path in required_dirs.items():
        if not os.path.isdir(full_path):
            missing_directories.append(full_path)

    if bool(getattr(config, "kill_icon_enabled", False)):
        style = str(getattr(config, "kill_icon_style", "0") or "").strip()
        if style not in ("", "0", "none", "off", "disabled", "不启用", "未启用"):
            if not ResourceManager.style_has_kill_icons(style):
                invalid_config_refs.append(
                    _make_issue(
                        "kill_icon_style",
                        style,
                        ResourceManager.get_kill_icon_style_dir(style),
                        "style assets missing",
                    )
                )

    if bool(getattr(config, "flash_enabled", False)):
        image_style = str(getattr(config, "flash_image_style", "none") or "").strip()
        if image_style not in ("", "0", "none", "off", "disabled", "不启用", "未启用"):
            style_dir = ResourceManager.get_app_data_path(f"resources/flash_images/{image_style}")
            if not os.path.isdir(style_dir):
                invalid_config_refs.append(
                    _make_issue("flash_image_style", image_style, style_dir, "style directory missing")
                )
            elif not _style_dir_has_images(style_dir):
                empty_style_dirs.append(style_dir)
                invalid_config_refs.append(
                    _make_issue(
                        "flash_image_style",
                        image_style,
                        style_dir,
                        "style directory has no supported image files",
                    )
                )

    if bool(getattr(config, "flash_audio_enabled", False)):
        audio_style = str(getattr(config, "flash_audio_style", "none") or "").strip()
        if audio_style not in ("", "0", "none", "off", "disabled", "不启用", "未启用"):
            style_dir = ResourceManager.get_app_data_path(f"resources/flash_audio/{audio_style}")
            if not os.path.isdir(style_dir):
                invalid_config_refs.append(
                    _make_issue("flash_audio_style", audio_style, style_dir, "style directory missing")
                )
            elif not has_audio_files(style_dir, DEFAULT_AUDIO_EXTENSIONS):
                empty_style_dirs.append(style_dir)
                invalid_config_refs.append(
                    _make_issue(
                        "flash_audio_style",
                        audio_style,
                        style_dir,
                        "style directory has no supported audio files",
                    )
                )

    if bool(getattr(config, "crosshair_enabled", False)) and str(getattr(config, "crosshair_style", "") or "").strip() == "custom":
        crosshair_dir = required_dirs["crosshair"]
        custom_data = getattr(config, "crosshair_custom_data", []) or []
        if not custom_data and not _dir_has_crosshair_files(crosshair_dir):
            invalid_config_refs.append(
                _make_issue(
                    "crosshair_custom_data",
                    "custom",
                    crosshair_dir,
                    "custom crosshair data missing",
                )
            )

    summary = {
        "ok": not missing_directories and not invalid_config_refs,
        "missing_directories": len(missing_directories),
        "invalid_config_refs": len(invalid_config_refs),
        "empty_style_dirs": len(empty_style_dirs),
    }

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "resource_root": resource_root,
        "missing_directories": missing_directories,
        "empty_style_dirs": sorted(set(empty_style_dirs), key=str.lower),
        "invalid_config_refs": invalid_config_refs,
        "summary": summary,
    }


def format_visual_resource_health(report: Dict[str, object]) -> str:
    """画面资源那一半的**人话**渲染（RN-508，2026-09-05 批 48）。措辞与音效那半对齐。"""
    summary = report.get("summary", {})
    root = str(report.get("resource_root", "") or "")
    ok = bool(summary.get("ok", False))
    lines = [
        f"■ 画面资源：{'一切正常' if ok else '发现问题'}",
        f"  存放位置：{shorten_path(root)}",
    ]

    missing = report.get("missing_directories", []) or []
    if missing:
        lines.append(f"  少了 {len(missing)} 个目录（对应的图片不会显示）：")
        lines.extend([f"    · {label_dir(relative_path(path, root))}" for path in missing])

    issues = report.get("invalid_config_refs", []) or []
    if issues:
        lines.append(f"  有 {len(issues)} 项设置指着找不到的东西：")
        for issue in issues:
            lines.append(
                f"    · 「{label_for_key(str(issue.get('key', '')))}」现在选的是"
                f"「{issue.get('value')}」—— {label_for_reason(str(issue.get('reason', '')))}"
                f"（应该在 {relative_path(str(issue.get('expected_path', '')), root)}）"
            )

    if len(lines) == 2:
        lines.append("  没有发现问题。")
    return "\n".join(lines)


def collect_resource_system_health() -> Dict[str, object]:
    audio = collect_audio_resource_health()
    visual = collect_visual_resource_health()
    audio_summary = audio.get("summary", {})
    visual_summary = visual.get("summary", {})
    summary = {
        "ok": bool(audio_summary.get("ok", False)) and bool(visual_summary.get("ok", False)),
        "audio_missing_directories": int(audio_summary.get("missing_directories", 0) or 0),
        "audio_invalid_config_refs": int(audio_summary.get("invalid_config_refs", 0) or 0),
        "audio_empty_style_dirs": int(audio_summary.get("empty_style_dirs", 0) or 0),
        "visual_missing_directories": int(visual_summary.get("missing_directories", 0) or 0),
        "visual_invalid_config_refs": int(visual_summary.get("invalid_config_refs", 0) or 0),
        "visual_empty_style_dirs": int(visual_summary.get("empty_style_dirs", 0) or 0),
        # v2.2.1: 完整性/GSI 检查（提示性，不影响 ok）
        "audio_incomplete_styles": int(audio_summary.get("incomplete_styles", 0) or 0),
        "gsi_cfg_status": str(audio_summary.get("gsi_cfg_status", "unknown")),
    }
    summary["missing_directories"] = summary["audio_missing_directories"] + summary["visual_missing_directories"]
    summary["invalid_config_refs"] = summary["audio_invalid_config_refs"] + summary["visual_invalid_config_refs"]
    summary["empty_style_dirs"] = summary["audio_empty_style_dirs"] + summary["visual_empty_style_dirs"]
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "audio": audio,
        "visual": visual,
        "summary": summary,
    }


def format_resource_system_health(report: Dict[str, object]) -> str:
    """整份体检报告的**人话**渲染（RN-508，2026-09-05 批 48）。

    这份文本有两个出口：屏幕上那块「体检报告」，和「导出报告」存成的 `.txt`。
    ⭐ 两个出口共用同一份措辞 —— 用户在屏幕上看到什么，导出去的就是什么。
      （想要机器可读的那一份，导出时选 `.json`，那条路一个字都没动。）
    """
    summary = report.get("summary", {})
    ok = bool(summary.get("ok", False))
    missing = int(summary.get("missing_directories", 0) or 0)
    invalid = int(summary.get("invalid_config_refs", 0) or 0)
    empty = int(summary.get("empty_style_dirs", 0) or 0)
    total = missing + invalid + empty

    lines = [
        "资源体检报告",
        f"检查时间：{_human_time(report.get('checked_at', ''))}",
        f"结论：{'一切正常，没有发现问题' if ok else f'发现 {total} 项问题'}",
    ]
    if not ok:
        lines += [
            f"  · 少了 {missing} 个目录",
            f"  · {invalid} 项设置指着找不到的东西",
            f"  · {empty} 个风格目录是空的",
        ]
    lines += [
        "",
        format_audio_resource_health(report.get("audio", {})),
        "",
        format_visual_resource_health(report.get("visual", {})),
    ]
    return "\n".join(lines)


def apply_conservative_resource_fix() -> Dict[str, object]:
    before = collect_resource_system_health()
    audio_fix = apply_conservative_audio_fix()

    created_visual_dirs: List[str] = []
    visual_root_ensurers = (
        ResourceManager.ensure_crosshair_directory,
        ResourceManager.ensure_flash_audio_directory,
        ResourceManager.ensure_flash_images_directory,
        ResourceManager.ensure_kill_icons_directory,
        ResourceManager.ensure_utility_guides_directory,
    )
    for ensure_directory in visual_root_ensurers:
        directory = ensure_directory()
        if not os.path.isdir(directory):
            continue
        if directory in before.get("visual", {}).get("missing_directories", []):
            created_visual_dirs.append(directory)

    after = collect_resource_system_health()
    return {
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_id": str(audio_fix.get("snapshot_id", "")),
        "created_visual_directories": created_visual_dirs,
        "audio_fix": audio_fix,
        "before": before,
        "after": after,
    }
