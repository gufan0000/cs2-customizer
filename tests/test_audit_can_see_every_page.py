# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-005 / RN-059：离屏审计必须能看到**每一页**，且绝不真占设备。

## 这一支判据要防的事

翻新工程的 5 支离屏脚本各自抄了一份「中和表」，内容 1~3 项不等。
后果是量出来的（2026-08-17）：

    flash          被 5/5 支脚本跳过     ← 零覆盖
    viewmodel      被 5/5 支脚本跳过     ← 零覆盖
    voice_output   被 5/5 支脚本跳过     ← 零覆盖
    music          被 4/5 支跳过
    kill_icon      被 2/5 支跳过（因此没有指纹基线）
    magnifier      被 0/5 支跳过

**flash(1507 行) + viewmodel(823) + voice_output(1935) = 4265 行界面，
从来没有排版审计、没有指纹、没有截图、没有焦点巡检。**
而 `music` 那条中和条件早在 `tab_order_audit` 里验证过，另外四支不知道 ——
同 RN-002 / RN-031 / RN-032 一模一样的病：**副本不会跟着彼此变，而且漂了不报错。**

## 判据分三层

1. **单一真相源**：AST 扫脚本目录，不许再出现第二张中和表。
2. **覆盖面**：中和之后 `unsafe_pages()` 必须是空的 —— 一页都不许再被跳过。
3. **保证**（最重要的一条）：闸门开着时，`register_*` 一律**不向
   keyboard / mouse 挂任何钩子**。这条不读代码，读的是"库到底被调用了没有"。
