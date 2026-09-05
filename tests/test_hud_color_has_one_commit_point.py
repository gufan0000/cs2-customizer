# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-175 / RN-129 / RN-131 / RN-426：`hud_color` 上「什么时候真的写进游戏」说不清。

外审 **4/6 票**：「应用预设」与底栏「保存 HUD 规则」构成**双重确认**，
玩家分不清点了预设是否已生效、改完还要不要再保存 —— 而顶部同时写着「已同步」。

## ⭐ 这一页的行为一直是对的，错的是三个词

查实 `_apply_preset()`：它只做 `_apply_rules_to_ui()` + `_set_dirty(True)`，
**一个字节都没写进游戏**。真正写盘 + 写 cfg + 挂 autoexec 的只有 `_save_hud_rules()`。

⇒ 「一个动作只有一个生效点」这件事**代码里早就成立**，是界面在说反话：

| 词 | 它让人以为 | 实际 |
|---|---|---|
| 按钮「**应用**预设」 | 这一步生效了 | 只填进编辑区 |
| 胶囊「保存 · 已**同步**」 | 已经同步到游戏里跑起来了 | 只是写盘了（RN-426）|
| 底栏「要点一下保存才会**写入**」 | 写到哪儿？写完就完了吗？ | 没说怎么在游戏里生效（RN-131）|

⚠ RN-426 的要害在登记册里写着：这句「已同步」**在总开关关着时也是真话** ——
⭐⭐ **一句真话被读成另一件事，和一句假话，要用两种修法**：
前者不能靠「改成正确的说法」修，它本来就正确 ⇒ 只能换掉那个一词两义的词。

## ⭐ 那句常驻说明只描述代码真做过的事

`_save_hud_rules()` 实测三步：`config.save_config()` → `write_cs2customizer_cfg()` →
`setup_autoexec()`（往 `autoexec.cfg` 里写 `exec cs2customizer.cfg` 并保证它排最后）。

