# -*- coding: utf-8 -*-
"""D2：单实例互斥锁。

目的：防止同一台机器同时运行两份帆派助手——双开会导致：
- Flask GSI 抢同一个 127.0.0.1:3000 端口
- 全局热键（keyboard/mouse hook）被双份处理
- config.json 读写互相覆盖
- pygame.mixer / VB-Cable 音频设备竞争

设计：
- 使用 Qt 原生 `QLockFile`（无新依赖）
- 锁文件放在用户 temp 目录 → ``%TEMP%\\FanTool_single_instance.lock``
- 30 秒 stale 超时：进程异常退出后，30 秒后其他实例可自动接管
- 任何异常都 **默认放行**：锁机制自身的 bug 绝不能把用户锁在门外

使用方式（见 main_widget.py）：

    from core.single_instance import ensure_single_instance
    ok, lock, msg = ensure_single_instance()
    if not ok:
        # 已有实例在跑，友好提示后退出
        QMessageBox.information(None, "帆派助手", msg)
        sys.exit(0)
    # 把 lock 挂到 app 上，整个进程期间持有
    app._single_instance_lock = lock

注意：
- `lock` 必须在进程生命周期内持续引用，否则被 GC 释放 → 锁失效
- `QLockFile` 会在进程退出时自动释放（即使是 kill -9）
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Optional, Tuple

LOCK_FILENAME = "FanTool_single_instance.lock"
STALE_TIMEOUT_MS = 30_000  # 30 秒


def _resolve_lock_path() -> str:
    """确定锁文件路径。优先用 %TEMP%（Windows）/ /tmp（POSIX）。"""
    try:
        return os.path.join(tempfile.gettempdir(), LOCK_FILENAME)
    except Exception:
        # 极端兜底
        return LOCK_FILENAME


def ensure_single_instance(
    lock_path: Optional[str] = None,
    stale_timeout_ms: int = STALE_TIMEOUT_MS,
) -> Tuple[bool, Optional[Any], str]:
    """检测是否已有帆派助手实例在运行。

    返回 ``(ok, lock, message)``：
    - ``ok=True``  当前进程拿到锁，可继续启动；``lock`` 是 QLockFile 对象，
      **必须由调用方保持强引用**，否则被 GC 回收会导致锁失效。
    - ``ok=False`` 已有实例在运行；``message`` 是可展示给用户的说明文本。
    - 任何内部异常都会 **默认放行**（返回 ok=True, lock=None），保证锁机制
      自身 bug 永远不会把用户锁在门外。
    """
    target = lock_path or _resolve_lock_path()

    # 延迟 import，避免在 PySide6 还没 import 时触发
    try:
        from PySide6.QtCore import QLockFile
    except Exception:
        # PySide6 不可用（理论上不会）——放行
        return True, None, ""

    try:
        lock = QLockFile(target)
        # 超过 stale_timeout_ms 的锁认为是残留，允许强制清理
        try:
            lock.setStaleLockTime(int(stale_timeout_ms))
        except Exception:
            pass

        # tryLock(0) 立即返回；我们给 100ms 缓冲
        acquired = lock.tryLock(100)
        if acquired:
            return True, lock, ""

        # 没拿到锁 → 已有实例
        msg = (
            "帆派助手已在运行中。\n\n"
            "如果你在任务栏找不到窗口，可以：\n"
            "  1. 检查系统托盘是否有帆派图标\n"
            "  2. 打开任务管理器结束现有进程后再启动\n"
            f"  3. 或等待 {stale_timeout_ms // 1000} 秒后重试（残留锁会自动清理）"
        )
        return False, lock, msg
    except Exception:
        # 锁机制自身异常 → 放行，让用户能用
        return True, None, ""
