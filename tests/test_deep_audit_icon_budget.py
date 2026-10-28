# SPDX-License-Identifier: GPL-3.0-or-later
"""像素结果、解码前预算和中途取消；不接触实际叠加窗口。"""
import random

import pytest
from PIL import Image

from core import kill_icon_import as mod


def test_sequence_budget_is_checked_before_decoding(tmp_path, monkeypatch):
    for i in range(3):
        Image.new("RGBA", (32, 32)).save(tmp_path / f"{i}.png")
    monkeypatch.setattr(mod, "MAX_DECODED_BYTES", 2 * 32 * 32 * 4)
    decoded = []
    monkeypatch.setattr(Image.Image, "convert", lambda *a, **k: decoded.append(True))
    with pytest.raises(mod.KillIconImportError, match="256 MiB"):
        mod._read_sequence_frames(str(tmp_path))
    assert not decoded


def test_chroma_key_matches_original_pixel_rule_and_preserves_rgb():
    rng = random.Random(284)
    data = rng.randbytes(64 * 64 * 4)
    frame = Image.frombytes("RGBA", (64, 64), data)
    expected = frame.copy()
    pixels = expected.load()
    color, tolerance = (100, 120, 140), 90
    for y in range(64):
        for x in range(64):
            r, g, b, a = pixels[x, y]
            if a and all(abs(value - target) <= tolerance for value, target in zip((r, g, b), color)):
                pixels[x, y] = (r, g, b, 0)
    actual = mod._apply_chroma_key([frame], color, tolerance)[0]
    assert actual.tobytes() == expected.tobytes()


def test_normalize_reuses_matching_frames_and_cancels():
    frame = Image.new("RGBA", (32, 32), (1, 2, 3, 123))
    frames = [frame]
    normalized, w, h, _ = mod._normalize_frames(frames)
    assert normalized is frames and normalized[0] is frame and (w, h) == (32, 32)
    with pytest.raises(mod.KillIconImportCancelled):
        mod._normalize_frames(frames, cancel=lambda: True)
    with pytest.raises(mod.KillIconImportCancelled):
        mod._pack_sheet(frames, w, h, cancel=lambda: True)


def test_mixed_aspect_ratios_cannot_allocate_an_unbounded_common_canvas(monkeypatch):
    frames = [Image.new("RGBA", (10000, 1)), Image.new("RGBA", (1, 10000))]
    allocated = []
    monkeypatch.setattr(Image, "new", lambda *a, **k: allocated.append(a))
    with pytest.raises(mod.KillIconImportError, match="256 MiB"):
        mod._normalize_frames(frames)
    assert not allocated
