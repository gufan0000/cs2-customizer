# -*- coding: utf-8 -*-
"""B3 资源迁移标志单元测试。

保证：
1. 无标志文件 → 应该走完整迁移
2. 标志文件存在且版本匹配且关键文件齐全 → 应跳过
3. schema 不匹配 → 应强制完整迁移（本迁移逻辑自身升级场景）
4. 版本不匹配 → 应强制完整迁移（应用版本升级场景）
5. 关键文件被手动删除 → 应强制完整迁移（用户清空 AppData 场景）
6. 标志文件损坏（非 JSON）→ 应强制完整迁移
7. 写入失败时主流程不受影响
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import resource_manager as rm  # noqa: E402
from resource_manager import (  # noqa: E402
    MIGRATION_CRITICAL_FILES,
    MIGRATION_MARKER_FILENAME,
    MIGRATION_MARKER_SCHEMA,
    ResourceManager,
)


class _TmpAppData:
    """临时 AppData 目录上下文，自动 patch get_app_data_dir。"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = self._tmp.name
        self._patcher = patch("resource_manager.get_app_data_dir", return_value=self.path)

    def __enter__(self):
        self._patcher.start()
        return self.path

    def __exit__(self, *exc):
        self._patcher.stop()
        self._tmp.cleanup()


def _prepare_critical_files(app_data: str) -> None:
    for rel in MIGRATION_CRITICAL_FILES:
        full = os.path.join(app_data, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"x")


def _write_marker(app_data: str, payload: dict) -> None:
    path = os.path.join(app_data, MIGRATION_MARKER_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


class TestMigrationMarker(unittest.TestCase):
    def test_no_marker_means_run_full(self):
        with _TmpAppData():
            self.assertFalse(ResourceManager._should_skip_migration())

    def test_matching_marker_with_critical_files_skips(self):
        with _TmpAppData() as app:
            _prepare_critical_files(app)
            _write_marker(app, {"schema": MIGRATION_MARKER_SCHEMA, "version": rm.VERSION})
            self.assertTrue(ResourceManager._should_skip_migration())

    def test_schema_mismatch_forces_full(self):
        with _TmpAppData() as app:
            _prepare_critical_files(app)
            _write_marker(app, {"schema": MIGRATION_MARKER_SCHEMA + 99, "version": rm.VERSION})
            self.assertFalse(ResourceManager._should_skip_migration())

    def test_version_mismatch_forces_full(self):
        with _TmpAppData() as app:
            _prepare_critical_files(app)
            _write_marker(app, {"schema": MIGRATION_MARKER_SCHEMA, "version": "0.0.0-old"})
            self.assertFalse(ResourceManager._should_skip_migration())

    def test_missing_critical_file_forces_full(self):
        with _TmpAppData() as app:
            # 写标志但不建关键文件
            _write_marker(app, {"schema": MIGRATION_MARKER_SCHEMA, "version": rm.VERSION})
            self.assertFalse(ResourceManager._should_skip_migration())

    def test_corrupt_marker_forces_full(self):
        with _TmpAppData() as app:
            _prepare_critical_files(app)
            path = os.path.join(app, MIGRATION_MARKER_FILENAME)
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not valid json")
            self.assertFalse(ResourceManager._should_skip_migration())

    def test_write_marker_creates_file_and_includes_version(self):
        with _TmpAppData() as app:
            ResourceManager._write_migration_marker()
            path = os.path.join(app, MIGRATION_MARKER_FILENAME)
            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["schema"], MIGRATION_MARKER_SCHEMA)
            self.assertEqual(data["version"], rm.VERSION)
            self.assertIn("timestamp", data)

    def test_write_marker_failure_silent(self):
        # patch os.makedirs 抛异常，_write_migration_marker 不应抛
        with _TmpAppData():
            with patch("resource_manager.os.makedirs", side_effect=PermissionError("x")):
                try:
                    ResourceManager._write_migration_marker()
                except Exception as e:  # pragma: no cover
                    self.fail(f"_write_migration_marker 应静默，实际抛: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
