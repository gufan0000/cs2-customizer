# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-033~038/040：音效家族的状态必须和用户看到的一致。

kill_sound 那一轮（RN-026）修的是同一个病，这一轮把它在**整个家族**里收干净：

| 页面 | 原状（探针实测，配置里指向已删除的风格） |
|---|---|
| kill_sound | 顶部「已配置 · 37」，39 把枪全显示「不启用」（已于上一轮修） |
| kill_voice | 同上，**关档时 RN-026 还没被发现，所以漏在了这里** |
| switch_weapon | 顶部「已配置 · 3」，三行全「不启用」，点测试报「文件不存在」 |
| reload_sound | 同上 |
| death_sound | ⭐ **闭环矛盾**：徽章「样式 · 已删除的风格」／下拉框「不启用」／ |
| | 选择卡「当前已选择"X"，**切换后可以直接点击测试**」／点测试「还没选风格」 |

⚠ 这一组判据的**共同要害**：必须造出「配了、但那个风格不存在」的状态，
否则两个口径给出的数字恰好相同，判据会全绿而毫无意义 ——
所以每一支行为判据前面都先有一条**空转守卫**。

⚠ 判据一律读**真正渲染出来的文字**，不读辅助函数。
上一轮我把判据落在 `_configured_weapon_count()` 上，而断点改的是徽章实际
用的那个变量，两者不相干 —— 缺陷注进去判据照样绿，回退验证当场逮住。
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from config import config  # noqa: E402

PAGES_DIR = REPO / "pages"

#: 走 `SoundPageBase` 那套武器网格的四页
GRID_PAGES = ["kill_sound", "kill_voice", "switch_weapon", "reload_sound"]
#: 会显示「资源 · …」那颗徽章的全部页面
BADGE_PAGES = GRID_PAGES + ["death_sound", "gun_sound", "special_sound"]


# ============================================================ 结构层：单一真相源

def _src(page: str) -> str:
    return (PAGES_DIR / f"{page}_page.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("page", GRID_PAGES)
def test_grid_pages_count_through_the_single_resolver(page):
    """四页的计数必须走 `_resolved_styles()`，不许再直接数配置的原始值。

    这一条是**便宜的全族覆盖**：行为判据只打两页代表（下面），
    而这条保证另外两页不会悄悄退回旧口径。
    """
    src = _src(page)
    assert "_resolved_styles()" in src, (
        f"{page} 没有走 `_resolved_styles()` —— 它一定又在数配置里的原始值了，"
        "而每一行显示的是解析后的值，两边必然对不上（RN-026/RN-033）。")
    assert "_stale_weapon_count(" in src, (
        f"{page} 没算失效项 —— 失效数会被静默算进「已配置」，"
        "用户只看到一个对不上的数字，看不到「有 N 项失效」这件唯一可行动的信息。")


@pytest.mark.parametrize("page", GRID_PAGES)
def test_no_page_counts_a_raw_config_dict_with_count_enabled_styles(page):
    """`count_enabled_styles(config.<dict>.values())` 这个写法必须绝迹。

    它就是缺陷本体：数的是**配置里的原始值**，而界面显示的是解析后的值。
    """
    tree = ast.parse(_src(page))
    # ⭐ 分母是这一页的调用点；页面被搬空之后「没人再这么数」自动成立。
    must_scan([n for n in ast.walk(tree) if isinstance(n, ast.Call)],
              f"{page} 页里的函数调用", least=20)
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "count_enabled_styles"):
            bad.append(node.lineno)
    assert not bad, (
        f"{page} 第 {bad} 行还在用 `count_enabled_styles()` 数原始配置值 —— "
        "换成 `self._configured_weapon_count(resolved=...)`（RN-033）。")


def test_the_resolver_lives_in_exactly_one_place_for_the_grid_family():
    """四页共用基类那一份，谁也不许再抄一份 `_resolved_style`。

    RN-002 的教训：同一份知识抄两遍，抄的时候都对，**漂了才发作**。
    """
    must_scan(GRID_PAGES, "GRID_PAGES（共用基类的四页）", least=4)
    owners = [p for p in GRID_PAGES if "def _resolved_style(" in _src(p)]
    assert not owners, (
        f"{owners} 自己又写了一份 `_resolved_style` —— 基类 "
        "`pages/sound_page_base.py` 已经有了，四页共用那一份。")
    base = (PAGES_DIR / "sound_page_base.py").read_text(encoding="utf-8")
    assert "def _resolved_style(" in base and "def _stale_weapon_count(" in base


