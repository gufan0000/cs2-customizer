# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-623（批 87 · X5）：退出清理表的顺序是契约，而在此之前没有任何判据守它。

## 实测读数（`scripts/x5_step_shuffler.py --apply` + 全量）

把 `gui_widget._run_shutdown_steps` 的 **18 步整个倒过来**再跑全量：
**288/288 文件 · 3584 用例 · 0 红。**

结构原因比 X4 那条还要精确一点。X4 是「没有判据调用过 `main()`」；
这里 **有** 判据调用 `closeEvent`，而且调了两次 ——
`test_x1_link_behavior.py::test_closing_routes_by_policy_only_when_there_is_a_tray`，
两次都走 `ask` / `tray` 分支，**在 `_run_shutdown_steps()` 之前就 `return` 了**
（那支判据自己的文档写着「这里不真的关窗，只验路由」，它没做错任何事）。
⭐⭐⭐ **于是覆盖率表上写着「closeEvent 被测过」，而真正的退出一次都没跑过。**

## 这份判据钉两条契约，**而两条的证据强度不一样，不许混着说**

① **改配置的步骤必须排在「落盘配置」之前** —— 这一条**没有人写下来**，
   连注释都没有，全靠第 2 步碰巧排在第 17 步前面。
   ⭐ 它是**通用规则**而不是一对特例：以后任何人新加一步、只要它给
   `self.config.X` 赋值、只要它排在落盘之后，这支判据就红。
   证据：`scripts/x5_exit_retry_probe.py` 实测「改完不再落盘 ⇒ 磁盘上读不到」。

② **「退订配置重载广播」必须是第一步** —— 这一条**写在注释里**（UP-035：
   总线是模块级的、活得比窗口久，不退订的话它一直握着已析构窗口的方法引用）。
   ⚠ 本批**没有独立复现**那个 RuntimeError；这一条钉的是**作者写下来的那个决定**，
   不是我重新验过的因果。⭐ 两者的区别要留在文件里 ——
   否则下一个人会以为这一整份判据的每一条都被复现过。

⛔ 第 4 步「停止GSI服务器」与第 3 步「恢复GSI游戏内状态」看起来也像一对契约，
   **本批没钉** —— 读过之后发现 `_cleanup_gsi_handlers_on_close` 走的是
   `self.gsi_handlers` 字典，和 `gsi_server` 无关，**换序不一定有害**。
   ⭐ 没验出来的顺序不许写成判据，那只是把注释换了个地方放。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from _denominator import must_scan

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui_widget.py"

SAVE_STEP = "落盘配置"
FIRST_STEP = "退订配置重载广播"


# ---------------------------------------------------------------- 读表

def _steps_list(tree: ast.AST):
    for cls in ast.walk(tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == "MainWindow"):
            continue
        for fn in ast.walk(cls):
            if not (isinstance(fn, ast.FunctionDef) and fn.name == "_run_shutdown_steps"):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == "steps"
                        and isinstance(node.value, ast.List)):
                    return node.value
    return None


def _self_methods(expr_node) -> list[str]:
    return [n.attr for n in ast.walk(expr_node)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "self"]


def _method_node(tree: ast.AST, name: str):
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "MainWindow":
            for fn in ast.iter_child_nodes(cls):
                if isinstance(fn, ast.FunctionDef) and fn.name == name:
                    return fn
    return None


def _mutates_config(node) -> bool:
    """这一段代码会不会给 `self.config.X` 赋值。"""
    for sub in ast.walk(node):
        targets = []
        if isinstance(sub, ast.Assign):
            targets = sub.targets
        elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
            targets = [sub.target]
        for t in targets:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Attribute)
                    and t.value.attr == "config"
                    and isinstance(t.value.value, ast.Name) and t.value.value.id == "self"):
                return True
    return False


