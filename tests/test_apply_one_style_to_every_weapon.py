# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-181：一个动作把一个风格配给这一页的全部武器。

## 缺陷

39 把武器 / 34 把枪要**逐个下拉**配置，分散在 6~8 个页签里，没有「一次配完」的入口
（外审 35 发 / 跨 10 页，票数最高；收编旧账 RN-106 与 4 个实例）。

批 50 的行为题调研更直接：给外审看这四页，问「你想让全部 34 把枪都用同一个风格，
会怎么做」—— **30/30 答「找不到」**，而他们在找的词是
「应用到全部武器」7 次、「全局风格」6 次、「一键应用到全部」3 次。
⇒ 按他们说的那个词命名。

⚠⚠ **那一轮的阳性对照没立住**：我拿 `preset_center`（有「一键应用」）当对照，
   而它那颗是「套用精选包」，回答不了「给全部枪配同一风格」—— 对照页也答「找不到」。
   ⭐ 批 43 那条教训第二次：**一个对照组先要证明它真的是对照。**
   ⇒ 改用**改前 / 改后**同题面复跑当证据（改前 30/30 找不到，是干净的基线）。

## 这里守的四件事

1. 这一族每一页都有这个动作 —— ⚠ 分母不许按「继承了哪个基类」划：
   `gun_sound` **不继承 `SoundPageBase`**，而它正是立案原文点名的那一页，
   改基类那一刀天生落不到它头上（实测第一版四页里只有它没拿到）。
2. 下拉里只出现**每一把武器都能用**的风格（取交集）——
   并集里会有某些武器根本没有的风格，套过去就是配了一个解析不出来的值。
3. 它**会覆盖**用户已有设置 ⇒ 必须先问，且那句话里带**确切的数**（RN-506 的线）。
4. 落盘走每页既有的 `_on_weapon_style_changed`，**不另造一条写配置的路**。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

REPO = Path(__file__).resolve().parent.parent

#: RN-181 这一族：每一把武器各有一个风格下拉的页。
#: ⚠ 分母**不按基类划** —— 按「页面上有没有 per-weapon 的风格下拉」划。
FAMILY = {
    "kill_sound": ("pages.kill_sound_page", "KillSoundPage"),
    "kill_voice": ("pages.kill_voice_page", "KillVoicePage"),
    "switch_weapon": ("pages.switch_weapon_page", "SwitchWeaponPage"),
    "gun_sound": ("pages.gun_sound_page", "GunSoundPage"),
    "reload_sound": ("pages.reload_sound_page", "ReloadSoundPage"),
}


@pytest.fixture
def styles_on_disk(tmp_path, monkeypatch):
    """往音效库里造两个**每一把武器都能用**的全局风格。

    ⚠ 不造的话这几条会整齐地 skip 掉 —— 而「覆盖 39 把武器」这件事
    从没被走到过。⭐ **skip 不是 pass，但它在报告上几乎长得一样。**
    """
    import wave

    from resource_manager import ResourceManager

    root = Path(ResourceManager.get_app_data_path("resources/audio"))

    def make(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 400)

    made = []
    styles = ("判据风格甲", "判据风格乙")

    # 全局风格（kill_sound / kill_voice 读这里）
    for style in styles:
        for level in range(1, 6):
            p = root / "kill_sounds" / style / f"{level}.wav"
            make(p)
            made.append(p)
            p = root / "kill_voices" / style / f"{level}.wav"
            make(p)
            made.append(p)

    # ⚠ per-weapon 风格：`switch_weapon` / `reload_sound` / `gun_sound` 读的是
    #   `<目录>/<武器>/<风格>/` —— 第一版夹具只造了全局那一种，
    #   于是这三页拿不到任何选项。⭐ **造了数据不等于被测的东西看得见那份数据。**
    #   只给**一部分**武器造：这样「跳过」那条支路也会被真的走到。
    from core.audio.special_events import SOUND_EVENTS  # noqa: F401  (确保 core 可 import)
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST

    weapons = ["weapon_ak47", "weapon_m4a1", "weapon_awp", "weapon_glock"]
    for sub_dir in ("switch_weapons", "reload_sounds"):
        for weapon in weapons:
            for style in styles:
                p = root / sub_dir / weapon / style / "a.wav"
                make(p)
                made.append(p)
    gun_types = [pf.gun_type for pf in SUPPORTED_GUN_SOUND_PROFILE_LIST[:4]]
    for gun in gun_types:
        for style in styles:
            p = root / "gun_sounds" / gun / style / "a.wav"
            make(p)
            made.append(p)

    # ⚠⚠ 光造出文件还不够：`ensure_styles_scanned()` 用 `_styles_scanned` 这个
    #   **一次性标志**挡住重扫，而这个 manager 是单例 —— 进程里别的测试早就
    #   把它扫过一遍（那时目录还是空的）。
    #   ⭐ **造了数据不等于被测的东西看得见那份数据。**
    from core.audio.runtime_audio import get_runtime_audio_manager

    manager = get_runtime_audio_manager()
    manager._styles_scanned = False
    manager.ensure_styles_scanned()

    yield ("判据风格甲", "判据风格乙")

    for p in made:
        p.unlink(missing_ok=True)
    manager._styles_scanned = False
    manager.ensure_styles_scanned()


