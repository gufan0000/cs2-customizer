import time
import os
from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS, find_audio_by_stem
from core.audio.runtime_audio import get_runtime_audio_manager
from config import config
from core.utils.logger import get_logger

audio_manager = get_runtime_audio_manager()

class GSIHandlerKills:
    def __init__(self):
        self.logger = get_logger("GSIHandlerKills")
        # 图像播放器
        self.image_player = None
        
        # 玩家数据跟踪
        self.previous_round_kills = {}
        self.previous_round = -1
        self.previous_total_kills = {}
        self.previous_match_kills = {}
        self.last_kill_sound_time = 0
        self.debounce_delay = 0.05
        self.played_sounds_this_round = {}
        self.new_round_start_time = {}
        # v2.2.1: 0.8→0.3。残留计数总在回合切换后立即到达，0.3s 足够吸收；
        # 更长的窗口只会增加吞掉真实首杀的概率（真实击杀另有开火推断放行兜底）。
        self.round_transition_guard_seconds = 0.3
        self.await_round_kill_reset = {}  # 回合切换后，等待 round_kills 归零再恢复播放
        # v2.2.1 闩锁兜底（修复"中途加入/归零包丢失导致整回合静音"）：
        # - await_reset_since: 闩锁置位时间，超时(15s)自动释放
        # - await_reset_baseline: 闩锁期间首个正数包的 (kills, killhs) 基线；
        #   之后计数高于基线=真实新击杀(如中途加入后的击杀)，低于基线=归零包被丢但计数已重启，均立即释放
        self.await_reset_timeout_seconds = 15.0
        self.await_reset_since = {}
        self.await_reset_baseline = {}
        # v2.2.1: 会话内是否见过 match_stats 组件。玩家的 GSI cfg 若缺
        # player_match_stats，回合结束补枪的双计数校验会永远失败——
        # 此时降级为仅凭 round_kills 增量放行（见 _is_round_end_kill_delta）。
        self.match_stats_ever_seen = False
        
        # 武器跟踪
        self.last_kill_weapon = ""  # 上一次击杀使用的武器
        self.current_weapon = ""    # 当前持有的武器
        self.last_non_knife_weapon = ""  # 上一个非knife武器
        self.last_confirmed_fire_weapon = ""  # 最近一次确认开火的武器
        self.previous_weapon_snapshot = {}  # 上一帧 weapons 快照
        self.frame_inferred_fire_weapon = ""  # 本帧基于弹药变化推断出的开火武器
        
        # 回合跟踪
        self.just_started_new_round = False  # 标记是否刚开始新回合

        # 本帧武器推断（GSI 缺 weapons 快照时短时回用最近开火武器）
        self.frame_active_weapon = ""  # 当前帧明确到的 active 武器
        self.frame_has_weapon_snapshot = False  # 当前帧是否有 weapons 快照
        self.last_confirmed_fire_weapon_time = 0.0  # 最近一次确认开火武器的时间
        self.kill_weapon_inference_ttl = 0.6  # weapons 缺失时才短时间回用最近开火武器

        # 记录每个玩家已播放的击杀等级，与武器无关
        self.played_kill_levels = {}  # {steamid: set(1, 2, 3...)}
        
        # 爆头跟踪
        self.previous_round_killhs = {}  # 跟踪每个玩家当前回合的爆头击杀数
        
        # 新增: 击杀回调机制
        self.kill_callbacks = []

        # 文件存在性缓存，避免每次击杀都扫描文件系统
        self._file_exists_cache = {}  # {path: bool}
        self._cache_timestamp = time.time()  # 缓存时间戳
        self._cache_ttl = 60  # 缓存有效期60秒

    def set_image_player(self, image_player_instance):
        """设置图片播放器实例"""
        self.image_player = image_player_instance

    def _file_exists(self, path):
        """带缓存的文件存在性检查（带TTL）"""
        current_time = time.time()

        # 缓存过期，清空重建
        if current_time - self._cache_timestamp > self._cache_ttl:
            self._file_exists_cache.clear()
            self._cache_timestamp = current_time
            self.logger.debug("文件存在性缓存已过期，已清空")

        if path not in self._file_exists_cache:
            self._file_exists_cache[path] = os.path.exists(path)
        return self._file_exists_cache[path]
        
    def register_kill_callback(self, callback):
        """注册击杀回调函数"""
        if callable(callback) and callback not in self.kill_callbacks:
            self.kill_callbacks.append(callback)
            self.logger.info(f"成功注册击杀回调: {callback}")
            return True
        return False

    MAX_TRACKED_STEAMIDS = 64  # per-steamid 跟踪字典上限,防观战/长会话无界增长

    def _evict_tracking_if_needed(self, keep_steamid=None):
        """超过上限时只保留当前玩家条目,清掉历史观战玩家,防内存无界增长。
        单人对局只有 1 个 steamid,永不触发;64 人服/连看 demo 才会清理。"""
        dicts = [
            self.previous_round_kills, self.previous_total_kills, self.previous_match_kills,
            self.played_sounds_this_round, self.new_round_start_time, self.await_round_kill_reset,
            self.played_kill_levels, self.previous_round_killhs,
            self.await_reset_since, self.await_reset_baseline,
        ]
        if max((len(d) for d in dicts), default=0) <= self.MAX_TRACKED_STEAMIDS:
            return
        for d in dicts:
            if keep_steamid is not None and keep_steamid in d:
                kept = d[keep_steamid]
                d.clear()
                d[keep_steamid] = kept
            else:
                d.clear()
        self.logger.info("击杀跟踪字典超过上限,已清理历史(观战)玩家条目")

    def process_data(self, data):
        """处理GSI数据"""
        # 获取当前steamid
        player_data = data.get("player", {})
        current_steamid = player_data.get("steamid", "")
        self._evict_tracking_if_needed(current_steamid)
        current_weapon_snapshot = self._extract_weapon_snapshot(player_data)
        self.frame_has_weapon_snapshot = bool(current_weapon_snapshot)
        self.frame_active_weapon = self._get_current_weapon(data)
        self.frame_inferred_fire_weapon = self._infer_fired_weapon(current_weapon_snapshot)
        self.previous_weapon_snapshot = current_weapon_snapshot

        if self.frame_inferred_fire_weapon:
            self.last_confirmed_fire_weapon = self.frame_inferred_fire_weapon
            self.last_confirmed_fire_weapon_time = time.time()
            if not self.frame_inferred_fire_weapon.startswith("weapon_knife") and self.frame_inferred_fire_weapon != "weapon_taser":
                self.last_non_knife_weapon = self.frame_inferred_fire_weapon

        # 首次记录玩家ID
        if not config.player_steamid and current_steamid:
            config.player_steamid = current_steamid
            config.save_config()
            self.logger.info(f"记录玩家SteamID: {current_steamid}")

        # 观战模式静音检查 - 新增
        if config.spectator_mode_mute and current_steamid and current_steamid != config.player_steamid:
            self.logger.debug(f"观战模式静音: 当前玩家 {current_steamid} != 本人 {config.player_steamid}")
            return  # 不是玩家本人，且开启了观战静音，直接返回

        # 检查玩家是否活动
        is_active = self._is_player_active(data)

        steamid = player_data.get("steamid", "")
        self._sync_match_kills(player_data, steamid, initialize_only=True)

        # activity 会偶发抖动，但非 live 阶段不应触发击杀播放
        if not is_active:
            round_phase = self._get_round_phase(data)
            if round_phase != "live":
                if self._is_round_end_kill_delta(round_phase, player_data, steamid):
                    self.logger.debug(
                        "玩家activity非playing但检测到回合结束最终击杀增量，放行一次击杀检测"
                    )
                else:
                    self.logger.debug(
                        f"玩家activity非playing且round.phase={round_phase or 'unknown'}，仅同步击杀计数"
                    )
                    self._sync_kill_count(data, player_data)
                    return
            self.logger.debug("玩家activity非playing但round.phase=live，继续击杀检测（避免吞音效）")

        # 检查新回合 (这部分很重要，在回合切换时保存数据)
        if "map" in data and "round" in data["map"]:
            current_round = data["map"]["round"]
            if current_round != self.previous_round:
                if self.image_player:
                    self.image_player.stop_images()
                # 保存上一回合的击杀数
                if steamid in self.previous_round_kills:
                    self.previous_total_kills[steamid] = self.previous_round_kills[steamid]
                # 重置当前回合数据
                self.previous_round_kills[steamid] = 0
                self.previous_round_killhs[steamid] = 0  # 重置爆头击杀数
                self.previous_round = current_round
                self.last_kill_sound_time = 0
                self.played_sounds_this_round[steamid] = set()
                # 新增: 重置已播放击杀等级
                self.played_kill_levels[steamid] = set()
                self.new_round_start_time[steamid] = time.time()
                if config.mode != "3. 死斗模式":
                    # round.phase 可用时优先用 phase 门控；仅在 phase 缺失或异常为 live 时启用闩锁兜底。
                    round_phase = self._get_round_phase(data)
                    latched = (not round_phase) or (round_phase == "live")
                    self.await_round_kill_reset[steamid] = latched
                    # 闩锁兜底状态：记录置位时间、清空基线（基线在首个正数包时采集）
                    if latched:
                        self.await_reset_since[steamid] = time.time()
                    self.await_reset_baseline.pop(steamid, None)
                self.just_started_new_round = True
                self.logger.debug(f"New round detected: {current_round}. Previous kills saved. Headshots reset.")

        # 更新当前武器
        current_weapon = self.frame_active_weapon
        if current_weapon:
            # 只有当武器变化时才更新
            if current_weapon != self.current_weapon:
                self.logger.debug(f"Weapon changed from {self.current_weapon} to {current_weapon}")
                self.current_weapon = current_weapon
                
                # 记录非knife武器
                if not current_weapon.startswith("weapon_knife") and current_weapon != "weapon_taser":
                    self.last_non_knife_weapon = current_weapon
                    self.logger.debug(f"记录非knife武器: {self.last_non_knife_weapon}")

        # 处理击杀音效
        if config.kill_sound_enabled:
            self._process_kill_sounds(data, steamid)
            
        # 清除新回合标记
        if self.just_started_new_round:
            self.just_started_new_round = False
        self._sync_match_kills(player_data, steamid, initialize_only=False)

    def _is_player_active(self, data):
        """检查玩家是否处于活动状态"""
        return (
            "player" in data and
            "activity" in data["player"] and
            data["player"]["activity"] == "playing"
        )

    def _sync_kill_count(self, data, player_data):
        """在玩家非活动状态时同步击杀计数，防止恢复后误判为新击杀"""
        steamid = player_data.get("steamid", "")
        if not steamid:
            return
        if "state" in player_data and "round_kills" in player_data["state"]:
            current_round_kills = player_data["state"]["round_kills"]
            current_killhs = player_data["state"].get("round_killhs", 0)
            prev = self.previous_round_kills.get(steamid, 0)
            prev_hs = self.previous_round_killhs.get(steamid, 0)
            if current_round_kills != prev or current_killhs != prev_hs:
                self.logger.debug(
                    f"非活动状态同步击杀数: activity={data.get('player', {}).get('activity', '?')}, "
                    f"round_kills {prev} -> {current_round_kills}, "
                    f"round_killhs {prev_hs} -> {current_killhs}"
                )
                self.previous_round_kills[steamid] = current_round_kills
                self.previous_round_killhs[steamid] = current_killhs
        self._sync_match_kills(player_data, steamid, initialize_only=False)

    def _get_player_match_kills(self, player_data):
        match_stats = player_data.get("match_stats", {}) if isinstance(player_data, dict) else {}
        if isinstance(match_stats, dict) and "kills" in match_stats:
            try:
                return int(match_stats.get("kills", 0) or 0)
            except (TypeError, ValueError):
                return None
        return None

    def _sync_match_kills(self, player_data, steamid, initialize_only=False):
        if not steamid:
            return
        match_kills = self._get_player_match_kills(player_data)
        if match_kills is None:
            return
        self.match_stats_ever_seen = True
        if initialize_only and steamid in self.previous_match_kills:
            return
        self.previous_match_kills[steamid] = match_kills

    def _is_round_end_kill_delta(self, round_phase, player_data, steamid):
        """仅在回合结束阶段且击杀计数真实增长时放行一次最终击杀。"""
        phase = str(round_phase or "").strip().lower()
        if phase not in {"over", "gameover"}:
            return False
        state = player_data.get("state", {}) if isinstance(player_data, dict) else {}
        current_round_kills = int(state.get("round_kills", 0) or 0)
        prev_round_kills = int(self.previous_round_kills.get(steamid, 0) or 0)
        if current_round_kills <= prev_round_kills:
            return False

        current_match_kills = self._get_player_match_kills(player_data)
        prev_match_kills = self.previous_match_kills.get(steamid)
        if current_match_kills is None or prev_match_kills is None:
            # v2.2.1 降级：整个会话从未见过 match_stats（GSI cfg 缺 player_match_stats 组件）
            # 时，双计数校验永远失败会吞掉所有回合结束补枪。此时 round_kills 真实增量
            # 已是足够强的信号，直接放行。
            # 注意：上游 steamid 拦截仅在 spectator_mode_mute 开启时生效；静音关闭时
            # 切换观战目标会带来从未见过的 steamid + 残留 round_kills，降级信号只对本人可靠。
            if not self.match_stats_ever_seen and (not config.player_steamid or steamid == config.player_steamid):
                self.logger.info(
                    f"回合结束击杀放行(降级模式,无match_stats组件): round_kills增量 {prev_round_kills}->{current_round_kills}"
                )
                return True
            self.logger.debug(
                f"回合结束击杀放行校验缺少match_stats.kills基线: current={current_match_kills}, prev={prev_match_kills}"
            )
            return False
        return int(current_match_kills) > int(prev_match_kills)

    def _compute_is_headshot(self, prev_kills, current_round_kills, prev_round_killhs, current_round_killhs):
        """根据 round_kills/round_killhs 增量保守判断本次触发是否爆头。"""
        kill_delta = max(0, int(current_round_kills) - int(prev_kills))
        hs_delta = max(0, int(current_round_killhs) - int(prev_round_killhs))
        if kill_delta <= 0 or hs_delta <= 0:
            return False
        if kill_delta == 1:
            return True
        # 多击杀合包时无法精确定位最后一杀，采用保守策略减少误判
        return hs_delta >= kill_delta
            
    def _get_current_weapon(self, data):
        """获取玩家当前使用的武器"""
        player_data = data.get("player", {})
        if "weapons" in player_data and player_data["weapons"] is not None:
            for weapon_key, weapon_data in player_data["weapons"].items():
                if weapon_data.get("state") == "active":
                    return weapon_data.get("name", "")
        return ""

    def _extract_weapon_snapshot(self, player_data):
        snapshot = {}
        weapons = player_data.get("weapons", {}) if isinstance(player_data, dict) else {}
        if not isinstance(weapons, dict):
            return snapshot

        for weapon_key, weapon_data in weapons.items():
            if not isinstance(weapon_data, dict):
                continue
            name = str(weapon_data.get("name", "") or "").strip()
            if not name:
                continue
            ammo_clip = weapon_data.get("ammo_clip")
            try:
                ammo_clip = int(ammo_clip) if ammo_clip is not None else None
            except (TypeError, ValueError):
                ammo_clip = None
            snapshot[weapon_key] = {
                "name": name,
                "ammo_clip": ammo_clip,
                "state": str(weapon_data.get("state", "") or "").strip().lower(),
            }
        return snapshot

    def _infer_fired_weapon(self, current_snapshot):
        candidates = []
        for weapon_key, current in current_snapshot.items():
            previous = self.previous_weapon_snapshot.get(weapon_key)
            if not previous:
                continue
            if current.get("name") != previous.get("name"):
                continue

            prev_ammo = previous.get("ammo_clip")
            current_ammo = current.get("ammo_clip")
            if prev_ammo is None or current_ammo is None:
                continue
            if current_ammo >= prev_ammo:
                continue

            candidates.append((
                1 if current.get("state") == "active" else 0,
                int(prev_ammo) - int(current_ammo),
                current.get("name", ""),
            ))

        if not candidates:
            return ""

        candidates.sort(reverse=True)
        return candidates[0][2]

    def _resolve_kill_weapon(self, current_time=None):
        current_time = current_time if current_time is not None else time.time()
        weapon = ""
        weapon_source = "unresolved"

        if self.frame_inferred_fire_weapon:
            weapon = self.frame_inferred_fire_weapon
            weapon_source = "frame_inferred_fire_weapon"
        elif self.frame_active_weapon:
            weapon = self.frame_active_weapon
            weapon_source = "frame_active_weapon"
        elif (
            not self.frame_has_weapon_snapshot
            and self.last_confirmed_fire_weapon
            and current_time - self.last_confirmed_fire_weapon_time <= self.kill_weapon_inference_ttl
        ):
            weapon = self.last_confirmed_fire_weapon
            weapon_source = "recent_last_confirmed_fire_weapon"

        if weapon.startswith("weapon_knife") or weapon == "weapon_taser":
            if self.last_non_knife_weapon:
                self.logger.debug(f"使用 knife 击杀，应用上一个非 knife 武器设置: {self.last_non_knife_weapon}")
                weapon = self.last_non_knife_weapon
                weapon_source = f"{weapon_source}->last_non_knife_weapon"

        self.logger.debug(
            f"击杀武器解析: resolved={weapon or 'none'}, source={weapon_source}, "
            f"frame_inferred={self.frame_inferred_fire_weapon or 'none'}, "
            f"frame_active={self.frame_active_weapon or 'none'}, "
            f"last_confirmed={self.last_confirmed_fire_weapon or 'none'}, "
            f"last_kill={self.last_kill_weapon or 'none'}"
        )
        return weapon

    def _resolve_style_value(self, style):
        """兼容旧配置字典：enabled=false 视为关闭。"""
        if isinstance(style, dict):
            if style.get("enabled") is False:
                return "0"
            return str(style.get("style", "0")).strip()
        if style is None:
            return "0"
        return str(style).strip()

    def _style_disabled(self, style):
        """统一识别显式关闭的样式值。"""
        return self._resolve_style_value(style).lower() in {
            "",
            "0",
            "none",
            "off",
            "disabled",
            "不启用",
            "未启用",
        }

    def _get_weapon_kill_sound_key(self, weapon_name, kills, is_headshot=False):
        """根据武器名称和击杀数获取对应的音效键，支持爆头和智能回退
        
        优化逻辑:
        1. 如果只有1.mp3和1-headshot.mp3，则所有击杀都使用这两个文件
        2. 如果有多个普通击杀音效，爆头音效只用于有配对的那个击杀数
        """
        if not config.kill_sound_enabled or kills <= 0 or kills > 5:
            return None
                 
        # 获取配置中的武器风格设置
        if not weapon_name:
            self.logger.debug("未解析到击杀武器，跳过击杀音效播放")
            return None

        if not weapon_name:
            self.logger.debug("未解析到击杀武器，跳过击杀语音播放")
            return None

        weapon_style = "0"
        has_explicit_style = weapon_name in config.weapon_kill_sounds
        weapon_sound_styles = getattr(audio_manager, "weapon_kill_sound_styles", {}) or {}
        kill_sound_styles = getattr(audio_manager, "kill_sound_styles", []) or []
        weapon_sounds_dir = getattr(audio_manager, "weapon_sounds_dir", "")
        kill_sounds_dir = getattr(audio_manager, "kill_sounds_dir", "")
        if has_explicit_style:
            weapon_style = self._resolve_style_value(config.weapon_kill_sounds.get(weapon_name, "0"))
            if self._style_disabled(weapon_style):
                self.logger.debug(f"武器 {weapon_name} 击杀音效已显式禁用，跳过播放")
                return None
        
        # 确定使用的音效集合和路径
        is_weapon_specific = False
        sound_style_dir = None
        
        # 检查是否使用武器特定音效
        if weapon_style != "0" and weapon_name in weapon_sound_styles and weapon_style in weapon_sound_styles[weapon_name]:
            is_weapon_specific = True
            sound_style_dir = os.path.join(weapon_sounds_dir, weapon_name, weapon_style)
        # 否则检查是否使用通用音效
        elif weapon_style != "0" and weapon_style in kill_sound_styles:
            sound_style_dir = os.path.join(kill_sounds_dir, weapon_style)
        # 使用默认音效
        else:
            sound_style_dir = kill_sounds_dir
        
        # 检查音效文件情况
        has_only_first_sounds = False
        available_normal_sounds = []
        available_headshot_sounds = []
        
        if sound_style_dir and self._file_exists(sound_style_dir):
            # 检查哪些普通击杀音效存在
            for i in range(1, 6):
                sound_file = find_audio_by_stem(sound_style_dir, str(i), DEFAULT_AUDIO_EXTENSIONS)
                if sound_file and self._file_exists(sound_file):
                    available_normal_sounds.append(i)

            # 检查哪些爆头音效存在
            for i in range(1, 6):
                headshot_file = find_audio_by_stem(sound_style_dir, f"{i}-headshot", DEFAULT_AUDIO_EXTENSIONS)
                if headshot_file and self._file_exists(headshot_file):
                    available_headshot_sounds.append(i)
            
            # 特殊情况: 只有1.mp3和1-headshot.mp3
            if len(available_normal_sounds) == 1 and available_normal_sounds[0] == 1 and len(available_headshot_sounds) == 1 and available_headshot_sounds[0] == 1:
                has_only_first_sounds = True
        
        # 构建音效键
        prefix = "kill"
        if is_weapon_specific:
            # 武器特定音效
            prefix = f"kill-{weapon_name}-{weapon_style}"
        elif weapon_style != "0":
            # 通用风格音效
            prefix = f"kill-{weapon_style}"
        
        # 确定使用哪个击杀数的音效
        actual_kill_num = min(kills, 5)
        
        # 如果可用的普通音效不为空
        if available_normal_sounds:
            # 特殊情况: 只有1.mp3和1-headshot.mp3，所有击杀都用这两个
            if has_only_first_sounds:
                if is_headshot and 1 in available_headshot_sounds:
                    # 爆头，使用1-headshot.mp3
                    headshot_key = f"{prefix}-1-headshot"
                    self.logger.debug(f"使用唯一爆头音效: {headshot_key}")
                    return headshot_key
                else:
                    # 非爆头或没有爆头音效，使用1.mp3
                    return f"{prefix}-1"
            else:
                # 常规情况: 尝试找最接近的可用普通音效
                closest_normal = self._find_closest_available(actual_kill_num, available_normal_sounds)
                
                # 爆头情况: 只有当对应击杀数有爆头音效时才使用
                if is_headshot and actual_kill_num in available_headshot_sounds:
                    headshot_key = f"{prefix}-{actual_kill_num}-headshot"
                    self.logger.debug(f"使用匹配的爆头音效: {headshot_key}")
                    return headshot_key
                
                # 普通击杀或没有对应的爆头音效
                return f"{prefix}-{closest_normal}"
        
        # 回退到通用音效时，主动按目标连杀数探测，避免尚未预加载时错误退回第一杀
        return self._resolve_generic_kill_sound_fallback(actual_kill_num, is_headshot)

    def _get_weapon_kill_voice_key(self, weapon_name, kills, is_headshot=False):
        """根据武器名称和击杀数获取对应的语音键，支持爆头和智能回退
        
        优化逻辑:
        1. 如果只有1.mp3和1-headshot.mp3，则所有击杀都使用这两个文件
        2. 如果有多个普通击杀语音，爆头语音只用于有配对的那个击杀数
        """
        if not config.kill_voice_enabled or kills <= 0 or kills > 5:
            return None
                 
        # 获取配置中的武器风格设置
        weapon_style = "0"
        has_explicit_style = weapon_name in config.weapon_kill_voices
        weapon_voice_styles = getattr(audio_manager, "weapon_kill_voice_styles", {}) or {}
        kill_voice_styles = getattr(audio_manager, "kill_voice_styles", []) or []
        weapon_voices_dir = getattr(audio_manager, "weapon_voices_dir", "")
        kill_voices_dir = getattr(audio_manager, "kill_voices_dir", "")
        if has_explicit_style:
            weapon_style = self._resolve_style_value(config.weapon_kill_voices.get(weapon_name, "0"))
            if self._style_disabled(weapon_style):
                self.logger.debug(f"武器 {weapon_name} 击杀语音已显式禁用，跳过播放")
                return None
        
        # 确定使用的语音集合和路径
        is_weapon_specific = False
        voice_style_dir = None
        
        # 检查是否使用武器特定语音
        if weapon_style != "0" and weapon_name in weapon_voice_styles and weapon_style in weapon_voice_styles[weapon_name]:
            is_weapon_specific = True
            voice_style_dir = os.path.join(weapon_voices_dir, weapon_name, weapon_style)
        # 否则检查是否使用通用语音
        elif weapon_style != "0" and weapon_style in kill_voice_styles:
            voice_style_dir = os.path.join(kill_voices_dir, weapon_style)
        # 使用默认语音
        else:
            voice_style_dir = kill_voices_dir
        
        # 检查语音文件情况
        has_only_first_voices = False
        available_normal_voices = []
        available_headshot_voices = []
        
        if voice_style_dir and self._file_exists(voice_style_dir):
            # 检查哪些普通击杀语音存在
            for i in range(1, 6):
                voice_file = find_audio_by_stem(voice_style_dir, str(i), DEFAULT_AUDIO_EXTENSIONS)
                if voice_file and self._file_exists(voice_file):
                    available_normal_voices.append(i)

            # 检查哪些爆头语音存在
            for i in range(1, 6):
                headshot_file = find_audio_by_stem(voice_style_dir, f"{i}-headshot", DEFAULT_AUDIO_EXTENSIONS)
                if headshot_file and self._file_exists(headshot_file):
                    available_headshot_voices.append(i)
            
            # 特殊情况: 只有1.mp3和1-headshot.mp3
            if len(available_normal_voices) == 1 and available_normal_voices[0] == 1 and len(available_headshot_voices) == 1 and available_headshot_voices[0] == 1:
                has_only_first_voices = True
        
        # 构建语音键
        prefix = "voice"
        if is_weapon_specific:
            # 武器特定语音
            prefix = f"voice-{weapon_name}-{weapon_style}"
        elif weapon_style != "0":
            # 通用风格语音
            prefix = f"voice-{weapon_style}"
        
        # 确定使用哪个击杀数的语音
        actual_kill_num = min(kills, 5)
        
        # 如果可用的普通语音不为空
        if available_normal_voices:
            # 特殊情况: 只有1.mp3和1-headshot.mp3，所有击杀都用这两个
            if has_only_first_voices:
                if is_headshot and 1 in available_headshot_voices:
                    # 爆头，使用1-headshot.mp3
                    headshot_key = f"{prefix}-1-headshot"
                    self.logger.debug(f"使用唯一爆头语音: {headshot_key}")
                    return headshot_key
                else:
                    # 非爆头或没有爆头语音，使用1.mp3
                    return f"{prefix}-1"
            else:
                # 常规情况: 尝试找最接近的可用普通语音
                closest_normal = self._find_closest_available(actual_kill_num, available_normal_voices)
                
                # 爆头情况: 只有当对应击杀数有爆头语音时才使用
                if is_headshot and actual_kill_num in available_headshot_voices:
                    headshot_key = f"{prefix}-{actual_kill_num}-headshot"
                    self.logger.debug(f"使用匹配的爆头语音: {headshot_key}")
                    return headshot_key
                
                # 普通击杀或没有对应的爆头语音
                return f"{prefix}-{closest_normal}"
        
        # 回退到通用语音时，主动按目标连杀数探测，避免尚未预加载时错误退回第一句
        return self._resolve_generic_kill_voice_fallback(actual_kill_num, is_headshot)

    def _find_closest_available(self, target, available_numbers):
        """在可用数字列表中找到最接近目标数字的值"""
        if not available_numbers:
            return 1  # 默认回退到1
        
        if target in available_numbers:
            return target  # 优先使用完全匹配的
        
        # 寻找小于或等于目标的最大数
        lower = [n for n in available_numbers if n <= target]
        if lower:
            return max(lower)
        
        # 如果没有小于或等于目标的数，返回最小的可用数
        return min(available_numbers)

    def _resolve_generic_kill_sound_fallback(self, kills, is_headshot=False):
        """兜底解析通用击杀音效键，避免未预加载时误判成第一杀。"""
        actual_kill_num = max(1, min(int(kills), 5))
        candidates = []
        if is_headshot:
            candidates.append(f"kill-{actual_kill_num}-headshot")
        candidates.append(f"kill-{actual_kill_num}")
        if actual_kill_num != 1:
            if is_headshot:
                candidates.append("kill-1-headshot")
            candidates.append("kill-1")

        for key in candidates:
            if audio_manager._load_sound_by_key(key):
                return key

        return "kill-1"

    def _resolve_generic_kill_voice_fallback(self, kills, is_headshot=False):
        """兜底解析通用击杀语音键，避免未预加载时误判成第一句。"""
        actual_kill_num = max(1, min(int(kills), 5))
        candidates = []
        if is_headshot:
            candidates.append(f"voice-{actual_kill_num}-headshot")
        candidates.append(f"voice-{actual_kill_num}")
        if actual_kill_num != 1:
            if is_headshot:
                candidates.append("voice-1-headshot")
            candidates.append("voice-1")

        for key in candidates:
            if audio_manager._load_voice_by_key(key):
                return key

        return "voice-1"

    def _get_round_phase(self, data):
        round_data = data.get("round", {})
        if isinstance(round_data, dict):
            phase = str(round_data.get("phase", "")).strip().lower()
            if phase:
                return phase
        map_data = data.get("map", {})
        if isinstance(map_data, dict):
            phase = str(map_data.get("phase", "")).strip().lower()
            if phase:
                return phase
        return ""

    def _play_kill_sound_with_retry(self, preferred_key, kill_level, is_headshot):
        """播放击杀音效并带保守回退，避免偶发加载失败后整轮吞音效。"""
        keys_to_try = []
        if preferred_key:
            keys_to_try.append(str(preferred_key))

        kill_level = max(1, min(int(kill_level), 5))
        suffix = "-headshot" if is_headshot else ""
        keys_to_try.append(f"kill-{kill_level}{suffix}")
        if is_headshot:
            keys_to_try.append(f"kill-{kill_level}")
        if kill_level != 1:
            keys_to_try.append(f"kill-1{suffix}")
            keys_to_try.append("kill-1")

        tried = []
        seen = set()
        for key in keys_to_try:
            if key in seen:
                continue
            seen.add(key)
            tried.append(key)
            if audio_manager.play_sound(
                key,
                channel_type="kill_sound",
                event_type="headshot" if is_headshot else "kill",
                priority=110 if is_headshot else 100,
                allow_preempt=True,
            ):
                if key != preferred_key:
                    self.logger.warning(f"[击杀回退] 使用回退音效: {key} (原始: {preferred_key})")
                return True, key

        self.logger.warning(f"[击杀失败] 所有候选音效均播放失败: {tried}")
        return False, preferred_key or ""

    def _ensure_kill_state(self, steamid, current_time):
        """P4.3: 确保某 steamid 的回合击杀跟踪状态已初始化（抽取自 _process_kill_sounds）。"""
        self.new_round_start_time.setdefault(steamid, current_time)
        self.previous_round_kills.setdefault(steamid, 0)
        self.previous_round_killhs.setdefault(steamid, 0)
        self.played_sounds_this_round.setdefault(steamid, set())
        self.played_kill_levels.setdefault(steamid, set())

    def _emit_kill_feedback(self, level, is_headshot, current_time):
        """P4.3: 播放一次击杀反馈（音效→语音→图标），返回 (played, used_key)。

        从死斗/非死斗两个高度重复的分支抽取的公共逻辑——去重判断仍由调用方负责，
        本方法只负责"取键、播放、成功后联动语音与图标"，行为与原内联代码等价。
        """
        sound_key = self._get_weapon_kill_sound_key(self.last_kill_weapon, level, is_headshot)
        if not sound_key:
            return False, ""
        played, used_key = self._play_kill_sound_with_retry(sound_key, level, is_headshot)
        if played:
            self.last_kill_sound_time = current_time
            if config.kill_voice_enabled:
                voice_key = self._get_weapon_kill_voice_key(self.last_kill_weapon, level, is_headshot)
                if voice_key:
                    self.logger.debug(f"播放击杀语音: {voice_key}")
                    audio_manager.play_voice(voice_key)
            if self.image_player and config.kill_icon_enabled:
                self.image_player.play_images(1, level)
        return played, used_key

    def _process_kill_sounds(self, data, steamid):
        """处理击杀音效"""
        current_time = time.time()
        if "map" in data and "round" in data["map"]:
            # （回合号本身不参与本方法逻辑，guard 仅确保 GSI 包含对局数据）
            # 初始化数据结构
            self._ensure_kill_state(steamid, current_time)

            player_data = data.get("player", {})
            if "state" in player_data and "round_kills" in player_data["state"]:
                current_round_kills = player_data["state"]["round_kills"]

                # 获取当前回合爆头击杀数
                current_round_killhs = player_data["state"].get("round_killhs", 0)

                # 回合切换后先等待 round_kills 真正回到 0，避免旧回合计数重播。
                # v2.2.1 三重兜底：仅靠"见 0 释放"会在中途加入/归零包丢失时把整回合击杀吞掉——
                # 增加 基线增量释放 / 基线回落释放 / 15s 超时释放。
                if self.await_round_kill_reset.get(steamid, False):
                    if current_round_kills <= 0:
                        self.await_round_kill_reset[steamid] = False
                        self.await_reset_baseline.pop(steamid, None)
                        self.previous_round_kills[steamid] = 0
                        self.previous_round_killhs[steamid] = current_round_killhs
                        self.played_kill_levels[steamid] = set()
                        self.played_sounds_this_round[steamid] = set()
                        self.logger.debug("检测到 round_kills 已归零，解除回合切换闩锁")
                    else:
                        baseline = self.await_reset_baseline.get(steamid)
                        latch_since = self.await_reset_since.get(steamid, current_time)
                        if baseline is None:
                            # 闩锁后首个正数包：可能是旧回合残留计数，只采集基线不播放
                            self.await_reset_baseline[steamid] = (current_round_kills, current_round_killhs)
                            self.previous_round_kills[steamid] = current_round_kills
                            self.previous_round_killhs[steamid] = current_round_killhs
                            self.logger.debug(
                                f"回合切换闩锁生效(采集基线): round_kills={current_round_kills}, round_killhs={current_round_killhs}"
                            )
                            return
                        base_kills, base_killhs = baseline
                        if current_round_kills > base_kills:
                            # 基线之上出现新增量 → 真实新击杀（典型：中途加入后打出击杀）。
                            # 释放闩锁，把 previous 恢复为基线，放行本包走正常增量播放。
                            self.await_round_kill_reset[steamid] = False
                            self.await_reset_baseline.pop(steamid, None)
                            self.previous_round_kills[steamid] = base_kills
                            self.previous_round_killhs[steamid] = base_killhs
                            self.logger.info(
                                f"闩锁兜底释放(基线增量): {base_kills}->{current_round_kills}，放行本次击杀"
                            )
                        elif current_round_kills < base_kills:
                            # 计数低于基线 → 归零包被丢但计数器已重启（新回合已在计数）。
                            # 释放闩锁并按新生命起点处理，放行本包。
                            self.await_round_kill_reset[steamid] = False
                            self.await_reset_baseline.pop(steamid, None)
                            self.previous_round_kills[steamid] = 0
                            self.previous_round_killhs[steamid] = 0
                            self.played_kill_levels[steamid] = set()
                            self.played_sounds_this_round[steamid] = set()
                            self.logger.info(
                                f"闩锁兜底释放(基线回落): {base_kills}->{current_round_kills}，按新回合计数放行"
                            )
                        elif current_time - latch_since >= self.await_reset_timeout_seconds:
                            # 计数持平但闩锁已卡超时 → 释放（previous 已同步为当前值，不会补播旧计数）
                            self.await_round_kill_reset[steamid] = False
                            self.await_reset_baseline.pop(steamid, None)
                            self.previous_round_kills[steamid] = current_round_kills
                            self.previous_round_killhs[steamid] = current_round_killhs
                            self.logger.info(
                                f"闩锁兜底释放(超时{self.await_reset_timeout_seconds:.0f}s): round_kills={current_round_kills}"
                            )
                            return
                        else:
                            self.previous_round_kills[steamid] = current_round_kills
                            self.previous_round_killhs[steamid] = current_round_killhs
                            self.logger.debug(
                                f"回合切换闩锁生效: round_kills={current_round_kills}, round_killhs={current_round_killhs}"
                            )
                            return

                round_phase = self._get_round_phase(data)
                if config.mode != "3. 死斗模式":
                    # 非 live 阶段只同步计数，不触发击杀播放
                    if round_phase and round_phase != "live":
                        if not self._is_round_end_kill_delta(round_phase, player_data, steamid):
                            self.previous_round_kills[steamid] = current_round_kills
                            self.previous_round_killhs[steamid] = current_round_killhs
                            return
                        self.logger.debug(
                            f"检测到回合结束最终击杀增量: phase={round_phase}, {self.previous_round_kills.get(steamid, 0)}->{current_round_kills}"
                        )

                    # phase 丢失时，仅在新回合极短窗口内防抖一次，避免把残留击杀当新击杀。
                    # v2.2.1: 本帧有弹药差分开火推断且为单杀增量时视为真实击杀放行。
                    # 开火推断只证明"此刻在开枪"，与包里计数是否为旧回合残留无因果——
                    # 残留计数通常一次跳多杀，故多杀增量即使伴随开火也先吸收防误播。
                    if (
                        not round_phase
                        and current_round_kills > 0
                        and self.previous_round_kills.get(steamid, 0) == 0
                        and not (self.frame_inferred_fire_weapon and current_round_kills == 1)
                        and current_time - self.new_round_start_time.get(steamid, current_time) < self.round_transition_guard_seconds
                    ):
                        self.logger.debug(
                            f"回合过渡防抖: round_kills={current_round_kills}, elapsed={current_time - self.new_round_start_time.get(steamid, current_time):.3f}s"
                        )
                        self.previous_round_kills[steamid] = current_round_kills
                        self.previous_round_killhs[steamid] = current_round_killhs
                        return

                # 诊断日志：记录击杀数变化，帮助排查吞音效问题
                prev_kills = self.previous_round_kills.get(steamid, 0)
                if current_round_kills < prev_kills:
                    self.logger.debug(
                        f"检测到 round_kills 回落: {prev_kills}->{current_round_kills}，重置回合内击杀跟踪"
                    )
                    self.played_kill_levels[steamid] = set()
                    self.played_sounds_this_round[steamid] = set()

                    if config.mode == "3. 死斗模式" and current_round_kills > 0:
                        self.logger.debug(
                            "死斗模式检测到正数回落，视为重生后的新生命周期，按 fresh 计数继续处理"
                        )
                        prev_kills = 0
                        self.previous_round_kills[steamid] = 0
                        self.previous_round_killhs[steamid] = 0
                    else:
                        self.previous_round_kills[steamid] = current_round_kills
                        self.previous_round_killhs[steamid] = current_round_killhs
                        return

                if current_round_kills != prev_kills:
                    self.logger.info(
                        f"[击杀诊断] round_kills: {prev_kills}->{current_round_kills}, "
                        f"health={player_data['state'].get('health', '?')}, "
                        f"played_levels={self.played_kill_levels.get(steamid, set())}, "
                        f"weapon={self.current_weapon}, mode={config.mode}"
                    )
                
                # 玩家死亡检测
                if player_data["state"].get("health", 100) == 0:
                    if current_round_kills <= prev_kills:
                        self.logger.debug(
                            "检测到死亡包且没有新的击杀增量，保留当前去重状态，等待后续 respawn/reset 包处理"
                        )
                        return

                # 检测新击杀 - 只有当击杀数增加时才更新击杀武器
                if current_round_kills > self.previous_round_kills.get(steamid, 0):
                    prev_kills = self.previous_round_kills.get(steamid, 0)
                    prev_killhs = self.previous_round_killhs.get(steamid, 0)
                    self.last_kill_weapon = self._resolve_kill_weapon(current_time)
                    
                    # 判断是否是爆头击杀（合包场景采用保守策略）
                    is_headshot = self._compute_is_headshot(
                        prev_kills, current_round_kills, prev_killhs, current_round_killhs
                    )
                    if current_round_kills - prev_kills > 1:
                        self.logger.debug(
                            f"检测到击杀合包: kills {prev_kills}->{current_round_kills}, "
                            f"killhs {prev_killhs}->{current_round_killhs}, is_headshot={is_headshot}"
                        )
                    
                    # 更新爆头击杀数记录
                    self.previous_round_killhs[steamid] = current_round_killhs
                    
                    self.logger.debug(f"击杀检测! 使用武器: {self.last_kill_weapon}, 爆头: {is_headshot}, 回合爆头数: {current_round_killhs}")

                    # 立即同步击杀计数，防止后续逻辑跳过时状态不一致
                    self.previous_round_kills[steamid] = current_round_kills

                    # 新增: 触发击杀回调
                    for callback in self.kill_callbacks:
                        try:
                            callback(is_headshot)
                        except Exception as e:
                            # B4: 外部回调异常附加堆栈，便于定位注册方
                            self.logger.exception(f"击杀回调错误: {e}")

                    # 根据模式选择, 决定击杀数逻辑（P4.3: 播放反馈已抽到 _emit_kill_feedback）
                    if config.mode == "3. 死斗模式":
                        # 死斗模式：每个不同击杀数用唯一虚拟键去重，>5 杀固定用等级 5
                        if current_round_kills > 0:
                            virtual_key = f"dm-{current_round_kills}"
                            if virtual_key not in self.played_sounds_this_round.get(steamid, set()):
                                kill_level = min(current_round_kills, 5)
                                played, used_key = self._emit_kill_feedback(
                                    kill_level, is_headshot, current_time
                                )
                                if played:
                                    self.played_sounds_this_round.setdefault(steamid, set()).add(virtual_key)
                                else:
                                    self.logger.warning(
                                        f"死斗模式击杀音效失败: steamid={steamid}, kill_level={kill_level}, key={used_key}"
                                    )
                                self.logger.debug(f"死斗模式: 播放了 {current_round_kills} 杀的音效，使用等级 {kill_level}")
                    else:
                        # 非死斗模式：按击杀级别(1-5)去重
                        if 0 < current_round_kills <= 5:
                            if current_round_kills not in self.played_kill_levels[steamid]:
                                played, used_key = self._emit_kill_feedback(
                                    current_round_kills, is_headshot, current_time
                                )
                                if played:
                                    self.played_kill_levels[steamid].add(current_round_kills)
                                else:
                                    self.logger.warning(
                                        f"竞技/自定义击杀音效失败: steamid={steamid}, kills={current_round_kills}, key={used_key}"
                                    )

                        elif current_round_kills > 5:
                            pass  # previous_round_kills 已在上方统一更新

    # v2.2.1: 删除死代码 _check_fast_kill / _resolve_kill_weapon_legacy——
    # 前者从未被 process_data 调用，且自维护一套计数会与主流程去重状态打架；
    # 后者已被 _resolve_kill_weapon 取代。
