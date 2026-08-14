# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R11 / UP-100 / UP-101：**审计的覆盖面只许增不许减**。

这个专项被同一种病咬过三次，一次比一次贵：

1. `UP-071`：`about` 页整页没有滚动区、内容压不下，审计一路绿灯——
   因为当时**根本没有纵向判据**。"某某维度全绿"要先确认那个维度有判据在看。
2. `UP-096`：排版审计默认跳过 5 个页面，历轮报告写的"22 页全绿"读起来像全覆盖，
   实际是 **22/27**，两个真缺陷（`UP-094`/`UP-095`）就藏在没覆盖的那 5 页里。
3. `UP-101`：焦点巡检只覆盖 **11/27**，报告只说"11 个页面全部为 0"。
   没覆盖的 16 页里，`preset_center` 和 `flash` 各藏着一处真缺陷。

三次的共同点是：**分母从来没有被写进报告，也从来没有判据盯着它**。
所以这里把分母本身变成被守护的对象——覆盖面的数字写死在这个文件里，
以后谁把某个页面从审计名单里拿掉，这条测试当场变红。

同样，紧凑模式（`UP-100`）这一档是 R11 才有的。它不是"另一种窗口尺寸"，
是用户点一下界面上的按钮就能进入的**另一套外壳**（860×640 固定 + 50px 顶栏 +
浮层侧边栏），内容可视区比完整模式少 160px。加了就不许再悄悄去掉。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_AUDIT = ROOT / "scripts" / "layout_overflow_audit.py"
FOCUS_AUDIT = ROOT / "scripts" / "tab_order_audit.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"

#: 应用的页面总数。分母，也是所有覆盖率的基准。
#: 开源裁剪把账号页整页移除，28 → 27；下面几个门槛跟着**同步下调 1**。
#: ⚠ 这不是把棘轮松掉：页面被物理删除时分母本来就该变小，
#: 松的是分母、不是覆盖率。改这几个数之前先确认页面是真没了。
TOTAL_PAGES = 27

#: 焦点巡检当前的默认覆盖面。`basic` 在 `gui_widget` 里内联建、没有独立类，
#: 进不了工厂表；另外 3 个构造即 spawn 子进程，默认档跳过。
#: **这个数只许增不许减。**
FOCUS_MIN_DEFAULT_PAGES = 21
#: `--include-unsafe` 时能覆盖到的页面数（26 = 27 − basic）。
FOCUS_MIN_ALL_PAGES = 26

#: 排版审计默认档的覆盖面（27 − 5 个构造即起设备的页面）。
LAYOUT_MIN_DEFAULT_PAGES = 21


