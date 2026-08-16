# SPDX-License-Identifier: GPL-3.0-or-later
import threading
import time
import math
import random
import os
from ctypes import windll
from core.utils.logger import get_logger
from core.utils.lazy_module import lazy_module

# UP-055: `import pygame` 曾在第 1 行。实测它是 show 前关键路径上最后一个
# pygame 入口（gui_widget.__init__ 建准心管理器时触发），本机约 400ms。
# 本模块用的是 threading 不是 multiprocessing，pygame 必须能在**主进程**里加载，
# 所以只能推迟、不能移走——推迟到用户真的显示准心那一刻。
# 用代理而不是"把 import 挪进各个方法"：`pygame.` 在本文件十几个方法里出现，
# 漏一处就是运行期崩溃。代理让漏掉的那处照常工作。
# 打包安全：pygame 在 build_release.py 的 BASE_HIDDEN_IMPORTS 里显式列着。
pygame = lazy_module("pygame", __name__)

logger = get_logger("CrosshairAnimation")

# 尝试导入win32相关库
try:
    import win32gui
    import win32con
    import win32api
    win32_available = True
except ImportError:
    win32_available = False
    logger.warning("未安装pywin32库，准心功能将不可用")

def show_win32_error():
    """显示Win32错误提示"""
    import tkinter.messagebox as messagebox
    messagebox.showerror(
        "错误", 
        "准心功能需要安装 pywin32 库。\n\n"
        "请在命令行中运行：\n"
        "pip install pywin32"
    )

