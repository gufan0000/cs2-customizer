# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""把"用户丢进来的那个东西"变成可识别的一堆相对路径（2026-09-16）。

旧向导只接受**目录**，而用户下下来的是 `资源标题.zip` —— 那一次手动解压
正是"导入很麻烦"的起点。全套设计见 `docs/资源导入_设计方案_v1_20260916.md`。

收三种东西：**压缩包**、**文件夹**、**单个素材文件**
（玩家从群里存下来的那一个 `.mp3`，最常见的一种）。

三件事：**认格式**（按文件头不按扩展名，改名的 RAR 是最常见的一种"装不进去"）、
**安全解压**（走 `core/archive_safe`，不写第四套）、**剥壳**（规则与社区站一致）。

⛔ 不在这里决定"这是什么资源" —— 那是 `resource_identify` 的事。
⚠ 解到**临时目录**，调用方用完必须 `cleanup()`：先解到临时区、验过再落盘，
是为了让"导入失败"能整体回滚，而不是在资源库里留下半套素材。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.archive_safe import (
    ARCHIVE_KINDS,
    MAX_ENTRIES,
    UNSUPPORTED_HINTS,
    ArchiveError,
    is_system_junk,
    iter_safe_members,
    sniff_archive_kind,
    strip_single_root,
)


def source_noun(path: str) -> str:
    """拖进来 / 选中的这个东西，**该叫它什么**（"文件夹" / "压缩包" / "文件"）。

    ⭐ 住在这一层是因为「该叫它什么」和「打不打得开」是同一份知识：
    页面那头原来自己写死成「文件夹 / 压缩包」二选一，而那是**加单文件那条路
    之前**的世界 —— 加完之后拖一个 `.mp3` 进来会被告知「已填入拖入的压缩包」。
    ⛔ 也不许让页面直接 import `archive_safe`：那会给页面链凭空加一个根，
    而 `test_release_critical_modules` 的注释逐字写过它不该登记在那张表里
    （它由 `kill_icon_pack` 那条链覆盖，重复登记会被双向断言逮住）。
    """
    if os.path.isdir(path):
        return "文件夹"
    return "压缩包" if sniff_archive_kind(path) in ARCHIVE_KINDS else "文件"


class ImportSourceError(Exception):
    """这个源没法用。消息是**直接给用户看的**，要能照着做。"""


class ImportCancelled(Exception):
    """用户中途取消。⭐ 与失败分开 —— 取消不该弹错误。"""


@dataclass
class ImportSource:
    """一个摊平了的导入源。"""

    #: `zip` 或 `dir`
    kind: str
    #: 喂给识别器的名字：压缩包名（不含扩展名）或文件夹名。
    #: ⭐ 这是"包名词典"那条信号的输入，**官网包靠它就能认出来**。
    display_name: str
    #: 可遍历的真实根目录（zip 解压后的临时目录）。
    root: str
    #: 相对 `root` 的路径清单，已剥壳、已按安全规则归一。
    paths: List[str] = field(default_factory=list)
    #: 剥掉的那层外壳名（没有就是空串），只用于说明。
    stripped_root: str = ""
    #: 作者放在包里、但**不是任何一类资源**的文件（`说明.txt` / `封面.jpg`）。
    #: ⭐ 它们不进 `paths`（进了就会让那一组变成 `mixed`、把识别器拖到"拿不准"），
    #:   但**必须报出来** —— 悄悄扔掉别人的文件和悄悄导入一样不该。
    companions: List[str] = field(default_factory=list)
    #: 丢掉了几条操作系统垃圾（`__MACOSX/` / `Thumbs.db` / `._*`）。
    #: 这一类不报文件名，只报个数：用户对它们没有任何决定要做。
    junk_count: int = 0
    _temp_dir: Optional[str] = None

    def cleanup(self) -> None:
        """删掉临时解压目录。⚠ 只删自己建的那个，别的一概不碰。"""
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = None

    def __del__(self):
        """⚠ 兜底：任何一条没走到 `cleanup()` 的路径（异常、提前 return、
        对象被回收）都会在 `%TEMP%` 留一份**整包解压副本**。
        ⭐ 核查实测：忘记 cleanup 就是确定地留一份，没有任何东西会提醒。
        ⛔ 兜底不是免责 —— 调用方**照样要**显式 cleanup：
        `__del__` 的时机由垃圾回收决定，不由代码决定。
        """
        try:
            self.cleanup()
        except Exception:
            pass

    def abs_path(self, relative: str) -> str:
        return os.path.join(self.root, str(relative).replace("/", os.sep))

    def read_text(self, relative: str) -> str:
        """读一个文本条目（给清单文件用）。读不了就返回空串。"""
        try:
            with open(self.abs_path(relative), "r", encoding="utf-8") as handle:
                return handle.read()
        except (OSError, UnicodeDecodeError):
            return ""


