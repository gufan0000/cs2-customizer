# SPDX-License-Identifier: GPL-3.0-or-later
"""v5 完整 smoke — 启动 + 9 主题 × 27 页面切换 + 关闭,捕捉所有运行时错误."""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication
from gui_widget import MainWindow
from theme_manager import get_theme_manager

THEMES = ["dark", "light", "green", "purple", "warm", "contrast", "rose", "ocean"]  # minimal 跳过(空 stylesheet)
PAGES = [
    "basic", "kill_sound", "kill_voice", "death_sound", "gun_sound",
    "switch_weapon", "reload_sound", "special_sound", "crosshair",
    "kill_icon", "magnifier", "flash", "viewmodel", "hud_color",
    "screen_effects", "music", "voice_output", "utility",
    "advanced", "audio_health", "audio_import_wizard", "audio_task_panel",
    "audio_replay", "config_snapshot", "preset_center", "about",
]


def main() -> int:
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
    for _ in range(8):
        app.processEvents()
        time.sleep(0.05)

    tm = get_theme_manager()
    errors = []
    transitions = 0

    # 主测试:每套主题切 27 页
    for theme_name in THEMES:
        try:
            tm.set_theme(theme_name)
        except Exception as e:
            errors.append(("theme", theme_name, repr(e), traceback.format_exc()))
            continue
        for _ in range(4):
            app.processEvents()
            time.sleep(0.04)

        for page in PAGES:
            try:
                win.show_page(page, animated=False)
                for _ in range(2):
                    app.processEvents()
                    time.sleep(0.02)
                transitions += 1
            except Exception as e:
                errors.append((theme_name, page, repr(e), traceback.format_exc()))

    win.close()
    for _ in range(4):
        app.processEvents()
        time.sleep(0.05)

    print(f"\n[smoke] 总计 {len(THEMES)} 主题 × {len(PAGES)} 页 = {transitions} 次切换")
    print(f"[smoke] 错误: {len(errors)}")
    for kind, name, err, tb in errors[:5]:
        print(f"  {kind} / {name}: {err}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
