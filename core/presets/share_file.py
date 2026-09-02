# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
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

#: 还要额外认的**旧**扩展名。本仓是自己那个后缀的第一手主人，所以这里是空元组；
#: 开源子集把它填成前身那个后缀 —— **只在「打开」这一侧认，导出一律写新的**。
#: ⚠ 这一行存在的理由是**让两个仓的差异收进一个常量**：
#:   在此之前那条差异是一个打在页面文件上的语义补丁，而批 40 把它锚着的那个方法
#:   整个改掉了 ⇒ 补丁当场失效、同步流水线会停住。
#:   ⭐ **能收进常量的差异，就不要留成补丁** —— 补丁锚在代码的形状上，
#:     而代码的形状每一批都在变；常量锚在意图上。
#: ⚠⚠ 这两行**必须紧挨着**：语义补丁在机械改名**之后**才应用，
#:   两行之间夹一段会被改名规则改写的注释，补丁的上下文就对不上了（实测踩过）。
SHARE_EXT = ".cs2c"
LEGACY_SHARE_EXTS: tuple = (".fanpai",)
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
    # ⭐⭐ 批 40：这里原来自带一份 `type_names`，写「HUD **颜色规则**」，
    #   而页面上的勾选框写「HUD 规则」——**同一类东西两个名字，隔着一个仓库**。
    #   批 38 刚在这一页上统一过一次同物两名，**这一份躲过了那一轮**：
    #   它只出现在**按下按钮之后**才弹出来的确认框里，任何一张截图都拍不到它。
    # ⇒ 名字与摘要都走 `preset_center` 那一份唯一真源。
    from .preset_center import describe_bundle

    described = describe_bundle(result.bundle)
    items = result.bundle.get("items", [])
    lines = [f"· {label}：{detail}" for label, detail in described]
    # ⚠⚠ RN-490（批 40 补刀）：这里原来直接 `result.manifest.get(...)`，
    #   而 `manifest.json` 只要是「合法 JSON 但**不是对象**」（数组 / 字符串 / 数字），
    #   `.get` 就抛 AttributeError —— 而这条异常从 `describe()` →
    #   `_read_config_file()` → `_import_config_path()` **一路裸奔**
    #   （AST 实证：两个调用点都没有 try）。
    # ⭐ 用户点了「打开一份配置文件」，然后**什么都不会发生** ——
    #   连一个错误框都没有。⭐⭐ 比崩溃更糟的是静默：崩溃至少说了话。
    # ⇒ manifest 只是"附言"，它坏了不该让整份文件读不成；
    #   坏了就当没有附言，正文照常显示。
    meta = result.manifest if isinstance(result.manifest, dict) else {}
    head = []
    if meta.get("title"):
        head.append(f"标题: {meta['title']}")
    if meta.get("author"):
        head.append(f"作者: {meta['author']}")
    if meta.get("app_version"):
        head.append(f"来自版本: {meta['app_version']}")
    return "\n".join(head + [f"包含 {len(items)} 类配置:"] + lines)
