"""分类音量(#3) + 响度归一(#6) 的回归测试。

覆盖：
- AudioManager._resolve_play_volume：主音量 × 分类倍率 × 归一增益，回合音效不叠加分类倍率，夹紧 [0,1]。
- AudioManager._apply_loudness_normalization：响清音衰减(set_volume)、轻音放大(重建样本)、关闭时 no-op。
- config 的 category_volumes / audio_loudness_normalize_enabled 存盘+读回。

注意：conftest 已把配置目录重定向到临时目录，本测试不会污染用户真实配置。
"""
import json
import os
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from core.audio.audio_manager import AudioManager


@pytest.fixture(scope="module")
def manager():
    return AudioManager()


def _make_stereo_sound(amp: int):
    """生成一个 220Hz 正弦 int16 Sound，峰值约为 amp，声道数与当前 mixer 对齐。"""
    init = pygame.mixer.get_init()
    channels = init[2] if init else 2
    n = 2000
    t = np.linspace(0, 1, n, endpoint=False)
    wave = (np.sin(2 * np.pi * 220 * t) * amp).astype(np.int16)
    arr = wave if channels == 1 else np.column_stack([wave] * channels)
    return pygame.sndarray.make_sound(np.ascontiguousarray(arr))


# ----------------------------- #3 分类音量 -----------------------------

def test_resolve_play_volume_category_multiplier(manager):
    cfg = SimpleNamespace(
        volume=1.0,
        round_sound_volume=0.5,
        category_volumes={"gun_sound": 0.5, "kill_sound": 1.0, "kill_voice": 0.25},
    )
    assert manager._resolve_play_volume(cfg, "gun_sound") == pytest.approx(0.5)
    assert manager._resolve_play_volume(cfg, "kill_sound") == pytest.approx(1.0)
    # kill_voice 也走分类倍率
    assert manager._resolve_play_volume(cfg, "kill_voice") == pytest.approx(0.25)
    # 回合音效用独立音量，不叠加分类倍率
    assert manager._resolve_play_volume(cfg, "round_sound") == pytest.approx(0.5)


def test_resolve_play_volume_master_norm_and_clamp(manager):
    cfg = SimpleNamespace(volume=0.8, round_sound_volume=1.0, category_volumes={"gun_sound": 0.5})
    info = SimpleNamespace(norm_gain=0.5)
    # 0.8 * 0.5 * 0.5 = 0.2
    assert manager._resolve_play_volume(cfg, "gun_sound", info) == pytest.approx(0.2)
    # 上限夹紧到 1.0
    cfg2 = SimpleNamespace(volume=1.0, round_sound_volume=1.0, category_volumes={})
    info2 = SimpleNamespace(norm_gain=5.0)
    assert manager._resolve_play_volume(cfg2, "kill_sound", info2) == pytest.approx(1.0)


def test_resolve_play_volume_handles_missing_fields(manager):
    # category_volumes 缺失/类型异常时不应抛错
    cfg = SimpleNamespace(volume=0.6, round_sound_volume=0.6, category_volumes=None)
    assert manager._resolve_play_volume(cfg, "gun_sound") == pytest.approx(0.6)


# ----------------------------- #6 响度归一 -----------------------------

def test_loudness_normalization_attenuates_loud(manager):
    from config import config
    prev, prev_t = config.audio_loudness_normalize_enabled, config.audio_loudness_target
    config.audio_loudness_normalize_enabled = True
    config.audio_loudness_target = 0.2
    try:
        loud = _make_stereo_sound(30000)
        out, gain = manager._apply_loudness_normalization(loud)
        assert gain < 1.0       # 大响度 → 衰减
        assert out is loud      # 不重建，靠 set_volume 衰减
    finally:
        config.audio_loudness_normalize_enabled, config.audio_loudness_target = prev, prev_t


def test_loudness_normalization_boosts_quiet(manager):
    from config import config
    prev, prev_t = config.audio_loudness_normalize_enabled, config.audio_loudness_target
    config.audio_loudness_normalize_enabled = True
    config.audio_loudness_target = 0.2
    try:
        quiet = _make_stereo_sound(2000)
        out, gain = manager._apply_loudness_normalization(quiet)
        assert gain == 1.0          # 放大已烘焙进样本
        assert out is not quiet     # 重建了 Sound
        arr = pygame.sndarray.array(out).astype(np.float64)
        rms = float(np.sqrt(np.mean(np.square(arr)))) / 32768.0
        assert rms == pytest.approx(0.2, abs=0.03)  # 拉到接近目标
    finally:
        config.audio_loudness_normalize_enabled, config.audio_loudness_target = prev, prev_t


def test_loudness_normalization_disabled_is_noop(manager):
    from config import config
    prev = config.audio_loudness_normalize_enabled
    config.audio_loudness_normalize_enabled = False
    try:
        s = _make_stereo_sound(10000)
        out, gain = manager._apply_loudness_normalization(s)
        assert out is s and gain == 1.0
    finally:
        config.audio_loudness_normalize_enabled = prev


# ----------------------------- 配置持久化 -----------------------------

def test_category_volume_config_roundtrip():
    from config import config, get_config_dir, CONFIG_FILENAME
    config.category_volumes["gun_sound"] = 0.42
    config.category_volumes["switch_weapon"] = 0.7
    config.audio_loudness_normalize_enabled = True
    config.audio_loudness_target = 0.25
    config.save_config_now()

    # 存盘内容正确
    path = os.path.join(get_config_dir(), CONFIG_FILENAME)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["category_volumes"]["gun_sound"] == pytest.approx(0.42)
    assert data["category_volumes"]["switch_weapon"] == pytest.approx(0.7)
    assert data["audio_loudness_normalize_enabled"] is True
    assert data["audio_loudness_target"] == pytest.approx(0.25)

    # 改内存值后从磁盘读回应恢复
    config.category_volumes["gun_sound"] = 0.0
    config.audio_loudness_normalize_enabled = False
    config.load_config()
    assert config.category_volumes["gun_sound"] == pytest.approx(0.42)
    assert config.audio_loudness_normalize_enabled is True


def test_voice_output_microphone_persisted():
    """回归:之前 UI 写 voice_output_microphone 但既不在 defaults / load / save 里,
    导致用户选的麦克风每次重启就丢。修复后应能完整 round-trip。"""
    import json
    from config import config, get_config_dir, CONFIG_FILENAME

    # 字段必须存在 + 默认是空字符串("默认")
    assert hasattr(config, "voice_output_microphone")
    config.voice_output_microphone = "SteelSeries Sonar Mic"
    config.save_config_now()

    path = os.path.join(get_config_dir(), CONFIG_FILENAME)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("voice_output_microphone") == "SteelSeries Sonar Mic"

    # 内存抹掉再 load_config 应该恢复
    config.voice_output_microphone = ""
    config.load_config()
    assert config.voice_output_microphone == "SteelSeries Sonar Mic"
