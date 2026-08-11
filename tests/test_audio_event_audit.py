# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _write_log(path: Path, lines: list[str]):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _line(message: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[{ts}] [INFO] [CS2Customizer.Test:1] {message}"


def _run_audit(cmd: list[str]):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        cwd=".",
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_audio_event_audit_require_pass(tmp_path):
    log_file = tmp_path / "cs2customizer_20990101.log"
    _write_log(
        log_file,
        [
            _line("播放击杀语音: voice-styleA-1"),
            _line("播放切枪音效: switch-weapon_m4a1-styleSwitch"),
            _line("播放换弹音效: reload-weapon_m4a1-styleReload"),
            _line("[投掷音效] 播放hegrenade投掷音效: grenade-hegrenade-styleG"),
            _line("[C4音效] 播放C4安装音效: c4-planted-styleC4"),
            _line("[血量警告] 播放音效: health-warning-styleH"),
            _line("[回合音效] 播放回合胜利音效: round-win-styleWin"),
            _line("[击杀诊断] round_kills: 0->1"),
        ],
    )

    cmd = [
        sys.executable,
        "audio_event_audit.py",
        "--log-file",
        str(log_file),
        "--minutes",
        "0",
        "--show-lines",
        "1",
        "--require",
        "kill_events",
        "--require",
        "voice_events",
        "--require",
        "switch_events",
        "--require",
        "reload_events",
        "--require",
        "grenade_events",
        "--require",
        "c4_events",
        "--require",
        "health_events",
        "--require",
        "round_events",
        "--fail-on-errors",
    ]
    result = _run_audit(cmd)
    assert result.returncode == 0, result.stdout + result.stderr


def test_audio_event_audit_fail_on_errors(tmp_path):
    log_file = tmp_path / "cs2customizer_20990101.log"
    _write_log(
        log_file,
        [
            _line("播放击杀语音: voice-styleA-1"),
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [CS2Customizer.Test:1] Play failed kill-1",
        ],
    )

    cmd = [
        sys.executable,
        "audio_event_audit.py",
        "--log-file",
        str(log_file),
        "--minutes",
        "0",
        "--show-lines",
        "1",
        "--require",
        "voice_events",
        "--fail-on-errors",
    ]
    result = _run_audit(cmd)
    assert result.returncode == 4, result.stdout + result.stderr


def test_audio_event_audit_warning_does_not_fail_errors(tmp_path):
    log_file = tmp_path / "cs2customizer_20990101.log"
    _write_log(
        log_file,
        [
            _line("[AudioHealth] OK"),
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WARNING] [CS2Customizer.VoiceOutputManager:127] [初始化] 未找到可用的VB-Cable设备",
        ],
    )

    cmd = [
        sys.executable,
        "audio_event_audit.py",
        "--log-file",
        str(log_file),
        "--minutes",
        "0",
        "--show-lines",
        "1",
        "--require",
        "audio_health",
        "--fail-on-errors",
    ]
    result = _run_audit(cmd)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "- warnings: 1" in result.stdout
