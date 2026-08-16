# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标风格库的查 / 删 / 撤销（KI-5）。

导入（`core.kill_icon_import`）解决的是"素材怎么进来"，这里解决的是
**进来之后怎么管**：

- KI-5 之前，导入即覆盖，没有确认、没有备份、没有"删掉这一个等级"、
  没有"恢复默认"。手滑把 ACE 的素材导到 1 杀上，只能再找一份原素材导回去
  ——如果原素材已经找不到了，那就没了。
- 页面也没法回答"这套风格到底有哪几个等级"。KI-5 之前唯一的信号是
  "时长滑条被禁掉了"，用户得靠猜。

所以这里只做两件事：**清单**（`list_style_levels`）和**可撤销的删除**
（`delete_level` / `restore_level`）。

本模块**不 import Qt 也不 import PIL**：清单要在建页路径上跑，只读 JSON
和目录项，代价必须是几毫秒级；判据也因此能在离屏环境里裸跑。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass

from core.utils.logger import get_logger

logger = get_logger("KillIconLibrary")

LEVELS = (1, 2, 3, 4, 5)

#: 普通图标 + 爆头覆写。变体不是"新的必需资源"，缺了就退回普通图标。
VARIANTS = ("", "hs")

#: 回收站目录名。放在 kill_icons 根下，前缀点号——`list_kill_icon_styles`
#: 会把它当成一个没有素材的目录跳过，不会冒充成一套风格。
TRASH_DIRNAME = ".trash"

#: 回收站里最多留多少条。再多就把最旧的真删掉——撤销是"刚刚手滑了"的兜底，
#: 不是版本管理，无限堆着只会把用户磁盘吃光。
TRASH_KEEP = 20

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

LEVEL_LABELS = {1: "1 杀", 2: "2 杀", 3: "3 杀", 4: "4 杀", 5: "5 杀（ACE）"}


@dataclass
class LevelEntry:
    """风格库里一个"击杀等级 × 变体"的现状。"""

    kills: int
    variant: str = ""
    kind: str = ""            # "sheet" | "legacy" | ""（没有素材）
    frames: int = 0
    fps: int = 0
    hold_seconds: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    sprite_path: str = ""
    json_path: str = ""
    legacy_dir: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.kind)

    @property
    def duration(self) -> float:
        if not self.frames or not self.fps:
            return float(self.hold_seconds or 0.0)
        return self.frames / float(self.fps) + float(self.hold_seconds or 0.0)

    @property
    def label(self) -> str:
        base = LEVEL_LABELS.get(self.kills, f"{self.kills} 杀")
        return f"{base}·爆头" if self.variant else base


def _resource_manager(resource_manager=None):
    if resource_manager is not None:
        return resource_manager
    from resource_manager import ResourceManager

    return ResourceManager


