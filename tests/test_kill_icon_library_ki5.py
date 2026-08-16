# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-5：风格库的清单与可撤销删除。

KI-5 之前这一块是**空的**：导入即覆盖，没有确认、没有备份、没有"删掉这一个
等级"、没有"恢复默认"。手滑把 ACE 的素材导到 1 杀上，只能再找一份原素材导
回去——如果原素材已经找不到了，那就没了。

页面那头同样没法回答"这套风格到底有哪几个等级"：唯一的信号是"时长滑条被
禁掉了"，用户得靠猜。
"""
from __future__ import annotations

import json
import os

import pytest

from core.kill_icon_library import (
    TRASH_DIRNAME,
    TRASH_KEEP,
    delete_level,
    level_entry,
    list_style_levels,
    purge_trash,
    restore_level,
    style_summary,
    trash_root,
)


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


@pytest.fixture
def manager(tmp_path):
    return _FakeResourceManager(tmp_path)


def _make_sheet(manager, style, kills, variant="", frames=12, fps=24, hold=0.0):
    sprite, meta = manager.get_kill_icon_sprite_sheet_paths(style, kills, variant)
    os.makedirs(os.path.dirname(sprite), exist_ok=True)
    with open(sprite, "wb") as handle:
        handle.write(b"\x89PNG fake")
    with open(meta, "w", encoding="utf-8") as handle:
        json.dump({"frame_width": 20, "frame_height": 16, "frames": frames,
                   "cols": frames, "rows": 1, "fps": fps, "hold_seconds": hold},
                  handle)
    return sprite, meta


def _make_legacy(manager, style, kills, frames=5):
    directory = manager.root / "kill_icons" / style / str(kills)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        (directory / f"{index + 1}.png").write_bytes(b"\x89PNG fake")
    return directory


# ==================================================== 1. 清单


def test_inventory_reports_what_is_there_without_decoding_anything(manager):
    """清单要跑在建页路径上，所以只读 JSON 和目录项，一个像素都不解。"""
    _make_sheet(manager, "风格", 1, frames=30, fps=15)
    _make_sheet(manager, "风格", 1, variant="hs", frames=8)
    _make_legacy(manager, "风格", 4, frames=7)

    entries = {(e.kills, e.variant): e for e in list_style_levels("风格", manager)}
    assert entries[(1, "")].kind == "sheet"
    assert entries[(1, "")].frames == 30
    assert entries[(1, "")].duration == pytest.approx(2.0)
    assert entries[(1, "hs")].exists is True
    assert entries[(4, "")].kind == "legacy"
    assert entries[(4, "")].frames == 7
    assert entries[(2, "")].exists is False
    assert entries[(4, "hs")].exists is False, "变体只认图集，不许往逐帧目录上兜"


def test_duration_includes_the_hold(manager):
    _make_sheet(manager, "风格", 1, frames=1, fps=30, hold=1.5)
    entry = level_entry("风格", 1, resource_manager=manager)
    assert entry.duration == pytest.approx(1.5 + 1 / 30.0)


def test_summary_says_which_levels_are_missing(manager):
    """"这套风格还差什么"要一眼看得见——KI-5 之前只能靠滑条被禁掉去猜。"""
    _make_sheet(manager, "风格", 1)
    _make_sheet(manager, "风格", 3)
    _make_sheet(manager, "风格", 3, variant="hs")

    summary = style_summary("风格", manager)
    assert summary["levels"] == [1, 3]
    assert summary["missing"] == [2, 4, 5]
    assert summary["headshot_levels"] == [3]


# ==================================================== 2. 可撤销的删除


def test_delete_moves_to_the_trash_instead_of_really_deleting(manager):
    """删错了的代价是"用户手上那份原素材可能已经没了"。

    而这一步是在页面上点一下就能触发的，所以它必须是可撤销的。
    """
    sprite, meta = _make_sheet(manager, "风格", 2)
    token = delete_level("风格", 2, resource_manager=manager)

    assert token and os.path.isdir(token)
    assert not os.path.exists(sprite) and not os.path.exists(meta)
    assert level_entry("风格", 2, resource_manager=manager).exists is False
    assert os.path.isfile(os.path.join(token, "restore.json"))


def test_restore_puts_it_back_byte_for_byte(manager):
    sprite, _meta = _make_sheet(manager, "风格", 2)
    original = open(sprite, "rb").read()

    token = delete_level("风格", 2, resource_manager=manager)
    assert restore_level(token, resource_manager=manager) is True

    assert open(sprite, "rb").read() == original
    assert level_entry("风格", 2, resource_manager=manager).frames == 12
    assert not os.path.exists(token), "撤销之后回收站那一格应当清掉"


def test_restore_refuses_to_clobber_a_newer_asset(manager):
    """删完又导了一份新的，这时撤销不能把新的盖掉。"""
    _make_sheet(manager, "风格", 2, frames=12)
    token = delete_level("风格", 2, resource_manager=manager)
    _make_sheet(manager, "风格", 2, frames=99)

    assert restore_level(token, resource_manager=manager) is False
    assert level_entry("风格", 2, resource_manager=manager).frames == 99


def test_legacy_frame_directories_can_be_deleted_and_restored(manager):
    directory = _make_legacy(manager, "老风格", 3, frames=4)
    token = delete_level("老风格", 3, resource_manager=manager)

    assert token
    assert not directory.exists()
    assert restore_level(token, resource_manager=manager) is True
    assert directory.is_dir()
    assert level_entry("老风格", 3, resource_manager=manager).frames == 4


def test_deleting_nothing_returns_none(manager):
    assert delete_level("风格", 5, resource_manager=manager) is None


def test_trash_lives_under_a_dot_directory_so_it_is_not_a_style(manager):
    """回收站不能冒充成一套风格出现在下拉里。"""
    _make_sheet(manager, "风格", 1)
    delete_level("风格", 1, resource_manager=manager)
    assert os.path.basename(trash_root(manager)) == TRASH_DIRNAME
    assert TRASH_DIRNAME.startswith(".")


def test_trash_is_capped(manager):
    """撤销是"刚刚手滑了"的兜底，不是版本管理——无限堆着只会吃光磁盘。"""
    for index in range(TRASH_KEEP + 4):
        _make_sheet(manager, "风格", 1)
        delete_level("风格", 1, resource_manager=manager)

    purge_trash(resource_manager=manager)
    slots = os.listdir(trash_root(manager))
    assert len(slots) <= TRASH_KEEP


def test_library_module_stays_free_of_qt_and_pil():
    """结构性判据：清单要在建页路径上跑，也要能在离屏判据里裸跑。"""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent /
              "core" / "kill_icon_library.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PySide6" not in imported
    assert "PIL" not in imported
