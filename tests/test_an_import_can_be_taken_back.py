# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""导入要能收回来，失败要自己收干净，问过的不要再问（2026-09-16）。

## 这三条是核对设计文档时发现自己没做的

设计方案 v1 的第 2 / 5 节白纸黑字写着「页内提示条 + **可撤销**」、
「失败**整体回滚**」、「**选完就记住**，同样形状下次不再问」——
而三条一条都没实现。⭐⭐ **自己写的设计文档也会腐烂**，
而它腐烂的方式是「写完就当它已经做了」。

## 三条各自守什么

| 条 | 不做的后果 |
|---|---|
| 失败回滚 | **半套素材留在资源库**，用户看到一个只有三分之一文件的风格，不会知道那是失败的残骸 |
| 撤销 | 导错了只能自己开资源目录去删，而他不知道刚才那一次放了哪些文件 |
| 学习表 | 同一个作者的包每次都要答一遍，玩家会觉得这软件没记性 |

（本项目测试逐文件跑：
 `python -m pytest tests/test_an_import_can_be_taken_back.py`）
"""
from __future__ import annotations

import os

import pytest

from core.resource_identify import UNSURE, _candidates_for_shape, identify_groups
from core.resource_import_wizard import apply_resource_import_plan, undo_import


def _plan(tmp_path, names):
    """造一个最小的落盘计划：几个源文件 + 它们的目标位置。"""
    source_dir = tmp_path / "src"
    source_dir.mkdir(exist_ok=True)
    resources = tmp_path / "res"
    resources.mkdir(exist_ok=True)
    recognized = []
    for name in names:
        src = source_dir / name
        src.write_bytes(b"RIFF" + b"\0" * 16)
        target = resources / "audio" / "kill_sounds" / "清脆" / name
        recognized.append({
            "source_path": str(src),
            "target_rel_path": f"audio/kill_sounds/清脆/{name}",
            "target_abs_path": str(target),
            "spec_key": "kill_sounds",
            "spec_label": "击杀音效",
            "domain": "audio",
            "conflict": False,
        })
    return {"recognized": recognized}, resources


def _landed(root):
    found = []
    for walk_root, _dirs, files in os.walk(str(root)):
        for name in files:
            found.append(os.path.relpath(os.path.join(walk_root, name), str(root)))
    return sorted(path.replace("\\", "/") for path in found)


# ---------------------------------------------------------------- 撤销

def test_an_import_can_be_taken_back_completely(tmp_path):
    report, resources = _plan(tmp_path, ["1.mp3", "2.mp3"])
    result = apply_resource_import_plan(report, dry_run=False)
    assert len(_landed(resources)) == 2

    outcome = undo_import(result)
    assert outcome["summary"]["removed_count"] == 2
    assert _landed(resources) == [], "撤销之后资源目录里还有东西"


def test_undo_also_takes_the_empty_folders_it_made(tmp_path):
    """⭐ 只删文件会留下一串空目录，而设置页把空的风格目录当成一个风格列出来。"""
    report, resources = _plan(tmp_path, ["1.mp3"])
    result = apply_resource_import_plan(report, dry_run=False)
    style_dir = resources / "audio" / "kill_sounds" / "清脆"
    assert style_dir.is_dir()
    undo_import(result)
    assert not style_dir.exists(), "空的风格目录留下了，设置页会把它当成一个风格"


def test_undo_never_touches_what_it_did_not_write(tmp_path):
    """⛔ 冲突跳过的那些**本来就没写进去** —— 删了就是删用户的旧素材。"""
    report, resources = _plan(tmp_path, ["1.mp3"])
    victim = resources / "audio" / "kill_sounds" / "清脆" / "老素材.mp3"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_bytes("这是用户自己的东西".encode("utf-8"))

    result = apply_resource_import_plan(report, dry_run=False)
    undo_import(result)
    assert victim.exists(), "撤销把用户原来就有的素材也删了"
    assert victim.read_bytes() == "这是用户自己的东西".encode("utf-8")


def test_undoing_twice_is_harmless(tmp_path):
    report, _resources = _plan(tmp_path, ["1.mp3"])
    result = apply_resource_import_plan(report, dry_run=False)
    undo_import(result)
    again = undo_import(result)
    assert again["summary"]["ok"], "第二次撤销报错了 —— 用户连点两下就会看到一个假错误"


# ---------------------------------------------------------------- 失败回滚

def test_a_partial_failure_rolls_the_whole_thing_back(tmp_path):
    """⭐⭐ **半套素材留在资源库里比什么都没导进去更难收拾** ——
    用户看到设置页多出一个只有三分之一文件的风格，不会知道那是失败的残骸。"""
    report, resources = _plan(tmp_path, ["1.mp3", "2.mp3", "3.mp3"])
    # 第三条指向一个不可能写成功的位置（父路径是个文件）
    blocker = tmp_path / "res" / "blocked"
    blocker.write_bytes(b"x")
    report["recognized"][2]["target_abs_path"] = str(blocker / "3.mp3")

    result = apply_resource_import_plan(report, dry_run=False)
    assert result["summary"]["failed_count"] >= 1
    assert result["rollback"]["rolled_back"] is True
    assert _landed(resources) == ["blocked"], (
        f"失败之后资源目录里留下了半套素材：{_landed(resources)}"
    )


def test_a_dry_run_never_rolls_back_because_it_never_wrote(tmp_path):
    report, _resources = _plan(tmp_path, ["1.mp3"])
    result = apply_resource_import_plan(report, dry_run=True)
    assert result["rollback"]["rolled_back"] is False


# ---------------------------------------------------------------- 学习表

def test_a_remembered_ambiguous_shape_is_preselected_but_still_asked():
    """⛔⛔ 2026-09-17 改判：记住了**也还是要问**，除非这个形状只可能是一类。

    旧判据钉的是「记住 ⇒ 不再问」，而那条规则**在原理上就不成立**：
    实测 `清脆/1.mp3`（击杀音效）、`残血/1.mp3`（血量警告）、
    `默认/1.mp3`（切枪音效）**形状指纹全是 `dir1/audio`** —— 一个指纹底下
    坐着七类。于是用户为第一个包答过一次「击杀音效」之后，
    **之后每一个同形状的包都被无声地归成击杀音效**，
    而他是在设置页里找不到自己的血量警告时才发现的。

    ⭐⭐⭐ 这正是本功能的前提事实（12 类音频共用扩展名、5 类连结构都一样）
    被自己的学习表违反了一次 —— **省一次点击，不值得拿"静默归错"去换。**
    ⇒ 分两档：形状唯一才照办；形状含糊就**预选在第一位**，还是问一次。
    """
    paths = ["AK47/默认/1.wav", "M4A1/默认/1.wav"]
    fresh = identify_groups(paths, source_name="素材.zip")
    assert fresh[0].confidence == UNSURE
    assert fresh[0].needs_user

    shape = fresh[0].shape
    learned = identify_groups(paths, source_name="另一个包.zip",
                              memory={shape: "switch_weapons"})[0]
    assert learned.needs_user, (
        f"`{shape}` 这个形状底下不止一类，记住了也不许替用户定 —— "
        f"候选：{_candidates_for_shape(shape)}")
    assert learned.remembered == "switch_weapons", (
        "还是要问，但上次的答案必须预选好，否则「记住」这件事对用户没有意义")
    assert learned.guesses[0].spec_key == "switch_weapons", "记住的那个要排第一"


def test_a_remembered_unambiguous_shape_is_not_asked_again():
    """⭐ 形状只可能是一类时，「记住 ⇒ 不再问」才成立。"""
    paths = ["我的准星.xchr"]
    shape = identify_groups(paths, source_name="素材.zip")[0].shape
    assert len(_candidates_for_shape(shape)) <= 1, (
        f"这条判据挑的形状 `{shape}` 必须是唯一候选的，否则它测的不是这件事")
    group = identify_groups(paths, source_name="素材.zip",
                            memory={shape: "crosshair"})[0]
    assert not group.needs_user


def test_the_remembered_choice_says_it_is_remembered():
    """⭐ 照上次办可以，但要**看得见** —— 无声地照办和无声地猜一样糟。"""
    paths = ["AK47/默认/1.wav"]
    shape = identify_groups(paths, source_name="素材.zip")[0].shape
    group = identify_groups(paths, source_name="素材.zip",
                            memory={shape: "reload_sounds"})[0]
    assert any("上次" in line for line in group.guesses[0].evidence), \
        group.guesses[0].evidence


def test_a_remembered_category_that_no_longer_exists_is_ignored():
    """⛔ 学习表是**存过盘的旧数据**，里面可能有早已删掉的类别名。
    ⭐ 失效方向朝"重新问一次"倒，不朝"照着一个不存在的类别办"倒。"""
    paths = ["AK47/默认/1.wav"]
    shape = identify_groups(paths, source_name="素材.zip")[0].shape
    group = identify_groups(paths, source_name="素材.zip",
                            memory={shape: "早就没有的类别"})[0]
    assert group.confidence == UNSURE
    assert group.needs_user


@pytest.mark.parametrize("junk", [None, "不是字典", 123, []])
def test_a_broken_memory_table_does_not_break_the_import(junk):
    groups = identify_groups(["AK47/默认/1.wav"], source_name="素材.zip",
                             memory=junk)
    assert groups, "学习表坏了就把整个识别带崩了"


def test_a_certain_group_is_not_overridden_by_memory():
    """⛔ 路径里明写着类目录名的，学习表不许顶掉它 ——
    ⭐ **用户这一次写在包里的东西，永远比他上一次的选择新。**"""
    group = identify_groups(["kill_sounds/清脆/1.mp3"], source_name="x.zip",
                            memory={"dir2/audio": "gun_sounds"})[0]
    assert group.preselect.spec_key == "kill_sounds"
