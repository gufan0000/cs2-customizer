# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-066/076：单选钮的指示器在**每个状态**下都必须是圆，判据读像素。

**这条判据存在的唯一理由是我上一轮判错了。**
外审报「选中项是方块、未选中是圆圈」，我拿 QSS 驳它 ——
「`:checked` 里没有动 `border-radius`，所以形状不会变」—— 然后判了假报。
下一轮它 3/3 全票又报，我抓像素一看：**它是对的**。
错法和 V-003 一样：**拿代码去驳一个关于屏幕的断言**。

真正的机制（离屏抓像素量出来的，不是读 QSS 推的）：
Qt QSS 里 `width/height` 给的是**内容框**，边框加在外面。
选中态内容 18 + 边框 5×2 = **28px 外框**，而两个状态都只写了
`border-radius: radio_size // 2` = 9px。于是
  · 外缘 radius 9 < 14 → 圆角矩形；
  · 内缘 radius = 9 − 5 = **4**，铺在 18px 的白底上 → **白色实心方块**。
未选中态外框只有 22px（radius 9 ≈ 11），加上背景透明看不到内缘，所以它一直是圆的
—— 于是同一排里「未选中圆、选中方」，肉眼一眼就能看出不齐。

⚠ 所以这条判据**不许写成「QSS 里有没有 border-radius」**。
那种写法上一版就在（而且是绿的），它正是我判错的那个推理。只准量形状。
"""
from __future__ import annotations

#: 圆的面积 / 外接矩形面积 = π/4 ≈ 0.785；正方形是 1.0。
#: 阈值取 0.90：抗锯齿和 1px 误差都够，而方块（1.0）过不去。
ROUND_MAX_FILL_RATIO = 0.90


def _indicator_shapes(qapp):
    """渲染一对单选钮，回报每个状态下**最大的非背景色块**的填充率。"""
    from PySide6.QtWidgets import QRadioButton, QVBoxLayout, QWidget

    import theme_manager as tm

    qapp.setStyleSheet(tm.get_stylesheet())
    host = QWidget()
    layout = QVBoxLayout(host)
    unchecked, checked = QRadioButton("未选中"), QRadioButton("选中")
    checked.setChecked(True)
    layout.addWidget(unchecked)
    layout.addWidget(checked)
    host.resize(240, 90)
    host.show()
    qapp.processEvents()
    image = host.grab().toImage()

    out = {}
    for name, widget in (("unchecked", unchecked), ("checked", checked)):
        rect = widget.geometry()
        band = min(34, rect.width())
        counts: dict[tuple[int, int, int], list[int]] = {}
        for y in range(rect.y(), rect.y() + rect.height()):
            for x in range(rect.x(), rect.x() + band):
                color = image.pixelColor(x, y)
                key = (color.red(), color.green(), color.blue())
                box = counts.setdefault(key, [0, x, y, x, y])
                box[0] += 1
                box[1] = min(box[1], x)
                box[2] = min(box[2], y)
                box[3] = max(box[3], x)
                box[4] = max(box[4], y)
        # 背景 = 出现最多的颜色；指示器 = 剩下最大的那一块
        ranked = sorted(counts.items(), key=lambda kv: -kv[1][0])
        shapes = []
        for key, (n, x0, y0, x1, y1) in ranked[1:]:
            w, h = x1 - x0 + 1, y1 - y0 + 1
            # 只看真正成块的：够大、够方正（指示器是等宽高的）
            if n >= 120 and 6 <= w <= 34 and abs(w - h) <= 2:
                shapes.append((key, n / (w * h), w, h))
        out[name] = shapes
    return out


def test_radio_indicator_is_round_in_every_state(qapp):
    shapes = _indicator_shapes(qapp)
    assert shapes["checked"], (
        "选中态一个色块都没量到 —— 判据在空转，先修抓图那一段，别让它假绿。")

    bad = []
    for state, found in shapes.items():
        for rgb, ratio, w, h in found:
            if ratio > ROUND_MAX_FILL_RATIO:
                bad.append(f"{state} 的 {rgb} 块 {w}x{h} 填充率 {ratio:.2f}")
    assert not bad, (
        "单选钮指示器里有**方形**色块（RN-066/076）：\n  " + "\n  ".join(bad)
        + f"\n填充率 >{ROUND_MAX_FILL_RATIO} 就是方的（圆是 π/4≈0.79）。\n"
        "`border-radius` 要按**外框**算：Qt QSS 的 width/height 是内容框，"
        "边框加在外面，内缘 radius = 外缘 radius − 边框宽。")


# ⚠ 这里原来还有一条 `test_this_judge_would_have_caught_the_old_qss` ——
# 想用「往 stylesheet 后面追加一段旧写法」来自证咬人。**那个复现不忠实**：
# 追加规则走的层叠路径和真实 QSS 不同，实测白块量出 16x16 / 填充率 0.84，
# 而真实旧代码是 18x20 / 0.99。判据自己的复现不准，比没有复现更坏。
# 咬人证明改走仓里现成的机制：`scripts/revert_verify.py` 的 RN-076 断点
# —— 它改的是 `theme_manager.py` 真身那一行，红/绿都是真的。
