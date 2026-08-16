# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-4b： CS2 Customizer 击杀图标包（一个 zip = 一整套风格）。

分发单位是**风格**而不是单个等级——这是这个功能存在的全部理由。社区素材
九成是打包发的，KI-4b 之前用户拿到一个 zip 要：自己解压、自己猜哪个文件是
几杀、一个等级一个等级地导五次。

这份文件里最要紧的不是"能不能装"，是**安全那一组**：zip 是从网上下下来的
外来数据，`extractall` 对着用户磁盘直接写是不能接受的。zip-slip 的表现是
往资源目录外面写文件（可以覆盖别的程序的东西），zip 炸弹的表现是把磁盘塞满。
这两条都是"功能测试全绿也照样中招"的类型。
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

from core.kill_icon_import import KillIconImportError
from core.kill_icon_pack import (
    MAX_ENTRIES,
    PACK_VERSION,
    export_pack,
    import_pack,
    probe_pack,
)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


class _FakeResourceManager:
    def __init__(self, root):
        self.root = root

    def get_kill_icon_sprite_sheet_paths(self, style_name, kills, variant=""):
        style_dir = self.root / "kill_icons" / style_name
        return (str(style_dir / f"{kills}{variant}.png"),
                str(style_dir / f"{kills}{variant}.json"))

    def get_kill_icon_legacy_frames_dir(self, style_name, kills):
        candidate = self.root / "kill_icons" / style_name / str(kills)
        return str(candidate) if candidate.is_dir() else None

    def get_kill_icon_metadata_path(self, style_name, kills):
        return str(self.root / "kill_icons" / style_name / f"{kills}.json")

    def get_app_data_path(self, relative):
        return str(self.root / relative.replace("/", os.sep))


def _sheet_bytes(frames=3, size=16):
    from io import BytesIO

    image = Image.new("RGBA", (size * frames, size), (0, 0, 0, 0))
    for index in range(frames):
        image.paste(Image.new("RGBA", (size, size), (index + 1, 0, 0, 255)),
                    (index * size, 0))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _metadata(frames=3, size=16, fps=20):
    return json.dumps({
        "frame_width": size, "frame_height": size, "frames": frames,
        "cols": frames, "rows": 1, "fps": fps, "version": 1,
    })


def _write_pack(path, levels=((1, ""), (2, ""), (3, "hs")), manifest=True, root=""):
    with zipfile.ZipFile(path, "w") as archive:
        prefix = f"{root}/" if root else ""
        if manifest:
            archive.writestr(prefix + "style.json", json.dumps({
                "pack_version": PACK_VERSION,
                "name": "霓虹",
                "author": "某位作者",
                "version": "2.1",
                "description": "一套很亮的图标",
            }, ensure_ascii=False))
        for kills, variant in levels:
            archive.writestr(f"{prefix}{kills}{variant}.png", _sheet_bytes())
            archive.writestr(f"{prefix}{kills}{variant}.json", _metadata())
    return path


def _write_loose_pack(path, names=("1.png", "ace.png", "3hs.png")):
    from io import BytesIO

    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            buffer = BytesIO()
            Image.new("RGBA", (20, 16), (120, 0, 0, 255)).save(buffer, "PNG")
            archive.writestr(name, buffer.getvalue())
    return path


# ==================================================== 1. 认包


def test_probe_reads_the_manifest_and_the_levels(tmp_path):
    probe = probe_pack(_write_pack(tmp_path / "pack.zip"))
    assert probe.name == "霓虹"
    assert probe.author == "某位作者"
    assert probe.version == "2.1"
    assert probe.levels == [(1, ""), (2, ""), (3, "hs")]
    assert probe.loose is False


def test_a_single_wrapper_folder_is_stripped(tmp_path):
    """解出来是 `包名/1.png` 的包占大多数。这层外壳不该变成用户的问题。"""
    probe = probe_pack(_write_pack(tmp_path / "pack.zip", root="霓虹图标包"))
    assert probe.levels == [(1, ""), (2, ""), (3, "hs")]


def test_pack_without_a_manifest_still_installs(tmp_path):
    """`style.json` 是给分发者用的规范，不该变成用户的门槛。"""
    probe = probe_pack(_write_pack(tmp_path / "我的图标.zip", manifest=False))
    assert probe.name == "我的图标"          # 退回 zip 文件名
    assert probe.usable is True


def test_loose_zip_is_recognised_by_level_names(tmp_path):
    """网盘上下下来的多半是一堆 `1.gif`…`5.gif`，不是标准包。"""
    probe = probe_pack(_write_loose_pack(tmp_path / "loose.zip"))
    assert probe.loose is True
    assert [(k, v) for k, v, _p in probe.loose_items] == [(1, ""), (3, "hs"), (5, "")]


