# -*- coding: utf-8 -*-
"""R1-9/R1-10 排版溢出审计(2026-06-12)，R4/R5 加固，R8a 补纵向判据。

全页 × 主题 × 字号 离屏构建，比人眼扫 160 张截图快且可回归；
像素级审美仍以渲染图为准。三条判据：

1. **横向溢出**：QScrollArea 出现水平滚动(本应只纵向滚) = 破版信号。
2. **按钮文案截断**：按钮被钉死宽度时布局"放得下"，只是文字被裁——横向判据抓不到。
3. **纵向裁切**(UP-072，R8a 加)：内容装不下**且滚不动**。

⚠️ 第 3 条是补上来的，此前本脚本**只有横向判据**。纵向被压扁时连个滚动条信号
   都没有，于是 `about` 页整页无滚动区、内容最小高 1091px 压进 750px 可视区
   （用户看不到下半截也滚不动）而审计一路绿灯——UP-071 就是这么长期没被发现的。
   任何"某某维度全绿"的结论，先确认那个维度真的有判据在看。

⚠️ **默认跳过 6 个"构造即起设备"的页面（R5 加）**
   viewmodel / magnifier / flash / voice_output / kill_icon / music
   这些页构造时会注册全局热键、初始化音频设备、spawn pygame 子进程——
   在审计脚本里建它们等于**真的**占设备、真的弹出全屏覆盖窗，那就是打扰前台。
   口径与 `gui_widget._preload_skip_pages` / `bench_page_build.UNSAFE_PAGES` 一致。
   确实要测它们时用 `--include-unsafe`，但请确认此刻没有别的事情在跑。

⚠️ **默认走原生平台 + `WA_DontShowOnScreen`，不是 offscreen（R5 改）**
   offscreen 平台在本机**一个真实字体都没有**（`QFontDatabase.families()` 返回空），
   中英文的 `horizontalAdvance` 会返回同一个假值甚至 0 —— 于是"按钮文案有没有被裁"
   这类判据全部失真，跑出来的绿色是**假绿**。
   `WA_DontShowOnScreen` 让控件照常参与布局、拿真实字体度量，但窗口**永不映射到屏幕**，
   所以不会打扰前台。需要极速粗筛时用 `--offscreen`，但别拿它的文案结论当验收。

⚠️ **紧凑模式在 R11 之前从来没有被审计过（UP-100）**
   `gui_widget.py:196` 有第二套窗口尺寸：`compact_mode` 开启时窗口**固定 860×640**
   （最小尺寸也是它），顶部多一条 50px 的紧凑顶栏，侧边栏改成浮层。
   实测内容可视区只剩 **590px**，而完整模式下是 750px —— 少了 160px。
   `compact_mode` 是持久化配置（`config.py:411`），切换入口是界面上的
   `_mode_toggle_btn`（tooltip「切换紧凑/完整模式」），**用户点一下就进去了**。
   而 R0~R10 十一轮所有排版审计跑的都是 1280×800 / 1200×800 的完整模式，
   `scripts/` 里搜 `compact` 一个审计都没有 —— 又一次"全绿要先问分母"，
   这次错在**尺寸轴**上而不是页面轴上（页面轴那次是 UP-096）。
   现在用 `--compact` 跑这一档，CI 也跑。

同时本脚本会：
- 设 `CS2C_SAFE_MODE_ACTIVE=1`，让 MainWindow 跳过 pygame 准心的延迟自动显示
  （否则跑到一半会有一个全屏置顶的准心覆盖窗冒出来）；
- 把系统托盘声明为不可用，避免原生平台下真的在任务栏托盘里冒出一个图标；
- 隔离配置与日志目录，绝不碰用户真实数据。

用法:
    python scripts/layout_overflow_audit.py                    # 安全档(默认)
    python scripts/layout_overflow_audit.py --width 1200 --height 800
    python scripts/layout_overflow_audit.py --themes all       # 9 主题全遍历
    python scripts/layout_overflow_audit.py --compact          # 紧凑模式 860×640
    python scripts/layout_overflow_audit.py --include-unsafe   # 会打扰前台，慎用
退出码: 0=零溢出,1=有溢出。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

# 让 MainWindow 跳过 pygame 准心自动显示(gui_widget 里认这个变量)
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
# 注意:QT_QPA_PLATFORM 在 main() 里按 --offscreen 决定,见那里的说明。
# 它只需早于 QApplication 构造,不必早于 import。

_tmp = Path(tempfile.gettempdir()) / "cs2customizer_layout_audit"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_tmp / "logs"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 与 gui_widget._preload_skip_pages / bench_page_build.UNSAFE_PAGES 同一份名单。
# 改这里请三处一起改。
UNSAFE_PAGES = {"viewmodel", "magnifier", "flash", "voice_output", "kill_icon", "music"}

# UP-084: 这份名单对**排版审计**来说过粗。页面"不安全"是因为构造时会做某件
# 打扰前台的事,而那件事往往挂在一个**配置开关**下——把开关在隔离配置里关掉,
# UI 照样完整构建,危险副作用不发生。
#
#   magnifier: __init__ → enable_magnifier(interactive=False) → _setup_key_detection()
#              → 注册全局热键(右键/F2/…),会劫持用户的鼠标右键。
#              config.magnifier_enabled=False 时走 disable_magnifier() 分支,不注册。
#
# 名单本身不动(它还服务于预载跳过、建页基准等别的用途),这里只在审计里
# 按页给出"中和条件"。中和不了的仍旧跳过,并照旧把跳过的页打印出来——
# 静默少测会被读成"全都覆盖了"。
NEUTRALIZABLE = {
    "magnifier": {"magnifier_enabled": False},
}

# UP-100: 紧凑模式的窗口尺寸。与 `gui_widget.MainWindow.__init__`（最小尺寸）
# 和 `_setup_window_size` 的紧凑分支（固定几何 + 居中）是同一组数——改那边请一起改。
# 实测这一档的内容可视区只有 590px（640 - 50px 紧凑顶栏），比完整模式的 750px 少 160px。
COMPACT_SIZE = (860, 640)
FULL_SIZE = (1280, 800)

ALL_THEMES = ("dark", "light", "green", "purple", "ocean", "warm", "rose", "contrast")


def _scopes(page, app):
    """把一个页面拆成若干「真正被布局过的测量范围」。

    R5 修的假阳性：直接对整页 `findChildren(QScrollArea)` 会连**非当前页签**里的
    滚动区一起量。Qt 不给隐藏的页签做布局，那些控件保留着构造时的陈旧几何
    （实测 special_sound 的隐藏页签视口只有 618~624px，而页签容器有 968px），
    于是稳定误报"溢出 58~140px"。逐个 `setCurrentIndex` 把页签切出来再量之后，
    四个页签全部零溢出——**那条缺陷根本不存在**。

    改成逐页签测量还顺带把覆盖变真了：以前非当前页签等于从没被检查过。

    返回 [(范围名 or None, 控件), ...]。
    """
    from PySide6.QtWidgets import QTabWidget

    tabs = [t for t in page.findChildren(QTabWidget) if t.count() > 0]
    if not tabs:
        return [(None, page)]

    out = []
    for tw in tabs:
        original = tw.currentIndex()
        for i in range(tw.count()):
            tw.setCurrentIndex(i)
            # 两拍:第一拍触发布局请求,第二拍让布局真正落地
            app.processEvents()
            app.processEvents()
            widget = tw.currentWidget()
            if widget is not None:
                out.append((tw.tabText(i), widget))
        tw.setCurrentIndex(original)
        app.processEvents()
    return out


def _elided_buttons(scope):
    """返回该范围内**文案放不下**的按钮 [(文案, 实际宽, 需要宽), ...]。

    判据：向 style 要**文字实际可用区**（`SE_PushButtonContents`），
    再跟 `fontMetrics().horizontalAdvance(text)` 比。

    不用 `sizeHint().width() > width()`：那条判据会被 QSS 的 padding 带偏。
    实测帮助面板那颗 24×24 的 "?" 按钮，sizeHint 报 47px（padding 16×2 撑的），
    但 "?" 字形只有 7px、画得下得很——9 个页面集体误报。
    padding 放不下不等于文字放不下，只有后者才是用户看得见的缺陷。

    为什么要单独查这个：横向溢出检测抓不到它。按钮被 `setFixedWidth` 钉死时，
    布局完全"放得下"（不会产生横向滚动条），只是**文字被裁**——
    对用户来说是"这个按钮写的什么看不全"，对审计来说却一片绿。
    """
    from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

    out = []
    for btn in scope.findChildren(QPushButton):
        text = btn.text().strip()
        if not btn.isVisible() or not text or btn.width() <= 0:
            continue
        opt = QStyleOptionButton()
        btn.initStyleOption(opt)
        content = btn.style().subElementRect(QStyle.SE_PushButtonContents, opt, btn)
        avail = content.width()
        if btn.icon() and not btn.icon().isNull():
            avail -= btn.iconSize().width() + 4
        need = btn.fontMetrics().horizontalAdvance(text)
        if avail > 0 and need > avail + 1:   # 1px 容差
            out.append((text, avail, need))
    return out


def _vertical_clip_of(scope, avail_h):
    """返回该范围「装不下且滚不动」的纵向缺口像素；没问题返回 None。

    UP-072：本脚本此前**只有横向判据**。可横向溢出只在有滚动区时才表现为
    水平滚动条，纵向被压扁则连信号都没有——`about` / `death_sound` 两页整页
    没有 QScrollArea，内容最小高 1091px 压进 750px 的可视区，用户既看不到
    下半截也滚不动，而审计一路绿灯。UP-071 就是这么长期没被发现的。

    ⚠️ **本判据的第一版有三个洞，全部由对抗复核实测查出，这里记下来免得再犯**：

    1. 它用 `scope.findChildren(QScrollArea)` 找外层滚动区，而 `findChildren`
       **不含控件自身**。`utility` 页的两个页签，scope 本身就是 QScrollArea ——
       于是走到"无滚动区"分支，`scope.layout()` 是 None，退回去量滚动区**外壳**的
       `minimumSizeHint()`（恒 58~62px，与内容多少完全无关），判据永远返回 None。
       实测：内容 3192px 塞进 410px 视口且纵向滚动关掉，判据照样说没问题。
    2. 它把"树序第一个非嵌套 QScrollArea"当页面级滚动区，于是 HelpPanel 内部的
       `helpScrollArea` 被误认，**9 个带帮助面板的页面（含 death_sound）被永久豁免**。
    3. "只要找到一个能滚的滚动区就整体 return None" —— 实测 54 个测量范围里
       **49 个走这条早退**，判据实际只覆盖 5 个。页头/操作条这类**滚动区之外**的
       固定内容被压扁，一条都看不见。

    现在不再对滚动区做特判。理由：`layout.minimumSize()` **本身就已经把
    「滚动区可以被压小」算进去了** —— 页面若有正经的根滚动区，这个值只是
    页头 + 滚动区最小高(约 60px) + 操作条，很小；页面若没有滚动区，这个值就是
    全部内容的高度。一个判据就能区分两者，特判反而制造了上面三个洞。

    唯一还需要单独处理的是「scope 自己就是滚动区」：它没有用户 layout，
    得改量内层 widget 的最小高 vs viewport 高。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea

    if isinstance(scope, QScrollArea):
        if scope.verticalScrollBarPolicy() != Qt.ScrollBarAlwaysOff:
            return None  # 滚得动就不是缺陷
        inner = scope.widget()
        need = inner.minimumSizeHint().height() if inner is not None else 0
        have = scope.viewport().height()
        return (need - have) if (have > 0 and need > have + 8) else None

    layout = scope.layout()
    need = layout.minimumSize().height() if layout is not None else scope.minimumSizeHint().height()

    have = avail_h
    if scope.height() > 0:
        # 两头都要防：内容顶不下时 Qt 会把窗口撑大，`scope.height()` 被膨胀，
        # 缺口会凭空消失；而页签内容的真实可视高又比整页 `avail_h` 小得多
        # （实测 414px vs 750px，中间 336px 是判据看不见的盲带）。取两者更小者。
        have = min(avail_h, scope.height())

    if have > 0 and need > have + 8:  # 容差 8px
        return need - have
    return None


