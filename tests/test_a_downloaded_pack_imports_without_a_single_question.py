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
    # ⚠ 2026-09-17：落点从 `AK47/` 改成 `ak47/`。**这不是把断言改绿** ——
    #   产品那头按 `core.gun_sound_profiles.GUN_SOUND_WEAPON_TYPES` 里的
    #   **小写代号**找目录，大写只是在 Windows 的不分大小写文件系统上
    #   碰巧撞对了；⭐ 「碰巧能用」和「对」在测试报告上长得一模一样。
    assert _landed(resources) == [
        "audio/gun_sounds/ak47/默认/1.wav",
        "audio/gun_sounds/awp/默认/1.wav",
        "audio/gun_sounds/m4a1/默认/1.wav",
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
        "audio/gun_sounds/ak47/默认/1.wav",
        "audio/gun_sounds/m4a1/默认/1.wav",
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
    assert _landed(resources) == ["audio/switch_weapons/ak47/默认/1.wav"]


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
    assert _landed(resources) == ["audio/gun_sounds/ak47/默认/1.wav"]


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
    # ⚠⚠ 2026-09-17：落点从 `爆头音效.mp3` 改成 `1.mp3`。
    #   ⭐⭐⭐ 旧断言断言的是一个**产品一辈子不会读的位置**：
    #   `AudioManager._load_range` 找的是 `1.*`~`5.*`（`style_creator`
    #   把击杀音效标成 `numbered`），而 `爆头音效.mp3` 不在其中 ——
    #   风格会出现在设置页的下拉框里（目录里有音频就算一个风格），
    #   **进游戏一声不响**。导入器现在替用户改名，并在提示条里说出来。
    assert _landed(resources) == ["audio/kill_sounds/爆头/1.mp3"]


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


# ---------------------------------------------- 格式分发：认出来的都不许掉下去

def test_every_format_the_sniffer_knows_is_either_opened_or_refused(tmp_path):
    """⭐⭐ 棘轮：**不列举格式**，拿 `_MAGIC` 自己现算。

    原来的分发写的是「`kind in UNSUPPORTED_HINTS` 就拒绝」——一条**按名单放行**
    的判断。于是 `_MAGIC` 认得出、名单里没有的那一种（当时是 gzip）
    两个 if 都不成立，一路掉到最后当成"一个素材文件"收下来。

    ⭐⭐⭐ 根因不是漏了一行文案，是**两处各自列举、谁也不管谁**：
    `_MAGIC` 每多认一种格式，分发那头就多一条静默的落法。
    ⇒ 这条判据钉的就是那个关系本身：认得出的，要么打得开，要么拒绝得明明白白。
    """
    from core.archive_safe import _MAGIC

    for magic, kind in _MAGIC:
        probe = tmp_path / f"探针_{kind}.bin"
        probe.write_bytes(magic + b"\0" * 512)
        if kind == "zip":
            continue          # zip 走正常开包路径，另有判据
        with pytest.raises(ImportSourceError) as caught:
            open_source(str(probe))
        message = str(caught.value)
        assert message, f"{kind} 被拒绝了却没说为什么"
        assert "解压" in message or "不是资源包" in message, (
            f"{kind} 的说法照着做不了：{message}")


def test_a_tar_gz_is_refused_instead_of_landing_as_a_dead_file(tmp_path):
    """⛔ `.tar.gz` 曾经会**原样落进资源目录**。

    实测记录：`枪声包.tar.gz` 进了 `audio/…/枪声包.tar.gz` ——
    导入报成功、文件也在，**进游戏永远不会响**。
    ⭐ 这是这个功能最该防的那一类失败：装得进去，不出错，不生效。
    """
    import gzip as gzlib

    packed = tmp_path / "枪声包.tar.gz"
    with gzlib.open(packed, "wb") as handle:
        handle.write(b"\0" * 2048)
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(packed))
    assert "gz" in str(caught.value), "没点名是什么格式，用户不知道该拿它怎么办"


