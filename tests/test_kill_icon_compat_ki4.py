# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-4/KI-5：素材兼容性与"静默失败"。

这份文件盯的是一类特别难发现的缺陷：**导入成功了，游戏里却不对，而且没有
任何报错**。KI-4 之前有四条这样的路，用户能做的只有困惑：

1. 拖一张静态 PNG 进来 → 图标只显示 0.033 秒，等于看不见。
2. 图集旁边躺着 `x.png` 和 `x.json`，选中那张 png → 整张图集被当成一帧，
   屏幕上是一条巨大的马赛克。
3. 把**文件夹**拖到设置页上 → 什么都不发生（连报错都没有）。
4. `.jpg` 单独拖进来被拒，同一个 `.jpg` 放进文件夹里却能进。

判据里最要紧的是"裁边必须按并集包围盒"那条：逐帧各裁各的做出来非常好看，
只有连着看才会发现整个动画在原地抖。
"""
from __future__ import annotations

import json

import pytest

from core.kill_icon_import import (
    DEFAULT_CHROMA_TOLERANCE,
    KillIconImportCancelled,
    KillIconImportError,
    analyze_frames,
    convert_to_style,
    guess_grid,
    parse_level_name,
    probe_source,
)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _rgba(width, height, color):
    return Image.new("RGBA", (width, height), color)


def _write_static_png(path, size=(24, 18), color=(200, 30, 30, 255)):
    _rgba(*size, color).save(str(path))
    return path


def _write_sequence(directory, frames=3, size=(20, 16)):
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        _rgba(*size, (index + 1, 0, 0, 255)).save(str(directory / f"{index + 1}.png"))
    return directory


class _FakeResourceManager:
    """把资源根目录按到 tmp_path 上，别碰用户真实的 %LOCALAPPDATA%。"""

    def __init__(self, root):
        self.root = root

    def get_kill_icon_sprite_sheet_paths(self, style_name, kills, variant=""):
        style_dir = self.root / "kill_icons" / style_name
        return (str(style_dir / f"{kills}{variant}.png"),
                str(style_dir / f"{kills}{variant}.json"))

    def get_kill_icon_legacy_frames_dir(self, style_name, kills):
        candidate = self.root / "kill_icons" / style_name / str(kills)
        return str(candidate) if candidate.is_dir() else None


# ==================================================== 1. 静态图（第 1 条静默失败）


def test_static_image_lands_with_a_hold_so_it_is_actually_visible(tmp_path):
    """一张静态 PNG 导进来必须能看见。

    KI-4 之前：静态图没有每帧时长 → 帧率回落到 30 → 1 帧 ÷ 30 = 0.033 秒。
    弹窗说"导入成功"，游戏里什么都没有。
    """
    manager = _FakeResourceManager(tmp_path)
    result = convert_to_style(_write_static_png(tmp_path / "icon.png"), "风格", 1,
                              resource_manager=manager)

    assert result["frames"] == 1
    assert result["hold_seconds"] >= 1.0, "单帧素材必须自带定格时长"

    metadata = json.loads(open(result["json_path"], encoding="utf-8").read())
    assert metadata["hold_seconds"] >= 1.0

    from kill_icon_overlay import playback_state
    assert playback_state(0.9, metadata["fps"], metadata["frames"],
                          hold=metadata["hold_seconds"]) is not None


def test_static_image_probe_says_it_will_be_frozen(tmp_path):
    """探测就要说清楚"这是一张静态图，会定格 N 秒"，不能等用户进游戏才发现。"""
    probe = probe_source(_write_static_png(tmp_path / "icon.png"))
    assert probe.frame_count == 1
    assert probe.hold_seconds >= 1.0
    assert any("静态" in w for w in probe.warnings), probe.warnings
    assert probe.duration >= 1.0


def test_multi_frame_sources_never_get_a_hold(tmp_path):
    """定格只对单帧素材生效。给多帧素材偷偷加尾巴就是改了别人的作品。"""
    manager = _FakeResourceManager(tmp_path)
    result = convert_to_style(_write_sequence(tmp_path / "seq", frames=3), "风格", 2,
                              resource_manager=manager)
    assert result["hold_seconds"] == 0.0


# ==================================================== 2. 图集选错文件（第 2 条）


def test_selecting_the_sheet_png_finds_its_json(tmp_path):
    """用户选中 `x.png` 而不是 `x.json` 时，要自动去找同名的配置。

    KI-4 之前的表现：整张图集被当成"一张静态图"读进来，缩到 1024 宽变成一帧。
    屏幕上是一条横着的马赛克，全程零警告。文件夹里躺着两个同名文件，
    凭什么用户知道要选 json？
    """
    sheet = tmp_path / "sheet.png"
    _rgba(60, 20, (10, 20, 30, 255)).save(str(sheet))
    (tmp_path / "sheet.json").write_text(json.dumps({
        "frame_width": 20, "frame_height": 20, "frames": 3, "cols": 3, "rows": 1,
        "fps": 12,
    }), encoding="utf-8")

    probe = probe_source(sheet)
    assert probe.kind == "spritesheet"
    assert probe.frame_count == 3
    assert (probe.frame_width, probe.frame_height) == (20, 20)


def test_native_spritesheet_is_copied_without_re_encoding(tmp_path):
    """我们自己格式的图集原样搬，不重新编码——重编码只会掉画质。"""
    manager = _FakeResourceManager(tmp_path)
    sheet = tmp_path / "sheet.png"
    _rgba(60, 20, (10, 20, 30, 255)).save(str(sheet))
    (tmp_path / "sheet.json").write_text(json.dumps({
        "frame_width": 20, "frame_height": 20, "frames": 3, "cols": 3, "rows": 1,
    }), encoding="utf-8")

    result = convert_to_style(sheet, "风格", 3, resource_manager=manager)
    assert open(result["sprite_path"], "rb").read() == open(sheet, "rb").read()


# ==================================================== 3. 格式表统一（第 4 条）


@pytest.mark.parametrize("name", ["a.jpg", "a.bmp", "a.png", "a.webp"])
def test_single_static_files_are_accepted_just_like_in_a_folder(tmp_path, name):
    """单文件与文件夹认的格式必须是**同一张表**。

    KI-4 之前 `.jpg` 单独拖进来报"不认识这个格式"，同一个 `.jpg` 放进文件夹
    却能进。用户感受是"这软件挑食挑得莫名其妙"。
    """
    path = tmp_path / name
    _rgba(20, 16, (90, 90, 90, 255)).convert("RGB" if name.endswith((".jpg", ".bmp"))
                                             else "RGBA").save(str(path))
    probe = probe_source(path)
    assert probe.frame_count == 1


def test_the_two_extension_tables_are_literally_the_same_set():
    """结构性判据：两张表不许各写各的——它们分家过一次，谁都没发现。"""
    from core.kill_icon_import import SEQUENCE_EXTENSIONS, SINGLE_FILE_EXTENSIONS

    assert set(SEQUENCE_EXTENSIONS) == set(SINGLE_FILE_EXTENSIONS)


# ==================================================== 4. Aseprite / 网格图集


def _write_aseprite(tmp_path, hash_style=True, frames=3, size=16):
    sheet = tmp_path / "hero.png"
    image = Image.new("RGBA", (size * frames, size), (0, 0, 0, 0))
    for index in range(frames):
        image.paste(_rgba(size, size, (index + 1, 0, 0, 255)), (index * size, 0))
    image.save(str(sheet))

    entries = {
        f"hero {index}.ase": {
            "frame": {"x": index * size, "y": 0, "w": size, "h": size},
            "duration": 50,
        }
        for index in range(frames)
    }
    payload = {
        "frames": entries if hash_style else list(entries.values()),
        "meta": {"image": "hero.png", "size": {"w": size * frames, "h": size}},
    }
    json_path = tmp_path / "hero.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    return json_path


@pytest.mark.parametrize("hash_style", [True, False])
def test_aseprite_export_is_understood(tmp_path, hash_style):
    """Aseprite 是做图标的人真正在用的工具，它的 schema 与我们的完全不同。

    KI-4 之前选中它只会得到一句"这份配置缺少 frame_width"——用户根本猜不到
    问题出在哪。hash 和 array 两种导出都要认：那在 Aseprite 里是个下拉框，
    用户不会知道我们只认其中一种。
    """
    json_path = _write_aseprite(tmp_path, hash_style=hash_style)
    probe = probe_source(json_path)
    assert probe.kind == "spritesheet"
    assert probe.frame_count == 3
    assert probe.fps == 20                      # 每帧 50ms
    assert any("Aseprite" in w for w in probe.warnings), probe.warnings


def test_aseprite_import_repacks_into_our_layout(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    result = convert_to_style(_write_aseprite(tmp_path), "风格", 4,
                              resource_manager=manager)
    metadata = json.loads(open(result["json_path"], encoding="utf-8").read())
    assert metadata["frames"] == 3
    assert metadata["frame_width"] == 16


def test_grid_guess_only_fires_when_it_is_unambiguous():
    """猜错的表现是切出一堆错位的半张图，而且照样"导入成功"。

    所以只认一眼就是的两种：一整行 / 一整列的正方形帧。剩下的问用户要行列数。
    """
    assert guess_grid(400, 100) == (4, 1)
    assert guess_grid(100, 400) == (1, 4)
    assert guess_grid(350, 250) is None
    assert guess_grid(100, 100) is None          # 一帧的正方形不算网格


def test_explicit_grid_slices_a_bare_spritesheet(tmp_path):
    """没有元数据的图集，用户填了行列就该切得出来。"""
    manager = _FakeResourceManager(tmp_path)
    sheet = tmp_path / "bare.png"
    image = Image.new("RGBA", (60, 20), (0, 0, 0, 0))
    for index in range(3):
        image.paste(_rgba(20, 20, (index + 1, 0, 0, 255)), (index * 20, 0))
    image.save(str(sheet))

    result = convert_to_style(sheet, "风格", 5, grid=(3, 1), resource_manager=manager)
    assert result["frames"] == 3
    assert result["frame_width"] == 20


# ==================================================== 5. 自动修正（KI-5）


def test_trim_uses_the_union_box_so_the_animation_does_not_jitter(tmp_path):
    """裁边必须按**所有帧的并集**包围盒。

    逐帧各裁各的会把每一帧的内容都推到画格正中，播放时整个动画在原地抖动。
    这个错误做出来非常好看，只有连着看才能发现不对。

    回退验证（已实测会红）：把裁边换成 `frame.crop(frame.getbbox())` 逐帧裁，
    画格尺寸和两帧的相对位置**同时**对不上。

    ⚠ 这条判据第一版是假绿的：素材选的是"亮点从画布左上角走到右下角"，
    并集包围盒正好等于整张画布，于是根本没进裁剪分支，怎么改都逮不住。
    现在四周留了 5px 的余量，逼它真的裁一次。
    """
    manager = _FakeResourceManager(tmp_path)
    directory = tmp_path / "moving"
    directory.mkdir()
    # 40x40 画布，10x10 的亮点从 (5,5) 走到 (25,25)：并集包围盒是 (5,5,35,35)
    for index, (x, y) in enumerate([(5, 5), (25, 25)]):
        frame = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        frame.paste(_rgba(10, 10, (255, 255, 255, 255)), (x, y))
        frame.save(str(directory / f"{index + 1}.png"))

    result = convert_to_style(directory, "风格", 1, trim=True, resource_manager=manager)
    assert (result["frame_width"], result["frame_height"]) == (30, 30), \
        "并集包围盒是 30x30；逐帧裁会得到 10x10"

    width = result["frame_width"]
    sheet = Image.open(result["sprite_path"]).convert("RGBA")
    first = sheet.crop((0, 0, width, width))
    second = sheet.crop((width, 0, width * 2, width))
    assert first.getbbox() != second.getbbox(), "两帧的亮点被裁到了同一个位置＝动画会抖"


def test_trim_actually_removes_a_uniform_margin(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    directory = tmp_path / "padded"
    directory.mkdir()
    for index in range(2):
        frame = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        frame.paste(_rgba(10, 10, (255, 0, 0, 255)), (15, 15))
        frame.save(str(directory / f"{index + 1}.png"))

    result = convert_to_style(directory, "风格", 2, trim=True, resource_manager=manager)
    assert (result["frame_width"], result["frame_height"]) == (10, 10)
    assert any("裁掉" in w for w in result["warnings"]), result["warnings"]


def test_chroma_key_rescues_an_opaque_background(tmp_path):
    """从视频转出来的素材大多是不透明的，叠在游戏画面上就是一个方块。

    老 pygame 版靠"纯黑当透明"抠图，所以老用户为那一版自制的黑底素材迁到
    Qt 版会变成黑框——随包的默认素材是真 alpha（实测过），中招的只会是
    用户自己做的。
    """
    manager = _FakeResourceManager(tmp_path)
    source = tmp_path / "blackbg.png"
    frame = Image.new("RGBA", (20, 20), (0, 0, 0, 255))
    frame.paste(_rgba(6, 6, (255, 255, 0, 255)), (7, 7))
    frame.save(str(source))

    result = convert_to_style(source, "风格", 3, chroma_key=(0, 0, 0),
                              resource_manager=manager)
    sheet = Image.open(result["sprite_path"]).convert("RGBA")
    assert sheet.getpixel((0, 0))[3] == 0, "背景没被抠掉"
    assert sheet.getpixel((10, 10))[3] == 255, "内容不该被抠掉"


def test_analysis_flags_an_opaque_background_and_a_fat_margin():
    frames = [Image.new("RGBA", (40, 40), (0, 0, 0, 255))]
    report = analyze_frames(frames)
    assert report["opaque_background"] is True
    assert report["suggested_key_color"] == (0, 0, 0)

    padded = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    padded.paste(_rgba(8, 8, (255, 0, 0, 255)), (16, 16))
    report = analyze_frames([padded])
    assert report["opaque_background"] is False
    assert report["transparent_margin"] >= 8


def test_analysis_is_not_done_during_a_plain_probe(tmp_path, monkeypatch):
    """探测默认**不读像素**。

    探测是"选完文件立刻要出信息"的交互；把 600 帧解一遍会当场卡住界面，
    而且那个卡顿时长由用户素材大小决定——最不该由用户素材决定的就是这个。
    """
    import core.kill_icon_import as module

    def _boom(*_args, **_kwargs):
        raise AssertionError("探测不该把整套帧解出来")

    monkeypatch.setattr(module, "_read_sequence_frames", _boom)
    probe = probe_source(_write_sequence(tmp_path / "seq", frames=4))
    assert probe.frame_count == 4


def test_cancelling_an_import_is_not_reported_as_a_failure(tmp_path):
    """取消不是错误。用 `KillIconImportError` 表示取消会让 UI 弹一个"导入失败"。"""
    manager = _FakeResourceManager(tmp_path)
    with pytest.raises(KillIconImportCancelled):
        convert_to_style(_write_sequence(tmp_path / "seq", frames=4), "风格", 1,
                         resource_manager=manager, cancel=lambda: True)
    assert not issubclass(KillIconImportCancelled, KillIconImportError)


def test_progress_is_reported_while_reading_frames(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    seen = []
    convert_to_style(_write_sequence(tmp_path / "seq", frames=4), "风格", 1,
                     resource_manager=manager,
                     progress=lambda done, total, stage: seen.append((done, total, stage)))
    assert seen, "导入要能报进度，否则大素材看起来像卡死"
    assert seen[-1][0] >= 1


# ==================================================== 6. 等级别名


@pytest.mark.parametrize("name,expected", [
    ("1.gif", (1, "")),
    ("3.png", (3, "")),
    ("ace.webp", (5, "")),
    ("kill2", (2, "")),
    ("三杀.gif", (3, "")),
    ("4hs.png", (4, "hs")),
    ("5_爆头.gif", (5, "hs")),
    ("headshot", None),
    ("随便什么.gif", None),
    ("6.gif", None),
])
def test_level_names_are_recognised_beyond_bare_digits(name, expected):
    """批量导入 KI-4 之前只认严格的 `1`~`5`。

    社区素材包里叫 `kill1` / `ace` / `三杀` 的比比皆是，一律被静默跳过
    （提示里只有一句"名字不是 1~5"，用户得自己去猜要改成什么）。
    """
    assert parse_level_name(name) == expected


def test_chroma_tolerance_has_a_sane_default():
    assert 0 < DEFAULT_CHROMA_TOLERANCE < 64
