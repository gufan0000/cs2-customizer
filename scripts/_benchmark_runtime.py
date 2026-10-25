# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated, exit-code-checked subprocesses for offline measurements."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def prepare_environment() -> Path:
    """Run before importing product modules; never migrate a user's profile."""
    root = Path(tempfile.mkdtemp(prefix="cs2customizer_benchmark_"))
    for name in ("config", "logs", "local", "roaming", "game/game/csgo/cfg"):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "CS2C_CONFIG_DIR": str(root / "config"),
        "CS2C_LOG_DIR": str(root / "logs"),
        "LOCALAPPDATA": str(root / "local"),
        "APPDATA": str(root / "roaming"),
        "CS2C_SAFE_MODE_ACTIVE": "1",
        "CS2C_SKIP_SOURCE_BACKUP": "1",
        "CS2C_NO_EXIT_GUARDIAN": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "SDL_AUDIODRIVER": "dummy",
        "SDL_VIDEODRIVER": "dummy",
    })
    (root / "config/config.json").write_text(json.dumps({
        "csgo_dir": str(root / "game"), "onboarding_completed": True,
        "announcement_only_on_update": True, "usage_report_enabled": False,
        "crash_report_prompt": "never", "close_action": "exit",
    }), encoding="utf-8")
    from _audit_neutralize import enable_audit_mode
    enable_audit_mode()
    return root


def read_result(proc: subprocess.CompletedProcess) -> dict | None:
    lines = [line[7:] for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    if proc.returncode != 0 or len(lines) != 1:
        return None
    try:
        result = json.loads(lines[0])
    except (ValueError, TypeError):
        return None
    if not isinstance(result, dict) or not result:
        return None
    if any(isinstance(v, (int, float)) and not math.isfinite(v) for v in result.values()):
        return None
    return result


def run_child(source: str, root: Path, timeout: float) -> dict | None:
    # A real saved script keeps traceback origins inspectable and avoids shell quoting.
    with tempfile.TemporaryDirectory(prefix="cs2customizer_bench_child_") as temp:
        script = Path(temp) / "measure.py"
        script.write_text(source, encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, str(script)], cwd=str(root),
                                  capture_output=True, text=True, errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            sys.stderr.write("benchmark child timed out\n")
            return None
    result = read_result(proc)
    if result is None:
        sys.stderr.write(f"benchmark child failed: exit={proc.returncode}\n"
                         + proc.stdout[-2000:] + "\n" + proc.stderr[-2000:] + "\n")
    return result
