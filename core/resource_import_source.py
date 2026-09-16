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
    UNSUPPORTED_HINTS,
    ArchiveError,
    iter_safe_members,
    sniff_archive_kind,
    strip_single_root,
)


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


def _check_cancel(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel and should_cancel():
        raise ImportCancelled("已取消")


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
    if kind in UNSUPPORTED_HINTS:
        # ⭐ 认出来了但打不开 ⇒ 给一句能照着做的话，而不是"不认识的文件"。
        raise ImportSourceError(UNSUPPORTED_HINTS[kind])
    if kind == "zip":
        return _open_archive(path, progress, should_cancel)
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
    if progress:
        progress(len(entries), len(entries), "已读取文件夹")
    # ⚠ 文件夹**不剥壳**：用户选的那一层就是他认为的根。
    #   剥掉会让 `<武器>/<风格>/` 这种结构少一层，而那一层是有含义的。
    return ImportSource(
        kind="dir",
        display_name=os.path.basename(path.rstrip("\\/")) or path,
        root=path,
        paths=sorted(entries),
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
    try:
        with zipfile.ZipFile(path) as archive:
            members = list(iter_safe_members(archive, ArchiveError, "资源包"))
            if not members:
                raise ImportSourceError("这个压缩包里没有文件。")
            names = [relative for _info, relative in members]
            stripped, root_name = strip_single_root(names)
            total = len(members)
            for index, (info, relative) in enumerate(members, start=1):
                _check_cancel(should_cancel)
                target_rel = stripped[index - 1]
                target = os.path.join(temp_dir, target_rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(target) or temp_dir, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if progress:
                    progress(index, total, f"正在解压：{target_rel}")
    except ImportCancelled:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except ArchiveError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ImportSourceError(str(exc)) from exc
    except zipfile.BadZipFile as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ImportSourceError(
            "这个压缩包打不开（文件可能没下载完整）。请重新下载一次再试。"
        ) from exc
    except ImportSourceError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ImportSourceError(f"解压时出错：{exc}") from exc

    stem = os.path.splitext(os.path.basename(path))[0]
    return ImportSource(
        kind="zip",
        display_name=stem,
        root=temp_dir,
        paths=sorted(stripped),
        stripped_root=root_name,
        _temp_dir=temp_dir,
    )
