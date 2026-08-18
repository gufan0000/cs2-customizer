# SPDX-License-Identifier: GPL-3.0-or-later
"""
v5 性能基线工具 — 启动时间 + 内存 + 切页时间

用法:
    python scripts/v5_perf_check.py [--label v4|v5_phaseN] [--rounds 3]

输出:
    artifacts/v5_baseline/<label>/perf.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psutil  # 已在依赖中


def measure_once() -> dict:
    """一轮性能测量:启动时间 + 内存 + 27 页切换时间"""
    from PySide6.QtWidgets import QApplication
    from gui_widget import MainWindow

    process = psutil.Process()
    # 这里原先还测了一次「建 QApplication 之前的 RSS」，但从来没进过返回值 ——
    # 报表里的三个内存数都是从 rss_after_init 起算的。留着只会让人以为量过。
    t0 = time.perf_counter()
    app = QApplication.instance() or QApplication(sys.argv)
    # UP-090: csgo_dir 是自动探测的，不沙箱化会把用户真实 CS2 目录里的
    # cs2customizer.cfg 覆盖成默认配置的内容。见 scripts/_audit_sandbox.py。
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    win = MainWindow()
    try:
        win.config.ui_expert_mode = True
    except Exception:
        pass
    win.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)
    t1 = time.perf_counter()
    startup_ms = (t1 - t0) * 1000

    rss_after_init = process.memory_info().rss

    pages = [
        "basic", "kill_sound", "kill_voice", "death_sound", "gun_sound",
        "switch_weapon", "reload_sound", "special_sound", "crosshair",
        "kill_icon", "magnifier", "flash", "viewmodel", "hud_color",
        "screen_effects", "music", "voice_output", "utility",
        "advanced", "about",
        "audio_health", "audio_import_wizard", "audio_task_panel",
        "audio_replay", "config_snapshot", "preset_center",
    ]

    page_times = {}
    for pid in pages:
        ts = time.perf_counter()
        try:
            win.show_page(pid, animated=False)
            for _ in range(4):
                app.processEvents()
        except Exception as e:
            page_times[pid] = {"error": str(e)}
            continue
        te = time.perf_counter()
        page_times[pid] = {"ms": round((te - ts) * 1000, 2)}

    rss_after_all = process.memory_info().rss
    win.close()

    valid_times = [v["ms"] for v in page_times.values() if "ms" in v]
    return {
        "startup_ms": round(startup_ms, 2),
        "rss_init_mb": round(rss_after_init / 1024 / 1024, 2),
        "rss_all_pages_mb": round(rss_after_all / 1024 / 1024, 2),
        "rss_growth_mb": round((rss_after_all - rss_after_init) / 1024 / 1024, 2),
        "page_switch_avg_ms": round(sum(valid_times) / len(valid_times), 2) if valid_times else 0,
        "page_switch_max_ms": round(max(valid_times), 2) if valid_times else 0,
        "page_times": page_times,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="v4")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "artifacts" / "v5_baseline"))
    parser.add_argument("--rounds", type=int, default=1,
                        help="测几轮(取最佳).注:多轮在同进程内跑,RSS 会累积,只有 round 1 是 cold start;"
                             "建议默认 1 轮,需要稳定性验证用 v5_perf_check_isolated.py(待写).")
    args = parser.parse_args()

    out_dir = Path(args.out) / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    rounds = []
    for i in range(args.rounds):
        print(f"\n=== Round {i+1}/{args.rounds} ===")
        r = measure_once()
        rounds.append(r)
        print(f"  startup_ms = {r['startup_ms']}")
        print(f"  rss_init_mb = {r['rss_init_mb']}")
        print(f"  rss_all_pages_mb = {r['rss_all_pages_mb']}")
        print(f"  page_switch_avg_ms = {r['page_switch_avg_ms']}")
        print(f"  page_switch_max_ms = {r['page_switch_max_ms']}")

    # 取最佳轮(startup_ms 最快那次)
    best = min(rounds, key=lambda r: r["startup_ms"])

    summary = {
        "label": args.label,
        "measured_at": datetime.now().isoformat(),
        "rounds": len(rounds),
        "best": best,
        "all_rounds": rounds,
    }

    out_path = out_dir / "perf.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[perf] saved {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
