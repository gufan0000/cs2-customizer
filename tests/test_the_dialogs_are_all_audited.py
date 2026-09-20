# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""对话框这一类界面，从此有人看着（RN-672，2026-09-20）。

## 这一批查出来的事

`dialogs/` 下 8 个 `QDialog`、3000 多行界面，**从建仓起不在任何一条排版判据的
遍历范围里** —— 两支审计遍历的都是 `win.pages`。而排版审计的报告年年写着
「覆盖面 27/27 个页面（全覆盖）」。

⭐⭐⭐ **「全覆盖」的分母是页面，而界面不只有页面。**
同一个形状这是第四次：UP-096 少 5 个页面、UP-100 少一档尺寸、
RN-666 少 `--tabs`×`--whole` 的乘积格，这次少的是**一整类容器**。

接进来之后当场逮到三条（都在「添加在线音乐」这个框上）：

1. **地板 700×700 比产品自己承诺的紧凑档窗口 860×640 还高** —— 不是"有点挤"，
   是**拖不小、也滚不动**，底下那 60px 连同「添加 / 取消」被屏幕切掉。
2. 「复制」按钮 `setFixedWidth(60)` —— 减掉 QSS padding 只剩 22px 画 28px 的字。
3. ⭐⭐ 修完第 1 条之后**第三条才露出来**：开局高度从 750 降到 620，
   六张平台卡在 1.25 字号档一起被压扁。**旧版之所以看不见它，靠的正是
   那个本身就是缺陷的高度** —— 一个缺陷可以一直替另一个缺陷挡着。

## 这份判据守的是什么

守的不是"那三条别回来"（那是回退断点的活），是**覆盖面别再塌回去**：
清单漏登记一个、审计那条路走不到、地板阈值被改成一个恒真的数 —— 三样都会
让报告重新变成一句好看的空话。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
LAYOUT_AUDIT = SCRIPTS / "layout_overflow_audit.py"
SQUEEZED_AUDIT = SCRIPTS / "squeezed_label_audit.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# ⚠ 只 import 清单那一支。`layout_overflow_audit` 一 import 就会隔离配置目录、
#   `enable_audit_mode()`，那是审计进程该做的事，不是测试进程该做的事 ⇒
#   对它一律**读源码走 AST**（也正是 CLAUDE.md §1 红线 2 要的手段）。
import _audit_dialogs as dlgs  # noqa: E402


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _calls_to(tree: ast.AST, name: str) -> list[ast.Call]:
    """按名字找调用。

    ⚠ 两种形态都要认：`mod.f()`（Attribute）和 `f()`（Name，直接 import 进来的）。
    第一版只认前者，于是 `room_in_cell` 数出 0 次 —— 判据自己红了，
    而红的理由和它要防的事毫无关系。⭐ 同一族的坑：**尺子问错了问题**。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == name:
            out.append(node)
        elif isinstance(func, ast.Name) and func.id == name:
            out.append(node)
    return out


def _guarding_ifs(tree: ast.AST, target: ast.AST) -> list[ast.If]:
    """target 被哪些 `if` 罩着。

    ⭐⭐⭐ RN-666 那条教训的直接产物：**判据查的是「存在」，而缺陷发生在
    「可达」上** —— 把 `if whole:` 改成 `if False:`，一条查"调用在不在 AST 里"
    的判据照样绿。所以这里不光要找到那个调用，还要看清它头顶的条件。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if any(child is target for child in ast.walk(node)):
            out.append(node)
    return out


# ============================ 一、清单别漏登记 ============================

def test_every_dialog_class_in_the_folder_is_registered():
    """`dialogs/` 里每个 `QDialog` 子类都要在清单里。

    ⭐ 这条是本批的核心：**清单类的东西一定会漏登记，而漏掉的那一个从此隐形** ——
    它不会红、不会警告，只会让"8/8 全覆盖"这句话悄悄变成 8/9。
    """
    found = dlgs.discover_dialog_classes()
    # 分母守卫：扫不到类就说明扫描本身坏了，这时「没有漏登记的」毫无意义。
    # ⚠ 下界取 7 不取 8：开源版是功能子集，音乐链路整条被裁 ⇒ 那边只有 7 个。
    assert len(found) >= 7, (
        f"只在 {dlgs.DIALOGS_DIR} 里扫到 {len(found)} 个 QDialog 子类，"
        "扫描坏了 —— 这时下面那句断言是空的")
    # ⚠ 这一方向要拿**整张清单**比（不是 available）：盘上有、清单里没有 = 漏登记。
    missing = sorted(found - {s.cls_name for s in dlgs.DIALOGS})
    assert not missing, (
        f"这些对话框没进 `_audit_dialogs.DIALOGS`，于是两支审计都看不见它们："
        f"{missing}。新增对话框请连同一个**能代表真实场景**的样本一起登记。")