def test_half_a_level_is_reported_not_silently_dropped(tmp_path):
    """只有 `2.png` 没有 `2.json` 的等级会被跳过——但必须说出来。"""
    path = tmp_path / "half.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("1.png", _sheet_bytes())
        archive.writestr("1.json", _metadata())
        archive.writestr("2.png", _sheet_bytes())

    probe = probe_pack(path)
    assert probe.levels == [(1, "")]
    assert any("半套" in w for w in probe.warnings), probe.warnings


def test_loose_priority_is_deterministic(tmp_path):
    """同一个包导两次，结果必须一样。

    按 zip 里的条目顺序"先到先得"会让结果取决于打包工具——用户看到的表现
    是"同一个包导两次出来的东西不一样"，这种事没人查得动。
    """
    path = tmp_path / "mixed.zip"
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGBA", (20, 16), (1, 0, 0, 255)).save(buffer, "PNG")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3/a.png", buffer.getvalue())
        archive.writestr("3.gif", buffer.getvalue())

    probe = probe_pack(path)
    assert probe.loose_items == [(3, "", "3.gif")], "同名的文件应当优先于目录"


# ==================================================== 2. 安全（重点）


def test_zip_slip_is_refused_before_anything_is_written(tmp_path):
    """`../` 的条目会写到资源目录外面。整个包拒掉，不是"跳过这一条"。

    只跳过那一条同样危险：一个包里既有正常素材又有逃逸条目时，用户会以为
    "导入成功了"，而攻击载荷已经落地。
    """
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("1.png", _sheet_bytes())
        archive.writestr("1.json", _metadata())
        archive.writestr("../../evil.txt", b"pwned")

    with pytest.raises(KillIconImportError) as excinfo:
        probe_pack(path)
    assert "不安全" in str(excinfo.value)
    assert not (tmp_path.parent / "evil.txt").exists()


@pytest.mark.parametrize("name", [
    "/absolute.png",
    "C:/windows/system32/evil.png",
    "a/../../../b.png",
])
def test_other_escaping_paths_are_refused(tmp_path, name):
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, b"x")
    with pytest.raises(KillIconImportError):
        probe_pack(path)


def test_zip_bomb_is_refused(tmp_path):
    """高压缩比的条目只可能是刻意构造的。"""
    path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("1.png", b"\0" * (8 * 1024 * 1024))

    with pytest.raises(KillIconImportError) as excinfo:
        probe_pack(path)
    assert "压缩比" in str(excinfo.value)


def test_too_many_entries_is_refused(tmp_path):
    path = tmp_path / "many.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(MAX_ENTRIES + 5):
            archive.writestr(f"f{index}.txt", os.urandom(64))
    with pytest.raises(KillIconImportError):
        probe_pack(path)


def test_a_broken_zip_gets_a_readable_message(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"this is not a zip")
    with pytest.raises(KillIconImportError) as excinfo:
        probe_pack(path)
    assert "打不开" in str(excinfo.value)


@pytest.mark.parametrize("name", ["../逃逸", "a/b", "..", "   "])
def test_a_malicious_style_name_in_the_manifest_is_sanitised(tmp_path, name):
    """包里的名字会**直接当目录名用**。"""
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("style.json", json.dumps({"name": name}, ensure_ascii=False))
        archive.writestr("1.png", _sheet_bytes())
        archive.writestr("1.json", _metadata())

    manager = _FakeResourceManager(tmp_path)
    try:
        result = import_pack(path, resource_manager=manager)
    except KillIconImportError:
        return          # 洗不出名字就拒绝，也是可接受的结果
    assert ".." not in result["style"]
    assert "/" not in result["style"] and "\\" not in result["style"]


# ==================================================== 3. 装进库


