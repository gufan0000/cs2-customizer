# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R2-1 .cs2customizer 分享文件:往返、五条安全红线、schema v1/v2 兼容。"""
import json
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.presets.preset_center import SCHEMA_NAME, export_bundle, validate_bundle
from core.presets.share_file import (
    BUNDLE_NAME,
    MANIFEST_NAME,
    MAX_ENTRIES,
    read_share_file,
    write_share_file,
)


def _make_share(tmp_path, bundle=None, name="t.cs2customizer"):
    p = str(tmp_path / name)
    write_share_file(p, bundle or export_bundle(["crosshair", "flash"]), title="测试包", author="孤帆")
    return p


def test_roundtrip_export_import(tmp_path):
    p = _make_share(tmp_path)
    r = read_share_file(p)
    assert r.ok, r.errors
    types = {i["type"] for i in r.bundle["items"]}
    assert types == {"crosshair", "flash"}
    assert r.manifest["title"] == "测试包"
    assert validate_bundle(r.bundle).ok


def test_v2_bundle_contains_new_types():
    bundle = export_bundle(["crosshair", "flash", "viewmodel", "magnifier", "hud_rules"])
    assert bundle["schema_version"] == 2
    types = {i["type"] for i in bundle["items"]}
    assert {"crosshair", "flash", "viewmodel", "magnifier", "hud_rules"} <= types
    # 准心 payload 必须带自定义画点数据
    cross = next(i for i in bundle["items"] if i["type"] == "crosshair")
    assert "crosshair_custom_data" in cross["payload"]


def test_v1_file_still_accepted(tmp_path):
    v1 = {
        "schema": SCHEMA_NAME,
        "schema_version": 1,
        "items": [{"type": "screen_effects", "payload": {"screen_effects_enabled": True}}],
    }
    p = str(tmp_path / "v1.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(BUNDLE_NAME, json.dumps(v1))
    r = read_share_file(p)
    assert r.ok, r.errors


def test_redline_path_traversal_rejected(tmp_path):
    p = str(tmp_path / "evil.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(BUNDLE_NAME, json.dumps(export_bundle(["crosshair"])))
        zf.writestr("../../evil.json", "{}")
    r = read_share_file(p)
    assert not r.ok
    assert any("穿越" in e for e in r.errors)


def test_redline_executable_rejected(tmp_path):
    p = str(tmp_path / "exe.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(BUNDLE_NAME, json.dumps(export_bundle(["crosshair"])))
        zf.writestr("resources/payload.exe", b"MZ")
    r = read_share_file(p)
    assert not r.ok
    assert any("扩展名" in e for e in r.errors)


def test_redline_absolute_path_rejected(tmp_path):
    p = str(tmp_path / "abs.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(BUNDLE_NAME, json.dumps(export_bundle(["crosshair"])))
        zf.writestr("/etc/passwd.json", "{}")
    r = read_share_file(p)
    assert not r.ok


def test_redline_entry_count(tmp_path):
    p = str(tmp_path / "many.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(BUNDLE_NAME, json.dumps(export_bundle(["crosshair"])))
        for i in range(MAX_ENTRIES + 1):
            zf.writestr(f"r/{i}.json", "{}")
    r = read_share_file(p)
    assert not r.ok
    assert any("条目数" in e for e in r.errors)


def test_redline_invalid_bundle_rejected(tmp_path):
    p = str(tmp_path / "bad.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(BUNDLE_NAME, json.dumps({"schema": "evil", "schema_version": 99, "items": []}))
    r = read_share_file(p)
    assert not r.ok
    assert any("校验失败" in e for e in r.errors)


def test_not_a_zip_rejected(tmp_path):
    p = str(tmp_path / "junk.cs2customizer")
    with open(p, "wb") as f:
        f.write(b"this is not a zip at all")
    r = read_share_file(p)
    assert not r.ok


def test_missing_bundle_rejected(tmp_path):
    p = str(tmp_path / "nobundle.cs2customizer")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(MANIFEST_NAME, "{}")
    r = read_share_file(p)
    assert not r.ok
    assert any("bundle" in e for e in r.errors)
