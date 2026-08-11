"""v2.2.1: 一步式"新建音效风格"核心逻辑（与 UI 解耦，便于单测）。

用户痛点：添加自定义音效要手动开资源目录、建文件夹、把文件逐个精确改名成
1.mp3~5.mp3、再回程序手动刷新——且 UI 从不提示这套命名规则。
本模块把"任意命名的源文件 → 规范落盘"做成一个原子操作：
    create_style(category, style_name, files, weapon=...) → 复制并自动改名。

支持的目录范式（见 audio_manager 扫描逻辑）：
- numbered  : 风格目录内 1..5.<ext>（击杀音效/击杀语音，含全局与武器专属两级）
- single    : 风格目录内任意单文件（切枪/换弹，播放取第一个音频文件）
- flat      : 文件名即风格（被击杀音效 death/<风格名>.<ext>）
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS
from resource_manager import ResourceManager

MAX_NUMBERED_SLOTS = 5

# Windows 文件名非法字符 + 路径分隔符；另拦截保留哨兵值
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"", "0", "none", "off", "disabled", "default", "不启用", "未启用", "con", "prn", "aux", "nul"}


@dataclass
class StyleTemplate:
    label: str
    root: str                     # 全局风格根目录（相对 resources/audio）
    layout: str                   # numbered | single | flat
    weapon_root: str = ""         # 武器专属根目录；空=不支持武器专属
    max_files: int = MAX_NUMBERED_SLOTS


CATEGORY_TEMPLATES: Dict[str, StyleTemplate] = {
    "kill_sound": StyleTemplate("击杀音效", "kill_sounds", "numbered", weapon_root="weapon_kill_sounds"),
    "kill_voice": StyleTemplate("击杀语音", "kill_voices", "numbered", weapon_root="weapon_kill_voices"),
    "switch_weapon": StyleTemplate("切枪音效", "switch_weapons", "single", weapon_root="switch_weapons", max_files=1),
    "reload_sound": StyleTemplate("换弹音效", "reload_sounds", "single", weapon_root="reload_sounds", max_files=1),
    "death_sound": StyleTemplate("被击杀音效", "death", "flat", max_files=1),
}


@dataclass
class StyleCreateResult:
    ok: bool
    style_name: str = ""
    target_dir: str = ""
    created_files: List[str] = field(default_factory=list)
    error: str = ""               # 机器可读错误码
    message: str = ""             # 用户可读中文说明


def validate_style_name(name: str) -> Optional[str]:
    """返回 None 表示合法；否则返回中文错误说明。"""
    value = str(name or "").strip()
    if not value:
        return "风格名不能为空"
    if value.lower() in _RESERVED_NAMES:
        return f"“{value}”是保留名称，请换一个风格名"
    if _ILLEGAL_CHARS.search(value):
        return '风格名不能包含 < > : " / \\ | ? * 等字符'
    if value.startswith(".") or value.endswith("."):
        return "风格名不能以点开头或结尾"
    if len(value) > 48:
        return "风格名过长（最多 48 个字符）"
    return None


def _is_supported_audio(path: str) -> bool:
    return str(path or "").lower().endswith(tuple(DEFAULT_AUDIO_EXTENSIONS))


def _audio_root() -> str:
    return ResourceManager.get_app_data_path("resources/audio")


def resolve_style_target_dir(category: str, style_name: str, weapon: str = "") -> str:
    """计算风格的落盘目录（flat 范式返回其根目录）。"""
    template = CATEGORY_TEMPLATES[category]
    root = _audio_root()
    if weapon and template.weapon_root:
        # 切枪/换弹本身就是 weapon/style 两级；击杀走 weapon_kill_* 根
        if category in ("switch_weapon", "reload_sound"):
            return os.path.join(root, template.weapon_root, weapon, style_name)
        return os.path.join(root, template.weapon_root, weapon, style_name)
    if template.layout == "flat":
        return os.path.join(root, template.root)
    return os.path.join(root, template.root, style_name)


def style_exists(category: str, style_name: str, weapon: str = "") -> bool:
    template = CATEGORY_TEMPLATES[category]
    target = resolve_style_target_dir(category, style_name, weapon)
    if template.layout == "flat":
        if not os.path.isdir(target):
            return False
        stem = str(style_name).lower()
        for fname in os.listdir(target):
            base, ext = os.path.splitext(fname)
            if base.lower() == stem and _is_supported_audio(fname):
                return True
        return False
    return os.path.isdir(target)


def create_style(
    category: str,
    style_name: str,
    files: List[str],
    *,
    weapon: str = "",
    overwrite: bool = False,
) -> StyleCreateResult:
    """把任意命名的源音频复制为规范结构。

    numbered: files 按顺序映射为 1..5.<原扩展名>
    single/flat: 只取 files[0]
    源文件一律复制（不移动、不改动用户原文件）。
    """
    if category not in CATEGORY_TEMPLATES:
        return StyleCreateResult(False, error="bad_category", message=f"未知的音效类别: {category}")
    template = CATEGORY_TEMPLATES[category]

    style_name = str(style_name or "").strip()
    name_error = validate_style_name(style_name)
    if name_error:
        return StyleCreateResult(False, error="bad_name", message=name_error)

    if weapon and not template.weapon_root:
        return StyleCreateResult(False, error="weapon_not_supported", message=f"{template.label}不支持武器专属风格")
    if category in ("switch_weapon", "reload_sound") and not weapon:
        return StyleCreateResult(False, error="weapon_required", message=f"{template.label}需要先选择武器")

    files = [str(f) for f in (files or []) if str(f or "").strip()]
    if not files:
        return StyleCreateResult(False, error="no_files", message="请至少添加一个音频文件")
    if len(files) > template.max_files:
        return StyleCreateResult(
            False, error="too_many_files",
            message=f"{template.label}最多支持 {template.max_files} 个文件（多余的请移除）",
        )
    for f in files:
        if not os.path.isfile(f):
            return StyleCreateResult(False, error="file_missing", message=f"文件不存在: {f}")
        if not _is_supported_audio(f):
            supported = "、".join(ext.lstrip(".") for ext in DEFAULT_AUDIO_EXTENSIONS)
            return StyleCreateResult(
                False, error="bad_extension",
                message=f"不支持的音频格式: {os.path.basename(f)}（支持 {supported}）",
            )

    if not overwrite and style_exists(category, style_name, weapon):
        return StyleCreateResult(
            False, error="style_exists",
            message=f"风格“{style_name}”已存在，换个名字或选择覆盖",
        )

    target_dir = resolve_style_target_dir(category, style_name, weapon)
    created: List[str] = []
    try:
        os.makedirs(target_dir, exist_ok=True)
        if overwrite and os.path.isdir(target_dir):
            # 覆盖时先清掉目录里的旧音频：用 2 个文件覆盖原 5 文件风格时，
            # 残留的 3/4/5 号旧音会混进新风格（不同扩展名的同名旧文件同理）
            for old in os.listdir(target_dir):
                old_path = os.path.join(target_dir, old)
                if os.path.isfile(old_path) and _is_supported_audio(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
        if template.layout == "flat":
            src = files[0]
            ext = os.path.splitext(src)[1].lower()
            dst = os.path.join(target_dir, f"{style_name}{ext}")
            shutil.copy2(src, dst)
            created.append(dst)
        elif template.layout == "single":
            src = files[0]
            ext = os.path.splitext(src)[1].lower()
            dst = os.path.join(target_dir, f"1{ext}")
            shutil.copy2(src, dst)
            created.append(dst)
        else:  # numbered
            for index, src in enumerate(files, start=1):
                ext = os.path.splitext(src)[1].lower()
                dst = os.path.join(target_dir, f"{index}{ext}")
                shutil.copy2(src, dst)
                created.append(dst)
    except OSError as exc:
        # 复制中途失败：清理本次已创建的文件，不留半成品
        for path in created:
            try:
                os.remove(path)
            except OSError:
                pass
        if template.layout != "flat":
            try:
                if os.path.isdir(target_dir) and not os.listdir(target_dir):
                    os.rmdir(target_dir)
            except OSError:
                pass
        return StyleCreateResult(False, error="io_error", message=f"复制文件失败：{exc}")

    hint = ""
    if template.layout == "numbered" and len(files) < MAX_NUMBERED_SLOTS:
        missing = list(range(len(files) + 1, MAX_NUMBERED_SLOTS + 1))
        hint = f"（未提供 {'、'.join(str(m) for m in missing)} 连杀音，触发时将回退到通用音效）"
    return StyleCreateResult(
        True,
        style_name=style_name,
        target_dir=target_dir,
        created_files=created,
        message=f"风格“{style_name}”已创建，共 {len(created)} 个文件{hint}",
    )


# ---------------------------------------------------------------------------
# v2.2.1: 全局风格管理（重命名 / 安全删除）——仅支持目录型全局风格
# （kill_sounds / kill_voices）。config 引用同步更新，删除移入回收区不物理删除。
# ---------------------------------------------------------------------------

_MANAGEABLE_CATEGORIES = {
    "kill_sound": ("kill_sounds", "weapon_kill_sounds"),
    "kill_voice": ("kill_voices", "weapon_kill_voices"),
}


def _update_style_refs(config_obj, config_key: str, old_name: str, new_name: Optional[str]) -> int:
    """把武器映射里等于 old_name 的引用改为 new_name（None 表示重置为 "0"）。返回更新条数。"""
    style_map = getattr(config_obj, config_key, None)
    if not isinstance(style_map, dict):
        return 0
    updated = 0
    for weapon, style in list(style_map.items()):
        if str(style) == old_name:
            style_map[weapon] = new_name if new_name is not None else "0"
            updated += 1
    return updated


def rename_style(category: str, old_name: str, new_name: str) -> StyleCreateResult:
    """重命名全局风格目录并同步 config 引用。"""
    if category not in _MANAGEABLE_CATEGORIES:
        return StyleCreateResult(False, error="bad_category", message="该类别暂不支持重命名")
    name_error = validate_style_name(new_name)
    if name_error:
        return StyleCreateResult(False, error="bad_name", message=name_error)
    root_rel, weapon_map_key = _MANAGEABLE_CATEGORIES[category]
    root = os.path.join(_audio_root(), root_rel)
    old_dir = os.path.join(root, old_name)
    new_dir = os.path.join(root, new_name.strip())
    if not os.path.isdir(old_dir):
        return StyleCreateResult(False, error="not_found", message=f"风格“{old_name}”不存在")
    if os.path.exists(new_dir):
        return StyleCreateResult(False, error="style_exists", message=f"风格“{new_name}”已存在")
    try:
        os.rename(old_dir, new_dir)
    except OSError as exc:
        return StyleCreateResult(
            False, error="io_error",
            message=f"重命名失败：目录可能被占用（{exc}）",
        )

    from config import config as _config

    updated = _update_style_refs(_config, weapon_map_key, old_name, new_name.strip())
    if updated:
        _config.save_config()
    return StyleCreateResult(
        True, style_name=new_name.strip(), target_dir=new_dir,
        message=f"已重命名为“{new_name.strip()}”，同步更新了 {updated} 处武器配置",
    )


def delete_style(category: str, style_name: str) -> StyleCreateResult:
    """安全删除全局风格：移入回收区 _trash（可手动找回），引用重置为不启用。"""
    if category not in _MANAGEABLE_CATEGORIES:
        return StyleCreateResult(False, error="bad_category", message="该类别暂不支持删除")
    root_rel, weapon_map_key = _MANAGEABLE_CATEGORIES[category]
    root = os.path.join(_audio_root(), root_rel)
    style_dir = os.path.join(root, style_name)
    if not os.path.isdir(style_dir):
        return StyleCreateResult(False, error="not_found", message=f"风格“{style_name}”不存在")

    import time as _time

    trash_root = os.path.join(_audio_root(), "_trash")
    trash_dir = os.path.join(trash_root, f"{_time.strftime('%Y%m%d_%H%M%S')}_{root_rel}_{style_name}")
    try:
        os.makedirs(trash_root, exist_ok=True)
        shutil.move(style_dir, trash_dir)
    except OSError as exc:
        return StyleCreateResult(
            False, error="io_error",
            message=f"删除失败：目录可能被占用（{exc}）",
        )

    from config import config as _config

    updated = _update_style_refs(_config, weapon_map_key, style_name, None)
    if updated:
        _config.save_config()
    return StyleCreateResult(
        True, style_name=style_name, target_dir=trash_dir,
        message=f"风格“{style_name}”已移入回收区（{updated} 处武器配置已重置为不启用），可在 _trash 目录找回",
    )


def list_style_files(category: str, style_name: str) -> List[str]:
    """列出全局风格目录内的音频文件（用于管理对话框展示）。"""
    if category not in _MANAGEABLE_CATEGORIES:
        return []
    root_rel, _ = _MANAGEABLE_CATEGORIES[category]
    style_dir = os.path.join(_audio_root(), root_rel, style_name)
    if not os.path.isdir(style_dir):
        return []
    return sorted(
        f for f in os.listdir(style_dir)
        if _is_supported_audio(f) and os.path.isfile(os.path.join(style_dir, f))
    )