def test_the_drop_hint_calls_a_single_file_a_file(tmp_path):
    """⚠ 拖放那句提示原来写死成「文件夹 / 压缩包」二选一。

    那是**加单文件那条路之前**的世界；加完之后拖一个 `爆头音效.mp3` 进来，
    它会说「已填入拖入的**压缩包**」。
    ⭐ 每一层单独看都对，错在层与层之间的假设 ——
    新入口加在 `open_source` 那层，说这句话的却是页面那层。
    """
    from pages.audio_import_wizard_page import AudioImportWizardPage

    noun = AudioImportWizardPage._drop_noun

    folder = tmp_path / "一个文件夹"
    folder.mkdir()
    assert noun(str(folder)) == "文件夹"

    plain = tmp_path / "爆头音效.mp3"
    plain.write_bytes(b"ID3" + b"\0" * 64)
    assert noun(str(plain)) == "文件"

    packed = tmp_path / "包.zip"
    with zipfile.ZipFile(packed, "w") as zf:
        zf.writestr("a.wav", b"RIFF")
    assert noun(str(packed)) == "压缩包"

    # ⭐ 改名的 RAR 也该叫"压缩包"——这样提示和随后那句
    #   「这是 RAR，请先解压」不会自相矛盾。
    renamed = tmp_path / "其实是rar.zip"
    renamed.write_bytes(b"Rar!\x1a\x07\x00 padding")
    assert noun(str(renamed)) == "压缩包"


# ------------------------------------- 真实世界的包里从来不只有素材

#: 四样**现实里躲不开**的杂物，各来自一个不同的源头。
REAL_WORLD_JUNK = [
    "__MACOSX/AK47/默认/._1.wav",   # Mac 上打 zip 必带
    "AK47/默认/Thumbs.db",          # Windows 看过一眼图片目录就有
    "说明.txt",                      # 作者自己放的
    "封面.jpg",                      # 同上，而 `.jpg` **是合法素材扩展名**
]


def _zip_with(tmp_path, name, names):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for entry in names:
            zf.writestr(entry, b"RIFF" + b"\0" * 32)
    return path


def test_junk_in_the_pack_does_not_cost_the_user_a_single_extra_question(tmp_path):
    """⭐⭐⭐ 这条判据量的就是**用户的验收标准**：问了几次。

    实测（改之前）：同一包枪声素材，加上上面那四样，
    **提问次数 0 → 4** —— `Thumbs.db` 混进去让那一组的形状从 `dir2/audio`
    变成 `dir2/mixed`，识别器当场降到"拿不准"；`说明.txt` 和 `封面.jpg`
    各自单独成一组，又各问一次。
    ⇒ 而这四样没有一样是用户"打算"导入的，四个问题**一个都没有正确答案**。
    """
    assets = ["AK47/默认/1.wav", "AK47/默认/2.wav", "M4A1/默认/1.wav"]

    def asked(path):
        source = open_source(str(path))
        try:
            groups = identify_groups(source.paths, source.display_name)
            return sum(1 for group in groups if group.needs_user)
        finally:
            source.cleanup()

    # ⚠ 包名要**真实**：零提问靠三条信号，包名词典是其中一条。
    #   第一版这里写的是 `干净.zip` / `现实.zip`，于是基线本身就是 1 次提问 ——
    #   ⭐ 判据用一个现实里不存在的包名，量到的就不是现实里的那个数。
    clean = asked(_zip_with(tmp_path, "AK47枪声替换包.zip", assets))
    real = asked(_zip_with(tmp_path, "AK47枪声替换包_v2.zip",
                           assets + REAL_WORLD_JUNK))
    assert clean == 0, f"连干净的包都要问 {clean} 次"
    assert real == clean, (
        f"带杂物的包多问了 {real - clean} 次 —— 而用户的标准就是这个数")


def test_junk_never_lands_in_the_resource_library(tmp_path):
    """⛔ 杂物也不许被**复制进去**。

    `Thumbs.db` 躺在 `audio/gun_sounds/AK47/默认/` 里不会让软件出错，
    但那是用户的资源库，不是回收站。
    """
    source = open_source(str(_zip_with(
        tmp_path, "现实.zip", ["AK47/默认/1.wav"] + REAL_WORLD_JUNK)))
    try:
        assert source.paths == ["AK47/默认/1.wav"]
    finally:
        source.cleanup()


def test_what_was_left_out_is_said_out_loud(tmp_path):
    """⭐ 摘出来的东西**必须报出来**。

    悄悄扔掉别人的文件，和悄悄把垃圾导进资源库是同一种毛病。
    ⚠ 两类分开：作者的附带文件点名（他可能想自己留着），
    系统临时文件只报个数（对它们没有任何决定要做）。
    """
    source = open_source(str(_zip_with(
        tmp_path, "现实.zip", ["AK47/默认/1.wav"] + REAL_WORLD_JUNK)))
    try:
        assert source.companions == ["封面.jpg", "说明.txt"]
        assert source.junk_count == 2, (
            f"`__MACOSX/._1.wav` 与 `Thumbs.db` 共 2 条，实得 {source.junk_count}")
    finally:
        source.cleanup()


