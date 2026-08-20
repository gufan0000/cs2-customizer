# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""`hud_color` 页的行为基线（翻新工程 M3 开档时补，此前**一支测试都没有**）。

这一页的特殊之处：它是少数几个**会往游戏目录写文件**的页面之一
（`write_cs2customizer_cfg` + `write_runtime_cfg` + `setup_autoexec`），
而且带一个"有未保存修改就拦住你离开"的脏状态机。
两件事凑一起，最危险的形状就是 **`_dirty` 与"到底写没写进游戏"脱钩**。

## RN-130：保存失败之后，页面显示"没有未保存修改"

`_save_hud_rules` 的顺序是：

    config.save_config()
    self._set_dirty(False)          # ← 先把脏标志清了
    ...
    write_cs2customizer_cfg(config)        # ← 这里抛异常的话
    ...
    except Exception:
        QMessageBox.critical(...)   # 弹个错
        return False                # 但 _dirty 已经是 False 了

于是：用户看到一个报错框，关掉；页面状态显示"已保存"；切页不再拦他。
**软件配置存住了，游戏里的 CFG 没写成，而界面上没有任何痕迹说明这件事。**

⇒ 可复用的问法：**"我干完了"这个标志，是在动作**开始**时置的，还是在动作
  **成功**之后置的？**（同族：QA-006「写失败后本次会话永不重试」。）
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from config import config
import pages.hud_color_page as page_module


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """拦掉模态框 —— 这一页有 10 处 QMessageBox，不拦会把 pytest 卡死。

    ⚠ 钩子挂在 **Qt 类本身**，不挂在页面模块里那个名字上（RN-125 的教训：
    页面哪天不再 import 它，这道防线会连同 import 一起被摘掉）。
    """
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0), raising=False)


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    p = page_module.HudColorPage()
    p.setAttribute(Qt.WA_DontShowOnScreen, True)
    yield p
    p.deleteLater()
    qapp.processEvents()


# ------------------------------------------------------------------ 读写往返


def test_rules_survive_a_round_trip_through_the_ui(page):
    """设置读写往返：UI 读出来的规则，再写回 UI，必须一字不差。

    这是这一页最基本的不变量 —— 它下面接着 CFG 编译器，规则错一位，
    游戏里的 HUD 就变成另一个颜色，而软件这边什么都不会报。
    """
    from core.hud.rule_model import normalize_profile

    before = page._build_rules_from_ui()
    profile = normalize_profile(page.profile_combo.currentData())
    page._apply_rules_to_ui(profile, before)
    after = page._build_rules_from_ui()
    assert after == before, "规则过一遍 UI 就变了 —— 下游 CFG 会跟着错"


def test_toggling_a_key_rule_changes_what_gets_compiled(page):
    """空转守卫：上面那条只验"没变"，得有人证明这些控件**真的**接在规则上。"""
    key = next(iter(page.key_widgets))
    widgets = page.key_widgets[key]
    before = page._build_rules_from_ui()["key_rules"][key]["enabled"]
    widgets["enabled"].setChecked(not before)
    after = page._build_rules_from_ui()["key_rules"][key]["enabled"]
    assert after != before, f"改了数字键 {key} 的勾选，编译出来的规则没跟着变"


# ------------------------------------------------------------------ 脏状态机


def test_a_clean_page_lets_you_leave(page):
    assert page.can_leave_page() is True


def test_editing_marks_the_page_dirty(page, qapp):
    key = next(iter(page.key_widgets))
    page._set_dirty(False)
    page.key_widgets[key]["enabled"].toggle()
    qapp.processEvents()
    assert page._dirty, "改了设置却没标记为未保存 —— 离开时不会拦，改动会被静默丢掉"


def test_a_failed_save_leaves_the_page_dirty(page, monkeypatch, qapp):
    """⭐ RN-130：写 CFG 失败时，**不许**把"未保存"标志清掉。

    失败之后 `_dirty` 若为 False：状态栏显示已保存、切页不再拦、
    用户以为设置已经进游戏了 —— 而 CFG 根本没写成。
    """
    monkeypatch.setattr(config, "csgo_dir", r"C:\somewhere\csgo", raising=False)

    def boom(*a, **k):
        raise OSError("cfg 被占用")

    monkeypatch.setattr("core.cfg_compiler.write_cs2customizer_cfg", boom, raising=False)

    page._set_dirty(True)
    ok = page._save_hud_rules(show_success_dialog=False)
    qapp.processEvents()

    assert ok is False, "写 CFG 失败了却报告保存成功"
    assert page._dirty, (
        "写 CFG 失败之后页面却显示「没有未保存修改」—— "
        "用户会以为规则已经进游戏了，而实际上没有")


def test_a_successful_save_clears_the_dirty_flag(page, monkeypatch, qapp):
    """反面守卫：成功时必须清掉，否则上面那条可以靠"永远脏"通过。"""
    monkeypatch.setattr(config, "csgo_dir", "", raising=False)   # 没配游戏目录 = 只存软件配置
    page._set_dirty(True)
    ok = page._save_hud_rules(show_success_dialog=False)
    qapp.processEvents()
    assert ok is True
    assert not page._dirty, "保存成功了还标着未保存，用户每次切页都会被拦一次"
