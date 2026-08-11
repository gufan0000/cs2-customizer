from __future__ import annotations

from pathlib import Path

from core.audio.audio_import_wizard import (
    apply_audio_import_plan,
    scan_audio_import_candidates,
)


def _write_audio_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-audio")


def test_scan_audio_import_candidates_recognizes_supported_roots(tmp_path):
    source_dir = tmp_path / "source"
    audio_root = tmp_path / "audio_root"

    _write_audio_file(source_dir / "packA" / "kill_sounds" / "default" / "1.wav")
    _write_audio_file(source_dir / "packB" / "switch_weapon" / "weapon_ak47" / "classic" / "switch.mp3")
    _write_audio_file(source_dir / "random" / "misc" / "effect.ogg")

    report = scan_audio_import_candidates(str(source_dir), str(audio_root))
    summary = report.get("summary", {})
    recognized = report.get("recognized", [])
    unrecognized = report.get("unrecognized", [])

    assert summary.get("scanned_audio_files") == 3
    assert summary.get("recognized_count") == 2
    assert summary.get("unrecognized_count") == 1
    assert len(recognized) == 2
    assert len(unrecognized) == 1

    rel_targets = {item["target_rel_path"] for item in recognized}
    assert "kill_sounds\\default\\1.wav" in rel_targets
    assert "switch_weapons\\weapon_ak47\\classic\\switch.mp3" in rel_targets


def test_apply_audio_import_plan_skips_conflicts_by_default(tmp_path):
    source_dir = tmp_path / "source"
    audio_root = tmp_path / "audio_root"

    src_a = source_dir / "kill_sounds" / "default" / "1.wav"
    src_b = source_dir / "kill_sounds" / "default" / "2.wav"
    _write_audio_file(src_a)
    _write_audio_file(src_b)

    dst_conflict = audio_root / "kill_sounds" / "default" / "1.wav"
    _write_audio_file(dst_conflict)

    report = scan_audio_import_candidates(str(source_dir), str(audio_root))
    result = apply_audio_import_plan(report, dry_run=False, overwrite_existing=False)
    summary = result.get("summary", {})

    assert summary.get("copied_count") == 1
    assert summary.get("skipped_conflicts_count") == 1
    assert summary.get("failed_count") == 0
    assert (audio_root / "kill_sounds" / "default" / "2.wav").exists()


def test_apply_audio_import_plan_dry_run_does_not_write(tmp_path):
    source_dir = tmp_path / "source"
    audio_root = tmp_path / "audio_root"
    src = source_dir / "kill_voices" / "default" / "1.wav"
    _write_audio_file(src)

    report = scan_audio_import_candidates(str(source_dir), str(audio_root))
    result = apply_audio_import_plan(report, dry_run=True, overwrite_existing=False)
    summary = result.get("summary", {})

    assert summary.get("copied_count") == 1
    assert not (audio_root / "kill_voices" / "default" / "1.wav").exists()
