#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R9 回归：把「只能靠肉眼判断」的部分拍下来。

R9 收工时有两处明确没有像素级证据：
  1. **T 型准心到底长什么样**——判据只能验"中心线以上没有像素"这类性质，
     验不了"它看起来对不对"。
  2. **flash / kill_icon / music / viewmodel / voice_output 五页**——
     构造即起热键/音频设备/子进程，会打扰前台，所以历轮审计与指纹都跳过它们。
     它们的页头迁移（R9-C）当时只有单元测试覆盖，没有任何视觉证据。

本脚本把这两处补上。⚠ 会构造那 5 个页面，即会短暂起热键/音频设备/子进程。

用法：
    python scripts/r9_visual_evidence.py --out H:/tmp/r9_shots
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 页头迁移了但从没被拍过的 5 页（口径同 layout_overflow_audit.UNSAFE_PAGES）
NEVER_CAPTURED = ["flash", "kill_icon", "music", "viewmodel", "voice_output"]
# R9-D 重构过建页骨架的 4 页
REFACTORED = ["kill_sound", "kill_voice", "switch_weapon", "reload_sound"]


def capture_crosshair_styles(out_dir: Path) -> None:
    """用**真正的渲染器**把 5 个样式各画一遍，拼成一张对照图。

    不走页面预览——预览是另一套独立绘制代码。这里要看的是玩游戏时屏幕上那一套。
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    from crosshair_overlay import USER_STYLES, CrosshairFrame, paint_crosshair

    cell, pad, label_h = 180, 12, 28
    styles = [s for s in USER_STYLES if s != "custom"]  # custom 需要用户点阵
    width = len(styles) * (cell + pad) + pad
    height = cell + label_h + pad * 2

    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(24, 26, 30))
    painter = QPainter(img)
    painter.setFont(QFont("Microsoft YaHei", 11))

    for i, style in enumerate(styles):
        x0 = pad + i * (cell + pad)
        # `center` 是 CrosshairFrame 的显式字段，不传就用默认值——
        # 别改用 painter.translate()，那会和默认 center 叠加，画出来是偏的。
        center = QPointF(x0 + cell / 2, pad + cell / 2)
        paint_crosshair(painter, CrosshairFrame(style=style, size=70, thickness=3,
                                                center=center))
        painter.setPen(QColor(220, 224, 230))
        painter.drawText(x0, pad + cell + 4, cell, label_h,
                         Qt.AlignHCenter | Qt.AlignVCenter, style)

    painter.end()
    path = out_dir / "crosshair_styles.png"
    img.save(str(path))
    print(f"  准心 5 样式对照图 → {path.name}")

    # T 型单独放大一张，外加旋转 90°，确认竖杆是跟着转的
    for angle in (0, 90):
        big = QImage(260, 260, QImage.Format_ARGB32_Premultiplied)
        big.fill(QColor(24, 26, 30))
        p = QPainter(big)
        paint_crosshair(p, CrosshairFrame(style="t_shape", size=140, thickness=4,
                                          rotation=float(angle),
                                          center=QPointF(130, 130)))
        p.end()
        name = f"t_shape_{angle}deg.png"
        big.save(str(out_dir / name))
        print(f"  T 型 {angle}° 放大 → {name}")


def capture_pages(out_dir: Path, pages: list[str]) -> list[str]:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
    if len(QFontDatabase.families()) == 0:
        print("!! 字体库为空，截图不可信，拒绝出图")
        raise SystemExit(2)

    from config import config

    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()
    config.ui_expert_mode = True
    # 准心页要拍 t_shape，先把配置切过去
    config.crosshair_style = "t_shape"

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    for _ in range(3):
        app.processEvents()

    done = []
    for pid in pages:
        if pid not in win._page_names:
            print(f"  ⚠ 没有这个页面: {pid}")
            continue
        try:
            win.show_page(pid, animated=False)
            for _ in range(5):
                app.processEvents()
            page = win.pages.get(pid)
            if page is None:
                print(f"  ⚠ 页面对象为空: {pid}")
                continue
            pix = page.grab()
            path = out_dir / f"page_{pid}.png"
            pix.save(str(path))
            print(f"  {pid:<14} {pix.width()}×{pix.height()} → {path.name}")
            done.append(pid)
        except Exception as exc:
            print(f"  ❌ {pid} 截图失败: {type(exc).__name__}: {exc}")

    try:
        win.close()
    except Exception:
        pass
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"H:/tmp/r9_shots")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("== 1. 准心渲染器实拍 ==")
    capture_crosshair_styles(out_dir)

    print("\n== 2. 页面实拍 ==")
    targets = ["crosshair"] + REFACTORED + NEVER_CAPTURED
    done = capture_pages(out_dir, targets)

    print(f"\n共出图 {len(done)} 个页面 + 3 张准心图 → {out_dir}")
    missed = [p for p in targets if p not in done]
    if missed:
        print(f"⚠ 没拍到: {missed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
