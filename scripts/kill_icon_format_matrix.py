# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标格式验收矩阵（KI-4/5/6，2026-08-16）。

每一种"用户可能塞进来的东西"都**真造一个文件、真跑一遍导入、再用运行时
装载器读回来对账**，最后打一张表。

为什么要有这个而不是只靠 pytest：
- 判据是按行为分组写的，回答不了"到底支持哪些格式"这个用户会问的问题；
- 判据里的样本都是 3 帧 20x16 的最小件，**帧一多就翻车的问题它照不出来**
  （导出包条目数跟帧数走那次事故就是这么漏的）；
- 这张表本身就是文档：改了格式支持面，重跑一次就知道对外该怎么说。

全程写在临时目录里，**不碰用户的风格库**。

用法：
    python scripts/kill_icon_format_matrix.py
    python scripts/kill_icon_format_matrix.py --markdown   # 输出 Markdown 表格
退出码：0=全部符合预期，1=有格子与预期不符。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 日志别写进用户真实目录
os.environ.setdefault("CS2C_LOG_DIR", tempfile.mkdtemp(prefix="cs2customizer_matrix_log_"))
# 离屏：这个脚本**不许**在用户屏幕上冒出任何窗口
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

# ⚠ 必须先建 QGuiApplication 再用 QImage 读图。
# 没有它 `QImage(path)` 一律返回 null（图片格式插件没被装载），表现是
# "导入成功但运行时装载器读不出来"——一整张表全红，而产品代码毫无问题。
_QAPP = QGuiApplication.instance() or QGuiApplication([])

from PIL import Image  # noqa: E402

from core.kill_icon_import import (  # noqa: E402
    KillIconImportError, convert_to_style, guess_grid, probe_source,
)
from core.kill_icon_pack import import_pack, probe_pack  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="cs2customizer_ki_matrix_"))
ASSETS = WORK / "assets"
LIB = WORK / "lib"
ASSETS.mkdir(parents=True)
LIB.mkdir(parents=True)


# 用**真的** ResourceManager，只把它的数据根按到临时目录上。
#
# ⚠ 别在这里另写一个假的 ResourceManager：第一版就是这么写的，结果它把素材
# 放在 `<根>/kill_icons/…` 而真实实现是 `<根>/resources/kill_icons/…`，
# 于是整张表都显示"导入成功但运行时装载器读不出来"——产品代码毫无问题，
# 是验收脚本自己把路径算错了。导入端和播放端必须走同一套路径解析。
import resource_manager as _rm_module  # noqa: E402

_rm_module.ResourceManager.get_app_data_path = staticmethod(
    lambda relative: str(LIB / str(relative).replace("/", os.sep)))

RM = _rm_module.ResourceManager

STYLE_ROOT = LIB / "resources" / "kill_icons"


# ==================================================== 造素材


def _frame(index, size=(48, 36), alpha=255):
    """每帧一个可区分的颜色，导入后能逐帧对账。"""
    return Image.new("RGBA", size, ((index * 37) % 250 + 1, (index * 11) % 250, 60, alpha))


def make_gif(path, frames=6, ms=80):
    images = [_frame(i) for i in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=ms, loop=0, disposal=2)
    return path


def make_webp(path, frames=5, ms=60):
    images = [_frame(i) for i in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=ms, lossless=True)
    return path


def make_apng(path, frames=4, ms=50):
    images = [_frame(i) for i in range(frames)]
    images[0].save(path, format="PNG", save_all=True,
                   append_images=images[1:], duration=ms)
    return path


def make_avif(path, frames=1):
    _frame(0).save(path, format="AVIF")
    return path


def make_static(path, mode="RGBA"):
    image = _frame(3)
    if mode != "RGBA":
        image = image.convert(mode)
    image.save(path)
    return path


def make_sequence(directory, frames=7, extension=".png", mixed=False):
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        image = _frame(index)
        ext = extension
        if mixed:
            ext = (".png", ".jpg", ".webp")[index % 3]
        if ext in (".jpg", ".jpeg"):
            image = image.convert("RGB")
        image.save(directory / f"frame-{index + 1}{ext}")
    return directory


