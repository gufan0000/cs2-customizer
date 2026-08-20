# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""键盘焦点巡检（R1-4 建立 2026-06-12，R8d/UP-077 重写判据）。

对指定页面离屏实例化，沿 `nextInFocusChain` 走焦点链，与**阅读序**对比。

用法:
    python scripts/tab_order_audit.py                 # 默认高频页
    python scripts/tab_order_audit.py crosshair music # 指定页
    python scripts/tab_order_audit.py --verbose       # 打印每一处错位的身份
退出码:0=焦点链与阅读序一致，1=存在错位。

────────────────────────────────────────────────────────────────────
R8d 为什么把判据整个换掉（原判据报 52 处，实际只有 2 处真缺陷）
────────────────────────────────────────────────────────────────────

原判据把页面当**一张平铺的纸**，按 `(y // 24, x)` 排序，再逐位比对。
三个毛病叠在一起，把 4 个页面判成"焦点顺序错位"，而其中 3 个页面是对的：

1. **并排卡片被拆开**。准心页「准心样式」「准心颜色」两张卡左右并排，
   右卡的单选比左卡高 25px，平铺排序就把**整张右卡排到左卡前面**。
   而 Tab 链走的是「读完左卡再读右卡」——那才是人读界面的方式。
   7 处错位，**7 处都是假的**。

2. **滚动区内外的坐标被硬比**。gun_sound 的动作条在滚动区**外**（y=838），
   滚动区**内**的内容绝对坐标能到 y=1045（早滚出视口了）。
   拿这两个 y 比大小没有意义。12 处错位，**12 处都是假的**。

3. **一个错位滚成一片**。逐位比对下，一个控件插错位置会让它**之后的全部**
   计为错位。music 页 28 个控件报 16 处，真实只有 2 个控件位置不对。

现在的判据：
  · 阅读序**递归**——块（卡片/动作条/滚动区/页签）之间按行排，块内部再递归；
  · 「同行」按**矩形垂直重叠**判，不用固定像素容差
    （固定容差在 voice_output 上正好卡在边界把对的判成错的，而且不随字号缩放）；
  · 错位数报**最少要挪动几个控件**（n − 最长上升子序列），不报逐位差异。

