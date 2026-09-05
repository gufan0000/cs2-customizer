# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面说明文案必须是**写给玩家看的**，不是写给做界面的人看的（2026-08-16）。

外审在 8 个页面上独立指出同一件事：副标题写的是**版面决策**而不是功能。
例如「击杀音效页保持列表式效率，把分类切换和快速试听留在一屏里」——
玩家读完既不知道这功能干什么，也不知道第一步该做什么。
这类句子是设计笔记漏进了产品界面，属于客观错误，不是审美偏好。

判据用**词表**而不是人工复核：这类话有很稳定的说法
（"收在首屏"、"保持列表式效率"、"更省空间"、"像工具面板一样"…）。
词表命中即红，改文案的人自然会绕开这些说法。

⚠ 词表只加**描述版面/实现决策**的词，不要加正常功能词。
判据宁可漏也不能误伤——一条会误伤的判据，下一个人会直接把它删掉。

## RN-522（2026-09-05 批 51）：分母只有 0.7%

批 49 的制度体检故意注坏时逮到：把状态芯片改成 `progress: idle` 这种内部记号，
本判据**一声不响**。根因是它的分母只认 4 个记号（`description` / `PAGE_LEAD` /
`PAGE_DESC` / `subtitle`）—— 实测**只看得见 26 条**，而 `pages/` 里含中文的
非 docstring 字面量有 **3586 条**。而批 48 的 RN-508 修的正是芯片与表格里的文案,
**那一整族缺陷全在分母之外**。

⇒ 分母改成**按承载方式识别**：凡是把字符串送上屏幕的构造器与 setter
（`QLabel(...)` / `setText(...)` / `StatusChip(...)` / `QMessageBox.warning(...)` /
`SettingsCard.make(...)` / `PageHeader(...)` / 底栏 `configure_primary(...)` …），
它的字面量参数就在分母里。实测 **26 → 971 条**（含中文 833），
覆盖率 **0.7% → 23.2%**，且**一放宽当场逮出一处存量**（`utility_page` 那句
「预览按钮保留在首屏」，在已关档页上）。

⚠⚠ **23.2% 不是 100%，别把「放宽了」读成「全覆盖了」。** 分母外还剩：
f-string 片段 1233 条（多是 HTML 与拼接）、日志调用约 200 条（**本来就不该在分母里**）、
裸赋值 / 列表 / 字典里的 1031 条。⇒ 配了覆盖率棘轮（见
`test_the_denominator_does_not_fall_behind`）：**新文案换一条没被认出来的路走，
覆盖率会掉，判据会说话** —— 这是 RN-483/511/521/522 同一族（按记号划分母）的解，
补记号只能解决这一次，**量分母本身**才解决下一次。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from _denominator import must_scan


ROOT = Path(__file__).resolve().parents[1]

#: 这些说法描述的是"界面怎么排"，不是"功能是什么"。
#: 每一条都来自真实出现过的文案，不是想象出来的。
LAYOUT_JARGON = (
    "收在首屏",
    "压在首屏",
    "留在首屏",
    "收进同一块",
    "收进一张",
    "保持列表式效率",
    "走紧凑列表",
    "更省空间",
    "像工具面板一样",
    "首屏判断会更直接",
    "卡片层级",
    "拆成清晰卡片",
    "压缩在首屏",
    "都在首屏完成",
)

#: 面向用户的说明文案的**关键字/常量**名（RN-522 之前的全部分母）。
COPY_KEYWORDS = ("description", "PAGE_LEAD", "PAGE_DESC", "subtitle")

#: 构造时第一个（页头与卡片是前两个）位置实参就是屏幕上那段文字的控件/工厂。
TEXT_CTORS = {
    "QLabel": 1, "QPushButton": 1, "QCheckBox": 1, "QRadioButton": 1,
    "QGroupBox": 1, "QToolButton": 1, "QAction": 1, "QCommandLinkButton": 1,
    "StatusChip": 1, "SettingsRow": 1,
    "PageHeader": 2,                       # (标题, 副标题)
}

#: 第一个位置实参会被显示出来的方法。
TEXT_METHODS = (
    "setText", "set_text", "setToolTip", "setPlaceholderText", "setTitle",
    "setWindowTitle", "set_message", "addItem", "addTab", "setPrefix",
    "setSuffix", "setStatusTip", "setWhatsThis", "setLabelText",
    "setItemText", "setTabText",
    "configure_primary", "configure_secondary",   # 底栏按钮
    "_show_notice", "guide_empty_library", "_guide_empty_library",
)