def _build(page_id, qapp):
    import importlib
    mod, cls = FAMILY[page_id]
    page = getattr(importlib.import_module(mod), cls)()
    qapp.processEvents()
    return page


@pytest.mark.parametrize("page_id", sorted(FAMILY))
def test_every_page_in_the_family_has_the_action(page_id, qapp):
    """⚠ 第一版只改了 `SoundPageBase`，而 `gun_sound` 不继承它 ——
    四页里**只有立案原文点名的那一页没拿到**。分母按基类划就会漏掉它。
    """
    page = _build(page_id, qapp)
    try:
        assert hasattr(page, "apply_all_btn"), (
            f"{page_id} 没有「应用到全部武器」。⚠ 如果它不继承 `SoundPageBase`，"
            "那就得单独实现一份 —— 改基类落不到它头上。")
        assert page.apply_all_btn.text() == "应用到全部武器", (
            f"按钮文案变了：{page.apply_all_btn.text()!r}。"
            "这个词是行为题调研里玩家自己说得最多的那个（7 次），别随手改。")
        assert hasattr(page, "apply_all_combo") and hasattr(page, "apply_all_hint")
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page_id", sorted(FAMILY))
def test_it_says_why_when_it_cannot_be_used(page_id, qapp):
    """一个风格都没有时，按钮置灰**并说明原因** —— 灰着不说话等于坏了。"""
    page = _build(page_id, qapp)
    try:
        if page.apply_all_btn.isEnabled():
            pytest.skip("这台机器上有可用风格，这条走不到（它守的是空库那一支）")
        assert not page.apply_all_combo.isEnabled()
        hint = page.apply_all_hint.text()
        assert "先导入或新建" in hint, f"置灰了却没说为什么：{hint!r}"
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page_id", sorted(FAMILY))
def test_the_options_never_include_something_no_weapon_has(page_id, qapp, styles_on_disk):
    """下拉里的每个选项，**至少要有一把武器能用**。

    ⚠⚠ 第一版这条钉的是「交集」，而 `switch_weapon` / `reload_sound` / `gun_sound`
    的风格是 **per-weapon** 的（`<目录>/<武器>/<风格>/`）—— 交集在真实配置下
    几乎必然为空。⭐ **那会让这个功能恰好在最痛的那三页上没用**，
    而 RN-181 原文点名的正是那 34 把枪。
    ⇒ 选项用并集；不写坏值这件事交给**套用时跳过**（下一条判据钉它）。
    """
    page = _build(page_id, qapp)
    try:
        page._refresh_style_catalog()
        qapp.processEvents()
        options = [page.apply_all_combo.itemText(i)
                   for i in range(page.apply_all_combo.count())]
        assert options, (
            "造了风格却一个选项都没有 —— 这条判据本来会 skip 过去，"
            "而 skip 在报告上和 pass 几乎长得一样。")
        if page_id == "gun_sound":
            per_weapon = [set(page.weapon_styles.get(g, []) or [])
                          for g in page.weapon_configs]
        else:
            per_weapon = [set(page._style_options_for(w))
                          for w in page._get_all_weapons()]
        assert per_weapon, "一把武器都没扫到 —— 这条判据没了分母"
        for opt in options:
            supported = [i for i, s in enumerate(per_weapon) if opt in s]
            assert supported, (
                f"「{opt}」一把武器都用不了，却出现在「整套套用」的下拉里。")
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page_id", sorted(FAMILY))
def test_it_asks_before_overwriting_and_says_how_many(page_id, qapp, monkeypatch, styles_on_disk):
    """⚠ 这是会覆盖已有设置的动作（RN-506 的破坏性那一侧）：
    必须先问，而且那句话里要有**确切的数**，不是「一些」。
    """
    page = _build(page_id, qapp)
    try:
        page._refresh_style_catalog()
        qapp.processEvents()
        options = [page.apply_all_combo.itemText(i)
                   for i in range(page.apply_all_combo.count())]
        assert options, "造了风格却一个选项都没有"
        page.apply_all_combo.setCurrentIndex(0)

        # ⚠⚠ **起始态得自己保证**：同一个进程里前面那条判据可能已经把这个风格
        #   套上去了（`config` 是单例，跨用例不复位）—— 那样这次就走「无需改动」，
        #   确认框根本不会出现，而断言会报「没问一句」，把我引向完全错误的方向。
        #   ⭐ 判据要造出它要测的那个状态，别指望环境恰好是干净的（同批 48 那条）。
        style0 = page.apply_all_combo.currentText()
        disabled = getattr(page, "DISABLED_STYLE_TEXT", "不启用")
        for weapon in page._weapons_supporting(style0):
            # ⭐ 走产品自己的落盘路径复位 —— 各页 `weapon_rows` 装的东西形状不同
            #   （`WeaponRowWidget` vs dict），摸控件会漏掉一半页。
            page._on_weapon_style_changed(weapon, disabled)
        qapp.processEvents()

        asked = {}

        def fake_question(_parent, title, text, *_a, **_k):
            asked["title"] = title
            asked["text"] = text
            return QMessageBox.No          # 用户点「否」

        monkeypatch.setattr(QMessageBox, "question", fake_question)
        # ⚠⚠ `information` 也必须挡：走到「无需改动 / 没有武器能用」那两条支路时
        #   它会弹**真模态框**，离屏环境下整台测试就挂死在那儿（实测 rc=124）。
        #   ⭐ 只挡自己预期的那一条路，等于赌被测代码不会走别的路。
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
        page._apply_style_to_all_weapons()

        assert asked, "覆盖全部武器之前没有问一句"
        import re
        assert re.search(r"\d+ 把", asked["text"]), (
            f"问的时候没给确切的数：{asked['text']!r}")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_it_reuses_the_existing_write_path():
    """落盘必须走每页既有的 `_on_weapon_style_changed` —— 不许另造一条。

    ⭐ 另造一条的代价不是重复代码，是**两条路会各自漂移**：
    那条既有路径里还带着「卸载旧风格 / 加载新风格 / 刷新运行时」几步。
    """
    for src in (REPO / "pages" / "sound_page_base.py",
                REPO / "pages" / "gun_sound_page.py"):
        tree = ast.parse(src.read_text(encoding="utf-8"))
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_apply_style_to_all_weapons"), None)
        assert fn is not None, f"{src.name} 里没有 `_apply_style_to_all_weapons`"
        body = ast.get_source_segment(src.read_text(encoding="utf-8"), fn) or ""
        assert "_on_weapon_style_changed" in body or "setCurrentText" in body, (
            f"{src.name} 的整套套用没有走既有落盘路径")
        assert "config." not in body.replace("config.json", ""), (
            f"{src.name} 的整套套用在自己直接写 config —— 那是第二条路。")


