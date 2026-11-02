# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline P2 probes. No game, network, real display, audio device or hotkeys.

Run in a fresh process: python scripts/bench_gsi_packet.py --mode packets|preview|flash
CPU is one-core process CPU; wakeups are instrumented loop/timer callbacks,
not OS-wide context switches. Flash uses SDL dummy at 1920x1080: its compositor
cost cannot be inferred from this probe. Packet timings exclude imports/setup.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def packet(index=0):
    return {
        "provider": {"steamid": "p2-offline", "timestamp": 1700000000 + index / 10},
        "map": {"name": "de_dust2", "phase": "live", "round": 2},
        "round": {"phase": "live"},
        "player": {"steamid": "p2-offline", "activity": "playing",
                   "state": {"health": 100, "armor": 100, "flashed": 0,
                             "round_kills": 0, "round_killhs": 0},
                   "match_stats": {"kills": 0},
                   "weapons": {"weapon_0": {"name": "weapon_ak47", "state": "active",
                                             "ammo_clip": 30, "ammo_reserve": 90},
                               "weapon_1": {"name": "weapon_glock", "state": "holstered",
                                             "ammo_clip": 20}}},
    }


def summary(values):
    ordered = sorted(values)
    return {"n": len(values), "p50_ms": round(statistics.median(ordered), 6),
            "p95_ms": round(ordered[int((len(ordered) - 1) * .95)], 6)}


def timed(call, count, after=None, completion=None):
    values = []
    for i in range(count):
        start = time.perf_counter_ns()
        call(i)
        values.append((time.perf_counter_ns() - start) / 1e6)
        if after:
            after()
        if completion is not None:
            completion.append((time.perf_counter_ns() - start) / 1e6)
    return summary(values)


class TimedLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.holds = []

    def __enter__(self):
        self.lock.acquire()
        self.start = time.perf_counter_ns()
        return self

    def __exit__(self, *_args):
        self.holds.append((time.perf_counter_ns() - self.start) / 1e6)
        self.lock.release()


def packets(count, folder):
    # Dummy mixer decodes normally but has no physical output. The keyboard
    # controller and ducker are replaced before constructing a sound handler.
    from core.audio.audio_manager import AudioManager
    from core.audio import runtime_audio
    with patch.object(runtime_audio, "get_runtime_audio_manager", return_value=SimpleNamespace()):
        import gsi_handler_sounds as sounds
    from config import config
    from gsi_handler_hud_color import GSIHandlerHudColor
    from core.hud.rule_model import get_default_hud_rules
    from PySide6.QtCore import QObject, Signal

    logging.disable(logging.CRITICAL)

    class Magnifier(QObject):
        changed = Signal(str)

        def update_current_weapon(self, name):
            self.changed.emit(name)

    cfg = dict(player_steamid="p2-offline", spectator_mode_mute=True,
               gun_sound_enabled=True, death_sound_enabled=False,
               switch_weapon_sound_enabled=False, reload_sound_enabled=False)
    for profile in sounds.SUPPORTED_GUN_SOUND_PROFILE_LIST:
        cfg[profile.style_key] = "0"
        cfg[profile.legacy_enabled_key] = False
    data = packet()
    out = {}
    with patch.multiple(config, **cfg), patch.object(sounds, "Controller"), patch.object(sounds, "GameAudioDucker"):
        handler = sounds.GSIHandlerSounds()
        sound_handler = handler
        handler._game_audio_ducker = SimpleNamespace()
        out["sounds_disabled_styles"] = timed(lambda i: handler.process_data(data), count)
        magnifier = Magnifier()
        magnifier.changed.connect(lambda name: None)
        handler.set_magnifier_component(magnifier)
        out["sounds_magnifier_same_weapon"] = timed(lambda i: handler.process_data(data), count)
        for profile in sounds.SUPPORTED_GUN_SOUND_PROFILE_LIST:
            setattr(config, profile.style_key, "bench")
        out["sounds_all_styles_inventory"] = timed(lambda i: handler.process_data(data), count)

    # Real engine and filesystem. Alternate a stable default/low-health rule;
    # virtual 100ms timestamps allow writes without sleeping in the timed path.
    rules = get_default_hud_rules("balanced_default")
    with patch.multiple(config, hud_rules=rules, hud_rules_enabled=True,
                        hud_runtime_sync_mode="safe", csgo_dir=str(folder)):
        handler = GSIHandlerHudColor()
        handler._ensure_effect_timer = lambda: None
        handler._write_lock = TimedLock()
        handler._engine_lock = TimedLock()
        if hasattr(handler, "_effect_lock"):
            handler._effect_lock = TimedLock()
        def hud(i):
            data["player"]["state"]["health"] = 10 if i % 2 else 100
            with patch("gsi_handler_hud_color.time", SimpleNamespace(time=lambda: 1000 + i * .1)):
                handler.process_data(data)
        drain = getattr(handler, "_color_queue", None)
        completion = []
        out["hud_packets"] = timed(hud, min(count, 400), drain.join if drain else None, completion)
        out["hud_write_completion"] = summary(completion)
        out["hud_write_lock"] = summary(handler._write_lock.holds)
        out["hud_engine_lock"] = summary(handler._engine_lock.holds)
        if hasattr(handler, "_effect_lock"):
            out["hud_gsi_queue_lock"] = summary(handler._effect_lock.holds)
        out["hud_cfg_exists"] = bool(list(folder.rglob("cs2customizer_hud_runtime.cfg")))
        handler.stop()

    # Real WAV decode and cache-hit playback through the production manager.
    # Synthetic 2s stereo PCM is reproducible; it is not a user's audio corpus.
    import wave
    wav = folder / "p2.wav"
    with wave.open(str(wav), "wb") as stream:
        stream.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        stream.writeframes(bytes(44100 * 2 * 2 * 2))
    manager = AudioManager()
    manager._notify_loaded = lambda *a: None
    manager._record_timeline_event = lambda **kw: None
    manager._load_sound_by_key = lambda key: manager.load_sound(key, str(wav), "kill_sound")
    with patch.multiple(config, **{**cfg, "gun_sound_enabled": False,
                                  "death_sound_enabled": True,
                                  "sfx_forwarding_enabled": False}), patch.object(sounds, "audio_manager", manager):
        sound_handler._apply_death_sound_duck = lambda **kw: None
        sound_handler.death_cooldown_duration = 0
        data["player"]["state"]["health"] = 0
        def audio_packet(i, cold=True):
            config.death_sound_style = f"p2-{i}" if cold else "p2-hot"
            sound_handler.last_health = 100
            sound_handler._death_tracked_steamid = "p2-offline"
            sound_handler.process_data(data)
        out["audio_cold_packet"] = timed(audio_packet, min(count, 200))
        audio_packet(0, False)
        out["audio_hot_packet"] = timed(lambda i: audio_packet(i, False), count)
    manager.cleanup()
    return out


