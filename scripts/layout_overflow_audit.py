# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R1-9/R1-10 排版溢出审计(2026-06-12)，R4/R5 加固，R8a 补纵向判据。

全页 × 主题 × 字号 离屏构建，比人眼扫 160 张截图快且可回归；
像素级审美仍以渲染图为准。五条判据：

1. **横向溢出**：QScrollArea 出现水平滚动(本应只纵向滚) = 破版信号。
2. **按钮文案截断**：按钮被钉死宽度时布局"放得下"，只是文字被裁——横向判据抓不到。
3. **纵向裁切**(UP-072，R8a 加)：内容装不下**且滚不动**。
4. **状态徽章高度不齐**(RN-026)：某颗芯片文案太长换了行，整排肉眼可见地歪。
5. **内层滚动区藏内容**(RN-177)：页面本身已经会滚，里面再套一层带高度上限的
   滚动区，等于把内容藏进一个用户不知道要滚的小窗口。

⚠️ 第 5 条同样是补上来的，而它补的是**一整类的分母**：第 1 条里明写着
   「只看最外层滚动区，内层的滚动是有意设计」—— 那句话对横向成立，
   对纵向不成立，于是「内层滚动区藏纵向内容」从来没有任何判据在看。
   实测代价：`viewmodel` 的预设卡视口 320px 装 872px，5 组预设只有 1 组完整
   可见，而卡副标题写着「5 组」。这一页 2026-08-18 就已关档、审计一路绿灯、
   24 轮外审也没看见（看图渲染的是窗口，折叠线以下从没进过画面，RN-170）。

⚠️ 第 3 条是补上来的，此前本脚本**只有横向判据**。纵向被压扁时连个滚动条信号
   都没有，于是 `about` 页整页无滚动区、内容最小高 1091px 压进 750px 可视区
   （用户看不到下半截也滚不动）而审计一路绿灯——UP-071 就是这么长期没被发现的。
   任何"某某维度全绿"的结论，先确认那个维度真的有判据在看。

⚠️ **默认跳过 6 个"构造即起设备"的页面（R5 加）**
   viewmodel / magnifier / flash / voice_output / kill_icon / music
   这些页构造时会注册全局热键、初始化音频设备、spawn pygame 子进程——
   在审计脚本里建它们等于**真的**占设备、真的弹出全屏覆盖窗，那就是打扰前台。
   口径与 `gui_widget._preload_skip_pages` 一致；跳过/中和的决定统一由 `scripts/_audit_neutralize.py` 出。
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

# 让 MainWindow 跳过 pygame 准心自动显示(gui_widget 里认这个变量)
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
# 注意:QT_QPA_PLATFORM 在 main() 里按 --offscreen 决定,见那里的说明。
# 它只需早于 QApplication 构造,不必早于 import。

# RN-032：配置目录走共享工装。这条对排版审计尤其要紧 ——
# 个人配置下页面全是"已配置"的样子，而**全新用户的空状态文案完全不同**
# （更长、更多、还多出几行提示），审计长期没看过那一档。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ui_mode as _um  # noqa: E402  界面模式（普通/专家）的唯一真相源，见 RN-134
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_layout_audit")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 名单取产品那一份（唯一真相源），这里不另抄——抄出来的副本不会跟着产品变。

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
#   kill_icon: KI-1 之前它"不安全"是因为整条播放链跑在一个 pygame 子进程里
#              （建播放器就 spawn 一个 python.exe + SDL 视频窗口）。KI-1 把渲染
#              搬到主进程的 Qt 叠加层之后，那个子进程不存在了，而叠加窗口只在
#              **真正播放的那一刻**才创建。审计里没人触发播放，再把总开关按成
#              False，构造这一页不会有任何前台副作用。
#              名单本身不动（预载跳过那边的口径是另一回事），这里只放行审计。
# RN-005：中和表全仓唯一一份（这段以前在 5 支脚本里各写一遍，内容 1~3 项不等，
# 后果是 flash / viewmodel / voice_output 三页被全部 5 支跳过 —— 零覆盖）。
from _audit_neutralize import (  # noqa: E402
    apply as neutralize_apply,
    describe as neutralize_describe,
    enable_audit_mode,
    unsafe_pages,
)

