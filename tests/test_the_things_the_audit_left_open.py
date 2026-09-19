# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""收尾批：上一轮立案不修的那几条 + 用户反馈里的图标问题。

五组判据，对应五条独立缺陷：

① **打包图标不是 ICO** —— `icon.ico` / `myicon.ico` 是改了扩展名的单张 64×64 PNG。
   ⭐⭐⭐ Qt 的 `QIcon` 按**内容**嗅探格式，所以程序窗口里一直是好的；
   而 Windows 任务栏 / 快捷方式 / exe 资源要的是真 ICO 容器。
   **界面里看着好好的，界面外就坏了** —— 而开发只看得见界面里那一半。
   （它至今没炸，是因为 PyInstaller 6 碰巧会用 Pillow 归一化。换个打包器就断。）

② **拍图工装的两个开关是正交的，而盲区在乘积上** —— `--tabs` 逐页签拍但按视口
   高度（折线以下没人看过），`--whole` 拍无折线整页但只对**默认页签**生效。
   于是"有页签 + 内容超高"的那一格从来没有过一张完整的图。

③ **托盘不可用时三个关闭行为全塌缩成"直接退出"**，而下拉框照样让人选。

④ **替身缺产品要调的方法** —— 上一批给产品加 `stop_channel_type`，两个替身当场
   AttributeError。这条判据把"替身该有哪些方法"从人记变成算出来。

