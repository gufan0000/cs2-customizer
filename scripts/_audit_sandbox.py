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

**中和方式**（两半，缺一不可）：

1. 把 `config.csgo_dir` 指到临时目录。不是置空——置空会让页面走
   「未配置 CS2 目录」分支，UI 文案和布局跟着变，等于把被审计对象改掉了。
   指向一个真实存在的空目录，页面照常走"已配置"分支，写操作落在临时目录里。
2. **掐掉配置落盘**（`block_config_persistence`）。第 1 步改的只是内存里的值，
   而审计过程中有三条路会把整份配置写回磁盘，于是沙箱路径被刻进用户的
   真实配置。这半截 R9-A 漏了，2026-08-16 才补。详见该函数的注释。

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
_SAVES_BLOCKED = False
#: 被换掉的原始落盘函数，供 `restore_config_persistence()` 还原。
#: 审计脚本用不到还原（跑完就退进程），但**测试用得到**：本模块在同一个
#: pytest 进程里被调过一次之后，配置就再也存不了盘了，后面任何验"改了配置
#: 能存回去"的用例都会红——而且红在别的文件里，单跑那个文件还是绿的。
_ORIGINAL_SAVERS: dict = {}

#: 审计期间被掐掉的配置落盘入口。三个都要掐：
#: `save_config` 是防抖入口，`save_config_now` 是关窗/退出用的同步入口，
#: `_do_save_config` 是真正写盘的那个（防抖 timer 和 atexit 兜底都直接调它）。
_SAVE_ENTRY_POINTS = ("save_config", "save_config_now", "_do_save_config")


def sandbox_dir() -> Path:
    """沙箱目录的路径（不建目录、不改配置），供调用方在动手之前先检查它。"""
    override = os.environ.get(SANDBOX_DIR_ENV)
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "cs2customizer_audit_game_sandbox"


def block_config_persistence(verbose: bool = True) -> None:
    """掐掉配置落盘：审计**只许读，不许写**。幂等。

    ⚠ 这是 UP-090 漏掉的下半截，2026-08-16 才补上，中间一直在悄悄发生。

    上面那半截只把 `config.csgo_dir` 改成沙箱路径，**改的是内存里的值**。
    可审计跑起来之后还会走这三条路把整份配置写回磁盘：

      1. 建准心页时 `_on_style_changed` / `_on_color_changed` 被信号连带触发
         → `config.save_config()`（防抖 500ms）
      2. 收尾时 `magnifier_page.cleanup()` → `save_settings()` → `save_config()`
      3. `gui_widget.closeEvent` 的退出步骤 → `config.save_config_now()`

    而 `_do_save_config` 写的是**整份配置**——于是沙箱那条 `csgo_dir` 被
    原样刻进用户真实的 `%LOCALAPPDATA%\\CS2Customizer\\config.json`。
    实测后果：用户的 CS2 目录变成 `%TEMP%\\cs2customizer_audit_game_sandbox`，
    软件下次启动就对着一个临时目录写 cfg，而 Windows 随时会清掉它。

    最阴的是这个函数原来的日志里写着「隔离配置一旦被保存过，csgo_dir 里
    存的就已经是沙箱路径了」——**症状被看见过，还被当成正常现象解释掉了。**
    """
    global _SAVES_BLOCKED
    if _SAVES_BLOCKED:
        return
    from config import config

    # 先把可能已经排上队的防抖 timer 掐掉，否则它会在 0.5s 后自己写盘，
    # 而 atexit 兜底也认这个 timer（`_atexit_flush` 只在有 pending 时才 flush）。
    try:
        with config._save_lock:
            if getattr(config, "_save_timer", None) is not None:
                config._save_timer.cancel()
                config._save_timer = None
    except Exception:
        pass

    def _refuse(*_args, **_kwargs):
        return None

    _refuse.__doc__ = "审计沙箱：配置落盘已被禁用（scripts/_audit_sandbox.py）"
    for name in _SAVE_ENTRY_POINTS:
        _ORIGINAL_SAVERS[name] = getattr(config, name)
        setattr(config, name, _refuse)
    _SAVES_BLOCKED = True
    if verbose:
        print("   已禁止审计期间的配置落盘（审计只读）")


def restore_config_persistence() -> None:
    """把落盘入口还回去。审计脚本用不着（跑完就退），测试收尾必须调。"""
    global _SAVES_BLOCKED
    if not _SAVES_BLOCKED:
        return
    from config import config

    for name, func in _ORIGINAL_SAVERS.items():
        setattr(config, name, func)
    _ORIGINAL_SAVERS.clear()
    _SAVES_BLOCKED = False


def sandbox_external_writes(verbose: bool = True) -> Path:
    """把 `config.csgo_dir` 重定向到临时目录并掐掉配置落盘，返回该目录。幂等。"""
    global _SANDBOX_DIR
    if _SANDBOX_DIR is not None:
        return _SANDBOX_DIR

    from config import config

    # 顺序要紧：先掐落盘再改 csgo_dir。反过来的话，中间那一瞬如果有别的线程
    # 触发保存，沙箱路径照样会被写出去。
    block_config_persistence(verbose=verbose)

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
        # 这里读到的 real 可能本身就是沙箱路径——那说明**某一次审计已经把它写脏了**，
        # 需要用户手工改回真实 CS2 目录（本函数不替用户改配置）。
        # 这条注释原来写的是「隔离配置一旦被保存过就是这样，属正常」——错的，
        # 见 block_config_persistence 的说明。
        if real and Path(real) != sandbox:
            print(f"   （探测到的真实目录 {real} 本次不会被写入）")
    return sandbox
