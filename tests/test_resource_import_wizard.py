# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
from pathlib import Path

from core.resource_import_wizard import (
    apply_resource_import_plan,
    scan_resource_import_candidates,
)


def _write_file(path: Path, content: bytes = b"resource"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_scan_resource_import_candidates_visual_mode_recognizes_visual_roots(tmp_path):
    source_dir = tmp_path / "source"
    resources_root = tmp_path / "resources"

    _write_file(source_dir / "packA" / "flash_images" / "style1" / "frame.png")
    _write_file(source_dir / "packB" / "kill_icons" / "default" / "1.json", b"{}")
    _write_file(source_dir / "packC" / "crosshair" / "my_crosshair.xchr")
    _write_file(source_dir / "packD" / "kill_sounds" / "default" / "1.wav")

    report = scan_resource_import_candidates(str(source_dir), str(resources_root), domain="visual")
    summary = report.get("summary", {})
    recognized = report.get("recognized", [])

    assert report.get("domain") == "visual"
    assert summary.get("scanned_resource_files") == 4
    assert summary.get("recognized_count") == 3
    assert summary.get("unrecognized_count") == 1
    assert {item["spec_key"] for item in recognized} == {"flash_images", "kill_icons", "crosshair"}
    assert {
        item["target_rel_path"] for item in recognized
    } == {
        os.path.join("flash_images", "style1", "frame.png"),
        os.path.join("kill_icons", "default", "1.json"),
        os.path.join("crosshair", "my_crosshair.xchr"),
    }


def test_scan_resource_import_candidates_all_mode_tracks_conflicts(tmp_path):
    source_dir = tmp_path / "source"
    resources_root = tmp_path / "resources"

    _write_file(source_dir / "kill_sounds" / "default" / "1.wav")
    _write_file(source_dir / "flash_audio" / "style1" / "flash.wav")
    _write_file(resources_root / "flash_audio" / "style1" / "flash.wav")

    report = scan_resource_import_candidates(str(source_dir), str(resources_root), domain="all")
    summary = report.get("summary", {})
    recognized = report.get("recognized", [])

    assert report.get("domain") == "all"
    assert summary.get("scanned_resource_files") == 2
    assert summary.get("recognized_count") == 2
    assert summary.get("conflict_count") == 1
    assert summary.get("importable_count") == 1
    assert {item["domain"] for item in recognized} == {"audio", "visual"}
    assert any(item["conflict"] for item in recognized if item["spec_key"] == "flash_audio")


def test_apply_resource_import_plan_dry_run_preserves_domain_metadata(tmp_path):
    source_dir = tmp_path / "source"
    resources_root = tmp_path / "resources"

    _write_file(source_dir / "kill_sounds" / "default" / "1.wav")
    _write_file(source_dir / "flash_images" / "styleA" / "preview.png")

    report = scan_resource_import_candidates(str(source_dir), str(resources_root), domain="all")
    result = apply_resource_import_plan(report, dry_run=True, overwrite_existing=False)

    copied = result.get("copied", [])
    summary = result.get("summary", {})

    assert summary.get("copied_count") == 2
    assert summary.get("failed_count") == 0
    assert {item["domain"] for item in copied} == {"audio", "visual"}
    assert not (resources_root / "kill_sounds" / "default" / "1.wav").exists()
    assert not (resources_root / "flash_images" / "styleA" / "preview.png").exists()
