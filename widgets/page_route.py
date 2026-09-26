# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-528：**指路本身没错，错在目标不在这一屏上** —— 让那个页名自己可点。

形状照抄 `community_library.stale_style_route` / `wire_stale_route` 那一对
（RN-197 验过）：文案里嵌一条**零高度**的链接，接线全仓只有一份。
叙事、分母（11 处）与逐处分类见 `CS2 Customizer_翻新工程/档案/X_指路指向看不见的地方.md`
与 `tests/test_a_named_page_is_reachable_from_where_it_is_named.py`。
"""
from __future__ import annotations

from core.utils.logger import get_logger

_logger = get_logger()

#: 链接的 href 前缀。真正的 page_id 跟在后面。
#: ⛔ 页面**不许自己拼跳转逻辑** —— 同 `STALE_ROUTE_HREF` 的理由：
#:    一个写死在页面里的目标，改导航时没有任何东西会发现它没跟着改。
PAGE_ROUTE_HREF = "cs2customizer:page/"


def goto_page(widget, page_id: str) -> bool:
    """把窗口切到某一页。**全仓只有这一份实现。**

    ⚠ `force=True` 是要害：不带它，普通模式下没有导航入口的页会**静默 return**
    —— 点了什么都不会发生。**原来那两份副本都漏了它。**
    """
    window = widget.window() if hasattr(widget, "window") else None
    if window is None:
        return False
    try:
        ensure = getattr(window, "ensure_page_loaded", None)
        if callable(ensure):
            ensure(page_id)
        show = getattr(window, "show_page", None)
        if not callable(show):
            _logger.warning(f"跳转失败：窗口上没有 show_page（目标 {page_id!r}）")
            return False
        show(page_id, animated=False, force=True)
        return True
    except Exception as exc:                      # noqa: BLE001
        # 跳转失败不许把调用方拖垮：它多半是在刷新状态条的路上。
        _logger.warning(f"跳转到 {page_id!r} 失败：{exc}")
        return False


IMPORTER_PAGE_ID = "audio_import_wizard"


def hand_to_importer(widget, paths) -> bool:
    """把拖到某一页上的包转交给「导入资源」（批 123）。

    RN-193 早就说透：「三步被劈在两个区域里，换个说法治不好」——
    「去社区拿 → 打开资源目录放进去 → 刷新」中间那两步**砍掉**，
    下好的包拖到哪一页都行，由统一导入去问、去装、能撤销。
    ⛔ 不在各页里另写一套解压 / 认类别 —— 那是第二份导入器。
    """
    window = widget.window() if hasattr(widget, "window") else None
    pages = getattr(window, "pages", None) or {}
    # 先认出「用户是在哪一页松的手」—— 跳过去之后要告诉他为什么到了导入页
    from_id = next((pid for pid, page in pages.items() if page is widget), "")
    if not paths or not goto_page(widget, IMPORTER_PAGE_ID):
        return False
    importer = (getattr(window, "pages", None) or {}).get(IMPORTER_PAGE_ID)
    accept = getattr(importer, "accept_sources", None)
    if not callable(accept):
        _logger.warning("转交导入失败：导入资源页没建出来或没有 accept_sources")
        return False
    return bool(accept(list(paths), handed_from=(page_label(widget, from_id) if from_id else "") or "这一页"))


def _page_names_of(widget) -> dict:
    """那份**唯一**的 page_id → 显示名表（主窗的 `_page_names`）。

    ⚠ 只问 `widget.window()` 不够：页面在 `_create_pages()` 里建，**那一刻还没挂进
    窗口**，而状态条文案正是那一刻算的 ⇒ 兜底去 `topLevelWidgets()` 找（RN-584，
    仍是同一份表，不是第二份清单）。
    """
    window = widget.window() if hasattr(widget, "window") else None
    names = getattr(window, "_page_names", None)
    if names:
        return names
    try:
        from PySide6.QtWidgets import QApplication

        for top in QApplication.topLevelWidgets():
            names = getattr(top, "_page_names", None)
            if names:
                return names
    except Exception:                             # noqa: BLE001
        pass
    return {}


def page_label(widget, page_id: str) -> str:
    """这一页在导航里的显示名。**真源是主窗的 `_page_names`**，别在页面里抄第二份。

    ⛔⛔ **取不到不许退回 `page_id`** —— 那是内部英文名，退回去就是把它印到屏幕上
    （RN-584：批 74 真这么干过，外审 3/3 报「链接文案是英文 advanced」）。
    ⇒ 返回空串，怎么退由 `page_route()` 决定。
    """
    return str(_page_names_of(widget).get(page_id) or "")


def page_route(page_id: str, label: str) -> str:
    """那段可点的页名。**零高度** —— 嵌进原句里的一个词，不是一颗按钮。

    ⛔ 零高度是硬约束：紧凑档加一行控件会把状态卡压掉（RN-185）。
    ⛔ **`label` 空了就不给链接**，退成一句读得通的中文 ——
    ⭐ 宁可少一条链接，也不许屏幕上出现内部英文名（RN-584）。
    """
    if not label or label == page_id:
        _logger.warning(f"页名取不到（{page_id!r}），退成不带链接的说法")
        return "设置"
    # ⛔⛔ RN-590：颜色必须实算，不许发裸 `<a>`（那是纯蓝，9 主题 5 个不达 AA）。
    #   ⚠ `route_link_color()` 是全仓唯一一份这个计算，借它、不抄第二份。数与叙事见判据。
    from widgets.community_library import route_link_color

    return (f'<a href="{PAGE_ROUTE_HREF}{page_id}" '
            f'style="color:{route_link_color()};">{label}</a>')


def wire_page_routes(label_widget) -> None:
    """把一个标签上所有 `cs2customizer:page/<id>` 链接接上跳转。**全仓只有这一份接线。**

    ⚠ 不开 `openExternalLinks`：`cs2customizer:page/...` 不是真 URL，交给系统浏览器
    会弹一个「找不到应用」的框（同 `wire_stale_route` 的理由）。
    """
    from PySide6.QtCore import Qt

    label_widget.setTextFormat(Qt.RichText)
    label_widget.setOpenExternalLinks(False)

    def _on(href: str) -> None:
        if href.startswith(PAGE_ROUTE_HREF):
            goto_page(label_widget, href[len(PAGE_ROUTE_HREF):])

    label_widget.linkActivated.connect(_on)
