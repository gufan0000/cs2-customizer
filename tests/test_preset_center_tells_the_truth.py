# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 38（2026-09-01）：预设中心这一页说的话，和它做的事对不对得上。

## 主刀：**这一页把「你想打包哪些」当成了「你改了哪些」**

`_on_selection_changed` 里有一句 `self.mark_dirty()`。勾一下「局内视角」
—— 一个纯粹的「这一套包含哪些」的**选择** —— 实测 config 里
**0 个键**发生变化（57 个会被写回的键逐个深拷贝比对过），
而这一句让页面进入 dirty 态。dirty 在 `DirtyPageMixin` 里带着一项权力：

    can_leave_page() → QMessageBox「当前页面有未保存修改，是否保存后离开？」

⇒ 实测四步，每一步都长得完全正常，每一步都是假的：

  ① 勾一下      → 胶囊「状态 · 待应用」          假状态
  ② 底栏        → 「有未应用的预设变更。」        假句子
  ③ 想离开这一页 → 模态框拦人，can_leave_page()=False   假拦截
  ④ 点「保存并离开」→ `_save_changes()` 改动 **0 个键**，
                     却弹「已应用类型: hud_rules, screen_effects, …」 假成功

⭐⭐⭐ **一个假前提，会一路把四个各自正确的机制变成四句假话。**
那四个机制（dirty 标志、状态胶囊、离开确认、应用回执）单看每一个都没写错，
错的是它们共用的那个前提：「这一页有一种叫『未保存的修改』的东西」。

## ⭐⭐ 为什么外审替它作了不在场证明

改前 12 发问「你现在按下『应用当前预设』，软件里会发生什么」：
**0/12 答「会有变化」**，7/12 答「不会有变化」（依据逐字是那颗「状态 · 已同步」胶囊）。
也就是说 —— **它答对了**。

因为上面那四步里，**只有第 ①② 步在屏幕上，而它们要等用户动一下才出现**；
③④ 一个是模态框、一个是 config 的字节，都不在任何一张截图里。

⭐⭐ **看图这把尺子量的是「这一屏此刻说了什么」，量不到「你动一下之后它会说什么」。**
不是尺子方向反了（批 32），是**这个缺陷只在时间轴上存在**，而截图没有时间轴。
⇒ 这一条只能由判据钉住。

## 另一半：**底栏那句话点名的类别，是一份对不上的半份清单**

底栏构造时写死「支持 HUD / 屏幕特效 / 特殊音效 **三域**预设。」，
而同屏往上 250px 就摆着 **7 个**勾选框，引擎 `SUPPORTED_TYPES` 也是 **7** 类。
外审 12 发 **12/12 答「7 类」、12/12 答「矛盾: 有」**，11/12 逐字抄出了那句话。

⭐ 而这句话还是**一次性**的：`_refresh_dirty_ui` 一跑就把它冲掉，再也回不来
—— **它既是假的，又只在零交互的首屏出现，也就是每个人看到的第一眼。**
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "pages" / "preset_center_page.py"


@pytest.fixture()
def page(qapp, monkeypatch):
    """建一页真的 `PresetCenterPage`，并把所有模态框换成探针。

    ⚠ 不 monkeypatch `export_bundle` / `apply_bundle` —— 本文件里好几条断言
      问的正是「真的写回去之后 config 变没变」，替身会把那个问题整个抹掉。
    """
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: 0)
    import pages.preset_center_page as mod

    p = mod.PresetCenterPage()
    p.resize(1280, 900)
    p.show()
    qapp.processEvents()
    yield p
    p.deleteLater()
    qapp.processEvents()


def _chips(page) -> list[str]:
    bar = page.status_badge_label
    layout = bar.layout()
    if layout is None:
        return []
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget() if item else None
        if isinstance(w, QLabel) and w.objectName() == "audioStatusChip" and not w.isHidden():
            out.append(w.text())
    return out


def _visible_texts(page) -> list[str]:
    return [w.text() for w in page.findChildren(QLabel)
            if w.isVisibleTo(page) and w.text()]


# --------------------------------------------------------------------------
# 空转守卫：先证明这支夹具真的建出了一页能用的东西（RN-169）
# --------------------------------------------------------------------------

def test_the_fixture_really_built_the_page(page):
    """⭐ 没有这一条，下面每一条「不许出现 X」的断言都能靠「页面是空的」拿到绿。"""
    # ⚠⚠ 这道守卫原来数的是**状态胶囊**：4 颗 → 批 40 减到 2 颗、
    #   补刀又减到 1 颗（撤掉「内容 · N 项」「来源 · …」「模式 · 合并」）。
    #   于是它被**连降三次门槛**，每一次都写着"降门槛必须说明为什么"。
    # ⭐⭐⭐ 三次都说明了理由，三次都是对的 —— 而这恰恰说明**它拿错了信号**：
    #   一个会被本页正常演进反复推着走的数，当不了「这一页建出来了没有」的证据。
    #   ⭐ 空转守卫要挑一个**和本次改动无关**的量，否则它会年年跟着改，
    #     而每一次改都长得像放水。
    # ⇒ 改成数**可见按钮**（这一页的动作面，重排/换名都不改变它有一堆按钮这件事）。
    buttons = [b for b in page.findChildren(QPushButton)
               if b.isVisibleTo(page) and (b.text() or "").strip()]
    assert len(buttons) >= 8, f"只数到 {len(buttons)} 颗可见按钮 —— 页面没建全"
    assert len(_visible_texts(page)) >= 15, "可见文本太少，这一页多半没建出来"
    labels = [lb for _a, _t, lb in page._TYPE_CHECKBOX_SPEC]
    assert len(labels) >= 5, f"打包类别只有 {labels} —— 分母塌了"


# --------------------------------------------------------------------------
# 主刀
# --------------------------------------------------------------------------

def test_this_page_has_no_such_thing_as_an_unsaved_change(page):
    """⭐⭐⭐ 批 40：这一页**结构上**不再有「未保存的修改」这种东西。

    批 38 把 `mark_dirty()` 收窄到只剩一个真源（「读进来一份还没应用的预设包」）；
    批 40 把两条导入路统一成「确认 → 应用」之后，**那一个真源也不再产生状态**
    ⇒ 整个 `DirtyPageMixin` 退场。
    ⭐ **一个机制收窄到只剩一个用例之后，下一个该问的问题是：
      那一个用例，是不是也可以不由它来做。**

    ⚠ 这条**取代**了批 38 那三条（勾选不算改动 / 走得掉 / dirty 只有一个来源）——
      它们钉的是「那个机制别乱用」，而现在没有那个机制了。
    ⭐ 不是删掉了事：**掏空一条判据比删掉它更危险，因为掏空之后它还是绿的**
      （批 31 那条）。所以这里换成一条**更强**的：不是「别调」，是「调不到」。
    """
    from widgets.dirty_page_mixin import DirtyPageMixin

    assert not isinstance(page, DirtyPageMixin), (
        "这一页又继承回 `DirtyPageMixin` 了 —— 那意味着 `can_leave_page()` "
        "又有资格弹模态框拦人，而这一页没有任何一种「未保存的修改」。")
    for name in ("is_dirty", "mark_dirty", "clear_dirty", "can_leave_page"):
        assert getattr(page, name, None) is None, (
            f"这一页又长出了 `{name}` —— 见上。")
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    functions = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)]
    # ⚠ 空转守卫（批 40 补刀补上）：下面那条是**否定断言 + 一次 AST 扫描** ——
    #   源码读空了、或者 `ast.parse` 换了形状，它一样是绿的。
    #   ⭐ 先证明这次真的扫到了一整页的函数，那条「没人再调 dirty」才算数。
    assert len(functions) >= 25, (
        f"只从 {SRC.name} 里扫出 {len(functions)} 个函数 —— 分母塌了，"
        "下面那条「没人再调 dirty」是靠扫了个空拿到的绿。")
    callers = [fn.name for fn in ast.walk(tree)
               if isinstance(fn, ast.FunctionDef)
               and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr in ("mark_dirty", "clear_dirty")
                       for n in ast.walk(fn))]
    assert not callers, f"这几个函数还在调 dirty：{callers}"


def test_leaving_the_page_never_puts_a_modal_in_the_way(page, qapp, monkeypatch):
    """⭐⭐ 这条是上一条的**行为面**，故意分开写。

    上一条问的是「类上还有没有那个方法」，这一条问的是
    「主窗真去问它能不能走的时候，屏幕上会不会冒出一个框」。
    ⚠ `gui_widget` 两处都写的是 `getattr(page, "can_leave_page", None)` ——
      **没有这个属性就直接放行**，所以撤掉 mixin 之后这条路是通的；
      但那是主窗的写法，不是这一页能保证的事，所以要单独钉。
    """
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)

    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()

    gate = getattr(page, "can_leave_page", None)
    assert gate is None or gate() is True, "只是勾了一下打包范围，就走不掉了。"
    assert not shown, (
        f"离开这一页时弹了框：{shown}\n"
        "⭐ 「你想导出哪些」不是「你改了哪些」——前者没有资格拦人。")


