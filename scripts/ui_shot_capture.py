# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""把主界面每一页离屏拍成 PNG，供人眼 / 外审模型审视觉。

**这是「像素级证据」那一条腿**。`layout_overflow_audit.py` 量的是控件几何，
量不到 `drawText` 画出界、占位文字被切、信息挤在一起这类问题——
KI-7 那 73 条判据全绿的同时，预览框里的占位文字两头各被切掉一个字，
就是被截图抓出来的。两条腿要一起跑，谁也替代不了谁。

安全口径逐条抄 `layout_overflow_audit.py`，理由见那边的注释，这里只列结论：
  · **原生平台 + `WA_DontShowOnScreen`** —— 拿真实字体，但窗口永不映射到屏幕。
    offscreen 平台在本机 `QFontDatabase.families()` 返回 **0**，中文全渲染成方块；
    拿方块图去做视觉评审等于自己造误报，所以字体库为空时**直接拒绝出图**。
  · 托盘声明不可用、`CS2C_SAFE_MODE_ACTIVE=1`、配置/日志目录隔离、
    `sandbox_external_writes()` 掐掉落盘与 csgo_dir 外写。
  · 默认跳过 4 个"构造即起设备"的页，另 2 个（magnifier/kill_icon）靠配置开关中和后纳入。
    名单与中和条件与排版审计**同源**，改一处请一起改。

⚠ `QImage.save()` 失败时**只返回 False，不抛异常**——目录不存在就静默丢图，
   脚本却照样打印成功。这里显式检查返回值。

用法:
    python scripts/ui_shot_capture.py --out H:/tmp/uishots            # 完整模式
    python scripts/ui_shot_capture.py --out H:/tmp/uishots --compact  # 紧凑模式
    python scripts/ui_shot_capture.py --out H:/tmp/uishots --pages about,advanced
退出码: 0=全部出图, 1=有页面失败, 2=环境不合格(无字体)。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")

# RN-032：配置目录一律走共享工装。自己 mkdir + setdefault 的老写法挡不住
# `migrate_old_config()` 把仓库根那份未跟踪的个人 config.json 复制进来 ——
# 实测本脚本抓出来的图长期是**开发机配置**的样子，不是全新用户的样子。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ui_mode  # noqa: E402  界面模式（普通/专家）的唯一真相源，见 RN-134
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_ui_shots")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# RN-005：中和表全仓唯一一份（这段以前在 5 支脚本里各写一遍，内容 1~3 项不等，
# 后果是 flash / viewmodel / voice_output 三页被全部 5 支跳过 —— 零覆盖）。
from _audit_neutralize import (  # noqa: E402
    apply as neutralize_apply,
    describe as neutralize_describe,
    enable_audit_mode,
    unsafe_pages,
)

enable_audit_mode()   # 必须在 import 产品模块之前

COMPACT_SIZE = (860, 640)
FULL_SIZE = (1280, 800)


def _save(widget, path: Path) -> bool:
    from PySide6.QtGui import QImage

    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(widget.size(), QImage.Format_ARGB32)
    image.fill(0xFF14161C)
    widget.render(image)
    if not image.save(str(path)):
        print(f"!! 存图失败: {path}")
        return False
    return True


def _safe_name(text: str) -> str:
    """页签名压成**纯 ASCII**。

    ⚠ 不是洁癖：这些图的第一消费者是外审模型，路径要拼进 prompt 里。
    「中文路径能不能被它的 sandbox 读到」是个没验证过的变量，
    而页签名恰好全是中文（手枪 / 血量警告 / 回合）。文件名里已经带页签序号，
    丢掉中文不影响定位，所以直接把这个变量消掉。
    """
    keep = [c for c in str(text).strip() if c.isalnum() and c.isascii()]
    return "".join(keep)