enable_audit_mode()   # 必须在 import 产品模块之前

# UP-100: 紧凑模式的窗口尺寸。与 `gui_widget.MainWindow.__init__`（最小尺寸）
# 和 `_setup_window_size` 的紧凑分支（固定几何 + 居中）是同一组数——改那边请一起改。
# 实测这一档的内容可视区只有 590px（640 - 50px 紧凑顶栏），比完整模式的 750px 少 160px。
COMPACT_SIZE = (860, 640)
FULL_SIZE = (1280, 800)

ALL_THEMES = ("dark", "light", "green", "purple", "ocean", "warm", "rose", "contrast")


def is_inside_any(widget, containers):
    """`widget` 是不是 `containers` 里某一个、或它的后代。

    单独拎出来是因为**判据也要用它** —— 判据自己再写一遍祖先遍历，
    就又多了一份会各自漂移的副本（RN-002 那一族的病）。
    """
    if not containers:
        return False
    node = widget
    while node is not None:
        if any(node is c for c in containers):
            return True
        node = node.parentWidget()
    return False


def scopes_with_skip(page, app):
    """把一个页面拆成若干「真正被布局过的测量范围」。

    返回 `[(范围名 or None, 控件, 要跳过的容器元组), ...]`；
    范围名为 `None` 的那一条是**页面余下部分**。

    ## R5 当年为什么只返回页签内容

    直接对整页 `findChildren(QScrollArea)` 会连**非当前页签**里的滚动区一起量。
    Qt 不给隐藏的页签做布局，那些控件保留着构造时的陈旧几何（实测
    special_sound 的隐藏页签视口只有 618~624px，而页签容器有 968px），
    于是稳定误报「溢出 58~140px」。逐个 `setCurrentIndex` 切出来再量之后，
    四个页签全部零溢出 —— **那条缺陷根本不存在**。这个理由到今天仍然成立。

    ## RN-030：可那条修法把「页签之外的一切」也一起排除了

    「只返回页签内容」是拿**替换**当**排除**用。躲开陈旧几何只需要排除
    **非当前页签的内容**，而实际排除掉的是页头、状态徽章条、顶层卡片、
    底部操作栏 —— 也就是这些页面上最显眼的那部分。实测（2026-08-22）：

        magnifier 125 · voice_output 76 · kill_sound/kill_voice/switch_weapon/
        reload_sound 各 38 · gun_sound 36 · flash 35 · utility 33 ·
        special_sound 31   ⇒ 10 页合计 ~490 个可见控件从未被任何判据看过

    ⇒ 现在**两条都要**：页面余下部分是一个范围（跳过页签内容），
    每个页签内容各自还是一个范围。

    ⚠ **跳过的是 `tw.widget(i)`（页签内容），不是整个 `QTabWidget`。**
    页签**条**（QTabBar）不属于任何一个页签内容，而它一直被正常布局、
    有文字、会被截断，是每页最显眼的控件之一。跳过整个 QTabWidget
    会让它掉进两不管地带 —— 判据 `test_the_tab_bar_itself_is_measured`
    专门钉这一条。

    ## ⚠⚠ 这是个**生成器**，而且「页面余下部分」必须第一个出来

    实测（2026-08-22，紧凑档）：**把页签切一遍，会把整页的布局最小高永久改大**，
    而且 `setCurrentIndex(original)` 复位之后也回不来：

        magnifier  596 → 612        flash  500 → 516
        kill_sound / switch_weapon / voice_output  不变

    成因是 Qt 的尺寸提示：页签内容**没被显示过之前**报的 hint 偏小，
    显示过一次之后才准，于是 `QTabWidget` 的最小高跟着长一截。

    ⇒ 先切页签、再量整页 = **量的是审计自己戳过之后的页面**。
    第一版就是这么写的（还振振有词地写了理由），复量时对不上才发现：
    magnifier 的纵向缺口新鲜时是 6px（在容差内），戳过之后是 22px。
    ⭐ **工装的观测动作本身会改变被观测对象** —— 这条在本仓是第一次踩到。

    写成生成器是为了让顺序**真的**生效：判据是在调用方拿到 scope 之后
    才去读几何的，光把整页排在列表第一位没有用（那时页签早切完了）。
    生成器 yield 到哪儿才做到哪儿，整页那一发出去时页签一根没动过。

    ⚠ 因此**不许只消费一半**：中途 break 会把某个 QTabWidget 停在
    非原始页签上。要一次性拿全的用 `list(...)` 或 `_scopes()`。
    """
    from PySide6.QtWidgets import QTabWidget

    tabs = [t for t in page.findChildren(QTabWidget) if t.count() > 0]
    if not tabs:
        yield (None, page, ())
        return

    tab_pages = tuple(
        w for tw in tabs for w in (tw.widget(i) for i in range(tw.count()))
        if w is not None
    )
    yield (None, page, tab_pages)          # 必须在任何 setCurrentIndex 之前

    for tw in tabs:
        original = tw.currentIndex()
        for i in range(tw.count()):
            tw.setCurrentIndex(i)
            # 两拍:第一拍触发布局请求,第二拍让布局真正落地
            app.processEvents()
            app.processEvents()
            widget = tw.currentWidget()
            if widget is not None:
                yield (tw.tabText(i), widget, ())
        tw.setCurrentIndex(original)
        app.processEvents()