⑤ **投掷物六张卡只露得出四张**，而状态条同时写着「0/6」。
"""
from __future__ import annotations

import ast
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ==================== ① 打包图标必须是真 ICO ====================

#: Windows 会去取的档位。16=标题栏/任务栏小图标，24/32=托盘与资源管理器，
#: 48=大图标与快捷方式。不含 256 —— 手上最大的原图只有 64×64，
#: 造一张放大的 256 是假分辨率，缺口记在登记册里等原始 logo。
REQUIRED_ICON_SIZES = {16, 24, 32, 48}

PACKAGED_ICONS = ("icon.ico", "myicon.ico")


def _ico_entries(raw: bytes):
    """读 ICONDIR，返回 [(宽, 高, 位深), ...]。不是 ICO 就返回 None。"""
    if len(raw) < 6 or raw[:4] != b"\x00\x00\x01\x00":
        return None
    count = struct.unpack_from("<H", raw, 4)[0]
    out = []
    for i in range(count):
        off = 6 + i * 16
        if off + 16 > len(raw):
            return out
        w, h, _nc, _res, _pl, bpp, _size, _doff = struct.unpack_from("<BBBBHHII", raw, off)
        out.append((w or 256, h or 256, bpp))
    return out


@pytest.mark.parametrize("name", PACKAGED_ICONS)
def test_the_packaged_icon_is_a_real_ico_container(name):
    """扩展名是 .ico 就必须真的是 ICO —— 不许是改了名的 PNG。"""
    path = ROOT / name
    assert path.exists(), f"{name} 不在了；它在 build_release.py 的发布清单里"
    raw = path.read_bytes()
    assert not raw.startswith(b"\x89PNG\r\n\x1a\n"), (
        f"{name} 是一张 PNG，只是扩展名写成了 .ico。"
        "Qt 按内容嗅探所以窗口图标看着正常，但 Windows 任务栏/快捷方式/exe 资源"
        "要的是真 ICO 容器。"
    )
    assert _ico_entries(raw) is not None, f"{name} 的前四字节不是 ICONDIR"


@pytest.mark.parametrize("name", PACKAGED_ICONS)
def test_the_packaged_icon_covers_the_sizes_windows_asks_for(name):
    """只打一张 64×64 的话，16/24/32/48 每一档都是现场缩出来的。"""
    entries = _ico_entries((ROOT / name).read_bytes())
    assert entries, f"{name} 里一个目录项都没有"
    sizes = {w for w, h, _bpp in entries if w == h}
    missing = sorted(REQUIRED_ICON_SIZES - sizes)
    assert not missing, f"{name} 缺这些档: {missing}（现有 {sorted(sizes)}）"
    # 分母守卫：这条判据要有东西可查
    assert len(REQUIRED_ICON_SIZES) >= 4


def test_both_packaged_icons_stay_in_step():
    """两份图标是同一张图的两个名字（发布清单里各塞了一份）——别让它们分叉。"""
    blobs = {n: (ROOT / n).read_bytes() for n in PACKAGED_ICONS}
    assert len(set(blobs.values())) == 1, (
        "icon.ico 与 myicon.ico 内容不同了。`_resolve_icon_path()` 是按顺序取第一个"
        "存在的，两者分叉会让源码模式和打包模式显示不同的图标。"
    )


# ==================== ② 拍图工装：页签 × 整页 ====================

CAPTURE = ROOT / "scripts" / "ui_shot_capture.py"


def _capture_tree():
    return ast.parse(CAPTURE.read_text(encoding="utf-8"))


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_the_per_tab_capture_can_also_shoot_whole_pages():
    """`_capture_tabs` 得能出无折线整页图，否则页签 × 超高那一格永远没人看。"""
    tree = _capture_tree()
    fn = _func(tree, "_capture_tabs")
    assert fn is not None, "ui_shot_capture.py 里没有 _capture_tabs 了"
    params = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "whole" in params, (
        "_capture_tabs 收不到 whole —— 那么 --tabs 的图仍然只有视口高度，"
        "页签里折线以下的内容一张图都没有（RN-665①）"
    )
    # ⚠⚠ 光查「调用在不在」是不够的 —— 回退验证实测：把 `if whole:` 改成
    #    `if False:`，调用照样在 AST 里，这条判据照样绿。
    # ⭐⭐⭐ **判据查的是「存在」，而缺陷发生在「可达」上。**
    # ⇒ 改成：那个调用必须被一个**提到 whole 的条件**罩着。
    guarded = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "whole" not in names:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                    and inner.func.id == "_shoot_whole":
                guarded = True
    assert guarded, (
        "_capture_tabs 里没有「由 whole 决定的 _shoot_whole 调用」—— "
        "要么没调，要么那个调用被一个与 whole 无关的条件挡住了"
    )


def test_the_whole_switch_reaches_the_per_tab_capture():
    """开关得真的接到线上 —— 有形参没人传，等于没做。"""
    tree = _capture_tree()
    main = _func(tree, "main")
    assert main is not None
    wired = False
    for node in ast.walk(main):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "_capture_tabs":
            continue
        for kw in node.keywords:
            if kw.arg == "whole" and ast.unparse(kw.value) == "args.whole":
                wired = True
    assert wired, "main() 调 _capture_tabs 时没有把 args.whole 传进去"


def test_both_capture_paths_share_one_whole_page_implementation():
    """撑高窗口 + 必须复位这套动作只许有一份 —— 两份迟早分叉一份。"""
    tree = _capture_tree()
    assert _func(tree, "_shoot_whole") is not None, "没有 _shoot_whole"
    for owner in ("_capture_whole", "_capture_tabs"):
        fn = _func(tree, owner)
        called = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_shoot_whole" in called, f"{owner} 没走共用的 _shoot_whole"


# ==================== ③ 托盘不可用 ⇒ 关闭行为置灰 ====================

def _close_action_shell(tray_available: bool):
    """只搭出这条逻辑需要的两个控件，拿真方法跑 —— 不建整页（构造整页会起设备）。"""
    from PySide6.QtWidgets import QComboBox, QLabel

    from pages.advanced_page import AdvancedPage

    class _Shell:
        pass

    shell = _Shell()
    combo = QComboBox()
    combo.addItem("每次询问（默认）", "ask")
    combo.addItem("最小化到系统托盘", "tray")
    combo.addItem("直接退出程序", "exit")
    combo.setCurrentIndex(0)
    shell.close_action_combo = combo
    shell.close_action_tray_hint = QLabel("")
    shell._system_tray_available = staticmethod(lambda: tray_available)
    AdvancedPage._refresh_close_action_availability(shell)
    return shell


def test_close_action_is_greyed_out_when_there_is_no_tray(qapp):
    """没有托盘时三个选项全是死的 —— 那就不许摆成可选项（RN-665⑤）。"""
    shell = _close_action_shell(tray_available=False)
    assert not shell.close_action_combo.isEnabled(), (
        "托盘不可用，下拉框却还能选。用户选「最小化到系统托盘」之后程序照样退出，"
        "而且一声不吭。"
    )
    assert shell.close_action_tray_hint.isVisible() or shell.close_action_tray_hint.text(), (
        "置灰了却没说原因 —— 那和坏掉长得一样"
    )
    assert "托盘" in shell.close_action_tray_hint.text()
    assert shell.close_action_combo.currentData() == "exit", (
        "置灰的同时得把当前值落到真正会发生的那个行为上"
    )


def test_close_action_stays_usable_when_the_tray_is_there(qapp):
    """⚠ 反向：托盘正常时不许乱灰。这条是上一条的分母。"""
    shell = _close_action_shell(tray_available=True)
    assert shell.close_action_combo.isEnabled()
    assert not shell.close_action_tray_hint.text()
    assert shell.close_action_combo.currentData() == "ask", "不该动用户已有的选择"


def test_tray_probe_fails_open(qapp):
    """⚠ 探测不出来时朝「可用」倒：朝「不可用」倒会在正常机器上把功能灰掉。"""
    from pages.advanced_page import AdvancedPage

    import PySide6.QtWidgets as qtw

    real = qtw.QSystemTrayIcon.isSystemTrayAvailable

    def _boom():
        raise RuntimeError("探测炸了")

    qtw.QSystemTrayIcon.isSystemTrayAvailable = staticmethod(_boom)
    try:
        assert AdvancedPage._system_tray_available() is True
    finally:
        qtw.QSystemTrayIcon.isSystemTrayAvailable = real


# ==================== ④ 替身的最小接口 ====================

def _public_audio_calls(path: Path) -> set[str]:
    """产品文件里 `(self.)audio_manager.X(...)` 用到的**公开**方法名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr.startswith("_"):
            continue
        base = node.value
        if isinstance(base, ast.Attribute) and base.attr in ("audio_manager", "audio_mgr"):
            out.add(node.attr)
        elif isinstance(base, ast.Name) and base.id in ("audio_manager", "audio_mgr"):
            out.add(node.attr)
    return out


