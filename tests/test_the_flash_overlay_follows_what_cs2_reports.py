# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 136（RN-706②）：闪光白屏按 CS2 真实报的值画。

F-02 进游戏实测（6 颗，正对 / 侧对 / 背对各两颗，`H:/tmp/ingame_runs/20261003_113246`）：
CS2 的 `player.state.flashed` 只报 0 / 1。正对那颗「1」持续约 1.1s，归零那一刻游戏仍是全白、再用约 2s 淡回；
擦边的「1」只有 0.02s。以前 CS2 Customizer ：1 ⇒ 0.46 浓度、归零后淡出从 0 起算（等于没淡）、100ms 后再补一刀强制清除
⇒ 游戏还白着两秒， CS2 Customizer 的白屏已经没了；且映射在 19→20 处断崖（0.885 → 0.078）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _probe(tmp_path, body: str) -> dict:
    # ⚠ 子进程里跑：import flash_process 会改本进程的 DPI 感知、拉 pygame，不许污染 pytest 进程；不开窗口。
    p = tmp_path / "flash_probe.py"
    p.write_text(f"import json, sys\nsys.path.insert(0, {str(REPO)!r})\nimport flash_process as fp\n"
                 + body + "\nprint('@@' + json.dumps(out))\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    return json.loads(line[-1][2:])


def test_the_strength_never_drops_as_the_flash_value_rises(tmp_path):
    out = _probe(tmp_path, "out = {'s': [fp.flash_strength(v) for v in range(0, 256)]}")
    s = out["s"]
    drops = [(v, s[v - 1], s[v]) for v in range(1, 256) if s[v] < s[v - 1]]
    assert not drops, f"闪光值变大、白屏反而变淡：{drops[:5]}"
    assert s[0] == 0.0 and s[1] == 1.0, f"CS2 只报 0 / 1 ⇒ 1 必须是满强度，实际 {s[1]}"


def test_the_white_screen_fades_like_the_game_after_cs2_drops_to_zero(tmp_path):
    out = _probe(tmp_path, """
def replay(held, fade_out=True, fade_in=True):
    fe = fp.FlashEffectProcess()
    env = fe.envelope
    trace = []
    t = 0.0
    while t < held + 3.0:
        v = 1 if t < held else 0
        fe.update_flash_value(v)          # 子进程收到的值（与命令线程同一条路）
        fe.flash_value = v
        trace.append((round(t, 3), env.step(t, v, fe.current_opacity, fade_in, fade_out)))
        t += 1 / 60
    return fe.max_opacity, trace

full, front = replay(1.1)       # 正对：实测「1」持续约 1.1s
_, glance = replay(0.02)        # 擦边：实测 0.02s
_, nofade = replay(1.1, fade_out=False)
out = {'full': full, 'front': front, 'glance': glance, 'nofade': nofade}
""")
    full = out["full"]
    at = lambda tr, t: max(v for tt, v in tr if tt <= t + 1e-9 and tt >= t - 1 / 60)  # noqa: E731
    front = out["front"]
    assert at(front, 1.0) >= full * 0.99, "被闪中（GSI=1）要画满强度"
    assert at(front, 1.1 + 1.0) >= full * 0.4, (
        f"归零 1 秒后游戏仍明显发白（实测亮度 233~204/255）， CS2 Customizer 的白屏不该已经没了：{at(front, 2.1):.2f}")
    assert at(front, 1.1 + 2.1) == 0.0, "正对那颗淡出应在约 2 秒内走完"
    glance = out["glance"]
    assert max(v for _t, v in glance) < full * 0.2, "擦边一下（淡入才走了一点）不该被画成满屏白"
    assert at(glance, 0.02 + 0.5) == 0.0, "擦边那颗淡出应很快走完"
    assert at(out["nofade"], 1.1 + 0.05) == 0.0, "关了淡出 ⇒ 归零当场清掉"


def test_the_main_process_does_not_cut_the_fade_short(monkeypatch):
    import gsi_handler_flash as ghf
    from config import config

    monkeypatch.setattr(config, "flash_enabled", True, raising=False)
    clears: list[float] = []

    class _PM:
        audio_auto_stop = False
        audio_playing = False

        def update_flash_value(self, v):
            pass

        def force_clear_flash(self):
            clears.append(time.monotonic())

    class _Comp:
        process_manager = _PM()

    def frame(v):
        # ⚠ 不带 map.round：处理器把「回合号变了」当成强制清零，首帧带回合号 = 这一颗根本没开始，
        #   判据就恒绿（回退验证逮到过这一版）
        return {"player": {"state": {"flashed": v, "health": 100}}}

    h = ghf.GSIHandlerFlash()
    h.set_flash_component(_Comp())
    h.process_data(frame(1))
    assert h.current_flash_value == 1, "这一颗没开始 —— 下面的断言会恒绿"
    h.process_data(frame(0))
    time.sleep(0.4)
    assert not clears, "归零后 0.4 秒内就补发了强制清除 ⇒ 把子进程的淡出拦腰砍断"

    monkeypatch.setattr(ghf, "_CLEAR_AFTER_S", 0.15)
    h2 = ghf.GSIHandlerFlash()
    h2.set_flash_component(_Comp())
    h2.process_data(frame(1))
    h2.process_data(frame(0))
    h2.process_data(frame(1))          # 补刀之前新一颗又闪了
    time.sleep(0.4)
    assert not clears, "新一颗闪光已经开始，迟到的强制清除把它也清掉了"
    h2.process_data(frame(0))
    time.sleep(0.4)
    assert clears, "淡出走完后的那次强制清除（双重保险）没发"


class _ClearPM:
    def __init__(self):
        self.current_flash_value = 1
        self.clears = 0

    def force_clear_flash(self):
        self.clears += 1

    def update_flash_value(self, v):
        self.current_flash_value = v


def test_switching_flash_off_mid_flash_clears_the_overlay_at_once(monkeypatch):
    """批 136 进游戏逮到（FLASH-SWITCH 10-02、10-03 两轮都红）：首页拨关闪光只改配置，
    GSI 那边不再转发 ⇒ 子进程按最后一个值一直画，直到 10 秒断流看门狗。"""
    import types

    import gui_widget
    from config import config

    pm = _ClearPM()

    class _Self:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    me = _Self()
    me.config = config
    me.logger = types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None, warning=lambda *a: None,
                                      debug=lambda *a: None)
    me.pages = {"flash": types.SimpleNamespace(process_manager=pm)}
    monkeypatch.setattr(config, "flash_enabled", True, raising=False)
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    try:
        gui_widget.MainWindow._on_switch_changed(me, "flash_enabled", False)
    except Exception:  # noqa: BLE001 —— 后面那些与闪光无关的收尾不在本判据范围
        pass
    assert pm.clears == 1 and pm.current_flash_value == 0, "拨关闪光时正画着的那层没当场清掉"


def test_the_gsi_side_also_clears_when_flash_was_turned_off_elsewhere(monkeypatch):
    """预设 / 闪光页也会关 flash_enabled，不经首页开关 ⇒ GSI 那边看到关了、自己还记着「正被闪」就清。"""
    import gsi_handler_flash as ghf
    from config import config

    pm = _ClearPM()
    h = ghf.GSIHandlerFlash()
    h.set_flash_component(type("C", (), {"process_manager": pm})())
    h.current_flash_value = 1
    monkeypatch.setattr(config, "flash_enabled", False, raising=False)
    h.process_data({"player": {"state": {"flashed": 1, "health": 100}}})
    assert pm.clears == 1 and h.current_flash_value == 0


def test_the_main_process_waits_at_least_as_long_as_the_longest_fade(tmp_path):
    import gsi_handler_flash as ghf

    out = _probe(tmp_path, "out = {'max': fp.FADE_OUT_MAX_S}")
    assert ghf._CLEAR_AFTER_S > out["max"], (ghf._CLEAR_AFTER_S, out["max"])
