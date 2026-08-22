# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-077：卡片副标题不许讲**版面决策** —— 全站 28 页，不是只有音效家族。

**为什么这不是文风偏好**：描述版面的文案会随版面腐烂，描述功能的不会。
RN-036/RN-050 那批里的「把启用开关和总音量固定在上方」在 UP-100 把头部卡
挪进滚动区之后**就已经是事实错误**，而没有任何判据会因此变红 ——
版面自白是一种**注定会变成谎话**的文案。

⭐ 这条判据的**上一版分母只有 2 页**（写在 `test_gun_special_sound_truth.py`
里，`PAGES = ["gun_sound", "special_sound"]`），于是 M3-b 盘点 `viewmodel` 时
当场撞到三处一模一样的，其中一句「5 组常用持枪参数继续保留完整编辑能力，
**滚动区域更紧凑一些**」是**对着上一版说话**，而用户没见过上一版。
放开分母后一次量出 **20 条 / 8 页**（副标题总数 93）—— 音效家族那两页
一条都不在里面。同 RN-073 那条教训：
**判据写完要问的不是它绿不绿，是它的分母是多少。**

⚠ 抽取器的名单也栽过一次同样的跟头：第一版只认 `SettingsCard` /
`_create_section_card`，于是 `magnifier_page.py` 的 `_create_inner_panel_card()`
整支落在视野外，里面躺着两条。所以下面按**名字里带 card/panel/section/header**
放宽，而不是列举工厂函数名。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: 「A、B 和 C **摆在**某处」这个模板本身就是自白，逐词列举永远列不全。
LAYOUT_PATTERNS = [
    r"(收|放|集中|摆|固定|挪|排成|并排|归)[^，。；]{0,8}"
    r"(一起|一块|一组|一排|一行|同一|上方|下方|面板里|卡片里|一个面板)",
    # 「都集中在这里」是自白，而「准心偏了就在这里校回来」不是 —— 差别在动词。
    # ⚠ 第一版把 `放` 也配上 `这里`，当场误判了一条刚写好的功能文案。
    r"(集中|收|归|摆)[^，。；]{0,8}这里",
    r"(视线|来回找|来回滚动|来回跳|不用来回)",
    r"(更紧凑|紧凑一些|滚动区域|版面|布局更|首屏更像)",
]

#: 单独出现就算自白的词（位置代词 + 历史上真出现过的自白措辞）。
LAYOUT_WORDS = [
    "上方", "下方", "左侧栏", "同一组", "同一块", "同一排", "同一行",
    "一行里", "收在一起", "收在一个", "收到一起", "放在一起", "放到一起",
    "集中在一起", "集中到一起", "集中在一块", "集中到一块", "紧凑", "滚动区",
    "折叠起来", "摆出来", "更像一块", "固定在", "分开调试", "上面那", "下面那",
    "这张卡", "本卡", "卡片里", "面板里", "便于快速试", "确认映射",
    "集中管理各阶段", "并排",
    # ⚠ 这一批是**改完复跑那一轮补上的**：外审 3/3 × 多张图报了
    # 「把首屏基础观感…压成一张概况卡」，而上面那套词表和模板**一条都没匹上**
    # （它用的动词是「压成」，不在动词表里）。
    # ⇒ 诚实的结论：**禁用词表不可能穷尽这一类**。这条判据是拦「已知说法回归」的棘轮，
    #   真正的**发现通道**是外审看图。别把它当成"扫过就没有了"。
    "压成", "挤成", "概况卡", "首屏", "往下找", "底栏", "顶栏", "标签栏",
]


