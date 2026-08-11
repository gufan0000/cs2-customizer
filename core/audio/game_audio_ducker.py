from __future__ import annotations

import atexit
import json
import os
import threading
import time

from config import config
from core.utils.logger import get_logger


DEFAULT_GUN_SOUND_DUCK_RATIO = 0.18
DEFAULT_GUN_SOUND_DUCK_ATTACK_MS = 0
DEFAULT_GUN_SOUND_DUCK_RELEASE_MS = 120
DEFAULT_TARGET_PROCESS_NAMES = ("cs2.exe", "csgo.exe")


def clamp_gun_sound_duck_ratio(value, fallback: float = DEFAULT_GUN_SOUND_DUCK_RATIO) -> float:
    try:
        numeric = float(value)
    except Exception:
        return fallback
    return max(0.0, min(1.0, numeric))


def clamp_gun_sound_duck_time_ms(value, fallback: int) -> int:
    try:
        numeric = int(float(value))
    except Exception:
        return fallback
    return max(0, min(2000, numeric))


class _SessionAudioBackend:
    kind = "session"
    supports_dynamic_level = True

    def __init__(self, cfg=None, logger=None):
        self._config = cfg or config
        self._logger = logger or get_logger("GameAudioDucker")
        self._lock = threading.Lock()
        # 扫描串行化：duck 与 restore 可能从不同线程并发进入 _scan_sessions，
        # 无锁时会并发改写 _cached_sessions / 陈旧状态恢复互相打架
        self._scan_lock = threading.RLock()
        self._audio_utilities = None
        self._import_failed = False
        self._import_error_logged = False
        self._cached_sessions: list[tuple[str, object, str]] = []
        self._last_scan_time = 0.0
        self._transition_token = 0
        self._ducked_sessions: dict[str, dict[str, object]] = {}
        self._state_path = self._resolve_state_path()
        self._stale_state = self._load_stale_state()
        # 2.1.4: COM 每线程初始化标记（GSI 工作线程里调 pycaw 前必须 CoInitialize，
        # 否则在 Qt(STA) 主线程已占用 COM 的进程里会报
        # "argument 5: TypeError: expected LP_LPVOID..."，导致会话扫描一直失败、
        # Ducking 退化到兜底模式）
        self._com_initialized_threads = threading.local()

    def _ensure_com_initialized(self):
        """确保当前线程已做 COM 初始化（幂等，每线程一次）。"""
        if getattr(self._com_initialized_threads, "done", False):
            return
        try:
            import comtypes

            comtypes.CoInitialize()
        except Exception:
            # 已初始化(RPC_E_CHANGED_MODE等)或环境缺 comtypes——继续走原逻辑
            pass
        self._com_initialized_threads.done = True

    def _resolve_state_path(self) -> str:
        appdata_dir = os.environ.get("LOCALAPPDATA")
        if appdata_dir:
            runtime_dir = os.path.join(appdata_dir, "FanTool", "runtime")
        else:
            runtime_dir = os.path.join(os.getcwd(), ".runtime")
        os.makedirs(runtime_dir, exist_ok=True)
        return os.path.join(runtime_dir, "gun_sound_duck_state.json")

    def _clear_runtime_state_locked(self) -> None:
        try:
            if os.path.exists(self._state_path):
                os.remove(self._state_path)
        except Exception:
            pass
        self._stale_state = None

    def _write_runtime_state_locked(self) -> None:
        if not self._ducked_sessions:
            self._clear_runtime_state_locked()
            return

        payload = {
            "timestamp": time.time(),
            "sessions": [
                {
                    "process_name": str(state.get("process_name", "") or "").lower(),
                    "original": float(state.get("original", 1.0)),
                    "ducked": float(state.get("ducked", 0.0)),
                }
                for state in self._ducked_sessions.values()
                if state.get("volume") is not None
            ],
        }
        if not payload["sessions"]:
            self._clear_runtime_state_locked()
            return
        try:
            with open(self._state_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            self._logger.debug(f"写入 Ducking 状态失败: {exc}")

    def _load_stale_state(self):
        try:
            if not os.path.exists(self._state_path):
                return None
            with open(self._state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return None

        try:
            timestamp = float(payload.get("timestamp", 0.0))
        except Exception:
            timestamp = 0.0
        if timestamp <= 0 or (time.time() - timestamp) > 12 * 3600:
            try:
                os.remove(self._state_path)
            except Exception:
                pass
            return None

        sessions = payload.get("sessions", [])
        if not isinstance(sessions, list) or not sessions:
            return None
        return payload

    def _recover_stale_state_if_needed(self, sessions: list[tuple[str, object, str]]) -> None:
        payload = self._stale_state
        if not payload or not sessions:
            return

        records_by_process: dict[str, dict[str, float]] = {}
        for item in payload.get("sessions", []):
            process_name = str(item.get("process_name", "") or "").strip().lower()
            if not process_name:
                continue
            original = clamp_gun_sound_duck_ratio(item.get("original", 1.0), 1.0)
            ducked = clamp_gun_sound_duck_ratio(item.get("ducked", 0.0), 0.0)
            record = records_by_process.get(process_name)
            if record is None:
                records_by_process[process_name] = {"original": original, "ducked": ducked}
            else:
                record["original"] = max(record["original"], original)
                record["ducked"] = min(record["ducked"], ducked)

        recovered = 0
        for _session_key, volume, process_name in sessions:
            record = records_by_process.get(str(process_name or "").lower())
            if not record:
                continue
            original = float(record["original"])
            ducked = float(record["ducked"])
            if original <= ducked + 0.03:
                continue
            try:
                current = float(volume.GetMasterVolume())
            except Exception:
                continue
            if current <= ducked + 0.05 and current < original - 0.05:
                if self._set_volume(volume, original):
                    recovered += 1

        if recovered:
            self._logger.warning(f"检测到上次未恢复的游戏音量，已自动修复 {recovered} 个音频会话")

        # 状态文件读写与 _write_runtime_state_locked（在 self._lock 下调用）互斥
        with self._lock:
            self._clear_runtime_state_locked()

    def _target_process_names(self) -> set[str]:
        configured = getattr(self._config, "gun_sound_duck_target_processes", None)
        if isinstance(configured, (list, tuple, set)):
            names = {
                str(name).strip().lower()
                for name in configured
                if str(name).strip()
            }
            if names:
                return names
        return set(DEFAULT_TARGET_PROCESS_NAMES)

    def _attack_ms(self) -> int:
        return clamp_gun_sound_duck_time_ms(
            getattr(self._config, "gun_sound_duck_attack_ms", DEFAULT_GUN_SOUND_DUCK_ATTACK_MS),
            DEFAULT_GUN_SOUND_DUCK_ATTACK_MS,
        )

    def _release_ms(self) -> int:
        return clamp_gun_sound_duck_time_ms(
            getattr(self._config, "gun_sound_duck_release_ms", DEFAULT_GUN_SOUND_DUCK_RELEASE_MS),
            DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
        )

    def _import_audio_utilities(self):
        if self._audio_utilities is not None:
            return self._audio_utilities
        if self._import_failed:
            return None
        try:
            from pycaw.pycaw import AudioUtilities
        except Exception as exc:
            self._import_failed = True
            if not self._import_error_logged:
                self._logger.info(f"未检测到 pycaw，枪声 Ducking 将回退到热键模式: {exc}")
                self._import_error_logged = True
            return None

        self._audio_utilities = AudioUtilities
        return self._audio_utilities

    @staticmethod
    def _session_key(session) -> str:
        process = getattr(session, "Process", None)
        process_name = ""
        process_id = "unknown"
        if process is not None:
            try:
                process_name = os.path.basename(process.name() or "").lower()
            except Exception:
                process_name = ""
            try:
                process_id = str(process.pid)
            except Exception:
                process_id = "unknown"
        display_name = str(getattr(session, "DisplayName", "") or "").strip()
        return f"{process_id}:{process_name}:{display_name}"

    def _scan_sessions(self, refresh: bool = False) -> list[tuple[str, object, str]]:
        with self._scan_lock:
            return self._scan_sessions_locked(refresh)

    def _scan_sessions_locked(self, refresh: bool = False) -> list[tuple[str, object, str]]:
        audio_utilities = self._import_audio_utilities()
        if audio_utilities is None:
            return []

        now = time.monotonic()
        if not refresh and self._cached_sessions and (now - self._last_scan_time) < 1.0:
            return list(self._cached_sessions)

        target_processes = self._target_process_names()
        matches: list[tuple[str, object, str]] = []
        try:
            self._ensure_com_initialized()
            sessions = audio_utilities.GetAllSessions() or []
        except Exception as exc:
            self._logger.debug(f"扫描游戏音频会话失败: {exc}")
            return list(self._cached_sessions)

        for session in sessions:
            process = getattr(session, "Process", None)
            if process is None:
                continue

            try:
                process_name = os.path.basename(process.name() or "").lower()
            except Exception:
                continue

            if process_name not in target_processes:
                continue

            try:
                volume = session.SimpleAudioVolume
                volume.GetMasterVolume()
            except Exception:
                continue

            matches.append((self._session_key(session), volume, process_name))

        if matches:
            self._recover_stale_state_if_needed(matches)
        self._cached_sessions = matches
        self._last_scan_time = now
        return list(matches)

    def is_available(self) -> bool:
        if self._ducked_sessions:
            return True
        return bool(self._scan_sessions())

    def _set_volume(self, volume, value: float) -> bool:
        try:
            volume.SetMasterVolume(max(0.0, min(1.0, float(value))), None)
            return True
        except Exception:
            return False

    def _run_transition(
        self,
        transitions: list[tuple[object, float, float]],
        duration_ms: int,
        token: int,
        *,
        clear_on_complete: bool,
    ) -> None:
        if not transitions:
            if clear_on_complete:
                with self._lock:
                    if token == self._transition_token:
                        self._ducked_sessions.clear()
                        self._clear_runtime_state_locked()
            return

        if duration_ms <= 0:
            for volume, _start, end in transitions:
                self._set_volume(volume, end)
            if clear_on_complete:
                with self._lock:
                    if token == self._transition_token:
                        self._ducked_sessions.clear()
                        self._clear_runtime_state_locked()
            return

        steps = max(1, min(12, int(duration_ms / 15) or 1))
        sleep_seconds = max(0.005, duration_ms / steps / 1000.0)

        def worker():
            try:
                for step in range(1, steps + 1):
                    with self._lock:
                        if token != self._transition_token:
                            return
                    progress = step / steps
                    for volume, start, end in transitions:
                        value = start + ((end - start) * progress)
                        self._set_volume(volume, value)
                    time.sleep(sleep_seconds)
            finally:
                if clear_on_complete:
                    with self._lock:
                        if token == self._transition_token:
                            self._ducked_sessions.clear()
                            self._clear_runtime_state_locked()

        threading.Thread(target=worker, daemon=True).start()

    def start_duck(self, ratio: float, attack_ms: int | None = None) -> bool:
        ratio = clamp_gun_sound_duck_ratio(ratio)
        sessions = self._scan_sessions(refresh=not bool(self._cached_sessions))
        if not sessions and self._ducked_sessions:
            sessions = [
                (key, state.get("volume"), "")
                for key, state in self._ducked_sessions.items()
                if state.get("volume") is not None
            ]
        if not sessions:
            return False

        transitions: list[tuple[object, float, float]] = []
        with self._lock:
            self._transition_token += 1
            token = self._transition_token

            for key, volume, _process_name in sessions:
                try:
                    current = float(volume.GetMasterVolume())
                except Exception:
                    continue

                state = self._ducked_sessions.get(key)
                original = float(state["original"]) if state else current
                target = clamp_gun_sound_duck_ratio(original * ratio, fallback=0.0)
                self._ducked_sessions[key] = {
                    "original": original,
                    "ducked": target,
                    "volume": volume,
                    "process_name": _process_name,
                }
                transitions.append((volume, current, target))

            duration_ms = self._attack_ms() if attack_ms is None else clamp_gun_sound_duck_time_ms(attack_ms, self._attack_ms())
            self._write_runtime_state_locked()

        self._run_transition(transitions, duration_ms, token, clear_on_complete=False)
        return bool(transitions)

    def _build_restore_transitions(
        self,
        ducked_sessions: dict[str, dict[str, object]],
    ) -> list[tuple[object, float, float]]:
        transitions: list[tuple[object, float, float]] = []
        unresolved_by_process: dict[str, dict[str, float]] = {}

        for state in ducked_sessions.values():
            volume = state.get("volume")
            process_name = str(state.get("process_name", "") or "").strip().lower()
            try:
                original = float(state.get("original", 1.0))
            except Exception:
                original = 1.0
            ducked = clamp_gun_sound_duck_ratio(state.get("ducked", 0.0), 0.0)

            if volume is not None:
                try:
                    current = float(volume.GetMasterVolume())
                except Exception:
                    current = None
                else:
                    transitions.append((volume, current, original))
                    continue

            if not process_name:
                continue

            existing = unresolved_by_process.get(process_name)
            if existing is None:
                unresolved_by_process[process_name] = {"original": original, "ducked": ducked}
            else:
                existing["original"] = max(existing["original"], original)
                existing["ducked"] = min(existing["ducked"], ducked)

        if not unresolved_by_process:
            return transitions

        for _session_key, volume, process_name in self._scan_sessions(refresh=True):
            process_key = str(process_name or "").strip().lower()
            expected = unresolved_by_process.get(process_key)
            if not expected:
                continue

            try:
                current = float(volume.GetMasterVolume())
            except Exception:
                continue

            original = float(expected["original"])
            ducked = float(expected["ducked"])
            if current <= ducked + 0.05 and current < original - 0.05:
                transitions.append((volume, current, original))

        return transitions

    def restore(self, release_ms: int | None = None) -> bool:
        with self._lock:
            if not self._ducked_sessions:
                return False

            self._transition_token += 1
            token = self._transition_token
            ducked_snapshot = {
                key: dict(state)
                for key, state in self._ducked_sessions.items()
            }

            duration_ms = self._release_ms() if release_ms is None else clamp_gun_sound_duck_time_ms(release_ms, self._release_ms())

        transitions = self._build_restore_transitions(ducked_snapshot)
        self._run_transition(transitions, duration_ms, token, clear_on_complete=True)
        return True


class _HotkeyAudioBackend:
    kind = "hotkey"
    supports_dynamic_level = False

    def __init__(self, mute_callback, restore_callback):
        self._mute_callback = mute_callback
        self._restore_callback = restore_callback

    def is_available(self) -> bool:
        return callable(self._mute_callback) and callable(self._restore_callback)

    def start_duck(self, _ratio: float, attack_ms: int | None = None) -> bool:
        del attack_ms
        if not self.is_available():
            return False
        self._mute_callback()
        return True

    def restore(self, release_ms: int | None = None) -> bool:
        del release_ms
        if not self.is_available():
            return False
        self._restore_callback()
        return True


class GameAudioDucker:
    def __init__(
        self,
        cfg=None,
        logger=None,
        session_backend=None,
        fallback_backend=None,
        timer_factory=None,
        clock=None,
    ):
        self._config = cfg or config
        self._logger = logger or get_logger("GameAudioDucker")
        self._session_backend = session_backend or _SessionAudioBackend(cfg=self._config, logger=self._logger)
        self._fallback_backend = fallback_backend
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._restore_timer = None
        self._restore_token = 0
        self._stage_timer = None
        self._stage_token = 0
        self._hold_until = 0.0
        self._active_backend = None
        self._is_ducked = False
        self._current_release_ms = self._default_release_ms()
        atexit.register(self.close)

    def _ducking_enabled(self) -> bool:
        return bool(getattr(self._config, "gun_sound_ducking_enabled", True))

    def _allow_hotkey_fallback(self) -> bool:
        return bool(getattr(self._config, "gun_sound_duck_fallback_hotkey_mode", True))

    def _duck_ratio(self) -> float:
        return clamp_gun_sound_duck_ratio(
            getattr(self._config, "gun_sound_duck_ratio", DEFAULT_GUN_SOUND_DUCK_RATIO),
            DEFAULT_GUN_SOUND_DUCK_RATIO,
        )

    def _default_release_ms(self) -> int:
        return clamp_gun_sound_duck_time_ms(
            getattr(self._config, "gun_sound_duck_release_ms", DEFAULT_GUN_SOUND_DUCK_RELEASE_MS),
            DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
        )

    def _cancel_restore_timer_locked(self) -> None:
        if self._restore_timer is None:
            return
        try:
            self._restore_timer.cancel()
        except Exception:
            pass
        self._restore_timer = None

    def _cancel_stage_timer_locked(self) -> None:
        if self._stage_timer is None:
            return
        try:
            self._stage_timer.cancel()
        except Exception:
            pass
        self._stage_timer = None

    def _resolve_backend_locked(self):
        if self._ducking_enabled() and self._session_backend and self._session_backend.is_available():
            return self._session_backend
        if self._allow_hotkey_fallback() and self._fallback_backend and self._fallback_backend.is_available():
            return self._fallback_backend
        return None

    def _apply_duck_level_locked(self, ratio: float | None = None, attack_ms: int | None = None) -> bool:
        backend = self._resolve_backend_locked()
        if backend is None:
            return False

        resolved_ratio = self._duck_ratio() if ratio is None else clamp_gun_sound_duck_ratio(ratio, self._duck_ratio())

        if self._is_ducked and self._active_backend is backend:
            if getattr(backend, "supports_dynamic_level", False):
                started = backend.start_duck(resolved_ratio, attack_ms=attack_ms)
                if started:
                    return True
            else:
                return True

        if self._is_ducked and self._active_backend is not None and self._active_backend is not backend:
            try:
                self._active_backend.restore(self._current_release_ms)
            except Exception:
                pass
            self._active_backend = None
            self._is_ducked = False

        started = backend.start_duck(resolved_ratio, attack_ms=attack_ms)
        if not started and backend is not self._fallback_backend and self._allow_hotkey_fallback():
            fallback = self._fallback_backend
            if fallback is not None and fallback.is_available():
                backend = fallback
                started = backend.start_duck(resolved_ratio, attack_ms=attack_ms)

        if not started:
            self._active_backend = None
            self._is_ducked = False
            return False

        self._active_backend = backend
        self._is_ducked = True
        return True

    def start_duck(self, *, ratio: float | None = None, attack_ms: int | None = None) -> bool:
        with self._lock:
            return self._apply_duck_level_locked(ratio=ratio, attack_ms=attack_ms)

    def hold_for(
        self,
        delay: float,
        *,
        peak_ratio: float | None = None,
        peak_ms: int = 0,
        sustain_ratio: float | None = None,
        release_ms: int | None = None,
        attack_ms: int | None = None,
    ) -> bool:
        return self.duck_for(
            delay,
            peak_ratio=peak_ratio,
            peak_ms=peak_ms,
            sustain_ratio=sustain_ratio,
            release_ms=release_ms,
            attack_ms=attack_ms,
        )

    def duck_for(
        self,
        delay: float,
        *,
        peak_ratio: float | None = None,
        peak_ms: int = 0,
        sustain_ratio: float | None = None,
        release_ms: int | None = None,
        attack_ms: int | None = None,
    ) -> bool:
        with self._lock:
            try:
                normalized_delay = max(0.0, float(delay))
            except Exception:
                normalized_delay = 0.0

            sustain = self._duck_ratio() if sustain_ratio is None else clamp_gun_sound_duck_ratio(sustain_ratio, self._duck_ratio())
            initial = sustain
            if peak_ratio is not None:
                initial = min(sustain, clamp_gun_sound_duck_ratio(peak_ratio, sustain))

            if not self._apply_duck_level_locked(ratio=initial, attack_ms=attack_ms):
                return False

            self._hold_until = max(self._hold_until, self._clock() + normalized_delay)
            resolved_release_ms = self._default_release_ms() if release_ms is None else clamp_gun_sound_duck_time_ms(release_ms, self._default_release_ms())
            self._current_release_ms = max(self._current_release_ms, resolved_release_ms)

            self._schedule_stage_locked(
                delay_ms=max(0, int(peak_ms)),
                sustain_ratio=sustain,
                attack_ms=attack_ms,
                use_peak=peak_ratio is not None and initial < sustain,
            )
            self._schedule_restore_locked()
            return True

    def _schedule_stage_locked(
        self,
        *,
        delay_ms: int,
        sustain_ratio: float,
        attack_ms: int | None,
        use_peak: bool,
    ) -> None:
        self._cancel_stage_timer_locked()
        if not use_peak or delay_ms <= 0:
            return

        self._stage_token += 1
        token = self._stage_token
        timer = self._timer_factory(delay_ms / 1000.0, lambda: self._apply_sustain_level_when_due(token, sustain_ratio, attack_ms))
        timer.daemon = True
        self._stage_timer = timer
        timer.start()

    def _apply_sustain_level_when_due(self, token: int, sustain_ratio: float, attack_ms: int | None) -> None:
        with self._lock:
            if token != self._stage_token:
                return
            self._stage_timer = None
            if not self._is_ducked or self._active_backend is None:
                return
            if getattr(self._active_backend, "supports_dynamic_level", False):
                try:
                    self._active_backend.start_duck(sustain_ratio, attack_ms=attack_ms)
                except Exception:
                    return

    def _schedule_restore_locked(self) -> None:
        self._cancel_restore_timer_locked()
        remaining = max(0.0, self._hold_until - self._clock())
        self._restore_token += 1
        token = self._restore_token
        timer = self._timer_factory(remaining, lambda: self._restore_when_due(token))
        timer.daemon = True
        self._restore_timer = timer
        timer.start()

    def _restore_when_due(self, token: int) -> None:
        with self._lock:
            if token != self._restore_token:
                return

            remaining = self._hold_until - self._clock()
            if remaining > 0.01:
                self._restore_timer = None
                self._schedule_restore_locked()
                return

            self._restore_timer = None
            self._cancel_stage_timer_locked()
            self._hold_until = 0.0
            if self._active_backend is not None and self._is_ducked:
                try:
                    self._active_backend.restore(self._current_release_ms)
                except Exception:
                    pass
            self._active_backend = None
            self._is_ducked = False
            self._current_release_ms = self._default_release_ms()

    def restore(self) -> bool:
        with self._lock:
            self._cancel_restore_timer_locked()
            self._cancel_stage_timer_locked()
            self._hold_until = 0.0
            if self._active_backend is None or not self._is_ducked:
                return False
            try:
                restored = self._active_backend.restore(self._current_release_ms)
            finally:
                self._active_backend = None
                self._is_ducked = False
                self._current_release_ms = self._default_release_ms()
            return bool(restored)

    def is_ducked(self) -> bool:
        with self._lock:
            return bool(self._is_ducked)

    def close(self) -> None:
        with self._lock:
            self._cancel_restore_timer_locked()
            self._cancel_stage_timer_locked()
            self._hold_until = 0.0
            if self._active_backend is not None and self._is_ducked:
                try:
                    self._active_backend.restore(0)
                except Exception:
                    pass
            self._active_backend = None
            self._is_ducked = False
            self._current_release_ms = self._default_release_ms()


def build_hotkey_ducker(mute_callback, restore_callback, cfg=None, logger=None, **kwargs) -> GameAudioDucker:
    return GameAudioDucker(
        cfg=cfg or config,
        logger=logger,
        fallback_backend=_HotkeyAudioBackend(mute_callback, restore_callback),
        **kwargs,
    )
