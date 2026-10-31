# SPDX-License-Identifier: GPL-3.0-or-later
"""批 129：素材导入的武器目录名、强杀后的音量守护（RN-706①）、麦克风直通掉线刷屏。

分母：素材导入 2 条（RN-656② 两半）+ 退出守护 3 条（接线 / 读状态 / 父进程被硬退后真接手）+ 直通 1 条。
"""

from __future__ import annotations

import ast
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
    # This one child deliberately exercises the guardian, using fake restoration
    # and its own runtime directory; other tests keep the default opt-out.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_CURRENT_TEST", "CS2C_NO_EXIT_GUARDIAN")}
    env["CS2C_LOG_DIR"] = str(tmp_path / "logs")
    env["LOCALAPPDATA"] = str(tmp_path / "appdata")   # 守护会写 runtime/exit_guardian.log，别落进用户真目录
    subprocess.run([sys.executable, str(child)], env=env, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if mark.exists():
            break
        time.sleep(0.05)
    assert mark.exists(), "父进程被硬退之后守护没有接手"


class _Vol:
    def __init__(self, v):
        self.v = v

    def GetMasterVolume(self):  # noqa: N802
        return self.v

    def SetMasterVolume(self, v, _ctx):  # noqa: N802
        self.v = v


def test_the_guardian_really_restores_and_says_so_in_its_log(monkeypatch, tmp_path):
    """批 136：上面那条端到端判据把恢复函数整个换成了假的 —— 真的恢复条件、真的日志从来没一起跑过。
    读数取 10-03 进游戏 HARDKILL 守护日志：cs2.exe 当前 0.198、压低目标 0.198、原值 1.0。"""
    from core.audio import game_audio_ducker
    from core.runtime import exit_guardian

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    state = tmp_path / "CS2Customizer" / "runtime" / "gun_sound_duck_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"timestamp": time.time(), "sessions": [
        {"process_name": "cs2.exe", "original": 1.0, "ducked": 0.198}]}), encoding="utf-8")
    vol = _Vol(0.198)
    monkeypatch.setattr(game_audio_ducker._SessionAudioBackend, "_scan_sessions",
                        lambda self, refresh=False: self._recover_stale_state_if_needed([("k", vol, "cs2.exe")]) or [])
    assert exit_guardian.restore_after_parent_death() == 1
    assert vol.v == 1.0
    log = (tmp_path / "CS2Customizer" / "runtime" / "exit_guardian.log").read_text(encoding="utf-8")
    assert "还回 1 个" in log and "0.198" in log, log


def _run_child_that_lost_its_parent(tmp_path, parent_pid):
    """真的走 PyInstaller 同款入口：`sys.frozen` + `--multiprocessing-fork`，由 `spawn_main` 自己抛异常。"""
    mark = tmp_path / "restored.txt"
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        sys.frozen = True
        import core.runtime.exit_guardian as g
        def fake_restore():
            open({str(mark)!r}, "w").write("ok")
            return 1
        g.restore_after_parent_death = fake_restore
        import multiprocessing
        g.freeze_support_quietly(multiprocessing.freeze_support, sys.argv)
        print("不该走到主程序")
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["LOCALAPPDATA"] = str(tmp_path / "appdata")
    done = subprocess.run(
        [sys.executable, str(child), "--multiprocessing-fork", f"parent_pid={parent_pid}", "pipe_handle=999999"],
        env=env, timeout=60, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done, mark


def test_a_child_that_lost_its_parent_restores_the_volume_and_leaves_quietly(tmp_path):
    """RN-723：批 140 进游戏实测，首次压声后约 1 秒内强杀 ⇒ 打包版弹错误框、残留进程、音量停在压低值。"""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    done, mark = _run_child_that_lost_its_parent(tmp_path, dead.pid)
    assert done.returncode == 0 and "Traceback" not in done.stderr, done.stderr
    assert "不该走到主程序" not in done.stdout
    assert mark.exists(), "父进程已死，子进程没有顶班恢复音量"
    log = (tmp_path / "appdata" / "CS2Customizer" / "runtime" / "exit_guardian.log").read_text(encoding="utf-8")
    assert "没连上父进程" in log, log


def test_a_child_that_failed_while_its_parent_lives_does_not_touch_the_volume(tmp_path):
    """父进程还活着时音量归它管：子进程起不来只是少了兜底，不许替它恢复。"""
    done, mark = _run_child_that_lost_its_parent(tmp_path, os.getpid())
    assert done.returncode == 0 and "Traceback" not in done.stderr, done.stderr
    assert not mark.exists()


def test_the_main_process_still_sees_a_real_freeze_support_error():
    """接异常只限子进程：主进程这里出错要照常报。"""
    from core.runtime import exit_guardian

    def boom():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        exit_guardian.freeze_support_quietly(boom, ["CS2 Customizer.exe"])


def test_the_app_entry_goes_through_the_quiet_freeze_support():
    tree = ast.parse((ROOT / "main_widget.py").read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "freeze_support_quietly" in called


def test_the_utility_display_process_leaves_when_the_app_is_gone(monkeypatch):
    """批 136 进游戏（HARDKILL）逮到：只杀 CS2 Customizer 主进程，道具瞄点显示子进程一直活着（18 线程、约 73MB）。"""
    import multiprocessing
    import queue
    import threading

    import utility_display

    class _DeadParent:
        @staticmethod
        def is_alive():
            return False

    monkeypatch.setattr(multiprocessing, "parent_process", lambda: _DeadParent())
    w = utility_display.UtilityDisplayWorker(queue.Queue(), queue.Queue())
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(3.0)
    if t.is_alive():
        w.running = False
    assert not t.is_alive(), "父进程已经不在了，道具瞄点显示进程 3 秒内没自己退出"


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
