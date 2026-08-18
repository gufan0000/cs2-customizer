# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""打包冒烟自动挑产物时，不许挑到安装包。

**2026-08-18 实际踩到**：`python scripts/smoke_packaged.py`（不给 `--exe`）
按 mtime 挑 `release/*/*.exe` 里最新的那个——而安装包
`release/installer/CS2 Customizer 安装包_2.2.4.exe` **是在应用产物之后生成的**，
所以它永远是最新的那个。

结果：冒烟启动的是**安装程序**，等 UAC 等到超时、探不到窗口、日志 0 字符，
7 条判据一起红。表面上看是"打包版起不来"，实际上**一个字都没测到**。

⭐ 两条要害：
① **一道门禁测错了对象，比它不存在更坏** —— 它给出的是一个看起来很严重、
   但和被测对象毫无关系的结论，会把人引去查根本没坏的地方；
② 它**真的在用户机器上拉起了安装器**。这次卡在 UAC 没装成（注册表仍是 2.2.0），
   但那是运气，不是设计。

修法：自动挑选排除 `installer/` 目录与「安装包」字样，并要求同级有 `_internal`
（onedir 产物的形状）。挑不到宁可报错，不瞎跑。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parent.parent
SMOKE = REPO / "scripts" / "smoke_packaged.py"


def _autodetect_block(*, code_only: bool = True) -> str:
    """截出 `--exe` 留空时那段自动挑选的**代码**。

    ⚠ **必须把注释剥掉。** 第一版判据只写了 `assert "installer" in block`，
    而我在同一段里写了一条解释这件事的注释（"⇒ 自动挑选一律排除 installer 目录"）——
    于是把过滤条件整条删掉之后，判据**照样绿**：它看见的是注释，不是代码。
    回退验证当场把它判成假绿。
    ⇒ 同 RN-072 那条教训的第二例：**文本比对连注释一起看，等于给自己发通行证。**
    """
    src = SMOKE.read_text(encoding="utf-8")
    m = re.search(r"if exe is None:(.*?)\n    if not exe\.is_file", src, re.S)
    assert m, "找不到自动挑选那段代码——判据的前提没了，别让它假绿"
    block = m.group(1)
    if not code_only:
        return block
    return "\n".join(re.sub(r"#.*$", "", line) for line in block.splitlines())


def test_the_extractor_actually_found_the_block():
    block = _autodetect_block()
    assert "release/*/*.exe" in block, (
        "自动挑选那段的写法变了，这条判据可能已经在空转：\n" + block[:400])


def test_the_comment_stripper_actually_strips():
    """空转守卫：剥注释这一步自己失效的话，上面那条教训就白学了。"""
    with_comments = _autodetect_block(code_only=False)
    code = _autodetect_block()
    assert "⇒" in with_comments, "那段里本来就该有解释性注释，现在没有了——判据前提变了"
    assert "⇒" not in code, "注释没被剥掉，下面的判据可能又在读注释"


def test_the_installer_directory_is_excluded():
    block = _autodetect_block()
    assert 'c.parent.name.lower() != "installer"' in block, (
        "自动挑选没有排除 `release/installer/` —— 安装包比应用产物新，"
        "它会被挑中，于是冒烟启动的是安装程序（还会真的拉起 UAC）。\n"
        "实际代码：\n" + block)


def test_it_requires_the_onedir_shape():
    """光排除目录名不够：换个名字放别处照样会被挑中。

    正面条件才是硬的 —— onedir 产物同级必然有 `_internal`。
    """
    block = _autodetect_block()
    assert '(c.parent / "_internal").is_dir()' in block, (
        "自动挑选没有要求 onedir 的形状（同级 `_internal` 目录）。"
        "只靠排除名字是黑名单，遇到没想到的名字就漏。")


def test_it_refuses_rather_than_guessing():
    """挑不到就报错退出，不许退化成"随便挑一个"。"""
    block = _autodetect_block()
    assert "return 1" in block, "挑不到产物时没有直接失败退出"
