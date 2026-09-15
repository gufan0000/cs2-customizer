# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from config import config
import pages.advanced_page as advanced_page_module


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _visible_audio_status_chip_texts(status_bar) -> list[str]:
    layout = status_bar.layout()
    if layout is None:
        return []
    texts: list[str] = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            texts.append(widget.text())
    return texts


def _create_valid_cs2_root(tmp_path: Path) -> Path:
    root = tmp_path / "Counter-Strike Global Offensive"
    (root / "game" / "csgo" / "cfg").mkdir(parents=True, exist_ok=True)
    return root


def test_advanced_page_overview_badges_sync(qapp, tmp_path, monkeypatch):
    cs2_root = _create_valid_cs2_root(tmp_path)

    monkeypatch.setattr(config, "csgo_dir", str(cs2_root), raising=False)
    monkeypatch.setattr(config, "debug_mode", False, raising=False)
    monkeypatch.setattr(config, "ui_theme", "dark", raising=False)
    # RN-138：调试徽章现在只在**看得见调试卡片**时才挂（专家模式）。
    # ⚠ 这一行不是可有可无的：原先本条判据不钉界面模式，于是它读的是
    # **conftest 那个跨文件跨轮次累积的配置目录**里恰好留下的值 ——
    # 本机（累积成专家模式）4 颗徽章绿，CI（全新配置）3 颗当场红。
    # ⭐ **一条不钉前置状态的判据，绿不绿取决于前面跑过谁。**
    monkeypatch.setattr(config, "ui_expert_mode", True, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(advanced_page_module, "find_cfg_path", lambda: None)

    page = advanced_page_module.AdvancedPage()

    assert page.page_lead_label.objectName() == "pageLeadLabel"
    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text == "目录 · 已配置" for text in chips)
    assert any(text == "来源 · 手动设置" for text in chips)
    assert any(text == "调试 · 未启用" for text in chips)
    assert any(text == "主题 · 深色主题" for text in chips)
    assert page.debug_status_label.objectName() == "statusLabel"
    assert "正常使用状态" in page.debug_status_label.text()
    assert str(cs2_root) in page.csgo_dir_text.toolTip()
    assert str(cs2_root) in page.status_card.toolTip()

    page.debug_mode = True
    page._update_debug_status()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "调试 · 已启用" for text in chips)
    assert "已启用调试模式" in page.debug_status_label.text()

    light_index = page.theme_combo.findData("light")
    page._on_theme_changed(light_index)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "主题 · 浅色主题" for text in chips)

    page._auto_detected = True
    page._sync_overview_status()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "来源 · 自动检测" for text in chips)

    page.deleteLater()
    qapp.processEvents()


def test_the_view_payload_button_does_not_declare_a_height_below_the_qss_floor(qapp):
    """⛔ RN-591：「查看将上报的内容」那颗按钮**不许自带比 QSS 下限矮的高度声明**。

    ⭐⭐⭐ 那句 `setFixedHeight(32)` 从写下那天起就没让它变成过 32：32 比 QSS 给
    `secondaryButton` 的下限矮 ⇒ `mark_compact_buttons()` 判「调用点声明得更矮」⇒
    标 `fp_short` ⇒ 那条下限被摘成 `0px` ⇒ 控件 min 塌到 **18**（只剩 padding+border）
    ⇒ 这张卡竖向一紧就被压到 **22**，16px 的字**只画得出上半截**
    （外审整页图 3/3 报「完全无法辨认」，逐像素复核成立）。
    ⭐⭐⭐ **它唯一的作用，是把这颗按钮从「和兄弟一样高」变成「可以被压扁」。**

    ⚠⚠ 这条是**回退验证逼出来的**：我原先把这个断点挂在
    `test_layout_audit_checks_button_text_vertically` 上，而**那条判据喂的是合成按钮、
    根本不看真页面** ⇒ 把 `setFixedHeight(32)` 放回去它照样绿。
    ⭐⭐⭐ **断点打在了被测对象上，判据却盯着另一个对象 —— 汇总行上看不出区别。**

    ⇒ 这条查**源码里那一行在不在**（而不是量像素）：像素在 CI 的字体度量下不复现
    （`_split_known` 那段记着 2026-08-22 公开仓 `e265ab1` 被这么判红过），
    而「有没有写这句声明」在哪台机器上都一样。
    """
    import ast
    import inspect
    import textwrap

    src = inspect.getsource(advanced_page_module.AdvancedPage._create_usage_report_section)
    tree = ast.parse(textwrap.dedent(src))
    # ⚠ 分母守卫（空转风险棘轮第三次逮我，批 75 ×2 + 本条）：这段源码里必须真的建着
    #   那颗按钮，否则「没写矮声明」和「按钮已经搬走 / 方法被掏空」在报告上是同一个绿。
    buttons = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "QPushButton"
        and n.args and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "查看将上报的内容"
    ]
    assert len(buttons) == 1, "分母塌了：`_create_usage_report_section` 里找不到「查看将上报的内容」那颗按钮"
    bad = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") in ("setFixedHeight", "setMinimumHeight")
        and n.args and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, int) and n.args[0].value < 36
    ]
    assert not bad, (
        f"`_create_usage_report_section` 里第 {bad} 行又写了比 QSS 下限（36）矮的高度声明 —— "
        "它不会让按钮变矮，只会让 `fp_short` 摘掉地板，"
        "然后布局把它压到比声明还矮的位置，字被裁掉一截（RN-591）。")