⇒ 文案说「写进游戏的 cfg，并挂进 autoexec」「当局要立刻见效就在控制台敲
`exec cs2customizer.cfg`」—— **每一分句都有代码支撑**。
⛔ 不写「下次进游戏会自动生效」：那是**游戏**会不会执行 autoexec，
我没有证据 —— ⭐ **描述我们做了什么，不承诺别人会怎样**（RN-011 / RN-254）。
"""
from __future__ import annotations

import ast
import sys

import pytest
from pathlib import Path
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PAGE = REPO / "pages" / "hud_color_page.py"

# ⚠ 判据 ⑥ 要真的把页面建出来（那条回执是运行时拼的），
#   复用那份离屏主窗夹具（含设备页中和、拦模态框）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

main_window = _shared_main_window

#: 读起来像「这一步就生效了」的词。⚠ 只查**预设那一颗按钮**的文案，
#: 不查全页 —— 底栏那颗**就该**用「保存」，它是唯一的生效点。
COMMIT_WORDS = ("应用", "生效", "保存", "写入", "同步")

#: 一词两义的词：它同时指「写盘」和「在游戏里跑起来」，而玩家读的是后一个。
AMBIGUOUS_IN_CHIP = ("同步",)


def _consts(node) -> list[str]:
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _page_tree():
    return ast.parse(PAGE.read_text(encoding="utf-8"))


def _preset_button_text() -> str:
    """`apply_profile_btn = QPushButton("…")` 里那个字面量。"""
    for node in ast.walk(_page_tree()):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if (isinstance(t, ast.Attribute) and t.attr == "apply_profile_btn"
                    and isinstance(node.value, ast.Call)):
                args = [a for a in node.value.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if args:
                    return args[0].value
    return ""


def _function(name: str):
    for node in ast.walk(_page_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


# ------------------------------------------------------------------ 判据

# ⛔⛔ 这里原本是判据 ①「预设那颗按钮不许听起来像『这一步就生效了』」。
#   **2026-09-03 批 43 删除** —— 它盯的那颗按钮（「载入这套」）被 RN-501 删了。
#
# ⭐ 它是**红着**离开的，不是绿着：它开头那句
#   `assert text, "找不到预设那颗按钮的文案 —— 判据瞎了"` 是一道分母守卫，
#   按钮一没它当场报「判据瞎了」。⇒ **对象被删掉的判据来找了我，
#   而不是安静地变成一条恒真的断言。** 这正是 RN-469 那一族要的东西。
#
# ⚠ 按批 33 的规矩处置：**要么改钉现在的唯一入口，要么删掉它；
#   留着改成恒真是最坏的一种。** 这里选删 —— 它想守的「一个动作只有一个生效点」
#   现在由 ⑨ `test_using_a_preset_takes_one_action_not_two` **结构性地**守着
#   （连那颗按钮都不许存在，就谈不上它的文案像不像提交）。
#   ⭐ 一条判据被另一条更硬的判据完全覆盖时，留着它只是多一份会腐烂的副本。
#
# ⚠ `_preset_button_text()` 与 `COMMIT_WORDS` 一并保留：⑨ 报错时要拿它们说人话。


def test_applying_a_preset_still_writes_nothing_to_the_game():
    """② 而它的**行为**也不许变：预设只填编辑区，不许碰配置或写 cfg。

    ⚠ 光钉住文案是不够的 —— 词改对了、哪天有人给它加一句
    `config.save_config()`，双重确认就又回来了，而 ① 全绿。
    ⭐ **一条管措辞的判据，和一条管行为的判据，谁也替不了谁。**
    """
    fn = _function("_apply_preset")
    assert fn is not None, "`_apply_preset` 不见了"
    called = {
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    forbidden = called & {"save_config", "write_cs2customizer_cfg", "setup_autoexec",
                          "write_runtime_cfg", "_save_hud_rules"}
    assert not forbidden, (
        f"`_apply_preset` 里调了 {sorted(forbidden)} —— 它就成了第二个生效点。"
    )


def test_the_save_state_chip_does_not_say_synced():
    """③ 状态胶囊不许用「同步」——它一词两义，而玩家读的是「在游戏里跑起来了」。

    ⚠ RN-426 的要害：那句话**在总开关关着时也是真话**（它由 `_dirty` 决定，
    说的是「你的改动已经写出去了」）。
    ⭐⭐ **一句真话被读成另一件事，和一句假话，要用两种修法** ——
    前者不能靠「改成正确的说法」修，它本来就正确；只能换掉那个词。
    """
    fn = _function("_sync_status_strip")
    assert fn is not None, "`_sync_status_strip` 不见了"
    texts = _consts(fn)
    assert texts, "状态胶囊一条文案都没读到 —— 判据瞎了"
    bad = [t for t in texts if any(w in t for w in AMBIGUOUS_IN_CHIP)]
    assert not bad, (
        f"状态胶囊里还留着一词两义的词：{bad}\n"
        "⭐「同步」同时指「写盘」和「在游戏里跑起来」，玩家读的是后一个。"
    )


def test_the_bottom_bar_says_how_it_takes_effect_in_game():
    """④ 底栏那句常驻说明必须回答「保存完之后，游戏里怎么才见效」。

    ⭐ RN-131 的裁定：做成**常驻一行**，位置在**生效按钮旁**，
    ⛔ 不进模态框（关掉就没了）、⛔ 不放页尾
    （官网那轮外审两轮 6 发说「藏在底部小字里」＝没放）。

    ⚠ 判据认的是那条**可操作的指令**，不是某种措辞：
    只要屏幕上有 `exec cs2customizer.cfg`，玩家就有得照做。
    """
    fn = _function("_refresh_dirty_ui")
    assert fn is not None, "`_refresh_dirty_ui` 不见了"
    # ⚠ 分母只取**真正进底栏那句话**的字面量，即 `set_message(...)` 的实参。
    #   第一版扫了整个函数的字面量，于是把 `save_btn.setText("保存 HUD 规则")`
    #   也当成了「底栏说明」，报它没写 `exec cs2customizer.cfg` ——
    #   ⭐ 一颗按钮的文案和一句状态说明是两种东西，判据得分得清。
    messages = [
        a.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "set_message"
        for a in ast.walk(n)
        if isinstance(a, ast.Constant) and isinstance(a.value, str)
    ]
    assert len(messages) >= 2, (
        f"底栏只读到 {len(messages)} 条 `set_message` 文案 —— "
        "它有「有改动 / 已保存」两态，判据瞎了"
    )
    missing = [m for m in messages if "exec cs2customizer.cfg" not in m]
    assert not missing, (
        "底栏这几句没说清「游戏里怎么才见效」：\n  "
        + "\n  ".join(repr(m) for m in missing)
        + "\n⭐ 那句指令原来只在**成功模态框**里出现过一次，关掉就没了。"
    )


def _edit_persists_without_pressing(page, button_text: str) -> bool:
    """这一页改一个控件，**不点任何按钮**，配置就变了吗？

    变了 ⇒ 那颗带「应用」字样的按钮不是提交点，底栏说「自动保存」是**真话**。
    ⭐ 这不是白名单：它每次都真的改一下、真的读一遍配置。
      哪天这一页改成「要点了才生效」，这里立刻证不出来，判据自动开始报它。

    ⚠ 只对**有 per-weapon 风格下拉**的页成立（它们有 `_on_weapon_style_changed`
      这条既有落盘路径可以拿来验）；别的页一律返回 False = 不给例外。
    """
    changer = getattr(page, "_on_weapon_style_changed", None)
    reader = getattr(page, "_configured_style", None)
    weapons = getattr(page, "_get_all_weapons", None)
    if callable(changer) and not callable(reader):
        # ⚠ `gun_sound` 不继承 `SoundPageBase`，读写用的是另一套名字
        #   （`weapon_configs` / `_effective_style`）——**同一件事两套 API**。
        #   按一套名字找，就会漏掉那一页（本批第二次踩到同一件事）。
        configs = getattr(page, "weapon_configs", None)
        # ⚠ 读**配置里写着什么**（`_get_profile_style`），不是读解析后的值：
        #   `_effective_style` 会把「风格已不在」解析回 '0'，于是喂什么进去
        #   都读回 '0'，探针永远看不到变化（实测就是这样卡住的）。
        raw = getattr(page, "_get_profile_style", None)
        if isinstance(configs, dict) and callable(raw):
            weapons = lambda: list(configs)      # noqa: E731
            reader = lambda g: raw(configs[g])   # noqa: E731
    if not (callable(changer) and callable(reader) and callable(weapons)):
        return False
    try:
        names = list(weapons())
        if not names:
            return False
        weapon = names[0]
        before = reader(weapon)
        # ⚠ 不能依赖「磁盘上有别的风格可选」——空库时只有「不启用」一个选项，
        #   证据取不到，例外就假装不成立（实测五页全被误判）。
        #   ⇒ 直接喂一个**当前值以外**的值给落盘路径，看它认不认。
        #   认了就说明「改一下就存」，那颗带「应用」字样的按钮不是提交点。
        probe = "不启用" if str(before) not in ("0", "", "不启用") else "__probe__"
        changer(weapon, probe)
        after = reader(weapon)
        changer(weapon, before if str(before) not in ("", None) else "0")
        return str(after) != str(before)
    except Exception:
        return False


def test_no_page_says_no_button_needed_while_showing_a_button(main_window, qapp):
    """⑥ 跨页：底栏那条共用回执不许在**摆着必须点的按钮**的页上说「不用点任何按钮」。

    ⚠⚠ 这条不是 hud_color 一页的事，是**共用件的分母错了**：批 16 把
    「改动已自动保存」当成了全站事实，铺到 15 页。批 24 实测 **15 页里 2 页不是**
    （`hud_color` 摆着「保存 HUD 规则」、`magnifier` 摆着「应用」「应用偏移」）——
    于是同一行底栏里，左边说「不用点任何按钮」，右边就是那颗必须点的按钮。

    ⭐⭐ **一句被当成全站事实的话，只要有一页不成立，它在那一页就是假的** ——
    而共用件让它假得整整齐齐，15 页一个模子。
    ⭐ **共用件省的是重复，不是判断。**

    ⚠ 分母由机器自己找（带 `master_switch_row` 的页 × 页上带提交词的可见按钮），
    **不是一张手写名单** —— 将来哪一页加了保存按钮，这条会自己报到。
    """
    from PySide6.QtWidgets import QPushButton

    from widgets import master_switch_effect as eff

    commit_words = ("保存", "应用", "写入", "提交")
    checked, bad = [], []
    for page_id in list(main_window._page_names.keys()):
        try:
            main_window.ensure_page_loaded(page_id)
            main_window.show_page(page_id, animated=False, force=True)
            qapp.processEvents()
        except Exception:
            continue
        page = main_window.pages.get(page_id)
        if page is None or getattr(page, "master_switch_row", None) is None:
            continue
        checked.append(page_id)
        buttons = [b.text().strip() for b in page.findChildren(QPushButton)
                   if b.isVisibleTo(page) and b.text()
                   and any(w in b.text() for w in commit_words)]
        # ⚠⚠ 批 50：这几个词认的是**字面**，不是事实。「应用到全部武器」
        #   含「应用」二字，但它是**动作**不是提交 —— 不点它，你逐个改的
        #   那些照样已经落盘了。判成「说假话」是这条判据自己认错了。
        # ⛔ 不给它开名单白名单（那正是 RN-483/511/521/522 那一族的病）。
        # ⇒ 例外**用证据换**：这一页得当场证明「改一个控件就落盘」。
        #   证不出来的，照旧算它说假话。
        buttons = [t for t in buttons
                   if not _edit_persists_without_pressing(page, t)]
        if buttons and eff.saves_automatically(page):
            bad.append(f"{page_id}：摆着 {buttons} 却仍用「自动保存」那套回执")
    assert len(checked) >= 12, f"只量到 {checked} —— 分母塌了（实测应有 15 页）"
    assert not bad, "\n  ".join(["这些页的底栏回执在说假话："] + bad)


def test_the_success_dialog_is_not_the_only_place_that_says_it():
    """⑤ ⚠ 反向守卫：不许把常驻那行删掉、退回「只有模态框里写过」。

    ⭐ RN-131 就是这么来的 —— 成功框里明明写着 `游戏内执行: exec cs2customizer.cfg`，
    而外审仍有 3 发在问「是自动生效还是要在控制台输入指令」。
    **一句只在模态框里出现过的说明，等于没有说明。**
    """
    dialog_fn = _function("_save_hud_rules")
    bar_fn = _function("_refresh_dirty_ui")
    in_dialog = any("exec cs2customizer.cfg" in t for t in _consts(dialog_fn or ast.parse("")))
    in_bar = any("exec cs2customizer.cfg" in t for t in _consts(bar_fn or ast.parse("")))
    assert not (in_dialog and not in_bar), (
        "`exec cs2customizer.cfg` 只在保存成功的模态框里说过 —— 关掉就没了。"
    )


# ============================================================ 批 43：RN-501 / RN-438
#
# ⭐⭐⭐ **下拉已经在改规则了，只是改了一半，而屏幕上没有任何东西说它改了。**
#
# 实测（批 43 探针，`balanced_default` vs `tactical` 两套一共差 **13 个字段**）：
#
#   | | 字段数 |
#   |---|---|
#   | **只动下拉就已经跟着新预设走**（界面上看不见的：持续时间/间隔/阈值/回合态…）| **12** |
#   | 必须点「载入这套」才变（界面上看得见的：`kill.effect`）| **1** |
#
# 成因在 `_build_rules_from_ui()`：它**从下拉当前选中的 profile 起手**
# （`rules = get_default_hud_rules(profile)`），再把界面上看得见的那几项覆盖回去。
# ⇒ 界面上没有的字段跟着**下拉**走，看得见的跟着**编辑区**走。
#
# ⚠ 于是那颗按钮旁边那句提示 ——「载入只是把这套规则填进下面的编辑区，还没写进游戏」
#   —— **是反的**：一大半规则根本不经过编辑区，从下拉直达保存。
#   而它正是外审行为题 9/9 答对时逐字抄出来的依据。
#   ⭐⭐ **一句假话可以替版面承担理解，而且答对率会很好看。**
#
# ⇒ 修法：**下拉即载入**，删掉那颗按钮（3 步 → 2 步）。
#   理由第三条来自批 40：**一个机制收窄到只剩一个用例之后，
#   问那一个用例是不是也可以不由它来做** —— 这颗按钮的用例只剩 1/13 个字段。

@pytest.fixture(autouse=True)
def _leave_the_page_clean(request):
    """⚠⚠ 离场时必须把这一页的「未保存」标记清掉，否则**整轮 pytest 挂死**。

    实测（批 43）：新判据把页面留成 dirty ⇒ 夹具拆卸时 `win.close()`
    走到 `can_leave_page()` 的 `msg.exec()` —— 一个**离屏模态框**，
    没有人能点它，pytest 就停在那里，报告上看不出任何异常。

    ⭐⭐ 这是同一个形状第二次咬人（批 40：确认框从 `QMessageBox.question`
    改成实例 `box.exec()` 之后，测试原钩子不报错地失效、整轮挂死）。
    ⇒ **凡是会把页面改脏的判据，必须自带一条离场清理** ——
      而它得写成 fixture，不能写在函数末尾：断言失败时那一行根本跑不到。
    """
    yield
    win = request.node.funcargs.get("main_window")
    page = getattr(win, "pages", {}).get("hud_color") if win is not None else None
    if page is not None and hasattr(page, "_set_dirty"):
        page._set_dirty(False)


def _hud_page(main_window, qapp):
    main_window.ensure_page_loaded("hud_color")
    main_window.show_page("hud_color", animated=False, force=True)
    qapp.processEvents()
    page = main_window.pages.get("hud_color")
    assert page is not None, "hud_color 页没建出来 —— 下面几条会无条件通过"
    return page


def _profile_values(page):
    return [page.profile_combo.itemData(i) for i in range(page.profile_combo.count())]


def _load(page, qapp, index):
    """把某一套预设**真的载进编辑区**（不管它是靠下拉自动载入还是靠按钮）。

    ⭐ 判据不该假设修法长什么样：改成「下拉即载入」之后，
    `setCurrentIndex` 自己就完成了；在那之前还得补一次 `_apply_preset()`。
    两种世界里这个 helper 都成立。
    """
    page.profile_combo.setCurrentIndex(index)
    qapp.processEvents()
    if hasattr(page, "_apply_preset"):
        page._apply_preset()
        qapp.processEvents()


def _flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def test_choosing_a_preset_leaves_no_half_applied_state(main_window, qapp):
    """⑦ **RN-501**：换了下拉之后，编辑区必须整套都是那一套，不许是两套各一半。

    判据形状：拿两套**真的不一样**的预设，只动下拉、不做别的，
    然后比 `_build_rules_from_ui()` 与那一套预设的差异字段。
    ⭐ 分母是「这两套预设之间真正不同的字段」——它一空，这条判据什么都没测。
    """
    from core.hud.rule_model import get_default_hud_rules

    page = _hud_page(main_window, qapp)
    values = _profile_values(page)
    base, other = "balanced_default", "tactical"
    assert base in values and other in values, f"预设名变了：{values}"

    differ = must_scan(
        [k for k, v in _flat(get_default_hud_rules(base)).items()
         if _flat(get_default_hud_rules(other)).get(k) != v],
        f"{base} 与 {other} 之间真正不同的字段", least=5)

    # ⚠⚠ **这一步不能省：先真的把 base 载进编辑区。**
    #   第一版判据只 `setCurrentIndex(base)` 就换到 other，**当场全绿** ——
    #   因为界面上那几项从来没被设成过 base 的值，`_build_rules_from_ui`
    #   起手用的又是 other 的默认值，两边碰巧一致。
    # ⭐⭐ **那个混合态只在「先载入过一套、再换下拉」时出现** ——
    #   而那正是「换一套预设」的真实动线（RN-438 说的就是它）；
    #   第一次挑预设时它不出现。
    # ⭐ 一条判据的 setup 少一步，它测的就是另一条动线了。
    _load(page, qapp, values.index(base))
    page.profile_combo.setCurrentIndex(values.index(other))
    qapp.processEvents()

    now = _flat(page._build_rules_from_ui())
    want = _flat(get_default_hud_rules(other))
    stale = [k for k in differ if now.get(k) != want.get(k)]
    assert not stale, (
        f"只换了下拉，{len(stale)}/{len(differ)} 个字段还停在上一套预设上：\n  "
        + "\n  ".join(f"{k}: 现在={now.get(k)!r} 应为={want.get(k)!r}" for k in stale[:8])
        + "\n⭐ 屏幕上只报一个预设名，而规则是两套各一半 —— 保存会把这个混合体写进游戏。"
    )


def test_the_page_never_names_a_preset_it_has_not_loaded(main_window, qapp):
    """⑧ **RN-501 的另一半**：屏幕上报的预设名，必须是编辑区里真正那一套。

    ⚠ 这条和 ⑦ 分开写：⑦ 管「规则对不对」，⑧ 管「屏幕说得对不对」。
    ⭐ 一条管数据的判据，和一条管屏幕的判据，谁也替不了谁（同本文件 ①②）。
    """
    from PySide6.QtWidgets import QLabel

    from core.hud.rule_model import get_default_hud_rules

    page = _hud_page(main_window, qapp)
    values = _profile_values(page)
    _load(page, qapp, values.index("balanced_default"))
    page.profile_combo.setCurrentIndex(values.index("tactical"))
    qapp.processEvents()

    named = must_scan(
        [(lb.objectName() or "QLabel", lb.text().strip())
         for lb in page.findChildren(QLabel)
         if not lb.isHidden() and "预设" in (lb.text() or "")],
        "屏幕上提到预设的可见文字", least=1)

    want_label = page.profile_combo.currentText()
    now = _flat(page._build_rules_from_ui())
    truth = _flat(get_default_hud_rules("tactical"))
    editor_matches = all(
        now.get(k) == v for k, v in truth.items()
        if k in _flat(get_default_hud_rules("balanced_default"))
        and _flat(get_default_hud_rules("balanced_default"))[k] != v)

    lying = [(n, t) for n, t in named if want_label in t] if not editor_matches else []
    assert not lying, (
        f"屏幕上有 {len(lying)} 处报着「{want_label}」，而编辑区里不是那一套：\n  "
        + "\n  ".join(f"[{n}] {t}" for n, t in lying)
        + "\n⭐ 一个只在某个状态下为真的名字，在别的状态里就是一句谎。"
    )


def test_using_a_preset_takes_one_action_not_two(main_window, qapp):
    """⑨ **RN-438**：挑一套预设是**一个**动作，不是「选 + 载入」两个。

    ⚠ 这条不是"少一颗按钮好看"，它钉的是 ⑦⑧ 那个混合态**在结构上不可能出现** ——
    只要还有一颗按钮负责「把下拉里的东西搬进编辑区」，
    那两者之间就存在一个屏幕在说谎的窗口。
    ⭐ 批 40：**一个机制收窄到只剩一个用例之后，问那一个用例是不是也可以不由它来做。**
      实测那颗按钮的用例只剩 13 个差异字段里的 1 个。
    """
    from PySide6.QtWidgets import QPushButton

    page = _hud_page(main_window, qapp)
    buttons = must_scan(
        [b.text().strip() for b in page.findChildren(QPushButton)
         if not b.isHidden() and b.text().strip()],
        "hud_color 页上可见的按钮", least=1)
    loaders = [t for t in buttons if any(w in t for w in ("载入", "套用", "应用预设"))]
    assert not loaders, (
        f"预设卡里还有一颗搬运按钮：{loaders}\n"
        "⇒ 挑预设应当在下拉那一下就完成（RN-438：三步 → 两步），"
        "而那一步与保存之间不许再插一个「已经选了但还没搬过去」的状态。"
    )


def test_switching_presets_keeps_the_hand_tuned_number_keys(main_window, qapp):
    """⑩ 换预设不许动用户手调的**数字键**那 9 项。

    ⚠ 这条锁的是一个**实测事实**，不是一个愿望：`_apply_preset` 明写着
    `preset_rules["key_rules"] = current_rules["key_rules"]`，批 43 探针实测
    9 项 0 项被覆盖。⇒ 「下拉即载入」之所以敢做，全靠这一条成立。
    ⭐ **一个结论所依赖的事实，要有判据看着**（批 8 那条）。
    """
    page = _hud_page(main_window, qapp)
    values = _profile_values(page)
    _load(page, qapp, values.index("balanced_default"))

    keys = must_scan(list(page.key_widgets)[:3], "数字键控件", least=3)
    for k in keys:
        page.key_widgets[k]["enabled"].setChecked(True)
        page.key_widgets[k]["color"].setCurrentIndex(3)
    before = {k: (page.key_widgets[k]["enabled"].isChecked(),
                  page.key_widgets[k]["color"].currentData()) for k in keys}

    page.profile_combo.setCurrentIndex(values.index("tactical"))
    qapp.processEvents()

    after = {k: (page.key_widgets[k]["enabled"].isChecked(),
                 page.key_widgets[k]["color"].currentData()) for k in keys}
    clobbered = [k for k in keys if before[k] != after[k]]
    assert not clobbered, (
        f"换预设把用户手调的数字键覆盖了：{clobbered}\n  "
        + "\n  ".join(f"{k}: {before[k]} -> {after[k]}" for k in clobbered)
    )


def test_the_event_rows_share_one_set_of_columns(main_window, qapp):
    """⑪ **RN-503**：事件响应各行的「颜色 / 效果」下拉必须落在同一列上。

    ⚠ 这条不是我先写的，是**外审 4 发报「两行未对齐」、我实测复量之后**才写的
    （CLAUDE.md：它报几何问题一律实测复量再定性 —— 这次连成因都说对了）。
    实测：`kill` 行的颜色下拉 x=303、`death` 行 x=327，**差 24px**；效果下拉同样差 24px。
    成因是复选框文案「击杀变色」(4 字) 与「被击杀变色」(5 字) 差一个字。

    ⭐ 紧挨着的上一张卡（数字键映射）用 `QGridLayout`，所以它一直是齐的 ——
      **同一页上两张卡，一张对齐一张不对齐**，这正是外审看见的东西。
    ⭐ **对齐不是靠每行小心翼翼，是靠让它们共用一套列。**

    ⚠⚠ **这条判据的第一版量的是像素坐标，破坏验证当场判它假绿。**
    原因不是逻辑错，是**这个进程量不到像素**：`QT_QPA_PLATFORM=offscreen`
    下没有中文字体，两个复选框的文字都是零宽 ⇒ 实测两行 `w` 都是 **32**、
    x 都是 **66**，天然「对齐」，无论布局怎么写它都绿。
    ⭐⭐⭐ **一个没有字体的进程，会让任何量「形状」的判据量到一个用户从没见过的版面**
      —— 这句话逐字写在 `test_status_chips_do_not_look_clickable.py` 顶部，
      而我在同一个仓里又写了一条这样的判据。
      ⭐ **知道一条教训，和在下一次动手时用上它，是两件事**（RN-469 那条的第三次现身）。
    ⇒ 改成量**结构**：对齐在这里是一个结构事实（共用一个 `QGridLayout` 的列），
      不是一个像素事实。⭐ **能用结构表达的不变量，别拿像素去量。**
    """
    from PySide6.QtWidgets import QGridLayout

    page = _hud_page(main_window, qapp)
    families = {
        "颜色": must_scan(list(page.event_color_combos.items()), "事件行的颜色下拉", least=2),
        "效果": must_scan(list(page.event_effect_combos.items()), "事件行的效果下拉", least=2),
    }
    # ⚠ `combo.parentWidget().layout()` 拿到的是**卡片**的布局，不是装着它的那个 ——
    #   事件那张网格是 `eg.addLayout(...)` 嵌进去的**嵌套布局**，不挂在任何 widget 上。
    #   ⭐ 判据第二版就栽在这一步：它报「不在 QGridLayout 里」，而它其实在。
    grids = must_scan(page.findChildren(QGridLayout), "页面里的网格布局", least=1)

    def _owning_grid(w):
        for g in grids:
            if g.indexOf(w) >= 0:
                return g
        return None

    bad = []
    for what, items in families.items():
        cols = {}
        for key, combo in items:
            grid = _owning_grid(combo)
            if grid is None:
                bad.append(f"「{what}」·{key}：不在 QGridLayout 里 ⇒ 这一行自己算列宽")
                continue
            idx = grid.indexOf(combo)
            cols[key] = grid.getItemPosition(idx)[1] if idx >= 0 else None
        if len(set(cols.values())) > 1:
            bad.append(f"「{what}」下拉不在同一列上：{cols}")
    assert not bad, (
        "\n  ".join(["事件响应各行没有共用一套列："] + bad)
        + "\n⇒ 用 `QGridLayout` 把它们放进同一组列（同这一页上面那张数字键卡）。"
        + "\n⚠ 实测（有字体的真窗口）：不共用列时颜色下拉 x=303 vs 327、效果 683 vs 707，"
        "都差 24px —— 成因是复选框文案差一个字。"
    )


def test_no_copy_claims_an_unsaved_state_while_the_page_is_clean(main_window, qapp):
    """⑫ **RN-502**：页面干净时，屏幕上不许有任何一句说「还没写进游戏」。

    ⚠⚠ 这条是**我自己这一批引入的缺陷**逼出来的，外审 **8/12 判高**：
    我把预设卡那句提示从**条件句**（「**载入**只是把这套规则填进编辑区，
    还没写进游戏」—— 主语是那个动作，任何时候都为真）改成了**无条件陈述**
    （「…；还没写进游戏，点右下角保存」），而顶部状态胶囊同时写着「保存 · 已存下」。

    ⭐⭐⭐ **把一句条件句改成陈述句，就把一句永远为真的话，
    变成了一句多数时候为假的话。**
    ⇒ 说**动作的后果**，不说**当前的状态**：状态归状态条管。
    """
    from PySide6.QtWidgets import QLabel

    page = _hud_page(main_window, qapp)
    page._set_dirty(False)
    qapp.processEvents()

    visible = must_scan(
        [(lb.objectName() or "QLabel", (lb.text() or "").strip())
         for lb in page.findChildren(QLabel)
         if not lb.isHidden() and (lb.text() or "").strip()],
        "页面干净时屏幕上的可见文案", least=5)

    # ⚠ 只抓**断言当前状态**的说法；「换完要点保存才写进游戏」这种讲因果的不算。
    claims = [(n, t) for n, t in visible
              if ("还没写进游戏" in t or "尚未写进游戏" in t or "未写进游戏" in t)]
    assert not claims, (
        "页面是干净的（没有未保存改动），屏幕上却有话说「还没写进游戏」：\n  "
        + "\n  ".join(f"[{n}] {t}" for n, t in claims)
        + "\n⭐ 顶部状态胶囊此时写的是「保存 · 已存下」—— 同屏两句话互相打架。"
    )
