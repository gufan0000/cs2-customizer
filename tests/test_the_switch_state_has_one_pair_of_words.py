# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-647（批 98）：就地总开关的状态，全站只许一对词 —— `master_switch_link.STATE_ON_TEXT / STATE_OFF_TEXT`。

批 97 改完 flash 看击杀音效页：同一张状态卡上开关行写「已开启」（开关行自带的词），
芯片写「开关 · 已启用」（`sound_page_base` 那一族各自 f-string 写的）。八页同病。
术语表（惯例 §5）加了一行：开关状态一律「已开启 / 未开启」；「已启用 / 未启用 / 已关闭 / 已禁用」
只留给子功能与非开关状态。

判据两条腿：
- 文本守卫：任何页面文件里，写「开关 · …」「显示 · …」「效果 · …」「总开关：…」那一行的 f-string
  不许再用第三种词；
- 渲染守卫：拿三页（kill_sound / magnifier / crosshair）真的建出来，芯片那一格的词必须等于开关行的词。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _denominator import must_scan  # noqa: E402
from config import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
#: 开关状态那一行的形状：`f"开关 · {'X' if enabled else 'Y'}"` / `f"总开关：{'X' if enabled else 'Y'}"`
_LINE = re.compile(r"""f"(?:[^"{]*总开关：|(?:开关|显示|效果) · )\{'([^']+)' if \w+ else '([^'（]+)""")


def test_every_switch_state_line_uses_the_switch_rows_words():
    from widgets import master_switch_link as msl

    hits = []
    bad = []
    for p in sorted((ROOT / "pages").glob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for on, off in _LINE.findall(line):
                hits.append((p.name, i))
                if (on, off) != (msl.STATE_ON_TEXT, msl.STATE_OFF_TEXT):
                    bad.append(f"{p.name}:{i} 「{on} / {off}」")
    must_scan(hits, "页面里写开关状态的那些行", least=15)
    assert not bad, ("这些行写开关状态用了开关行以外的词（RN-647）：\n  " + "\n  ".join(bad)
                     + f"\n⇒ 一律 {msl.STATE_ON_TEXT} / {msl.STATE_OFF_TEXT}（惯例 §5）")


def _chips(bar) -> list[str]:
    layout = bar.layout()
    return [w.text() for w in (layout.itemAt(i).widget() for i in range(layout.count() if layout else 0))
            if isinstance(w, QLabel) and w.objectName() == "audioStatusChip" and not w.isHidden()]


@pytest.mark.parametrize("page_id, module, cls, key, head", [
    ("magnifier", "pages.magnifier_page", "MagnifierPage", "magnifier_enabled", "开关"),
    ("crosshair", "pages.crosshair_page", "CrosshairPage", "crosshair_enabled", "显示"),
])
def test_the_chip_and_the_switch_row_say_the_same_word(qapp, monkeypatch, page_id, module, cls, key, head):
    import importlib

    from widgets import master_switch_link as msl

    mod = importlib.import_module(module)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    for enabled in (False, True):
        monkeypatch.setattr(config, key, enabled, raising=False)
        page = getattr(mod, cls)(config) if page_id == "magnifier" else getattr(mod, cls)()
        qapp.processEvents()
        try:
            row = getattr(page, "master_switch_row", None)
            assert row is not None, f"{page_id} 没有就地开关行（判据锚点失效）"
            row_word = row._state_label.text()
            chips = [t for t in _chips(page.status_badge_label) if t.startswith(f"{head} · ")]
            assert chips, f"{page_id} 没有「{head} · …」芯片：{_chips(page.status_badge_label)}"
            word = chips[0].split(" · ", 1)[1].strip()
            expected = msl.STATE_ON_TEXT if enabled else msl.STATE_OFF_TEXT
            assert row_word == expected, "夹具：开关行没同步到 config"
            assert word == expected, (
                f"{page_id}：开关行写「{row_word}」，同一张卡的芯片写「{head} · {word}」（RN-647）")
        finally:
            page.deleteLater()
            qapp.processEvents()
