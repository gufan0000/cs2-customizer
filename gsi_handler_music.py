# SPDX-License-Identifier: GPL-3.0-or-later
import threading
import time

from config import config
from core.utils.logger import get_logger
from music_player import get_music_player


logger = get_logger("GSIHandlerMusic")

# v2.2.1: 模块级实例引用——音乐页关闭"游戏联动"时需要拿到同一个 handler
# 来恢复被联动改掉的播放状态（此前关开关只写 config，音乐永久卡在暂停/低音量）
_handler_instance = None


def get_music_gsi_handler():
    """返回最近创建的音乐 GSI 处理器实例（可能为 None）。"""
    return _handler_instance


class GSIHandlerMusic:
    """音乐播放器的 GSI 处理器。"""

    def __init__(self):
        global _handler_instance
        self.player = None
        self.player_alive = None
        self.last_health = 100
        self.last_state_change_time = 0
        self.state_change_cooldown = 0.5
        self.is_volume_lowered = False
        self.is_paused_by_game = False
        # v2.2.1: GSI 断流看门狗——存活状态(音乐被暂停/降音量)下游戏崩溃/
        # 断流时收尾包永远不来，音乐会卡在联动态。看门狗在断流超时后恢复常态。
        self._last_data_time = 0.0
        self._watchdog_started = False
        self._watchdog_timeout = 15.0
        _handler_instance = self

    def _music_session_active(self):
        return bool(config.music_enabled and self.player is not None)

    def _ensure_player(self):
        if self.player is None:
            self.player = get_music_player()
        return self.player

    def restore_game_link_state(self, reason: str = ""):
        """把音乐从"游戏联动态"恢复为常态：恢复音量、恢复播放、清联动标志。

        触发时机：关闭游戏联动开关、GSI 断流看门狗超时。
        只在确实处于联动态（被暂停/被降音量）时动手，避免打扰用户手动操作。
        """
        if self.player is None:
            return
        # 先取消挂起的联动淡变：存活侧"淡出到0再暂停"进行中时标志位还没置上，
        # 只查标志位会早退，随后淡变回调把音乐暂停且再无人恢复
        fade_canceled = False
        try:
            fade_canceled = self.player.cancel_fade()
        except Exception:
            pass
        if not (self.is_paused_by_game or self.is_volume_lowered or fade_canceled):
            return
        logger.info(f"[音乐播放器] 恢复联动前状态{f'（{reason}）' if reason else ''}")
        try:
            if self.is_volume_lowered:
                self.player.reset_temp_volume()
                self.is_volume_lowered = False
            if self.is_paused_by_game:
                if self.player.is_playing and self.player.is_paused:
                    self.player.resume()
                # 淡出到0再暂停的路径会把原始音量停在0，恢复时重放有效音量
                try:
                    self.player._apply_effective_volume()
                except Exception:
                    pass
                self.is_paused_by_game = False
            if fade_canceled and self.player.is_playing and not self.player.is_paused:
                # 淡出被中途取消，音量停在中间值，恢复有效音量
                self.player._apply_effective_volume()
        except Exception:
            logger.exception("[音乐播放器] 恢复联动前状态失败")
        self.player_alive = None  # 下一个GSI包按全新状态判定

    def _start_watchdog_if_needed(self):
        if self._watchdog_started:
            return
        self._watchdog_started = True

        def _watchdog_loop():
            while True:
                time.sleep(5.0)
                if _handler_instance is not self:
                    return  # 实例被替换（重建/测试），旧看门狗自行退出
                try:
                    if (
                        (self.is_paused_by_game or self.is_volume_lowered)
                        and self._last_data_time > 0
                        and time.time() - self._last_data_time > self._watchdog_timeout
                    ):
                        self.restore_game_link_state("GSI断流看门狗")
                except Exception:
                    logger.exception("[音乐播放器] 看门狗异常")

        thread = threading.Thread(target=_watchdog_loop, daemon=True, name="MusicGsiWatchdog")
        thread.start()

    def process_data(self, data):
        if not config.music_enabled:
            return
        if not config.music_game_link_enabled:
            return

        self._ensure_player()
        self._last_data_time = time.time()
        self._start_watchdog_if_needed()

        player_data = data.get("player", {})
        current_steamid = player_data.get("steamid", "")

        if not config.player_steamid and current_steamid:
            config.player_steamid = current_steamid
            config.save_config()
            logger.info(f"[音乐播放器] 记录玩家SteamID: {current_steamid}")

        # 音乐联动只关心"本人"的死活：死亡后观战时 GSI 的 player 会切成被观战者
        # （activity 仍为 playing 且 health>0），不按 steamid 过滤会被误判为"复活"
        # 而错误暂停/恢复音乐。与 HUD 引擎的观战排除逻辑一致，不依赖观战静音开关。
        if (
            current_steamid
            and config.player_steamid
            and current_steamid != config.player_steamid
        ):
            return

        is_active = self._is_player_active(data)
        state_data = player_data.get("state", {})
        current_health = state_data.get("health", 0)
        is_alive = is_active and current_health > 0

        current_time = time.time()
        if current_time - self.last_state_change_time < self.state_change_cooldown:
            return

        if self.player_alive is not True and is_alive:
            logger.info(f"[音乐播放器] 检测到玩家存活 (血量: {current_health})")
            self.player_alive = True
            self.last_state_change_time = current_time
            self._on_player_alive()
        elif self.player_alive is True and not is_alive:
            if not is_active:
                logger.info("[音乐播放器] 检测到退出游戏/未在游戏中")
            else:
                logger.info(f"[音乐播放器] 检测到玩家死亡 (血量: {current_health})")
            self.player_alive = False
            self.last_state_change_time = current_time
            self._on_player_death()

        self.last_health = current_health

    def _is_player_active(self, data):
        return (
            "player" in data
            and "activity" in data["player"]
            and data["player"]["activity"] == "playing"
        )

    def _on_player_death(self):
        if not self._music_session_active():
            return

        player = self._ensure_player()

        # 存活侧"淡出到0再暂停"可能仍在进行（标志位未置），先取消，
        # 否则其回调会在死亡处理完之后把音乐暂停，卡在音量0+暂停态
        fade_canceled = False
        try:
            fade_canceled = player.cancel_fade()
        except Exception:
            pass
        was_volume_lowered = self.is_volume_lowered

        if self.is_volume_lowered:
            if config.music_death_volume_custom:
                target_volume = config.music_death_volume
                logger.info(
                    f"[音乐播放器] 死亡 → 恢复音量到自定义: {target_volume * 100:.0f}%"
                )
            else:
                target_volume = 1.0
                logger.info("[音乐播放器] 死亡 → 恢复音量到正常: 100%")

            if config.music_fade_enabled and config.music_fade_in_duration > 0:
                player.fade_volume(
                    target_volume,
                    config.music_fade_in_duration,
                    temporary=True,
                )
            else:
                player.set_volume(target_volume, temporary=True)

            self.is_volume_lowered = False

        if config.music_death_action == "play":
            if not player.is_playing:
                player.play()
                logger.info("[音乐播放器] 死亡 → 开始播放")
            elif player.is_paused:
                player.resume()
                logger.info("[音乐播放器] 死亡 → 恢复播放")
                # v2.2.1: 存活侧若走了"淡出到0再暂停"，原始音量停在0，
                # 直接 resume 会无声——恢复时重放有效音量
                try:
                    player._apply_effective_volume()
                except Exception:
                    pass
            elif fade_canceled and not was_volume_lowered:
                # 淡出被中途取消，音乐仍在播放但音量停在中间值，恢复有效音量
                try:
                    player._apply_effective_volume()
                except Exception:
                    pass
            self.is_paused_by_game = False
        elif config.music_death_action == "pause":
            logger.info("[音乐播放器] 死亡 → 暂停播放")
            if player.is_playing and not player.is_paused:
                player.pause()
                self.is_paused_by_game = True
        elif config.music_death_action == "keep":
            logger.info("[音乐播放器] 死亡 → 保持当前状态")

    def _on_player_alive(self):
        if not self._music_session_active():
            return

        player = self._ensure_player()

        if config.music_revive_action == "pause":
            logger.info("[音乐播放器] 存活 → 暂停播放")
            if config.music_fade_enabled and config.music_fade_out_duration > 0:

                def pause_callback():
                    player.pause()
                    self.is_paused_by_game = True

                player.fade_volume(
                    0,
                    config.music_fade_out_duration,
                    pause_callback,
                    temporary=None,
                )
            else:
                player.pause()
                self.is_paused_by_game = True
        elif config.music_revive_action == "lower":
            target_volume = config.music_revive_volume
            logger.info(
                f"[音乐播放器] 存活 → 降低音量至: {target_volume * 100:.0f}%"
            )
            if config.music_fade_enabled and config.music_fade_out_duration > 0:
                player.fade_volume(
                    target_volume,
                    config.music_fade_out_duration,
                    temporary=True,
                )
            else:
                player.set_volume(target_volume, temporary=True)
            self.is_volume_lowered = True
        elif config.music_revive_action == "keep":
            logger.info("[音乐播放器] 存活 → 保持当前状态")
