# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 145：界面字体随包。

雅黑只有 Regular / Bold，QSS 里写 500 实际是 Regular、写 600 实际是 Bold，层级全靠粗体。
随包还有一个好处：CI、开源版、用户电脑量到的是同一套字体度量（RN-651 那一类红就是度量不同）。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
FONTS = REPO / "fonts"
SKIP_DIRS = {
    "tests", "scripts", "build_tools", "docs", "artifacts", "output", "release", "logs",
    ".build", "__pycache__", "resources", "fonts", "server", ".git", ".github", ".claude",
}


def test_the_font_files_and_their_licence_are_in_the_repo():
    names = {p.name for p in FONTS.iterdir()}
    assert {"SailSansSC-Regular.ttf", "SailSansSC-Medium.ttf", "SailSansSC-Bold.ttf", "OFL.txt"} <= names
    licence = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License" in licence and "Adobe" in licence, "OFL 要求随字体带上版权和许可全文"


def test_asking_for_the_stylesheet_loads_the_font_first(qapp):
    """样式表先生效、字体后加载的话，已经 polish 过的控件不会换字体。"""
    from PySide6.QtGui import QFontDatabase

    from core.utils.app_fonts import UI_FONT_FAMILY
    from theme_manager import get_stylesheet

    stylesheet = get_stylesheet()
    assert UI_FONT_FAMILY in QFontDatabase.families()
    assert f'font-family: "{UI_FONT_FAMILY}", "Microsoft YaHei UI"' in stylesheet, "雅黑要留在后面兜底生僻字"


@pytest.mark.parametrize("weight, style", [(400, "Regular"), (500, "Medium"), (700, "Bold")])
def test_each_weight_the_stylesheet_uses_really_exists(qapp, weight, style):
    from PySide6.QtGui import QFont, QFontInfo

    from core.utils.app_fonts import UI_FONT_FAMILY, load_ui_fonts

    assert load_ui_fonts()
    font = QFont(UI_FONT_FAMILY)
    font.setPixelSize(13)
    font.setWeight(QFont.Weight(weight))
    info = QFontInfo(font)
    assert info.family() == UI_FONT_FAMILY
    assert info.styleName() == style


_NATIVE_PROBE = r'''
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "windows"
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGlyphRun, QImage, QPainter, QRawFont
from PySide6.QtWidgets import QApplication
app = QApplication([])
fonts, family = sys.argv[1], sys.argv[2]
files = {s: os.path.join(fonts, f"SailSansSC-{s}.ttf") for s in ("Regular", "Medium", "Bold")}
for path in files.values():
    QFontDatabase.addApplicationFont(path)
TEXT, PX = "换一套会把默认色和事件设置整套换掉", 40

def ink(draw):
    img = QImage(900, 80, QImage.Format_Grayscale8)
    img.fill(QColor("black"))
    p = QPainter(img)
    p.setPen(QColor("white"))
    draw(p)
    p.end()
    return sum(img.constBits().tobytes())

def by_weight(weight):
    def draw(p):
        f = QFont(family)
        f.setPixelSize(PX)
        f.setWeight(QFont.Weight(weight))
        p.setFont(f)
        p.drawText(5, 60, TEXT)
    return draw

def by_file(path):
    raw = QRawFont(path, PX)
    def draw(p):
        idx = raw.glyphIndexesForString(TEXT)
        run = QGlyphRun()
        run.setRawFont(raw)
        run.setGlyphIndexes(idx)
        x, pos = 5.0, []
        for a in raw.advancesForGlyphIndexes(idx):
            pos.append(QPointF(x, 60))
            x += a.x()
        run.setPositions(pos)
        p.drawGlyphRun(QPointF(0, 0), run)
    return draw

print(json.dumps({"files": {s: ink(by_file(p)) for s, p in files.items()},
                  "weights": {w: ink(by_weight(w)) for w in (400, 500, 700)}}))
'''