@pytest.mark.parametrize("page", BADGE_PAGES)
def test_resource_badge_classification_is_not_copy_pasted_per_page(page):
    """资源徽章的分级只能有一份（`audio_status_badge.resource_badge`）。

    原先七页各抄一遍下面这段，**七份都把「素材目录还没建」报成红色异常**：

        health_level = "danger" if not health["ok"] else ...
        "资源 · 正常" if health["ok"] else f"资源 · 异常 {n}"

    而「还没放素材」正是全新安装的样子（实测新装用户在四个音效页
    各看到一个红色「资源 · 异常」，点开 tooltip 只有一行绝对路径）。
    """
    src = _src(page)
    assert 'health_level' not in src, (
        f"{page} 还在自己算 `health_level` —— 改成 `resource_badge(health)`（RN-035）。")
    assert "资源 · 异常" not in src, (
        f"{page} 还自己拼「资源 · 异常」的文案 —— 那份分级把全新安装判成红色报错。")
    assert "resource_badge(" in src, f"{page} 没用 `resource_badge()`"


@pytest.mark.parametrize("page", BADGE_PAGES)
def test_no_page_orders_the_user_to_flip_a_switch_that_may_already_be_on(page):
    """副标题不许无条件写「先去「基础设置」打开总开关」。

    同一屏上徽章写着「开关 · 已启用」，副标题却命令用户去打开它 ——
    **自相矛盾**。外审六发截图里四发独立点出这一条，措辞几乎一样：
    「文案矛盾引发困惑」「误导玩家离开当前界面」。

    ⚠ 判据只管**页面自己的说明文案**（`PAGE_LEAD` / `description=`）。
    底部操作条那句「总开关当前关闭，…可先去「基础设置」打开」是**条件文案**，
    只在真的关着时才出现，那是对的，不在此列。

    ⚠⚠ **这条判据只覆盖 `BADGE_PAGES` 这七页**，别把它的绿读成"全站都查过了"。
    同一句话在 `flash` / `magnifier` / `utility` 三页也在（2026-08-17 实测），
    那三页分属 P2/P3/P4 批次、还没锁基线，留到各自那一轮改
    （已在登记册 RN-034 记为存量）。—— UP-096 的教训：
    **任何"某某维度全绿"的结论，先确认那个维度真的有判据在看。**
    """
    src = _src(page)
    for m in re.finditer(r'(PAGE_LEAD\s*=\s*|description=)"([^"]*)"', src):
        text = m.group(2)
        assert "先去「基础设置」打开总开关" not in text, (
            f"{page} 的页面说明无条件命令用户去开总开关：{text!r}\n"
            "改成陈述总开关在哪；「现在开没开」交给徽章和底部操作条按状态说（RN-034）。")


@pytest.mark.parametrize("page", ["switch_weapon", "reload_sound"])
def test_the_level_argument_branch_is_gone(page):
    """`_test_<x>_sound(weapon, level)` 这个分支必须消失 —— 它一走必 TypeError。

    那两个函数**只接一个参数**。它没爆过，纯粹因为这两页 `TEST_LEVELS is None`
    ⇒ `WeaponRowWidget` 不建档位菜单、`testLevelClicked` 永不发射。
    是死代码，但是**写错的**死代码：哪天给这两页加档位试听，第一次点就崩。
    """
    tree = ast.parse(_src(page))
    fn = f"_test_{'switch' if page == 'switch_weapon' else 'reload'}_sound"
    arity = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            arity[fn] = len(node.args.args) - 1      # 去掉 self
    assert fn in arity, f"{page} 里找不到 {fn}"
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == fn and len(node.args) > arity[fn]):
            bad.append((node.lineno, len(node.args)))
    assert not bad, (
        f"{page} 第 {bad} 处按 {arity[fn]} 参的 {fn} 传了更多参数 —— 走到就 TypeError（RN-037）。")


@pytest.mark.parametrize("page", GRID_PAGES)
def test_configured_examples_are_computed_once(page):
    """「已配置示例」在一次刷新里只准算一遍（RN-038 / RN-019 / RN-014 同形）。

    原先 `_configured_preview_names()` 在同一个方法里被调两次，而两次之间
    没有任何东西改变过它的输入 —— 纯重复计算。
    """
    tree = ast.parse(_src(page))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_refresh_status_badge":
            calls = [n.lineno for n in ast.walk(node)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr in ("_configured_weapon_names",
                                         "_configured_preview_names")]
            assert len(calls) <= 1, (
                f"{page}._refresh_status_badge 里算了 {len(calls)} 遍已配置示例"
                f"（第 {calls} 行）—— 输入没变，结果必然逐字相同。")
            return
    pytest.fail(f"{page} 里找不到 _refresh_status_badge")


