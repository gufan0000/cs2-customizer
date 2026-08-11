# -*- coding: utf-8 -*-
"""`.cs2customizer` 配置分享文件(R2-1,2026-06-12)。

容器 = zip(manifest.json + bundle.json [+ 未来的 resources/])。
v1 只读取两个 json,zip 里任何其它内容一律忽略——但解析前仍执行全部安全红线:

  红线1  总大小上限(压缩前 200MB / 压缩包 50MB)——拒绝 zip 炸弹
  红线2  文件数上限(256)
  红线3  路径穿越拒绝(绝对路径 / `..` / 盘符)
  红线4  扩展名白名单(json/wav/mp3/ogg/png/jpg/jpeg/gif)——可执行体进不来
  红线5  bundle 必须通过 preset_center.validate_bundle 才允许 apply

导入应用前由 preset_center 自动建配置快照,可一键回滚。
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import VERSION

from .preset_center import SCHEMA_VERSION, validate_bundle

SHARE_EXT = ".cs2c"
#: 前身（闭源版）导出的分享文件用 `.fanpai`。**只在打开对话框的过滤器里认它**——
#: 容器格式与安检逻辑完全一致，没有理由让用户手工改扩展名才能导入；
#: 但导出一律写新扩展名，不再产生旧后缀的文件。
LEGACY_SHARE_EXTS = (".fanpai",)
MANIFEST_NAME = "manifest.json"
BUNDLE_NAME = "bundle.json"

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024        # 压缩包本体
MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024  # 解压总量(防 zip 炸弹)
MAX_ENTRIES = 256
ALLOWED_EXTS = {".json", ".wav", ".mp3", ".ogg", ".png", ".jpg", ".jpeg", ".gif"}


@dataclass
class ShareReadResult:
    ok: bool
    bundle: Optional[Dict] = None
    manifest: Optional[Dict] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _entry_is_unsafe(name: str) -> Optional[str]:
    """返回不安全原因;None=安全。"""
    norm = name.replace("\\", "/")
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return f"绝对路径: {name}"
    parts = norm.split("/")
    if ".." in parts:
        return f"路径穿越: {name}"
    if norm.endswith("/"):
        return None  # 目录项
    ext = os.path.splitext(norm)[1].lower()
    if ext not in ALLOWED_EXTS:
        return f"扩展名不允许: {name}"
    return None


def write_share_file(path: str, bundle: Dict, title: str = "", author: str = "") -> None:
    """写 .cs2customizer 文件。bundle 需是 export_bundle 的产物。"""
    manifest = {
        "format": "cs2customizer_share",
        "schema_version": SCHEMA_VERSION,
        "app_version": VERSION,
        "created_at": int(time.time()),
        "title": str(title or "")[:80],
        "author": str(author or "")[:40],
        "types": [item.get("type") for item in bundle.get("items", [])],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=1))
        zf.writestr(BUNDLE_NAME, json.dumps(bundle, ensure_ascii=False, indent=1))


def read_share_file(path: str) -> ShareReadResult:
    """读取并全量安检 .cs2customizer;返回 bundle(尚未应用)。"""
    warnings: List[str] = []
    try:
        if os.path.getsize(path) > MAX_ARCHIVE_BYTES:
            return ShareReadResult(ok=False, errors=["文件超过 50MB 上限"])
    except OSError as exc:
        return ShareReadResult(ok=False, errors=[f"无法读取文件: {exc}"])

    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                return ShareReadResult(ok=False, errors=[f"条目数超限({len(infos)}>{MAX_ENTRIES})"])
            total = 0
            for info in infos:
                total += max(0, info.file_size)
                reason = _entry_is_unsafe(info.filename)
                if reason:
                    return ShareReadResult(ok=False, errors=[f"不安全条目,已拒绝: {reason}"])
            if total > MAX_TOTAL_UNCOMPRESSED:
                return ShareReadResult(ok=False, errors=["解压总量超过 200MB 上限"])

            names = {i.filename for i in infos}
            if BUNDLE_NAME not in names:
                return ShareReadResult(ok=False, errors=["缺少 bundle.json,不是有效的分享文件"])

            manifest = None
            if MANIFEST_NAME in names:
                try:
                    manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
                except Exception:
                    warnings.append("manifest 损坏,已忽略")
            try:
                bundle = json.loads(zf.read(BUNDLE_NAME).decode("utf-8"))
            except Exception as exc:
                return ShareReadResult(ok=False, errors=[f"bundle.json 解析失败: {exc}"])
    except zipfile.BadZipFile:
        return ShareReadResult(ok=False, errors=["不是有效的 .cs2customizer(zip)文件"])
    except OSError as exc:
        return ShareReadResult(ok=False, errors=[f"读取失败: {exc}"])

    validation = validate_bundle(bundle)
    if not validation.ok:
        return ShareReadResult(ok=False, errors=["内容校验失败: " + "; ".join(validation.errors)], warnings=warnings)
    warnings.extend(validation.warnings)
    return ShareReadResult(ok=True, bundle=bundle, manifest=manifest, warnings=warnings)


def describe(result: ShareReadResult) -> str:
    """给导入确认框的人话描述。"""
    if not result.ok or result.bundle is None:
        return "(无效文件)"
    type_names = {
        "hud_rules": "HUD 颜色规则", "screen_effects": "屏幕特效", "special_sound": "特殊音效",
        "crosshair": "准心", "flash": "自定闪光", "viewmodel": "局内视角", "magnifier": "开镜放大",
    }
    items = result.bundle.get("items", [])
    lines = [f"· {type_names.get(i.get('type'), i.get('type'))}" for i in items]
    meta = result.manifest or {}
    head = []
    if meta.get("title"):
        head.append(f"标题: {meta['title']}")
    if meta.get("author"):
        head.append(f"作者: {meta['author']}")
    if meta.get("app_version"):
        head.append(f"来自版本: {meta['app_version']}")
    return "\n".join(head + [f"包含 {len(items)} 类配置:"] + lines)
