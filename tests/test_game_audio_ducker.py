# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from core.audio.game_audio_ducker import GameAudioDucker, _SessionAudioBackend


class _DummyBackend:
    def __init__(self, *, available=True, start_result=True, supports_dynamic_level=True):
        self.available = available
        self.start_result = start_result
        self.supports_dynamic_level = supports_dynamic_level
        self.start_calls: list[tuple[float, int | None]] = []
        self.restore_calls: list[int | None] = []

    def is_available(self) -> bool:
        return self.available

    def start_duck(self, ratio: float, attack_ms: int | None = None) -> bool:
        self.start_calls.append((ratio, attack_ms))
        return self.start_result

    def restore(self, release_ms: int | None = None) -> bool:
        self.restore_calls.append(release_ms)
        return True


class _ManualTimer:
    def __init__(self, factory, delay: float, callback):
        self._factory = factory
        self.target = factory.now + max(0.0, float(delay))
        self.callback = callback
        self.cancelled = False
        self.started = False
        self.daemon = False

    def start(self):
        self.started = True
        self._factory.timers.append(self)

    def cancel(self):
        self.cancelled = True


class _ManualTimerFactory:
    def __init__(self):
        self.now = 0.0
        self.timers: list[_ManualTimer] = []

    def __call__(self, delay: float, callback):
        return _ManualTimer(self, delay, callback)

    def advance(self, seconds: float):
        self.now += seconds
        while True:
            due = [
                timer
                for timer in list(self.timers)
                if timer.started and not timer.cancelled and timer.target <= self.now
            ]
            if not due:
                break
            for timer in due:
                self.timers.remove(timer)
                timer.callback()


class _DummyConfig:
    gun_sound_ducking_enabled = True
    gun_sound_duck_ratio = 0.18
    gun_sound_duck_release_ms = 120
    gun_sound_duck_fallback_hotkey_mode = True


def test_ducker_prefers_session_backend_and_extends_hold():
    timer_factory = _ManualTimerFactory()
    session_backend = _DummyBackend()
    fallback_backend = _DummyBackend()

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=session_backend,
        fallback_backend=fallback_backend,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.3) is True
    assert session_backend.start_calls == [(0.18, None)]
    assert fallback_backend.start_calls == []

    timer_factory.advance(0.2)
    assert session_backend.restore_calls == []

    assert ducker.hold_for(0.3) is True
    assert session_backend.start_calls == [(0.18, None), (0.18, None)]

    timer_factory.advance(0.2)
    assert session_backend.restore_calls == []

    timer_factory.advance(0.15)
    assert session_backend.restore_calls == [120]


def test_ducker_falls_back_when_session_backend_unavailable():
    timer_factory = _ManualTimerFactory()
    session_backend = _DummyBackend(available=False)
    fallback_backend = _DummyBackend(supports_dynamic_level=False)

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=session_backend,
        fallback_backend=fallback_backend,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.1) is True
    assert session_backend.start_calls == []
    assert fallback_backend.start_calls == [(0.18, None)]

    timer_factory.advance(0.1)
    assert fallback_backend.restore_calls == [120]


def test_ducker_retries_hotkey_fallback_when_session_start_fails():
    timer_factory = _ManualTimerFactory()
    session_backend = _DummyBackend(start_result=False)
    fallback_backend = _DummyBackend(supports_dynamic_level=False)

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=session_backend,
        fallback_backend=fallback_backend,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.1) is True
    assert session_backend.start_calls == [(0.18, None)]
    assert fallback_backend.start_calls == [(0.18, None)]


def test_ducker_applies_peak_then_sustain_for_dynamic_backend():
    timer_factory = _ManualTimerFactory()
    session_backend = _DummyBackend()

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=session_backend,
        fallback_backend=None,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.5, peak_ratio=0.08, peak_ms=60, sustain_ratio=0.14, release_ms=180) is True
    assert session_backend.start_calls == [(0.08, None)]

    timer_factory.advance(0.06)
    assert session_backend.start_calls == [(0.08, None), (0.14, None)]

    timer_factory.advance(0.5)
    assert session_backend.restore_calls == [180]


def test_ducker_does_not_reduck_hotkey_backend_for_peak_stage():
    timer_factory = _ManualTimerFactory()
    fallback_backend = _DummyBackend(supports_dynamic_level=False)

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=_DummyBackend(available=False),
        fallback_backend=fallback_backend,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.3, peak_ratio=0.08, peak_ms=50, sustain_ratio=0.14, release_ms=160) is True
    assert fallback_backend.start_calls == [(0.08, None)]

    timer_factory.advance(0.05)
    assert fallback_backend.start_calls == [(0.08, None)]

    timer_factory.advance(0.3)
    assert fallback_backend.restore_calls == [160]


def test_restore_cancels_pending_timer():
    timer_factory = _ManualTimerFactory()
    session_backend = _DummyBackend()

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=session_backend,
        fallback_backend=None,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.5, peak_ratio=0.08, peak_ms=50, sustain_ratio=0.14, release_ms=200) is True
    assert ducker.restore() is True
    assert session_backend.restore_calls == [200]

    timer_factory.advance(0.5)
    assert session_backend.restore_calls == [200]


def test_close_restores_immediately():
    timer_factory = _ManualTimerFactory()
    session_backend = _DummyBackend()

    ducker = GameAudioDucker(
        cfg=_DummyConfig(),
        session_backend=session_backend,
        fallback_backend=None,
        timer_factory=timer_factory,
        clock=lambda: timer_factory.now,
    )

    assert ducker.duck_for(0.5, peak_ratio=0.08, peak_ms=50, sustain_ratio=0.14, release_ms=200) is True
    ducker.close()

    assert session_backend.restore_calls == [0]


def test_session_backend_recovers_stale_duck_state(tmp_path):
    class _DummyVolume:
        def __init__(self, value: float):
            self.value = value

        def GetMasterVolume(self):
            return self.value

        def SetMasterVolume(self, value, _ctx):
            self.value = float(value)

    backend = _SessionAudioBackend(cfg=_DummyConfig())
    backend._state_path = str(tmp_path / "duck_state.json")
    backend._stale_state = {
        "timestamp": 1.0,
        "sessions": [
            {"process_name": "cs2.exe", "original": 0.72, "ducked": 0.08},
        ],
    }

    volume = _DummyVolume(0.08)
    backend._recover_stale_state_if_needed([("123:cs2.exe:", volume, "cs2.exe")])

    assert volume.value == 0.72
    assert backend._stale_state is None


def test_session_backend_restore_rescans_current_session_when_original_handle_is_gone():
    class _BrokenVolume:
        def GetMasterVolume(self):
            raise RuntimeError("stale session")

    class _DummyVolume:
        def __init__(self, value: float):
            self.value = value

        def GetMasterVolume(self):
            return self.value

        def SetMasterVolume(self, value, _ctx):
            self.value = float(value)

    backend = _SessionAudioBackend(cfg=_DummyConfig())
    current_volume = _DummyVolume(0.18)
    backend._scan_sessions = lambda refresh=False: [("new:cs2.exe", current_volume, "cs2.exe")]
    backend._ducked_sessions = {
        "old:cs2.exe": {
            "original": 1.0,
            "ducked": 0.18,
            "volume": _BrokenVolume(),
            "process_name": "cs2.exe",
        }
    }

    assert backend.restore(0) is True
    assert current_volume.value == 1.0
    assert backend._ducked_sessions == {}
