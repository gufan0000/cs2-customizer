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
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ==================== ① 打包图标必须是真 ICO ====================

#: Windows 会去取的档位。16=标题栏/任务栏小图标，24/32=托盘与资源管理器，
#: 48=大图标与快捷方式。不含 256 —— 手上最大的原图只有 64×64（2026-09-20 全盘
#: 扫过 6151 张图，像它的 14 张全是 64×64 且逐字节相同），而 Pillow 对超过源图的
#: 档位是**安静跳过**的，连假分辨率都造不出来。缺口要等一张真正更大的原图。
REQUIRED_ICON_SIZES = {16, 24, 32, 48, 64}

#: ⚠ 三份，不是两份。`setup_icon.ico` 以前是某一批为了让 Inno 认而**手工重铸**的
#: 第三样东西 —— 同源却没有任何机制保证它跟前两份同步（RN-668）。
PACKAGED_ICONS = ("icon.ico", "myicon.ico",
                  "build_tools/installer_assets/setup_icon.ico")


def _ico_entries(raw: bytes):
    """读 ICONDIR，返回 [(宽, 高, 位深, 帧格式), ...]。不是 ICO 就返回 None。"""
    if len(raw) < 6 or raw[:4] != b"\x00\x00\x01\x00":
        return None
    count = struct.unpack_from("<H", raw, 4)[0]
    out = []
    for i in range(count):
        off = 6 + i * 16
        if off + 16 > len(raw):
            return out
        w, h, _nc, _res, _pl, bpp, _size, doff = struct.unpack_from(
            "<BBBBHHII", raw, off)
        kind = "PNG" if raw[doff:doff + 8] == b"\x89PNG\r\n\x1a\n" else "BMP"
        out.append((w or 256, h or 256, bpp, kind))
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
    sizes = {w for w, h, _bpp, _k in entries if w == h}
    missing = sorted(REQUIRED_ICON_SIZES - sizes)
    assert not missing, f"{name} 缺这些档: {missing}（现有 {sorted(sizes)}）"
    # 分母守卫：这条判据要有东西可查
    assert len(REQUIRED_ICON_SIZES) >= 4


@pytest.mark.parametrize("name", PACKAGED_ICONS)
def test_the_packaged_icon_uses_the_frame_format_the_installer_accepts(name):
    """⚠ 帧格式必须是 BMP。

    BMP 帧是本项目**唯一被安装器验证过**的格式（手工重铸那份 setup_icon.ico
    就是 BMP 帧）。批 106 我把 icon.ico 改成真 ICO 时用了 Pillow 的默认 PNG 帧，
    而那一档从来没有进过安装器 —— 是我引进来的未验证变更（RN-668 改回）。
    """
    entries = _ico_entries((ROOT / name).read_bytes())
    kinds = {k for *_x, k in entries}
    assert kinds == {"BMP"}, f"{name} 的帧格式是 {kinds}，要的是 BMP"


def test_all_three_icons_stay_in_step():
    """三份必须逐字节相同。

    ⭐ `_resolve_icon_path()` 按顺序取第一个存在的，前两份分叉会让源码模式和
    打包模式显示不同的图标；而第三份（安装器那份）以前是**手工重铸**的，
    同源却没有任何机制保证它跟前两份同步。
    """
    blobs = {n: (ROOT / n).read_bytes() for n in PACKAGED_ICONS}
    assert len(blobs) == 3, "分母守卫：三个消费者一个都不能少"
    assert len(set(blobs.values())) == 1, (
        "三份图标的内容不一致了：\n  " +
        "\n  ".join(f"{n}: {len(b)} 字节" for n, b in blobs.items()) +
        "\n⇒ 跑一次 python build_tools/make_app_icon.py"
    )


def _bitmap_generator():
    """拿到「从位图原图出 .ico」那一支生成器；派生仓不是这一支就返回 None。

    ⚠ 派生仓（开源版）有一支**同名但完全不同**的 `make_app_icon.py`：它是
    **用代码画准星**的，不吃任何位图原图（那张 AI 鹰头位图按法务理由被排除）。
    ⭐ 按能力判断，不按仓库名 —— **照闭源版文件集写死的断言，在子集仓里不是
    「更严」，是「错」**（RN-453 那条同族教训）。
    """
    sys.path.insert(0, str(ROOT))
    import importlib

    mod = importlib.import_module("build_tools.make_app_icon")
    if all(hasattr(mod, n) for n in ("SOURCE", "render", "ladder", "SIZES")):
        return mod
    return None


