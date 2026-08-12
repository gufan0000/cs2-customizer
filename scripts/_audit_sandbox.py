# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""审计脚本的外部写入沙箱（UP-090）。

**为什么需要它**：审计脚本已经隔离了配置目录和日志目录（`CS2C_CONFIG_DIR` /
`CS2C_LOG_DIR`），但那两个变量管不到第三个出口——**CS2 游戏目录**。

`config.csgo_dir` 是自动探测的：隔离配置是空的 → 探测器扫盘 → 扫到用户真机上
任意一个 CS2 安装。于是排版审计构建放大镜页时，
`_ensure_sensitivity_support_files_if_needed()` 会往那个真实游戏目录写
`cs2customizer.cfg` / `cs2customizer_magnifier_runtime.cfg`，**内容还是默认配置生成的**，
把用户原来的绑定覆盖掉。

R9-A 实测抓到：`G:\\SteamLibrary\\...\\cfg\\cs2customizer.cfg` 被写成默认配置的 2007 字节版本
（用户真实配置应生成 2075 字节）。这事已经悄悄发生过很多轮了——审计本身"绿"，
副作用不在任何判据的视野里。

**中和方式**：把 `config.csgo_dir` 指到临时目录。不是置空——置空会让页面走
「未配置 CS2 目录」分支，UI 文案和布局跟着变，等于把被审计对象改掉了。
指向一个真实存在的空目录，页面照常走"已配置"分支，写操作落在临时目录里。

用法（在 import config 之后、建任何页面之前调一次）：

    from _audit_sandbox import sandbox_external_writes
    sandbox_external_writes()

`tests/test_audit_side_effects_r9a.py` 会 AST 扫描所有会建页的审计脚本，
确认每一个都调了这个函数。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: 沙箱目录的完整路径覆盖。默认 `%TEMP%/cs2customizer_audit_game_sandbox`。
#:
#: 之所以要能覆盖：`%TEMP%` 在 Windows 上是 `C:\Users\<用户名>\AppData\Local\Temp`,
#: **路径里带着当前用户名**。平时无所谓，但高级设置页会把 CS2 目录**原样显示出来**，
#: 于是任何截了那一页的图都会把用户名一起印进去。开源版的 README 截图就这么把它
#: 发出去过一次——而本产品的日志脱敏器（`core/utils/log_filter.py`）专门就是
#: 干掉 `C:\Users\<用户名>\` 的。要出对外的截图时把这个变量指到不含用户名的目录。
SANDBOX_DIR_ENV = "CS2C_AUDIT_SANDBOX_DIR"

_SANDBOX_DIR: Path | None = None


def sandbox_dir() -> Path:
    """沙箱目录的路径（不建目录、不改配置），供调用方在动手之前先检查它。"""
    override = os.environ.get(SANDBOX_DIR_ENV)
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "cs2customizer_audit_game_sandbox"


def sandbox_external_writes(verbose: bool = True) -> Path:
    """把 `config.csgo_dir` 重定向到临时目录，返回该目录。幂等。"""
    global _SANDBOX_DIR
    if _SANDBOX_DIR is not None:
        return _SANDBOX_DIR

    from config import config

    # 路径必须**固定**，不能用 mkdtemp：`page_fingerprint.py` 要求同一份代码跑两次
    # 得出同一个指纹，而高级设置页会把 CS2 目录原样显示出来。随机目录名会让
    # 指纹每次都不同，于是"页面变了"这个信号彻底失效。
    sandbox = sandbox_dir()
    # 建出 CS2 的目录形状，写入方 os.makedirs 也能自己建，但先建好更接近真实布局
    (sandbox / "game" / "csgo" / "cfg").mkdir(parents=True, exist_ok=True)

    real = getattr(config, "csgo_dir", "") or ""
    config.csgo_dir = str(sandbox)
    _SANDBOX_DIR = sandbox

    if verbose:
        print(f"   已沙箱化 CS2 游戏目录写入: {sandbox}")
        # 隔离配置一旦被保存过，csgo_dir 里存的就已经是沙箱路径了——
        # 这时再打印"探测到的真实目录"只会误导人
        if real and Path(real) != sandbox:
            print(f"   （探测到的真实目录 {real} 本次不会被写入）")
    return sandbox
