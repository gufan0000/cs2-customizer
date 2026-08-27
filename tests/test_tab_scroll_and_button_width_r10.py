# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R10（UP-095 / UP-094 / UP-081）：页签要能滚，按钮宽度不许写死。

**这两类缺陷的共同点是"不报错"**：
- 页签装不下时 Qt **不会自己长出滚动条**，而是把控件压扁——实拍到的后果是
  卡片标题与正文字形直接重叠、不可读（UP-095 的 flash 页就是这样）。
  而排版审计给出的数字是"最小高超出可视区 279px"，读起来像"滚一下就好"。
- 按钮写死宽度时，文案放不下就打省略号，也不会报错。用户看到的是
  「保存FPS设...」，没人会意识到那是个缺陷。

**为什么这两条以前一直绿**：flash / kill_icon 属于"构造即打扰前台"的 5 个页面，
排版审计默认跳过它们（UP-096）。历轮报告里的"22 页全绿"其实是 22/27。

判据的分工：
- 排版审计（`--include-unsafe`，438 组合）量的是**真实截断与裁切**，是主判据；
- 本文件是**源码层的防回潮**——审计要跑真窗口、几十秒，且默认不覆盖这 5 页，
  而这里在单元测试里就能拦住"又把滚动区去掉""又写死一个宽度"。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAGES = REPO / "pages"


