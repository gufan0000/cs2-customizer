import pygame
import os
import queue as _queue
import time
from multiprocessing import Queue, Process
from config import config
from resource_manager import ResourceManager
from utility_usage_tracker import get_usage_tracker
import ctypes

# DPI感知设置
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


class UtilityDisplayWorker:
    """道具显示工作器（在独立进程中运行）"""
    def __init__(self, command_queue, status_queue):
        self.command_queue = command_queue
        self.status_queue = status_queue
        self.pygame_initialized = False
        self.screen = None
        self.clock = None
        self.running = True
        
        # 窗口设置
        self.window_width = 400
        self.window_height = 200
        self.window_x = -10000  # 初始位置在屏幕外
        self.window_y = -10000  # 初始位置在屏幕外
        self.window_visible = False
        self.hwnd = None
        
        # 屏幕尺寸缓存
        self.screen_width = 0
        self.screen_height = 0
        
        # 图片设置
        self.current_images = {}  # {'站位': surface, '瞄准': surface}
        self.image_scale = 1.0
        self.image_opacity = 255
        self.offset_x = 0
        self.offset_y = 0
        
        # 菜单设置
        self.menu_visible = False
        self.menu_items = []
        self.current_menu_level = 0  # 0=位置选择, 1=道具选择
        self.selected_location = None
        self.menu_font = None
        self.menu_opacity = 200
        
        print("[UtilityWorker] 工作器初始化完成")
    
    def init_pygame(self):
        """初始化pygame窗口"""
        try:
            print("[UtilityWorker] 开始初始化pygame...")
            
            # 确保pygame完全清理
            if self.pygame_initialized:
                pygame.quit()
                self.pygame_initialized = False
                time.sleep(0.1)
            
            # 初始化pygame
            pygame.init()
            pygame.display.init()
            
            # 创建一个小的初始窗口（隐藏在屏幕外）
            os.environ['SDL_VIDEO_WINDOW_POS'] = '-10000,-10000'
            
            # 创建窗口
            self.screen = pygame.display.set_mode(
                (100, 100),
                pygame.NOFRAME | pygame.DOUBLEBUF
            )
            pygame.display.set_caption("Utility Guide")
            
            # Windows特定设置
            try:
                import platform
                if platform.system() == "Windows":
                    import win32api  # noqa: F401  可用性探测：缺包则整组功能降级
                    import win32con
                    import win32gui
                    
                    self.hwnd = pygame.display.get_wm_info()["window"]
                    print(f"[UtilityWorker] 获取窗口句柄: {self.hwnd}")
                    
                    # 设置窗口属性
                    ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                    ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
                    ex_style &= ~win32con.WS_EX_APPWINDOW
                    win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
                    
                    # 不设置透明色键，改用alpha通道
                    # win32gui.SetLayeredWindowAttributes(self.hwnd, win32api.RGB(1, 1, 1), 0, win32con.LWA_COLORKEY)
                    
                    # 设置窗口透明度
                    win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 250, win32con.LWA_ALPHA)
                    
                    # 初始位置在屏幕外
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                        -10000, -10000, 0, 0,
                        win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                    
                    print("[UtilityWorker] Windows窗口属性设置完成")
            except ImportError as e:
                print(f"[UtilityWorker] Win32 API不可用，使用默认窗口: {e}")
            except Exception as e:
                print(f"[UtilityWorker] 设置Windows窗口属性失败: {e}")
            
            # 初始化字体
            try:
                # 尝试加载中文字体
                font_paths = [
                    "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
                    "C:/Windows/Fonts/simhei.ttf",  # 黑体
                    "C:/Windows/Fonts/simsun.ttc",  # 宋体
                ]
                font_loaded = False
                for font_path in font_paths:
                    if os.path.exists(font_path):
                        self.menu_font = pygame.font.Font(font_path, 24)
                        font_loaded = True
                        print(f"[UtilityWorker] 加载字体: {font_path}")
                        break
                
                if not font_loaded:
                    self.menu_font = pygame.font.Font(None, 36)
                    print("[UtilityWorker] 使用默认字体")
            except Exception:
                self.menu_font = pygame.font.Font(None, 36)
                print("[UtilityWorker] 字体加载失败，使用默认字体")
            
            self.clock = pygame.time.Clock()
            self.pygame_initialized = True
            
            # 清空初始窗口（使用黑色背景）
            self.screen.fill((20, 20, 25))
            pygame.display.flip()
            
            print("[UtilityWorker] pygame初始化成功")
            return True
            
        except Exception as e:
            print(f"[UtilityWorker] 初始化pygame失败: {e}")
            import traceback
            traceback.print_exc()
            self.pygame_initialized = False
            return False
    
    def get_screen_size(self):
        """获取屏幕尺寸（缓存）"""
        if self.screen_width > 0 and self.screen_height > 0:
            return self.screen_width, self.screen_height
        
        # 尝试使用Windows API获取屏幕尺寸
        try:
            import win32api
            self.screen_width = win32api.GetSystemMetrics(0)
            self.screen_height = win32api.GetSystemMetrics(1)
            print(f"[UtilityWorker] 屏幕尺寸(win32): {self.screen_width}x{self.screen_height}")
        except Exception:
            # 使用默认值
            self.screen_width = 1920
            self.screen_height = 1080
            print(f"[UtilityWorker] 使用默认屏幕尺寸: {self.screen_width}x{self.screen_height}")
        
        return self.screen_width, self.screen_height
    
    def show_menu(self, menu_items, level=0):
        """显示菜单"""
        print(f"[UtilityWorker] 显示菜单，项目: {menu_items}, 级别: {level}")
        
        if not self.pygame_initialized:
            if not self.init_pygame():
                print("[UtilityWorker] pygame初始化失败，无法显示菜单")
                return
        
        if not menu_items:
            print("[UtilityWorker] 菜单项为空，无法显示")
            return
        
        self.menu_items = menu_items
        self.current_menu_level = level
        self.menu_visible = True
        
        # 获取屏幕尺寸（使用缓存）
        screen_width, screen_height = self.get_screen_size()
        
        # 计算菜单大小 - 增加高度
        menu_width = 450
        menu_height = 90 + len(menu_items) * 50 + 40  # 标题(90) + 每项(50) + 底部提示(40)
        
        self.window_x = (screen_width - menu_width) // 2
        self.window_y = (screen_height - menu_height) // 2
        self.window_width = menu_width
        self.window_height = menu_height
        
        print(f"[UtilityWorker] 菜单窗口位置: {self.window_x}, {self.window_y}, 大小: {menu_width}x{menu_height}")
        
        # 设置窗口位置和大小
        if self.hwnd:
            try:
                import win32gui
                import win32con
                
                # 移动并调整窗口大小
                win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST,
                    self.window_x, self.window_y,
                    self.window_width, self.window_height,
                    win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
                
                # 如果pygame窗口大小不匹配，重新创建
                if self.screen.get_width() != self.window_width or self.screen.get_height() != self.window_height:
                    os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
                    self.screen = pygame.display.set_mode(
                        (self.window_width, self.window_height),
                        pygame.NOFRAME | pygame.DOUBLEBUF
                    )

                    # 与 show_utility_images 的重建路径对齐：SDL 重建可能换句柄，
                    # 不重取 hwnd/重设样式与置顶，菜单会丢置顶且 hide 操作旧死句柄
                    self.hwnd = pygame.display.get_wm_info()["window"]
                    ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                    ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
                    ex_style &= ~win32con.WS_EX_APPWINDOW
                    win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
                    win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 250, win32con.LWA_ALPHA)
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST,
                        self.window_x, self.window_y,
                        self.window_width, self.window_height,
                        win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)

                print("[UtilityWorker] 窗口已显示并置顶")
            except Exception as e:
                print(f"[UtilityWorker] 设置窗口位置失败: {e}")
        else:
            # 如果没有hwnd，重新创建窗口
            os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
            self.screen = pygame.display.set_mode(
                (self.window_width, self.window_height),
                pygame.NOFRAME | pygame.DOUBLEBUF
            )
        
        self.window_visible = True
        
        # 立即渲染菜单
        self.render_menu()
        
        # 强制更新显示
        pygame.display.flip()
    
    def render_menu(self):
        """渲染菜单"""
        if not self.menu_visible or not self.pygame_initialized:
            return
        
        print("[UtilityWorker] 渲染菜单...")
        
        try:
            # 使用深色背景
            self.screen.fill((20, 20, 25))
            
            # 绘制标题背景
            title_bg = pygame.Rect(0, 0, self.window_width, 50)
            pygame.draw.rect(self.screen, (30, 30, 35), title_bg)
            
            # 绘制标题
            if self.current_menu_level == 0:
                title = "选择投掷位置:"
            else:
                title = f"位置: {self.selected_location}"
            
            title_surface = self.menu_font.render(title, True, (255, 255, 255))
            title_rect = title_surface.get_rect(centerx=self.window_width//2, centery=25)
            self.screen.blit(title_surface, title_rect)
            
            # 绘制分割线
            pygame.draw.line(self.screen, (60, 60, 70), (10, 50), (self.window_width-10, 50), 2)
            
            # 绘制菜单项
            y_offset = 65
            for i, item in enumerate(self.menu_items):
                # 绘制选项背景
                item_rect = pygame.Rect(15, y_offset - 5, self.window_width - 30, 40)
                pygame.draw.rect(self.screen, (35, 35, 45), item_rect, border_radius=5)
                pygame.draw.rect(self.screen, (55, 55, 65), item_rect, 1, border_radius=5)
                
                # 绘制数字标记
                num_surface = self.menu_font.render(f"[{i+1}]", True, (100, 200, 255))
                self.screen.blit(num_surface, (25, y_offset))
                
                # 绘制选项文字
                text_surface = self.menu_font.render(item, True, (220, 220, 220))
                self.screen.blit(text_surface, (90, y_offset))
                
                y_offset += 50
            
            # 绘制底部提示背景
            hint_bg = pygame.Rect(0, self.window_height - 40, self.window_width, 40)
            pygame.draw.rect(self.screen, (25, 25, 30), hint_bg)
            
            # 绘制提示
            if self.current_menu_level == 0:
                hint = "[ESC] 关闭"
            else:
                hint = "[0] 返回  [ESC] 关闭"
            hint_surface = self.menu_font.render(hint, True, (150, 150, 160))
            hint_rect = hint_surface.get_rect(centerx=self.window_width//2, centery=self.window_height-20)
            self.screen.blit(hint_surface, hint_rect)
            
            # 更新显示
            pygame.display.flip()
            print("[UtilityWorker] 菜单渲染完成")
            
        except Exception as e:
            print(f"[UtilityWorker] 渲染菜单失败: {e}")
            import traceback
            traceback.print_exc()
    
    def show_utility_images(self, stand_path, aim_path):
        """显示道具图片（站位+瞄准）"""
        print(f"[UtilityWorker] 显示道具图片: {stand_path}, {aim_path}")
        
        if not self.pygame_initialized:
            if not self.init_pygame():
                print("[UtilityWorker] pygame初始化失败，无法显示图片")
                return
        
        try:
            # 加载图片
            stand_img = pygame.image.load(stand_path).convert_alpha()
            aim_img = pygame.image.load(aim_path).convert_alpha()
            
            # 计算缩放后的尺寸
            base_width = 350
            base_height = 250
            scaled_width = int(base_width * self.image_scale)
            scaled_height = int(base_height * self.image_scale)
            
            # 缩放图片
            stand_img = pygame.transform.smoothscale(stand_img, (scaled_width, scaled_height))
            aim_img = pygame.transform.smoothscale(aim_img, (scaled_width, scaled_height))
            
            # 设置透明度
            stand_img.set_alpha(self.image_opacity)
            aim_img.set_alpha(self.image_opacity)
            
            self.current_images = {'站位': stand_img, '瞄准': aim_img}
            
            # 计算窗口大小（两张图片并排）
            self.window_width = scaled_width * 2 + 30
            self.window_height = scaled_height + 60
            
            # 获取屏幕尺寸（使用缓存）
            screen_width, screen_height = self.get_screen_size()
            
            # 计算窗口位置（屏幕右下角）
            self.window_x = screen_width - self.window_width - 100 + self.offset_x
            self.window_y = screen_height - self.window_height - 100 + self.offset_y
            
            # 确保窗口位置不是负数
            self.window_x = max(0, self.window_x)
            self.window_y = max(0, self.window_y)
            
            print(f"[UtilityWorker] 图片窗口位置: {self.window_x}, {self.window_y}, 大小: {self.window_width}x{self.window_height}")
            
            # 设置窗口位置和大小
            if self.hwnd:
                try:
                    import win32gui
                    import win32con
                    
                    # 移动并调整窗口大小
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST,
                        self.window_x, self.window_y,
                        self.window_width, self.window_height,
                        win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
                    
                    # 如果pygame窗口大小不匹配，重新创建
                    if self.screen.get_width() != self.window_width or self.screen.get_height() != self.window_height:
                        os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
                        self.screen = pygame.display.set_mode(
                            (self.window_width, self.window_height),
                            pygame.NOFRAME | pygame.DOUBLEBUF
                        )
                        
                        # 重新获取窗口句柄
                        self.hwnd = pygame.display.get_wm_info()["window"]
                        
                        # 重新设置窗口属性
                        ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                        ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
                        ex_style &= ~win32con.WS_EX_APPWINDOW
                        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
                        
                        # 设置窗口透明度
                        win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 250, win32con.LWA_ALPHA)
                        
                        # 再次设置位置确保正确
                        win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST,
                            self.window_x, self.window_y,
                            self.window_width, self.window_height,
                            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
                        
                except Exception as e:
                    print(f"[UtilityWorker] 设置图片窗口位置失败: {e}")
            else:
                # 如果没有hwnd，重新创建窗口
                os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
                self.screen = pygame.display.set_mode(
                    (self.window_width, self.window_height),
                    pygame.NOFRAME | pygame.DOUBLEBUF
                )
            
            self.window_visible = True
            self.menu_visible = False
            self.render_images()
            
            # 强制更新显示
            pygame.display.flip()
            
        except Exception as e:
            print(f"[UtilityWorker] 加载道具图片失败: {e}")
            import traceback
            traceback.print_exc()
    
    def render_images(self):
        """渲染道具图片"""
        if not self.window_visible or not self.current_images:
            return
        
        print("[UtilityWorker] 渲染道具图片...")
        
        try:
            # 填充背景
            self.screen.fill((20, 20, 25))
            
            # 绘制背景
            bg = pygame.Surface((self.window_width, self.window_height))
            bg.set_alpha(240)
            bg.fill((25, 25, 35))
            self.screen.blit(bg, (0, 0))
            
            # 绘制图片
            y_offset = 40
            if '站位' in self.current_images:
                self.screen.blit(self.current_images['站位'], (10, y_offset))
                # 绘制标签
                label = self.menu_font.render("站位", True, (255, 255, 255))
                label_rect = label.get_rect(centerx=10 + self.current_images['站位'].get_width()//2, y=10)
                self.screen.blit(label, label_rect)
            
            if '瞄准' in self.current_images:
                x_pos = self.current_images['站位'].get_width() + 20 if '站位' in self.current_images else 10
                self.screen.blit(self.current_images['瞄准'], (x_pos, y_offset))
                # 绘制标签
                label = self.menu_font.render("瞄准", True, (255, 255, 255))
                label_rect = label.get_rect(centerx=x_pos + self.current_images['瞄准'].get_width()//2, y=10)
                self.screen.blit(label, label_rect)
            
            pygame.display.flip()
            print("[UtilityWorker] 图片渲染完成")
            
        except Exception as e:
            print(f"[UtilityWorker] 渲染图片失败: {e}")
            import traceback
            traceback.print_exc()
    
    def hide_all(self):
        """隐藏所有窗口"""
        print("[UtilityWorker] 隐藏所有窗口")
        
        self.menu_visible = False
        self.window_visible = False
        self.current_images.clear()
        
        if self.pygame_initialized:
            # 清空屏幕（使用黑色背景）
            if self.screen:
                self.screen.fill((20, 20, 25))
                pygame.display.flip()
            
            # 真隐藏窗口：旧实现移动到 (-10000,-10000)，在存在左/上方
            # 副显示器的负坐标多屏布局里该点可能仍在可视区（隐藏失败留残窗）。
            # 各显示路径都带 SWP_SHOWWINDOW，可正常复显
            if self.hwnd:
                try:
                    import win32gui
                    import win32con
                    win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
                except Exception as e:
                    print(f"[UtilityWorker] 隐藏窗口失败: {e}")
    
    def run(self):
        """主循环"""
        print("[UtilityWorker] 工作器主循环启动")
        
        # 延迟初始化pygame，避免过早创建窗口
        self.status_queue.put(("initialized", True))
        
        while self.running:
            try:
                # UP-061: 原本 `if not empty(): get_nowait()` + `time.sleep(0.001)`
                # 空转轮询。下面虽有 clock.tick(10)，但那只在窗口**可见**时生效，
                # 而这个进程绝大多数时间窗口是隐藏的 —— 那段时间就是纯烧 CPU。
                # 改为阻塞等待：命令一到立刻返回，超时只决定多久醒一次泵事件。
                try:
                    cmd = self.command_queue.get(
                        timeout=0.05 if (self.pygame_initialized and self.window_visible) else 0.2
                    )
                except _queue.Empty:
                    cmd = None
                # 处理命令
                if cmd is not None:
                    print(f"[UtilityWorker] 收到命令: {cmd[0]}")
                    
                    if cmd[0] == "quit":
                        self.running = False
                        break
                    elif cmd[0] == "show_menu":
                        _, items, level = cmd
                        self.show_menu(items, level)
                    elif cmd[0] == "show_images":
                        _, stand_path, aim_path = cmd
                        self.show_utility_images(stand_path, aim_path)
                    elif cmd[0] == "hide":
                        self.hide_all()
                    elif cmd[0] == "hide_menu_only":
                        # 只隐藏菜单，保持图片显示
                        self.menu_visible = False
                        print("[UtilityWorker] 隐藏菜单，保持图片显示")
                    elif cmd[0] == "update_settings":
                        _, scale, opacity, offset_x, offset_y = cmd
                        self.image_scale = scale
                        self.image_opacity = int(opacity * 255)
                        self.offset_x = offset_x
                        self.offset_y = offset_y
                        print(f"[UtilityWorker] 更新设置: scale={scale}, opacity={opacity}")
                    elif cmd[0] == "set_selected_location":
                        _, location = cmd
                        self.selected_location = location
                
                # 处理pygame事件
                if self.pygame_initialized:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            self.running = False
                    
                    # 保持窗口刷新（降低刷新率）
                    if self.window_visible:
                        # 只在需要时刷新
                        if self.clock:
                            self.clock.tick(10)  # 降低到10 FPS，减少CPU使用
                # 不再 sleep：节奏由上面阻塞 get 的 timeout 决定（UP-061）

            except Exception as e:
                print(f"[UtilityWorker] 主循环错误: {e}")
                import traceback
                traceback.print_exc()
        
        print("[UtilityWorker] 工作器退出")
        if self.pygame_initialized:
            pygame.quit()


class UtilityDisplay:
    """道具显示控制器"""
    def __init__(self, parent_window=None):
        self.parent_window = parent_window
        self.process = None
        self.command_queue = None
        self.status_queue = None
        self.worker_ready = False
        # UP-006: 分帧等就绪用的定时器与截止时刻（见 `_start_worker`）
        self._ready_timer = None
        self._ready_deadline = 0.0

        # 当前地图和道具信息
        self.current_map = None
        self.current_team = None  # 当前阵营
        self.utility_data = {}  # {location: [utilities]}
        
        # 使用频率追踪器
        self.usage_tracker = get_usage_tracker()
        
        print("[UtilityDisplay] 初始化道具显示控制器")
        self._start_worker()
    
    #: 等工作进程报"我起来了"的上限。超过就当它没起来（`_send_command` 会全部 no-op）。
    _READY_TIMEOUT = 10.0
    #: 轮询间隔。这个值只影响"就绪后多久接上"，不影响界面——因为不再阻塞 GUI 线程了。
    _READY_POLL_MS = 50

    def _start_worker(self):
        """启动工作进程。**不阻塞调用线程**（UP-006）。

        原实现在这里 `Process.start()` 之后就地 `while ... time.sleep(0.1)` 轮询
        `status_queue`，超时上限 **10 秒**。而本类是在 GUI 线程构造的
        （`main_widget._connect_utility_later`），所以那段轮询整段压在 GUI 线程上——
        代码里自己的注释写着实测约 **0.9 秒**，最坏 10 秒。用户开「道具瞄点」页就冻。

        改成起完进程立刻返回，用 `QTimer` 分帧收 `status_queue`。安全性来自一个
        既有事实：**所有对外命令都经 `_send_command`，而它本来就 `if self.worker_ready`**——
        就绪之前发的命令原本就会被丢掉（超时那条分支就是这么走的），
        `main_widget` 那边也早写了注释「GSI 事件在 display 就位前由 handler 安全忽略」。
        所以"晚一点就绪"不是新行为，只是把等待从 GUI 线程挪走了。

        没有 Qt 事件循环时（单元测试、脚本直接用）退回原来的阻塞等待，
        否则 QTimer 永远不会触发，工作进程就永远接不上。
        """
        try:
            print("[UtilityDisplay] 启动工作进程...")

            self.command_queue = Queue()
            self.status_queue = Queue()
            self.process = Process(
                target=self._worker_main,
                args=(self.command_queue, self.status_queue)
            )
            self.process.daemon = True
            self.process.start()

            self._ready_deadline = time.time() + self._READY_TIMEOUT
            if self._schedule_ready_poll():
                return
            # 没有事件循环：退回阻塞等待（行为与 UP-006 之前完全一致）
            while time.time() < self._ready_deadline:
                if self._drain_ready_status():
                    return
                time.sleep(0.1)
            print("[UtilityDisplay] 道具显示工作进程启动超时")

        except Exception as e:
            print(f"[UtilityDisplay] 启动道具显示进程失败: {e}")
            import traceback
            traceback.print_exc()
            self.worker_ready = False

    def _schedule_ready_poll(self) -> bool:
        """挂上分帧轮询；没有 Qt 事件循环时返回 False，让调用方退回阻塞等待。"""
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
        except Exception:
            return False
        if QApplication.instance() is None:
            return False

        timer = QTimer()
        timer.setInterval(self._READY_POLL_MS)

        def _tick():
            if self._drain_ready_status():
                timer.stop()
                self._ready_timer = None
                return
            if time.time() >= self._ready_deadline:
                timer.stop()
                self._ready_timer = None
                print("[UtilityDisplay] 道具显示工作进程启动超时")

        timer.timeout.connect(_tick)
        # 必须挂在实例上留引用：局部变量出作用域后 QTimer 会被回收，定时器静默失效。
        self._ready_timer = timer
        timer.start()
        return True

    def _drain_ready_status(self) -> bool:
        """收一次就绪状态；收到（无论成功失败）返回 True。"""
        try:
            if self.status_queue is None or self.status_queue.empty():
                return False
            status, result = self.status_queue.get_nowait()
        except (_queue.Empty, OSError, ValueError):
            return False
        if status != "initialized":
            return False
        if result:
            self.worker_ready = True
            print("[UtilityDisplay] 道具显示工作进程启动成功")
            self._init_settings()
        else:
            print("[UtilityDisplay] 道具显示工作进程初始化失败")
        return True


    @staticmethod
    def _worker_main(command_queue, status_queue):
        """工作进程主函数"""
        try:
            worker = UtilityDisplayWorker(command_queue, status_queue)
            worker.run()
        except Exception as e:
            print(f"[UtilityDisplay] 工作进程异常: {e}")
            import traceback
            traceback.print_exc()
            status_queue.put(("initialized", False))
    
    def _init_settings(self):
        """初始化设置"""
        if self.worker_ready:
            self._send_command((
                "update_settings",
                config.utility_guide_scale,
                config.utility_guide_opacity,
                config.utility_guide_position_x,
                config.utility_guide_position_y
            ))
    
    def _send_command(self, cmd):
        """发送命令到工作进程"""
        if self.worker_ready and self.command_queue:
            try:
                print(f"[UtilityDisplay] 发送命令: {cmd[0]}")
                self.command_queue.put(cmd)
            except Exception as e:
                print(f"[UtilityDisplay] 发送命令失败: {e}")
    
    def load_map_utilities(self, map_name, team=None):
        """加载地图道具 - 支持阵营和排序"""
        print(f"[UtilityDisplay] 加载地图道具: {map_name}, 阵营: {team}")
        
        self.current_map = map_name
        self.current_team = team
        self.utility_data.clear()
        
        # 获取地图文件夹路径
        map_dir = ResourceManager.get_app_data_path(f"resources/utility_guides/{map_name}")
        
        if not os.path.exists(map_dir):
            print(f"[UtilityDisplay] 地图目录不存在: {map_dir}")
            # 创建目录
            os.makedirs(map_dir, exist_ok=True)
            # 创建T和CT文件夹
            os.makedirs(os.path.join(map_dir, "T"), exist_ok=True)
            os.makedirs(os.path.join(map_dir, "CT"), exist_ok=True)
            return
        
        # 根据阵营确定要加载的文件夹
        if team:
            # 如果有阵营信息，只加载对应阵营的道具
            team_dir = os.path.join(map_dir, team)
            if os.path.exists(team_dir):
                self._load_utilities_from_dir(team_dir)
            else:
                print(f"[UtilityDisplay] 阵营目录不存在: {team_dir}")
                # 创建阵营目录
                os.makedirs(team_dir, exist_ok=True)
        else:
            # 如果没有阵营信息，加载根目录和所有子目录
            # 首先加载根目录下的道具（兼容旧版）
            self._load_utilities_from_dir(map_dir, skip_subdirs=["T", "CT"])
            
            # 如果有T或CT目录，根据情况加载
            t_dir = os.path.join(map_dir, "T")
            ct_dir = os.path.join(map_dir, "CT")
            
            # 如果两个目录都存在但没有阵营信息，暂时不加载
            if os.path.exists(t_dir) or os.path.exists(ct_dir):
                print("[UtilityDisplay] 检测到T/CT目录，等待阵营信息确认")
        
        # 应用排序
        self._apply_sorting()
        
        print(f"[UtilityDisplay] 加载地图 {map_name} 道具完成（已排序）: {self.utility_data}")
    
    def _load_utilities_from_dir(self, base_dir, skip_subdirs=None):
        """从指定目录加载道具"""
        if skip_subdirs is None:
            skip_subdirs = []
        
        # 扫描所有子文件夹（投掷位置）
        for location in os.listdir(base_dir):
            location_path = os.path.join(base_dir, location)
            
            # 跳过非目录项
            if not os.path.isdir(location_path):
                continue
            
            # 跳过隐藏文件夹和指定跳过的文件夹
            if location.startswith('.') or location in skip_subdirs:
                continue
            
            utilities = []
            
            # 扫描该位置下的所有道具图片
            files = os.listdir(location_path)
            processed = set()
            
            for file in files:
                if file in processed or file.startswith('.'):
                    continue
                
                # 提取道具名称
                if file.endswith('_站位.jpg') or file.endswith('_站位.png'):
                    utility_name = file.replace('_站位.jpg', '').replace('_站位.png', '')
                    
                    # 检查是否有对应的瞄准图片
                    aim_jpg = f"{utility_name}_瞄准.jpg"
                    aim_png = f"{utility_name}_瞄准.png"
                    
                    if aim_jpg in files or aim_png in files:
                        utilities.append(utility_name)
                        processed.add(file)
                        processed.add(aim_jpg if aim_jpg in files else aim_png)
                        print(f"[UtilityDisplay] 找到道具: {location}/{utility_name}")
            
            if utilities:
                self.utility_data[location] = utilities
    
    def _apply_sorting(self):
        """应用使用频率排序"""
        if not self.current_map or not self.current_team:
            return
        
        # 获取排序后的位置列表
        sorted_locations = self.usage_tracker.get_sorted_locations(self.current_map, self.current_team)
        
        if sorted_locations:
            # 合并排序列表和原始列表
            original_locations = list(self.utility_data.keys())
            merged_locations = self.usage_tracker.merge_with_unsorted(sorted_locations, original_locations)
            
            # 重建有序字典
            new_utility_data = {}
            for location in merged_locations:
                if location in self.utility_data:
                    # 获取该位置的道具并排序
                    utilities = self.utility_data[location]
                    sorted_utilities = self.usage_tracker.get_sorted_utilities(
                        self.current_map, self.current_team, location
                    )
                    
                    if sorted_utilities:
                        # 合并排序列表和原始列表
                        merged_utilities = self.usage_tracker.merge_with_unsorted(
                            sorted_utilities, utilities
                        )
                        new_utility_data[location] = merged_utilities
                    else:
                        new_utility_data[location] = utilities
            
            self.utility_data = new_utility_data
            print("[UtilityDisplay] 已应用使用频率排序")
    
    def show_location_menu(self):
        """显示位置选择菜单"""
        print(f"[UtilityDisplay] 显示位置选择菜单，道具数据: {self.utility_data}")
        
        if not self.utility_data:
            print("[UtilityDisplay] 没有可用的道具")
            return
        
        locations = list(self.utility_data.keys())
        self._send_command(("show_menu", locations, 0))
    
    def show_utility_menu(self, location_index):
        """显示道具选择菜单"""
        print(f"[UtilityDisplay] 显示道具选择菜单，位置索引: {location_index}")
        
        if location_index < 1 or location_index > len(self.utility_data):
            print(f"[UtilityDisplay] 无效的位置索引: {location_index}")
            return
        
        locations = list(self.utility_data.keys())
        location = locations[location_index - 1]
        utilities = self.utility_data[location]
        
        print(f"[UtilityDisplay] 位置 {location} 的道具: {utilities}")
        
        self._send_command(("set_selected_location", location))
        self._send_command(("show_menu", utilities, 1))
    
    def show_utility(self, location_index, utility_index):
        """显示道具图片"""
        print(f"[UtilityDisplay] 显示道具图片，位置索引: {location_index}, 道具索引: {utility_index}")
        
        locations = list(self.utility_data.keys())
        if location_index < 1 or location_index > len(locations):
            print(f"[UtilityDisplay] 无效的位置索引: {location_index}")
            return
        
        location = locations[location_index - 1]
        utilities = self.utility_data[location]
        
        if utility_index < 1 or utility_index > len(utilities):
            print(f"[UtilityDisplay] 无效的道具索引: {utility_index}")
            return
        
        utility_name = utilities[utility_index - 1]
        print(f"[UtilityDisplay] 显示道具: {location}/{utility_name}")
        
        # 构建图片路径 - 支持阵营目录
        if self.current_team:
            location_path = ResourceManager.get_app_data_path(
                f"resources/utility_guides/{self.current_map}/{self.current_team}/{location}"
            )
        else:
            location_path = ResourceManager.get_app_data_path(
                f"resources/utility_guides/{self.current_map}/{location}"
            )
        
        # 查找站位和瞄准图片
        stand_path = None
        aim_path = None
        
        for ext in ['.jpg', '.png']:
            if not stand_path and os.path.exists(os.path.join(location_path, f"{utility_name}_站位{ext}")):
                stand_path = os.path.join(location_path, f"{utility_name}_站位{ext}")
            if not aim_path and os.path.exists(os.path.join(location_path, f"{utility_name}_瞄准{ext}")):
                aim_path = os.path.join(location_path, f"{utility_name}_瞄准{ext}")
        
        if stand_path and aim_path:
            print(f"[UtilityDisplay] 找到图片: {stand_path}, {aim_path}")
            self._send_command(("show_images", stand_path, aim_path))
        else:
            print("[UtilityDisplay] 图片文件不存在")
    
    def hide(self):
        """隐藏所有显示"""
        print("[UtilityDisplay] 隐藏所有显示")
        self._send_command(("hide",))
    
    def update_settings(self, scale, opacity, offset_x, offset_y):
        """更新显示设置"""
        self._send_command(("update_settings", scale, opacity, offset_x, offset_y))
    
    def cleanup(self):
        """清理资源"""
        print("[UtilityDisplay] 清理资源")
        # UP-006: 就绪轮询可能还挂着（进程起得慢、或压根没起来）。
        # 不停掉的话它会在退出链路上继续 tick 一个已经被清理的对象。
        if self._ready_timer is not None:
            try:
                self._ready_timer.stop()
            except RuntimeError:
                pass    # 底层 C++ 对象已被回收，忽略
            self._ready_timer = None
        if self.process and self.process.is_alive():
            self._send_command(("quit",))
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
        self.worker_ready = False