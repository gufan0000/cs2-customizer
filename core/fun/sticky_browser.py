# SPDX-License-Identifier: GPL-3.0-or-later
"""贴屏浏览器窗口：把 Chromium 内核浏览器变成一块无边框竖屏，压在游戏上层。

为什么不用 QWebEngine：打包体积 +150MB，且 PySide6 的 QtWebEngine 是否带
H.264/AAC 专有编解码器不可保证——缺了抖音直接黑屏。借系统 Edge/Chrome
的 --app 模式则体积零增量、编解码天然齐全、登录态还能独立留存。

三条实测得来的硬约束（改代码前先读，全是踩过的）：
  1. 去标题栏只能用 SetWindowRgn 裁。Chromium 的标题栏是自绘在客户区里的，
     去掉 WS_CAPTION/WS_THICKFRAME 后 GetWindowLong 会如实报告已去掉，
     但那条标题栏和三个窗口按钮照样画在那里。
  2. 全程按物理像素工作。主程序若不是 DPI-aware，125% 缩放下贴屏位置整体错 25%。
  3. 收尾只能按 --user-data-dir 或 PID 树精确匹配，**绝不能按 msedge.exe 镜像名杀**，
     那会把用户自己开着的浏览器一起带走。
"""
import ctypes
import json
import os
import socket
import subprocess
import time

import win32api
import win32con
import win32gui
import win32process

from core.utils.logger import get_logger

logger = get_logger("StickyBrowser")

# 移动端 UA 是「刷短视频模式」的开关：桌面 UA 在窄竖窗里会被挤成横屏网格
# 并弹出溢出窗口的登录框，完全不可用。
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

_BROWSER_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

_CS2_WINDOW_CLASSES = ("SDL_app",)
_CS2_WINDOW_TITLES = ("Counter-Strike 2", "Counter-Strike: Global Offensive")
_CS2_PROCESSES = ("cs2.exe", "csgo.exe")

MONITOR_DEFAULTTOPRIMARY = 1

WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_PLAY = 46
APPCOMMAND_MEDIA_PAUSE = 47

TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_char * 260),
    ]


def process_tree_pids(root_pid):
    """收集 root_pid 及其所有后代 PID。

    浏览器是多进程的，音频实际由某个渲染/工具子进程发出，只看启动 PID 会漏。
    用 Toolhelp32 快照建父子表，比起逐个查命令行快得多（毫秒级）。
    """
    pids = {int(root_pid)}
    try:
        snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return pids
        try:
            entry = _PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
            children = {}
            ok = ctypes.windll.kernel32.Process32First(snapshot, ctypes.byref(entry))
            while ok:
                children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
                ok = ctypes.windll.kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            ctypes.windll.kernel32.CloseHandle(snapshot)
        pending = [int(root_pid)]
        while pending:
            current = pending.pop()
            for child in children.get(current, []):
                if child not in pids:
                    pids.add(child)
                    pending.append(child)
    except Exception:
        logger.exception("枚举进程树失败")
    return pids