def test_the_registry_does_not_name_a_class_that_vanished():
    """反方向：清单里点名、且这个检出里**有那个模块文件**的类，必须真的还在。"""
    found = dlgs.discover_dialog_classes()
    assert len(found) >= 7, "扫描坏了，见上一条"
    stale = sorted(dlgs.registered_classes() - found)
    assert not stale, (
        f"清单里这些类在 `dialogs/` 里已经不存在了：{stale}。"
        "删掉对应的 `DialogSpec`，别留着它在构造期抛异常。")


def test_the_subset_switch_cannot_hide_a_broken_entry():
    """`DialogSpec.available` 是个**静音开关**，守住它只能盖「这个仓里没这东西」。

    ⭐⭐⭐ 同 RN-671：开源版是功能子集（音乐链路整条被裁 ⇒ 没有
    `dialogs/add_url_dialog.py`），所以清单必须能说「本检出里没有它」——
    但这种标志一旦能被误用，它就能把「类改名了」「文件删错了」一起咽下去。
    ⇒ 钉住：被判成「本检出里没有」的那些，它们的类名**不许**还出现在
    `dialogs/` 里。真不在，才算不在。
    """
    found = dlgs.discover_dialog_classes()
    gone = dlgs.missing_dialogs()
    liars = sorted({s.cls_name for s in gone} & found)
    assert not liars, (
        f"这些登记声称「本检出里没有」，而它们的类就在 `dialogs/` 里：{liars}。"
        "多半是 `DialogSpec.module` 写错了文件名 —— 那会让审计静默少测一个对话框。")
    # 分母：上游必须是满的；缺的只允许出现在功能子集里。
    if (dlgs.DIALOGS_DIR.parent / "build_tools" / "oss_sync").is_dir():
        assert not gone, (
            f"上游（有 `build_tools/oss_sync` 的那个仓）应当 8 个都在，实际缺："
            f"{[s.key for s in gone]}")


def test_every_registered_dialog_says_what_its_sample_represents():
    """每条登记都要写清"这个样本代表什么场景"。

    ⭐ 样本一旦不具代表性，审计量的就是一个没人会看到的界面 ——
    实测第一版给 `AddURLDialog` 传 `player=None`，「支持平台」页从 6~7 条
    缩成 1 条，那一页的缺陷正好藏在被削掉的那几条里。
    写出来是为了下一个人能判断它**还**具不具代表性。
    """
    assert dlgs.DIALOGS, "清单是空的"
    thin = [s.key for s in dlgs.DIALOGS if len(s.sample.strip()) < 8]
    assert not thin, f"这些登记没写样本代表什么场景：{thin}"


# ====================== 二、审计那条路真的走得到 ======================

def test_the_layout_audit_really_reaches_the_dialogs():
    """排版审计里那句 `build_all` 不光要在，还要**走得到**。

    它被 `if not args.no_dialogs:` 罩着 —— 这是有意的（那个开关给"我只想
    快速看页面"用）。判据要钉的是：罩着它的条件确实提到那个开关，
    而不是一个恒假的东西。
    """
    tree = _tree(LAYOUT_AUDIT)
    calls = _calls_to(tree, "build_all")
    assert len(calls) == 1, (
        f"`layout_overflow_audit` 里 `build_all` 出现了 {len(calls)} 次，"
        "判据没法确定该看哪一个")
    ifs = _guarding_ifs(tree, calls[0])
    assert ifs, "那句 `build_all` 头上一个条件都没有，和预期的结构对不上"
    mentions = [i for i in ifs
                if "no_dialogs" in ast.unparse(i.test)]
    assert mentions, (
        "罩着 `build_all` 的条件里没有提到 `no_dialogs` —— "
        "它可能被换成了一个恒假的条件，那样审计会**静默地**不看对话框。"
        f"实际条件：{[ast.unparse(i.test) for i in ifs]}")