def _overflow_of(scope):
    """返回该范围内最外层滚动区的横向溢出像素；无溢出返回 None。"""
    from PySide6.QtWidgets import QScrollArea

    for sa in scope.findChildren(QScrollArea):
        # 只看最外层滚动区:内层(地图预览/画廊)的横向滚动是有意设计
        anc, nested = sa.parentWidget(), False
        while anc is not None and anc is not scope:
            if isinstance(anc, QScrollArea):
                nested = True
                break
            anc = anc.parentWidget()
        if nested:
            continue
        hbar = sa.horizontalScrollBar()
        if hbar is not None and hbar.maximum() > 8:  # 容差 8px
            return hbar.maximum()
    return None


def main():
    ap = argparse.ArgumentParser(description="CS2 Customizer 排版溢出审计")
    # 默认留空，好让 --compact 换掉整档默认值而又不覆盖用户显式给的尺寸
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--compact", action="store_true",
                    help="按紧凑模式跑（config.compact_mode=True，窗口 860×640，"
                         "多一条 50px 紧凑顶栏、侧边栏改浮层）。UP-100：这一档在 R11 "
                         "之前从来没被审计过，而用户点一下界面上的切换按钮就能进去。")
    ap.add_argument("--themes", default="dark,light",
                    help='逗号分隔；"all" = 8 个有 QSS 的主题全遍历'
                         '(minimal 走系统原生样式，不参与)')
    ap.add_argument("--scales", default="1.0,1.1,1.25")
    ap.add_argument("--offscreen", action="store_true",
                    help="用 offscreen 平台跑(更快)。但本机 offscreen 没有任何真实字体，"
                         "文字度量失真——**文案截断结论不可信**，只适合粗筛布局溢出。")
    ap.add_argument("--include-unsafe", action="store_true",
                    help="连同 6 个构造即起热键/音频设备/子进程的页面一起测。"
                         "会真的占设备、真的弹全屏覆盖窗——即打扰前台。慎用。")
    ap.add_argument("--require-fonts", action="store_true",
                    help="字体库为空时直接失败(退出码 2)。CI 必开：无字体环境下"
                         "文字度量全失真，跑出来的绿是**假绿**，"
                         "而一个会假绿的门禁比没有门禁更坏。")
    args = ap.parse_args()

    base_w, base_h = COMPACT_SIZE if args.compact else FULL_SIZE
    width = args.width if args.width is not None else base_w
    height = args.height if args.height is not None else base_h

    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    else:
        # 原生平台才有真实字体;窗口靠 WA_DontShowOnScreen 不映射到屏幕
        os.environ.pop("QT_QPA_PLATFORM", None)

    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication.instance() or QApplication([])

    if not args.offscreen:
        # 原生平台下 MainWindow 会真的往任务栏托盘塞一个图标——那是打扰前台。
        # 声明托盘不可用,产品代码里已有优雅降级分支(会打日志"系统托盘不可用")。
        QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
        from PySide6.QtGui import QFontDatabase
        fam = len(QFontDatabase.families())
        print(f"平台: 原生 + WA_DontShowOnScreen（字体家族 {fam} 个，度量真实）")
        if fam == 0:
            print("!! 字体库为空，文案截断结论不可信")
            if args.require_fonts:
                print("!! --require-fonts 已开启，拒绝在无字体环境下给出结论")
                return 2
    else:
        print("平台: offscreen —— ⚠ 无真实字体，**文案截断结论不可信**，仅供粗筛")
        if args.require_fonts:
            print("!! --require-fonts 与 --offscreen 冲突：offscreen 拿不到真实字体度量")
            return 2

    from config import config
    from theme_manager import get_theme_manager
    from ui_design_system import apply_font_scale

    # UP-090: 配置/日志目录已隔离，但 csgo_dir 是自动探测的，会指到用户真实
    # 游戏目录。放大镜页构建时会往那里写 cs2customizer.cfg（还是默认配置的内容）。
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    # 专家页一并检测
    config.ui_expert_mode = True

    # UP-100: 必须在 MainWindow 构造**之前**设。`MainWindow.__init__` 一进来就
    # `self._compact_mode = getattr(config, 'compact_mode', False)` 并据此定最小尺寸，
    # 构造完再改这个配置项，窗口不会跟着变——只会得到一个"尺寸像紧凑、外壳是完整"的
    # 四不像，量出来的可视区是假的。
    config.compact_mode = bool(args.compact)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    if not args.offscreen:
        # 参与布局但永不映射到屏幕——这是"拿真实字体又不打扰前台"的关键
        from PySide6.QtCore import Qt as _Qt
        win.setAttribute(_Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    # 离屏"屏幕"只有 800x800,应用的几何恢复会向屏幕钳制;show 后强制回到目标尺寸
    win.setMinimumSize(width, height)
    win.resize(width, height)
    app.processEvents()
    if win.width() < width:
        print(f"!! 无法达到目标宽度: 实际 {win.width()}")

    tm = get_theme_manager()
    page_ids = list(win._page_names.keys())
    # UP-096: 总页数要单独留一份。以前只打印"页面 22"，读起来像全覆盖，
    # 实际是 22/27——UP-094/095 两个真缺陷就藏在没被覆盖的那 5 页里，
    # 藏了很多轮，因为报告从没说过分母是多少。
    total_pages = len(page_ids)
    skipped = []
    neutralized = []
    if not args.include_unsafe:
        # UP-084: 能靠配置开关中和掉危险副作用的页,纳入审计;中和不了的才跳过。
        for pid, overrides in NEUTRALIZABLE.items():
            if pid not in page_ids:
                continue
            for attr, value in overrides.items():
                setattr(config, attr, value)
            neutralized.append(f"{pid}（{', '.join(f'{k}={v}' for k, v in overrides.items())}）")
        skipped = sorted(p for p in page_ids
                         if p in UNSAFE_PAGES and p not in NEUTRALIZABLE)
        page_ids = [p for p in page_ids if p not in skipped]

    themes = ALL_THEMES if args.themes.strip() == "all" else tuple(
        t.strip() for t in args.themes.split(",") if t.strip())
    scales = tuple(float(s) for s in args.scales.split(",") if s.strip())

    problems = []
    elided = []
    clipped = []
    checked = 0

    for theme in themes:
        for scale in scales:
            apply_font_scale(scale)
            tm.set_theme(theme)
            app.processEvents()
            for pid in page_ids:
                try:
                    win.show_page(pid, animated=False)
                    app.processEvents()
                    page = win.pages.get(pid)
                    if page is None:
                        continue
                    # 可视高 = 目标窗口高 - 窗口装饰/导航栏等固定开销。
                    # 不能直接用容器的 height()：内容顶不下时 Qt 会把窗口撑大，
                    # 那样量出来的"可视高"是被内容膨胀过的，缺口会凭空消失。
                    container = page.parentWidget()
                    chrome = win.height() - (container.height() if container is not None else win.height())
                    avail_h = height - max(0, chrome)

                    for scope_name, scope in _scopes(page, app):
                        checked += 1
                        label = pid if scope_name is None else f"{pid}/{scope_name}"
                        over = _overflow_of(scope)
                        if over is not None:
                            problems.append((theme, scale, label, over))
                        short = _vertical_clip_of(scope, avail_h)
                        if short is not None:
                            clipped.append((theme, scale, label, short, avail_h))
                        for text, have, need in _elided_buttons(scope):
                            elided.append((theme, scale, label, text, have, need))
                except Exception as exc:
                    problems.append((theme, scale, pid, f"异常:{exc}"))

    apply_font_scale(1.0)
    tm.set_theme(getattr(config, "ui_theme", "dark") or "dark")

    # UP-100: 档位要和覆盖面一样**每次都报**。同一句"全绿"，跑的是完整模式
    # 还是紧凑模式，结论完全不是一回事——不写出来就会被读成"两档都绿"。
    mode = "紧凑模式（compact_mode=True）" if args.compact else "完整模式"
    print(f"\n== {mode} ｜ 窗口 {width}×{height} ｜ 主题 {len(themes)} × "
          f"字号 {len(scales)} × 页面 {len(page_ids)} = 检查 {checked} 个组合 ==")
    # UP-096: 覆盖面**每次都要报**，不是只在有跳过时才报。
    # 静默少测会被读成"全都覆盖了"——这正是 UP-094/095 藏了很多轮的原因。
    covered = f"   覆盖面: {len(page_ids)}/{total_pages} 个页面"
    if len(page_ids) == total_pages:
        print(covered + "（全覆盖）")
    else:
        print(covered + f"，**未覆盖 {total_pages - len(page_ids)} 个**")
    if neutralized:
        print(f"   已中和后纳入 {len(neutralized)} 个原本"
              f"「不安全」的页面: {'; '.join(neutralized)}")
    if skipped:
        print(f"   已跳过 {len(skipped)} 个页面(构造即起热键/音频设备/子进程，"
              f"测它们会打扰前台): {', '.join(skipped)}")
        print("   需要覆盖它们请加 --include-unsafe（会打扰前台，需在授权时段跑）")
    if problems:
        for theme, scale, pid, detail in problems:
            print(f"  溢出: [{theme} x{scale}] {pid} -> {detail}")
    else:
        print("  ✓ 无水平溢出")

    # 按钮文案截断:横向溢出检测抓不到(按钮被钉死时布局"放得下",只是文字被裁)
    if elided:
        seen = {}
        for theme, scale, pid, text, have, need in elided:
            seen.setdefault((pid, text), []).append((theme, scale, have, need))
        print(f"  ✗ {len(seen)} 处按钮文案放不下(会被打省略号):")
        for (pid, text), hits in sorted(seen.items()):
            theme, scale, have, need = hits[0]
            worst = max(n - h for _t, _s, h, n in hits)
            print(f"     [{pid}] 「{text}」 文字可用区 {have}px 需 {need}px "
                  f"(差 {worst}px，命中 {len(hits)}/{len(themes) * len(scales)} 个主题×字号)")
    else:
        print("  ✓ 无按钮文案截断")

    # UP-072: 纵向裁切且滚不动——横向判据完全看不见这一类
    if clipped:
        seen = {}
        for theme, scale, pid, short, avail in clipped:
            seen.setdefault(pid, []).append((theme, scale, short, avail))
        print(f"  ✗ {len(seen)} 处内容纵向装不下且无法滚动:")
        for pid, hits in sorted(seen.items()):
            worst = max(s for _t, _s, s, _a in hits)
            avail = hits[0][3]
            print(f"     [{pid}] 最小高超出可视区 {worst}px(可视 {avail}px)，"
                  f"命中 {len(hits)}/{len(themes) * len(scales)} 个主题×字号")
    else:
        print("  ✓ 无纵向裁切")

    win.close()
    win.deleteLater()
    app.processEvents()
    return 1 if (problems or elided or clipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
