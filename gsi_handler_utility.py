# SPDX-License-Identifier: GPL-3.0-or-later
import keyboard
import threading
import time
from config import config
from utility_usage_tracker import get_usage_tracker
import os
from resource_manager import ResourceManager
from core.utils.logger import get_logger

logger = get_logger("GSIHandlerUtility")


class GSIHandlerUtility:
    """道具瞄点GSI处理器"""
    
    # CS2地图映射 - 修正地图名称
    CS2_MAPS = {
        # 活跃地图池
        "de_dust2": "炙热沙城",      # 修正：dust2是炙热沙城
        "de_mirage": "荒漠迷城",     # 修正：mirage是荒漠迷城
        "de_inferno": "炼狱小镇",
        "de_nuke": "核子危机",
        "de_overpass": "死亡游乐园",
        "de_vertigo": "殒命大厦",
        "de_ancient": "远古遗迹",
        "de_anubis": "阿努比斯",
        
        # 预备图池
        "de_train": "列车停放站",
        "de_cache": "死城之谜",
        "cs_office": "办公室",
        "cs_italy": "意大利",
    }
    
    def __init__(self):
        self.current_map = None
        self.player_team = None
        self.player_alive = False
        self.utility_display = None

        # 快捷键状态
        self.hotkey_pressed = False
        self.menu_level = 0  # 0=无菜单, 1=位置选择, 2=道具选择
        self.selected_location = 0
        self.selected_location_name = None  # 存储选中的位置名称

        # 记录是否正在显示图片
        self.showing_images = False

        # 地图变化回调
        self.map_change_callback = None

        # 快捷键监听线程
        self.hotkey_thread = None
        self.hotkey_listener_active = False
        self._hotkey_hook_handle = None  # 存储keyboard hook句柄

        # 数字键监听线程
        self.number_listener_thread = None
        self._number_hook_handle = None  # 存储keyboard hook句柄

        # 定时刷新线程
        self.refresh_thread = None
        self.refresh_active = False
        self.last_refresh_time = 0

        # 修改超时检测相关变量
        self.last_data_time = 0  # 上次收到有效数据的时间
        # v2.2.1: 10→15s（配合连续3次判定，实际约24s判退出）。
        # 旧注释声称30秒但实际是10，长加载/长暂停(>20s)会被误判退出并硬重置菜单状态
        self.data_timeout = 15
        self.in_game = False  # 是否在游戏中
        self.consecutive_no_data_count = 0  # 连续无数据计数器

        # 使用频率追踪器
        self.usage_tracker = get_usage_tracker()

        # 初始化快捷键监听

        # 启动定时刷新
        self._runtime_ready = False
    
    def set_utility_display(self, display):
        """设置道具显示控制器"""
        self.utility_display = display
        logger.info("道具显示控制器已连接")
        
        # 重新初始化快捷键监听
        if not self._runtime_ready:
            self._activate_runtime()
        else:
            self.reinit_hotkey_listener()
    
    def set_utility_components(self, utility_display=None, gui_component=None):
        """设置道具瞄点组件（GSI处理器标准接口）"""
        if utility_display:
            self.set_utility_display(utility_display)
        
        if gui_component:
            # 设置地图变化回调
            self.map_change_callback = gui_component.on_map_changed
            logger.info("已设置地图变化回调")
    
    def _activate_runtime(self):
        if self._runtime_ready or not self.utility_display:
            return
        self._runtime_ready = True
        self.init_hotkey_listener()
        self.start_refresh_timer()

    def reinit_hotkey_listener(self):
        """重新初始化快捷键监听"""
        logger.info(f"[道具瞄点] 重新初始化快捷键监听，新快捷键: {config.utility_guide_hotkey}")
        # 停止旧的监听
        self.stop_hotkey_listener()

        # 等待一下确保线程完全停止
        time.sleep(0.2)

        # 启动新的监听
        self.init_hotkey_listener()
        logger.info("[道具瞄点] 快捷键监听已重新启动")
    
    HOTKEY_OWNER = "道具瞄点"

    def _unhook_hold_handles(self):
        """v2.2.1: 注销 hold 模式的 keyboard.on_press/on_release 钩子。"""
        handles = getattr(self, "_hold_hook_handles", None) or []
        self._hold_hook_handles = []
        for handle in handles:
            try:
                keyboard.unhook(handle)
            except Exception:
                pass

    def stop_hotkey_listener(self):
        """停止快捷键监听"""
        self.hotkey_listener_active = False

        # 清理keyboard hook（P2.1: 经注册中心 token 注销）
        if self._hotkey_hook_handle is not None:
            try:
                from core.hotkeys import registry as hotkey_registry

                hotkey_registry.unregister(self._hotkey_hook_handle)
                self._hotkey_hook_handle = None
            except Exception:
                logger.exception("清理hotkey hook失败")

        # v2.2.1: 清理 hold 模式钩子（旧版从不清理→改键后幽灵热键）
        self._unhook_hold_handles()

        # 菜单打开时数字键监听线程与其钩子由 menu_level 驱动：
        # 归零让其自然退出并自清钩子，否则改键/重启监听后残留（漏停一路）
        self.menu_level = 0

        # 等待线程结束
        if self.hotkey_thread and self.hotkey_thread.is_alive():
            self.hotkey_thread.join(timeout=1)
    
    def init_hotkey_listener(self):
        """初始化快捷键监听"""
        if not config.utility_guide_enabled:
            logger.info("道具瞄点功能未启用，跳过快捷键监听")
            return

        # 确保旧线程已停止
        self.stop_hotkey_listener()

        # 启动新的监听线程
        self.hotkey_listener_active = True
        self.hotkey_thread = threading.Thread(target=self._hotkey_listener_thread, daemon=True, name="UtilityHotkey")
        self.hotkey_thread.start()
        logger.info(f"道具瞄点快捷键监听已启动: {config.utility_guide_hotkey}, 模式: {config.utility_guide_mode}")
    
    def _hotkey_listener_thread(self):
        """快捷键监听线程（使用事件驱动）"""
        hotkey = config.utility_guide_hotkey.lower()
        mode = config.utility_guide_mode
        logger.info(f"开始监听快捷键: {hotkey}, 模式: {mode}")

        if mode == "hold":
            # 长按模式 - 使用 keyboard.on_press/on_release 事件
            def on_press(event):
                if not self.hotkey_listener_active:
                    return
                if event.name.lower() == hotkey and not self.hotkey_pressed:
                    self.hotkey_pressed = True
                    self.on_hotkey_press()

            def on_release(event):
                if not self.hotkey_listener_active:
                    return
                if event.name.lower() == hotkey and self.hotkey_pressed:
                    self.hotkey_pressed = False
                    self.on_hotkey_release()

            # v2.2.1: 保存返回的钩子句柄——旧版注册后从不 unhook，
            # 每次改键/重启监听都会泄漏一层旧钩子（闭包捕获旧hotkey），
            # 重新激活后新旧键同时触发（幽灵热键）。
            press_hook = keyboard.on_press(on_press)
            release_hook = keyboard.on_release(on_release)
            self._hold_hook_handles = [press_hook, release_hook]

            # 等待停止信号
            while self.hotkey_listener_active:
                time.sleep(0.1)

            # 线程退出前自清理 hold 钩子（stop_hotkey_listener 也会兜底清理）
            self._unhook_hold_handles()

        else:
            # 切换模式 - 使用事件驱动防止连续触发
            last_toggle_time = [0]  # 使用列表以便在闭包中修改
            last_debug_time = [0]

            def on_key_event(event):
                if not self.hotkey_listener_active:
                    return
                if event.event_type == 'down' and event.name.lower() == hotkey:
                    current_time = time.time()

                    # 每10秒输出一次调试信息
                    if current_time - last_debug_time[0] > 10:
                        logger.info(f"[道具瞄点] 快捷键监听运行中，监听键: {hotkey}, 模式: {mode}, 在游戏中: {self.in_game}, 玩家存活: {self.player_alive}")
                        last_debug_time[0] = current_time

                    logger.info(f"[道具瞄点] 检测到快捷键 {hotkey} 按下！")
                    # 防抖：确保距离上次切换至少500ms
                    if current_time - last_toggle_time[0] > 0.5:
                        self.on_hotkey_toggle()
                        last_toggle_time[0] = current_time

            # P2.1: 经热键注册中心注册（行为等价 keyboard.hook），
            # interest_keys 让其他功能域改键时能发现与引导键的冲突。
            from core.hotkeys import registry as hotkey_registry

            self._hotkey_hook_handle = hotkey_registry.register_hook(
                self.HOTKEY_OWNER, on_key_event,
                interest_keys=[hotkey], note="引导显示切换键",
            )

            # 等待停止信号
            while self.hotkey_listener_active:
                time.sleep(0.1)

            # 清理事件监听（由stop_hotkey_listener统一处理）
    
    def on_hotkey_press(self):
        """快捷键按下"""
        # 如果正在显示图片，直接关闭
        if self.showing_images:
            logger.info("关闭道具图片显示")
            self.menu_level = 0
            self.selected_location = 0
            self.selected_location_name = None
            self.showing_images = False
            if self.utility_display:
                self.utility_display.hide()
            return

        logger.info(f"快捷键按下，玩家存活: {self.player_alive}, 在游戏中: {self.in_game}, 道具显示器: {self.utility_display is not None}")

        if not self.utility_display:
            logger.info("道具显示器未初始化")
            return

        # 修改判断条件：需要在游戏中且玩家存活
        if not self.in_game:
            logger.info("未在游戏中，不显示菜单")
            return

        if not self.player_alive:
            logger.info("玩家未存活，不显示菜单")
            return

        # 显示位置选择菜单
        self.menu_level = 1
        logger.info(f"准备显示位置菜单，当前道具数据: {self.utility_display.utility_data}")
        self.utility_display.show_location_menu()

        # 监听数字键选择
        self._start_number_listener()
    
    def on_hotkey_release(self):
        """快捷键释放（长按模式）"""
        logger.info("快捷键释放")
        if not self.utility_display:
            return

        # 隐藏所有显示
        self.menu_level = 0
        self.selected_location = 0
        self.selected_location_name = None
        self.showing_images = False
        self.utility_display.hide()
    
    def on_hotkey_toggle(self):
        """快捷键切换（切换模式）"""
        # 如果正在显示图片，直接关闭
        if self.showing_images:
            logger.info("关闭道具图片显示")
            self.menu_level = 0
            self.selected_location = 0
            self.selected_location_name = None
            self.showing_images = False
            if self.utility_display:
                self.utility_display.hide()
            return

        logger.info(f"快捷键切换，菜单级别: {self.menu_level}, 玩家存活: {self.player_alive}, 在游戏中: {self.in_game}")

        if not self.utility_display:
            logger.info("道具显示器未初始化")
            return

        # 修改判断条件：需要在游戏中且玩家存活
        if not self.in_game:
            logger.info("未在游戏中，不显示菜单")
            return

        if not self.player_alive:
            logger.info("玩家未存活，不显示菜单")
            return

        if self.menu_level == 0:
            # 显示菜单
            self.menu_level = 1
            logger.info(f"准备显示位置菜单，当前道具数据: {self.utility_display.utility_data}")
            
            # 检查是否有道具数据
            if not self.utility_display.utility_data:
                logger.warning(f"警告：当前地图 {self.current_map} 阵营 {self.player_team} 没有道具数据")
                logger.warning("请检查道具文件夹是否存在并包含正确的图片文件")
                return

            # 隐藏可能存在的图片，显示菜单
            self.utility_display.hide()
            self.utility_display.show_location_menu()
            self._start_number_listener()
        else:
            # 隐藏菜单和图片
            self.menu_level = 0
            self.selected_location = 0
            self.selected_location_name = None
            self.showing_images = False
            self.utility_display.hide()
            logger.info("关闭菜单和图片")
    
    def _start_number_listener(self):
        """启动数字键监听"""
        # 确保不重复启动监听线程
        if hasattr(self, 'number_listener_thread') and self.number_listener_thread and self.number_listener_thread.is_alive():
            logger.info("数字键监听线程已在运行，跳过启动")
            return
            
        self.number_listener_thread = threading.Thread(target=self._number_listener_thread, daemon=True, name="UtilityNumberKey")
        self.number_listener_thread.start()
    
    def _number_listener_thread(self):
        """数字键监听线程（使用事件驱动）"""
        logger.info("开始监听数字键输入")

        # 防止按键重复触发
        last_key_time = {}
        key_cooldown = 0.3  # 300ms冷却时间

        def on_key_event(event):
            if self.menu_level <= 0:
                return

            if event.event_type != 'down':
                return

            current_time = time.time()
            key = event.name

            # 监听数字键1-9
            if key in ['1', '2', '3', '4', '5', '6', '7', '8', '9']:
                # 检查冷却时间
                if key not in last_key_time or current_time - last_key_time[key] > key_cooldown:
                    logger.info(f"数字键 {key} 被按下")
                    self.on_number_pressed(int(key))
                    last_key_time[key] = current_time

            # 监听0键（返回）
            elif key == '0':
                if '0' not in last_key_time or current_time - last_key_time['0'] > key_cooldown:
                    logger.info("0键被按下（返回）")
                    if self.menu_level == 2:
                        # 返回位置选择
                        self.menu_level = 1
                        self.selected_location = 0
                        self.selected_location_name = None
                        self.utility_display.show_location_menu()
                    elif self.menu_level == 1:
                        # 关闭菜单
                        self.menu_level = 0
                        self.selected_location = 0
                        self.selected_location_name = None
                        self.utility_display.hide()
                    last_key_time['0'] = current_time

            # 监听ESC键（取消）
            elif key == 'esc':
                if 'esc' not in last_key_time or current_time - last_key_time['esc'] > key_cooldown:
                    logger.info("ESC键被按下（取消）")
                    self.menu_level = 0
                    self.selected_location = 0
                    self.selected_location_name = None
                    self.showing_images = False
                    self.utility_display.hide()
                    last_key_time['esc'] = current_time

        # P2.1: 经注册中心注册菜单数字键监听（瞬态，菜单关闭即注销）
        from core.hotkeys import registry as hotkey_registry

        self._number_hook_handle = hotkey_registry.register_hook(
            self.HOTKEY_OWNER, on_key_event,
            interest_keys=[str(i) for i in range(1, 10)] + ["esc"],
            note="瞄点菜单数字键(瞬态)",
        )

        # 等待菜单关闭
        while self.menu_level > 0:
            time.sleep(0.1)

        # 清理事件监听
        if self._number_hook_handle is not None:
            try:
                hotkey_registry.unregister(self._number_hook_handle)
                self._number_hook_handle = None
            except Exception:
                logger.exception("清理number hook失败")

        logger.info("数字键监听已停止")

    def on_number_pressed(self, number):
        """数字键按下处理"""
        if not self.utility_display:
            return
        
        if self.menu_level == 1:
            # 选择位置
            logger.info(f"选择位置: {number}")

            # 获取位置名称（用于记录）
            locations = list(self.utility_display.utility_data.keys())
            if 1 <= number <= len(locations):
                self.selected_location_name = locations[number - 1]

            self.selected_location = number
            self.menu_level = 2
            self.utility_display.show_utility_menu(number)

        elif self.menu_level == 2:
            # 选择道具
            logger.info(f"选择道具: 位置{self.selected_location}, 道具{number}")
            
            # 记录使用（在显示之前记录）
            if self.selected_location_name and self.current_map and self.player_team:
                locations = list(self.utility_display.utility_data.keys())
                if 1 <= self.selected_location <= len(locations):
                    location = locations[self.selected_location - 1]
                    utilities = self.utility_display.utility_data[location]
                    
                    if 1 <= number <= len(utilities):
                        utility_name = utilities[number - 1]
                        
                        # 构建文件路径
                        if self.player_team:
                            location_path = ResourceManager.get_app_data_path(
                                f"resources/utility_guides/{self.current_map}/{self.player_team}/{location}"
                            )
                        else:
                            location_path = ResourceManager.get_app_data_path(
                                f"resources/utility_guides/{self.current_map}/{location}"
                            )
                        
                        # 查找图片文件
                        stand_path = None
                        aim_path = None
                        for ext in ['.jpg', '.png']:
                            if not stand_path and os.path.exists(os.path.join(location_path, f"{utility_name}_站位{ext}")):
                                stand_path = os.path.join(location_path, f"{utility_name}_站位{ext}")
                            if not aim_path and os.path.exists(os.path.join(location_path, f"{utility_name}_瞄准{ext}")):
                                aim_path = os.path.join(location_path, f"{utility_name}_瞄准{ext}")
                        
                        # 记录使用
                        if stand_path and aim_path:
                            try:
                                self.usage_tracker.record_usage(
                                    self.current_map,
                                    self.player_team,
                                    location,
                                    utility_name,
                                    stand_path,
                                    aim_path
                                )
                            except Exception:
                                logger.exception("记录使用失败")
            
            # 显示道具
            self.utility_display.show_utility(self.selected_location, number)
            
            # 标记正在显示图片
            self.showing_images = True
            
            # 根据模式决定后续行为
            if config.utility_guide_mode == "toggle":
                # 切换模式：隐藏菜单但保持图片显示
                self.menu_level = 0
                # 只隐藏菜单，不隐藏图片
                self.utility_display._send_command(("hide_menu_only",))
                
                # 如果设置了显示时长，启动定时器
                if config.utility_guide_display_duration > 0:
                    timer = threading.Timer(
                        config.utility_guide_display_duration,
                        self._auto_hide_images
                    )
                    timer.daemon = True
                    timer.start()
            # 长按模式下，等待释放键
    
    def _auto_hide_images(self):
        """自动隐藏图片"""
        self.showing_images = False
        if self.utility_display:
            self.utility_display.hide()
    
    def start_refresh_timer(self):
        """启动定时刷新"""
        if self.refresh_active:
            return
        
        self.refresh_active = True
        self.refresh_thread = threading.Thread(target=self._refresh_timer_thread, daemon=True, name="UtilityRefresh")
        self.refresh_thread.start()
        logger.info("道具瞄点定时刷新已启动")
    
    def stop_refresh_timer(self):
        """停止定时刷新"""
        self.refresh_active = False
        if self.refresh_thread and self.refresh_thread.is_alive():
            self.refresh_thread.join(timeout=1)
    
    def _refresh_timer_thread(self):
        """定时刷新线程"""
        while self.refresh_active:
            try:
                current_time = time.time()
                
                # 修改超时检测逻辑：需要连续多次无数据才判定退出游戏
                if self.in_game:
                    time_since_last_data = current_time - self.last_data_time
                    if time_since_last_data > self.data_timeout:
                        self.consecutive_no_data_count += 1
                        logger.info(f"连续无数据计数: {self.consecutive_no_data_count}, 距离上次数据: {time_since_last_data:.1f}秒")

                        # 需要连续3次检测到无数据才判定退出游戏
                        if self.consecutive_no_data_count >= 3:
                            logger.info("确认退出游戏，重置地图和阵营信息")
                            self.reset_game_state()
                    else:
                        # 有数据，重置计数器
                        self.consecutive_no_data_count = 0
                
                # 每15秒刷新一次
                if current_time - self.last_refresh_time >= 15:
                    if self.in_game:  # 只在游戏中时刷新
                        self.refresh_map_and_team()
                    self.last_refresh_time = current_time
                
                time.sleep(3)  # 改为5秒检查一次，减少检查频率
            except Exception:
                logger.exception("定时刷新错误")
                time.sleep(3)

    def refresh_map_and_team(self):
        """刷新地图和阵营信息"""
        if self.current_map and self.player_team and self.utility_display:
            # 重新加载道具数据（会根据当前阵营加载）
            self.utility_display.load_map_utilities(self.current_map, self.player_team)
            logger.info(f"刷新道具数据 - 地图: {self.current_map}, 阵营: {self.player_team}")
    
    def reset_game_state(self):
        """重置游戏状态（退出游戏时调用）"""
        old_map = self.current_map
        old_team = self.player_team
        
        # 重置状态
        self.in_game = False
        self.current_map = None
        self.player_team = None
        self.player_alive = False
        self.consecutive_no_data_count = 0  # 重置计数器
        
        # 隐藏菜单和图片
        if self.utility_display:
            self.menu_level = 0
            self.selected_location = 0
            self.selected_location_name = None
            self.showing_images = False
            self.utility_display.hide()
            
            # 清空道具数据
            self.utility_display.utility_data.clear()
        
        # 通知UI更新
        if self.map_change_callback:
            try:
                self.map_change_callback(None, None)
                logger.info("已通知UI：退出游戏，重置地图信息")
            except Exception as e:
                # B4: 外部回调异常附加堆栈
                logger.exception(f"调用地图更新回调失败: {e}")

        logger.info(f"游戏状态已重置 - 之前地图: {old_map}, 之前阵营: {old_team}")
    
    def process_data(self, data):
        """处理GSI数据"""
        # 更新最后收到数据的时间
        current_time = time.time()
        
        # 检查是否在游戏中
        # 判断条件：有map数据，且map中有name字段
        is_in_game = False
        if "map" in data and data["map"] and "name" in data["map"]:
            map_name = data["map"]["name"]
            if map_name and map_name != "":
                is_in_game = True
                self.last_data_time = current_time
                # 重置连续无数据计数器
                self.consecutive_no_data_count = 0
        
        # 如果之前在游戏中，现在不在游戏中，不立即重置（等待超时确认）
        if self.in_game and not is_in_game:
            # 不立即重置，等待超时机制确认
            logger.info(f"未收到地图数据，等待确认（连续无数据次数: {self.consecutive_no_data_count}）")
            return

        # 更新游戏状态
        was_in_game = self.in_game
        self.in_game = is_in_game

        # 如果刚进入游戏
        if not was_in_game and is_in_game:
            logger.info("检测到进入游戏")
        
        # 如果不在游戏中，不处理其他数据
        if not is_in_game:
            return
        
        # 检查玩家状态
        if "player" in data:
            player_data = data["player"]
            
            # 更新玩家存活状态
            if "state" in player_data:
                health = player_data["state"].get("health", 0)
                was_alive = self.player_alive
                self.player_alive = health > 0
                
                # 如果玩家死亡，隐藏菜单
                if was_alive and not self.player_alive:
                    logger.info("玩家死亡，隐藏菜单")
                    if self.utility_display:
                        self.menu_level = 0
                        self.selected_location = 0
                        self.selected_location_name = None
                        self.showing_images = False
                        self.utility_display.hide()
                elif not was_alive and self.player_alive:
                    logger.info("玩家复活")
            
            # 更新玩家阵营
            if "team" in player_data:
                old_team = self.player_team
                self.player_team = player_data["team"]
                
                # 如果阵营变化，重新加载道具并通知UI
                if old_team != self.player_team:
                    logger.info(f"阵营变化: {old_team} -> {self.player_team}")
                    if self.current_map:
                        if self.utility_display:
                            self.utility_display.load_map_utilities(self.current_map, self.player_team)
                        # 通知UI更新
                        if self.map_change_callback:
                            try:
                                self.map_change_callback(self.current_map, self.player_team)
                                logger.info(f"已通知UI更新阵营信息: {self.player_team}")
                            except Exception as e:
                                # B4: 外部回调异常附加堆栈
                                logger.exception(f"调用阵营更新回调失败: {e}")
        
        # 检查地图变化
        if "map" in data:
            map_data = data["map"]
            
            if "name" in map_data:
                new_map = map_data["name"]
                
                # 地图变化时重新加载道具
                if new_map != self.current_map:
                    self.current_map = new_map
                    self.on_map_changed(new_map)
    
    def on_map_changed(self, map_name):
        """地图变化处理"""
        logger.info(f"地图切换到: {map_name}")

        # 获取地图显示名称
        map_display_name = self.CS2_MAPS.get(map_name, map_name)
        logger.info(f"地图名称: {map_display_name}")

        # 如果道具显示控制器已初始化，加载新地图的道具
        if self.utility_display:
            # 传递当前阵营（如果有）
            self.utility_display.load_map_utilities(map_name, self.player_team)
            logger.info(f"道具数据: {self.utility_display.utility_data}")

        # 重置菜单状态
        self.menu_level = 0
        self.selected_location = 0
        self.selected_location_name = None
        self.showing_images = False

        # 调用UI更新回调
        if self.map_change_callback:
            try:
                self.map_change_callback(map_name, self.player_team)
                logger.info(f"已通知UI更新地图信息: {map_name}, 阵营: {self.player_team}")
            except Exception as e:
                # B4: 外部回调异常附加堆栈
                logger.exception(f"调用地图更新回调失败: {e}")