# ============================================================ 行为层

class _GridAudioManager:
    """够把 kill_sound / kill_voice 建起来的最小替身。只有 `styleA` 真实存在。"""

    def __init__(self):
        self.kill_sound_styles = ["styleA"]
        self.weapon_kill_sound_styles = {}
        self.kill_voice_styles = ["styleA"]
        self.weapon_kill_voice_styles = {}
        self.weapon_sounds_dir = "sounds/weapon"
        self.kill_sounds_dir = "sounds/common"
        self.weapon_voices_dir = "sounds/weapon_voices"
        self.kill_voices_dir = "sounds/voices"
        self.switch_weapons_dir = "sounds/switch"
        self.reload_sounds_dir = "sounds/reload"
        self._sounds = {}

    def ensure_styles_scanned(self):
        return None

    def scan_kill_sound_styles(self):
        return self.kill_sound_styles

    def scan_weapon_kill_sound_styles(self):
        return self.weapon_kill_sound_styles

    def play_sound(self, key, channel_type=None):
        return False

    def load_sound(self, *a, **k):
        return True


_HEALTH_FRESH_INSTALL = {
    "ok": False, "missing": ["X:/whatever/resources/audio/switch_weapons"],
    "empty": [], "invalid": [], "issue_count": 1,
}

#: 三把枪配着**已经不存在**的风格。数量刻意 != 0，好让两个口径给出不同的数。
_STALE_CONFIG = {"weapon_ak47": "已删除的风格", "weapon_awp": "也删了",
                 "weapon_glock": "还是删了"}


@pytest.fixture()
def reported(monkeypatch):
    """截下 `report_preview_failure` 的调用 —— 试听失败到底跟用户说了什么。"""
    seen = []
    import widgets.preview_feedback as pf

    def fake(page, reason, detail=None):
        seen.append((getattr(reason, "value", str(reason)), detail))

    for mod_name in ("widgets.preview_feedback", "pages.switch_weapon_page",
                     "pages.reload_sound_page", "pages.death_sound_page",
                     "pages.kill_voice_page"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "report_preview_failure"):
            monkeypatch.setattr(mod, "report_preview_failure", fake)
    monkeypatch.setattr(pf, "report_preview_failure", fake, raising=False)
    return seen


def _visible_chips(page):
    """徽章条上**当前真正显示着**的芯片文字。

    `AudioStatusBadgeBar` 用芯片复用池，隐藏的那些还留着上一次渲染的旧文字。
    """
    from PySide6.QtWidgets import QLabel

    return [c.text() for c in page.status_badge_label.findChildren(QLabel)
            if not c.isHidden()]


def _badge_text(page) -> str:
    return " | ".join(_visible_chips(page))


def _rows_showing_a_style(page) -> int:
    """列表里**真正显示着某个风格**（而不是「不启用」）的行数。"""
    from PySide6.QtWidgets import QComboBox

    n = 0
    for row in page.weapon_rows.values():
        combo = row.findChild(QComboBox)
        if combo is not None and combo.currentText() != page.DISABLED_STYLE_TEXT:
            n += 1
    return n


@pytest.fixture(params=["switch_weapon", "reload_sound"])
def grid_page(request, qapp, monkeypatch):
    name = request.param
    mod = __import__(f"pages.{name}_page", fromlist=["x"])
    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: _GridAudioManager())
    monkeypatch.setattr(mod, "collect_category_health",
                        lambda _roots: dict(_HEALTH_FRESH_INSTALL))
    # 目录里一个风格都扫不到 ⇒ 配置里那三把枪全是"配了但风格不在"
    monkeypatch.setattr(mod, "list_style_dirs_with_audio", lambda *a, **k: [])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    cfg_attr = ("weapon_switch_sounds" if name == "switch_weapon"
                else "weapon_reload_sounds")
    enabled_attr = ("switch_weapon_sound_enabled" if name == "switch_weapon"
                    else "reload_sound_enabled")
    monkeypatch.setattr(config, enabled_attr, True, raising=False)
    monkeypatch.setattr(config, cfg_attr, dict(_STALE_CONFIG), raising=False)
    cls = getattr(mod, "SwitchWeaponPage" if name == "switch_weapon" else "ReloadSoundPage")
    p = cls()
    p._page_name = name
    yield p
    p.deleteLater()
    qapp.processEvents()


