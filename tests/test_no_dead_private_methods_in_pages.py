# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""`pages/` 里不许留下**从来没人调用**的私有方法，且总数只许减不许增。

**来源**：翻新工程 M3 开 `crosshair` 页时顺手扫出来的 —— 这一页自己定义了
`_create_badge_label` / `_set_badge_state`，而页顶部早就 `from pages.audio_status_badge
import create_badge_label`，真正在用的是共享那份。同样的残留在 **9 个页面文件**里都有，
其中 5 页**已经关档**。

⭐ 这是「关档 ≠ 这页没问题」的又一个实例：人眼逐页看必然漏，只有判据扫得干净。

---

## 这条判据的要害全在**语料**和**调用面**上，两个都踩过

### ① 语料：`.build/` 里有整个产品的打包暂存副本
第一版用 `pathlib.rglob('*.py')` 扫全盘，把 `.build/release-*/stage/` 下的**旧副本**
一起算进去了。副本里的类名与真身同名，于是「这个类在哪个文件」被最后扫到的那份覆盖，
调用面整个算歪。⇒ 语料必须是 **git 跟踪 + 未跟踪**（后者是 RN-112 的教训：
`ls-files` 看不见还没 `add` 的新文件，而新文件恰恰最可能是那个调用者）。

### ② 调用面：基类的私有方法是被**子类**调用的
第二版按"本文件"算调用面，于是 `SoundPageBase` 的 5 个方法（含 **91 行**的
`_build_sound_page_ui`）全被判成死的 —— 它们其实被 4 个子类页调着。
差一点删掉活代码。⇒ 调用面 = **本文件 + 所有（传递）子类所在文件 + 全仓字符串面**。

