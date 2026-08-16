# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""CS2 Customizer 击杀图标包：一个 zip = 一整套风格（KI-4b）。

**分发单位是"风格"而不是"单个等级"**，这是这个模块存在的全部理由。
社区素材九成是打包发的，KI-4b 之前用户拿到一个 zip 要：自己解压、自己
猜哪个文件是几杀、一个等级一个等级地导五次。

包长这样：

    我的图标包.zip
    ├── style.json          # 名字 / 作者 / 版本 / 说明 / 预览图
    ├── preview.png         # 可选
    ├── 1.png  1.json       # 就是运行时格式本身，导入 = 校验 + 落库
    ├── 2.png  2.json
    ├── 3.png  3.json  3hs.png  3hs.json     # 爆头变体
    └── ...

三个刻意的决定：

1. **包内就是运行时格式**，所以导入不重新编码、不掉画质，导出就是反过来
   打一次包。`style.json` 缺了也照装（拿 zip 文件名当风格名）——规范是给
   分发者用的，不该变成用户的门槛。
2. **松散包也认**：里面是一堆 `1.gif`…`5.gif` 或 `1/ 2/ 3/` 目录时，
   解到临时目录后走正常导入管线。用户从网盘下下来的多半是这种。
3. **解压前逐条校验**。zip 是外来数据，`extractall` 直接对着用户磁盘写
   是不能接受的：`../../` 的条目会写到资源目录外面（zip-slip），
   高压缩比的条目能把磁盘塞满（zip 炸弹）。见 `_iter_safe_members`。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field

from core.kill_icon_import import (
    KillIconImportCancelled,
    KillIconImportError,
    convert_to_style,
    parse_level_name,
)
from core.utils.logger import get_logger

logger = get_logger("KillIconPack")

#: 包格式版本。往里加字段不用涨版本；改字段含义才涨。
PACK_VERSION = 1

MANIFEST_NAME = "style.json"

#: 包里的等级条目：`3.png` / `3.json` / `3hs.png` / `3hs.json`。
LEVEL_ENTRY_RE = re.compile(r"^([1-5])(hs)?\.(png|json)$", re.IGNORECASE)

#: 允许出现在包根上的附加文件。
EXTRA_ENTRIES = ("style.json", "preview.png", "readme.txt", "readme.md", "license.txt")

# ---- 以下三条是"外来 zip"的护栏，别为了兼容某个包把它们放宽 ----

#: 条目数上限。
#:
#: 我们自己导出的包永远是 5 个等级 ×2 个文件 + 几个附加文件（十几条），
#: 但**别人的松散包**可以是"每个等级一个帧序列目录"，那就是
#: 5 个等级 × `MAX_FRAMES`(600) 帧。这个数按后者定。
#:
#: ⚠ 这条上限一开始定成 400，结果是**我们自己导出的包自己装不回来**：
#: 用户的默认风格是 519 帧的逐帧目录，导出来 520 个条目，一导入就被这条挡了。
#: 拿真实素材跑一次往返才发现——判据里用的都是 3 帧的小样本。
MAX_ENTRIES = 3200

#: 解压后总字节上限。默认风格 519 帧 350x250 打成图集也就几十 MB。
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

#: 单条目压缩比上限。压缩比几千倍的条目只可能是刻意构造的。
MAX_COMPRESSION_RATIO = 500


@dataclass
class PackProbe:
    """看一眼这个 zip 是什么。不写任何文件。"""

    path: str
    name: str = ""
    author: str = ""
    version: str = ""
    description: str = ""
    #: 标准包：`[(kills, variant), ...]`
    levels: list = field(default_factory=list)
    #: 松散包：`[(kills, variant, 包内路径), ...]`
    loose_items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    entry_count: int = 0
    total_bytes: int = 0

    @property
    def loose(self) -> bool:
        return not self.levels and bool(self.loose_items)

    @property
    def usable(self) -> bool:
        return bool(self.levels or self.loose_items)