def test_the_generator_is_the_source_of_truth_for_the_icons():
    """⭐⭐ 盘上那三份必须是生成器**现在**能产出的东西。

    在 RN-668 之前它们是三样各自为政的文件（两份假 ICO ＋ 一份手工重铸），
    没有任何机制保证同步 —— 而「手工重铸」这一步没写在任何地方。
    """
    mod = _bitmap_generator()
    if mod is None:
        pytest.skip("派生仓的图标生成器是用代码画的，不吃位图原图")
    SIZES, SOURCE, ladder, render = mod.SIZES, mod.SOURCE, mod.ladder, mod.render

    assert SOURCE.exists(), f"图标原图不在了：{SOURCE}"
    raw = render()
    assert ladder(raw) == sorted(SIZES), "生成器产出的档位和它自己声明的对不上"
    for name in PACKAGED_ICONS:
        assert (ROOT / name).read_bytes() == raw, (
            f"{name} 和生成器产出的不一致 ⇒ 跑 python build_tools/make_app_icon.py"
        )


def test_the_icon_source_bitmap_never_reaches_the_public_repo():
    """⛔⛔ 图标原图是 AI 生成、仓库里没有出处记录的位图。

    ⭐⭐⭐ 它在 RN-668 之前**只存在于 `icon.ico` 内部** —— 于是它从来没有以
    「一个文件」的身份出现在同步排除表前面。**一个藏在容器里的资产，不会触发
    任何一条按文件名划分母的规矩。** 现在它落成了真文件，这道门就必须有人守。

    ⚠ 同步管道自己在开源仓里不存在（`build_tools/oss_sync/` 也在排除表里），
    所以这条判据在派生仓里会跳过 —— 那正是它该守的地方在上游的证据。
    """
    manifest = ROOT / "build_tools" / "oss_sync" / "manifest.py"
    if not manifest.exists():
        pytest.skip("派生仓里没有同步管道（它自己也在排除表里）")
    src = manifest.read_text(encoding="utf-8")
    assert '"build_tools/icon_source/"' in src, (
        "`build_tools/icon_source/` 不在 oss_sync 的排除表里了 —— "
        "那张 AI 位图会被 --apply 推进公开仓，正是 2026-08-12 审计要防的事"
    )
    # 阴性对照：同族那条一直都在，两条一起丢说明我读错了文件
    assert "splash_art_ai.png" in src, "分母守卫：连同族那条都找不到，八成读错了文件"