def _read_json(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning(f"读取击杀图标配置失败 {path}: {exc}")
        return {}


def level_entry(style_name, kills, variant="", resource_manager=None) -> LevelEntry:
    """一个等级的现状。不解码任何像素。"""
    manager = _resource_manager(resource_manager)
    sprite_path, json_path = manager.get_kill_icon_sprite_sheet_paths(
        style_name, int(kills), variant=variant
    )
    entry = LevelEntry(kills=int(kills), variant=str(variant or ""),
                       sprite_path=sprite_path, json_path=json_path)

    if os.path.isfile(sprite_path) and os.path.isfile(json_path):
        metadata = _read_json(json_path)
        entry.kind = "sheet"
        entry.frames = int(metadata.get("frames") or 0)
        entry.fps = int(metadata.get("fps") or 0)
        entry.hold_seconds = float(metadata.get("hold_seconds") or 0.0)
        entry.frame_width = int(metadata.get("frame_width") or 0)
        entry.frame_height = int(metadata.get("frame_height") or 0)
        return entry

    if variant:
        # 变体只认图集：老格式里没有"爆头"这个概念，往逐帧目录上兜只会
        # 把普通图标当成爆头图标用。
        return entry

    legacy_dir = manager.get_kill_icon_legacy_frames_dir(style_name, int(kills))
    if legacy_dir and os.path.isdir(legacy_dir):
        entry.kind = "legacy"
        entry.legacy_dir = legacy_dir
        try:
            entry.frames = sum(
                1 for name in os.listdir(legacy_dir)
                if name.lower().endswith(_IMAGE_EXTENSIONS)
            )
        except OSError:
            entry.frames = 0
        metadata = _read_json(manager.get_kill_icon_metadata_path(style_name, int(kills)))
        entry.fps = int(metadata.get("fps") or 0)
        entry.hold_seconds = float(metadata.get("hold_seconds") or 0.0)
    return entry


def list_style_levels(style_name, resource_manager=None):
    """`[(1,""), (1,"hs"), (2,""), ...]` 的现状清单，按等级排。"""
    return [
        level_entry(style_name, kills, variant, resource_manager)
        for kills in LEVELS
        for variant in VARIANTS
    ]


def style_summary(style_name, resource_manager=None):
    """一句话概括这套风格：几个等级有素材、有没有爆头变体。"""
    entries = list_style_levels(style_name, resource_manager)
    normal = [e for e in entries if not e.variant and e.exists]
    headshot = [e for e in entries if e.variant and e.exists]
    missing = [k for k in LEVELS if k not in {e.kills for e in normal}]
    return {
        "levels": sorted(e.kills for e in normal),
        "missing": missing,
        "headshot_levels": sorted(e.kills for e in headshot),
        "frames": sum(e.frames for e in normal),
    }


# ==================================================== 回收站（可撤销的删除）


def trash_root(resource_manager=None):
    manager = _resource_manager(resource_manager)
    return manager.get_app_data_path(f"resources/kill_icons/{TRASH_DIRNAME}")


def _new_trash_slot(style_name, kills, variant, resource_manager=None):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_style = "".join(c for c in str(style_name) if c not in '\\/:*?"<>|').strip() or "风格"
    base = os.path.join(trash_root(resource_manager),
                        f"{stamp}_{safe_style}_{kills}{variant}")
    slot = base
    suffix = 1
    while os.path.exists(slot):
        slot = f"{base}-{suffix}"
        suffix += 1
    os.makedirs(slot, exist_ok=True)
    return slot


def delete_level(style_name, kills, variant="", resource_manager=None):
    """把一个等级的素材挪进回收站，返回可以拿去 `restore_level` 的令牌。

    **不是真删**：删错了的代价是"用户手上那份原素材可能已经没了"，
    而这一步是用户在页面上点一下就能触发的。没素材可删时返回 None。
    """
    entry = level_entry(style_name, kills, variant, resource_manager)
    if not entry.exists:
        return None

    slot = _new_trash_slot(style_name, kills, variant, resource_manager)
    moved = []
    try:
        if entry.kind == "sheet":
            for path in (entry.sprite_path, entry.json_path):
                if os.path.isfile(path):
                    shutil.move(path, os.path.join(slot, os.path.basename(path)))
                    moved.append(os.path.basename(path))
        else:
            target = os.path.join(slot, os.path.basename(entry.legacy_dir.rstrip("\\/")))
            shutil.move(entry.legacy_dir, target)
            moved.append(os.path.basename(target))
    except OSError as exc:
        logger.error(f"删除击杀图标素材失败 {style_name}/{kills}{variant}: {exc}")
        raise

    manifest = {
        "style": str(style_name),
        "kills": int(kills),
        "variant": str(variant or ""),
        "kind": entry.kind,
        "sprite_path": entry.sprite_path,
        "json_path": entry.json_path,
        "legacy_dir": entry.legacy_dir,
        "moved": moved,
        "deleted_at": time.time(),
    }
    with open(os.path.join(slot, "restore.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)

    logger.info(f"击杀图标素材已进回收站: {style_name}/{kills}{variant} → {slot}")
    purge_trash(resource_manager=resource_manager)
    return slot


def restore_level(token, resource_manager=None):
    """把回收站里的一条搬回原位。目标已被新素材占了就不覆盖，返回 False。"""
    if not token or not os.path.isdir(token):
        return False
    manifest = _read_json(os.path.join(token, "restore.json"))
    if not manifest:
        return False

    try:
        if manifest.get("kind") == "sheet":
            for name in manifest.get("moved", []):
                source = os.path.join(token, name)
                target = (manifest["sprite_path"] if name.lower().endswith(".png")
                          else manifest["json_path"])
                if not os.path.isfile(source) or os.path.exists(target):
                    return False
            for name in manifest.get("moved", []):
                source = os.path.join(token, name)
                target = (manifest["sprite_path"] if name.lower().endswith(".png")
                          else manifest["json_path"])
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(source, target)
        else:
            names = manifest.get("moved") or []
            if not names:
                return False
            source = os.path.join(token, names[0])
            target = manifest.get("legacy_dir") or ""
            if not os.path.isdir(source) or not target or os.path.exists(target):
                return False
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.move(source, target)
    except OSError as exc:
        logger.error(f"撤销删除失败: {exc}")
        return False

    shutil.rmtree(token, ignore_errors=True)
    logger.info(f"击杀图标素材已从回收站恢复: {manifest.get('style')}/{manifest.get('kills')}")
    return True


def purge_trash(keep=TRASH_KEEP, resource_manager=None):
    """只留最近 `keep` 条，其余真删。"""
    root = trash_root(resource_manager)
    if not os.path.isdir(root):
        return 0
    try:
        slots = sorted(
            (os.path.join(root, name) for name in os.listdir(root)),
            key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
        )
    except OSError:
        return 0
    removed = 0
    for slot in slots[: max(0, len(slots) - int(keep))]:
        shutil.rmtree(slot, ignore_errors=True)
        removed += 1
    return removed