def _subtitle_literals(path: Path) -> list[tuple[int, str]]:
    """AST 摘出所有卡片/页头副标题字面量：(行号, 文本)。

    只看**用户真的会读到**的那一段。注释和 docstring 一律不看 ——
    RN-072 那轮的判据就是因为文本比对连注释一起看，被自己的说明性注释判红。

    ⚠ **RN-091（2026-08-18 补）**：这个抽取器原来只认「调用的实参」，
    于是音效家族那 4 页（kill_sound / kill_voice / reload_sound / switch_weapon）
    **一条都抽不到** —— 它们的页头文案是类常量 `PAGE_LEAD`，
    由 `sound_page_base` 转手递给 `PageHeader(description=...)`。
    实测 `kill_sound_page.py` 抽到 **0 条**，而总量守卫（≥60）照样过关。
    ⇒ 又一次分母：**总量够不代表每条通路都在出货**。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        # ① 类常量通路：`PAGE_LEAD = "..."`（音效家族经基类转递给页头）
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not (isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str) and node.value.value):
                    continue
                if not isinstance(t, ast.Name):
                    continue
                if t.id == "PAGE_LEAD":
                    out.append((node.value.lineno, node.value.value, "PAGE_LEAD"))
                # ③ 模块常量通路：`XXX_LEAD_TEXT = "..."`（RN-145）。
                # 页头文案有两种说法（库空 / 库不空）时，`description=` 收的就不再是
                # 字面量而是一个名字 —— 抽取器的实参通路当场**看不见这一页**，
                # 而总量守卫照样绿（少一条而已）。这正是 RN-091 那条教训的第二次现身。
                # ⭐ 顺带把**空状态那一句**也纳入扫描：它以前从来没被扫过。
                elif t.id.endswith("_LEAD_TEXT"):
                    out.append((node.value.lineno, node.value.value, "LEAD_TEXT"))
            continue
        # ② 实参通路：SettingsCard / 私有卡片工厂 / PageHeader
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
        owner = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
        low = (name or "").lower()
        # ⚠ 记下**是哪条分支匹上的**。空转守卫要靠它 —— 见
        # `test_the_extractor_actually_sees_the_variant_factories`。
        if name == "SettingsCard" or owner == "SettingsCard":
            branch = "SettingsCard"
        elif any(k in low for k in ("card", "panel", "section", "group")):
            branch = "变体工厂"
        elif "header" in low:
            branch = "PageHeader"
        else:
            continue
        is_card = branch != "PageHeader"
        cand: list[ast.expr] = []
        if is_card and len(node.args) >= 2:
            cand.append(node.args[1])          # description 是第 2 个位置参数
        cand += [kw.value for kw in node.keywords if kw.arg in ("description", "subtitle", "desc")]
        for c in cand:
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value:
                out.append((c.lineno, c.value, branch))
    return out


def _copy_sources() -> list[Path]:
    return sorted((REPO / "pages").glob("*.py")) + [REPO / "gui_widget.py"]


def _self_talk() -> list[tuple[str, int, list[str], str]]:
    hits = []
    for path in _copy_sources():
        for lineno, text, _branch in _subtitle_literals(path):
            bad = [w for w in LAYOUT_WORDS if w in text]
            bad += [m.group(0) for p in LAYOUT_PATTERNS for m in re.finditer(p, text)]
            if bad:
                hits.append((path.name, lineno, sorted(set(bad)), text))
    return hits


def test_the_extractor_actually_sees_the_subtitles():
    """空转守卫①：总量还在数量级上。

    93 是 2026-08-17 的实测数；这里只要求"数量级还在"，不钉死具体值。
    """
    total = sum(len(_subtitle_literals(p)) for p in _copy_sources())
    assert total >= 60, (
        f"只摘到 {total} 条卡片副标题，实测应有 90+ —— "
        "抽取器（很可能是那个 card/panel/header 名字白名单）瞎了，下面那条判据在空转。")


def test_the_extractor_actually_sees_the_variant_factories():
    """空转守卫②：**私有工厂那条分支**必须真的在出货。

    ⚠ 这条守卫改过两版，两版都被回退验证判为假绿：
      · 第一版只数总数 —— 抽取器退回「只认 SettingsCard」之后总数还有 60+，过关；
      · 第二版点名 `magnifier_page` / `voice_output_page` —— 这两页**两种工厂都用**，
        退回之后它们照样出货，还是过关。
    ⇒ 守卫必须盯**会被拆掉的那条分支本身**，不是盯页面、更不是盯总数。
    这正是 RN-073 那条教训的第三次现身：分母。
    """
    by_branch: dict[str, int] = {}
    for path in _copy_sources():
        for _lineno, _text, branch in _subtitle_literals(path):
            by_branch[branch] = by_branch.get(branch, 0) + 1
    assert by_branch.get("变体工厂", 0) >= 4, (
        f"私有工厂（`_create_inner_panel_card` / `_create_panel_card` / "
        f"`_create_section_card` 这一类）只出了 {by_branch.get('变体工厂', 0)} 条副标题。 "
        f"各分支实际出货：{by_branch}。 "
        "抽取器一旦退回「只认 SettingsCard」，这条分支归零而总数照样够 —— "
        "下面那条判据就在**部分空转**，而没人看得出来。")


def test_the_extractor_actually_sees_the_page_lead_constants():
    """空转守卫③：**类常量那条通路**必须真的在出货（RN-091）。

    音效家族 4 页的页头文案是 `PAGE_LEAD` 类常量，不是调用实参。
    这条通路 2026-08-18 之前**完全没被抽到**，而总量守卫一直是绿的。
    ⇒ 每加一条通路就要配一条只盯它自己的守卫，否则总量会把它盖住。
    """
    by_branch: dict[str, int] = {}
    for path in _copy_sources():
        for _lineno, _text, branch in _subtitle_literals(path):
            by_branch[branch] = by_branch.get(branch, 0) + 1
    assert by_branch.get("PAGE_LEAD", 0) >= 4, (
        f"`PAGE_LEAD` 这条通路只出了 {by_branch.get('PAGE_LEAD', 0)} 条。 "
        f"各分支实际出货：{by_branch}。 "
        "音效家族至少 4 页（kill_sound / kill_voice / reload_sound / switch_weapon）"
        "用这个写法，少于 4 说明抽取器又瞎了一条腿。")


def test_the_extractor_actually_sees_the_module_lead_constants():
    """空转守卫④：**模块常量那条通路**必须真的在出货（RN-145）。

    `kill_icon_page` 的页头文案有两种说法（风格库空 / 不空），所以
    `PageHeader(description=...)` 收的是一个名字而不是字面量。
    实参通路对它是瞎的，而总量守卫只会少一条、照样绿。

    ⭐ 这条守卫是**改动自己造出来的盲区**——我把一句字面量收成常量的那一刻，
    这一页就从全站文案扫描里掉出去了，没有任何东西会响。
    """
    by_branch: dict[str, int] = {}
    for path in _copy_sources():
        for _lineno, _text, branch in _subtitle_literals(path):
            by_branch[branch] = by_branch.get(branch, 0) + 1
    assert by_branch.get("LEAD_TEXT", 0) >= 2, (
        f"`*_LEAD_TEXT` 这条通路只出了 {by_branch.get('LEAD_TEXT', 0)} 条。 "
        f"各分支实际出货：{by_branch}。 "
        "`kill_icon_page` 的 NORMAL_LEAD_TEXT / EMPTY_LEAD_TEXT 至少 2 条。")


#: 指向**窗口级导航**的方位说法。这是唯一真正会翻车的一类：
#: 紧凑档（860×640）没有侧栏 —— 导航收成左上角一个 ⋮ 菜单。
#:
#: ⚠ 第一版是**一刀切禁所有方位词**，当场量出 24 处，而里面大半是对的：
#:   · `advanced_page` 的「右下角/左下角/右上角/左上角」是 OSD 位置的**选项值**，
#:     `fun_page` 的「屏幕左侧/右侧」同理 —— 那是设置项内容，不是指路；
#:   · 「点右上角「?」看用法」「点右下角…」里的 ? 按钮和底栏**两档都在**，说的是实话。
#: ⇒ 一刀切会把 20 条正确文案判红，判据就会被人关掉。只禁真会腐烂的那一种。
DIRECTION_PATTERNS = [
    r"(左侧|左边|左方|右侧|右边)[^，。；]{0,6}(页面|页|栏|导航|菜单)",
    r"侧栏",
]

def _indicating_copy() -> list[tuple[str, int, str]]:
    """**指路文案**：卡片副标题 + 页头 + 帮助面板。方位词只在这三处会翻车。

    ⚠ 扫描面也窄化过一次。第一版扫「所有中文字面量」，于是把三条不是指路的判红：
      · `advanced_page` 的「侧栏显示「常用」分组」是一个**管侧栏的设置项标签** ——
        它就该叫侧栏；
      · `gui_widget` 的「常用分组初始化失败(侧栏按默认分组继续)」是**日志**，用户看不到。
    ⇒ 判据的扫描面不是越大越好，是要**正好等于缺陷能长的地方**。
    """
    out = [(p.name, ln, text)
           for p in _copy_sources()
           for ln, text, _branch in _subtitle_literals(p)]
    for path in [REPO / "ui_help_panel.py"]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and any("一" <= ch <= "鿿" for ch in node.value)):
                out.append((path.name, node.lineno, node.value))
    return out


def test_no_screen_direction_words_in_user_facing_copy():
    """文案不许写屏幕方位 —— **紧凑档没有侧栏**，方位词在那一档直接是错的。

    ⭐ 这条规则是**我自己踩出来的**，而且是「改完复跑」那一轮逮住的：
    我为了修 RN-075 的同名歧义，把 `flash` 的引导改成
    「先在**左侧**「基础设置」页的「功能开关」里打开「自定闪光」」——
    读起来清楚多了，完整档也确实在左侧。
    然后同一批截图复跑，外审 **3/3 × 多张紧凑图**判「高」，其中一发直接写
    「方位误写为"左侧"」：紧凑档 860×640 下导航是**左上角一个 ⋮ 菜单**，
    没有任何"左侧栏"。⇒ **我修一条「高」的时候造出了另一条「高」。**

    所以这条判据要扫的不只是卡片副标题，还有帮助面板 —— 因为出事的那一处在帮助面板。
    """
    offenders = [
        (name, lineno, text) for name, lineno, text in _indicating_copy()
        if any(re.search(p, text) for p in DIRECTION_PATTERNS)
    ]
    assert not offenders, (
        f"{len(offenders)} 处用户可见文案按位置指向导航（紧凑档没有侧栏，那一档就是错的）：\n"
        + "\n".join(f"  {name}:{ln}  {text[:70]}" for name, ln, text in offenders)
        + "\n改成按**名字**指路（「导航里的「基础设置」页」），不要按位置指路。")


def test_no_layout_self_talk_in_any_card_subtitle():
    hits = _self_talk()
    assert not hits, (
        f"{len(hits)} 条卡片副标题还在讲版面而不是功能（RN-077）：\n"
        + "\n".join(f"  {name}:{ln}  {bad}\n     {text}" for name, ln, bad, text in hits)
        + "\n\n改成「这张卡能帮玩家做什么」。理由不是文风："
        "描述版面的文案会随版面腐烂（RN-050 那句「固定在上方」在 UP-100 之后"
        "就已经是事实错误），描述功能的不会。")


@pytest.mark.parametrize("page", ["gun_sound", "special_sound"])
def test_the_old_two_page_judge_is_covered_by_this_one(page):
    """上一版那两页的禁用词，现在由全站判据一并管着。

    留这条是为了让「判据搬家」这件事本身有判据 —— 否则搬完之后
    `test_gun_special_sound_truth.py` 里那条被删掉，覆盖面悄悄少两页也没人知道。
    """
    old_banned = ["固定在上方", "放在同一组", "摆出来", "更像一块",
                  "便于快速试", "确认映射", "集中管理各阶段"]
    missing = [w for w in old_banned
               if w not in LAYOUT_WORDS
               and not any(re.search(p, w) for p in LAYOUT_PATTERNS)]
    assert not missing, (
        f"上一版（{page}）拦得住而现在拦不住的措辞：{missing} —— "
        "判据搬家不许缩小覆盖面。")


def test_field_labels_never_wrap_into_two_lines(qapp, monkeypatch):
    """⭐⭐ RN-191：以「:」结尾的**字段标签**不许被挤到折行。

    实测（紧凑档 860×640，`magnifier`）：

        「主武器热键:」  宽 69px / 需 **73px**  ⇒ 折成「主武器热」+「键:」
        「防抖延迟(ms):」宽 73px / 需 88px、「微调:」「大幅:」同样折行

    **差 4px 就断成两行。** 而它躲得过一切"有没有溢出/有没有截断"的判据 ——
    折行既不溢出也不截断（RN-121 记过这条）。

    ⭐⭐ 更要紧的是 RN-121 当年**已经留了 opt-out** (`KEEP_WRAP_PROPERTY`)，
    可它是 **opt-in 的**：得有人想起来在调用处设那个属性，而表单标签的调用方
    一个都没设。⇒ **一个"默认开、需要显式关"的行为，等于"绝大多数地方都开着"；
    opt-out 的存在不代表它被用上了。**

    现在的规则从文案自己推得出来（`_is_field_label`），不靠名单。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    import sys as _sys

    _scripts = str(REPO / "scripts")
    if _scripts not in _sys.path:
        _sys.path.insert(0, _scripts)
    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    config.compact_mode = True
    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        win.setMinimumSize(860, 640)
        win.resize(860, 640)
        qapp.processEvents()

        page_ids = [p for p in win._page_names if p not in neutral.unsafe_pages()]
        neutral.apply(config, page_ids)
        offenders, checked = [], 0
        for page_id in page_ids:
            win.show_page(page_id, animated=False)
            for _ in range(3):
                qapp.processEvents()
            page = win.pages.get(page_id)
            if page is None:
                continue
            for label in page.findChildren(QLabel):
                text = label.text().strip()
                if not text or label.isHidden():
                    continue
                if not (text[-1] in ":：" and len(text) <= 16):
                    continue
                checked += 1
                # ⚠ 断言的是**规则本身**（字段标签不许开折行），不是"此刻被挤没被挤"。
                # 第一版断言的是症状 —— 而"差 4px 折不折"取决于这一次布局跑到哪儿：
                # 同一页，先逐页走一遍再看是 4 个折行，直接跳过去看是 0 个。
                # ⭐ **一条结论随导航历史变化的判据，绿的时候什么都不证明。**
                if label.wordWrap():
                    need = label.fontMetrics().horizontalAdvance(text)
                    offenders.append(
                        f"{page_id}: 「{text}」 开着折行"
                        f"（宽 {label.width()}px / 需 {need}px）")

        assert checked >= 20, (
            f"只量到 {checked} 个字段标签 —— 判据在空转，先修取标签那一段")
        assert not offenders, (
            f"紧凑档里这些字段标签被挤到折行（{len(offenders)} 个）：\n  "
            + "\n  ".join(offenders[:8])
            + "\n⭐ 折行不是「空间不够」的结果，是「我说我能折行」的结果 —— "
            "它躲得过一切溢出/截断判据（RN-121 / RN-191）。")
    finally:
        config.compact_mode = False
        win.close()
        win.deleteLater()
        qapp.processEvents()
