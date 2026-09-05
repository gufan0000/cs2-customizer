# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R9-C（UP-047 / UP-092）：页头统一走 `PageHeader`，且别再写死字号。

**为什么值得盯**：这类样板不会报错，只会悄悄长回来——写新页的人照着隔壁页
复制一段就行，没有任何东西会拦他。R9-C 之前正是这样：26 个页面各抄一份，
抄出了 **4 种不同的标题字号**（20/22/24/不设），而且没有一个生效。

`title_font_size` 那件事的实测结论（见 UP-092）：`QLabel#titleLabel` 的 QSS 里有
`font-size: {h1}px`，Qt 的样式表字号会盖过 `setFont`。指纹实测——把全部 26 页的
内联字号删掉，**逐控件位置与尺寸零变化**。也就是说那三种字号从来没生效过，
它们唯一的作用是让每个读代码的人误以为这些页面长得不一样。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
PAGES = REPO / "pages"


def _page_sources() -> dict[str, str]:
    return {
        p.name: p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(PAGES.glob("*.py"))
        if not p.name.startswith("__")
    }


def test_no_page_hand_rolls_a_title_label():
    """任何页面都不许再手搓 `setObjectName("titleLabel")`。

    回退验证：把任意一页改回手搓页头，本条立刻变红。
    """
    offenders = [
        name for name, src in _page_sources().items()
        if 'setObjectName("titleLabel")' in src or "setObjectName('titleLabel')" in src
    ]
    assert not offenders, (
        "这些页面又手搓了页头，请改用 widgets.page_header.PageHeader：\n  "
        + "\n  ".join(offenders)
    )


def test_no_page_hand_rolls_a_page_lead_label():
    """副标题同理——它和标题是一体的，分开写就会又长出两套。"""
    offenders = [
        name for name, src in _page_sources().items()
        if 'setObjectName("pageLeadLabel")' in src
    ]
    assert not offenders, (
        "这些页面又手搓了副标题：\n  " + "\n  ".join(offenders)
    )


def test_page_header_is_actually_adopted_widely():
    """自检：上面两条是"没有坏东西"，这条确认"好东西真的在"。

    只写反向判据的话，把 26 个页头全删了也能全绿。
    """
    # R9-D 之后有两条路径：页面自己建，或继承 SoundPageBase 由基类建。
    users = [
        name for name, src in _page_sources().items()
        if "PageHeader(" in src or "SoundPageBase" in src
    ]
    assert len(users) >= 24, f"只有 {len(users)} 个页面用了 PageHeader，迁移多半被回退了"


def test_no_page_pins_a_title_font_size():
    """页面不许再传 `title_font_size=<数字>`——那个参数在本项目里没有效果。

    QSS 的 `QLabel#titleLabel { font-size: h1 }` 会盖过 `setFont`。
    留着只会误导：让人以为"这一页标题比别页小"，而实际渲染完全一样。
    组件本身仍保留这个参数（别的项目/别的 objectName 可能真要用），
    但**本仓库的页面**一律传 None。
    """
    bad = []
    for name, src in _page_sources().items():
        for m in re.finditer(r"title_font_size\s*=\s*(\w+)", src):
            if m.group(1) != "None":
                bad.append(f"{name}: title_font_size={m.group(1)}")
    assert not bad, (
        "这些页面写死了标题字号，但它不会生效（UP-092）：\n  " + "\n  ".join(bad)
    )


def test_pages_do_not_import_qfont_just_for_the_dead_title_size():
    """连带判据：迁移后 16 个页面的 `QFont` 导入变成了未使用。

    这条不是查风格，是查**证据**——如果哪天有人又 import 回 QFont 并且不用它，
    多半是又把那段样板抄回来了。
    """
    bad = []
    for name, src in must_scan(_page_sources().items(), "pages/ 的源码", least=20):
        if "QFont" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        imported = any(
            isinstance(node, ast.ImportFrom)
            and any(a.name == "QFont" for a in node.names)
            for node in ast.walk(tree)
        )
        if not imported:
            continue
        used = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "QFont"
        )
        if used == 0:
            bad.append(name)
    assert not bad, f"这些页面 import 了 QFont 却没用：{bad}"


def test_page_header_can_express_every_shape_the_pages_needed():
    """组件得撑得住 26 个页面的全部形态，否则迁移就会变成"改外观"。

    R9-C 实测补出来的三个能力，每一个都对应一次真实的像素偏差：
      - `title_font_size=None`   不设 QFont（准心页等原本就没设）
      - `spacing`                标题与副标题的距离（多数页面原本是 12，不是默认的 4）
      - `title_spacing=None`     标题行沿用 Qt 默认间距（写死 10 会让准心页的 "?" 挪 2px）
      - `body`                   帮助面板要插在标题与副标题**之间**，
                                 传页面主布局会让它跑到副标题下面、副标题上移 12px
    """
    import inspect

    from widgets.page_header import PageHeader

    sig = inspect.signature(PageHeader.__init__)
    for param in ("title_font_size", "spacing", "title_spacing"):
        assert param in sig.parameters, f"PageHeader 缺少 {param} 参数"

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    header = PageHeader("标题", description="副标题", title_font_size=None,
                        spacing=12, title_spacing=None)
    assert header.description_label is not None
    assert header.description_label.objectName() == "pageLeadLabel"
    assert header.title_label.objectName() == "titleLabel"
    assert header.body is not None, "帮助面板要靠 body 才能插回标题与副标题之间"