@pytest.mark.skipif(os.name != "nt", reason="DirectWrite 只在 Windows 上")
def test_on_the_native_platform_each_weight_draws_its_own_file(tmp_path):
    """批 158：判据跑在 offscreen（FreeType 字体库）上，三档字重各认各的；用户的窗口走 DirectWrite，
    切片留着可变字体的 STAT 表时，400 / 500 都拿 Bold 文件来画 —— 批 145~157 全站正文其实是 700。

    所以在原生平台另起一个进程，按族名 + 字重画一行字，看墨量对上的是哪个文件。
    """
    import json
    import subprocess
    import sys

    from core.utils.app_fonts import UI_FONT_FAMILY

    probe = tmp_path / "native_font_probe.py"
    probe.write_text(_NATIVE_PROBE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    out = subprocess.run([sys.executable, str(probe), str(FONTS), UI_FONT_FAMILY],
                         capture_output=True, text=True, timeout=120, env=env, check=True)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    files, weights = data["files"], data["weights"]
    assert files["Regular"] < files["Medium"] < files["Bold"], files
    for weight, style in (("400", "Regular"), ("500", "Medium"), ("700", "Bold")):
        drawn = weights[weight]
        nearest = min(files, key=lambda s: abs(files[s] - drawn))
        assert nearest == style and abs(drawn - files[style]) < files[style] * 0.01, (
            f"要 {weight} 画出来的是 {nearest}：墨量 {drawn}，各文件 {files}")


@pytest.mark.parametrize("style", ["Regular", "Medium", "Bold"])
def test_the_cut_fonts_carry_no_variable_font_tables(style):
    """STAT / fvar 是可变字体的轴描述；静态切片留着它，DirectWrite 把三档认成一个字面（批 158）。"""
    from fontTools.ttLib import TTFont

    font = TTFont(FONTS / f"SailSansSC-{style}.ttf", lazy=True)
    assert "STAT" not in font and "fvar" not in font, sorted(font.keys())
    fs_selection, mac_style = font["OS/2"].fsSelection, font["head"].macStyle
    assert bool(fs_selection & 0x40) == (style == "Regular"), bin(fs_selection)
    assert bool(fs_selection & 0x20) == (style == "Bold") == bool(mac_style & 1), (bin(fs_selection), mac_style)


def test_the_generator_drops_the_stat_table_it_inherits():
    """字体是生成物：脚本不删 STAT，下次重跑就悄悄回到全站粗体，而上面两条要到那时才红。"""
    import importlib.util

    from fontTools.otlLib.builder import buildStatTable
    from fontTools.ttLib import TTFont

    spec = importlib.util.spec_from_file_location("make_ui_fonts", REPO / "build_tools" / "make_ui_fonts.py")
    make_ui_fonts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_ui_fonts)
    font = TTFont(FONTS / "SailSansSC-Bold.ttf")
    buildStatTable(font, [{"tag": "wght", "name": "Weight", "values": [{"value": 700, "name": "Bold"}]}])
    font["OS/2"].fsSelection, font["head"].macStyle = 0, 0
    make_ui_fonts.set_style_bits(font, "Bold")
    assert "STAT" not in font
    assert font["OS/2"].fsSelection & 0x20 and font["head"].macStyle & 1

    tree = ast.parse((REPO / "build_tools" / "make_ui_fonts.py").read_text(encoding="utf-8"))
    build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build")
    calls = {node.func.id for node in ast.walk(build) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "set_style_bits" in calls, "build() 没调 set_style_bits"


def _stroke(style: str) -> float:
    """「一」字横画的厚度（字体单位）。"""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    font = TTFont(FONTS / f"SailSansSC-{style}.ttf")
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[font.getBestCmap()[ord("一")]].draw(pen)
    return pen.bounds[3] - pen.bounds[1]


def test_body_strokes_are_heavier_than_the_weight_name_says():
    """批 154：字没有 hinting，用户 125% 缩放下 wght 400 的横画约一个像素，看着发虚。

    Regular 切 450（横画 82 → 93 单位），Medium 跟着到 560，三档之间仍各差约 20。
    """
    regular, medium, bold = (_stroke(s) for s in ("Regular", "Medium", "Bold"))
    assert regular >= 90, f"Regular 横画 {regular}：回到了 wght 400 的 82"
    assert medium - regular >= 15 and bold - medium >= 15, (regular, medium, bold)


def test_the_generator_still_cuts_the_heavier_regular():
    """字体文件是生成物：脚本改回 400，下次重跑就悄悄回到发虚的那一档，而上一条判据要到那时才红。"""
    tree = ast.parse((REPO / "build_tools" / "make_ui_fonts.py").read_text(encoding="utf-8"))
    weights = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "WEIGHTS")
    cut = {style: wght for style, _, wght in weights}
    assert cut["Regular"] >= 450 and cut["Medium"] > 500, weights


