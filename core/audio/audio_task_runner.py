# SPDX-License-Identifier: GPL-3.0-or-later
"""Async audio maintenance task queue with Qt signals."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List

from PySide6.QtCore import QObject, Signal

from config import config
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger


@dataclass
class _Task:
    task_id: str
    task_type: str
    reason: str
    fn: Callable[["_Task"], None]
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    success: bool = False
    message: str = ""


class AudioTaskRunner(QObject):
    """Single-worker FIFO task queue for audio reload/refresh jobs."""

    task_started = Signal(str, str)  # task_id, reason
    task_progress = Signal(str, int, str)  # task_id, 0~100, message
    task_finished = Signal(str, bool, str)  # task_id, success, message

    def __init__(self):
        super().__init__()
        self.logger = get_logger("AudioTaskRunner")
        self._lock = threading.Lock()
        self._queue: Deque[_Task] = deque()
        self._history: List[Dict[str, object]] = []
        self._worker_thread: threading.Thread | None = None
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def get_history(self, limit: int = 100) -> List[Dict[str, object]]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._history[-limit:])

    def submit_reload_audio_task(self, reason: str) -> str:
        return self._submit_task("reload_audio", reason, self._run_reload_audio)

    def submit_import_refresh_task(self, reason: str) -> str:
        return self._submit_task("import_refresh", reason, self._run_import_refresh)

    def _submit_task(self, task_type: str, reason: str, fn: Callable[["_Task"], None]) -> str:
        task_id = uuid.uuid4().hex[:12]
        task = _Task(
            task_id=task_id,
            task_type=task_type,
            reason=str(reason or task_type),
            fn=fn,
        )
        with self._lock:
            self._queue.append(task)
        self._ensure_worker()
        self.logger.info(f"[AudioTask] queued: {task.task_id} {task.task_type} ({task.reason})")
        return task_id

    def _ensure_worker(self):
        with self._lock:
            thread = self._worker_thread
            if thread and thread.is_alive():
                return
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="AudioTaskRunner")
            self._worker_thread.start()

    def _worker_loop(self):
        while not self._stop_flag:
            with self._lock:
                if self._queue:
                    task = self._queue.popleft()
                else:
                    # 退出决策与线程引用清理必须同锁原子完成：否则"判空后、
                    # 线程真正退出前"入队的任务既不被取走也不会触发新 worker
                    self._worker_thread = None
                    return
            self._execute_task(task)

    def _execute_task(self, task: _Task):
        task.started_at = time.time()
        self.task_started.emit(task.task_id, task.reason)
        self.task_progress.emit(task.task_id, 1, "任务开始")
        self.logger.info(f"[AudioTask] started: {task.task_id} {task.task_type}")

        try:
            task.fn(task)
            task.success = True
            if not task.message:
                task.message = "任务完成"
            self.task_progress.emit(task.task_id, 100, task.message)
        except Exception as exc:
            task.success = False
            task.message = f"{exc}"
            self.task_progress.emit(task.task_id, 100, task.message)
            self.logger.error(f"[AudioTask] failed: {task.task_id} {task.task_type}: {exc}", exc_info=True)
        finally:
            task.finished_at = time.time()
            self.task_finished.emit(task.task_id, task.success, task.message)
            self._push_history(task)
            self.logger.info(
                f"[AudioTask] finished: {task.task_id} success={task.success} "
                f"cost={task.finished_at - task.started_at:.2f}s message={task.message}"
            )

    def _push_history(self, task: _Task):
        entry = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "reason": task.reason,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "duration": max(0.0, task.finished_at - task.started_at),
            "success": task.success,
            "message": task.message,
        }
        with self._lock:
            self._history.append(entry)
            if len(self._history) > 300:
                self._history = self._history[-300:]

    def _run_reload_audio(self, task: _Task):
        manager = get_runtime_audio_manager()
        self.task_progress.emit(task.task_id, 20, "重置样式扫描状态")
        if hasattr(manager, "_styles_scanned"):
            manager._styles_scanned = False
        self.task_progress.emit(task.task_id, 45, "扫描音频资源目录")
        manager.ensure_styles_scanned()
        self.task_progress.emit(task.task_id, 75, "加载启用的音效资源")
        manager.load_all_enabled_sounds()
        self.task_progress.emit(task.task_id, 90, "写入配置")
        if hasattr(config, "save_config_now"):
            config.save_config_now()
        else:
            config.save_config()
        task.message = "音频资源重载完成"

    def _run_import_refresh(self, task: _Task):
        manager = get_runtime_audio_manager()
        self.task_progress.emit(task.task_id, 25, "刷新导入后的样式索引")
        if hasattr(manager, "_styles_scanned"):
            manager._styles_scanned = False
        manager.ensure_styles_scanned()
        self.task_progress.emit(task.task_id, 65, "预加载当前启用音效")
        manager.load_all_enabled_sounds()
        self.task_progress.emit(task.task_id, 90, "保存配置")
        if hasattr(config, "save_config_now"):
            config.save_config_now()
        else:
            config.save_config()
        task.message = "导入后刷新完成"


_runner_lock = threading.Lock()
_runner_instance: AudioTaskRunner | None = None


def get_audio_task_runner() -> AudioTaskRunner:
    global _runner_instance
    if _runner_instance is None:
        with _runner_lock:
            if _runner_instance is None:
                _runner_instance = AudioTaskRunner()
    return _runner_instance


def submit_reload_audio_task(reason: str) -> str:
    return get_audio_task_runner().submit_reload_audio_task(reason)


def submit_import_refresh_task(reason: str) -> str:
    return get_audio_task_runner().submit_import_refresh_task(reason)

