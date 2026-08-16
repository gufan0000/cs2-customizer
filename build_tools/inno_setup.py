#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""ISCC.exe（Inno Setup 编译器）定位 —— 打包链路与安装态冒烟共用这一份。

**为什么单独成一个模块**：`build_tools/build_release.py` 和
`scripts/smoke_installer.py` 都要现编安装包，各写一套定位逻辑的结果就是两边
朝不同方向漂：一边用 `Inno Setup*` 通配（装了 7 也能找到、报错会点名找过哪些
目录），另一边把 "Inno Setup 6" 写死在三条候选路径里（装了 7 就说"没装"、
而且不告诉你它找过哪儿）。重复实现只会朝一个方向发展，所以合并成一处。

**这里记着 2.2.3 踩的那个坑**：当时只查 PATH 和 Program Files，误判成"没装
Inno Setup、安装包做不了"，实际它一直装在 `%LOCALAPPDATA%\\Programs\\Inno Setup 6\\`
—— Inno 的安装向导选"仅为我安装"就落这儿，那里既不在 PATH 上，也不在
Program Files 里。所以搜索根必须含 `%LOCALAPPDATA%\\Programs`，
而找不到时的报错必须**点名找过哪些路径**：只说一句"找不到"会被读成"没装"。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# 报错正文的缩进。build_release 把它塞进 RuntimeError，跟着 `[FAIL] ` 那类前缀
# 对齐；调用方要别的缩进就自己传。
DEFAULT_INDENT = "       "


def inno_setup_roots() -> list[Path]:
    """ISCC.exe 可能所在的安装根目录（不含版本子目录）。

    顺序即优先级：用户级安装排在系统级前面——本机就是用户级那一份。
    环境变量没设的跳过，不猜盘符（`C:` 不是硬保证）。
    """
    roots: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "Programs")
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value))
    return roots


def find_iscc_candidates() -> list[Path]:
    """所有存在的候选 ISCC.exe，高版本在前。"""
    # 目录名带主版本号（Inno Setup 6）——用通配匹配，出 7 时不用改代码；
    # 逆序让高版本排前面。
    found: list[Path] = []
    for root in inno_setup_roots():
        try:
            found.extend(sorted(root.glob("Inno Setup*/ISCC.exe"), reverse=True))
        except OSError:
            continue
    return found


def find_iscc() -> Path | None:
    """定位 ISCC.exe：PATH 优先，其次逐个候选目录。找不到返回 None。

    PATH 优先是有意的：操作者显式把某个版本加进 PATH，就是在表达"用这个"，
    不该被目录扫描出来的另一个版本盖过去。
    """
    on_path = shutil.which("iscc")
    if on_path:
        return Path(on_path)
    for candidate in find_iscc_candidates():
        if candidate.exists():
            return candidate
    return None


def missing_iscc_message(indent: str = DEFAULT_INDENT) -> str:
    """找不到编译器时的报错文案 —— 必须逐条列出找过哪些位置。

    这不是排版讲究：2.2.3 那次误判正是因为报错只说"找不到 ISCC"，
    读的人无从判断它是真没装、还是装在了没被搜的地方（后者才是事实）。
    """
    searched = "\n".join(
        f"{indent}  - {root}\\Inno Setup*\\ISCC.exe" for root in inno_setup_roots()
    )
    if not searched:
        searched = f"{indent}  （无处可搜：LOCALAPPDATA / ProgramFiles 环境变量一个都没设）"
    return (
        "找不到 Inno Setup 编译器 ISCC.exe。\n"
        f"{indent}PATH 上没有，以下位置也没有：\n"
        f"{searched}\n"
        f"{indent}装了但不在上面的路径？把 ISCC.exe 所在目录加进 PATH 即可。"
    )
