# -*- coding: utf-8 -*-
"""生成 GitHub 社交预览图（Open Graph 卡片）。

产物: docs/images/social-preview.png，1280×640。
用法: python scripts/make_social_preview.py

GitHub 的 social preview 是**仓库设置里手工上传**的，不能由仓库文件自动生效：
    Settings → General → Social preview → Upload an image
没设的话，别人在 Twitter / Discord / 微信里贴仓库链接，卡片上只有一个默认的
灰底 GitHub 图标 + 仓库名——等于放弃了这块最大的免费曝光位。

视觉沿用 `build_tools/make_installer_assets.py` 的语言（深色底 + 紫 accent #7c5cff），
与应用深色主题、安装向导品牌图保持一致。

⚠️ 与 make_installer_assets 同一条纪律：**没有中文字体就响亮失败，不静默降级**。
PIL 内置位图字体没有 CJK 字形，降级的结果是一排豆腐块，而且脚本会正常退出——
等你在社交平台上看见乱码卡片时已经晚了。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "docs" / "images" / "social-preview.png"

W, H = 1280, 640

ACCENT = (124, 92, 255)
ACCENT_SOFT = (160, 136, 255)
TOP = (18, 18, 26)
BOTTOM = (36, 28, 56)
TEXT = (242, 242, 250)
SUBTEXT = (162, 156, 186)
CHIP_BG = (44, 40, 66)

WINDOWS_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
BOLD_CANDIDATES = (
    WINDOWS_FONT_DIR / "msyhbd.ttc",
    WINDOWS_FONT_DIR / "msjhbd.ttc",
    WINDOWS_FONT_DIR / "simhei.ttf",
)
REGULAR_CANDIDATES = (
    WINDOWS_FONT_DIR / "msyh.ttc",
    WINDOWS_FONT_DIR / "msjh.ttc",
    WINDOWS_FONT_DIR / "simhei.ttf",
)

ALLOW_FONT_FALLBACK = os.environ.get("ASSETS_ALLOW_FONT_FALLBACK") == "1"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    attempted = []
    for candidate in (BOLD_CANDIDATES if bold else REGULAR_CANDIDATES):
        attempted.append(str(candidate))
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    if not ALLOW_FONT_FALLBACK:
        raise RuntimeError(
            f"未找到可用的 CJK 中文字体（已尝试: {attempted}）。"
            "社交预览图上印着中文，用 PIL 内置字体会渲染成豆腐块且不报错。"
            "确认无所谓时用 ASSETS_ALLOW_FONT_FALLBACK=1 显式降级。"
        )
    print("!! 警告：无 CJK 字体，中文将渲染为豆腐块", file=sys.stderr)
    return ImageFont.load_default()


def _vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    w, h = size
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return grad.resize((w, h), Image.BILINEAR)


def _chip(draw: ImageDraw.ImageDraw, xy, text, font) -> int:
    """画一个圆角标签，返回它的宽度（供水平排布用）。"""
    x, y = xy
    pad_x, pad_y = 18, 10
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    w = right - left + pad_x * 2
    h = bottom - top + pad_y * 2
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=CHIP_BG)
    draw.text((x + pad_x - left, y + pad_y - top), text, font=font, fill=SUBTEXT)
    return w


def main() -> int:
    img = _vertical_gradient((W, H), TOP, BOTTOM)
    d = ImageDraw.Draw(img)

    # 左侧一条 accent 竖带，和安装向导大图同一个视觉母题
    d.rectangle((0, 0, 10, H), fill=ACCENT)

    # 右下角一个大号淡紫准心轮廓：一眼说明这是 CS 相关工具，且不使用任何游戏素材
    cx, cy, arm, gap, th = 1055, 455, 96, 26, 9
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x0 = cx + dx * gap
        y0 = cy + dy * gap
        x1 = cx + dx * (gap + arm)
        y1 = cy + dy * (gap + arm)
        d.line((x0, y0, x1, y1), fill=(70, 56, 112), width=th)
    d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=(70, 56, 112))

    d.text((72, 112), "CS2 Customizer", font=_font(84, bold=True), fill=TEXT)
    d.text((76, 214), "给 CS2 玩家的本地个性化工具", font=_font(38), fill=ACCENT_SOFT)

    lines = [
        "准心 · 击杀音效与图标 · HUD 配色 · 局内视角 · 道具瞄点",
        "只走 Valve 官方 GSI 接口与 cfg 文件，不碰游戏进程",
    ]
    y = 296
    for line in lines:
        d.text((76, y), line, font=_font(29), fill=SUBTEXT)
        y += 46

    chips = ["GPL-3.0", "Python 3.13", "PySide6", "Windows", "1393 tests"]
    x = 76
    chip_font = _font(24)
    for text in chips:
        x += _chip(d, (x, 430), text, chip_font) + 12

    d.text((76, 536), "github.com/gufan0000/cs2-customizer",
           font=_font(27, bold=True), fill=(126, 118, 158))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"已生成 {OUT}  ({OUT.stat().st_size // 1024} KB, {W}×{H})")
    print("下一步（只能手工做）: 仓库 Settings → General → Social preview → 上传这张图")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