def make_native_sheet(stem, frames=5, size=32, fps=20):
    sheet = Image.new("RGBA", (size * frames, size), (0, 0, 0, 0))
    for index in range(frames):
        sheet.paste(_frame(index, (size, size)), (index * size, 0))
    sheet.save(f"{stem}.png")
    Path(f"{stem}.json").write_text(json.dumps({
        "frame_width": size, "frame_height": size, "frames": frames,
        "cols": frames, "rows": 1, "fps": fps, "version": 1,
    }), encoding="utf-8")
    return Path(f"{stem}.png"), Path(f"{stem}.json")


def make_aseprite(stem, frames=4, size=24, hash_style=True, ms=40):
    sheet = Image.new("RGBA", (size * frames, size), (0, 0, 0, 0))
    for index in range(frames):
        sheet.paste(_frame(index, (size, size)), (index * size, 0))
    sheet.save(f"{stem}.png")
    entries = {
        f"hero {i}.ase": {"frame": {"x": i * size, "y": 0, "w": size, "h": size},
                          "duration": ms}
        for i in range(frames)
    }
    Path(f"{stem}.json").write_text(json.dumps({
        "frames": entries if hash_style else list(entries.values()),
        "meta": {"image": os.path.basename(f"{stem}.png"),
                 "size": {"w": size * frames, "h": size}},
    }), encoding="utf-8")
    return Path(f"{stem}.json")


