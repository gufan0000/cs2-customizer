from __future__ import annotations


from core.backup import release_backup


def test_release_backup_create_list_verify(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    (project_root / "core").mkdir(parents=True, exist_ok=True)
    (project_root / "resources" / "audio").mkdir(parents=True, exist_ok=True)
    (project_root / "core" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (project_root / "resources" / "audio" / "a.mp3").write_bytes(b"audio")
    (project_root / "build").mkdir(parents=True, exist_ok=True)
    (project_root / "build" / "skip.bin").write_bytes(b"skip")

    backup_home = tmp_path / "backup_home"
    backup_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(release_backup, "get_config_dir", lambda: str(backup_home))

    created = release_backup.create_release_backup("test", str(project_root), max_keep=5)
    assert created["file_count"] == 2

    listed = release_backup.list_release_backups()
    assert listed
    backup_id = listed[0]["backup_id"]

    verified = release_backup.verify_backup(backup_id)
    assert verified["ok"] is True
    assert verified["checked_files"] == 2

