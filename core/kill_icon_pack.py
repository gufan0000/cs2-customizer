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
   高压缩比的条目能把磁盘塞满（zip 炸弹）。见 `core/archive_safe.iter_safe_members`。
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
from core.io_validation import replace_with_retry
from core.archive_safe import (
    MAX_COMPRESSION_RATIO as _MAX_COMPRESSION_RATIO,
    MAX_ENTRIES as _MAX_ENTRIES,
    MAX_UNCOMPRESSED_BYTES as _MAX_UNCOMPRESSED_BYTES,
    iter_safe_members,
    strip_single_root,
)

logger = get_logger("KillIconPack")

#: 包格式版本。往里加字段不用涨版本；改字段含义才涨。
PACK_VERSION = 1

MANIFEST_NAME = "style.json"

#: 批 117：包作者的授权与说明 —— 导入时留在风格目录里、导出时原样带走。
#: 以前导入只把作者名拼进一次提示、导出三个参数调用点一个都没传 ⇒ 每个经 CS2 Customizer 转手的包都被剥掉署名。
CARRIED_FILES = ("license.txt", "readme.txt")


def _style_dir(resource_manager, style_name) -> str:
    """风格目录 = 等级图集所在的目录（所有资源管理器 / 判据里的替身都有这个取法）。"""
    return os.path.dirname(resource_manager.get_kill_icon_sprite_sheet_paths(style_name, 1)[0])


def read_style_meta(style_name, resource_manager=None) -> dict:
    """风格目录里记着的包元数据（导入时落的）。没有就是空字典。"""
    if resource_manager is None:
        from resource_manager import ResourceManager as resource_manager
    path = os.path.join(_style_dir(resource_manager, style_name), MANIFEST_NAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _keep_pack_meta(style_dir, probe, temp_root):
    """把作者 / 版本 / 说明和随包文件留进风格目录。失败不影响导入本身。"""
    try:
        meta = {"pack_version": PACK_VERSION, "name": probe.name, "author": probe.author,
                "version": probe.version, "description": probe.description}
        with open(os.path.join(style_dir, MANIFEST_NAME), "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2, ensure_ascii=False)
        for relative in probe.carried:
            shutil.copyfile(os.path.join(temp_root, relative), os.path.join(style_dir, relative.lower()))
    except OSError as exc:
        logger.warning(f"图标包元数据没留下来（不影响导入）：{exc}")


#: 包里的等级条目：`3.png` / `3.json` / `3hs.png` / `3hs.json`。
LEVEL_ENTRY_RE = re.compile(r"^([1-5])(hs)?\.(png|json)$", re.IGNORECASE)


# ---- 外来 zip 的三条护栏：实现在 `core/archive_safe.py`（2026-09-16 提升上去的）----
#
#: ⭐ 搬走的理由：同一套护栏原来有三份（这里 / `presets/share_file.py` / 社区站
#:   `pack_validate.php`），而资源导入统一化要第四个调用点。
#: ⚠ 行为**零变化**：异常类型（`KillIconImportError`）与消息措辞（"图标包"）
#:   都是调用时传进去的，判据 `test_kill_icon_pack_ki4.py` 一条没改。
#: ⚠ 三个上限的值也一字未动 —— `MAX_ENTRIES` 那个数是拿真实素材换来的
#:   （默认风格 519 帧导出 520 条目，上限原本 400，我们自己的包自己装不回来）。
MAX_ENTRIES = _MAX_ENTRIES
MAX_UNCOMPRESSED_BYTES = _MAX_UNCOMPRESSED_BYTES
MAX_COMPRESSION_RATIO = _MAX_COMPRESSION_RATIO


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
    #: 根上的随包文件（包作者的授权 / 说明），包内路径
    carried: list = field(default_factory=list)

    @property
    def loose(self) -> bool:
        return not self.levels and bool(self.loose_items)

    @property
    def usable(self) -> bool:
        return bool(self.levels or self.loose_items)


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
        members = list(iter_safe_members(archive, KillIconImportError, "图标包"))
        probe.entry_count = len(members)
        probe.total_bytes = sum(int(info.file_size or 0) for info, _ in members)
        paths = [relative for _info, relative in members]
        stripped, root = strip_single_root(paths)
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
        probe.carried = [p for p in stripped if "/" not in p and p.lower() in CARRIED_FILES]

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
            members = list(iter_safe_members(archive, KillIconImportError, "图标包"))
            paths = [relative for _info, relative in members]
            stripped, _root = strip_single_root(paths)
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
        style_dir = _style_dir(resource_manager, style)
        if imported and os.path.isdir(style_dir):
            _keep_pack_meta(style_dir, probe, temp_root)
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


def export_pack(style_name, output_path, author=None, description=None,
                version=None, resource_manager=None, progress=None):
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

    # 批 117：没显式给的就用导入时记下的 —— 转手不剥署名
    kept = read_style_meta(style_name, resource_manager)
    manifest = {
        "pack_version": PACK_VERSION,
        "name": str(style_name),
        "author": str(kept.get("author", "") if author is None else author),
        "version": str((kept.get("version") if version is None else version) or "1.0"),
        "description": str(kept.get("description", "") if description is None else description),
        "levels": [f"{e.kills}{e.variant}" for e in entries],
    }
    style_dir = _style_dir(resource_manager, style_name)
    carried = [n for n in CARRIED_FILES if os.path.isfile(os.path.join(style_dir, n))]

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
            for name in carried:
                archive.write(os.path.join(style_dir, name), name)
        # 批 117：写完先重开校验一遍，坏了就不替换 —— 旧文件原样留着，别让用户拿到一个坏包
        with zipfile.ZipFile(temp_path) as check:
            bad = check.testzip()
        if bad is not None:
            raise KillIconImportError(f"打出来的包校验不过（{bad} 损坏），已放弃，原文件没动。")
        replace_with_retry(temp_path, output_path)
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
