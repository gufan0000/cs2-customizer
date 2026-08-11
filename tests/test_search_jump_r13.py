# -*- coding: utf-8 -*-
"""R13 搜索跳转链路的**端到端**判据（离屏真窗口，2026-08-10）。

`test_settings_search_r13.py` 量的是搜索引擎本身（纯函数）。这一份量的是
**另一条通道**：索引说某一项存在，跳过去之后运行时到底能不能在真实页面上
找到它并高亮。

⚠ 为什么要两条通道分开量（QA-018 的直接教训）：
索引是离线生成的，它自己的自洽证明不了运行时能用。如果只量引擎，
"索引里有 369 条、搜得到" 会全绿，而用户点过去发现页面上什么也没高亮 ——
一条通道的自洽不是证据。这里就是那第二条通道。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget
    from config import config

    config.ui_expert_mode = True
    w = gui_widget.MainWindow(auto_background_preload=False)
    yield w
    try:
        w.close()
        w.deleteLater()
        app.processEvents()
    except Exception:
        pass


def _type(win, app, text):
    """模拟用户敲键：走的是真实的 textEdited 通路，不是直接塞 model。"""
    win.settings_search_box.setText(text)
    win._on_search_text_edited(text)
    app.processEvents()


def _popup_rows(win):
    """读**用户真正看得见的那份**候选。

    ⚠ 这里必须用 `completionModel()`，不能用 `model()`。
    回退验证当场逮到过：把 `UnfilteredPopupCompletion` 换回
    `setFilterMode(MatchContains)`（也就是把改造整个退回去），
    判据居然照样绿 —— 因为 `model()` 是**源** model，无论怎么过滤都是全量；
    popup 显示的是 QCompleter 内部那层代理 `completionModel()`。
    量错了通道，判据就是假绿的。
    """
    from widgets.search_popup import ROLE_KIND, ROLE_PAGE_ID

    completer = win._settings_search_completer
    completer.setCompletionPrefix(win.settings_search_box.text())
    model = completer.completionModel()
    return [
        {
            "text": model.index(r, 0).data(Qt.DisplayRole),
            "page_id": model.index(r, 0).data(ROLE_PAGE_ID),
            "kind": model.index(r, 0).data(ROLE_KIND),
        }
        for r in range(model.rowCount())
    ]


# ---------------- 下拉里看到的 == 引擎算出来的 ----------------


@pytest.mark.parametrize("query", ["zx", "zhunxin", "准心", "音量", "dukcing", "声音太大"])
def test_popup_rows_match_engine(win, app, query):
    """改造前这条一定红：下拉走 QCompleter 纯子串，`zx` 是 0 行。"""
    from core.settings_search import search_detailed

    _type(win, app, query)
    rows = _popup_rows(win)
    expected = search_detailed(query)
    assert rows, f"「{query}」的下拉是空的"
    assert [r["page_id"] for r in rows] == [e["page_id"] for e in expected]
    assert [r["text"] for r in rows] == [e["text"] for e in expected]


def test_popup_carries_page_id_not_parsed_from_text(win, app):
    """重名项必须靠 UserRole 区分。「准心大小」在准心设置和预设中心都有。"""
    _type(win, app, "准心大小")
    rows = [r for r in _popup_rows(win) if r["text"] == "准心大小"]
    assert rows, "没搜到「准心大小」"
    assert all(r["page_id"] for r in rows)


# ---------------- 跳过去之后，真的定位到了那一行 ----------------


@pytest.mark.parametrize("query,page_id", [
    ("观战静音", "basic"),
    ("准心大小", "crosshair"),
    ("原声保留", "gun_sound"),
])
def test_jump_lands_and_highlights_a_real_row(win, app, query, page_id):
    _type(win, app, query)
    rows = _popup_rows(win)
    assert rows and rows[0]["page_id"] == page_id, rows[:3]

    win._on_search_return()
    app.processEvents()

    assert win._current_page_id == page_id
    target = getattr(win, "_search_hit_target", None)
    assert target is not None, "跳过去了但什么都没高亮"

    # 高亮的这一块里必须真的含有查询词——否则等于随便亮了个东西糊弄人
    texts = _visible_texts(target)
    assert any(query in t for t in texts), (
        f"高亮的目标里没有「{query}」，只有 {texts[:6]}"
    )


def _visible_texts(widget):
    from PySide6.QtWidgets import QWidget

    out = []
    for w in [widget] + widget.findChildren(QWidget):
        try:
            t = w.text() if hasattr(w, "text") else ""
        except Exception:
            t = ""
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out


@pytest.mark.parametrize("query,page_id,tab", [
    ("启用回合音效", "special_sound", "回合"),
    ("启用投掷物音效", "special_sound", "投掷物"),
    ("启用低血量警告", "special_sound", "血量警告"),
])
def test_jump_switches_to_the_right_tab(win, app, query, page_id, tab):
    """项落在非当前页签里时，跳转必须先把页签切过去。

    ⚠ 这条一定要走**真实跳转链路**（_on_search_return），不能在测试里自己
    调 `_activate_page_tab` 再断言。回退验证当场逮到过：第一版判据自己先切了
    页签，于是把 `_highlight_search_target` 里那句切页签删掉，判据照样绿 ——
    量的是那个 helper，不是"跳转有没有用它"。
    """
    win.show_page("basic", force=True)
    app.processEvents()
    _type(win, app, query)
    win._on_search_return()
    app.processEvents()

    assert win._current_page_id == page_id
    page = win.pages.get(page_id)
    from PySide6.QtWidgets import QTabWidget

    tabs = [t for t in page.findChildren(QTabWidget) if t.count() > 0]
    assert tabs, f"{page_id} 上没找到页签控件"
    current = [t.tabText(t.currentIndex()).strip() for t in tabs]
    assert tab in current, f"页签没切到「{tab}」，当前是 {current}"

    target = getattr(win, "_search_hit_target", None)
    assert target is not None
    assert any(query in t for t in _visible_texts(target)), (
        f"切到页签了但高亮的不是「{query}」")


def test_every_indexed_item_is_locatable_on_its_page(win, app):
    """**跨通道对拉**：抽查索引里的项，在真实页面上是不是都找得到。

    这是本文件存在的理由。全量跑太慢（369 条 × 建页），所以按页抽样，
    但**分母如实打印**——静默抽样会被读成"全都验过了"。
    """
    from core.settings_search import text_matches

    data = json.loads((ROOT / "core" / "search_index.json").read_text(encoding="utf-8"))
    # 只查运行时通道覆盖过的页：静态通道收的项来自源码字面量，
    # 有些挂在条件分支里，默认配置下本来就不该在页面上（不是缺陷）。
    runtime_pages = set(data["coverage"]["runtime_pages"])
    by_page = {}
    for it in data["items"]:
        if it["page"] in runtime_pages and it["kind"] in ("check", "radio"):
            by_page.setdefault(it["page"], []).append(it)

    checked = missing = 0
    misses = []
    for pid, items in sorted(by_page.items()):
        win.ensure_page_loaded(pid)
        win.show_page(pid, force=True)
        app.processEvents()
        page = win.pages.get(pid)
        if page is None:
            continue
        for it in items[:4]:      # 每页抽 4 条
            checked += 1
            win._activate_page_tab(page, it.get("tab", ""))
            app.processEvents()
            if win._find_setting_row(page, it["text"]) is None:
                # 退回卡片级也算找到（跳转链路本来就有这层兜底）
                if not any(text_matches(it["text"], t) for t in _visible_texts(page)):
                    missing += 1
                    misses.append(f"{pid}:{it['text']}")

    print(f"\n[跨通道对拉] 抽查 {checked} 条勾选/单选项（共 {len(data['items'])} 条索引，"
          f"覆盖 {len(by_page)} 个运行时页）")
    assert checked >= 20, f"抽样太少({checked})，这条判据说明不了问题"
    assert not misses, f"索引里有、页面上找不到：{misses}"


# ---------------- 空态与最近搜索 ----------------


def test_empty_box_offers_suggestions(win, app):
    win._show_search_suggestions()
    app.processEvents()
    rows = _popup_rows(win)
    assert rows, "空搜索框应该给出「最近搜索/常去页面」，不该是一片空白"
    assert all(r["kind"] in ("recent", "suggest") for r in rows)


def test_no_result_query_still_offers_a_way_out(win, app):
    _type(win, app, "asdfghjkl")
    rows = _popup_rows(win)
    assert rows, "搜不到时也要给出路，不能只弹一句「没有匹配」"
    assert all(r["kind"] in ("recent", "suggest") for r in rows)
    # 建议行不许被回车当成结果跳过去
    actionable = [r for r in (win._search_rows or []) if r.get("kind") in ("item", "page")]
    assert not actionable


@pytest.mark.parametrize("theme", ["dark", "light", "green", "contrast"])
def test_popup_follows_theme_with_readable_contrast(win, app, theme):
    """结果面板必须跟着主题走，且文字与底色要有真实对比度。

    ⚠ 这条是**渲染实测**逼出来的，逻辑判据一条都看不见它：
    completer 的 popup 是带 Qt::Popup 标志的独立顶层 QListView，
    接不到打在 MainWindow 上的那份 QSS，而 QSS 里也没有针对裸 QListView 的规则 ——
    深色主题下它一直是**纯白**的。
    修好之后又踩第二个坑：QSS 里同时写 background 会和 palette 打架，
    浅色主题变成**白字白底**。所以这里量的不是"有没有设主题"，
    而是"底色和文字到底差多少" —— 只有后者骗不了人。
    """
    from theme_manager import get_theme_manager

    get_theme_manager().set_theme(theme)
    app.processEvents()

    pal = win._settings_search_completer.popup().palette()
    base = pal.base().color()
    text = pal.text().color()
    # 亮度差：小于 0.25 基本就是"看不见"（白字白底那次实测差 0.06）
    delta = abs(base.lightnessF() - text.lightnessF())
    assert delta >= 0.25, (
        f"{theme} 主题下结果面板底色 {base.name()} 与文字 {text.name()} "
        f"亮度只差 {delta:.2f} —— 用户看不清"
    )
    # 深色主题的面板底色必须真的是深的，不能停在系统默认白
    if theme in ("dark", "contrast"):
        assert base.lightnessF() < 0.5, f"{theme} 主题下面板还是亮的: {base.name()}"


def test_search_box_width_is_elastic(win):
    """紧凑模式只有 860 宽，钉死 220 会把顶栏右侧的按钮挤扁。"""
    box = win.settings_search_box
    assert box.minimumWidth() < box.maximumWidth()
    assert box.maximumWidth() < 16777215, "没有设上限等于没约束"
