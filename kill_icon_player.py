# SPDX-License-Identifier: GPL-3.0-or-later
import os
import json
import queue as _queue
import threading
import time
from multiprocessing import Queue, Process
from config import config
from resource_manager import ResourceManager
from core.utils.lazy_module import lazy_module
import ctypes

# UP-055: `import pygame` 曾在这里的第 1 行，是 show 前关键路径上的 pygame 入口
# 之一（gui_widget.__init__ 建 KillIconPlayer 时触发），本机约 400ms。
# 而**父进程一次都不用 pygame**——本文件里所有 `pygame.` 调用都在 KillIconWorker
# 里，那个类只在子进程(multiprocessing spawn)中运行；父进程的 KillIconPlayer
# 只负责起进程、发命令。子进程会重新 import 本模块并在入口显式装载。
# 仍用代理而非 None：万一父进程哪天真碰了 pygame，代价是慢一次，而不是崩一次。
#
# 打包安全：pygame 在 build_release.py 的 BASE_HIDDEN_IMPORTS 里显式列着，
# 不依赖此处的静态 import 被发现，故懒加载不会让它从产物里消失。
pygame = lazy_module("pygame", __name__)


def _load_pygame():
    """在子进程入口显式装载 pygame（父进程不该调用）。"""
    import pygame as _pygame

    globals()["pygame"] = _pygame
    return _pygame

# DPI感知设置 (保持不变)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        print("警告: 无法在子进程中设置DPI感知，图标位置在缩放屏幕上可能不准确。")