def test_the_mac_metadata_folder_does_not_block_the_shell_strip(tmp_path):
    """⭐⭐ 顺序判据：垃圾必须在**剥壳之前**扔掉。

    Mac 打的包里 `__MACOSX/` 是和 `枪声包/` **并列的第二个顶层目录** ——
    留着它 `strip_single_root` 就认为"根不唯一"、整个外壳剥不掉，
    于是每条路径都多出一层，归类器再也对不上。
    ⇒ 这不是"顺手清理"，它决定了剥壳成不成。
    """
    source = open_source(str(_zip_with(tmp_path, "枪声包.zip", [
        "枪声包/AK47/默认/1.wav",
        "枪声包/AK47/默认/2.wav",
        "__MACOSX/枪声包/AK47/默认/._1.wav",
    ])))
    try:
        assert source.stripped_root == "枪声包", (
            f"外壳没剥掉（stripped_root={source.stripped_root!r}）—— "
            f"`__MACOSX/` 把它顶成了两个根")
        assert source.paths == ["AK47/默认/1.wav", "AK47/默认/2.wav"]
    finally:
        source.cleanup()


def test_a_lone_image_is_still_an_asset_not_a_cover(tmp_path):
    """⛔⛔ "平铺的图片算封面"这条规则**不许**把单张图片关在门外。

    用户单独拖一张击杀图标 `.png` 进来是最常见的用法之一 ——
    包里没有音频，那张图就是他要导的东西本身。
    ⭐ 所以"包里有音频"这个前提是那条规则的一半，去掉它就成了新缺陷。
    """
    one = tmp_path / "天使.png"
    one.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    source = open_source(str(one))
    try:
        assert source.paths == ["天使.png"]
        assert source.companions == []
    finally:
        source.cleanup()


def test_a_pack_with_nothing_importable_says_so_instead_of_importing_nothing(tmp_path):
    """⚠ 只有杂物的包要**说清楚**，而不是"导入成功、0 个文件"。"""
    only_junk = _zip_with(tmp_path, "空壳.zip", ["说明.txt", "__MACOSX/._说明.txt"])
    with pytest.raises(ImportSourceError) as caught:
        open_source(str(only_junk))
    assert "素材" in str(caught.value)


def test_a_dragged_folder_is_not_taxed_for_the_thumbnails_windows_left_in_it(tmp_path):
    """⛔ 用户把自己整理好的**文件夹**直接拖进来，不该因为系统留下的文件多挨一问。

    **只要用资源管理器看过一眼**那个目录，里面就会有 `Thumbs.db` / `desktop.ini`
    —— 而它们混进去会让那一组的形状从 `dir2/audio` 变成 `dir2/mixed`、
    识别器降到「拿不准」，凭空多问一次，且那个问题没有正确答案。

    ⚠ 这条判据必须用文件夹：压缩包那条路在**解压前**就滤过一遍垃圾，
    两处互相兜住 ⇒ 拿 zip 测的话，把 `split_entries` 那一遍整个撤掉也不会红。
    ⭐⭐ 回退验证就是这么把我另一条断点判成假绿的（同 RN-002：
    只要还有第二份副本，删掉一份也没有任何东西会红）。
    """
    folder = tmp_path / "AK47枪声替换包"
    inner = folder / "AK47" / "默认"
    inner.mkdir(parents=True)
    (inner / "1.wav").write_bytes(b"RIFF" + b"\0" * 32)
    (inner / "2.wav").write_bytes(b"RIFF" + b"\0" * 32)
    (inner / "Thumbs.db").write_bytes(b"\0" * 16)
    (folder / "desktop.ini").write_bytes(b"[.ShellClassInfo]")

    source = open_source(str(folder))
    try:
        assert source.paths == ["AK47/默认/1.wav", "AK47/默认/2.wav"], source.paths
        assert source.junk_count == 2
        groups = identify_groups(source.paths, source.display_name)
        asked = sum(1 for group in groups if group.needs_user)
        assert asked == 0, f"因为目录里的系统文件多问了 {asked} 次"
    finally:
        source.cleanup()
