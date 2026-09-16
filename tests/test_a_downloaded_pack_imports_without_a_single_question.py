# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""端到端：一个社区站下下来的包，拖进去应当**一句都不用问**（2026-09-16）。

## 这条判据守的是整件事的成败

用户原话是「官网的资源可以更方便兼容」。⭐ 而"方便"是可以量的：
**从拖进来到文件落位，中间问了用户几个问题。** 官网包的答案应该是 0。

这条路径要同时走通四层，缺一层就问得出来：

| 层 | 模块 | 它负责 |
|---|---|---|
| 源 | `resource_import_source` | 认格式、安全解压、剥壳 |
| 识 | `resource_identify` | 包名词典把它抬到 `likely` |
| 归 | `resource_placement` | **源路径自带的层原样搬**，不再追问 |
| 落 | `resource_import_wizard` | 冲突检测、逃逸检查、真复制 |

## 手验逼出来的那一刀

第一版走到"归"这层会问「这套素材属于哪一把武器？」——
因为它只看**文件名**（`1.wav`）猜武器，看不见路径里的 `AK47/`。
⭐⭐⭐ 而那一包里每个文件的武器都不一样，**这个问题根本没有正确答案**；
更要命的是这正是**官网包最常见的形态**（社区站不规定结构，
作者照着自己资源目录的样子打包）。

⚠ 这一刀是**端到端手验**逼出来的，单元判据一条都没红 ——
每一层单独看都对，错在层与层之间那个假设。

（本项目测试逐文件跑：
 `python -m pytest tests/test_a_downloaded_pack_imports_without_a_single_question.py`）