def _scopes(page, app):
    """`scopes_with_skip()` 的二元组形态，留给只关心「量哪些控件」的调用方。

    ⚠ 不许在这里另写一份拆分逻辑 —— 副本不会跟着彼此变，而且漂了不报错
    （RN-002 那一族）。
    """
    return [(name, scope) for name, scope, _skip in scopes_with_skip(page, app)]


def _uneven_status_chips(scope):
    """返回同一排状态徽章里**高度不一致**的芯片组 [(芯片文案, 高, 该排众数高), ...]。

    RN-026 引出的第 4 条判据。一排徽章本来齐平，某颗文案太长就会换行、比别的高一截，
    肉眼一看就歪 —— 而**前三条判据一条都看不见它**：换行既不产生横向滚动
    （放得下），也不截断文字（画得全），更谈不上纵向裁切（滚得动）。
    实测：把「已配置 · 0」改成「已配置 · 0（37 项风格已失效）」之后整排错位，
    三条判据全绿，是重看渲染图 + 外审复跑发现的。

    只看 `AudioStatusBadgeBar` 这一种容器：它的芯片是**同一排、同一角色**的，
    高度不齐就是缺陷；别处的控件高度不同往往是有意的，不能一概而论。
    """
    from PySide6.QtWidgets import QLabel, QWidget

    out = []
    for bar in scope.findChildren(QWidget):
        if bar.__class__.__name__ != "AudioStatusBadgeBar":
            continue
        chips = [c for c in bar.findChildren(QLabel)
                 if c.isVisible() and c.text().strip()]
        if len(chips) < 2:
            continue
        # ⭐⭐ RN-185：**先问"这一条装不装得下"，再问"齐不齐"。**
        # 原来只有下面那半条（齐不齐），而实测踩到的是：紧凑档竖向不够时布局
        # 挑了这条没有下限的徽章条来压，条高 13px、芯片要 40px ——
        # 四颗芯片只剩顶上一道圆弧、文字整个没了，而它们**被压得一样扁**，
        # 于是"齐平"判据一路绿灯。
        # ⇒ **一条只看"齐不齐"的判据，看不见"全都不对"。**
        bar_h = bar.height()
        for chip in chips:
            need = chip.sizeHint().height()
            if bar_h > 0 and need > bar_h + 2:
                out.append((f"[被压扁] {chip.text().strip()}", bar_h, need))

        heights = [c.height() for c in chips]
        common = max(set(heights), key=heights.count)
        for chip, h in zip(chips, heights):
            if h != common:
                out.append((chip.text().strip(), h, common))
    return out