def test_the_squeezed_audit_really_reaches_the_dialogs():
    """挤压审计那边是**无条件**跑的，判据钉住这一点。"""
    tree = _tree(SQUEEZED_AUDIT)
    calls = _calls_to(tree, "build_all")
    assert len(calls) == 1, (
        f"`squeezed_label_audit` 里 `build_all` 出现了 {len(calls)} 次")
    ifs = _guarding_ifs(tree, calls[0])
    assert not ifs, (
        "挤压审计里的对话框遍历被条件罩住了 —— 这一支没有开关，"
        f"多出来的条件是：{[ast.unparse(i.test) for i in ifs]}")


def test_both_audits_share_one_squeeze_judgement():
    """挤压判定只许有一份。

    ⛔ 对话框那一段不许另抄一份判定 —— 两份一定会漂，而漂了不报错。
    这支审计自己就栽过：量错了对象，从上线那天起红了一路（RN-505）。
    """
    tree = _tree(SQUEEZED_AUDIT)
    calls = _calls_to(tree, "_squeezed_labels")
    assert len(calls) >= 2, (
        f"页面与对话框应当各调用一次同一个判定函数，实际只有 {len(calls)} 次")
    room_calls = _calls_to(tree, "room_in_cell")
    assert len(room_calls) == 1, (
        f"`room_in_cell`（量尺）被调了 {len(room_calls)} 次 —— "
        "多于一次就说明判定逻辑被抄成了两份")


# ======================== 三、地板阈值别被改虚 ========================

def test_the_floor_rule_is_pinned_to_the_compact_window():
    """地板体检必须拿**紧凑档窗口**当预算，不能拿当前这一档。

    ⭐⭐ 拿 `(width, height)` 当预算的话，完整档 1280×800 下这条判据几乎恒真 ——
    而它要防的恰恰是「小屏用户拖不小」。**一个跟着当前档走的阈值，
    在最宽松的那一档里等于没有。**（同 RN-666：永远达不到的阈值 = 没有这一档。）
    """
    tree = _tree(LAYOUT_AUDIT)
    calls = _calls_to(tree, "floor_verdict")
    assert len(calls) == 1, f"`floor_verdict` 被调了 {len(calls)} 次"
    args = calls[0].args
    assert len(args) == 2, "`floor_verdict` 的调用形状变了"
    assert isinstance(args[1], ast.Name) and args[1].id == "COMPACT_SIZE", (
        "地板预算不是 `COMPACT_SIZE` 而是 "
        f"`{ast.unparse(args[1])}` —— 见本条 docstring")


def test_the_floor_rule_actually_rejects_a_too_tall_floor():
    """先证明这把尺子逮得住：喂一个地板超标的假对话框，它必须说话。

    ⭐ 不先验尺子，「地板都装得进紧凑档」那句话就只是**没人在看**。
    """
    class _FakeSize:
        def __init__(self, w, h):
            self._w, self._h = w, h

        def width(self):
            return self._w

        def height(self):
            return self._h

    class _FakeDialog:
        def __init__(self, w, h):
            self._size = _FakeSize(w, h)

        def minimumSize(self):
            return self._size

    budget = (860, 640)
    assert dlgs.floor_verdict(_FakeDialog(700, 700), budget), "高超标却没报"
    assert dlgs.floor_verdict(_FakeDialog(900, 400), budget), "宽超标却没报"
    assert not dlgs.floor_verdict(_FakeDialog(860, 640), budget), (
        "正好等于预算的地板被误报 —— 主窗装得下它就装得下（见 floor_verdict 的推导）")
    assert not dlgs.floor_verdict(_FakeDialog(400, 300), budget)


def test_every_dialog_debt_key_names_a_registered_dialog():
    """在册的对话框存量债，键必须指向清单里真有的那个对话框。

    ⭐ 打错一个字的后果不是红，是**那条债从此对不上账**：它既不再命中
    （于是只提醒不红），也不会拦住同一处的新债。
    """
    tree = _tree(LAYOUT_AUDIT)
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if not isinstance(key, ast.Tuple) or not key.elts:
                continue
            first = key.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if first.value.startswith("对话框:"):
                    keys.append(first.value)
    assert keys, "一条对话框存量债都没扫到 —— 分母为空，下面的断言是空的"
    known = set(dlgs.registered_keys())
    bad = sorted({k for k in keys if k.split("对话框:", 1)[1] not in known})
    assert not bad, f"这些债的键不在对话框清单里（打错字或对话框已删）：{bad}"


# ==================== 四、这一批修掉的三条，行为上钉住 ====================

