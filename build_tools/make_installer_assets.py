# -*- coding: utf-8 -*-
"""生成 Inno 安装向导品牌图(2.2.0)。

产物(BMP,Inno 要求):
  installer_assets/wizard_large.bmp  328x628  欢迎/完成页左侧大图
  installer_assets/wizard_small.bmp  110x116  其余页右上角小图
视觉:深色底(#16161e→#221b33 渐变)+ 紫 accent(#7c5cff),与应用深色主题同语言。
复跑: python build_tools/make_installer_assets.py
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

OUT = Path(__file__).resolve().parent / "installer_assets"
OUT.mkdir(exist_ok=True)

ACCENT = (124, 92, 255)
ACCENT_DIM = (94, 70, 200)
TOP = (22, 22, 30)
BOTTOM = (34, 27, 51)
TEXT = (240, 240, 248)
SUBTEXT = (158, 152, 180)

WINDOWS_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
CJK_BOLD_FONT_CANDIDATES = (
    WINDOWS_FONT_DIR / "msyhbd.ttc",
    WINDOWS_FONT_DIR / "msjhbd.ttc",
    WINDOWS_FONT_DIR / "simhei.ttf",
)
CJK_REGULAR_FONT_CANDIDATES = (
    WINDOWS_FONT_DIR / "msyh.ttc",
    WINDOWS_FONT_DIR / "msjh.ttc",
    WINDOWS_FONT_DIR / "simhei.ttf",
)

SPLASH_TITLE = "帆派助手"
SPLASH_STATUS = "正在启动…"
SPLASH_SIZE = (600, 360)
TITLE_SAFE_BOX = (80, 250, 520, 310)
STATUS_SAFE_BOX = (160, 306, 440, 350)
# 可选的美术底图。本仓库不分发它（原图是 AI 生成的旧品牌美术，已随开源裁剪删除），
# 缺失时 make_splash() 会退回下面的渐变占位图，而不是让整条打包链断掉。
SPLASH_ART_SOURCE = OUT / "splash_art_ai.png"
SPLASH_TITLE_POSITION = (SPLASH_SIZE[0] // 2, 278)
SPLASH_STATUS_POSITION = (SPLASH_SIZE[0] // 2, 326)

REPLACE_RETRY_DELAYS = (0.02, 0.04, 0.08, 0.12)

# 允许无中文字体时降级为 PIL 内置字体。**默认关闭，必须显式打开。**
#
# 为什么默认要炸而不是降级：这个脚本生成的是**随安装包发布的品牌图**，图上印着中文。
# PIL 内置位图字体没有 CJK 字形，降级的结果是一排方框（豆腐块）——
# 而这个失败是**静默**的：脚本正常退出、图也生成了，你要等装机时才看见乱码标题。
# 构建期响亮失败远好过安静产出坏产物。
# 非中文 Windows / Linux / CI 容器上只想跑通流程的，显式设这个环境变量表态即可。
ALLOW_FONT_FALLBACK = os.environ.get("ASSETS_ALLOW_FONT_FALLBACK") == "1"

_FONT_FALLBACK_WARNED = False


def _font(size: int, bold: bool = False):
    global _FONT_FALLBACK_WARNED

    candidates = CJK_BOLD_FONT_CANDIDATES if bold else CJK_REGULAR_FONT_CANDIDATES
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue

    attempted = ", ".join(str(path) for path in candidates)
    if not ALLOW_FONT_FALLBACK:
        raise RuntimeError(
            f"未找到可用的 CJK 中文字体（已尝试: {attempted}）。"
            "品牌图含中文，缺字体会渲染成方框且不会报错，因此这里直接失败。"
            "请 install 安装 Microsoft YaHei / JhengHei / SimHei 之一后重跑；"
            "仅需占位图时设 ASSETS_ALLOW_FONT_FALLBACK=1 显式降级。"
        )

    if not _FONT_FALLBACK_WARNED:
        print(
            f"[WARN] 未找到可用的中文字体（已尝试: {attempted}），"
            "按 ASSETS_ALLOW_FONT_FALLBACK=1 回退 PIL 内置字体；中文将显示为方框，"
            "**该产物不可用于正式发布**。"
        )
        _FONT_FALLBACK_WARNED = True
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10.1 的 load_default() 不接受 size
        return ImageFont.load_default()


def _splash_fonts():
    return _font(34, bold=True), _font(17)


def _draw_centered(draw, position, text, font, fill) -> None:
    """以 position 为中心绘制文本。

    正常路径仍走 anchor="mm"（与既有已入库的品牌图逐像素一致）。
    只有落到 PIL 内置位图字体时才手算包围盒——那种字体不认 anchor，
    传了会被静默忽略，文字直接跑到左上角。
    """
    if hasattr(font, "getmask2"):
        draw.text(position, text, font=font, fill=fill, anchor="mm")
        return
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (position[0] - (right + left) / 2, position[1] - (bottom + top) / 2),
        text,
        font=font,
        fill=fill,
    )


def _replace_with_retry(source_path: Path, output_path: Path) -> None:
    for delay in REPLACE_RETRY_DELAYS:
        try:
            os.replace(source_path, output_path)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(source_path, output_path)


def _vgradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px_row = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = px_row
    return img


def make_large():
    w, h = 328, 628
    img = _vgradient(w, h)
    d = ImageDraw.Draw(img)

    # 顶部斜切 accent 条带
    d.polygon([(0, 0), (w, 0), (w, 54), (0, 96)], fill=ACCENT)
    d.polygon([(0, 96), (w, 54), (w, 66), (0, 110)], fill=ACCENT_DIM)

    # 中部:准星意象(圆 + 十字),呼应 CS 工具属性
    cx, cy, r = w // 2, 262, 74
    for rr, col, wd in ((r, ACCENT, 5), (r - 22, ACCENT_DIM, 3)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=wd)
    gap, ln = 12, 34
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x1 = cx + dx * gap, cy + dy * gap
        x2 = cx + dx * (gap + ln), cy + dy * (gap + ln)
        d.line([x1, x2], fill=ACCENT, width=5)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=ACCENT)

    # 文案
    _draw_centered(d, (w // 2, 408), "帆派助手", _font(44, bold=True), TEXT)
    _draw_centered(d, (w // 2, 458), "CS2 游戏体验增强工具", _font(17), SUBTEXT)

    # 底部细节线 + 版本占位(安装器不显示具体版本,保持素材可复用)
    d.line([(36, 540), (w - 36, 540)], fill=(58, 52, 86), width=2)
    _draw_centered(d, (w // 2, 568), "github.com/OWNER/cs2-customizer", _font(15), SUBTEXT)

    img.save(OUT / "wizard_large.bmp")
    print("wizard_large.bmp", img.size)


def make_small():
    w, h = 110, 116
    img = _vgradient(w, h)
    d = ImageDraw.Draw(img)
    cx, cy, r = w // 2, h // 2, 34
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT, width=4)
    gap, ln = 7, 16
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d.line(
            [(cx + dx * gap, cy + dy * gap), (cx + dx * (gap + ln), cy + dy * (gap + ln))],
            fill=ACCENT, width=4,
        )
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=ACCENT)
    img.save(OUT / "wizard_small.bmp")
    print("wizard_small.bmp", img.size)


def placeholder_splash_art() -> Image.Image:
    """无美术源图时的占位底图：与向导图同语言的深色渐变 + 准星意象。"""
    w, h = SPLASH_SIZE
    img = _vgradient(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, 132
    for rr, col, wd in ((84, ACCENT, 5), (58, ACCENT_DIM, 3)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=wd)
    gap, ln = 14, 38
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d.line(
            [(cx + dx * gap, cy + dy * gap), (cx + dx * (gap + ln), cy + dy * (gap + ln))],
            fill=ACCENT, width=5,
        )
    d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=ACCENT)
    return img


def compose_splash(source_path: Path, output_path: Path) -> None:
    """Compose the branded startup image and replace the output atomically.

    源图不存在时**照旧抛 FileNotFoundError**（且不碰已有输出）——降级是调用方
    make_splash() 的决定，不是这里的：拿一张占位图悄悄盖掉别人给的美术源图，
    比报错更难查。
    """
    source_path = Path(source_path)

    with Image.open(source_path) as source:
        base = ImageOps.fit(
            source.convert("RGB"),
            SPLASH_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.42),
        )
    compose_splash_from_image(base, output_path)


def compose_splash_from_image(base: Image.Image, output_path: Path) -> None:
    """在已裁切好的底图上叠暗角与文案，原子替换输出文件。"""
    output_path = Path(output_path)
    image = base

    overlay = Image.new("RGBA", SPLASH_SIZE, (0, 0, 0, 0))
    overlay_pixels = overlay.load()
    fade_start = 190
    for y in range(fade_start, SPLASH_SIZE[1]):
        progress = (y - fade_start) / (SPLASH_SIZE[1] - 1 - fade_start)
        alpha = round(205 * progress)
        for x in range(SPLASH_SIZE[0]):
            overlay_pixels[x, y] = (15, 10, 30, alpha)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(image)
    title_font, status_font = _splash_fonts()
    _draw_centered(draw, SPLASH_TITLE_POSITION, SPLASH_TITLE, title_font, TEXT)
    _draw_centered(draw, SPLASH_STATUS_POSITION, SPLASH_STATUS, status_font, SUBTEXT)

    forbidden = (255, 0, 255)
    safe_magenta = (254, 0, 255)
    pixels = image.get_flattened_data()
    if forbidden in pixels:
        image.putdata([safe_magenta if pixel == forbidden else pixel for pixel in pixels])

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.stem}-",
            suffix=".tmp.png",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        image.save(temporary_path, format="PNG")
        _replace_with_retry(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def make_splash():
    """生成项目根目录的 PyInstaller 启动闪屏。

    美术源图是**可选**的：本仓库不分发它。缺失时用渐变占位图顶上，
    别让"没有那张 png"变成整条打包链的硬阻断。
    """
    dst = Path(__file__).resolve().parent.parent / "splash.png"
    if SPLASH_ART_SOURCE.is_file():
        compose_splash(SPLASH_ART_SOURCE, dst)
        print("splash.png", SPLASH_SIZE, "->", dst)
        return

    print(
        f"[WARN] 未找到闪屏美术源图 {SPLASH_ART_SOURCE}，改用渐变占位图生成 splash.png。"
        "\n       如需自定义启动画面，把任意图片放到该路径后重跑本脚本"
        f"（会按 {SPLASH_SIZE[0]}x{SPLASH_SIZE[1]} 居中裁切）。"
    )
    compose_splash_from_image(placeholder_splash_art(), dst)
    print("splash.png(placeholder)", SPLASH_SIZE, "->", dst)


if __name__ == "__main__":
    make_large()
    make_small()
    make_splash()
    print("OK ->", OUT)
