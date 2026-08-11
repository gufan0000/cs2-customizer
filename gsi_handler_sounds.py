# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time

from pynput.keyboard import Controller, KeyCode

from config import config
from core.audio.game_audio_ducker import (
    DEFAULT_GUN_SOUND_DUCK_RATIO,
    DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
    GameAudioDucker,
    clamp_gun_sound_duck_ratio,
    clamp_gun_sound_duck_time_ms,
)
from core.gun_sound_profiles import (
    GUN_SOUND_PROFILES,  # noqa: F401  本文件未直接用，但测试经 gsi_handler_sounds.GUN_SOUND_PROFILES 访问
    SUPPORTED_GUN_SOUND_PROFILE_LIST,
    SUPPORTED_GUN_SOUND_PROFILES,
    build_gun_sound_duck_plan,
    gun_sound_style_enabled,
    is_gun_sound_master_enabled,
    is_gun_sound_burst,
    resolve_gun_sound_style,
)
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger


audio_manager = get_runtime_audio_manager()
DEATH_SOUND_HOLD_DURATION = 0.30
DEATH_SOUND_MUTE_ONLY_HOLD_DURATION = 0.26
DEATH_SOUND_PEAK_MS = 60
DEATH_SOUND_MIN_SUSTAIN_RATIO = 0.05
DEATH_SOUND_MAX_SUSTAIN_RATIO = 0.12
DEATH_SOUND_RELEASE_SCALE = 1.6
DEATH_SOUND_MUTE_ONLY_RELEASE_SCALE = 1.15


