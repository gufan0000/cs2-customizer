# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""生成界面随包字体 `fonts/SailSansSC-{Regular,Medium,Bold}.ttf`（批 145）。

    python build_tools/make_ui_fonts.py [--source <NotoSansSC-VF.ttf>]

产物进版本库，打包和 CI 不跑这支脚本。只有界面文案用上了 GB2312 以外的字才需要重跑。

- 三个字重：雅黑只有 Regular / Bold，14px 粗体糊成一团，界面需要 500 那一档。
- 字符范围：ASCII、拉丁扩展、GB2312、常用符号、产品代码字符串里出现的所有非 ASCII 字符。
  生僻字不进子集，由样式表里排在后面的微软雅黑兜底。
- 私有族名：不和用户电脑上装的 Noto Sans SC 串。OFL 也要求改过的版本不用保留字体名。
- 行高改成 1.36em 且上下居中。Noto 原值 1.448em、字面偏下 56/1000，按钮里的字看着往下坠。
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "fonts"
FAMILY = "Sail Sans SC"
WEIGHTS = (("Regular", 400), ("Medium", 500), ("Bold", 700))
#: 字面中心在基线上方 380/1000，上下各留一半 ⇒ (1060 - 300) / 2 = 380。
ASCENT, DESCENT = 1060, 300
SKIP_DIRS = {
    "tests", "scripts", "build_tools", "docs", "artifacts", "output", "release", "logs",
    ".build", "__pycache__", "resources", "fonts", "server", ".git", ".github", ".claude",
}
SYMBOLS = "，。、；：？！…—～·「」『』《》〈〉（）【】〔〕“”‘’％＋－＝／℃×÷°•●○▲△▼▽◆◇★☆→←↑↓✓✔✕✗"


def gb2312_chars() -> set[str]:
    chars = set()
    for hi in range(0xA1, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes((hi, lo)).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return chars


def source_chars() -> set[str]:
    """产品代码字符串里的非 ASCII 字符：界面文案一个字都不该落到兜底字体上。"""
    chars = set()
    for base, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_manual_backup")]
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(Path(base, name).read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    chars |= {c for c in node.value if ord(c) > 0x7F}
    return {c for c in chars if not 0x1F000 <= ord(c) <= 0x1FFFF}


def charset() -> str:
    chars = {chr(c) for c in range(0x20, 0x7F)} | {chr(c) for c in range(0xA0, 0x180)}
    chars |= gb2312_chars() | source_chars() | set(SYMBOLS)
    return "".join(sorted(chars))


def rename(font: TTFont, style: str) -> None:
    name = font["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 21, 22):
            name.removeNames(nameID=rec.nameID)
    for platform in ((3, 1, 0x409), (1, 0, 0)):
        if style == "Medium":
            # 按 OpenType 规范：RBIZ 之外的字重放进 nameID 16/17
            name.setName(f"{FAMILY} Medium", 1, *platform)
            name.setName("Regular", 2, *platform)
            name.setName(FAMILY, 16, *platform)
            name.setName("Medium", 17, *platform)
        else:
            name.setName(FAMILY, 1, *platform)
            name.setName(style, 2, *platform)
        name.setName(f"{FAMILY} {style}", 4, *platform)
        name.setName(f"SailSansSC-{style}", 6, *platform)
        name.setName(f"Sail;SailSansSC-{style}", 3, *platform)


def set_line_metrics(font: TTFont) -> None:
    hhea, os2 = font["hhea"], font["OS/2"]
    hhea.ascent, hhea.descent, hhea.lineGap = ASCENT, -DESCENT, 0
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ASCENT, -DESCENT, 0
    os2.usWinAscent, os2.usWinDescent = ASCENT, DESCENT


def build(source: str, style: str, weight: int, text: str) -> Path:
    instance = instancer.instantiateVariableFont(TTFont(source), {"wght": weight}, updateFontNames=True)
    options = subset.Options()
    options.layout_features = ["kern", "liga", "locl", "ccmp", "mark", "mkmk", "vert", "palt"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.hinting = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=text)
    subsetter.subset(instance)
    rename(instance, style)
    set_line_metrics(instance)
    path = OUT / f"SailSansSC-{style}.ttf"
    instance.save(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    text = charset()
    print(f"字符数 {len(text)}")
    for style, weight in WEIGHTS:
        path = build(args.source, style, weight, text)
        print(path.name, path.stat().st_size // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