def _safe_relpath(name):
    """把 zip 里的条目名归一成一个**保证落在解压根之内**的相对路径。

    拒绝：绝对路径、盘符、任何 `..` 段。返回 None 表示这条不能要。
    """
    raw = str(name or "").replace("\\", "/")
    if not raw or raw.endswith("/"):
        return None
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    return "/".join(parts) if parts else None


def _iter_safe_members(archive):
    """逐条产出 `(info, 安全相对路径)`，同时把总量卡住。

    ⚠ 不许换成 `ZipFile.extractall`：它对 zip-slip 只有部分防护（依赖 Python
    版本），对总大小和压缩比完全不管。zip 是从网上下下来的外来数据。
    """
    total = 0
    count = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        relative = _safe_relpath(info.filename)
        if relative is None:
            raise KillIconImportError(
                f"这个 zip 里有一条不安全的路径：{info.filename}。为安全起见整个包都不导入。"
            )
        count += 1
        if count > MAX_ENTRIES:
            raise KillIconImportError(
                f"这个 zip 里的文件超过 {MAX_ENTRIES} 个，不像是一个图标包。"
            )
        size = int(getattr(info, "file_size", 0) or 0)
        compressed = max(1, int(getattr(info, "compress_size", 0) or 0))
        if size / compressed > MAX_COMPRESSION_RATIO:
            raise KillIconImportError(
                f"这个 zip 里有异常高压缩比的条目（{info.filename}），已拒绝解压。"
            )
        total += size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise KillIconImportError(
                f"这个 zip 解压后超过 "
                f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB，不像是一个图标包。"
            )
        yield info, relative


def _strip_single_root(entries):
    """很多包解出来是 `包名/1.png`。把这层统一的外壳剥掉。"""
    roots = {path.split("/")[0] for path in entries if "/" in path}
    if len(roots) != 1 or any("/" not in path for path in entries):
        return entries, ""
    root = roots.pop()
    return [path[len(root) + 1:] for path in entries], root


def probe_pack(zip_path):
    """看包里有什么。**只读，不解压到磁盘。**"""
    zip_path = str(zip_path)
    if not os.path.isfile(zip_path):
        raise KillIconImportError(f"找不到这个文件：{zip_path}")
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise KillIconImportError(
            f"这个 zip 打不开：{os.path.basename(zip_path)}（{exc}）"
        ) from exc

    probe = PackProbe(path=zip_path)
    with archive:
        members = list(_iter_safe_members(archive))
        probe.entry_count = len(members)
        probe.total_bytes = sum(int(info.file_size or 0) for info, _ in members)
        paths = [relative for _info, relative in members]
        stripped, root = _strip_single_root(paths)
        lookup = dict(zip(stripped, paths))

        manifest = {}
        if MANIFEST_NAME in lookup:
            try:
                with archive.open(lookup[MANIFEST_NAME]) as handle:
                    loaded = json.loads(handle.read().decode("utf-8"))
                manifest = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError, UnicodeDecodeError) as exc:
                probe.warnings.append(f"{MANIFEST_NAME} 读不出来，已忽略（{exc}）。")

        probe.name = str(manifest.get("name") or root or
                         os.path.splitext(os.path.basename(zip_path))[0]).strip()
        probe.author = str(manifest.get("author") or "").strip()
        probe.version = str(manifest.get("version") or "").strip()
        probe.description = str(manifest.get("description") or "").strip()

        # 标准包：根上成对的 <等级>.png + <等级>.json
        pairs = {}
        for path in stripped:
            if "/" in path:
                continue
            match = LEVEL_ENTRY_RE.match(path)
            if not match:
                continue
            key = (int(match.group(1)), (match.group(2) or "").lower())
            pairs.setdefault(key, set()).add(match.group(3).lower())
        probe.levels = sorted(key for key, kinds in pairs.items()
                              if {"png", "json"} <= kinds)

        incomplete = sorted(key for key, kinds in pairs.items()
                            if {"png", "json"} > kinds)
        if incomplete:
            probe.warnings.append(
                "这些等级只有半套文件（缺 .png 或 .json），会被跳过："
                + "、".join(f"{k}{v}" for k, v in incomplete)
            )

        if not probe.levels:
            probe.loose_items = _collect_loose_items(stripped)
            if not probe.loose_items:
                probe.warnings.append(
                    "包里没找到能认出来的等级素材。"
                    "文件或文件夹请按 1~5 命名（也认 ace / 三杀 这类写法）。"
                )
    return probe


