# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 155：闪光预览左上角那行说明，在最亮的白闪 100% 上也读得清。

原来是半透明白字直接画在闪光叠层上：用户默认就是白色 75%，那一行字白底白字（外审 S4 列为最明显的对比不足）。
量的是渲染出来的像素，不是常量：垫底那一笔删掉，像素就回到白闪的颜色。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.parametrize("color", ["白色", "黄色", "黑色"])
def test_the_caption_reads_on_any_flash(qapp, color):
    from PySide6.QtGui import QColor, QImage

    from core.utils.contrast import contrast_ratio
    from widgets.flash_preview_widget import CAPTION_TEXT, FlashPreviewWidget

    widget = FlashPreviewWidget()
    widget.resize(600, 240)
    widget.update_settings(bg_color=color, opacity_pct=100)
    image = QImage(widget.size(), QImage.Format_RGB32)
    widget.render(image)
    # 说明那块底的左边沿内侧：底从 (10, 10) 起，左右各留 8px，这一点上没有字
    under = QColor(image.pixel(13, 16)).name()
    ratio = contrast_ratio(CAPTION_TEXT.name(), under)
    assert ratio >= 4.5, f"{color} 100% 上说明字对比度 {ratio:.2f}（底 {under}）"
    assert "实时预览" not in widget.caption(), "卡片标题已经写了「实时预览」，框里不再念一遍"
