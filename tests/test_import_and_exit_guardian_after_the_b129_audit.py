# SPDX-License-Identifier: GPL-3.0-or-later
"""批 129：素材导入的武器目录名、强杀后的音量守护（RN-706①）、麦克风直通掉线刷屏。

分母：素材导入 2 条（RN-656② 两半）+ 退出守护 3 条（接线 / 读状态 / 父进程被硬退后真接手）+ 直通 1 条。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── 素材导入：文件名猜武器、切枪 / 换弹的目录名 ───────────────────────────

def _targets(spec_key, names):
    from core.resource_placement import plan_placements

    plan = plan_placements(spec_key, names, style_name="测试")
    assert plan.ready, plan.questions
    return [p.target_rel_path for p in plan.placements]


def test_a_suffixed_weapon_name_is_not_cut_at_the_dash():
    """`M4A1-S.wav` 以前被切成 `m4a1` —— 那是 **M4A4** 的合法代号，消音版的声音悄悄装进了 M4A4。"""
    got = _targets("gun_sounds", ["M4A1-S.wav", "AK-47.wav"])
    assert got == ["audio/gun_sounds/m4a1_silencer/测试/M4A1-S.wav", "audio/gun_sounds/ak47/测试/AK-47.wav"]


@pytest.mark.parametrize("spec_key,table", [("switch_weapons", "weapon_switch_sounds"),
                                            ("reload_sounds", "weapon_reload_sounds")])
def test_loose_weapon_files_land_in_the_folders_the_product_reads(spec_key, table):
    """⭐ 产品按 GSI 全名找目录（`switch_weapons/weapon_ak47/<风格>/`），以前导入写的是 `ak47`；
    而且一个目录里散放几把枪的文件会被整组编号成一个 `1.wav`、落进「新风格」，其余丢掉。"""
    from config import config

    got = _targets(spec_key, ["AK-47.wav", "awp.wav"])
    assert got == [f"audio/{spec_key}/weapon_ak47/测试/1.wav", f"audio/{spec_key}/weapon_awp/测试/1.wav"]
    readable = set(getattr(config, table))
    assert {"weapon_ak47", "weapon_awp"} <= readable, "导入写的目录名必须是产品那张表里的键"


# ── 退出守护（RN-706①）─────────────────────────────────────────────────

def test_ducking_the_game_starts_the_exit_guardian(monkeypatch, tmp_path):
    """接线：游戏音量真的被压下去（状态文件第一次落盘）⇒ 起守护。"""
    from core.audio import game_audio_ducker
    from core.runtime import exit_guardian

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    started = []
    monkeypatch.setattr(exit_guardian, "ensure_started", lambda: started.append(True) or True)
    ducker = game_audio_ducker._SessionAudioBackend(cfg=types.SimpleNamespace())
    ducker._ducked_sessions = {"k": {"process_name": "cs2.exe", "original": 1.0, "ducked": 0.2, "volume": object()}}
    ducker._write_runtime_state_locked()
    assert started == [True]
    assert Path(ducker._state_path).exists()


def test_the_guardian_restores_the_processes_named_in_the_state_file(monkeypatch, tmp_path):
    """守护不读用户配置：要恢复哪几个进程从状态文件里来；没有状态文件（正常退出已恢复）就什么都不做。"""
    from core.audio import game_audio_ducker
    from core.runtime import exit_guardian

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert exit_guardian.restore_after_parent_death() == 0
    state = tmp_path / "CS2Customizer" / "runtime" / "gun_sound_duck_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"timestamp": time.time(), "sessions": [
        {"process_name": "cs2.exe", "original": 1.0, "ducked": 0.198}]}), encoding="utf-8")
    scanned = []
    monkeypatch.setattr(game_audio_ducker._SessionAudioBackend, "_scan_sessions",
                        lambda self, refresh=False: scanned.append(self._target_process_names()) or [])
    assert exit_guardian.restore_after_parent_death() == 1
    assert scanned == [{"cs2.exe"}]


def test_the_guardian_takes_over_when_the_app_is_killed(tmp_path):
    """端到端：父进程起守护后被硬退（`os._exit`，与任务管理器结束 / 看门狗那一刀同形）⇒ 守护接手。
    ⚠ 不碰真音量：恢复函数换成写一个标记文件，这里量的只是「父进程死了守护会不会跑」。"""
    mark = tmp_path / "restored.txt"
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {str(ROOT)!r})
        import core.runtime.exit_guardian as g
        def fake_restore():
            open({str(mark)!r}, "w").write("ok")
            return 1
        g.restore_after_parent_death = fake_restore
        if __name__ == "__main__":
            g.ensure_started()
            for _ in range(200):
                if g.is_running():
                    break
                time.sleep(0.05)
            time.sleep(1.5)          # 让守护读完启动数据（真软件里父进程活得远比这久）
            os._exit(0)
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["CS2C_LOG_DIR"] = str(tmp_path / "logs")
    subprocess.run([sys.executable, str(child)], env=env, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if mark.exists():
            break
        time.sleep(0.05)
    assert mark.exists(), "父进程被硬退之后守护没有接手"


def test_the_guardian_never_starts_inside_pytest():
    from core.runtime import exit_guardian

    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert exit_guardian.ensure_started() is False


# ── 麦克风直通：设备掉线时别每 10ms 刷一条 error ──────────────────────────

def test_mic_passthrough_gives_up_quietly_when_the_device_is_gone(monkeypatch):
    import voice_output_manager as vom

    class _Broken:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def read(self, n):
            raise OSError("设备已拔出")

        def write(self, data):
            pass

    monkeypatch.setattr(vom.sd, "InputStream", _Broken)
    monkeypatch.setattr(vom.sd, "OutputStream", _Broken)
    monkeypatch.setattr(vom.sd, "query_devices",
                        lambda *a, **k: {"default_samplerate": 48000, "max_input_channels": 1})
    monkeypatch.setattr(vom.time, "sleep", lambda s: None)
    errors = []
    mgr = vom.VoiceOutputManager.__new__(vom.VoiceOutputManager)
    mgr.is_initialized = True
    mgr.microphone_passthrough_active = False
    mgr.logger = types.SimpleNamespace(error=errors.append, info=lambda *a: None, warning=lambda *a: None)
    mgr.get_microphone_id_by_key = lambda name: 0
    mgr.vb_cable_rate, mgr.vb_cable_device_id, mgr.chunk_size = 48000, 1, 256
    mgr.mute_lock, mgr.mix_lock = threading.Lock(), threading.Lock()
    mgr.mute_microphone, mgr.current_mix_audio, mgr.mix_position = False, None, 0
    mgr.start_microphone_passthrough("默认")
    mgr.passthrough_thread.join(5)
    assert not mgr.passthrough_thread.is_alive(), "设备掉线后直通线程一直不退"
    assert len(errors) <= 2, f"掉线后刷了 {len(errors)} 条 error"