def test_the_stylesheet_only_asks_for_three_weights():
    """写 600 不会报错，只会悄悄变成 Bold：层级又回到靠粗体。"""
    import re

    from theme_manager import ThemeManager

    weights = set(re.findall(r"font-weight:\s*(\w+)", ThemeManager().themes["dark"].generate_stylesheet()))
    assert weights <= {"400", "500", "700", "bold", "normal"}, weights


def test_a_missing_font_file_does_not_stop_the_app(qapp, monkeypatch):
    from core.utils import app_fonts
    from resource_manager import ResourceManager

    monkeypatch.setattr(app_fonts, "_loaded", False)
    monkeypatch.setattr(ResourceManager, "get_exe_resource_path",
                        staticmethod(lambda relative: str(REPO / "no_such_dir" / relative)))
    assert app_fonts.load_ui_fonts() is False


def _product_cjk() -> set[str]:
    chars = set()
    files = 0
    for base, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_manual_backup")]
        for name in names:
            if not name.endswith(".py"):
                continue
            files += 1
            tree = ast.parse(Path(base, name).read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    # U+9FFF 只出现在正则区间的端点上，不是界面文字
                    chars |= {c for c in node.value if 0x4E00 <= ord(c) < 0x9FFF}
    must_scan(range(files), "产品 .py", least=150)
    return chars


def test_every_chinese_character_in_the_product_is_in_the_font(qapp):
    """缺字不会崩，只是那一个字落到雅黑上，字重和字形都对不上。

    红了 ⇒ 跑 `python build_tools/make_ui_fonts.py` 重新生成。
    """
    from PySide6.QtGui import QRawFont

    raw = QRawFont(str(FONTS / "SailSansSC-Regular.ttf"), 13)
    chars = _product_cjk()
    must_scan(chars, "产品字符串里的汉字", least=1000)
    missing = sorted(c for c in chars if not raw.supportsCharacter(ord(c)))
    assert not missing, f"字体里缺这些字：{''.join(missing)}"


def test_the_font_name_survives_the_open_source_rename():
    """同步工具的改名规则改代码、不改 ttf：族名带品牌的话，开源版认不出字体，悄悄退回雅黑（RN-756）。"""
    import importlib.util

    from PySide6.QtGui import QRawFont

    from core.utils.app_fonts import UI_FONT_FAMILY

    manifest_path = REPO / "build_tools" / "oss_sync" / "manifest.py"
    # 派生工具只在上游存在；下游仍必须实测改名后的代码与二进制族名一致。
    if manifest_path.is_file():
        spec = importlib.util.spec_from_file_location("oss_manifest", manifest_path)
        manifest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manifest)
        renamed = UI_FONT_FAMILY
        for old, new in manifest.RENAME_RULES:
            renamed = renamed.replace(old, new)
        assert renamed == UI_FONT_FAMILY
    raw = QRawFont(str(FONTS / "SailSansSC-Regular.ttf"), 13)
    assert raw.familyName() == UI_FONT_FAMILY


def test_the_packaged_build_carries_the_fonts():
    """打包版漏了字体不会报错，只会悄悄退回雅黑，而所有判据量的都是随包字体。"""
    source = (REPO / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    assert '(stage_dir / "fonts", "fonts")' in source
    assert '"fonts" / "SailSansSC-Medium.ttf"' in source
