# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""生成程序图标（2026-08-12 建立）。

**为什么图标要用代码画出来，而不是放一张图进仓库。**

原来那张图标是一个鹰头，来源是 AI 生成，仓库里没有任何出处记录。公开仓库里这有
两个问题：①纯 AI 生成图在多个法域不受著作权保护，而 NOTICE 却把它当作"保留权利
的标识"来声明——这个主张站不住；②每个 fork 都会继承它，而作者无法证明自己有权
分发它。同一条理由已经让 `splash_art_ai.png` 被排除出本仓库。

画在代码里之后，出处是 100% 清楚的：它就是这个文件。

顺带修掉两件旧毛病：

1. **原 `icon.ico` 是伪装成 .ico 的单帧 64×64 PNG。** 单帧意味着 16×16 的任务栏和
   资源管理器里全靠缩放，发虚；PNG 帧则是 Inno Setup 不接受的格式——所以历史上有
   人手工"重铸"出一份 `installer_assets/setup_icon.ico` 给安装器用
   （`installer.iss` 里那句注释就是这么来的）。**一个手工步骤，没人记得它存在。**
   现在三个路径由本脚本一次出齐，字节相同。
2. **小尺寸不是靠缩放。** 每个尺寸单独画：32px 以下去掉内环、加粗笔画、拉大缺口，
   否则细环在 16px 上会糊成一团灰。

视觉沿用 `make_installer_assets` 的语言（深色底 + 紫 accent + 准星意象），
调色板直接从那边 import，**不许两处各写一份**。

复跑: python build_tools/make_app_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_tools.make_installer_assets import ACCENT, ACCENT_DIM, BOTTOM, TOP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: 三个消费者，内容完全相同：
#:   icon.ico    —— Qt 窗口/任务栏图标、PyInstaller 的 --icon（build_release.py）
#:   myicon.ico  —— main_widget 探测的备用名，历史遗留，仍在候选表里
#:   installer_assets/setup_icon.ico —— Inno 的 SetupIconFile
OUTPUTS = (
    ROOT / "icon.ico",
    ROOT / "myicon.ico",
    ROOT / "build_tools" / "installer_assets" / "setup_icon.ico",
)

#: Windows 会按场景取不同尺寸：16 资源管理器列表 / 32 桌面 / 48 中图标 /
#: 256 大图标与文件属性页。少一档就在那个场景里被缩放。
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: 低于这个尺寸只画"环 + 中心点"。
#:
#: 实测过一版是"环 + 内环 + 四根准星刻线"全画上再缩小：16px 上刻线从 r=2.2px 伸到
#: r=4.8px，**正好顶到环**，三者糊成一个实心疙瘩——放大看根本认不出是准星。
#: 小尺寸不是"同一张图画细一点"，是**换一个更简的构图**。
SIMPLIFY_BELOW = 40

#: 超采样倍数。16px 的图标只有 256 个像素，抗锯齿全靠它。
SUPERSAMPLE = 8


def _rounded_gradient(size: int) -> Image.Image:
    """圆角方底 + 竖向渐变，圆角外透明。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        t = y / max(1, size - 1)
        row = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(size):
            pixels[x, y] = (*row, 255)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=round(size * 0.22), fill=255
    )
    img.paste(gradient, (0, 0), mask)
    return img


def draw_icon(size: int) -> Image.Image:
    """按 `size` 单独绘制一帧（内部按 SUPERSAMPLE 倍放大后缩回）。"""
    big = size * SUPERSAMPLE
    img = _rounded_gradient(big)
    d = ImageDraw.Draw(img)

    simple = size < SIMPLIFY_BELOW
    cx = cy = big / 2

    if simple:
        # 环 + 中心点。笔画按比例加粗，否则缩到 16px 会掉到 1px 以下变成一层灰。
        ring_r = big * 0.31
        d.ellipse(
            [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
            outline=ACCENT, width=round(big * 0.105),
        )
        dot_r = big * 0.075
        d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=ACCENT)
        return img.resize((size, size), Image.Resampling.LANCZOS)

    ring_r = big * 0.30
    stroke = big * 0.070
    gap = big * 0.115
    # 刻线要在环**之内**收住：伸到环上就和环连成一体，准星的缺口感就没了
    tick = ring_r - gap - stroke * 0.9
    dot_r = big * 0.045

    d.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=ACCENT, width=round(stroke),
    )
    inner_r = big * 0.20
    d.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        outline=ACCENT_DIM, width=round(big * 0.042),
    )
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d.line(
            [(cx + dx * gap, cy + dy * gap), (cx + dx * (gap + tick), cy + dy * (gap + tick))],
            fill=ACCENT, width=round(stroke),
        )
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=ACCENT)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def build_ico(path: Path) -> None:
    """写出一个多尺寸 ICO。

    `bitmap_format="bmp"` 是**必需的**：默认写 PNG 帧，而 Inno Setup 不接受
    PNG 帧的 ICO（历史上就是因为这个才有了手工重铸的 setup_icon.ico）。
    `append_images` 让每个尺寸用各自单独画的那一帧，而不是从 256 缩下来。
    """
    frames = {size: draw_icon(size) for size in SIZES}
    base = frames[max(SIZES)]
    base.save(
        path,
        format="ICO",
        bitmap_format="bmp",
        sizes=[(s, s) for s in SIZES],
        append_images=[frames[s] for s in SIZES if s != max(SIZES)],
    )


def main() -> int:
    primary = OUTPUTS[0]
    primary.parent.mkdir(parents=True, exist_ok=True)
    build_ico(primary)
    data = primary.read_bytes()
    for other in OUTPUTS[1:]:
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_bytes(data)
    print(f"图标 {len(data) // 1024} KB, 帧 {SIZES}")
    for p in OUTPUTS:
        print(f"  -> {p.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
