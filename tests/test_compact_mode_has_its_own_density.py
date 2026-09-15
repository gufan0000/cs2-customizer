# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""紧凑档要有自己的一档版面密度（RN-548 / X2，批 65），而且那一档不许是死信。

## 这条判据在防什么

⭐⭐⭐ **紧凑档以前只是把窗口改小**：1280×800 → 860×640，内容可视区 750 → 462px
（少 288px），而版面密度**一档都没跟着变**。于是它的竖向余量不到 1px ——
滚动条从 6 加到 **7px 就当场红**（批 62 实测），10px 时多出 13 处「最小高超出可视区」。
⭐ **一个已经零余量的容器，会把任何一次改进都变成一次「变坏」**，
   而历史上那次「收窄到 6px，更精致」正是这么来的：**不是审美，是没地方了。**

## 而立案说的修法走不通 —— 这一条比缺陷本身更值钱

RN-548 立案写的是「给 `ui_design_system` 加一档跟着窗口模式变的规格」。
批 65 开工先用 AST 数了一遍：全仓 **813 处** `setContentsMargins` / `setSpacing` /
`setFixedHeight` / `setMinimumHeight` 里，实参来自设计系统 token 的只有 **8 处（1%）**；
`spacing` / `container` 两组 token 的读取点只剩 `gui_widget.py` **6 处**。
⭐⭐⭐ **给一个没人在读的规格加一档，等于什么都没做。**
⇒ 改成一条**上限**：`apply_compact_density()` 在页面建完之后把已经写死的数收一收。

⇒ 所以本文件有两类判据，缺一不可：
  ① 这一档**真的动了像素**（收得到、还得回去、完整档不受影响）；
  ② 这一档**没有变成第二个死信**（数住在设计系统里、且真的有人调它）。
     ⭐ 只写第①类的话，下一次有人把调用点删掉，全量照样全绿。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QBoxLayout, QFormLayout, QGridLayout,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget

    w = gui_widget.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)   # ⛔ 不打扰前台
    w.resize(1280, 800)
    w.show()
    app.processEvents()
    for pid in list(w._page_names):
        try:
            w.show_page(pid, animated=False)
        except Exception:  # noqa: BLE001
            pass
    app.processEvents()
    yield w
    w._force_exit = True
    w.close()


def _all_layouts(root):
    from ui_style_applier import _vertical_layouts

    return _vertical_layouts(root)


def _fingerprint(root):
    """每个 layout 的竖向数字，用于比对「收了」「还回去了」。"""
    out = {}
    for lay in _all_layouts(root):
        m = lay.contentsMargins()
        if isinstance(lay, (QGridLayout, QFormLayout)):
            sp = lay.verticalSpacing()
        elif isinstance(lay, QBoxLayout):
            sp = lay.spacing()
        else:
            sp = None
        out[id(lay)] = (m.top(), m.bottom(), sp)
    return out


def test_the_tier_actually_squeezes_something(app, win):
    """①-a 分母守卫：这一档收不到任何东西时，必须喊出来。

    ⚠⚠ **两个轴都要单独数。** 第一版只问「有没有 ≥50 个 layout 动了」，
    而这一档有**两个上限**（竖向间距、上下边距）—— 回退验证把间距那个调成 9999，
    边距那个照样在收，判据**照样绿**。
    ⭐⭐ **一条只问「有没有东西动」的判据，看不见「两件事里坏了一件」**
    （同 RN-185：只看「齐不齐」的判据看不见「全都不对」）。
    """
    from ui_design_system import get_design_system
    from ui_style_applier import apply_compact_density

    cap = get_design_system().density.compact_max_vertical_margin
    apply_compact_density(win, False)
    app.processEvents()
    before = _fingerprint(win)
    apply_compact_density(win, True)
    app.processEvents()
    after = _fingerprint(win)
    try:
        moved = [k for k in before if before[k] != after.get(k)]
        margins = [k for k in moved if before[k][:2] != after[k][:2]]
        spacings = [k for k in moved if before[k][2] != after[k][2]]
        assert len(moved) >= 50, (
            f"紧凑密度只动了 {len(moved)} 个 layout（分母 {len(before)}）—— "
            f"这一档在空转。上限 {cap}px")
        assert len(margins) >= 20, (
            f"**上下边距**那个轴只动了 {len(margins)} 个 layout —— 它那条上限在空转")
        assert len(spacings) >= 20, (
            f"**竖向间距**那个轴只动了 {len(spacings)} 个 layout —— 它那条上限在空转")
        # ⭐ 而且只许**变小**：这一档是上限，不是「重排版面」。
        grew = [k for k in moved
                if any(a is not None and b is not None and b > a
                       for a, b in zip(before[k], after[k]))]
        assert not grew, f"有 {len(grew)} 个 layout 的竖向数字被**改大**了 —— 上限档不该把谁撑开"
    finally:
        apply_compact_density(win, False)
        app.processEvents()


