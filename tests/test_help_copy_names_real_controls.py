# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-167：文案点名的控件**必须真的存在**。

⭐ **这条判据推翻了它自己的立案说法。**
RN-167 立案时写的是「文案不该说控件在哪」（~6 处「点右上角「?」看用法」）。
但把它引用的那次**真实失效**翻出来看：`audio_status_badge` 那句
「点右下角「打开音频资源」」坏掉，坏的是**按钮被换成了别的**（空库时那颗
按钮已经变成「去社区拿一套…」）—— 就算当初写成无方位的
「点「打开音频资源」」，**它照样是错的**。
⇒ **删方位词防不住那次失效。** 真正的缺陷是「点名了一个不存在的控件」。

而方位词那一刀，`test_no_layout_self_talk_sitewide.py` 里已经量过并且否掉了
（一刀切当场判红 24 处，大半是对的：OSD 角落是**选项值**，
「点右上角「?」」在两档里都是实话）。⇒ 这一轮**不动那 12 处文案**，
改成给「点名的控件存不存在」配一条棘轮。

**首跑的收成（4 条真缺陷，全在共用助手里）**：

| 文案写的 | 实际控件 |
|---|---|
| 勾上「开启击杀图标」 | **已不存在** —— 批 1（RN-161）把那颗 checkbox 换成了 `MasterSwitchRow`（「总开关」）|
| 点击「保存设置到CFG」 | 「保存到CFG」|
| 点「开始体检」 | 「立即体检」|
| 可用「一键保守修复」 | 「一键修复（保守）」|

⭐ 第一条是**批 1 自己弄坏的**，而批 1/2/3 的判据一条都没看见 ——
RN-138 / RN-163 那个形状的第三次现身：**一处改动不会去通知描述它的文案**，
而这次描述它的文案住在 `ui_help_panel.py`，改按钮的人根本不会打开那个文件。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: 「点/按/勾上…「X」」—— 只在**动作语境**里的引号才是在点名控件。
#: 中文的「」既用来点名按钮，也用来强调普通词（「为什么这个音效不响」、
#: 「用在几杀」、「没放文件」）。不带动词就分不开这两种，会把强调判成缺陷。
#:
#: ⚠ 动词表放宽过一次：第一版没有「用」，于是
#: 「可用「一键保守修复」」**整条漏掉**（分母 35 → 39，多逮出一条真缺陷）。
#: 和 `LAYOUT_WORDS` 一样，这是**拦已知形状的棘轮，不是发现通道** ——
#: 别把「扫过了」读成「没有了」。
#:
#: ⚠⚠ **RN-401：动词和控件名之间夹一个方位词，整条就看不见了。**
#: 第一版要求动词**紧挨**引号，于是这些一条都没进过分母：
#:
#: | 漏掉的原话 | 出处 |
#: |---|---|
#: | 点**右下角**「绘制准心」写进游戏 | `crosshair_page.py:269`（RN-174 的本体）|
#: | 点**本页的**「启用自定闪光」直接开 | `ui_help_panel.py[flash]` —— **RN-192 已经删掉那颗按钮**|
#: | 点**右上角**「?」看用法 | 四个页面的页头 |
#:
#: ⭐⭐ 讽刺的是，方位词恰恰是**"硬指引"的标志** —— 也就是这条棘轮最该盯的那一片，
#: 被它自己的正则整片切掉了。⭐ **一个棘轮的分母，比它自以为的小。**
#: ⭐ 而 RN-192 的现场注释白纸黑字写着「文案点名的控件名必须跟调用方一起走（RN-167）」，
#: 它照做了 —— 只改了**页头**那一处，帮助面板那句没人看见。
POSITION = (
    r"(?:右上角|右下角|左上角|左下角|页面底部|页面顶部|底部操作栏|底栏|操作栏|"
    r"底部|顶部|上面|下面|右边|左边|右侧|左侧|页尾|页首|这一页|本页|"
    r"最下面|最上面|卡片里|这里)"
)
CLICK_CONTEXT = re.compile(
    r"(点击|点|按下|按|勾上|勾选|打开|切到|进入|使用|可用|用|选中|回到|去)"
    r"\s*(?:" + POSITION + r"的?\s*)?[「]([^「」]{1,24})[」]"
)

