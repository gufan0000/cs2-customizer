# -*- coding: utf-8 -*-
"""生成 README 用的界面截图（离屏，不打扰前台）。

用法:
    python scripts/capture_readme_shots.py                 # 全部
    python scripts/capture_readme_shots.py --only crosshair
    python scripts/capture_readme_shots.py --out /tmp/shots # 换输出目录

输出到 `docs/images/`，README 直接引用。改了界面之后重跑一次即可。

三条纪律，和本仓库其它离屏脚本一致：

1. **原生平台 + `WA_DontShowOnScreen`**，不用 `QT_QPA_PLATFORM=offscreen`。
   offscreen 平台在本机一个真实字体都没有，截出来的图文字全是方框或空白。
   `WA_DontShowOnScreen` 让控件照常参与布局、拿真实字体，但窗口**永不映射到屏幕**。
2. **托盘声明为不可用**：原生平台下 MainWindow 会真往任务栏托盘塞图标，那是打扰前台。
3. **沙箱化外部写入**：`csgo_dir` 是自动探测的，不沙箱会把用户真实 CS2 目录里的
   cfg 覆盖掉；配置与日志目录也一并指向临时目录。

**不截那 6 个"构造即起设备"的页面**（viewmodel / magnifier / flash /
voice_output / kill_icon / music）——它们构造时注册全局热键、初始化音频设备、
spawn pygame 子进程，在截图脚本里建它们等于真的占设备、真的弹全屏覆盖窗。
口径与 `bench_page_build.UNSAFE_PAGES` / `layout_overflow_audit` 一致。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# 必须在导入产品代码之前设：MainWindow 构造时就会读这些
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
_tmp = Path(tempfile.mkdtemp(prefix="cs2c_readme_shots_"))
os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_tmp / "logs"))
os.environ.pop("QT_QPA_PLATFORM", None)     # 要真实字体
for sub in ("config", "logs"):
    (_tmp / sub).mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT = 1280, 800

#: 上 README 的页面。挑的是"一眼能看懂这软件干什么"的几页，
#: 不是把 26 页全塞进去——README 不是相册。
SHOTS = [
    ("home", None, "首页：系统状态、常用入口、主题切换"),
    ("crosshair", "crosshair", "准心：样式 / 颜色 / 粗细 / 间隙，Qt 叠加层实时预览"),
    ("hud_color", "hud_color", "HUD 配色：按队伍与血量条件切换"),
    ("special_sound", "special_sound", "特殊音效：回合、C4、投掷物、血量警告"),
    ("advanced", "advanced", "高级设置：CS2 目录、主题、系统集成、快捷键总览"),
]

#: 主题条：同一页在几套主题下的对比。9 套全放太长，挑 4 套差异最大的。
THEME_STRIP = ["dark", "light", "ocean", "rose"]

UNSAFE_PAGES = {"viewmodel", "magnifier", "flash", "voice_output", "kill_icon", "music"}


def _settle(app, rounds: int = 10, pause: float = 0.05) -> None:
    """让布局、主题、动画都落定再取图。

    截图比布局审计更吃这一步：审计只要几何数字对，截图要像素也对——
    动画没跑完就 grab，会截到半透明的过渡态。
    """
    for _ in range(rounds):
        app.processEvents()
        time.sleep(pause)


def build_window(app, theme: str = "dark"):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSystemTrayIcon

    # 原生平台下 MainWindow 会真的往托盘塞图标 —— 那是打扰前台。
    # 产品代码里已有"托盘不可用"的优雅降级分支。
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    # 必须先把资源目录骨架建好，否则截出来的首页开局就是黄灯「音频 · 需检查12」。
    # 那 12 个是 REQUIRED_AUDIO_DIRS 的数量——真实启动时这一步在**后台线程**里做
    # （main_widget.py 的「阶段 1.5 静默资源迁移」/ background_loader 阶段 2），
    # 而本脚本用 auto_background_preload=False 建窗口、也不走 main_widget 入口，
    # 于是那一步压根没发生。同步补上，让截图反映"启动完成后"的样子。
    from resource_manager import ResourceManager

    ResourceManager.copy_resources_to_appdata()

    from config import config
    from theme_manager import get_theme_manager

    config.ui_expert_mode = False        # README 展示默认形态，不开专家模式
    config.compact_mode = False
    get_theme_manager().set_theme(theme)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    # 离屏"屏幕"可能比目标尺寸小，show 后应用会向屏幕钳制几何；强制回到目标尺寸
    win.setMinimumSize(WIDTH, HEIGHT)
    win.resize(WIDTH, HEIGHT)
    _settle(app)
    return win


def grab(win, app, path: Path) -> bool:
    _settle(app, rounds=6)
    pix = win.grab()
    if pix.isNull() or pix.width() < 100:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(pix.save(str(path), "PNG"))


def capture_pages(app, out: Path, only: str | None) -> list[str]:
    win = build_window(app)
    made = []
    for name, page_id, _desc in SHOTS:
        if only and only != name:
            continue
        if page_id in UNSAFE_PAGES:
            print(f"  跳过 {name}（构造即起设备）")
            continue
        if page_id is not None:
            try:
                win.show_page(page_id, animated=False)
            except Exception as exc:
                print(f"  ❌ {name}: 切页失败 {exc}")
                continue
        target = out / f"{name}.png"
        if grab(win, app, target):
            kb = target.stat().st_size // 1024
            print(f"  ✅ {name}.png  ({kb} KB)")
            made.append(target.name)
        else:
            print(f"  ❌ {name}: grab 返回空图")
    win.close()
    app.processEvents()
    return made


def capture_theme_strip(app, out: Path) -> str | None:
    """同一页 × 4 主题，拼成 2×2。

    ⚠ 主题必须在**窗口建好之后**切。`get_theme_manager().set_theme()` 在构造前调没用——
    MainWindow 构造时会按 `config.ui_theme` 自己刷一遍样式，把之前设的盖掉。
    第一版就是这么写的，结果四格全是深色，四张图看着一模一样。
    与 `layout_overflow_audit` 的做法保持一致：建一个窗口，循环切主题。

    横排四格在 README 里每格只有 400px 宽，什么都看不清；改 2×2，每格 800px。
    """
    from PIL import Image

    win = build_window(app)
    # 主题条用**准心页**而不是首页，两个原因：
    # ① 准心页的配色元素更多（滑块、单选、预览画布、语义色按钮），主题差异一眼可见；
    # ② 首页「运行面板」里有「主题 · 深色」这类状态标签，而状态条的刷新是延迟的
    #    ——切主题后连刷两次都还慢一档，四格里会出现"下拉写着深海、
    #    标签写着浅色"这种一眼假的组合。换一页比跟状态条的缓存较劲划算。
    win.show_page("crosshair", animated=False)
    _settle(app)

    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    from config import config

    tiles = []
    for theme in THEME_STRIP:
        tm.set_theme(theme)
        # 只调 set_theme 会让样式变了、**文案没变**：顶栏下拉读的是 config.ui_theme。
        config.ui_theme = theme
        combo = getattr(win, "theme_combo", None)
        if combo is not None:
            idx = combo.findData(theme)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
        _settle(app, rounds=8)
        tmp = out / f"_theme_{theme}.png"
        if grab(win, app, tmp):
            tiles.append(tmp)
            print(f"  ✅ 主题 {theme}")
        else:
            print(f"  ❌ 主题 {theme}: grab 返回空图")
    win.close()
    app.processEvents()

    if len(tiles) < 4:
        print(f"  ⚠ 只拿到 {len(tiles)} 格，跳过拼图（2×2 需要 4 格）")
        for t in tiles:
            t.unlink(missing_ok=True)
        return None

    images = [Image.open(t) for t in tiles]
    w = min(i.width for i in images)
    h = min(i.height for i in images)
    images = [i.crop((0, 0, w, h)) for i in images]
    gap = 10
    canvas = Image.new("RGB", (w * 2 + gap, h * 2 + gap), (255, 255, 255))
    for idx, img in enumerate(images):
        canvas.paste(img, ((idx % 2) * (w + gap), (idx // 2) * (h + gap)))
    if canvas.width > 1600:
        canvas = canvas.resize((1600, int(canvas.height * 1600 / canvas.width)), Image.LANCZOS)
    dest = out / "themes.png"
    canvas.save(dest, "PNG", optimize=True)
    for t in tiles:
        t.unlink(missing_ok=True)
    print(f"  ✅ themes.png  ({dest.stat().st_size // 1024} KB, 2×2 {' / '.join(THEME_STRIP)})")
    return dest.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "images"))
    ap.add_argument("--only", default=None, help="只截某一张（见 SHOTS 里的名字）")
    ap.add_argument("--skip-themes", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    fam = len(QFontDatabase.families())
    print(f"平台: 原生 + WA_DontShowOnScreen（字体家族 {fam} 个）")
    if fam == 0:
        print("❌ 字体库为空，截出来的字会是方框或空白。别在无桌面会话里跑这个脚本。")
        return 2

    print(f"输出: {out}")
    print(f"配置/日志沙箱: {_tmp}")
    print("\n页面截图:")
    made = capture_pages(app, out, args.only)

    if not args.skip_themes and not args.only:
        print("\n主题条:")
        strip = capture_theme_strip(app, out)
        if strip:
            made.append(strip)

    print(f"\n共 {len(made)} 张: {', '.join(made)}")
    return 0 if made else 1


if __name__ == "__main__":
    raise SystemExit(main())