def test_full_mode_is_left_alone(app, win):
    """①-b 完整档必须一个像素都不动 —— 这一档只买紧凑档的余量。"""
    from ui_style_applier import apply_compact_density

    apply_compact_density(win, False)
    app.processEvents()
    a = _fingerprint(win)
    apply_compact_density(win, False)
    app.processEvents()
    assert a == _fingerprint(win), "完整档反复调用竟然改了数 —— 它不是幂等的"


def test_the_tier_round_trips(app, win):
    """①-c **拨得回去**。紧凑/完整是界面上一颗按钮，用户随时会拨回来；
    还不回原样就等于把紧凑档的间距永久带进了完整档。"""
    from ui_style_applier import apply_compact_density

    apply_compact_density(win, False)
    app.processEvents()
    origin = _fingerprint(win)
    for _ in range(2):          # 拨两轮：幂等性也一起验了
        apply_compact_density(win, True)
        app.processEvents()
        apply_compact_density(win, False)
        app.processEvents()
    back = _fingerprint(win)
    bad = {k: (origin[k], back.get(k)) for k in origin if origin[k] != back.get(k)}
    assert not bad, (
        f"拨回完整档之后有 {len(bad)} 个 layout 没回到原样，例如："
        + str(list(bad.items())[:3]))


def _func_source(module_path: str, func_name: str) -> ast.FunctionDef:
    tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    raise AssertionError(f"{module_path} 里找不到 {func_name}()")


def test_the_caps_live_in_the_design_system():
    """②-a 数必须住在设计系统里，不许在实现里写死。

    ⭐ 这一条是本批那个发现的反面：**规格层之所以变成死信，是因为没有任何东西
    要求实现去读它。** 一旦这里也写死数字，下一个人改密度会去改实现，
    设计系统那一档当天就再次变成注释。
    """
    fn = _func_source(str(REPO / "ui_style_applier.py"), "apply_compact_density")
    reads = {n.attr for n in ast.walk(fn)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
             and n.value.attr == "density"}
    assert {"compact_max_vertical_spacing", "compact_max_vertical_margin"} <= reads, (
        f"`apply_compact_density` 没有从 `ds.density` 读上限，只读到 {sorted(reads)}")


def test_the_tier_is_wired_into_the_window():
    """②-b 有人调它 —— 而且**两条路都要有**：建页那条和拨档那条。

    ⚠ 只有建页那条的话，用户在界面上点「⇔ 紧凑」时已经建好的页不会跟着收；
      只有拨档那条的话，拨完之后新建的页不会跟着收。两条缺一条都是半个功能。
    """
    tree = ast.parse((REPO / "gui_widget.py").read_text(encoding="utf-8"))
    callers = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id == "apply_compact_density"):
                callers.add(node.name)
    assert "_apply_compact_mode" in callers, (
        f"拨档那条路没调 `apply_compact_density`（调用点：{sorted(callers)}）—— "
        "用户点「⇔ 紧凑」时已经建好的页不会跟着收")
    assert callers - {"_apply_compact_mode"}, (
        f"只有拨档那条路在调（调用点：{sorted(callers)}）—— 拨完之后新建的页不会跟着收")


def test_the_scrollbar_is_wide_enough_to_be_discoverable():
    """②-c 滚动条宽度**不许再退回去**（RN-045）。

    同题面行为题四档，问「这一页显示完了吗？你从画面哪儿看出来的」，
    数「依据里提到滚动条」的比例：

    | 那一档 | 有效发 | 提到滚动条 |
    |---|---|---|
    | 修之前（6px，1.06:1） | 12 | **0（0%）** |
    | 批 61 只修对比度（6px，3.4:1） | 21 | **3（14%）** |
    | 加宽到 10px | 20 | **10（50%）** |
    | 批 62 发货版（6px + 把透明轨道画出来） | 24 | **1（4%）** |

    ⭐⭐⭐ **我用一个「看起来等价、又不占版面」的替代方案，换掉了一个已经被数
    证明有效的方案 —— 而换的时候手上没有数。** 那 4px 一直要不起，
    不是因为它贵，是因为**装它的那个容器早就没有余量了**（RN-548）。
    """
    from ui_design_system import ScrollbarSpec

    assert ScrollbarSpec().width >= 10, (
        f"滚动条又被收窄到 {ScrollbarSpec().width}px —— "
        "行为题实测 6px 只有 4~14% 的人看得出这里能滚，10px 是 50%")