def _elided_buttons(scope, skip=()):
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
        if is_inside_any(btn, skip):
            continue
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


#: RN-177 第 5 条判据的**声明式例外**。键 = (页面, 滚动区里第一个孩子的类名或 objectName)，
#: 值 = 为什么这一处的内层滚动是对的。**每一条都要写理由**，理由不成立就该修页面。
#:
#: ⭐ 例外表存在的原因是一条实测出来的区别：`viewmodel` 的预设卡数量是**固定的 5**、
#:    而且页面文案明写「5 组」，藏起来就是文案骗人；`voice_output` 的槽位列表长度
#:    **由用户决定**，那是一份列表控件，内层滚动是它的正常形态。
#:    一条分不清这两者的判据，会逼我把一个正常的列表拆掉 —— 那正是
#:    「分母不对的判据不只是漏，它还会诬告对的代码」（RN-167）。
NESTED_SCROLL_ALLOWED: dict[tuple[str, str], str] = {
    ("voice_output", "voiceSlotList"):
        "语音槽位是一份长度由用户决定的列表（初始 5、上限 50），内层滚动是列表控件的"
        "正常形态；它藏住的量随槽位数变化，不是固定内容被钉死的高度上限。"
        "⚠ 例外只免掉「不许藏内容」这一条，不代表这一处没账 —— "
        "「默认 5 个槽位露不全最后一个」记在 RN-184，等 P3 翻到这一页时一起判。",
}


def _nested_scroll_hidden(scope, page, page_id, skip=()):
    """返回「内层滚动区藏住内容」的清单：[(名字, 视口高, 藏住的像素)]。

    RN-177（第 5 条判据）。⭐ 这条判据补的不是一个 bug，是**一整类的分母**：

    `_overflow_of` 里明写着「只看最外层滚动区:内层(地图预览/画廊)的横向滚动是有意设计」，
    于是**内层滚动区藏纵向内容这一类从来没有任何判据在看**。实测代价：
    `viewmodel` 的「视角预设」卡外面套着 `setMaximumHeight(320)` 的滚动区，
    视口 320px 装 872px —— 5 组预设只有 1 组完整可见，而卡副标题写着「5 组」。
    这一页 2026-08-18 就已关档，排版审计一路绿灯，**24 轮外审也没看见**
    （看图脚本渲染的是窗口，折叠线以下从来没进过画面，见 RN-170）。

    规则：**页面级滚动区里面的内层滚动区，不许藏内容**——页面本身已经会滚了，
    再套一层只会把内容藏进一个用户不知道要滚的小窗口。容差 24px（滚动条钢化/取整）。
    真正需要内层滚动的（长度由用户决定的列表）走 `NESTED_SCROLL_ALLOWED` 声明。

    ⚠ **「嵌套」要相对 `page` 判，不能相对 `scope` 判** —— 这条判据的第一版就
    栽在这里，而且**第一次跑就是绿的**：`_scopes()` 对带页签的页面返回的是
    **页签内容**，于是页面级滚动区成了 `scope` 的**祖先**而不是后代，
    页签里的滚动区一个都算不成"嵌套"。`voice_output` 的槽位列表（探针实测
    藏 114px）因此完全逃过检测 —— 把它从例外表里拿掉做破坏测试，判据**照样绿**。
    ⇒ 又一次印证：**判据第一次跑就绿，先怀疑它没在看，别当成通过**。
    """
    from PySide6.QtWidgets import QScrollArea

    hits = []
    for sa in scope.findChildren(QScrollArea):
        if sa.isHidden() or is_inside_any(sa, skip):
            continue
        anc, nested = sa.parentWidget(), False
        while anc is not None:
            if isinstance(anc, QScrollArea):
                nested = True
                break
            if anc is page:      # 边界取页面：再往上是主窗口，跟这一页无关
                break
            anc = anc.parentWidget()
        if not nested:
            continue
        inner = sa.widget()
        name = (sa.objectName() or (inner.objectName() if inner is not None else "")
                or type(sa).__name__)
        if (page_id, name) in NESTED_SCROLL_ALLOWED:
            continue
        vbar = sa.verticalScrollBar()
        hidden = vbar.maximum() if vbar is not None else 0
        if hidden > 24:
            hits.append((name, sa.viewport().height(), hidden))
    return hits