def test_importing_a_pack_installs_every_level(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    result = import_pack(_write_pack(tmp_path / "pack.zip"), resource_manager=manager)

    assert result["style"] == "霓虹"
    assert result["levels"] == [(1, ""), (2, ""), (3, "hs")]
    for kills, variant in result["levels"]:
        sprite, meta = manager.get_kill_icon_sprite_sheet_paths("霓虹", kills, variant)
        assert os.path.isfile(sprite) and os.path.isfile(meta)


def test_pack_import_does_not_re_encode_the_sheets(tmp_path):
    """包内就是运行时格式，所以导入 = 校验 + 落库，不重新编码、不掉画质。"""
    manager = _FakeResourceManager(tmp_path)
    import_pack(_write_pack(tmp_path / "pack.zip", levels=((1, ""),)),
                resource_manager=manager)
    sprite, _meta = manager.get_kill_icon_sprite_sheet_paths("霓虹", 1)
    assert open(sprite, "rb").read() == _sheet_bytes()


def test_loose_pack_is_converted_through_the_normal_pipeline(tmp_path):
    manager = _FakeResourceManager(tmp_path)
    result = import_pack(_write_loose_pack(tmp_path / "loose.zip"),
                         style_name="散装", resource_manager=manager)
    assert result["loose"] is True
    assert result["levels"] == [(1, ""), (3, "hs"), (5, "")]
    # 散装包里是静态图，必须带上定格时长，否则进游戏 0.03 秒就没了
    assert all(item["hold_seconds"] >= 1.0 for item in result["imported"])


def test_a_pack_with_nothing_usable_is_rejected_with_instructions(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", b"hi")
    with pytest.raises(KillIconImportError) as excinfo:
        import_pack(path, resource_manager=_FakeResourceManager(tmp_path))
    assert "1.png" in str(excinfo.value), "报错要告诉用户包该长什么样"


# ==================================================== 4. 导出 → 导入 往返


def test_export_then_import_round_trips(tmp_path):
    """导出的包必须能被自己装回来。

    这条横跨导出与导入两端：两边各自的测试都绿、对包结构的约定却分了家，
    只有这里会红。
    """
    manager = _FakeResourceManager(tmp_path)
    import_pack(_write_pack(tmp_path / "pack.zip"), resource_manager=manager)

    out = tmp_path / "out.zip"
    exported = export_pack("霓虹", out, author="我", description="导出的",
                           resource_manager=manager)
    assert exported["levels"] == ["1", "2", "3hs"]

    probe = probe_pack(out)
    assert probe.name == "霓虹"
    assert probe.author == "我"
    assert probe.levels == [(1, ""), (2, ""), (3, "hs")]

    back = import_pack(out, style_name="回来的", resource_manager=manager)
    assert back["levels"] == [(1, ""), (2, ""), (3, "hs")]

    original, _ = manager.get_kill_icon_sprite_sheet_paths("霓虹", 1)
    copied, _ = manager.get_kill_icon_sprite_sheet_paths("回来的", 1)
    assert open(original, "rb").read() == open(copied, "rb").read()


def test_export_converts_legacy_frame_directories_into_sheets(tmp_path):
    """老的逐帧目录也要能打包分享——那是存量用户手上真正有的东西。

    导出的**永远是运行时格式**，逐帧目录在这里先转成图集：包里条目数因此
    恒定（每个等级两个文件）。这不是洁癖——用户真实的默认风格是 519 帧，
    原样打进去就是 520 个条目，一导入就被条目数上限挡住，
    **我们自己导出的包自己装不回来**。这条判据就是那次的产物。
    """
    manager = _FakeResourceManager(tmp_path)
    legacy = tmp_path / "kill_icons" / "老风格" / "2"
    legacy.mkdir(parents=True)
    for index in range(3):
        Image.new("RGBA", (12, 12), (index + 1, 0, 0, 255)).save(
            str(legacy / f"{index + 1}.png"))

    out = tmp_path / "老风格.zip"
    export_pack("老风格", out, resource_manager=manager)

    with zipfile.ZipFile(out) as archive:
        names = sorted(archive.namelist())
    assert names == ["2.json", "2.png", "style.json"], names

    back = import_pack(out, style_name="装回来", resource_manager=manager)
    assert back["levels"] == [(2, "")]
    assert back["imported"][0]["frames"] == 3


def test_a_pack_never_grows_one_entry_per_frame(tmp_path):
    """条目数必须只跟**等级数**走，不跟帧数走。

    这条钉的是上面那次真实事故的因：判据里用的都是 3 帧的小样本，
    帧数一多才炸，而炸的地方在导入端，离导出端很远。
    """
    manager = _FakeResourceManager(tmp_path)
    legacy = tmp_path / "kill_icons" / "多帧" / "5"
    legacy.mkdir(parents=True)
    for index in range(120):
        Image.new("RGBA", (8, 8), (index % 250 + 1, 0, 0, 255)).save(
            str(legacy / f"{index + 1:03d}.png"))

    out = tmp_path / "多帧.zip"
    export_pack("多帧", out, resource_manager=manager)
    with zipfile.ZipFile(out) as archive:
        assert len(archive.namelist()) == 3, "120 帧不该变成 120 个条目"

    back = import_pack(out, style_name="装回来", resource_manager=manager)
    assert back["imported"][0]["frames"] == 120


def test_exporting_an_empty_style_is_refused(tmp_path):
    with pytest.raises(KillIconImportError):
        export_pack("不存在", tmp_path / "x.zip",
                    resource_manager=_FakeResourceManager(tmp_path))