def _collect_loose_items(paths):
    """松散包：`1.gif`、`ace.webp`、`3/` 这种。返回 `[(kills, variant, 路径)]`。

    同一个等级有多个候选时的优先级：**JSON（带元数据）→ 图片 → 目录**。
    定死这个顺序是为了让同一个包每次导入的结果一样——按 zip 里的条目顺序
    "先到先得"会让结果取决于打包工具，用户看到的表现是"同一个包导两次
    出来的东西不一样"。
    """
    candidates = {}
    for path in paths:
        head = path.split("/")[0]
        parsed = parse_level_name(head)
        if not parsed:
            continue
        if "/" in path:
            # 目录里的条目统一记成"这个目录"，帧序列整个交给导入管线
            rank, value = 2, head
        elif path.lower().endswith(".json"):
            rank, value = 0, path
        else:
            rank, value = 1, path
        current = candidates.get(parsed)
        if current is None or rank < current[0]:
            candidates[parsed] = (rank, value)
    return sorted((kills, variant, value)
                  for (kills, variant), (_rank, value) in candidates.items())


def import_pack(zip_path, style_name=None, resource_manager=None,
                progress=None, cancel=None, overwrite=True):
    """把一个 zip 图标包装进风格库。返回结果字典。

    `style_name=None` 时用包里 `style.json` 的名字，再退到 zip 文件名。
    """
    if resource_manager is None:
        from resource_manager import ResourceManager as resource_manager

    probe = probe_pack(zip_path)
    if not probe.usable:
        raise KillIconImportError(
            f"{os.path.basename(str(zip_path))} 里没有可用的击杀图标素材。\n"
            f"图标包应当在根目录放 1.png/1.json … 5.png/5.json，"
            f"或者按 1~5 命名的图片 / 文件夹。"
        )

    style = _sanitize_style_name(style_name or probe.name)
    warnings = list(probe.warnings)
    imported = []
    failed = []

    temp_root = tempfile.mkdtemp(prefix="cs2customizer_kipack_")
    try:
        with zipfile.ZipFile(str(zip_path)) as archive:
            members = list(_iter_safe_members(archive))
            paths = [relative for _info, relative in members]
            stripped, _root = _strip_single_root(paths)
            total = max(1, len(members))
            for index, ((info, relative), target_rel) in enumerate(
                    zip(members, stripped)):
                if cancel is not None and cancel():
                    raise KillIconImportCancelled()
                target = os.path.join(temp_root, target_rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                if progress is not None:
                    try:
                        progress(index + 1, total, "解压")
                    except Exception:
                        pass

        if probe.levels:
            for kills, variant in probe.levels:
                source_json = os.path.join(temp_root, f"{kills}{variant}.json")
                try:
                    result = convert_to_style(
                        source_json, style, kills, variant=variant,
                        resource_manager=resource_manager,
                    )
                    imported.append(result)
                    warnings.extend(result.get("warnings", []))
                except KillIconImportError as exc:
                    failed.append(f"{kills}{variant}（{exc}）")
        else:
            for kills, variant, relative in probe.loose_items:
                source = os.path.join(temp_root, relative.replace("/", os.sep))
                try:
                    result = convert_to_style(
                        source, style, kills, variant=variant,
                        resource_manager=resource_manager,
                    )
                    imported.append(result)
                    warnings.extend(result.get("warnings", []))
                except KillIconImportError as exc:
                    failed.append(f"{os.path.basename(relative)}（{exc}）")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    if not imported:
        raise KillIconImportError(
            "这个包里的素材一个都没导进去。\n" + "\n".join(failed[:5])
        )

    logger.info(
        f"导入图标包: {os.path.basename(str(zip_path))} → 风格「{style}」"
        f"（{len(imported)} 个等级，失败 {len(failed)} 个）"
    )
    return {
        "style": style,
        "name": probe.name,
        "author": probe.author,
        "version": probe.version,
        "imported": imported,
        "levels": sorted({(r["kills"], r["variant"]) for r in imported}),
        "failed": failed,
        "warnings": warnings,
        "loose": probe.loose,
    }


def _sanitize_style_name(name):
    """包里的名字会**直接当目录名用**，先洗一遍。"""
    cleaned = str(name or "").strip()
    for bad in ('\\', '/', ':', '*', '?', '"', '<', '>', '|', '\0'):
        cleaned = cleaned.replace(bad, "")
    cleaned = cleaned.replace("..", "").strip(" .")
    if not cleaned:
        raise KillIconImportError("这个包没有可用的风格名，请在导入时自己填一个。")
    return cleaned[:64]


# ==================================================== 导出


def export_pack(style_name, output_path, author="", description="",
                version="1.0", resource_manager=None, progress=None):
    """把一套风格打成 zip。

    导出的**永远是运行时格式**（图集 + JSON），逐帧目录的老素材会在这里先
    转成图集再打包。三个理由：

    1. 对方导入时不需要再转一次码，也就不会掉画质；
    2. 包里条目数恒定（每个等级两个文件），不会因为素材帧多就撞上
       `MAX_ENTRIES`——真实的默认风格是 519 帧，原样打进去就是 520 个条目；
    3. 同一套风格无论是新格式还是老格式导出来，包的结构都一样。
    """
    from core.kill_icon_library import list_style_levels

    if resource_manager is None:
        from resource_manager import ResourceManager as resource_manager

    entries = [e for e in list_style_levels(style_name, resource_manager) if e.exists]
    if not entries:
        raise KillIconImportError(f"风格「{style_name}」里没有素材，没什么可导出的。")

    output_path = str(output_path)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    manifest = {
        "pack_version": PACK_VERSION,
        "name": str(style_name),
        "author": str(author or ""),
        "version": str(version or "1.0"),
        "description": str(description or ""),
        "levels": [f"{e.kills}{e.variant}" for e in entries],
    }

    handle, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(output_path)), suffix=".tmp")
    os.close(handle)
    staging = tempfile.mkdtemp(prefix="cs2customizer_kiexport_")
    written = []
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME,
                             json.dumps(manifest, indent=2, ensure_ascii=False))
            for index, entry in enumerate(entries):
                name = f"{entry.kills}{entry.variant}"
                if entry.kind == "sheet":
                    sprite_path, json_path = entry.sprite_path, entry.json_path
                else:
                    sprite_path = os.path.join(staging, f"{name}.png")
                    json_path = os.path.join(staging, f"{name}.json")
                    convert_to_style(entry.legacy_dir, style_name, entry.kills,
                                     variant=entry.variant,
                                     resource_manager=resource_manager,
                                     output_paths=(sprite_path, json_path))
                archive.write(sprite_path, f"{name}.png")
                archive.write(json_path, f"{name}.json")
                written.append(name)
                if progress is not None:
                    try:
                        progress(index + 1, len(entries), "打包")
                    except Exception:
                        pass
        os.replace(temp_path, output_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    logger.info(f"导出图标包: 风格「{style_name}」→ {output_path}（{len(written)} 个等级）")
    return {
        "style": str(style_name),
        "path": output_path,
        "levels": written,
        "size": os.path.getsize(output_path),
    }