#: 「添加在线音乐」属于被开源版裁掉的音乐链路 —— 那边没有这个文件。
#: ⛔ 不是 skip 成习惯：只对**这个检出里根本不存在**的对话框放行（见
#:   `test_the_subset_switch_cannot_hide_a_broken_entry`，它守着这个开关）。
_ADD_URL = next(s for s in dlgs.DIALOGS if s.key == "add_url")
_needs_add_url = pytest.mark.skipif(
    not _ADD_URL.available,
    reason="功能子集里没有 dialogs/add_url_dialog.py（音乐链路整条被裁）")


@pytest.fixture()
def _add_url(qapp):
    """真建一个「添加在线音乐」框。

    ⚠ `WA_DontShowOnScreen`：参与布局、拿真实字体度量，但永不映射到屏幕（§3）。
    ⛔ 绝不 `exec()` —— 模态框在测试进程里是**卡死不是失败**。
    """
    from PySide6.QtCore import Qt

    dlg = dlgs._build_add_url(None)
    dlg.setAttribute(Qt.WA_DontShowOnScreen, True)
    dlg.show()
    for _ in range(3):
        qapp.processEvents()
    yield dlg
    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()


def _text_box(btn) -> tuple[int, int, int, int]:
    """(横向可用, 横向需要, 纵向可用, 纵向需要)。

    ⚠⚠ **一定要向 style 要 `SE_PushButtonContents`，不能拿 `btn.height()` 顶替。**
    本判据第一版纵向那一半就是拿 `btn.height() < fontMetrics().height()` 写的，
    而 QSS 的 padding 把两者拉开了整整 14px：断点把尺寸策略删掉之后，
    按钮从 37px 掉到 34px（**文字可用区 20px < 字高 23px，已经在裁字了**），
    而 34 > 23 —— 判据一声不吭。**回退验证当场判它假绿。**
    ⭐ 又一次「尺子问错了问题」：我问的是「按钮够不够高」，
    要保证的是「留给字的那一格够不够高」。

    ⚠ 和排版审计那条判据是同一把尺，但这里**没法 import 它** —— 那个模块一被
    import 就会去隔离配置目录、`enable_audit_mode()`。真要改判定口径，
    改的是审计那一份，这里跟着复量即可。
    """
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    opt = QStyleOptionButton()
    btn.initStyleOption(opt)
    rect = btn.style().subElementRect(QStyle.SE_PushButtonContents, opt, btn)
    fm = btn.fontMetrics()
    return (rect.width(), fm.horizontalAdvance(btn.text().strip()),
            rect.height(), fm.height())


@_needs_add_url
def test_the_add_url_floor_fits_the_compact_window(_add_url):
    """地板不许再高过紧凑档窗口。原来钉的是 `setMinimumSize(700, 700)`。"""
    assert not dlgs.floor_verdict(_add_url, (860, 640)), (
        f"「添加在线音乐」的最小尺寸又顶穿紧凑档了：{dlgs.floor_of(_add_url)}。"
        "⛔ 别用显式 `setMinimumSize` —— 它会盖掉布局算出来的那个真实下限。")


@_needs_add_url
def test_the_add_url_copy_buttons_show_their_whole_label(_add_url, qapp):
    """「支持平台」页每颗「复制」按钮都要画得下「复制」两个字。"""
    from PySide6.QtWidgets import QPushButton, QTabWidget

    tabs = _add_url.findChildren(QTabWidget)[0]
    index = next(i for i in range(tabs.count()) if "平台" in tabs.tabText(i))
    tabs.setCurrentIndex(index)
    for _ in range(3):
        qapp.processEvents()

    copies = [b for b in tabs.currentWidget().findChildren(QPushButton)
              if b.text().strip() == "复制"]
    # 分母守卫：一颗都没有就说明这一页没渲染出来，"没被裁"是空话。
    assert len(copies) >= 2, (
        f"「支持平台」页只找到 {len(copies)} 颗「复制」按钮 —— "
        "样本退化了（`_SamplePlayer` 没拿到真的 url_resolver？），这条断言是空的")
    bad = [(w_have, w_need) for w_have, w_need, _h, _n in map(_text_box, copies)
           if w_need > w_have]
    assert not bad, (
        f"「复制」按钮的文字被裁：{bad}（可用, 需要）。"
        "⛔ 别再给它 `setFixedWidth` —— 字号一放大就不够。")