def test_the_fixture_really_produces_stale_entries(grid_page):
    """空转守卫：先证明这套夹具真的造出了「配了但风格不在」的状态。

    没有这一条，下面所有判据都可能是在一个「根本没有失效项」的世界里全绿。
    """
    stale = grid_page._stale_weapon_count()
    assert stale == 3, f"夹具没造出预期的 3 个失效项（实际 {stale}），下面的判据会空转"
    assert _rows_showing_a_style(grid_page) == 0, "夹具没让那几行退回「不启用」"


def test_badge_number_matches_the_rows_the_user_can_see(grid_page):
    """徽章上的「已配置 · N」必须等于列表里**真正显示着风格**的行数。

    ⚠ 刻意从**渲染出来的芯片文字**里抠数字，不读 `_configured_weapon_count()`。
    """
    text = _badge_text(grid_page)
    m = re.search(r"已配置\s*·\s*(\d+)", text)
    assert m, f"徽章里没有「已配置 · N」：{text!r}"
    assert int(m.group(1)) == _rows_showing_a_style(grid_page), (
        f"徽章说已配置 {m.group(1)} 个，而列表里显示着风格的只有 "
        f"{_rows_showing_a_style(grid_page)} 行：{text!r}")


def test_the_badge_says_out_loud_that_some_entries_went_stale(grid_page):
    """失效项必须**在屏幕上被说出来**，不能只是从计数里消失。"""
    text = _badge_text(grid_page)
    assert "失效" in text, f"徽章没提失效项：{text!r}"


def test_the_visible_hint_line_says_how_to_fix_it(grid_page):
    """「怎么修」必须落在**可见**的那一行上。

    ⚠ RN-009：`summary_label` 建出来就 `hide()`，写进去等于没写。
    kill_sound 那轮我就写错过一次，外审复跑一句「醒目报错却无修复引导，
    易让玩家误判为软件损坏」直接点破。
    """
    assert grid_page.summary_label.isHidden(), (
        "summary_label 竟然可见了？那 RN-009 的前提变了，这条判据要重写")
    hint = grid_page.category_overview_hint_label.text()
    assert not grid_page.category_overview_hint_label.isHidden()
    assert "3" in hint and "重新选" in hint, f"可见提示行没说清怎么修：{hint!r}"


def test_previewing_a_stale_style_says_the_style_is_gone(grid_page, reported):
    """点「测试」要说「你选的那个风格没了」，不能说「文件不存在」或「还没选风格」。

    原状：那一行明明显示「不启用」，点测试却报「文件不存在」——
    用户会去查音频设备和素材，而真正的原因是他配的风格已经被改名或删掉。
    """
    reported.clear()
    grid_page._test_weapon("weapon_ak47")
    assert reported, "点了测试却什么都没告诉用户（UP-037 那个「点了没反应」）"
    reason, detail = reported[-1]
    assert reason == "stale_style", f"报的是 {reason!r}（detail={detail!r}），应为 stale_style"
    assert detail and "已删除的风格" in str(detail), (
        f"没把那个失效的风格名说出来：{detail!r}")


def test_a_missing_material_dir_is_not_painted_as_a_red_error(grid_page):
    """全新安装（素材目录还不存在）不许显示成红色「资源 · 异常」。

    这是外审 S4 六发里五发独立点出的那条：
    「红色'资源·异常'但无具体原因与修复指引，容易让玩家误以为程序崩溃」。
    实测机制比它猜的更糟 —— 那个"异常"的全部内容就是「目录还没建」。
    """
    text = _badge_text(grid_page)
    assert "资源 · 异常" not in text, (
        f"素材目录还没建被画成了红色异常：{text!r}")
    assert "待添加" in text, f"没给出「素材待添加」这个说法：{text!r}"


# --------------------------------------------------------- death_sound 那个闭环

