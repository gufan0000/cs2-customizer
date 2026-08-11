# SPDX-License-Identifier: GPL-3.0-or-later
import pygame
import os
import sys
import time
import threading
import math
import random
import queue
from multiprocessing import Queue
import win32gui
import win32con
from ctypes import windll

# 添加DPI感知设置
def set_dpi_awareness():
    """设置DPI感知以避免缩放问题"""
    try:
        # Windows 10及以上版本 - Per-Monitor V2 DPI awareness (最佳)
        windll.shcore.SetProcessDpiAwareness(2)  # 2 = Per-Monitor DPI aware V2
        print("DPI感知模式: Per-Monitor V2")
    except Exception as e:
        print(f"Per-Monitor V2 不可用: {e}")
        try:
            # Windows 8.1及以上版本 - System DPI aware
            windll.shcore.SetProcessDpiAwareness(1)
            print("DPI感知模式: System DPI aware")
        except Exception as e:
            print(f"System DPI aware 不可用: {e}")
            try:
                # Windows Vista及以上版本 - DPI aware
                windll.user32.SetProcessDPIAware()
                print("DPI感知模式: DPI aware")
            except Exception as e:
                print(f"无法设置DPI感知模式: {e}")

# 在定义类之前调用
set_dpi_awareness()

class FlashEffectProcess:
    def __init__(self):
        self.is_running = False
        self.flash_value = 0
        self.bg_color = "white"
        self.max_opacity = 0.75
        self.current_opacity = 0
        self.screen_width = 0
        self.screen_height = 0
        self.flash_image = None
        self.original_image = None
        self.original_image_size = (0, 0)
        self.image_opacity = 0.5
        self.image_position = (0.5, 0.5)
        self.image_size = (0.3, 0.3)
        self.needs_redraw = True
        
        # 保存程序是否在EXE环境中运行
        self.is_exe = getattr(sys, 'frozen', False)
        
        # 新增闪光样式相关属性
        self.flash_style = "standard"  # 默认标准样式
        
        # 脉冲效果参数
        self.pulse_speed = 8.0       # 脉冲速度
        self.pulse_intensity = 0.15  # 脉冲强度
        
        # 模糊效果参数
        self.blur_factor = 0.3       # 模糊强度
        self.blur_layers = 5         # 模糊层数
        
        # 光晕效果参数
        self.halo_intensity = 0.8    # 光晕强度
        self.halo_size = 0.75        # 光晕大小因子
        
        # 彩色效果参数
        self.color_cycle_speed = 2.0  # 颜色循环速度
        self.color_intensity = 0.3    # 颜色强度
        
        # 波纹效果参数
        self.wave_speed = 2.0        # 波纹速度
        self.wave_count = 3          # 波纹数量
        self.wave_thickness = 8      # 波纹线条粗细
        
        # 闪烁效果参数
        self.flicker_speed = 15.0    # 闪烁速度
        self.flicker_randomness = 0.3 # 闪烁随机度
        
        # 旋转效果参数
        self.rotation_speed = 2.0    # 旋转速度
        self.ray_count = 12          # 光芒数量
        
        # 颗粒效果参数
        self.particle_count = 200    # 颗粒数量
        self.particle_size_range = (2, 6) # 颗粒大小范围
        
        # 淡入淡出控制
        self.is_fading_in = False
        self.is_fading_out = False
        self.fade_start_time = 0
        self.fade_in_duration = 0.3  # 300ms淡入
        self.fade_out_duration = 0.2  # 200ms淡出
        self.fade_in_enabled = True  # 是否启用淡入效果
        self.fade_out_enabled = True # 是否启用淡出效果
        
    def initialize(self, screen_width, screen_height):
        """初始化闪光效果进程"""
        self.screen_width = screen_width
        self.screen_height = screen_height
        
        # 确保pygame模块正确初始化
        if not pygame.get_init():
            pygame.init()
        
        print(f"当前环境: {'EXE' if self.is_exe else 'Python'}, 屏幕尺寸: {screen_width}x{screen_height}")
        
        # 重置窗口位置设置
        os.environ.pop('SDL_VIDEO_WINDOW_POS', None)
        
        # 清除任何可能的SDL视频位置设置
        if 'SDL_VIDEO_WINDOW_POS' in os.environ:
            del os.environ['SDL_VIDEO_WINDOW_POS']
        
        # 使用CENTERED初始化窗口
        os.environ['SDL_VIDEO_CENTERED'] = '1'
        
        # 创建窗口 - 使用标准方式
        self.overlay_win = pygame.display.set_mode(
            (screen_width, screen_height), 
            pygame.NOFRAME | pygame.SRCALPHA
        )
        pygame.display.set_caption("Flash_Effect")
        
        # 获取窗口句柄并设置属性
        hwnd = pygame.display.get_wm_info()["window"]
        
        # 设置扩展窗口样式
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd, 
            win32con.GWL_EXSTYLE, 
            ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW
        )
        
        # 设置透明颜色
        user32 = windll.user32

        def RGB(r, g, b):
            return r | (g << 8) | (b << 16)

        user32.SetLayeredWindowAttributes(hwnd, RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
        
        # 明确设置窗口大小和位置到完整屏幕
        win32gui.SetWindowPos(
            hwnd, 
            win32con.HWND_TOPMOST, 
            0, 0, screen_width, screen_height,
            win32con.SWP_SHOWWINDOW
        )
        
        # 验证窗口位置和大小
        rect = win32gui.GetWindowRect(hwnd)
        print(f"闪光窗口位置和大小: 左={rect[0]}, 上={rect[1]}, 右={rect[2]}, 下={rect[3]}")
        print(f"闪光窗口实际尺寸: 宽={rect[2]-rect[0]}, 高={rect[3]-rect[1]}")
        
        self.is_running = True
        print("闪光效果窗口初始化完成")
        
    def load_image(self, image_path):
        """加载闪光图片，强制控制尺寸"""
        print(f"尝试加载图片: {image_path}")
        
        if image_path == "none":
            self.flash_image = None
            print("图片样式设置为'none'，不加载图片")
            return
            
        if os.path.exists(image_path):
            try:
                # 确保pygame已初始化
                if not pygame.get_init():
                    pygame.init()
                    
                # 原始加载
                original_image = pygame.image.load(image_path)
                
                # 检查是否需要转换
                if original_image.get_alpha():
                    original_image = original_image.convert_alpha()
                else:
                    original_image = original_image.convert()
                    
                # 获取原始尺寸
                orig_width, orig_height = original_image.get_size()
                print(f"原始图片尺寸: {orig_width}x{orig_height}")
                
                # 存储原始图片和尺寸
                self.original_image = original_image
                self.original_image_size = (orig_width, orig_height)
                
                # 在EXE环境中应用尺寸修正
                if getattr(sys, 'frozen', False):
                    # 缩放系数(这个值需要根据测试确定)
                    scale_factor = 0.75  # 减小图片尺寸25%
                    scaled_width = int(orig_width * scale_factor)
                    scaled_height = int(orig_height * scale_factor)
                    
                    # 缩放图片
                    self.flash_image = pygame.transform.smoothscale(
                        original_image, (scaled_width, scaled_height))
                    
                    print(f"EXE环境: 应用图片缩放 {scale_factor}, 新尺寸: {scaled_width}x{scaled_height}")
                else:
                    # Python环境中使用原始尺寸
                    self.flash_image = original_image
                    
                img_size = self.flash_image.get_size()
                print(f"最终使用图片尺寸: {img_size[0]}x{img_size[1]}")
                    
            except Exception as e:
                print(f"图片加载出错: {e}")
                import traceback
                traceback.print_exc()
                self.flash_image = None
        else:
            print(f"图片文件不存在: {image_path}")
            self.flash_image = None
            
    def update_flash_value(self, value):
        """更新闪光值，直接设置不透明度"""
        # 保存原始值
        self.flash_value = value
        
        # 特殊处理小值 - 关键修复
        if value > 0 and value < 20:  # CS:GO实际闪光值范围通常是1-20
            # 给小值赋予较大的基础不透明度
            # 闪光值为1时基础不透明度为0.6
            # 闪光值为20时不透明度为0.9
            normalized_value = 0.6 + (value / 20.0) * 0.3
            print(f"应用小值加强: 原始值={value}, 归一化后={normalized_value:.2f}")
        else:
            # 标准归一化处理
            normalized_value = float(min(255, max(0, value))) / 255.0
        
        # 直接设置当前不透明度
        self.current_opacity = normalized_value * self.max_opacity
        
        print(f"更新闪光值: {value}, 归一化值: {normalized_value:.2f}, 不透明度: {self.current_opacity:.2f}")
        
        # 强制重绘
        self.needs_redraw = True
            
    def update_settings(self, settings):
        """更新设置"""
        if "bg_color" in settings:
            self.bg_color = settings["bg_color"]
        if "max_opacity" in settings:
            self.max_opacity = settings["max_opacity"]
        if "image_opacity" in settings:
            self.image_opacity = settings["image_opacity"]
            # 更新图片透明度时强制重绘
            self.needs_redraw = True
        if "image_position" in settings:
            self.image_position = settings["image_position"]
            # 更新图片位置时强制重绘
            self.needs_redraw = True
        if "image_size" in settings:
            self.image_size = settings["image_size"]
            # 更新图片大小时强制重绘
            self.needs_redraw = True
            
        print(f"更新设置: 背景={self.bg_color}, 背景不透明度={self.max_opacity:.2f}, 图片不透明度={self.image_opacity:.2f}")
    
    def update_style(self, style):
        """更新闪光样式"""
        self.flash_style = style
        print(f"闪光样式已更新: {style}")
        self.needs_redraw = True
    
    def update_style_parameters(self, parameters):
        """更新样式参数"""
        if "pulse_speed" in parameters:
            self.pulse_speed = parameters["pulse_speed"]
        if "pulse_intensity" in parameters:
            self.pulse_intensity = parameters["pulse_intensity"]
        if "blur_factor" in parameters:
            self.blur_factor = parameters["blur_factor"]
        if "blur_layers" in parameters:
            self.blur_layers = parameters["blur_layers"]
        if "halo_intensity" in parameters:
            self.halo_intensity = parameters["halo_intensity"]
        if "halo_size" in parameters:
            self.halo_size = parameters["halo_size"]
        if "color_cycle_speed" in parameters:
            self.color_cycle_speed = parameters["color_cycle_speed"]
        if "color_intensity" in parameters:
            self.color_intensity = parameters["color_intensity"]
        if "wave_speed" in parameters:
            self.wave_speed = parameters["wave_speed"]
        if "wave_count" in parameters:
            self.wave_count = parameters["wave_count"]
        if "wave_thickness" in parameters:
            self.wave_thickness = parameters["wave_thickness"]
        if "flicker_speed" in parameters:
            self.flicker_speed = parameters["flicker_speed"]
        if "flicker_randomness" in parameters:
            self.flicker_randomness = parameters["flicker_randomness"]
        if "rotation_speed" in parameters:
            self.rotation_speed = parameters["rotation_speed"]
        if "ray_count" in parameters:
            self.ray_count = parameters["ray_count"]
        if "particle_count" in parameters:
            self.particle_count = parameters["particle_count"]
        if "particle_size_range" in parameters:
            self.particle_size_range = parameters["particle_size_range"]
        
        self.needs_redraw = True
        print("闪光样式参数已更新")
    
    def main_loop(self):
        """主循环"""
        clock = pygame.time.Clock()
        self.needs_redraw = True
        
        # 帧率控制变量
        base_fps = 30       # 默认帧率
        active_fps = 120    # 闪光活跃时帧率
        transition_fps = 120 # 过渡期间帧率
        current_fps = base_fps
        
        # 添加淡入淡出控制
        self.is_fading_in = False
        self.is_fading_out = False
        self.fade_start_time = 0
        self.fade_in_duration = 0.3  # 300ms淡入
        self.fade_out_duration = 0.2  # 200ms淡出
        
        # 添加闪光稳定期检测
        stable_flash_time = 0
        stable_threshold = 0.5  # 闪光稳定0.5秒后降低帧率
        
        # 清理检查计时器
        last_cleanup_check = time.time()
        cleanup_interval = 0.5  # 每0.5秒执行一次清理检查
        
        # 闪光值历史记录
        last_flash_value = self.flash_value
        
        while self.is_running:
            current_time = time.time()
            
            # 检测闪光值变化
            if self.flash_value != last_flash_value:
                # 闪光开始 - 从0变为非0
                if last_flash_value == 0 and self.flash_value > 0:
                    self.is_fading_in = True
                    self.is_fading_out = False
                    self.fade_start_time = current_time
                    current_fps = transition_fps
                    print("开始淡入效果")
                
                # 闪光结束 - 从非0变为0
                elif last_flash_value > 0 and self.flash_value == 0:
                    self.is_fading_in = False
                    self.is_fading_out = True
                    self.fade_start_time = current_time
                    current_fps = transition_fps
                    print("开始淡出效果")
                
                # 普通闪光值变化 - 重置稳定计时
                else:
                    stable_flash_time = current_time
                    current_fps = active_fps
                
                # 标记需要重绘
                self.needs_redraw = True
                
                # 更新上一个闪光值
                last_flash_value = self.flash_value
            
            # 处理淡入淡出效果
            actual_opacity = self.current_opacity
            if self.is_fading_in and self.fade_in_enabled:
                # 计算淡入进度 (0.0 到 1.0)
                fade_progress = min(1.0, (current_time - self.fade_start_time) / self.fade_in_duration)
                # 应用渐进不透明度
                target_opacity = self.current_opacity
                actual_opacity = target_opacity * fade_progress
                
                self.needs_redraw = True
                
                # 淡入完成
                if fade_progress >= 1.0:
                    self.is_fading_in = False
                    stable_flash_time = current_time
                    
            elif self.is_fading_out and self.fade_out_enabled:
                # 计算淡出进度 (0.0 到 1.0)
                fade_progress = min(1.0, (current_time - self.fade_start_time) / self.fade_out_duration)
                # 应用渐退不透明度
                start_opacity = self.current_opacity
                actual_opacity = start_opacity * (1.0 - fade_progress)
                
                self.needs_redraw = True
                
                # 淡出完成
                if fade_progress >= 1.0:
                    self.is_fading_out = False
                    # 强制清除
                    self.overlay_win.fill((0, 0, 0, 0))
                    pygame.display.flip()
                    actual_opacity = 0
                    self.needs_redraw = False
            
            # 检测闪光稳定期 - 如果闪光值稳定一段时间，降低帧率节省资源
            if self.flash_value > 0 and not self.is_fading_in and not self.is_fading_out:
                if current_time - stable_flash_time > stable_threshold:
                    # 闪光已稳定，降低帧率至60fps
                    current_fps = 60
            
            # 周期性清理检查 - 即使没有GSI更新也能确保清理
            if current_time - last_cleanup_check > cleanup_interval:
                # 如果闪光值为0但屏幕可能仍有内容，强制清理
                if self.flash_value == 0 and not self.is_fading_out:
                    # 强制清屏并更新
                    self.overlay_win.fill((0, 0, 0, 0))
                    pygame.display.flip()
                    # 删除了此处的调试输出
                last_cleanup_check = current_time
            
            # 处理事件
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.is_running = False
            
            # 决定是否需要重绘
            if self.needs_redraw or self.flash_value > 0 or self.is_fading_out:
                # 清屏
                self.overlay_win.fill((0, 0, 0, 0))
                
                # 只有闪光值大于0或正在淡出时才渲染内容
                if self.flash_value > 0 or self.is_fading_out:
                    # 确定实际使用的不透明度
                    render_opacity = actual_opacity
                    
                    # 1. 渲染背景 - 仅当背景透明度大于0时
                    if render_opacity > 0.01:
                        # 根据设置的颜色渲染背景
                        if self.bg_color == "white":
                            bg_color = (255, 255, 255, int(render_opacity * 255))
                        elif self.bg_color == "black":
                            bg_color = (0, 0, 0, int(render_opacity * 255))
                        elif self.bg_color == "red":
                            bg_color = (255, 0, 0, int(render_opacity * 255))
                        elif self.bg_color == "green":
                            bg_color = (0, 255, 0, int(render_opacity * 255))
                        elif self.bg_color == "blue":
                            bg_color = (0, 0, 255, int(render_opacity * 255))
                        elif self.bg_color == "yellow":
                            bg_color = (255, 255, 0, int(render_opacity * 255))
                        elif self.bg_color == "cyan":
                            bg_color = (0, 255, 255, int(render_opacity * 255))
                        elif self.bg_color == "magenta":
                            bg_color = (255, 0, 255, int(render_opacity * 255))
                        elif self.bg_color == "orange":
                            bg_color = (255, 165, 0, int(render_opacity * 255))
                        else:
                            # 默认白色
                            bg_color = (255, 255, 255, int(render_opacity * 255))
                        
                        # 创建背景表面
                        bg_surface = self._scratch_surface("bg")
                        bg_surface.fill(bg_color)
                        self.overlay_win.blit(bg_surface, (0, 0))
                    
                    # 2. 渲染图片 - 独立于背景，仅依赖图片自身透明度设置
                    self._render_flash_image(render_opacity)
                    
                    # 3. 应用特殊效果 - 基于当前闪光风格
                    self._apply_flash_style_effects(render_opacity)
                
                # 更新显示
                pygame.display.flip()
                self.needs_redraw = False
            
            # 闪光值为0且非过渡状态时，可以使用更低帧率
            if self.flash_value == 0 and not self.is_fading_out and not self.is_fading_in:
                current_fps = base_fps
                # 如果长时间无闪光，可进一步降低帧率
                if current_time - last_cleanup_check > 5.0:
                    current_fps = 15
            
            # 应用当前帧率
            clock.tick(current_fps)

        # ==================== 退出清理（UP-007）====================
        # pygame.quit() 必须由主循环自己在退出后调用，绝不能让命令线程代劳——
        # 那样会在主循环还在渲染时把 SDL 显示拆掉，进程挂住不退。
        # 这里已经跳出 while，不会再有任何渲染调用，销毁是安全的。
        try:
            pygame.quit()
        except Exception:
            pass
    
    def _render_flash_image(self, opacity):
        """渲染闪光图片，针对不同环境使用不同的定位逻辑"""
        if self.flash_image is not None and self.image_opacity > 0.01:
            try:
                # 获取图片尺寸
                img_width, img_height = self.flash_image.get_size()
                
                # 位置计算 - 针对不同环境调整
                if self.is_exe:
                    # EXE环境的位置计算
                    # 对于居中位置(0.5左右)，强制使用屏幕中心
                    if (abs(self.image_position[0] - 0.5) < 0.05 and 
                        abs(self.image_position[1] - 0.5) < 0.05):
                        # 强制居中
                        img_x = (self.screen_width - img_width) // 2
                        img_y = (self.screen_height - img_height) // 2
                        print(f"EXE环境: 图片强制居中 ({img_x}, {img_y})")
                    else:
                        # 非中心位置使用校正后的比例计算
                        # 校正系数(需要根据测试调整)
                        x_correction = 0.7  # 位置校正比例
                        y_correction = 0.7
                        
                        # 对原始比例进行调整
                        x_ratio = self.image_position[0]
                        y_ratio = self.image_position[1]
                        
                        # 从0.5为基准进行放射状校正
                        adjusted_x = 0.5 + (x_ratio - 0.5) * x_correction
                        adjusted_y = 0.5 + (y_ratio - 0.5) * y_correction
                        
                        # 计算位置
                        img_x = int(self.screen_width * adjusted_x - img_width / 2)
                        img_y = int(self.screen_height * adjusted_y - img_height / 2)
                        
                        print(f"EXE环境: 图片校正位置 原始=({x_ratio:.2f},{y_ratio:.2f}), " 
                              f"校正后=({adjusted_x:.2f},{adjusted_y:.2f}), 像素=({img_x},{img_y})")
                else:
                    # Python环境的标准计算
                    img_x = int(self.screen_width * self.image_position[0] - img_width / 2)
                    img_y = int(self.screen_height * self.image_position[1] - img_height / 2)
                    print(f"Python环境: 图片位置 ({img_x}, {img_y})")
                
                # 确保图片在屏幕内
                img_x = max(0, min(img_x, self.screen_width - img_width))
                img_y = max(0, min(img_y, self.screen_height - img_height))
                
                # 创建临时副本以设置透明度(不影响原始图片)
                image_copy = self.flash_image.copy()

                # 设置图片透明度 - 考虑整体闪光不透明度
                img_alpha = int(255 * self.image_opacity * (opacity / self.max_opacity))
                image_copy.set_alpha(img_alpha)
                
                # 绘制图片
                self.overlay_win.blit(image_copy, (img_x, img_y))
            except Exception as e:
                print(f"绘制图片失败: {e}")
                import traceback
                traceback.print_exc()
    
    def _scratch_surface(self, key: str):
        """取一块可复用的全屏透明画布（UP-012）。

        原先每帧都 `pygame.Surface((w, h), SRCALPHA)` 新建：2560×1440×4 ≈ 14.7MB，
        120fps 下就是约 1.7GB/s 的分配/回收 churn——闪光弹炸开的那一瞬间正好掉帧，
        而那恰恰是最不能掉帧的时刻。

        现在按 key 缓存并复用，每次只 fill 清空（memset），省掉 malloc/free 与
        随之而来的缺页。分辨率变化时自动重建。

        key 按用途分开：主循环的背景层与风格效果层在同一帧里先后使用，
        虽然当前代码里背景层 blit 完才轮到风格层（共用一块也安全），
        但分开更经得起后续改动。
        """
        cache = getattr(self, "_scratch_cache", None)
        if cache is None:
            cache = self._scratch_cache = {}
        size = (self.screen_width, self.screen_height)
        surf = cache.get(key)
        if surf is None or surf.get_size() != size:
            surf = pygame.Surface(size, pygame.SRCALPHA)
            cache[key] = surf
        # 必须清空：blur/halo/spiral 等分支是"往上画图形"而不是整面 fill，
        # 不清的话会残留上一帧的内容。
        surf.fill((0, 0, 0, 0))
        return surf

    def _apply_flash_style_effects(self, opacity):
        """应用特殊闪光样式效果"""
        # 获取当前时间用于动画效果
        current_time = time.time()
        
        # 根据当前样式应用效果
        if self.flash_style == "standard":
            # 标准样式 - 不需要额外效果
            pass
        
        elif self.flash_style == "pulse":
            # 脉冲效果 - 添加轻微闪烁
            try:
                pulse_factor = self.pulse_intensity
                pulse_speed = self.pulse_speed
                
                # 使用正弦波创建脉动效果
                pulse = math.sin(current_time * pulse_speed) * pulse_factor + 1.0
                
                # 重要修复：使用乘法而不是替换原始不透明度
                # 不影响原始背景，只增加亮度
                pulse_surface = self._scratch_surface("pulse")
                
                # 使用更适合的透明度值 - 调整为合理范围
                pulse_alpha = int(min(80, pulse * 60))
                pulse_surface.fill((255, 255, 255, pulse_alpha))
                
                # 使用BLEND_RGBA_ADD混合模式增加亮度而不是覆盖
                self.overlay_win.blit(pulse_surface, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
                
                print(f"应用脉冲效果: 强度={pulse_factor:.2f}, 速度={pulse_speed:.2f}, 波值={pulse:.2f}")
            except Exception as e:
                print(f"应用脉冲效果出错: {e}")
        
        elif self.flash_style == "blur":
            # 边缘模糊效果 - 修复版本
            try:
                center_x = self.screen_width // 2
                center_y = self.screen_height // 2
                
                # 增加径向渐变的密度和可见度
                max_radius = int(max(self.screen_width, self.screen_height) * self.blur_factor)
                
                # 增加圈的数量，减小间距
                num_circles = 15  # 原来是self.blur_layers (通常为5)
                step = max_radius // num_circles
                
                # 确保最小步长
                step = max(step, 10)
                
                # 创建渐变表面
                blur_surface = self._scratch_surface("blur")
                
                # 先绘制一个基础白色圆形在核心区域
                base_radius = int(max_radius * 0.3)
                base_alpha = int(opacity * 100)
                pygame.draw.circle(
                    blur_surface,
                    (255, 255, 255, base_alpha),
                    (center_x, center_y),
                    base_radius,
                    0  # 填充圆
                )
                
                # 再绘制渐变圆环
                for i in range(num_circles):
                    radius = base_radius + step * (i + 1)
                    # 从中心到边缘逐渐减小不透明度
                    fade_factor = i / float(num_circles)
                    # 提高透明度值使效果更明显
                    circle_alpha = int((1.0 - fade_factor) * opacity * 80)
                    
                    if circle_alpha <= 0:
                        continue
                        
                    # 增加圆环宽度，使其更可见
                    ring_width = max(5, int(10 * (1.0 - fade_factor)))
                    
                    pygame.draw.circle(
                        blur_surface,
                        (255, 255, 255, circle_alpha),
                        (center_x, center_y),
                        radius,
                        ring_width  # 根据距离中心的距离动态调整宽度
                    )
                
                # 使用Alpha混合添加到主窗口
                self.overlay_win.blit(blur_surface, (0, 0))
                
                print(f"应用模糊效果: 因子={self.blur_factor:.2f}, 圈数={num_circles}")
            except Exception as e:
                print(f"应用模糊效果出错: {e}")
        
        elif self.flash_style == "halo":
            # 光晕效果 - 修复版本
            try:
                # 创建单独的光晕表面，而不是直接在主窗口绘制
                halo_surface = self._scratch_surface("halo")
                
                center_x = self.screen_width // 2
                center_y = self.screen_height // 2
                max_radius = int(max(self.screen_width, self.screen_height) * self.halo_size)
                
                # 增加渐变平滑度
                layers = 12  # 增加层数，使渐变更平滑
                
                # 先绘制中心实心圆
                core_radius = int(max_radius * 0.15)
                core_opacity = int(opacity * 180 * self.halo_intensity)
                
                pygame.draw.circle(
                    halo_surface,
                    (255, 255, 255, core_opacity),
                    (center_x, center_y),
                    core_radius,
                    0  # 填充圆
                )
                
                # 从中心向外绘制渐变光晕
                for i in range(layers):
                    # 计算当前层的半径，确保由内向外均匀分布
                    radius_factor = (i + 1) / float(layers)
                    radius = int(core_radius + (max_radius - core_radius) * radius_factor)
                    
                    # 计算当前层的不透明度，从中心向外衰减
                    fade_factor = radius_factor
                    halo_opacity = int((1.0 - fade_factor) * opacity * 180 * self.halo_intensity)
                    
                    if halo_opacity <= 0:
                        continue
                    
                    # 绘制当前层的圆，使用填充圆而不是圆环
                    pygame.draw.circle(
                        halo_surface,
                        (255, 255, 255, halo_opacity),
                        (center_x, center_y),
                        radius,
                        0  # 填充圆
                    )
                
                # 使用正常混合模式添加到主窗口，保留原始背景
                self.overlay_win.blit(halo_surface, (0, 0))
                
                print(f"应用光晕效果: 强度={self.halo_intensity:.2f}, 大小={self.halo_size:.2f}")
            except Exception as e:
                print(f"应用光晕效果出错: {e}")
        
        elif self.flash_style == "rainbow":
            # 彩虹色闪光效果
            try:
                # 使用HSV色彩空间循环
                hue = (current_time * self.color_cycle_speed) % 1.0
                
                # 将HSV转换为RGB
                h = hue * 6.0
                i = int(h)
                f = h - i
                q = 1 - f
                
                if i % 6 == 0:
                    r, g, b = 1, f, 0
                elif i % 6 == 1:
                    r, g, b = q, 1, 0
                elif i % 6 == 2:
                    r, g, b = 0, 1, f
                elif i % 6 == 3:
                    r, g, b = 0, q, 1
                elif i % 6 == 4:
                    r, g, b = f, 0, 1
                else:
                    r, g, b = 1, 0, q
                
                # 创建彩色叠加层
                color_surface = self._scratch_surface("color")
                
                # 调整为合适的透明度
                color_alpha = int(opacity * 100 * self.color_intensity)
                color = (int(r*255), int(g*255), int(b*255), color_alpha)
                color_surface.fill(color)
                
                # 使用适当的混合模式
                self.overlay_win.blit(color_surface, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
                
                print(f"应用彩虹效果: 颜色=({r:.2f},{g:.2f},{b:.2f}), 速度={self.color_cycle_speed:.2f}")
            except Exception as e:
                print(f"应用彩虹效果出错: {e}")
                
        elif self.flash_style == "wave":
            # 波纹效果
            try:
                center_x = self.screen_width // 2
                center_y = self.screen_height // 2
                
                # 创建波纹表面
                wave_surface = self._scratch_surface("wave")
                
                # 波纹参数
                wave_speed = self.wave_speed
                wave_count = self.wave_count
                wave_thickness = self.wave_thickness
                max_radius = max(self.screen_width, self.screen_height) * 0.8
                
                # 绘制多个波纹圆环
                for i in range(wave_count):
                    # 计算半径随时间变化
                    phase = (current_time * wave_speed + i / wave_count) % 1.0
                    radius = phase * max_radius
                    
                    # 随距离衰减透明度
                    alpha = int((1.0 - phase) * opacity * 100)
                    if alpha <= 0:
                        continue
                    
                    # 绘制波纹圆环
                    pygame.draw.circle(
                        wave_surface,
                        (255, 255, 255, alpha),
                        (center_x, center_y),
                        radius,
                        wave_thickness
                    )
                
                # 添加到主窗口
                self.overlay_win.blit(wave_surface, (0, 0))
                
                print(f"应用波纹效果: 速度={wave_speed:.2f}, 数量={wave_count}")
            except Exception as e:
                print(f"应用波纹效果出错: {e}")
                
        elif self.flash_style == "flicker":
            # 闪烁效果
            try:
                # 创建闪烁表面
                flicker_surface = self._scratch_surface("flicker")
                
                # 闪烁参数
                flicker_speed = self.flicker_speed
                flicker_randomness = self.flicker_randomness
                
                # 计算当前闪烁状态 - 使用正弦和随机值组合
                base_flicker = (math.sin(current_time * flicker_speed) + 1) / 2
                random_factor = random.random() * flicker_randomness
                flicker_value = min(1.0, max(0.0, base_flicker + random_factor - flicker_randomness/2))
                
                # 计算闪烁透明度
                flicker_alpha = int(flicker_value * opacity * 255)
                
                # 绘制闪烁效果
                flicker_surface.fill((255, 255, 255, flicker_alpha))
                
                # 添加到主窗口
                self.overlay_win.blit(flicker_surface, (0, 0))
                
                print(f"应用闪烁效果: 速度={flicker_speed:.2f}, 随机度={flicker_randomness:.2f}")
            except Exception as e:
                print(f"应用闪烁效果出错: {e}")
                
        elif self.flash_style == "spiral":
            # 旋转光芒效果
            try:
                center_x = self.screen_width // 2
                center_y = self.screen_height // 2
                
                # 创建旋转表面
                spiral_surface = self._scratch_surface("spiral")
                
                # 旋转参数
                rotation_speed = self.rotation_speed
                ray_count = self.ray_count
                max_length = min(self.screen_width, self.screen_height) * 0.6
                
                # 计算基础旋转角度
                base_angle = current_time * rotation_speed * math.pi
                
                # 绘制光芒
                for i in range(ray_count):
                    angle = base_angle + (i * 2 * math.pi / ray_count)
                    
                    # 计算光芒端点
                    end_x = center_x + math.cos(angle) * max_length
                    end_y = center_y + math.sin(angle) * max_length
                    
                    # 绘制光芒线条
                    pygame.draw.line(
                        spiral_surface,
                        (255, 255, 255, int(opacity * 150)),
                        (center_x, center_y),
                        (end_x, end_y),
                        10  # 线宽
                    )
                
                # 添加到主窗口
                self.overlay_win.blit(spiral_surface, (0, 0))
                
                print(f"应用旋转效果: 速度={rotation_speed:.2f}, 光芒数={ray_count}")
            except Exception as e:
                print(f"应用旋转效果出错: {e}")
                
        elif self.flash_style == "particles":
            # 颗粒效果
            try:
                # 创建颗粒表面
                particles_surface = self._scratch_surface("particles")
                
                # 颗粒参数
                particle_count = self.particle_count
                particle_size_range = self.particle_size_range
                
                # 随机生成颗粒
                for _ in range(particle_count):
                    # 随机位置
                    x = random.randint(0, self.screen_width)
                    y = random.randint(0, self.screen_height)
                    
                    # 随机大小
                    size = random.randint(*particle_size_range)
                    
                    # 随机亮度
                    brightness = random.random() * 0.5 + 0.5  # 0.5-1.0
                    
                    # 计算不透明度
                    particle_alpha = int(brightness * opacity * 255)
                    
                    # 绘制颗粒
                    pygame.draw.circle(
                        particles_surface,
                        (255, 255, 255, particle_alpha),
                        (x, y),
                        size
                    )
                
                # 添加到主窗口
                self.overlay_win.blit(particles_surface, (0, 0))
                
                print(f"应用颗粒效果: 数量={particle_count}")
            except Exception as e:
                print(f"应用颗粒效果出错: {e}")
    
    def shutdown(self):
        """请求关闭进程（UP-007）。

        ⚠️ 这个方法跑在**命令线程**上，绝不能在这里调 pygame.quit()。
        原先就是这么写的，后果是：命令线程销毁 SDL 显示时，主循环很可能正卡在
        display.flip() / blit 中途，SDL 资源被并发拆掉，子进程于是挂住不退——
        父进程等 2 秒超时后只能 terminate()，表现为用户点 X 之后界面冻约 3 秒
        （实测 21/38 次退出触发慢步骤告警，中位 2.43s）。

        正确做法：这里只置标志，pygame.quit() 交给主循环自己在退出后做。
        """
        self.is_running = False


#: 每积累这么多次「队列空」就查一次父进程还在不在。
#: 0.05s 超时 × 20 ≈ 1 秒查一次，父进程被强杀后约 1s 内本进程自行退出。
_PARENT_CHECK_EVERY_EMPTIES = 20


def process_commands(command_queue, flash_effect):
    """处理命令队列 - 增强版

    ⚠ QA-002：**父进程被强杀时，队列不会断，异常也不会抛。**
    下面那个 `except (EOFError, BrokenPipeError, OSError)` 守卫是 2.2.1 专门为
    「父进程崩了别留下全屏罩」加的，但它**永远不触发** —— 实测强杀父进程后，
    子进程连续 44 秒全是 `queue.Empty`，一次管道异常都没有。
    原因：multiprocessing 的 Queue 在读端看不到写端消失，`get(timeout=)` 只会超时。

    后果是真的：本进程 `daemon=True`，靠父进程 atexit 收尸；父进程被 TerminateProcess
    杀掉时 atexit 不跑，于是本进程变孤儿，按最后一帧继续渲染 ——
    如果那一帧正好是「被闪中」，用户屏幕上会永久留一层全屏白罩，
    **重启软件也清不掉**（清屏命令发给的是新起的子进程，老的那个还在画）。

    正解是主动查父进程：spawn 时父进程句柄被复制进子进程当 sentinel，
    父进程被强杀时该句柄同样会 signaled，所以 `parent_process().is_alive()` 会翻 False。
    实测强杀后约 1 秒内检出并自行退出。
    """
    import multiprocessing as _mp

    try:
        _parent = _mp.parent_process()
    except Exception:
        _parent = None      # 非 spawn/fork 场景（例如直接跑本模块）拿不到，跳过检测
    _empty_streak = 0

    while flash_effect.is_running:
        try:
            # 阻塞等待命令，有命令立刻响应，无命令不耗CPU
            command = command_queue.get(timeout=0.05)
            _empty_streak = 0

            # 处理强制清除命令 - 最高优先级
            if command.get("type") == "force_clear":
                print("收到强制清除命令")
                flash_effect.flash_value = 0
                flash_effect.current_opacity = 0
                flash_effect.needs_redraw = True
                flash_effect.overlay_win.fill((0, 0, 0, 0))
                pygame.display.flip()
                flash_effect.overlay_win.fill((0, 0, 0, 0))
                pygame.display.flip()
                print("闪光效果已强制清除")

            # 闪光值更新命令，高优先级处理
            elif command.get("type") == "update_flash":
                flash_value = command.get("value", 0)

                if flash_value > 0 and flash_effect.flash_value == 0:
                    flash_effect.is_fading_in = True
                    flash_effect.is_fading_out = False
                    flash_effect.fade_start_time = time.time()
                    print("开始淡入效果")
                elif flash_value == 0 and flash_effect.flash_value > 0:
                    flash_effect.is_fading_in = False
                    flash_effect.is_fading_out = True
                    flash_effect.fade_start_time = time.time()
                    print("开始淡出效果")

                flash_effect.update_flash_value(flash_value)

                if flash_value == 0 and not flash_effect.is_fading_out:
                    flash_effect.overlay_win.fill((0, 0, 0, 0))
                    pygame.display.flip()
                    print("闪光效果已清除(值为0)")

            elif command.get("type") == "update_style":
                style = command.get("style", "standard")
                flash_effect.update_style(style)
                print(f"闪光样式已更新: {style}")

            elif command.get("type") == "update_style_parameters":
                parameters = command.get("parameters", {})
                flash_effect.update_style_parameters(parameters)
                print("样式参数已更新")

            elif command.get("type") == "update_fade_settings":
                settings = command.get("settings", {})
                if "fade_in_enabled" in settings:
                    flash_effect.fade_in_enabled = settings["fade_in_enabled"]
                if "fade_out_enabled" in settings:
                    flash_effect.fade_out_enabled = settings["fade_out_enabled"]
                print(f"淡入淡出设置已更新: 淡入={flash_effect.fade_in_enabled}, 淡出={flash_effect.fade_out_enabled}")

            elif command.get("type") == "update_image_rotation":
                mode = command.get("mode", "none")
                print(f"收到图片轮换模式更新: {mode}")

            elif command.get("type") == "update_settings":
                flash_effect.update_settings(command.get("settings", {}))
            elif command.get("type") == "load_image":
                flash_effect.load_image(command.get("path", ""))
            elif command.get("type") == "shutdown":
                flash_effect.shutdown()
                return
        except queue.Empty:
            # QA-002: 父进程存活检测挂在这里 —— 队列空是常态（几乎每一拍都空），
            # 所以这是唯一能稳定拿到执行机会的位置。
            _empty_streak += 1
            if _empty_streak >= _PARENT_CHECK_EVERY_EMPTIES:
                _empty_streak = 0
                if _parent is not None and not _parent.is_alive():
                    print("父进程已退出（存活检测），关闭闪光进程，避免留下全屏覆盖层")
                    flash_effect.shutdown()
                    return
            continue
        except (EOFError, BrokenPipeError, OSError) as e:
            # ⚠ 这条**不是**父进程崩溃检测（实测强杀父进程时它永远不触发，见函数 docstring）。
            # 留着只为兜住真正的队列 IO 异常（句柄被关、系统资源异常等）。
            # 别再把它当成「已经防住孤儿进程了」—— 防孤儿的是上面那段存活检测。
            print(f"命令队列 IO 异常，关闭闪光进程: {e}")
            flash_effect.shutdown()
            return
        except Exception as e:
            print(f"处理命令异常: {e}")


def process_function(command_queue, screen_width, screen_height):
    """闪光效果进程的主函数"""
    try:
        flash_effect = FlashEffectProcess()
        flash_effect.initialize(screen_width, screen_height)
        
        # 启动命令处理线程
        command_thread = threading.Thread(
            target=process_commands,
            args=(command_queue, flash_effect),
            daemon=True,
            name="FlashCommand"
        )
        command_thread.start()
        
        # 运行主循环
        flash_effect.main_loop()
        
    except Exception as e:
        print(f"闪光效果进程出错: {e}")
        import traceback
        traceback.print_exc()


# 当作为独立程序运行时
if __name__ == "__main__":
    # 从命令行参数获取屏幕尺寸
    if len(sys.argv) >= 3:
        width = int(sys.argv[1])
        height = int(sys.argv[2])
        
        # 创建命令队列
        from multiprocessing import Queue
        queue = Queue()
        
        # 启动进程
        process_function(queue, width, height)
    else:
        print("需要屏幕宽度和高度参数")