def _intercept_confirm(monkeypatch, seen=None, choose=None):
    """拦住导入确认框，并替测试「按下」其中一颗按钮。

    ⚠⚠ 批 40 之前这里拦的是 `QMessageBox.question`（**类方法**）。
      RN-484 把确认框换成了**实例 + 自定义按钮**（`box.exec()`），
      于是那个钩子一个字都没报错地失效了 —— 实测整轮 pytest **当场挂死**
      在一个离屏但真实的模态框上（120 秒无任何输出）。
    ⭐⭐ **钩子必须挂在被测代码真正会调的那个方法上**：
      钩子挂错地方不会报"没挂上"，只会挂死或静默放行。

    `choose=None` ⇒ 按「取消」（RejectRole）；否则按文案里含 `choose` 的那颗。
    """
    picked = {}

    def fake_exec(self):
        if seen is not None:
            # ⚠⚠ 这里原来只记 `self.text()`。而 RN-484 之后，
            #   「问没问该怎么处理你自己加的条目」这件事**是写在按钮上的**，
            #   不在正文里 ⇒ 破坏实验（强行让 conflicts 恒非空）**没能让判据变红**。
            #   ⭐⭐ 一条断言只能看见它真正读到的那几个字节：
            #     我改的是按钮，断的却是正文，那条判据结构上照不到它自己声称的事。
            seen.append("\n".join(
                [self.text(), self.informativeText() or ""]
                + [b.text() for b in self.buttons()]))
        target = None
        for btn in self.buttons():
            if choose is None:
                if self.buttonRole(btn) == QMessageBox.RejectRole:
                    target = btn
                    break
            elif choose in btn.text():
                target = btn
                break
        picked["btn"] = target
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: picked.get("btn"))
    return picked


