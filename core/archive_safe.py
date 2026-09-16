# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""外来压缩包的安全解压护栏（2026-09-16，资源导入统一化）。

同一套护栏**原来有三份**：`kill_icon_pack`（实现从这里提升上来）、
`presets/share_file`、社区站 `pack_validate.php`（与桌面端逐字镜像）。
资源导入要第四个调用点 ⇒ 收成一份，别让四份各自漂。全套设计见 `docs/资源导入_设计方案_v1_20260916.md`。

⚠ `share_file` 那份**不收编**：它的上限更严（256 条目 / 200MB）且带扩展名白名单。
⭐ **护栏合并只能朝严的方向** —— 让某一处变松的"统一"不是重构，是降级。

⭐ 调用方传自己的 `error` 与 `what`，所以异常类型与措辞原样保留
（判据钉的正是这两样）⇒ 行为零变化。
⛔ 不许换成 `extractall`：它对 zip-slip 只有部分防护，对总大小和压缩比完全不管。
"""
from __future__ import annotations

import re
import zipfile
from typing import Iterator, Sequence, Tuple


class ArchiveError(Exception):
    """压缩包不能安全处理。调用方可以传自己的异常类顶掉它。"""


#: 三条上限的值与 `kill_icon_pack` 原值**逐字相同**，别在这里"顺手收紧"——
#: `MAX_ENTRIES` 那个数是拿真实素材换来的（默认风格 519 帧逐帧目录导出 520 个条目，
#: 上限原本定 400，结果是**我们自己导出的包自己装不回来**）。
MAX_ENTRIES = 3200
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 500

#: 文件头魔数。⭐ 这张表的用处不是"支持"这些格式，是**认出来之后说人话**：
#: 用户把 `.rar` 改名成 `.zip` 拖进来时，「这不是一个 zip」远不如
#: 「这是 RAR，请先解压」有用。站端 `pack_validate.php:252-261` 同款做法。
_MAGIC = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),      # 空 zip
    (b"PK\x07\x08", "zip"),      # 分卷
    (b"Rar!\x1a\x07", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"\x1f\x8b", "gzip"),
    (b"MZ", "exe"),
)

#: 认得出、但**打不开**的格式 ⇒ 给一句能照着做的话。
UNSUPPORTED_HINTS = {
    "rar": "这是 RAR 压缩包，软件打不开。请先用解压软件解开，再把解出来的文件夹拖进来。",
    "7z": "这是 7z 压缩包，软件打不开。请先用解压软件解开，再把解出来的文件夹拖进来。",
    "exe": "这是一个可执行文件，不是资源包。软件不会运行它。",
}


def sniff_archive_kind(path: str) -> str:
    """按**文件头**认格式，不看扩展名。

    ⭐ 不看扩展名是要点：改名的 RAR 是最常见的一种"这包怎么装不进去"。
    返回 `zip` / `rar` / `7z` / `gzip` / `exe` / `unknown`；读不了返回 `unknown`。
    """
    try:
        with open(str(path), "rb") as handle:
            head = handle.read(8)
    except OSError:
        return "unknown"
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    return "unknown"


def safe_relpath(name: str):
    """把包内条目名归一成一个**保证落在解压根之内**的相对路径。

    拒绝：绝对路径、盘符、任何 `..` 段。返回 None 表示这一条不能要。
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


def iter_safe_members(
    archive: zipfile.ZipFile,
    error: type = ArchiveError,
    what: str = "资源包",
) -> Iterator[Tuple[zipfile.ZipInfo, str]]:
    """逐条产出 `(info, 安全相对路径)`，同时把总量卡住。

    `error` / `what` 让调用方保住自己的异常类型与措辞（判据钉着它们）。
    """
    total = 0
    count = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        relative = safe_relpath(info.filename)
        if relative is None:
            raise error(
                f"这个 zip 里有一条不安全的路径：{info.filename}。为安全起见整个包都不导入。"
            )
        count += 1
        if count > MAX_ENTRIES:
            raise error(f"这个 zip 里的文件超过 {MAX_ENTRIES} 个，不像是一个{what}。")
        size = int(getattr(info, "file_size", 0) or 0)
        compressed = max(1, int(getattr(info, "compress_size", 0) or 0))
        if size / compressed > MAX_COMPRESSION_RATIO:
            raise error(f"这个 zip 里有异常高压缩比的条目（{info.filename}），已拒绝解压。")
        total += size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise error(
                f"这个 zip 解压后超过 "
                f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB，不像是一个{what}。"
            )
        yield info, relative


def strip_single_root(entries: Sequence[str]):
    """很多包解出来是 `包名/1.png`。把这层统一的外壳剥掉。

    ⚠ **只剥"单层且所有文件都在里面"**的那一种。站端
    `pack_validate.php:194-205` 是同一条规则——两边对"外壳"的定义必须一致，
    否则同一个包在站里通过、装进来却是另一个形状。
    """
    entries = list(entries)
    roots = {path.split("/")[0] for path in entries if "/" in path}
    if len(roots) != 1 or any("/" not in path for path in entries):
        return entries, ""
    root = roots.pop()
    return [path[len(root) + 1:] for path in entries], root
