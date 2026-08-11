# SPDX-License-Identifier: GPL-3.0-or-later
"""
v5 视觉基线工具 — 截全 27 页 × 2 分辨率

用法:
    python scripts/v5_visual_baseline.py [--out DIR] [--label v4|v5_phaseN|...]

输出:
    artifacts/v5_baseline/<label>/<res>_<page_id>.png  (27 页 × 2 分辨率 = 54 张)
    artifacts/v5_baseline/<label>/manifest.json        (运行元信息)

每个 phase commit 前都跑一次,然后 v5_visual_diff.py 对比两个 label。
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

from PySide6.QtWidgets import QApplication

from gui_widget import MainWindow


# 默认就能访问的 21 页
DEFAULT_PAGES = [
    "basic", "kill_sound", "kill_voice", "death_sound", "gun_sound",
    "switch_weapon", "reload_sound", "special_sound", "crosshair",
    "kill_icon", "magnifier", "flash", "viewmodel", "hud_color",
    "screen_effects", "music", "voice_output", "utility",
    "advanced", "about",
]

# 专家模式才显示的 6 页(需启用 ui_expert_mode)
EXPERT_PAGES = [
    "audio_health", "audio_import_wizard", "audio_task_panel",
    "audio_replay", "config_snapshot", "preset_center",
]

ALL_PAGES = DEFAULT_PAGES + EXPERT_PAGES  # 27 页

RESOLUTIONS = [
    (1920, 1080, "1920"),
    (1366, 768, "1366"),
]


def capture_all(out_dir: Path, label: str) -> dict:
    """截全 27 页 × 2 分辨率,返回 manifest 字典"""
    target_dir = out_dir / label
    target_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    # UP-090: csgo_dir 是自动探测的，不沙箱化会把用户真实 CS2 目录里的
    # cs2customizer.cfg 覆盖成默认配置的内容。见 scripts/_audit_sandbox.py。
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    win = MainWindow()

    # 强制开启专家模式让 6 个专家页可见
    try:
        win.config.ui_expert_mode = True
    except Exception:
        pass

    win.show()
    app.processEvents()
    time.sleep(0.5)

    saved = []
    failed = []
    started_at = datetime.now()

    for w, h, res_tag in RESOLUTIONS:
        win.resize(w, h)
        for _ in range(8):
            app.processEvents()
            time.sleep(0.06)

        for page_id in ALL_PAGES:
            try:
                win.show_page(page_id, animated=False)
            except Exception as e:
                failed.append({"page": page_id, "res": res_tag, "error": str(e)})
                continue

            for _ in range(8):
                app.processEvents()
                time.sleep(0.04)
            time.sleep(0.20)
            for _ in range(4):
                app.processEvents()
                time.sleep(0.04)

            pix = win.grab()
            out_path = target_dir / f"{res_tag}_{page_id}.png"
            ok = pix.save(str(out_path), "PNG")
            if ok:
                saved.append({"page": page_id, "res": res_tag, "file": out_path.name,
                              "size": out_path.stat().st_size})
            else:
                failed.append({"page": page_id, "res": res_tag, "error": "save failed"})

    win.close()
    finished_at = datetime.now()

    manifest = {
        "label": label,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
        "resolutions": [r[2] for r in RESOLUTIONS],
        "pages_total": len(ALL_PAGES),
        "expected_count": len(ALL_PAGES) * len(RESOLUTIONS),
        "saved_count": len(saved),
        "failed_count": len(failed),
        "saved": saved,
        "failed": failed,
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(PROJECT_ROOT / "artifacts" / "v5_baseline"),
                        help="输出根目录")
    parser.add_argument("--label", default="v4",
                        help="标签:v4 / v5_phase1 / v5_phase2 / ... / v5_final")
    args = parser.parse_args()

    out_dir = Path(args.out)
    print(f"[baseline] label={args.label} out={out_dir}")
    manifest = capture_all(out_dir, args.label)

    print(f"\n[baseline] saved={manifest['saved_count']}/{manifest['expected_count']}")
    if manifest["failed"]:
        print(f"[baseline] FAILED:")
        for f in manifest["failed"]:
            print(f"    {f['res']}_{f['page']}: {f['error']}")
        return 1
    print(f"[baseline] OK in {manifest['duration_s']:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