#: 残留多久算"上次留下的"。⚠ 别定太短：同一台机器上可能有**两个**导入同时在跑
#: （主窗口一个、判据一个），把人家正在用的目录扫了会让那一边当场崩。
_SWEEP_AFTER_SECONDS = 6 * 3600


def sweep_stale_temp_dirs(now: float = 0.0) -> int:
    """把上次留下的解压残留收拾掉，返回清掉几个。

    ⭐ 为什么光有 `cleanup()` 和 `__del__` 不够：**进程被强杀时两个都不会跑**。
    实测到过一个 —— 一次被 `Terminate` 杀掉的冒烟进程留下了整包副本。
    ⛔ 只扫自己前缀（`cs2customizer_import_`）的目录，别的一概不碰。
    """
    import time

    now = now or time.time()
    root = tempfile.gettempdir()
    cleaned = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if not name.startswith("cs2customizer_import_"):
            continue
        path = os.path.join(root, name)
        try:
            if not os.path.isdir(path):
                continue
            if now - os.path.getmtime(path) < _SWEEP_AFTER_SECONDS:
                continue
            shutil.rmtree(path, ignore_errors=True)
            cleaned += 1
        except OSError:
            continue
    return cleaned


def _is_category_dir(name: str) -> bool:
    """这个目录名是不是某类资源的目录（`round_sounds`、`kill_icons`、`audio`…）。

    ⚠ 与站端 `pack_validate.php` 的剥壳规则不矛盾：那边管的是击杀图标包（`风格名/1.png`），
    外壳永远是包名；这里多挡的只是「外壳恰好就是类别目录」这一种。
    """
    from core.resource_catalog import RESOURCE_SPECS

    folded = str(name or "").strip().casefold()
    if folded in ("audio", "resources"):
        return True
    for spec in RESOURCE_SPECS:
        if folded in {spec.key.casefold(), spec.root_name.casefold(),
                      *(alias.casefold() for alias in spec.aliases)}:
            return True
    return False


