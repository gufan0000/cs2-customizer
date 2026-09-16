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
import struct
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

#: 打包格式（**能不能打开是另一回事**）。给调用方措辞用：
#: 「拖进来的是压缩包」对 rar 也成立，只是接下来会被 `UNSUPPORTED_HINTS` 挡掉。
#: ⭐ 放在这里是因为**格式名字只在 `_MAGIC` 里定义过一次** ——
#:   谁要判"这是不是个包"，都不该在自己那头重抄一份名单。
ARCHIVE_KINDS = frozenset({"zip", "rar", "7z", "gzip"})

#: 认得出、但**打不开**的格式 ⇒ 给一句能照着做的话。
UNSUPPORTED_HINTS = {
    "rar": "这是 RAR 压缩包，软件打不开。请先用解压软件解开，再把解出来的文件夹拖进来。",
    "7z": "这是 7z 压缩包，软件打不开。请先用解压软件解开，再把解出来的文件夹拖进来。",
    # ⭐⭐ 2026-09-16 补：gzip 原本**认得出却没有这一条** —— 于是
    #   `open_source` 的 `kind in UNSUPPORTED_HINTS` 不成立、`kind == "zip"` 也不成立，
    #   它一路掉到最后那句 `_open_single_file`，被当成"一个素材文件"收下来。
    #   实测：`枪声包.tar.gz` 原样落进 `audio/…/枪声包.tar.gz`。
    # ⇒ **装得进去、永远不会响**，而这正是这个功能最该防的那一类失败。
    #   根因不是漏了一行文案，是这张表和分发的 if 链**各自列举、谁也不管谁**：
    #   `_MAGIC` 多认一种格式，分发那头就多一条静默的落法。
    "gzip": "这是 tar.gz / gz 压缩包，软件打不开。请先用解压软件解开，再把解出来的文件夹拖进来。",
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


#: 操作系统自己塞进包里的东西。⭐ 它们**不是任何人的内容** ——
#: 没有哪个用户"打算"把 `Thumbs.db` 导进资源库，所以这一类直接丢掉、不必问。
_JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_JUNK_DIRS = ("__macosx",)


def is_system_junk(name: str) -> bool:
    """这一条是不是操作系统塞进来的垃圾。

    ⭐⭐ 为什么这件事值一个函数：实测同一包素材，加上四样**现实里躲不开**的杂物
    （Mac 打包必带的 `__MACOSX/._*`、看过一眼图片目录就有的 `Thumbs.db`、
    作者自己放的 `说明.txt` 和 `封面.jpg`），**要问用户的次数从 0 涨到 4** ——
    因为混进非音频扩展名会让那一组的形状变成 `mixed`，识别器当场降到"拿不准"。
    ⇒ 用户的验收标准是"问了几次"，而杂物是最便宜的一条。

    ⚠ 只认**确定是系统产物**的那几样。作者自己放的说明与封面不在这里
    （那是他的内容，该单独告诉用户"没导入"，而不是当垃圾悄悄扔掉）。
    """
    parts = [p for p in str(name or "").replace("\\", "/").split("/") if p]
    if not parts:
        return True
    if any(part.lower() in _JUNK_DIRS for part in parts):
        return True
    leaf = parts[-1]
    if leaf.lower() in _JUNK_NAMES:
        return True
    # AppleDouble：Mac 给每个文件配的那份 `._同名` 元数据。
    return leaf.startswith("._")


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


#: 按这个顺序试着把 CP437 那串还原回中文。⚠ 顺序有讲究：
#: GBK 是简体中文 Windows 的默认页，放第一个；后面两个是繁中 / 日文。
_FALLBACK_ENCODINGS = ("gbk", "big5", "cp932")

#: Info-ZIP 的 Unicode Path 扩展字段。7-Zip / WinRAR 写包时会带上它，
#: 而 Python 的 `zipfile` **不解析它** —— 于是连正确记录了 UTF-8 名字的包
#: 也一样会乱码。项目既有经验逐字写过「判乱码必须看 0x7075 扩展字段」。
_UNICODE_PATH_HEADER = 0x7075


def _unicode_path_from_extra(info) -> str:
    """从 0x7075 扩展字段里取真正的 UTF-8 名字；没有就返回空串。"""
    data = bytes(getattr(info, "extra", b"") or b"")
    offset = 0
    while offset + 4 <= len(data):
        header, size = struct.unpack_from("<HH", data, offset)
        body = data[offset + 4:offset + 4 + size]
        offset += 4 + size
        if header != _UNICODE_PATH_HEADER or len(body) < 5:
            continue
        if body[0] != 1:                     # version，只认 1
            continue
        try:
            return body[5:].decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return ""


def decode_member_name(info) -> str:
    """把 zip 条目名还原成人看得懂的字符串。

    ⭐⭐⭐ 为什么必须有这一步：中文用户用 Windows 右键「发送到 → 压缩(zipped)
    文件夹」打的包，文件名按 **GBK** 存且**不置 0x0800 标志位**；
    Python 的 `zipfile` 对没有该标志位的名字一律按 **CP437** 解 ⇒
    `清脆/1.mp3` 变成 `╟σ┤α/1.mp3`。
    实测：这串乱码一路穿过剥壳、识别、归类，**在用户的资源目录里建出一个
    叫 `╟σ┤α` 的风格目录**，设置页的下拉框里就显示这串乱码，而导入报「成功 3」。

    ⚠ 更狠的一支：GBK 尾字节正好是 `0x5C` 的那些汉字（`乗` `俓` `僜` … 基本区
    里有一百多个），CP437 解出来带一个 `\\`，被 `safe_relpath` 归一成 `/` ⇒
    **凭空多出一层目录、风格名被从中间劈开**。

    三级还原，按可靠度排：
    ① `0x7075` 扩展字段（打包工具明写的 UTF-8 原名，最可靠）；
    ② `0x0800` 标志位已置 ⇒ `zipfile` 解对了，原样用；
    ③ 否则把 `zipfile` 用 CP437 解出来的那串**编回字节**，按本地编码再解一次。
       ⛔ 只在"解出来确实含中日韩字符"时才采信 —— 否则一个真正用 CP437
       命名的西文包会被我们改坏。**宁可保留原样，也不许猜错成另一个名字。**
    """
    name = str(getattr(info, "filename", "") or "")
    from_extra = _unicode_path_from_extra(info)
    if from_extra:
        return from_extra
    if int(getattr(info, "flag_bits", 0) or 0) & 0x800:
        return name
    # ⚠⚠ 往返必须拿 `orig_filename`，不能拿 `filename`：`zipfile` 读包时会把
    #   `\` 归一成 `/`（那是它自己的安全处理），而 GBK 尾字节正好是 `0x5C` 的
    #   那批汉字（`乗` = 81 5C）解出来就带一个 `\` ⇒ 等我们拿到 `filename` 时
    #   那个字节**已经变成 0x2F 了**，编回 cp437 再也还原不出原字。
    #   实测：`乗风/1.mp3` 到手是 `ü/╖τ/1.mp3`，凭空多一层目录。
    # ⭐ 安全性不受影响：还原出来的名字照样要过 `safe_relpath`（拒 `..`、
    #   拒绝对路径、再归一一次分隔符）。
    original = str(getattr(info, "orig_filename", "") or name)
    try:
        raw = original.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in _FALLBACK_ENCODINGS:
        try:
            candidate = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if candidate != name and any("一" <= ch <= "鿿" or
                                     "぀" <= ch <= "ヿ"
                                     for ch in candidate):
            return candidate
    return name


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
        relative = safe_relpath(decode_member_name(info))
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