def _capture_tabs(app, win, pid: str, out: Path, mode: str, failed: list) -> int:
    """有页签的页，每个页签各拍一张。

    ⚠ 为什么需要这个：默认只拍"当前页签"，而 `gun_sound`（5 个页签）和
    `special_sound`（4 个页签）**只有第一个页签**进过任何一次视觉巡检。
    外审 2026-08-17 那三轮全部只看到「手枪」和「投掷物」——
    C4 / 血量警告 / 回合三个页签的版面从来没有第二双眼睛看过。
    这与 RN-030（排版审计对有页签的页只量当前页签内容）是同一个盲区的两条腿。

    拍完把页签**复位到原来那个**：不复位会让后续基线/指纹拿到"停在末页签"的
    状态，而基线是按"刚进页面"的样子立的。
    """
    from PySide6.QtWidgets import QTabWidget

    page = getattr(win, "pages", {}).get(pid)
    if page is None:
        return 0
    shots = 0
    for tab_widget in page.findChildren(QTabWidget):
        if tab_widget.count() <= 1:
            continue
        original = tab_widget.currentIndex()
        try:
            for index in range(tab_widget.count()):
                tab_widget.setCurrentIndex(index)
                for _ in range(3):
                    app.processEvents()
                name = _safe_name(tab_widget.tabText(index))
                stem = f"{mode}_{pid}__tab{index}" + (f"_{name}" if name else "")
                path = out / f"{stem}.png"
                if _save(win, path):
                    shots += 1
                else:
                    failed.append(f"{pid}#tab{index}")
        finally:
            tab_widget.setCurrentIndex(original)
            app.processEvents()
    return shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--compact", action="store_true", help="紧凑模式 860x640")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--pages", default="", help="逗号分隔，只拍这几页")
    ap.add_argument("--include-unsafe", action="store_true",
                    help="连同构造即起热键/音频设备的页一起拍——会打扰前台，慎用")
    ap.add_argument("--tabs", action="store_true",
                    help="有页签的页逐个页签各拍一张（默认只拍当前页签）")
    _ui_mode.add_expert_argument(ap)
    args = ap.parse_args()

    width, height = COMPACT_SIZE if args.compact else FULL_SIZE

    os.environ.pop("QT_QPA_PLATFORM", None)      # 原生平台才有真实字体
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

    fam = len(QFontDatabase.families())
    if fam == 0:
        print("!! 字体库为空 —— 中文会渲染成方块，这种图做视觉评审只会造误报。拒绝出图。")
        return 2
    print(f"平台: 原生 + WA_DontShowOnScreen（字体家族 {fam} 个）")

    from config import config
    from theme_manager import get_theme_manager
    from ui_design_system import apply_font_scale
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()
    # RN-134：默认按**产品默认的普通模式**取样 —— 这里原来写死 `= True`，
    # 于是十七轮外审看的全是专家视图（连"已经收进专家模式"的卡片都照拍不误）。
    _ui_mode.apply(config, args.expert)
    # 必须在 MainWindow 构造**之前**设：__init__ 一进来就据此定最小尺寸，
    # 构造完再改只会得到"尺寸像紧凑、外壳是完整"的四不像（UP-100）。
    config.compact_mode = bool(args.compact)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(width, height)
    win.resize(width, height)
    app.processEvents()
    if win.width() < width:
        print(f"!! 未达目标宽度: 实际 {win.width()}")

    page_ids = list(win._page_names.keys())
    total = len(page_ids)
    neutralized = []
    skipped = []
    if not args.include_unsafe:
        neutralized = neutralize_apply(config, page_ids)
        skipped = sorted(p for p in page_ids if p in unsafe_pages())
        page_ids = [p for p in page_ids if p not in skipped]
    if args.pages.strip():
        want = {p.strip() for p in args.pages.split(",") if p.strip()}
        page_ids = [p for p in page_ids if p in want]

    apply_font_scale(args.scale)
    get_theme_manager().set_theme(args.theme)
    app.processEvents()

    out = Path(args.out)
    mode = "compact" if args.compact else "full"
    ok, failed = 0, []
    extra_tabs = 0
    for pid in page_ids:
        try:
            _ui_mode.goto(win, pid)
            for _ in range(3):
                app.processEvents()
            # 拍**整窗**而不是页面控件：用户看到的是含侧边栏/顶栏的整体，
            # 页面单独拍会漏掉导航区与内容区之间的关系问题。
            if _save(win, out / f"{mode}_{pid}.png"):
                ok += 1
            else:
                failed.append(pid)
            if args.tabs:
                extra_tabs += _capture_tabs(app, win, pid, out, mode, failed)
        except Exception as exc:
            print(f"!! {pid} 异常: {exc}")
            failed.append(pid)

    apply_font_scale(1.0)
    # 界面模式必须写进报告：不写，读图的人（和外审）会默认这是普通视图（RN-134）
    print(f"\n== {mode} 模式 {width}x{height} 主题 {args.theme} 字号 {args.scale}"
          f" · 界面 {_ui_mode.describe(args.expert)} ==")
    print(f"   出图 {ok} 张 → {out}"
          + (f"（另 {extra_tabs} 张来自逐页签）" if extra_tabs else ""))
    # 覆盖面每次都要报：静默少拍会被读成"全都看过了"（UP-096 的教训）
    print(f"   覆盖面: {len(page_ids)}/{total} 页"
          + (f"，跳过构造即起设备的 {len(skipped)} 页: {', '.join(skipped)}" if skipped else "（全覆盖）"))
    if neutralized:
        print(f"   已中和后纳入: {neutralize_describe(neutralized)}")
    if failed:
        print(f"!! 失败 {len(failed)} 页: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