"""
from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


# ============================================================ 一、单一真相源

def test_the_neutralize_table_exists_in_exactly_one_place():
    """中和表只准有一份，且必须在 `scripts/_audit_neutralize.py` 里。

    判的是**赋值语句的名字**，不是注释：以后有人再写
    `NEUTRALIZABLE = {...}` / `NEUTRALIZE = {...}`，这条当场报。
    """
    owners = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if (isinstance(target, ast.Name)
                        and target.id in {"NEUTRALIZABLE", "NEUTRALIZE"}):
                    owners.append(f"{path.name}:{node.lineno}")
    assert owners == ["_audit_neutralize.py:" + owners[0].split(":")[1]] or \
        [o.split(":")[0] for o in owners] == ["_audit_neutralize.py"], (
        f"中和表出现在这些地方：{owners} —— 只准 `_audit_neutralize.py` 一份（RN-005）")


def test_every_neutralize_entry_says_what_it_blocks():
    """表里每一条都必须有注释说明"它挡住了什么"。

    没有理由的中和条件是最危险的一类：下一个人不知道能不能删，
    于是它永远留着，而它挡的那件事可能早就不存在了
    （`kill_icon` 那条在 tab_order_audit 里就白留了一整轮重构）。
    """
    source = (REPO / "scripts" / "_audit_neutralize.py").read_text(encoding="utf-8")
    body = source[source.index("NEUTRALIZE: dict"):source.index("def enable_audit_mode")]
    import _audit_neutralize as mod
    for page_id in mod.NEUTRALIZE:
        marker = f'"{page_id}":'
        assert marker in body, page_id
        before = body[:body.index(marker)]
        # 这一条上面紧邻的若干行里必须有注释
        preceding = [ln.strip() for ln in before.rstrip().split("\n")[-6:]]
        assert any(ln.startswith("#") for ln in preceding), (
            f"`{page_id}` 那条中和条件上面没有任何注释 —— "
            "写清它挡住了什么，否则下一个人不敢删也不敢改")


# ============================================================ 二、覆盖面

def test_no_page_is_skipped_by_the_audits_any_more():
    """中和之后一页都不许被跳过。

    ⚠ 这条**不是**在说"设备页不再占设备"——`core.page_traits` 那个产品事实
    没变。它说的是"审计侧已经有办法安全地把它们全部纳入"。
    """
    import _audit_neutralize as mod
    left = sorted(mod.unsafe_pages())
    assert not left, (
        f"这些页仍然被所有离屏审计跳过：{left} —— "
        "要么给出中和条件，要么在档案里写明为什么它必须留在盲区")


def test_only_the_shared_table_may_read_the_device_page_list():
    """`scripts/` 下只有 `_audit_neutralize.py` 能 import `DEVICE_OWNING_PAGES`。

    ⭐ 这条判据的**命题**换过一次，过程值得记：
    前三版都在试图"枚举出会构造页面的审计工具"，而每个候选识别信号都有病 ——

        v1  硬写 5 支脚本名          → 漏了 `renovation_baseline`（第 6 处）
        v2  文本包含 DEVICE_OWNING…  → 命中 `revert_verify` 里的断点锚点**字符串**
        v2.5 AST + show_page         → 拉进一批一次性老脚本；更糟的是它靠
                                       "有没有引用 DEVICE_OWNING_PAGES"识别，
                                       而那正是被修掉的东西 ⇒ **修完就不再被盯着**
        v3  两个 AST 条件的交集      → 又漏了 `renovation_baseline` / `tab_order_audit`

    ⇒ 要防的不是"某支工具没 import 共享表"（那需要先枚举工具），
      而是"**有人又从 `DEVICE_OWNING_PAGES` 私自造了一份跳过名单**"。
      后者可以精确判定，且不随修复变化。新写的脚本要跳过设备页，
      唯一的路就是 import 那个常量 —— 一 import 就被这条拦住。

    ⚠ 产品侧（`gui_widget` 的静默预载）照常 import 它 —— 那是**产品事实**的
      正当消费者。这条只管 `scripts/`。
    """
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.name == "_audit_neutralize.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom)
                    and any(a.name == "DEVICE_OWNING_PAGES" for a in node.names)):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        f"这些脚本自己去读设备页名单造跳过逻辑：{offenders} —— "
        "跳过/中和的决定只准由 `scripts/_audit_neutralize.py` 做（RN-005）")


#: 自己构造页面的脚本 —— 必须**真的调用**中和，不是 import 一下。
_MUST_NEUTRALIZE = ["ui_shot_capture.py", "layout_overflow_audit.py", "page_fingerprint.py",
                    "build_search_index.py", "tab_order_audit.py", "bench_page_build.py"]
#: 只编排、由子进程去构造页面的脚本 —— 它只需要认 `unsafe_pages()` 这条拒绝线。
_ORCHESTRATORS = ["renovation_baseline.py"]


def _neutralize_aliases(tree: ast.AST) -> tuple[set, set]:
    """从 `from _audit_neutralize import apply as neutralize_apply` 里把别名挖出来。

    判据不能假设大家都用同一个别名 —— 现役就有 `apply as neutralize_apply`
    和直接 `NEUTRALIZE` 两种写法。
    """
    applies, tables = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("_audit_neutralize"):
            for alias in node.names:
                if alias.name == "apply":
                    applies.add(alias.asname or alias.name)
                elif alias.name in ("NEUTRALIZE", "NEUTRALIZABLE"):
                    tables.add(alias.asname or alias.name)
    return applies, tables


def test_the_shared_table_is_actually_used_by_the_gate_scripts():
    """反向判据：光"没人私自造名单"不够 —— 得确认关键几支**真的在调用**它。

    ⚠ RN-073：这条判据的**上一版是假绿的** —— 它只查文件里有没有
    `"_audit_neutralize"` 这个子串，于是「import 了但从来不调用」完全过关。
    实际后果：`bench_page_build` 把 `apply` 导进来就没再管，第二层中和
    在那支脚本里等于没接上。
    ⇒ 改成 AST 找 **Call 节点 / 对 NEUTRALIZE 的读取**，并把别名解析进去。
    同一条规矩在本仓写过多次：**判断"有没有被调用"永远走 AST，不看子串。**

    覆盖面写死在两张名单里，不假装全覆盖（UP-096）：
    自己建页的要调用中和，只编排的只要认拒绝线。
    """
    bad = []
    for name in _MUST_NEUTRALIZE:
        tree = ast.parse((REPO / "scripts" / name).read_text(encoding="utf-8"))
        applies, tables = _neutralize_aliases(tree)
        called = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id in applies for n in ast.walk(tree))
        # tab_order_audit 走的是"读表 + 事后还原"，不用 apply()，同样算真的在用
        read_table = any(isinstance(n, ast.Name) and n.id in tables
                         and isinstance(n.ctx, ast.Load) for n in ast.walk(tree))
        # 函数体里 `from _audit_neutralize import NEUTRALIZE` 也要认
        read_table = read_table or any(
            isinstance(n, ast.Attribute) and n.attr in ("NEUTRALIZE", "NEUTRALIZABLE")
            for n in ast.walk(tree))
        if not (called or read_table):
            got = f"import 了 {sorted(applies | tables) or '什么都没'}，但一次都没调用/读取"
            bad.append(f"{name}（{got}）")
    assert not bad, (
        f"这几支自己建页，却没有真正中和：{bad}（RN-005 / RN-073）。"
        "只 import 不调用 = 第二层中和在这支脚本里没接上。"
        f"⚠ 本条覆盖面 = {_MUST_NEUTRALIZE}")

    for name in _ORCHESTRATORS:
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "unsafe_pages" in text, (
            f"{name} 是编排者（页面在子进程里建），至少要认 `unsafe_pages()` 这条拒绝线")


def test_shot_capture_and_layout_audit_enable_the_hotkey_gate():
    """会构造页面的脚本必须打开热键闸门，且要在 import 产品之前。

    顺序错了等于没开：注册中心读的是 `os.environ`，而页面在构造时就注册。
    """
    for name in ("ui_shot_capture.py", "layout_overflow_audit.py",
                 "page_fingerprint.py", "build_search_index.py"):
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "enable_audit_mode()" in text, f"{name} 没开热键闸门（RN-059）"
        gate_at = text.index("enable_audit_mode()")
        # 产品模块的 import 必须都在闸门之后
        for product in ("import gui_widget", "from config import config"):
            pos = text.find(product)
            if pos >= 0:
                assert pos > gate_at, (
                    f"{name}: `{product}` 出现在 enable_audit_mode() **之前** —— "
                    "闸门要在 import 产品模块之前打开，否则页面构造时读到的是旧值")


# ============================================================ 三、保证（最重要）

@pytest.fixture()
def hotkey_gate(monkeypatch):
    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    from core.hotkeys import registry
    importlib.reload(registry)
    yield registry
    monkeypatch.delenv("CS2C_NO_GLOBAL_HOTKEYS", raising=False)
    importlib.reload(registry)


def test_the_gate_registers_nothing_with_the_real_libraries(hotkey_gate, monkeypatch):
    """⭐ 闸门开着时，keyboard / mouse **一次都不许被调用**。

    这条判据的要害是它**不读代码**，读的是库到底被碰了没有 ——
    以后有人绕过注册中心直接 `keyboard.add_hotkey(...)`，
    这条判据不会报（它管不到），但注册中心这一层的承诺是钉住的。
    配套的那条"页面构造后绑定表里没有真 handle"在下面。
    """
    calls = []

    class FakeLib:
        def __getattr__(self, name):
            def spy(*a, **kw):
                calls.append(name)
                return object()
            return spy

    monkeypatch.setattr(hotkey_gate, "_keyboard", FakeLib(), raising=False)
    monkeypatch.setattr(hotkey_gate, "_mouse", FakeLib(), raising=False)

    assert hotkey_gate.hotkeys_disabled() is True

    tokens = [
        hotkey_gate.register_key("t", "f1", on_press=lambda *_: None),
        hotkey_gate.register_hotkey("t", "ctrl+alt+x", lambda: None, suppress=True),
        hotkey_gate.register_hook("t", lambda *_: None, suppress=True),
        hotkey_gate.register_mouse("t", "right", on_press=lambda *_: None),
    ]

    assert calls == [], f"闸门开着却调了底层库：{calls}"
    assert all(t is not None for t in tokens), (
        "闸门开着时也必须照常发 token 并记账 —— "
        "否则高级设置页的绑定总览和改键冲突提示在审计进程里就量不到了")
    bindings = hotkey_gate.list_bindings()
    assert len(bindings) >= 4
    assert all("审计模式" in (b.get("note") or "") for b in bindings), bindings


def test_without_the_gate_the_real_libraries_are_used(hotkey_gate, monkeypatch):
    """空转守卫：闸门**关掉**时必须真去调库。

    没有这一条，上面那支可以靠"这个函数根本不工作"作弊通过。
    """
    monkeypatch.delenv("CS2C_NO_GLOBAL_HOTKEYS", raising=False)
    importlib.reload(hotkey_gate)
    calls = []

    class FakeLib:
        def __getattr__(self, name):
            def spy(*a, **kw):
                calls.append(name)
                return object()
            return spy

    monkeypatch.setattr(hotkey_gate, "_keyboard", FakeLib(), raising=False)
    monkeypatch.setattr(hotkey_gate, "_mouse", FakeLib(), raising=False)

    assert hotkey_gate.hotkeys_disabled() is False
    hotkey_gate.register_hotkey("t", "ctrl+alt+y", lambda: None)
    hotkey_gate.register_mouse("t", "right", on_press=lambda *_: None)
    assert calls, "闸门关着却没碰底层库 —— 那上面那支判据是假绿的"


def test_the_gate_is_never_switched_on_by_product_code():
    """产品代码任何地方都不许设 `CS2C_NO_GLOBAL_HOTKEYS`。

    只有 `scripts/` 下的审计工装能设。设错地方就是给真实用户偷偷关掉音板热键
    —— 这也正是**故意不复用** `CS2C_SAFE_MODE_ACTIVE` 的原因
    （那个变量在真实运行里也会被 `main_widget` 打开）。
    """
    offenders = []
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith((".build/", "scripts/", "tests/", ".claude/")):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "CS2C_NO_GLOBAL_HOTKEYS" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            # 只拦"写"：os.environ[...] = ... / setdefault / putenv
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and "CS2C_NO_GLOBAL_HOTKEYS" in ast.dump(target)):
                        offenders.append(f"{rel}:{node.lineno}")
            if isinstance(node, ast.Call):
                dumped = ast.dump(node)
                if ("CS2C_NO_GLOBAL_HOTKEYS" in dumped
                        and ("setdefault" in dumped or "putenv" in dumped)):
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"产品代码在设审计闸门：{offenders} —— 那会给真实用户关掉全局热键（RN-059）")


def test_no_page_registers_a_real_hotkey_when_the_gate_is_on(qapp, monkeypatch):
    """⭐ 端到端：闸门开着 + 全新配置，逐个构造 6 个设备页，
    keyboard / mouse 一次都不许被调用。

    这是"我敢把这些页纳入审计覆盖面"的那条依据本身。
    2026-08-17 探针实测的原始数字：六页全部 0 次库调用、0 条真绑定、0 个可见窗口。
    """
    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")

    calls = []
    for modname in ("keyboard", "mouse"):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for name in ("add_hotkey", "on_press_key", "on_release_key", "hook",
                     "hook_key", "block_key", "on_button", "on_click"):
            if hasattr(mod, name):
                monkeypatch.setattr(
                    mod, name,
                    (lambda n=f"{modname}.{name}": (
                        lambda *a, **kw: calls.append(n)))(),
                    raising=False)

    from core.hotkeys import registry
    importlib.reload(registry)
    import _audit_neutralize as neutral
    from config import config
    neutral.apply(config)

    from core.page_traits import DEVICE_OWNING_PAGES

    built = []
    for page_id in sorted(DEVICE_OWNING_PAGES):
        module_name = {"kill_icon": "kill_icon", "voice_output": "voice_output"}.get(
            page_id, page_id)
        try:
            mod = importlib.import_module(f"pages.{module_name}_page")
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"{page_id} 无法导入：{exc}")
        cls = next(obj for name, obj in vars(mod).items()
                   if name.endswith("Page") and isinstance(obj, type))
        try:
            page = cls(config) if page_id == "magnifier" else cls()
        except TypeError:
            page = cls()
        built.append(page_id)
        page.deleteLater()

    assert built, "一页都没构造起来，这条判据没量到东西"
    assert calls == [], (
        f"闸门开着，但这些页还是直接碰了底层热键库：{sorted(set(calls))} —— "
        "说明它们绕过了注册中心（RN-059 管不到那种写法，要单独修）")
    importlib.reload(registry)


# ============================================================ 四、侧栏不许切字

def test_sidebar_never_shows_a_half_cut_nav_item_at_the_top(qapp, monkeypatch):
    """⭐ RN-060：侧栏视口**上边缘**不许落在某个导航项中间。

    实测原状（2026-08-17，1280×800 完整模式，逐页量）：

        侧栏视口 657px / 内容 1449px / 项高约 43px
        滚动值 26 / 69 / 112 / 155 / 244 / 287 / …（差值正好等于项高）
        ⇒ **28 页里 16 页**顶部被切 13~20px、底部被切 19~21px

    用户看到的是**残缺的导航文字**（「基础设置」只剩下半截）。
    外审 8 发独立报这一条，跨 4 页的 7 张截图。

    ⚠ 排版审计一直是绿的：侧栏是 QScrollArea，"露半行"几何上不算溢出
    （同 RN-045）。⇒ **判据看不见的东西只有眼睛能看见** —— 所以这条判据
    量的是"项与视口边缘的相对位置"，不是"有没有溢出"。

    ⚠ 只断言**上**边缘。视口高 657 不是项高 43 的整数倍，
    上下不可能同时对齐，只能选一头；选顶部是因为那是视觉起点。
    底边剩下的那道缝里没有文字，不构成"残缺的字"。
    """
    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QAbstractButton

    import _audit_neutralize as neutral
    from config import config
    neutral.apply(config)
    config.ui_expert_mode = True
    config.compact_mode = False

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        qapp.processEvents()

        scroll = getattr(win, "_sidebar_scroll", None)
        assert scroll is not None, "找不到侧栏滚动区"
        viewport = scroll.viewport()
        if scroll.verticalScrollBar().maximum() <= 0:
            pytest.skip("这台机器上侧栏不需要滚动，这条判据量不到东西")

        offenders = []
        scrolled_pages = 0
        at_bottom = []
        for page_id in list(win._page_names.keys()):
            win.show_page(page_id, animated=False)
            for _ in range(4):
                qapp.processEvents()
            bar = scroll.verticalScrollBar()
            if bar.value() > 0:
                scrolled_pages += 1
            # ⚠ 滚到底这一页（导航列表最后一项，本仓是 `about`）**结构性无解**：
            # 视口高 657 不是项高 43 的整数倍，滚到底时视口底边与内容底边对齐，
            # 顶边就必然落在某项中间。此时"上面还有内容"正需要提示，
            # 而"下面还有内容"已经不需要 —— 所以这是**对的那一头**。
            # 豁免它不是放宽判据：要消掉它得给侧栏内容底部加动态 padding，
            # 那是 X1/X2 的事，收益也远小于复杂度。
            if bar.value() >= bar.maximum():
                at_bottom.append(page_id)
                continue
            for btn in scroll.findChildren(QAbstractButton):
                if not btn.isVisible() or btn.height() <= 4:
                    continue
                y = btn.mapTo(viewport, QPoint(0, 0)).y()
                if y >= viewport.height() or y + btn.height() <= 0:
                    continue        # 完全在视口外 —— 正常
                if y < -2:
                    offenders.append(
                        f"{page_id}: 「{btn.text().strip()}」顶部被切 {-y}px")

        assert scrolled_pages >= 5, (
            f"只有 {scrolled_pages} 页滚动过 —— 前提不成立，这条判据量不到东西")
        assert len(at_bottom) <= 1, (
            f"滚到底的页不止一个：{at_bottom} —— 豁免范围只该是导航列表最后一项，"
            "多出来说明滚动逻辑又少滚了（RN-008 那一类）")
        assert not offenders, (
            f"侧栏顶部还有被切一半的导航项（{len(offenders)} 处）：{offenders[:6]} —— "
            "滚完要对齐到项边界（RN-060）。"
            f"⚠ 本条覆盖面：{len(win._page_names)} 页里除滚到底的 {at_bottom} 之外全部")
    finally:
        win.close()
        win.deleteLater()


def test_bench_covers_every_registered_page():
    """建页耗时的页面清单必须覆盖 `gui_widget` 注册的每一页。

    RN-061：`bench_page_build.PAGE_SPECS` 长期只有 **18** 项，缺 9 页 ——
    6 个设备页（那时连"能不能测"都被拒绝）+ fun_afterlife +
    audio_import_wizard + audio_task_panel（纯粹是加页时漏了）。
    ⇒ 建页耗时棘轮长期只盯 18/28 页，**而漏了不报错**。

    ⚠ `basic` 内联在 `gui_widget` 里、不是独立页类，按现状豁免；
    豁免只有这一项，写在断言里，不藏在名单里。
    """
    src = (REPO / "scripts" / "bench_page_build.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    specs = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "PAGE_SPECS"):
            specs = {el.elts[0].value for el in node.value.elts}
    assert specs, "找不到 PAGE_SPECS"

    gui = (REPO / "gui_widget.py").read_text(encoding="utf-8")
    # 页面注册处：`self.pages[page_id] = page` 之前的那一串 `elif page_id == "x"`
    registered = set(re.findall(r'page_id\s*==\s*[\'"]([a-z_]+)[\'"]', gui))
    registered -= {"basic"}
    assert len(registered) >= 20, (
        f"只识别出 {len(registered)} 个注册页，识别规则可能失效了：{sorted(registered)}")

    missing = sorted(registered - specs)
    assert not missing, (
        f"这些页没进建页耗时清单：{missing} —— 棘轮看不见它们（RN-061）。"
        f"⚠ 唯一豁免是内联的 `basic`")


def test_focus_audit_covers_every_page_with_a_class(qapp, monkeypatch):
    """焦点巡检必须覆盖每一个有独立页类的页，且不许有错位。

    RN-059：`tab_order_audit.SPAWNS_SUBPROCESS` 是**第 8 处**私有跳过名单
    （`{"flash", "viewmodel"}`）。探针在 `subprocess.Popen` 边界上实测：
    两页构造时子进程调用 **0 次** —— flash 只在 `flash_enabled` 为真时才起进程，
    而中和表已把它按成 False；viewmodel 同理。
    纳入后覆盖面 25/28 → **27/28**（只剩内联的 `basic`），
    ⭐ **当场就在 `viewmodel` 上报出一处 Tab 顺序错位**（RN-069）：
    走到第 5 个焦点跳到左下角的「保存设置到CFG」（y=487），
    再折回右上角的「循环按键」输入框（y=229）。

    这一条判据同时守两件事：覆盖面别缩、错位别回来。
    ⚠ 走子进程跑真脚本 —— 它的裁定是**进程级退出码**（RN-068：CI 上出现过
    「打印通过、退出码 1」，那个 1 来自退出链路不是判定结果）。
    """
    import subprocess
    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    # ⚠ 必须摘掉继承来的配置目录：pytest 进程里 conftest 已经设了一个**跨用例
    # 累积**的 CS2C_CONFIG_DIR，子进程继承它之后 `use_pristine_config_dir`
    # （非 force）会直接复用，于是巡检跑在一份脏配置上、报出与真实状态无关的错位。
    # 这就是 RN-031/RN-032 那个坑的第三次现身。
    env.pop("CS2C_CONFIG_DIR", None)
    env.pop("CS2C_LOG_DIR", None)
    proc = subprocess.run(
        [sys.executable, "scripts/tab_order_audit.py"],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "焦点巡检 覆盖面" in out, f"没拿到覆盖面报告：\n{out[-800:]}"
    import re as _re
    m = _re.search(r"覆盖面: (\d+)/(\d+) 个页面", out)
    assert m, out[-500:]
    covered, total = int(m.group(1)), int(m.group(2))
    assert covered >= total - 1, (
        f"焦点巡检覆盖面缩到 {covered}/{total} —— "
        "唯一允许不覆盖的是内联的 `basic`（RN-059）")
    # RN-068：认审计自己吐的那一行，不认退出码 —— 退出码在这条路上被
    # 退出期原生崩溃（0xC0000409）盖过，本机可复现，而判定本身是好的。
    m_rc = _re.search(r"RESULT rc=(-?\d+)", out)
    assert m_rc, (
        "巡检没吐 `RESULT rc=<n>` 那一行 —— 裁定必须由审计自己交付（RN-068）。"
        f"\n{out[-800:]}")
    assert m_rc.group(1) == "0", (
        f"焦点巡检报了错位（rc={m_rc.group(1)}）：\n{out[-1500:]}")
    if proc.returncode != 0:
        # 不判红，但要留痕：退出码和裁定不一致本身是一条值得查的事
        print(f"⚠ 退出码 {proc.returncode} 与裁定 rc=0 不一致 —— "
              "退出期崩溃/被洗，见 RN-068")
