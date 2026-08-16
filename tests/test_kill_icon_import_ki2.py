# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-2：素材导入管线。

KI-2 之前这条链是**断的**——不是格式不够多，是入口根本不存在：设置页上
没有导入按钮，制作工具生成完图集还存到用户随便选的地方，生成完仍要用户
自己搬进 %LOCALAPPDATA% 的资源目录、自己改名、自己手搓 JSON。

所以这份文件盯的是"用户真会喂进来什么"，以及"喂进来之后播放器认不认"。
最后一条判据（往返）最关键：导入产物必须能被**运行时装载器**原样读回来，
这两边任何一边改了格式约定，都会在那里当场变红。
"""
from __future__ import annotations

import json
import os

import pytest

from core.kill_icon_import import (
    KillIconImportError,
    convert_to_style,
    probe_source,
)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _rgba(width, height, color):
    return Image.new("RGBA", (width, height), color)


def _write_gif(path, frames=4, size=(20, 16), duration_ms=100):
    # 每帧颜色必须真的互不相同：PIL 存 GIF 时会把内容一样的相邻帧合并掉，
    # 分量算式一旦溢出 255 被钳到同色，写出来的帧数就对不上（这里踩过一次）。
    images = [
        _rgba(*size, ((index * 7) % 256, (index * 13) % 256, 40, 255))
        for index in range(frames)
    ]
    images[0].save(str(path), save_all=True, append_images=images[1:],
                   duration=duration_ms, loop=0, disposal=2)
    return path


def _write_webp(path, frames=3, size=(20, 16), duration_ms=50):
    images = [_rgba(*size, (0, index * 60 + 10, 0, 255)) for index in range(frames)]
    images[0].save(str(path), save_all=True, append_images=images[1:],
                   duration=duration_ms, lossless=True)
    return path


def _write_apng(path, frames=3, size=(20, 16), duration_ms=40):
    images = [_rgba(*size, (0, 0, index * 60 + 10, 255)) for index in range(frames)]
    images[0].save(str(path), save_all=True, append_images=images[1:],
                   duration=duration_ms, format="PNG")
    return path


def _write_sequence(directory, frames=3, size=(20, 16)):
    directory.mkdir(parents=True, exist_ok=True)
    # 故意用会把字典序坑掉的命名：frame-2 必须排在 frame-10 前面
    names = ["frame-1.png", "frame-2.png", "frame-10.png"][:frames]
    for index, name in enumerate(names):
        _rgba(*size, (index + 1, 0, 0, 255)).save(str(directory / name))
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


# ==================================================== 1. 探测


def test_probe_reads_gif_frames_and_rate(tmp_path):
    probe = probe_source(_write_gif(tmp_path / "a.gif", frames=4, duration_ms=100))
    assert probe.kind == "animation"
    assert probe.frame_count == 4
    assert probe.fps == 10          # 每帧 100ms
    assert probe.duration == pytest.approx(0.4)


def test_gif_import_warns_about_one_bit_transparency(tmp_path):
    """GIF 的硬边不是我们能修的，但**必须说出来**。

    用户拿表情包当击杀图标是最常见的用法，导进去发现边缘一圈白，
    如果软件一声不吭，用户只会以为是软件画得糙。
    """
    probe = probe_source(_write_gif(tmp_path / "a.gif"))
    assert any("1-bit" in w or "硬白边" in w for w in probe.warnings), probe.warnings


def test_animated_webp_and_apng_are_accepted(tmp_path):
    """这两个才是有全 alpha 的动图格式，是我们真正推荐的入口。"""
    webp = probe_source(_write_webp(tmp_path / "a.webp", frames=3))
    assert webp.frame_count == 3
    assert not any("1-bit" in w for w in webp.warnings)

    apng = probe_source(_write_apng(tmp_path / "a.png", frames=3))
    assert apng.frame_count == 3


def test_sequence_is_sorted_numerically_not_lexically(tmp_path):
    """帧序列按文件名里的数字排，不是字典序。

    字典序会把 `frame-10` 排在 `frame-2` 前面——动画倒着抽风，而且不报错。
    """
    directory = _write_sequence(tmp_path / "seq", frames=3)
    probe = probe_source(directory)
    assert probe.kind == "sequence"
    assert probe.frame_count == 3


def test_unknown_format_is_rejected_with_a_readable_message(tmp_path):
    """真正不认识的格式，报错里要写清楚支持什么。"""
    bad = tmp_path / "a.xyz"
    bad.write_bytes(b"not an image")
    with pytest.raises(KillIconImportError) as excinfo:
        probe_source(bad)
    assert "不认识这个格式" in str(excinfo.value)


@pytest.mark.parametrize("name,keyword", [
    ("clip.mp4", "视频"),
    ("art.psd", "分层"),
    ("logo.svg", "矢量"),
    ("pack.rar", "解压"),
])
def test_recognizable_but_unsupported_formats_get_a_way_out(tmp_path, name, keyword):
    """KI-4：认得出来但不支持的格式，报错必须给**下一步怎么办**。

    KI-4 之前这些统一回一句"不认识这个格式"。用户拿着一个 mp4 站在原地：
    既不知道为什么不行，也不知道该干嘛。视频是这里最常见的一种——
    社区素材有不少是从集锦里剪的片段。
    """
    bad = tmp_path / name
    bad.write_bytes(b"not an image")
    with pytest.raises(KillIconImportError) as excinfo:
        probe_source(bad)
    assert keyword in str(excinfo.value)


def test_empty_directory_is_rejected(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(KillIconImportError):
        probe_source(empty)


def test_oversized_frames_are_downscaled_not_rejected(tmp_path):
    """用户从网上拿的动图动辄上千像素，而图标在屏幕上就 350 宽。

    缩小比报错友好得多——报错等于把这个素材直接判死刑。
    """
    big = tmp_path / "big.png"
    _rgba(2000, 1500, (255, 0, 0, 255)).save(str(big))
    probe = probe_source(big)
    assert max(probe.frame_width, probe.frame_height) <= 1024
    assert any("等比缩小" in w for w in probe.warnings), probe.warnings


def test_mismatched_frame_sizes_are_aligned_and_reported(tmp_path):
    """尺寸不一的帧序列在老的制作工具里会**默默画歪**：它拿第一张的尺寸当
    画格，别的帧 paste 到左上角，大的被裁小的留边，全程不报错。
    """
    directory = tmp_path / "mixed"
    directory.mkdir()
    _rgba(20, 16, (255, 0, 0, 255)).save(str(directory / "1.png"))
    _rgba(40, 30, (0, 255, 0, 255)).save(str(directory / "2.png"))

    probe = probe_source(directory)
    assert (probe.frame_width, probe.frame_height) == (40, 30)
    assert any("尺寸不一致" in w for w in probe.warnings), probe.warnings


# ==================================================== 2. 落库


def test_import_writes_a_style_entry(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    result = convert_to_style(
        _write_webp(tmp_path / "a.webp", frames=3),
        "我的风格", 2, resource_manager=manager,
    )

    assert os.path.isfile(result["sprite_path"])
    assert os.path.isfile(result["json_path"])
    metadata = json.loads(open(result["json_path"], encoding="utf-8").read())
    assert metadata["frames"] == 3
    assert metadata["frame_width"] == 20
    assert metadata["cols"] >= 1
    assert result["kills"] == 2


def test_duration_wins_over_fps_and_lands_as_frame_rate(tmp_path):
    """用户拖的是"待多久"，落盘的仍是帧率——素材 JSON 的格式一个字节没变。"""
    manager = _FakeResourceManager(tmp_path)
    result = convert_to_style(
        _write_gif(tmp_path / "a.gif", frames=30, duration_ms=100),
        "风格", 1, fps=60, duration=2.0, resource_manager=manager,
    )
    assert result["fps"] == 15          # 30 帧 / 2 秒
    assert result["frames"] == 30


def test_headshot_variant_lands_next_to_the_normal_icon(tmp_path):
    """爆头素材是同一等级的**覆写**，文件名带后缀，不新开目录。"""
    manager = _FakeResourceManager(tmp_path)
    normal = convert_to_style(_write_webp(tmp_path / "a.webp"), "风格", 3,
                              resource_manager=manager)
    headshot = convert_to_style(_write_webp(tmp_path / "b.webp"), "风格", 3,
                                variant="hs", resource_manager=manager)

    assert os.path.basename(normal["sprite_path"]) == "3.png"
    assert os.path.basename(headshot["sprite_path"]) == "3hs.png"
    assert os.path.isfile(normal["sprite_path"]), "导入爆头素材不该覆盖普通图标"


def test_reimport_overwrites_in_place(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    first = convert_to_style(_write_webp(tmp_path / "a.webp", frames=3), "风格", 1,
                             resource_manager=manager)
    second = convert_to_style(_write_gif(tmp_path / "b.gif", frames=5), "风格", 1,
                              resource_manager=manager)
    assert first["sprite_path"] == second["sprite_path"]
    metadata = json.loads(open(second["json_path"], encoding="utf-8").read())
    assert metadata["frames"] == 5


def test_bad_style_name_is_rejected_before_touching_disk(tmp_path):
    """风格名会直接当目录名用，路径分隔符必须在落盘之前就拦掉。"""
    manager = _FakeResourceManager(tmp_path)
    for bad in ("", "  ", "../逃逸", "a/b", "a\\b"):
        with pytest.raises(KillIconImportError):
            convert_to_style(_write_webp(tmp_path / "a.webp"), bad, 1,
                             resource_manager=manager)


def test_bad_kill_level_is_rejected(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    for bad in (0, 6, 99):
        with pytest.raises(KillIconImportError):
            convert_to_style(_write_webp(tmp_path / "a.webp"), "风格", bad,
                             resource_manager=manager)


def test_failed_import_leaves_no_half_written_sheet(tmp_path, monkeypatch):
    """写盘中途失败不许留下半张图集。

    留下半张的表现是"进游戏看到花屏或者干脆没图标"，而且看不出发生过什么——
    比直接失败糟得多。所以落盘走的是"先写临时文件再改名"。
    """
    import core.kill_icon_import as module

    manager = _FakeResourceManager(tmp_path)
    sprite_path, _json_path = manager.get_kill_icon_sprite_sheet_paths("风格", 1)

    def _boom(path, payload):
        raise OSError("磁盘满了")

    monkeypatch.setattr(module, "_write_json", _boom)
    with pytest.raises(OSError):
        convert_to_style(_write_webp(tmp_path / "a.webp"), "风格", 1,
                         resource_manager=manager)

    directory = os.path.dirname(sprite_path)
    leftovers = [n for n in os.listdir(directory) if n.endswith(".tmp")]
    assert not leftovers, f"留下了临时文件: {leftovers}"


# ==================================================== 3. 往返（最关键的一条）


def test_imported_asset_loads_back_through_the_runtime_loader(tmp_path, monkeypatch):
    """导入产物必须能被**运行时装载器**原样读回来。

    这条判据横跨导入与播放两个模块。导入端和播放端各自都有自己的测试，
    但两边对"图集长什么样"的约定要是悄悄分了家，各自的测试都还是绿的——
    只有这条会红。切帧顺序、cols 的含义、fps 的落点，全在这里对账。
    """
    from resource_manager import ResourceManager
    import kill_icon_overlay

    def _resolver(relative_path):
        normalized = relative_path.replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / normalized)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(_resolver))

    convert_to_style(
        _write_sequence(tmp_path / "seq", frames=3),
        "往返风格", 4, duration=1.5,
    )

    animation = kill_icon_overlay.load_level_animation("往返风格", 4)
    assert animation is not None, "导入的素材运行时装载器读不出来"
    assert animation.frame_count == 3
    assert animation.fps == 2                    # 3 帧 / 1.5 秒
    assert (animation.frame_width, animation.frame_height) == (20, 16)
    # 帧顺序：导入时按数字排序写进图集，读回来必须还是同一个顺序
    assert [f.pixelColor(10, 8).red() for f in animation.frames] == [1, 2, 3]


def test_imported_style_is_discoverable_by_the_style_scanner(tmp_path, monkeypatch):
    """导完就该在设置页的风格下拉里出现，不需要用户重启或手动刷新目录。"""
    from resource_manager import ResourceManager

    def _resolver(relative_path):
        normalized = relative_path.replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / normalized)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(_resolver))

    convert_to_style(_write_webp(tmp_path / "a.webp"), "新风格", 1)

    assert "新风格" in ResourceManager.list_kill_icon_styles()
    assert ResourceManager.has_kill_icon_level_assets("新风格", 1) is True
