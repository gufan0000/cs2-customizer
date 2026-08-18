# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-046~053：`gun_sound` / `special_sound` 说的话必须和用户看到的一致。

这两页**不在 `SoundPageBase` 那个簇里**（方法相似度只有 19~34%），所以上一轮
RN-033 的修法没有覆盖到它们。探针实测（2026-08-17，全新配置）：

| 页 | 造的状态 | 页面说的话 | 每一行实际显示 |
|---|---|---|---|
| gun_sound | 2 把枪配了已删除的风格 | 「已配置 · 2/18」「分类 · 手枪 2/9」 | 全是「不启用」 |
| special_sound | 8 个回合事件全配上 | 「已选 **5**/8」 | 全是「不启用」 |

⭐ `special_sound` 那条是**两个错叠在一起**：
  ① 计数分子把「回合有哪几个事件」**手写成 5 个字段**，而事件表里已经是 8 个
     （2.2.4 加了 比赛开始 / 比赛结束 / 半场交换）—— 分母 `len(ROUND_TYPE_META)`
     是派生的，所以是 8。⇒ **计数上限 5、分母 8，配满也永远显示不满。**
     `core/audio/special_events` 的模块 docstring 开篇就在讲"这张表存在的意义
     是别再有第二份手写清单"，而徽章代码里就躺着第二份。
  ② 数的是配置原始值，而下拉框显示的是解析后的值（RN-026/RN-033 那个病）。

⚠ 判据一律读**真正渲染出来的文字**（`QLabel.text()`），不读辅助函数 ——
上一轮的假绿全出在这里：判据落在 `_configured_weapon_count()` 上，
而断点改的是徽章实际用的那个变量，两者不相干。

⚠ 每一支行为判据前都有**空转守卫**：不造「配了但风格不存在」的状态，
两个口径给出的数字恰好相同，判据会全绿而毫无意义。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PAGES_DIR = REPO / "pages"
PAGES = ["gun_sound", "special_sound"]


def _src(page: str) -> str:
    return (PAGES_DIR / f"{page}_page.py").read_text(encoding="utf-8")


# ==================================================== 结构层：单一真相源与死代码

def test_style_resolver_is_single_sourced():
    """「配置值 → 这一行真正显示的值」这条知识只准有一份。

    RN-033 上一轮把它收进了 `SoundPageBase`，但那个基类只服务四页；
    `gun_sound` / `special_sound` / `death_sound` 的数据模型都不同，
    于是"要么各写一份、要么强行并基类"看起来是唯一选择 —— 都不对。
    真正共用的是一个**纯函数**：`resolve_style(配置值, 可选列表)`。
    数据模型不同不妨碍共用它，因为它不碰数据模型。

    RN-002 / RN-031 / RN-032 的同一条教训：**只要还有第二份副本，
    修好一份就等于没修**，而且漂的时候不报错。
    """
    badge_src = (PAGES_DIR / "audio_status_badge.py").read_text(encoding="utf-8")
    assert "def resolve_style(" in badge_src, (
        "`pages/audio_status_badge.py` 里没有 `resolve_style()` —— "
        "它是这条知识的唯一真相源。")

    owners = []
    for path in PAGES_DIR.glob("*_page.py"):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and re.fullmatch(
                    r"_resolved?_style(_value)?", node.name):
                # 基类那份是 GRID 家族经 `_get_style_display_text` 的实现，
                # 与纯函数不是一回事，允许它存在；页面自己写就不行。
                owners.append(f"{path.name}:{node.lineno}:{node.name}")
    assert not owners, (
        f"这些页自己又写了一份风格解析：{owners} —— 改成调 "
        "`audio_status_badge.resolve_style()`。")