def _handler_requirements() -> dict[str, set[str]]:
    """每个 GSI 处理器类要求 audio_manager 有哪些公开方法。"""
    req = {}
    for path in sorted(ROOT.glob("gsi_handler*.py")):
        calls = _public_audio_calls(path)
        if not calls:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                req[node.name] = calls
    return req


def _stand_ins():
    """(测试文件, 替身类名, 方法集, 该文件构造的处理器) 四元组。

    ⚠ **只看没有基类的替身**：`_FallbackAudioManager` 这类子类是**故意残缺**的变体，
    它们存在的意义就是缺某个方法好走回退分支，不能拿完整性去要求它们。
    """
    req = _handler_requirements()
    rows = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        handlers = sorted({h for h in req if re.search(rf"\b{h}\s*\(", src)})
        if not handlers:
            continue
        need = set()
        for h in handlers:
            need |= req[h]
        if not need:
            continue
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.ClassDef) or node.bases:
                continue
            if "audio" not in node.name.lower():
                continue
            methods = {
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            rows.append((path.name, node.name, methods, need))
    return rows


def test_the_handler_requirements_are_not_empty():
    """分母守卫：算不出要求就说明上面那套 AST 失配了，下面那条会空转成绿。"""
    req = _handler_requirements()
    assert len(req) >= 3, f"只认出 {len(req)} 个 GSI 处理器，AST 口径八成漂了"
    assert "play_sound" in set().union(*req.values())
    rows = _stand_ins()
    assert len(rows) >= 5, f"只找到 {len(rows)} 个替身，分母不对"


def test_gsi_stand_ins_implement_what_the_handlers_actually_call():
    """⭐ 上一批给产品加了 `stop_channel_type`，两个替身当场 AttributeError。

    ⭐⭐ 而**另外两个文件的替身同样缺它，只是没走到那条路径所以一直绿** ——
    这条判据就是拿来逮那种"还没轮到它红"的替身的。
    """
    broken = []
    for fname, cname, methods, need in _stand_ins():
        missing = sorted(need - methods)
        if missing:
            broken.append(f"{fname}::{cname} 缺 {missing}")
    assert not broken, "替身没跟上产品接口:\n  " + "\n  ".join(broken)


# ==================== ⑤ 投掷物六张卡要露得出来 ====================

class _WidthShell:
    """只给 `_responsive_columns_for_cards` 它唯一要的那个输入。"""

    def __init__(self, width):
        self._w = width

    def width(self):
        return self._w


@pytest.mark.parametrize(
    "width, expected, why",
    [
        (1060, 3, "1280 窗口减掉侧栏的真实页宽"),
        (824, 2, "紧凑档 860 窗口的真实页宽"),
        (520, 1, "再窄就只能一列"),
    ],
)
def test_the_grenade_grid_uses_the_columns_the_width_allows(width, expected, why):
    """⭐ 阈值原来是 1380，而这一页**永远到不了 1380** ——
    一个达不到的阈值和没有这一档是一回事，却在代码里长得像已经考虑过宽屏了。"""
    from pages.special_sound_page import SpecialSoundPage

    got = SpecialSoundPage._responsive_columns_for_cards(_WidthShell(width), 6)
    assert got == expected, f"页宽 {width}（{why}）应当 {expected} 列，实际 {got}"


def test_six_grenade_types_fit_in_two_rows_on_a_normal_window():
    """六种投掷物、状态条写「0/6」——那六张就得在首屏摆得下（RN-665③）。"""
    from core.audio.audio_manager import AudioManager
    from pages.special_sound_page import SpecialSoundPage

    total = len(AudioManager.GRENADE_TYPES)
    assert total == 6, f"投掷物类型变成 {total} 种了，这条判据的算式要重算"
    columns = SpecialSoundPage._responsive_columns_for_cards(_WidthShell(1060), total)
    rows = -(-total // columns)
    assert rows <= 2, f"1060 的页宽下要排 {rows} 行，首屏放不下（列数 {columns}）"


def test_the_naming_hint_sits_below_the_cards():
    """那三行命名提示原先顶在网格上面，把卡片推到了折线外。

    ⚠ 它是「我要自己做素材」时才看的，不是进页面第一眼要看的。
    """
    src = (ROOT / "pages" / "special_sound_page.py").read_text(encoding="utf-8")
    grid_at = src.index("scroll_layout.addLayout(grid)")
    hint_at = src.index("scroll_layout.addWidget(naming_hint)")
    assert hint_at > grid_at, (
        "命名提示又跑到网格上面去了 —— 那会把六张卡里的最后两张推出首屏"
    )
