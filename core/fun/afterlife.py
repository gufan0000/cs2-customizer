# SPDX-License-Identifier: GPL-3.0-or-later
"""整活「死亡刷短视频」编排器。

把 gsi_handler_fun 的死亡/复活/中断三个边沿，接到 sticky_browser 的
显示/隐藏与播放控制上。

行为契约（用户定的，改之前先确认）：
  · 死亡 → 贴屏窗口显示、恢复播放、焦点交给它（CS2 捕获光标，不交焦点就滑不动）
  · 复活 → **暂停**播放、隐藏窗口、焦点还给 CS2
  · 下次死亡 → **从上次暂停处接着播**，不刷新、不重新加载、不重开进程
  · 浏览器进程全程常驻，只有软件退出或功能关闭时才真正结束

窗口只在第一次用时启动一次：冷启动要 3-5 秒，摊到每次死亡上会毁掉节奏。
"""
import os

from PySide6.QtCore import QObject, QTimer, Signal

from core.fun.platforms import get_platform
from core.fun.platforms import resolve as resolve_platform
from core.fun.sticky_browser import StickyBrowser, find_browser, find_game_window, force_foreground
from core.utils.logger import get_logger

logger = get_logger("Afterlife")

PROFILE_DIR_NAME = "fun_browser_profile"
# 连续这么多次显示失败就本次会话停用，避免每次死亡都卡一下
FAILURE_CIRCUIT_LIMIT = 3