def _read_table(src: str):
    """返回 `[(序号, 步骤名, 是否改配置), ...]`，序号从 1 起、即执行顺序。

    ⭐ 这一层**不需要** X4 那套「AST 作用域 + 行号」：退出顺序是一个**列表字面量**，
    被一个平铺的 `for name, fn in steps:` 按下标跑掉 —— 文本顺序就是执行顺序，
    中间没有回调可以把两者拧反（RN-620 的那个陷阱在这里结构上不存在）。
    ⚠ 而「它仍然是一个平铺 for 循环」这件事本身要被钉住，见下面第一支判据。
    """
    tree = ast.parse(src)
    node = _steps_list(tree)
    assert node is not None, (
        "找不到 `MainWindow._run_shutdown_steps` 里的 `steps = [...]` —— "
        "退出顺序不再是一张表了，这份判据的全部前提都没了，先回来重写它。")
    out = []
    for i, elt in enumerate(node.elts, 1):
        assert isinstance(elt, ast.Tuple) and len(elt.elts) == 2, (
            f"第 {i} 个元素不是 `(名字, 可调用)` 二元组。")
        name = elt.elts[0].value
        bodies = [elt.elts[1]]
        for m in _self_methods(elt.elts[1]):
            fn = _method_node(tree, m)
            if fn is not None:
                bodies.append(fn)
        out.append((i, name, any(_mutates_config(b) for b in bodies)))
    return out


@pytest.fixture(scope="module")
def src() -> str:
    return GUI.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 前提

def test_the_exit_steps_are_still_a_flat_table_run_in_order(src):
    """这份判据的前提：表是数据，且被一个**平铺的** for 循环按序跑掉。

    ⛔ 有人把它改成「按条件跳步」「并发跑」「按 dict 排序」之后，
    「第 N 步在第 M 步之前」就不再等于「先跑 N 后跑 M」——
    而这份判据的每一条断言都建立在那个等号上。
    """
    tree = ast.parse(src)
    fn = _method_node(tree, "_run_shutdown_steps")
    assert fn is not None, "`_run_shutdown_steps` 没了。"
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
    assert len(loops) == 1, (
        f"`_run_shutdown_steps` 里有 {len(loops)} 个 for 循环 —— "
        "本判据假设只有一个、且它就是按序跑表的那个。")
    assert isinstance(loops[0].iter, ast.Name) and loops[0].iter.id == "steps", (
        "那个 for 循环遍历的不是 `steps` 了。")
    assert not [n for n in ast.walk(loops[0])
                if isinstance(n, ast.Call) and "Thread" in ast.unparse(n.func)], (
        "退出步骤开始并发跑了 —— 顺序契约当场失效，这份判据全部作废，回来重写。")


def test_the_table_has_at_least_the_two_steps_this_file_pins(src):
    names = [n for _, n, _ in _read_table(src)]
    for want in (FIRST_STEP, SAVE_STEP):
        assert want in names, (
            f"退出表里没有「{want}」这一步了 —— 它被改名或删掉了，"
            f"而本文件的契约是按名字认的。当前的表：{names}")


# ---------------------------------------------------------------- 契约 ①

def test_every_step_that_changes_the_config_runs_before_it_is_saved(src):
    """⭐ 没有人写下来的那条契约：**改配置的步骤必须排在「落盘配置」之前。**

    第 2 步「保存音乐进度」把播放位置写进 `self.config`，而它**只**靠第 17 步
    「落盘配置」写出去。⇒ 排在落盘之后的任何一次配置改动都是**静默丢掉**：
    用户听到一半退出，下次进来从头开始，界面上一个字都不会说。

    ⭐⭐ 这一条故意写成**通用规则**而不是「第 2 步要在第 17 步前」：
    以后新加的步骤只要给 `self.config.X` 赋值又排在落盘之后，这里就红。
    """
    table = _read_table(src)
    save_idx = next(i for i, n, _ in table if n == SAVE_STEP)
    # ⛔⛔ 分母先钉住，再查违规 —— 否则「没有任何步骤改配置」会让这条规则**恒绿**，
    #    而那正是它失效的样子（RN-615：从被测对象推出来的分母，抓不住对象被拆掉）。
    #    ⚠ 这不是为了判据好看：唯一那个改配置的步骤就是「保存音乐进度」，
    #    它一旦消失，用户听到一半退出、下次从头开始，**界面上一个字都不会说**。
    movers = [(i, n) for i, n, mut in table if mut]
    assert movers, (
        "退出清理表里**一步都不改配置**了 —— 这条规则从此恒绿，等于没有。"
        "要么是「保存音乐进度」那一步被拆了（那本身就是缺陷），"
        "要么是有人把配置改动搬去了别处（那就回来把这份判据改对）。")

    late = [(i, n) for i, n, mut in table if mut and i > save_idx]
    assert not late, (
        f"这些步骤改了配置，却排在「{SAVE_STEP}」（第 {save_idx} 步）之后："
        f"{late} —— 它们改的东西**不会落盘**，用户那一次改动静默消失。"
        "要么把它们挪到落盘之前，要么在它们之后再落一次盘。")


# ---------------------------------------------------------------- 契约 ②

