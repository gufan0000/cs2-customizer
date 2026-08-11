# SPDX-License-Identifier: GPL-3.0-or-later
"""Single runtime audio kernel with 2.x compatibility."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Dict, List, Optional

import pygame

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_audio_by_stem,
    find_first_audio_file,
    list_style_dirs_with_audio,
    list_unique_audio_stems,
)
from core.gun_sound_profiles import (
    SUPPORTED_GUN_SOUND_PROFILE_LIST,
    gun_sound_style_enabled,
    is_gun_sound_master_enabled,
)
from core.audio.audio_event_timeline import AudioEvent, get_audio_event_timeline
from core.audio.audio_playback_policy import PlaybackRequest, decide_channel_action, resolve_priority
from core.utils.logger import get_logger


class _NullChannel:
    def play(self, *_args, **_kwargs):
        return None

    def stop(self):
        return None

    def get_busy(self):
        return False


@dataclass
class AudioInfo:
    path: str
    category: str
    weapon_id: Optional[str] = None
    style: Optional[str] = None
    loaded: bool = False
    sound: Optional[pygame.mixer.Sound] = None
    last_used: float = 0.0
    norm_gain: float = 1.0  # 响度归一增益：<1 播放时衰减；>1 已通过重建样本预放大并回落为 1


class _CompatMap(Mapping):
    def __init__(self, manager: "AudioManager", include_category: str | None = None, exclude_category: str | None = None):
        self._manager = manager
        self._include_category = include_category
        self._exclude_category = exclude_category

    def _ok(self, info: AudioInfo) -> bool:
        if not info.loaded or not info.sound:
            return False
        if self._include_category and info.category != self._include_category:
            return False
        if self._exclude_category and info.category == self._exclude_category:
            return False
        return True

    def __getitem__(self, key: str):
        with self._manager._lock:
            info = self._manager._sounds.get(key)
            if not info or not self._ok(info):
                raise KeyError(key)
            return info.sound

    def __iter__(self):
        with self._manager._lock:
            keys = [k for k, info in self._manager._sounds.items() if self._ok(info)]
        return iter(keys)

    def __len__(self):
        with self._manager._lock:
            return sum(1 for info in self._manager._sounds.values() if self._ok(info))


class AudioManager:
    ROUND_TYPES = ("start", "action", "win", "lose", "mvp")
    GRENADE_TYPES = ("hegrenade", "flashbang", "smoke", "molotov", "incgrenade", "decoy")
    GUN_TYPES = tuple(profile.gun_type for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST)
    DISABLED_STYLES = {"", "0", "none", "off", "disabled", "不启用", "未启用"}

    def __init__(self):
        self.logger = get_logger("AudioManager")
        self._lock = Lock()
        self._sounds: Dict[str, AudioInfo] = {}
        self._access_order: OrderedDict[str, None] = OrderedDict()
        self._max_sounds = 50
        self._on_loaded_callbacks: List[Callable] = []
        self._on_error_callbacks: List[Callable] = []
        self._compat_warned: set[str] = set()
        self._volume = 0.7
        self._styles_scanned = False

        self._mixer_ready = self._init_mixer()

        self.awp_channel = self._make_channel(0)
        self.gun_sound_channels = [
            self.awp_channel,
            self._make_channel(9),
            self._make_channel(10),
        ]
        self._gun_sound_channel_index = 0
        self.kill_sound_channel = self._make_channel(1)
        self.kill_voice_channel = self._make_channel(2)
        self.switch_weapon_channel = self._make_channel(3)
        # 切枪音效多通道池：解决"切刀→快速切枪"时第二个切换音被丢的问题
        # （单通道 + allow_preempt=False 会被策略判为 drop）。ch11/ch12 是空闲通道，
        # 让相邻的两次切换音能叠着播、互不顶掉。
        self.switch_weapon_channels = [
            self.switch_weapon_channel,
            self._make_channel(11),
            self._make_channel(12),
        ]
        self._switch_weapon_channel_index = 0
        self.reload_channel = self._make_channel(4)
        self.grenade_sound_channel = self._make_channel(5)
        self.c4_sound_channel = self._make_channel(6)
        self.health_warning_channel = self._make_channel(7)
        self.round_sound_channel = self._make_channel(8)
        # v2.2.1: 死亡音效独立通道——旧版与击杀/爆头共用 ch1，
        # 互杀(trade kill)时自己的击杀声(100)占道，死亡声(40)被策略 drop 吞掉。
        # 独立通道后两声可同时播放，互不影响。
        self.death_sound_channel = self._make_channel(13)

        self._sounds_view = _CompatMap(self, exclude_category="kill_voice")
        self._voices_view = _CompatMap(self, include_category="kill_voice")

        from resource_manager import ResourceManager

        self.audio_base_dir = ResourceManager.get_app_data_path("resources/audio")
        self.kill_sounds_dir = os.path.join(self.audio_base_dir, "kill_sounds")
        self.weapon_sounds_dir = os.path.join(self.audio_base_dir, "weapon_kill_sounds")
        self.kill_voices_dir = os.path.join(self.audio_base_dir, "kill_voices")
        self.weapon_voices_dir = os.path.join(self.audio_base_dir, "weapon_kill_voices")
        self.death_sounds_dir = os.path.join(self.audio_base_dir, "death")
        self.switch_weapons_dir = os.path.join(self.audio_base_dir, "switch_weapons")
        self.reload_sounds_dir = os.path.join(self.audio_base_dir, "reload_sounds")
        self.reload_dir = self.reload_sounds_dir
        self.grenade_sounds_dir = os.path.join(self.audio_base_dir, "grenade_sounds")
        self.c4_sounds_dir = os.path.join(self.audio_base_dir, "c4_sounds")
        self.health_warning_dir = os.path.join(self.audio_base_dir, "health_warning")
        self.round_sounds_dir = os.path.join(self.audio_base_dir, "round_sounds")
        self.gun_sounds_dir = os.path.join(self.audio_base_dir, "gun_sounds")

        self.kill_sound_styles: List[str] = []
        self.kill_voice_styles: List[str] = []
        self.weapon_kill_sound_styles: Dict[str, List[str]] = {}
        self.weapon_kill_voice_styles: Dict[str, List[str]] = {}
        self.death_sound_styles: List[str] = []
        self.death_styles: List[str] = self.death_sound_styles
        self.switch_weapon_styles: Dict[str, List[str]] = {}
        self.reload_styles: Dict[str, List[str]] = {}
        self.grenade_sound_styles: Dict[str, List[str]] = {}
        self.c4_sound_styles: List[str] = []
        self.health_warning_styles: List[str] = []
        self.round_start_styles: List[str] = []
        self.round_action_styles: List[str] = []
        self.round_win_styles: List[str] = []
        self.round_lose_styles: List[str] = []
        self.round_mvp_styles: List[str] = []
        self.gun_sound_styles: Dict[str, List[str]] = {w: [] for w in self.GUN_TYPES}

        self.fade_timers: Dict[tuple[str, object], threading.Timer] = {}
        self.fade_threads: Dict[tuple[str, object], threading.Thread] = {}
        # QA-016: 通道归属令牌。淡出线程只在"这条通道还是我的"时才动手。
        # 键是通道对象（__init__ 里固定造的那十几个，集合有界，不会涨）。
        self.fade_owner: Dict[object, int] = {}
        self._fade_seq = 0
        self._active_channel_requests: Dict[str, PlaybackRequest] = {}
        # 保护"读活跃请求→决策→播放→写回"整段：GSI处理线程/UI试听/语音转发
        # 可能并发 play_sound 同一通道，锁外决策会重复播放或漏抢占
        self._playback_lock = threading.Lock()
        self._timeline = get_audio_event_timeline()

    def _init_mixer(self) -> bool:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(16)
            return True
        except Exception as e:
            self.logger.error(f"Pygame mixer init failed: {e}")
            return False

    def _make_channel(self, idx: int):
        if not self._mixer_ready:
            return _NullChannel()
        try:
            return pygame.mixer.Channel(idx)
        except Exception:
            return _NullChannel()

    @property
    def sounds(self):
        self._warn_deprecated_once("sounds", "audio_manager.sounds is compatibility view")
        return self._sounds_view

    @property
    def voices(self):
        self._warn_deprecated_once("voices", "audio_manager.voices is compatibility view")
        return self._voices_view

    def _warn_deprecated_once(self, token: str, message: str):
        if token in self._compat_warned:
            return
        self._compat_warned.add(token)
        self.logger.warning(f"[AudioCompat][DEPRECATED] {message}")

    def _norm_style(self, style) -> str:
        if style is None:
            return ""
        return str(style).strip()

    def _resolve_style_value(self, style) -> str:
        if isinstance(style, dict):
            if style.get("enabled") is False:
                return "0"
            return self._norm_style(style.get("style", ""))
        return self._norm_style(style)

    def _style_enabled(self, style) -> bool:
        return self._resolve_style_value(style).lower() not in self.DISABLED_STYLES

    def register_callback(self, event: str, callback: Callable):
        if event == "loaded":
            self._on_loaded_callbacks.append(callback)
        elif event == "error":
            self._on_error_callbacks.append(callback)

    def _notify_loaded(self, key: str, category: str):
        for cb in self._on_loaded_callbacks:
            try:
                cb(key, category)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    def _notify_error(self, message: str):
        self.logger.error(message)
        for cb in self._on_error_callbacks:
            try:
                cb(message)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    def _evict_lru_locked(self):
        if not self._access_order:
            return
        lru_key = next(iter(self._access_order))
        info = self._sounds.pop(lru_key, None)
        self._access_order.pop(lru_key, None)
        if info and info.sound:
            # v2.2.1: 别名与规范键共享同一 AudioInfo/Sound 对象——
            # 若仍有存活的别名/规范键指向该 info，stop() 会截断它正在播放的声音。
            # 只有当没有任何键再引用这个 info 时才 stop。
            still_referenced = any(other is info for other in self._sounds.values())
            if not still_referenced:
                try:
                    info.sound.stop()
                except Exception:
                    pass

    def _store(self, key: str, sound_obj, path: str, category: str, weapon_id=None, style=None):
        with self._lock:
            if len(self._sounds) >= self._max_sounds and key not in self._sounds:
                self._evict_lru_locked()
            self._sounds[key] = AudioInfo(
                path=path,
                category=category,
                weapon_id=weapon_id,
                style=style,
                loaded=True,
                sound=sound_obj,
                last_used=time.time(),
            )
            self._access_order[key] = None
            self._access_order.move_to_end(key)

    def _alias(self, alias_key: str, target_key: str):
        if alias_key == target_key:
            return
        with self._lock:
            info = self._sounds.get(target_key)
            if not info:
                return
            self._sounds[alias_key] = info
            self._access_order[alias_key] = None
            self._access_order.move_to_end(alias_key)

    def _load_first_available_generic_kill_sound(self, number: int, is_headshot: bool = False) -> bool:
        n = int(number)
        self.ensure_styles_scanned()

        for style in self.kill_sound_styles:
            if not self.load_kill_sound_generic(style, n, is_headshot=is_headshot):
                continue
            self._alias(f"kill-{n}", f"kill-{style}-{n}")
            if is_headshot and self._get_info(f"kill-{style}-{n}-headshot"):
                self._alias(f"kill-{n}-headshot", f"kill-{style}-{n}-headshot")
            return True

        return False

    def _load_first_available_generic_kill_voice(self, count: int, is_headshot: bool = False) -> bool:
        c = int(count)
        self.ensure_styles_scanned()

        for style in self.kill_voice_styles:
            if not self.load_kill_voice(style, is_headshot=is_headshot, count=c):
                continue
            self._alias(f"voice-{c}", f"voice-{style}-{c}")
            if is_headshot and self._get_info(f"voice-{style}-{c}-headshot"):
                self._alias(f"voice-{c}-headshot", f"voice-{style}-{c}-headshot")
            return True

        return False

    def load_sound(self, key: str, path: str, category: str, weapon_id: str = None, style: str = None) -> bool:
        if not path or not os.path.isfile(path):
            self._notify_error(f"Audio file missing: {path}")
            self._record_timeline_event(
                action="load",
                key=key,
                channel_type=category,
                event_type="load",
                reason="file_missing",
                success=False,
                meta={"path": path, "category": category},
            )
            return False
        try:
            if not self._mixer_ready:
                self._notify_error("Pygame mixer unavailable")
                self._record_timeline_event(
                    action="load",
                    key=key,
                    channel_type=category,
                    event_type="load",
                    reason="mixer_unavailable",
                    success=False,
                    meta={"path": path, "category": category},
                )
                return False
            sound = pygame.mixer.Sound(path)
            sound, norm_gain = self._apply_loudness_normalization(sound)
            sound.set_volume(self._volume)
            self._store(key, sound, path, category, weapon_id=weapon_id, style=style)
            if norm_gain != 1.0:
                with self._lock:
                    _info = self._sounds.get(key)
                    if _info is not None:
                        _info.norm_gain = float(norm_gain)
            self._notify_loaded(key, category)
            self._record_timeline_event(
                action="load",
                key=key,
                channel_type=category,
                event_type="load",
                reason="loaded",
                success=True,
                meta={"path": path, "category": category},
            )
            return True
        except Exception as e:
            self._notify_error(f"Load failed {path}: {e}")
            self._record_timeline_event(
                action="load",
                key=key,
                channel_type=category,
                event_type="load",
                reason=f"load_failed:{e}",
                success=False,
                meta={"path": path, "category": category},
            )
            return False

    def _map_channel_to_sfx_type(self, channel_type: str):
        mapping = {
            "kill_sound": "kill_sound",
            "kill_voice": "kill_voice",
            "gun_sound": "gun_sound",
            "awp": "gun_sound",
            "switch_weapon": "switch_weapon",
            "reload": "reload_sound",
            "death": "death_sound",
            # v2.2.1 起死亡音效走独立通道，channel_type 传的是 "death_sound"，
            # 缺这个键会导致"被击杀音效"分类音量滑块对死亡音效无效
            "death_sound": "death_sound",
            "grenade_sound": "special_sound",
            "c4_sound": "special_sound",
            "health_warning": "special_sound",
            "round_sound": "round_sound",
        }
        return mapping.get(channel_type)

    def _resolve_play_volume(self, config, channel_type: str, info=None) -> float:
        """计算最终播放音量。

        最终音量 = 主音量(回合音效用其独立音量) × 分类倍率 × 响度归一增益，夹紧到 [0,1]。
        回合音效已有独立音量(round_sound_volume)，不再叠加分类倍率，避免双重缩放。
        """
        if channel_type == "round_sound":
            base = getattr(config, "round_sound_volume", self._volume)
        else:
            base = getattr(config, "volume", self._volume)
        try:
            base = float(base)
        except (TypeError, ValueError):
            base = self._volume

        mult = 1.0
        if channel_type != "round_sound":
            cat = self._map_channel_to_sfx_type(channel_type)
            if cat:
                cat_vols = getattr(config, "category_volumes", None)
                if isinstance(cat_vols, dict):
                    try:
                        mult = float(cat_vols.get(cat, 1.0))
                    except (TypeError, ValueError):
                        mult = 1.0
        mult = max(0.0, min(1.0, mult))

        norm = 1.0
        if info is not None:
            try:
                norm = float(getattr(info, "norm_gain", 1.0))
            except (TypeError, ValueError):
                norm = 1.0
            norm = max(0.0, norm)

        return max(0.0, min(1.0, base * mult * norm))

    def _apply_loudness_normalization(self, sound):
        """按 RMS 把单个音频拉到目标响度，返回 (sound, norm_gain)。

        - gain<=1：返回 (原 sound, gain)，播放时用 set_volume 衰减（pygame 原生，安全）。
        - gain>1：用 numpy 放大样本并重建 Sound（带削波保护，避免破音），返回 (新 sound, 1.0)。
        默认关闭；任何异常一律回退 (原 sound, 1.0)，绝不影响正常播放。
        """
        from config import config

        if not bool(getattr(config, "audio_loudness_normalize_enabled", False)):
            return sound, 1.0
        try:
            import numpy as np
            import pygame.sndarray as sndarray

            arr = sndarray.array(sound)
            if arr.size == 0:
                return sound, 1.0
            data = arr.astype(np.float64)
            rms = float(np.sqrt(np.mean(np.square(data)))) / 32768.0
            if rms <= 1e-6:
                return sound, 1.0

            target = getattr(config, "audio_loudness_target", 0.2)
            try:
                target = max(0.02, min(1.0, float(target)))
            except (TypeError, ValueError):
                target = 0.2

            gain = target / rms
            gain = max(0.1, min(8.0, gain))  # 限幅，避免把噪声放大或过度衰减

            if gain <= 1.0:
                return sound, gain  # 衰减交给播放时 set_volume

            peak = float(np.max(np.abs(data)))
            if peak <= 0:
                return sound, 1.0
            max_gain_no_clip = (0.99 * 32767.0) / peak
            applied = min(gain, max_gain_no_clip)
            if applied <= 1.0:
                return sound, 1.0  # 已接近满幅，无法再放大

            amplified = np.clip(data * applied, -32768, 32767).astype(np.int16)
            new_sound = sndarray.make_sound(np.ascontiguousarray(amplified))
            return new_sound, 1.0
        except Exception as e:
            self.logger.debug(f"响度归一跳过: {e}")
            return sound, 1.0

    def _select_gun_sound_channel(self):
        channels = self.gun_sound_channels or [self.awp_channel]
        if not channels:
            return self.awp_channel

        start = self._gun_sound_channel_index % len(channels)
        for offset in range(len(channels)):
            index = (start + offset) % len(channels)
            channel = channels[index]
            busy = bool(channel and hasattr(channel, "get_busy") and channel.get_busy())
            if not busy:
                self._gun_sound_channel_index = (index + 1) % len(channels)
                return channel

        channel = channels[start]
        self._gun_sound_channel_index = (start + 1) % len(channels)
        return channel

    def _select_switch_weapon_channel(self):
        channels = getattr(self, "switch_weapon_channels", None) or [self.switch_weapon_channel]
        if not channels:
            return self.switch_weapon_channel

        start = self._switch_weapon_channel_index % len(channels)
        for offset in range(len(channels)):
            index = (start + offset) % len(channels)
            channel = channels[index]
            busy = bool(channel and hasattr(channel, "get_busy") and channel.get_busy())
            if not busy:
                self._switch_weapon_channel_index = (index + 1) % len(channels)
                return channel

        channel = channels[start]
        self._switch_weapon_channel_index = (start + 1) % len(channels)
        return channel

    def _select_channel(self, channel_type: str):
        if channel_type in {"awp", "gun_sound"}:
            return self._select_gun_sound_channel()
        if channel_type == "switch_weapon":
            return self._select_switch_weapon_channel()
        if channel_type == "reload":
            return self.reload_channel
        if channel_type == "grenade_sound":
            return self.grenade_sound_channel
        if channel_type == "c4_sound":
            return self.c4_sound_channel
        if channel_type == "health_warning":
            return self.health_warning_channel
        if channel_type == "round_sound":
            return self.round_sound_channel
        if channel_type == "death_sound":
            return self.death_sound_channel
        return self.kill_sound_channel

    def _channel_state_key(self, channel_type: str, channel_obj) -> str:
        if channel_obj is None:
            return channel_type or "default"
        return f"{channel_type or 'custom'}:{id(channel_obj)}"

    def _record_timeline_event(
        self,
        *,
        action: str,
        key: str,
        channel_type: str,
        event_type: str,
        reason: str = "",
        success: bool = True,
        meta: Dict[str, object] | None = None,
    ):
        from config import config

        if not bool(getattr(config, "audio_event_timeline_enabled", True)):
            return
        try:
            self._timeline.record(
                AudioEvent(
                    timestamp=time.time(),
                    action=action,
                    key=key,
                    channel_type=channel_type,
                    event_type=event_type or "",
                    reason=reason,
                    success=success,
                    meta=meta or {},
                )
            )
        except Exception:
            pass

    def _get_info(self, key: str):
        with self._lock:
            info = self._sounds.get(key)
            if not info or not info.loaded or not info.sound:
                return None
            info.last_used = time.time()
            self._access_order[key] = None
            self._access_order.move_to_end(key)
            return info

    def play_sound(
        self,
        key: str,
        channel_type: str = "kill_sound",
        loops: int = 0,
        channel=None,
        event_type: str | None = None,
        priority: int | None = None,
        allow_preempt: bool | None = None,
    ) -> bool:
        from config import config
        from voice_output_manager import get_voice_output_manager

        resolved_event_type = str(event_type or channel_type or "default")
        profile = str(getattr(config, "audio_policy_profile", "kill_preempt_v1") or "kill_preempt_v1")
        resolved_priority = resolve_priority(
            resolved_event_type,
            explicit_priority=priority,
            profile=profile,
        )
        resolved_allow_preempt = True if allow_preempt is None else bool(allow_preempt)

        # QA-015: 加载**必须**在转发之前。
        # 原顺序是「先转发、后按需加载」：预载有预算上限（_max_sounds=50，而重度配置
        # 有 171 项），没被预载到的键第一次触发时 `self._sounds.get(key)` 拿不到东西，
        # 转发就被静默跳过 —— 本地照常出声、日志一个字没有，**队友什么都听不到**，
        # 第二次起才正常。开了音效转发的用户，每个新音效都会哑一次。
        with self._lock:
            exists = key in self._sounds
        if not exists:
            self._load_sound_by_key(key)

        info = self._get_info(key)
        if not info:
            self._notify_error(f"Audio not loaded: {key}")
            self._record_timeline_event(
                action="drop",
                key=key,
                channel_type=channel_type,
                event_type=resolved_event_type,
                reason="audio_not_loaded",
                success=False,
            )
            return False

        if getattr(config, "sfx_forwarding_enabled", False):
            sfx_type = self._map_channel_to_sfx_type(channel_type)
            if sfx_type and getattr(config, "sfx_forwarding_options", {}).get(sfx_type, False):
                obj = info.sound if info.loaded else None
                if obj:
                    volume = self._resolve_play_volume(config, channel_type, info)
                    try:
                        # 注意保持这一步在 self._playback_lock **之外**：
                        # play_pygame_sound_to_voice 会按 PTT 键并写 VB-Cable，
                        # 挪进锁里会把所有播放串行化，表现成卡顿/掉声。
                        get_voice_output_manager().play_pygame_sound_to_voice(obj, volume)
                    except Exception as e:
                        self.logger.error(f"Forward failed: {e}")
                else:
                    # 以前这里既不加载也不记账，日志里查不到任何痕迹
                    self._record_timeline_event(
                        action="forward",
                        key=key,
                        channel_type=channel_type,
                        event_type=resolved_event_type,
                        reason="not_loaded",
                        success=False,
                    )

        from config import config
        try:
            volume = self._resolve_play_volume(config, channel_type, info)
            info.sound.set_volume(volume)
            use_channel = channel or self._select_channel(channel_type)
            channel_key = self._channel_state_key(channel_type, use_channel)

            with self._playback_lock:
                active_request = self._active_channel_requests.get(channel_key)
                channel_busy = bool(use_channel and hasattr(use_channel, "get_busy") and use_channel.get_busy())
                playback_request = PlaybackRequest(
                    key=key,
                    channel_type=channel_type,
                    event_type=resolved_event_type,
                    priority=resolved_priority,
                    allow_preempt=resolved_allow_preempt,
                )
                decision = decide_channel_action(
                    playback_request,
                    active_request,
                    channel_busy=channel_busy,
                )

                log_line = (
                    f"[AudioPolicy][{decision.action.upper()}] key={key} channel={channel_type} "
                    f"event={resolved_event_type} priority={resolved_priority} reason={decision.reason}"
                )
                if decision.action == "play":
                    self.logger.debug(log_line)
                else:
                    self.logger.info(log_line)
                if decision.action == "drop":
                    self._record_timeline_event(
                        action="drop",
                        key=key,
                        channel_type=channel_type,
                        event_type=resolved_event_type,
                        reason=decision.reason,
                        success=False,
                        meta={"priority": resolved_priority, "profile": profile},
                    )
                    return False

                if decision.action == "preempt" and use_channel and hasattr(use_channel, "stop"):
                    try:
                        use_channel.stop()
                    except Exception:
                        pass
                    self._record_timeline_event(
                        action="preempt",
                        key=key,
                        channel_type=channel_type,
                        event_type=resolved_event_type,
                        reason=decision.reason,
                        success=True,
                        meta={"priority": resolved_priority, "profile": profile},
                    )

                if use_channel:
                    use_channel.play(info.sound, loops=loops)
                else:
                    info.sound.play(loops=loops)
                self._active_channel_requests[channel_key] = playback_request
            self._record_timeline_event(
                action="play",
                key=key,
                channel_type=channel_type,
                event_type=resolved_event_type,
                reason="played",
                success=True,
                meta={"priority": resolved_priority, "profile": profile},
            )
            return True
        except Exception as e:
            self._notify_error(f"Play failed {key}: {e}")
            self._record_timeline_event(
                action="drop",
                key=key,
                channel_type=channel_type,
                event_type=resolved_event_type,
                reason=f"play_failed:{e}",
                success=False,
                meta={"priority": resolved_priority, "profile": profile},
            )
            return False

    def play_voice(self, key: str):
        from config import config
        from voice_output_manager import get_voice_output_manager

        # QA-015: 同 play_sound —— 加载在转发之前，否则冷键第一次触发队友听不到
        info = self._get_info(key)
        if not info:
            self._load_voice_by_key(key)
            info = self._get_info(key)
        if not info:
            return

        if getattr(config, "sfx_forwarding_enabled", False):
            if getattr(config, "sfx_forwarding_options", {}).get("kill_voice", False):
                obj = info.sound if info.loaded else None
                if obj:
                    try:
                        get_voice_output_manager().play_pygame_sound_to_voice(obj, getattr(config, "volume", self._volume))
                    except Exception as e:
                        self.logger.error(f"Voice forward failed: {e}")
                else:
                    self._record_timeline_event(
                        action="forward", key=key, channel_type="kill_voice",
                        event_type="kill_voice", reason="not_loaded", success=False,
                    )

        try:
            info.sound.set_volume(self._resolve_play_volume(config, "kill_voice", info))
            self.kill_voice_channel.play(info.sound)
        except Exception as e:
            self.logger.error(f"Play voice failed {key}: {e}")

    def play_sound_with_fade(self, key: str, channel_type: str = "round_sound", fade_in_ms: int = 500, fade_out_ms: int = 1000):
        from config import config

        with self._lock:
            exists = key in self._sounds
        if not exists:
            self._load_sound_by_key(key)

        info = self._get_info(key)
        if not info:
            return

        channel = self._select_channel(channel_type)
        self._clear_fade_effect(key, channel)

        target = getattr(config, "round_sound_volume", self._volume) if channel_type == "round_sound" else getattr(config, "volume", self._volume)
        fade_in_s = max(0.01, fade_in_ms / 1000.0)
        fade_out_s = max(0.01, fade_out_ms / 1000.0)

        try:
            info.sound.set_volume(0.0)
            channel.play(info.sound)
        except Exception as e:
            self.logger.error(f"Fade start failed {key}: {e}")
            return

        # QA-016: 登记这次播放对通道的归属。
        # 五个回合音效（start/action/win/lose/mvp）共用同一个 round_sound 通道，
        # 上一段的淡出 Timer 是在 fade_in 跑完之后才 start 的，所以实际落点
        # ≈ 素材长度 + fade_in —— 早已越过"自己还在播"的时刻。等它触发时，
        # 通道上往往换成了**下一回合的音效**，而 803 行那句 `channel.stop()`
        # 会把别人的声音硬切掉。竞技 7 秒冻结期下，只要胜/负素材长度落在
        # 约 6.4~12.4 秒（用户自己导入的号角/梗音效绝大多数在这段），
        # **每个己方胜负回合都必现**。
        # 用自增整数而不是 key 当令牌：同一个 key 连播两次也一并覆盖。
        # 也别改用 `channel.get_sound() is info.sound` —— _NullChannel 和现有
        # 测试里的假通道都没有 get_sound，会连带炸一片。
        self._fade_seq += 1
        token = self._fade_seq
        self.fade_owner[channel] = token

        def _still_mine() -> bool:
            return bool(channel.get_busy()) and self.fade_owner.get(channel) == token

        def fade_out():
            if not _still_mine():
                self.fade_timers.pop((key, channel), None)
                self.fade_threads.pop((key, channel), None)
                return
            start = time.time()
            while _still_mine():
                p = (time.time() - start) / fade_out_s
                if p >= 1.0:
                    break
                try:
                    info.sound.set_volume(max(0.0, target * (1.0 - p)))
                except Exception:
                    break
                time.sleep(0.02)
            try:
                if _still_mine():
                    channel.stop()
            except Exception:
                pass
            self.fade_timers.pop((key, channel), None)
            self.fade_threads.pop((key, channel), None)

        def fade_in():
            start = time.time()
            while channel.get_busy():
                p = (time.time() - start) / fade_in_s
                if p >= 1.0:
                    break
                try:
                    info.sound.set_volume(max(0.0, target * p))
                except Exception:
                    break
                time.sleep(0.02)
            try:
                if channel.get_busy():
                    info.sound.set_volume(target)
            except Exception:
                pass
            delay = max(0.0, float(info.sound.get_length()) - fade_out_s)
            t = threading.Timer(delay, fade_out)
            t.daemon = True
            self.fade_timers[(key, channel)] = t
            t.start()

        th = threading.Thread(target=fade_in, name="AudioFadeIn", daemon=True)
        self.fade_threads[(key, channel)] = th
        th.start()

    def _clear_fade_effect(self, key: str, channel):
        t = self.fade_timers.pop((key, channel), None)
        if t:
            try:
                t.cancel()
            except Exception:
                pass
        self.fade_threads.pop((key, channel), None)

    def stop_sound(self, key: str):
        with self._lock:
            info = self._sounds.get(key)
            if info and info.sound:
                info.sound.stop()

    def stop_all(self):
        try:
            pygame.mixer.stop()
        except Exception:
            pass

    def stop_all_sounds(self):
        self.stop_all()

    def stop_channel(self, channel):
        if channel:
            try:
                channel.stop()
            except Exception:
                pass

    def unload_sound(self, key: str):
        with self._lock:
            info = self._sounds.pop(key, None)
            self._access_order.pop(key, None)
        if info and info.sound:
            try:
                info.sound.stop()
            except Exception:
                pass

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, float(volume)))
        with self._lock:
            for info in self._sounds.values():
                if info.sound:
                    try:
                        info.sound.set_volume(self._volume)
                    except Exception:
                        pass

    def get_volume(self) -> float:
        return self._volume

    def get_loaded_sounds(self, category: str = None) -> List[str]:
        with self._lock:
            if category:
                return [k for k, i in self._sounds.items() if i.loaded and i.category == category]
            return [k for k, i in self._sounds.items() if i.loaded]

    def get_sound_info(self, key: str) -> Optional[AudioInfo]:
        with self._lock:
            return self._sounds.get(key)

    def is_loaded(self, key: str) -> bool:
        with self._lock:
            info = self._sounds.get(key)
            return bool(info and info.loaded and info.sound)

    def get_loaded_count(self) -> int:
        with self._lock:
            return sum(1 for i in self._sounds.values() if i.loaded)

    def all_sounds_loaded(self):
        return len(self.sounds) > 0

    def get_all_sound_keys(self):
        return list(self.sounds.keys())

    def ensure_styles_scanned(self):
        if not self._styles_scanned:
            self._scan_audio_styles()
            self._styles_scanned = True

    def _scan_audio_styles(self):
        # 2.2.0: 全量重扫前清目录扫描缓存(导入/载入音频路径都走这里)
        try:
            from core.audio.audio_file_utils import invalidate_style_dirs_cache

            invalidate_style_dirs_cache()
        except Exception:
            pass
        self.scan_kill_sound_styles()
        self.scan_kill_voice_styles()
        self.scan_weapon_kill_sound_styles()
        self.scan_weapon_kill_voice_styles()
        self.scan_death_styles()
        self.scan_switch_weapon_styles()
        self.scan_reload_styles()
        self.scan_grenade_sound_styles()
        self.scan_c4_sound_styles()
        self.scan_health_warning_styles()
        self.scan_round_sound_styles()
        self.scan_gun_sound_styles()
        self.death_styles = self.death_sound_styles

    def scan_kill_sound_styles(self):
        self.kill_sound_styles = list_style_dirs_with_audio(self.kill_sounds_dir, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.kill_sound_styles

    def scan_kill_voice_styles(self):
        self.kill_voice_styles = list_style_dirs_with_audio(self.kill_voices_dir, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.kill_voice_styles

    def scan_weapon_kill_sound_styles(self):
        self.weapon_kill_sound_styles = {}
        if not os.path.isdir(self.weapon_sounds_dir):
            return self.weapon_kill_sound_styles
        for weapon in sorted(os.listdir(self.weapon_sounds_dir), key=str.lower):
            p = os.path.join(self.weapon_sounds_dir, weapon)
            if os.path.isdir(p):
                self.weapon_kill_sound_styles[weapon] = list_style_dirs_with_audio(p, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.weapon_kill_sound_styles

    def scan_weapon_kill_voice_styles(self):
        self.weapon_kill_voice_styles = {}
        if not os.path.isdir(self.weapon_voices_dir):
            return self.weapon_kill_voice_styles
        for weapon in sorted(os.listdir(self.weapon_voices_dir), key=str.lower):
            p = os.path.join(self.weapon_voices_dir, weapon)
            if os.path.isdir(p):
                self.weapon_kill_voice_styles[weapon] = list_style_dirs_with_audio(p, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.weapon_kill_voice_styles

    def scan_death_styles(self):
        self.death_sound_styles = list_unique_audio_stems(self.death_sounds_dir, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        self.death_styles = self.death_sound_styles
        return self.death_sound_styles

    def scan_switch_weapon_styles(self):
        self.switch_weapon_styles = {}
        if not os.path.isdir(self.switch_weapons_dir):
            return self.switch_weapon_styles
        for weapon in sorted(os.listdir(self.switch_weapons_dir), key=str.lower):
            p = os.path.join(self.switch_weapons_dir, weapon)
            if os.path.isdir(p):
                self.switch_weapon_styles[weapon] = list_style_dirs_with_audio(p, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.switch_weapon_styles

    def scan_reload_styles(self):
        self.reload_styles = {}
        if not os.path.isdir(self.reload_sounds_dir):
            return self.reload_styles
        for weapon in sorted(os.listdir(self.reload_sounds_dir), key=str.lower):
            p = os.path.join(self.reload_sounds_dir, weapon)
            if os.path.isdir(p):
                self.reload_styles[weapon] = list_style_dirs_with_audio(p, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.reload_styles

    def scan_grenade_sound_styles(self):
        self.grenade_sound_styles = {}
        for gt in self.GRENADE_TYPES:
            p = os.path.join(self.grenade_sounds_dir, gt)
            self.grenade_sound_styles[gt] = list_style_dirs_with_audio(p, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.grenade_sound_styles

    def scan_c4_sound_styles(self):
        self.c4_sound_styles = list_style_dirs_with_audio(self.c4_sounds_dir, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.c4_sound_styles

    def scan_health_warning_styles(self):
        self.health_warning_styles = list_style_dirs_with_audio(self.health_warning_dir, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.health_warning_styles

    def _scan_sound_styles(self, directory: str):
        return list_style_dirs_with_audio(directory, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)

    def scan_round_sound_styles(self):
        self.round_start_styles = self._scan_sound_styles(os.path.join(self.round_sounds_dir, "start"))
        self.round_action_styles = self._scan_sound_styles(os.path.join(self.round_sounds_dir, "action"))
        self.round_win_styles = self._scan_sound_styles(os.path.join(self.round_sounds_dir, "win"))
        self.round_lose_styles = self._scan_sound_styles(os.path.join(self.round_sounds_dir, "lose"))
        self.round_mvp_styles = self._scan_sound_styles(os.path.join(self.round_sounds_dir, "mvp"))
        return {
            "start": self.round_start_styles,
            "action": self.round_action_styles,
            "win": self.round_win_styles,
            "lose": self.round_lose_styles,
            "mvp": self.round_mvp_styles,
        }

    def scan_gun_sound_styles(self):
        self.gun_sound_styles = {w: [] for w in self.GUN_TYPES}
        for w in self.GUN_TYPES:
            p = os.path.join(self.gun_sounds_dir, w)
            self.gun_sound_styles[w] = list_style_dirs_with_audio(p, extensions=DEFAULT_AUDIO_EXTENSIONS, sort=True)
        return self.gun_sound_styles

    def _load_count_file(self, base_dir: str, stem: str, key: str, category: str, weapon_id=None, style=None) -> bool:
        path = find_audio_by_stem(base_dir, stem, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not path:
            return False
        return self.load_sound(key, path, category, weapon_id=weapon_id, style=style)

    def _load_range(self, base_dir: str, key_builder: Callable[[int], str], category: str, weapon_id=None, style=None, headshot: bool = False, index: int = None):
        loaded = False
        nums = [int(index)] if index is not None else [1, 2, 3, 4, 5]
        for i in nums:
            key = key_builder(i)
            loaded = self._load_count_file(base_dir, str(i), key, category, weapon_id=weapon_id, style=style) or loaded
            if headshot:
                loaded = self._load_count_file(base_dir, f"{i}-headshot", f"{key}-headshot", category, weapon_id=weapon_id, style=style) or loaded
        return loaded

    def load_kill_sound(self, style, is_headshot: bool = False, number: int = None) -> bool:
        style = self._resolve_style_value(style)
        if not self._style_enabled(style):
            return False
        style_dir = os.path.join(self.kill_sounds_dir, style)
        if not os.path.isdir(style_dir):
            return False
        return self._load_range(style_dir, lambda i: f"kill-{style}-{i}", "kill_sound", style=style, headshot=is_headshot, index=number)

    def load_kill_sound_generic(self, style: str, number: int, is_headshot: bool = False) -> bool:
        style = self._resolve_style_value(style)
        if not self._style_enabled(style):
            return False
        style_dir = os.path.join(self.kill_sounds_dir, style)
        if not os.path.isdir(style_dir):
            return False
        key = f"kill-{style}-{int(number)}"
        loaded = self._load_count_file(style_dir, str(int(number)), key, "kill_sound", style=style)
        if is_headshot:
            loaded = self._load_count_file(style_dir, f"{int(number)}-headshot", f"{key}-headshot", "kill_sound", style=style) or loaded
        return loaded

    def load_kill_sound_default(self, number: int, is_headshot: bool = False) -> bool:
        n = int(number)
        loaded = self.load_kill_sound_generic("default", n, is_headshot=is_headshot)
        if loaded:
            self._alias(f"kill-{n}", f"kill-default-{n}")
            if is_headshot:
                self._alias(f"kill-{n}-headshot", f"kill-default-{n}-headshot")
            return True

        key = f"kill-{n}"
        loaded = self._load_count_file(self.kill_sounds_dir, str(n), key, "kill_sound", style="default")
        if is_headshot:
            loaded = self._load_count_file(self.kill_sounds_dir, f"{n}-headshot", f"{key}-headshot", "kill_sound", style="default") or loaded
        if loaded:
            return True
        return self._load_first_available_generic_kill_sound(n, is_headshot=is_headshot)

    def load_kill_sound_for_weapon(self, weapon: str, style, is_headshot: bool = False, number: int = None) -> bool:
        style = self._resolve_style_value(style)
        if not self._style_enabled(style):
            return False
        self.ensure_styles_scanned()
        if style not in self.weapon_kill_sound_styles.get(weapon, []):
            return self.load_kill_sound(style, is_headshot=is_headshot, number=number)
        style_dir = os.path.join(self.weapon_sounds_dir, weapon, style)
        if not os.path.isdir(style_dir):
            return False
        return self._load_range(style_dir, lambda i: f"kill-{weapon}-{style}-{i}", "kill_sound", weapon_id=weapon, style=style, headshot=is_headshot, index=number)

    def load_kill_voice(self, style, is_headshot: bool = False, count: int = None) -> bool:
        style = self._resolve_style_value(style)
        if not self._style_enabled(style):
            return False
        style_dir = os.path.join(self.kill_voices_dir, style)
        if not os.path.isdir(style_dir):
            return False
        loaded = self._load_range(style_dir, lambda i: f"voice-{style}-{i}", "kill_voice", style=style, headshot=is_headshot, index=count)
        if style == "default" and count is not None:
            self._alias(f"voice-{int(count)}", f"voice-default-{int(count)}")
            if is_headshot:
                self._alias(f"voice-{int(count)}-headshot", f"voice-default-{int(count)}-headshot")
        return loaded

    def load_kill_voice_for_weapon(self, weapon: str, style, kill_count: int | bool | None = 1, is_headshot: bool | None = None) -> bool:
        style = self._resolve_style_value(style)
        if not self._style_enabled(style):
            return False
        self.ensure_styles_scanned()

        if isinstance(kill_count, bool):
            count = None
            headshot = bool(kill_count) if is_headshot is None else bool(is_headshot)
            self._warn_deprecated_once("load_kill_voice_for_weapon_bool", "load_kill_voice_for_weapon(weapon, style, bool) is deprecated")
        else:
            count = int(kill_count) if kill_count is not None else None
            headshot = bool(is_headshot)

        if style not in self.weapon_kill_voice_styles.get(weapon, []):
            return self.load_kill_voice(style, is_headshot=headshot, count=count)

        style_dir = os.path.join(self.weapon_voices_dir, weapon, style)
        if not os.path.isdir(style_dir):
            return False

        loaded = False
        nums = [count] if count is not None else [1, 2, 3, 4, 5]
        for i in nums:
            key = f"voice-{weapon}-{style}-{i}"
            p = find_audio_by_stem(style_dir, str(i), extensions=DEFAULT_AUDIO_EXTENSIONS)
            if not p:
                p = find_audio_by_stem(os.path.join(self.kill_voices_dir, style), str(i), extensions=DEFAULT_AUDIO_EXTENSIONS)
            if p:
                loaded = self.load_sound(key, p, "kill_voice", weapon_id=weapon, style=style) or loaded

            if headshot:
                hs_key = f"{key}-headshot"
                hs_p = find_audio_by_stem(style_dir, f"{i}-headshot", extensions=DEFAULT_AUDIO_EXTENSIONS)
                if not hs_p:
                    hs_p = find_audio_by_stem(os.path.join(self.kill_voices_dir, style), f"{i}-headshot", extensions=DEFAULT_AUDIO_EXTENSIONS)
                if hs_p:
                    loaded = self.load_sound(hs_key, hs_p, "kill_voice", weapon_id=weapon, style=style) or loaded
        return loaded

    def load_death_sound(self, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        p = find_audio_by_stem(self.death_sounds_dir, style, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        return self.load_sound(f"death-{style}", p, "death_sound", style=style)

    def load_switch_weapon_sound(self, weapon, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.switch_weapons_dir, weapon, style)
        if not os.path.isdir(d):
            return False
        p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        return self.load_sound(f"switch-{weapon}-{style}", p, "switch_weapon", weapon_id=weapon, style=style)

    def load_reload_sound(self, weapon, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.reload_sounds_dir, weapon, style)
        if not os.path.isdir(d):
            return False
        p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        return self.load_sound(f"reload-{weapon}-{style}", p, "reload_sound", weapon_id=weapon, style=style)

    def load_grenade_sound(self, grenade_type, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.grenade_sounds_dir, grenade_type, style)
        if not os.path.isdir(d):
            return False
        p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        return self.load_sound(f"grenade-{grenade_type}-{style}", p, "special_sound", weapon_id=grenade_type, style=style)

    def load_c4_sound(self, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.c4_sounds_dir, style)
        if not os.path.isdir(d):
            return False
        p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS, preferred_tokens=("planted", "install", "bomb", "下包", "安放"))
        if not p:
            return False
        return self.load_sound(f"c4-planted-{style}", p, "special_sound", style=style)

    def load_health_warning_sound(self, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.health_warning_dir, style)
        if not os.path.isdir(d):
            return False
        p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        return self.load_sound(f"health-warning-{style}", p, "special_sound", style=style)

    def _parse_round_args(self, arg1: str, arg2: str):
        a1 = self._norm_style(arg1)
        a2 = self._norm_style(arg2)
        if a1 in self.ROUND_TYPES and a2 not in self.ROUND_TYPES:
            return a1, a2
        if a2 in self.ROUND_TYPES and a1 not in self.ROUND_TYPES:
            return a2, a1
        return a1, a2

    def load_round_sound(self, arg1: str, arg2: str) -> bool:
        round_type, style = self._parse_round_args(arg1, arg2)
        if round_type not in self.ROUND_TYPES:
            return False
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.round_sounds_dir, round_type, style)
        if not os.path.isdir(d):
            return False
        p = find_audio_by_stem(d, round_type, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        canonical = f"round-{style}-{round_type}"
        ok = self.load_sound(canonical, p, "round_sound", style=style)
        if ok:
            self._alias(f"round-{round_type}-{style}", canonical)
        return ok

    def load_gun_sound(self, gun_type, style) -> bool:
        style = self._norm_style(style)
        if not self._style_enabled(style):
            return False
        d = os.path.join(self.gun_sounds_dir, gun_type, style)
        if not os.path.isdir(d):
            return False
        p = find_first_audio_file(d, extensions=DEFAULT_AUDIO_EXTENSIONS)
        if not p:
            return False
        canonical = f"gun-{gun_type}-{style}"
        ok = self.load_sound(canonical, p, "gun_sound", weapon_id=gun_type, style=style)
        if ok:
            self._alias(f"{gun_type}-{style}", canonical)
        return ok

    def _remove_keys(self, pred: Callable[[str], bool]) -> int:
        removed = []
        with self._lock:
            for k in list(self._sounds.keys()):
                if pred(k):
                    removed.append(k)
            for k in removed:
                self._sounds.pop(k, None)
                self._access_order.pop(k, None)
        return len(removed)

    def unload_kill_sound(self, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k.startswith(f"kill-{s}-")) > 0

    def unload_kill_sound_for_weapon(self, weapon, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k.startswith(f"kill-{weapon}-{s}-")) > 0

    def unload_kill_voice(self, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k.startswith(f"voice-{s}-")) > 0

    def unload_kill_voice_for_weapon(self, weapon, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k.startswith(f"voice-{weapon}-{s}-")) > 0

    def unload_death_sound(self, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k == f"death-{s}") > 0

    def unload_switch_weapon_sound(self, weapon, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k == f"switch-{weapon}-{s}") > 0

    def unload_reload_sound(self, weapon, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k == f"reload-{weapon}-{s}") > 0

    def unload_grenade_sound(self, grenade_type, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k == f"grenade-{grenade_type}-{s}") > 0

    def unload_c4_sound(self, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k == f"c4-planted-{s}") > 0

    def unload_health_warning_sound(self, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k == f"health-warning-{s}") > 0

    def unload_round_sound(self, round_type, style):
        rt, s = self._parse_round_args(round_type, style)
        return self._remove_keys(lambda k: k in (f"round-{rt}-{s}", f"round-{s}-{rt}")) > 0

    def unload_gun_sound(self, gun_type, style):
        s = self._norm_style(style)
        return self._remove_keys(lambda k: k in (f"{gun_type}-{s}", f"gun-{gun_type}-{s}")) > 0

    def _load_sound_by_key(self, key: str) -> bool:
        self.ensure_styles_scanned()

        if key.startswith("kill-"):
            payload = key[5:]
            hs = payload.endswith("-headshot")
            if hs:
                payload = payload[:-9]
            parts = [p for p in payload.split("-") if p]

            if len(parts) >= 3 and parts[0].startswith("weapon_"):
                weapon = parts[0]
                style = "-".join(parts[1:-1])
                try:
                    num = int(parts[-1])
                    if style:
                        return self.load_kill_sound_for_weapon(weapon, style, is_headshot=hs, number=num)
                except Exception:
                    pass

            if len(parts) >= 2:
                style = "-".join(parts[:-1])
                try:
                    num = int(parts[-1])
                    if style:
                        return self.load_kill_sound_generic(style, num, is_headshot=hs)
                except Exception:
                    pass

            if len(parts) >= 1:
                try:
                    num = int(parts[0])
                    return self.load_kill_sound_default(num, is_headshot=hs)
                except Exception:
                    pass

        elif key.startswith("voice-"):
            return self._load_voice_by_key(key)

        elif key.startswith("death-"):
            return self.load_death_sound(key[6:])

        elif key.startswith("switch-"):
            payload = key[7:]
            if "-" in payload:
                weapon, style = payload.split("-", 1)
                return self.load_switch_weapon_sound(weapon, style)

        elif key.startswith("reload-"):
            payload = key[7:]
            if "-" in payload:
                weapon, style = payload.split("-", 1)
                return self.load_reload_sound(weapon, style)

        elif key.startswith("grenade-"):
            payload = key[8:]
            if "-" in payload:
                gt, style = payload.split("-", 1)
                return self.load_grenade_sound(gt, style)

        elif key.startswith("c4-planted-"):
            return self.load_c4_sound(key[len("c4-planted-"):])

        elif key.startswith("health-warning-"):
            return self.load_health_warning_sound(key[len("health-warning-"):])

        elif key.startswith("round-"):
            payload = key[6:]
            if "-" in payload:
                first, rest = payload.split("-", 1)
                if first in self.ROUND_TYPES:
                    return self.load_round_sound(first, rest)
                style, rt = payload.rsplit("-", 1)
                if rt in self.ROUND_TYPES:
                    return self.load_round_sound(style, rt)
                return self.load_round_sound(first, rest)

        elif key.startswith("gun-"):
            payload = key[4:]
            if "-" in payload:
                gun, style = payload.split("-", 1)
                return self.load_gun_sound(gun, style)

        elif "-" in key:
            gun, style = key.split("-", 1)
            if style and os.path.isdir(os.path.join(self.gun_sounds_dir, gun)):
                ok = self.load_gun_sound(gun, style)
                if ok:
                    self._alias(key, f"gun-{gun}-{style}")
                return ok

        return False

    def _load_voice_by_key(self, key: str) -> bool:
        if not key.startswith("voice-"):
            return False

        payload = key[6:]
        hs = payload.endswith("-headshot")
        if hs:
            payload = payload[:-9]
        parts = [p for p in payload.split("-") if p]

        if len(parts) >= 3 and parts[0].startswith("weapon_"):
            weapon = parts[0]
            style = "-".join(parts[1:-1])
            try:
                c = int(parts[-1])
                if style:
                    return self.load_kill_voice_for_weapon(weapon, style, c, is_headshot=hs)
            except Exception:
                pass

        if len(parts) >= 2:
            style = "-".join(parts[:-1])
            try:
                c = int(parts[-1])
                if style:
                    return self.load_kill_voice(style, is_headshot=hs, count=c)
            except Exception:
                pass

        if len(parts) >= 1:
            try:
                c = int(parts[0])
                loaded_default = self.load_kill_voice("default", is_headshot=hs, count=c)
                ok = loaded_default
                if not ok:
                    ok = self._load_first_available_generic_kill_voice(c, is_headshot=hs)
                if loaded_default:
                    self._alias(f"voice-{c}", f"voice-default-{c}")
                    if hs:
                        self._alias(f"voice-{c}-headshot", f"voice-default-{c}-headshot")
                return ok
            except Exception:
                pass

        return False

    def _preload_budget_left(self) -> int:
        """预载还能再装几个。UP-060 用它把「解码后立刻被淘汰」的白工掐掉。"""
        with self._lock:
            return self._max_sounds - len(self._sounds)

    def load_all_enabled_sounds(self):
        """启动预热音频缓存。**受 `_max_sounds` 预算约束**（UP-060）。

        改之前的行为：不管上限、把所有启用项全解码一遍。对重度用户是双重损失——
        实测灌入 171 个（击杀/语音/切枪/换弹各 37 + 枪声 10 + 投掷 6 + 回合 5 + C4/血量）
        时，**121 个解码完立刻被淘汰**（71% 的功白做），而且淘汰的是**先装进去的**：
        击杀音效一个都没留下，反倒是 C4、血量警告、回合音效这些最低频的全占着缓存。
        于是重度用户每次击杀都要现场解码——延迟正好砸在最要紧的那一刻。

        现在分两轮装：
          1. **低基数类先装**（回合/C4/血量/投掷/枪声/死亡，合计通常 ≤23 个）——
             它们数量固定且每类只有几个，先占住能保证**每一类都有缓存覆盖**；
          2. **高基数的按事件频率填剩余预算**（击杀 → 击杀语音 → 切枪 → 换弹）；
          3. 预算用尽即停，不再解码后丢弃。

        没装进来的不会失灵：`play_sound` 走的是 `if not exists: self._load_sound_by_key(key)`
        的按需加载路径，缓存只是热身。
        配置在上限内的用户（实测本机 36 个）加载集合与改前完全一致，只是顺序不同。
        """
        from config import config

        self.ensure_styles_scanned()

        # ---- 第 1 轮：低基数类，保证每类都有覆盖 ----
        if getattr(config, "death_sound_enabled", False) and self._style_enabled(getattr(config, "death_sound_style", "0")):
            self.load_death_sound(getattr(config, "death_sound_style", "0"))

        if is_gun_sound_master_enabled(config):
            for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
                style = getattr(config, profile.style_key, "0")
                if gun_sound_style_enabled(style):
                    self.load_gun_sound(profile.gun_type, style)

        if getattr(config, "grenade_sound_enabled", False):
            for gt, style in getattr(config, "grenade_sound_styles", {}).items():
                if self._style_enabled(style):
                    self.load_grenade_sound(gt, style)

        if getattr(config, "c4_sound_enabled", False) and self._style_enabled(getattr(config, "c4_sound_style", "0")):
            self.load_c4_sound(getattr(config, "c4_sound_style", "0"))

        if getattr(config, "health_warning_enabled", False) and self._style_enabled(getattr(config, "health_warning_style", "0")):
            self.load_health_warning_sound(getattr(config, "health_warning_style", "0"))

        if getattr(config, "round_sound_enabled", False):
            for phase, key in (("start", "round_start_style"), ("action", "round_action_style"),
                               ("win", "round_win_style"), ("lose", "round_lose_style"),
                               ("mvp", "round_mvp_style")):
                if self._style_enabled(getattr(config, key, "0")):
                    self.load_round_sound(phase, getattr(config, key, "0"))

        # ---- 第 2 轮：高基数的按事件频率填剩余预算，装满即停 ----
        # 顺序即优先级：击杀是全局最高频事件,排最前。
        weapon_keyed = (
            ("kill_sound_enabled", "weapon_kill_sounds",
             lambda w, s: self.load_kill_sound_for_weapon(w, s, is_headshot=True)),
            ("kill_voice_enabled", "weapon_kill_voices",
             lambda w, s: self.load_kill_voice_for_weapon(w, s, True)),
            ("switch_weapon_sound_enabled", "weapon_switch_sounds",
             self.load_switch_weapon_sound),
            ("reload_sound_enabled", "weapon_reload_sounds",
             self.load_reload_sound),
        )
        skipped = 0
        for enable_key, map_key, loader in weapon_keyed:
            if not getattr(config, enable_key, False):
                continue
            for weapon, style in getattr(config, map_key, {}).items():
                if not self._style_enabled(style):
                    continue
                if self._preload_budget_left() <= 0:
                    skipped += 1
                    continue
                loader(weapon, style)
        if skipped:
            self.logger.info(
                f"[预载] 缓存已达上限 {self._max_sounds}，剩余 {skipped} 个音效改为按需加载"
                f"（避免解码后立刻被淘汰）"
            )

    def cleanup(self):
        for t in list(self.fade_timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        self.fade_timers.clear()
        self.fade_threads.clear()
        self.fade_owner.clear()      # QA-016

        self.stop_all()
        with self._lock:
            self._sounds.clear()
            self._access_order.clear()
        try:
            pygame.mixer.quit()
        except Exception:
            pass


_audio_manager_instance = None
_instance_lock = Lock()


def get_audio_manager() -> AudioManager:
    global _audio_manager_instance
    if _audio_manager_instance is None:
        with _instance_lock:
            if _audio_manager_instance is None:
                _audio_manager_instance = AudioManager()
    return _audio_manager_instance
