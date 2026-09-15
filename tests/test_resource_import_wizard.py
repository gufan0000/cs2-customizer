# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""资源导入向导：识别支持的根目录 / 冲突跳过 / dry-run 不写盘。

⚠⚠ **批 80 从 `tests/test_audio_import_wizard.py` 搬过来的。**
那三个用例原先指着 `core/audio/audio_import_wizard.py` —— 而那份代码的功能
早已泛化搬家到 `core/resource_import_wizard.py`（多一个 `domain` 参数，
默认值就是 `"audio"`，所以调用方式一字不差），**旧文件从那天起零引用**。

⭐⭐⭐ **一个只测试死代码的测试，永远绿，而且让那段死代码看起来是活的。**
死码扫描把它报成「零引用模块」时，我差一点因为「它有单测」就放过它。
⇒ 搬过来之后：产品代码 **−248 行**，而这三件事第一次真的被测到了。
"""
from __future__ import annotations

from pathlib import Path

from core.resource_import_wizard import (
    apply_resource_import_plan,
    scan_resource_import_candidates,
)


def _write_audio_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-audio")


def test_scan_resource_import_candidates_recognizes_supported_roots(tmp_path):
    source_dir = tmp_path / "source"
    audio_root = tmp_path / "audio_root"

    _write_audio_file(source_dir / "packA" / "kill_sounds" / "default" / "1.wav")
    _write_audio_file(source_dir / "packB" / "switch_weapon" / "weapon_ak47" / "classic" / "switch.mp3")
    _write_audio_file(source_dir / "random" / "misc" / "effect.ogg")

    report = scan_resource_import_candidates(str(source_dir), str(audio_root))
    summary = report.get("summary", {})
    recognized = report.get("recognized", [])
    unrecognized = report.get("unrecognized", [])

    assert summary.get("scanned_resource_files") == 3
    assert summary.get("recognized_count") == 2
    assert summary.get("unrecognized_count") == 1
    assert len(recognized) == 2
    assert len(unrecognized) == 1

    rel_targets = {item["target_rel_path"] for item in recognized}
    # ⚠ 泛化成「资源」之后目标路径前面多一层 domain 目录（`audio/`）——
    #   这是有意的设计（同一套向导要放视觉资源）。
    assert "audio/kill_sounds\\default\\1.wav" in rel_targets
    assert "audio/switch_weapons\\weapon_ak47\\classic\\switch.mp3" in rel_targets


def test_apply_resource_import_plan_skips_conflicts_by_default(tmp_path):
    source_dir = tmp_path / "source"
    audio_root = tmp_path / "audio_root"

    src_a = source_dir / "kill_sounds" / "default" / "1.wav"
    src_b = source_dir / "kill_sounds" / "default" / "2.wav"
    _write_audio_file(src_a)
    _write_audio_file(src_b)

    # ⛔ 冲突文件必须放在**真实**目标路径上（含 domain 那一层）；
    #   放在旧路径上的话它谁也挡不着，而用例会绿着告诉你「冲突跳过没问题」。
    dst_conflict = audio_root / "audio" / "kill_sounds" / "default" / "1.wav"
    _write_audio_file(dst_conflict)

    report = scan_resource_import_candidates(str(source_dir), str(audio_root))
    result = apply_resource_import_plan(report, dry_run=False, overwrite_existing=False)
    summary = result.get("summary", {})

    assert summary.get("copied_count") == 1
    assert summary.get("skipped_conflicts_count") == 1
    assert summary.get("failed_count") == 0
    assert (audio_root / "audio" / "kill_sounds" / "default" / "2.wav").exists()


def test_apply_resource_import_plan_dry_run_does_not_write(tmp_path):
    source_dir = tmp_path / "source"
    audio_root = tmp_path / "audio_root"
    src = source_dir / "kill_voices" / "default" / "1.wav"
    _write_audio_file(src)

    report = scan_resource_import_candidates(str(source_dir), str(audio_root))
    result = apply_resource_import_plan(report, dry_run=True, overwrite_existing=False)
    summary = result.get("summary", {})

    assert summary.get("copied_count") == 1
    # ⭐⭐ 原来这里写的是不含 `audio/` 的旧路径 —— 那个文件**永远不存在**，
    #   于是这条断言恒真、这个用例从来没有测过 dry-run。
    assert not (audio_root / "audio" / "kill_voices" / "default" / "1.wav").exists()
