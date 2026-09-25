# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 117（对标补课）：素材进出不丢东西、不撑爆。

- 拖进好几个 zip 只装第一个、其余**既不导入也不提示**（混在里面的单个素材同样静默丢掉）；
- 导出把作者剥掉（调用点三个参数一个都没传），导入读到的作者 / license.txt 不落盘 ⇒
  CS2 Customizer 是这条互通链上的**署名剥离器**；
- 写完 zip 不验一遍；
- 缺 `cols` 时运行时按「图集宽 ÷ 帧宽」、导入却按 `cols or 1` —— 同一份文件两个答案；原样搬运不设帧数上限；
- 缩放只夹比例不夹内存，而默认风格 150% 已常驻 475MB。
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

from core.kill_icon_import import KillIconImportError, convert_to_style, probe_source
from core.kill_icon_pack import PACK_VERSION, export_pack, import_pack, read_style_meta
from kill_icon_overlay import (SCALED_MEMORY_BUDGET, capped_scale, compute_scaled_size,
                               sheet_columns)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


class _RM:
    def __init__(self, root):
        self.root = root

    def get_kill_icon_sprite_sheet_paths(self, style_name, kills, variant=""):
        d = self.root / "kill_icons" / style_name
        return str(d / f"{kills}{variant}.png"), str(d / f"{kills}{variant}.json")

    def get_kill_icon_legacy_frames_dir(self, style_name, kills):
        c = self.root / "kill_icons" / style_name / str(kills)
        return str(c) if c.is_dir() else None

    def get_kill_icon_metadata_path(self, style_name, kills):
        return str(self.root / "kill_icons" / style_name / f"{kills}.json")

    def get_app_data_path(self, relative):
        return str(self.root / relative.replace("/", os.sep))


def _sheet_png(frames=3, size=16):
    from io import BytesIO
    image = Image.new("RGBA", (size * frames, size), (0, 0, 0, 0))
    for i in range(frames):
        image.paste(Image.new("RGBA", (size, size), (i + 1, 0, 0, 255)), (i * size, 0))
    buf = BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def _pack(path, name="霓虹", author="某位作者", license_text=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("style.json", json.dumps({"pack_version": PACK_VERSION, "name": name,
                                             "author": author, "version": "2.1", "description": "说明"}))
        for k in (1, 2):
            z.writestr(f"{k}.png", _sheet_png())
            z.writestr(f"{k}.json", json.dumps({"frame_width": 16, "frame_height": 16, "frames": 3,
                                                "cols": 3, "rows": 1, "fps": 20, "version": 1}))
        if license_text:
            z.writestr("LICENSE.txt", license_text)
    return path


# ──────────────────────────── 署名跟着包走 ────────────────────────────

def test_the_author_and_license_survive_an_import_export_round_trip(tmp_path):
    rm = _RM(tmp_path / "lib")
    src = _pack(tmp_path / "in.zip", license_text="CC BY 4.0 · 某位作者")
    import_pack(src, resource_manager=rm)
    assert read_style_meta("霓虹", rm).get("author") == "某位作者", "导入读到的作者没落盘"

    out = tmp_path / "out.zip"
    export_pack("霓虹", out, resource_manager=rm)          # 调用点不传作者（和工坊没问时一样）
    with zipfile.ZipFile(out) as z:
        manifest = json.loads(z.read("style.json").decode("utf-8"))
        names = set(z.namelist())
    assert manifest["author"] == "某位作者" and manifest["version"] == "2.1", manifest
    assert "license.txt" in names, f"授权文件在转手时丢了：{sorted(names)}"


def test_an_explicit_author_still_wins(tmp_path):
    rm = _RM(tmp_path / "lib")
    import_pack(_pack(tmp_path / "in.zip"), resource_manager=rm)
    out = tmp_path / "out.zip"
    export_pack("霓虹", out, author="我", resource_manager=rm)
    with zipfile.ZipFile(out) as z:
        assert json.loads(z.read("style.json").decode("utf-8"))["author"] == "我"


def test_a_broken_archive_never_replaces_the_old_file(tmp_path, monkeypatch):
    """写完重开校验：坏了就放弃，旧文件原样留着。"""
    rm = _RM(tmp_path / "lib")
    import_pack(_pack(tmp_path / "in.zip"), resource_manager=rm)
    out = tmp_path / "out.zip"
    out.write_bytes(b"old")
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "1.png")
    with pytest.raises(KillIconImportError):
        export_pack("霓虹", out, resource_manager=rm)
    assert out.read_bytes() == b"old", "校验不过还是把旧文件换掉了"


# ──────────────────────────── 拖进好几个 zip ────────────────────────────