⇒ 一句话：**"没人用"这个结论的可信度，等于你那个"所有人"的定义有多准。**
"""
from __future__ import annotations

import ast
import collections
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "pages"

#: Qt 的回调是框架调的，源码里没有调用点，不算死码。
QT_OVERRIDES = {
    "paintEvent", "mousePressEvent", "mouseMoveEvent", "mouseReleaseEvent",
    "resizeEvent", "showEvent", "hideEvent", "closeEvent", "keyPressEvent",
    "wheelEvent", "eventFilter", "dragEnterEvent", "dropEvent", "enterEvent",
    "leaveEvent", "sizeHint", "__init__",
}

#: 棘轮：当前还剩多少个。**只许调小**。
#: 12 → 10：M3 开 crosshair 页时清掉本页那两个。
#: 10 → 8：M3 开 kill_icon 页时清掉那两个「老接口」（`_preview_settings` /
#:         `_test_kill_icon`，全仓零调用，功能早已被现在的试播路径取代）。
#: 剩下的 8 个分布在 advanced / music / utility / viewmodel 四页，
#: 归各自页面的档案 —— 本工程的纪律是**只在开档的页里动刀**。
MAX_REMAINING = 8


def _corpus() -> list[Path]:
    """语料 = git 跟踪 + 未跟踪（见模块说明 ①）。"""
    out: list[str] = []
    for args in (
        ["git", "ls-files", "-z", "*.py"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "*.py"],
    ):
        res = subprocess.run(args, cwd=ROOT, capture_output=True)
        out += [x for x in res.stdout.decode("utf-8").split("\0") if x]
    return [ROOT / x for x in out]


def find_dead_private_methods() -> list[tuple[str, str, str, int]]:
    trees: dict[Path, ast.Module] = {}
    calls: dict[Path, collections.Counter] = {}
    strings: collections.Counter = collections.Counter()
    class_file: dict[str, Path] = {}
    bases: dict[str, list[str]] = collections.defaultdict(list)

    for p in _corpus():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        trees[p] = tree
        calls[p] = collections.Counter(
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute))
        # ⚠ 字符串引用面**只取产品代码**，不含 tests/。
        # 它的用途是逮住动态派发（getattr / 按名字连信号），而那只会发生在产品里。
        # 把测试也算进来的话，**判据在文档或断言里写下那个方法名，就等于把它救活**——
        # 这个自指陷阱今天连踩两次：先是空转守卫的探针名，后是反面守卫里
        # 那句 `("sound_page_base.py", "_build_sound_page_ui") not in dead`。
        # ⇒ 拿全仓文本当证据的判据，**判据自己也在语料里**。
        is_test = p.parent.name == "tests" or p.name.startswith("test_")
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if not is_test:
                    strings[n.value] += 1
            elif isinstance(n, ast.ClassDef):
                class_file[n.name] = p
                bases[n.name] += [
                    b.id if isinstance(b, ast.Name)
                    else (b.attr if isinstance(b, ast.Attribute) else "")
                    for b in n.bases
                ]

    children: dict[str, set[str]] = collections.defaultdict(set)
    for cls, bs in bases.items():
        for b in bs:
            if b:
                children[b].add(cls)

    def _closure(cls: str, edges) -> set[str]:
        seen: set[str] = set()
        stack = list(edges(cls))
        while stack:
            d = stack.pop()
            if d not in seen:
                seen.add(d)
                stack += list(edges(d))
        return seen

    def descendants(cls: str) -> set[str]:
        return _closure(cls, lambda c: children.get(c, ()))

    def ancestors(cls: str) -> set[str]:
        """祖先也要算进调用面：**基类调钩子、子类覆写**是这套页面的主要结构。

        `SoundPageBase` 里写着 `self._style_options_for(...)`，实现在
        `KillSoundPage` 等 4 个子类里。只往下看的话，这些覆写方法会被整批
        判成死码（实测一下子多出 8 个假阳性）。
        """
        return _closure(cls, lambda c: [b for b in bases.get(c, ()) if b])

    dead: list[tuple[str, str, str, int]] = []
    for p in sorted(PAGES.glob("*.py")):
        tree = trees.get(p)
        if tree is None:
            continue
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            related = descendants(cls.name) | ancestors(cls.name)
            scope = {p} | {class_file[d] for d in related if d in class_file}
            for f in cls.body:
                if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not f.name.startswith("_") or f.name in QT_OVERRIDES:
                    continue
                n_calls = sum(calls[q][f.name] for q in scope if q in calls)
                if n_calls == 0 and strings[f.name] == 0:
                    dead.append((p.name, cls.name, f.name,
                                 (f.end_lineno or f.lineno) - f.lineno + 1))
    return dead


def test_dead_private_method_count_only_shrinks():
    dead = find_dead_private_methods()
    listing = "\n".join(f"  {a} · {b}.{c}  {d} 行" for a, b, c, d in dead)
    assert len(dead) <= MAX_REMAINING, (
        f"pages/ 里从没人调用的私有方法涨到 {len(dead)} 个（上限 {MAX_REMAINING}）：\n"
        f"{listing}\n"
        "新写的页别再自己复制一份共享工具；确实要留的，说明它为什么留着。"
    )


def test_the_page_being_renovated_is_clean():
    """已经翻新过的页必须是 0 —— 棘轮只保证不涨，不保证清过的页不复发。"""
    cleaned = {"crosshair_page.py", "kill_icon_page.py"}
    dead = [d for d in find_dead_private_methods() if d[0] in cleaned]
    assert not dead, f"已清理过的页又长出死方法：{dead}"


def test_the_scan_actually_sees_a_dead_method(tmp_path, monkeypatch):
    """空转守卫：往 pages/ 放一个真的没人调的私有方法，扫描必须认出来。

    ⚠ 没有这条，`_corpus()` 或调用面写错会让扫描**恒返回空**，
    上面两条判据就永远绿 —— 那正是这类"数出来的判据"最常见的死法。

    ⚠⚠ 探针方法名**必须在运行时拼出来**，不许在本文件里以完整字面量出现：
    第一版直接写 `assert "_never_called_probe_method" in names` 就红了 ——
    扫描会把**全仓字符串面**算作引用，而这条断言里的那个字面量就在全仓里，
    于是探针被自己的断言"救活"，判据报"看不见"。
    ⇒ **判据自己也是被扫的语料。** 凡是拿全仓文本当证据的判据，
      都要先问一句：我写下的这句话会不会变成它要找的证据？
    """
    name = "_never" + "_called" + "_probe" + "_method"      # 见上面第二条 ⚠
    probe = PAGES / "_dead_probe_tmp_page.py"
    assert not probe.exists(), f"探针文件已存在，先删掉：{probe}"
    probe.write_text(f"class ProbePage:\n    def {name}(self):\n        return 1\n",
                     encoding="utf-8")
    try:
        names = {c for _, _, c, _ in find_dead_private_methods()}
        assert name in names, "扫描看不见刚放进去的死方法 —— 它现在什么都逮不住"
    finally:
        probe.unlink()


def test_a_method_called_only_by_a_subclass_is_not_dead():
    """反面守卫：**基类的私有方法被子类调用**时不许判死。

    这条是拿一次差点删掉 91 行活代码换来的：按"本文件"算调用面时，
    `SoundPageBase._build_sound_page_ui` 被判成死的，而它有 4 个子类页在调。
    """
    dead = {(a, c) for a, _, c, _ in find_dead_private_methods()}
    assert ("sound_page_base.py", "_build_sound_page_ui") not in dead, (
        "调用面又缩回本文件了 —— 基类方法会被整批误杀")


def test_a_hook_overridden_in_a_subclass_is_not_dead():
    """反面守卫（另一个方向）：**基类调钩子、子类覆写**时不许判死。

    这是同一天踩到的第二个方向：把 tests/ 从字符串面里摘掉之后，
    `_style_options_for` / `_test_weapon` 这类**在 `SoundPageBase` 里被调用、
    实现落在 4 个子类页**的钩子一下子多出 8 个假阳性 —— 因为调用点在**祖先**文件里，
    而当时的调用面只往下看。
    ⇒ 继承链两个方向都要走：**子类会调基类的私有方法，基类也会调子类覆写的钩子。**
    """
    dead = {(a, c) for a, _, c, _ in find_dead_private_methods()}
    for page in ("kill_sound_page.py", "kill_voice_page.py",
                 "reload_sound_page.py", "switch_weapon_page.py"):
        assert (page, "_style_options_for") not in dead, (
            f"{page} 的钩子被判成死码 —— 调用面漏了祖先那一层")