#: RN-196：RN-030 把分母补齐之后，**紧凑档**当场浮出来的存量债。
#:
#: 这些不是这一批改坏的，是**一直存在、一直没有判据看得见**的：以前有页签的
#: 页面根本没有「整页」这个测量范围（RN-030），所以整页装不下这件事无人可报。
#:
#: 键 = (页面, 类别)，值 = (实测最坏像素, 理由)。**数必须等于实测值**——
#: 留富余的棘轮不是棘轮。比记录更坏 ⇒ 当场红；不再命中 ⇒ 也当场红（提醒收紧）。
#:
#: ⚠ 它们要改的是产品版面（用户可感知），属 B 堆，得走裁定 + 外审，
#: 不在「把审计修准」这一批的范围内。
KNOWN_COMPACT_DEBT: dict[tuple[str, str], tuple[int, str]] = {
    ("kill_sound", "clip"): (64, "紧凑档整页布局最小高超出可视区"),
    ("kill_voice", "clip"): (64, "同上（同族同基类）"),
    ("reload_sound", "clip"): (64, "同上（同族同基类）"),
    ("switch_weapon", "clip"): (64, "同上（同族同基类）"),
    ("magnifier", "clip"): (82, "全站最大页，紧凑档最缺高的一页"),
    ("magnifier", "overflow"): (29, "紧凑档整页横向溢出 11~29px（随字号递增）"),
}


def _split_known(hits, kind, known=None):
    """把命中拆成「在册的存量债」和「新的」，并挑出可以收紧的。

    返回 (新命中, 变坏的, 可收紧的)。三样都打印，**但只有前两样让门变红**。

    ## ⚠ 为什么第三样（可收紧的）不红 —— 这是 CI 逮出来的

    第一版让三样都红，理由写得也对：只判「变没变坏」的棘轮，在缺陷被修好之后
    会永远停在旧数上，从「守着一条线」退化成「记着一个古董」。

    **可它在 CI 上当场把整道门判红了**（2026-08-22 公开仓 `e265ab1`）：
    `kill_sound` / `kill_voice` / `reload_sound` / `switch_weapon` 四条纵向债
    **在 CI 那台机器上根本不复现** —— 字体度量不同，同一份代码量出来的像素就不同。

    ⭐⭐ **一个按像素写死的棘轮，是一台机器的事实。** 「不再命中」既可能是
    「缺陷修好了」，也可能只是「这台机器渲染得不一样」，而判据分不出这两者 ——
    分不出就不该拿它去红。

    ⇒ 现在它是**上限**语义：超过在册数、或冒出新的一页 ⇒ 红；不命中 ⇒ 打印提醒。
    「别让它变成古董」这件事改由收工清单里的人工复核管（每次报告都会把在册清单
    整个打出来，不会静默）。

    ⚠ `known` 要由调用方给：这张表记的是**紧凑档**的事实，完整档拿它对账
    会得到「六条全都不再命中、请收紧」的假红 —— 第一版就是这么翻车的。
    完整档传 `{}`，于是任何命中都算新增（这正是想要的）。
    """
    table = KNOWN_COMPACT_DEBT if known is None else known
    worst: dict[str, int] = {}
    for pid, px in hits:
        worst[pid] = max(worst.get(pid, 0), px)

    fresh, worse = [], []
    for pid, px in sorted(worst.items()):
        entry = table.get((pid, kind))
        if entry is None:
            fresh.append((pid, px))
        elif px > entry[0] + 2:          # 2px 容差：取整/滚动条钢化
            worse.append((pid, px, entry[0]))
    loosened = [
        (pid, px) for (pid, k), (px, _why) in table.items()
        if k == kind and pid not in worst
    ]
    return fresh, worse, loosened