def _module(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _argparse_options(path: Path) -> set[str]:
    """脚本用 `add_argument` 声明的所有**精确**选项名。"""
    out = set()
    for node in ast.walk(_module(path)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "add_argument"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.add(arg.value)
    return out


def _default_pages(path: Path) -> list[str]:
    """求出 `DEFAULT_PAGES` 的实际值。

    ⚠ 这个函数是回退验证逼出来的。判据的第一版自己拿 `PAGE_FACTORY` 减
    `SPAWNS_SUBPROCESS` **重新算**了一遍覆盖面，压根没读 `DEFAULT_PAGES`——
    于是把 `DEFAULT_PAGES` 换成写死的 11 项名单，判据依旧全绿。
    **判据必须读被守护的那个值本身，不能自己算一份等价的。**
    """
    tree = _module(path)
    ns: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        name = getattr(node.targets[0], "id", "")
        if name in ("PAGE_FACTORY", "SPAWNS_SUBPROCESS"):
            ns[name] = ast.literal_eval(node.value)
        elif name == "DEFAULT_PAGES":
            try:                       # 字面量名单
                return list(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                pass
            # 推导式：[pid for pid in PAGE_FACTORY if pid not in SPAWNS_SUBPROCESS]
            factory = ns.get("PAGE_FACTORY") or {}
            spawns = set(ns.get("SPAWNS_SUBPROCESS") or ())
            return [p for p in factory if p not in spawns]
    raise AssertionError(f"{path.name} 里找不到 DEFAULT_PAGES")


def _literal(path: Path, name: str):
    """读模块级常量的字面量值。走 AST 而不是 import——审计脚本一 import
    就会拉起 QApplication 和一堆产品代码，测试不该付这个代价。"""
    for node in _module(path).body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} 里找不到模块级常量 {name}")


# --------------------------------------------------------------- 焦点巡检


def test_focus_audit_total_pages_matches_the_app():
    assert _literal(FOCUS_AUDIT, "TOTAL_PAGES") == TOTAL_PAGES, (
        "焦点巡检的分母和应用真实页面数对不上了。分母错了，覆盖率就是假的——"
        "先去确认 gui_widget._page_names 到底有几个页面。"
    )


def test_focus_audit_default_coverage_never_shrinks():
    factory = _literal(FOCUS_AUDIT, "PAGE_FACTORY")
    default = _default_pages(FOCUS_AUDIT)
    assert len(default) >= FOCUS_MIN_DEFAULT_PAGES, (
        f"焦点巡检默认覆盖面从 {FOCUS_MIN_DEFAULT_PAGES} 掉到了 {len(default)}。"
        "UP-101 之前它只有 11 页，而没覆盖的页面里藏着真缺陷。只许增不许减。"
    )
    assert len(factory) >= FOCUS_MIN_ALL_PAGES, (
        f"能构造的页面从 {FOCUS_MIN_ALL_PAGES} 掉到了 {len(factory)}"
    )


def test_focus_audit_prints_its_denominator():
    """覆盖面必须是**每次都打印**的固定一行，不是只在有跳过时才说。

    UP-096 的教训：静默少测会被读成"全都覆盖了"。
    """
    src = FOCUS_AUDIT.read_text(encoding="utf-8")
    assert "覆盖面" in src and "TOTAL_PAGES" in src, "焦点巡检没有打印覆盖面"
    # 打印语句必须落在**无条件**执行的位置：把它塞进 `if missing:` 分支里，
    # 全覆盖那次就什么都不说，等于又回到了"读起来像全覆盖"。
    tree = _module(FOCUS_AUDIT)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    top_level_srcs = []
    for stmt in main.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.JoinedStr):
            top_level_srcs.append(ast.dump(stmt.value))
    assert any("覆盖面" in s for s in top_level_srcs), (
        "覆盖面那一行不在 main() 的顶层语句里——它必须无条件执行"
    )


# --------------------------------------------------------------- 排版审计


def test_layout_audit_default_coverage_never_shrinks():
    unsafe = set(_literal(LAYOUT_AUDIT, "UNSAFE_PAGES"))
    neutralizable = set(_literal(LAYOUT_AUDIT, "NEUTRALIZABLE"))
    skipped = unsafe - neutralizable
    covered = TOTAL_PAGES - len(skipped)
    assert covered >= LAYOUT_MIN_DEFAULT_PAGES, (
        f"排版审计默认覆盖面从 {LAYOUT_MIN_DEFAULT_PAGES} 掉到了 {covered}。"
        "UP-096：跳过的页面里藏过两个真缺陷。要加进 UNSAFE_PAGES，"
        "先想想能不能像 magnifier 那样用配置开关中和掉危险副作用。"
    )


# --------------------------------------------------------------- 紧凑模式


def test_layout_audit_has_a_compact_mode():
    """UP-100：紧凑模式这一档必须还在。

    它不是"再跑一个尺寸"，是另一套外壳：窗口固定 860×640、顶部多一条 50px 顶栏、
    侧边栏改浮层，内容可视区 590px vs 完整模式 750px。R0~R10 十一轮从没跑过这一档，
    一开就抓出三类真缺陷（preset_center 横向溢出 24/24 组合全中、
    audio_import_wizard 三个按钮打省略号、special_sound 两个页签纵向压扁）。
    """
    # ⚠ 这里原本是 `assert "--compact" in src`。回退验证当场判它假绿：
    # 把开关改名成 `--compact-DISABLED`，子串 `"--compact"` **照样命中**，判据全绿。
    # 又一次"别用子串判断"。改成 AST 取 argparse 的**精确选项名**。
    assert "--compact" in _argparse_options(LAYOUT_AUDIT), (
        "排版审计的 --compact 档没了（注意：改名也算没了）"
    )
    assert _literal(LAYOUT_AUDIT, "COMPACT_SIZE") == (860, 640), (
        "紧凑档尺寸要和 gui_widget 里的紧凑分支一致（setMinimumSize(860, 640) / "
        "_setup_window_size 的固定几何）"
    )
    tree = _module(LAYOUT_AUDIT)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    # `config.compact_mode` 必须在 MainWindow 构造**之前**赋值，否则窗口不会跟着变，
    # 量出来的可视区是假的（窗口尺寸像紧凑、外壳还是完整）。
    body = ast.dump(main)
    assert "compact_mode" in body, "main() 里没有设置 config.compact_mode"


def test_compact_size_matches_the_product_code():
    """审计里的 860×640 必须和产品代码里的那一份对得上。

    两处写死同一组数、又不互相校验，就是下一个"文档说的判据和代码里的判据
    是两回事"（R8d 踩过：文档写行容差 24px，代码里是 y//24 分桶）。
    """
    gui = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    assert re.search(r"setMinimumSize\(\s*860\s*,\s*640\s*\)", gui), (
        "gui_widget 里紧凑模式的最小尺寸变了，审计的 COMPACT_SIZE 要跟着改"
    )
    w, h = _literal(LAYOUT_AUDIT, "COMPACT_SIZE")
    assert (w, h) == (860, 640)


@pytest.mark.parametrize("needle", [
    "--compact",
    "tab_order_audit.py",
])
def test_ci_runs_the_new_gates(needle):
    """新判据不进 CI 就等于没有判据。

    R8a 的教训写在 README 里：修完没有回归守门，下一轮很容易把上一轮的修复
    悄悄改回去——本专项已经出现过"某维度全绿其实是根本没有判据"的情况。
    """
    assert CI.exists(), "找不到 CI 配置"
    assert needle in CI.read_text(encoding="utf-8"), (
        f"CI 里没有 {needle}——这一档没人守着"
    )