class GSIHandlerSounds:
    def __init__(self):
        self.logger = get_logger("GSIHandlerSounds")
        self.keyboard = Controller()
        self._game_audio_ducker = GameAudioDucker(cfg=config, logger=self.logger)

        for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
            setattr(self, f"is_{profile.gun_type}_active", False)
            setattr(self, f"last_{profile.gun_type}_fire_time", 0.0)
            setattr(self, f"previous_{profile.gun_type}_ammo", {})
            setattr(self, f"{profile.gun_type}_fired_this_frame", False)

        self.last_health = 100
        self._death_tracked_steamid = ""  # 基线所属的steamid，观战切换时重建基线
        self.death_cooldown = 0
        self.death_cooldown_duration = 5.0
        self.last_active_weapon = ""
        self.weapon_reload_states = {}
        self.magnifier_component = None

    def set_magnifier_component(self, magnifier_component):
        self.magnifier_component = magnifier_component
        self.logger.info("已设置放大组件引用")

    def _restore_ducker_if_features_disabled(self):
        if is_gun_sound_master_enabled(config) or bool(getattr(config, "death_sound_enabled", False)):
            return
        is_ducked = getattr(self._game_audio_ducker, "is_ducked", None)
        if callable(is_ducked) and is_ducked():
            self.logger.debug("枪声替换与被击杀音效均未启用，主动恢复游戏音量")
            self._game_audio_ducker.restore()

    def _resolve_current_weapon(self, player_data):
        weapons = player_data.get("weapons", {}) or {}
        fallback_weapon = ""
        fallback_priority = -1

        for weapon_data in weapons.values():
            weapon_name = str(weapon_data.get("name", "") or "").strip()
            if not weapon_name:
                continue

            weapon_state = str(weapon_data.get("state", "") or "").strip().lower()
            if weapon_state == "active":
                return weapon_name

            if weapon_state and weapon_state != "holstered":
                priority = 2
            elif not weapon_state:
                priority = 1
            else:
                priority = 0

            if priority > fallback_priority:
                fallback_weapon = weapon_name
                fallback_priority = priority

        return fallback_weapon

    def process_data(self, data):
        player_data = data.get("player", {})
        current_steamid = player_data.get("steamid", "")
        current_weapon = self._resolve_current_weapon(player_data)
        self._restore_ducker_if_features_disabled()

        if not config.player_steamid and current_steamid:
            config.player_steamid = current_steamid
            config.save_config()
            self.logger.info(f"记录玩家SteamID: {current_steamid}")

        if config.spectator_mode_mute and current_steamid and current_steamid != config.player_steamid:
            if self.magnifier_component:
                self.magnifier_component.update_current_weapon("")
            return

        if self.magnifier_component:
            self.magnifier_component.update_current_weapon(current_weapon)

        if not self._is_player_active(data):
            self._reset_weapon_states()
            return

        self._reset_gun_frame_flags()

        if is_gun_sound_master_enabled(config):
            for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
                self._process_gun_sound(profile.gun_type, data)

        if config.death_sound_enabled:
            self._process_death_sound(data)
        else:
            # 功能关闭期间也要跟踪血量基线：否则关闭期死过一次，
            # 重新开启时陈旧的 last_health>0 会和 health==0 组成假死亡边沿
            self._sync_death_baseline(player_data)

        if config.switch_weapon_sound_enabled:
            self._process_weapon_switch_sound(data)

        if config.reload_sound_enabled:
            self._process_reload_sound(data)

    def _is_player_active(self, data):
        return (
            "player" in data
            and "activity" in data["player"]
            and data["player"]["activity"] == "playing"
        )

    def _reset_gun_frame_flags(self):
        for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
            setattr(self, f"{profile.gun_type}_fired_this_frame", False)

    def _reset_weapon_states(self):
        for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
            setattr(self, f"is_{profile.gun_type}_active", False)

    @staticmethod
    def _style_disabled(style):
        return not gun_sound_style_enabled(style)

    def _apply_gun_sound_duck(self, profile, *, last_fire_time: float, current_time: float):
        shot_interval = None
        if last_fire_time > 0:
            shot_interval = max(0.0, current_time - last_fire_time)
        is_burst = is_gun_sound_burst(profile, shot_interval)
        hold_duration = getattr(config, profile.mute_duration_key, 0.4)
        duck_plan = build_gun_sound_duck_plan(
            config,
            profile,
            is_burst=is_burst,
            hold_duration=hold_duration,
        )
        self._game_audio_ducker.duck_for(
            duck_plan.hold_duration,
            peak_ratio=duck_plan.peak_ratio,
            peak_ms=duck_plan.peak_ms,
            sustain_ratio=duck_plan.sustain_ratio,
            release_ms=duck_plan.release_ms,
        )
        return duck_plan

    def _process_gun_sound(self, gun_type: str, data):
        profile = SUPPORTED_GUN_SOUND_PROFILES[gun_type]
        style = resolve_gun_sound_style(getattr(config, profile.style_key, "0"))
        if not gun_sound_style_enabled(style):
            return

        player_data = data.get("player", {})
        weapons = player_data.get("weapons", {}) or {}
        current_time = time.time()

        previous_ammo = getattr(self, f"previous_{gun_type}_ammo")
        last_fire_time_attr = f"last_{gun_type}_fire_time"
        fired_this_frame_attr = f"{gun_type}_fired_this_frame"
        active_attr = f"is_{gun_type}_active"

        matched_weapon = False
        for weapon_key, weapon_data in weapons.items():
            if weapon_data.get("name") not in profile.gsi_names:
                continue

            matched_weapon = True
            current_ammo = weapon_data.get("ammo_clip")
            state = str(weapon_data.get("state", "") or "").strip().lower()

            if current_ammo is not None:
                prev_ammo = previous_ammo.get(weapon_key)
            else:
                prev_ammo = None

            if current_ammo is not None:
                previous_ammo[weapon_key] = current_ammo

            if state != "active" or state == "reloading" or current_ammo is None:
                setattr(self, active_attr, False)
                return

            last_fire_time = getattr(self, last_fire_time_attr, 0.0)
            fired_this_frame = bool(getattr(self, fired_this_frame_attr, False))
            if (
                prev_ammo is not None
                and current_ammo < prev_ammo
                and (current_time - last_fire_time) > profile.min_fire_interval
                and not fired_this_frame
            ):
                self._apply_gun_sound_duck(profile, last_fire_time=last_fire_time, current_time=current_time)
                setattr(self, last_fire_time_attr, current_time)
                sound_key = f"gun-{gun_type}-{style}"
                # allow_preempt=True：连点/连射时若 3 条枪声通道都还在播（尤其用了较长的
                # 自定义枪声素材），新的一发会抢占最旧的通道而不是被直接丢掉，
                # 保证每一发都有声音反馈。（GSI 靠弹夹数轮询判断开火，两帧之间的极限连点
                # 仍无法逐发捕获，这是平台粒度限制，只能缓解。）
                audio_manager.play_sound(
                    sound_key,
                    channel_type="gun_sound",
                    event_type="gun_fire",
                    priority=35,
                    allow_preempt=True,
                )
                setattr(self, active_attr, True)
                setattr(self, fired_this_frame_attr, True)
            else:
                setattr(self, active_attr, False)
            return

        if not matched_weapon:
            setattr(self, active_attr, False)

    def _process_awp_sound(self, data):
        self._process_gun_sound("awp", data)

    def _process_deagle_sound(self, data):
        self._process_gun_sound("deagle", data)

    def _process_usp_sound(self, data):
        self._process_gun_sound("usp", data)

    def _process_revolver_sound(self, data):
        self._process_gun_sound("revolver", data)

    def _process_ssg08_sound(self, data):
        self._process_gun_sound("ssg08", data)

    def _process_scar20_sound(self, data):
        self._process_gun_sound("scar20", data)

    def _process_g3sg1_sound(self, data):
        self._process_gun_sound("g3sg1", data)

    def _process_nova_sound(self, data):
        self._process_gun_sound("nova", data)

    def _process_mag7_sound(self, data):
        self._process_gun_sound("mag7", data)

    def _process_sawedoff_sound(self, data):
        self._process_gun_sound("sawedoff", data)

    def _sync_death_baseline(self, player_data):
        state = player_data.get("state", {})
        if "health" in state:
            self.last_health = state["health"]
            self._death_tracked_steamid = player_data.get("steamid", "")

    def _process_death_sound(self, data):
        current_time = time.time()
        player_data = data.get("player", {})

        if "state" in player_data and "health" in player_data["state"]:
            current_health = player_data["state"]["health"]
            steamid = player_data.get("steamid", "")
            prev_health = self.last_health

            # 基线先行更新：旧实现在冷却期直接 return 冻结基线，
            # 死亡超过冷却时长(5s)后会用陈旧的 >0 基线对 health==0 重复判死
            self.last_health = current_health

            # 观战切换目标/首帧：不同人的血量不构成边沿，重建基线即可
            if steamid != self._death_tracked_steamid:
                self._death_tracked_steamid = steamid
                return

            if current_time < self.death_cooldown:
                return

            if current_health == 0 and prev_health > 0:
                self.logger.info(f"检测到玩家死亡! death_sound_style: {config.death_sound_style}")
                self.death_cooldown = current_time + self.death_cooldown_duration
                mute_only = self._style_disabled(config.death_sound_style)
                self._apply_death_sound_duck(mute_only=mute_only)

                if mute_only:
                    self.logger.debug("播放风格0: 仅静音")
                else:
                    sound_key = f"death-{config.death_sound_style}"
                    # v2.2.1: 走独立死亡通道(ch13)——旧版挤在 ch1，互杀(trade kill)时
                    # 自己的击杀声正在播，死亡声会被策略 drop 永久吞掉。
                    played = audio_manager.play_sound(
                        sound_key,
                        channel_type="death_sound",
                        event_type="death",
                        priority=40,
                        allow_preempt=False,
                    )
                    if played:
                        self.logger.debug(f"播放死亡音效: {sound_key}")
                    else:
                        self.logger.error(f"警告: 死亡音效播放失败: {sound_key}")

    def _apply_death_sound_duck(self, *, mute_only: bool):
        base_ratio = clamp_gun_sound_duck_ratio(
            getattr(config, "gun_sound_duck_ratio", DEFAULT_GUN_SOUND_DUCK_RATIO),
            DEFAULT_GUN_SOUND_DUCK_RATIO,
        )
        base_release_ms = clamp_gun_sound_duck_time_ms(
            getattr(config, "gun_sound_duck_release_ms", DEFAULT_GUN_SOUND_DUCK_RELEASE_MS),
            DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
        )

        if mute_only:
            hold_duration = DEATH_SOUND_MUTE_ONLY_HOLD_DURATION
            peak_ratio = 0.0
            peak_ms = 0
            sustain_ratio = 0.0
            release_ms = clamp_gun_sound_duck_time_ms(
                int(round(base_release_ms * DEATH_SOUND_MUTE_ONLY_RELEASE_SCALE)),
                DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
            )
        else:
            hold_duration = DEATH_SOUND_HOLD_DURATION
            peak_ratio = 0.0
            peak_ms = DEATH_SOUND_PEAK_MS
            sustain_ratio = min(
                DEATH_SOUND_MAX_SUSTAIN_RATIO,
                max(DEATH_SOUND_MIN_SUSTAIN_RATIO, base_ratio * 0.45),
            )
            release_ms = clamp_gun_sound_duck_time_ms(
                int(round(base_release_ms * DEATH_SOUND_RELEASE_SCALE)),
                DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
            )

        self._game_audio_ducker.duck_for(
            hold_duration,
            peak_ratio=peak_ratio,
            peak_ms=peak_ms,
            sustain_ratio=sustain_ratio,
            release_ms=release_ms,
        )

    def _process_weapon_switch_sound(self, data):
        player_data = data.get("player", {})
        current_weapon = ""
        if "weapons" in player_data and player_data["weapons"] is not None:
            for weapon_data in player_data["weapons"].values():
                if weapon_data.get("state") == "active":
                    current_weapon = weapon_data.get("name", "")
                    break

        if current_weapon and current_weapon.startswith("weapon_knife"):
            self.logger.debug(f"检测到刀类型: {current_weapon}，映射为 weapon_knife")
            current_weapon = "weapon_knife"

        if current_weapon and current_weapon != self.last_active_weapon:
            self.logger.info(f"武器切换: {self.last_active_weapon} -> {current_weapon}")
            weapon_style = config.weapon_switch_sounds.get(current_weapon, "0")
            if not self._style_disabled(weapon_style):
                sound_key = f"switch-{current_weapon}-{weapon_style}"
                played = audio_manager.play_sound(
                    sound_key,
                    channel_type="switch_weapon",
                    event_type="switch_weapon",
                    priority=25,
                    allow_preempt=False,
                )
                if played:
                    self.logger.debug(f"播放切枪音效: {sound_key}")
                else:
                    self.logger.error(f"切枪音效播放失败: {sound_key}")

            self.last_active_weapon = current_weapon

    def _process_reload_sound(self, data):
        player_data = data.get("player", {})
        if "weapons" not in player_data or player_data["weapons"] is None:
            return

        for weapon_key, weapon_data in player_data["weapons"].items():
            weapon_name = weapon_data.get("name", "")
            if weapon_name in ["weapon_knife", "weapon_taser", "weapon_hegrenade", "weapon_molotov", "weapon_incgrenade"]:
                continue
            if weapon_name.startswith("weapon_knife"):
                continue

            is_reloading = weapon_data.get("state") == "reloading"
            was_reloading = self.weapon_reload_states.get(weapon_key, False)
            if is_reloading and not was_reloading:
                self.logger.info(f"检测到武器开始换弹: {weapon_name}")
                weapon_style = config.weapon_reload_sounds.get(weapon_name, "0")
                if not self._style_disabled(weapon_style):
                    sound_key = f"reload-{weapon_name}-{weapon_style}"
                    played = audio_manager.play_sound(
                        sound_key,
                        channel_type="reload",
                        event_type="reload",
                        priority=22,
                        allow_preempt=False,
                    )
                    if played:
                        self.logger.debug(f"播放换弹音效: {sound_key}")
                    else:
                        self.logger.error(f"换弹音效播放失败: {sound_key}")

            self.weapon_reload_states[weapon_key] = is_reloading

    def _schedule_restore_volume(self, delay):
        self._game_audio_ducker.hold_for(delay)

    def _mute_game_sound(self):
        self._game_audio_ducker.start_duck()

    def _send_game_mute_hotkey(self):
        self.keyboard.press(KeyCode(char="\\"))
        self.keyboard.press("0")
        self.keyboard.release("0")
        self.keyboard.release(KeyCode(char="\\"))

    def _restore_volume(self):
        self._game_audio_ducker.restore()

    def _send_game_restore_hotkey(self):
        self.keyboard.press(KeyCode(char="\\"))
        self.keyboard.press("9")
        self.keyboard.release("9")
        self.keyboard.release(KeyCode(char="\\"))

    def cleanup(self):
        try:
            self._game_audio_ducker.close()
        except Exception as exc:
            self.logger.warning(f"清理枪声 Ducking 失败: {exc}")