def _pick_free_port():
    """随便要一个空闲端口。拿不到就返回 0，调用方据此跳过 CDP（功能降级不报错）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])
    except Exception:
        logger.exception("选取调试端口失败，将跳过页面自动调整")
        return 0


def find_browser(preferred=""):
    """定位可用的 Chromium 内核浏览器；preferred 为空则按候选表探测。"""
    preferred = str(preferred or "").strip()
    if preferred and os.path.isfile(preferred):
        return preferred
    for path in _BROWSER_CANDIDATES:
        if os.path.isfile(path):
            return path
    return ""


def _process_image_name(pid):
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def find_game_window():
    """找 CS2 主窗口。类名/标题先粗筛，再用进程映像名核实，避免误认同名窗口。"""
    found = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return True
        if cls not in _CS2_WINDOW_CLASSES and title not in _CS2_WINDOW_TITLES:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if _process_image_name(pid) in _CS2_PROCESSES:
            found.append(hwnd)
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        logger.exception("枚举窗口失败")
    return found[0] if found else 0


def force_foreground(hwnd, attempts=3):
    """跨越 Windows 前台锁把焦点交给目标窗口。

    裸 SetForegroundWindow 会被前台锁**静默拒绝**——注意它失败时抛的是
    错误码 0 的 pywintypes.error（"No error message is available"），
    不是异常状态，必须按返回值/实际前台窗口判定，不能只靠 try/except。

    三级手段，逐级加码：
      1. AttachThreadInput 到当前前台线程，借它的前台权限
      2. 补一次 SW_SHOW + BringWindowToTop（刚从隐藏恢复的窗口常需要这步）
      3. 合成一次 ALT 键——系统把它当"用户有交互"，从而解开前台锁
    绝不去改 ForegroundLockTimeout 之类的系统设置。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    for attempt in range(max(1, attempts)):
        try:
            current = win32gui.GetForegroundWindow()
            if current == hwnd:
                return True
            if attempt >= 1:
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
            if attempt >= 2:
                # 合成 ALT 抬起：让系统认为刚发生过用户输入，解开前台锁
                ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            cur_tid = win32api.GetCurrentThreadId()
            fg_tid, _ = win32process.GetWindowThreadProcessId(current)
            attached = False
            if fg_tid and fg_tid != cur_tid:
                attached = bool(ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True))
            try:
                ctypes.windll.user32.SetForegroundWindow(hwnd)  # 用 ctypes：失败只返回 0，不抛错
            finally:
                if attached:
                    ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
            if win32gui.GetForegroundWindow() == hwnd:
                return True
        except Exception:
            logger.exception("切换前台窗口异常")
        time.sleep(0.12)
    logger.warning(f"未能把焦点切到窗口 {hwnd}（前台锁拒绝）")
    return False


def _title_bar_height(hwnd):
    """Chromium 自绘标题栏高度（物理像素）。32 逻辑像素按窗口 DPI 换算。"""
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    except Exception:
        dpi = 96
    return int(round(32 * dpi / 96))


def _work_area(anchor_hwnd=0):
    """取贴屏目标屏幕的工作区。游戏在哪块屏，就贴哪块屏。"""
    try:
        if anchor_hwnd and win32gui.IsWindow(anchor_hwnd):
            monitor = win32api.MonitorFromWindow(anchor_hwnd, MONITOR_DEFAULTTOPRIMARY)
        else:
            monitor = win32api.MonitorFromPoint((0, 0), MONITOR_DEFAULTTOPRIMARY)
        info = win32api.GetMonitorInfo(monitor)
        return info.get("Work") or info.get("Monitor")
    except Exception:
        logger.exception("取显示器工作区失败，回落主屏")
        return (0, 0, win32api.GetSystemMetrics(win32con.SM_CXSCREEN), win32api.GetSystemMetrics(win32con.SM_CYSCREEN))