def _check_cancel(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel and should_cancel():
        raise ImportCancelled("已取消")


_ASSET_EXTENSIONS: Optional[frozenset] = None


def _asset_extensions() -> frozenset:
    """"算资源"的扩展名全集。

    ⛔ **不在这里另立一张名单** —— 每一类资源自己的 `extensions` 就是真源
    （`RESOURCE_SPECS`）。另立一份的代价是它会漂：新增一类资源时没人记得回来改。
    ⚠ 懒加载是为了别把 `core.resource_catalog → core.audio` 那一串拖进页面的
    import 时间（`test_lazy_imports_r8a` 盯着这件事）。
    """
    global _ASSET_EXTENSIONS
    if _ASSET_EXTENSIONS is None:
        from core.resource_catalog import RESOURCE_SPECS

        _ASSET_EXTENSIONS = frozenset(
            str(ext).lower() for spec in RESOURCE_SPECS for ext in spec.extensions)
    return _ASSET_EXTENSIONS


#: 认得出、但**产品播不了**的媒体格式 ⇒ 给一句能照着做的话，
#: 而不是一句笼统的"不支持"。⭐ `.m4a` 排第一：微信/QQ 语音转存就是它。
_CONVERTIBLE_HINTS = {
    ".m4a": "M4A", ".aac": "AAC", ".flac": "FLAC", ".wma": "WMA",
    ".mp4": "MP4 视频", ".mkv": "MKV 视频", ".avi": "AVI 视频",
    ".mov": "MOV 视频", ".opus": "Opus", ".amr": "AMR",
}


def _not_an_asset_message(extension: str) -> str:
    """「这个文件产品用不了」的人话。

    ⛔ 不写成"不认识的文件"：用户手上那个 `.m4a` 是**认得出**的，
    他要的是"那我该怎么办"，而不是"软件不认识它"。
    """
    supported = "、".join(sorted(_asset_extensions()))
    name = _CONVERTIBLE_HINTS.get(extension)
    if name:
        return (f"这是一个 {name} 文件，软件播不了它。"
                f"请先用转换工具转成 mp3 / wav / ogg，再拖进来。")
    shown = extension or "（没有扩展名）"
    return (f"`{shown}` 不是软件认得的素材格式，导进去也不会生效。"
            f"支持的是：{supported}。")


def split_entries(names) -> tuple:
    """把一包条目分成三摊：**素材** / **作者的附带文件** / **系统垃圾个数**。

    ⭐⭐ 这一步的理由是量出来的：同一包枪声素材，加上四样现实里躲不开的杂物，
    **要问用户的次数 0 → 4**（`AK47/默认/Thumbs.db` 让那一组变成 `dir2/mixed`、
    `说明.txt` 和 `封面.jpg` 各自单独成组，识别器只能答"拿不准"）。
    而用户的验收标准就是那个数：「官网的资源可以更方便兼容」。

    ⚠ 两摊分开处置，不许合并：
    - 系统垃圾**只报个数** —— 用户对 `Thumbs.db` 没有任何决定要做；
    - 附带文件**报文件名** —— 那是作者的内容，悄悄扔掉和悄悄导入一样不该。
    """
    assets: List[str] = []
    companions: List[str] = []
    junk = 0
    allowed = _asset_extensions()
    for name in names:
        text = str(name or "").replace("\\", "/")
        if not text:
            continue
        if is_system_junk(text):
            junk += 1
        elif os.path.splitext(text)[1].lower() in allowed:
            assets.append(text)
        else:
            companions.append(text)
    return _move_cover_art(assets, companions) + (junk,)


#: 图片类资源的合法形状只有「`<名>/*.图片`」（`IMAGE_SHAPED`），**没有平铺这一档**。
_IMAGE_EXT_FOR_COVER = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"})
_AUDIO_EXT_FOR_COVER = frozenset({".mp3", ".wav", ".ogg"})


def _move_cover_art(assets: List[str], companions: List[str]) -> tuple:
    """包里既有音频、又有**平铺在根的图片** ⇒ 那张图是封面，不是素材。

    ⚠ `.jpg` / `.png` 本身是合法的素材扩展名（闪光图片、道具瞄点、击杀图标都用），
    所以上面那一步按扩展名分拣时，`封面.jpg` 会被当成素材 —— 实测它自己单独成一组
    `flat/image`，识别器答"拿不准"，于是**多问用户一次**。

    ⭐ 判据不是文件名（`封面` / `cover` / `预览` 各写各的，词典永远少一格），
    而是**形状**：图片类资源的合法形状只有「`<名>/*.图片`」，平铺那一档根本不存在。
    ⛔ 而"包里有音频"这个前提不许去掉 —— 少了它，用户单独拖一张击杀图标 `.png`
    进来会被当成封面拒收，那是**把最常见的一种用法关掉**。
    """
    if not any(os.path.splitext(p)[1].lower() in _AUDIO_EXT_FOR_COVER
               for p in assets):
        return assets, companions
    kept, moved = [], []
    for path in assets:
        flat = "/" not in path
        if flat and os.path.splitext(path)[1].lower() in _IMAGE_EXT_FOR_COVER:
            moved.append(path)
        else:
            kept.append(path)
    return kept, companions + moved


def open_source(
    path: str,
    progress: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ImportSource:
    """把一个压缩包或文件夹变成 `ImportSource`。

    `progress(done, total, 说明)`；`should_cancel()` 返回 True 就抛 `ImportCancelled`。
    """
    # ⭐ 顺手收拾上次被强杀留下的残留 —— 放在这里而不是应用启动时，
    #   是因为**只有真的要导入时才需要那块磁盘**，而应用启动已经够慢了。
    sweep_stale_temp_dirs()
    path = os.path.abspath(str(path or ""))
    if not path or not os.path.exists(path):
        raise ImportSourceError("找不到这个文件或文件夹。")
    if os.path.isdir(path):
        return _open_directory(path, progress, should_cancel)

    kind = sniff_archive_kind(path)
    if kind == "zip":
        return _open_archive(path, progress, should_cancel)
    if kind != "unknown":
        # ⭐⭐ 这里原来写的是 `if kind in UNSUPPORTED_HINTS`，而那是一条
        #   **按名单放行**的判断：`_MAGIC` 认得出、名单里却没有的格式（当时是 gzip）
        #   两个 if 都不成立，一路掉到下面被当成"一个素材文件"收下来。
        #   实测 `枪声包.tar.gz` 原样落进 `audio/…/枪声包.tar.gz` ——
        #   **装得进去、永远不会响**。
        # ⇒ 改成**按名单拒绝**：`_MAGIC` 认出来的、除了 zip，一个都不许往下走。
        #   以后 `_MAGIC` 再多认一种格式，最坏是提示话术糙一点，
        #   而不是多出一条静默把二进制塞进资源目录的路。
        raise ImportSourceError(UNSUPPORTED_HINTS.get(
            kind, "这个文件不是资源包，软件打不开。"
            "如果它是压缩包，请先用解压软件解开，再把解出来的文件夹拖进来。"))
    # ⭐ 剩下的当**单个素材文件**收 —— 玩家手里最常见的就是这个：
    #   从群里存下来一个 `爆头音效.mp3` 直接拖进来，
    #   而不是先给它建个文件夹再打个包。
    return _open_single_file(path, progress)


def _open_directory(
    path: str,
    progress: Optional[Callable[[int, int, str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> ImportSource:
    entries: List[str] = []
    for walk_root, _dirs, files in os.walk(path):
        _check_cancel(should_cancel)
        for filename in files:
            absolute = os.path.join(walk_root, filename)
            relative = os.path.relpath(absolute, path).replace("\\", "/")
            entries.append(relative)
    if not entries:
        raise ImportSourceError("这个文件夹是空的，没有可以导入的文件。")
    # ⚠ 压缩包那条路有三条上限（3200 条 / 512MB / 压缩比），**文件夹这条一条都没有**。
    #   于是在「选择目录」里点错一层（选了 `下载`、`图片`，甚至整个 D 盘）会把
    #   整棵树收进来，确认面板列几万条，落盘时把几十 GB 照片复制进资源目录。
    #   ⭐ 同一件事在两条入口上防得不一样，就是只防了一半。
    if len(entries) > MAX_ENTRIES:
        raise ImportSourceError(
            f"这个文件夹里有 {len(entries)} 个文件，远超一个资源包该有的规模"
            f"（上限 {MAX_ENTRIES}）。是不是选到上一层了？"
            f"请选中真正装素材的那一层再试。")
    assets, companions, junk = split_entries(entries)
    if not assets:
        raise ImportSourceError(
            "这个文件夹里没有认得出的素材文件。"
            "支持的是音频（mp3 / wav / ogg）与图片（png / jpg 等）。")
    if progress:
        progress(len(entries), len(entries), "已读取文件夹")
    # ⚠ 文件夹**不剥壳**：用户选的那一层就是他认为的根。
    #   剥掉会让 `<武器>/<风格>/` 这种结构少一层，而那一层是有含义的。
    return ImportSource(
        kind="dir",
        display_name=os.path.basename(path.rstrip("\\/")) or path,
        root=path,
        paths=sorted(assets),
        companions=sorted(companions),
        junk_count=junk,
    )


def _open_single_file(
    path: str,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> ImportSource:
    """一个素材文件。

    ⛔ `root` 是**用户自己的目录**，所以这条路径上 `_temp_dir` 必须留空 ——
    `cleanup()` 只删自己建的临时目录，绝不能把用户的下载文件夹删了。
    ⚠ `paths` 只放这一个文件：同目录里别的东西跟这次导入无关，
    收进来就成了"我拖了一个文件，它把整个下载夹都导进去了"。
    """
    if os.path.getsize(path) <= 0:
        raise ImportSourceError("这个文件是空的。")
    # ⛔⛔ 这道闸门原来**只有目录和压缩包两条路有**，单文件这条一次都没查过 ——
    #   于是 `.m4a`（微信/QQ 语音转存最常见的格式）、`.mp4`、`.txt` 全都收下，
    #   逼用户从 17 个类目里挑一个（全部拿不准、没有正确答案），挑完报
    #   「导入完成：成功 1」，文件真躺进 `audio/kill_sounds/<风格>/爆头.m4a`，
    #   设置页里看得见那个风格，**进游戏一声不响**。
    # ⭐⭐⭐ 同一道闸门在三条路里只装了两道 —— 又是「各自列举、谁也不管谁」。
    #   ⇒ 判据 `test_every_entry_point_refuses_the_same_non_asset` 按**入口**遍历，
    #     不按格式列举。
    extension = os.path.splitext(path)[1].lower()
    if extension not in _asset_extensions():
        raise ImportSourceError(_not_an_asset_message(extension))
    if progress:
        progress(1, 1, "已读取文件")
    return ImportSource(
        kind="file",
        # ⭐ 不含扩展名 —— 它是"包名词典"那条信号的输入，
        #   `击杀音效.mp3` 要能命中「击杀音效」。
        display_name=os.path.splitext(os.path.basename(path))[0],
        root=os.path.dirname(path),
        paths=[os.path.basename(path)],
    )


#: zip 里除了「存储」和「Deflate」，别的压缩方法 Python 标准库都读不了。
#: ⚠ 这不是我们的选择，是 `zipfile` 的边界；认出来并说人话，别让它抛英文。
_READABLE_COMPRESSION = (0, 8)
_COMPRESSION_NAMES = {9: "Deflate64", 12: "BZip2", 14: "LZMA", 93: "Zstandard",
                      95: "XZ", 96: "JPEG", 97: "WavPack", 98: "PPMd"}


def _refuse_what_zipfile_cannot_read(archive) -> None:
    """**落盘之前**先判死刑：带密码的、用了读不了的压缩方法的。

    ⭐ 放在解压循环之前，是因为解到一半才抛意味着 `%TEMP%` 里留下半个包；
    而这两件事**看一眼中央目录就知道**，一个字节都不用解。
    """
    for info in archive.infolist():
        if info.flag_bits & 0x1:
            raise ImportSourceError(
                "这个压缩包有解压密码，软件打不开。"
                "请先用解压软件输入密码解开，再把解出来的文件夹拖进来。")
    methods = {info.compress_type for info in archive.infolist()
               if info.compress_type not in _READABLE_COMPRESSION}
    if methods:
        name = _COMPRESSION_NAMES.get(sorted(methods)[0], f"编号 {sorted(methods)[0]}")
        raise ImportSourceError(
            f"这个 zip 用了软件读不了的压缩方式（{name}）。"
            f"请用解压软件解开，再把解出来的文件夹拖进来；"
            f"或者重新打包时选「标准 / Deflate」压缩。")


def _open_archive(
    path: str,
    progress: Optional[Callable[[int, int, str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> ImportSource:
    # ⚠ 调用方（`open_source`）已经 sniff 过一次；这里再挡一道是因为
    #   本函数也可能被别处直接调用，而它会往磁盘解压。
    if sniff_archive_kind(path) != "zip":
        raise ImportSourceError("这个文件不是 zip 压缩包。")

    temp_dir = tempfile.mkdtemp(prefix="cs2customizer_import_")
    settled = False
    try:
        with zipfile.ZipFile(path) as archive:
            _refuse_what_zipfile_cannot_read(archive)
            members = list(iter_safe_members(archive, ArchiveError, "资源包"))
            if not members:
                raise ImportSourceError("这个压缩包里没有文件。")
            # ⭐⭐ 垃圾必须在**剥壳之前**扔掉，顺序不许换：Mac 打的包里
            #   `__MACOSX/` 是和 `枪声包/` **并列的第二个顶层目录**，
            #   留着它 `strip_single_root` 就认为"根不唯一"、整个外壳剥不掉，
            #   于是每条路径都多出一层，归类器再也对不上。
            #   ⇒ 这一条不是"顺手清理"，它决定了剥壳成不成。
            before = len(members)
            members = [pair for pair in members if not is_system_junk(pair[1])]
            junk_count = before - len(members)
            if not members:
                raise ImportSourceError(
                    "这个压缩包里只有系统生成的临时文件，没有素材。")
            names = [relative for _info, relative in members]
            stripped, root_name = strip_single_root(names)
            if root_name and _is_category_dir(root_name):
                # 批 123 端到端逮到：`round_sounds/win/清脆/1.wav` 被当成外壳剥成
                # `win/清脆/1.wav` —— 唯一能说明「这是回合音效」的那一层没了，
                # 于是它去问用户，**第一猜还是「枪声替换」**（选了就装进 gun_sounds/win/）。
                # ⭐ 外壳是「包名」那一层；名字就是资源类别目录的那层是内容，不剥。
                stripped, root_name = names, ""
            total = len(members)
            # ⚠ Windows 的文件系统不分大小写，而 zip 分 ⇒ `a.mp3` 与 `A.MP3`
            #   会写到同一个文件上。实测：三条条目（含一条重复）解出来磁盘上只有
            #   一个文件，而 `paths` 里留着三条 ⇒ 导入报「成功 3」，
            #   用户丢了两个音效且毫不知情。
            written = {}
            collisions = []
            for index, (info, relative) in enumerate(members, start=1):
                _check_cancel(should_cancel)
                target_rel = stripped[index - 1]
                folded = target_rel.casefold()
                if folded in written:
                    collisions.append((written[folded], relative))
                    continue
                written[folded] = relative
                target = os.path.join(temp_dir, target_rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(target) or temp_dir, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if progress:
                    progress(index, total, f"正在解压：{target_rel}")
            if collisions:
                raise ImportSourceError(
                    f"这个包里有 {len(collisions)} 组文件重名"
                    f"（例如 `{collisions[0][0]}` 与 `{collisions[0][1]}`）。"
                    f"Windows 不分大小写，装进去会互相覆盖 —— "
                    f"请先把它们改成不同的名字再打包。")
            stripped = [s for s in stripped if s.casefold() in written]
        settled = True
    except ImportCancelled:
        raise
    except ArchiveError as exc:
        raise ImportSourceError(str(exc)) from exc
    except zipfile.BadZipFile as exc:
        raise ImportSourceError(
            "这个压缩包打不开（文件可能没下载完整）。请重新下载一次再试。"
        ) from exc
    except ImportSourceError:
        raise
    except OSError as exc:
        raise ImportSourceError(f"解压时出错：{exc}") from exc
    except Exception as exc:
        # ⭐⭐ 这一条是**兜底**，而它的必要性是实测出来的：原来的 `except` 是
        #   **列举式**的（Cancelled / ArchiveError / BadZipFile / OSError），
        #   于是带密码的包抛的 `RuntimeError`、Deflate64 抛的
        #   `NotImplementedError`、回调自己抛的异常**全在名单之外** ——
        #   一路穿到页面，弹出「发生了预料之外的错误：File <ZipInfo …> is
        #   encrypted, password required for extraction」这种英文加对象 repr。
        # ⭐⭐⭐ 又是「枚举式的名单永远少一格」（同 RN-602 / RN-596）。
        raise ImportSourceError(
            f"读这个压缩包时出了意料之外的问题：{exc}\n"
            f"如果它是从网盘下的，多半是没下完整或者带了解压密码 —— "
            f"请先用解压软件打开看看，再把解出来的文件夹拖进来。") from exc
    finally:
        # ⛔ 清理必须走 `finally`：上面每个 except 各写一遍 `rmtree` 的写法
        #   **漏掉了名单外的异常**，实测一个加密包就在 `%TEMP%` 里
        #   留下一份整包半成品，要等 6 小时后的某次导入才被扫掉。
        if not settled:
            shutil.rmtree(temp_dir, ignore_errors=True)

    assets, companions, _ = split_entries(stripped)
    if not assets:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ImportSourceError(
            "这个压缩包里没有认得出的素材文件。"
            "支持的是音频（mp3 / wav / ogg）与图片（png / jpg 等）。")
    stem = os.path.splitext(os.path.basename(path))[0]
    return ImportSource(
        kind="zip",
        display_name=stem,
        root=temp_dir,
        paths=sorted(assets),
        stripped_root=root_name,
        companions=sorted(companions),
        junk_count=junk_count,
        _temp_dir=temp_dir,
    )