@pytest.fixture()
def page(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    import pages.kill_icon_page as page_module

    QApplication.instance() or QApplication([])
    p = page_module.KillIconPage()
    ran = {}

    def run_now(fn, label):
        ran["label"] = label
        result = fn(lambda *a: None, lambda: False)
        p._describe_result_seen = p._describe_result(result)
        ran["result"] = result
        return True

    monkeypatch.setattr(p, "_run_import", run_now)
    p._ran = ran
    yield p
    p.deleteLater()


def test_every_dragged_zip_is_imported_and_each_one_is_reported(page, monkeypatch, tmp_path):
    import core.kill_icon_pack as pack_module

    seen = []

    def fake_import(path, **_kw):
        seen.append(os.path.basename(str(path)))
        if "坏" in str(path):
            raise KillIconImportError("这个 zip 打不开")
        return {"style": os.path.basename(str(path))[:-4], "levels": [(1, "")], "author": ""}

    monkeypatch.setattr(pack_module, "import_pack", fake_import)
    page._import_paths([str(tmp_path / "甲.zip"), str(tmp_path / "坏.zip"), str(tmp_path / "乙.zip"),
                        str(tmp_path / "单个.gif")])
    assert seen == ["甲.zip", "坏.zip", "乙.zip"], f"没有逐个导入：{seen}"
    text = page._describe_result_seen
    assert "✓ 「甲」" in text and "✗ 坏.zip" in text and "✓ 「乙」" in text, text
    assert "1 个单独的素材没导入" in text, f"混在里面的单个素材又被静默丢了：{text}"


# ──────────────────────────── 同一份文件同一个答案 ────────────────────────────

def test_a_missing_cols_is_read_the_same_way_on_import_as_at_runtime(tmp_path):
    """缺 cols：运行时按 图集宽 ÷ 帧宽 = 3 列；导入以前按 1 列，只读得出第一帧。"""
    (tmp_path / "s.png").write_bytes(_sheet_png(frames=3))
    (tmp_path / "s.json").write_text(json.dumps(
        {"image": "s.png", "frame_width": 16, "frame_height": 16, "frames": 3, "fps": 20}), encoding="utf-8")
    probe = probe_source(str(tmp_path / "s.json"))
    assert probe.grid[0] == sheet_columns(None, 48, 16) == 3, probe.grid


def test_the_verbatim_path_also_caps_frames_and_writes_cols(tmp_path):
    rm = _RM(tmp_path / "lib")
    (tmp_path / "s.png").write_bytes(_sheet_png(frames=3))
    (tmp_path / "s.json").write_text(json.dumps(
        {"image": "s.png", "frame_width": 16, "frame_height": 16, "frames": 9999, "fps": 20}), encoding="utf-8")
    result = convert_to_style(str(tmp_path / "s.json"), "原样", 1, resource_manager=rm)
    written = json.loads((tmp_path / "lib" / "kill_icons" / "原样" / "1.json").read_text(encoding="utf-8"))
    assert written["frames"] <= 600, f"原样搬运没过帧数闸门：{written['frames']}"
    assert written.get("cols") == 3, f"转手出去的包缺 cols：{written}"
    assert any("600" in w for w in result.get("warnings", [])), "截了帧却没说"


# ──────────────────────────── 缩放的内存上限 ────────────────────────────

DEFAULT_STYLE = [(46, 350, 250), (123, 350, 250), (74, 350, 250), (75, 350, 250), (201, 350, 250)]


def test_the_default_style_keeps_every_scale_it_could_already_use():
    """默认风格 519 帧：150% ≈475MB，在预算内 ⇒ 现有设置一个像素都不变。"""
    assert capped_scale(DEFAULT_STYLE, 350, 1.5) == 1.5
    assert capped_scale(DEFAULT_STYLE, 350, 1.0) == 1.0


def test_an_oversized_style_is_shrunk_as_a_whole_to_fit_the_budget():
    got = capped_scale(DEFAULT_STYLE, 350, 2.0)
    assert 1.0 < got < 2.0, got

    def total(s):
        return sum(n * w * h * 4 for n, fw, fh in DEFAULT_STYLE for w, h in [compute_scaled_size(fw, fh, 350, s)])

    assert total(got) <= SCALED_MEMORY_BUDGET < total(got + 0.02), "压过头了或没压够"


def test_legacy_frame_folders_count_toward_the_budget(tmp_path):
    """默认风格恰恰是逐帧目录 —— 清单只数帧不量尺寸（它不许碰 Qt/PIL），
    算内存预算时不补量的话，上限对最常见的那套素材完全不起作用。"""
    from PySide6.QtWidgets import QApplication

    from kill_icon_overlay import budget_levels

    QApplication.instance() or QApplication([])
    rm = _RM(tmp_path / "lib")
    d = tmp_path / "lib" / "kill_icons" / "老" / "1"
    d.mkdir(parents=True)
    for i in range(3):
        Image.new("RGBA", (40, 30)).save(d / f"{i:03d}.png")
    assert budget_levels("老", rm) == [(3, 40, 30)]


def test_the_page_says_when_the_scale_is_capped(page, monkeypatch):
    import kill_icon_overlay as lib

    told = []
    monkeypatch.setattr(page, "_current_style", lambda: "默认")
    monkeypatch.setattr(page, "_show_notice", lambda msg, *a, **k: told.append(msg))
    monkeypatch.setattr(lib, "effective_scale", lambda *a, **k: 1.54)
    page._say_if_scale_is_capped(2.0)
    assert told and "154%" in told[0], told
    told.clear()
    monkeypatch.setattr(lib, "effective_scale", lambda style, bw, s, *a, **k: s)
    page._say_if_scale_is_capped(1.0)
    assert not told, "没压也在说"
