"""v5 Phase 10 — 9 套主题 smoke 测试.

切换每套主题,截图 basic 页,确认无破坏.
输出: artifacts/v5_baseline/v5_themes_smoke/<theme>_basic.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from gui_widget import MainWindow
from theme_manager import get_theme_manager


THEMES = ["dark", "light", "green", "purple", "warm", "contrast", "rose", "ocean", "minimal"]
OUT = PROJECT_ROOT / "artifacts" / "v5_baseline" / "v5_themes_smoke"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    # UP-090: csgo_dir 是自动探测的，不沙箱化会把用户真实 CS2 目录里的
    # fanpai.cfg 覆盖成默认配置的内容。见 scripts/_audit_sandbox.py。
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    win = MainWindow()
    try:
        win.config.ui_expert_mode = True
    except Exception:
        pass
    win.show()
    win.resize(1366, 768)
    for _ in range(8):
        app.processEvents(); time.sleep(0.06)

    tm = get_theme_manager()
    errors = []
    for theme_name in THEMES:
        try:
            tm.set_theme(theme_name)
            for _ in range(8):
                app.processEvents(); time.sleep(0.05)
            win.show_page("basic", animated=False)
            for _ in range(6):
                app.processEvents(); time.sleep(0.05)
            time.sleep(0.2)
            for _ in range(4):
                app.processEvents(); time.sleep(0.05)
            pix = win.grab()
            out_path = OUT / f"{theme_name}_basic.png"
            ok = pix.save(str(out_path), "PNG")
            print(f"  [{'OK' if ok else 'FAIL'}] {theme_name}: {out_path.name}")
        except Exception as e:
            errors.append((theme_name, str(e)))
            print(f"  [FAIL] {theme_name}: {e}")

    win.close()
    if errors:
        print(f"\n失败 {len(errors)}/{len(THEMES)}")
        return 1
    print(f"\n9 套主题 smoke OK,产物在 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