def test_unsubscribing_the_config_reload_bus_is_the_first_step(src):
    """UP-035 写下来的那条：总线活得比窗口久，不先退订就会握着死对象。

    ⚠ **本批没有独立复现**那个 RuntimeError（见模块文档）。
    这一条钉的是作者写下来的那个决定，不是我重新验过的因果。
    """
    table = _read_table(src)
    idx = next(i for i, n, _ in table if n == FIRST_STEP)
    assert idx == 1, (
        f"「{FIRST_STEP}」现在排第 {idx} 步。UP-035 的理由就写在它上面那行注释里："
        "配置重载总线是模块级的、活得比窗口久，退订晚一步，"
        "中间任何一次 apply_bundle() 都会打在已析构的窗口上。")


# ---------------------------------------------------------------- 反面对照

def _reversed_source(src: str) -> str:
    """把表倒过来（和 `scripts/x5_step_shuffler.py` 同一个做法，只在内存里）。"""
    lines = src.splitlines(keepends=True)
    node = _steps_list(ast.parse(src))
    open_line = node.lineno - 1
    chunks, prev = [], open_line + 1
    for elt in node.elts:
        chunks.append("".join(lines[prev:elt.end_lineno]))
        prev = elt.end_lineno
    return "".join(lines[:open_line + 1]) + "".join(reversed(chunks)) + "".join(lines[prev:])


def test_the_ruler_actually_catches_a_reversed_table(src):
    """⛔ 没有这一支，上面两条「绿」既可能是「顺序对」，也可能是**尺子量不出来**。

    实测依据：整张表倒过来跑全量是 **288/288 · 0 红** ——
    ⭐⭐⭐ 而那个读数唯一能证明的，是**当时没有一把尺子在量这件事**。
    """
    bad = _reversed_source(src)
    ast.parse(bad)                       # 倒过来仍是合法 Python —— 这正是它危险的原因
    assert [n for _, n, _ in _read_table(bad)] == \
           [n for _, n, _ in reversed(_read_table(src))], (
        "反面对照自己没构造成功 —— 那么下面那句『它分得开』也不算数。")

    def verdict(text):
        table = _read_table(text)
        save_idx = next(i for i, n, _ in table if n == SAVE_STEP)
        first_idx = next(i for i, n, _ in table if n == FIRST_STEP)
        return (not [1 for i, _, mut in table if mut and i > save_idx], first_idx == 1)

    # ⛔ 这里断言的是「两种顺序**结论不同**」，不是「倒过来一定红」。
    #    第一版写的是后者，而它在**磁盘上的表已经被破坏脚本倒过**的那一刻
    #    自己变成红的（倒了两次 = 原序），报出来的话却是「这把尺子是坏的」——
    #    ⭐ 一句在特定前提下才成立的断言，失败时给出的是一条误导性的结论。
    assert verdict(src) != verdict(bad), (
        f"正序与倒序在这把尺子下给出**同一个结论** {verdict(src)} —— "
        "那么它对顺序根本不敏感，上面两条绿不说明任何事。")
    # ⛔ 这里**不再**顺手断言「磁盘上这一版是合规的」：那句话上面两支判据已经在说，
    #    而写在这里会让本支在表被破坏时也跟着红 ——
    #    ⭐ 反面对照必须对「当前这一版对不对」保持中立，否则它量的就不是尺子了。


def test_no_test_has_ever_run_the_real_exit_path(src):
    """⭐⭐⭐ 结构原因：**有判据调了 `closeEvent`，而它在真正的退出之前就 return 了。**

    这一支**红了是好消息** —— 说明终于有人把整条退出路径跑起来了。
    真到那天，回来把这支删掉，换成那条真跑的判据。

    ⚠ 判定用的是「`_run_shutdown_steps(` 出现在 tests/ 的任何一处」，
    这是**下界**（RN-620）：出现 ≠ 被执行。
    它唯一的用途是给「该不该再写端到端退出判据」一个可比的数。
    """
    scanned = [py for py in sorted((ROOT / "tests").glob("*.py"))
               if py.name != Path(__file__).name]
    must_scan(scanned, "tests/ 下的判据文件", least=200)

    hits = [py.name for py in scanned
            if "_run_shutdown_steps(" in py.read_text(encoding="utf-8", errors="replace")]
    assert not hits, (
        f"有判据开始真跑退出清理表了：{hits}。这是好事 —— "
        "回到本文件，把这支换成对那条真实路径的断言。")
