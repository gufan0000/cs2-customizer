# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""退出守护（RN-706① / RN-625，来历见档案 B129）： CS2 Customizer 被强杀 / 看门狗 `os._exit` 后，把压下去的游戏音量还回去。

- **懒起**：压声后端第一次把状态写进 `gun_sound_duck_state.json` 才起；不用压声的人零成本。
- multiprocessing 子进程（同闪光进程的起法），只**等父进程消失**，然后看状态文件：
  不在 = 正常退出已恢复，什么都不做；在 = 没来得及恢复，用压声后端自己的「陈旧状态修复」还回去
  （要恢复哪几个进程也从文件里读，不读用户配置）。
- `daemon=True`：正常退出由 multiprocessing 收掉、不卡退出；强杀时钩子不跑，它正好接手。
- 起进程在小线程里做：第一次压声在 GSI 线程的开枪路径上，不许为它等一次 CreateProcess。
⛔ 守护里不 import Qt、不写配置、不连网。
"""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_process = None
_starting = False


class _FixedTargets:
    """守护进程里的「配置」：只回答要恢复哪几个进程（来自状态文件），其余一律用默认值。"""

    def __init__(self, names):
        self.gun_sound_duck_target_processes = sorted(names)

    def __getattr__(self, name):
        return None


def _log(line: str) -> None:
    """守护自己的小日志（`runtime/exit_guardian.log`）：它在父进程死后才干活，没有别的地方能看见它做了什么。"""
    try:
        from core.audio.game_audio_ducker import _SessionAudioBackend

        path = os.path.join(os.path.dirname(_SessionAudioBackend._resolve_state_path(None)), "exit_guardian.log")
        import time

        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%m-%d %H:%M:%S')} [{os.getpid()}] {line}\n")
    except Exception:
        pass


def restore_after_parent_death() -> int:
    """父进程已不在：状态文件还在就恢复。返回状态文件里记着的会话数（没有状态文件返回 0）。"""
    # 用压声那一层（会话音量后端）自己的「陈旧状态修复」—— 状态文件格式和恢复条件只有它一份
    from core.audio.game_audio_ducker import _SessionAudioBackend

    probe = _SessionAudioBackend(cfg=_FixedTargets(()))
    payload = probe._stale_state
    if not payload:
        _log("父进程已退出；没有压声状态文件（正常退出已恢复，或从没压过）")
        return 0
    names = {str(item.get("process_name", "") or "").strip().lower()
             for item in payload.get("sessions", []) if isinstance(item, dict)}
    names.discard("")
    if not names:
        return 0
    ducker = _SessionAudioBackend(cfg=_FixedTargets(names))
    ducker.recovery_trace = []
    ducker._ensure_com_initialized()
    ducker._scan_sessions(refresh=True)        # 扫到目标会话时就地走「陈旧状态修复」
    _log(f"父进程已退出；状态文件 {sorted(names)}；会话（名, 当前, 压低目标, 原值）{ducker.recovery_trace}；"
         f"还回 {ducker.recovered_count} 个")
    return len(names)


def _guardian_main() -> None:
    """子进程入口：等父进程死，再按状态文件把音量还回去。"""
    import multiprocessing as mp

    parent = mp.parent_process()
    if parent is None:
        return
    _log(f"守护已起，盯着父进程 {parent.pid}")
    try:
        from multiprocessing.connection import wait

        wait([parent.sentinel])
    except Exception:
        return
    try:
        restore_after_parent_death()
    except Exception as exc:
        _log(f"恢复时出错：{exc!r}")


def _spawn() -> None:
    global _process, _starting
    try:
        from multiprocessing import Process

        proc = Process(target=_guardian_main, name="Cs2customizerExitGuardian", daemon=True)
        proc.start()
        with _lock:
            _process = proc
    except Exception as exc:
        _log(f"起守护进程失败：{exc!r}")
    finally:
        with _lock:
            _starting = False


def ensure_started() -> bool:
    """第一次真的压了音量时调用；幂等、不阻塞。起不来不影响主功能（只是少了兜底）。"""
    global _starting
    if os.environ.get("CS2C_NO_EXIT_GUARDIAN") == "1":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # 判据里压声是假会话，不许为它真起一个盯着测试进程的子进程（它会在测试进程退出后去碰真音量）
        return False
    with _lock:
        if _starting or (_process is not None and _process.is_alive()):
            return True
        _starting = True
    threading.Thread(target=_spawn, name="ExitGuardianSpawn", daemon=True).start()
    return True


def is_running() -> bool:
    with _lock:
        return _process is not None and _process.is_alive()
