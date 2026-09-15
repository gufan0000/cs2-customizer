# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""同一排控件，高度得是它那个角色声明的数（RN-549 / RN-550 / X2，批 66）。

## 一个根因，两条账

⭐⭐⭐ **设计系统的高度令牌被当成 QSS 的「内容盒」发出去了。**
`InputSpec.text_height = 34` / `ButtonSpec.secondary_height = 36` 这些名字都叫「高度」，
而 QSS 的 `min-height` 量的是**内容盒**：加上 `padding` 和 `border` 之后，
屏幕上分别是 **50** 和 **54**。⇒ 调用点写 `setFixedHeight(34)` 的每一处都成了死信
（Qt 在 min > max 时取 min），而**规格和调用点两处独立声明都写着同一个数**。

| 号 | 表现 | 数 |
|---|---|---|
| RN-549 | `gun_sound` 紧凑档底栏三颗按钮 **36 / 38 / 54** | 外审改完复跑 **2/3 发**独立报「同组控件高度不一致」 |
| RN-550 | 顶栏搜索框 **50** 高挂在 **50** 高的容器里、top=8 ⇒ 下边永远漏 **8px** | 两档每一页都有 |

⚠⚠ 而 RN-549 那一排在**批 63 之前是齐的**（三颗都被那条下限顶到 54）——
`mark_compact_buttons()` 只认「调用点声明的 max 比 QSS 下限还小」的按钮，
批 63 把认得出的两颗降下来、认不出的第三颗（写的是 `setMinimumHeight(30)`，
**只给下限没给上限**）留在原地，那一排才歪的。
⭐⭐⭐ **一次「把大部分修好」的改动，会把「全都一样地不对」变成「参差不齐」** ——
而后者在屏幕上更刺眼。

⚠ 全站输入框/下拉框还有 **5 种**在同一个机制下（实测 `QComboBox` 4 种 + `QLineEdit#input`），
  那是 **RN-551**，要动全站像素、单独一轮外审。这里只钉住这两处。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLineEdit, QPushButton, QWidget,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def compact_win(app):
    """⚠ RN-549 **只在紧凑档现形**（那颗按钮只在紧凑档才建出来）。
    `config.compact_mode` 必须在 `MainWindow` 构造**之前**赋值，
    否则只会得到「尺寸像紧凑、外壳是完整」的四不像（UP-100）。"""
    import gui_widget
    from _audit_neutralize import apply as neutralize_apply
    from _audit_sandbox import block_config_persistence, restore_config_persistence
    from config import config

    # ⚠⚠⚠ RN-558（批 67）：**这条夹具把 `compact_mode=True` 漏进了磁盘。**
    # 配置目录 `%TEMP%/cs2customizer_test_config` 是**固定名、跨轮次累积**的
    # （`conftest.py` 里那段，理由是 RN-141）；`config.compact_mode = True` 一赋值
    # 就被防抖/atexit 写了回去，而下面 teardown 里那句还原**没有再落一次盘**。
    # ⇒ 从批 66 起，**任何单跑的判据都在紧凑档下建窗口**：实测
    #   `test_keyboard_focus_is_visible` 单跑只取到 4 类按钮（侧栏在紧凑档是浮层、
    #   `isVisibleTo` 为假），而 `--jobs 6` 各有各的目录（`_w0..w5`）所以整跑看不见 ——
    #   ⭐⭐⭐ **一个缺陷只在「单跑」时现形，而门禁只看「整跑」。**
    # ⇒ 内存里怎么改都行，**磁盘上一个字都不许落**。RN-141 / 473 / 553 之后同形第四次。
    block_config_persistence(verbose=False)
    was = getattr(config, "compact_mode", False)
    config.compact_mode = True
    pages = ["gun_sound"]
    neutralize_apply(config, pages)
    w = gui_widget.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)   # ⛔ 不打扰前台
    w.resize(860, 640)
    w.show()
    app.processEvents()
    for pid in pages:
        try:
            w.show_page(pid, animated=False)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(6):
            app.processEvents()
    yield w
    w._force_exit = True
    w.close()
    config.compact_mode = was
    restore_config_persistence()


def _action_bars(win):
    out = []
    for page in win.pages.values():
        out.extend(w for w in page.findChildren(QWidget)
                   if w.__class__.__name__ == "PageActionBar")
    return out


def test_the_denominator_is_not_empty(compact_win):
    """分母守卫：底栏或那颗紧凑档按钮建不出来时必须喊出来。"""
    bars = _action_bars(compact_win)
    assert bars, "一条 PageActionBar 都没建出来 —— 这条判据在空转"
    btns = [b for bar in bars for b in bar.findChildren(QPushButton)
            if b.isVisibleTo(bar) and b.text().strip()]
    assert len(btns) >= 3, (
        f"底栏只量到 {len(btns)} 颗按钮（批 66 实测 gun_sound 紧凑档 3 颗）—— 分母塌了")


