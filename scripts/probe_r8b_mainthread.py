# -*- coding: utf-8 -*-
"""R8b 前置度量之二：24FPS 主线程重绘会不会卡住界面。

**为什么必须单独量这个**：`probe_r8b_crosshair.py` 量的是「画一帧几微秒」，
那只是 QPainter 在内存位图上的光栅化。产品里真正跑的是
`QTimer → update() → 事件循环 → paintEvent → 后备存储`整条链，
而这条链**占用的是主线程**——也就是用户点按钮、拖滑块的同一个线程。

UP-079 就是这么栽的：R8a 把 pygame 挪出启动路径后，成本没消失，
落到了主线程的准心定时器上，实测一次 **426.8ms 冻结**。
所以「一帧才 0.0065ms」不能直接推出「主线程扛得住」——
得用 UP-079 同款的心跳探针，量事件循环**实际被拖延**了多少。

**不打扰前台**：窗口设 `Qt.WA_DontShowOnScreen`。控件照常收到 paintEvent、
照常走后备存储，但永远不映射到屏幕上（排版审计 UP-068 用的同一招）。

隔离：配置/日志指向临时目录。
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time

_ISOLATED = tempfile.mkdtemp(prefix="cs2customizer_probe_r8b2_")
os.environ["CS2C_CONFIG_DIR"] = os.path.join(_ISOLATED, "config")
os.environ["CS2C_LOG_DIR"] = os.path.join(_ISOLATED, "logs")
os.environ["CS2C_SAFE_MODE_ACTIVE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

HEARTBEAT_MS = 10
RUN_SECONDS = 6.0


class FakeCrosshair(QWidget):
    """按 R8b 设想的方式画准心：QTimer 驱动、主线程 paintEvent、100x100。

    刻意取**最贵**的组合当样本：自定义像素准心 + 抗锯齿 + 霓虹扩散三层环，
    量出来的是上界，不是典型值。
    """

    def __init__(self, fps):
        super().__init__(None)
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(100, 100)
        self.phase = 0
        self.frames = 0
        self.paint_ms = []
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / fps))
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self.phase += 1
        self.update()
        self.repaint()  # 强制同帧完成，别让统计漏掉真实成本

    def paintEvent(self, event):
        t0 = time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QPointF(50, 50)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 255, 0, 255))
        for k in range(120):
            x = (k * 7) % 30
            y = (k * 11) % 30
            p.drawRect(int(c.x() + (x - 15) * 1.3), int(c.y() + (y - 15) * 1.3), 2, 2)
        p.setBrush(Qt.NoBrush)
        for i in range(3):
            wave = ((self.phase * 0.02) + i * 0.2) % 1.0
            pen = QPen(QColor(255, 80, 0, max(1, int(255 * (1 - wave)))))
            pen.setWidth(max(1, int(2 * (1 - wave))))
            p.setPen(pen)
            p.drawEllipse(c, wave * 40, wave * 40)
        p.end()
        self.frames += 1
        self.paint_ms.append((time.perf_counter() - t0) * 1000.0)


class Heartbeat:
    """10ms 心跳：定时器实际到点时间与预期的差 = 事件循环被拖延的量。"""

    def __init__(self):
        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(HEARTBEAT_MS)
        self.timer.timeout.connect(self._beat)
        self.last = None
        self.lags = []

    def start(self):
        self.last = time.perf_counter()
        self.timer.start()

    def _beat(self):
        now = time.perf_counter()
        gap = (now - self.last) * 1000.0
        self.last = now
        self.lags.append(max(0.0, gap - HEARTBEAT_MS))


def measure(fps, with_crosshair):
    app = QApplication.instance() or QApplication(sys.argv)
    hb = Heartbeat()
    ch = None
    if with_crosshair:
        ch = FakeCrosshair(fps)
        ch.show()
        ch.timer.start()
    hb.start()

    end = time.perf_counter() + RUN_SECONDS
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.001)

    hb.timer.stop()
    if ch:
        ch.timer.stop()
        ch.close()

    lags = sorted(hb.lags)
    out = {
        "beats": len(lags),
        "lag_median": statistics.median(lags) if lags else 0.0,
        "lag_p95": lags[int(len(lags) * 0.95)] if lags else 0.0,
        "lag_max": max(lags) if lags else 0.0,
    }
    if ch:
        pm = sorted(ch.paint_ms)
        out["frames"] = ch.frames
        out["paint_median"] = statistics.median(pm) if pm else 0.0
        out["paint_max"] = max(pm) if pm else 0.0
    return out


def main():
    print(f"隔离目录: {_ISOLATED}")
    print(f"心跳 {HEARTBEAT_MS}ms，每组跑 {RUN_SECONDS}s，样本取最贵的准心组合（自定义像素+抗锯齿+三层环）\n")

    rows = []
    rows.append(("基线（无准心）", measure(0, False)))
    for fps in (24, 60):
        rows.append((f"主线程准心 {fps}FPS", measure(fps, True)))

    print(f"{'场景':<22}{'心跳数':>8}{'滞后中位':>11}{'p95':>9}{'最大':>9}{'帧数':>7}{'画帧中位':>11}{'画帧最大':>10}")
    print("-" * 88)
    for name, r in rows:
        frames = r.get("frames", "—")
        pmed = f"{r['paint_median']:.3f}ms" if "paint_median" in r else "—"
        pmax = f"{r['paint_max']:.3f}ms" if "paint_max" in r else "—"
        print(f"{name:<22}{r['beats']:>8}{r['lag_median']:>10.3f}ms{r['lag_p95']:>8.3f}"
              f"{r['lag_max']:>8.3f}{str(frames):>7}{pmed:>11}{pmax:>10}")

    base = rows[0][1]
    for name, r in rows[1:]:
        print(f"\n{name} 相对基线：滞后中位 {r['lag_median'] - base['lag_median']:+.3f}ms，"
              f"最大 {r['lag_max'] - base['lag_max']:+.3f}ms")
    print("\n判读口径：UP-079 那次实测的单次冻结是 426.8ms。上面的『最大』一列若仍是个位数毫秒，"
          "说明主线程绘制不构成可感知卡顿。")


if __name__ == "__main__":
    main()
