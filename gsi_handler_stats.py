# SPDX-License-Identifier: GPL-3.0-or-later
from core.utils.logger import get_logger

logger = get_logger("GSIHandlerStats")

class GSIHandlerStats:
    """GSI统计数据处理器 - 简化版，使用最直接的逻辑"""
    
    def __init__(self, gui_instance):
        self.gui = gui_instance
        self.status_dashboard = None
        
        # 核心状态跟踪
        self.last_kill_count = 0      # 上一次的击杀数
        self.last_killhs_count = 0    # 上一次的爆头数
        self.last_health = -1         # 上一次的血量（初始为-1，确保第一次能正确检测）
        self.death_in_progress = False # 防止死亡重复统计
        self.first_update = True       # 标记是否是第一次更新
        
        # 会话统计
        self.total_kills = 0
        self.total_headshots = 0
        self.total_deaths = 0
        
        # 获取状态仪表盘实例
        if hasattr(gui_instance, 'get_status_dashboard'):
            dashboard = gui_instance.get_status_dashboard()
            # v2.2.1: 接口守卫——校验仪表盘具备全部所需方法，避免接入
            # API 不一致的实现导致统计静默失效（异常被外层 try 吞掉）
            required = ('update_kill_count', 'update_death_count', 'update_headshot_count')
            if dashboard and all(hasattr(dashboard, m) for m in required):
                self.status_dashboard = dashboard
                logger.info("成功获取状态仪表盘实例")
            elif dashboard:
                logger.warning("状态仪表盘缺少所需接口，统计仅记录日志")
            else:
                logger.info("状态仪表盘未启用，统计仅记录日志")
        else:
            logger.info("GUI实例未提供状态仪表盘接口，统计仅记录日志")
            
    def process_data(self, data):
        """处理GSI数据 - 使用最简单的逻辑"""
        # 获取玩家数据
        player_data = data.get("player", {})
        current_steamid = player_data.get("steamid", "")
        
        # 检查是否是玩家本人：会话统计只认本人，与观战静音开关解耦。
        # 死亡观战时 player 会切成被观战者（activity 仍是 playing），
        # 旧逻辑在静音关闭时会把对方的击杀/死亡累进自己的统计。
        from config import config
        self_steamid = data.get("provider", {}).get("steamid", "") or config.player_steamid
        if current_steamid and self_steamid and current_steamid != self_steamid:
            return
            
        # 检查玩家是否在游戏中
        if player_data.get("activity") != "playing":
            return
            
        # 获取玩家状态
        player_state = player_data.get("state", {})
        
        # 调试：首次运行时输出完整的state结构
        if not hasattr(self, '_state_structure_logged'):
            logger.info(f"[调试] player.state 结构: {player_state}")
            self._state_structure_logged = True
        
        current_health = player_state.get("health", -1)  # 使用-1作为默认值以便检测
        current_kills = player_state.get("round_kills", 0)
        current_killhs = player_state.get("round_killhs", 0)
        
        # 如果health字段不存在，输出警告
        if current_health == -1:
            logger.warning(f"[警告] 未找到health字段，state内容: {player_state.keys()}")
            current_health = 100  # 恢复默认值
        
        # 调试信息 - 输出健康值
        if current_health != self.last_health:
            logger.info(f"[健康值变化] {self.last_health} -> {current_health}")
        
        # ===== 死亡检测 =====
        # 简单逻辑：血量从 >0 变为 0
        if not self.first_update and current_health == 0 and self.last_health > 0:
            if not self.death_in_progress:  # 防止重复
                self.total_deaths += 1
                self.death_in_progress = True
                
                if self.status_dashboard:
                    self.status_dashboard.update_death_count(1)

                logger.info(f"[死亡检测] 玩家死亡，总死亡数: {self.total_deaths}")
                
        elif current_health > 0:
            # 玩家活着，重置死亡标记
            if self.death_in_progress:
                logger.info(f"[复活检测] 玩家复活，血量: {current_health}")
            self.death_in_progress = False
            
        # ===== 击杀检测 =====
        # 简单逻辑：击杀数增加（不包括归零）
        if not self.first_update and current_kills > self.last_kill_count:
            # 计算新增击杀
            new_kills = current_kills - self.last_kill_count
            new_headshots = max(0, current_killhs - self.last_killhs_count)
            
            # 更新总数
            self.total_kills += new_kills
            self.total_headshots += new_headshots
            
            if self.status_dashboard:
                # 更新击杀数
                for _ in range(new_kills):
                    self.status_dashboard.update_kill_count(1)
                    
                # 更新爆头数
                for _ in range(new_headshots):
                    self.status_dashboard.update_headshot_count()

            logger.info(f"[击杀检测] 新增击杀: +{new_kills} (当前回合: {current_kills}), 爆头: +{new_headshots}")
            logger.info(f"[会话统计] 总击杀: {self.total_kills}, 总爆头: {self.total_headshots}, K/D: {self._calculate_kd()}")
            
        elif current_kills < self.last_kill_count:
            # 击杀数减少，可能是新回合或死亡重置
            logger.info(f"[击杀重置] 击杀数从 {self.last_kill_count} 重置为 {current_kills}")
            
        # 更新记录
        self.last_health = current_health
        self.last_kill_count = current_kills
        self.last_killhs_count = current_killhs
        self.first_update = False  # 标记已完成第一次更新
        
    def _calculate_kd(self):
        """计算K/D比值"""
        if self.total_deaths > 0:
            return f"{self.total_kills / self.total_deaths:.2f}"
        elif self.total_kills > 0:
            return f"{self.total_kills}.00"
        else:
            return "0.00"
            
    def get_stats_summary(self):
        """获取统计摘要"""
        return {
            'total_kills': self.total_kills,
            'total_deaths': self.total_deaths,
            'total_headshots': self.total_headshots,
            'kd_ratio': self._calculate_kd(),
            'headshot_rate': f"{(self.total_headshots / self.total_kills * 100):.1f}%" if self.total_kills > 0 else "0%"
        }