def test_upstream_only_breakpoints_really_are_upstream_only():
    """⛔ `upstream_only=True` 是个**静音开关** —— 它让一条断点在派生仓里
    从「腐烂」变成「不适用」，也就是**不再计入退出码**。

    ⭐⭐⭐ 它要守的那一格是真的（同名不同物，见 RN-671），但同一个开关也能
    拿来掩盖一条真腐烂的断点。⇒ 打了这个标志的断点，它的目标文件必须**确实**
    在派生仓里归对方所有或被排除；随手打一个在普通产品文件上，这条判据当场红。
    """
    script = ROOT / "scripts" / "revert_verify.py"
    manifest = ROOT / "build_tools" / "oss_sync" / "manifest.py"
    if not manifest.exists():
        pytest.skip("派生仓里没有同步清单（它自己也在排除表里）")

    import importlib.util
    spec = importlib.util.spec_from_file_location("_rv_under_test", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    flagged = [r for r in mod.REVERTS if getattr(r, "upstream_only", False)]
    assert flagged, "一条都没有 ⇒ 这条判据在空转（有就该守着，没有就该删掉它）"

    # ⚠⚠ 第一版是拿路径字符串去 `in manifest 源码` 里搜，**回退验证当场判它没逮住**：
    #   `build_tools/make_app_icon.py` 在 `GENERATED`（第三张表）里也逐字出现，
    #   于是删掉 `OWNED_BY_OSS` 那一行它照样匹配得上。
    #   ⭐⭐⭐ **那把尺子问的是「这个字符串出现过吗」，而我要保证的是
    #   「它在这两张表里」** —— 又一次分母划错。⇒ 真读那两张表。
    sys.path.insert(0, str(ROOT / "build_tools" / "oss_sync"))
    spec2 = importlib.util.spec_from_file_location("_manifest_under_test", manifest)
    mf = importlib.util.module_from_spec(spec2)
    sys.modules[spec2.name] = mf
    spec2.loader.exec_module(mf)
    claimed = list(mf.OWNED_BY_OSS) + list(mf.EXCLUDE_PREFIX)
    assert len(claimed) > 40, f"分母守卫：只读出 {len(claimed)} 条声明，八成读错了表"

    bad = []
    for r in flagged:
        rel = r.path.relative_to(ROOT).as_posix()
        ok = any(rel == c or (c.endswith("/") and rel.startswith(c)) for c in claimed)
        if not ok:
            bad.append(rel)
    assert not bad, (
        "这些断点打了 upstream_only，但它们的目标文件在派生仓里既不归对方所有、"
        f"也没被排除 —— 那就不是「同名不同物」，是拿静音开关掩盖腐烂：{bad}"
    )


def test_the_size_ladder_never_asks_for_more_than_the_source_has():
    """⛔ 往 SIZES 里加超过原图的档位是**安静失效**的。

    ⭐⭐⭐ Pillow 对 `sizes=` 里超过源图尺寸的项**不报错也不生成**；写上 256
    只会得到一个「少了 256 档」的 .ico，而它看起来和写对了一模一样。
    生成器为此显式拦了一道，这条判据守住那道拦截还在。
    """
    from PIL import Image

    mod = _bitmap_generator()
    if mod is None:
        pytest.skip("派生仓的图标生成器是用代码画的，档位不受原图尺寸限制")
    side = Image.open(mod.SOURCE).size[0]
    assert max(mod.SIZES) <= side, (
        f"SIZES 最大要到 {max(mod.SIZES)}，而原图只有 {side}px —— "
        "Pillow 会安静少档。要更大的档就换原图。"
    )
    assert len(mod.SIZES) >= 5, "分母守卫：档位表被砍空了这条判据就没意义"


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


def test_eight_round_events_fit_in_three_rows():
    """回合有 8 个事件、状态条写「已选 0/8」，那就不该排成四行往下掉（RN-669）。"""
    from core.audio.special_events import events_in_group
    from pages.special_sound_page import SpecialSoundPage

    total = len(list(events_in_group("round")))
    assert total >= 6, f"回合事件只剩 {total} 个了，这条判据的算式要重算"
    columns = SpecialSoundPage._responsive_columns_for_cards(_WidthShell(1060), total)
    rows = -(-total // columns)
    assert rows <= 3, f"1060 的页宽下要排 {rows} 行（列数 {columns}）"


def test_the_round_volume_shares_a_row_with_the_switch():
    """总音量原先是头部卡里的一张**卡中卡**，上下内边距 + 独占一行。

    ⭐ 实测：并成一行之后回合页签的溢出量从「第 7/8 张完全看不见」降到 43px，
    而零素材横幅本身占 54px —— 有素材的用户那 8 张卡就全露了（RN-669）。
    """
    src = (ROOT / "pages" / "special_sound_page.py").read_text(encoding="utf-8")
    body = src[src.index("def _create_round_tab"):src.index("def _create_round_tab") + 4000]
    assert "control_row" in body, "回合页签没有那一行合并布局了"
    switch_at = body.index("round_enabled_checkbox = QCheckBox")
    slider_at = body.index("round_volume_slider = QSlider")
    between = body[switch_at:slider_at]
    assert "_row_card()" not in between, (
        "总音量又被包回一张卡中卡里了 —— 那会把第 7、8 个回合事件推出首屏"
    )
    assert "control_row.addWidget(self.round_volume_slider" in body, (
        "音量滑块不在那一行合并布局里"
    )


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
