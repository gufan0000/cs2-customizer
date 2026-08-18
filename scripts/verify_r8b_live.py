# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R8b-E 前置：Qt 准心的**真窗口**验收（UP-054）。

设计文档 §9-3 把「置顶 / 点击穿透 / 缩放屏居中」列为"只能在真屏幕上看"，
因此一直没做。**那个口径划得太保守了**——这三样里绝大部分能程序化验，
而且比人眼看更严：

    人眼「看着像在正中」   →  GetWindowRect 量物理像素，偏差精确到 1px
    人眼「点得动下面的东西」→  WindowFromPoint 打屏幕正中，返回的不能是准心
    人眼「没抢走焦点」     →  GetForegroundWindow 前后对比，一模一样才算过

真正需要人眼的只剩**观感**（11 个联动和老版比有没有跑偏），那是主观项。

本脚本会在屏幕正中**短暂显示**准心（默认 1.0s，`--hold` 可调）。
这是唯一一次打扰前台，且只有一个 100x100 的小方块，不抢焦点（会验证这一点）。

用法:
    python scripts/verify_r8b_live.py            # 全套
    python scripts/verify_r8b_live.py --hold 0.2 # 缩短显示时间
退出码:0=全部通过,1=有项目未通过。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

# RN-032：配置目录一律走共享工装 —— 自己 mkdir + setdefault 挡不住
# migrate_old_config() 把仓库根那份未跟踪的个人 config.json 复制进来。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_verify_r8b")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication  # noqa: E402

from crosshair_overlay import (  # noqa: E402
    CANVAS_PX,
    COLOR_MAP,
    IDLE_ANIMATIONS,
    KILL_EFFECTS,
    USER_STYLES,
    CrosshairOverlayManager,
)

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


class _Cfg:
    crosshair_size = 24
    crosshair_thickness = 2
    crosshair_color = "green"
    crosshair_style = "crosshair"
    crosshair_animation = "none"
    crosshair_kill_effect = "none"
    crosshair_custom_data = []


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def _title(hwnd):
    if not hwnd:
        return "<null>"
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    return f"{hwnd} «{buf.value or '—'}» [{cls.value}]"


def _fg(tag=""):
    """采样当前前台窗口。定位「谁改了前台」只能靠逐段采样，不能靠猜。"""
    h = user32.GetForegroundWindow()
    if tag:
        print(f"    · 前台@{tag}: {_title(h)}")
    return h


def _window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _monitor_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _opaque_pixel_count(pixmap):
    img = pixmap.toImage()
    return sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if img.pixelColor(x, y).alpha() > 0
    )


