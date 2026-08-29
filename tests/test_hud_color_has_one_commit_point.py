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
from pathlib import Path

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

def test_the_preset_button_does_not_sound_like_a_commit():
    """① 预设那颗按钮不许听起来像「这一步就生效了」。

    ⭐ 它的**行为**一直是对的（只 `_apply_rules_to_ui` + `_set_dirty(True)`），
    所以这条判的是词，不是行为 —— 而下面那条判行为。
    """
    text = _preset_button_text()
    assert text, "找不到预设那颗按钮的文案 —— 判据瞎了，下面几条会无条件通过"
    hit = [w for w in COMMIT_WORDS if w in text]
    assert not hit, (
        f"预设按钮的文案是 {text!r}，含提交词 {hit} —— "
        "外审 4/6 票说它和底栏那颗构成「双重确认」。\n"
        "⭐ 一个动作只有一个生效点；这一颗只负责**载入到编辑区**。"
    )


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
