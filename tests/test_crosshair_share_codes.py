# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 130：CS2 准心分享码 ↔ CS2 Customizer 准心。样例码取自公开实现的测试（fixture 里注明出处），逐条对解码与编码。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import crosshair_sharecode as cs

FIX = json.loads((Path(__file__).parent / "fixtures" / "crosshair_sharecode_samples.json").read_text(encoding="utf-8"))


def _close(a, b):
    return abs(a - b) < 1e-9 if isinstance(a, float) or isinstance(b, float) else a == b


@pytest.mark.parametrize("s", FIX["samples"], ids=lambda s: s["code"])
def test_every_published_sample_decodes_to_its_published_fields(s):
    got = cs.decode(s["code"])
    want = s["crosshair"]
    assert set(got) == set(want), (sorted(set(got) ^ set(want)))
    bad = {k: (got[k], want[k]) for k in want if not _close(got[k], want[k])}
    assert not bad, bad


@pytest.mark.parametrize("s", [s for s in FIX["samples"] if s["crosshair"]["version"] in (3, 4)],
                         ids=lambda s: s["code"])
def test_every_current_sample_encodes_back_to_the_same_code(s):
    assert cs.encode(s["crosshair"]) == s["code"]


@pytest.mark.parametrize("code", FIX["invalid"] + ["CSGO-12345-12345-12345-12345-1234", "随便一句话", ""])
def test_a_wrong_code_is_refused_with_a_sentence_not_a_crash(code):
    with pytest.raises(cs.ShareCodeError) as e:
        cs.decode(code)
    assert str(e.value)


def test_a_code_with_a_few_characters_copied_wrong_is_caught_by_the_checksum():
    """上面那几个坏码都在更早一步就被拒了（字符不合法 / 版本不认识），一个都没走到校验 —— 回退验证逮到这条恒绿。
    这里拿真码改一个字符（仍是合法字符），只有校验能拦住它。"""
    caught = 0
    for s in FIX["samples"]:
        code = s["code"]
        i = 5 + 6 * 2 + 2                      # 第三段中间那个字符
        ch = code[i]
        alt = cs.ALPHABET[(cs.ALPHABET.index(ch) + 1) % len(cs.ALPHABET)]
        bad = code[:i] + alt + code[i + 1:]
        try:
            cs.decode(bad)
        except cs.ShareCodeError as e:
            caught += "校验" in str(e)
    assert caught == len(FIX["samples"]), f"改了一个字符的 {len(FIX['samples'])} 个码里只有 {caught} 个被校验拦下"


def test_an_old_code_says_the_game_no_longer_takes_it():
    old = next(s["code"] for s in FIX["samples"] if s["crosshair"]["version"] == 1)
    with pytest.raises(cs.ShareCodeError, match="重新导出"):
        cs.to_cs2customizer(old)


def test_import_maps_onto_the_overlay_settings_and_says_what_it_dropped():
    # 静态十字、绿 50/250/50、gap 4、length 8、thickness 2、1080 高
    cfg, notes = cs.to_cs2customizer("CSGO-hLbCn-69VT6-Bok83-9MOqW-SWzwQ", target_height=1080)
    assert cfg == {"crosshair_style": "crosshair", "crosshair_color_custom": "#32FA32", "crosshair_alpha": 255,
                   "crosshair_thickness": 2, "crosshair_gap": 4, "crosshair_size": 24, "crosshair_outline": 0,
                   "crosshair_dot": False}
    assert notes == []
    # 只有点、1080 出码、1440 的屏 ⇒ 等比放大并说出来
    cfg, notes = cs.to_cs2customizer("CSGO-MnUCC-89iG7-2cVar-wy7Yn-amCpF", target_height=1440)
    assert cfg["crosshair_style"] == "dot" and cfg["crosshair_thickness"] == 4
    assert any("1440" in n for n in notes)
    # 动态十字（经典）+ 跟随后坐力 ⇒ 两条说明
    _cfg, notes = cs.to_cs2customizer("CSGO-sP6xU-TSyN9-sZcO5-2D48M-UppkP", target_height=768)
    assert any("扩散" in n for n in notes) and any("后坐力" in n for n in notes)


def test_export_then_import_gives_back_the_same_overlay():
    cfg = {"crosshair_style": "t_shape", "crosshair_color": "green", "crosshair_color_custom": "#12AB34",
           "crosshair_alpha": 200, "crosshair_size": 30, "crosshair_gap": 3, "crosshair_thickness": 2,
           "crosshair_outline": 1, "crosshair_dot": True}
    code = cs.from_cs2customizer(cfg, screen_height=1080)
    back, _ = cs.to_cs2customizer(code, target_height=1080)
    for k, v in back.items():
        assert cfg[k] == v, (k, cfg[k], v)


def test_settings_changed_while_the_crosshair_is_off_show_up_when_it_is_turned_on(monkeypatch):
    """批 130 进游戏逮到（XHAIR-CODE）：导入成功、配置是品红 + 间隙 4，打开准心画出来的却是启动时那个绿色无间隙的。
    根因不在分享码：Qt 准心只在启动时读一次 config，准心页又在准心关着时不推设置 ⇒ 关着时改的任何样式都丢。"""
    import types

    from PySide6.QtWidgets import QApplication

    import crosshair_overlay as co

    QApplication.instance() or QApplication([])

    class _Win:
        def recenter(self):
            return False

        def show(self):
            pass

        raise_ = apply_click_through = hide = close = deleteLater = show

    monkeypatch.setattr(co, "CrosshairOverlayWindow", _Win)
    monkeypatch.setattr(co.CrosshairOverlayManager, "_render_once", lambda self: None)
    cfg = types.SimpleNamespace(crosshair_size=20, crosshair_thickness=2, crosshair_color="green",
                                crosshair_style="crosshair", crosshair_animation="none", crosshair_kill_effect="none",
                                crosshair_custom_data=[], crosshair_color_custom="", crosshair_gap=0,
                                crosshair_outline=0, crosshair_dot=False, crosshair_alpha=255)
    m = co.CrosshairOverlayManager(cfg)
    try:
        values, _ = cs.to_cs2customizer("CSGO-hLbCn-69VT6-Bok83-9MOqW-SWzwQ", 1080)   # 准心关着时导入
        for k, v in values.items():
            setattr(cfg, k, v)
        m.show_crosshair()
        st = m._state
        assert (st.color, st.gap, st.size, st.thickness) == ("#32FA32", 4, 24, 2), (
            f"打开准心后画的还是启动时那一套：{st.color} gap={st.gap} size={st.size}")
    finally:
        m.destroy()


def test_a_hand_drawn_crosshair_is_refused_on_export():
    with pytest.raises(cs.ShareCodeError, match="自绘"):
        cs.from_cs2customizer({"crosshair_style": "custom"})
