# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""UP-060 回归：启动预载必须受 LRU 上限约束，且高频类不能被低频类挤掉。

改之前实测（171 个灌入 / 上限 50）：
  · 121 个解码完立刻被淘汰 —— 71% 的功白做；
  · 淘汰的是**先装进去的**，于是击杀音效 0 个留存，
    而 C4 / 血量警告 / 回合音效这些最低频的 100% 占着缓存。
  重度用户因此每次击杀都要现场解码，延迟砸在最要紧的那一刻。

判据落在**产品代码的真实调用**上：直接跑 `load_all_enabled_sounds()`，
用假的 loader 记录它到底请求了哪些、请求了几次，
而缓存与淘汰走的是真实的 `_store` / `_evict_lru_locked`。
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from threading import Lock

import pytest

from core.audio.audio_manager import AudioManager


class _FakeSound:
    """`_evict_lru_locked` 会对被淘汰项调 stop()。"""

    def stop(self):
        pass


class _SilentLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


WEAPONS = [f"weapon_{i}" for i in range(37)]


def _make_manager():
    """不跑 __init__（那会初始化 mixer、占用音频设备），只搭出 LRU 需要的字段。"""
    am = AudioManager.__new__(AudioManager)
    am.logger = _SilentLogger()
    am._lock = Lock()
    am._sounds = {}
    am._access_order = OrderedDict()
    am._max_sounds = 50
    am._styles_scanned = True
    return am


class _HeavyConfig:
    """重度用户：四个按武器分类的音效全开，外加所有低基数类。"""

    kill_sound_enabled = True
    kill_voice_enabled = True
    switch_weapon_sound_enabled = True
    reload_sound_enabled = True
    death_sound_enabled = True
    death_sound_style = "s"
    grenade_sound_enabled = True
    c4_sound_enabled = True
    c4_sound_style = "s"
    health_warning_enabled = True
    health_warning_style = "s"
    round_sound_enabled = True
    round_start_style = "s"
    round_action_style = "s"
    round_win_style = "s"
    round_lose_style = "s"
    round_mvp_style = "s"
    gun_sound_enabled = False  # 走 is_gun_sound_master_enabled，单独控制

    weapon_kill_sounds = {w: "s" for w in WEAPONS}
    weapon_kill_voices = {w: "s" for w in WEAPONS}
    weapon_switch_sounds = {w: "s" for w in WEAPONS}
    weapon_reload_sounds = {w: "s" for w in WEAPONS}
    grenade_sound_styles = {f"g{i}": "s" for i in range(6)}


@pytest.fixture
def heavy(monkeypatch):
    """把各 loader 换成"只记账 + 走真实 _store"的假实现。"""
    import config as config_mod

    am = _make_manager()
    calls = Counter()

    def make_loader(category, arity):
        def loader(*args, **kwargs):
            calls[category] += 1
            key = f"{category}:{args[0] if args else category}"
            am._store(key, _FakeSound(), f"/fake/{key}.wav", category)
            return True
        return loader

    for name, category in (
        ("load_kill_sound_for_weapon", "kill_sound"),
        ("load_kill_voice_for_weapon", "kill_voice"),
        ("load_switch_weapon_sound", "switch_weapon"),
        ("load_reload_sound", "reload"),
        ("load_death_sound", "death"),
        ("load_gun_sound", "gun_sound"),
        ("load_grenade_sound", "grenade"),
        ("load_c4_sound", "c4"),
        ("load_health_warning_sound", "health_warning"),
        ("load_round_sound", "round"),
    ):
        monkeypatch.setattr(am, name, make_loader(category, 2), raising=False)

    monkeypatch.setattr(am, "ensure_styles_scanned", lambda: None, raising=False)
    monkeypatch.setattr(am, "_style_enabled", lambda s: str(s) not in ("0", "", "None"),
                        raising=False)
    monkeypatch.setattr(config_mod, "config", _HeavyConfig(), raising=False)

    am.load_all_enabled_sounds()
    return am, calls


def test_preload_never_exceeds_cache_capacity(heavy):
    """解码次数不该超过缓存装得下的量——超出的部分是纯白工。"""
    am, calls = heavy
    total_decodes = sum(calls.values())
    assert total_decodes <= am._max_sounds, (
        f"预载解码了 {total_decodes} 个，而缓存只装得下 {am._max_sounds} 个："
        f"多出的 {total_decodes - am._max_sounds} 次解码做完就被淘汰了"
    )


def test_highest_frequency_category_survives_preload(heavy):
    """击杀音效是全局最高频事件，绝不能被低频类挤出缓存。"""
    am, _calls = heavy
    kept = Counter(info.category for info in am._sounds.values())
    assert kept["kill_sound"] > 0, (
        "击杀音效在预载后一个都没留在缓存里——最高频的事件反而每次都要现场解码。"
        f"当前缓存构成：{dict(kept)}"
    )


def test_low_cardinality_categories_all_get_cached(heavy):
    """低基数类数量固定且每类只有几个，应当每一类都有覆盖。"""
    am, _calls = heavy
    kept = Counter(info.category for info in am._sounds.values())
    for category in ("round", "c4", "health_warning", "grenade", "death"):
        assert kept[category] > 0, f"{category} 一个都没缓存到：{dict(kept)}"


def test_light_config_still_loads_everything(monkeypatch):
    """配置在上限内的用户（实测本机 36 个）加载集合必须与改前完全一致。"""
    import config as config_mod

    am = _make_manager()
    calls = Counter()

    def make_loader(category):
        def loader(*args, **kwargs):
            calls[category] += 1
            am._store(f"{category}:{args[0] if args else category}", _FakeSound(),
                      "/fake.wav", category)
            return True
        return loader

    for name, category in (
        ("load_kill_sound_for_weapon", "kill_sound"),
        ("load_kill_voice_for_weapon", "kill_voice"),
        ("load_switch_weapon_sound", "switch_weapon"),
        ("load_reload_sound", "reload"),
        ("load_death_sound", "death"),
        ("load_gun_sound", "gun_sound"),
        ("load_grenade_sound", "grenade"),
        ("load_c4_sound", "c4"),
        ("load_health_warning_sound", "health_warning"),
        ("load_round_sound", "round"),
    ):
        monkeypatch.setattr(am, name, make_loader(category), raising=False)
    monkeypatch.setattr(am, "ensure_styles_scanned", lambda: None, raising=False)
    monkeypatch.setattr(am, "_style_enabled", lambda s: str(s) not in ("0", "", "None"),
                        raising=False)

    class _LightConfig(_HeavyConfig):
        # 只开击杀音效的 36 把武器 —— 与本机真实配置同规模
        kill_voice_enabled = False
        switch_weapon_sound_enabled = False
        reload_sound_enabled = False
        grenade_sound_enabled = False
        c4_sound_enabled = False
        health_warning_enabled = False
        round_sound_enabled = False
        death_sound_enabled = False
        weapon_kill_sounds = {w: "s" for w in WEAPONS[:36]}

    monkeypatch.setattr(config_mod, "config", _LightConfig(), raising=False)
    am.load_all_enabled_sounds()

    assert calls["kill_sound"] == 36, (
        f"上限内的配置本该全部装进来，实际只装了 {calls['kill_sound']}/36"
    )