class AfterlifeController(QObject):
    """死亡刷短视频的编排器。GSI 回调经信号转到主线程执行。"""

    # GSI 处理线程 → 主线程。Qt 的跨线程信号是排队投递的，窗口操作必须在主线程。
    _death_edge = Signal()
    _respawn_edge = Signal()
    _abort_edge = Signal(str)

    statusChanged = Signal(str)  # 供设置页显示当前状态

    def __init__(self, config_obj, parent=None):
        super().__init__(parent)
        self.config = config_obj
        self.browser = None
        self.game_hwnd = 0
        self._failures = 0
        self._session_disabled = False

        self._stay_timer = QTimer(self)
        self._stay_timer.setSingleShot(True)
        self._stay_timer.timeout.connect(self._on_stay_timeout)

        self._death_edge.connect(self._handle_death)
        self._respawn_edge.connect(self._handle_respawn)
        self._abort_edge.connect(self._handle_abort)

    # ---- 装配 ----

    def attach_handler(self, handler):
        """把 GSI 事件源接过来。回调只做信号转发，不在 GSI 线程碰窗口。"""
        handler.set_callbacks(
            on_death=self._death_edge.emit,
            on_respawn=self._respawn_edge.emit,
            on_abort=self._abort_edge.emit,
        )

    def profile_dir(self):
        from config import get_config_dir

        path = os.path.join(get_config_dir(), PROFILE_DIR_NAME)
        os.makedirs(path, exist_ok=True)
        return path

    def _build_browser(self):
        url, mobile_ua = resolve_platform(
            getattr(self.config, "fun_afterlife_platform", None),
            custom_url=getattr(self.config, "fun_afterlife_url", ""),
            custom_mobile_ua=getattr(self.config, "fun_afterlife_mobile_ua", True),
        )
        return StickyBrowser(
            self.profile_dir(),
            url=url,
            browser_path=str(getattr(self.config, "fun_afterlife_browser_path", "") or ""),
            mobile_ua=mobile_ua,
            side=str(getattr(self.config, "fun_afterlife_side", "right") or "right"),
            height_ratio=float(getattr(self.config, "fun_afterlife_height_ratio", 0.82) or 0.82),
        )

    def reload_platform(self):
        """换平台后重开浏览器。

        网址和 UA 都是**启动参数**，运行中的窗口改不了，只能整个重开。
        没开启或没预热过就什么都不做，免得在设置页点两下就白白拉起一个进程。
        """
        if self.browser is None:
            return False
        self.shutdown()
        self._failures = 0
        self._session_disabled = False
        return self.preheat()

    # ---- 生命周期 ----

    def preheat(self):
        """提前把窗口开好并隐藏，死亡时只剩一次显示，延迟从数秒压到毫秒级。"""
        if self._session_disabled or not bool(getattr(self.config, "fun_afterlife_enabled", False)):
            return False
        if self.browser and self.browser.is_alive():
            return True
        if not find_browser(str(getattr(self.config, "fun_afterlife_browser_path", "") or "")):
            logger.warning("未找到 Edge/Chrome，死亡刷短视频功能不可用")
            self.statusChanged.emit("未找到 Edge 或 Chrome 浏览器")
            return False
        self.browser = self._build_browser()
        anchor = find_game_window()
        ok = self.browser.launch(anchor_hwnd=anchor, start_hidden=True)
        if ok:
            # 预热完立刻暂停：此时页面可能已自动起播，不暂停会一直在后台放
            self.browser.pause()
            self.statusChanged.emit("已就绪")
            # 等首屏渲染完再纠正 tab；窗口此刻是隐藏的，用户看不到这个切换过程
            QTimer.singleShot(9000, self.ensure_feed)
        else:
            self.browser = None
            self.statusChanged.emit("浏览器启动失败")
        return ok

    def ensure_feed(self):
        """把页面从"落错的 tab"切到视频流。

        抖音登录后会把 www.douyin.com 固定重定向到精选网格页，URL 参数覆盖不掉、
        它也不记住你手动切过的偏好，只能进去之后再切一次（详见 platforms.py）。

        全程 fail-soft：切不动就停在原页面，主功能一点不受影响。
        """
        preset = get_platform(getattr(self.config, "fun_afterlife_platform", None))
        feed_js = preset.get("feed_js") or ""
        wrong_landing = preset.get("wrong_landing") or ""
        if not feed_js or not wrong_landing:
            return False
        if self.browser is None or not self.browser.is_alive():
            return False
        url = self.browser.current_url()
        if not url:
            logger.debug("读不到当前页面地址，跳过 tab 纠正")
            return False
        if wrong_landing not in url:
            return True  # 已经在视频流上，不用动
        result = self.browser.eval_js(feed_js)
        if result == "clicked":
            self.browser.pause()  # 切过去会自动起播，隐藏期间不能出声
            logger.info("已把页面切到视频流")
            return True
        logger.info(f"页面 tab 纠正未生效（{result}），保持原样")
        return False

    def shutdown(self):
        """软件退出 / 功能关闭时才真正结束浏览器进程。"""
        self._stay_timer.stop()
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                logger.exception("关闭贴屏浏览器失败")
        self.browser = None
        self.statusChanged.emit("已停止")

    # ---- 边沿处理（均在主线程）----

    def _handle_death(self):
        if self._session_disabled:
            return
        delay = max(0, int(getattr(self.config, "fun_afterlife_delay_ms", 800) or 0))
        QTimer.singleShot(delay, self._show_now)

    def _show_now(self):
        if self._session_disabled:
            return
        if not self.preheat():
            return
        self.game_hwnd = find_game_window() or self.game_hwnd
        ok = self.browser.show(anchor_hwnd=self.game_hwnd, take_focus=True)
        if not ok:
            self._failures += 1
            logger.warning(f"贴屏窗口显示失败（第 {self._failures} 次）")
            if self._failures >= FAILURE_CIRCUIT_LIMIT:
                self._session_disabled = True
                logger.error("连续显示失败，本次运行停用死亡刷短视频功能")
                self.statusChanged.emit("连续失败已停用，请重启软件重试")
            return
        self._failures = 0
        # GSI 可能中途断流（退出游戏、崩溃），没有这个兜底窗口就再也收不回来
        max_stay = max(0, int(getattr(self.config, "fun_afterlife_max_stay_sec", 180) or 0))
        if max_stay > 0:
            self._stay_timer.start(max_stay * 1000)
        self.statusChanged.emit("播放中")

    def _handle_respawn(self):
        self._retract("复活")

    def _handle_abort(self, reason):
        self._retract(reason or "中断")

    def _on_stay_timeout(self):
        # 到这儿说明复活边沿一直没来（多半是 GSI 断流），主动收回
        self._retract("停留超时")

    def _retract(self, reason):
        """暂停播放 + 隐藏 + 焦点还给游戏。不关进程，下次接着播。"""
        self._stay_timer.stop()
        if not self.browser or not self.browser.is_alive():
            return
        if not self.browser.visible:
            self.browser.pause()  # 没显示也确保它不在后台出声
            return
        target = find_game_window() or self.game_hwnd
        # hide() 内部会先 pause 再隐藏，顺序不能颠倒——先隐藏的话
        # 暂停命令有可能打在一个已经不可见的窗口上而不生效
        self.browser.hide(restore_focus_to=target)
        if target and not force_foreground(target):
            logger.warning("未能把焦点切回游戏窗口")
        logger.info(f"已收回贴屏窗口（{reason}）")
        self.statusChanged.emit("已暂停")

    # ---- 设置页用 ----

    def preview(self):
        """设置页的预览：弹出来看效果，**不自动收回**。

        原先写死 20 秒后自动收回，用户正看着它就自己消失了，像出了故障。
        预览是用来慢慢看和调位置的，收回交给「收回窗口」按钮。
        """
        if not self.preheat():
            return False
        self.game_hwnd = find_game_window() or self.game_hwnd
        self._stay_timer.stop()
        ok = self.browser.show(anchor_hwnd=self.game_hwnd, take_focus=True)
        if ok:
            self.statusChanged.emit("预览中，点「收回窗口」结束")
        return ok

    def retract_now(self):
        self._retract("手动收回")

    def open_login(self):
        """让用户在这个 profile 里登录一次抖音。

        登录态存在独立 profile 里，与用户日常浏览器完全隔离；登录后
        以后每次死亡弹出来都是已登录的推荐流。凭据全程只在浏览器里，
        本软件不经手、不读取。
        """
        if not self.preheat():
            return False
        self.game_hwnd = find_game_window() or self.game_hwnd
        self._stay_timer.stop()  # 登录要花时间，不能中途被超时收回
        return self.browser.show(anchor_hwnd=self.game_hwnd, take_focus=True)