**验过它还抓得到真缺陷**：把 music 那处修复回退，本判据立刻报 2。
"""
from __future__ import annotations

import bisect
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# UP-083: 本脚本会真实实例化页面,而页面构造会触发 config 写盘 ——
# 实测跑一次就把 config.json 整个重新序列化了一遍。原先它**一行隔离都没有**,
# 于是每跑一次审计都在动用户真实的 %LOCALAPPDATA%\CS2Customizer\config.json。
# 这次没造成值变化(重写保留了原值),但那是运气:同目录下的
# layout_overflow_audit 会设 config.ui_expert_mode=True,
# 换个脚本、换个属性就是真真切切改用户设置了。
# 与 UP-065 同类:诊断/审计工具写错地方,污染的是用户的真实数据。
# RN-032：配置目录一律走共享工装 —— 自己 mkdir + setdefault 挡不住
# migrate_old_config() 把仓库根那份未跟踪的个人 config.json 复制进来。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_tab_audit")
# 页面里若有准心/音频的自动启动分支,别让审计把它拉起来
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLayout, QWidget  # noqa: E402

# 应用一共有多少个页面。这是**覆盖面的分母**，必须和 `gui_widget._page_names`
# 对得上——`tests/test_audit_coverage_r11.py` 会盯着它，对不上就红。
TOTAL_PAGES = 27

# 全部有独立模块、能单独构造的页面（`basic` 是在 `gui_widget` 里内联建的，没有独立类，
# 所以分母 27 里它永远进不来——这一条要写出来，否则 26/27 会被当成 bug 反复查）。
PAGE_FACTORY = {
    "kill_sound": ("pages.kill_sound_page", "KillSoundPage"),
    "kill_voice": ("pages.kill_voice_page", "KillVoicePage"),
    "kill_icon": ("pages.kill_icon_page", "KillIconPage"),
    "crosshair": ("pages.crosshair_page", "CrosshairPage"),
    "death_sound": ("pages.death_sound_page", "DeathSoundPage"),
    "gun_sound": ("pages.gun_sound_page", "GunSoundPage"),
    "switch_weapon": ("pages.switch_weapon_page", "SwitchWeaponPage"),
    "reload_sound": ("pages.reload_sound_page", "ReloadSoundPage"),
    "special_sound": ("pages.special_sound_page", "SpecialSoundPage"),
    "viewmodel": ("pages.viewmodel_page", "ViewmodelPage"),
    "music": ("pages.music_page", "MusicPage"),
    "voice_output": ("pages.voice_output_page", "VoiceOutputPage"),
    "fun_afterlife": ("pages.fun_page", "FunPage"),
    "utility": ("pages.utility_page", "UtilityPage"),
    "magnifier": ("pages.magnifier_page", "MagnifierPage"),
    "flash": ("pages.flash_page", "FlashPage"),
    "hud_color": ("pages.hud_color_page", "HudColorPage"),
    "screen_effects": ("pages.screen_effects_page", "ScreenEffectsPage"),
    "advanced": ("pages.advanced_page", "AdvancedPage"),
    "audio_health": ("pages.audio_health_page", "AudioHealthPage"),
    "audio_import_wizard": ("pages.audio_import_wizard_page", "AudioImportWizardPage"),
    "audio_task_panel": ("pages.audio_task_panel_page", "AudioTaskPanelPage"),
    "audio_replay": ("pages.audio_replay_page", "AudioReplayPage"),
    "config_snapshot": ("pages.config_snapshot_page", "ConfigSnapshotPage"),
    "preset_center": ("pages.preset_center_page", "PresetCenterPage"),
    "about": ("pages.about_page", "AboutPage"),
}

# 构造即占外部资源的页面（口径同 `core.page_traits`）。
# RN-005/RN-059 之后中和表只有 `scripts/_audit_neutralize.py` 一份，
# 六页全部可纳入 —— 这里不再自己列名单。历史注释保留在下面，
# 两个都已经纳入默认档）。要跑它们加 `--include-unsafe`。
# ⚠ 2026-08-16：`kill_icon` 从这份名单里移走了。它当年"不安全"是因为整条播放链
#    跑在一个 pygame 子进程里（建播放器就 spawn 一个 python.exe + SDL 视频窗口），
#    KI-1 把渲染搬到主进程的 Qt 叠加层之后那个子进程就不存在了，叠加窗口也只在
#    **真正播放的那一刻**才创建。排版审计早在 KI-1 时就跟着改了，这边一直没改——
#    于是这一页在焦点巡检里**白白少测了一整轮重构**（KI-6 把它重写成了清单板）。
#    「不安全名单」和「已经不安全了吗」是两件事，改完渲染架构要顺手复核这类名单。
# RN-059：这里原来是 `{"flash", "viewmodel"}` —— 第 8 处私有跳过名单。
# 探针在 `subprocess.Popen` 边界上实测：两页构造时子进程调用 **0 次**
# （flash 只在 `flash_enabled` 为真时才起进程，而中和表已把它按成 False；
#  viewmodel 同理）。⇒ 两页纳入，覆盖面 25/28 → 27/28（只剩内联的 basic）。
# 留这个空集合是因为报告逻辑要一个统一出口；要往回加，先在
# `scripts/_audit_neutralize.py` 里写清"它挡住了什么"。
SPAWNS_SUBPROCESS: set[str] = set()

# ⚠ UP-101: 这份名单原先只有 **11** 个页面，而报告只打印"11 个页面全部为 0"，
# 读起来像全覆盖 —— 和 UP-096 是同一种病（"全绿要先问分母"），只是换了个审计。
# 没被覆盖的 16 个页面里，`preset_center` / `audio_import_wizard` 恰恰就是
# R11 在紧凑模式下查出真排版缺陷的那两页。现在默认覆盖 23/27，并且**每次都打印分母**。
DEFAULT_PAGES = [pid for pid in PAGE_FACTORY if pid not in SPAWNS_SUBPROCESS]

#: 构造前要按页中和掉的配置项（手法同 UP-084 的 `NEUTRALIZABLE`）。
#:
#: UP-087: `music` 页在**隔离配置**下会当场发一次网络下载——隔离目录是新的，
#: `music_default_song_added` 为假，`MusicPlayer.__init__` 就去下载默认曲目
#: 「CS的LEMON」。审计每跑一次下一次，CI 里也一样。
#: **审计工具不该有网络副作用**：它让结果依赖外网可达性，也把构造耗时
#: 绑在一次 HTTP 上。把开关置真即可，UI 照常完整构建。
# RN-005：中和表全仓唯一一份（这段以前在 5 支脚本里各写一遍，内容 1~3 项不等，
# 后果是 flash / viewmodel / voice_output 三页被全部 5 支跳过 —— 零覆盖）。
from _audit_neutralize import (  # noqa: E402
    enable_audit_mode,
)

enable_audit_mode()   # 必须在 import 产品模块之前



#: 少数页面的构造函数要参数（口径以 `gui_widget` 里真正的构造点为准，
#: 别照类签名猜——`MagnifierPage(self.config)` 传的是 config 单例本身）。
def _ctor_args(page_id):
    if page_id == "magnifier":
        from config import config as cfg

        return (cfg,)
    return ()


def _neutralize(page_id):
    """返回 (已改的键值对) 供事后还原；隔离配置里改，不碰用户真实文件。"""
    from config import config as cfg

    previous = {}
    from _audit_neutralize import NEUTRALIZE
    for key, value in NEUTRALIZE.get(page_id, {}).items():
        previous[key] = getattr(cfg, key, None)
        setattr(cfg, key, value)
    return previous


def _restore(previous):
    from config import config as cfg

    for key, value in previous.items():
        setattr(cfg, key, value)


#: 「块」= 读的时候会被当成一个整体、读完再读下一个的东西。
#: ⚠ `layoutColumn` 不是一种卡片，是**并排的列容器**（RN-122，2026-08-19）。
#: 本模块的定论一直是「读完左列再读中列再读右列」，UP-101 也已经为**裸布局**做的列
#: 加过这条分组。但列如果是一个**控件**（`QWidget` + `QVBoxLayout`），
#: `_outermost_block_under` 只会认到里面那张卡，两列的卡片于是被按 y 交错成"阅读序"，
#: 而键盘实际是一列走到底 —— 判出来的"错位"是假的。
#: ⇒ 列容器自己也要算一个块。产品侧给这种容器起这个 objectName（无样式含义）。
BLOCK_NAMES = {"card", "settingsCard", "pageActionBar", "layoutColumn"}
BLOCK_TYPES = {"SettingsCard", "PageActionBar", "QScrollArea", "QTabWidget"}


def is_block(w) -> bool:
    return w.objectName() in BLOCK_NAMES or type(w).__name__ in BLOCK_TYPES


def focusable_chain(root: QWidget):
    """沿焦点链收集属于 root、接受 Tab 聚焦、可见的控件。"""
    seen = []
    w = root.nextInFocusChain()
    guard = 0
    while w is not None and w is not root and guard < 4000:
        guard += 1
        if w.isVisibleTo(root) and w.focusPolicy() & Qt.TabFocus and root.isAncestorOf(w):
            seen.append(w)
        w = w.nextInFocusChain()
    return seen


def _pos_in(w, container):
    p = w.mapTo(container, w.rect().topLeft())
    return p.x(), p.y()


def _order_rows(items, container, rects=None):
    """按「同行 + 从左到右」排。「同行」= 矩形**垂直重叠**。

    不用固定像素容差：① 边界脆——voice_output 的主音量行与模式行正好差 24px
    （= 原容差），被并成一行再按 x 排就把顺序排反了，而页面是对的；
    ② 不随字号缩放——1.25 档下行距变大，同一个 24px 会从"同行"变"跨行"。
    重叠判据自带缩放不变性：控件长高了，行距也长高了。

    `rects` 允许调用方直接给出每个 key 的 (x, top, bottom)——布局分组没有对应的
    控件可以 `mapTo`，只能由成员矩形并集算出来。
    """
    def band(w):
        if rects is not None and w in rects:
            return rects[w]
        x, y = _pos_in(w, container)
        return x, y, y + max(1, w.height())

    rows, cur, cur_bottom = [], [], None
    for w in sorted(items, key=lambda w: (band(w)[1], band(w)[0])):
        _x, top, bottom = band(w)
        if cur and top >= cur_bottom:
            rows.append(cur)
            cur, cur_bottom = [w], bottom
        else:
            cur.append(w)
            cur_bottom = bottom if cur_bottom is None else max(cur_bottom, bottom)
    if cur:
        rows.append(cur)

    out = []
    for row in rows:
        out.extend(sorted(row, key=lambda w: band(w)[0]))
    return out


def _layout_path(layout, w, depth=0):
    """从 `layout` 走到直接摆放 `w` 的那条**子布局链**；`w` 不在其中返回 None。

    只往 `item.layout()` 下钻，**不跨控件边界**——控件里面的布局属于它自己那一层，
    由 `reading_order` 的递归去处理。
    """
    if layout is None or depth > 12:
        return None
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is w:
            return []
        sub = item.layout()
        if sub is not None:
            found = _layout_path(sub, w, depth + 1)
            if found is not None:
                return [sub] + found
    return None


def _layout_path_of(layout, w, container):
    """`_layout_path` 的外层：控件本身不在布局里时，上溯到**真正被摆放的祖先**。

    ⚠ UP-101：可编辑的 `QComboBox` 会把 Tab 焦点交给它内部的 `QLineEdit`，
    于是焦点链里出现的是那个 `QLineEdit`，而布局里摆的是 `QComboBox`。
    只查控件自己会找不到，那个 QLineEdit 就自成一组、按它自己的坐标去跟
    同一行的按钮比 x —— `preset_center` 的「按地图预设」那行就是这么被判错位的。
    内部零件不是独立控件，排序时它**就是**它所属的那个复合控件。
    """
    node = w
    hops = 0
    while node is not None and node is not container and hops < 8:
        path = _layout_path(layout, node)
        if path is not None:
            return path
        node = node.parentWidget()
        hops += 1
    return None


def _outermost_block_under(w, container):
    found = None
    p = w.parentWidget()
    while p is not None and p is not container:
        if is_block(p):
            found = p
        p = p.parentWidget()
    return found


def reading_order(widgets, container, layout=None):
    """**递归**的阅读序：块之间按行排，块内部再递归同样的规则。

    ⚠ UP-101：块只认**控件**边界是不够的。`preset_center` 的工作台卡里是三列
    并排，而那三列是**裸的 QVBoxLayout**（没有承载它们的控件），判据于是看不见
    列的存在，只能把卡里所有控件摊平按行排。后果：中间那列一个 34px 高的下拉框
    纵向跨过了左列的两行复选框，"矩形重叠"把本来分明的两行**桥接**成了一行，
    再按 x 排就得出「准心、自定闪光、屏幕特效、局内视角、特殊音效」这种
    左右横跳的"阅读序"，判 preset_center 错位 2 处 —— **是假阳性**。
    实测两行 y 区间 [273,290) 与 [298,315)，间隙 +8px，根本不重叠。

    真实的 Tab 行为是「读完左列再读中列再读右列」，和 R8d 对**并排卡片**的定论
    完全一样，只是这次并排的是裸布局。所以这一层也要按子布局分组。
    """
    if layout is None:
        layout = container.layout()

    groups, keys = {}, {}
    for w in widgets:
        block = _outermost_block_under(w, container)
        if block is not None:
            key = block
        else:
            # 同一条子布局链下的控件归一组；`path[0]` 是本层的最外层子布局。
            path = _layout_path_of(layout, w, container)
            key = path[0] if path else w
        keys[w] = key
        groups.setdefault(key, []).append(w)

    # 布局分组没有控件可以 mapTo，矩形取成员并集。
    rects = {}
    for key, members in groups.items():
        if isinstance(key, QLayout):
            spans = [(_pos_in(m, container)[0], _pos_in(m, container)[1],
                      _pos_in(m, container)[1] + max(1, m.height())) for m in members]
            rects[key] = (min(s[0] for s in spans),
                          min(s[1] for s in spans),
                          max(s[2] for s in spans))

    out = []
    for key in _order_rows(list(groups), container, rects):
        members = groups[key]
        inner = [m for m in members if m is not key]
        if key in members:
            out.append(key)      # 块自身也能聚焦（QScrollArea 就是）→ 先落在块上
        if not inner:
            continue
        if isinstance(key, QLayout):
            # 布局分组：容器不变（坐标系不变），但根布局下降一层，保证收敛
            out.extend(reading_order(inner, container, key))
        else:
            out.extend(reading_order(inner, key))
    return out


def min_moves(chain, ideal) -> int:
    """最少要挪动几个控件才能把焦点链排成阅读序 = n − 最长上升子序列长度。

    不用逐位比对：那个指标里**一个控件插错位置会让它之后的全部计为错位**，
    music 页真实 2 个控件不对，逐位比对报 16 处——照着 16 去找会找不到 16 个东西。
    """
    rank = {w: i for i, w in enumerate(ideal)}
    seq = [rank[w] for w in chain if w in rank]
    tails = []
    for v in seq:
        i = bisect.bisect_left(tails, v)
        if i == len(tails):
            tails.append(v)
        else:
            tails[i] = v
    return len(seq) - len(tails)


def describe(w, root):
    text = ""
    for attr in ("text", "currentText", "title"):
        if hasattr(w, attr):
            try:
                text = str(getattr(w, attr)()) or ""
            except Exception:
                text = ""
            if text:
                break
    x, y = _pos_in(w, root)
    return f"{type(w).__name__}[{text[:16] or w.objectName() or '—'}] @({x},{y})"


def audit_page(page_id, verbose=False) -> int:
    spec = PAGE_FACTORY.get(page_id)
    if spec is None:
        print(f"[skip] {page_id}: 无独立工厂,跳过")
        return 0
    mod_name, cls_name = spec
    mod = __import__(mod_name, fromlist=[cls_name])
    previous = _neutralize(page_id)
    try:
        page = getattr(mod, cls_name)(*_ctor_args(page_id))
    finally:
        _restore(previous)
    page.resize(1200, 900)
    page.show()
    QApplication.processEvents()

    chain = focusable_chain(page)
    ideal = reading_order(chain, page)
    moves = min_moves(chain, ideal)

    print(f"[{page_id}] 可聚焦控件 {len(chain)} 个,需挪动 {moves} 个")
    if moves and verbose:
        for idx, (a, b) in enumerate(zip(chain, ideal)):
            if a is not b:
                print(f"   #{idx}")
                print(f"      链上  = {describe(a, page)}")
                print(f"      阅读序= {describe(b, page)}")

    page.close()
    page.deleteLater()
    QApplication.processEvents()
    return 1 if moves else 0


def main():
    app = QApplication.instance() or QApplication([])  # noqa: F841
    # UP-090: 见 `_audit_sandbox` —— csgo_dir 是自动探测的，不沙箱化会写到真实游戏目录
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "--verbose" in sys.argv
    include_unsafe = "--include-unsafe" in sys.argv
    if args:
        pages = args
    elif include_unsafe:
        pages = list(PAGE_FACTORY)
    else:
        pages = DEFAULT_PAGES
    rc = 0
    for pid in pages:
        try:
            rc |= audit_page(pid, verbose=verbose)
        except Exception as exc:
            print(f"[{pid}] 审计失败: {exc}")
            rc = 1

    # UP-101: 覆盖面**每次都打印**，不是只在有跳过时才打印。
    # 静默少测会被读成"全都覆盖了"——UP-096 就是这么让两个真缺陷藏了很多轮的，
    # 而本脚本此前只报"11 个页面全部为 0"，分母从来没写出来过。
    covered = f"== 焦点巡检 覆盖面: {len(pages)}/{TOTAL_PAGES} 个页面"
    missing = TOTAL_PAGES - len(pages)
    if missing <= 0:
        print(covered + "（全覆盖）")
    else:
        uncovered = set(PAGE_FACTORY) - set(pages)
        # 分开报「因为会 spawn 子进程而跳过」和「本次只是没点名」——
        # 混成一句会把"你自己指定了两个页面"说成"其余 24 个都危险"，
        # 那种报告读一次就再也不会被信任。
        spawns = sorted(uncovered & SPAWNS_SUBPROCESS)
        not_asked = sorted(uncovered - SPAWNS_SUBPROCESS)
        detail = "，**未覆盖 %d 个**（basic 无独立类" % missing
        if spawns:
            detail += "；构造即 spawn 子进程: " + ", ".join(spawns)
        if not_asked:
            detail += "；本次未点名: %d 个" % len(not_asked)
        print(covered + detail + "）")
        if spawns:
            print("   需要覆盖它们请加 --include-unsafe")
    print(f"== 焦点巡检 {'通过' if rc == 0 else '存在错位'} ==")
    # RN-068/092：机器可读的裁定由 `_audit_verdict.deliver()` 在 `__main__` 里打，
    # 见文件末尾。这里只把 rc 算出来往上交。
    return rc


if __name__ == "__main__":
    # ⚠ RN-068/092：**裁定由 `_audit_verdict` 交付，不给退出链路改写的机会。**
    # CI 上出现过「打印通过、退出码 1、无 traceback」——那个 1 来自
    # Qt/keyboard/各页析构，不是判定结果（2026-08-17 `41217bf` 实录）。
    # 反向的同一条坑也在册：门禁脚本的非零退出码曾被产品退出链路洗成 0。
    from _audit_verdict import deliver, make_teardown_noise_visible

    make_teardown_noise_visible()
    deliver("focus", main())
