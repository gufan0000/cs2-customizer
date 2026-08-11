"""
v4 美学评估 — 真实截图捕获

捕获多个代表性页面 × 两个分辨率，输出到 artifacts/aesthetic_eval_20260507/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui_widget import MainWindow


PAGES = [
    "basic",          # 基础设置：toggle/combobox 密集
    "kill_sound",     # 击杀音效：响应式网格 + 武器卡
    "flash",          # 闪光：带预览组件
    "crosshair",      # 准心：滑块/数字
    "music",          # 音乐：列表/播放控制
    "voice_output",   # 语音输出
    "advanced",       # 高级
    "about",          # 关于
]

RESOLUTIONS = [
    (1920, 1080, "1920"),
    (1366, 768, "1366"),
]

OUT_DIR = PROJECT_ROOT / "artifacts" / "aesthetic_eval_20260507"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    # UP-090: csgo_dir 是自动探测的，不沙箱化会把用户真实 CS2 目录里的
    # fanpai.cfg 覆盖成默认配置的内容。见 scripts/_audit_sandbox.py。
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    win = MainWindow()
    win.show()
    app.processEvents()
    time.sleep(0.4)

    saved: list[str] = []

    for w, h, res_tag in RESOLUTIONS:
        win.resize(w, h)
        # 强制走一次 reflow
        for _ in range(6):
            app.processEvents()
            time.sleep(0.06)

        for page_key in PAGES:
            try:
                win.show_page(page_key, animated=False)
            except Exception as e:
                print(f"[skip] {page_key} ({res_tag}): {e}")
                continue
            for _ in range(8):
                app.processEvents()
                time.sleep(0.04)
            time.sleep(0.18)
            for _ in range(4):
                app.processEvents()
                time.sleep(0.04)

            pix = win.grab()
            out_path = OUT_DIR / f"{res_tag}_{page_key}.png"
            ok = pix.save(str(out_path), "PNG")
            if ok:
                saved.append(str(out_path))
                print(f"[ok] {out_path.name}")
            else:
                print(f"[fail] {out_path.name}")

    win.close()
    print(f"\n共保存 {len(saved)} 张到 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