"""
from __future__ import annotations

import os
import zipfile

import pytest

from core.resource_identify import LIKELY, identify_groups, read_manifest
from core.resource_import_source import ImportSourceError, open_source
from core.resource_import_wizard import apply_resource_import_plan, plan_from_decisions


def _make_zip(path, entries, payload=b"RIFF____"):
    with zipfile.ZipFile(path, "w") as archive:
        for entry in entries:
            archive.writestr(entry, payload)
    return str(path)


def _run(zip_path, resources_root, style_name="默认"):
    """走完整条链路，返回 (问了几个问题, 落到哪些相对路径)。"""
    source = open_source(zip_path)
    try:
        manifest = read_manifest(source.paths, source.read_text)
        groups = identify_groups(
            source.paths, source_name=source.display_name, manifest=manifest)
        decisions = []
        for group in groups:
            pick = group.preselect
            decisions.append({
                "paths": group.paths,
                "spec_key": pick.spec_key if pick else "",
                "style_name": style_name,
            })
        report = plan_from_decisions(source, decisions, str(resources_root))
        apply_resource_import_plan(report, dry_run=False)
        return report
    finally:
        source.cleanup()


def _landed(resources_root):
    found = []
    for walk_root, _dirs, files in os.walk(str(resources_root)):
        for name in files:
            rel = os.path.relpath(os.path.join(walk_root, name), str(resources_root))
            found.append(rel.replace("\\", "/"))
    return sorted(found)


# ---------------------------------------------------- 官网形态：一句都不问

def test_a_weapon_shaped_pack_asks_nothing_and_lands_correctly(tmp_path):
    """⭐ 本文件的主判据。包名说了是枪声，路径自带 `<武器>/<风格>`。"""
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = _make_zip(tmp_path / "全枪枪声替换 v2.zip", [
        "外壳/AK47/默认/1.wav",
        "外壳/M4A1/默认/1.wav",
        "外壳/AWP/默认/1.wav",
    ])

    report = _run(zip_path, resources)

    assert not report["unrecognized"], (
        f"官网形态的包被问了问题：{report['unrecognized']} —— "
        "而这一包里每个文件的武器都不一样，那个问题没有正确答案。"
    )
    assert _landed(resources) == [
        "audio/gun_sounds/AK47/默认/1.wav",
        "audio/gun_sounds/AWP/默认/1.wav",
        "audio/gun_sounds/M4A1/默认/1.wav",
    ]


def test_the_wrapper_folder_does_not_become_a_weapon_name(tmp_path):
    """⚠ 外壳没剥干净的表现很隐蔽：多出来一层 `外壳/`，
    文件全都进了一把叫「外壳」的枪下面，而复制是成功的。"""
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = _make_zip(tmp_path / "枪声包.zip", [
        "某某整合包/AK47/默认/1.wav",
        "某某整合包/M4A1/默认/1.wav",
    ])
    _run(zip_path, resources)
    landed = _landed(resources)
    assert not any("整合包" in path for path in landed), landed
    assert landed == [
        "audio/gun_sounds/AK47/默认/1.wav",
        "audio/gun_sounds/M4A1/默认/1.wav",
    ]


def test_a_kill_sound_pack_lands_under_its_style(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = _make_zip(tmp_path / "CF爆头 击杀音效包.zip", [
        "清脆/1.mp3", "清脆/2.mp3", "低沉/1.mp3",
    ])
    report = _run(zip_path, resources)
    assert not report["unrecognized"]
    assert _landed(resources) == [
        "audio/kill_sounds/低沉/1.mp3",
        "audio/kill_sounds/清脆/1.mp3",
        "audio/kill_sounds/清脆/2.mp3",
    ]


def test_the_pack_name_alone_decides_between_two_identical_shapes(tmp_path):
    """⭐ 同一个形状，只有包名不同 ⇒ 落到两个不同的目录。

    这一条直接证明"包名词典"那条信号**独自**在起作用。
    """
    for name, expect in (("击杀音效合集.zip", "kill_sounds"),
                         ("击杀语音合集.zip", "kill_voices")):
        resources = tmp_path / f"res_{expect}"
        resources.mkdir()
        zip_path = _make_zip(tmp_path / name, ["风格甲/1.mp3"])
        _run(zip_path, resources)
        assert _landed(resources) == [f"audio/{expect}/风格甲/1.mp3"], name


# ---------------------------------------------------- 非官网：问，但只问一次

def test_a_shapeless_pack_is_not_imported_silently(tmp_path):
    """没有任何线索的包 ⇒ 拿不准 ⇒ ⛔ **一个文件都不许落盘**。

    ⭐ 比"猜错了"更糟的是"猜错了还落了盘"：用户得自己去资源目录里找回来。
    """
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = _make_zip(tmp_path / "素材.zip", ["AK47/默认/1.wav"])
    report = _run(zip_path, resources)
    assert report["summary"]["recognized_count"] == 0
    assert _landed(resources) == [], "拿不准却落了盘"


def test_the_same_pack_lands_once_the_user_picks(tmp_path):
    """用户选了之后，同一个包立刻就能落对位置。"""
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = _make_zip(tmp_path / "素材.zip", ["AK47/默认/1.wav"])
    source = open_source(zip_path)
    try:
        groups = identify_groups(source.paths, source_name=source.display_name)
        decisions = [{"paths": groups[0].paths, "spec_key": "switch_weapons",
                      "style_name": "默认"}]
        report = plan_from_decisions(source, decisions, str(resources))
        apply_resource_import_plan(report, dry_run=False)
    finally:
        source.cleanup()
    assert _landed(resources) == ["audio/switch_weapons/AK47/默认/1.wav"]


# ---------------------------------------------------- 外来数据的边界

def test_a_renamed_rar_says_what_to_do_about_it(tmp_path):
    """⭐ 「这不是一个 zip」远不如「这是 RAR，请先解压」有用。"""
    fake = tmp_path / "看起来像zip.zip"
    fake.write_bytes(b"Rar!\x1a\x07\x00 not really a zip")
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(fake))
    assert "RAR" in str(caught.value)
    assert "解压" in str(caught.value), "只说了它是什么，没说该怎么办"


def test_a_zip_slip_pack_never_writes_outside(tmp_path):
    """⛔ 整条链路上最不能破的一条。"""
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../../evil.wav", b"x")
    with pytest.raises(ImportSourceError):
        open_source(str(zip_path))
    assert not (tmp_path.parent / "evil.wav").exists()
    assert _landed(resources) == []


def test_the_temp_directory_is_cleaned_up(tmp_path):
    """⚠ 每导一个包留一份解压副本，用户的临时目录会被慢慢填满。"""
    zip_path = _make_zip(tmp_path / "包.zip", ["a/1.wav"])
    source = open_source(zip_path)
    temp_root = source.root
    assert os.path.isdir(temp_root)
    source.cleanup()
    assert not os.path.isdir(temp_root)


def test_an_empty_zip_says_so(tmp_path):
    zip_path = tmp_path / "空.zip"
    with zipfile.ZipFile(zip_path, "w"):
        pass
    with pytest.raises(ImportSourceError):
        open_source(str(zip_path))


def test_a_folder_is_accepted_just_like_a_zip(tmp_path):
    """用户已经自己解压过的情况 —— 同样要能吃。"""
    resources = tmp_path / "resources"
    resources.mkdir()
    folder = tmp_path / "全枪枪声替换"
    (folder / "AK47" / "默认").mkdir(parents=True)
    (folder / "AK47" / "默认" / "1.wav").write_bytes(b"x")
    source = open_source(str(folder))
    try:
        groups = identify_groups(source.paths, source_name=source.display_name)
        assert groups[0].confidence == LIKELY
        report = plan_from_decisions(
            source,
            [{"paths": groups[0].paths, "spec_key": groups[0].preselect.spec_key,
              "style_name": "默认"}],
            str(resources))
        apply_resource_import_plan(report, dry_run=False)
    finally:
        source.cleanup()
    assert _landed(resources) == ["audio/gun_sounds/AK47/默认/1.wav"]


def test_importing_twice_does_not_overwrite_by_default(tmp_path):
    """⭐ 冲突时**跳过**而不是覆盖 —— 这是旧向导就有的行为，别在新路上丢掉。"""
    resources = tmp_path / "resources"
    resources.mkdir()
    zip_path = _make_zip(tmp_path / "击杀音效包.zip", ["清脆/1.mp3"])
    _run(zip_path, resources)
    report = _run(zip_path, resources)
    assert report["summary"]["conflict_count"] == 1


# ---------------------------------------------------- 单个素材文件

def test_a_single_audio_file_can_be_imported(tmp_path):
    """⭐ 用户点名的第三种入口：「一个 zip 或者文件夹或者**单文件**」。

    ⚠ 实测逮到它当时被一句「这个文件不是压缩包，也不是文件夹」挡掉了 ——
    而玩家手里最常见的恰恰是这个：从群里存下来一个 `.mp3` 直接拖进来，
    不会先给它建个文件夹再打个包。
    """
    one = tmp_path / "爆头音效.mp3"
    one.write_bytes(b"ID3" + b"\0" * 64)
    source = open_source(str(one))
    try:
        assert source.kind == "file"
        assert source.paths == ["爆头音效.mp3"]
        # ⭐ `display_name` 不含扩展名 —— 它是包名词典那条信号的输入。
        assert source.display_name == "爆头音效"
    finally:
        source.cleanup()


def test_a_single_file_import_lands_where_the_user_picked(tmp_path):
    resources = tmp_path / "res"
    resources.mkdir()
    one = tmp_path / "爆头音效.mp3"
    one.write_bytes(b"ID3" + b"\0" * 64)
    source = open_source(str(one))
    try:
        report = plan_from_decisions(
            source,
            [{"paths": source.paths, "spec_key": "kill_sounds",
              "style_name": "爆头"}],
            str(resources))
        apply_resource_import_plan(report, dry_run=False)
    finally:
        source.cleanup()
    assert _landed(resources) == ["audio/kill_sounds/爆头/爆头音效.mp3"]


def test_a_single_file_never_drags_in_its_neighbours(tmp_path):
    """⛔ 只收这一个文件。

    ⭐ 同目录里别的东西跟这次导入无关 —— 收进来就成了
    「我拖了一个文件，它把整个下载夹都导进去了」。
    """
    folder = tmp_path / "downloads"
    folder.mkdir()
    (folder / "要的.mp3").write_bytes(b"ID3")
    (folder / "不要的.mp3").write_bytes(b"ID3")
    (folder / "报税表.xlsx").write_bytes(b"PK\x03\x04")
    source = open_source(str(folder / "要的.mp3"))
    try:
        assert source.paths == ["要的.mp3"]
    finally:
        source.cleanup()


def test_cleaning_up_a_single_file_source_never_deletes_the_users_folder(tmp_path):
    """⛔⛔ 单文件那条路上 `root` 是**用户自己的目录**。

    `cleanup()` 只许删自己建的临时目录 —— 把用户的下载文件夹删了
    是这个功能能犯的最严重的错误。
    """
    folder = tmp_path / "我的下载"
    folder.mkdir()
    keep = folder / "宝贝素材.mp3"
    keep.write_bytes(b"ID3")
    source = open_source(str(keep))
    source.cleanup()
    source.cleanup()      # 再来一次也不许出事
    assert folder.is_dir(), "用户的目录被删了"
    assert keep.exists(), "用户的文件被删了"


def test_an_empty_single_file_says_so(tmp_path):
    empty = tmp_path / "空的.mp3"
    empty.write_bytes(b"")
    with pytest.raises(ImportSourceError):
        open_source(str(empty))


def test_a_renamed_rar_is_still_refused_not_taken_as_a_single_file(tmp_path):
    """⚠ 加了"单文件"这条路之后最容易破的就是这一条：
    RAR 不是 zip ⇒ 会不会被当成"一个素材文件"收下来？**不许**。
    """
    fake = tmp_path / "素材.zip"
    fake.write_bytes(b"Rar!\x1a\x07\x00 padding")
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(fake))
    assert "RAR" in str(caught.value)
