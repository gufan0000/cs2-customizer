# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R8b 前置度量：准心一帧到底要花多少钱（QPainter vs pygame.draw）。

**为什么要量**：R8b 的计划书写着「pygame+threading → Qt 透明置顶窗 + QPainter」，
但没有任何一个数字支撑「QPainter 扛得住」。而这次迁移的落点是**主线程**
（QWidget 只能在主线程画），一帧的成本直接换算成用户在设置界面里的卡顿。
所以动手前必须知道：一帧几毫秒、24FPS 占主线程多少百分比。

**为什么可以离屏量**：这里比的是**光栅化成本**，两边都画进内存位图
（QImage / pygame.Surface），谁都不创建窗口、不碰前台、不抢视频资源。
呈现（flip / DWM 合成）不在比较范围内——那部分 Qt 走 DWM 分层窗，
pygame 走 SDL+LWA_COLORKEY，成本形态不同，硬凑一个数字没有意义。

隔离：配置/日志都指向临时目录，绝不碰用户真实文件（UP-065/UP-083 的教训）。
"""
from __future__ import annotations

import os
import statistics
import sys
import time

# RN-032：配置目录走共享工装。原写法 mkdtemp 出来的目录连 config 子目录都没建，
# 产品侧只能靠"迁移失败被 except 吞掉"侥幸拿到默认值 —— 不是隔离，是碰巧。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pristine_config import use_pristine_config_dir  # noqa: E402

_ISOLATED = use_pristine_config_dir("cs2customizer_probe_r8b")
os.environ["CS2C_SAFE_MODE_ACTIVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SIZE = 100          # 与产品一致：window_size = 100
CROSSHAIR = 20      # 默认 crosshair_size
THICK = 2           # 默认 crosshair_thickness
ROUNDS = 400


def _median_ms(fn, rounds=ROUNDS):
    # 先热身，别把首帧的一次性开销（画笔/表面分配）算进中位数
    for _ in range(30):
        fn(0)
    samples = []
    for i in range(rounds):
        t0 = time.perf_counter()
        fn(i)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "median": statistics.median(samples),
        "p95": samples[int(len(samples) * 0.95)],
        "max": samples[-1],
    }


def bench_qt():
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841

    img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    results = {}

    def _frame(painter, phase, style, antialias):
        painter.setRenderHint(QPainter.Antialiasing, antialias)
        pen = QPen(QColor(0, 255, 0, 255))
        pen.setWidth(THICK)
        painter.setPen(pen)
        c = QPointF(SIZE / 2, SIZE / 2)
        half = CROSSHAIR / 2
        if style == "crosshair":
            painter.drawLine(QPointF(c.x(), c.y() - half), QPointF(c.x(), c.y() + half))
            painter.drawLine(QPointF(c.x() - half, c.y()), QPointF(c.x() + half, c.y()))
        elif style == "circle":
            painter.drawEllipse(c, half, half)
        elif style == "dot":
            painter.setBrush(QColor(0, 255, 0, 255))
            painter.drawEllipse(c, max(2, CROSSHAIR // 4), max(2, CROSSHAIR // 4))
        elif style == "custom":
            # 自定义准心 = 一堆像素方块。取 30×30 网格的一半点数作为悲观样本
            painter.setBrush(QColor(0, 255, 0, 255))
            painter.setPen(Qt.NoPen)
            for k in range(120):
                x = (k * 7) % 30
                y = (k * 11) % 30
                painter.drawRect(int(c.x() + (x - 15) * 1.3), int(c.y() + (y - 15) * 1.3), THICK, THICK)
        elif style == "neon_wave":
            # 最贵的击杀联动：3 层扩散圆环 + 主准心
            painter.setBrush(Qt.NoBrush)
            for i in range(3):
                wave = ((phase * 0.02) + i * 0.2) % 1.0
                pen2 = QPen(QColor(255, 80, 0, max(1, int(255 * (1 - wave)))))
                pen2.setWidth(max(1, int(THICK * (1 - wave))))
                painter.setPen(pen2)
                painter.drawEllipse(c, wave * 40, wave * 40)
            painter.setPen(pen)
            painter.drawLine(QPointF(c.x(), c.y() - half), QPointF(c.x(), c.y() + half))
            painter.drawLine(QPointF(c.x() - half, c.y()), QPointF(c.x() + half, c.y()))

    for style in ("crosshair", "circle", "dot", "custom", "neon_wave"):
        for aa in (False, True):
            def run(i, _style=style, _aa=aa):
                img.fill(0)
                p = QPainter(img)
                _frame(p, i, _style, _aa)
                p.end()

            key = f"{style}{'+AA' if aa else ''}"
            results[key] = _median_ms(run)
    return results


def bench_pygame():
    import math

    import pygame

    surf = pygame.Surface((SIZE, SIZE))
    results = {}
    color = (0, 255, 0, 255)
    c = (SIZE // 2, SIZE // 2)
    half = CROSSHAIR // 2

    def _frame(i, style):
        surf.fill((0, 0, 0))
        if style == "crosshair":
            pygame.draw.line(surf, color, (c[0], c[1] - half), (c[0], c[1] + half), THICK)
            pygame.draw.line(surf, color, (c[0] - half, c[1]), (c[0] + half, c[1]), THICK)
        elif style == "circle":
            pygame.draw.circle(surf, color, c, half, THICK)
        elif style == "dot":
            pygame.draw.circle(surf, color, c, max(2, CROSSHAIR // 4))
        elif style == "custom":
            for k in range(120):
                x = (k * 7) % 30
                y = (k * 11) % 30
                pygame.draw.rect(surf, color, (c[0] + (x - 15) * 1.3, c[1] + (y - 15) * 1.3, THICK, THICK))
        elif style == "neon_wave":
            for j in range(3):
                wave = ((i * 0.02) + j * 0.2) % 1.0
                alpha = max(1, int(255 * (1 - wave)))
                pygame.draw.circle(surf, (255, 80, 0, alpha), c, int(wave * 40),
                                   max(1, int(THICK * (1 - wave))))
            pygame.draw.line(surf, color, (c[0], c[1] - half), (c[0], c[1] + half), THICK)
            pygame.draw.line(surf, color, (c[0] - half, c[1]), (c[0] + half, c[1]), THICK)
        return math.pi  # 防优化

    for style in ("crosshair", "circle", "dot", "custom", "neon_wave"):
        results[style] = _median_ms(lambda i, _s=style: _frame(i, _s))
    return results


def main():
    print(f"隔离目录: {_ISOLATED}")
    print(f"画布 {SIZE}x{SIZE}，准心尺寸 {CROSSHAIR}，线宽 {THICK}，每项 {ROUNDS} 帧取中位数\n")

    qt = bench_qt()
    pg = bench_pygame()

    print(f"{'样式':<16}{'QPainter中位':>14}{'p95':>9}{'pygame中位':>14}{'p95':>9}")
    print("-" * 64)
    for style in ("crosshair", "circle", "dot", "custom", "neon_wave"):
        q = qt[style]
        qa = qt[f"{style}+AA"]
        p = pg[style]
        print(f"{style:<16}{q['median']:>13.4f}ms{q['p95']:>8.3f}{p['median']:>13.4f}ms{p['p95']:>8.3f}")
        print(f"{'  └ 开抗锯齿':<16}{qa['median']:>13.4f}ms{qa['p95']:>8.3f}{'—':>14}{'—':>9}")

    worst = max(qt[k]["median"] for k in qt)
    print(f"\nQPainter 最贵一帧（含抗锯齿）: {worst:.4f}ms")
    print(f"24FPS 下占主线程: {worst * 24 / 1000 * 100:.3f}%")
    print(f"60FPS 下占主线程: {worst * 60 / 1000 * 100:.3f}%")


if __name__ == "__main__":
    main()
