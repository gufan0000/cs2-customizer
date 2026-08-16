# SPDX-License-Identifier: GPL-3.0-or-later
import threading
import time
from core.audio.runtime_audio import get_runtime_audio_manager
from core.audio.special_events import get_event, sound_key
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
        self.round_sounds_played = {}  # 跟踪已播放的回合音效
        
        # MVP检测相关
        self.is_current_round_mvp = False  # 玩家是当前回合的MVP
        self.mvp_check_timer = None  # MVP检测定时器
        self.current_round_number = 0  # 当前回合号
        # None 表示"还没观测过"。**不能用 0 当初值**：那会让首帧读到的真实
        # 计数被当成一次增长，见 _update_mvp_status。
        self.previous_mvps_count = None
        # over 边沿后等 MVP 计数落地用。旧实现是一个写死的 0.15s 定时器，
        # 赌 GSI 在这个窗口内把计数推过来，没有任何判据守着这个数字。
        self._mvp_resolved = threading.Event()

        # 比赛级事件跟踪。
        # None = 还没观测过。同 previous_mvps_count，**首帧只播种不判定**：
        # 中途启动软件时 map.phase 直接就是 live，拿 "" 当上一帧会误播"比赛开始"。
        self.previous_map_phase = None
        self.previous_team_side = None
        self.match_start_played = False
        
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

        # MVP检测。**这里不能再用 is_self 挡**：死亡观战时 player 块是被观战者的，
        # 一挡就等于"死了就看不见自己的 MVP 增量"，而回合结束恰恰常在你已阵亡时
        # 发生（埋包 MVP 是最典型的例子）。改由 _update_mvp_status 内部按 steamid
        # 从 allplayers 里认自己，认不出来才退回 player 块。
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
    
    def _read_own_mvp_count(self, data):
        """读取**本人**的 MVP 计数，读不到返回 None。

        优先从 `allplayers` 里按 steamid 找自己，其次才用 `player` 块——顺序
        不能反，这是"死了就拿不到 MVP 音效"那个缺陷的根子：

        死亡观战时 GSI 的 `player` 块会切成**被观战者**。而回合结束这一刻，
        你如果已经阵亡（埋包后被清、残局被换掉），`player` 里装的是队友的
        match_stats。旧实现在这种情况下被 `is_self` 挡掉，整帧跳过，于是
        自己的 MVP 增量在 over 边沿之前根本没被看见 —— MVP 音效只在
        "你活到回合结束"时才响，而埋包 MVP 恰恰最常在死后拿到。

        `allplayers_match_stats` 在 GSI cfg 里是开着的（cfg_utils.CFG_TEMPLATE），
        所以按 steamid 取自己是有数据支撑的；取不到时才退回旧路径。
        """
        steamid = getattr(config, "player_steamid", "") or ""

        allplayers = data.get("allplayers")
        if steamid and isinstance(allplayers, dict):
            for entry in allplayers.values():
                if not isinstance(entry, dict):
                    continue
                # allplayers 的键有时是 steamid、有时是槽位号，两种都认
                if str(entry.get("steamid", "")) != str(steamid):
                    continue
                stats = entry.get("match_stats") or {}
                if "mvps" in stats:
                    return int(stats["mvps"])

        player = data.get("player") or {}
        player_steamid = str(player.get("steamid", "") or "")
        # 没配 steamid 时无法分辨自己和被观战者，只能信 player 块
        is_self = (not steamid) or (not player_steamid) or player_steamid == steamid
        if is_self:
            stats = player.get("match_stats") or {}
            if "mvps" in stats:
                return int(stats["mvps"])
        return None

    def _update_mvp_status(self, data):
        """跟踪本人的 MVP 计数，计数增长即标记本回合为 MVP。"""
        current_mvps = self._read_own_mvp_count(data)
        if current_mvps is None:
            return

        if self.previous_mvps_count is None:
            # **首次观测播种，不比较**。旧实现把初值 0 当成"上一帧的真实计数"，
            # 于是中途启动软件/掉线重连时，第一帧读到的 3 会被当成"从 0 涨到 3"，
            # 当前回合直接被误标成 MVP —— 只要这一局你队赢了就会误播 MVP 音效。
            self.previous_mvps_count = current_mvps
            self.logger.info(f"[MVP检测] 首次观测到 MVP 计数={current_mvps}，播种不判定")
            return

        if current_mvps > self.previous_mvps_count:
            self.logger.info(
                f"[MVP检测] MVP 计数增加: {self.previous_mvps_count} -> {current_mvps}"
            )
            self.is_current_round_mvp = True
            self._mvp_resolved.set()
        elif current_mvps < self.previous_mvps_count:
            # 换了一局，计数归零。重新播种即可，不是 MVP 事件
            self.logger.info(f"[MVP检测] MVP 计数回落到 {current_mvps}，按新比赛重新播种")

        self.previous_mvps_count = current_mvps
    
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
            style = self._resolve_style_value(getattr(config, "c4_sound_style", "0"))
            if self._style_disabled(style):
                # 样式未配置视为已处理，否则本回合会每 0.25s 重试并刷日志
                self.bomb_planted_sound_played = True
                self.logger.debug("[C4音效] 当前样式为0，跳过播放")
            else:
                self.last_bomb_play_attempt = time.time()
                if self._play_event("c4", "planted"):
                    self.bomb_planted_sound_played = True
                else:
                    self.logger.warning("[C4音效] 未播出，等待下次重试")

        # 拆除 / 爆炸（2.2.4 新增）。这两个是一次性边沿，不像安放那样要重试：
        # 它们之后回合就结束了，没有"再来一次"的机会窗口。
        if bomb_state != self.previous_bomb_state:
            if bomb_state == "defused":
                self.logger.info("[C4检测] 检测到C4被拆除")
                self._play_event("c4", "defused")
            elif bomb_state == "exploded":
                self.logger.info("[C4检测] 检测到C4爆炸")
                self._play_event("c4", "exploded")

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
                self._play_event("health", "warning")

                # 设置已播放标志和冷却时间。冷却时长以前写死在代码里（5 秒），
                # 嫌吵和嫌少的用户都没法调，现在从配置读。
                self.health_warning_played = True
                try:
                    cooldown = float(
                        getattr(config, "health_warning_cooldown", self.health_warning_cooldown_duration)
                    )
                except (TypeError, ValueError):
                    cooldown = self.health_warning_cooldown_duration
                self.health_warning_cooldown = current_time + max(0.0, cooldown)
            
            # 如果血量恢复到阈值以上，重置已播放标志
            elif current_health > config.health_warning_threshold and self.health_warning_played:
                self.health_warning_played = False
                self.logger.debug(f"[血量警告] 血量已恢复: {current_health}/{config.health_warning_threshold}")
            
            # 更新上一帧血量
            self.previous_health = current_health
    
    def _play_health_warning_sound(self):
        """播放血量警告音效。保留这个名字是因为测试和外部调用点在用它。"""
        return self._play_event("health", "warning")
    
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
                # 冻结时间判断。**热身期一律记作"不在冻结"**，不只是"不播"。
                # 热身期 CS2 的 map.phase 是 warmup 而 round.phase 照样报
                # freezetime；如果只在播放处排除热身、却照常把 True 记进
                # previous_freeze_time，那么热身结束进入真正第一回合的冻结期时
                # **没有上升沿**，第一回合的开始音效会整个丢掉。
                is_freeze_time = round_phase == "freezetime" and data.get("map", {}).get("phase") != "warmup"
            
            # 获取回合胜利团队
            if "win_team" in data["round"]:
                win_team = data["round"]["win_team"]
                current_win_team = str(win_team).lower() if win_team else ""
                if current_win_team and current_win_team != self.previous_round_win:
                    self.logger.info(f"[回合音效] 检测到回合胜利队伍: {win_team}")
                    round_win = current_win_team  # 转为小写以匹配self.team_side格式
            
            # 调试：输出完整的round数据
            self.logger.debug(f"[回合音效] 回合数据: {data['round']}")
        
        # ── 比赛级事件（2.2.4 新增）────────────────────────────────────
        # 热身期 CS2 的 map.phase 是 "warmup"，而 round.phase 照样报 freezetime。
        # 所以"回合开始"的边沿必须把热身排除掉，否则热身开始时响一声、而真正
        # 的第一回合因为 previous_freeze_time 还是 True 反而不响。
        in_warmup = current_phase == "warmup"
        first_frame = self.previous_map_phase is None

        if current_phase == "warmup" and self.previous_map_phase != "warmup":
            # 回到热身 = 换了一局，比赛开始可以再响一次
            self.match_start_played = False

        if (
            not first_frame
            and current_phase == "live"
            and self.previous_map_phase == "warmup"
            and not self.match_start_played
        ):
            self.logger.info("[回合音效] 检测到比赛开始")
            self._play_event("round", "match_start")
            self.match_start_played = True

        if not first_frame and current_phase == "gameover" and self.previous_map_phase != "gameover":
            self.logger.info("[回合音效] 检测到比赛结束")
            self._play_event("round", "match_end")

        # 半场交换：自己的阵营变了且不是刚进服（previous_team_side 已知）
        if (
            self.team_side
            and self.previous_team_side
            and self.team_side != self.previous_team_side
        ):
            self.logger.info(
                f"[回合音效] 检测到半场交换: {self.previous_team_side} -> {self.team_side}"
            )
            self._play_event("round", "halftime")
        if self.team_side:
            self.previous_team_side = self.team_side

        # 检测回合开始(冻结阶段)。is_freeze_time 里已经排除了热身，见上面。
        if is_freeze_time and not self.previous_freeze_time:
            self.logger.info("[回合音效] 检测到回合开始(冻结时间)")
            self._play_event("round", "start")
            # 重置MVP状态。**必须连 Event 一起清**，否则上一回合置位的 Event
            # 会让下一回合的等待立刻返回。
            self.is_current_round_mvp = False
            self._mvp_resolved.clear()
            self.logger.debug("[MVP检测] 冻结时间开始，重置MVP标志")

        # 检测行动开始阶段 - 基于round.phase变化
        if round_phase == "live" and self.previous_round_direct_phase != "live" and not in_warmup:
            self.logger.info("[回合音效] 检测到行动开始")
            self._play_event("round", "action")

        # 检测回合结束 - 当round.phase变为"over"时
        if round_phase == "over" and self.previous_round_direct_phase != "over" and not in_warmup:
            self.logger.info("[回合音效] 检测到回合结束")

            # v2.2.1: 解耦"win_team刚变化"与"phase翻over"两个边沿——
            # GSI 可能先发 win_team 再翻 over（差一帧以上），旧逻辑要求两者同帧，
            # 否则 round_win 为空 → 胜/负/MVP 音效整块丢失。over 沿直接用本帧 win_team。
            effective_win = round_win or current_win_team

            # 如果已知胜利队伍，判断胜负
            if effective_win:
                if effective_win == self.team_side:
                    self.logger.info(f"[回合音效] 玩家队伍胜利: {self.team_side}")

                    # 在后台等 MVP 计数落地（详见 _check_and_play_win_sound）。
                    # 不能在 GSI 线程上直接等——那会把整条 GSI 管线堵住，
                    # 而我们等的正是后续 GSI 帧。
                    if self.mvp_check_timer:
                        self.mvp_check_timer.cancel()
                    self.mvp_check_timer = threading.Timer(0.0, self._check_and_play_win_sound)
                    self.mvp_check_timer.daemon = True
                    self.mvp_check_timer.start()
                else:
                    self.logger.info(f"[回合音效] 玩家队伍失败: {self.team_side}≠{effective_win}")
                    self._play_event("round", "lose")

        # 更新状态
        self.previous_freeze_time = is_freeze_time
        self.previous_round_phase = current_phase
        self.previous_map_phase = current_phase
        self.previous_round_direct_phase = round_phase
        self.previous_round_win = current_win_team

        self.logger.debug("[回合音效] 处理完成\n")
    
    #: over 边沿后最多等多久让 MVP 计数落地。GSI 是 throttle 0.0 / buffer 0.01，
    #: 正常一两帧就到；给到 1.2s 是为了覆盖卡顿，等到了就立刻走、不会白等。
    MVP_RESOLVE_TIMEOUT_S = 1.2

    def _check_and_play_win_sound(self, _data=None):
        """等 MVP 计数落地，然后播 MVP 或普通胜利音效。

        旧实现是 `threading.Timer(0.15, ...)` —— 赌 GSI 在 150ms 内把 MVP 计数
        推过来。推慢了就退化成普通胜利音效，而且**没有任何判据守着 0.15 这个
        数字**，改快改慢都不会有人发现。现在改成"等到 MVP 事件或超时"：
        到了就立刻响应，没到就等满超时，两头都不赌。
        """
        resolved = self._mvp_resolved.wait(self.MVP_RESOLVE_TIMEOUT_S)
        if self.is_current_round_mvp:
            self.logger.info(
                f"[回合音效] 确认玩家是本回合MVP（等待{'命中' if resolved else '超时后仍成立'}），播放MVP音效"
            )
            self._play_event("round", "mvp")
        else:
            self.logger.info("[回合音效] 玩家不是本回合MVP，播放常规胜利音效")
            self._play_event("round", "win")

    def _update_player_team(self, data):
        """更新玩家所在队伍。

        **按 steamid 找自己优先，`player.team` 只是兜底**。旧实现顺序是反的
        （`if player.team ... elif allplayers ...`），而 `player.team` 几乎总是
        存在，所以那条 elif **永远走不到**。观战他人时（休闲/死斗可以观战敌方）
        `team_side` 会跟着被观战者跑，胜/负音效直接反过来。
        """
        old_team = self.team_side
        steamid = getattr(config, "player_steamid", "") or ""
        resolved = None

        allplayers = data.get("allplayers")
        if steamid and isinstance(allplayers, dict):
            for entry in allplayers.values():
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("steamid", "")) != str(steamid):
                    continue
                team = entry.get("team")
                if team in ("CT", "T"):
                    resolved = team.lower()
                break

        if resolved is None:
            player = data.get("player") or {}
            player_steamid = str(player.get("steamid", "") or "")
            # 观战别人时 player 块是对方的，这时候宁可保持上一次的判定
            if (not steamid) or (not player_steamid) or player_steamid == steamid:
                team = player.get("team")
                if team in ("CT", "T"):
                    resolved = team.lower()

        if resolved is not None and resolved != old_team:
            self.team_side = resolved
            self.logger.info(f"[回合音效] 玩家队伍更新: {old_team} -> {resolved}")
        elif resolved is not None:
            self.team_side = resolved
    
    def _play_event(self, group: str, key: str) -> bool:
        """播放一个特殊音效事件。**五个 `_play_round_*` 方法合并成的这一个。**

        原来 start/action/win/lose/mvp 各有一个近乎逐字复制的方法，差别只在
        风格字段名、音效键、优先级三处。复制粘贴的代价不只是行数：
        - 那五份里 `priority=88/90` 和 `allow_preempt` 全是**死代码**，因为
          `hasattr(audio_manager, 'play_sound_with_fade')` 恒真，else 分支从没跑过；
        - 于是回合音效实际上绕过了音频策略层，抢占关系无人管理（已在
          audio_manager._admit_playback 一并修掉）。

        事件的全部属性来自 core/audio/special_events 的事件表。
        """
        event = get_event(group, key)
        if event is None:
            self.logger.warning(f"[特殊音效] 未知事件: {group}/{key}")
            return False

        style = self._resolve_style_value(getattr(config, event.config_attr, "0"))
        if self._style_disabled(style):
            self.logger.debug(f"[特殊音效] {event.label}未启用")
            return False

        # 确保素材已加载（冷键第一次触发时 _sounds 里还没有）
        if event.group == "round":
            audio_manager.load_round_sound(event.key, style)
        elif event.group == "c4":
            audio_manager.load_c4_sound(style, event.key)
        else:
            audio_manager.load_health_warning_sound(style)

        key_name = sound_key(event, style)
        channel = "round_sound" if event.group == "round" else (
            "c4_sound" if event.group == "c4" else "health_warning"
        )
        event_type = f"round_{event.key}" if event.group == "round" else (
            "c4" if event.group == "c4" else "health_warning"
        )

        try:
            if event.fade:
                played = audio_manager.play_sound_with_fade(
                    key_name,
                    channel_type=channel,
                    fade_in_ms=500,
                    fade_out_ms=1000,
                    event_type=event_type,
                    priority=event.priority,
                    allow_preempt=True,
                )
            else:
                played = audio_manager.play_sound(
                    key_name,
                    channel_type=channel,
                    event_type=event_type,
                    priority=event.priority,
                    allow_preempt=True,
                )
            if played:
                self.logger.info(f"[特殊音效] 播放{event.label}: {key_name}")
                self.round_sounds_played[event.key] = True
            else:
                self.logger.warning(f"[特殊音效] {event.label}未播出: {key_name}")
            return bool(played)
        except Exception:
            self.logger.exception(f"[特殊音效] 播放{event.label}失败")
            return False

