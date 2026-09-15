# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-561：从仓根起走的扫描，必须排除 `.claude/`（那底下是整个仓的**副本**）。

`.claude/worktrees/<name>/` 是 git worktree 的落脚处 —— 会话工具会在那儿挂一份
**完整的仓副本**（2026-09-08 实测本机就有一份，属于另一个会话，`git worktree list`
里是活的）。任何从仓根起走的扫描如果不跳过它，**每个文件会被数两遍**。

⭐⭐ 而这类污染只朝**一个方向**失效：
   它让「有没有 X」永远答**有**、让「有几个」永远**偏大** ——
   也就是说，它专门破坏「我要证明某样东西**不存在**」这一类结论。
   2026-09-08 批 68 的死代码探针就是这么差点得出反向结论的：
   9 个零引用的名字被全判成「有外部引用」，而那些「引用」全是副本里的同一份定义。

## 为什么要有这条判据（而不是靠惯例）

实测：全仓 **11 处**从仓根起走的遍历里，**10 处已经排除了 `.claude`** ——
那不是巧合，是批 55 踩过一次之后一处处补上的（X1 契约面当时把每个名字数了两遍）。
⭐ **但没有任何东西看着这件事**：明天新写的第 12 处会照样漏，
   而它漏的方式和批 68 那支探针一模一样 —— 悄悄地、朝着「有」的方向。
⇒ 这条判据就是那个「看着的东西」。

## 分母（说清楚）

只管**从仓根起走**的（`os.walk(REPO)` / `REPO.rglob(...)` / `REPO.glob("**/...")`）。
走子目录的（`pages/`、`tests/`）结构上够不到根级的 `.claude/`，不进分母 ——
⚠ 第一版没分这个，数出 333 处「没排除」，那是个**填出来的数**
（⭐ 一个分母错了的普查不会空着，它会填满）。
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("tests", "scripts", "build_tools")

#: 这些名字在本仓里惯例上就是「仓根」。
ROOT_NAMES = {"REPO", "ROOT", "PROJECT_ROOT", "REPO_ROOT"}


def _is_repo_root(node: ast.AST) -> bool:
    """这个表达式是不是指向仓根。

    ⚠ `Path(__file__).parent…` 这种链子，**几个 `.parent` 才到仓根是数不出来的**
    （放在 `tests/` 里是两个，放在 `tests/x/` 里是三个）。
    ⇒ 一律当成「可能是仓根」。这是**故意往多了算**：
    ⭐ 这条判据要的是「有没有写排除」，多问一处的代价是多写一行排除，
      少问一处的代价是又一次把每个文件数两遍 —— **失效方向朝要查那边倒。**
    """
    if isinstance(node, ast.Name):
        return node.id in ROOT_NAMES or node.id == "__file__"
    if isinstance(node, ast.Constant):
        return node.value in (".", "./")
    if isinstance(node, ast.Call):                       # Path(x) / str(x)
        return any(_is_repo_root(a) for a in node.args)
    if isinstance(node, ast.Attribute):                  # x.parent(.parent)
        if node.attr in ("parent", "parents"):
            return _is_repo_root(node.value)
        return node.attr in ROOT_NAMES
    if isinstance(node, ast.Subscript):                  # x.parents[1]
        return _is_repo_root(node.value)
    return False


def _walk_target(call: ast.Call):
    """这个调用是不是一次目录遍历；是的话返回它的起点表达式。"""
    f = call.func
    if not isinstance(f, ast.Attribute):
        return None
    if f.attr == "walk" and call.args:
        return call.args[0]
    if f.attr == "rglob":
        return f.value
    if f.attr == "glob" and call.args:
        a = call.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str) and "**" in a.value:
            # ⚠ glob 的模式自己可能已经把范围限进子目录了（`build_tools/**/*.py`），
            #   那种够不到根级的 `.claude/`，不算「从根起走」。
            if not a.value.lstrip("./").startswith("**"):
                return None
            return f.value
    return None


def _root_walkers() -> list[tuple[Path, int, str]]:
    out = []
    for d in SCAN_DIRS:
        base = REPO / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if ".claude" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                src = io.open(path, encoding="utf-8", errors="ignore").read()
                tree = ast.parse(src)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    target = _walk_target(node)
                    if target is not None and _is_repo_root(target):
                        out.append((path, node.lineno, src))
    return out


def test_there_are_root_walkers_to_talk_about():
    """分母守卫：一处都找不到，说明识别器坏了，而下一条会安静地全绿。"""
    walkers = _root_walkers()
    must_scan(walkers, "从仓根起走的遍历点", least=5)


def test_every_root_walk_excludes_the_worktree_copies():
    """从仓根起走的扫描，源码里必须出现 `.claude` 这个排除。

    ⚠ 这条判的是**写法**不是行为：真去建一份 worktree 副本再数一遍，
    代价是几十秒 + 一次 `git worktree add`，而「有没有写排除」在源码里唯一且明确
    （同 RN-551 那条源码面判据的理由）。
    """
    offenders = []
    for path, lineno, src in _root_walkers():
        if ".claude" not in src:
            offenders.append(f"{path.relative_to(REPO).as_posix()}:{lineno}")
    assert not offenders, (
        "这些地方从仓根起走，却没有排除 `.claude/`：\n  " + "\n  ".join(offenders) +
        "\n⭐ `.claude/worktrees/` 底下是整个仓的一份副本 —— 不跳过它，"
        "每个文件会被数两遍，而这种污染**只朝「有」的方向失效**：\n"
        "  它专门破坏「我要证明某样东西不存在」这一类结论（RN-561）。")


def test_the_recogniser_actually_tells_root_walks_from_subdir_walks():
    """阳性 + 阴性对照：识别器分不清这两者的话，上面两条都没有意义。

    ⚠ 第一版没有这个区分，把走 `pages/` 的也算进来，
    数出 **333 处「没排除」** —— 一个填满了的、错的答案。
    """
    def targets(code: str):
        return [_is_repo_root(t) for t in
                (_walk_target(n) for n in ast.walk(ast.parse(code))
                 if isinstance(n, ast.Call))
                if t is not None]

    # 阳性：从仓根起走
    assert targets("import os\nfor a,b,c in os.walk(REPO): pass") == [True]
    assert targets("for p in REPO.rglob('*.py'): pass") == [True]
    assert targets("for p in Path(__file__).parent.parent.rglob('*.py'): pass") == [True]
    # 阴性：走子目录 / 限定了子路径的 glob
    assert targets("for p in (REPO / 'pages').rglob('*.py'): pass") == [False]
    assert targets("for p in PROJECT_ROOT.glob('build_tools/**/*.py'): pass") == []
    assert targets("import os\nfor a,b,c in os.walk(PAGES_DIR): pass") == [False]