#: ⚠ 靠**接收者**区分，不靠方法名：`QMessageBox.warning(...)` 上屏，
#:   而 `logger.warning(...)` 只进日志。实测 `pages/` 里 `warning` 两种都有 ——
#:   ⭐ 光认方法名会把 100 多条日志文案拖进分母，那才是真正会让人删掉这条判据的误伤。
RECEIVER_CALLS = {
    ("QMessageBox", "information"): slice(1, 3),   # (parent, 标题, 正文)
    ("QMessageBox", "warning"): slice(1, 3),
    ("QMessageBox", "critical"): slice(1, 3),
    ("QMessageBox", "question"): slice(1, 3),
    ("QMessageBox", "about"): slice(1, 3),
    ("SettingsCard", "make"): slice(0, 2),         # (标题, 说明)
}


def _receiver(func):
    value = getattr(func, "value", None)
    return getattr(value, "id", None) or getattr(value, "attr", None)


def _iter_page_copy():
    """产出 (文件名, 行号, 文案)。

    ⭐ RN-522：分母不再按「参数叫什么名字」划，按「**这段字符串会不会被送上屏幕**」划。
    """
    for path in sorted((ROOT / "pages").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                       # 语法坏了是别的判据的事
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", None)
                taken = []
                if fname in TEXT_CTORS:
                    taken = node.args[:TEXT_CTORS[fname]]
                elif fname in TEXT_METHODS:
                    taken = node.args[:1]
                elif isinstance(node.func, ast.Attribute):
                    where = RECEIVER_CALLS.get((_receiver(node.func), fname))
                    if where is not None:
                        taken = node.args[where]
                for arg in taken:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        yield path.name, arg.lineno, arg.value
                # description="..." 这类关键字实参
                for kw in node.keywords:
                    if (kw.arg in COPY_KEYWORDS
                            and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)):
                        yield path.name, kw.value.lineno, kw.value.value
            # PAGE_LEAD = "..." 这类模块/类级常量
            elif isinstance(node, ast.Assign):
                name = getattr(node.targets[0], "id", "") or getattr(
                    node.targets[0], "attr", "")
                if (name in COPY_KEYWORDS
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    yield path.name, node.value.lineno, node.value.value


def test_page_copy_has_no_layout_jargon():
    offenders = []
    for filename, lineno, text in must_scan(
            list(_iter_page_copy()), "pages/*.py 里被送上屏幕的字面量", least=700):
        hits = [w for w in LAYOUT_JARGON if w in text]
        if hits:
            offenders.append(f"{filename}:{lineno} 命中{hits} → {text[:46]}…")
    assert not offenders, (
        "这些页面说明写的是版面决策，不是功能说明。玩家读完不知道这功能干什么、"
        "第一步该做什么：\n  " + "\n  ".join(offenders))


def test_the_jargon_list_itself_still_matches_something():
    """⚠ 词表判据最容易烂掉的方式，是词表本身跟产品文案彻底脱节后
    **永远绿着**，看起来有人在看、其实什么都没看。

    这里拿一段真实出现过的原文做锚：它必须仍被词表逮住。
    """
    historical = "击杀音效页保持列表式效率，把分类切换和快速试听留在一屏里，适合高频逐项排查。"
    assert any(w in historical for w in LAYOUT_JARGON), (
        "词表已经逮不住当初那批文案了，说明它被改空或改跑偏了")


#: 机器记号：`snake_case` 标识符、或 `key: value` / `key=value` 这种内部状态串。
#: ⭐ 这正是批 49 制度体检注入的那一类（`progress: idle`），而旧分母看不见它。
MACHINE_TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
MACHINE_PAIR = re.compile(r"^[a-z][a-z0-9_]*\s*[:=]\s*[A-Za-z0-9_.\-]+$")
HAN = re.compile(r"[\u4e00-\u9fff]")


def _is_machine_token(text: str) -> bool:
    """一段会上屏的文字，是不是内部记号而不是人话。

    ⚠ 只判**不含中文**的串：'0 px' / '100%' / 'CAPSLOCK' / 'mouse1' / 'https://'
    这些实测都在分母里，且都是正当的（数值、按键名、占位符）——
    ⭐ 所以规则要窄到只认「像变量名」的形状，不是「没有中文就红」。
    """
    s = text.strip()
    if not s or HAN.search(s):
        return False
    return bool(MACHINE_TOKEN.match(s) or MACHINE_PAIR.match(s))


def test_screen_copy_is_not_a_machine_token():
    """屏幕上不许出现 `progress: idle` 这种写给程序看的记号。

    ⭐ 这是批 48 RN-508「翻译了容器，没翻译内容」那一族的判据形态：
    容器（卡片标题）早就是中文了，**内容**（芯片、表格格子）却还留着内部值。
    """
    offenders = [
        f"{filename}:{lineno} → {text!r}"
        for filename, lineno, text in must_scan(
            list(_iter_page_copy()), "pages/*.py 里被送上屏幕的字面量", least=700)
        if _is_machine_token(text)
    ]
    assert not offenders, (
        "这些内部记号会原样显示给玩家看：\n  " + "\n  ".join(offenders)
        + "\n⇒ 屏幕上写人话，内部值留在内部（同 RN-508）。")


def test_the_machine_token_rule_still_recognizes_the_thing_it_was_written_for():
    """⚠ 上面那条今天命中 **0** —— 一条 0 命中的规则最容易在重构里被改空而不被发现。

    拿批 49 体检**真正注入过**的那个串做锚：识别器必须仍然认得它。
    ⭐ 同 `test_the_jargon_list_itself_still_matches_something` 的道理：
    **规则要有一个它必须逮住的已知样本**，否则「全绿」和「瞎了」长得一样。
    """
    assert _is_machine_token("progress: idle")
    assert _is_machine_token("audio_health_scan")
    assert _is_machine_token("level=warning")
    # 反向：这些是正当的屏幕文案，不许被误伤（全部取自当前分母里的真实串）
    for ok in ("100%", "0 px", "CAPSLOCK", "mouse1", "https://", "X:", "1.0",
               " 毫秒", "已保存"):
        assert not _is_machine_token(ok), ok


def test_the_denominator_does_not_fall_behind():
    """⭐⭐⭐ **补记号只能解决这一次，量分母本身才解决下一次。**

    RN-483 / RN-511 / RN-521 / RN-522 是同一族：判据按某个记号划分母，
    不带那个记号的东西**天生不在分母里**，于是判据永远绿着。
    ⇒ 这一条不判文案，判**分母自己**：屏幕承载物认出来的中文字面量，
    占 `pages/` 全部中文字面量的比例不许掉下去。

    有人把新文案换一条没被认出来的路送上屏（新工厂、新组件、新 setter），
    这个比例会掉，这条判据会说话。

    实测（2026-09-05 批 51）：认出 971 条，其中含中文 833；
    `pages/` 含中文的非 docstring 字面量 3586 条 ⇒ 覆盖率 **23.2%**。
    旧口径是 26/3586 = **0.7%**。
    """
    seen_han = sum(
        1 for _f, _l, text in _iter_page_copy() if HAN.search(text))
    total_han = _han_literals_in_pages()
    ratio = seen_han / total_han
    assert seen_han >= 800, (
        f"屏幕承载物只认出 {seen_han} 条中文文案（批 51 实测 833）——"
        "识别器多半瞎了，而不是文案真的少了这么多。")
    assert ratio >= 0.20, (
        f"分母覆盖率掉到 {ratio:.1%}（批 51 实测 23.2%，下限 20%）。\n"
        "⇒ 多半是新文案走了一条没被认出来的路上屏"
        "（新的卡片工厂 / 新组件 / 新 setter）。\n"
        "把那条路加进 `TEXT_CTORS` / `TEXT_METHODS` / `RECEIVER_CALLS`，"
        "别把这个下限调低。")


def _han_literals_in_pages() -> int:
    """`pages/*.py` 里含中文的非 docstring 字符串字面量总数（分母的分母）。"""
    total = 0
    files = must_scan(sorted((ROOT / "pages").glob("*.py")), "pages/*.py", least=20)
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if getattr(n, "body", None) and isinstance(n.body, list)
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and HAN.search(node.value)):
                total += 1
    assert total > 2000, f"只数到 {total} 条中文字面量，识别器坏了"
    return total


