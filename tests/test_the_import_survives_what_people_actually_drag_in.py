# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""用户手上那个文件真长这样吗（2026-09-17）。

## 这一族的共同形态

判据喂的一直是**我自己造的干净样本**：UTF-8 名字的 zip、没有密码、
标准 Deflate、文件名恰好叫 `1.mp3`。而中文玩家手上的东西不长这样：

| 现实里的东西 | 改之前的表现 |
|---|---|
| Windows 右键「发送到 → 压缩文件夹」打的中文包 | 文件名按 **CP437** 解 ⇒ 资源目录里建出 `╟σ┤α` 这种风格 |
| 网盘常见的**带解压密码**的 zip | 弹一句英文 `File <ZipInfo …> is encrypted` + `%TEMP%` 里留一份半成品 |
| 7-Zip 选了 LZMA / 撞上 Deflate64 | 同上，`NotImplementedError` 原样穿出去 |
| 微信/QQ 语音转存的 `.m4a` | **被当成素材收下**，落进资源目录，进游戏一声不响 |
| 浏览器里拖一个下载链接 | 鼠标显示"可以放"，放下之后**什么都不发生，也不说一句** |

⭐⭐⭐ 一条共同的教训：**枚举式的名单永远少一格。**
`except` 列举了四种异常、闸门装在三条入口里的两条、格式按名单放行——
每一处漏掉的那一格，都是现实里最常见的那一种。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_import_survives_what_people_actually_drag_in.py`）
"""
from __future__ import annotations

import os
import tempfile
import zipfile

import pytest

from core.archive_safe import decode_member_name
from core.resource_import_source import ImportSourceError, open_source


def _windows_style_chinese_zip(path, names):
    """造一个「Windows 压缩文件夹」风格的 zip：名字按 GBK 存、**不置 0x800**。

    ⚠ `zipfile.writestr` 遇到非 ASCII 会自动置 0x800 并写 UTF-8，
    所以先用**等字节长度**的 ASCII 占位名写，再在字节层替换成 GBK 字节。
    ⭐ 占位名必须等长 —— 长度不等会改坏 filename length 字段，
    得到的是"打不开"而不是"乱码"，那就测的不是这件事了。
    """
    holders = {}
    for index, name in enumerate(names):
        width = len(name.encode("gbk"))
        stem = f"P{index}" * width
        holders[name] = stem[:width]
    with zipfile.ZipFile(path, "w") as archive:
        for name, holder in holders.items():
            assert len(holder.encode("ascii")) == len(name.encode("gbk"))
            archive.writestr(holder, b"ID3" + b"\0" * 32)
    raw = open(path, "rb").read()
    for name, holder in holders.items():
        raw = raw.replace(holder.encode("ascii"), name.encode("gbk"))
    with open(path, "wb") as sink:
        sink.write(raw)
    return str(path)


# ---------------------------------------------------- ① 中文文件名

def test_a_pack_made_by_windows_explorer_keeps_its_chinese_names(tmp_path):
    """⭐⭐⭐ 社区站上大量的包是这么打的。

    Python 的 `zipfile` 对没有 0x0800 标志位的名字一律按 **CP437** 解 ⇒
    `清脆/1.mp3` 变成 `╟σ┤α/1.mp3`，而这串乱码会**一路穿到用户的资源目录里
    建出一个叫 `╟σ┤α` 的风格**，设置页的下拉框里就显示它，导入报「成功 3」。
    """
    packed = _windows_style_chinese_zip(
        tmp_path / "击杀音效包.zip", ["清脆/1.mp3", "清脆/2.mp3", "低沉/1.mp3"])
    source = open_source(packed)
    try:
        assert source.paths == ["低沉/1.mp3", "清脆/1.mp3", "清脆/2.mp3"]
    finally:
        source.cleanup()


def test_a_chinese_name_whose_gbk_tail_byte_is_a_backslash_is_not_split(tmp_path):
    """⚠ GBK 尾字节正好是 `0x5C` 的那批汉字（`乗` = 81 5C，基本区里一百多个）。

    CP437 解出来带一个 `\\` ⇒ **凭空多出一层目录、名字被从中间劈开**。
    ⭐⭐ 而这一条只能拿 `orig_filename` 还原：`zipfile` 读包时会把 `\\`
    归一成 `/`（它自己的安全处理），等我们拿到 `filename` 时
    那个字节**已经变成 0x2F 了**，再也还原不回去。
    """
    packed = _windows_style_chinese_zip(tmp_path / "包.zip", ["乗风/1.mp3"])
    with zipfile.ZipFile(packed) as archive:
        info = archive.infolist()[0]
        assert "/" in info.filename and info.filename.count("/") == 2, (
            "这条判据的前提是 zipfile 把反斜杠归一成了斜杠；"
            f"实得 {info.filename!r}")
        assert decode_member_name(info) == "乗风/1.mp3"


def test_a_plain_ascii_pack_is_never_touched(tmp_path):
    """⛔ 还原只在"解出来确实含中日韩字符"时采信 ——
    一个真正用 CP437 命名的西文包不许被我们改坏。"""
    packed = tmp_path / "western.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("style/1.mp3", b"ID3" + b"\0" * 32)
    source = open_source(str(packed))
    try:
        assert source.paths == ["1.mp3"]
    finally:
        source.cleanup()


# ---------------------------------------------------- ② 打不开的 zip

@pytest.fixture
def private_temp(tmp_path, monkeypatch):
    """把 `tempfile` 的落点挪到本用例私有的目录。

    ⛔⛔ 第一版数的是**全局 `%TEMP%` 里的 `cs2customizer_import_*` 个数** ——
    而全量是 6 路并行跑的，隔壁 worker 同一刻建一个就让这条红。
    ⭐⭐⭐ 单跑全绿、全量红，而红的原因与被测代码毫无关系 ——
    这是我这一轮**第三次**写出依赖共享全局状态的判据
    （另两次：页面用跨次持久的 `%TEMP%/cs2customizer_test_config`、
    以及那条数分母的棘轮）。⇒ 同一个错法反复出现，说明它不是疏忽，
    是「判据要自带它需要的整个世界」这件事我没有当成默认动作。
    """
    private = tmp_path / "temp"
    private.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private))
    yield private


def _count_leftovers(root):
    try:
        return sum(1 for name in os.listdir(str(root))
                   if name.startswith("cs2customizer_import_"))
    except OSError:
        return 0


def test_a_password_protected_zip_says_so_in_chinese(tmp_path):
    """⛔ 网盘分享带密码是国内最常见的分发方式之一。

    改之前用户看到的是：「发生了预料之外的错误：File <ZipInfo
    filename='风格/1.mp3' …> is encrypted, password required for extraction」
    —— 一串英文加 Python 对象 repr，既不说"这个包有密码"也不说该怎么办。
    """
    packed = tmp_path / "网盘下的.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("风格/1.mp3", b"ID3" + b"\0" * 32)
    raw = bytearray(packed.read_bytes())
    raw[raw.find(b"PK\x03\x04") + 6] |= 1          # 本地头的通用标志位 bit0
    raw[raw.find(b"PK\x01\x02") + 8] |= 1          # 中央目录的同一位
    packed.write_bytes(bytes(raw))

    with pytest.raises(ImportSourceError) as caught:
        open_source(str(packed))
    assert "密码" in str(caught.value)
    assert "解压软件" in str(caught.value), "只说是什么，没说该怎么办"


def test_a_zip_that_cannot_be_read_leaves_no_leftovers(tmp_path, private_temp):
    """⛔⛔ 失败路径**也要清临时目录**。

    原来每个 `except` 分支各写一遍 `rmtree`，而那是一张**列举式**的名单
    （Cancelled / ArchiveError / BadZipFile / OSError）—— 加密包抛的
    `RuntimeError` 不在名单里，于是一个几百兆的包解到一半就在 `%TEMP%`
    里留着，最快也要等 6 小时后的某一次导入才被扫掉。
    ⇒ 改成 `finally`。
    """
    packed = tmp_path / "坏的.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("风格/1.mp3", b"ID3" + b"\0" * 32)
    raw = bytearray(packed.read_bytes())
    raw[raw.find(b"PK\x03\x04") + 6] |= 1
    raw[raw.find(b"PK\x01\x02") + 8] |= 1
    packed.write_bytes(bytes(raw))

    before = _count_leftovers(private_temp)
    with pytest.raises(ImportSourceError):
        open_source(str(packed))
    assert _count_leftovers(private_temp) == before, "失败路径漏了临时目录"


def test_an_unsupported_compression_method_says_which_one(tmp_path):
    """⚠ 7-Zip / WinRAR 打 zip 时选 LZMA 很常见，Python 读不了。"""
    packed = tmp_path / "lzma.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("风格/1.mp3", b"ID3" + b"\0" * 32)
    raw = bytearray(packed.read_bytes())
    # 本地头 +8 与中央目录 +10 是压缩方法
    raw[raw.find(b"PK\x03\x04") + 8] = 14
    raw[raw.find(b"PK\x01\x02") + 10] = 14
    packed.write_bytes(bytes(raw))

    with pytest.raises(ImportSourceError) as caught:
        open_source(str(packed))
    assert "LZMA" in str(caught.value)
    assert "解压" in str(caught.value)


def test_entries_that_collide_on_windows_are_refused(tmp_path):
    """⛔ Windows 不分大小写，而 zip 分 ⇒ `a.mp3` 与 `A.MP3` 会互相覆盖。

    实测：三条条目解出来磁盘上只剩一个文件，而 `paths` 里留着三条 ⇒
    导入报「成功 3」，**用户丢了两个音效且毫不知情**。
    """
    packed = tmp_path / "重名.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("风格/a.mp3", b"AAAA")
        archive.writestr("风格/A.MP3", b"BBBB")
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(packed))
    assert "重名" in str(caught.value)


# ---------------------------------------------------- ③ 三条入口同一道闸门

@pytest.mark.parametrize("extension", [".m4a", ".mp4", ".txt", ".aac", ".flac"])
def test_a_single_non_asset_file_is_refused(tmp_path, extension):
    """⛔⛔ 这道闸门原来**只装在目录和压缩包两条路上**，单文件那条一次都没查过。

    实测：`.m4a`（微信/QQ 语音转存最常见的格式）被当素材收下，
    逼用户从 17 个类目里挑一个（全部拿不准、没有正确答案），
    挑完报「导入完成：成功 1」，文件真躺进 `audio/kill_sounds/<风格>/爆头.m4a`，
    设置页里看得见那个风格，**进游戏一声不响**。
    """
    one = tmp_path / f"群里存的{extension}"
    one.write_bytes(b"\0" * 128)
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(one))
    assert "mp3" in str(caught.value), "要告诉他支持什么 / 该转成什么"


def test_the_gate_is_the_same_on_every_entry_point(tmp_path):
    """⭐⭐ 棘轮：**按入口遍历，不按格式列举**。

    三条入口（单文件 / 文件夹 / 压缩包）必须对同一个非素材文件给出同一个判断。
    ⛔ 这条判据存在的理由就是上面那个缺陷的形态：
    同一道闸门在三条路里只装了两道，而漏掉的那条是玩家最常用的。
    """
    payload = b"\0" * 64

    lone = tmp_path / "说明.txt"
    lone.write_bytes(payload)

    folder = tmp_path / "一个文件夹"
    folder.mkdir()
    (folder / "说明.txt").write_bytes(payload)

    packed = tmp_path / "包.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("说明.txt", payload)

    for entry in (lone, folder, packed):
        with pytest.raises(ImportSourceError):
            open_source(str(entry))


def test_a_folder_with_absurdly_many_files_is_refused(tmp_path):
    """⚠ 压缩包有 3200 条上限，而文件夹这条路**一条都没有** ——
    在「选择目录」里点错一层（选了整个 `下载`）会把整棵树收进来。
    ⭐ 同一件事在两条入口上防得不一样，就是只防了一半。"""
    from core.archive_safe import MAX_ENTRIES

    folder = tmp_path / "点错了"
    folder.mkdir()
    for index in range(MAX_ENTRIES + 5):
        (folder / f"{index}.mp3").write_bytes(b"ID3")
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(folder))
    assert "上一层" in str(caught.value), "要说清他多半是选错了层，而不是只报个数"