@_needs_add_url
def test_the_platform_cards_declare_themselves_unshrinkable(_add_url, qapp):
    """每张平台卡的**竖向尺寸策略必须是 Fixed** —— 卡有自然高度，装不下就滚。

    ## ⚠ 为什么这一条是机制级断言，而不是"把框压小看看字裂没裂"

    行为版我写了、也在审计进程里复现过（1.25 字号 + 620px 高 ⇒ 文字可用区
    20px 画 23px 的字，六颗一起中），**但它在 pytest 进程里三轮都压不出来** ——
    同一段代码、同样的 `apply_font_scale(1.25)`，量到的字高与可用区都不一样。
    ⭐ 按 §0「同一件事串行修 3 轮即停」停在这里，改钉机制本身，并把这条限制写在这儿。
    ⚠ 行为那一半没有丢：`layout_overflow_audit` 的按钮压扁判据每轮两档都在量它，
      本批那 12 条在册的对话框按钮债就是它报出来的。

    机制：`QScrollArea` 开了 `setWidgetResizable(True)` 之后会把内层控件 resize
    成视口大小，而内层控件**不是顶层窗口** —— `QLayout::SetDefaultConstraint`
    只给顶层窗口设 `minimumSize`，所以它一直是 (0,0)，视口一小就压扁而不是出滚动条。
    """
    from PySide6.QtWidgets import QFrame, QSizePolicy, QTabWidget

    tabs = _add_url.findChildren(QTabWidget)[0]
    index = next(i for i in range(tabs.count()) if "平台" in tabs.tabText(i))
    tabs.setCurrentIndex(index)
    for _ in range(3):
        qapp.processEvents()

    frames = [f for f in tabs.currentWidget().findChildren(QFrame)
              if f.frameShape() == QFrame.StyledPanel]
    assert len(frames) >= 2, (
        f"「支持平台」页只找到 {len(frames)} 张卡 —— 样本退化了，这条断言是空的")
    loose = [f for f in frames
             if f.sizePolicy().verticalPolicy() != QSizePolicy.Fixed]
    assert not loose, (
        f"{len(loose)}/{len(frames)} 张平台卡的竖向策略不是 Fixed，视口一小就会被"
        "压扁而不是让滚动条出来（1.25 字号档实测：文字可用区 20px 画 23px 的字）。")


@_needs_add_url
def test_the_platform_cards_scroll_instead_of_squashing(qapp):
    """框子变矮时平台卡该让滚动条出来，不是把自己压扁。

    ⭐⭐ 这一条是**修好上面那条地板之后才露出来的**：旧版开局 750px 高正好
    压不到，而那 750 本身就是毛病。一个缺陷可以一直替另一个缺陷挡着。
    ⚠ 只在 1.25 字号档现形 —— 所以这条判据自己把字号调上去。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    from ui_design_system import apply_font_scale

    apply_font_scale(1.25)
    try:
        from PySide6.QtWidgets import QTabWidget

        dlg = dlgs._build_add_url(None)
        dlg.setAttribute(Qt.WA_DontShowOnScreen, True)
        dlg.show()
        for _ in range(3):
            qapp.processEvents()

        # ⚠⚠ **先切到这一页，再压高度。** 顺序反了压不出来 ——
        #   不是当前页签的内容不参与那一次布局，于是 resize 之后再切过来时
        #   它拿到的是已经稳定下来的尺寸。判据第一版就是反的，
        #   **回退验证当场判它没逮住**（这是本条第二次栽在"量的时机"上）。
        tabs = dlg.findChildren(QTabWidget)[0]
        index = next(i for i in range(tabs.count()) if "平台" in tabs.tabText(i))
        tabs.setCurrentIndex(index)
        for _ in range(3):
            qapp.processEvents()

        dlg.resize(dlg.width(), 620)
        for _ in range(4):
            qapp.processEvents()

        copies = [b for b in tabs.currentWidget().findChildren(QPushButton)
                  if b.text().strip() == "复制"]
        assert len(copies) >= 2, "样本退化了，见上一条"
        # ⚠ 量的是**文字可用区**，不是按钮高 —— 见 `_text_box` 那段。
        squashed = [(h_have, h_need) for _w, _n, h_have, h_need in map(_text_box, copies)
                    if h_need > h_have]
        assert not squashed, (
            f"1.25 字号 + 620px 高下平台卡被压扁：{squashed}（文字可用高, 字高）。"
            "⛔ 平台卡要 `QSizePolicy.Fixed` —— `QScrollArea` 的内层控件不是顶层"
            "窗口，`SetDefaultConstraint` 不给它设 minimumSize，不钉就会被压。")
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()
    finally:
        apply_font_scale(1.0)