def test_page_copy_does_not_point_at_a_nonexistent_page():
    """文案里提到的页面名，必须真的在侧栏里存在。

    实测「…可先刷新风格列表再回首页启用」出现在 **5 个页面**，
    而侧栏里**从来没有叫「首页」的东西**（那一页叫「基础设置」）。

    ⚠⚠ **这条判据第一版只查「首页」这一个词**（`回首页|去首页|首页启用`）——
    它是为那一次的缺陷写的，硬编码了那三个字面量。
    2026-09-04 批 46 当场被绕过去：我给 `audio_replay` 的空状态加了一颗
    「去**音效页**试听一次」，而侧栏里没有叫「音效页」的东西
    （我跳的 `kill_sound` 在侧栏叫「**击杀音效**」）——
    ⭐⭐⭐ **给「上次那个 bug」写的判据，挡不住「同一类的下一个 bug」**
      （这句话逐字写在 `test_master_switch_row.py` 里，而我在另一份文件里又踩了一次）。
    ⇒ 泛化成：凡是「去/回/到 **X页**」这种**指路**句式，X 就必须在侧栏里找得到。
    """
    nav_titles = must_scan(_sidebar_titles(), "侧栏里的页面标题", least=20)

    #: 指路句式：动词 + 页面名 + 「页」。
    #: ⚠ 代词类（本页/这一页/上一页…）**不是**指路 —— 它们说的是当前这一页。
    pronouns = ("本", "这", "那", "上", "下", "每", "整", "当前", "同", "另", "各", "首")
    pointer = re.compile(r"[去回到往]\s*([^\s，。；：、「」（）()]{2,6})页")

    # ⚠⚠ **只看用户看得见的字面量，必须先去 docstring。**
    #   泛化第一版扫的是裸文本，当场误报 4 处 —— 全是注释 / docstring 里的散文
    #   （「到指定功能页」「去别的页」「回写首页」「去掉之后页」）。
    # ⭐⭐ 而「扫文本的判据必须先去注释」这句话，批 45 刚记过一次
    #   （那次是 CI 判据被我自己写的注释喂了一个错的位置）—— 隔一批又踩了一次。
    # ⭐ 走 AST 拿字符串常量，注释天然不在里面；docstring 再显式摘掉。
    ghosts = []
    files = must_scan(sorted((ROOT / "pages").glob("*.py")), "pages/*.py", least=20)
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and id(node) not in docs):
                continue
            for m in pointer.finditer(node.value):
                name = m.group(1)
                if name.startswith(pronouns):
                    continue
                # ⭐ 文案里那个名字必须**就是**某个侧栏标题（带不带「页」都行）。
                # ⚠⚠ 第一版写的是 `any(name in title ...)` —— **方向反了**，
                #   而这句注释当时就写着「反过来不算」。
                #   于是「去**音效**页」被「击杀音效」含住而放过，
                #   破坏验证当场判它假绿。
                # ⭐⭐ **注释写对了，代码写反了 —— 而注释不会被执行。**
                if name in nav_titles or f"{name}页" in nav_titles:
                    continue
                ghosts.append(f"{path.name}:{node.lineno}  「{m.group(0)}」")
            # ⚠ 老那条留着：它点名的是一个**具体**的历史缺陷，而泛化那条
            #   认不出「首页」（代词表里就有「首」，会被跳过）。
            #   ⭐ 两条各看一半，都要。
            if re.search(r"回首页|去首页|首页启用", node.value):
                ghosts.append(f"{path.name}:{node.lineno}  「首页」")
    assert "首页" not in " ".join(nav_titles), "侧栏现在真有「首页」了，请更新本判据"
    assert not ghosts, (
        "这些文案在给用户指路，而侧栏里没有那个名字：\n  "
        + "\n  ".join(ghosts)
        + f"\n侧栏实际有：{nav_titles}"
        + "\n⭐ 文案点名的目标名要跟真正的目标走 —— 抄成字面量之后，"
          "那一页改名的当天就有好几处对不上，而且一处都不会报错。")


def _sidebar_titles():
    """从 `gui_widget.py` 的 nav_groups 里静态取出侧栏显示名。

    走 AST 而不是跑 GUI：这条判据只关心文案与导航名对不对得上，
    没必要为此建一个主窗口。
    """
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    titles = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", "") == "nav_groups":
            for group in node.value.elts:
                for item in group.elts[1].elts:
                    titles.add(item.elts[1].value)
    assert titles, "没能从 gui_widget.nav_groups 解析出侧栏条目，判据失效了"
    return titles