@pytest.mark.parametrize("page", PAGES)
def test_no_private_method_is_dead(page):
    """页面里定义的私有方法必须**至少被引用一次**。

    起因是 `gun_sound._create_weapon_card`：**113 行，全仓零调用**，
    而且它自己带着两处错 ——
      · 标签写成「镜声风格:」（该页是枪声，"镜声"是开镜放大页的词）；
      · `title_row` 建了、装了武器名，却**从未 addLayout 进卡片**
        ⇒ 万一哪天把它接回去，第一件事就是"每张卡片都没有武器名"。
    ⇒ 死代码不是"多占几行"，是**藏着一颗按了才响的雷**。

    这条判据是**通用的**，不是只盯那一个方法：以后再有人复制一份卡片构造器
    忘了删，它当场就报。
    """
    tree = ast.parse(_src(page))
    src = _src(page)
    dead = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        name = node.name
        if not name.startswith("_") or name.startswith("__"):
            continue
        # 出现次数 <= 1 说明只有 `def` 那一处，没有任何调用点。
        # 用 \b 边界，免得 `_test_gun_sound` 把 `_test_gun_sound_x` 也算进去。
        if len(re.findall(rf"\b{re.escape(name)}\b", src)) <= 1:
            dead.append(f"{name}（第 {node.lineno} 行）")
    assert not dead, (
        f"{page} 有定义了但全页零引用的私有方法：{dead} —— "
        "死代码会连着它内部的错一起腐烂，删掉或接回去，别留着。")