class CrosshairAnimationSystem:
    """优化后的准心动画系统 - 保留所有功能"""
    def __init__(self, config_obj, root=None):
        self.config = config_obj
        self.root = root
        self.is_visible = False
        self.overlay_win = None
        self.draw_thread = None
        self.redraw_event = threading.Event()
        
        # 准心设置 - 从配置加载
        self.size = getattr(config_obj, 'crosshair_size', 20)
        self.thickness = getattr(config_obj, 'crosshair_thickness', 2)
        self.color = getattr(config_obj, 'crosshair_color', 'red')
        self.style = getattr(config_obj, 'crosshair_style', 'crosshair')
        self.animation_style = getattr(config_obj, 'crosshair_animation', 'none')
        self.kill_effect = getattr(config_obj, 'crosshair_kill_effect', 'none')
        
        # 动画状态
        self.kill_animation_active = False
        self.kill_animation_start_time = 0
        self.kill_animation_type = None
        self.is_headshot = False
        
        # 性能优化变量
        self.last_frame_time = 0
        self.frame_skip_counter = 0
        self.need_redraw = True
        self.last_settings = None
        
        # 碎片效果变量
        self.shatter_fragments = []
        self.last_shatter_time = 0
        
        # 窗口相关
        self.window_size = 100  # 使用100x100的小窗口，足够显示准心
        self.window_center = (50, 50)  # 窗口中心
        
        # 颜色映射表（类常量，避免每帧创建）
        self.COLOR_MAP = {
            "red": (255, 0, 0, 255),
            "green": (0, 255, 0, 255),
            "blue": (0, 0, 255, 255),
            "yellow": (255, 255, 0, 255),
            "cyan": (0, 255, 255, 255),
            "white": (255, 255, 255, 255)
        }
        
    def show_crosshair(self):
        """显示准心窗口"""
        logger.info("准心动画初始化")
        if not win32_available:
            logger.error("pywin32未安装，无法显示准心")
            show_win32_error()
            return
            
        # 2.2.0 丝滑化:窗口已存在 → 只切 win32 可见性(毫秒级)。
        # 此前每次开关都销毁/重建 pygame 窗口+绘制线程,单次实测 ~916ms,
        # 是"点击发卡"的最大单点。失败自动回退完整重建路径,功能零妥协。
        if self.overlay_win is not None and not getattr(self, "_destroyed", False):
            try:
                hwnd = pygame.display.get_wm_info()["window"]
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
                self.is_visible = True
                self.need_redraw = True
                self.redraw_event.set()
                if not (self.draw_thread and self.draw_thread.is_alive()):
                    self.draw_thread = threading.Thread(
                        target=self.draw_crosshair_loop, daemon=True, name="CrosshairDraw"
                    )
                    self.draw_thread.start()
                logger.info("准心快速恢复显示(复用窗口)")
                return
            except Exception:
                logger.exception("准心快速显示失败,回退完整重建")
                self.overlay_win = None

        # 如果已经显示，先隐藏
        if self.is_visible:
            logger.info("准心已在显示中，先隐藏再重新创建")
            self.destroy()
            time.sleep(0.1)  # 等待资源释放
            
        try:
            logger.info("开始创建准心窗口...")
            # 初始化pygame（如果已经初始化会自动跳过）
            if not pygame.get_init():
                pygame.init()
            pygame.display.init()  # 确保display模块初始化
            
            # 获取屏幕尺寸 - 使用和KillIconWorker相同的方式
            screen_width = win32api.GetSystemMetrics(0)
            screen_height = win32api.GetSystemMetrics(1)
            logger.info(f"[准心] 屏幕分辨率: {screen_width}x{screen_height}")
            
            # 计算窗口位置（屏幕中心）
            window_x = (screen_width - self.window_size) // 2
            window_y = (screen_height - self.window_size) // 2
            logger.info(f"[准心] 窗口大小={self.window_size}x{self.window_size}, 窗口位置=({window_x}, {window_y})")
            
            # 设置窗口位置
            os.environ['SDL_VIDEO_WINDOW_POS'] = f'{window_x},{window_y}'
            
            # 创建窗口 - 优化：使用小窗口而不是全屏
            self.overlay_win = pygame.display.set_mode((self.window_size, self.window_size), pygame.NOFRAME)
            pygame.display.set_caption("Crosshair Overlay")
            
            # 获取窗口句柄
            hwnd = pygame.display.get_wm_info()["window"]
            
            # 设置窗口属性
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 
                                 ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW)
            
            # 设置透明
            user32 = windll.user32

            def RGB(r, g, b):
                return r | (g << 8) | (b << 16)

            user32.SetLayeredWindowAttributes(hwnd, RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
            
            # 置顶
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            
            # 保存窗口信息
            self.window_center = (self.window_size // 2, self.window_size // 2)
            
            # 开启绘制循环（重建路径必须清 _destroyed：destroy() 超时兜底
            # 会保持该标志为 True，不清的话新线程一进循环就退出，准心不可见）
            self._destroyed = False
            self.redraw_event.clear()
            self.is_visible = True
            self.draw_thread = threading.Thread(target=self.draw_crosshair_loop, daemon=True, name="CrosshairDraw")
            self.draw_thread.start()
            
            logger.info("准心显示成功 - 使用优化的小窗口模式")
            
        except Exception as e:
            logger.error(f"显示准心时出错: {e}", exc_info=True)
    
    def update_settings(self, size, thickness, color, style, animation_style, kill_effect):
        """更新准心设置。

        ⚠ **这套老渲染器不支持 2.2.4 补的样式参数**（中心间隙 / 描边 / 中心点 /
        透明度 / 自定义色）。它只在 Qt 渲染器创建失败时才会被启用，属于保命回退，
        不值得把新几何再实现一遍。

        但"不支持"必须**出声**：静默忽略的话，用户在页面上拖间隙滑块、预览也
        跟着变，游戏里却纹丝不动，看起来像功能坏了而不是回退了。这里在真的
        配了新参数时记一条 warning，体检报告和日志里都能看到。
        """
        self._warn_unsupported_extras()
        # 检查设置是否改变
        new_settings = (size, thickness, color, style, animation_style, kill_effect)
        if self.last_settings != new_settings:
            self.need_redraw = True
            self.redraw_event.set()
            self.last_settings = new_settings
            
        self.size = size
        self.thickness = thickness
        self.color = color
        self.style = style
        self.animation_style = animation_style
        self.kill_effect = kill_effect

    #: 老渲染器画不出来的样式参数：配置名 → 中文说明。空值/0 视为没配。
    _UNSUPPORTED_EXTRAS = {
        "crosshair_gap": "中心间隙",
        "crosshair_outline": "黑色描边",
        "crosshair_dot": "中心点",
        "crosshair_color_custom": "自定义颜色",
    }

    def _warn_unsupported_extras(self):
        try:
            configured = [
                label
                for attr, label in self._UNSUPPORTED_EXTRAS.items()
                if getattr(self.config, attr, None) not in (None, "", 0, False)
            ]
            alpha = getattr(self.config, "crosshair_alpha", 255)
            if alpha not in (None, 255):
                configured.append("透明度")
            if configured and configured != getattr(self, "_warned_extras", None):
                self._warned_extras = configured
                self.logger.warning(
                    "[准心] 当前是 pygame 回退渲染器，以下设置画不出来："
                    + "、".join(configured)
                    + "（只有 Qt 渲染器创建失败才会回退，原因见启动日志）"
                )
        except Exception:
            pass

    def draw_crosshair_loop(self):
        """优化的准心绘制循环 - 保留所有动画功能"""
        try:
            running = True
            # 动画相关变量
            self.animation_phase = 0
            
            # 使用Pygame的Clock控制帧率
            clock = pygame.time.Clock()
            
            while running and not getattr(self, "_destroyed", False):
                # 2.2.0: 隐藏期间线程不退出,idle 等待——再次显示零创建成本
                if not self.is_visible:
                    self.redraw_event.wait(timeout=0.5)
                    self.redraw_event.clear()
                    continue
                current_time = time.time()
                
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                
                # 获取当前设置
                size = self.size
                thickness = self.thickness
                color_name = self.color
                style = self.style
                animation_style = self.animation_style
                
                has_animation = (animation_style != "none") or self.kill_animation_active
                if not has_animation and not self.need_redraw:
                    self.redraw_event.wait(timeout=0.5)
                    self.redraw_event.clear()
                    continue
                
                if self.redraw_event.is_set():
                    self.redraw_event.clear()
                
                # 清屏为黑色背景（会被透明化）
                self.overlay_win.fill((0, 0, 0))
                
                # 使用类常量颜色映射表
                color = self.COLOR_MAP.get(color_name, (0, 255, 0, 255))
                
                # 应用动画效果
                modified_size = size
                modified_color = color
                modified_thickness = thickness
                rotation_angle = 0
                center = self.window_center  # 使用窗口中心
                shatter_progress = 0
                
                # 更新动画阶段
                self.animation_phase += 0.05
                if self.animation_phase > 6.28:  # 2*PI
                    self.animation_phase = 0
                
                sin_phase = math.sin(self.animation_phase)
                abs_sin_phase = abs(sin_phase)
                sin_double = math.sin(self.animation_phase * 2)
                sin_triple = math.sin(self.animation_phase * 3)
                
                # 处理常规动画
                if animation_style == "breathing":
                    # 呼吸效果 - 大小变化
                    scale_factor = 1.0 + 0.2 * abs_sin_phase
                    modified_size = int(size * scale_factor)
                
                elif animation_style == "pulse":
                    # 脉冲效果
                    if random.random() < 0.01:
                        pulse_value = 1.0
                        modified_size = int(size * (1.0 + 0.3 * pulse_value))
                
                elif animation_style == "color":
                    # 颜色渐变
                    r = int((math.sin(self.animation_phase) * 0.5 + 0.5) * 255)
                    g = int((math.sin(self.animation_phase + 2.0) * 0.5 + 0.5) * 255)
                    b = int((math.sin(self.animation_phase + 4.0) * 0.5 + 0.5) * 255)
                    modified_color = (r, g, b, 255)
                
                elif animation_style == "rotate":
                    # 旋转效果
                    rotation_angle = self.animation_phase * 57.3  # 弧度转角度
                
                elif animation_style == "wave":
                    # 扩散效果
                    modified_size = int(size * (1.0 + 0.15 * sin_double))
                    modified_thickness = max(1, int(thickness * (1.0 + 0.2 * sin_triple)))
                
                elif animation_style == "bounce":
                    # 弹跳效果
                    bounce_offset = sin_double * 5
                    center = (self.window_center[0], self.window_center[1] + bounce_offset)
                
                elif animation_style == "blink":
                    # 闪烁效果
                    if sin_triple > 0:
                        modified_color = self.brighten_color(color, 1.5)
                    else:
                        modified_color = self.dim_color(color, 0.7)
                
                elif animation_style == "shake":
                    # 抖动效果
                    shake_intensity = 2.0
                    shake_x = random.uniform(-shake_intensity, shake_intensity)
                    shake_y = random.uniform(-shake_intensity, shake_intensity)
                    center = (self.window_center[0] + shake_x, self.window_center[1] + shake_y)
                
                # 处理击杀联动动画
                if self.kill_animation_active:
                    duration = 0.8  # 动画持续时间
                    elapsed = current_time - self.kill_animation_start_time
                    
                    if elapsed > duration:
                        # 动画结束
                        self.kill_animation_active = False
                    else:
                        # 动画进行中
                        progress = elapsed / duration
                        
                        if self.kill_animation_type == "pulse":
                            # 脉冲效果 - 增强版
                            pulse_factor = 1.0 + math.sin(progress * math.pi) * 1.0
                            modified_size = int(modified_size * pulse_factor)
                        
                        elif self.kill_animation_type == "explosion":
                            # 爆炸效果 - 增强版
                            if progress < 0.5:
                                explosion_factor = 1.0 + progress * 4.0
                            else:
                                explosion_factor = 3.0 - (progress - 0.5) * 4.0
                            modified_size = int(modified_size * explosion_factor)
                        
                        elif self.kill_animation_type == "rotate":
                            # 旋转效果 - 增强版
                            extra_rotation = progress * 720
                            rotation_angle += extra_rotation
                        
                        elif self.kill_animation_type == "shake":
                            # 抖动效果 - 增强版
                            shake_intensity = 10.0 * (1.0 - progress)
                            shake_x = random.uniform(-shake_intensity, shake_intensity)
                            shake_y = random.uniform(-shake_intensity, shake_intensity)
                            center = (self.window_center[0] + shake_x, self.window_center[1] + shake_y)
                            
                        elif self.kill_animation_type == "x_flash":
                            # X形闪烁效果
                            if progress < 0.4:
                                style = "x_mark"
                                modified_color = (255, 0, 0, 255)
                            else:
                                modified_color = self.brighten_color(color, 1.5)
                        
                        elif self.kill_animation_type == "rainbow_wave":
                            # 彩虹冲击波效果
                            wave_radius = progress * 40
                            hue = (progress * 360) % 360
                            r, g, b = self.hsv_to_rgb(hue/360, 1.0, 1.0)
                            wave_color = (r, g, b, int(255 * (1.0 - progress)))
                            self.draw_wave_effect(center, wave_radius, wave_color)
                        
                        elif self.kill_animation_type == "shatter":
                            # 破碎重组效果
                            if progress < 0.3:
                                style = "shatter"
                                shatter_progress = progress / 0.3
                            elif progress < 0.7:
                                style = "dot"
                                modified_size = max(3, size // 8)
                            else:
                                style = "shatter"
                                shatter_progress = 1.0 - (progress - 0.7) / 0.3
                        
                        elif self.kill_animation_type == "multi_pulse":
                            # 多重脉冲效果
                            pulse_frequency = 15
                            pulse_factor = 1.0 + 0.8 * abs(math.sin(progress * math.pi * pulse_frequency))
                            modified_size = int(modified_size * pulse_factor)
                            color_intensity = 0.7 + 0.3 * abs(math.sin(progress * math.pi * pulse_frequency))
                            modified_color = self.brighten_color(color, color_intensity + 0.5)
                        
                        elif self.kill_animation_type == "neon_wave":
                            # 霓虹扩散效果
                            hue = (progress * 360) % 360
                            r, g, b = self.hsv_to_rgb(hue/360, 1.0, 1.0)
                            modified_color = (r, g, b, 255)
                            
                            # 添加多层扩散波
                            for i in range(3):
                                wave_progress = (progress + i * 0.2) % 1.0
                                wave_radius = wave_progress * 40
                                wave_alpha = int(255 * (1.0 - wave_progress))
                                if wave_alpha > 0:
                                    wave_color = (r, g, b, wave_alpha)
                                    outline_width = max(1, int(modified_thickness * (1.0 - wave_progress)))
                                    pygame.draw.circle(self.overlay_win, wave_color, center, int(wave_radius), outline_width)
                        
                        elif self.kill_animation_type == "x_overlay":
                            # 十字星辉效果
                            center_x, center_y = center
                            x_angle = 45
                            x_size = size * 1.8
                            x_alpha = 255
                            
                            rad_angle = math.radians(x_angle)
                            cos_val = math.cos(rad_angle)
                            sin_val = math.sin(rad_angle)
                            
                            base_color = self.COLOR_MAP.get(color_name, (0, 255, 0, 255))[:3]
                            x_color = base_color + (x_alpha,)
                            
                            # 绘制X形
                            line_length = int(x_size // 2)
                            inner_gap = max(3, modified_size // 4)
                            
                            # 计算点位置
                            outer_p1 = (center_x + line_length * cos_val, center_y + line_length * sin_val)
                            outer_p2 = (center_x - line_length * cos_val, center_y - line_length * sin_val)
                            outer_p3 = (center_x + line_length * sin_val, center_y - line_length * cos_val)
                            outer_p4 = (center_x - line_length * sin_val, center_y + line_length * cos_val)
                            
                            inner_p1 = (center_x + inner_gap * cos_val, center_y + inner_gap * sin_val)
                            inner_p2 = (center_x - inner_gap * cos_val, center_y - inner_gap * sin_val)
                            inner_p3 = (center_x + inner_gap * sin_val, center_y - inner_gap * cos_val)
                            inner_p4 = (center_x - inner_gap * sin_val, center_y + inner_gap * cos_val)
                            
                            x_thickness = max(1, modified_thickness)
                            
                            # 绘制线条
                            pygame.draw.line(self.overlay_win, x_color, outer_p1, inner_p1, x_thickness)
                            pygame.draw.line(self.overlay_win, x_color, outer_p2, inner_p2, x_thickness)
                            pygame.draw.line(self.overlay_win, x_color, outer_p3, inner_p3, x_thickness)
                            pygame.draw.line(self.overlay_win, x_color, outer_p4, inner_p4, x_thickness)
                
                # 绘制不同风格的准心
                center_x, center_y = center
                
                # 特殊效果样式处理
                if style == "x_mark":
                    # X形准心
                    line_length = modified_size // 2
                    pygame.draw.line(self.overlay_win, modified_color, 
                                (center_x - line_length, center_y - line_length), 
                                (center_x + line_length, center_y + line_length), modified_thickness)
                    pygame.draw.line(self.overlay_win, modified_color, 
                                (center_x - line_length, center_y + line_length), 
                                (center_x + line_length, center_y - line_length), modified_thickness)
                elif style == "shatter":
                    # 破碎效果处理
                    self._draw_shatter_effect(center, modified_size, modified_thickness, modified_color, shatter_progress)
                elif style == "crosshair":
                    if rotation_angle != 0:
                        # 旋转的十字准心
                        self._draw_rotated_crosshair(center, modified_size, modified_thickness, modified_color, rotation_angle)
                    else:
                        # 标准十字准心
                        pygame.draw.line(self.overlay_win, modified_color, 
                                    (center_x, center_y - modified_size//2), 
                                    (center_x, center_y + modified_size//2), modified_thickness)
                        pygame.draw.line(self.overlay_win, modified_color, 
                                    (center_x - modified_size//2, center_y), 
                                    (center_x + modified_size//2, center_y), modified_thickness)
                elif style == "dot":
                    radius = max(2, modified_size // 4)
                    pygame.draw.circle(self.overlay_win, modified_color, center, radius)
                elif style == "circle":
                    radius = max(5, modified_size // 2)
                    pygame.draw.circle(self.overlay_win, modified_color, center, radius, modified_thickness)
                elif style == "t_shape":
                    # T型准心
                    pygame.draw.line(self.overlay_win, modified_color,
                                (center_x, center_y), 
                                (center_x, center_y + modified_size//2), modified_thickness)
                    pygame.draw.line(self.overlay_win, modified_color,
                                (center_x - modified_size//2, center_y), 
                                (center_x + modified_size//2, center_y), modified_thickness)
                elif style == "custom" and hasattr(self.config, 'crosshair_custom_data') and self.config.crosshair_custom_data:
                    # 自定义准心
                    self._draw_custom_crosshair(center, modified_size, modified_thickness, modified_color, rotation_angle)
                
                # 更新显示
                pygame.display.flip()
                self.need_redraw = False
                
                # 智能动态帧率控制 - 根据实际需求调节
                if has_animation:
                    clock.tick(24)  # 动态效果保持流畅
                else:
                    clock.tick(1)  # 静态准心时极低帧率以节省资源
                    
        except Exception as e:
            logger.error(f"准心绘制错误: {e}", exc_info=True)
    
    def _draw_rotated_crosshair(self, center, size, thickness, color, angle):
        """绘制旋转的十字准心"""
        center_x, center_y = center
        rad_angle = math.radians(angle)
        cos_val = math.cos(rad_angle)
        sin_val = math.sin(rad_angle)
        
        # 计算旋转后的线条端点
        length = size // 2
        p1 = (center_x + length * cos_val, center_y + length * sin_val)
        p2 = (center_x - length * cos_val, center_y - length * sin_val)
        p3 = (center_x + length * sin_val, center_y - length * cos_val)
        p4 = (center_x - length * sin_val, center_y + length * cos_val)
        
        pygame.draw.line(self.overlay_win, color, p1, p2, thickness)
        pygame.draw.line(self.overlay_win, color, p3, p4, thickness)
    
    def _draw_custom_crosshair(self, center, size, thickness, color, rotation_angle=0):
        """绘制自定义准心，支持旋转"""
        center_x, center_y = center
        scale = size / 15
        pixel_size = max(1, thickness)
        
        for point in self.config.crosshair_custom_data:
            x, y = point
            
            if rotation_angle != 0:
                # 旋转自定义准心点
                rad_angle = math.radians(rotation_angle)
                cos_val = math.cos(rad_angle)
                sin_val = math.sin(rad_angle)
                
                # 相对于中心的坐标
                rel_x = (x - 15) * scale
                rel_y = (y - 15) * scale
                
                # 旋转坐标
                rot_x = rel_x * cos_val - rel_y * sin_val
                rot_y = rel_x * sin_val + rel_y * cos_val
                
                abs_x = center_x + rot_x
                abs_y = center_y + rot_y
            else:
                # 不旋转的普通坐标转换
                abs_x = center_x + (x - 15) * scale
                abs_y = center_y + (y - 15) * scale
            
            # 绘制像素点
            pygame.draw.rect(self.overlay_win, color, 
                          (abs_x - pixel_size/2, abs_y - pixel_size/2, 
                           pixel_size, pixel_size))
    
    def _draw_shatter_effect(self, center, size, thickness, color, progress):
        """绘制破碎效果"""
        center_x, center_y = center
        
        # 创建碎片数据（如果不存在）
        if not hasattr(self, 'shatter_fragments') or self.kill_animation_start_time != getattr(self, 'last_shatter_time', 0):
            self.shatter_fragments = []
            if self.style == "crosshair":
                # 十字准心的碎片
                fragments_count = 8
                for i in range(fragments_count):
                    angle = 2 * math.pi * i / fragments_count
                    distance = random.uniform(0.3, 1.0) * size
                    self.shatter_fragments.append({
                        'x': math.cos(angle) * distance,
                        'y': math.sin(angle) * distance,
                        'size': max(3, size // 3),
                        'angle': random.uniform(0, math.pi)
                    })
            else:
                # 其他准心类型的碎片
                fragments_count = 6
                for i in range(fragments_count):
                    angle = 2 * math.pi * i / fragments_count
                    distance = random.uniform(0.2, 0.8) * size
                    self.shatter_fragments.append({
                        'x': math.cos(angle) * distance,
                        'y': math.sin(angle) * distance,
                        'size': max(2, size // 4),
                        'angle': random.uniform(0, math.pi)
                    })
            
            self.last_shatter_time = self.kill_animation_start_time
        
        # 绘制碎片
        for fragment in self.shatter_fragments:
            # 计算当前位置（应用progress）
            curr_x = center_x + fragment['x'] * progress
            curr_y = center_y + fragment['y'] * progress
            
            # 根据原准心类型绘制碎片
            if self.style == "crosshair":
                # 十字碎片 - 小线段
                line_len = fragment['size'] // 2
                angle = fragment['angle'] + progress * math.pi
                end_x = curr_x + math.cos(angle) * line_len
                end_y = curr_y + math.sin(angle) * line_len
                start_x = curr_x - math.cos(angle) * line_len
                start_y = curr_y - math.sin(angle) * line_len
                pygame.draw.line(self.overlay_win, color, 
                            (start_x, start_y), (end_x, end_y), 
                            max(1, thickness - 1))
            elif self.style == "circle":
                # 圆形碎片 - 小弧
                pygame.draw.arc(self.overlay_win, color, 
                            (curr_x - fragment['size'], curr_y - fragment['size'], 
                             fragment['size']*2, fragment['size']*2), 
                            fragment['angle'], fragment['angle'] + math.pi,
                            max(1, thickness - 1))
            else:
                # 其他类型 - 小点
                pygame.draw.circle(self.overlay_win, color, 
                                (int(curr_x), int(curr_y)), 
                                max(1, fragment['size'] // 2))
    
    def draw_wave_effect(self, center, radius, color):
        """绘制波纹效果"""
        if radius > 0:
            pygame.draw.circle(self.overlay_win, color, center, int(radius), 2)
            
    def brighten_color(self, color, factor):
        """调亮颜色"""
        r, g, b, a = color
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))
        return (r, g, b, a)
    
    def dim_color(self, color, factor):
        """调暗颜色。下限取1：纯黑(0,0,0)是分层窗口的透明色键，
        深色准心闪烁压暗到精确纯黑会被整块抠成透明（准心出现缺口）"""
        r, g, b, a = color
        r = max(1, int(r * factor))
        g = max(1, int(g * factor))
        b = max(1, int(b * factor))
        return (r, g, b, a)
    
    def hsv_to_rgb(self, h, s, v):
        """将HSV颜色值转换为RGB"""
        if s == 0.0:
            return (v, v, v)
        
        i = int(h * 6)
        f = (h * 6) - i
        p = v * (1 - s)
        q = v * (1 - s * f)
        t = v * (1 - s * (1 - f))
        
        i %= 6
        if i == 0:
            return (int(v * 255), int(t * 255), int(p * 255))
        elif i == 1:
            return (int(q * 255), int(v * 255), int(p * 255))
        elif i == 2:
            return (int(p * 255), int(v * 255), int(t * 255))
        elif i == 3:
            return (int(p * 255), int(q * 255), int(v * 255))
        elif i == 4:
            return (int(t * 255), int(p * 255), int(v * 255))
        else:
            return (int(v * 255), int(p * 255), int(q * 255))
    
    def register_kill_handler(self, gsi_handler_kills):
        """注册到击杀处理器以接收击杀事件"""
        if gsi_handler_kills:
            gsi_handler_kills.register_kill_callback(self.on_kill_event)
            try:
                overlay_manager = getattr(self.root, "screen_effect_overlay", None) if self.root else None
                if overlay_manager and hasattr(overlay_manager, "on_kill_event"):
                    gsi_handler_kills.register_kill_callback(overlay_manager.on_kill_event)
            except Exception:
                pass
            logger.info("[CrosshairAnimation] 已注册到击杀处理器")
    
    def on_kill_event(self, is_headshot):
        """处理击杀事件"""
        if not self.is_visible:
            return
           
        # 获取当前设置的击杀联动效果
        kill_effect = self.kill_effect
        if kill_effect == "none":
            return
        
        self.kill_animation_active = True
        self.kill_animation_start_time = time.time()
        self.kill_animation_type = kill_effect
        self.is_headshot = is_headshot
        self.need_redraw = True  # 触发重绘
        self.redraw_event.set()
    
    def hide_crosshair(self):
        """隐藏准心(2.2.0: 只隐藏窗口,不销毁——再次显示毫秒级)"""
        if not self.is_visible:
            logger.info("准心未显示，无需隐藏")
            return

        self.is_visible = False
        self.redraw_event.set()

        if self.overlay_win is not None:
            try:
                hwnd = pygame.display.get_wm_info()["window"]
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                logger.info("准心已隐藏(窗口保留,复显零成本)")
                return
            except Exception:
                logger.exception("快速隐藏失败,走完整销毁")
        self.destroy()

    def destroy(self):
        """完整销毁窗口与绘制线程(退出/重建时用)。"""
        logger.info("正在销毁准心窗口...")
        self._destroyed = True
        self.is_visible = False
        self.redraw_event.set()

        # 等待绘制线程结束（静态准心的等待周期最长约1s，留足余量）
        if self.draw_thread and self.draw_thread.is_alive():
            logger.info("等待绘制线程结束...")
            self.draw_thread.join(timeout=2.0)
            if self.draw_thread.is_alive():
                # 线程未按时退出：保持 _destroyed=True 让它醒来后自行退出。
                # 此时绝不能 display.quit() 或复位标志——旧线程会在已销毁的
                # 表面上继续绘制，或复活后与下次重建的新线程抢绘同一窗口
                logger.warning("绘制线程未在超时内退出，跳过窗口销毁（线程将自行退出，重建路径会重置状态）")
                return
        self.draw_thread = None

        # 清理 Pygame 资源
        if self.overlay_win:
            try:
                pygame.display.quit()
                self.overlay_win = None
                logger.info("Pygame窗口已关闭")
            except Exception as e:
                logger.error(f"关闭窗口时出错: {e}")

        self._destroyed = False  # 允许之后重新创建
        logger.info("准心已销毁")

# 保持向后兼容的别名
CrosshairAnimation = CrosshairAnimationSystem
