# SPDX-License-Identifier: GPL-3.0-or-later
"""测试共用件：别让模块单例 `config.config` 排着的保存落进下一个用例的目录。

⛔ `Config._do_save_config` 写的是 `get_config_path()` —— **调用那一刻**读
   `CS2C_CONFIG_DIR`。上一个用例让单例排了一个 0.5s 的防抖保存，这个用例
   setenv 到 tmp_path 之后它才到点 ⇒ 单例的旧状态写进本用例的 config.json，
   还吃掉判据造的写盘失败（2026-09-23 实测：并行 6 路 120 次里 13 次）。
⭐ 先只修在了一份判据里；另两份（退出写盘、闪光参数）同样先 setenv 再读盘 ⇒
   挪到这里，由 conftest 每个用例开跑前调一次。
"""
import sys
import threading


def flush_config_singletons_pending_save():
    """单例有排着的防抖保存就立即写进**它自己当下的**目录；定时器已在跑就等它跑完。

    没 import 过 config 就什么都不做（不为了清理去触发一次 import）。
    """
    mod = sys.modules.get("config")
    single = getattr(mod, "config", None) if mod is not None else None
    timer = getattr(single, "_save_timer", None) if single is not None else None
    if timer is None:
        return
    single.save_config_now()
    if isinstance(timer, threading.Thread) and timer is not threading.current_thread():
        timer.join(timeout=5.0)