def preview(seconds):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QWidget
    from widgets.kill_icon_preview import KillIconPreview
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    widget = KillIconPreview(parent)
    frame = QImage(350, 250, QImage.Format_ARGB32)
    frame.fill(0xffabcdef)
    widget.set_animation(SimpleNamespace(frames=(frame, frame), fps=30,
                                         frame_width=350, frame_height=250))
    parent.show()
    app.processEvents()
    parent.hide()
    app.processEvents()
    ticks = [0]
    widget._timer.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    start, cpu = time.perf_counter(), time.process_time()
    loop.exec()
    elapsed = time.perf_counter() - start
    out = {"seconds": elapsed, "cpu_percent": (time.process_time() - cpu) / elapsed * 100,
           "timer_wakeups_per_s": ticks[0] / elapsed}
    widget.stop()
    parent.close()
    return out


def flash(seconds):
    import pygame
    # Import has an intentional process-local DPI setting, hence separate mode.
    import flash_process as fp
    from queue import Queue
    effect = fp.FlashEffectProcess()
    pygame.display.init()
    effect.screen_width, effect.screen_height = 1920, 1080
    effect.overlay_win = pygame.display.set_mode((1920, 1080))
    effect.is_running = True
    effect._apply_pending_monitor = lambda: None
    flips, wakes = [0], [0]
    real_flip, real_events = pygame.display.flip, pygame.event.get
    def events():
        wakes[0] += 1
        return real_events()
    def flip():
        flips[0] += 1
        real_flip()
    # A producer thread sends shutdown; it does no display work.
    commands = Queue()
    timer = threading.Timer(seconds, lambda: commands.put({"type": "shutdown"}))
    timer.start()
    start, cpu = time.perf_counter(), time.process_time()
    with patch.object(pygame.event, "get", events), patch.object(pygame.display, "flip", flip):
        effect.main_loop(commands)
    elapsed = time.perf_counter() - start
    timer.join()
    return {"seconds": elapsed, "cpu_percent": (time.process_time() - cpu) / elapsed * 100,
            "loop_wakeups_per_s": wakes[0] / elapsed, "flips_per_s": flips[0] / elapsed,
            "display": "SDL dummy 1920x1080; no compositor measurement"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("packets", "preview", "flash"), default="packets")
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    os.environ.update(QT_QPA_PLATFORM="offscreen", SDL_VIDEODRIVER="dummy",
                      SDL_AUDIODRIVER="dummy", CS2C_NO_EXIT_GUARDIAN="1")
    with tempfile.TemporaryDirectory(prefix="p2_bench_") as temporary:
        folder = Path(temporary)
        for name in ("CS2C_CONFIG_DIR", "CS2C_LOG_DIR", "LOCALAPPDATA", "APPDATA"):
            target = folder / name
            target.mkdir()
            os.environ[name] = str(target)
        (folder / "CS2C_CONFIG_DIR" / "config.json").write_text("{}", encoding="utf-8")
        try:
            result = packets(args.count, folder) if args.mode == "packets" else globals()[args.mode](args.seconds)
            print("P2_RESULT " + json.dumps({"mode": args.mode, "result": result}, ensure_ascii=False))
        finally:
            logging.shutdown()


if __name__ == "__main__":
    main()