def main():
    hold = 1.0
    if "--hold" in sys.argv:
        hold = float(sys.argv[sys.argv.index("--hold") + 1])

    app = QApplication.instance() or QApplication([])
    cfg = _Cfg()
    manager = CrosshairOverlayManager(cfg)

    foreground_before = user32.GetForegroundWindow()
    print(f"显示前的前台窗口句柄: {foreground_before}")
    print(f"\n准心将在屏幕正中显示约 {hold:.1f} 秒 ——")

    manager.show_crosshair()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)

    win = manager.overlay_win
    hwnd = int(win.winId())

    print("\n== 窗口属性 ==")
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    for flag, flag_name, why in (
        (WS_EX_LAYERED, "WS_EX_LAYERED", "逐像素透明的前提"),
        (WS_EX_TRANSPARENT, "WS_EX_TRANSPARENT", "鼠标穿透"),
        (WS_EX_TOOLWINDOW, "WS_EX_TOOLWINDOW", "不进 Alt+Tab / 任务栏"),
        (WS_EX_NOACTIVATE, "WS_EX_NOACTIVATE", "点了也不激活"),
        (WS_EX_TOPMOST, "WS_EX_TOPMOST", "盖在游戏上"),
    ):
        check(f"扩展样式 {flag_name}（{why}）", ex & flag)

    print("\n== 几何（物理像素）==")
    x, y, w, h = _window_rect(hwnd)
    sw, sh = _monitor_size()
    check(f"画布物理边长 = {CANVAS_PX}", abs(w - CANVAS_PX) <= 1 and abs(h - CANVAS_PX) <= 1,
          f"实测 {w}x{h}，屏幕 {sw}x{sh}")
    cx, cy = x + w / 2, y + h / 2
    dx, dy = cx - sw / 2, cy - sh / 2
    check("准心中心与屏幕中心偏差 ≤1px", abs(dx) <= 1 and abs(dy) <= 1,
          f"偏移 ({dx:+.1f}, {dy:+.1f})")

    print("\n== 点击穿透（真做一次命中测试）==")
    pt = wintypes.POINT(int(sw // 2), int(sh // 2))
    hit = user32.WindowFromPoint(pt)
    check("屏幕正中的命中测试没有落在准心上", hit != hwnd,
          f"命中句柄 {hit}，准心句柄 {hwnd}")

    print("\n== 不打扰前台 ==")
    foreground_after = user32.GetForegroundWindow()
    check("前台窗口没有被抢走", foreground_after == foreground_before,
          f"{foreground_before} → {foreground_after}")

    print("\n== 盖不盖得住游戏（造一个假的无边框全屏窗口比 Z 序）==")
    # 这是设计文档里风险 R-1 的正面验证。真实情形：CS2 跑无边框窗口化时
    # 是一个**普通（非置顶）**的全屏窗口并持有焦点；准心是 TOPMOST。
    # TOPMOST 窗口永远排在非 TOPMOST 之上，与谁持有焦点无关——这里就验这一条。
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QWidget as _QWidget

    fake_game = _QWidget(None)
    fake_game.setWindowFlags(_Qt.FramelessWindowHint)     # 注意：**不加** WindowStaysOnTop
    fake_game.setWindowTitle("FakeGame")
    pal = fake_game.palette()
    pal.setColor(QPalette.Window, QColor(20, 24, 30))
    fake_game.setPalette(pal)
    fake_game.setAutoFillBackground(True)
    fake_game.setGeometry(int(sw / 2 - 200), int(sh / 2 - 200), 400, 400)
    fake_game.show()
    fake_game.raise_()
    fake_game.activateWindow()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)

    game_hwnd = int(fake_game.winId())

    GW_HWNDNEXT = 2

    def _z_index(target):
        h = user32.GetTopWindow(None)
        i = 0
        while h:
            if h == target:
                return i
            h = user32.GetWindow(h, GW_HWNDNEXT)
            i += 1
        return None

    z_cross = _z_index(hwnd)
    z_game = _z_index(game_hwnd)
    check("准心的 Z 序高于（非置顶的）全屏窗口",
          z_cross is not None and z_game is not None and z_cross < z_game,
          f"准心 Z={z_cross}，假游戏 Z={z_game}（数字越小越靠上）")
    # ⚠ 别断言"假游戏拿到了焦点"——Windows 不允许后台进程 SetForegroundWindow，
    # 从这个控制台进程里 activateWindow() 根本推不动前台，那个断言的**前提**就不成立。
    # （第一版就是这么写的，FAIL 的是判据不是产品。）
    # 真正该验的是：准心自己**不是**前台窗口——置顶不等于抢焦点，这两件事常被混为一谈。
    check("准心是置顶窗，但它不是前台窗口（置顶 ≠ 抢焦点）",
          user32.GetForegroundWindow() != hwnd,
          f"前台={user32.GetForegroundWindow()}，准心={hwnd}")

    fake_game.close()
    fake_game.deleteLater()
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    # 假游戏进出会改动前台，后面那条"销毁准心不改前台"要以此刻为基线，
    # 否则量到的是本脚本自己的副作用。
    foreground_baseline = _fg("关掉假游戏之后")

    print("\n== 逐样式 / 逐动画 / 逐联动真渲染 ==")
    blanks = []
    for style in USER_STYLES:
        points = [(15, 10), (15, 20), (10, 15), (20, 15)] if style == "custom" else []
        cfg.crosshair_custom_data = points
        manager.update_settings(24, 2, "green", style, "none", "none")
        app.processEvents()
        if _opaque_pixel_count(win.grab()) == 0:
            blanks.append(f"样式 {style}")
    cfg.crosshair_custom_data = []
    check(f"{len(USER_STYLES)} 个样式都画得出东西", not blanks, ",".join(blanks) or "全部有像素")

    blanks = []
    for color in COLOR_MAP:
        manager.update_settings(24, 2, color, "crosshair", "none", "none")
        app.processEvents()
        if _opaque_pixel_count(win.grab()) == 0:
            blanks.append(color)
    check(f"{len(COLOR_MAP)} 种颜色都画得出东西", not blanks, ",".join(blanks) or "全部有像素")

    blanks = []
    for anim in IDLE_ANIMATIONS:
        manager.update_settings(24, 2, "green", "crosshair", anim, "none")
        for _ in range(6):
            app.processEvents()
            time.sleep(0.01)
        if _opaque_pixel_count(win.grab()) == 0:
            blanks.append(anim)
    check(f"{len(IDLE_ANIMATIONS)} 个空闲动画都画得出东西", not blanks,
          ",".join(blanks) or "全部有像素")

    blanks = []
    for effect in KILL_EFFECTS:
        if effect == "none":
            continue
        manager.update_settings(24, 2, "green", "crosshair", "none", effect)
        manager.on_kill_event(True)
        app.processEvents()
        empty_frames = 0
        for _ in range(10):
            app.processEvents()
            time.sleep(0.02)
            if _opaque_pixel_count(win.grab()) == 0:
                empty_frames += 1
        if empty_frames:
            blanks.append(f"{effect}({empty_frames}帧空)")
    check(f"{len(KILL_EFFECTS) - 1} 个击杀联动整段都画得出东西", not blanks,
          ",".join(blanks) or "全程有像素")

    print("\n== 显示/隐藏切换（2.2.0 丝滑化的既有成果）==")
    manager.update_settings(24, 2, "green", "crosshair", "none", "none")
    t0 = time.perf_counter()
    manager.hide_crosshair()
    app.processEvents()
    manager.show_crosshair()
    app.processEvents()
    toggle_ms = (time.perf_counter() - t0) * 1000
    check("一次隐藏+显示 < 50ms（老实现重建一次曾要 916ms）", toggle_ms < 50,
          f"实测 {toggle_ms:.1f}ms")

    print("\n== 静态准心不空转 ==")
    # ⚠ 这里必须先等上一段的击杀联动走完（0.8s）再断言。
    # 第一版没等，报了 FAIL —— 但那时联动确实还在放，定时器本来就该在跑。
    # **判据缺了前提，不是产品有缺陷**。顺带把「它会自己停」也证了。
    manager.update_settings(24, 2, "green", "crosshair", "none", "none")
    from crosshair_overlay import KILL_DURATION_S

    check("联动进行中定时器在跑（该跑的时候要跑）", manager._timer.isActive())
    deadline = time.perf_counter() + KILL_DURATION_S + 0.5
    while time.perf_counter() < deadline and manager._timer.isActive():
        app.processEvents()
        time.sleep(0.01)
    check("联动结束后定时器自己停下（静态准心零唤醒）", not manager._timer.isActive())

    manager.update_settings(24, 2, "green", "crosshair", "breathing", "none")
    app.processEvents()
    check("切到有动画时定时器重新起来", manager._timer.isActive())
    manager.update_settings(24, 2, "green", "crosshair", "none", "none")
    app.processEvents()
    check("切回静态时定时器再次停下", not manager._timer.isActive())

    print("\n== 前台归属逐段采样 ==")
    _fg("样式/动画/联动跑完")
    time.sleep(max(0.0, hold - 0.5))
    before_destroy = _fg("销毁前")
    manager.destroy()
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    foreground_end = _fg("销毁后")
    check("销毁准心没有改动前台窗口", foreground_end == before_destroy,
          f"{_title(before_destroy)} → {_title(foreground_end)}")
    check("整段跑测下来前台归属没被准心改过", before_destroy == foreground_baseline,
          f"{_title(foreground_baseline)} → {_title(before_destroy)}")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n== 共 {len(results)} 项，{len(results) - len(failed)} 项通过 ==")
    if failed:
        print("未通过：" + "、".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
