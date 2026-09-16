# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""外来压缩包的三条护栏，在**收成一份之后**仍然守得住（2026-09-16）。

## 为什么要这一条

`core/archive_safe.py` 是把 `kill_icon_pack` 里那套护栏提升上来的，动机是
资源导入统一化需要第四个调用点（前三个：击杀图标包 / `.cs2customizer` 分享文件 / 社区站）。

⭐⭐⭐ **一次"把三份合成一份"的重构，最危险的地方不是合错，是合完之后
只有原来那一份还有判据守着** —— 新的公共模块自己没有判据，
而旧判据是隔着调用方测的，调用方一换实现它照样绿。
⇒ 这里直接对着**公共模块**测，和 `test_kill_icon_pack_ki4.py` 各测一端。

⚠ 三条上限的**数值**也钉住：`MAX_ENTRIES` 那个 3200 是拿真实素材换来的
（默认风格 519 帧逐帧目录导出 520 个条目，上限原本定 400，
结果是我们自己导出的包自己装不回来）。有人"顺手收紧"它时要当场红。

（本项目测试逐文件跑：
 `python -m pytest tests/test_an_outside_archive_cannot_escape_or_explode.py`）
"""
from __future__ import annotations

import io
import zipfile

import pytest

from core.archive_safe import (
    MAX_COMPRESSION_RATIO,
    MAX_ENTRIES,
    MAX_UNCOMPRESSED_BYTES,
    ArchiveError,
    iter_safe_members,
    safe_relpath,
    sniff_archive_kind,
    strip_single_root,
)


def _zip_with(names, payload=b"x"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, payload)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


# ---------------------------------------------------------------- 路径逃逸

@pytest.mark.parametrize("evil", [
    "../evil.txt",
    "../../evil.txt",
    "a/../../evil.txt",
    "/etc/passwd",
    "C:/Windows/evil.txt",
    "c:\\windows\\evil.txt",
])
def test_every_escaping_path_is_refused(evil):
    """⭐ 逐个形态都要测：`..`、绝对路径、盘符是**三种**不同的逃法，
    而一个只挡住 `..` 的实现在前两条判据上照样绿。"""
    assert safe_relpath(evil) is None, f"{evil} 被放行了 —— 它能写到资源目录外面"


def test_an_ordinary_path_survives_normalization():
    """反面守卫：护栏不能严到把正常路径也吃掉（否则没有包装得进来）。"""
    assert safe_relpath("style/1.png") == "style/1.png"
    assert safe_relpath("style/./1.png") == "style/1.png"
    assert safe_relpath("style\\1.png") == "style/1.png"


def test_zip_slip_stops_the_whole_pack_not_just_that_entry():
    """⛔ 撞到不安全路径要**整个包都不导入**，不是"跳过这一条"。

    跳过那一条意味着用户拿到一个**半装进去的包**，而他不会知道少了什么。
    """
    with pytest.raises(ArchiveError) as caught:
        list(iter_safe_members(_zip_with(["ok.png", "../evil.txt"])))
    assert "不安全" in str(caught.value)


# ---------------------------------------------------------------- 总量护栏

def test_a_zip_bomb_is_refused_by_compression_ratio():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.bin", b"\0" * (MAX_COMPRESSION_RATIO * 4096))
    buffer.seek(0)
    with pytest.raises(ArchiveError) as caught:
        list(iter_safe_members(zipfile.ZipFile(buffer)))
    assert "压缩比" in str(caught.value)


def test_too_many_entries_is_refused():
    names = [f"f{index}.txt" for index in range(MAX_ENTRIES + 5)]
    with pytest.raises(ArchiveError):
        list(iter_safe_members(_zip_with(names)))


def test_the_three_ceilings_keep_the_values_they_were_given():
    """⚠ 数值本身是判据的一部分，见模块头那段「装不回来」的账。"""
    assert MAX_ENTRIES == 3200
    assert MAX_UNCOMPRESSED_BYTES == 512 * 1024 * 1024
    assert MAX_COMPRESSION_RATIO == 500


def test_the_caller_keeps_its_own_exception_type():
    """⭐ 这一条守的是**重构的兼容性**：调用方传进来的异常类必须真的被抛出。

    `kill_icon_pack` 的判据断言的是 `KillIconImportError`；
    如果这里改成永远抛 `ArchiveError`，那边会在**另一个文件**里红，
    而看到的人不会想到是这次重构干的。
    """
    class MyError(Exception):
        pass

    with pytest.raises(MyError):
        list(iter_safe_members(_zip_with(["../x.txt"]), MyError, "测试包"))


# ---------------------------------------------------------------- 认格式

@pytest.mark.parametrize("head, expect", [
    (b"PK\x03\x04rest", "zip"),
    (b"Rar!\x1a\x07\x00", "rar"),
    (b"7z\xbc\xaf\x27\x1c\x00", "7z"),
    (b"MZ\x90\x00", "exe"),
    (b"random bytes", "unknown"),
])
def test_the_kind_comes_from_the_header_not_the_extension(tmp_path, head, expect):
    """⭐ 改名的 RAR 是最常见的一种"这包怎么装不进去"——
    扩展名写着 `.zip`，内容是 RAR。按文件头认才认得出来。"""
    target = tmp_path / "whatever.zip"
    target.write_bytes(head)
    assert sniff_archive_kind(str(target)) == expect


def test_an_unreadable_path_is_unknown_not_a_crash():
    assert sniff_archive_kind("H:/definitely/not/here.zip") == "unknown"


# ---------------------------------------------------------------- 剥壳

def test_a_single_wrapper_folder_is_stripped():
    entries, root = strip_single_root(["pack/1.png", "pack/2.png"])
    assert entries == ["1.png", "2.png"]
    assert root == "pack"


def test_a_mixed_root_is_left_alone():
    """⚠ 只剥"单层且所有文件都在里面"的那一种。

    ⭐ 这条规则必须和社区站 `pack_validate.php:194-205` 一致 ——
    两边对"外壳"的定义一旦分叉，同一个包在站里通过、装进来却是另一个形状。
    """
    entries, root = strip_single_root(["1.png", "pack/2.png"])
    assert entries == ["1.png", "pack/2.png"]
    assert root == ""

    entries, root = strip_single_root(["a/1.png", "b/2.png"])
    assert root == "", "两个不同的根不是外壳，剥掉会把 a/b 这一层信息丢掉"
