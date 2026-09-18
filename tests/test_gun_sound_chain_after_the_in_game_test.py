# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 103：用户进游戏实测后这一轮的五处修复，一条一条钉住。

被测的都是「听不出来但一定错」的那类：
  ① 一包掉 N 发只播 1 声（快枪的替换声只响一半）
  ② 本机 steamid 自举用了 `player` 段（首包在观战 ⇒ 永久哑火）
  ③ 弹夹账本从不清空（捡同型枪 ⇒ 幻影枪声）
  ④ 风格目录第一个文件坏了 ⇒ 整把枪静音
  ⑤ 闪光音频和枪声抢同一条 mixer 通道
每条后面跟一条**空转守卫**：把修法撤掉，判据必须立刻变红。
"""
from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

from core.gun_sound_profiles import (
    GUN_SOUND_PROFILES,
    MAX_SHOTS_PER_PACKET,
)

REPO = Path(__file__).resolve().parents[1]


# ============================================================ 夹具

class _CollectTimer:
    """补发定时器替身：不起线程、不睡，`start()` 当场执行。"""

    def __init__(self, delay, fn, args=()):
        self.delay = delay
        self.fn = fn
        self.args = args
        self.daemon = False
        self.cancelled = False

    def start(self):
        if not self.cancelled:
            self.fn(*self.args)

    def cancel(self):
        self.cancelled = True


def _handler(monkeypatch, gun_type: str, style: str = "styleX", *, play_result=True):
    import gsi_handler_sounds
    from config import config

    plays: list[str] = []
    restores: list[int] = []
    delays: list[float] = []

    class _Audio:
        def play_sound(self, key, **_kw):
            plays.append(key)
            return play_result

        def prewarm_gun_sound(self, *_a, **_k):
            return None

    class _Ducker:
        def duck_for(self, _delay, **_kw):
            return True

        def is_ducked(self):
            return False

        def restore(self):
            restores.append(1)
            return True

        def prewarm(self):
            return None

    class _Keyboard:
        def press(self, *_a, **_k):
            return None

        def release(self, *_a, **_k):
            return None

    class _Timer(_CollectTimer):
        def __init__(self, delay, fn, args=()):
            delays.append(delay)
            super().__init__(delay, fn, args)

    clock = {"now": 500.0}
    # ⚠ 枪声总开关在测试环境里是**关**的（批 101 踩过）：`process_data` 与
    # `_play_extra_shot` 都先问它，不开就一声不响 —— 那种红和真缺陷长得一样。
    monkeypatch.setattr(gsi_handler_sounds, "is_gun_sound_master_enabled", lambda _cfg: True)
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", _Audio())
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _Keyboard)
    monkeypatch.setattr(
        gsi_handler_sounds, "time",
        types.SimpleNamespace(time=lambda: clock["now"], monotonic=lambda: clock["now"]),
    )
    monkeypatch.setattr(config, f"{gun_type}_style", style, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_ratio", 0.18, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_release_ms", 120, raising=False)
    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._game_audio_ducker = _Ducker()
    handler._extra_shot_timer_factory = _Timer
    return handler, gsi_handler_sounds, plays, restores, delays, clock


def _packet(gun_type: str, ammo: int, *, steamid: str = "", provider: str = ""):
    profile = GUN_SOUND_PROFILES[gun_type]
    player = {
        "activity": "playing",
        "weapons": {"weapon_0": {
            "name": profile.gsi_names[0], "state": "active", "ammo_clip": ammo}},
    }
    if steamid:
        player["steamid"] = steamid
    data = {"player": player}
    if provider:
        data["provider"] = {"steamid": provider}
    return data


# ============================================================ ① 一包掉 N 发就补 N 声

@pytest.mark.parametrize("gun_type", ["ak47", "p90", "negev", "mac10"])
def test_a_packet_that_dropped_two_rounds_plays_two_shots(monkeypatch, gun_type):
    """GSI 包间隔 P50 126ms 而快枪周期 70~100ms ⇒ 一包常常掉 2 发。以前只播 1 声。"""
    handler, _m, plays, _r, delays, _c = _handler(monkeypatch, gun_type)
    getattr(handler, f"previous_{gun_type}_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound(gun_type, _packet(gun_type, 28))

    assert len(plays) == 2, f"{gun_type}：弹夹掉了 2 发只播了 {len(plays)} 声"
    assert all(k == f"gun-{gun_type}-styleX" for k in plays)
    # 补的那一发要按游戏周期铺开，不许和第一发叠在同一毫秒（那是一声爆音不是两声枪响）
    assert delays == [pytest.approx(GUN_SOUND_PROFILES[gun_type].fire_period)]


def test_three_rounds_in_one_packet_play_three(monkeypatch):
    handler, _m, plays, _r, delays, _c = _handler(monkeypatch, "negev")
    getattr(handler, "previous_negev_ammo")["weapon_0"] = 100
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("negev", _packet("negev", 97))
    assert len(plays) == 3
    period = GUN_SOUND_PROFILES["negev"].fire_period
    assert delays == [pytest.approx(period), pytest.approx(2 * period)]


def test_an_implausible_ammo_drop_resyncs_silently_instead_of_spraying(monkeypatch):
    """掉得超过上限 ⇒ 账本对不上（捡了把弹夹更少的同型枪 / 卡顿后补包），只重记、不出声。"""
    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 30 - MAX_SHOTS_PER_PACKET - 1))

    assert plays == [], "一次错账喷了一梭子"
    # 账本必须已经跟上，否则下一包会拿旧数再算一次
    assert getattr(handler, "previous_ak47_ammo")["weapon_0"] == 30 - MAX_SHOTS_PER_PACKET - 1


def test_that_judge_sees_the_old_one_sound_per_packet_behaviour(monkeypatch):
    """空转守卫：把「按差值补发」换回「只播一声」，上面那条必须变红。"""
    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    monkeypatch.setattr(handler, "_schedule_extra_shots", lambda *_a, **_k: None)
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 28))
    assert len(plays) == 1, "撤掉补发之后居然还是 2 声 —— 上面那条判据在空转"


def test_a_new_packet_cancels_the_extra_shots_of_the_previous_one(monkeypatch):
    """两包的补发不许叠：新一包来了，上一包还没响的补发作废。"""
    handler, _m, _p, _r, _d, clock = _handler(monkeypatch, "ak47")
    pending = []

    class _Lazy(_CollectTimer):
        def start(self):
            pending.append(self)

    handler._extra_shot_timer_factory = _Lazy
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 28))
    assert len(pending) == 1 and not pending[0].cancelled

    clock["now"] += 0.13
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 26))
    assert pending[0].cancelled, "上一包的补发没被撤，两包的补发会叠在一起"


# ============================================================ ② 本机 steamid 只认 provider 段

def test_the_self_steamid_comes_from_the_provider_block_not_the_spectated_player(monkeypatch):
    """观战时 `player` 段整段是**被观战者**；首包用它自举会把别人的 ID 永久写进配置。"""
    from config import config

    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    monkeypatch.setattr(config, "player_steamid", "", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    monkeypatch.setattr(config, "save_config", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(handler, "_process_death_sound", lambda *_a, **_k: None)
    monkeypatch.setattr(handler, "_sync_death_baseline", lambda *_a, **_k: None)

    # 首包收在观战状态：我是 ME，正在看 OTHER 的视角。
    first = _packet("ak47", 30, steamid="OTHER", provider="ME")
    handler.process_data(first)
    assert config.player_steamid == "ME", "又把被观战者的 ID 当成自己的写进了配置"

    # 之后本人开枪必须照常出声
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler.process_data(_packet("ak47", 29, steamid="ME", provider="ME"))
    assert plays, "本人的包被当成观战给静音了"


def test_a_spectated_packet_is_still_muted(monkeypatch):
    """反面：provider 在场时，观战别人的包照样不出声（这道防护不许因为改法而松掉）。"""
    from config import config

    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    monkeypatch.setattr(config, "player_steamid", "ME", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    monkeypatch.setattr(handler, "_process_death_sound", lambda *_a, **_k: None)
    monkeypatch.setattr(handler, "_sync_death_baseline", lambda *_a, **_k: None)

    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler.process_data(_packet("ak47", 29, steamid="OTHER", provider="ME"))
    assert plays == [], "观战别人开枪也响了"


def test_the_bootstrap_does_not_persist_anything_without_a_provider_block(monkeypatch):
    """没有 provider 段就**不自举**：宁可不记，也不要记一个可能是别人的 ID。"""
    from config import config

    handler, _m, _p, _r, _d, _c = _handler(monkeypatch, "ak47")
    monkeypatch.setattr(config, "player_steamid", "", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    saved = []
    monkeypatch.setattr(config, "save_config", lambda *_a, **_k: saved.append(1), raising=False)
    monkeypatch.setattr(handler, "_process_death_sound", lambda *_a, **_k: None)
    monkeypatch.setattr(handler, "_sync_death_baseline", lambda *_a, **_k: None)

    handler.process_data(_packet("ak47", 30, steamid="OTHER"))
    assert config.player_steamid == ""
    assert saved == []


def test_the_source_reads_provider_steamid_for_self_identity():
    """AST 空转守卫：`_self_steamid` 必须读 provider 段，不许退回 player 段。"""
    src = (REPO / "gsi_handler_sounds.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_self_steamid"),
        None,
    )
    assert fn is not None, "`_self_steamid` 不在了 —— 自我识别又散回调用点了？"
    literals = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "provider" in literals
    assert "player" not in literals, "`_self_steamid` 里出现了 player 段 —— 观战时它是别人的数据"


# ============================================================ ③ 弹夹账本要清

def test_leaving_the_game_clears_the_ammo_ledger(monkeypatch):
    """死亡/回合切换/回菜单都走这里。账本不清 ⇒ 同槽位换一把弹夹更少的同型枪会响假枪声。"""
    handler, _m, _p, _r, _d, _c = _handler(monkeypatch, "ak47")
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_weapon_states()
    assert getattr(handler, "previous_ak47_ammo") == {}


def test_a_pickup_after_death_does_not_fire_a_phantom_shot(monkeypatch):
    """端到端：30 发的 AK → 死亡 → 捡起一把 28 发的 AK（同槽位键）⇒ 不许出声。

    ⚠ 这里**必须**用一个「合理」的掉发量（2 发）。拿 30 → 12 写是测不出来的：
    18 发先被 `_shots_in_this_packet` 的上限拦掉了 ——
    ⭐⭐⭐ 两条修复互相盖住时，先撞上的那条会把后一条的判据变成空转，
    而回退验证正是这么逮到它的（本批实测：那一刀撤了，判据照样绿）。
    """
    from config import config

    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    monkeypatch.setattr(config, "player_steamid", "ME", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    monkeypatch.setattr(handler, "_process_death_sound", lambda *_a, **_k: None)
    monkeypatch.setattr(handler, "_sync_death_baseline", lambda *_a, **_k: None)

    handler.process_data(_packet("ak47", 30, steamid="ME", provider="ME"))
    assert getattr(handler, "previous_ak47_ammo")["weapon_0"] == 30

    # 死亡：activity 不再是 playing
    handler.process_data({"player": {"activity": "menu", "steamid": "ME"}, "provider": {"steamid": "ME"}})

    handler.process_data(_packet("ak47", 28, steamid="ME", provider="ME"))
    assert plays == [], "捡起一把弹夹更少的同型枪，响了一发幻影枪声"


def test_that_judge_sees_the_phantom_shot_when_the_ledger_is_not_cleared(monkeypatch):
    """空转守卫：把清账撤掉，幻影枪声必须出现。"""
    from config import config

    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    monkeypatch.setattr(config, "player_steamid", "ME", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    monkeypatch.setattr(handler, "_process_death_sound", lambda *_a, **_k: None)
    monkeypatch.setattr(handler, "_sync_death_baseline", lambda *_a, **_k: None)
    # 只保留旧行为：清 active 标志，不清账本
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST

    def _old_reset():
        for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
            setattr(handler, f"is_{profile.gun_type}_active", False)

    monkeypatch.setattr(handler, "_reset_weapon_states", _old_reset)

    handler.process_data(_packet("ak47", 15, steamid="ME", provider="ME"))
    handler.process_data({"player": {"activity": "menu", "steamid": "ME"}, "provider": {"steamid": "ME"}})
    handler.process_data(_packet("ak47", 13, steamid="ME", provider="ME"))
    assert plays, "账本不清居然也没有幻影枪声 —— 上面那条判据在空转"


# ============================================================ ④ 压声撤回 / 第一个文件坏了

def test_a_shot_that_could_not_be_played_undoes_the_duck(monkeypatch):
    """压声先于播放。播不出来又不撤 ⇒ 玩家听到的是「原声被压掉、替换声没响」。"""
    handler, _m, plays, restores, _d, _c = _handler(monkeypatch, "ak47", play_result=False)
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 29))
    assert len(plays) == 1
    assert restores == [1], "这一发没播出来，压声却留着 —— 开枪几乎没声音"


def test_a_shot_that_played_keeps_the_duck(monkeypatch):
    """反面：正常出声时不许撤压声（否则原声立刻回来，等于没压）。"""
    handler, _m, plays, restores, _d, _c = _handler(monkeypatch, "ak47", play_result=True)
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 29))
    assert len(plays) == 1 and restores == []


def test_a_broken_first_file_does_not_silence_the_whole_style(tmp_path):
    """目录里第一个文件解码失败 ⇒ 以前整把枪静音，其余 4 个好取样一个都不装。"""
    from core.audio.audio_manager import AudioManager

    style_dir = tmp_path / "ak47" / "试离子AK"
    style_dir.mkdir(parents=True)
    for name in ("1.wav", "2.wav", "3.wav"):
        (style_dir / name).write_bytes(b"RIFF....WAVEfmt ")

    manager = AudioManager.__new__(AudioManager)
    manager._lock = __import__("threading").Lock()
    manager._sounds = {}
    manager._access_order = __import__("collections").OrderedDict()
    manager._max_sounds = 50
    manager.gun_sounds_dir = str(tmp_path)
    manager.logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None, debug=lambda *_a, **_k: None,
        warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None)
    manager._styles_scanned = True
    manager._on_loaded_callbacks = []
    manager._on_error_callbacks = []

    bad = {str(style_dir / "1.wav")}
    loaded: list[str] = []

    def fake_load(key, path, category, weapon_id=None, style=None):
        if path in bad:
            return False
        loaded.append(key)
        manager._sounds[key] = types.SimpleNamespace(loaded=True, sound=object(), path=path)
        manager._access_order[key] = None
        return True

    manager.load_sound = fake_load
    manager._style_enabled = lambda s: True
    manager._norm_style = lambda s: s
    manager._alias = lambda a, t: None
    manager._unload_other_styles_for_gun = lambda g, s: None

    assert manager.load_gun_sound("ak47", "试离子AK") is True, "第一个文件坏了就放弃了整套"
    # 规范键必须落在**能解码的那个**文件上，且剩下的都装成取样
    assert "gun-ak47-试离子AK" in loaded
    assert len(manager._variant_table()["gun-ak47-试离子AK"]) == 2


# ============================================================ ⑤ mixer 通道不许重号（全仓）

def _channel_literals_across_repo() -> dict[int, list[str]]:
    """全仓扫出所有写死的 mixer 通道号。

    ⭐ 既有那条判据只扫 `audio_manager` 里的 `_make_channel(N)`，
    而闪光音频写的是 `pygame.mixer.Channel(10)` —— 同一条 ch10 同时在枪声池里，
    两边互相硬切，而判据**结构上看不见**（批 103）。分母扩到全仓。
    """
    found: dict[int, list[str]] = {}
    skip = {"__pycache__", ".build", "tests", ".claude"}
    for path in REPO.rglob("*.py"):
        if any(part in skip for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name not in {"_make_channel", "Channel"}:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                found.setdefault(arg.value, []).append(f"{path.relative_to(REPO)}:{node.lineno}")
    return found


def test_no_two_features_hardcode_the_same_mixer_channel():
    found = _channel_literals_across_repo()
    assert found, "全仓一个写死的通道号都没扫到 —— 这条判据在空转"
    clashes = {idx: where for idx, where in found.items() if len(where) > 1}
    assert not clashes, f"同一条 mixer 通道被两处写死：{clashes}"


def test_every_hardcoded_channel_fits_the_configured_mixer_size():
    src = (REPO / "core" / "audio" / "audio_manager.py").read_text(encoding="utf-8")
    sizes = [
        node.args[0].value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_num_channels"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert sizes, "找不到 set_num_channels"
    size = max(sizes)
    for idx, where in _channel_literals_across_repo().items():
        assert idx < size, f"通道 {idx}（{where}）超出 mixer 的 {size} 条"


def test_the_flash_audio_is_not_on_a_gun_sound_channel():
    """闪光音频用的那条不许落在枪声池里 —— 循环播的闪光音频会把枪声掐掉。"""
    import flash_process_manager

    src = (REPO / "core" / "audio" / "audio_manager.py").read_text(encoding="utf-8")
    pool: list[int] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Attribute) and t.attr == "gun_sound_channels"]
        if not targets or not isinstance(node.value, ast.List):
            continue
        for item in node.value.elts:
            if (isinstance(item, ast.Call) and item.args
                    and isinstance(item.args[0], ast.Constant)):
                pool.append(item.args[0].value)
    assert pool, "没扫到枪声通道池"
    # awp_channel 也在池里（它是 ch0），单独加上
    pool.append(0)
    assert flash_process_manager.FLASH_AUDIO_CHANNEL not in pool, (
        f"闪光音频用的 ch{flash_process_manager.FLASH_AUDIO_CHANNEL} 在枪声池 {sorted(set(pool))} 里")


# ============================================================ ⑥ 假通道不许静默吞声

def test_a_shot_that_landed_on_a_fake_channel_reports_failure(monkeypatch):
    """拿不到真通道时要如实报失败 —— 以前它静默吞掉这一发还返回 True。"""
    import collections
    import threading as _th

    from core.audio.audio_manager import AudioManager, _NullChannel

    m = AudioManager.__new__(AudioManager)
    m._lock = _th.Lock()
    m._playback_lock = _th.RLock()
    m._sounds = {}
    m._access_order = collections.OrderedDict()
    m._max_sounds = 50
    m._active_channel_requests = {}
    m._compat_warned = set()
    m.logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None, debug=lambda *_a, **_k: None,
        warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None)
    m._on_loaded_callbacks = []
    m._on_error_callbacks = []
    events: list[dict] = []
    m._record_timeline_event = lambda **kw: events.append(kw)
    m._notify_error = lambda _msg: None

    info = types.SimpleNamespace(
        loaded=True, sound=types.SimpleNamespace(set_volume=lambda _v: None),
        path="x.wav", category="gun_sound", norm_gain=1.0, last_used=0.0)
    m._sounds["gun-ak47-styleX"] = info
    m._get_info = lambda _k: info
    m._pick_gun_sound_variant = lambda k: k
    m._resolve_play_volume = lambda *_a, **_k: 1.0
    m._select_channel = lambda _t: _NullChannel()
    m._map_channel_to_sfx_type = lambda _t: None

    assert m.play_sound("gun-ak47-styleX", channel_type="gun_sound") is False, (
        "落在假通道上的这一发被静默吞掉了，而 play_sound 还说成功")
    assert any(e.get("reason") == "channel_unavailable" for e in events), (
        "时间线上查不到这一发去哪了 —— 玩家只会觉得「有时候不响」")


def test_the_fake_channel_is_marked_so_it_can_be_recognised():
    """`is_null` 是识别它的唯一记号 —— 拿掉这个记号，上面那条判据就回到空转。"""
    from core.audio.audio_manager import _NullChannel

    assert getattr(_NullChannel, "is_null", False) is True
    # 它仍要满足通道的接口（别的调用点会问 get_busy / stop）
    ch = _NullChannel()
    assert ch.get_busy() is False
    assert ch.stop() is None


# ============================================================ ⑦ 积压的包不许补播

def test_a_packet_that_waited_too_long_updates_the_ledger_but_makes_no_sound(monkeypatch):
    """处理线程卡顿后补跑积压 ⇒ 补播一串迟到的枪声比漏掉它们更难听。"""
    from core.gun_sound_profiles import STALE_PACKET_SECONDS
    from gsi_server import PACKET_RECV_KEY

    handler, _m, plays, _r, _d, clock = _handler(monkeypatch, "ak47")
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30

    data = _packet("ak47", 29)
    data[PACKET_RECV_KEY] = clock["now"] - (STALE_PACKET_SECONDS + 0.2)
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", data)

    assert plays == [], "一个躺了半秒多的包还在出声"
    # ⭐ 账本必须跟上：否则下一包会拿一个更旧的数去算差值，攒出一串假开火
    assert getattr(handler, "previous_ak47_ammo")["weapon_0"] == 29


def test_a_fresh_packet_still_plays(monkeypatch):
    """反面：带着时刻戳的新包照常出声（这道闸不许把正常的包也拦掉）。"""
    from gsi_server import PACKET_RECV_KEY

    handler, _m, plays, _r, _d, clock = _handler(monkeypatch, "ak47")
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    data = _packet("ak47", 29)
    data[PACKET_RECV_KEY] = clock["now"] - 0.05
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", data)
    assert len(plays) == 1


def test_a_packet_without_a_timestamp_is_treated_as_fresh(monkeypatch):
    """没有时刻戳（判据造的包、别的入口）当新的 —— 不许因为缺字段就整条静音。"""
    handler, _m, plays, _r, _d, _c = _handler(monkeypatch, "ak47")
    getattr(handler, "previous_ak47_ammo")["weapon_0"] = 30
    handler._reset_gun_frame_flags()
    handler._process_gun_sound("ak47", _packet("ak47", 29))
    assert len(plays) == 1


def test_the_server_stamps_every_packet_it_accepts():
    """AST：入队那一步必须真的打时刻戳，否则上面那几条永远绿。"""
    import ast

    src = (REPO / "gsi_server.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "game_state_update"
    )
    stamped = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Subscript) for t in n.targets)
    ]
    assert stamped, "`game_state_update` 里没有给包打时刻戳那一步"
    src_fn = ast.unparse(fn)
    assert "PACKET_RECV_KEY" in src_fn and "monotonic" in src_fn