#: 比对前先脱掉**装饰符**。
#: ⚠ 这一条也是踩出来的：击杀图标那张导入卡把「＋」和「导入」拆成**两个
#: QLabel**（`widgets/kill_icon_style_strip.KillIconStyleAddCard`），
#: 用户看到的是「＋ 导入」，而源码里找不到这个字面量。
#: ⇒ 不归一化就会把一条**完全正确**的文案判成缺陷。
DECORATION = re.compile(r"[＋+…\.⌄▾▸·\s（）()「」\"']")

#: **被点名的根本不是本软件的控件** —— 判据没有任何办法自己看出这一点。
#: ⚠ 白名单只收这一类，不收「这条红了但我不想改」。每一条都写清它到底是什么。
NOT_OUR_CONTROLS = {
    ("screen_effects", "无边框窗口"): "CS2 游戏里的显示模式，不是本软件的控件",
    # ⚠ 键是 `fun` 不是 `fun_afterlife`：这一页的**注册 id 和文件名对不上**
    # （注册表里叫 fun_afterlife，文件叫 `pages/fun_page.py`）。
    # 写错的那一版判据当场把这条正确文案判红 —— 见下面那条族映射守卫。
    ("fun", "全屏窗口化"): "同上，CS2 的显示模式",
    ("about", "疑难杂症解决包"): "「 CS2 Customizer 疑难杂症解决包」是另一个独立程序，不是本页控件",
}

#: 每一页都能用到的共用控件来源（底栏、状态徽章、空库引导、主窗）。
SHARED_SOURCES = [
    REPO / "pages" / "sound_page_base.py",
    REPO / "pages" / "audio_status_badge.py",
    REPO / "widgets" / "community_library.py",
    REPO / "widgets" / "master_switch_link.py",
    REPO / "gui_widget.py",
    #: ⚠ RN-401：放宽正则之后当场冒出 4 条假缺陷「点右上角「?」看用法」——
    #: 那颗 "?" 是**每一页都有**的帮助按钮（`ui_help_panel.py:40`
    #: `super().__init__("?", parent)`），而这个文件不在共用来源里。
    #: `preset_center` 那条碰巧绿，只是因为 `core/presets/preset_center.py` 里
    #: 恰好另有一个 "?" 字面量 —— ⭐ **一条靠巧合成立的绿，和红一样是坏消息。**
    #: （与上面 `dialogs` 那条同型：分母不够的判据会反过来诬告正确的代码。）
    REPO / "ui_help_panel.py",
]

#: ⚠ `dialogs` 是**补上去的**，而漏掉它的代价是当场造出一条假缺陷：
#: 「保存播放设置」只存在于 `dialogs/kill_icon_workshop.py:173`，
#: 族映射里没有这个目录 ⇒ 判据报「这个按钮不存在」。
#: ⭐ 分母不够的判据不是"少抓几条"，是**会反过来诬告正确的代码**。
FAMILY_DIRS = ["pages", "widgets", "core", "dialogs"]


def _norm(text: str) -> str:
    return DECORATION.sub("", text)


