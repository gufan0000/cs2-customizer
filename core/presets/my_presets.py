# -*- coding: utf-8 -*-
"""「我的预设」——命名保存/应用/改名/删除（UP-040）。

原状：想换一整套配置，只能「导出到文件」再「导入文件」。用户得自己记住
哪个 .fanpai 文件是"训练场设置"、哪个是"竞技设置"，还得自己管这些文件放哪。
换句话说，软件把**它自己该做的事**（记住几套命名配置）推给了文件系统。

这里在已有的 `export_bundle` / `apply_bundle` 之上加一层薄薄的具名存储：
- 存 `%APPDATA%/FanTool/presets/*.json`，每个预设一个文件；
- **不重新发明序列化**，bundle 格式和分享文件完全一致，
  所以「我的预设」和「导出分享」之间可以互相转换，将来也只有一处要维护；
- 应用走 `apply_bundle()`，于是自动获得两件事：应用前自动快照（可回滚）、
  以及 UP-035 的配置重载广播（已打开的页面会跟着刷新，不会把预设写回旧值）。

文件名与预设名的关系：名字可能含 `/ : *` 等非法字符，也可能重名，
所以磁盘上用 slug + 冲突序号，真实名字存在文件内容的 `name` 字段里。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List

from core.utils.logger import get_logger

from .preset_center import SUPPORTED_TYPES, apply_bundle, export_bundle, validate_bundle

__all__ = [
    "MyPreset",
    "presets_dir",
    "list_presets",
    "save_preset",
    "apply_preset",
    "rename_preset",
    "delete_preset",
    "MAX_NAME_LEN",
]

_logger = get_logger("MyPresets")

MAX_NAME_LEN = 40
_SLUG_RE = re.compile(r"[^0-9A-Za-z一-鿿_-]+")


@dataclass
class MyPreset:
    preset_id: str                     # 磁盘文件名（不含 .json）
    name: str                          # 用户看到的名字
    types: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    file_path: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "preset_id": self.preset_id, "name": self.name, "types": list(self.types),
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


def presets_dir() -> str:
    from config import get_app_data_dir

    return get_app_data_dir("presets")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("_", str(name or "").strip()).strip("_")
    return slug[:MAX_NAME_LEN] or "preset"


def _unique_id(name: str, exclude_id: str = "") -> str:
    base = _slugify(name)
    existing = {p.preset_id for p in list_presets() if p.preset_id != exclude_id}
    if base not in existing:
        return base
    for i in range(2, 1000):
        candidate = f"{base}_{i}"
        if candidate not in existing:
            return candidate
    return f"{base}_{int(time.time())}"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def list_presets() -> List[MyPreset]:
    """按更新时间倒序列出。**坏文件跳过而不是抛异常**——

    一个手工编辑坏了的 json 不该让整个「我的预设」列表打不开。
    """
    directory = presets_dir()
    out: List[MyPreset] = []
    try:
        names = os.listdir(directory)
    except Exception:
        return out
    for filename in names:
        if not filename.lower().endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            bundle = data.get("bundle", {})
            out.append(MyPreset(
                preset_id=os.path.splitext(filename)[0],
                name=str(data.get("name") or os.path.splitext(filename)[0]),
                types=[str(i.get("type", "")) for i in bundle.get("items", []) or []],
                created_at=str(data.get("created_at", "")),
                updated_at=str(data.get("updated_at", "")),
                file_path=path,
            ))
        except Exception:
            _logger.warning(f"[我的预设] 跳过无法解析的文件: {filename}")
    out.sort(key=lambda p: p.updated_at or p.created_at, reverse=True)
    return out


def _write(preset_id: str, name: str, bundle: Dict[str, object], created_at: str = "") -> MyPreset:
    directory = presets_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{preset_id}.json")
    now = _now()
    payload = {
        "name": name,
        "created_at": created_at or now,
        "updated_at": now,
        "bundle": bundle,
    }
    # 原子写：先写临时文件再 replace，中途断电不会留下半个 json
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return MyPreset(
        preset_id=preset_id, name=name,
        types=[str(i.get("type", "")) for i in bundle.get("items", []) or []],
        created_at=payload["created_at"], updated_at=now, file_path=path,
    )


def save_preset(name: str, selected_types: List[str], *, overwrite_id: str = "") -> MyPreset:
    """把当前配置的指定几类存成一个具名预设。

    Args:
        name: 用户起的名字
        selected_types: 要包含哪几类（`preset_center.SUPPORTED_TYPES` 的子集）
        overwrite_id: 传了就覆盖那一条（保留 created_at），否则新建
    """
    clean = str(name or "").strip()
    if not clean:
        raise ValueError("预设名不能为空")
    if len(clean) > MAX_NAME_LEN:
        clean = clean[:MAX_NAME_LEN]

    types = [t for t in (selected_types or []) if t in SUPPORTED_TYPES]
    if not types:
        raise ValueError("至少要选择一类配置")

    bundle = export_bundle(types)
    created_at = ""
    if overwrite_id:
        for item in list_presets():
            if item.preset_id == overwrite_id:
                created_at = item.created_at
                break
        preset_id = overwrite_id
    else:
        preset_id = _unique_id(clean)

    result = _write(preset_id, clean, bundle, created_at=created_at)
    _logger.info(f"[我的预设] 已保存「{clean}」({preset_id})，含 {len(types)} 类")
    return result


def _load_bundle(preset_id: str) -> Dict[str, object]:
    path = os.path.join(presets_dir(), f"{preset_id}.json")
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp).get("bundle", {})


def apply_preset(preset_id: str, mode: str = "merge"):
    """应用一个具名预设。

    走 `apply_bundle()` 而不是自己写配置，于是自动获得：
    应用前自动快照（可回滚）+ UP-035 的配置重载广播（已打开的页面会刷新）。
    """
    bundle = _load_bundle(preset_id)
    validation = validate_bundle(bundle)
    if not validation.ok:
        _logger.error(f"[我的预设] {preset_id} 内容不合法: {validation.errors}")
        from .preset_center import ApplyResult

        return ApplyResult(ok=False, errors=list(validation.errors))
    return apply_bundle(bundle, mode=mode)


def rename_preset(preset_id: str, new_name: str) -> MyPreset:
    """改名。**只改内容里的 name，不动文件名**——

    文件名一旦被别处引用（比如日志里记了 id），改掉会让线索断掉；
    而且重命名文件在 Windows 上还要处理占用，没必要。
    """
    clean = str(new_name or "").strip()
    if not clean:
        raise ValueError("预设名不能为空")
    path = os.path.join(presets_dir(), f"{preset_id}.json")
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    return _write(preset_id, clean[:MAX_NAME_LEN], data.get("bundle", {}),
                  created_at=str(data.get("created_at", "")))


def delete_preset(preset_id: str) -> bool:
    path = os.path.join(presets_dir(), f"{preset_id}.json")
    try:
        os.remove(path)
        _logger.info(f"[我的预设] 已删除 {preset_id}")
        return True
    except FileNotFoundError:
        return False
    except Exception:
        _logger.exception(f"[我的预设] 删除失败 {preset_id}")
        return False