def _overflow_of(scope, skip=()):
    """返回该范围内最外层滚动区的横向溢出像素；无溢出返回 None。

    ⚠ 「内层的滚动是有意设计」这句只对**横向**成立。纵向的那一半交给
    `_nested_scroll_hidden`（RN-177）—— 这里放过去的东西那边会接住。
    """
    from PySide6.QtWidgets import QScrollArea

    for sa in scope.findChildren(QScrollArea):
        if is_inside_any(sa, skip):
            continue
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
    _um.add_expert_argument(ap)
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

    # RN-134：默认按**产品默认的普通模式**审 —— 这里原来写死 `= True`，
    # 理由写的是"专家页一并检测"，可那件事现在由 `_ui_mode.goto()` 的 force 兜着，
    # 不必再把每一页都换成专家视图。审专家视图请显式 `--expert`。
    _um.apply(config, args.expert)

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

    # ⭐⭐ RN-195：音乐控制条必须**在开量之前**就位，否则这道门依赖挂钟。
    # 档位的选择理由、以及两类工装为什么口径不同，全在 `_audit_music_bar` 里。
    #
    # 这道门要的是**最坏那一档**：控制条**在**。RN-195 之后它不再无条件出现，
    # 但只做「不建」不做「撤走」—— 放过一次音乐的用户就永远停在这一档，
    # 所以按"没有控制条"来验收等于把大半用户的世界排除在门外。
    import _audit_music_bar as _mbar

    print("   " + _mbar.pin(win, app, _mbar.MODE_WORST_CASE))

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
        for pid in neutralize_apply(config, page_ids):
            neutralized.append(neutralize_describe([pid]))
        skipped = sorted(p for p in page_ids if p in unsafe_pages())
        page_ids = [p for p in page_ids if p not in skipped]

    themes = ALL_THEMES if args.themes.strip() == "all" else tuple(
        t.strip() for t in args.themes.split(",") if t.strip())
    scales = tuple(float(s) for s in args.scales.split(",") if s.strip())

    problems = []
    elided = []
    clipped = []
    uneven = []
    nested_hidden = []          # RN-177：内层滚动区藏住内容
    checked = 0

    for theme in themes:
        for scale in scales:
            apply_font_scale(scale)
            tm.set_theme(theme)
            app.processEvents()
            for pid in page_ids:
                try:
                    _um.goto(win, pid)
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

                    for scope_name, scope, skip in scopes_with_skip(page, app):
                        checked += 1
                        label = pid if scope_name is None else f"{pid}/{scope_name}"
                        over = _overflow_of(scope, skip)
                        if over is not None:
                            problems.append((theme, scale, label, over))
                        short = _vertical_clip_of(scope, avail_h)
                        if short is not None:
                            clipped.append((theme, scale, label, short, avail_h))
                        for text, have, need in _elided_buttons(scope, skip):
                            elided.append((theme, scale, label, text, have, need))
                        for name, vp_h, hidden in _nested_scroll_hidden(
                                scope, page, pid, skip):
                            nested_hidden.append((theme, scale, label, name, vp_h, hidden))
                    # 徽章判据对整页量。RN-030 之前这是**唯一**一条看得见页头/状态卡/
                    # 底栏的判据（那时 `_scopes()` 对有页签的页面只返回页签内容）；
                    # 现在页面余下部分本身就是一个范围，这里保持整页量是因为
                    # 一排徽章本来就该整排一起看，拆进范围里反而会把一排劈开。
                    for text, h, common in _uneven_status_chips(page):
                        uneven.append((theme, scale, pid, text, h, common))
                except Exception as exc:
                    problems.append((theme, scale, pid, f"异常:{exc}"))

    apply_font_scale(1.0)
    tm.set_theme(getattr(config, "ui_theme", "dark") or "dark")

    # RN-195：回验 —— 上面那一整轮真的全程都在钉住的那一档里。
    # 钉住只是"我打算量哪一档"；不回验的话，一条在途中冒出来的控制条照样能
    # 混过去，而产物读起来毫无异样（页与页之间差的那 42px 会被当成页面差异）。
    _mbar.assert_stable(win)

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
    # RN-196：整页范围的存量债走声明式棘轮；页签范围与异常一律照常报。
    blocking_overflow = []
    page_overflow = []
    for theme, scale, label, detail in problems:
        if "/" not in label and isinstance(detail, int):
            page_overflow.append((label, detail))
        else:
            blocking_overflow.append((theme, scale, label, detail))
    # RN-196：存量债只在紧凑档对账（那是它被量出来的那一档）。
    debt = KNOWN_COMPACT_DEBT if args.compact else {}
    of_fresh, of_worse, of_loose = _split_known(page_overflow, "overflow", debt)

    if blocking_overflow or of_fresh or of_worse:
        for theme, scale, label, detail in blocking_overflow:
            print(f"  溢出: [{theme} x{scale}] {label} -> {detail}")
        for pid, px in of_fresh:
            print(f"  ✗ 溢出(新): [{pid}] 整页横向溢出 {px}px")
        for pid, px, was in of_worse:
            print(f"  ✗ 溢出(变坏): [{pid}] {was}px → {px}px")
    else:
        print("  ✓ 无水平溢出（在册存量债除外，见下）")
    if of_loose:
        # ⚠ 提醒，**不判红** —— 见 `_split_known` 的说明：不命中既可能是修好了，
        # 也可能只是这台机器渲染得不一样，判据分不出这两者。
        print("  ! 这些在册的横向存量债在**这台机器上**不再命中，请人工确认是"
              "「修好了」还是「环境不同」，前者请从 KNOWN_COMPACT_DEBT 删掉: "
              + ", ".join(pid for pid, _ in of_loose))

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
    # RN-196: 同上，整页范围的存量债走棘轮，页签范围照常报。
    blocking_clip = []
    page_clip = []
    clip_avail = {}
    for theme, scale, label, short, avail in clipped:
        if "/" not in label:
            page_clip.append((label, short))
            clip_avail[label] = avail
        else:
            blocking_clip.append((label, short, avail))
    cl_fresh, cl_worse, cl_loose = _split_known(page_clip, "clip", debt)

    if blocking_clip or cl_fresh or cl_worse:
        seen = {}
        for label, short, avail in blocking_clip:
            seen.setdefault(label, []).append((short, avail))
        print(f"  ✗ {len(seen) + len(cl_fresh) + len(cl_worse)} 处内容纵向装不下且无法滚动:")
        for label, hits in sorted(seen.items()):
            print(f"     [{label}] 最小高超出可视区 {max(s for s, _a in hits)}px"
                  f"(可视 {hits[0][1]}px)，命中 {len(hits)} 个主题×字号")
        for pid, px in cl_fresh:
            print(f"     [{pid}] (新) 整页最小高超出可视区 {px}px"
                  f"(可视 {clip_avail.get(pid, '?')}px)")
        for pid, px, was in cl_worse:
            print(f"     [{pid}] (变坏) {was}px → {px}px")
    else:
        print("  ✓ 无纵向裁切（在册存量债除外，见下）")
    if cl_loose:
        # ⚠ 同上：提醒，不判红。CI 上这四页就是不复现的（字体度量不同）。
        print("  ! 这些在册的纵向存量债在**这台机器上**不再命中，请人工确认是"
              "「修好了」还是「环境不同」，前者请从 KNOWN_COMPACT_DEBT 删掉: "
              + ", ".join(pid for pid, _ in cl_loose))

    if debt and (page_overflow or page_clip):
        print(f"  ℹ 在册存量债 {len(debt)} 条（RN-196，紧凑档，"
              f"待裁定后随各页动刀）: "
              + "、".join(f"{pid}·{kind}{px}px"
                          for (pid, kind), (px, _w) in sorted(debt.items())))

    # RN-026 引出的第 4 条：同一排状态徽章里有芯片因文案换行而比别人高
    if uneven:
        seen = {}
        for theme, scale, pid, text, h, common in uneven:
            seen.setdefault((pid, text), (h, common))
        print(f"  ✗ {len(seen)} 处状态徽章不对劲"
              "（[被压扁]=整条高度小于芯片所需，文字画不出来；"
              "其余=文案太长换了行、比同排高一截）:")
        for (pid, text), (h, common) in sorted(seen.items()):
            if text.startswith("[被压扁]"):
                print(f"     [{pid}] {text} 整条只有 {h}px，芯片要 {common}px")
            else:
                print(f"     [{pid}] 「{text}」 高 {h}px，同排其余 {common}px")
    else:
        print("  ✓ 状态徽章高度齐平")

    # RN-177 第 5 条：内层滚动区藏住内容——前四条一条都看不见这一类
    if nested_hidden:
        seen = {}
        for theme, scale, pid, name, vp_h, hidden in nested_hidden:
            cur = seen.get((pid, name))
            if cur is None or hidden > cur[1]:
                seen[(pid, name)] = (vp_h, hidden)
        print(f"  ✗ {len(seen)} 处内层滚动区藏住内容(页面本身已经会滚，不该再套一层):")
        for (pid, name), (vp_h, hidden) in sorted(seen.items()):
            total = vp_h + hidden
            print(f"     [{pid}] {name} 视口 {vp_h}px / 内容 {total}px，"
                  f"藏住 {hidden}px（只露出 {vp_h * 100 // max(1, total)}%）")
        print("     确属「长度由用户决定的列表」请在 NESTED_SCROLL_ALLOWED 里"
              "写明理由，别直接调阈值。")
    else:
        print("  ✓ 无内层滚动区藏内容")

    win.close()
    win.deleteLater()
    app.processEvents()
    # RN-196：在册的整页存量债不让门变红（它们要改产品版面，得走裁定 + 外审），
    # 但**变坏和新增**照样红。
    # ⚠ "已经不该在册"那一样**不红** —— 第一版让它红，CI 当场把整道门判红：
    # 那四条纵向债在 CI 的字体度量下根本不复现。像素级棘轮是一台机器的事实。
    return 1 if (blocking_overflow or of_fresh or of_worse
                 or blocking_clip or cl_fresh or cl_worse
                 or elided or uneven or nested_hidden) else 0


if __name__ == "__main__":
    # ⚠ RN-092：裁定走 `_audit_verdict`，不走退出码 —— 见那个文件的说明。
    # ⭐ RN-194 更新：那句「还没在 CI 上现过形」已经作废 —— 2026-08-22 在**本机**
    # 现形了，同一棵树跑 9 次里 3 次退出码 127 而裁定行是 rc=0。本机请走
    # `python scripts/gate.py layout`（它读裁定行，退出码干净）。
    from _audit_verdict import deliver, make_teardown_noise_visible

    make_teardown_noise_visible()
    deliver("layout", main())