def test_opening_a_config_file_asks_before_it_changes_anything(page, qapp, monkeypatch, tmp_path):
    """⭐ **阳性对照 + 主刀**：打开一份文件必须先弹确认框，按「否」就一个键都不许动。

    ⚠ 批 38 那条阳性对照（「导入真的会让页面变 dirty」）随 dirty 一起退场，
      而**撤掉一条阳性对照不补一条新的，等于把主刀那条判据变成只会说「不」的判据**
      —— 它会在「整个导入功能被删光」时依然全绿。
    """
    import json as _json

    from core.presets.preset_center import export_bundle

    bundle = export_bundle(["hud_rules", "crosshair"])
    path = tmp_path / "friend.json"
    path.write_text(_json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

    asked = []
    _intercept_confirm(monkeypatch, seen=asked, choose=None)   # choose=None ⇒ 按「取消」
    applied = []
    import pages.preset_center_page as mod
    monkeypatch.setattr(mod, "apply_bundle",
                        lambda *a, **k: applied.append(a) or (_ for _ in ()).throw(
                            AssertionError("按了「否」还是把它应用了")))

    page._import_config_path(str(path))
    qapp.processEvents()

    assert len(asked) == 1, f"打开一份配置文件时没有先问一句：{asked}"
    text = asked[0]
    for label in ("HUD 规则", "准心"):
        assert label in text, (
            f"确认框里没有逐字写出「{label}」：\n{text}\n"
            "⭐ 「先看清里面是什么再决定」是这一步存在的**全部**理由；"
            "它要是只报个数字，那就跟没问一样。")
    assert not applied, "按了「否」，却还是调了 apply_bundle"


def test_both_file_kinds_go_through_the_same_one_button(page):
    """⭐⭐⭐ RN-478：一个动作一颗按钮，两种扩展名在**幕后**分派。

    改前这里是 2×2 四颗按钮（`.json` 一对、`.cs2customizer` 一对）外加第五颗「应用」，
    外审 12 发问「朋友发你一个文件你点哪个」——**12/12「有把握: 没有」**。
    ⭐ 摆在屏幕上的不该是两种容器格式（那是实现细节），玩家的动作只有两个。
    """
    visible = [b for b in page.findChildren(QPushButton)
               if b.isVisibleTo(page) and b.text()]
    assert len(visible) >= 5, f"这一页只扫到 {len(visible)} 颗可见按钮 —— 分母塌了"

    # ⚠⚠ RN-494：这个筛选原来带着 `and "预设" not in b.text()`，
    #   而改动前那两颗导入按钮里恰好有一颗叫「**导入预设包**」——
    #   ⭐⭐ **它被自己的判据滤出了分母**，于是 `len(openers) == 1`
    #   在改前那个「2×2 四颗按钮」的缺陷状态下**照样通过**。
    #   一条本该逮住旧缺陷的判据，被一个为了绕开旧缺陷而写的过滤条件绕开了。
    #   ⇒ 过滤条件只许排除**当前确实存在且确实是另一回事**的东西，
    #     不许排除"我不想让它进来的那个词"。
    openers = [b.text() for b in visible
               if "打开" in b.text() or "导入" in b.text()]
    exporters = [b.text() for b in visible if "导出" in b.text()]
    assert len(openers) == 1, (
        f"「打开别人给的文件」这一个动作有 {len(openers)} 颗按钮：{openers}\n"
        "⭐ 一个动作一个入口（批 31）——文件格式版：格式是实现细节，动作才是入口。")
    assert len(exporters) == 1, (
        f"「把我这一套发出去」这一个动作有 {len(exporters)} 颗按钮：{exporters}")

    # ⚠⚠ 这一段原来在**源码文本**里找 `*{SHARE_EXT} *.json` 这个字面拼法。
    #   而批 40 补刀为了让开源子集不再需要语义补丁，把过滤器改成
    #   `f"配置文件 ({patterns} *.json)"` —— 行为一个字节没变，判据当场变红。
    # ⭐⭐ **一条钉在源码形状上的判据，会红在一次纯粹的重写上，
    #   也会绿在一次真正的功能删除上**（换个拼法照样能删掉 .json）。
    #   ⇒ 改成截住对话框、看**它真的收到了什么过滤器**。
    #   这样它在开源子集（`SHARE_EXT = ".cs2c"`）里同样成立。
    from core.presets.share_file import LEGACY_SHARE_EXTS, SHARE_EXT
    from PySide6.QtWidgets import QFileDialog

    seen_filter = {}
    real = QFileDialog.getOpenFileName

    def _spy(*args, **kwargs):
        seen_filter["value"] = args[3] if len(args) > 3 else kwargs.get("filter", "")
        return "", ""

    QFileDialog.getOpenFileName = staticmethod(_spy)
    try:
        page._open_config_file()
    finally:
        QFileDialog.getOpenFileName = real

    flt = seen_filter.get("value", "")
    assert flt, "「打开一份配置文件」没有弹出文件对话框 —— 分母塌了"
    for ext in (SHARE_EXT, *LEGACY_SHARE_EXTS, ".json"):
        assert ext in flt, (
            f"打开文件的对话框不认 `{ext}`（实际过滤器：{flt!r}）—— "
            "撤掉一颗按钮却不让剩下那颗吃两种文件，等于把功能删了一半。")


def test_the_two_file_kinds_do_not_behave_differently(page):
    """⚠⚠ **一颗按钮两种行为，比两颗按钮更糟** —— 至少两颗按钮把选择摆在明面上。

    改前 `.cs2customizer` 走「安检→确认→应用」，`.json` 走「塞进预览→再点一次按钮」，
    而决定走哪条的是**用户看不见的扩展名**。
    ⇒ 判据钉的是汇流点：两条读法必须都从 `_read_config_file` 出来，
      而 `apply_bundle` 在这一页只许有一个调用方。
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    appliers = [fn.name for fn in ast.walk(tree)
                if isinstance(fn, ast.FunctionDef)
                and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "apply_bundle" for n in ast.walk(fn))]
    assert sorted(appliers) == ["_apply_starter_pack", "_import_config_path"], (
        f"`apply_bundle` 的调用方是 {sorted(appliers)}。\n"
        "打开文件这条路只许有一个落地点（内置精选那条是另一个动作，它有自己的确认框）。")


def test_applying_the_current_config_back_onto_itself_is_a_no_op(page):
    """⭐ 把上面那条的**前提**单独钉住：这不是「碰巧没变」，是结构上不可能变。

    `export_bundle(当前 config)` → `apply_bundle` 写回同样的值。
    ⚠ 这一条不许被上面那条替代：哪天有人让这颗按钮变得有作用，
      「不许出现这颗按钮」就从「它没用」退化成一条纯粹的版式偏好。
    """
    from config import config
    from core.presets.preset_center import apply_bundle, export_bundle

    bundle = export_bundle(page._selected_types())
    watched = [k for item in bundle["items"] for k in item["payload"]]
    assert len(watched) >= 20, f"只有 {len(watched)} 个键进了包 —— 分母塌了"
    before = {k: copy.deepcopy(getattr(config, k, None)) for k in watched}
    apply_bundle(bundle, mode="merge")
    changed = [k for k in watched if before[k] != getattr(config, k, None)]
    assert not changed, (
        f"把当前配置原样写回自己，居然有 {len(changed)} 个键变了：{changed[:5]}\n"
        "那说明 export/apply 不是互逆的，这一页的问题就不是"
        "「按了没用」而是「按了会悄悄改东西」——两条都得重裁。")


# --------------------------------------------------------------------------
# 另一半：半份清单
# --------------------------------------------------------------------------

def test_no_visible_sentence_names_a_half_list_of_the_supported_kinds(page, qapp):
    """⭐⭐ 这条判据就是这次缺陷的定义。

    这一页上任何一句**枚举类别**的话，只有两种合法说法：

      · 说「这个软件支持哪些」 ⇒ 必须把 **7 类全部**说完；
      · 说「你现在勾了哪些」   ⇒ 必须**等于当前勾选**。

    第三种（点名两三个就停）都是假话。底栏那句
    「支持 HUD / 屏幕特效 / 特殊音效 三域预设。」就是第三种，
    而它出现在**零交互的首屏**上。

    ⚠ 不去钉「三域」这两个字：钉字面量只能拦住这一次的写法。
      ⭐ 批 27 那条 —— 不问这句话是怎么造出来的，只问屏幕上有没有这样一句话。
    """
    labels = [lb for _a, _t, lb in page._TYPE_CHECKBOX_SPEC]
    checked = {lb for attr, _t, lb in page._TYPE_CHECKBOX_SPEC
               if getattr(page, attr).isChecked()}

    texts = _visible_texts(page) + [page.action_bar.message_label.text()]
    offenders = []
    for text in texts:
        named = {lb for lb in labels if lb in text}
        if len(named) < 2:
            continue                      # 点名 0~1 个不算「枚举」
        if named == set(labels) or named == checked:
            continue                      # 两种合法说法
        offenders.append((text, sorted(named)))

    assert not offenders, (
        "这些话点名了一份**对不上的半份清单**：\n  " +
        "\n  ".join(f"「{t}」点名 {n}（共 {len(labels)} 类，当前勾了 {len(checked)} 类）"
                    for t, n in offenders) +
        "\n⭐ 一句枚举类别的话，要么说全部，要么说当前勾选。第三种都是假话。")


def test_the_scope_chip_says_how_many_there_are_not_just_how_many_are_ticked(page):
    """⭐⭐ **这条是改完复跑逼出来的，而它逼出来的是我自己这一批造的。**

    改前：底栏那句假话在，而七个勾选框就在第一屏上 ⇒ 外审 12/12 答「能装 **7** 类」。
    改后第一版：假话没了，可重排把那七个勾选框挪到了折线以下 ⇒
    窗口档 **6/6 答「5」**（那是「你现在勾了几个」），整页档才答 7。

    ⭐ 我修掉了那句假话，同时**把这个问题的答案从第一屏上搬走了**；
      而第一屏上仅存的那颗胶囊「范围 · 5 类」，孤零零地读起来是含糊的 ——
      批 31 那条（一个控件怎么被读，由它的邻居决定）的另一个形态：
      **我搬走的是它的邻居，它自己一个字都没改，意思却变了。**
    ⇒ 让它自带分母。
    """
    total = len(page._TYPE_CHECKBOX_SPEC)
    chips = _chips(page)
    scope = next((c for c in chips if c.startswith("范围")), None)
    assert scope, f"找不到「范围」那颗胶囊：{chips}"
    assert f"/{total}" in scope, (
        f"「{scope}」只说了勾中几个，没说一共几类。\n"
        "⭐ 这颗胶囊在第一屏上，而那七个勾选框不在 —— 它得自己把话说完。")


def test_the_bottom_line_does_not_overstate_what_applying_a_preset_does(page):
    """⭐ 底栏那句话不许说成「换掉你现在的设置」。

    三条应用通路 —— 内置精选 `_apply_starter_pack`、我的预设 `apply_preset`、
    按地图 `apply_rule_for_map` —— **全都是 `mode="merge"`**（AST 实测），
    只写这份预设覆盖到的键。说「换掉你现在的设置」是**朝着更吓人的方向**说过头了。

    ⚠⚠ 这句话的第一版就是这么写的，是**改完复跑**逮住的（紧凑窗口 3/3 报它
      和「模式 · 合并」互相矛盾）—— 批 36 那条第二次现身：
      **这一批最贵的一句话，是我自己补上去的那半句。**
    """
    import core.presets.my_presets as mp

    src = ast.parse((REPO / "core" / "presets" / "my_presets.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(src)
              if isinstance(n, ast.FunctionDef) and n.name == "apply_preset")
    default = fn.args.defaults[-1]
    assert isinstance(default, ast.Constant) and default.value == "merge", (
        "`apply_preset` 的默认模式不是 merge 了 —— 底栏那句话得重新裁一次")
    assert mp is not None

    text = page.action_bar.message_label.text()
    assert "换掉你现在的设置" not in text, (
        f"底栏说「{text}」—— merge 模式只动这份预设覆盖到的键，别的一个不碰。")
    assert "覆盖到的" in text or "别的不动" in text, (
        f"底栏说「{text}」—— 没说清「只动这套预设管的那几类」。")


def test_tab_walks_the_cards_in_the_order_they_are_shown(page, qapp):
    """⭐⭐ **摆放顺序改了，Tab 键的顺序不会跟着改。**

    Qt 的焦点链默认走**构造顺序**，而本批只动了**显示顺序** ——
    首跑 `scripts/tab_order_audit.py` 当场报「[preset_center] 需挪动 8 个」：
    屏幕上第一张卡（内置精选）里的控件，按 Tab 要按到第 12 下才轮到。

    ⭐⭐ 这是判据抓的，我自己出图、外审看图**结构上都不可能看见** ——
      焦点顺序不在任何一张截图里。
      （和本批主刀同形：**截图没有时间轴，也没有键盘。**）

    ⚠ 这里不重造一遍 `tab_order_audit` 的阅读序算法（那份判据自己在跑）。
      这一条只钉一件更窄、也更稳的事：**焦点链先走完靠前那张卡，
      才轮到靠后那张卡** —— 也就是重排必须被跟上。

    ⚠⚠ **这条判据的第一版被回退验证判成假绿**，而原因是它问错了问题：
      它问「从『内置精选』的下拉框出发，一路 Tab 走不走得到工作台的第一个勾选框」——
      ⭐⭐ **而焦点链是一个环**，从任何一个控件出发都必然走到其余每一个。
      **那个问题的答案永远是「能」，跟顺序毫无关系。**
      ⇒ 改成从页面本身这个**固定原点**走完整个环，比两者的**下标**。
    """
    order, node = [], page
    for _ in range(600):
        node = node.nextInFocusChain()
        if node is page or node is None:
            break
        order.append(node)
    assert len(order) >= 20, (
        f"整条焦点链只有 {len(order)} 个控件 —— 这一页有 29 个可聚焦控件，环没走完")
    index = {id(w): i for i, w in enumerate(order)}
    starter = index.get(id(page.starter_combo))
    workbench = index.get(id(page.cb_hud))
    assert starter is not None and workbench is not None, (
        "「内置精选」的下拉框或工作台的第一个勾选框不在焦点链里")
    assert starter < workbench, (
        f"焦点链里「内置精选」排在第 {starter}、工作台的第一个勾选框排在第 {workbench} —— "
        "屏幕上内置精选在上面，Tab 却先走工作台。\n"
        "⭐ Qt 的焦点链默认走**构造顺序**，重排只动了显示顺序。")


def test_nothing_can_silently_throw_away_an_imported_bundle(page, qapp):
    """⭐⭐⭐ 「读进来一份包」这件事，不许被一个不说话的动作抹掉。

    `_render_preview()` 第一句就是 `export_bundle(当前勾选)` 并覆盖 `_current_bundle`。
    改前底栏次位那颗「重新预览」直接绑着它 ⇒ 读进来一份包、还没应用时点一下，
    那份包**一声不响地没了**，而页面仍然 dirty、「应用」仍然亮着，
    按下去应用的是**你自己的当前配置**。

    ⚠⚠ 它本来不显眼。是**我撤掉底栏主按钮之后，它接管了底栏最响的位置**，
      改完复跑当场有一发点它的名（「右下角最醒目的常驻操作是「重新预览」，
      刚进来的玩家无法理解其作用与触发时机」）——
      ⭐ 批 31 逐字再现：**一个控件怎么被读、有多大杀伤力，由它的邻居决定。**

    ⭐⭐⭐ **批 40 把这条缺陷的整个前提拆掉了**：既然「打开一份文件」现在是
      「确认 → 立刻应用」，页面就**从来不持有一份还没落地的包** ——
      没有那份包，就没有「一声不响扔掉它」这件事。
    ⇒ 这条判据只留前半（底栏不许再长按钮）；后半换成更根本的一条：
      **`_render_preview` 永远只从当前勾选出图**，也就是预览只表达一件事。
      ⚠ 没有后半这一句，「让预览重新记住某份外来的包」会悄悄回来，
        而那正是那个中间态复活的第一步。
    """
    from PySide6.QtWidgets import QAbstractButton

    # ⭐ 分母守卫：底栏那两颗按钮**是建出来的**（`PageActionBar` 自带 primary/secondary），
    #   本批只是把它们 `setVisible(False)`。先确认我看的是一条真的底栏，
    #   再让它去断言「一颗都没露脸」。
    all_bar = page.action_bar.findChildren(QAbstractButton)
    assert len(all_bar) >= 2, (
        f"底栏里只找到 {len(all_bar)} 个按钮控件 —— `PageActionBar` 换实现了？"
        "那这条判据在断言一件它已经看不见的事")
    bar_buttons = [b for b in all_bar if b.isVisibleTo(page.action_bar)]
    assert not bar_buttons, (
        f"底栏又长出按钮了：{[b.text() for b in bar_buttons]}\n"
        "⭐ 这一页没有该由底栏承担的动作（同 magnifier / utility）。")

    from core.presets.preset_center import export_bundle

    # ⭐ 阳性对照：先塞一份**外来**的包进去，再改一下勾选 ——
    #   预览必须当场变回「你现在勾的那几类」，而不是继续展示那份外来的。
    page._current_bundle = export_bundle(["hud_rules"])
    before = page.preview_summary_label.text()
    assert "HUD 规则" in before or before, "摘要是空的，这条判据没在量东西"

    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()

    shown = {label for label, _detail in
             __import__("core.presets.preset_center", fromlist=["x"]).describe_bundle(
                 page._current_bundle)}
    ticked = {lb for attr, _t, lb in page._TYPE_CHECKBOX_SPEC
              if getattr(page, attr).isChecked()}
    assert shown == ticked, (
        f"预览里是 {sorted(shown)}，而现在勾着的是 {sorted(ticked)}。\n"
        "⭐ 预览只许表达一件事：**你现在的设置**。它一旦有第二种含义，"
        "屏幕上就得再加一句话去区分，而那句话迟早会和事实岔开（批 38 那颗「来源」胶囊）。")


def test_each_kind_has_exactly_one_name_on_screen(page):
    """⭐ 同一类东西在同一屏上不许有两个名字。

    实测：勾选框上写「HUD 规则」，而 `_TYPE_CHECKBOX_SPEC` 的显示名是「HUD」，
    于是预览摘要、我的预设那句话、状态卡 tooltip 全叫它「HUD」——
    改完复跑有一发逐字把这两处并排抄出来当矛盾报。
    """
    for attr, _tid, label in page._TYPE_CHECKBOX_SPEC:
        box_text = getattr(page, attr).text().strip()
        assert box_text == label, (
            f"勾选框上写「{box_text}」，而别处叫它「{label}」——同一类东西两个名字。")


def test_that_half_list_judge_is_not_vacuous(page):
    """⭐ 空转守卫：上一条的分母是「屏幕上枚举类别的句子」——

    要是哪天这一页一句都不枚举了，它就变成恒真。这里造一句假话喂给同一套逻辑，
    确认它认得出来。
    """
    labels = [lb for _a, _t, lb in page._TYPE_CHECKBOX_SPEC]
    fake = f"支持 {labels[0]} / {labels[1]} / {labels[2]} 三域预设。"
    named = {lb for lb in labels if lb in fake}
    assert 2 <= len(named) < len(labels), (
        f"造出来的这句假话只点名了 {named} —— 那条判据的识别逻辑已经失效了")


def test_the_first_paint_message_is_the_same_kind_of_sentence_as_later_ones(page, qapp):
    """⭐ 底栏那句话不许是「构造时写死一句、之后被冲掉再也回不来」的一次性文案。

    原来的写法是 `set_message("支持 … 三域预设。")` 写死在 `_init_ui` 里，
    而 `_refresh_dirty_ui` 一跑就换成别的 —— **那句话只在首屏活着**，
    也就是**只有每个人的第一眼看得到它，而它是假的**。
    ⇒ 现在要求：首屏那句话必须由同一个出口产生（刷新一次，内容不变）。
    """
    first = page.action_bar.message_label.text()
    page._refresh_bottom_message()
    qapp.processEvents()
    assert page.action_bar.message_label.text() == first, (
        f"首屏写的是「{first}」，刷新一次就变成"
        f"「{page.action_bar.message_label.text()}」——\n"
        "⭐ 那句首屏文案没有第二个人负责，它不会跟着状态走，也没人会去核对它。")


# --------------------------------------------------------------------------
# 折线：新手要的那条路，得在第一屏上
# --------------------------------------------------------------------------

def test_the_only_red_button_is_not_sitting_on_an_empty_shelf(page, qapp):
    """⭐ 全页唯一那颗红按钮「删除该图预设」，在一条绑定都没有时不许是亮的。

    ⚠⚠ **同一页上同一件事，两张卡原来给了相反的处理**：
    「我的预设」一条都没有时会把「删除」禁掉（`refresh_my_presets`，UP-022），
    而「按地图自动切换」那颗红的照样亮着 —— 坐在一张逐字写着
    「尚无地图绑定」的卡上。批 29 RN-447（红「删除」全长在空槽位上）的又一个实例。

    ⚠ 判别到**当前这一张图**：`_on_map_rule_delete` 删的是下拉框里那张图的绑定，
      别的图有绑定并不让这颗按钮有事可做。

    ⚠⚠ **第一版直接 `assert not list_rules()`，当场红在 `['de_ancient']` 上。**
      那条绑定不是产品写的，是**同一场 pytest 里另一支判据**
      （`test_map_preset_rules.py`）写进 `config.map_preset_rules` 之后没收拾。
      ⭐⭐ 批 37 RN-473 隔了一批换了个器官又来一次：上次是固定沙箱目录里
        攒着**产品自己**写的东西，这次是同一个 config 单例里攒着
        **另一支判据**写的东西 —— **共享的可写状态会攒，而攒的东西
        看起来和"这台机器本来就是这样"一模一样。**
      ⇒ 不去量那个飘的值，去量**决定那个值的规则**：两臂各自钉一遍。
    """
    from config import config

    original = getattr(config, "map_preset_rules", None)
    current = str(page.map_combo.currentText()).strip().lower()
    try:
        config.map_preset_rules = {}
        page._refresh_map_rules_label()
        qapp.processEvents()
        assert not page.map_delete_btn.isEnabled(), (
            "一条地图绑定都没有，而那颗红色的「删除该图预设」还是亮的。")
        assert page.map_delete_btn.toolTip(), (
            "禁用了却没说为什么 —— 批 36 那条（tooltip 空串）在这一页的实例。")

        # 阳性对照：这张图真的绑过之后，它必须能点 ——
        # ⭐ 没有这一臂，「一律禁用」也能拿到绿。
        config.map_preset_rules = {current: {"bundle": {}, "saved_at": 0}}
        page._refresh_map_rules_label()
        qapp.processEvents()
        assert page.map_delete_btn.isEnabled(), (
            f"「{current}」已经绑过预设了，而那颗删除按钮点不动。")

        # 反向对照：绑的是**别的图**时，它照样不该亮。
        config.map_preset_rules = {"de_somewhere_else": {"bundle": {}, "saved_at": 0}}
        page._refresh_map_rules_label()
        qapp.processEvents()
        assert not page.map_delete_btn.isEnabled(), (
            "绑的是别的图，而这颗按钮删的是当前这张 —— 它不该是亮的。")
    finally:
        config.map_preset_rules = original if isinstance(original, dict) else {}
        page._refresh_map_rules_label()


def test_the_disabled_buttons_all_say_why(page, qapp):
    """⭐ 这一页上**每一颗**默认就禁用的可见按钮，都得说清「为什么现在不能点」。

    批 23（RN-150）问的是「看不看得出它禁用了」，批 36 问的是「知不知道为什么」
    —— **是两个问题**。

    ⚠⚠ RN-492：这条判据本批一度写成 `for name in ("map_delete_btn",)` ——
      一个**硬编码的一元组**。它是这么来的：改前是 `("apply_btn", "map_delete_btn")`，
      而 RN-478 把 `apply_btn` 整颗撤掉了，于是元组"自然地"缩成了一个。
    ⭐⭐⭐ 而实测这一页当时有 **5 颗**可见且禁用的按钮，
      其中 4 颗（应用 / 覆盖 / 改名 / 删除）tooltip 是**空串** ——
      判据名承诺的是全页性质，分母里却只剩下唯一合规的那一颗，**全绿**。
      这是批 39 那条「守卫拿自己的白名单当分母」在按钮上的翻版：
      ⭐ **一份点名清单，会在被点名的东西消失时安静地变成一份短清单，
        而不是变成一条红线。**
    ⇒ 改判：分母**当场从屏幕上数**，不再由我预先写死。
    """
    qapp.processEvents()
    disabled = [b for b in page.findChildren(QPushButton)
                if b.isVisibleTo(page) and b.text() and not b.isEnabled()]
    # 空转守卫：这一页默认态本来就该有禁用按钮（没存过预设 + 当前图没绑定）。
    assert len(disabled) >= 4, (
        f"默认态只数到 {len(disabled)} 颗禁用按钮 —— 分母塌了，"
        "这条判据就成了恒真。期望至少 4 颗（我的预设那一排）。")
    silent = [(b.text(), b.toolTip()) for b in disabled if len(b.toolTip()) < 10]
    assert not silent, (
        f"这些按钮禁用着，却没说为什么：{silent}\n"
        "⭐ 一颗灰按钮不解释自己，用户只会以为软件坏了。")


def test_the_empty_my_presets_hint_names_what_it_would_save(page, qapp):
    """⭐⭐ 这条钉的是**我自己这一批造出来的一个缺陷的修法**。

    重排把「我的预设」提到了工作台之前，于是它那句
    「先在**上面**勾选要包含的类别」当场变成假话（勾选框跑到了下面）。
    ⇒ 照 RN-401 的规矩：不指方向，点名控件；
      而更好的一步是**把答案直接说出来**，让人不必跑一趟。

    ⚠ 说出来就要跟着变：勾选一改，这句话必须重算，
      否则它会**具体而肯定地说错**（批 30 那条）。
    """
    page.my_preset_combo.setCurrentIndex(-1)
    qapp.processEvents()
    text = page.my_preset_hint_label.text()
    labels = [lb for attr, _t, lb in page._TYPE_CHECKBOX_SPEC
              if getattr(page, attr).isChecked()]
    assert labels, "默认一类都没勾？那这条判据的样本不对"
    assert all(lb in text for lb in labels), (
        f"空态那句话是「{text}」，而现在勾中的是 {labels} —— 没把它们说全。")
    assert "上面" not in text and "下面" not in text, (
        f"空态那句话又拿方位指路了：「{text}」（RN-401）")

    before = text
    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()
    assert page.my_preset_hint_label.text() != before, (
        "勾选变了，而那句「会把这 N 类存成一套：…」一个字都没变 —— "
        "它现在是一句具体而肯定的假话。")


@pytest.fixture(scope="module")
def real_window(qapp):
    """⚠⚠ **折线只能在真窗里量。**

    第一版拿一个独立的 `PresetCenterPage().resize(1280, 750)` 去量，
    当场给出「完整档露出 71%，通过」——而**真窗里是 0%**。实测两边差多少：

        独立页 1280×750 : 视口 1268×690 · 内容高 1372 · 一键应用 top=666
        真窗   1280×800 : 视口 1074×673 · 内容高 1851 · 一键应用 top=1058

    宽 194px、内容高差 479px。侧边栏、顶栏、底栏都不在独立页里，
    而它们**正是把视口挤成 673 的那几样东西**。
    ⭐⭐ 批 26 那条换了个器官又来一次：**判据跑在一个用户从没见过的容器里**
      —— 那次是没有中文字体的进程，这次是没有外壳的页面。
    """
    import os

    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")
    from PySide6.QtCore import Qt

    import _audit_neutralize as neutral
    import _ui_mode
    from config import config

    neutral.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        neutral.apply(config, list(win._page_names.keys()))
        # ⚠ 专家页：普通模式下 `show_page` 会静默 return，必须走 `goto`（force）。
        _ui_mode.goto(win, "preset_center")
        for _ in range(3):
            qapp.processEvents()
        yield win
    finally:
        win.close()
        qapp.processEvents()


def test_the_page_header_is_still_the_first_thing_on_the_page(qapp, real_window):
    """⚠⚠ **这条是被我自己的第一版重排逼出来的。**

    那一版 `insertWidget(index, card)` 从 0 开始插，六张卡占住 0~5，
    把页头一路推到整页**最下面**（实测页头 top=1818，落在折线以下）。
    而那时「一键应用露不露脸」那条判据 —— 本批的主判据 —— **是绿的**。

    ⭐⭐ 批 32 定的规矩是「重排的判据只许钉对象、不许钉数量」。
      它的背面这次才付出代价：**只钉一个对象的判据，看不见我把别的东西挤到哪儿去了。**
    ⇒ 重排类改动至少要有两条：一条钉「该上来的上来了」，
      一条钉「原来在上面的没被挤下去」。
    """
    from PySide6.QtWidgets import QScrollArea

    page = real_window.pages["preset_center"]
    scroll = page.findChild(QScrollArea)
    vp = scroll.viewport()
    lead = page.page_lead_label
    top = lead.mapTo(vp, lead.rect().topLeft()).y()
    assert 0 <= top < 200, (
        f"页头那句话跑到了 y={top}（视口高 {vp.height()}，内容高 {scroll.widget().height()}）。\n"
        "⭐ 重排卡片时把非卡片的东西一起挪了。")


@pytest.mark.parametrize("size,tag", [((1280, 800), "完整档"), ((860, 640), "紧凑档")])
def test_the_one_click_path_is_above_the_fold(qapp, real_window, size, tag):
    """⭐ 改前实测（真窗）：内容高 1851 / 视口 673 ⇒ **64% 的页面在折线以下**，
    而「内置精选 · 一键应用」在 y=1058（露出 **0%**）。

    外审改前 12 发（窗口档）**6/6 说「找不到现成可一键套用的配置」**，
    而同一页的整页无折线图上 **3/6 直接指向「三套开箱即用的体验包」** ——
    ⭐⭐ **答案在页面上，只是不在屏幕上。**

    ⚠ 只钉**对象**，不钉「露出 0% 的控件有几个」（批 32：那种数会把
      「把对的东西搬上来」判成退步）。
    """
    from PySide6.QtWidgets import QScrollArea

    win = real_window
    win.setMinimumSize(*size)
    win.resize(*size)
    for _ in range(3):
        qapp.processEvents()
    page = win.pages["preset_center"]
    scroll = page.findChild(QScrollArea)
    vp = scroll.viewport()
    btn = page.starter_apply_btn
    assert btn.isVisibleTo(page), "「一键应用」不见了"
    # ⚠ 这道守卫原来写的是 `vp.height() <= 700`，而**撤掉底栏那两颗按钮之后
    #   视口自己长到了 714**（`PageActionBar` 少了按钮就矮一截 —— 同批 28：
    #   RN-196 的纵向债有一大半是被一条跟布局无关的改动清掉的）。
    # ⭐ 拿一个会被自己的改动推着走的数当守卫，它迟早会红在一件好事上。
    #   ⇒ 换成问那件它真正想确认的事：**这一页是不是长在真窗里**。
    assert page.window() is win, (
        f"{tag}：量的这一页不在 MainWindow 里 —— 那就不是用户看到的那一屏"
        "（裸页面的视口比真窗宽 194px、内容矮 479px）")
    top = btn.mapTo(vp, btn.rect().topLeft()).y()
    shown = max(0, min(top + btn.height(), vp.height()) - max(top, 0))
    pct = 100.0 * shown / max(1, btn.height())
    assert pct >= 100.0, (
        f"{tag}：内置精选的「一键应用」只露出 {pct:.0f}%"
        f"（top={top}，视口 {vp.width()}x{vp.height()}，内容高 {scroll.widget().height()}）。\n"
        "⭐ 这是这一页上唯一一条不用碰文件、不用先有预设就能换整套配置的路，"
        "而它是新手唯一想要的那条。")


# --------------------------------------------------------------------------
# 批 40：三条裁定
# --------------------------------------------------------------------------

def test_the_preview_says_what_is_in_the_set_in_words(page):
    """⭐⭐⭐ RN-476：这一块必须用人话说清「这一套里装了什么」，不许是原始 JSON。

    改前它是一个 340px 高的只读框，里面 **8767 个字符 / 329 行**
    （`{"schema": "cs2customizer_preset_bundle", "schema_version": 2, "items": […`），
    而那张卡的副标题逐字承诺自己是给人「快速确认内容范围」用的。
    外审 12 发问「你说得出这一套里有哪几类、每一类大概是什么吗」——
    **12/12「说不出」**，其中 8 发是在这个框**完整可见**的整页图上答的。
    ⇒ ⭐⭐ **一个把全部信息都摊开的控件，可以同时是一个什么都没说的控件。**
    """
    text = page.preview_summary_label.text()
    ticked = [lb for attr, _t, lb in page._TYPE_CHECKBOX_SPEC
              if getattr(page, attr).isChecked()]
    assert len(ticked) >= 3, f"默认只勾了 {ticked} —— 这条判据的样本不对"
    for label in ticked:
        assert label in text, (
            f"摘要里没有逐字写出「{label}」：\n{text}")
    for token in ('"schema"', '"payload"', '"items"', "schema_version"):
        assert token not in text, (
            f"摘要里又混进了 JSON 的记号 `{token}`：\n{text[:200]}")
    assert 20 <= len(text) <= 1200, (
        f"摘要长 {len(text)} 字 —— 改前那个框是 8767 字，"
        "把它换成一段同样读不完的东西没有意义")


def test_the_raw_json_is_still_reachable_but_not_the_default(page, qapp):
    """⭐ **阳性对照**：原始内容不许直接删掉 —— 打开了别人给的文件想看清里面时它有用。

    ⚠ 它是 `setVisible(False)` 而不是 RN-009 那种「建出来就 `hide()`、
      全仓再没人 `show()`」的死控件 —— 这条判据证明**它回得来**。
    """
    assert not page.preview_text.isVisibleTo(page), (
        "原始 JSON 默认就摊在那儿 —— 那正是 RN-476。")
    page.raw_toggle_btn.setChecked(True)
    qapp.processEvents()
    assert page.preview_text.isVisibleTo(page), (
        "点了「查看原始内容」它也不出来 —— 那这颗开关和那个框都是死的。")
    assert '"schema"' in page.preview_text.toPlainText()
    page.raw_toggle_btn.setChecked(False)
    qapp.processEvents()
    assert not page.preview_text.isVisibleTo(page)


def test_the_kind_names_have_exactly_one_home_in_the_whole_repo(page):
    """⭐⭐ RN-476 的另一半：`type_id → 中文名` 这张表全仓只许有一份。

    改前有**两份**且不一致：`share_file.describe()` 写「HUD **颜色规则**」，
    页面的 `_TYPE_CHECKBOX_SPEC` 写「HUD 规则」。
    ⚠ 批 38 刚在这一页上统一过一次同物两名，而**这一份躲过了那一轮** ——
      它只出现在**按下按钮之后**才弹出来的确认框里，任何截图都拍不到它。
    ⭐⭐⭐ 台账那条「外审的盲区」再添一个实例：**代码 / 时间轴 / 键盘 / 记账**
      之外，还有「要交互之后才存在的那些画面」。
    """
    import ast as _ast

    from core.presets.preset_center import TYPE_LABELS

    assert set(TYPE_LABELS) >= {"hud_rules", "crosshair"}, "真源表塌了"
    for _attr, type_id, label in page._TYPE_CHECKBOX_SPEC:
        assert TYPE_LABELS.get(type_id) == label, (
            f"勾选框把 `{type_id}` 叫「{label}」，而真源表叫「{TYPE_LABELS.get(type_id)}」。")

    offenders = []
    for path in sorted((REPO / "core").rglob("*.py")) + sorted((REPO / "pages").rglob("*.py")):
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Dict):
                continue
            keys = {k.value for k in node.keys
                    if isinstance(k, _ast.Constant) and isinstance(k.value, str)}
            if not {"hud_rules", "screen_effects"} <= keys:
                continue
            values = [v.value for v in node.values
                      if isinstance(v, _ast.Constant) and isinstance(v.value, str)]
            if any(any("\u4e00" <= ch <= "\u9fff" for ch in v) for v in values):
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    assert offenders == ["core/presets/preset_center.py:%d" % _labels_lineno()], (
        f"「类别 id → 中文名」这张表在这几处各有一份：{offenders}\n"
        "⭐ 全仓只许有一份（`core.presets.preset_center.TYPE_LABELS`）——"
        "第二份不会报错，它只会在某一天和第一份说不一样的话。")


def _labels_lineno() -> int:
    import ast as _ast

    src = (REPO / "core" / "presets" / "preset_center.py").read_text(encoding="utf-8")
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name) \
                and node.target.id == "TYPE_LABELS":
            return node.value.lineno
    raise AssertionError("`TYPE_LABELS` 找不到了 —— 这条判据已经瞎了")


def test_no_two_chips_say_the_same_number(page):
    """⭐ 同一个数不许在状态卡上出现两次 —— 读的人会把它读成两笔。

    改前第一颗写「范围 · 5/7 类」、第三颗写「内容 · 5 项」，
    而 `export_bundle` 每一类**恰好产出一项** ⇒ 那两个 5 永远相等。

    ⚠⚠ 补刀之后这张卡只剩**一颗**胶囊，于是「两颗说同一个数」结构上不可能发生，
      这条判据在当下是**恒真**的（九维度审查逮到的六条空转之一）。
    ⭐ 而「因为现在不可能所以删掉它」是错的 —— 会再长回来的正是胶囊。
      ⇒ 改判成**闭集**：把当下这一颗钉住。
        再加第（二）颗胶囊的人会当场变红，被迫回来重新回答「这两个数是不是同一笔」。
      ⚠ 这里的白名单不是分母（批 39 那条教训），分母仍是屏幕上真实的胶囊；
        白名单只是「我们商定过的那一份」，任何偏离都要有人重新裁定。
    """
    import re as _re

    chips = _chips(page)
    known = ["范围 · 5/7 类"]
    if len(chips) < 2:
        assert chips == known, (
            f"状态胶囊变成了 {chips}（商定过的是 {known}）。\n"
            "⭐ 少于两颗时这条判据本身是恒真的，所以它改成钉住这个闭集：\n"
            "  · 加了一颗 ⇒ 回来确认它和「范围」说的不是同一笔数；\n"
            "  · 改了文案 ⇒ 回来更新这份闭集，并想一遍它还携不携带信息。")
        return
    numbers = []
    for chip in chips:
        found = _re.findall(r"\d+", chip)
        numbers.append((chip, found[0] if found else None))
    seen = {}
    for chip, first in numbers:
        if first is None:
            continue
        if first in seen:
            raise AssertionError(
                f"「{seen[first]}」和「{chip}」打头的是同一个数 {first} —— "
                "同一个数写两遍，会被读成两笔。")
        seen[first] = chip


@pytest.mark.parametrize("size,tag", [((1280, 800), "完整档"), ((860, 640), "紧凑档")])
def test_every_scope_checkbox_is_above_the_fold(qapp, real_window, size, tag):
    """⭐⭐⭐ RN-477：那七个勾选框，每一个都必须在第一屏上。

    改前实测（真窗 1280×800，视口 1074×710）：第一排 `cb_hud` 露出 **27%**、
    第二排 `cb_magnifier` / `cb_viewmodel` 露出 **0%**。
    外审问「这一屏上哪些操作会受这组勾选影响」——
      · 窗口图（看不见折线以下）  **6/6「找不到」**
      · 整页无折线图              **6/6「4 个」**，且 **6/6 说「依据：图上写着」**
    ⇒ ⭐⭐⭐ **立案说它是「跨区域逆向联动」（一个理解问题），而实测推翻了：
      只要看得见，理解一点问题都没有。唯一的缺陷是它在折线以下。**

    ⚠ 钉的是**每一个勾选框**，不是那张卡 —— 卡的下边框被折线切掉是长页面的常态
      （RN-170），而「用户能不能看见并勾到它」问的是控件。
    """
    from PySide6.QtWidgets import QScrollArea

    win = real_window
    win.setMinimumSize(*size)
    win.resize(*size)
    for _ in range(3):
        qapp.processEvents()
    page = win.pages["preset_center"]
    assert page.window() is win, "这一页没长在真窗里 —— 折线量出来的数不算数"
    scroll = page.findChild(QScrollArea)
    vp = scroll.viewport()
    content = scroll.widget()

    boxes = [(lb, getattr(page, attr)) for attr, _t, lb in page._TYPE_CHECKBOX_SPEC]
    assert len(boxes) >= 7, f"只找到 {len(boxes)} 个勾选框 —— 分母塌了"
    hidden = []
    for label, box in boxes:
        top = box.mapTo(content, box.rect().topLeft()).y()
        bottom = top + box.height()
        shown = max(0, min(bottom, vp.height()) - max(top, 0))
        if shown < box.height():
            hidden.append(f"{label} top={top} 露出 {round(100 * shown / max(1, box.height()))}%")
    assert not hidden, (
        f"[{tag} {size[0]}×{size[1]}，视口高 {vp.height()}，内容高 {content.height()}] "
        f"这几个勾选框没有完整露在第一屏上：\n  " + "\n  ".join(hidden) + "\n"
        "⭐ 它决定四处的内容（导出 / 存为新预设 / 按地图保存 / 状态卡第一颗胶囊），"
        "而那四处都在第一屏上说话。")


def test_the_scope_selector_is_a_card_of_its_own(page):
    """⭐ 它不许再住在别的卡里 —— 那正是它被读成「归那张卡所有」的原因。

    ⛔ 也不许并进「我的预设」：那只是换一个收养人。
    """
    from widgets.settings_card import SettingsCard  # noqa: F401

    node = page.cb_hud.parent()
    owners = []
    while node is not None and node is not page:
        title = getattr(node, "objectName", lambda: "")()
        if title == "card":
            for child in node.findChildren(QLabel):
                if child.text().strip() in ("保存/导出的范围",):
                    owners.append("own")
            break
        node = node.parent()
    assert owners == ["own"], (
        "「保存/导出的范围」那组勾选框所在的卡，标题不是它自己 —— "
        "它又被别的卡收养了，而收养它的那张卡会替它决定摆在页面的第几屏。")


def test_the_empty_preset_dropdown_says_it_is_empty(page, qapp):
    """⭐ 一条预设都没有时，下拉框不许是一个**完全空白**的框。

    批 40 两轮外审共 5 发点名：「初次进入下拉框空白且按钮大面积置灰」
    「空白框与输入框形态混淆，分不清是要在框里打字还是点『存为新预设』」。
    ⭐⭐ **一个空控件不说明自己为什么空，就会被读成「我该往里面填点什么」。**

    ⚠ 那一项**不许带 data** —— 「一条都没有 ⇒ 除『存为新预设』外全禁用」
      这条既有规则读的是 `currentData()`，带了 data 就会把四颗按钮全放开。
    """
    from core.presets.my_presets import list_presets

    if list_presets():
        pytest.skip("这台机器上已经存过预设了，这条只在空态下问得出来")
    combo = page.my_preset_combo
    assert combo.count() >= 1, "空态下拉框一项都没有 —— 那就是一个白框"
    assert combo.currentText().strip(), f"空态那一项是空字符串：{combo.currentText()!r}"
    assert combo.currentData() is None, (
        "空态占位项带了 data —— 「一条都没有就禁用那四颗按钮」那条规则会被它骗过去。")
    assert not page.my_preset_apply_btn.isEnabled(), "一条预设都没有，「应用」却是亮的"


# --------------------------------------------------------------------------
# 批 40 补刀：改完复跑 + 九维度审查逮出来的七条
# --------------------------------------------------------------------------

@pytest.mark.parametrize("music_bar", ["auto", "on"])
def test_the_way_to_open_a_friends_file_is_on_the_first_screen(qapp, real_window, music_bar):
    """⭐⭐⭐ RN-486：「打开一份配置文件」必须整颗露在**完整档**的第一屏上。

    这条有一组**天然对照实验**撑着。同一份状态、同一个问题
    （「朋友发来一份配置文件，你会点哪个」），只差看不看得见折线以下：

        · 窗口图（=真实第一屏）  6/6「有把握: **没有**」，答案乱猜
        · 整页无折线图            6/6「**打开一份配置文件**」· 候选数 1 ·「有把握: **有**」

    ⇒ 命名（RN-478）修好之后，剩下的唯一障碍就是它不在第一屏上。

    ⚠⚠ 这与 RN-170（折线假象）**必须分开**，判别法是看抱怨的内容：
      · 「这块画坏了 / 被切了」只在窗口图上报 ⇒ **假象**，那是截图的边，不是产品的病；
      · 「我找不到做 X 的入口」只在窗口图上报 ⇒ **真缺陷**，
        因为窗口图就是用户真正的第一屏（RN-414 同形）。

    ⚠ 只钉完整档。紧凑档（视口 554px，整页 1339px）放不下所有卡，
      实测那一档露出的是这张卡的**标题和说明**（卡 y=515，折线 554）——
      比改前（整张卡在 y=685，一个像素都没有）好，但按钮仍在折线下，另案（RN-496）。

    ⚠⚠⚠ **窗口尺寸必须和别处一致，不许自己挑一个。**
      这条判据第一版写的是 `1280×900`，当场绿 —— 而同一时刻的外审窗口图
      仍然 6/6 答「一键应用 · 没把握」。原因不是产品，是**我挑的尺子**：
      出图工装 `ui_shot_capture.py` 和同族的既有折线判据
      `test_the_one_click_path_is_above_the_fold` 用的都是 **1280×800**，
      而我给自己多要了 100px，那 100px 正好够把两颗按钮抬过折线。
    ⭐⭐⭐ **一条判据绿着，可能是因为我选的参数，而不是因为缺陷修好了** ——
      而它和"真的修好了"在测试报告上长得一模一样。
      ⇒ 折线类判据的窗口尺寸只有一个来源：**产品出图用的那一档**。

    ⚠⚠⚠ **而尺寸对上之后还有第二个容器变量：音乐控制条（127px）。**
      实测同一个 1280×800：
        · 音乐条 auto（全新配置，没放过音乐 ⇒ 不建）  视口 714 → 两颗按钮 **露出 100%**
        · 音乐条 on （放过一次音乐就永远是这一档）     视口 **587** → **露出 0%**
      ⇒ ⭐⭐ **这条修法对没放过音乐的人成立，对放过音乐的人不成立** ——
        而后者是一条**单向**的路（RN-195：那根条建出来就不再消失）。
      要腾的那 ~110px 只能来自「当前状态」那张卡，而实测 **27/27 页都有状态徽章**
      ⇒ 那是一次跨页裁定，归 **RN-496**，不在本批。
    ⭐ 所以这条判据**两档都跑**，各自钉住当下为真的那件事：
      auto 档钉「两颗按钮整颗露出」，on 档钉「至少卡的标题还在第一屏上」——
      **不许只跑容易的那一档然后说这条修好了。**
    """
    import _audit_music_bar as mbar
    from PySide6.QtWidgets import QScrollArea

    win = real_window
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    mbar.pin(win, qapp, music_bar)
    for _ in range(3):
        qapp.processEvents()
    page = win.pages["preset_center"]
    scroll = page.findChild(QScrollArea)
    vp = scroll.viewport()
    assert page.window() is win, "量的这一页不在 MainWindow 里 —— 那不是用户看到的那一屏"

    def _exposure(widget):
        top = widget.mapTo(vp, widget.rect().topLeft()).y()
        shown = max(0, min(top + widget.height(), vp.height()) - max(top, 0))
        return top, 100.0 * shown / max(1, widget.height())

    if music_bar == "auto":
        for name in ("import_btn", "export_btn"):
            btn = getattr(page, name)
            assert btn.isVisibleTo(page), f"{name} 不见了"
            top, pct = _exposure(btn)
            assert pct >= 100.0, (
                f"{name}（{btn.text()!r}）只露出 {pct:.0f}%"
                f"（top={top}，视口 {vp.width()}x{vp.height()}，"
                f"内容高 {scroll.widget().height()}）。\n"
                "⭐ 跟朋友交换配置是这一页存在的理由之一，"
                "而实测「看不见」= 6/6 找不到、「看得见」= 6/6 一次选对。")
        return

    # 音乐条 on：按钮进不了第一屏（RN-496 在册）。这一档钉的是**别再更糟**：
    # 那张卡的标题必须还在第一屏上，否则连"这里能跟朋友换配置"都读不到了。
    title = None
    for label in page.findChildren(QLabel):
        if label.objectName() == "cardTitle" and "交换" in label.text():
            title = label
            break
    assert title is not None, "找不到交换配置那张卡的标题 —— 分母塌了"
    top, pct = _exposure(title)
    assert pct >= 100.0, (
        f"音乐条建出来（127px）之后，连「{title.text()}」这个标题都掉出第一屏了"
        f"（top={top}，视口 {vp.width()}x{vp.height()}）。\n"
        "⭐ 按钮进不了第一屏是 RN-496 的已知欠账；标题再掉下去就是**变得更糟**。")


def test_the_exchange_card_comes_before_the_one_that_is_empty_for_newcomers():
    """⭐ 第一屏放不下的时候，让位的应该是那张对第一次来的人还没有内容的卡。

    「我的预设」在全新安装上是一个空下拉框加四颗灰按钮（`list_presets()` 为空，
    全仓无任何预置路径）；而「和朋友交换配置」第一天就能用。
    ⇒ 交换卡必须排在「我的预设」**之前**。

    ⚠ 钉的是**相对次序**，不是绝对下标 —— 批 32：重排的判据只许钉对象。
    """
    import inspect

    import pages.preset_center_page as mod

    src = inspect.getsource(mod.PresetCenterPage._init_ui)
    order_src = src.split("card_order = (", 1)[1].split(")", 1)[0]
    names = [n.strip() for n in order_src.replace("\n", " ").split(",") if n.strip()]
    assert "workbench_card" in names and "my_presets_card" in names, (
        f"card_order 里少了要比的那两张卡：{names}")
    assert names.index("workbench_card") < names.index("my_presets_card"), (
        f"「我的预设」排到了交换卡前面：{names}\n"
        "⭐ 那张卡对每一个新用户都是空的，而它会把交换配置整张推下折线。")


def test_the_import_mode_is_asked_at_the_moment_it_matters(page, qapp, monkeypatch, tmp_path):
    """⭐⭐⭐ RN-484：导入模式不再是页面上的下拉框，而是确认框里的两颗后果按钮，
    **且只在这份文件真的会让两种模式得出不同结果时才问**。

    端到端实测：64 个键里只有 5 个在两种模式下结果不同，
    7 类里有 3 类（准心 / 屏幕特效 / 局内视角）逐字节相同 ——
    ⭐ 一个在多数场景里什么都不改的选择，不该摆在所有人的必经之路上。
    """
    import json as _json

    from core.presets.preset_center import export_bundle

    assert not hasattr(page, "mode_combo"), (
        "页面上又长回了一个导入模式下拉框 —— 那个选择要等有了文件才做得了。")

    quiet = tmp_path / "crosshair_only.json"
    quiet.write_text(_json.dumps(export_bundle(["crosshair"]), ensure_ascii=False),
                     encoding="utf-8")
    seen = []
    _intercept_confirm(monkeypatch, seen=seen, choose=None)
    page._import_config_path(str(quiet))
    qapp.processEvents()
    assert len(seen) == 1, f"没弹确认框：{seen}"
    assert "留着" not in seen[0] and "清掉" not in seen[0], (
        f"这份文件里两种模式结果完全一样，却还是问了一句：\n{seen[0]}\n"
        "⭐ 准心 17 个键里 dict 型的是 0 个 —— 合并和覆盖逐字节同解。")
    assert "导入" in seen[0], f"不该问模式的时候，按钮不是一颗干脆的「导入」：\n{seen[0]}"

    noisy = tmp_path / "hud.json"
    noisy.write_text(_json.dumps(export_bundle(["hud_rules"]), ensure_ascii=False),
                     encoding="utf-8")
    seen2 = []
    _intercept_confirm(monkeypatch, seen=seen2, choose=None)
    page._import_config_path(str(noisy))
    qapp.processEvents()
    assert len(seen2) == 1, f"没弹确认框：{seen2}"
    assert "自定义条目" in seen2[0], (
        f"这份文件会碰到 dict 型的键，却没问该怎么处理你自己加的条目：\n{seen2[0]}")


def test_choosing_replace_in_the_dialog_really_replaces(page, qapp, monkeypatch, tmp_path):
    """⭐ **阳性对照**：上一条只问「问没问」，这一条问「按下去算不算数」。

    ⚠ 撤掉页面下拉之后，`mode` 的唯一来源变成了「用户按了哪颗按钮」——
      那条线要是断了，产品会**永远走 merge** 而判据一条都不红。
    """
    import json as _json

    from core.presets.preset_center import export_bundle

    path = tmp_path / "hud.json"
    path.write_text(_json.dumps(export_bundle(["hud_rules"]), ensure_ascii=False),
                    encoding="utf-8")

    got = []
    import pages.preset_center_page as mod
    monkeypatch.setattr(mod, "apply_bundle",
                        lambda b, mode="merge": got.append(mode) or _FakeApply())

    _intercept_confirm(monkeypatch, choose="清掉")
    page._import_config_path(str(path))
    qapp.processEvents()
    assert got == ["replace"], f"按了「清掉，只要文件里的」，传下去的却是 {got}"

    got.clear()
    _intercept_confirm(monkeypatch, choose="留着")
    page._import_config_path(str(path))
    qapp.processEvents()
    assert got == ["merge"], f"按了「留着，只补上文件里的」，传下去的却是 {got}"


class _FakeApply:
    ok = True
    errors = ()
    warnings = ()
    applied_types = ("hud_rules",)
    changed_keys = ()


def test_a_summary_line_is_never_the_same_for_everyone():
    """⭐⭐ RN-487：摘要里那句「N 条按键颜色规则」不许是一个恒定值。

    改前它数的是 `key_rules` 的**槽位数**，而 `_build_key_rules()` 恒建 "1"~"9"
    九项、`_normalize_key_rules` 只覆盖不新增 ⇒ 这一行对**所有人、所有预设**
    永远是「9 条按键颜色规则」；实测全新配置里 `enabled=True` 的是 **0** 个，
    而 HUD 页对同一份数据显示的是「数字键 · 0 项」。
    ⭐ 这张卡是本批为了「让人读得懂里面有什么」才加的 ——
      它的第一行不能是一句对谁都一样的话。
    """
    from core.presets.preset_center import _summarize_payload

    on = _summarize_payload("hud_rules", {
        "hud_rules_enabled": True,
        "hud_rules": {"key_rules": {"1": {"enabled": True}, "2": {"enabled": False},
                                    "3": {"enabled": True}}},
    })
    off = _summarize_payload("hud_rules", {
        "hud_rules_enabled": True,
        "hud_rules": {"key_rules": {"1": {"enabled": False}, "2": {"enabled": False},
                                    "3": {"enabled": False}}},
    })
    assert on != off, (
        f"开了两条和一条都没开，摘要写的是同一句话：{on!r}\n"
        "⭐ 一句对谁都一样的话，等于没说。")
    assert "2" in on, f"开着两条，摘要却没说 2：{on!r}"


def test_the_confirm_text_for_an_empty_file_talks_about_the_file(page, tmp_path):
    """⭐ 打开一份空文件时，确认框要说**这份文件**，不许说本页的勾选框。

    改前这条路直接复用了预览卡的 `_summary_text`，而那个函数的空态分支写的是
    「一类都没勾…到上面「保存/导出的范围」勾上至少一类」——
    ⭐⭐ 而导入这条路**根本不读那组勾选**（那张卡上自己写着「不看这里」）。
      一句话搬了个家，就从"对的"变成"答非所问且指错控件"。
    """
    import json as _json

    path = tmp_path / "empty.json"
    path.write_text(_json.dumps({"schema": "cs2customizer_preset_bundle",
                                 "schema_version": 2, "items": []},
                                ensure_ascii=False), encoding="utf-8")
    bundle, text, _warnings = page._read_config_file(str(path))
    assert bundle is not None, f"这是一份合法的空包，却读不开：{text}"
    assert "勾" not in text, (
        f"打开别人的空文件，却叫用户去勾自己的导出范围：\n{text}")
    assert "文件" in text, f"这句话没提到「文件」，那它说的就不是这件事：\n{text}"


def test_a_preset_name_survives_a_round_trip_through_the_dropdown(page, qapp):
    """⭐⭐ RN-491：预设名不许从下拉框的**显示文案**上切出来。

    改前是 `currentText().split("（")[0]`，而显示文案是 `f"{name}（{n} 类）"`；
    预设名本身允许含全角「（」（`save_preset` 只做 strip + 截断）⇒
    名字叫「准心（低灵敏）」的预设，一走「覆盖」就被**静默改名**成「准心」并落盘。

    ⭐⭐ 这是本仓「状态从屏幕文案反推」那一族的第三个实例 ——
      前两次是**读**状态，这一次**会写坏用户的数据**。

    ⚠⚠ 这条判据是**回退验证逼出来的**：我修了代码却一条判据都没写，
      而那条断点当时指着一条根本不看预设名的判据 ⇒ 回退验证判它**假绿**。
      ⭐ **改了代码没配判据，和没改一样 —— 只是没改这件事会被下一轮忘掉。**
    """
    from core.presets.my_presets import delete_preset, save_preset

    tricky = "准心（低灵敏）"
    item = save_preset(tricky, ["crosshair"])
    try:
        page.refresh_my_presets()
        qapp.processEvents()
        idx = page.my_preset_combo.findData(item.preset_id)
        assert idx >= 0, "刚存的预设没出现在下拉框里 —— 分母塌了"
        page.my_preset_combo.setCurrentIndex(idx)
        qapp.processEvents()
        assert "（" in page.my_preset_combo.currentText(), (
            "显示文案里连一个全角括号都没有 —— 这条判据的样本不对")
        _pid, got = page._current_my_preset()
        assert got == tricky, (
            f"名字被下拉框的显示文案切坏了：存的是 {tricky!r}，取回来的是 {got!r}\n"
            "⭐ 名字要跟着 id 一起放进 itemData，显示文案只负责显示。")
    finally:
        delete_preset(item.preset_id)
        page.refresh_my_presets()


def test_every_visible_action_can_be_found_by_the_settings_search(page):
    """⭐⭐⭐ RN-485：这一页上每一颗有独立动作的可见按钮，都要能被设置搜索找到。

    「导出成文件，发给朋友」里那个**全角逗号**让 `normalize()` 撞上 `_SENTENCE`
    （`[，。！？；、,;]`）判定「这是句子不是设置项」，整条返回空串 ⇒
    这一页唯一的导出入口在全站搜索里一条都不剩。
    ⭐⭐⭐ 而 `build_search_index.py --check` **退出码仍然是 0** ——
      它只校验「重新生成一遍是不是逐字节相同」，**看不见「有一条根本没进去」**。
      ⇒ 一道跑着的、绿着的、以它命名的门禁，结构上照不到它该防的那件事。

    ⚠ 通名（应用 / 删除 / 改名 / 覆盖）本来就不进索引，那是有意的，走白名单。
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "_bsi_probe", str(REPO / "scripts" / "build_search_index.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bsi_probe"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass

    # ⚠ 空转守卫 + **阳性对照**，两样缺一不可：
    #   · 分母：这一页真的扫到了一批该进索引的按钮；
    #   · 阳性对照：`normalize` 真的会把带标点的整条丢掉 ——
    #     否则「一条都没漏」可能只是因为这支 normalize 对什么都点头。
    assert not mod.normalize("导出成文件，发给朋友"), (
        "阳性对照失败：normalize 现在不再丢弃带全角逗号的文案了 —— "
        "这条判据量的那件事已经不存在，它变成了一条恒真。")
    assert mod.normalize("打开一份配置文件"), "阳性对照失败：normalize 把正常文案也丢了"

    generic = {"应用", "删除", "改名", "覆盖", "?"}
    checked, unfindable = [], []
    for btn in page.findChildren(QPushButton):
        text = (btn.text() or "").strip()
        if not text or not btn.isVisibleTo(page) or text in generic:
            continue
        checked.append(text)
        if not mod.normalize(text):
            unfindable.append(text)
    assert len(checked) >= 5, f"只扫到 {checked} —— 分母塌了"
    assert not unfindable, (
        f"这些按钮在设置搜索里一条都找不到：{unfindable}\n"
        "⭐ 多半是文案里带了标点（逗号/句号/顿号/省略号）——"
        "`normalize()` 会把带标点的判成句子整条丢掉，"
        "而 `--check` 只比对「重新生成是否一致」，看不见这件事。")