class KillIconWorker:
    """在独立进程中运行的击杀图标工作器 (优化版)"""
    def __init__(self, command_queue, status_queue):
        self.command_queue = command_queue
        self.status_queue = status_queue
        self.pygame_initialized = False
        self.screen = None
        self.clock = None
        self.sprites = {}
        self.animations = {}
        self.playing = False
        self._play_thread = None  # 当前播放线程引用
        self.current_animation = None
        self.current_frame = 0
        self.window_visible = False
        self.window_width = 400
        self.window_height = 300
        self.window_x = -9999
        self.window_y = -9999
        self.offset_x = 0
        self.offset_y = 0
        self.scale = 1.0
        self.base_width = 350
        self.base_height = 250
        self.hwnd = None
        self.last_draw_time = 0
        self.frame_interval = 1.0 / 30
        self.running = True
        self.current_style_name = None
        self.scaled_sprites_cache = {}
        
        # 在初始化时获取屏幕信息（软件启动时就计算好）
        import platform
        if platform.system() == "Windows":
            import win32api
            self.screen_width = win32api.GetSystemMetrics(0)
            self.screen_height = win32api.GetSystemMetrics(1)
            print(f"[KillIconWorker] 屏幕分辨率: {self.screen_width}x{self.screen_height}")
        else:
            self.screen_width = 1920
            self.screen_height = 1080

    def init_pygame(self):
        """初始化pygame窗口"""
        try:
            pygame.quit()
            pygame.init()
            pygame.display.init()
            
            if hasattr(self, 'window_x') and hasattr(self, 'window_y') and self.window_x != -9999:
                os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
            else:
                os.environ['SDL_VIDEO_WINDOW_POS'] = '-9999,-9999'
            
            self.screen = pygame.display.set_mode(
                (self.window_width, self.window_height),
                pygame.NOFRAME | pygame.SRCALPHA | pygame.DOUBLEBUF | pygame.HWSURFACE
            )
            pygame.display.set_caption("Kill Icon")
            
            import platform
            if platform.system() == "Windows":
                import win32api
                import win32con
                import win32gui
                
                self.hwnd = pygame.display.get_wm_info()["window"]
                
                ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW
                ex_style &= ~win32con.WS_EX_APPWINDOW
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
                win32gui.SetLayeredWindowAttributes(self.hwnd, win32api.RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
                
                if self.window_x == -9999:
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, -9999, -9999, 0, 0,
                        win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                else:
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                        self.window_x, self.window_y,
                        self.window_width, self.window_height,
                        win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
            
            self.clock = pygame.time.Clock()
            self.pygame_initialized = True
            
            self.clear_screen()
            
        except Exception as e:
            print(f"初始化pygame失败: {e}")
            self.pygame_initialized = False

    def clear_screen(self):
        """清空屏幕"""
        if self.screen:
            self.screen.fill((0, 0, 0))
            pygame.display.update()

    def _calculate_window_position(self):
        """计算窗口位置（基于屏幕尺寸、窗口尺寸、偏移量）"""
        # 使用预先获取的屏幕尺寸
        base_x = (self.screen_width - self.window_width) // 2
        base_y = (self.screen_height * 3) // 4 - self.window_height // 2 + 50
        
        self.window_x = base_x + self.offset_x
        self.window_y = base_y + self.offset_y
        
        print(f"[位置计算] 屏幕={self.screen_width}x{self.screen_height}, 窗口={self.window_width}x{self.window_height}, 位置=({self.window_x}, {self.window_y})")
    
    def position_window(self, screen_width, screen_height):
        """计算并设置窗口位置（包含偏移）- 向后兼容方法"""
        # 父进程传来的是 Qt 逻辑像素（高DPI下与物理像素不一致），不采用；
        # 但初始化时取的值在运行中改分辨率后会过时——每次定位前在本进程
        # 内重取物理分辨率，兼顾两者
        try:
            import win32api
            self.screen_width = win32api.GetSystemMetrics(0)
            self.screen_height = win32api.GetSystemMetrics(1)
        except Exception:
            pass  # 保留旧值

        self._calculate_window_position()
        
        if not self.pygame_initialized:
            os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
        
        if self.pygame_initialized and self.hwnd:
            import platform
            if platform.system() == "Windows":
                import win32gui
                import win32con
                win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                    self.window_x, self.window_y,
                    self.window_width, self.window_height,
                    win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
                self.window_visible = True
    
    def hide_window(self):
        """隐藏窗口"""
        if self.pygame_initialized and self.hwnd:
            import platform
            if platform.system() == "Windows":
                import win32gui
                import win32con
                win32gui.SetWindowPos(self.hwnd, 0, -9999, -9999, 0, 0,
                    win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
            self.window_visible = False

    def load_sprite_sheet(self, kills, sprite_path, json_path):
        """加载Sprite Sheet"""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            sprite_surface = pygame.image.load(sprite_path).convert_alpha()
            
            frame_width = data.get('frame_width', 350)
            frame_height = data.get('frame_height', 250)
            frame_count = data.get('frames', 30)
            cols = data.get('cols', sprite_surface.get_width() // frame_width)
            
            frames = []
            for i in range(frame_count):
                x = (i % cols) * frame_width
                y = (i // cols) * frame_height
                if x + frame_width <= sprite_surface.get_width() and y + frame_height <= sprite_surface.get_height():
                    frame_rect = pygame.Rect(x, y, frame_width, frame_height)
                    frame = sprite_surface.subsurface(frame_rect).copy()
                    frames.append(frame)
            
            self.animations[kills] = {
                'fps': data.get('fps', 30),
                'loop': data.get('loop', False),
                'frame_width': frame_width,
                'frame_height': frame_height
            }
            
            self.sprites[kills] = frames
            # 只清除该击杀数的缓存条目，不清除整个缓存
            keys_to_remove = [k for k in self.scaled_sprites_cache if k[0] == kills]
            for k in keys_to_remove:
                del self.scaled_sprites_cache[k]

            print(f"加载动画 {kills}杀: FPS={data.get('fps', 30)}")
            return True
            
        except Exception as e:
            print(f"加载Sprite Sheet失败: {e}")
            return False

    def load_frame_sequence(self, kills, frames_dir, metadata_path=None):
        """加载旧版逐帧动画"""
        try:
            frame_files = [
                os.path.join(frames_dir, name)
                for name in sorted(os.listdir(frames_dir))
                if os.path.isfile(os.path.join(frames_dir, name))
                and name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))
            ]
            if not frame_files:
                return False

            frames = [pygame.image.load(path).convert_alpha() for path in frame_files]
            first_frame = frames[0]
            fps = 30
            if metadata_path and os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    fps = int(metadata.get('fps', 30) or 30)
                except Exception:
                    fps = 30

            self.animations[kills] = {
                'fps': fps,
                'loop': False,
                'frame_width': first_frame.get_width(),
                'frame_height': first_frame.get_height()
            }
            self.sprites[kills] = frames
            keys_to_remove = [k for k in self.scaled_sprites_cache if k[0] == kills]
            for k in keys_to_remove:
                del self.scaled_sprites_cache[k]

            print(f"加载逐帧动画 {kills}杀: FPS={fps}, frames={len(frames)}")
            return True
        except Exception as e:
            print(f"加载逐帧动画失败: {e}")
            return False

    def play_animation(self, kills, custom_fps=None):
        """播放动画（优化版：使用预缩放）"""
        # 在方法开头导入，确保在所有地方都可用
        import platform
        import win32gui
        import win32con
        import win32api
        
        if not self.pygame_initialized or kills not in self.sprites:
            return

        # 停止旧动画并等待线程退出
        self.playing = False
        if self._play_thread is not None and self._play_thread.is_alive():
            self._play_thread.join(timeout=0.2)
        
        original_frame_width = self.animations[kills].get('frame_width', self.base_width)
        original_frame_height = self.animations[kills].get('frame_height', self.base_height)

        target_width = self.base_width * self.scale
        aspect_ratio = original_frame_height / original_frame_width if original_frame_width > 0 else 1
        target_height = target_width * aspect_ratio

        scaled_width = int(target_width)
        scaled_height = int(target_height)

        cache_key = (kills, scaled_width, scaled_height)
        if cache_key not in self.scaled_sprites_cache:
            print(f"缓存未命中，为 {cache_key} 创建预缩放帧...")
            original_frames = self.sprites.get(kills, [])
            scaled_frames = [pygame.transform.smoothscale(frame, (scaled_width, scaled_height)) for frame in original_frames]
            self.scaled_sprites_cache[cache_key] = scaled_frames
        else:
            print(f"缓存命中: {cache_key}")

        # 如果窗口尺寸改变，更新尺寸并重新计算位置
        if scaled_width != self.window_width or scaled_height != self.window_height:
            self.window_width = scaled_width
            self.window_height = scaled_height
            # 尺寸改变时重新计算位置（使用预先获取的屏幕尺寸）
            self._calculate_window_position()
            
            # 隐藏窗口，避免重建时的闪烁
            os.environ['SDL_VIDEO_WINDOW_POS'] = f'{self.window_x},{self.window_y}'
            self.screen = pygame.display.set_mode(
                (self.window_width, self.window_height),
                pygame.NOFRAME | pygame.SRCALPHA | pygame.DOUBLEBUF | pygame.HWSURFACE | pygame.HIDDEN
            )
            if platform.system() == "Windows":
                self.hwnd = pygame.display.get_wm_info()["window"]
                ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW
                ex_style &= ~win32con.WS_EX_APPWINDOW
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
                win32gui.SetLayeredWindowAttributes(self.hwnd, win32api.RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
                # 设置初始位置（不显示）
                win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                    self.window_x, self.window_y,
                    self.window_width, self.window_height,
                    win32con.SWP_NOACTIVATE)
        
        # 每次播放都确保窗口位置正确（使用刚计算的新位置）
        if self.pygame_initialized and self.hwnd:
            if platform.system() == "Windows":
                try:
                    # 三步走：隐藏 → 移动 → 显示（确保无瞬移）
                    # 第1步：隐藏窗口
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                        0, 0, 0, 0,
                        win32con.SWP_HIDEWINDOW | win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                    # 第2步：移动到新位置（窗口已隐藏，看不到移动过程）
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                        self.window_x, self.window_y,
                        self.window_width, self.window_height,
                        win32con.SWP_NOACTIVATE)
                    # 第3步：显示窗口（直接在正确位置显示）
                    win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 
                        0, 0, 0, 0,
                        win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                except Exception as e:
                    print(f"设置窗口位置失败: {e}")
        
        fps = custom_fps if custom_fps is not None else self.animations[kills].get('fps', 30)
        
        print(f"播放动画 {kills}杀: FPS={fps}, 缩放={self.scale}, 最终尺寸={scaled_width}x{scaled_height}")
        
        self.current_animation = kills
        self.current_frame = -1 # 设置为-1，确保第一帧总是被绘制
        self.playing = True
        self.frame_interval = 1.0 / max(1, fps) # 防止除以零

        # 播放代号：旧线程若未在 join 超时内退出，playing 被新播放置回 True
        # 会让它复活，与新线程并发改写 current_frame/刷新同一窗口（帧错乱）。
        # 每次播放递增代号，旧线程发现代号失配即自行退出。
        self._play_token = getattr(self, "_play_token", 0) + 1
        token = self._play_token
        self._play_thread = threading.Thread(target=self._play_loop, args=(token,), daemon=True, name="KillIconPlay")
        self._play_thread.start()

    # ======================================================================
    # 这是唯一被修改的方法
    # ======================================================================
    def _play_loop(self, token=None):
        """播放循环 (优化版：精确控制帧率，减少不必要的绘制)"""
        # 检查动画是否有效
        if not self.playing or self.current_animation not in self.sprites:
            return
        if token is not None and token != getattr(self, "_play_token", token):
            return  # 已被新播放取代

        cache_key = (self.current_animation, self.window_width, self.window_height)
        
        if cache_key not in self.scaled_sprites_cache:
            print(f"错误: 播放循环开始时缓存 {cache_key} 不存在！")
            self.playing = False
            return
            
        scaled_frames = self.scaled_sprites_cache[cache_key]
        frame_count = len(scaled_frames)

        if frame_count == 0:
            self.playing = False
            return
            
        start_time = time.time()
        
        while self.playing:
            if token is not None and token != getattr(self, "_play_token", token):
                return  # 新播放已接管窗口，本线程退出且不清屏
            # 计算理论上应该播放的帧
            elapsed_time = time.time() - start_time
            target_frame_index = int(elapsed_time / self.frame_interval)

            if target_frame_index >= frame_count:
                # 动画播放完毕
                self.playing = False
                self.clear_screen()
                break

            # 只有当需要切换到新的一帧时，才进行绘制
            if target_frame_index > self.current_frame:
                self.current_frame = target_frame_index
                
                try:
                    # 获取要绘制的帧
                    frame_to_draw = scaled_frames[self.current_frame]
                    
                    # 清屏并绘制新帧
                    self.screen.fill((0, 0, 0, 0)) # 使用带alpha的颜色清屏
                    self.screen.blit(frame_to_draw, (0, 0))
                    
                    # 更新显示 (这是触发与游戏渲染冲突的关键操作)
                    pygame.display.update()
                except IndexError:
                    # 如果索引越界，说明动画已结束
                    self.playing = False
                    self.clear_screen()
                    break
                except Exception as e:
                    print(f"绘制帧时出错: {e}")
                    self.playing = False
                    break

            # 计算到下一帧理论时间的休眠时长
            next_frame_target_time = start_time + (self.current_frame + 1) * self.frame_interval
            sleep_duration = next_frame_target_time - time.time()
            
            # 智能休眠，避免CPU空转，同时保证响应性
            if sleep_duration > 0:
                time.sleep(min(sleep_duration, 0.01)) # 每次最多休眠10ms，以快速响应停止命令
    # ======================================================================
    # 修改结束
    # ======================================================================

    def run(self):
        """主循环"""
        self.status_queue.put(("initialized", True))

        while self.running:
            try:
                # UP-061: 原本是 `if not empty(): get_nowait()` + `time.sleep(0.001)`,
                # 即约 640~1000Hz 空转轮询 —— 长期占 CPU、阻止 CPU 进深度休眠,
                # 而这个进程绝大多数时间根本无事可做(没在放动画)。
                # 改为**阻塞等待**:命令一到就立刻返回(比轮询更跟手,不是更慢),
                # 超时只用来决定"多久醒一次去泵 pygame 事件"。
                # 播放中按 ~60Hz 醒(够泵事件),空闲时 5Hz。
                #
                # 判据用 window_visible 而不是 pygame_initialized：后者一旦首次
                # 显示过就**永远为真**，于是"空闲 5Hz"这句承诺从第一次击杀之后就
                # 再也达不到，等于把 1000Hz 空转换成了 60Hz 空转。
                # 窗口藏在 (-9999,-9999) 时根本不需要按帧泵事件。
                try:
                    cmd = self.command_queue.get(
                        timeout=0.016 if self.window_visible else 0.2
                    )
                except _queue.Empty:
                    cmd = None
                if cmd is not None:
                    if cmd[0] == "quit":
                        self.running = False
                        break
                    elif cmd[0] == "show":
                        _, screen_width, screen_height = cmd
                        if not self.pygame_initialized:
                            self.init_pygame()
                        self.position_window(screen_width, screen_height)
                    elif cmd[0] == "hide":
                        self.hide_window()
                    elif cmd[0] == "load_style":
                        _, style_name = cmd
                        self.current_style_name = style_name
                        self.sprites.clear()
                        self.animations.clear()
                        self.scaled_sprites_cache.clear()
                        if not self.pygame_initialized:
                            self.init_pygame()
                        style_dir = ResourceManager.get_kill_icon_style_dir(style_name)
                        if os.path.exists(style_dir):
                            for kills in range(1, 6):
                                sprite_path, json_path = ResourceManager.get_kill_icon_sprite_sheet_paths(style_name, kills)
                                if os.path.exists(sprite_path) and os.path.exists(json_path):
                                    self.load_sprite_sheet(kills, sprite_path, json_path)
                                    continue

                                legacy_dir = ResourceManager.get_kill_icon_legacy_frames_dir(style_name, kills)
                                if legacy_dir:
                                    metadata_path = ResourceManager.get_kill_icon_metadata_path(style_name, kills)
                                    self.load_frame_sequence(kills, legacy_dir, metadata_path)
                    elif cmd[0] == "play":
                        _, kills, custom_fps = cmd
                        self.play_animation(kills, custom_fps)
                    elif cmd[0] == "stop":
                        self.playing = False
                        self.clear_screen()
                    elif cmd[0] == "update_offset":
                        _, offset_x, offset_y = cmd
                        self.offset_x = offset_x
                        self.offset_y = offset_y
                        # 偏移改变时重新计算位置
                        self._calculate_window_position()
                        print(f"偏移更新: ({offset_x}, {offset_y}), 新位置: ({self.window_x}, {self.window_y})")
                    elif cmd[0] == "update_scale":
                        _, scale = cmd
                        if self.scale != scale:
                           self.scale = scale
                           self.scaled_sprites_cache.clear()
                           # 缩放改变时也会影响窗口尺寸，播放时会重新计算位置
                           print(f"缩放更新: {scale}")
                    elif cmd[0] == "update_base_size":
                        _, base_width, base_height = cmd
                        if self.base_width != base_width or self.base_height != base_height:
                           self.base_width = base_width
                           self.base_height = base_height
                           self.scaled_sprites_cache.clear()
                
                if self.pygame_initialized:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            self.running = False
                # 不再 sleep：节奏由上面阻塞 get 的 timeout 决定
            except Exception as e:
                print(f"Worker错误: {e}")
        
        if self.pygame_initialized:
            pygame.quit()


class KillIconPlayer:
    def __init__(self, parent_window=None):
        self.parent_window = parent_window
        self.current_style = None
        self.process = None
        self.command_queue = None
        self.status_queue = None
        self.worker_ready = False
        self.animations = {}
        # 延迟启动工作进程，不阻塞主线程
        import threading
        self._start_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._worker_starting = False
        self._pending_commands = []
        
    def _ensure_worker_started(self):
        if self.worker_ready:
            return True
        with self._start_lock:
            if self.worker_ready:
                return True
            if self._worker_starting:
                return True
            if self.process and self.process.is_alive():
                return self.worker_ready
            self._worker_starting = True
            threading.Thread(target=self._start_worker, daemon=True, name="KillIconInit").start()
        return True

    def _start_worker(self):
        try:
            self.command_queue = Queue()
            self.status_queue = Queue()
            self.process = Process(target=self._worker_main, args=(self.command_queue, self.status_queue))
            self.process.daemon = True
            self.process.start()
            
            timeout = 5.0
            start_time = time.time()
            while time.time() - start_time < timeout:
                if not self.status_queue.empty():
                    status, result = self.status_queue.get()
                    if status == "initialized" and result:
                        self.worker_ready = True
                        print("击杀图标工作进程已启动")
                        break
                time.sleep(0.1)
            
            if not self.worker_ready:
                print("击杀图标工作进程启动超时")
            else:
                self._init_config()
                self._flush_pending_commands()
                
            if config.kill_icon_enabled and self.worker_ready:
                self.enable_kill_icons()
        except Exception as e:
            print(f"启动击杀图标进程失败: {e}")
            self.worker_ready = False
        finally:
            self._worker_starting = False
    
    def _init_config(self):
        """初始化配置"""
        if self.worker_ready:
            self._send_command(("update_offset", config.kill_icon_offset_x, config.kill_icon_offset_y))
            self._send_command(("update_scale", config.kill_icon_scale))
            self._send_command(("update_base_size", config.kill_icon_base_width, config.kill_icon_base_height))
    
    @staticmethod
    def _worker_main(command_queue, status_queue):
        # 子进程入口：pygame 只在这一侧需要（UP-055）
        _load_pygame()
        worker = KillIconWorker(command_queue, status_queue)
        worker.run()
    
    def _queue_command(self, cmd):
        with self._command_lock:
            self._pending_commands.append(cmd)

    def _flush_pending_commands(self):
        if not self.worker_ready or not self.command_queue:
            return
        with self._command_lock:
            pending_commands = list(self._pending_commands)
            self._pending_commands.clear()
        for pending_cmd in pending_commands:
            self._send_command(pending_cmd)

    def _send_command(self, cmd):
        if self.worker_ready and self.command_queue:
            try:
                self.command_queue.put(cmd)
            except Exception as e:
                print(f"发送命令失败: {e}")
        else:
            self._queue_command(cmd)

    def enable_kill_icons(self):
        self._ensure_worker_started()
        if self.parent_window:
            # 兼容PySide6和Tkinter
            if hasattr(self.parent_window, 'winfo_screenwidth'):
                # Tkinter
                screen_width = self.parent_window.winfo_screenwidth()
                screen_height = self.parent_window.winfo_screenheight()
            else:
                # PySide6/PyQt6
                screen = self.parent_window.screen()
                screen_width = screen.size().width()
                screen_height = screen.size().height()
            self._send_command(("show", screen_width, screen_height))
    
    def disable_kill_icons(self):
        self._send_command(("hide",))
    
    def _read_style_metadata(self, style_name, kills):
        metadata_path = ResourceManager.get_kill_icon_metadata_path(style_name, kills)
        if not os.path.exists(metadata_path):
            return {}
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def load_style(self, style_name):
        self._ensure_worker_started()
        self.current_style = style_name
        self.animations.clear()
        style_found = False

        for kills in range(1, 6):
            if not ResourceManager.has_kill_icon_level_assets(style_name, kills):
                continue
            metadata = self._read_style_metadata(style_name, kills)
            self.animations[kills] = {'fps': int(metadata.get('fps', 30) or 30)}
            style_found = True

        self._send_command(("load_style", style_name))
        return style_found
    
    def play_icon(self, kills, custom_fps=None):
        if not config.kill_icon_enabled:
            return
        self._ensure_worker_started()
        if self.parent_window:
            # 兼容PySide6和Tkinter
            if hasattr(self.parent_window, 'winfo_screenwidth'):
                # Tkinter
                screen_width = self.parent_window.winfo_screenwidth()
                screen_height = self.parent_window.winfo_screenheight()
            else:
                # PySide6/PyQt6
                screen = self.parent_window.screen()
                screen_width = screen.size().width()
                screen_height = screen.size().height()
            self._send_command(("show", screen_width, screen_height))
        self._send_command(("play", kills, custom_fps))
    
    def stop(self):
        self._send_command(("stop",))
    
    def cleanup(self):
        with self._command_lock:
            self._pending_commands.clear()
        if self.process and self.process.is_alive():
            try:
                if self.command_queue:
                    self.command_queue.put(("quit",))
            except Exception:
                pass
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
        self.worker_ready = False
    
    def play_images(self, style, kills):
        if not config.kill_icon_enabled:
            return
        if not self.current_style or self.current_style != config.kill_icon_style:
            if not self.load_style(config.kill_icon_style):
                return
        self.play_icon(kills, None)
    
    def stop_images(self):
        self.stop()
    
    def clear_preloaded_images(self):
        pass
    
    def update_fps_for_style(self, style_name, kills, new_fps):
        metadata_path = ResourceManager.get_kill_icon_metadata_path(style_name, kills)
        style_dir = ResourceManager.get_kill_icon_style_dir(style_name)
        try:
            if not ResourceManager.has_kill_icon_level_assets(style_name, kills):
                return False
            os.makedirs(style_dir, exist_ok=True)
            data = self._read_style_metadata(style_name, kills)
            data['fps'] = int(new_fps)
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if style_name == self.current_style and kills in self.animations:
                self.animations[kills]['fps'] = int(new_fps)
            print(f"已保存 {kills}杀 FPS设置: {new_fps}")
            return True
        except Exception as e:
            print(f"更新FPS配置失败: {e}")
            return False
    
    def get_style_fps(self, style_name, kills):
        if style_name == self.current_style and kills in self.animations:
            return self.animations[kills].get('fps', 30)
        metadata = self._read_style_metadata(style_name, kills)
        return int(metadata.get('fps', 30) or 30)
    
    def update_position_offset(self, offset_x, offset_y):
        """更新位置偏移"""
        self._ensure_worker_started()
        self._send_command(("update_offset", offset_x, offset_y))
    
    def update_scale(self, scale):
        """更新缩放比例"""
        self._ensure_worker_started()
        self._send_command(("update_scale", scale))
    
    def preview_position_and_scale(self, kills=1, duration=3):
        """预览位置和大小设置"""
        was_enabled = config.kill_icon_enabled
        if not was_enabled:
            config.kill_icon_enabled = True
            self.enable_kill_icons()
        
        self.play_icon(kills, 30)
        
        def stop_preview():
            self.stop()
            if not was_enabled:
                config.kill_icon_enabled = False
                self.disable_kill_icons()
        
        threading.Timer(duration, stop_preview).start()