def test_every_action_bar_button_declares_a_row_height(compact_win):
    """RN-549：这一排里每颗按钮都必须**声明**一个高度，且是这一排的那两个数之一。

    ⚠⚠ 第一版判的是**渲染高 == 角色声明**，当场被离屏环境打红：
      offscreen 没有真字体，`sizeHint` 缩水，全排量出 31px 而 max 是 36/38。
      ⭐ 批 43 那句逐字写着：**能用结构表达的不变量，别拿像素去量。**
    ⇒ 改判「有没有声明」——那正是那颗 54px 缺的东西：它写的是
      `setMinimumHeight(30)`，**只给下限没给上限**，于是 `mark_compact_buttons()`
      认不出它（它只认「max 比 QSS 下限还小」的按钮），
      QSS 那条内容盒下限就原样留在它身上（36 + padding 8×2 + border 1×2 = **54**）。
    """
    from widgets.page_action_bar import PageActionBar

    # Qt 的「没有上限」哨兵；PySide6 不导出 QWIDGETSIZE_MAX，用它的值。
    NO_MAX = (1 << 24) - 1

    allowed = {PageActionBar.PRIMARY_HEIGHT, PageActionBar.SECONDARY_HEIGHT}
    bad, scanned = [], 0
    for bar in _action_bars(compact_win):
        for b in bar.findChildren(QPushButton):
            if not b.isVisibleTo(bar) or not b.text().strip():
                continue
            scanned += 1
            mx = b.maximumHeight()
            if mx >= NO_MAX:
                bad.append(f"{b.text().strip()!r} #{b.objectName()} "
                           f"**没有声明高度上限**（min={b.minimumHeight()}）")
            elif mx not in allowed:
                bad.append(f"{b.text().strip()!r} #{b.objectName()} "
                           f"声明的上限 {mx} 不是这一排的高度 {sorted(allowed)}")
    # 分母守卫（空转扫描器要求的那一句正向断言）：扫不到按钮时必须红，
    # 否则「分母为空」和「真的没问题」在报告上一模一样。
    assert scanned >= 3, (
        f"底栏只扫到 {scanned} 颗按钮（批 66 实测 gun_sound 紧凑档 3 颗）—— 这条判据在空转")
    assert not bad, (
        "底栏这几颗按钮没按这一排的规矩声明高度：\n  " + "\n  ".join(bad)
        + "\n⇒ 页面往这排里插按钮请走 `PageActionBar.adopt_button()`。")


def test_the_top_search_box_fits_inside_the_top_bar(compact_win):
    """RN-550：顶栏搜索框不许比它的容器还高。

    实测改前：框高 **50**、top=8、父容器高 **50** ⇒ 底边落在 58，
    下边框与底部圆角被顶栏的分割线切掉。**两档每一页都有。**
    """
    boxes = [e for e in compact_win.findChildren(QLineEdit)
             if e.objectName() == "settingsSearchBox"]
    assert len(boxes) == 1, f"顶栏搜索框找到 {len(boxes)} 个 —— 分母不对"
    box = boxes[0]
    parent = box.parentWidget()
    top = box.mapTo(parent, box.rect().topLeft()).y()
    over = (top + box.height()) - parent.height()
    assert over <= 0, (
        f"顶栏搜索框下边漏出容器 {over}px（框高 {box.height()}、top={top}、"
        f"容器高 {parent.height()}）—— 下边框与圆角会被顶栏的分割线切掉")


