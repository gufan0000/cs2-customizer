# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path

from core import config_snapshot_manager as snap_mod


def test_snapshot_create_list_restore_prune(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({"a": 1}, ensure_ascii=False), encoding="utf-8")

    class _CfgObj:
        def __init__(self):
            self.loaded = False

        def save_config_now(self):
            return None

        def load_config(self):
            self.loaded = True

    cfg_obj = _CfgObj()
    monkeypatch.setattr(snap_mod, "config", cfg_obj)
    monkeypatch.setattr(snap_mod, "get_config_dir", lambda: str(cfg_dir))
    monkeypatch.setattr(snap_mod, "get_config_path", lambda: str(cfg_file))

    snap1 = snap_mod.create_snapshot("test1")
    assert snap1.snapshot_id
    assert Path(snap1.file_path).exists()

    cfg_file.write_text(json.dumps({"a": 2}, ensure_ascii=False), encoding="utf-8")
    snap2 = snap_mod.create_snapshot("test2")
    assert snap2.snapshot_id != snap1.snapshot_id

    items = snap_mod.list_snapshots()
    assert len(items) >= 2

    restored = snap_mod.restore_snapshot(snap1.snapshot_id)
    assert restored.ok is True
    assert cfg_obj.loaded is True

    removed = snap_mod.prune_snapshots(max_keep=1)
    assert removed >= 1