@pytest.fixture()
def death_page(qapp, monkeypatch):
    import pages.death_sound_page as mod

    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: _GridAudioManager())
    monkeypatch.setattr(mod, "collect_category_health",
                        lambda _roots: dict(_HEALTH_FRESH_INSTALL))
    monkeypatch.setattr(mod, "list_unique_audio_stems", lambda *a, **k: [])
    monkeypatch.setattr(mod, "find_audio_by_stem", lambda *a, **k: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "death_sound_style", "已删除的风格", raising=False)
    p = mod.DeathSoundPage()
    yield p
    p.deleteLater()
    qapp.processEvents()


def test_death_fixture_really_produces_a_stale_style(death_page):
    """空转守卫。"""
    assert death_page._stale_style_name() == "已删除的风格"
    assert death_page.style_combo.currentText() == death_page.DISABLED_STYLE_TEXT


def test_death_page_never_claims_a_vanished_style_is_selected(death_page):
    """屏幕上不许有任何一处说「当前已选择<那个已经没了的风格>」。

    原状是个**闭环矛盾**：选择卡说「当前已选择"X"，切换后可以直接点击测试」，
    点了测试它说「还没选风格」。页面把用户送进一个必然失败的动作。
    """
    surfaces = {
        "徽章": _badge_text(death_page),
        "选择卡状态行": death_page.selection_state_label.text(),
        "概况卡标题": death_page.style_overview_name_label.text(),
        "底部操作条": death_page.action_bar.message_label.text()
        if hasattr(death_page.action_bar, "message_label") else "",
    }
    for where, text in surfaces.items():
        assert "当前已选择“已删除的风格”" not in text, f"{where} 还在说它生效：{text!r}"
    # 概况卡的大字标题必须是解析后的值，不能是配置里那个已经没了的名字
    assert death_page.style_overview_name_label.text() == death_page.DISABLED_STYLE_TEXT, (
        f"概况卡标题摆的还是原始配置值：{surfaces['概况卡标题']!r}")


def test_death_page_says_the_old_choice_is_gone_and_how_to_fix(death_page):
    """要把唯一可行动的信息说出来：你原来选的那个没了，重新选一个。"""
    text = death_page.selection_state_label.text()
    assert "已删除的风格" in text and "重新选" in text, f"没说清：{text!r}"


def test_death_page_preview_reports_stale_not_no_style(death_page, reported):
    """点「测试」不许说「还没选风格」—— 用户明明选过。"""
    reported.clear()
    death_page._test_sound()
    assert reported, "点了测试却什么都没说"
    reason, detail = reported[-1]
    assert reason == "stale_style", f"报的是 {reason!r}，应为 stale_style"
    assert str(detail) == "已删除的风格"


def test_death_page_missing_dir_is_not_a_red_error(death_page):
    text = _badge_text(death_page)
    assert "资源 · 异常" not in text, text
    assert "待添加" in text, text


# ------------------------------------------------------ kill_voice 的静默试听

def test_kill_voice_preview_is_never_silent(qapp, monkeypatch, reported):
    """RN-040：kill_voice 点「测试」在未配置时原来**只写一行日志就返回**。

    用户看到的是「点了没反应」（同 UP-037 那一类；其余各页早改了，这页漏下）。
    而且要分清两种情况：真没配 vs 配过但风格已经不在了。
    """
    import pages.kill_voice_page as mod

    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: _GridAudioManager())
    monkeypatch.setattr(mod, "collect_category_health",
                        lambda _roots: {"ok": True, "missing": [], "empty": [],
                                        "invalid": [], "issue_count": 0})
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", dict(_STALE_CONFIG), raising=False)
    monkeypatch.setattr(mod, "report_preview_failure",
                        lambda page, reason, detail=None: reported.append(
                            (getattr(reason, "value", str(reason)), detail)))
    p = mod.KillVoicePage()
    try:
        assert p._stale_weapon_count() == 3, "夹具没造出失效项，下面会空转"
        reported.clear()
        p._test_weapon_voice("weapon_ak47", 1)
        assert reported, "点了测试却什么都没告诉用户"
        assert reported[-1][0] == "stale_style", reported[-1]

        reported.clear()
        p._test_weapon_voice("weapon_mp9", 1)      # 这把压根没配
        assert reported and reported[-1][0] == "no_style", reported[-1]
    finally:
        p.deleteLater()
        qapp.processEvents()


def test_page_help_texts_still_cover_every_sound_page():
    """顺手的存在性守卫：改文案时别把帮助键改没了。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from ui_help_panel import PAGE_HELP_TEXTS

    for page in BADGE_PAGES:
        assert page in PAGE_HELP_TEXTS, f"{page} 的帮助文案不见了"