def make_bare_grid(path, cols=4, rows=2, size=25):
    sheet = Image.new("RGBA", (size * cols, size * rows), (0, 0, 0, 0))
    for index in range(cols * rows):
        sheet.paste(_frame(index, (size, size)),
                    ((index % cols) * size, (index // cols) * size))
    sheet.save(path)
    return path


def _png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def make_standard_pack(path, levels=((1, ""), (2, ""), (3, "hs")), root="", manifest=True):
    size, frames = 28, 4
    sheet = Image.new("RGBA", (size * frames, size), (0, 0, 0, 0))
    for index in range(frames):
        sheet.paste(_frame(index, (size, size)), (index * size, 0))
    payload = json.dumps({"frame_width": size, "frame_height": size, "frames": frames,
                          "cols": frames, "rows": 1, "fps": 24, "version": 1})
    with zipfile.ZipFile(path, "w") as archive:
        prefix = f"{root}/" if root else ""
        if manifest:
            archive.writestr(prefix + "style.json", json.dumps(
                {"pack_version": 1, "name": "矩阵包", "author": "验收脚本",
                 "version": "1.0"}, ensure_ascii=False))
        for kills, variant in levels:
            archive.writestr(f"{prefix}{kills}{variant}.png", _png_bytes(sheet))
            archive.writestr(f"{prefix}{kills}{variant}.json", payload)
    return path


def make_loose_pack_files(path, names=("1.gif", "ace.png", "三杀.png")):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            if name.endswith(".gif"):
                buffer = BytesIO()
                images = [_frame(i) for i in range(3)]
                images[0].save(buffer, "GIF", save_all=True,
                               append_images=images[1:], duration=100)
                archive.writestr(name, buffer.getvalue())
            else:
                archive.writestr(name, _png_bytes(_frame(1)))
    return path


def make_loose_pack_dirs(path, levels=(1, 2)):
    with zipfile.ZipFile(path, "w") as archive:
        for kills in levels:
            for index in range(4):
                archive.writestr(f"{kills}/frame-{index + 1}.png",
                                 _png_bytes(_frame(index)))
    return path


def make_evil_pack(path, kind):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if kind == "slip":
            archive.writestr("1.png", _png_bytes(_frame(0)))
            archive.writestr("../../evil.txt", b"pwned")
        elif kind == "bomb":
            archive.writestr("1.png", b"\0" * (8 * 1024 * 1024))
        elif kind == "many":
            for index in range(3300):
                archive.writestr(f"f{index}.txt", os.urandom(32))
    return path


# ==================================================== 跑一格


class Row:
    def __init__(self, group, label, note=""):
        self.group = group
        self.label = label
        self.note = note
        self.ok = None
        self.detail = ""


ROWS = []
_level = [0]


def _next_level():
    """1~5 轮着用，导入互不覆盖。"""
    _level[0] = _level[0] % 5 + 1
    return _level[0]


def accept(group, label, source, *, style="矩阵", expect_frames=None,
           expect_static=False, note="", **kwargs):
    """跑一次导入，再用**运行时装载器**读回来对账。"""
    from kill_icon_overlay import load_level_animation, playback_state

    row = Row(group, label, note)
    ROWS.append(row)
    kills = _next_level()
    try:
        # 返回值用不上：对账走下面的**运行时装载器**（游戏里怎么读，这里就怎么读）
        convert_to_style(source, style, kills, resource_manager=RM, **kwargs)
    except Exception as exc:
        row.ok = False
        row.detail = f"导入失败：{exc}"
        return row

    # 运行时装载器怎么读的，游戏里就怎么播
    animation = load_level_animation(style, kills)

    if animation is None:
        row.ok = False
        row.detail = "导入成功但运行时装载器读不出来"
        return row

    problems = []
    if expect_frames is not None and animation.frame_count != expect_frames:
        problems.append(f"帧数 {animation.frame_count} ≠ 预期 {expect_frames}")
    if expect_static:
        if animation.hold_seconds <= 0:
            problems.append("单帧素材没有定格时长")
        elif playback_state(1.0, animation.fps, animation.frame_count,
                            hold=animation.hold_seconds) is None:
            problems.append("单帧素材第 1 秒就已经播完了（等于看不见）")

    row.ok = not problems
    hold = f"，定格 {animation.hold_seconds:.1f}s" if animation.hold_seconds else ""
    row.detail = ("；".join(problems) if problems else
                  f"{animation.frame_count} 帧 @ {animation.fps}fps"
                  f"（{animation.frame_width}x{animation.frame_height}{hold}）")
    return row


def accept_pack(group, label, path, *, style=None, expect_levels=None, note=""):
    row = Row(group, label, note)
    ROWS.append(row)
    try:
        probe = probe_pack(path)
        result = import_pack(path, style_name=style, resource_manager=RM)
    except Exception as exc:
        row.ok = False
        row.detail = f"导入失败：{exc}"
        return row

    levels = result["levels"]
    if expect_levels is not None and levels != expect_levels:
        row.ok = False
        row.detail = f"等级 {levels} ≠ 预期 {expect_levels}"
        return row
    row.ok = True
    author = f"，作者 {probe.author}" if probe.author else ""
    row.detail = (f"风格「{result['style']}」{len(levels)} 个等级"
                  f"{author}，{probe.entry_count} 个条目")
    return row


def reject(group, label, action, *, expect_keyword, note=""):
    """该拒的必须拒，而且**报错里要有出路**。"""
    row = Row(group, label, note)
    ROWS.append(row)
    try:
        action()
    except KillIconImportError as exc:
        message = str(exc)
        row.ok = expect_keyword in message
        row.detail = (message.splitlines()[0] if row.ok
                      else f"报错里没有「{expect_keyword}」：{message.splitlines()[0]}")
        return row
    except Exception as exc:
        row.ok = False
        row.detail = f"抛的不是给用户看的错误：{type(exc).__name__}: {exc}"
        return row
    row.ok = False
    row.detail = "居然没报错"
    return row


# ==================================================== 主流程


def run():
    a = ASSETS

    # ---------------- 动图
    accept("动图", "GIF", make_gif(a / "a.gif", frames=6, ms=80), expect_frames=6,
           note="边缘会有硬白边（1-bit 透明），导入时会提示")
    accept("动图", "WebP 动图", make_webp(a / "a.webp", frames=5), expect_frames=5,
           note="推荐：真 alpha，边缘干净")
    accept("动图", "APNG", make_apng(a / "anim.png", frames=4), expect_frames=4,
           note="推荐：真 alpha")
    try:
        accept("动图", "AVIF", make_avif(a / "a.avif"), expect_frames=1,
               expect_static=True, note="Pillow 带 AVIF 编解码时可用")
    except Exception as exc:
        row = Row("动图", "AVIF", "本机 Pillow 不能写 AVIF，未测")
        row.ok = None
        row.detail = str(exc)
        ROWS.append(row)

    # ---------------- 静态图
    for label, name, mode in (("静态 PNG", "s.png", "RGBA"),
                              ("静态 JPG", "s.jpg", "RGB"),
                              ("静态 BMP", "s.bmp", "RGB"),
                              ("静态 TIFF", "s.tif", "RGB")):
        accept("静态图", label, make_static(a / name, mode), expect_frames=1,
               expect_static=True, note="自动定格 1.5 秒，否则 0.03 秒等于看不见")

    # ---------------- 帧序列
    accept("帧序列", "PNG 序列文件夹", make_sequence(a / "seq_png", frames=7),
           expect_frames=7, note="社区最常见的形态；文件名里的数字决定顺序")
    accept("帧序列", "混合格式文件夹", make_sequence(a / "seq_mix", frames=6, mixed=True),
           expect_frames=6, note="png / jpg / webp 混着放也行")
    accept("帧序列", "只有一张图的文件夹",
           make_sequence(a / "seq_one", frames=1), expect_frames=1, expect_static=True)

    # ---------------- 图集
    sheet_png, sheet_json = make_native_sheet(str(a / "native"), frames=5, fps=20)
    accept("图集", "CS2 Customizer 图集（选 .json）", sheet_json, expect_frames=5,
           note="原样搬进来，不重新编码")
    accept("图集", "CS2 Customizer 图集（选 .png）", sheet_png, expect_frames=5,
           note="会自动找同名 .json——选错文件不再变成一条马赛克")
    accept("图集", "Aseprite 导出（hash）",
           make_aseprite(str(a / "ase_hash"), frames=4), expect_frames=4,
           note="按它的分帧信息重新打包")
    accept("图集", "Aseprite 导出（array）",
           make_aseprite(str(a / "ase_arr"), frames=4, hash_style=False),
           expect_frames=4, note="Aseprite 导出对话框里的另一个选项")
    bare = make_bare_grid(a / "bare.png", cols=4, rows=2)
    accept("图集", "无配置的图集（手填行列）", bare, grid=(4, 2), expect_frames=8,
           note="在「高级导入」里填列数和行数")
    strip = make_bare_grid(a / "strip.png", cols=5, rows=1, size=30)
    guessed = guess_grid(150, 30)
    accept("图集", "无配置的一整行方格（自动认出）", strip, grid=guessed,
           expect_frames=5, note=f"能一眼看出行列时自动填好（这里认出 {guessed}）")

    # ---------------- zip 图标包
    accept_pack("图标包", "标准包（含 style.json）",
                make_standard_pack(a / "pack.zip"),
                expect_levels=[(1, ""), (2, ""), (3, "hs")],
                note="一个 zip = 一整套风格，含作者/版本/说明")
    accept_pack("图标包", "标准包（外面套一层目录）",
                make_standard_pack(a / "pack_root.zip", root="霓虹图标包"),
                expect_levels=[(1, ""), (2, ""), (3, "hs")],
                note="解出来是「包名/1.png」的那种，外壳会自动剥掉")
    accept_pack("图标包", "没有 style.json 的包",
                make_standard_pack(a / "无名包.zip", manifest=False),
                expect_levels=[(1, ""), (2, ""), (3, "hs")],
                note="退回用 zip 文件名当风格名")
    accept_pack("图标包", "松散包（1.gif / ace.png / 三杀.png）",
                make_loose_pack_files(a / "loose.zip"), style="松散",
                expect_levels=[(1, ""), (3, ""), (5, "")],
                note="网盘上下下来的多半是这种")
    accept_pack("图标包", "松散包（1/ 2/ 帧序列目录）",
                make_loose_pack_dirs(a / "loose_dir.zip"), style="松散目录",
                expect_levels=[(1, ""), (2, "")])

    # ---------------- 自动修正
    padded = a / "padded"
    padded.mkdir(exist_ok=True)
    for index in range(3):
        canvas = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        canvas.paste(_frame(index, (16, 16)), (22, 22))
        canvas.save(padded / f"{index + 1}.png")
    row = accept("自动修正", "裁掉四周的透明边", padded, trim=True, expect_frames=3,
                 note="很多素材四周留大片空白，图标在屏幕上显得又小又偏")
    if row.ok and "16x16" not in row.detail:
        row.ok, row.detail = False, f"没裁到 16x16：{row.detail}"

    blackbg = a / "blackbg.png"
    canvas = Image.new("RGBA", (40, 40), (0, 0, 0, 255))
    canvas.paste(_frame(2, (16, 16)), (12, 12))
    canvas.save(blackbg)
    row = accept("自动修正", "抠掉不透明的背景色", blackbg, chroma_key=(0, 0, 0),
                 expect_frames=1, expect_static=True,
                 note="从视频转的素材大多不透明；老版本靠纯黑抠图的自制素材也走这条")
    if row.ok:
        sheet = Image.open(
            RM.get_kill_icon_sprite_sheet_paths("矩阵", _level[0])[0]).convert("RGBA")
        if sheet.getpixel((0, 0))[3] != 0:
            row.ok, row.detail = False, "背景没被抠掉"

    mixed_size = a / "mixed_size"
    mixed_size.mkdir(exist_ok=True)
    Image.new("RGBA", (20, 16), (255, 0, 0, 255)).save(mixed_size / "1.png")
    Image.new("RGBA", (40, 30), (0, 255, 0, 255)).save(mixed_size / "2.png")
    row = accept("自动修正", "各帧尺寸不一致", mixed_size, expect_frames=2,
                 note="统一按最大画格居中对齐，并在导入时说明")
    if row.ok and "40x30" not in row.detail:
        row.ok, row.detail = False, f"没对齐到 40x30：{row.detail}"

    big = a / "big.png"
    Image.new("RGBA", (2000, 1500), (200, 0, 0, 255)).save(big)
    row = accept("自动修正", "超大尺寸（2000x1500）", big, expect_frames=1,
                 expect_static=True, note="自动等比缩到 1024 以内，不是报错")
    if row.ok and "1024x768" not in row.detail:
        row.ok, row.detail = False, f"没缩到 1024x768：{row.detail}"

    # ---------------- 老格式
    make_sequence(STYLE_ROOT / "老风格" / "3", frames=9)
    row = Row("老格式", "逐帧目录（老版本的素材）", "存量用户手上就是这个，照常能播")
    ROWS.append(row)
    from kill_icon_overlay import load_level_animation
    animation = load_level_animation("老风格", 3)
    row.ok = animation is not None and animation.frame_count == 9
    row.detail = (f"{animation.frame_count} 帧 @ {animation.fps}fps"
                  if animation else "读不出来")

    # ---------------- 导出往返
    from core.kill_icon_pack import export_pack

    row = Row("导出", "导出整套风格再装回来",
              "导出的就是运行时格式，对方导入时不用再转一次码")
    ROWS.append(row)
    try:
        out = WORK / "导出.zip"
        exported = export_pack("矩阵包", out)
        back = import_pack(out, style_name="装回来的")
        original = RM.get_kill_icon_sprite_sheet_paths("矩阵包", 1)[0]
        copied = RM.get_kill_icon_sprite_sheet_paths("装回来的", 1)[0]
        same = open(original, "rb").read() == open(copied, "rb").read()
        # 导出侧的等级是 "3hs" 这样的字符串，导入侧是 (3, "hs") 这样的元组
        came_back = {f"{kills}{variant}" for kills, variant in back["levels"]}
        row.ok = bool(same and came_back and came_back == set(exported["levels"]))
        row.detail = (f"{len(exported['levels'])} 个等级 / "
                      f"{exported['size'] // 1024}KB，图集逐字节一致"
                      if row.ok else "往返之后对不上")
    except Exception as exc:
        row.ok, row.detail = False, f"{exc}"

    row = Row("导出", "导出老的逐帧目录风格", "打包时先转成图集，条目数不跟帧数走")
    ROWS.append(row)
    try:
        out = WORK / "老风格.zip"
        export_pack("老风格", out)
        with zipfile.ZipFile(out) as archive:
            names = sorted(archive.namelist())
        back = import_pack(out, style_name="老风格装回来")
        row.ok = names == ["3.json", "3.png", "style.json"] and \
            back["imported"][0]["frames"] == 9
        row.detail = f"{len(names)} 个条目：{names}"
    except Exception as exc:
        row.ok, row.detail = False, f"{exc}"

    # ---------------- 该拒的
    for name, keyword, note in (
        ("clip.mp4", "视频", "报错里直接告诉你先转成 WebP / GIF"),
        ("art.psd", "分层", "先在原软件里导出 PNG 序列"),
        ("logo.svg", "矢量", "先导出成 PNG"),
        ("pack.rar", "解压", "zip 能直接拖，rar/7z 要先解压"),
        ("song.mp3", "音频", ""),
        ("what.xyz", "不认识这个格式", "报错里列出支持哪些"),
    ):
        path = a / name
        path.write_bytes(b"not an image")
        reject("不支持（有出路）", name, lambda p=path: probe_source(p),
               expect_keyword=keyword, note=note)

    empty = a / "空文件夹"
    empty.mkdir(exist_ok=True)
    reject("不支持（有出路）", "空文件夹", lambda: probe_source(empty),
           expect_keyword="没有可用的图片", note="顺带说清帧序列该怎么放")

    broken = a / "broken.zip"
    broken.write_bytes(b"this is not a zip")
    reject("安全护栏", "损坏的 zip", lambda: probe_pack(broken),
           expect_keyword="打不开")
    reject("安全护栏", "zip-slip（含 ../ 的条目）",
           lambda: probe_pack(make_evil_pack(a / "slip.zip", "slip")),
           expect_keyword="不安全", note="整个包拒掉，不是跳过那一条")
    reject("安全护栏", "zip 炸弹（异常压缩比）",
           lambda: probe_pack(make_evil_pack(a / "bomb.zip", "bomb")),
           expect_keyword="压缩比")
    reject("安全护栏", "条目数超限",
           lambda: probe_pack(make_evil_pack(a / "many.zip", "many")),
           expect_keyword="不像是一个图标包")
    reject("安全护栏", "风格名里带路径分隔符",
           lambda: convert_to_style(a / "a.webp", "../逃逸", 1, resource_manager=RM),
           expect_keyword="路径分隔符", note="风格名会直接当目录名用")


# ==================================================== 输出


MARK = {True: "✅", False: "❌", None: "—"}


def render(markdown=False):
    groups = []
    for row in ROWS:
        if not groups or groups[-1][0] != row.group:
            groups.append((row.group, []))
        groups[-1][1].append(row)

    if markdown:
        print("| 分类 | 格式 | 结果 | 实测 | 说明 |")
        print("|---|---|---|---|---|")
        for group, rows in groups:
            for row in rows:
                print(f"| {group} | {row.label} | {MARK[row.ok]} | {row.detail} | {row.note} |")
    else:
        width = max(len(r.label) for r in ROWS) + 2
        for group, rows in groups:
            print(f"\n== {group} " + "=" * (58 - len(group)))
            for row in rows:
                print(f"  {MARK[row.ok]} {row.label:<{width}} {row.detail}")
                if row.note:
                    print(f"      {row.note}")

    bad = [r for r in ROWS if r.ok is False]
    skipped = [r for r in ROWS if r.ok is None]
    print(f"\n共 {len(ROWS)} 格：符合预期 {sum(1 for r in ROWS if r.ok)}，"
          f"不符 {len(bad)}，未测 {len(skipped)}")
    for row in bad:
        print(f"  ❌ {row.group} / {row.label}：{row.detail}")
    return 1 if bad else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--keep", action="store_true", help="保留临时目录以便查看产物")
    args = parser.parse_args()
    try:
        run()
        return render(args.markdown)
    finally:
        if args.keep:
            print(f"\n产物留在：{WORK}")
        else:
            shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