def _string_literals(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    return {
        _norm(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _family_files(page_id: str) -> list[Path]:
    """一页的**控件来源**：它自己 + 全仓文件名里带它的 + 共用件。"""
    out = [REPO / "pages" / f"{page_id}_page.py"]
    for folder in FAMILY_DIRS:
        base = REPO / folder
        if base.exists():
            out += [p for p in base.rglob("*.py") if page_id in p.name]
    return out + SHARED_SOURCES


def _control_labels(page_id: str) -> set[str]:
    labels: set[str] = set()
    for path in _family_files(page_id):
        labels |= _string_literals(path)
    return labels


def _non_docstring_strings(path: Path) -> list[tuple[int, str]]:
    """只看**用户读得到**的字面量。docstring 一律不看。

    RN-072 / RN-163 都栽在这上面：判据连注释和 docstring 一起扫，
    结果被自己的说明性文字判红，然后人就会去改那段**本来是对的**说明。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _strip_comments(text: str) -> str:
    """去掉整行注释，保留行号结构（换成空行）。

    ⚠⚠ **RN-401：这里原来不去注释，于是判据会被"记录这条缺陷的那段注释"判红。**
    修 flash 那句假话时，我在现场写了一条注释引用原话
    （「原来写『点本页的「启用自定闪光」』」）—— 文案已经改对了，
    判据却照旧红，因为它把注释也读成了给用户看的文案。

    ⭐ 这**正是** `_non_docstring_strings` 那条已经写在文件里的教训
    （RN-072 / RN-163：判据连注释一起扫，被自己的说明性文字判红，
    然后人就会去改一段本来是对的说明）。
    ⇒ 而这个函数走的是**另一条通路**（裸文本扫描，不过 AST），
    所以那层保护它一点都没享受到。
    ⭐⭐ **一个教训只修在它被发现的那条通路上，等于只修了一份副本。**
    """
    return "\n".join(
        "" if line.lstrip().startswith("#") else line
        for line in text.splitlines()
    )


def _help_panel_sections() -> list[tuple[str, str]]:
    """帮助面板按 `page_id` 分段 —— 每段文案只该点名**那一页**的控件。"""
    text = _strip_comments((REPO / "ui_help_panel.py").read_text(encoding="utf-8"))
    keys = [
        (m.start(), m.group(3))
        for m in re.finditer(r"^(\s*)([\"'])([a-z_0-9]+)\2\s*:", text, re.M)
    ]
    out = []
    for i, (start, page_id) in enumerate(keys):
        end = keys[i + 1][0] if i + 1 < len(keys) else len(text)
        out.append((page_id, text[start:end]))
    return out


def _named_controls() -> list[tuple[str, str, str]]:
    """全部「被文案点名的控件」：(出处, page_id, 控件名)。

    两条通路：**帮助面板**（按 page_id 分段）和**页面自己的文案**。
    ⚠ 少一条通路就少一片分母 —— 页面通路是后补的，一补就多逮出两条。
    """
    found: list[tuple[str, str, str]] = []
    for page_id, body in _help_panel_sections():
        for _verb, name in CLICK_CONTEXT.findall(body):
            found.append((f"ui_help_panel.py[{page_id}]", page_id, name))
    for path in sorted((REPO / "pages").glob("*_page.py")):
        page_id = path.stem[: -len("_page")]
        for lineno, literal in _non_docstring_strings(path):
            for _verb, name in CLICK_CONTEXT.findall(literal):
                found.append((f"{path.name}:{lineno}", page_id, name))
    return found


def _resolves(name: str, labels: set[str]) -> bool:
    """控件名要么整个对上，要么是某个标签的**主干**（允许标签多带几个尾巴）。

    留 6 个字的余量是给「导入图标包…」这类**带后缀的按钮**用的；
    再宽就会把「保存」匹到「保存播放设置」上，那等于放弃判别力。
    """
    target = _norm(name)
    return any(
        target == label or (target in label and len(label) <= len(target) + 6)
        for label in labels
    )


def _offenders() -> list[tuple[str, str, str]]:
    out = []
    for source, page_id, name in _named_controls():
        if (page_id, name) in NOT_OUR_CONTROLS:
            continue
        if not _resolves(name, _control_labels(page_id)):
            out.append((source, page_id, name))
    return out


def test_every_named_control_actually_exists():
    """文案点名的每一颗控件都要能在**那一页自己的**源码里找到。

    ⭐ 为什么是「那一页自己的」而不是全仓：拿全仓比对时，
    一个在别处日志里偶然出现的同名字符串就能让缺陷蒙混过关。
    判据的比对面要**正好等于用户能点到的东西**。
    """
    bad = _offenders()
    assert not bad, (
        f"{len(bad)} 处文案点名了一颗**不存在的控件**：\n"
        + "\n".join(f"  {src}  →「{name}」（{pid} 页里没有这颗）" for src, pid, name in bad)
        + "\n\n控件被改名或删掉时，描述它的文案不会跟着变，也不会有任何东西报错"
        "（RN-138 / RN-163 / RN-167 同一个形状）。\n"
        "把文案改成控件**现在真正的名字**；如果它根本不是本软件的控件"
        "（游戏设置、外部程序），加进 NOT_OUR_CONTROLS 并写清它是什么。"
    )


def test_the_extractor_actually_sees_enough_named_controls():
    """空转守卫①：分母还在数量级上。

    54 是 2026-08-22 的实测数。抽取器（正则、分段、docstring 过滤）
    一旦瞎掉，上面那条会**全绿通过**而什么都没检查。
    """
    total = len(_named_controls())
    assert total >= 40, (
        f"只抽到 {total} 处点名控件的文案，实测应有 50+ —— "
        "抽取器瞎了，上面那条判据在空转。"
    )


def test_both_extraction_paths_are_shipping():
    """空转守卫②：**两条通路各自**都要在出货。

    ⚠ 只看总数是拦不住的：页面通路（后补的那条）整个归零时，
    帮助面板一条腿照样能顶出 39 条，总量守卫过关。
    这正是 `test_no_layout_self_talk_sitewide` 里那条教训的又一次现身 ——
    **每加一条通路就要配一条只盯它自己的守卫。**
    """
    by_path: dict[str, int] = {}
    for source, _pid, _name in _named_controls():
        key = "帮助面板" if source.startswith("ui_help_panel") else "页面文案"
        by_path[key] = by_path.get(key, 0) + 1
    assert by_path.get("帮助面板", 0) >= 25, f"帮助面板通路只出了 {by_path.get('帮助面板', 0)} 条：{by_path}"
    assert by_path.get("页面文案", 0) >= 8, f"页面文案通路只出了 {by_path.get('页面文案', 0)} 条：{by_path}"


def test_the_family_map_reaches_the_dialogs_folder():
    """空转守卫③：族映射必须够到 **`dialogs/`**。

    ⭐ 这条守卫是本轮**踩出来的**，而且它拦的不是漏报是**诬告**：
    「保存播放设置」只存在于 `dialogs/kill_icon_workshop.py`，
    第一版族映射只有 pages / widgets / core ⇒ 判据当场报
    「击杀图标页没有这颗按钮」，而那句帮助文案**完全正确**。
    ⇒ 分母不够的判据会**反过来让人去改对的东西**。
    """
    labels = _control_labels("kill_icon")
    assert _norm("保存播放设置") in labels, (
        "「保存播放设置」找不到了 —— 它住在 `dialogs/kill_icon_workshop.py`。 "
        f"FAMILY_DIRS 现在是 {FAMILY_DIRS}，少了 dialogs 就会把正确文案判成缺陷。"
    )


def test_every_page_id_reaches_its_own_source_files():
    """空转守卫④：每个 page_id 都要够得到**它自己的**源文件。

    ⭐ 这是这条判据最阴的一种坏法：`_family_files()` 找不到任何页面文件时
    **不会报错**，只是把比对面悄悄退化成「只剩共用件」——
    那一页从此变成"点名什么都算存在"，而判据一片绿。

    ⚠ 触发过一次：`fun_afterlife` 这一页的**注册 id 和文件名对不上**
    （文件是 `pages/fun_page.py`）。这类错配以后每加一页都可能再来一次。
    """
    degraded = []
    for _source, page_id, _name in _named_controls():
        own = [
            p for p in _family_files(page_id)
            if p not in SHARED_SOURCES and p.exists()
        ]
        if not own:
            degraded.append(page_id)
    assert not degraded, (
        f"这些 page_id 找不到任何属于自己的源文件：{sorted(set(degraded))}\n"
        "它们的控件名比对已经退化成「只跟共用件比」—— 判据对这几页是半空转的。\n"
        "多半是页面 id 和文件名对不上（如 fun_afterlife / fun_page.py）。"
    )


def test_the_whitelist_does_not_become_a_rubber_stamp():
    """白名单不许长成橡皮图章。

    它只收「这根本不是本软件的控件」这一类（游戏设置、外部程序）。
    这一类天然极少 —— 一旦开始增长，说明有人在用它**关掉判据**而不是修文案。
    """
    assert len(NOT_OUR_CONTROLS) <= 5, (
        f"NOT_OUR_CONTROLS 已经有 {len(NOT_OUR_CONTROLS)} 条。"
        "它只该收「不是本软件控件」的那一类，超过 5 条基本可以确定被当成消音开关用了。"
    )
    for (page_id, name), why in NOT_OUR_CONTROLS.items():
        assert why and len(why) >= 8, f"({page_id}, {name}) 没写清它到底是什么东西"


def test_the_master_switch_help_line_follows_the_control():
    """⭐ 批 1 那条被改坏的帮助文案，配一条只盯它的判据。

    `kill_icon` 的启用方式在 RN-161 里从一颗 `QCheckBox`(「开启击杀图标」)
    换成了 `MasterSwitchRow`。帮助面板那句 `勾上「开启击杀图标」`
    在那一刻起就指着一颗**不存在的控件**，而批 1/2/3 全绿。

    上面那条通用判据已经能拦住它了 —— 这条是**回归锚**：
    通用判据将来若被放宽（正则、白名单、余量），这一条会先响。
    """
    from widgets.master_switch_link import ROW_LABEL_TEXT

    body = dict(_help_panel_sections())["kill_icon"]
    assert "开启击杀图标" not in body, (
        "帮助面板又在教用户去勾一颗 RN-161 已经删掉的 checkbox。"
    )
    assert f"「{ROW_LABEL_TEXT}」" in body, (
        f"`kill_icon` 的帮助文案里没有提到那颗真正的开关（「{ROW_LABEL_TEXT}」）—— "
        "三步引导的第一步就断了。"
    )


def test_the_position_word_clause_is_not_vacuous():
    """空转守卫⑥（RN-401）：**方位词那一段必须真的在多逮东西。**

    第一版正则要求动词**紧挨**引号，于是「点**右下角**「绘制准心」」这种
    一条都进不了分母 —— 而方位词恰恰是「硬指引」的标志，也就是这条棘轮
    最该盯的那一片。实测：加上这一段，分母 **50 → 59**。

    ⚠ 这条守的不是"分母别掉"（那是①），是"**这一段别退化成摆设**" ——
    有人把 `POSITION` 改成一个匹配不到任何东西的表达式，①②照样全绿。
    """
    narrow = re.compile(
        r"(点击|点|按下|按|勾上|勾选|打开|切到|进入|使用|可用|用|选中|回到|去)"
        r"\s*[「]([^「」]{1,24})[」]"
    )
    sample = "改完点右下角「绘制准心」写进游戏。也可以点本页的「启用自定闪光」。"
    assert not narrow.findall(sample), "样本选错了：窄正则本来就该看不见它"
    assert len(CLICK_CONTEXT.findall(sample)) == 2, (
        f"放宽后的正则看不见夹着方位词的点名：{CLICK_CONTEXT.findall(sample)}")

    real = sum(1 for _s, _p, _n in _named_controls())
    narrow_hits = 0
    for _pid, body in _help_panel_sections():
        narrow_hits += len(narrow.findall(body))
    for path in sorted((REPO / "pages").glob("*_page.py")):
        for _lineno, literal in _non_docstring_strings(path):
            narrow_hits += len(narrow.findall(literal))
    assert real > narrow_hits, (
        f"方位词那一段一条都没多逮到（宽 {real} vs 窄 {narrow_hits}）—— "
        f"它已经退化成摆设")


def test_comments_in_the_help_panel_are_not_read_as_user_copy():
    """空转守卫⑦（RN-401）：帮助面板通路必须**去掉注释**再读。

    ⚠ 这条是当场踩出来的：修好 flash 那句假话之后，判据**照旧红** ——
    因为我在现场写了一条注释引用原话，而这条通路是**裸文本扫描**，
    把注释也读成了给用户看的文案。

    ⭐ 页面通路早就有这层保护（`_non_docstring_strings`，RN-072 / RN-163），
    帮助面板通路一点都没享受到。
    ⭐⭐ **一个教训只修在它被发现的那条通路上，等于只修了一份副本。**
    """
    poisoned = (
        '    "flash": (\n'
        '        # 原来写「点本页的「启用自定闪光」直接开」，那颗按钮已删\n'
        '        "1. 在本页打开「自定闪光」总开关<br>"\n'
        '    ),\n'
    )
    cleaned = _strip_comments(poisoned)
    names = [n for _v, n in CLICK_CONTEXT.findall(cleaned)]
    assert "启用自定闪光" not in names, (
        f"注释里的旧文案被当成了给用户看的文案：{names}")
    assert "自定闪光" in names, (
        f"去注释去过头了，真正的文案也没了：{names}")

    # ⚠⚠ **上面只测了那个函数，没测它有没有被用上。**
    # 回退验证当场判这条假绿：把 `_help_panel_sections` 里的 `_strip_comments(...)`
    # 拆掉，这条判据**纹丝不动**（它自己直接调函数，绕过了调用点）。
    # ⭐⭐ **一条只测「零件好使」的判据，证明不了「零件装上了」。**
    # ⇒ 下面这段走**真实通路**：真的分段，断言分出来的每一段里都没有注释行。
    for page_id, body in _help_panel_sections():
        offenders = [ln for ln in body.splitlines() if ln.lstrip().startswith("#")]
        assert not offenders, (
            f"帮助面板通路把注释也读进来了（{page_id} 段）：{offenders[:2]}")


# --------------------------------------------------------------------------
# RN-087：文案不许再把人支去一个**不必去**的地方
# --------------------------------------------------------------------------

#: 「去基础设置开那个开关」这个句式。⚠ 只拦**同时**出现"基础设置"和"开/启用"
#: 的行 —— 单说「基础设置」是正常的（那一页确实存在，别的话题也会提到它）。
SENT_AWAY = re.compile(r"基础设置[^。；\n]{0,12}(?:启用|打开|开启)")


def _pages_with_an_in_place_switch() -> set[str]:
    """哪些页自己就带一颗总开关 —— **真源是产品代码，不是我记的名单**。

    两条来源缺一不可：
      · 页面直接调 `make_master_switch_row(self, "...")`；
      · `sound_page_base` 调它 ⇒ **它的每一个子类**都有（键是变量，AST 认不出来，
        所以按"谁继承了这个基类"来收）。
    ⚠ 漏掉第二条的话，五个音效页会静默躲开这条规则 —— 而它们正是这次
      9 条错文案里的 5 条。⭐ **一份"哪些页适用"的名单，漏掉的那部分不会喊疼。**
    """
    found: set[str] = set()
    base_users: set[str] = set()
    for path in sorted((REPO / "pages").glob("*_page.py")):
        src = path.read_text(encoding="utf-8")
        page_id = path.stem[: -len("_page")]
        if re.search(r"make_master_switch_row\(\s*self\s*,", src):
            found.add(page_id)
        if re.search(r"class\s+\w+\s*\(\s*SoundPageBase\b", src):
            base_users.add(page_id)
    base_src = (REPO / "pages" / "sound_page_base.py").read_text(encoding="utf-8")
    if "make_master_switch_row" in base_src:
        found |= base_users
    return found


def test_the_in_place_switch_roster_is_not_empty():
    """⭐ 分母守卫：这条规则的分母是"有就地开关的页"，它要是空的，下面那条永远绿。"""
    roster = _pages_with_an_in_place_switch()
    assert len(roster) >= 10, (
        f"只找到 {len(roster)} 页有就地总开关：{sorted(roster)} —— "
        "RN-144/147/155/189 一共铺了十几页，说明这份名单的取法瞎了。")
    assert {"kill_sound", "crosshair", "magnifier"} <= roster, (
        f"名单里缺了已知一定有的页：{sorted(roster)}\n"
        "⚠ `kill_sound` 那几页的开关在 `SoundPageBase` 里 —— "
        "只扫页面自己的源码会把它们整片漏掉。")


def test_no_help_text_sends_the_user_somewhere_they_no_longer_need_to_go():
    """⭐⭐ RN-087：**帮助面板 9 条还在教用户「去基础设置启用某某开关」**，

    而 RN-144/147/155/189 早就把那颗开关搬到了**每一页自己的状态卡第一行**。

    ⭐ 这条的形状是本工程的老熟人：**一次修复只改了它被发现的那一处**。
    RN-192 / RN-401 修好了 `flash` 那一条（还在现场注释里写下「文案点名的控件名
    必须跟调用方一起走」），**而同一个文件里另外九条一动没动** ——
    因为那条棘轮问的是「点名的控件**存不存在**」，
    而这九条点名的控件（基础设置里那颗开关）**确实存在**。
    ⇒ ⭐⭐ **「文案说的东西存在」和「文案说的事该做」是两条判据。**
    """
    roster = _pages_with_an_in_place_switch()
    offenders = []
    for page_id, body in _help_panel_sections():
        if page_id not in roster:
            continue
        for line in body.splitlines():
            if SENT_AWAY.search(line):
                offenders.append(f"{page_id}: {line.strip()[:70]}")
    assert not offenders, (
        "这几页自己就有总开关，帮助文案却还在把人支去「基础设置」：\n  " +
        "\n  ".join(offenders) +
        "\n⇒ 改成「在本页状态卡最上面打开「总开关」」（`flash` 那条是改好的样板）。")
