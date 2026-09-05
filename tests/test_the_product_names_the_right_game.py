# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-204：屏幕上还在管这个游戏叫 **CS:GO**，而这是一个 CS2 工具。

## 立案说的和实测的

旧账 RN-204 只说了 `about` 一页（「文案仍写『CS:GO 游戏状态接口』，
CS2 玩家会误以为不兼容」）。分母自己算之后是**跨两页 4 处**：

| 位置 | 谁在说 | 说什么 |
|---|---|---|
| `pages/about_page.py:383` | 页面正文 | 「本工具通过监听 **CS:GO** 游戏状态接口 (GSI)」|
| `pages/advanced_page.py:860` | 选目录对话框标题 | 「选择 **CS:GO** 安装目录」|
| `pages/advanced_page.py:880` | `QMessageBox.information` | 「**CS:GO** 目录设置成功！」|
| `pages/advanced_page.py:886` | `QMessageBox.critical` | 「无效的 **CS:GO** 目录！…」|

⭐⭐ 而 `advanced` 是**已关档页** —— 又一次「立案说的是一页，实测是跨页」
（批 43 的 RN-503 同型）。⭐ **立案的数会过期，而它写小的时候比写大更难发现。**

⚠ 全站已经有一处**正确**的说法：`ui_help_panel.py` 里
「GSI（Game State Integration）是 **CS2** 提供的游戏状态接口」——
⇒ 这不是"还没决定叫什么"，是**同一件事有两个说法，而其中一个是错的**。

## ⚠⚠ 这条判据的分母有三个坑，全是踩出来的

1. **日志文案不算**（RN-057）：`logger.info(f"CS:GO 目录已设置: …")` 改了，
   搜日志的人就找不到了。日志里那 4 处**故意保留**。
2. ⭐⭐ **`critical` / `information` / `warning` 同时是 `logger` 和 `QMessageBox`
   的方法名。** 第一版分类器按方法名判，把 `QMessageBox.critical(...)`
   那个**模态框**判成了日志 —— 4 处漏成 3 处。
   ⇒ 必须看**接收者**：`self.logger.xxx` 才是日志，`QMessageBox.xxx` 是屏幕。
   ⭐ **一个名字同时属于两个完全不同的东西时，按名字分类必然出错。**
3. ⛔ **`game/csgo/cfg` 是磁盘上真实存在的目录名**（全仓 16 处路径字面量），
   一个字都不许改。CS2 的安装目录里那一层**确实还叫 `csgo`**。
"""
from __future__ import annotations

import ast
from pathlib import Path

from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent

#: 错的叫法。⚠ 只查这一个写法；`csgo`（小写、无冒号）是路径，不在此列。
WRONG_NAME = "CS:GO"

#: 不扫的目录。
#: ⚠⚠ `scripts` 是 2026-09-04 批 45 全量跑出来才补上的：
#:   `scripts/revert_verify.py` 里那条**为这一条缺陷写的回退断点**，
#:   描述文字里逐字引用了原文「本工具通过监听 **CS:GO** 游戏状态接口」——
#:   于是判据把**记录这条缺陷的那份记录**当成了缺陷本身。
#:   ⭐⭐ 同 RN-401：帮助面板那条通路不去注释，把「记录缺陷的注释」读成了给用户看的文案。
#:   ⭐ **一条判据扫得太宽，最先咬到的往往是写它的人留下的说明。**
#:   ⛔ 而 `scripts/` 本来就不该在分母里：它不画界面，里面的字没有用户会看见。
SKIP_DIRS = (".build", ".claude", "tests", "scripts", "build", "dist",
             "__pycache__", ".venv", "release", "docs")

#: 日志方法名。⚠ 只有挂在 `logger` 上才算 —— 见模块头第 2 条。
LOG_METHODS = frozenset({"info", "debug", "warning", "error", "exception", "critical"})


def _product_files() -> list[Path]:
    out = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if any(rel.startswith(d + "/") or f"/{d}/" in rel for d in SKIP_DIRS):
            continue
        out.append(path)
    return out


def _is_logger_call(call: ast.Call) -> bool:
    """这一次调用是往日志里写吗 —— **看接收者，不看方法名**。"""
    fn = call.func
    if not isinstance(fn, ast.Attribute) or fn.attr not in LOG_METHODS:
        return False
    owner = fn.value
    while isinstance(owner, ast.Attribute):
        if "logger" in owner.attr.lower() or "log" == owner.attr.lower():
            return True
        owner = owner.value
    if isinstance(owner, ast.Name) and "log" in owner.id.lower():
        return True
    return False


def _on_screen_hits(path: Path) -> list[tuple[int, str]]:
    """这个文件里**会画到屏幕上**且含错叫法的字符串字面量。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    if WRONG_NAME not in text:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:                                    # pragma: no cover
        return []

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))

    logged = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_logger_call(node):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    logged.add(id(sub))

    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if WRONG_NAME not in node.value:
            continue
        if id(node) in docstrings or id(node) in logged:
            continue
        hits.append((node.lineno, node.value[:60]))
    return sorted(hits)


