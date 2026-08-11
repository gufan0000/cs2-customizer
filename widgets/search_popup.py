# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""顶栏搜索结果面板（S4/S5，2026-08-10）。

**改造前是什么样**：搜索框挂一个 `QCompleter`，喂给它 396 条固定字符串
（"页面名 · 关键词"），过滤方式是 Qt 自带的 `MatchContains` —— 纯子串。
而按回车走的是 `core.settings_search.search()`，带拼音、首字母、拼写容错、
口语近义。**下拉和回车是两套完全不同的搜索引擎**，实测 19 条查询里 11 条
表现不一致：打 `zx` 下拉一条不出（396 条串里没有 "zx"），回车却能跳到准心设置；
打 `音` 下拉刷出 167 条按字母序排的候选，只露前 9 条。

也就是说，拼音搜索、口语搜索、拼写容错这三样做好的功能，**在下拉里全部不可见**。
用户打 `zx` 看到空下拉，第一反应是"搜不到"，不会再去按回车。做了等于没做。

**改造后**：`QCompleter` 只当弹窗机制用（焦点、Esc、上下键、DPI、输入法这些
它已经处理好了，从零写一个 popup 是本轮最大的风险面），换掉两样东西 ——
  1. `UnfilteredPopupCompletion`：不让它自己过滤，原样显示我喂的 model；
  2. model 由 `search_detailed()` 的结果**每次按键重建**。
于是下拉里的顺序就是相关度顺序，三样能力立刻可见。

`page_id` 走 `Qt.UserRole`，不再从显示字符串里反解 —— 原来的 `resolve_entry()`
按 `" · "` 切分页面名反查，两条同名项（"准心大小" 在准心设置和预设中心都有）
根本分不开。
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

# 一行结果携带的数据
ROLE_PAGE_ID = Qt.UserRole + 1
ROLE_SUBTITLE = Qt.UserRole + 2
ROLE_KIND = Qt.UserRole + 3      # item / page / recent / suggest
ROLE_TAB = Qt.UserRole + 4       # 项所在页签（跳转时要先切过去）
ROLE_HIT = Qt.UserRole + 5       # 命中的词
ROLE_QUERY = Qt.UserRole + 6     # recent 行：点它是"再搜一次"，不是跳页

ROW_HEIGHT = 46
_PAD_X = 12

KIND_TAG = {
    "item": "设置项",
    "page": "页面",
    "recent": "最近",
    "suggest": "常去",
}


def _make_item(row: dict) -> QStandardItem:
    item = QStandardItem(str(row.get("text", "")))
    item.setEditable(False)
    item.setData(str(row.get("page_id", "")), ROLE_PAGE_ID)
    item.setData(str(row.get("subtitle", "")), ROLE_SUBTITLE)
    item.setData(str(row.get("kind", "page")), ROLE_KIND)
    item.setData(str(row.get("tab", "")), ROLE_TAB)
    item.setData(str(row.get("hit", "")), ROLE_HIT)
    item.setData(str(row.get("query", "")), ROLE_QUERY)
    return item


def build_model(rows: List[dict], parent=None) -> QStandardItemModel:
    """建一个 popup 用的 model。只在创建搜索框时调一次。"""
    model = QStandardItemModel(parent)
    fill_model(model, rows)
    return model


def fill_model(model: QStandardItemModel, rows: List[dict]) -> None:
    """就地换掉 model 的内容。

    ⚠ **每次按键都必须走这条路，不能 `completer.setModel(新 model)`。**
    实测（tests/test_search_jump_r13）：`QCompleter.setModel()` 之后旧 model 的
    C++ 对象已被销毁，调用方再碰它一下就是
    `RuntimeError: Internal C++ object already deleted` —— 用户敲第二个字就炸。
    就算不碰，每次按键新建一个 model 挂在 completer 名下也是纯泄漏。
    """
    model.removeRows(0, model.rowCount())
    for row in rows:
        model.appendRow(_make_item(row))


def subtitle_for(row: dict) -> str:
    """结果的第二行：告诉用户"这一条在哪儿"。"""
    kind = row.get("kind")
    if kind == "item":
        parts = [row.get("page_name", "")]
        if row.get("tab"):
            parts.append(row["tab"])
        card = row.get("card") or ""
        # 卡片标题**本身**也是一条结果（R14/S9），此时 card == text，
        # 再拼一遍就成了「准心快速回正 / 局内视角 · 准心快速回正」——
        # 第二行是用来说"这一条在哪儿"的，把标题重复一遍等于没说。
        if card and card != row.get("text"):
            parts.append(card)
        return " · ".join(p for p in parts if p)
    if kind == "page":
        # 页面结果的第二行说清"为什么搜到它"——命中的是哪个词。
        # 不写的话，搜"太吵了"跳出"基础设置"会显得莫名其妙。
        hit = row.get("hit", "")
        return f"匹配「{hit}」" if hit and hit != row.get("text") else "整页"
    return row.get("subtitle", "")


class SearchResultDelegate(QStyledItemDelegate):
    """两行式结果行：主标题 + 次行位置，右侧一个类型小标签。

    刻意不加任何发光/玻璃/动效（红线），只用文字层级和颜色深浅区分。
    颜色一律取自 `option.palette`，所以 9 套主题自动跟随，不与 theme_manager 耦合。
    """

    def sizeHint(self, option, index):  # noqa: N802 (Qt 命名)
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter, option, index):  # noqa: N802
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)

        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
            main_color = option.palette.highlightedText().color()
            sub_color = QColor(main_color)
            sub_color.setAlpha(185)
        else:
            # 自己填底色，不指望 QListView 的 QSS 背景 —— 那条路会和 palette 打架
            # （见 gui_widget._apply_search_popup_theme 里那段实测）。
            painter.fillRect(option.rect, option.palette.base())
            main_color = option.palette.text().color()
            sub_color = QColor(main_color)
            sub_color.setAlpha(140)

        rect = option.rect.adjusted(_PAD_X, 0, -_PAD_X, 0)

        # 右侧类型标签先占位，主标题的可用宽度要把它扣掉，否则长项名会盖上去
        kind = index.data(ROLE_KIND) or "page"
        tag = KIND_TAG.get(kind, "")
        tag_font = QFont(option.font)
        tag_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.5))
        tag_w = 0
        if tag:
            painter.setFont(tag_font)
            tag_w = painter.fontMetrics().horizontalAdvance(tag) + 10

        text_w = max(20, rect.width() - tag_w)

        title_font = QFont(option.font)
        painter.setFont(title_font)
        fm = painter.fontMetrics()
        title = fm.elidedText(str(index.data(Qt.DisplayRole) or ""),
                              Qt.ElideRight, text_w)
        painter.setPen(main_color)
        painter.drawText(rect.left(), rect.top() + 6, text_w, fm.height(),
                         Qt.AlignLeft | Qt.AlignVCenter, title)

        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.0))
        painter.setFont(sub_font)
        sfm = painter.fontMetrics()
        sub = sfm.elidedText(str(index.data(ROLE_SUBTITLE) or ""),
                             Qt.ElideRight, text_w)
        painter.setPen(sub_color)
        painter.drawText(rect.left(), rect.top() + 6 + fm.height() - 2, text_w,
                         sfm.height(), Qt.AlignLeft | Qt.AlignVCenter, sub)

        if tag:
            painter.setFont(tag_font)
            painter.setPen(sub_color)
            painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, tag)

        painter.restore()