def test_the_compact_fixture_blocks_persistence_before_it_assigns():
    """RN-563（批 68）：**上面那条判据测的是它自己现写的一份复制品，不是这个夹具。**

    ⭐⭐⭐ 回退验证逮到的：断点把 `compact_win` 夹具里那句
    `block_config_persistence(...)` 改成 `pass`，而
    `test_this_file_does_not_leave_compact_mode_on_disk` **纹丝不动地绿着** ——
    因为它跑的是一个 subprocess 探针，探针源码里**自己另写了一句**
    `block_config_persistence`。破坏夹具对那份复制品毫无影响。
    ⇒ 批 47 RN-513 逐字那一条：**一条判据如果把被测的逻辑在测试里重写一遍，
    它测的就是自己的那一份。** 那条行为探针**仍然有价值**（它证明「掐落盘」这个机制真的有效），
    但它证明不了「**这个夹具用了它**」——那是两件事，要两条判据。

    ⇒ 本条走 AST 看结构：夹具里 `block_config_persistence` 的调用必须
    **早于**任何对 `config.compact_mode` 的赋值。
    """
    import ast

    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fixture = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == "compact_win"), None)
    assert fixture is not None, "找不到 compact_win 夹具 —— 它被改名了？分母守卫在此"

    block_line = None
    assign_line = None
    for node in ast.walk(fixture):
        if (block_line is None and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "block_config_persistence"):
            block_line = node.lineno
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Attribute) and t.attr == "compact_mode"
                        and isinstance(t.value, ast.Name) and t.value.id == "config"
                        for t in node.targets)):
            if assign_line is None or node.lineno < assign_line:
                assign_line = node.lineno

    assert block_line is not None, (
        "`compact_win` 夹具里没有 `block_config_persistence(...)` —— "
        "赋给 `config.compact_mode` 的值会被防抖/退出链路写回**跨轮次累积的共享目录**，"
        "于是从此每一次**单跑**判据都在紧凑档下建窗口，而 `--jobs N` 各有各的目录 ⇒ "
        "⭐⭐⭐ **门禁只看整跑，结构上看不见这件事**（RN-558）。")
    assert assign_line is not None, "夹具不再赋 `config.compact_mode`？那这条判据该退休了"
    assert block_line < assign_line, (
        f"`block_config_persistence` 在第 {block_line} 行，而 `config.compact_mode` "
        f"在第 {assign_line} 行就被赋值了 —— 掐落盘必须**在赋值之前**。")


def test_this_file_does_not_leave_compact_mode_on_disk(tmp_path, monkeypatch):
    """RN-558（批 67）：上面那条紧凑档夹具，不许把 `compact_mode` 落到磁盘上。

    ⭐⭐⭐ **一个漏进共享配置的布尔值，会把「单跑」和「整跑」变成两个世界。**
    `conftest.py` 把配置目录指到 `%TEMP%/cs2customizer_test_config`，那是个**固定名、
    跨轮次累积**的目录（理由是 RN-141）；而 `--jobs N` 会给每一路加 `_wI` 后缀。
    ⇒ 批 66 这条夹具赋的 `compact_mode = True` 被防抖写回磁盘、teardown 的还原
    **没有再落一次盘**，于是**从那以后每一次单跑判据都在紧凑档下建窗口**：

    | 判据 | 单跑（脏配置） | 整跑（`_w0..w5` 干净） |
    |---|---|---|
    | `test_keyboard_focus_is_visible` | 只取到 **4/8** 类按钮（侧栏在紧凑档是浮层）| 绿 |
    | `test_search_jump_r13` | 4 跑 3 红、每次红的用例都不同 | 绿 |

    ⭐ 我为此追了几个小时的「不稳定」，根都在这一处。RN-141 / 473 / 553 之后**同形第四次**。
    ⇒ 夹具期间掐掉落盘（`block_config_persistence`），内存里怎么改都行。

    ⚠ 这条判据自己**不碰**共享目录：把 `CS2C_CONFIG_DIR` 指到 `tmp_path`，
      在那儿走一遍同样的赋值 + 还原，然后看磁盘上有没有留下 `compact_mode: true`。
    """
    import json
    import subprocess
    import sys as _sys

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, r'{REPO}')\n"
        f"sys.path.insert(0, r'{REPO / 'scripts'}')\n"
        "from _audit_sandbox import block_config_persistence, restore_config_persistence\n"
        "from config import config\n"
        "block_config_persistence(verbose=False)\n"
        "was = getattr(config, 'compact_mode', False)\n"
        "config.compact_mode = True\n"
        # ⭐ 关键：真实世界里防抖/退出链路会在这一刻落一次盘（`_audit_sandbox`
        #   的说明里逐字列了三条路）。判据必须把那一下**演出来** ——
        #   否则短生命周期的探针根本不写文件，第一版就是这么假绿的，破坏验证当场逮到。
        "config.save_config_now()\n"
        "config.compact_mode = was\n"
        "restore_config_persistence()\n",
        encoding="utf-8")
    env = dict(os.environ)
    env["CS2C_CONFIG_DIR"] = str(tmp_path / "cfg")
    env["CS2C_LOG_DIR"] = str(tmp_path / "logs")
    subprocess.run([_sys.executable, str(probe)], check=True, capture_output=True,
                   env=env, cwd=str(REPO))

    written = tmp_path / "cfg" / "config.json"
    if not written.exists():
        return          # 一个字都没落盘 —— 这正是要的
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data.get("compact_mode") is not True, (
        "紧凑档夹具把 `compact_mode: true` 留在了磁盘上。\n"
        "⭐ 配置目录是跨轮次累积的固定名，于是从此每一次**单跑**判据都在紧凑档下建窗口，"
        "而 `--jobs N` 各有各的目录 —— **门禁只看整跑，看不见这件事。**")
