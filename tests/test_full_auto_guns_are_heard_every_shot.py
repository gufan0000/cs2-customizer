# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""全自动枪声替换（2026-09-17）：**每一发都要响，扫射不许断、不许抽**。

## 背景（RN-254 → RN-432，悬了四个月）

`FULL_AUTO_GUN_SOUND_WEAPON_TYPES` 从仓库首个提交起写死 17 把全自动，上方无一字解释。
隔壁会话考古 + 本机复核：**排除没有技术原因** —— 前身版本（2025-11）只发过 10 把半自动，
2.0 重构把档案扩到 35 把、连发参数全调好之后，用这张名单把运行期集合收回旧的那一档。
真实对局 GSI 包间隔（2026-03 两份日志反推）P5 62ms / P25 100ms / P50 126ms，
与步枪射速（AK 100ms）同量级；竞品靠同一条 `ammo_clip` 递减链路全武器可用。

## 参考竞品实测好用的四条机制，各配一条判据

| 机制 | 我方原状 | 判据 |
|---|---|---|
| 没有速率闸门（100% 捕获） | 步枪闸门 0.09s，真实包间隔序列下 **AK 白丢 15%** | ③ 拿真实分布的间隔喂 `_process_gun_sound`，一发不许丢 |
| 原声钉在 20% 当节奏骨架 | 扫射压到 8.6%（步枪）/ 6.8%（机枪），且逐包下探 | ④ 扫射档持续 ≈ 20%、峰值 = 持续（平的） |
| 5 槽轮转 | 3 条通道 | ⑤ 池子 5 条、索引互不重复、不超 mixer 总数 |
| 全武器可用 | 17 把选不到 | ① 35/35 在运行期集合里；⑥ 页面真有「步枪」页签与 AK-47 卡 |

