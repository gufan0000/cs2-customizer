import threading
import time
from core.audio.runtime_audio import get_runtime_audio_manager
from config import config
from core.utils.logger import get_logger

audio_manager = get_runtime_audio_manager()

class GSIHandlerSpecial:
    def __init__(self):
        self.logger = get_logger("GSIHandlerSpecial")
        # 投掷物相关
        self.current_grenade = None  # 当前手持投掷物
        self.previous_active_weapon = None  # 上一帧手持的武器
        self.previous_grenade_counts = {}  # 上一帧各投掷物数量
        self.grenade_held_type = None  # 当前手持的投掷物类型
        
        # C4相关
        self.previous_bomb_state = ""  # 上一帧的C4状态
        self.bomb_planted_sound_played = False  # 防止重复播放
        self.bomb_planting_detected = False  # 检测planting状态
        self.last_bomb_play_attempt = 0.0  # 上次尝试播放C4音效时间
        self.bomb_play_retry_interval = 0.25  # planted阶段重试间隔，降低偶发漏播
        
        # 血量警告相关
        self.previous_health = 100  # 上一帧的健康值
        self.health_warning_played = False  # 当前低血量警告是否已播放
        self.health_warning_cooldown = 0  # 冷却时间戳
        self.health_warning_cooldown_duration = 5.0  # 默认5秒冷却时间
        
        # 回合状态跟踪
        self.previous_round_phase = ""  # 上一帧回合阶段(map.phase)
        self.previous_round_direct_phase = ""  # 上一帧直接回合阶段(round.phase)
        self.previous_freeze_time = False  # 跟踪上一帧是否是冻结时间
        self.team_side = None  # 玩家所在队伍 (ct/t)
        self.previous_round_win = None  # 上一次回合胜利状态
        self.previous_mvp = ""  # 上一个MVP
        self.previous_mvps_count = 0  # 上一帧MVP数量
        self.round_sounds_played = {}  # 跟踪已播放的回合音效
        
        # MVP检测相关 - 简化
        self.is_current_round_mvp = False  # 玩家是当前回合的MVP
        self.mvp_check_timer = None  # MVP检测定时器
        self.current_round_number = 0  # 当前回合号
        
        # 投掷物类型映射
        self.grenade_types = {
            "weapon_hegrenade": "hegrenade",
            "weapon_flashbang": "flashbang",
            "weapon_smokegrenade": "smoke",
            "weapon_molotov": "molotov",
            "weapon_incgrenade": "incgrenade",
            "weapon_decoy": "decoy"
        }
        
        # 初始化连续帧计数器
        self.frame_counter = 0
        self.debug_mode = bool(getattr(config, "gsi_debug_mode", False))
        
        self.logger.info("[特殊音效] GSI处理器已初始化")
    
    def process_data(self, data):
        """处理GSI数据"""
        self.frame_counter += 1
        
        # ===== 完整GSI数据结构输出 =====
        # 每200帧输出一次完整的GSI数据结构
        if self.debug_mode and self.frame_counter % 200 == 0:
            self.logger.debug("\n[GSI数据] ==========================================")
            self.logger.debug(f"数据类型: {type(data)}")
            self.logger.debug(f"数据键: {list(data.keys())}")
            
            # 打印各部分数据
            if "provider" in data:
                self.logger.debug(f"Provider: {data['provider']}")
            if "map" in data:
                self.logger.debug(f"Map信息: {data['map']}")
            if "round" in data:
                self.logger.debug(f"Round信息: {data['round']}")
            if "player" in data:
                player = data["player"]
                self.logger.debug(f"玩家ID: {player.get('steamid', '未知')}")
                self.logger.debug(f"玩家队伍: {player.get('team', '未知')}")
                self.logger.debug(f"玩家状态: {player.get('state', {})}")
                self.logger.debug(f"玩家活动: {player.get('activity', '未知')}")
            if "bomb" in data:
                self.logger.debug(f"炸弹信息类型: {type(data['bomb'])}")
                self.logger.debug(f"炸弹信息值: {data['bomb']}")

            self.logger.debug("[GSI数据] ==========================================\n")
        
        # 获取当前steamid
        player_data = data.get("player", {})
        current_steamid = player_data.get("steamid", "")
        
        # 观战模式静音检查
        if config.spectator_mode_mute and current_steamid and current_steamid != config.player_steamid:
            return  # 不是玩家本人，且开启了观战静音，直接返回

        # 玩家个人事件（血量/手雷/MVP）只对"本人"数据有效：死亡观战时 GSI 的
        # player 会切成被观战者，若不区分会把队友的低血量/投掷/MVP 当成自己的。
        # C4 与回合胜负是全局事件，不受此限制。
        is_self = (
            not current_steamid
            or not config.player_steamid
            or current_steamid == config.player_steamid
        )

        # activity 在实战中会偶发抖动，避免因此丢失C4/回合事件
        is_active = self._is_player_active(data)
            
        # 检查回合变化并重置状态
        if "map" in data and "round" in data["map"]:
            current_round = int(data["map"]["round"])
            if current_round != self.current_round_number:
                # 回合变化，重置MVP状态
                self.is_current_round_mvp = False
                self.current_round_number = current_round
                # 新回合重置C4状态，避免上一回合残留影响识别
                self.previous_bomb_state = ""
                self.bomb_planted_sound_played = False
                self.bomb_planting_detected = False
                self.last_bomb_play_attempt = 0.0
                # v2.2.1: 一并清胜负跟踪，避免上一回合 win_team 残留
                # 干扰下一回合的胜负判定（同队连胜时尤其明显）
                self.previous_round_win = ""
                self.logger.info(f"[回合变化] 新回合: {current_round}，重置MVP状态")
        
        # 处理投掷物逻辑
        if config.grenade_sound_enabled and is_active and is_self:
            self._process_grenade_throw(data)

        # 处理C4相关逻辑
        if config.c4_sound_enabled:
            self._process_bomb_events(data)

        # 处理血量警告逻辑
        if hasattr(config, 'health_warning_enabled') and config.health_warning_enabled and is_active and is_self:
            self._process_health_warning(data)

        # 处理回合音效逻辑
        if hasattr(config, 'round_sound_enabled') and config.round_sound_enabled:
            self._process_round_sounds(data)

        # MVP检测 - 检查MVP数量变化（观战他人时 match_stats 是对方的，跳过）
        if is_self:
            self._update_mvp_status(data)
    
    def _is_player_active(self, data):
        """检查玩家是否处于活动状态"""
        is_active = (
            "player" in data and 
            "activity" in data["player"] and 
            data["player"]["activity"] == "playing"
        )
        
        if self.debug_mode and self.frame_counter % 100 == 0:
            self.logger.debug(f"[调试] 玩家活动状态: {is_active}")
            
        return is_active
    
    def _update_mvp_status(self, data):
        """更新玩家MVP状态 - 简化版本"""
        # 从玩家数据中获取MVP计数
        if "player" in data and "match_stats" in data["player"]:
            match_stats = data["player"]["match_stats"]
            if "mvps" in match_stats:
                current_mvps = int(match_stats["mvps"])
                self.logger.debug(f"[MVP检测] 玩家MVP计数: 当前={current_mvps}, 之前={self.previous_mvps_count}")

                # 如果MVP计数增加，标记为MVP
                if current_mvps > self.previous_mvps_count:
                    self.logger.info(f"[MVP检测] 检测到MVP计数增加: {self.previous_mvps_count} -> {current_mvps}")
                    self.is_current_round_mvp = True
                    self.logger.debug(f"[MVP检测] 当前回合MVP标志设置为: {self.is_current_round_mvp}")
                
                # 更新前一帧MVP计数，用于下一帧比较
                self.previous_mvps_count = current_mvps
    
    def _check_if_player_is_mvp(self, data):
        """检查当前玩家是否是MVP - 简化版本"""
        self.logger.debug("[MVP检测] 开始检查玩家是否是MVP...")

        # 检查round数据用于调试
        if "round" in data and isinstance(data["round"], dict):
            round_data = data["round"]
            self.logger.debug(f"[MVP检测] 检查round数据: {round_data}")

        # 简化的MVP检测逻辑：只根据MVP标志判断
        self.logger.debug(f"[MVP检测] 当前回合MVP标志: {self.is_current_round_mvp}")
        if self.is_current_round_mvp:
            return True

        self.logger.debug("[MVP检测] 未能确认玩家是MVP")
        return False
    
    def _process_grenade_throw(self, data):
        """处理投掷物检测逻辑 - 基于手持状态和数量变化"""
        player_data = data.get("player", {})
        current_weapons = player_data.get("weapons", {})
        
        # 1. 检测当前手持武器
        active_weapon = None
        
        if current_weapons:
            for weapon_key, weapon_data in current_weapons.items():
                if weapon_data.get("state") == "active":
                    active_weapon = weapon_data.get("name", "")
                    break
        
        # 2. 统计当前各投掷物数量
        current_grenade_counts = {grenade_type: 0 for grenade_type in self.grenade_types.keys()}
        
        # 统计投掷物数量
        for weapon_key, weapon_data in current_weapons.items():
            weapon_name = weapon_data.get("name", "")
            if weapon_name in self.grenade_types:
                # 尝试使用ammo_reserve字段，如果不存在则默认为1
                reserve_count = weapon_data.get("ammo_reserve", 1)
                current_grenade_counts[weapon_name] += reserve_count
        
        # 3. 检测投掷动作: 如果之前手持的是手雷，且该手雷数量减少，判定为投掷
        if self.previous_active_weapon in self.grenade_types:
            previous_count = self.previous_grenade_counts.get(self.previous_active_weapon, 0)
            current_count = current_grenade_counts.get(self.previous_active_weapon, 0)
            
            if current_count < previous_count:
                grenade_type = self.grenade_types.get(self.previous_active_weapon)
                self.logger.info(f"[投掷检测] 检测到投掷: {grenade_type} (数量从 {previous_count} 变为 {current_count})")
                
                # 播放对应音效
                self._play_grenade_sound(grenade_type)
        
        # 当前手持的是手雷时，记录手雷类型
        if active_weapon in self.grenade_types:
            self.grenade_held_type = active_weapon
            if self.previous_active_weapon != active_weapon:
                self.logger.debug(f"[调试-投掷物] 现在手持投掷物: {active_weapon}")
        else:
            self.grenade_held_type = None
        
        # 更新状态，为下一帧做准备
        self.previous_active_weapon = active_weapon
        self.previous_grenade_counts = current_grenade_counts.copy()

    @staticmethod
    def _resolve_style_value(style):
        if isinstance(style, dict):
            if style.get("enabled") is False:
                return "0"
            return str(style.get("style", "0")).strip()
        if style is None:
            return "0"
        return str(style).strip()

    def _style_disabled(self, style):
        style = self._resolve_style_value(style)
        return style in ("0", "不启用", "未启用", "") or not style
    
    def _play_grenade_sound(self, grenade_type):
        """播放投掷物音效"""
        # 根据手雷类型获取配置的音效样式
        style = "0"  # 默认样式
        
        if hasattr(config, 'grenade_sound_styles') and grenade_type in config.grenade_sound_styles:
            style = self._resolve_style_value(config.grenade_sound_styles.get(grenade_type, "0"))
        
        if self._style_disabled(style):
            self.logger.debug(f"[投掷音效] {grenade_type}未配置音效风格，跳过播放")
            return  # 样式为0表示不播放
        
        # 构建音效键
        sound_key = f"grenade-{grenade_type}-{style}"
        
        # 播放音效。v2.2.1: allow_preempt 改为 True——手雷是单通道(ch5)，
        # 连投两颗雷（烟接闪很常见）时第一声未播完，第二声会被 preempt_disabled
        # 直接吞掉。同优先级下新雷切旧声，切断优于静音。
        audio_manager.play_sound(sound_key, channel_type="grenade_sound", event_type="grenade", priority=45, allow_preempt=True)
        self.logger.info(f"[投掷音效] 播放{grenade_type}投掷音效: {sound_key}")
    
    def _process_bomb_events(self, data):
        """处理C4相关事件 - 修复版本"""
        # 获取炸弹数据 - 修复字符串类型处理
        bomb_data = None
        bomb_state = ""
        
        # 检查bomb数据类型并适当处理
        if "bomb" in data:
            # 可能是字符串或字典
            if isinstance(data["bomb"], str):
                bomb_state = data["bomb"]
                self.logger.debug(f"[C4检测] 发现炸弹状态(字符串): {bomb_state}")
            elif isinstance(data["bomb"], dict):
                bomb_data = data["bomb"]
                bomb_state = bomb_data.get("state", "")
                self.logger.debug(f"[C4检测] 发现炸弹数据(字典): {bomb_data}")
            else:
                self.logger.debug(f"[C4检测] 未知炸弹数据类型: {type(data['bomb'])}")
        
        # 如果没有直接的炸弹数据，从其他地方寻找
        if not bomb_state and "map" in data and "phase" in data["map"]:
            map_phase = data["map"]["phase"]
            if map_phase == "planted":
                bomb_state = "planted"
                self.logger.debug(f"[C4检测] 通过map.phase检测到C4已安装: {map_phase}")
        
        if not bomb_state and "round" in data:
            round_data = data["round"]
            if isinstance(round_data, dict) and "bomb" in round_data:
                if isinstance(round_data["bomb"], str):
                    bomb_state = round_data["bomb"]
                    self.logger.debug(f"[C4检测] 通过round.bomb检测到炸弹状态: {bomb_state}")
        
        # 如果没有找到炸弹状态，退出
        if not bomb_state:
            return
        bomb_state = str(bomb_state).strip().lower()
        
        # 检测planting状态
        if bomb_state == "planting" and not self.bomb_planting_detected:
            self.bomb_planting_detected = True
            self.logger.info("[C4检测] 检测到正在安装C4")
        
        # 检测planted状态：未播成功前才尝试，且重试一律受 retry_interval 节流。
        # 旧逻辑 state_changed/planting_detected 会绕过时间门，播放失败时每帧重试刷屏。
        retry_ready = (
            self.last_bomb_play_attempt == 0.0
            or (time.time() - self.last_bomb_play_attempt) >= self.bomb_play_retry_interval
        )
        should_attempt_planted = (
            bomb_state == "planted"
            and not self.bomb_planted_sound_played
            and retry_ready
        )
        
        if should_attempt_planted:
            self.logger.info("[C4检测] 检测到C4已安装")
            
            # 获取配置的C4音效样式
            style = self._resolve_style_value(config.c4_sound_style if hasattr(config, 'c4_sound_style') else "0")
            
            if not self._style_disabled(style) and not self.bomb_planted_sound_played:
                # 构建音效键
                sound_key = f"c4-planted-{style}"
                
                # 播放音效
                try:
                    self.last_bomb_play_attempt = time.time()
                    played = audio_manager.play_sound(sound_key, channel_type="c4_sound", event_type="c4", priority=80, allow_preempt=True)
                    if played:
                        self.logger.info(f"[C4音效] 播放C4安装音效: {sound_key}")
                        self.bomb_planted_sound_played = True
                    else:
                        self.logger.warning(f"[C4音效] 播放返回False，等待下次重试: {sound_key}")
                except Exception:
                    self.logger.exception("[C4音效] 播放失败")
            elif self._style_disabled(style):
                # 样式未配置视为已处理，否则本回合会每 0.25s 重试并刷日志
                self.bomb_planted_sound_played = True
                self.logger.debug("[C4音效] 当前样式为0，跳过播放")
        
        # planting被取消或炸弹流程结束时重置标志，避免后续误触发/漏触发
        if bomb_state in ["defused", "exploded", "carried", "dropped"]:
            if bomb_state != self.previous_bomb_state:
                self.logger.info(f"[C4检测] 检测到C4状态变化: {self.previous_bomb_state} -> {bomb_state}")
            self.bomb_planted_sound_played = False
            self.bomb_planting_detected = False
            self.last_bomb_play_attempt = 0.0
        
        # 更新状态
        self.previous_bomb_state = bomb_state
    
    def _process_health_warning(self, data):
        """处理血量警告逻辑"""
        current_time = time.time()
        
        # 如果在冷却时间内，直接返回
        if current_time < self.health_warning_cooldown:
            return
            
        # 获取玩家当前血量
        player_data = data.get("player", {})
        if "state" in player_data and "health" in player_data["state"]:
            current_health = player_data["state"]["health"]
            
            # 检查是否低于警告阈值
            if (current_health > 0 and  # 确保玩家没有死亡
                current_health <= config.health_warning_threshold and  # 低于阈值
                self.previous_health > config.health_warning_threshold and  # 从高于阈值变为低于阈值
                not self.health_warning_played):  # 当前低血量状态下尚未播放
                
                self.logger.info(f"[血量警告] 检测到血量低于阈值: {current_health}/{config.health_warning_threshold}")
                
                # 播放警告音效
                self._play_health_warning_sound()
                
                # 设置已播放标志和冷却时间
                self.health_warning_played = True
                self.health_warning_cooldown = current_time + self.health_warning_cooldown_duration
            
            # 如果血量恢复到阈值以上，重置已播放标志
            elif current_health > config.health_warning_threshold and self.health_warning_played:
                self.health_warning_played = False
                self.logger.debug(f"[血量警告] 血量已恢复: {current_health}/{config.health_warning_threshold}")
            
            # 更新上一帧血量
            self.previous_health = current_health
    
    def _play_health_warning_sound(self):
        """播放血量警告音效"""
        # 获取配置的音效样式
        style = self._resolve_style_value(config.health_warning_style if hasattr(config, 'health_warning_style') else "0")
        
        if self._style_disabled(style):
            self.logger.debug("[血量警告] 未配置音效风格，跳过播放")
            return
        
        # 构建音效键
        sound_key = f"health-warning-{style}"
        
        try:
            # 尝试确保音效已加载
            if sound_key not in audio_manager.sounds:
                audio_manager.load_health_warning_sound(style)
            
            # 播放音效
            audio_manager.play_sound(sound_key, channel_type="health_warning", event_type="health_warning", priority=70, allow_preempt=True)
            self.logger.info(f"[血量警告] 播放音效: {sound_key}")
        except Exception:
            self.logger.exception("[血量警告] 播放失败")
    
    def _process_round_sounds(self, data):
        """处理回合音效"""
        self.logger.debug("\n[回合音效] 开始处理回合音效数据")
        
        # 确定玩家团队
        self._update_player_team(data)
        self.logger.debug(f"[回合音效] 玩家所在队伍: {self.team_side}")
        
        # 检测回合阶段变化
        current_phase = ""
        is_freeze_time = False
        round_win = None
        
        if "map" in data:
            # 获取回合阶段
            if "phase" in data["map"]:
                current_phase = data["map"]["phase"]
                self.logger.debug(f"[回合音效] 当前回合阶段: {current_phase}")
        
        # 获取round.phase和回合胜利信息
        round_phase = ""
        current_win_team = ""
        if "round" in data:
            if "phase" in data["round"]:
                round_phase = data["round"]["phase"]
                self.logger.debug(f"[回合音效] 当前round.phase: {round_phase}")
                # 冻结时间判断
                is_freeze_time = round_phase == "freezetime"
            
            # 获取回合胜利团队
            if "win_team" in data["round"]:
                win_team = data["round"]["win_team"]
                current_win_team = str(win_team).lower() if win_team else ""
                if current_win_team and current_win_team != self.previous_round_win:
                    self.logger.info(f"[回合音效] 检测到回合胜利队伍: {win_team}")
                    round_win = current_win_team  # 转为小写以匹配self.team_side格式
            
            # 调试：输出完整的round数据
            self.logger.debug(f"[回合音效] 回合数据: {data['round']}")
        
        # 检测回合开始(冻结阶段)
        if is_freeze_time and not self.previous_freeze_time:
            self.logger.info("[回合音效] 检测到回合开始(冻结时间)")
            self._play_round_start_sound()
            # 重置MVP状态
            self.is_current_round_mvp = False
            self.logger.debug(f"[MVP检测] 冻结时间开始，重置MVP标志: {self.is_current_round_mvp}")
        
        # 检测行动开始阶段 - 基于round.phase变化
        if round_phase == "live" and self.previous_round_direct_phase != "live":
            self.logger.info("[回合音效] 检测到行动开始")
            self._play_action_start_sound()
        
        # 检测回合结束 - 当round.phase变为"over"时
        if round_phase == "over" and self.previous_round_direct_phase != "over":
            self.logger.info("[回合音效] 检测到回合结束")

            # v2.2.1: 解耦"win_team刚变化"与"phase翻over"两个边沿——
            # GSI 可能先发 win_team 再翻 over（差一帧以上），旧逻辑要求两者同帧，
            # 否则 round_win 为空 → 胜/负/MVP 音效整块丢失。over 沿直接用本帧 win_team。
            effective_win = round_win or current_win_team

            # 如果已知胜利队伍，判断胜负
            if effective_win:
                if effective_win == self.team_side:
                    self.logger.info(f"[回合音效] 玩家队伍胜利: {self.team_side}")
                    
                    # 启动短暂定时器检查MVP状态
                    if self.mvp_check_timer:
                        self.mvp_check_timer.cancel()
                    
                    self.mvp_check_timer = threading.Timer(0.15, self._check_and_play_win_sound, [data])
                    self.mvp_check_timer.daemon = True
                    self.mvp_check_timer.start()
                else:
                    self.logger.info(f"[回合音效] 玩家队伍失败: {self.team_side}≠{effective_win}")
                    self._play_round_lose_sound()
        
        # 更新状态
        self.previous_freeze_time = is_freeze_time
        self.previous_round_phase = current_phase
        self.previous_round_direct_phase = round_phase
        self.previous_round_win = current_win_team
        
        self.logger.debug("[回合音效] 处理完成\n")
    
    def _check_and_play_win_sound(self, data):
        """短暂延迟后检查MVP状态并播放相应音效"""
        # 检查玩家是否为MVP
        player_is_mvp = self._check_if_player_is_mvp(data)
        
        if player_is_mvp:
            self.logger.info("[回合音效] 确认玩家是本回合MVP，播放MVP音效")
            self._play_mvp_sound()
        else:
            self.logger.info("[回合音效] 上回合玩家不是MVP，播放常规胜利音效")
            self._play_round_win_sound()
    
    def _update_player_team(self, data):
        """更新玩家所在队伍 - 增强版"""
        old_team = self.team_side
        
        # 尝试多种方式获取玩家队伍
        if "player" in data and "team" in data["player"]:
            team = data["player"]["team"]
            if team in ["CT", "T"]:
                self.team_side = team.lower()
                if self.team_side != old_team:
                    self.logger.info(f"[回合音效] 玩家队伍更新: {old_team} -> {self.team_side}")
        
        # 尝试从allplayers中获取
        elif "allplayers" in data and isinstance(data["allplayers"], dict) and config.player_steamid:
            for player_id, player_data in data["allplayers"].items():
                if player_data.get("steamid") == config.player_steamid and "team" in player_data:
                    team = player_data["team"]
                    if team in ["CT", "T"]:
                        self.team_side = team.lower()
                        if self.team_side != old_team:
                            self.logger.info(f"[回合音效] 玩家队伍更新(通过allplayers): {old_team} -> {self.team_side}")
                        break
    
    def _play_round_start_sound(self):
        """播放回合开始音效"""
        style = self._resolve_style_value(getattr(config, 'round_start_style', "0"))
        if self._style_disabled(style):
            self.logger.debug("[回合音效] 回合开始音效未启用")
            return
        
        # 确保音效已加载
        audio_manager.load_round_sound("start", style)
            
        # 构建音效键并播放
        sound_key = f"round-start-{style}"
        self.logger.info(f"[回合音效] 播放回合开始音效: {sound_key}")
        
        try:
            # 使用淡入淡出效果播放
            if hasattr(audio_manager, 'play_sound_with_fade'):
                audio_manager.play_sound_with_fade(sound_key, channel_type="round_sound", fade_in_ms=500, fade_out_ms=1000)
            else:
                # 如果没有淡入淡出方法，使用普通播放
                audio_manager.play_sound(
                    sound_key,
                    channel_type="round_sound",
                    event_type="round_start",
                    priority=55,
                    allow_preempt=False,
                )
            self.logger.info("[回合音效] 成功播放回合开始音效")
        except Exception:
            self.logger.exception("[回合音效] 播放回合开始音效失败")
        
        # 记录已播放
        self.round_sounds_played["start"] = True
    
    def _play_action_start_sound(self):
        """播放行动开始音效"""
        style = self._resolve_style_value(getattr(config, 'round_action_style', "0"))
        if self._style_disabled(style):
            self.logger.debug("[回合音效] 行动开始音效未启用")
            return
        
        # 确保音效已加载
        audio_manager.load_round_sound("action", style)
            
        # 构建音效键并播放
        sound_key = f"round-action-{style}"
        self.logger.info(f"[回合音效] 播放行动开始音效: {sound_key}")
        
        try:
            # 使用淡入淡出效果播放
            if hasattr(audio_manager, 'play_sound_with_fade'):
                audio_manager.play_sound_with_fade(sound_key, channel_type="round_sound", fade_in_ms=500, fade_out_ms=1000)
            else:
                # 如果没有淡入淡出方法，使用普通播放
                audio_manager.play_sound(
                    sound_key,
                    channel_type="round_sound",
                    event_type="round_action",
                    priority=60,
                    allow_preempt=False,
                )
            self.logger.info("[回合音效] 成功播放行动开始音效")
        except Exception:
            self.logger.exception("[回合音效] 播放行动开始音效失败")
    
    def _play_round_win_sound(self):
        """播放回合胜利音效"""
        style = self._resolve_style_value(getattr(config, 'round_win_style', "0"))
        if self._style_disabled(style):
            self.logger.debug("[回合音效] 回合胜利音效未启用")
            return
            
        # 确保音效已加载
        audio_manager.load_round_sound("win", style)
            
        # 构建音效键并播放
        sound_key = f"round-win-{style}"
        self.logger.info(f"[回合音效] 播放回合胜利音效: {sound_key}")
        
        try:
            # 使用淡入淡出效果播放
            if hasattr(audio_manager, 'play_sound_with_fade'):
                audio_manager.play_sound_with_fade(sound_key, channel_type="round_sound", fade_in_ms=500, fade_out_ms=1000)
            else:
                # 如果没有淡入淡出方法，使用普通播放
                audio_manager.play_sound(
                    sound_key,
                    channel_type="round_sound",
                    event_type="round_win",
                    priority=88,
                    allow_preempt=True,
                )
            self.logger.info("[回合音效] 成功播放回合胜利音效")
        except Exception:
            self.logger.exception("[回合音效] 播放回合胜利音效失败")
        
        # 记录已播放
        self.round_sounds_played["win"] = True
    
    def _play_round_lose_sound(self):
        """播放回合失败音效"""
        style = self._resolve_style_value(getattr(config, 'round_lose_style', "0"))
        if self._style_disabled(style):
            self.logger.debug("[回合音效] 回合失败音效未启用")
            return
            
        # 确保音效已加载
        audio_manager.load_round_sound("lose", style)
            
        # 构建音效键并播放
        sound_key = f"round-lose-{style}"
        self.logger.info(f"[回合音效] 播放回合失败音效: {sound_key}")
        
        try:
            # 使用淡入淡出效果播放
            if hasattr(audio_manager, 'play_sound_with_fade'):
                audio_manager.play_sound_with_fade(sound_key, channel_type="round_sound", fade_in_ms=500, fade_out_ms=1000)
            else:
                # 如果没有淡入淡出方法，使用普通播放
                audio_manager.play_sound(
                    sound_key,
                    channel_type="round_sound",
                    event_type="round_lose",
                    priority=88,
                    allow_preempt=True,
                )
            self.logger.info("[回合音效] 成功播放回合失败音效")
        except Exception:
            self.logger.exception("[回合音效] 播放回合失败音效失败")
        
        # 记录已播放
        self.round_sounds_played["lose"] = True
    
    def _play_mvp_sound(self):
        """播放MVP音效"""
        style = self._resolve_style_value(getattr(config, 'round_mvp_style', "0"))
        if self._style_disabled(style):
            self.logger.debug("[回合音效] MVP音效未启用")
            return
            
        # 确保音效已加载
        audio_manager.load_round_sound("mvp", style)
            
        # 构建音效键并播放
        sound_key = f"round-mvp-{style}"
        self.logger.info(f"[回合音效] 播放MVP音效: {sound_key}")
        
        try:
            # 使用淡入淡出效果播放
            if hasattr(audio_manager, 'play_sound_with_fade'):
                audio_manager.play_sound_with_fade(sound_key, channel_type="round_sound", fade_in_ms=500, fade_out_ms=1000)
            else:
                # 如果没有淡入淡出方法，使用普通播放
                audio_manager.play_sound(
                    sound_key,
                    channel_type="round_sound",
                    event_type="round_mvp",
                    priority=90,
                    allow_preempt=True,
                )
            self.logger.info("[回合音效] 成功播放MVP音效")
        except Exception:
            self.logger.exception("[回合音效] 播放MVP音效失败")
        
        # 记录已播放
        self.round_sounds_played["mvp"] = True

