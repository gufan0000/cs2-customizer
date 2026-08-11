# -*- coding: utf-8 -*-
"""把搜索结果面板真渲染出来看一眼（R13/S4）。

自绘 delegate 的排版对不对，逻辑判据一条都证明不了：两行会不会重叠、
右侧类型标签会不会被长项名压住、深浅主题下次行文字还看不看得清 ——
这些只能看像素。本脚本离屏渲染若干查询下的 popup，落成 PNG。

不打扰前台：窗口挂 `WA_DontShowOnScreen`，popup 用 QWidget.grab() 离屏取图。

用法:
    python scripts/probe_search_popup_render.py [--theme dark,light] [--out 目录]
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("FANPAI_SAFE_MODE_ACTIVE", "1")
_tmp = Path(tempfile.gettempdir()) / "fanpai_search_render"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("FANPAI_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("FANPAI_LOG_DIR", str(_tmp / "logs"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QUERIES = ["准心", "音量", "zx", "观战静音", "asdfghjkl", "",
           # R14 新增的三类：同义词 / 片段覆盖 / 卡片标题条目
           # （卡片标题那条的次行不能把标题重复一遍，只有渲染出来看得见）
           "准星", "准心回正", "cfg同步"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--themes", default="dark,light")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "fanpai_search_render"))
    args = ap.parse_args()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from _audit_sandbox import sandbox_external_writes
    from config import config

    sandbox_external_writes()
    config.ui_expert_mode = True
    config.compact_mode = False

    import gui_widget

    gui_widget.run_startup_source_backup = lambda *a, **k: None

    from theme_manager import get_theme_manager

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tm = get_theme_manager()

    popup = win._settings_search_completer.popup()
    made = []
    for theme in [t.strip() for t in args.themes.split(",") if t.strip()]:
        tm.set_theme(theme)
        app.processEvents()
        for q in QUERIES:
            win.settings_search_box.setText(q)
            win._on_search_text_edited(q)
            app.processEvents()

            rows = len(win._search_rows or [])
            if rows == 0:
                print(f"  [{theme}] {q!r:<12} 0 行，跳过取图")
                continue
            # popup 平时不显示，这里给它一个尺寸再离屏 grab
            popup.setAttribute(Qt.WA_DontShowOnScreen, True)
            popup.resize(360, min(8, rows) * 46 + 4)
            popup.show()
            app.processEvents()
            app.processEvents()
            name = f"popup_{theme}_{q or 'EMPTY'}.png"
            path = out_dir / name
            popup.grab().save(str(path))
            popup.hide()
            app.processEvents()
            made.append(path)
            first = win._search_rows[0]
            print(f"  [{theme}] {q!r:<12} {rows} 行  首条: "
                  f"[{first['kind']}] {first['text']} / {first.get('subtitle', '')}")

    print(f"\n共 {len(made)} 张，落在 {out_dir}")
    win.close()
    win.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
