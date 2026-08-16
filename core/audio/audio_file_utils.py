# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for audio file discovery and selection."""

from __future__ import annotations

import os
import time as _cache_time
from typing import Iterable, List, Optional, Sequence, Tuple


DEFAULT_AUDIO_EXTENSIONS: Tuple[str, ...] = (".mp3", ".wav", ".ogg")


def normalize_extensions(
    extensions: Optional[Sequence[str]] = None,
) -> Tuple[str, ...]:
    """Normalize extension list to lowercase values with leading dots."""
    if not extensions:
        return DEFAULT_AUDIO_EXTENSIONS

    normalized: List[str] = []
    for ext in extensions:
        if not ext:
            continue
        value = ext.strip().lower()
        if not value:
            continue
        if not value.startswith("."):
            value = f".{value}"
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized) if normalized else DEFAULT_AUDIO_EXTENSIONS


def is_audio_filename(
    filename: str,
    extensions: Optional[Sequence[str]] = None,
) -> bool:
    if not filename:
        return False
    lower_name = filename.lower()
    return lower_name.endswith(normalize_extensions(extensions))


def list_audio_files(
    directory: str,
    extensions: Optional[Sequence[str]] = None,
    sort: bool = True,
) -> List[str]:
    """Return audio filenames in a directory (file names only)."""
    if not directory or not os.path.isdir(directory):
        return []

    files: List[str] = []
    for name in os.listdir(directory):
        full_path = os.path.join(directory, name)
        if not os.path.isfile(full_path):
            continue
        if is_audio_filename(name, extensions):
            files.append(name)

    if sort:
        files.sort(key=str.lower)
    return files


def list_audio_paths(
    directory: str,
    extensions: Optional[Sequence[str]] = None,
    sort: bool = True,
) -> List[str]:
    files = list_audio_files(directory, extensions=extensions, sort=sort)
    return [os.path.join(directory, name) for name in files]


def has_audio_files(
    directory: str,
    extensions: Optional[Sequence[str]] = None,
) -> bool:
    if not directory or not os.path.isdir(directory):
        return False
    for name in os.listdir(directory):
        full_path = os.path.join(directory, name)
        if os.path.isfile(full_path) and is_audio_filename(name, extensions):
            return True
    return False


def find_first_audio_file(
    directory: str,
    extensions: Optional[Sequence[str]] = None,
    preferred_tokens: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """
    Pick a stable first audio file path.

    If preferred_tokens are provided, return the first file whose name
    contains any token (case-insensitive), otherwise fall back to the first
    audio file by sorted filename.
    """
    candidates = list_audio_files(directory, extensions=extensions, sort=True)
    if not candidates:
        return None

    tokens: List[str] = []
    if preferred_tokens:
        for token in preferred_tokens:
            if not token:
                continue
            value = token.strip().lower()
            if value:
                tokens.append(value)

    if tokens:
        for name in candidates:
            lower_name = name.lower()
            if any(token in lower_name for token in tokens):
                return os.path.join(directory, name)

    return os.path.join(directory, candidates[0])


def find_audio_by_tokens(
    directory: str,
    tokens: Optional[Iterable[str]] = None,
    extensions: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """按文件名关键词找音频，**找不到就返回 None，不回落到第一个文件**。

    和 `find_first_audio_file` 的区别只在最后那一步，但语义完全相反：
    那个是"给我这个目录的代表文件"，这个是"只要真正匹配的那个"。

    用在多个事件共用一个风格目录的场景（C4 的拆除/爆炸）：目录里通常只放了
    一个"下包"音效，这时拆除事件必须**安静地不响**。回落的话，用户会在拆包时
    听到本该在下包时响的声音——那听起来像 bug，比不响更糟。
    """
    candidates = list_audio_files(directory, extensions=extensions, sort=True)
    if not candidates:
        return None

    wanted = [t.strip().lower() for t in (tokens or ()) if t and t.strip()]
    if not wanted:
        return None

    for name in candidates:
        lower_name = name.lower()
        if any(token in lower_name for token in wanted):
            return os.path.join(directory, name)
    return None


def find_audio_by_stem(
    directory: str,
    stem: str,
    extensions: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Find first existing file by stem and extension priority."""
    if not directory or not stem or not os.path.isdir(directory):
        return None

    for ext in normalize_extensions(extensions):
        candidate = os.path.join(directory, f"{stem}{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None


# 2.2.0 卡顿治理:风格目录扫描进程级缓存(3 秒 TTL)。
# 实测每个音效页构建要做 ~184 次本函数调用(396 isdir + 203 listdir),
# 五个音效页 = 上千次重复磁盘 IO,是启动期逐页 300-500ms 微顿的共性大头。
# TTL 设计:启动批量构建窗口内全命中;用户"刷新风格/导入"等主动操作
# 距上次扫描必然 >3s,自然拿到新数据——无需在九个 scan_* 调用方逐一插失效。
# 全量重扫路径(_scan_audio_styles)仍显式 invalidate,双保险。
_style_dirs_cache: dict = {}
_STYLE_CACHE_TTL = 3.0


def invalidate_style_dirs_cache() -> None:
    """音频资源发生变化(重扫/导入)时调用,清空目录扫描缓存。"""
    _style_dirs_cache.clear()


def list_style_dirs_with_audio(
    parent_dir: str,
    extensions: Optional[Sequence[str]] = None,
    sort: bool = True,
) -> List[str]:
    """
    Return sub-directory names that contain at least one audio file.
    (结果带 3s TTL 进程缓存;返回副本,调用方可安全修改)
    """
    if not parent_dir or not os.path.isdir(parent_dir):
        return []

    key = (parent_dir, tuple(extensions) if extensions else None, sort)
    cached = _style_dirs_cache.get(key)
    if cached is not None and (_cache_time.perf_counter() - cached[0]) < _STYLE_CACHE_TTL:
        return list(cached[1])

    styles: List[str] = []
    for name in os.listdir(parent_dir):
        style_dir = os.path.join(parent_dir, name)
        if not os.path.isdir(style_dir):
            continue
        if has_audio_files(style_dir, extensions=extensions):
            styles.append(name)

    if sort:
        styles.sort(key=str.lower)
    _style_dirs_cache[key] = (_cache_time.perf_counter(), tuple(styles))
    return styles


def list_unique_audio_stems(
    directory: str,
    extensions: Optional[Sequence[str]] = None,
    sort: bool = True,
) -> List[str]:
    """
    Return unique file stems for all audio files in a directory.
    """
    stems: List[str] = []
    seen = set()
    for filename in list_audio_files(directory, extensions=extensions, sort=sort):
        stem = os.path.splitext(filename)[0]
        if stem in seen:
            continue
        stems.append(stem)
        seen.add(stem)

    if sort:
        stems.sort(key=str.lower)
    return stems