def test_round_event_list_is_not_handwritten_again():
    """`special_sound` 里不许再出现 `round_*_style` 字面量。

    这些字段名的唯一真相源是 `core/audio/special_events.SOUND_EVENTS`，
    页面通过 `ROUND_TYPE_META` 派生。而徽章计数处曾经手写了 5 个字面量：

        round_selected = count_enabled_styles([
            getattr(config, "round_start_style", "0"), ...  # 只有 5 个
        ])

    事件表里是 8 个 ⇒ 「已选 5/8」是**结构性上限**，不是巧合。
    2.2.4 加三个事件的那次改动没人碰这里，而**它不会报错**。
    """
    # ⚠ 只看**字符串字面量**，不看方法名和注释。
    # 第一版判据用的是裸正则 `round_[a-z_]+_style`，它会命中
    # `scan_round_sound_styles` 里的 `round_sound_style` 子串 —— 假报。
    # 第二版想靠加词边界解决，结果那个转义符在“写文件”
    # 那条链上被吃成了退格符（0x08），正则从此永不匹配
    # ⇒ **判据变成假绿**，比假报更危险。
    # 所以第三版换掉手段：走 AST 只取字符串常量，不再跟转义符较劲。
    hits = sorted({
        node.value for node in ast.walk(ast.parse(_src("special_sound")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and re.fullmatch(r"round_[a-z_]+_style", node.value)
    })
    assert not hits, (
        f"special_sound 又手写了回合样式字段名：{hits} —— "
        "从 `ROUND_TYPE_META`（派生自事件表）取，别再抄第二份清单。")


@pytest.mark.parametrize("page", PAGES)
def test_pages_do_not_count_raw_config_values(page):
    """`count_enabled_styles(<配置里的原始值>)` 这个写法必须绝迹。

    ⚠ 上一轮的同名判据只 parametrize 了 GRID 四页，`special_sound` 不在里面 ——
    于是那页顶着一模一样的缺陷、判据全绿。**这就是 UP-096 那条教训**：
    判据的覆盖面必须自己写清楚，否则"绿"会被读成"全看过了"。
    """
    for node in ast.walk(ast.parse(_src(page))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "count_enabled_styles"):
            pytest.fail(
                f"{page} 第 {node.lineno} 行还在数配置原始值 —— "
                "先过 `resolve_style()` 再数（RN-046/RN-048）。")


# ⚠ RN-077：这里原来有 `test_no_layout_self_talk_in_card_copy`（禁用词 × 本文件的
# `PAGES` 两页）。它**分母只有 2 页**，于是 M3-b 盘点 `viewmodel` 时当场撞到三处
# 一模一样的自白，放开分母后一次量出 20 条 / 8 页 —— 这两页反倒一条都没有。
# 判据已搬到 `tests/test_no_layout_self_talk_sitewide.py`（全站 + 模板匹配），
# 那里还留了一条判据钉住「搬家不许缩小覆盖面」。


# ==================================================== 行为层：gun_sound

def _visible_chips(page):
    from PySide6.QtWidgets import QLabel
    bar = page.status_badge_label
    return [c.text() for c in bar.findChildren(QLabel) if not c.isHidden()]


def _chip(page, prefix: str) -> str:
    for text in _visible_chips(page):
        if text.startswith(prefix):
            return text
    return ""


def _make_gun_page(monkeypatch, configured: dict, available: dict):
    """造一个 gun_sound：`configured` 是写进 config 的值，`available` 是扫到的风格。"""
    from config import config
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST
    import pages.gun_sound_page as mod

    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
        monkeypatch.setattr(config, profile.style_key,
                            configured.get(profile.gun_type, "0"), raising=False)
    monkeypatch.setattr(mod.GunSoundPage, "_scan_gun_sounds",
                        lambda self: setattr(self, "weapon_styles", dict(available)))
    return mod.GunSoundPage()


def test_gun_sound_idle_guard_counts_real_configuration(qapp, monkeypatch):
    """空转守卫：风格**存在**时，「已配置」必须真的数到它。

    没有这一条，下面那支判据可以靠"永远显示 0"作弊通过。
    """
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST
    first = SUPPORTED_GUN_SOUND_PROFILE_LIST[0].gun_type
    page = _make_gun_page(monkeypatch, {first: "存在的风格"},
                          {first: ["存在的风格"]})
    assert _chip(page, "已配置").startswith("已配置 · 1/"), (
        f"风格明明在，却没数进去：{_visible_chips(page)}")


def test_gun_sound_does_not_count_styles_that_are_gone(qapp, monkeypatch):
    """配了一个**已不存在**的风格时，「已配置」不许把它算进去。

    实测原状：徽章「已配置 · 2/18」「分类 · 手枪 2/9」，
    而那两行的下拉框显示的都是「不启用」—— 两个口径永久对不上，无人报错。
    """
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST
    types = [p.gun_type for p in SUPPORTED_GUN_SOUND_PROFILE_LIST[:2]]
    page = _make_gun_page(monkeypatch, {t: "已被删除的风格" for t in types}, {})

    for gun_type in types:
        combo = page.weapon_rows[gun_type]["style_combo"]
        assert combo.currentText() == page.DISABLED_STYLE_TEXT, (
            "前提没成立：这一行应当显示「不启用」，判据才有意义")

    configured_chip = _chip(page, "已配置")
    assert configured_chip.startswith("已配置 · 0/"), (
        f"「已配置」把失效项算进去了：{configured_chip}（每一行都显示「不启用」）")
    assert "失效" in " ".join(_visible_chips(page)), (
        f"没有任何地方告诉用户「有 N 项失效」：{_visible_chips(page)} —— "
        "对不上的数字不可行动，「有 2 项失效」才可行动。")


def test_gun_sound_preview_tells_stale_from_unset(qapp, monkeypatch):
    """试听要分清「真没配」和「配过但风格没了」。

    RN-029 的教训：这两件事合报成一句，用户会去查声卡驱动。
    """
    import widgets.preview_feedback as pf
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST

    said: list[str] = []
    monkeypatch.setattr(pf, "report_preview_failure",
                        lambda page, reason, detail="", **kw: said.append(reason))
    import pages.gun_sound_page as mod
    monkeypatch.setattr(mod, "report_preview_failure",
                        lambda page, reason, detail="", **kw: said.append(reason))

    gun_type = SUPPORTED_GUN_SOUND_PROFILE_LIST[0].gun_type
    page = _make_gun_page(monkeypatch, {gun_type: "已被删除的风格"}, {})
    page._test_gun_sound(gun_type)
    assert said and said[-1] == pf.PreviewFailure.STALE_STYLE, (
        f"配过但风格没了，报的却是 {said} —— 应报 STALE_STYLE")

    said.clear()
    page2 = _make_gun_page(monkeypatch, {}, {})
    page2._test_gun_sound(gun_type)
    assert said and said[-1] == pf.PreviewFailure.NO_STYLE, (
        f"真没配，报的却是 {said} —— 应报 NO_STYLE")


def test_gun_sound_empty_state_is_said_once_not_eighteen_times(qapp, monkeypatch):
    """全新安装时，「还没有素材」这句话只准出现**一次**。

    实测原状：18 张武器卡各挂一句「当前还没有检测到这个武器的可用风格资源，
    建议先保持"不启用"。」—— 一屏能看到 3 句，翻完 4 个页签共 18 句，
    而顶部状态卡已经写着「素材 · 待添加」。

    ⭐ 与上一轮那句 50 字辩解同一个病：**当初写它是因为别处没说，
    别处说了就该撤掉**。这次更狠——它是 18 份。
    """
    from PySide6.QtWidgets import QLabel
    page = _make_gun_page(monkeypatch, {}, {})
    hits = [label.text() for label in page.findChildren(QLabel)
            if "还没有检测到" in label.text() or "没有检测到该武器" in label.text()]
    assert len(hits) <= 1, (
        f"同一句空状态提示重复了 {len(hits)} 次 —— 收成页级一条（RN-049）")


# ==================================================== 行为层：special_sound

def _make_special_page(monkeypatch, round_styles, available):
    """造一个 special_sound：`available` 是"扫得到的风格列表"。

    ⚠ 注入点必须是 `_refresh_special_sound_styles` 本身，不能构造完再往
    `audio_manager` 上塞 —— `_refresh_style_catalog()` 会重扫一遍，
    把塞进去的值原地擦掉（第一版判据就是这么假绿的）。
    """
    from config import config
    from core.audio.special_events import SOUND_EVENTS, events_in_group, styles_attr
    import pages.special_sound_page as mod

    def _inject(self):
        self.audio_manager.grenade_sound_styles = {
            g: list(available) for g in self.GRENADE_TYPES}
        for event in SOUND_EVENTS:
            setattr(self.audio_manager, styles_attr(event), list(available))

    monkeypatch.setattr(mod.SpecialSoundPage,
                        "_refresh_special_sound_styles", _inject)

    for event in events_in_group("round"):
        monkeypatch.setattr(config, event.config_attr,
                            round_styles.get(event.key, "0"), raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    return mod.SpecialSoundPage()


def test_special_sound_round_count_is_not_capped_at_five(qapp, monkeypatch):
    """⭐ 本轮最硬的一条：8 个回合事件都配上，摘要必须说 8/8，不是 5/8。

    这条如果失败，看到的会是 `已选 5/8` —— 计数分子手写了 5 个字段，
    分母是从事件表派生的 8 个。**分子分母不同源，就是这种结果。**
    """
    from core.audio.special_events import events_in_group
    events = events_in_group("round")
    assert len(events) > 5, (
        "前提没成立：事件表里回合事件不足 6 个，这条判据量不到上限问题")

    page = _make_special_page(
        monkeypatch, {e.key: "存在的风格" for e in events}, ["存在的风格"])
    text = page.round_summary_label.text()
    assert f"{len(events)}/{len(events)}" in text, (
        f"回合摘要说的是 {text!r} —— 应当是 {len(events)}/{len(events)}。"
        "计数分子还在手写那 5 个字段（RN-046）。")


def test_special_sound_round_count_ignores_stale_styles(qapp, monkeypatch):
    """配了**不存在**的风格时，回合摘要不许把它算成已选。"""
    from core.audio.special_events import events_in_group
    events = events_in_group("round")
    page = _make_special_page(
        monkeypatch, {e.key: "已被删除的风格" for e in events}, [])

    for event in events:
        combo = page.round_combos[event.key]
        assert combo.currentText() == "不启用", "前提没成立"

    text = page.round_summary_label.text()
    assert f"已选 0/{len(events)}" in text, (
        f"回合摘要把失效项算成已选了：{text!r}")
    assert f"有 {len(events)} 项" in text, (
        f"没告诉用户有几项配的风格已经不在了：{text!r} —— 那是唯一可行动的信息")


@pytest.mark.parametrize("method,label", [
    ("_test_grenade_sound", "投掷物"),
    ("_test_health_warning", "血量警告"),
    ("_test_round_sound", "回合"),
    ("_test_c4_sound", "C4"),
])
def test_special_sound_preview_never_silently_does_nothing(
        qapp, monkeypatch, method, label):
    """四个「测试」按钮在没配音效时都必须给用户可见反馈。

    实测原状：**四个全是只写一行日志就 return** —— 用户看到的是"点了没反应"。
    UP-037 那一轮把其余各页都改了，这页四个出口一个没改。

    ⭐ 外审 8 发截图里有 **7 发独立**报「测试按钮未置灰，点击无反应易被误认为
    软件故障」。上一轮我把这类判成「现象真但机制已缓解（点了会给 toast）」——
    那个裁定对**有 toast 的页**成立，对这一页不成立。
    ⇒ 「已经修过」是按页成立的，不是按缺陷类型成立的。
    """
    import widgets.preview_feedback as pf
    import pages.special_sound_page as mod

    said: list[str] = []
    monkeypatch.setattr(pf, "report_preview_failure",
                        lambda page, reason, detail="", **kw: said.append(reason))
    monkeypatch.setattr(mod, "report_preview_failure",
                        lambda page, reason, detail="", **kw: said.append(reason),
                        raising=False)

    page = _make_special_page(monkeypatch, {}, [])
    from config import config
    config.grenade_sound_styles = dict.fromkeys(page.GRENADE_TYPES, "0")
    monkeypatch.setattr(config, "health_warning_style", "0", raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "0", raising=False)

    args = {
        "_test_grenade_sound": ("hegrenade",),
        "_test_health_warning": (),
        "_test_round_sound": ("start",),
        "_test_c4_sound": (page.C4_EVENTS[0],),
    }[method]
    getattr(page, method)(*args)

    assert said, (
        f"{label} 的「测试」在未配置时什么反馈都没有（只写了日志）—— "
        "用户看到的是「点了没反应」（RN-047）")


def test_special_sound_warns_when_style_chosen_but_module_off(
        qapp, monkeypatch):
    """选了风格却没勾模块开关时，页面必须说出来。

    这一页有**两层开关**：模块复选框 + 每一项的「不启用」。
    外审 8 发里 4 发独立报「双重开关逻辑冲突，玩家容易只选下拉项而遗漏总开关，
    导致局内不生效」。这不是加控件能解决的（那会更复杂），
    是**把当前状态说清楚**：配了、但这一类没开。
    """
    from core.audio.special_events import events_in_group
    from config import config
    events = events_in_group("round")
    page = _make_special_page(
        monkeypatch, {events[0].key: "存在的风格"}, ["存在的风格"])
    config.round_sound_enabled = False
    page._refresh_status_badge()

    text = page.round_summary_label.text()
    assert "没开" in text or "不会响" in text or "不生效" in text, (
        f"配了风格但模块没开，摘要只说 {text!r} —— "
        "得明说「这一类还没开，配了也不会响」（RN-051）")


def test_special_sound_status_chip_follows_current_tab(qapp, monkeypatch):
    """状态栏那颗随页签变的徽章要跟着当前页签走。

    实测原状：在「血量警告」页签上，状态栏第三颗徽章写的是「回合音量 · 100%」——
    跟当前页签毫无关系。外审两发独立报「将其他标签页的回合音量混在全局状态栏展示」。
    `gun_sound` 的「分类 · …」徽章早就是跟着页签走的，这页照它做。
    """
    page = _make_special_page(monkeypatch, {}, [])
    seen = {}
    for index in range(page.tab_widget.count()):
        page.tab_widget.setCurrentIndex(index)
        page._refresh_status_badge()
        seen[page.tab_widget.tabText(index)] = list(_visible_chips(page))

    health_chips = " ".join(seen.get("血量警告", []))
    assert "回合音量" not in health_chips, (
        f"血量警告页签上还在显示回合音量：{health_chips}")
    assert "阈值" in health_chips, (
        f"血量警告页签上没有本页签自己的信息：{health_chips}")


def test_hint_only_names_buttons_that_exist(qapp, monkeypatch):
    """提示文案里点名的按钮，必须真的是本页那颗按钮上的字。

    ⭐ RN-056，本轮**改完复跑外审逮住的、我自己引入的**缺陷（连续第三轮）：
    我把共享的 `resource_hint()` 搬到 `special_sound` 上，那句话写着
    「点右下角『打开音频资源』」—— 而这一页那颗按钮叫「**打开当前资源**」
    （它按当前页签开不同目录）。页面于是在指挥用户去点一个本页不存在的按钮。
    外审 8 发里 **4 发独立**报了这条，措辞几乎一样。

    ⇒ **单一真相源不等于文案可以照搬。** 一句话只要提到界面上的某个东西，
      那个东西就必须跟着调用方走；否则"收敛重复"反而制造出新的不一致。

    这条判据是**通用的**：以后任何一页往提示里写「点『XXX』」，
    只要 XXX 不在本页按钮上，它当场报。
    """
    import re as _re
    from PySide6.QtWidgets import QLabel, QPushButton

    pages = []
    from pages.gun_sound_page import GunSoundPage
    from pages.special_sound_page import SpecialSoundPage
    pages.append(("gun_sound", GunSoundPage()))
    pages.append(("special_sound", SpecialSoundPage()))

    problems = []
    for name, page in pages:
        buttons = {b.text().strip() for b in page.findChildren(QPushButton) if b.text().strip()}
        for label in page.findChildren(QLabel):
            text = label.text()
            if not text or label.isHidden():
                continue
            # 「点…『X』」这种句式里的引号内容才算"点名了一个按钮"
            for quoted in _re.findall(r"[「『]([^」』]{2,12})[」』]", text):
                if "点" not in text:
                    continue
                if quoted in buttons:
                    continue
                # 页签名、配置项名不算按钮；只在"这个词像个动作按钮"时才判
                if quoted.startswith(("打开", "刷新", "测试", "保存", "导出")):
                    problems.append(f"{name}: 文案说「{quoted}」，"
                                    f"但本页按钮只有 {sorted(buttons)}")

    assert not problems, "\n".join(problems)


def test_health_tab_keeps_the_two_sliders_on_one_row(qapp, monkeypatch):
    """血量警告卡里，两个滑块必须并排在**同一行**；选风格那行在它们下面。

    ⭐ RN-055，本轮**改完复跑外审逮住的、我自己引入的**第二条：
    外审 S3 报「触发阈值与警告音效带独立边框，而同级的再次提醒间隔通栏拉伸，
    容器样式不一致」（中）。我第一版把三行全摊成通栏 —— 容器是一致了，
    卡片也高了一行，于是**紧凑档 860×640 下最后一行被截**，
    复跑当场报「高」，而改之前紧凑档这一页是 NONE。
    ⇒ **拿一个「中」换来一个「高」是笔亏本的交易。**

    现在的改法不加高度：两个**同类**的东西（阈值滑块 / 间隔滑块）并排，
    「选风格 + 试听」通栏在下。行数与原来一致，而视觉分组终于和语义一致了。

    判据盯的是**几何**（同一个 y），不是代码写法 —— 换个写法只要行数没变就放行。
    """
    page = _make_special_page(monkeypatch, {}, [])
    page.resize(1280, 800)
    page.show()
    qapp.processEvents()

    threshold_row = page.threshold_slider.parentWidget()
    cooldown_row = page.cooldown_slider.parentWidget()
    style_row = page.health_style_combo.parentWidget()

    assert threshold_row.y() == cooldown_row.y(), (
        f"两个滑块没并排：阈值 y={threshold_row.y()}，间隔 y={cooldown_row.y()} —— "
        "卡片会高一行，紧凑档下最后一行被截（RN-055）")
    assert style_row.y() > threshold_row.y(), (
        f"选风格那行没在滑块下面：style y={style_row.y()}，"
        f"slider y={threshold_row.y()}")
    page.hide()


TERM_PAGES = ["kill_sound", "kill_voice", "switch_weapon", "reload_sound",
              "death_sound", "gun_sound", "special_sound"]


@pytest.mark.parametrize("page", TERM_PAGES)
def test_one_word_for_one_thing_in_user_facing_copy(page):
    """七个音效页里，"一套音效"这个东西只准叫**风格**，不许混用「样式」。

    RN-057：外审 S4 两发独立报「『样式』『风格』『模块』『素材』多词混用，
    用户无法理解其与音效配置的关系」（高）。核实（AST 只数用户可见字面量）：

        special_sound   样式 9  / 风格 16     ← 同一页两个词指同一个东西
        death_sound     样式 11 / 风格 23     ← 同上
        其余五页        样式 0  / 风格 N

    ⇒ 家族标准本来就是「风格」，混用的只有那两页。
    ⭐ 而 `death_sound` 是**上一轮刚关档**的页 —— 又一次印证
      「关档 ≠ 这页没问题」：新发现一类缺陷，要回头扫已关档的页。

    ⚠ 只查**用户看得见的**字面量：docstring 和 `logger` 文案不算。
    日志里的「样式已更新」故意保留 —— 那是给开发看的，改了搜日志的人会找不到。
    """
    tree = ast.parse(_src(page))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docs.add(doc)

    logged = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in (
                "info", "debug", "warning", "error", "exception"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    logged.add(sub.value)

    bad = [node.value for node in ast.walk(tree)
           if isinstance(node, ast.Constant) and isinstance(node.value, str)
           and "样式" in node.value
           and node.value not in docs and node.value not in logged]
    assert not bad, (
        f"{page} 的界面文案里还有「样式」：{bad} —— 家族统一叫「风格」（RN-057）")