@pytest.mark.parametrize("page_id", sorted(FAMILY))
def test_it_skips_weapons_that_do_not_have_the_style(page_id, qapp, monkeypatch,
                                                     styles_on_disk):
    """⭐ 用不了这个风格的武器**必须保持原样** —— 绝不写一个解析不出来的值。

    这是「选项用并集」的那一半安全性：并集让功能有用，跳过让它不出错。
    ⚠ 而且确认框要**把跳过的数说出来** —— 只说「全部」会留下一个
    用户以为配了、其实没配的沉默差额。
    """
    page = _build(page_id, qapp)
    try:
        page._refresh_style_catalog()
        qapp.processEvents()
        options = [page.apply_all_combo.itemText(i)
                   for i in range(page.apply_all_combo.count())]
        assert options, "造了风格却一个选项都没有"
        style = options[0]
        page.apply_all_combo.setCurrentText(style)

        # 同上：复位到「都没配」，否则可能走「无需改动」而这条判据什么都没验到
        disabled = getattr(page, "DISABLED_STYLE_TEXT", "不启用")
        for weapon in page._weapons_supporting(style):
            page._on_weapon_style_changed(weapon, disabled)
        qapp.processEvents()

        # ⚠⚠ **不许拿 `_weapons_supporting()` 来定义预期** —— 那正是被测的东西。
        #   第一版就是这么写的：破坏点把它改成「返回全部武器」，于是 `supported`
        #   也跟着变成全部、`untouched` 恒空，整段断言一句都不执行而判据全绿。
        #   ⭐ **判据拿被测函数算出自己的预期，就等于让被告写判决书。**
        #   ⇒ 预期从**磁盘上的真实情况**独立算出来。
        if page_id == "gun_sound":
            supported = {g for g in page.weapon_configs
                         if style in (page.weapon_styles.get(g, []) or [])}
        else:
            supported = {w for w in page._get_all_weapons()
                         if style in page._style_options_for(w)}
        if page_id == "gun_sound":
            everything = set(page.weapon_configs)
            before = {g: page._effective_style(page.weapon_configs[g])
                      for g in everything}
        else:
            everything = set(page._get_all_weapons())
            before = {w: page._configured_style(w) for w in everything}
        assert supported, "一把武器都用不了这个风格 —— 这条判据没了对象"

        asked = {}
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda _p, _t, text, *a, **k: (asked.update(text=text)
                                           or QMessageBox.Yes))
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
        page._apply_style_to_all_weapons()
        qapp.processEvents()

        untouched = everything - supported
        # ⚠⚠ 空转守卫：`kill_sound` / `kill_voice` 的风格是**全局**的，每把武器都有
        #   ⇒ `untouched` 恒空，下面整段一句都不执行，而判据照样绿。
        #   实测：撤掉产品里的「跳过」那一步，这条 5/5 全绿（破坏验证判它假绿）。
        #   ⭐ **一条判据可以在「它要防的那件事根本没机会发生」的页上永远为真。**
        #   ⇒ 那几页改成正面钉住「跳过名单确实是全集」，让它仍然在说话。
        if not untouched:
            assert supported == everything, (
                f"{page_id}：没有用不了这个风格的武器（全局风格页），"
                "那么『能用它的武器』必须就是全部 —— 现在对不上，说明 "
                "`_weapons_supporting` 算错了。")
        if untouched:
            assert "保持原样" in asked.get("text", ""), (
                f"有 {len(untouched)} 把武器会被跳过，而确认框没说：{asked.get('text')!r}")
        for weapon in untouched:
            now = (page._effective_style(page.weapon_configs[weapon])
                   if page_id == "gun_sound" else page._configured_style(weapon))
            assert now == before[weapon], (
                f"{weapon} 用不了「{style}」，却被改成了 {now!r} —— "
                "那是一个它自己也解析不出来的值（RN-026 那一族）。")
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page_id", sorted(FAMILY))
def test_compact_hides_the_row_but_not_the_ability(page_id, qapp):
    """⭐ 紧凑档（860×640）藏的是**控件**，不是**能力**。

    ⚠ 实测：那一行放在状态卡里会把整页顶出可视区 60px 上下，而这一族本来
    就欠着 64px 的在册债（RN-196）；把行高 32→26 只换回 4px ⇒
    **不是它太高，是那张卡装不下第七行**；挪到卡外、页签之上更糟（39 处）。
    ⇒ 紧凑档把那一行藏起来，动作改从底栏够得着。
    ⛔ 藏了控件却没给替代入口 = 那个动作在紧凑档消失了 —— 这条钉的就是这件事。
    """
    page = _build(page_id, qapp)
    try:
        page.resize(1200, 800)
        qapp.processEvents()
        page._sync_apply_all_visibility()
        assert page.apply_all_btn.isVisibleTo(page), "完整档反而看不到那一行"

        page.resize(860, 548)
        qapp.processEvents()
        page._sync_apply_all_visibility()
        assert not page.apply_all_btn.isVisibleTo(page), (
            "紧凑档还摆着那一行 —— 它会把整页顶出可视区")

        # 能力还在：紧凑档下必须有一个够得着的入口
        entry = (getattr(page, "_apply_all_menu_action", None)
                 or getattr(page, "_apply_all_compact_btn", None))
        assert entry is not None, (
            f"{page_id}：紧凑档把那一行藏了，却没有任何替代入口 —— "
            "那不是「换个地方」，是「这个动作在紧凑档消失了」。")
        assert callable(getattr(page, "_pick_style_and_apply_to_all", None)), (
            "替代入口没有对应的动作实现")
    finally:
        page.deleteLater()
        qapp.processEvents()