def _constructs(node: ast.AST, name: str) -> bool:
    """节点子树里有没有**真正构造** `name`（AST 找 Call，不看文本）。

    R9 回归里这个教训出现了四次：用子串判断"调用/构造"迟早会被
    注释、import 行或字符串常量骗到。
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        fn = sub.func
        if isinstance(fn, ast.Name) and fn.id == name:
            return True
        if isinstance(fn, ast.Attribute) and fn.attr == name:
            return True
    return False


#: 页签内容确实没有自己的滚动区，但**整页级**有一个把它包住了。必须写明理由。
#: 空理由 = 不算豁免（见 test_tab_scroll_exemptions_carry_a_reason）。
PAGE_LEVEL_SCROLL = {
    "magnifier_page.py": (
        "整页级滚动区在 magnifier_page.py:383（main_layout.addWidget(scroll, 1)），"
        "武器页签是它内部的一小块复选框网格；排版审计 438 组合实测无纵向裁切"
    ),
}


def _methods(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    return {
        n.name: n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
    }


def _scroll_in_chain(node: ast.FunctionDef, methods: dict[str, ast.FunctionDef],
                     seen: set[str] | None = None) -> bool:
    """这个方法**或它委托出去的 `self.xxx()`** 里有没有构造 QScrollArea。

    ⚠ 必须跟进委托，否则全是误报：`sound_page_base._build_sound_page_ui` 的
    滚动区建在 `_create_category_tab()` 里、`gun_sound_page._init_ui` 的建在
    `_create_weapon_tab()` 里。R10 第一版判据没跟进，一上来报了 3 个假阳性——
    **判据第一次跑红，先查判据的前提成不成立**。
    """
    seen = seen if seen is not None else set()
    if node.name in seen:
        return False
    seen.add(node.name)
    if _constructs(node, "QScrollArea"):
        return True
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)):
            continue
        target = sub.func.value
        if not (isinstance(target, ast.Name) and target.id == "self"):
            continue
        callee = methods.get(sub.func.attr)
        if callee is not None and _scroll_in_chain(callee, methods, seen):
            return True
    return False


def _tab_builders() -> list[tuple[str, str, bool]]:
    """所有"建页签"的方法：(文件名, 方法名, 这条链上是否有 QScrollArea)。

    认定标准是方法体里真的调了 `addTab(...)`——只按方法名叫 `_create_*_tab`
    来认会漏掉 `_init_ui` 里内联建页签的那几个。
    """
    out = []
    for path in sorted(PAGES.glob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover
            continue
        methods = _methods(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            adds_tab = any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and c.func.attr == "addTab"
                for c in ast.walk(node)
            )
            if not adds_tab:
                continue
            has = _scroll_in_chain(node, methods) or path.name in PAGE_LEVEL_SCROLL
            out.append((path.name, node.name, has))
    return out


def test_tab_scroll_exemptions_carry_a_reason():
    """豁免要有代价：没写理由就不算豁免，名单才不会无声变长。"""
    for name, reason in PAGE_LEVEL_SCROLL.items():
        assert (PAGES / name).exists(), f"豁免名单里的 {name} 已不存在，请删掉这条"
        assert reason and len(reason.strip()) >= 20, f"{name} 的豁免理由太敷衍：{reason!r}"


def test_the_tab_builder_detector_finds_them():
    """自检：探测器失灵的话，下面那条核心判据就是空转。"""
    builders = _tab_builders()
    assert len(builders) >= 10, f"只找到 {len(builders)} 个建页签方法，探测器多半失灵了"


def test_every_tab_is_scrollable():
    """核心判据：**每个页签都要有滚动区，无豁免**。

    R10 补完最后一个（`flash_page._create_preview_tab`）之后是 12/12，
    所以这里不挂豁免名单——豁免名单会慢慢变长，而"全都要有"是个能守住的线。

    回退验证：把 flash 或 special_sound 任一页签的 QScrollArea 去掉，本条立刻变红。
    """
    missing = [f"{f}::{m}" for f, m, has in _tab_builders() if not has]
    assert not missing, (
        "这些页签没有滚动区，内容一旦超出可视区，Qt 会把控件压扁（字形重叠），"
        "而不是长出滚动条：\n  " + "\n  ".join(missing)
        + "\n修法：套一层 QScrollArea(widgetResizable=True)，"
          "参考 pages/flash_page.py 的 _create_basic_tab。"
    )


#: UP-094 实测会被打省略号的两个按钮。写死宽度 + 中文文案 + 字号缩放 = 截断。
#: 全仓还有 21 处 `setFixedWidth` 用在按钮上，目前都有余量，
#: 由排版审计（6 个主题×字号组合逐个量真实截断）看着，不在这里一刀切。
TIGHT_BUTTONS = {
    # KI-7 把「保存播放设置」搬进了素材工坊（dialogs/kill_icon_workshop.py），
    # 这份名单只扫 pages/ 下的文件，所以那一条跟着挪走了。
    # 工坊那一侧由 test_kill_icon_workshop_ki7.py::test_the_dialog_fits_its_own_minimum_size
    # 盯着（口径不同：那条量的是整窗放不放得下，比"某个按钮有没有被写死宽度"更硬）。
    "kill_icon_page.py": ["重置位置和大小"],
}


def _fixed_width_button_texts(fname: str) -> set[str]:
    """这个文件里，哪些 QPushButton 被 setFixedWidth 钉死了宽度。"""
    src = (PAGES / fname).read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 名字 → 按钮文案
    texts: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        fn = node.value.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name != "QPushButton" or not node.value.args:
            continue
        arg = node.value.args[0]
        label = arg.value if isinstance(arg, ast.Constant) else ""
        for tgt in node.targets:
            key = tgt.id if isinstance(tgt, ast.Name) else getattr(tgt, "attr", None)
            if key:
                texts[key] = label

    pinned = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "setFixedWidth":
            continue
        obj = node.func.value
        key = obj.id if isinstance(obj, ast.Name) else getattr(obj, "attr", None)
        if key in texts:
            pinned.add(texts[key])
    return pinned


@pytest.mark.parametrize("fname", sorted(TIGHT_BUTTONS))
def test_known_tight_buttons_are_not_width_pinned(fname):
    """这两个按钮不许再用 `setFixedWidth`——用 `setMinimumWidth` 让它能长。

    `setFixedWidth` 把 min 和 max 一起钉死，字号放大时按钮不跟着长，文案就被
    打省略号。改成下限之后：文字装得下时宽度与原来一模一样（sizeHint 更小），
    装不下时才长——**默认状态下观感零变化**。

    `保存FPS设置` 还有个额外理由：有未保存改动时文案会变成「保存FPS设置 *」，
    比原文案更宽，写死的 120px 在那个状态下更不够。

    回退验证：把任一个改回 setFixedWidth，本条立刻变红。
    """
    pinned = _fixed_width_button_texts(fname)
    offenders = [t for t in TIGHT_BUTTONS[fname] if t in pinned]
    assert not offenders, (
        f"{fname} 的这些按钮又被写死宽度了，字号放大时会被打省略号：{offenders}\n"
        "改用 setMinimumWidth。"
    )


# ==================================================== 编码损坏（UP-098 / UP-099）

#: 判据只认**私有区字符**（U+E000–U+F8FF）：GBK 解码撞上无法映射的字节时留下的
#: 痕迹，本仓库的正常内容里不该出现任何一个，所以它是个零误报的信号。
#:
#: ⚠ 两条走过弯路的记录：
#: (1) 一开始还加了"乱码高频字 + 后跟 2 个汉字"的启发式，结果把
#:     pypinyin/phrases_dict.json 里的「民淳俗厚」「涓滴不剩」当成乱码——
#:     那是真成语。第二版换转义码点又写错了字符，直接把 README 全报成损坏。
#:     **自造的字符级启发式，不如一个精确信号。**
#: (2) 正则里用 \uXXXX 转义写，别把字符直接敲进去：私有区字符不可见，
#:     直接写进来会让本文件自己被判成"损坏"。
#:
#: 代价说清楚：**不带私有区字符的乱码本条查不出来**（kill_icon_player.py
#: 那三行就属于这种，R10 已单独修掉）。这条守的是"大面积损坏"，不是全部。
_PUA = re.compile("[\ue000-\uf8ff]")

#: 只在这个目录下允许存在损坏（UP-099：整个教程内容库，42 个文件，
#: 90% 的中文不可自动还原，处置待用户决定）。别的地方一个都不许有。
# ⭐⭐ 2026-08-26（RN-199）：**这条判据现在是无条件的。**
#
# 原来这里有两样东西：
#   · `_CORRUPTION_ALLOWED_UNDER = docs/tutorial/` —— 42 个乱码教程文件的豁免范围；
#   · `_KNOWN_BROKEN` —— 那两个语法都不合法的脚本。
# 两样都是**同一次基线导入事故**的产物，而整条教程流水线已随 RN-199 删除
# （247 个被跟踪文件 + 6 支只读它的脚本；git 历史里留着，`3b5301e` 是它唯一那次提交）。
#
# ⭐ **删掉一条死线路的净收益，往往是某条判据的例外跟着消失。**
#   在此之前这条判据说的是「除了那一片以外没有乱码」；现在说的是「没有乱码」。
# ⚠ 别再往回加豁免：真出现新的乱码文件，该修的是那个文件。

#: 不扫的目录：打包产物与第三方数据。
#: ⚠ `pypinyin/phrases_dict.json` 是**误报源**——「民淳俗厚」「涓滴不剩」
#: 是真成语，会命中上面的正则。第三方词库不该由本判据管。
_SKIP_DIRS = {
    ".git", "__pycache__", ".build", "node_modules", ".pytest_cache",
    "artifacts", "release", "dist", "build",
    # `.claude/worktrees/` 是助手会话建的临时 git worktree（`.git/info/exclude`
    # 里已排除，不入库）。它里面是**整个仓库的另一份拷贝**，扫到的话既会
    # 重复计数、又会把那份拷贝的历史问题算到当前工作区头上。
    # 2026-08-15 实测：一个残留 worktree 让这条判据报出 44 个"编码损坏"文件，
    # 全部来自那份拷贝的 docs/tutorial/ —— 而当前工作区的同名文件是好的。
    ".claude",
}
_SCAN_EXTS = {".py", ".md", ".json", ".yml", ".yaml", ".txt"}


def _corrupted_files() -> list[str]:
    out = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SCAN_EXTS:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:  # pragma: no cover
            continue
        if _PUA.search(text):
            out.append(path.relative_to(REPO).as_posix())
    return sorted(out)


def test_no_encoding_corruption_anywhere_in_the_repo():
    """源码与文档里不许再出现 UTF-8/GBK 乱码。

    **为什么这条值得存在**：R10 顺着 UP-091 那两个"语法都不过"的脚本查下去，
    发现同一次基线导入把 **48 个文件**的中文搞坏了，其中有产品代码
    （`kill_icon_player.py` 的三条 print / docstring）和一个**假绿的测试**
    （`test_tool_pages_ui_polish.py` 把播放列表名设成乱码而不是「默认」，
    测试照样通过——它想模拟的场景根本没模拟到）。

    这类损坏最阴的地方是**不报错**：Python 照常运行，测试照常绿，
    只有用户在控制台看到一堆「鍔犺浇閫愬抚鍔ㄧ敾」。

    回退验证：往任意源文件里塞一个私有区字符或一段乱码，本条立刻变红。
    """
    bad = [
        f for f in _corrupted_files()
        if True
    ]
    assert not bad, (
        "这些文件有 UTF-8/GBK 编码损坏（中文变乱码，且含不可逆的私有区字符）：\n  "
        + "\n  ".join(bad)
        + "\n排查：用 utf-8-sig 读出来，试 `s.encode('gbk').decode('utf-8')` 还原；"
          "带 '?' 或私有区字符的部分已不可逆。"
    )


def test_the_corruption_detector_still_recognises_corruption():
    """自检：探测器得真的认得出损坏，否则上面那条永远绿。

    ⚠⚠ **2026-08-26（RN-199）换了样本，而换样本这件事本身就是这条判据的一次事故。**

    原来它拿的是 `docs/tutorial/` 底下那 42 个已知损坏的教程文件当样本
    （「数量只许减不许增」）。而 RN-199 把整条教程流水线删了 ——
    ⭐⭐⭐ **删掉缺陷语料，就把「探测器还认不认得出缺陷」的证明一起删了。**
    上面那条判据会从「除了那一片以外没有乱码」变成「没有乱码」，
    看起来更严，实际上**再没有任何东西证明它还看得见东西**。

    ⇒ 改成**合成样本**：当场造一段真实形态的 mojibake（UTF-8 中文被按 GBK
    解码再回写，末尾留下不可逆的私有区字符），断言探测器认得出它，
    并断言一段正常中文**不会**被误判。
    ⭐ **一个不依赖仓库里恰好还留着几个坏文件的自检，才是真的自检。**
    """
    clean = '这是一段完全正常的中文说明，带标点：括号（）与引号「」。'
    assert not _PUA.search(clean), (
        f"探测器把一段正常中文判成了损坏：{clean!r} —— 它会开始诬告"
    )

    # 真实形态：私有区字符（U+E000..U+F8FF）正是那次事故里不可逆的那部分。
    corrupted = "鍔犺浇閫愬抚鍔ㄧ敾" + chr(0xE05F) + "锛?"
    assert _PUA.search(corrupted), (
        f"探测器认不出这段 mojibake：{corrupted!r} —— "
        "那么上面那条「全仓没有乱码」是空转的。"
    )

def test_the_button_detector_actually_sees_fixed_widths():
    """自检：探测器得真的认得出 `setFixedWidth`，否则上面那条永远绿。

    拿全仓还剩的那些写死宽度当样本——它们**不是缺陷**（有余量，排版审计盯着），
    只是用来证明探测器没瞎。
    """
    seen = 0
    for path in sorted(PAGES.glob("*.py")):
        try:
            seen += len(_fixed_width_button_texts(path.name))
        except SyntaxError:  # pragma: no cover
            continue
    assert seen >= 5, (
        f"全仓只认出 {seen} 个写死宽度的按钮，探测器多半失灵了"
        "（R10 实测应有 20 个上下）"
    )