def test_the_scan_can_tell_a_dialog_from_a_log_line():
    """⭐ 分类器自己的阳性对照：`QMessageBox.critical` 是屏幕，`logger.critical` 是日志。

    ⚠ 这条是被**第一版分类器判错**逼出来的：它按方法名判，
    于是把 `advanced_page.py:886` 那个 `QMessageBox.critical(...)` 模态框
    算成了日志，4 处漏成 3 处。
    ⭐⭐ **一个名字同时属于两个完全不同的东西时，按名字分类必然出错。**
    """
    src = (
        "from PySide6.QtWidgets import QMessageBox\n"
        "class P:\n"
        "    def f(self):\n"
        "        QMessageBox.critical(self, '错误', '屏幕上的 CS:GO 弹框')\n"
        "        self.logger.critical('日志里的 CS:GO 一行')\n"
    )
    tree = ast.parse(src)
    calls = must_scan([n for n in ast.walk(tree) if isinstance(n, ast.Call)],
                      "样例里的调用", least=2)
    verdict = {}
    for call in calls:
        fn = call.func
        if not isinstance(fn, ast.Attribute) or fn.attr != "critical":
            continue
        arg = next((a.value for a in ast.walk(call)
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    and "CS:GO" in a.value), None)
        if arg:
            verdict[arg] = _is_logger_call(call)
    assert verdict.get("屏幕上的 CS:GO 弹框") is False, (
        "分类器把 `QMessageBox.critical` 判成了日志 —— 那是一个模态框")
    assert verdict.get("日志里的 CS:GO 一行") is True, (
        "分类器认不出 `self.logger.critical` 是日志")


def test_no_screen_copy_still_calls_the_game_by_its_old_name():
    """RN-204：屏幕上不许再管这个游戏叫「CS:GO」。

    ⛔ 只管**画到屏幕上**的那些：`logger` 那几行故意保留（RN-057：
      改了搜日志的人会找不到），路径里的 `csgo` 一个字都不许动
      （CS2 的安装目录里那一层确实还叫 `csgo`）。
    """
    files = must_scan(_product_files(), "产品代码 *.py", least=50)
    offenders = {}
    for path in files:
        hits = _on_screen_hits(path)
        if hits:
            offenders[path.relative_to(REPO).as_posix()] = hits
    assert not offenders, (
        "这些**会画到屏幕上**的文案还在说「CS:GO」，而这是一个 CS2 工具：\n"
        + "\n".join(f"  {f}:{ln}  {t!r}" for f, hs in offenders.items() for ln, t in hs)
        + "\n⭐ 全站已经有一处正确的说法（`ui_help_panel`：「GSI…是 CS2 提供的"
          "游戏状态接口」）—— 这不是还没定叫什么，是同一件事有两个说法而其中一个是错的。"
        + "\n⛔ 别顺手改 `logger` 那几行，也别碰路径里的 `game/csgo/cfg`。"
    )


def test_the_log_lines_are_left_alone_on_purpose():
    """⭐ 反向守卫：日志里那几行**必须还在**。

    ⚠ 没有这一条，上面那条判据可以靠「把 `logger` 那几行也一起改掉」变绿 ——
    而那正是 RN-057 判过不许做的事（日志文案改了，搜日志的人找不到）。
    ⭐ **一条禁止某个词的判据，需要一条反向守卫说清它禁的是哪一片。**
    """
    kept = 0
    for path in must_scan(_product_files(), "产品代码 *.py", least=50):
        text = path.read_text(encoding="utf-8", errors="replace")
        if WRONG_NAME not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:                                # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_logger_call(node):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                            and WRONG_NAME in sub.value:
                        kept += 1
    # ⚠⚠ 第一版下界写的是 **3**，而实测就是 **4** —— 破坏验证当场判它假绿：
    #   改掉其中**一处**日志，`3 >= 3` 照样通过。
    # ⭐⭐ **一个比实际值低的下界，等于允许悄悄少掉几个** ——
    #   同批 41 那条：棘轮不收紧等于没有棘轮。
    assert kept >= 4, (
        f"日志里只剩 {kept} 处「CS:GO」（实测应有 4 处）—— "
        "多半是改屏幕文案时顺手把日志也改了。\n"
        "⭐ RN-057：日志文案是给开发看的，改了搜日志的人会找不到。"
    )
