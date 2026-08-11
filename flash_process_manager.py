# SPDX-License-Identifier: GPL-3.0-or-later
import multiprocessing
from multiprocessing import Process, Queue
import time
import os
import sys
import threading
from core.utils.logger import get_logger

logger = get_logger("FlashProcess")

def _set_spawn_method():
    """确保使用spawn方法启动进程，这在Windows上是必须的"""
    try:
        if sys.platform == 'win32':
            multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        # 如果已经设置过，可能会抛出异常，可以忽略
        pass

class FlashProcessManager:
    """管理闪光效果进程 - 增强版"""

    def __init__(self, config_obj):
        # 设置进程启动方法
        _set_spawn_method()

        self.config = config_obj
        self.process = None
        self.command_queue = None
        self.is_running = False
        self._main_window = None
        self._cleanup_done = False  # 防止重复清理

        # 设置
        self.bg_color = "white"
        self.max_opacity = 0.75
        self.image_opacity = 0.5
        self.image_position = (0.5, 0.5)
        self.image_size = (0.3, 0.3)

        # 新增：闪光样式
        self.flash_style = "standard"
        self.style_parameters = {}

        # 淡入淡出控制变量 - 明确初始化默认值
        self.fade_in_enabled = True    # 默认启用淡入效果
        self.fade_out_enabled = True   # 默认启用淡出效果

        # 进程监控变量
        self.last_health_check = 0
        self.health_check_interval = 5.0  # 5秒检查一次进程健康状态
        # v2.2.1: 闪光断流看门狗——CS2 被闪时 GSI 推包频率很高(远快于1s/包)，
        # 10s 无更新且闪光值>0 必然是断流(崩溃/退出)，强制清屏防永久留屏
        self.flash_stale_timeout = 10.0
        self._last_flash_update_time = 0.0
        self.restart_attempts = 0
        self.max_restart_attempts = 3
        self._last_restart_time = 0.0  # 稳定运行超过窗口后重启计数归零
        self._monitor_thread = None  # 存储监控线程引用

        # 当前闪光值
        self.current_flash_value = 0

        # 闪光音频相关
        self.audio_enabled = config_obj.flash_audio_enabled if hasattr(config_obj, 'flash_audio_enabled') else False
        self.audio_style = config_obj.flash_audio_style if hasattr(config_obj, 'flash_audio_style') else "none"
        self.audio_volume = config_obj.flash_audio_volume if hasattr(config_obj, 'flash_audio_volume') else 1.0
        self.audio_auto_stop = config_obj.flash_audio_auto_stop if hasattr(config_obj, 'flash_audio_auto_stop') else True
        self.current_audio = None
        self.audio_channel = None
        self.audio_playing = False

        # 保存屏幕尺寸
        self._saved_screen_width = 1920  # 默认值
        self._saved_screen_height = 1080  # 默认值
        self._pending_flash_image_style = "none"  # 进程未启动时记录待加载样式

        # 从配置加载设置
        self.load_settings_from_config()
    
    def load_settings_from_config(self):
        """从配置加载设置"""
        if hasattr(self.config, 'flash_bg_color'):
            self.bg_color = self.config.flash_bg_color
        if hasattr(self.config, 'flash_max_opacity'):
            self.max_opacity = self.config.flash_max_opacity
        if hasattr(self.config, 'flash_image_opacity'):
            self.image_opacity = self.config.flash_image_opacity
        if hasattr(self.config, 'flash_image_position'):
            self.image_position = self.config.flash_image_position
        if hasattr(self.config, 'flash_image_size'):
            self.image_size = self.config.flash_image_size
        if hasattr(self.config, 'flash_style'):
            self.flash_style = self.config.flash_style
        if hasattr(self.config, 'flash_style_params'):
            self.style_parameters = self.config.flash_style_params
            
        # 加载淡入淡出设置 - 修复点：添加这部分代码
        if hasattr(self.config, 'flash_fade_in_enabled'):
            self.fade_in_enabled = self.config.flash_fade_in_enabled
        if hasattr(self.config, 'flash_fade_out_enabled'):
            self.fade_out_enabled = self.config.flash_fade_out_enabled
        
        # 加载音频设置
        if hasattr(self.config, 'flash_audio_enabled'):
            self.audio_enabled = self.config.flash_audio_enabled
        if hasattr(self.config, 'flash_audio_style'):
            self.audio_style = self.config.flash_audio_style
        if hasattr(self.config, 'flash_audio_volume'):
            self.audio_volume = self.config.flash_audio_volume
        if hasattr(self.config, 'flash_audio_auto_stop'):
            self.audio_auto_stop = self.config.flash_audio_auto_stop
            
        if hasattr(self.config, 'flash_image_style') and self.config.flash_image_style != "none":
            self.load_flash_image(self.config.flash_image_style)

    def set_main_window(self, window):
        """设置主窗口引用，用于显示 Toast 通知"""
        self._main_window = window

    def start_process(self, screen_width, screen_height):
        """启动闪光效果进程"""
        if self.is_running:
            return

        # stop→start 复用同一个管理器时必须复位闩锁与重启计数，
        # 否则第二代进程的 stop_process 会被 _cleanup_done 直接短路，永远停不掉
        self._cleanup_done = False
        self.restart_attempts = 0

        # 保存屏幕尺寸
        self._saved_screen_width = screen_width
        self._saved_screen_height = screen_height
        
        # 创建命令队列
        self.command_queue = Queue()
        
        # 导入闪光进程模块
        from flash_process import process_function
        
        try:
            # 创建并启动进程（增加重试机制）
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    self.process = Process(
                        target=process_function,
                        args=(self.command_queue, screen_width, screen_height),
                        daemon=True
                    )
                    self.process.start()
                    
                    # 等待进程启动确认（最多等待2秒）
                    for i in range(20):
                        if self.process.is_alive():
                            break
                        time.sleep(0.1)
                    
                    if not self.process.is_alive():
                        raise RuntimeError("进程启动后立即终止")
                    
                    break  # 启动成功，跳出重试循环
                    
                except (PermissionError, RuntimeError) as e:
                    logger.error(f"启动闪光进程失败 (尝试 {attempt + 1}/{max_attempts}): {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(0.5)  # 等待一下再重试
                        # 清理失败的进程
                        if self.process and hasattr(self.process, 'terminate'):
                            try:
                                self.process.terminate()
                                self.process.join(timeout=1.0)
                            except Exception:
                                pass
                        # 重新创建命令队列
                        self.command_queue = Queue()
                    else:
                        raise  # 最后一次尝试失败，抛出异常
            
            self.is_running = True
            logger.info(f"闪光效果进程已启动 (PID: {self.process.pid if hasattr(self.process, 'pid') else 'Unknown'})")
            
            # 发送初始设置
            self.send_settings()
            
            # 发送样式设置
            self.update_flash_style(self.flash_style)
            if self.style_parameters:
                self.update_style_parameters(self.style_parameters)
                
            # 发送淡入淡出设置 - 修复点：添加这行代码
            self.update_fade_settings(fade_in_enabled=self.fade_in_enabled, fade_out_enabled=self.fade_out_enabled)
            
            # 如果有图片，加载它
            if hasattr(self.config, 'flash_image_style') and self.config.flash_image_style != "none":
                self.load_flash_image(self.config.flash_image_style)
            
            # 启动进程监控
            self.start_health_monitoring()
        except Exception as e:
            logger.error(f"启动闪光进程失败 (所有重试均失败): {e}", exc_info=True)
            self.is_running = False
            logger.warning("警告：闪光功能已禁用，但程序将继续运行")
            if self._main_window:
                self._main_window.show_toast_safe("闪白效果启动失败，该功能暂不可用", "error", 5000)
    
    def start_health_monitoring(self):
        """启动进程健康监控"""
        def monitor_process():
            while self.is_running:
                try:
                    current_time = time.time()

                    # 定期检查进程状态
                    if current_time - self.last_health_check >= self.health_check_interval:
                        self.last_health_check = current_time

                        # 检查进程是否存活
                        if self.process and hasattr(self.process, 'is_alive') and not self.process.is_alive():
                            logger.info("检测到闪光进程已终止，尝试重启...")
                            self.restart_process()

                        # v2.2.1: GSI 断流看门狗（见 _check_flash_stale）
                        self._check_flash_stale(current_time)

                except Exception as e:
                    logger.info(f"监控进程时出错: {e}")

                # 睡眠一段时间，减少CPU占用
                time.sleep(1.0)

        # 启动监控线程
        self._monitor_thread = threading.Thread(target=monitor_process, daemon=True, name="FlashMonitor")
        self._monitor_thread.start()
    
    def _check_flash_stale(self, current_time: float) -> bool:
        """v2.2.1: GSI 断流看门狗——正被闪时游戏崩溃/退出导致归零包永远不来，
        闪光效果会永久留屏（子进程按最后值恒定渲染）。
        闪光值 >0 且超过 stale 窗口没有任何更新 → 强制清除。返回是否触发了清除。
        """
        if (
            self.current_flash_value > 0
            and self._last_flash_update_time > 0
            and current_time - self._last_flash_update_time > self.flash_stale_timeout
        ):
            logger.warning(
                f"闪光值 {self.current_flash_value} 已 {self.flash_stale_timeout:.0f}s 无更新"
                "（GSI疑似断流），看门狗强制清除闪光"
            )
            self.force_clear_flash()
            self.current_flash_value = 0
            return True
        return False

    def restart_process(self):
        """尝试重启进程"""
        # 距上次重启已稳定运行超过 60s，视为偶发崩溃，计数归零；
        # 否则整个生命周期内累计 3 次偶发崩溃就会永久禁用闪光
        if self.restart_attempts > 0 and time.time() - self._last_restart_time > 60.0:
            self.restart_attempts = 0

        if self.restart_attempts >= self.max_restart_attempts:
            logger.warning(f"已达到最大重启尝试次数 ({self.max_restart_attempts})，放弃重启")
            self.is_running = False
            if self._main_window:
                self._main_window.show_toast_safe("闪光进程多次崩溃，已停用；可重开闪光页恢复", "error", 5000)
            return False
        
        try:
            # 停止现有进程
            if self.process:
                try:
                    if hasattr(self.process, 'terminate'):
                        self.process.terminate()
                    if hasattr(self.process, 'join'):
                        self.process.join(timeout=1.0)
                except Exception:
                    pass
            
            # 重置命令队列
            self.command_queue = Queue()
            
            # 获取屏幕尺寸
            screen_width = self._saved_screen_width
            screen_height = self._saved_screen_height
            
            # 导入闪光进程模块
            from flash_process import process_function
            
            # 创建并启动新进程
            self.process = Process(
                target=process_function,
                args=(self.command_queue, screen_width, screen_height),
                daemon=True
            )
            self.process.start()
            
            # 发送所有设置
            self.send_settings()
            self.update_flash_style(self.flash_style)
            if self.style_parameters:
                self.update_style_parameters(self.style_parameters)
                
            # 发送淡入淡出设置 - 修复点：添加这行代码
            self.update_fade_settings(fade_in_enabled=self.fade_in_enabled, fade_out_enabled=self.fade_out_enabled)
            
            # 如果有图片，重新加载
            if hasattr(self.config, 'flash_image_style') and self.config.flash_image_style != "none":
                self.load_flash_image(self.config.flash_image_style)
            
            self.restart_attempts += 1
            self._last_restart_time = time.time()
            logger.info(f"闪光进程已重启 (尝试 {self.restart_attempts}/{self.max_restart_attempts})")
            return True
            
        except Exception as e:
            logger.error(f"重启闪光进程失败: {e}")
            self.is_running = False
            return False
    
    def stop_process(self):
        """停止闪光效果进程"""
        if self._cleanup_done:
            return

        self._cleanup_done = True

        # 停止监控标志
        self.is_running = False

        # UP-007: 先把关闭命令发出去，再去等监控线程。
        # 原先顺序是反的——先 join 监控线程最多 2 秒，这段时间里子进程根本还不知道
        # 要退出，白白浪费；发完命令再等，子进程的收尾与我们的等待就重叠了。
        # 子进程的命令线程每 50ms 轮询一次队列，命令几乎立刻就被看到。
        if self.command_queue:
            try:
                self.command_queue.put({"type": "shutdown"}, timeout=1.0)
            except Exception as e:
                logger.warning(f"发送关闭命令失败: {e}")

        # 等待监控线程结束
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

        # 等待进程结束
        if self.process:
            try:
                if hasattr(self.process, 'join'):
                    self.process.join(timeout=2.0)

                # 如果进程还在运行，强制终止
                if hasattr(self.process, 'is_alive') and self.process.is_alive():
                    if hasattr(self.process, 'terminate'):
                        logger.info("进程未正常退出，强制终止")
                        self.process.terminate()
                        self.process.join(timeout=1.0)

                    # 最后手段：kill
                    if hasattr(self.process, 'is_alive') and self.process.is_alive():
                        if hasattr(self.process, 'kill'):
                            logger.warning("进程仍未退出，使用kill")
                            self.process.kill()
            except Exception as e:
                logger.error(f"停止进程时出错: {e}")

        self.process = None
        self.command_queue = None

        # 停止音频
        self.stop_audio()

        logger.info("闪光效果进程已停止")
    
    def update_flash_value(self, value):
        """更新闪光值，检测闪光开始时自动轮换图片"""
        if not self.is_running or not self.command_queue:
            return False
            
        # 清空队列中的旧闪光值更新命令，避免堆积
        self._clear_pending_flash_updates()
        
        # 检测闪光开始事件（从0变为非0）
        flash_starting = (value > 0 and self.current_flash_value == 0)
        
        # 检测闪光结束事件（从非0变为0）
        flash_ending = (value == 0 and self.current_flash_value > 0)
        
        # 如果闪光开始且启用了图片轮换，先轮换图片
        if flash_starting and hasattr(self.config, 'flash_image_rotation') and self.config.flash_image_rotation != "none":
            # 选择新图片
            self._rotate_flash_image()
            
            # 闪光开始，播放音频
            if self.audio_enabled and self.audio_style != "none":
                self.play_audio()
        
        # 如果闪光结束且启用了自动停止音频，停止音频
        if flash_ending and self.audio_enabled and self.audio_auto_stop:
            self.stop_audio()
            logger.info("闪光结束，根据设置自动停止音频")
        
        # 更新当前闪光值
        self.current_flash_value = value
        self._last_flash_update_time = time.time()  # v2.2.1: 供断流看门狗判定

        # 发送新的闪光值更新命令
        try:
            self.command_queue.put({
                "type": "update_flash",
                "value": value
            })
            logger.info(f"已发送闪光值更新: {value}")
            return True
        except Exception as e:
            logger.error(f"发送闪光值更新失败: {e}")
            return False
    
    def _rotate_flash_image(self):
        """根据轮换模式选择并加载新图片"""
        # 获取当前选择的风格名称
        style_name = self.config.flash_image_style if hasattr(self.config, 'flash_image_style') else "none"
        
        if style_name == "none":
            return
            
        # 获取轮换模式
        rotation_mode = self.config.flash_image_rotation if hasattr(self.config, 'flash_image_rotation') else "none"
        
        if rotation_mode == "none":
            return
        
        # 获取图片风格目录
        from resource_manager import ResourceManager
        style_dir = ResourceManager.get_app_data_path(f"resources/flash_images/{style_name}")
        
        # 检查目录是否存在
        if not os.path.exists(style_dir):
            logger.warning(f"警告: 闪光图片风格目录不存在: {style_dir}")
            return
        
        # 收集目录中所有有效图片
        valid_images = []
        for filename in os.listdir(style_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                valid_images.append(os.path.join(style_dir, filename))
        
        # 如果没有找到有效图片，返回
        if not valid_images:
            return
        
        # 根据轮换模式选择图片
        selected_image = None
        
        if rotation_mode == "random":
            # 随机选择图片
            import random
            selected_image = random.choice(valid_images)
            logger.info(f"闪光轮换: 随机选择图片: {os.path.basename(selected_image)}")
            
        elif rotation_mode == "sequence":
            # 顺序选择图片
            if not hasattr(self.config, 'flash_current_image_index'):
                self.config.flash_current_image_index = 0
            
            # 更新索引并保存配置
            index = self.config.flash_current_image_index % len(valid_images)
            self.config.flash_current_image_index = (index + 1) % len(valid_images)
            self.config.save_config()
            
            selected_image = valid_images[index]
            logger.info(f"闪光轮换: 顺序选择图片: {os.path.basename(selected_image)} (索引: {index})")
        
        # 如果选择了新图片，发送加载命令
        if selected_image and os.path.exists(selected_image):
            self.send_command({
                "type": "load_image",
                "path": selected_image
            })
    
    def _clear_pending_flash_updates(self):
        """清除队列中待处理的闪光值更新命令"""
        if not self.is_running or not self.command_queue:
            return
            
        # v2.2.1: 临时存储改用普通list——旧实现每次新建 multiprocessing.Queue
        # （会创建feeder线程+管道），高频闪光更新下开销显著
        kept_commands = []

        # 清空当前队列，只保留非闪光值更新命令
        try:
            while not self.command_queue.empty():
                cmd = self.command_queue.get(block=False)
                if cmd["type"] != "update_flash":
                    kept_commands.append(cmd)
        except Exception:
            pass

        # 将保留的命令放回原队列
        try:
            for cmd in kept_commands:
                self.command_queue.put(cmd)
        except Exception:
            pass
            
    def force_clear_flash(self):
        """强制清除闪光效果"""
        if not self.is_running or not self.command_queue:
            return
            
        # 发送强制清除命令
        try:
            self.command_queue.put({
                "type": "force_clear",
                "priority": True  # 标记为高优先级
            })
            logger.info("已发送强制清除命令")
            return True
        except Exception as e:
            logger.error(f"发送强制清除命令失败: {e}")
            return False
    
    def update_flash_style(self, style):
        """更新闪光样式"""
        if not self.is_running or not self.command_queue:
            self.flash_style = style  # 保存样式，以便进程启动时应用
            return False
            
        # 发送样式更新命令
        try:
            self.command_queue.put({
                "type": "update_style",
                "style": style
            })
            self.flash_style = style
            logger.info(f"已发送闪光样式更新: {style}")
            return True
        except Exception as e:
            logger.error(f"发送闪光样式更新失败: {e}")
            return False
    
    def update_style_parameters(self, parameters):
        """更新样式参数"""
        if not self.is_running or not self.command_queue:
            self.style_parameters = parameters  # 保存参数，以便进程启动时应用
            return False
            
        # 发送参数更新命令
        try:
            self.command_queue.put({
                "type": "update_style_parameters",
                "parameters": parameters
            })
            self.style_parameters = parameters
            logger.info("已发送样式参数更新")
            return True
        except Exception as e:
            logger.error(f"发送样式参数更新失败: {e}")
            return False
    
    def update_image_rotation(self, rotation_mode):
        """更新图片轮换模式"""
        if not self.is_running or not self.command_queue:
            return False
            
        # 发送更新命令
        try:
            self.command_queue.put({
                "type": "update_image_rotation",
                "mode": rotation_mode
            })
            logger.info(f"已发送图片轮换模式更新: {rotation_mode}")
            return True
        except Exception as e:
            logger.error(f"发送图片轮换模式更新失败: {e}")
            return False
    
    def update_fade_settings(self, fade_in_enabled=None, fade_out_enabled=None):
        """更新淡入淡出设置"""
        # 更新本地设置
        if fade_in_enabled is not None:
            self.fade_in_enabled = fade_in_enabled
        if fade_out_enabled is not None:
            self.fade_out_enabled = fade_out_enabled
            
        # 发送到进程
        if self.is_running and self.command_queue:
            self.send_command({
                "type": "update_fade_settings",
                "settings": {
                    "fade_in_enabled": self.fade_in_enabled,
                    "fade_out_enabled": self.fade_out_enabled
                }
            })
            logger.info(f"已发送淡入淡出设置更新: 淡入={self.fade_in_enabled}, 淡出={self.fade_out_enabled}")
    
    def load_flash_image(self, style_name):
        """加载闪光图片 - 初始加载不处理轮换"""
        from resource_manager import ResourceManager
        
        logger.info(f"请求加载闪光图片风格: {style_name}")
        self._pending_flash_image_style = style_name

        if not self.is_running or not self.command_queue:
            logger.debug(f"闪光进程未运行，已记录待加载图片风格: {style_name}")
            return
        
        if style_name == "none":
            logger.info("设置为不使用图片")
            success = self.send_command({
                "type": "load_image",
                "path": "none"
            })
            logger.error(f"发送无图片命令 {'成功' if success else '失败'}")
            return
            
        # 获取图片风格目录
        style_dir = ResourceManager.get_app_data_path(f"resources/flash_images/{style_name}")
        
        # 检查目录是否存在
        if not os.path.exists(style_dir):
            logger.warning(f"警告: 闪光图片风格目录不存在: {style_dir}")
            return
        
        # 默认图片路径
        default_image = os.path.join(style_dir, "flash.png")
        
        # 检查默认图片是否存在
        if os.path.exists(default_image):
            # 发送加载命令
            success = self.send_command({
                "type": "load_image",
                "path": default_image
            })
            if success:
                logger.info(f"已加载初始闪光图片: {default_image}")
            else:
                logger.error("发送加载图片命令失败")
        else:
            # 尝试查找目录中的任意图片作为备选
            for filename in os.listdir(style_dir):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    backup_image = os.path.join(style_dir, filename)
                    success = self.send_command({
                        "type": "load_image",
                        "path": backup_image
                    })
                    if success:
                        logger.info(f"已加载备选闪光图片: {backup_image}")
                        return
            
            logger.warning("警告: 找不到有效的闪光图片")
    
    def send_settings(self):
        """发送所有设置到进程"""
        if not self.is_running or not self.command_queue:
            return
            
        # 发送设置命令
        self.send_command({
            "type": "update_settings",
            "settings": {
                "bg_color": self.bg_color,
                "max_opacity": self.max_opacity,
                "image_opacity": self.image_opacity,
                "image_position": self.image_position,
                "image_size": self.image_size
            }
        })
        
    def send_command(self, command):
        """发送命令到进程并确认"""
        if not self.is_running or not self.command_queue:
            logger.error(f"无法发送命令 {command['type']}: 进程未运行")
            return False
            
        try:
            self.command_queue.put(command)
            logger.info(f"已发送命令: {command['type']}")
            return True
        except Exception as e:
            logger.error(f"发送命令失败: {e}")
            return False
    
    def update_settings(self, bg_color=None, max_opacity=None, image_opacity=None, 
                      image_position=None, image_size=None):
        """更新设置"""
        # 更新本地设置
        if bg_color is not None:
            self.bg_color = bg_color
        if max_opacity is not None:
            # 确保最小不透明度为0.01 (1%)
            self.max_opacity = max(0.01, max_opacity)
        if image_opacity is not None:
            self.image_opacity = image_opacity
        if image_position is not None:
            self.image_position = image_position
        if image_size is not None:
            self.image_size = image_size
            
        # 发送到进程
        if self.is_running and self.command_queue:
            self.send_command({
                "type": "update_settings",
                "settings": {
                    "bg_color": self.bg_color,
                    "max_opacity": self.max_opacity,
                    "image_opacity": self.image_opacity,
                    "image_position": self.image_position,
                    "image_size": self.image_size
                }
            })
            logger.info(f"已发送设置更新: 颜色={self.bg_color}, 不透明度={self.max_opacity:.2f}")
    
    def preview_flash(self, intensity=0.75, duration=3.0):
        """预览闪光效果 - 支持自定义持续时间"""
        if not self.is_running:
            logger.info("闪光效果进程未运行")
            return
            
        # 发送预览闪光值
        self.update_flash_value(int(intensity * 255))
        
        # 几秒后重置
        def reset_preview():
            time.sleep(duration)
            self.update_flash_value(0)
            
        # 启动重置线程
        reset_thread = threading.Thread(target=reset_preview, daemon=True, name="FlashPreviewReset")
        reset_thread.start()
        
    # 音频相关方法
    def play_audio(self):
        """播放闪光音频"""
        if not self.audio_enabled or self.audio_style == "none":
            return
        
        # 停止当前播放的音频
        self.stop_audio()
        
        # 选择音频文件
        audio_file = self._select_audio_file()
        if not audio_file:
            return
        
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, channels=2)
            
            # 创建专用通道用于播放闪光音频
            if self.audio_channel is None:
                self.audio_channel = pygame.mixer.Channel(10)  # 使用通道10
            
            # 加载音频
            self.current_audio = pygame.mixer.Sound(audio_file)
            self.current_audio.set_volume(self.audio_volume)
            
            # 在专用通道播放音频
            # 如果不是自动停止模式，则循环播放(pygame: -1 = 无限循环)
            # v2.1.1 fix: 旧版 else 0 是 bug, 导致"关闭自动停止"开关从未生效
            loops = 0 if self.audio_auto_stop else -1
            self.audio_channel.play(self.current_audio, loops=loops)
            
            self.audio_playing = True
            logger.info(f"播放闪光音频: {os.path.basename(audio_file)}, 自动停止: {self.audio_auto_stop}, 循环模式: {loops == -1}")
        except Exception as e:
            logger.error(f"播放闪光音频失败: {e}", exc_info=True)

    def stop_audio(self):
        """停止闪光音频"""
        try:
            import pygame
            if not pygame.mixer.get_init():
                self.current_audio = None
                self.audio_playing = False
                return

            if self.audio_channel and self.audio_channel.get_busy():
                logger.info("停止闪光音频")
                self.audio_channel.stop()
            
            self.current_audio = None
            self.audio_playing = False
        except Exception as e:
            logger.error(f"停止闪光音频失败: {e}")

    def _select_audio_file(self):
        """根据轮换模式选择音频文件"""
        from resource_manager import ResourceManager
        
        # 获取音频风格目录
        style_dir = ResourceManager.get_app_data_path(f"resources/flash_audio/{self.audio_style}")
        
        # 检查目录是否存在
        if not os.path.exists(style_dir):
            logger.warning(f"警告: 闪光音频风格目录不存在: {style_dir}")
            return None
        
        # 收集目录中所有有效音频文件
        valid_audio_files = []
        for filename in os.listdir(style_dir):
            if filename.lower().endswith(('.mp3', '.wav')):
                valid_audio_files.append(os.path.join(style_dir, filename))
        
        # 如果没有找到有效音频文件，返回
        if not valid_audio_files:
            return None
        
        # 根据轮换模式选择音频
        selected_audio = None
        rotation_mode = self.config.flash_audio_rotation if hasattr(self.config, 'flash_audio_rotation') else "none"
        
        if rotation_mode == "random":
            # 随机选择音频
            import random
            selected_audio = random.choice(valid_audio_files)
            logger.info(f"闪光音频轮换: 随机选择: {os.path.basename(selected_audio)}")
            
        elif rotation_mode == "sequence":
            # 顺序选择音频
            if not hasattr(self.config, 'flash_current_audio_index'):
                self.config.flash_current_audio_index = 0
            
            # 更新索引并保存配置
            index = self.config.flash_current_audio_index % len(valid_audio_files)
            self.config.flash_current_audio_index = (index + 1) % len(valid_audio_files)
            self.config.save_config()
            
            selected_audio = valid_audio_files[index]
            logger.info(f"闪光音频轮换: 顺序选择: {os.path.basename(selected_audio)} (索引: {index})")
        
        else:  # "none" 或其他
            # 使用第一个音频文件
            selected_audio = valid_audio_files[0]
            logger.info(f"闪光音频: 使用第一个文件: {os.path.basename(selected_audio)}")
        
        return selected_audio

    def play_test_audio(self):
        """播放测试音频"""
        if not self.is_running:
            logger.info("闪光效果进程未运行")
            return
        
        # 播放音频
        self.play_audio()
        
        # 如果设置了自动停止，则不需要额外操作，音频会自然结束
        # 如果禁用了自动停止，需要设置一个定时器手动停止测试音频
        if not self.audio_auto_stop:
            def stop_test():
                import time
                time.sleep(10)  # 测试音频播放10秒
                self.stop_audio()
                logger.info("测试音频已手动停止")
            
            import threading
            stop_thread = threading.Thread(target=stop_test, daemon=True, name="FlashTestStop")
            stop_thread.start()
            
    def update_audio_enabled(self, enabled):
        """更新音频启用状态"""
        self.audio_enabled = enabled
        
        # 如果禁用，停止当前播放的音频
        if not enabled and self.audio_playing:
            self.stop_audio()
        
        logger.info(f"闪光音频功能: {'开启' if enabled else '关闭'}")
            
    def update_audio_style(self, style):
        """更新音频风格"""
        self.audio_style = style
        
        # 如果正在播放，重新开始播放新风格
        if self.audio_playing:
            self.stop_audio()
            if self.current_flash_value > 0:
                self.play_audio()
                
        logger.info(f"闪光音频风格已更新: {style}")
            
    def update_audio_volume(self, volume):
        """更新音频音量"""
        self.audio_volume = volume
        
        # 如果正在播放，更新音量
        if self.audio_playing and self.current_audio:
            try:
                if hasattr(self.current_audio, 'set_volume'):
                    self.current_audio.set_volume(volume)
                    logger.info(f"已更新闪光音频音量: {volume:.2f}")
            except Exception as e:
                logger.error(f"更新音频音量失败: {e}")
                
    def update_auto_stop_setting(self, auto_stop):
        """更新闪光结束自动停止音频设置"""
        old_setting = self.audio_auto_stop
        self.audio_auto_stop = auto_stop
        logger.info(f"音频自动停止设置已从 {old_setting} 更新为 {auto_stop}")
        
        # 如果当前正在播放且设置发生变化
        if self.audio_playing and old_setting != auto_stop:
            # 如果从自动停止改为不自动停止，需要切换到循环播放
            if not auto_stop:
                self.restart_audio_in_loop_mode()
            # 如果从不自动停止改为自动停止，不需要特殊处理，让当前播放继续

    def restart_audio_in_loop_mode(self):
        """重新开始循环播放当前音频"""
        if not self.audio_playing or not self.current_audio:
            return
            
        try:
            # 保存当前音频
            current = self.current_audio
            
            # 停止当前播放
            if self.audio_channel:
                self.audio_channel.stop()
                
            # 重新以循环模式播放
            if self.audio_channel:
                self.audio_channel.play(current, loops=-1)
                logger.info("已切换到循环播放模式")
        except Exception as e:
            logger.error(f"切换到循环播放模式失败: {e}")
