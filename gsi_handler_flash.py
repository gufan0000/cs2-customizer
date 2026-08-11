# SPDX-License-Identifier: GPL-3.0-or-later
import threading
import time
from config import config
from core.utils.logger import get_logger

logger = get_logger("GSIHandlerFlash")

class GSIHandlerFlash:
    def __init__(self):
        # Flash component reference
        self.flash_component = None
        
        # Tracking flash state
        self.current_flash_value = 0
        self.last_flash_update_time = 0
        self.update_throttle = 0.05  # Seconds between updates
        
        # 添加回合跟踪
        self.last_round = -1
        
        logger.info("Flash GSI handler initialized")
    
    def set_flash_component(self, flash_component):
        """Set the flash UI component reference"""
        self.flash_component = flash_component
        logger.info("Flash component connected to GSI handler")
    
    def process_data(self, data):
        """处理GSI数据获取闪光状态"""
        # 跳过禁用状态
        if not hasattr(config, 'flash_enabled') or not config.flash_enabled:
            return
        
        # 获取当前时间
        current_time = time.time()
        
        # 获取闪光值
        flash_value = self._get_flash_value(data)
        
        # 添加额外的安全检查 - 如果玩家死亡或轮换，强制清除闪光效果
        player_data = data.get("player", {})
        player_state = player_data.get("state", {})
        player_health = player_state.get("health", -1)
        player_round = data.get("map", {}).get("round", -1)
        
        # 强制清除条件：玩家死亡或回合变化 → 闪光值按 0 处理。
        # 只在"确有闪光需要清"时告警：死亡状态会持续数秒、每帧都命中本条件，
        # 若不加 current_flash_value>0 的门，会每帧刷警告并每帧起延迟清除线程
        if player_health == 0 or (hasattr(self, 'last_round') and player_round != self.last_round and player_round > 0):
            flash_value = 0
            if self.current_flash_value > 0:
                logger.warning("检测到玩家状态变化，强制清除闪光效果")

        # 更新回合状态
        if player_round > 0:
            self.last_round = player_round

        # 打印调试信息（每帧都来，必须用 debug 级避免刷屏）
        value_change = abs(flash_value - self.current_flash_value)
        logger.debug(f"GSI闪光值: {flash_value}, 上一个值: {self.current_flash_value}, 变化: {value_change}, 时间间隔: {current_time - self.last_flash_update_time:.3f}秒")

        # 1. 处理闪光开始 - 闪光值从0变为非0
        if flash_value > 0 and self.current_flash_value == 0:
            # 闪光开始，立即更新
            self.last_flash_update_time = current_time
            self.current_flash_value = flash_value
            
            # 更新闪光组件，这会触发图片轮换和音频播放
            if self.flash_component and hasattr(self.flash_component, 'process_manager'):
                self.flash_component.process_manager.update_flash_value(flash_value)
                logger.info("检测到闪光开始，已更新闪光值")
        
        # 2. 处理闪光结束 - 闪光值从非0变为0（含强制清除，其已把 flash_value 归0）。
        # current_flash_value 已是0时无事可做，不再进入（旧逻辑裸 or force_clear
        # 会在死亡期间每帧发清除命令+起延迟线程，冲击子进程管道）
        elif flash_value == 0 and self.current_flash_value > 0:
            # 闪光结束，立即更新
            self.last_flash_update_time = current_time
            self.current_flash_value = 0
            
            # 更新闪光组件
            if self.flash_component and hasattr(self.flash_component, 'process_manager'):
                process_manager = self.flash_component.process_manager
                
                # 更新闪光值
                process_manager.update_flash_value(0)
                logger.info("检测到闪光结束，已清除闪光")
                
                # 检查是否需要停止音频
                if hasattr(process_manager, 'audio_auto_stop') and hasattr(process_manager, 'audio_playing'):
                    if process_manager.audio_auto_stop and process_manager.audio_playing:
                        if hasattr(process_manager, 'stop_audio'):
                            process_manager.stop_audio()
                            logger.info("根据自动停止设置停止闪光音频")
                    elif process_manager.audio_playing:
                        logger.info("保持音频播放（自动停止已禁用）")
                
                # 延迟100ms后发送强制清除命令，双重保险
                def send_delayed_clear():
                    time.sleep(0.1)
                    if hasattr(process_manager, 'force_clear_flash'):
                        process_manager.force_clear_flash()
                        logger.info("发送延迟闪光清除命令")
                
                # 启动延迟清除线程
                clear_thread = threading.Thread(target=send_delayed_clear, daemon=True, name="FlashDelayedClear")
                clear_thread.start()
        
        # 3. 普通闪光值变化 - 只更新闪光值（按 update_throttle 节流：
        # 闪光渐暗时值逐帧连续变化，无需每帧转发给子进程）
        elif flash_value != self.current_flash_value:
            if current_time - self.last_flash_update_time < self.update_throttle:
                return
            self.last_flash_update_time = current_time
            self.current_flash_value = flash_value

            # 更新闪光组件
            if self.flash_component and hasattr(self.flash_component, 'process_manager'):
                self.flash_component.process_manager.update_flash_value(flash_value)
                logger.debug(f"更新闪光值: {flash_value}")
    
    def _is_player_active(self, data):
        """检查玩家是否处于活动状态"""
        return (
            "player" in data and 
            "activity" in data["player"] and 
            data["player"]["activity"] == "playing"
        )
    
    def _get_flash_value(self, data):
        """从GSI数据中提取闪光值"""
        try:
            # 闪光值在GSI数据中的路径
            if "player" in data and "state" in data["player"]:
                player_state = data["player"]["state"]
                if "flashed" in player_state:
                    return int(player_state["flashed"])
            return 0
        except (KeyError, TypeError, ValueError):
            logger.exception("获取闪光值出错")
            return 0