class StickyBrowser:
    """一块贴在屏幕边缘的无边框竖屏浏览器窗口。

    生命周期：launch() 起进程并就位（默认起完即隐藏）→ show()/hide() 反复切换
    → close() 收尾。窗口全程复用，不每次死亡重开——冷启动 3-5 秒会毁掉节奏。
    """

    def __init__(self, profile_dir, *, url, browser_path="", mobile_ua=True,
                 side="right", height_ratio=0.82, margin=24, enable_cdp=True):
        self.profile_dir = profile_dir
        self.url = url
        self.browser_path = browser_path
        self.mobile_ua = mobile_ua
        self.side = side
        self.height_ratio = height_ratio
        self.margin = margin
        self.enable_cdp = enable_cdp
        self.cdp_port = 0

        self.proc = None
        self.hwnd = 0
        self._visible = False
        self._owned_pids = set()  # 允许被本对象操作的进程 PID，认窗口的唯一依据

    # ---- 几何 ----

    def target_rect(self, anchor_hwnd=0):
        """按 9:16 算贴屏矩形（物理像素）。"""
        left, top, right, bottom = _work_area(anchor_hwnd)
        area_h = bottom - top
        area_w = right - left
        win_h = max(240, int(area_h * self.height_ratio))
        win_w = max(160, int(win_h * 9 / 16))
        if win_w > area_w - self.margin * 2:
            win_w = max(160, area_w - self.margin * 2)
            win_h = int(win_w * 16 / 9)
        y = top + (area_h - win_h) // 2
        x = (right - win_w - self.margin) if self.side != "left" else (left + self.margin)
        return x, y, win_w, win_h

    # ---- 生命周期 ----

    def kill_leftovers(self):
        """清掉上次遗留的同 profile 浏览器进程。

        软件崩溃或被强杀时走不到退出清理，浏览器就变成孤儿进程赖在后台
        （窗口是隐藏的，用户根本看不见）。下次启动前必须先清一遍，否则
        既留着后台进程，Chromium 还会因 profile 被占用而把新窗口
        转交给旧实例，我们就再也控制不了它。

        只按 --user-data-dir 路径匹配，**绝不按 msedge.exe 镜像名杀**。
        """
        marker = str(self.profile_dir).replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{marker}') }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(1.0)
        except Exception:
            logger.exception("清理遗留浏览器进程失败（继续）")

    def launch(self, *, anchor_hwnd=0, start_hidden=True, timeout=25.0):
        if self.is_alive():
            return True
        exe = find_browser(self.browser_path)
        if not exe:
            logger.error("找不到 Edge 或 Chrome，贴屏浏览器无法启动")
            return False
        self.kill_leftovers()

        x, y, w, h = self.target_rect(anchor_hwnd)
        # 标题栏高度要等窗口出来才能按其 DPI 算；先按主屏 DPI 预估，就位时再精确重排
        pre_title = _title_bar_height(anchor_hwnd or win32gui.GetDesktopWindow())
        args = [
            exe,
            f"--app={self.url}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",                    # 压掉「正在同步你的浏览数据」首屏提示
            "--disable-features=EdgeSyncPromo,SyncPromo,PrivacySandboxSettings4",
            # 没有这条，Chromium 的自动播放策略会让首个视频停在播放按钮上不动，
            # 死亡弹出来是张静止画面，还得用户自己点一下
            "--autoplay-policy=no-user-gesture-required",
            f"--window-position={x},{y - pre_title}",
            f"--window-size={w},{h + pre_title}",
        ]
        if self.mobile_ua:
            args.append(f"--user-agent={MOBILE_UA}")
        if self.enable_cdp:
            # 用于开局把页面切到正确的 tab（见 eval_js）。端口只监听 127.0.0.1、
            # 每次启动随机选取；本机其它程序理论上可借它操作这个浏览器实例，
            # 所以这个 profile 只用来刷视频，不要拿它登录要紧账号。
            self.cdp_port = _pick_free_port()
            if self.cdp_port:
                args.append(f"--remote-debugging-port={self.cdp_port}")

        try:
            self.proc = subprocess.Popen(args)
        except Exception:
            logger.exception("启动贴屏浏览器进程失败")
            return False

        self._owned_pids = process_tree_pids(self.proc.pid) | self._pids_owning_profile()
        self.hwnd = self._await_window(self.proc.pid, timeout)
        if not self.hwnd:
            logger.error("贴屏浏览器窗口未出现，放弃")
            self.close()
            return False
        if not self._owns_hwnd(self.hwnd):
            # 走到这里说明认窗口逻辑出了问题。绝不能继续——下一步就是去改别人的窗口
            logger.error(f"窗口 {self.hwnd} 不属于本进程树，拒绝操作")
            self.hwnd = 0
            self.close()
            return False

        self._apply_frameless(anchor_hwnd)
        if start_hidden:
            self.hide(restore_focus_to=0)
        logger.info(f"贴屏浏览器已就位 hwnd={self.hwnd}")
        return True

    def _await_window(self, pid, timeout):
        """等自己的窗口出现。认窗口的判据只有一条：宿主进程必须是我们自己的。

        ⚠ 这里曾经有个回落：找不到自己 PID 的窗口时就返回任意一个
        Chrome_WidgetWin_1 窗口，注释还振振有词说"独立 user-data-dir 保证不会
        认到用户自己的浏览器"。**那是错的** —— 枚举出来的候选里本来就包含用户
        正在用的浏览器窗口，于是裁标题栏、贴屏、隐藏、发暂停命令全打到了用户
        自己看视频的窗口上。已实际造成事故。

        现在两条判据都要求宿主进程属于本 profile：
          1. 本次启动进程的进程树（快，覆盖绝大多数情况）
          2. 命令行里带本 profile 路径的进程（覆盖 Chromium 把窗口转交给
             同 profile 既有实例、启动进程随即退出的情况）
        两条都不中就认失败 —— 宁可功能不生效，也绝不去动不属于自己的窗口。
        """
        deadline = time.time() + timeout
        profile_pids = set()
        while time.time() < deadline:
            time.sleep(0.3)
            owned = process_tree_pids(pid)
            if not profile_pids or time.time() > deadline - timeout / 2:
                profile_pids = self._pids_owning_profile()
            owned |= profile_pids
            hit = []

            def _cb(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                try:
                    if win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1" or not win32gui.GetWindowText(hwnd):
                        return True
                except Exception:
                    return True
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid in owned:
                    hit.append(hwnd)
                return True

            try:
                win32gui.EnumWindows(_cb, None)
            except Exception:
                continue
            if hit:
                return hit[0]
        return 0

    def _pids_owning_profile(self):
        """命令行里带本 profile 路径的浏览器进程 PID。用户自己的浏览器不含此路径。"""
        marker = str(self.profile_dir).replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{marker}') }} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()}
        except Exception:
            logger.exception("查询本 profile 进程失败")
            return set()

    def _owns_hwnd(self, hwnd):
        """这个窗口是不是我们自己的。所有会改窗口状态的操作前都必须过这一关。

        窗口句柄会被系统回收复用，加上认窗口逻辑本身也可能出错，所以不能只在
        认窗口那一处判断——那次事故就是单点判断失守造成的。
        """
        if not hwnd or not self._owned_pids:
            return False
        try:
            if not win32gui.IsWindow(hwnd):
                return False
            _, wpid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return False
        return wpid in self._owned_pids

    def _apply_frameless(self, anchor_hwnd=0):
        """去掉边框与自绘标题栏，并贴到目标位置。"""
        hwnd = self.hwnd
        if not self._owns_hwnd(hwnd):
            return
        x, y, w, h = self.target_rect(anchor_hwnd)
        title_h = _title_bar_height(hwnd)
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME))
            # 整窗上移 title_h 并等量加高，裁掉标题栏后可视内容正好落在目标矩形
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, x, y - title_h, w, h + title_h,
                win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )
            region = ctypes.windll.gdi32.CreateRectRgn(0, title_h, w, h + title_h)
            # SetWindowRgn 成功后区域归系统所有，不能再 DeleteObject
            if not ctypes.windll.user32.SetWindowRgn(hwnd, region, True):
                ctypes.windll.gdi32.DeleteObject(region)
                logger.warning("裁剪标题栏失败，窗口会带一条 Chromium 自绘标题栏")
        except Exception:
            logger.exception("设置无边框贴屏失败")

    def reposition(self, anchor_hwnd=0):
        self._apply_frameless(anchor_hwnd)

    def show(self, *, anchor_hwnd=0, take_focus=True):
        """显示并（默认）把焦点交给它——CS2 会捕获光标，不交焦点就是看得见摸不着。"""
        if not self.is_alive() or not self._owns_hwnd(self.hwnd):
            return False
        self._apply_frameless(anchor_hwnd)
        try:
            # 要焦点就得用 SW_SHOW：SW_SHOWNOACTIVATE 恢复出来的窗口
            # 之后再 SetForegroundWindow 会被前台锁拒绝
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW if take_focus else win32con.SW_SHOWNOACTIVATE)
            x, y, w, h = self.target_rect(anchor_hwnd)
            title_h = _title_bar_height(self.hwnd)
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_TOPMOST, x, y - title_h, w, h + title_h,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )
        except Exception:
            logger.exception("显示贴屏窗口失败")
            return False
        self._visible = True
        if take_focus:
            force_foreground(self.hwnd)
        self.resume()
        return True

    def hide(self, *, restore_focus_to=0):
        if not self._owns_hwnd(self.hwnd):
            self._visible = False
            if restore_focus_to:
                force_foreground(restore_focus_to)
            return
        # 先暂停再隐藏：回到游戏后绝不能还听见短视频的声音
        self.pause()
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        except Exception:
            logger.exception("隐藏贴屏窗口失败")
        self._visible = False
        if restore_focus_to:
            force_foreground(restore_focus_to)

    # ---- 播放控制 ----

    def _send_appcommand(self, command):
        if not self._owns_hwnd(self.hwnd):
            return
        try:
            # 定向发给这个窗口，不用全局媒体键——那会连累用户正在放的音乐
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_APPCOMMAND, self.hwnd, command << 16)
        except Exception:
            logger.exception("发送媒体控制命令失败")

    def _set_mute(self, mute):
        """对这棵进程树的音频会话静音/解除。暂停万一没生效时的兜底。"""
        if self.proc is None:
            return
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        except Exception as exc:
            logger.debug(f"pycaw 不可用，跳过静音兜底: {exc}")
            return
        need_uninit = False
        try:
            try:
                comtypes.CoInitialize()
                need_uninit = True
            except Exception:
                pass
            targets = process_tree_pids(self.proc.pid)
            for session in AudioUtilities.GetAllSessions() or []:
                try:
                    if int(getattr(session, "ProcessId", 0) or 0) not in targets:
                        continue
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    volume.SetMute(1 if mute else 0, None)
                except Exception:
                    continue
        except Exception:
            logger.exception("设置贴屏浏览器静音失败")
        finally:
            if need_uninit:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def pause(self):
        """暂停播放：媒体暂停命令 + 静音兜底。"""
        if not self._owns_hwnd(self.hwnd):
            return
        self._send_appcommand(APPCOMMAND_MEDIA_PAUSE)
        self._set_mute(True)

    def resume(self):
        """恢复播放。先解除静音再发播放，避免恢复瞬间无声。"""
        if not self._owns_hwnd(self.hwnd):
            return
        self._set_mute(False)
        self._send_appcommand(APPCOMMAND_MEDIA_PLAY)

    # ---- 页面控制（CDP）----
    # 只用来做"开局把页面切到正确的 tab"这一件事。全链路 fail-soft：
    # 任何一步失败都只是页面停在默认位置，主功能（弹出/暂停/收回）照常。

    def _cdp_page(self, timeout=4):
        if not self.cdp_port:
            return None
        try:
            import requests

            resp = requests.get(f"http://127.0.0.1:{self.cdp_port}/json/list", timeout=timeout)
            pages = [p for p in resp.json() if p.get("type") == "page"]
            return pages[0] if pages else None
        except Exception as exc:
            logger.debug(f"读取调试端点失败（忽略）: {exc}")
            return None

    def current_url(self):
        page = self._cdp_page()
        return str((page or {}).get("url", "") or "")

    def eval_js(self, expression, timeout=10):
        """在页面里执行一段 JS，返回结果；失败返回 None，绝不抛。"""
        page = self._cdp_page()
        if not page or not page.get("webSocketDebuggerUrl"):
            return None
        try:
            import websocket
        except Exception as exc:
            logger.debug(f"websocket 库不可用，跳过页面调整: {exc}")
            return None
        try:
            # suppress_origin：不带 Origin 头，就不会触发 Chromium 的跨源拒绝，
            # 从而不必给浏览器加 --remote-allow-origins 去放宽限制
            conn = websocket.create_connection(
                page["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True
            )
        except Exception as exc:
            logger.debug(f"连接调试端点失败（忽略）: {exc}")
            return None
        try:
            conn.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True, "awaitPromise": False},
            }))
            deadline = time.time() + timeout
            while time.time() < deadline:
                message = json.loads(conn.recv())
                if message.get("id") == 1:
                    result = message.get("result", {}).get("result", {})
                    return result.get("value")
            return None
        except Exception as exc:
            logger.debug(f"执行页面脚本失败（忽略）: {exc}")
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def is_alive(self):
        if self.proc is None:
            return False
        return self._owns_hwnd(self.hwnd)

    @property
    def visible(self):
        return self._visible

    def close(self):
        """收尾。只杀自己那棵进程树，绝不按镜像名杀。"""
        proc, self.proc, self.hwnd, self._visible = self.proc, None, 0, False
        self._owned_pids = set()
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            logger.exception("关闭贴屏浏览器失败")