（本项目测试逐文件跑：`python -m pytest tests/test_full_auto_guns_are_heard_every_shot.py`）
"""
from __future__ import annotations

import ast
import dataclasses
import types
from pathlib import Path

import pytest

from core.gun_sound_profiles import (
    AUTOMATIC_GUN_TYPES,
    FULL_AUTO_GATE_SCALE,
    FULL_AUTO_GUN_SOUND_WEAPON_TYPES,
    GUN_SOUND_PROFILES,
    GUN_SOUND_TAB_GROUPS,
    GUN_SOUND_WEAPON_TYPES,
    SEMI_AUTO_GUN_TYPES,
    SUPPORTED_GUN_SOUND_PROFILES,
    SUPPORTED_GUN_SOUND_TAB_GROUPS,
    SUPPORTED_GUN_SOUND_WEAPON_TYPES,
    build_gun_sound_duck_plan,
    is_gun_sound_burst,
)

ROOT = Path(__file__).resolve().parent.parent

#: 真实对局的 GSI 包间隔（秒），按隔壁会话从 2026-03-01 死斗日志反推的分布取样：
#: P5 62ms / P25 100ms / P50 126ms，众数 75~125ms，1 秒滑窗峰值 11 包。
#: ⭐ 这是**包**间隔不是**发**间隔 —— 全自动扫射时一包最多报一次递减。
REAL_PACKET_GAPS = (0.062, 0.100, 0.126, 0.092, 0.075, 0.108, 0.150, 0.100, 0.085, 0.120) * 3


class _DummyConfig:
    gun_sound_duck_ratio = 0.18
    gun_sound_duck_release_ms = 120


# ------------------------------------------------ ① 35 把全在

def test_no_gun_in_the_profile_table_is_hidden_from_the_runtime():
    assert FULL_AUTO_GUN_SOUND_WEAPON_TYPES == ()
    assert SUPPORTED_GUN_SOUND_WEAPON_TYPES == GUN_SOUND_WEAPON_TYPES
    assert SUPPORTED_GUN_SOUND_TAB_GROUPS == GUN_SOUND_TAB_GROUPS
    assert len(AUTOMATIC_GUN_TYPES) == 17, AUTOMATIC_GUN_TYPES
    assert set(AUTOMATIC_GUN_TYPES) <= set(SUPPORTED_GUN_SOUND_WEAPON_TYPES)


# ------------------------------------------------ ② 闸门与扫射窗由射击周期算出

#: 真实 GSI 包间隔的下界（P5）。闸门只要低于它，就不可能拦住任何一包；
#: 高于它的闸门必须离射击周期至少一个抖动量（60ms），否则一次抖动就吃掉一发。
P5_PACKET_GAP = 0.062
JITTER = 0.060


@pytest.mark.parametrize("gun_type", GUN_SOUND_WEAPON_TYPES)
def test_the_gate_is_half_the_fire_period_for_every_gun(gun_type):
    """批 101：半自动的周期同样由游戏钉死（点得再快也快不过 cycletime）⇒ 闸门也从周期算。
    2026-09-17 之前半自动是手填的：Tec-9 0.09 对周期 0.12、沙鹰 0.18 对 0.224，余量 30~45ms。"""
    profile = GUN_SOUND_PROFILES[gun_type]
    assert profile.fire_period > 0
    # 闸门 = 周期 × 0.5：比周期短（不拦真开的那一发），又能挡同一发被两包重报。
    assert profile.min_fire_interval == pytest.approx(profile.fire_period * FULL_AUTO_GATE_SCALE, abs=1e-3)
    assert profile.min_fire_interval < profile.fire_period
    gate = profile.min_fire_interval
    assert gate < P5_PACKET_GAP or gate <= profile.fire_period - JITTER, (
        f"{gun_type} 闸门 {gate:.3f}s 离周期 {profile.fire_period:.3f}s 不到一个抖动量")


@pytest.mark.parametrize("gun_type", AUTOMATIC_GUN_TYPES)
def test_the_burst_window_covers_gsi_jitter(gun_type):
    profile = GUN_SOUND_PROFILES[gun_type]
    assert profile.automatic
    # 扫射窗要盖住 GSI 包间隔的尾部（P50 已有 126ms），否则同一梭子被判成一串单发。
    assert profile.burst_window >= 0.25
    assert is_gun_sound_burst(profile, 0.126) is True
    assert is_gun_sound_burst(profile, 0.20) is True


# ------------------------------------------------ ③ 真实包间隔下一发不丢

def _spray(handler, module, gun_type: str, gaps, *, clock):
    """按 `gaps` 的间隔喂 N 包，每包 `ammo_clip` 减一；返回播了几声。"""
    profile = GUN_SOUND_PROFILES[gun_type]
    gsi_name = profile.gsi_names[0]
    ammo = 40
    getattr(handler, f"previous_{gun_type}_ammo")["weapon_0"] = ammo
    for gap in gaps:
        clock["now"] += gap
        ammo -= 1
        payload = {"player": {"weapons": {"weapon_0": {
            "name": gsi_name, "state": "active", "ammo_clip": ammo}}}}
        handler._reset_gun_frame_flags()
        handler._process_gun_sound(gun_type, payload)


def _make_handler(monkeypatch, gun_type: str, style: str):
    import gsi_handler_sounds
    from config import config

    plays: list[str] = []
    ducks: list[dict] = []

    class _Audio:
        def play_sound(self, key, **_kw):
            plays.append(key)
            return True

    class _Ducker:
        def duck_for(self, delay, **kw):
            ducks.append(kw)
            return True

        def is_ducked(self):
            return False

        def restore(self):
            return True

    class _Keyboard:
        def press(self, *_a, **_k):
            return None

        def release(self, *_a, **_k):
            return None

    clock = {"now": 100.0}
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", _Audio())
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _Keyboard)
    monkeypatch.setattr(gsi_handler_sounds, "time", types.SimpleNamespace(time=lambda: clock["now"]))
    monkeypatch.setattr(config, f"{gun_type}_style", style, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_ratio", 0.18, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_release_ms", 120, raising=False)
    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._game_audio_ducker = _Ducker()
    return handler, gsi_handler_sounds, plays, ducks, clock


@pytest.mark.parametrize("gun_type", ["ak47", "m4a1", "p90", "negev", "cz75a"])
def test_a_spray_at_real_packet_intervals_plays_every_packet(monkeypatch, gun_type):
    handler, module, plays, _ducks, clock = _make_handler(monkeypatch, gun_type, "styleX")
    _spray(handler, module, gun_type, REAL_PACKET_GAPS, clock=clock)
    assert len(plays) == len(REAL_PACKET_GAPS), (
        f"{gun_type}：{len(REAL_PACKET_GAPS)} 包只播了 {len(plays)} 声 —— "
        "GSI 一包只报一次递减，每一包都是玩家真开的一发，闸门不许吃掉它")
    assert all(key == f"gun-{gun_type}-styleX" for key in plays)


def test_that_judge_sees_the_old_gate_losing_shots(monkeypatch):
    """空转守卫：把 AK 的闸门改回旧值 0.09s，同一串间隔必须**看得见丢发**。"""
    handler, module, plays, _ducks, clock = _make_handler(monkeypatch, "ak47", "styleX")
    old = dataclasses.replace(GUN_SOUND_PROFILES["ak47"], min_fire_interval=0.09)
    monkeypatch.setitem(SUPPORTED_GUN_SOUND_PROFILES, "ak47", old)
    _spray(handler, module, "ak47", REAL_PACKET_GAPS, clock=clock)
    captured = len(plays) / len(REAL_PACKET_GAPS)
    assert captured < 0.85, (
        f"旧闸门下捕获率 {captured:.0%} —— 这串间隔已经逼不出丢发，上面那条判据在空转")


def test_a_spray_reaches_the_runtime_through_the_public_entry(monkeypatch):
    """`process_data` 那条公开入口以前**根本不遍历** ak47（走的是 SUPPORTED 表）。"""
    from config import config

    handler, module, plays, _ducks, clock = _make_handler(monkeypatch, "ak47", "styleX")
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "player_steamid", "7656", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", False, raising=False)
    ammo = 30
    for gap in REAL_PACKET_GAPS[:5]:
        clock["now"] += gap
        ammo -= 1
        handler.process_data({"player": {
            "steamid": "7656", "activity": "playing",
            "weapons": {"weapon_0": {"name": "weapon_ak47", "state": "active", "ammo_clip": ammo}},
        }})
    # 第一包只建立基线（prev_ammo 为空），之后每包一声。
    assert len(plays) == 4, plays


# ------------------------------------------------ ④ 扫射档：原声留 ~20%、平的

@pytest.mark.parametrize("gun_type", AUTOMATIC_GUN_TYPES)
def test_the_spray_duck_keeps_a_flat_rhythm_skeleton(gun_type):
    """竞品每包把游戏音量钉在 20%，淡回永远走不完 ⇒ 自定义枪声盖在 20% 的原声扫射上，
    **原声的逐发节奏补齐了「一包一发」漏掉的那几发**。我方旧值压到 8.6%/6.8% 且逐包下探。"""
    profile = GUN_SOUND_PROFILES[gun_type]
    cfg = _DummyConfig()
    spray = build_gun_sound_duck_plan(cfg, profile, is_burst=True, hold_duration=0.24)
    first = build_gun_sound_duck_plan(cfg, profile, is_burst=False, hold_duration=0.24)
    assert 0.18 <= spray.sustain_ratio <= 0.22, f"{gun_type} 扫射档原声 {spray.sustain_ratio:.3f}"
    assert spray.peak_ratio == pytest.approx(spray.sustain_ratio), "扫射档不许逐包下探（抽吸）"
    # 第一发（非扫射档）仍然压得更深 —— 那是这梭子的起音。
    assert first.sustain_ratio < spray.sustain_ratio
    assert first.peak_ratio < first.sustain_ratio


def test_the_semi_auto_shape_did_not_move():
    """⛔ 反转全自动那一刀不许溅到半自动：USP 的扫射档仍比单发压得更深（既有判据的前提）。"""
    cfg = _DummyConfig()
    for gun_type in ("usp", "deagle", "awp", "scar20", "nova"):
        profile = GUN_SOUND_PROFILES[gun_type]
        assert not profile.automatic and gun_type in SEMI_AUTO_GUN_TYPES
        burst = build_gun_sound_duck_plan(cfg, profile, is_burst=True, hold_duration=0.2)
        single = build_gun_sound_duck_plan(cfg, profile, is_burst=False, hold_duration=0.2)
        assert burst.sustain_ratio < single.sustain_ratio, gun_type


# ------------------------------------------------ ⑦ 半自动：游戏速度连点 + GSI 抖动，一发不丢

#: CS2 的 cycletime（秒），**独立于档案表抄的** —— 判据不许拿被测表算自己的预期。
GAME_CYCLE = {"tec9": 0.12, "elite": 0.12, "glock": 0.15, "deagle": 0.224, "scar20": 0.25}
#: 2026-09-17 之前手填的闸门，留着当空转守卫的对照。
HAND_TYPED_GATES = {"tec9": 0.09, "elite": 0.08, "glock": 0.10, "deagle": 0.18}


def _jittered_clicks(period: float, n: int = 20, jitter: float = 0.058):
    """按游戏周期连点，GSI 包时刻前后抖 ±58ms（P5 包间隔 62ms 反推）：短一包、长一包交替。"""
    return tuple(period + (jitter if i % 2 else -jitter) for i in range(n))


@pytest.mark.parametrize("gun_type", sorted(GAME_CYCLE))
def test_a_click_train_at_game_speed_with_gsi_jitter_plays_every_click(monkeypatch, gun_type):
    assert GUN_SOUND_PROFILES[gun_type].fire_period == pytest.approx(GAME_CYCLE[gun_type], abs=1e-3)
    gaps = _jittered_clicks(GAME_CYCLE[gun_type])
    handler, module, plays, _ducks, clock = _make_handler(monkeypatch, gun_type, "styleX")
    _spray(handler, module, gun_type, gaps, clock=clock)
    assert len(plays) == len(gaps), (
        f"{gun_type}：{len(gaps)} 次点击只播了 {len(plays)} 声 —— "
        "游戏周期内点不出第二发，闸门离周期太近就只会吃掉真开的那一发")


@pytest.mark.parametrize("gun_type", sorted(HAND_TYPED_GATES))
def test_that_judge_sees_the_hand_typed_gates_losing_clicks(monkeypatch, gun_type):
    """空转守卫：把闸门改回手填的旧值，同一串点击必须**看得见丢发**。"""
    gaps = _jittered_clicks(GAME_CYCLE[gun_type])
    handler, module, plays, _ducks, clock = _make_handler(monkeypatch, gun_type, "styleX")
    old = dataclasses.replace(GUN_SOUND_PROFILES[gun_type], min_fire_interval=HAND_TYPED_GATES[gun_type])
    monkeypatch.setitem(SUPPORTED_GUN_SOUND_PROFILES, gun_type, old)
    _spray(handler, module, gun_type, gaps, clock=clock)
    assert len(plays) < len(gaps), (
        f"{gun_type} 旧闸门 {HAND_TYPED_GATES[gun_type]}s 下一发都没丢 —— 上面那条判据在空转")


# ------------------------------------------------ ⑤ 通道池 5 条

def test_the_gun_sound_channel_pool_has_five_distinct_channels():
    from core.audio.audio_manager import AudioManager

    mgr = AudioManager()
    assert len(mgr.gun_sound_channels) == 5
    assert len({id(ch) for ch in mgr.gun_sound_channels}) == 5


def test_channel_indices_do_not_collide_and_fit_the_mixer():
    """AST：`_make_channel(N)` 的字面量索引互不重复，且都小于 `set_num_channels(M)`。
    ⚠ 两个通道拿同一个索引不报错 —— 只是互相顶掉对方正在播的声音。"""
    tree = ast.parse((ROOT / "core" / "audio" / "audio_manager.py").read_text(encoding="utf-8"))
    indices, total = [], None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name == "_make_channel" and node.args and isinstance(node.args[0], ast.Constant):
            indices.append(int(node.args[0].value))
        if name == "set_num_channels" and node.args and isinstance(node.args[0], ast.Constant):
            total = int(node.args[0].value)
    assert total is not None and len(indices) >= 10, (indices, total)
    assert len(indices) == len(set(indices)), f"通道索引重复：{sorted(indices)}"
    assert max(indices) < total, f"索引 {max(indices)} 超出 mixer 的 {total} 条"


# ------------------------------------------------ ⑥ 页面真的摆出来了

def test_the_page_shows_the_rifle_tab_with_an_ak47_card(qapp, monkeypatch):
    from config import config
    import pages.gun_sound_page as mod

    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for gun_type in SUPPORTED_GUN_SOUND_WEAPON_TYPES:
        monkeypatch.setattr(config, f"{gun_type}_style", "0", raising=False)
    monkeypatch.setattr(mod.GunSoundPage, "_scan_gun_sounds",
                        lambda self: setattr(self, "weapon_styles", {}))
    page = mod.GunSoundPage()
    try:
        tabs = [page.tab_widget.tabText(i) for i in range(page.tab_widget.count())]
        assert tabs == [name for name, _ in GUN_SOUND_TAB_GROUPS]
        for cls in ("步枪", "冲锋枪", "机枪"):
            assert cls in tabs
        assert set(page.weapon_rows) == set(SUPPORTED_GUN_SOUND_WEAPON_TYPES)
        assert page.weapon_rows["ak47"]["style_combo"].count() >= 1
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_automatic_tabs_say_a_spray_keeps_some_original_sound(qapp, monkeypatch):
    """外审判断题「玩家会不会知道扫射时会留一点原声、不是整个换掉」**12/12 答不会**：
    那句话埋在页头长句末尾。⇒ 全自动的页签顶上各说一次；半自动页签不说（那里不成立）。"""
    from PySide6.QtWidgets import QLabel

    from config import config
    import pages.gun_sound_page as mod

    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for gun_type in SUPPORTED_GUN_SOUND_WEAPON_TYPES:
        monkeypatch.setattr(config, f"{gun_type}_style", "0", raising=False)
    monkeypatch.setattr(mod.GunSoundPage, "_scan_gun_sounds",
                        lambda self: setattr(self, "weapon_styles", {}))
    page = mod.GunSoundPage()
    try:
        per_tab = {}
        for index, (name, weapons) in enumerate(page._tab_groups):
            tab = page.tab_widget.widget(index)
            hints = [lb.text() for lb in tab.findChildren(QLabel) if "扫射" in lb.text() and "原声" in lb.text()]
            per_tab[name] = (hints, [w for w in weapons if GUN_SOUND_PROFILES[w].automatic], list(weapons))
        assert {n for n, (_h, auto, _all) in per_tab.items() if auto} >= {"冲锋枪", "步枪", "机枪", "手枪"}, per_tab
        for name, (hints, auto, everyone) in per_tab.items():
            assert len(hints) == (1 if auto else 0), f"{name} 页签上那句扫射说明出现了 {len(hints)} 次：{per_tab}"
            if auto and len(auto) == len(everyone):
                assert hints[0].startswith("这一组是全自动枪"), hints
            elif auto:
                # ⚠ 手枪页签里只有 CZ75-Auto 是全自动 —— 只许点它的名，不许把整组说成全自动。
                assert not hints[0].startswith("这一组"), hints
                for w in auto:
                    assert GUN_SOUND_PROFILES[w].display_name in hints[0], hints
        assert "狙击枪" in per_tab and not per_tab["狙击枪"][0], "狙击枪页签没有全自动，不该有那句"
        # 改后复跑 20/20 仍「不会」：玩家只看控件名 ⇒ 扫射那句也挂在「原声保留」的 tooltip 上，
        # 且那句提示本身必须短（第一版带了机制解释，被 12 发一致点名「冗长」）。
        assert "扫射" in page.weapon_rows["ak47"]["duck_caption"].toolTip()
        assert "扫射" not in page.weapon_rows["awp"]["duck_caption"].toolTip()
        assert len(per_tab["步枪"][0][0]) <= 40, per_tab["步枪"][0]
    finally:
        page.deleteLater()
        qapp.processEvents()
