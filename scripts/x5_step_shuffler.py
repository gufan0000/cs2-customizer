# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X5 的**破坏验证**：把 18 步退出清理表整个倒过来，看有没有判据变红。

## 为什么这次不用 X4 那个「搬家」破坏器

X4 的契约是「第 N 行必须在第 M 行之前」，破坏它只能真的搬代码 ——
而那个破坏器**骗了我一次**（缩进决定作用域，4 格的 `try:` 把 8 格的回调体截断、
自己落回 `main`，`ast.parse` 说合法、脚本打印「💥」，跑的却是第三个程序）。
⇒ 教训是 **一个破坏脚本必须核对自己声称做到的那件事**。

X5 的契约是**一个列表字面量的元素顺序**。破坏它 = 重排元素，
不动任何一行代码的内容、不动任何缩进。⭐ 这比 X4 安全一个量级，
但**教训照抄**：`--verify` 一定要跑，见 `_postcondition`。

## 为什么是「整个倒过来」，不是「随机打乱」

X4 那一轮的读数之所以值钱，是因为**九条一次全违反**：
一次全量就能回答「这一族有没有人守」，而不是九次各回答一条。
倒序是这个列表上「一次全违反」的唯一确定性写法 ——
它同时违反每一条相邻约束，且**可复现**（随机打乱每次结果不同，
下一批想复跑同一个破坏都做不到）。

⚠ 倒序之后产品**不会崩**：每一步都裹在独立的 `try` 里，异常只记一行 warning。
⭐⭐ 这正是要量的那件事 —— **退出路径被设计成「吞掉一切失败」，
于是顺序违反在结构上无法表现为红色。**

用法：
    python scripts/x5_step_shuffler.py --apply     # 倒序
    python scripts/x5_step_shuffler.py --restore   # 还原
    python scripts/x5_step_shuffler.py --verify    # 只核对当前状态
"""
from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "gui_widget.py"
BACKUP = ROOT / "gui_widget.py.x5bak"


def _steps_list_node(tree: ast.AST):
    """定位 `MainWindow._run_shutdown_steps` 里的 `steps = [...]`。"""
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


def _names(src: str) -> list[str]:
    node = _steps_list_node(ast.parse(src))
    if node is None:
        return []
    out = []
    for elt in node.elts:
        if isinstance(elt, ast.Tuple) and isinstance(elt.elts[0], ast.Constant):
            out.append(elt.elts[0].value)
    return out


def _chunks(src: str):
    """把列表体切成 18 段，每段 = 「这一步的注释 + 这一步的元组」。

    ⭐ 按「上一个元素结束的下一行 → 本元素结束行」切，注释自然跟着它解释的那一步走。
    ⛔ 不按空行或缩进切：那两样在这张表里都不稳定（有的步骤三行、有的一行）。
    """
    lines = src.splitlines(keepends=True)
    node = _steps_list_node(ast.parse(src))
    if node is None:
        raise SystemExit("⛔ 找不到 steps 表")
    head_end = node.elts[0].lineno - 1          # `steps = [` 之后、第一个元素之前
    # 第一个元素的前导注释要归第一段，所以往回退到 `steps = [` 那一行
    open_line = node.lineno - 1
    chunks, prev_end = [], open_line + 1
    for elt in node.elts:
        chunks.append("".join(lines[prev_end:elt.end_lineno]))
        prev_end = elt.end_lineno
    head = "".join(lines[:open_line + 1])
    tail = "".join(lines[prev_end:])
    assert head_end >= open_line
    return head, chunks, tail


def _postcondition(src: str, before: list[str]) -> None:
    """核对我**声称**做到的那件事：18 个名字一个不少、顺序确实反了、文件仍可解析。

    ⛔ 这一段是 X4 那条教训的直接产物（RN-620 教训 2）：
    「判据没抓住」和「我根本没破坏成功」，**输出一模一样**。
    """
    ast.parse(src)                                   # ① 仍是合法 Python
    after = _names(src)
    if sorted(after) != sorted(before):              # ② 一步没丢、没多
        raise SystemExit(f"⛔ 破坏失败：步骤集合变了\n  前：{before}\n  后：{after}")
    if after != list(reversed(before)):              # ③ 顺序**确实**反了
        raise SystemExit(f"⛔ 破坏失败：顺序没反过来\n  后：{after}")
    print(f"✅ 后置核对通过：{len(after)} 步，顺序已倒置")
    print(f"   第 1 步：{before[0]!r} → {after[0]!r}")
    print(f"   末 1 步：{before[-1]!r} → {after[-1]!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if args.restore:
        if not BACKUP.exists():
            print("⛔ 没有备份，无需还原")
            return 1
        shutil.copy2(BACKUP, TARGET)
        BACKUP.unlink()
        print(f"✅ 已还原 {TARGET.name}（{len(_names(TARGET.read_text(encoding='utf-8')))} 步）")
        return 0

    src = TARGET.read_text(encoding="utf-8")
    names = _names(src)

    if args.verify:
        print(f"当前表 {len(names)} 步，顺序：")
        for i, n in enumerate(names, 1):
            print(f"  {i:>3} {n}")
        return 0

    if not args.apply:
        ap.print_help()
        return 2

    if BACKUP.exists():
        raise SystemExit("⛔ 已有备份 —— 上一轮没还原。先跑 --restore。")
    shutil.copy2(TARGET, BACKUP)

    head, chunks, tail = _chunks(src)
    if len(chunks) != len(names):
        raise SystemExit(f"⛔ 切分对不上：{len(chunks)} 段 vs {len(names)} 步")
    new_src = head + "".join(reversed(chunks)) + tail
    _postcondition(new_src, names)
    TARGET.write_text(new_src, encoding="utf-8", newline="")
    print(f"💥 已倒置 {TARGET.name} 的退出清理表。备份在 {BACKUP.name}")
    print("⚠ 跑完全量后务必 --restore。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
