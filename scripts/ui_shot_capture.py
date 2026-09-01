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
import json
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
    account_session_leak,
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


def _capture_whole(app, win, pid: str, out: Path, mode: str, failed: list) -> int:
    """内容比视口高的页，**另拍一张没有折线的整页图**（RN-170）。

    ⚠⚠ 这补的是一个存在了 24 轮外审的盲区：`_save()` 渲染的是**窗口**
    （1280×800 / 860×640），所以每一页**折线以下的部分从来没被看过**。
    页签盲区（`_capture_tabs`）解除之后，这是同一个形状的第二条腿。

    ⭐⭐ 而它同时在**污染审查工具本身**：长页面在折线处永远有一个被切一半的
    元素，而外审**稳定地把它读成"这个容器坏了"**。2026-08-22 实测，
    12 发里 9 发非 NONE 全是这一条，且每一发都点名一个容器断言它损坏：

        「「+ 导入」卡片超出容器底边导致底部文字被裁切」（full，3/3）
        「「风格库」标题容器高度被严重挤压」（compact，3/3）
        「颜色选项被卡片底部边缘截断」（crosshair compact，3/3）

    三条**实测全是假的**：导入卡 127px 在 160px 容器里（富余 34px）、
    风格库标题 21px = sizeHint、颜色选项底部距父容器还有 78px。

    ⭐ 所以修法不是「让它别报」，是**别再给它一张注定会被误读的图**。

    ⚠⚠ **第一版是「滚到底再拍一张窗口」，实测不行**：那样只是把折线从下边
    搬到了上边 —— 同一批图复跑，外审改口报「顶部被裁切」「标题文字上半部分
    被容器上边缘裁切」，21 发里 12 发，一模一样的假象镜像了一遍。
    ⭐⭐ **补一张"另一半"解决不了折线，因为折线跟着视口走，不跟着内容走。**
    ⇒ 现在渲染的是**滚动区里那个内容控件本身、按它的完整高度** ——
    一张**根本没有折线**的图。

    ⚠ 它**不替代**整窗那张：整窗那张要看的是导航区与内容区的关系
    （见 `_save` 的调用处注释），这一张只看内容自己有没有真的坏。
    两张各有各的问题域，缺一不可。
    """
    from PySide6.QtWidgets import QScrollArea

    page = getattr(win, "pages", {}).get(pid)
    if page is None:
        return 0
    # ⚠ 只认**看得见的**滚动区。第一版没这一条，于是把 `helpScrollArea`
    # （帮助面板，一个默认隐藏的浮层）也算进来了 —— 它自己也会溢出。
    # ⚠ 而且不能只拍"滚动区里的内容控件"：`kill_icon` 的页头和状态卡
    #   **在滚动区外面**，那样拍会丢掉半页（实测拍出来 634px，比视口还矮）。
    # ⇒ 改成**把整个窗口撑高到不需要滚动**再拍整窗：既没有折线，
    #   又保住了「导航区与内容区的关系」这个只有整窗图才看得见的问题域。
    overflow = max(
        (s.verticalScrollBar().maximum()
         for s in page.findChildren(QScrollArea) if s.isVisible()),
        default=0,
    )
    if overflow <= 0:
        return 0

    original = win.size()
    original_min = win.minimumSize()
    try:
        win.setMinimumSize(0, 0)
        win.resize(original.width(), original.height() + overflow)
        for _ in range(4):
            app.processEvents()
        if _save(win, out / f"{mode}_{pid}__whole.png"):
            return 1
        failed.append(f"{pid}(whole)")
        return 0
    finally:
        # ⚠ 必须复位：不复位的话后面几页会按这个撑高的尺寸拍，
        # 而基线/对比立的是标准视口的样子（同 `_capture_tabs` 的复位理由）。
        win.setMinimumSize(original_min)
        win.resize(original)
        for _ in range(4):
            app.processEvents()


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
    ap.add_argument("--whole", action="store_true",
                    help="内容比视口高的页，**另拍一张没有折线的整页图**（RN-170）。"
                         "不给的话每一页折线以下的部分永远没人看过，"
                         "而折线处那个被切一半的元素会被外审读成「容器坏了」")
    ap.add_argument(
        "--scenario", action="append", default=[], metavar="KEY=VALUE",
        help="⭐ 造场景：拍之前往 config 上按几个值（可重复给）。"
             "值走 JSON 解析，解析不了就当字符串（`--scenario crosshair_style=custom` "
             "`--scenario crosshair_custom_data=[]`）。"
             "⚠ 出图工装默认拍的是**全新配置**，于是任何「只在某个状态下才成立的缺陷」都不进图 ——"
             "而外审**看不见的东西不会报**。RN-406 就是这么漏掉的："
             "选中「自定义」而没画过时准心一个像素都不画，"
             "而全新配置的样式是「十字」，那一屏永远拍不到那个状态。"
             "⛔ 这个开关**只给外审出图用**：基线和排版审计要的是可复现的那一档，别给它。")
    ap.add_argument("--music-bar", choices=("auto", "on"), default="auto",
                    help="音乐控制条拍不拍进去（RN-195）。"
                         "auto=按全新配置的样子，产品自己决定（没放过音乐⇒没有），"
                         "**基线拍这一档**；"
                         "on=强制建出来，量的是放过音乐的用户永远停在的那一档，"
                         "**送外审配合排版审计时拍这一档**。"
                         "⚠ 不给的话就是交给一个 8 秒定时器决定，实测会在一轮里"
                         "拍出两种可视区（见 scripts/_audit_music_bar.py）")
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

    # RN-472：落盘前的最后一道门。**必须在第一次 `_save()` 之前** ——
    # 这些图的下一站是外审，而一张图从"没拍"到"已经在送审目录里"
    # 中间没有任何一步会失败。
    leak = account_session_leak(win)
    if leak:
        print(leak)
        return 2

    # RN-195：钉住音乐控制条的档位（理由与两类工装的口径差别见该模块）。
    import _audit_music_bar as _mbar

    _mode = _mbar.MODE_WORST_CASE if args.music_bar == "on" else _mbar.MODE_PRISTINE
    print("   " + _mbar.pin(win, app, _mode))

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

    # ⭐ 造场景（RN-406）。**必须在中和之后**：中和表管的是"别让设备页起硬件"，
    # 而场景管的是"让某个状态出现在画面上"，两者不冲突；顺序反了会被中和覆盖掉。
    for item in args.scenario:
        key, _, raw = str(item).partition("=")
        key = key.strip()
        if not key:
            raise SystemExit(f"--scenario 写法是 KEY=VALUE，收到：{item!r}")
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            value = raw
        setattr(config, key, value)
        print(f"   场景: config.{key} = {value!r}")
    if args.scenario:
        # 页面是在上面 MainWindow 构造时建好的，config 改完要让它重读一遍。
        for pid in page_ids:
            page = win.pages.get(pid)
            for hook in ("_sync_overview_status", "load_settings", "refresh"):
                fn = getattr(page, hook, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception as exc:      # noqa: BLE001
                        print(f"   !! 场景刷新 {pid}.{hook} 失败: {exc}")
                    break

    apply_font_scale(args.scale)
    get_theme_manager().set_theme(args.theme)
    app.processEvents()

    out = Path(args.out)
    mode = "compact" if args.compact else "full"
    ok, failed = 0, []
    extra_tabs = 0
    extra_whole = 0
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
            if args.whole:
                extra_whole += _capture_whole(app, win, pid, out, mode, failed)
            if args.tabs:
                extra_tabs += _capture_tabs(app, win, pid, out, mode, failed)
        except Exception as exc:
            print(f"!! {pid} 异常: {exc}")
            failed.append(pid)

    apply_font_scale(1.0)
    # RN-195：回验 —— 这一批图**全程**都在同一档可视区里拍的。
    # 少了这一步，一批"前 26 张矮 42px、后 2 张不矮"的图看起来毫无异样，
    # 而外审会把那 42px 读成页面本身的差异。
    _mbar.assert_stable(win)
    # 界面模式必须写进报告：不写，读图的人（和外审）会默认这是普通视图（RN-134）
    print(f"\n== {mode} 模式 {width}x{height} 主题 {args.theme} 字号 {args.scale}"
          f" · 界面 {_ui_mode.describe(args.expert)} ==")
    extras = []
    if extra_tabs:
        extras.append(f"{extra_tabs} 张来自逐页签")
    if extra_whole:
        extras.append(f"{extra_whole} 张整页无折线")
    print(f"   出图 {ok} 张 → {out}" + (f"（另 {'、'.join(extras)}）" if extras else ""))
    if args.whole and not extra_whole:
        # 静默少拍会被读成"全都看过了"（UP-096 的教训）
        print("   ⚠ 给了 --whole 但一张都没多拍：这几页内容都没超过视口？"
              "还是滚动区取错了？—— 别把它读成「下半截没问题」")
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
