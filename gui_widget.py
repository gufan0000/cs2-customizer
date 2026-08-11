#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
帆派助手 2.0 - Widget版本
主窗口类
"""

import os
import threading

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QScrollArea, QFrame,
    QSlider, QComboBox, QStackedWidget,
    QSpinBox, QDoubleSpinBox, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Qt, QEvent, QSize, Signal, Slot, QEasingCurve, QSequentialAnimationGroup, QVariantAnimation
from PySide6.QtGui import QFont, QColor

from config import config, VERSION
from core.utils.logger import get_logger
from theme_manager import get_theme_manager, get_stylesheet
from ui_design_system import get_design_system
from ui_style_applier import apply_unified_styles
from ui_animations import get_animation_manager
from ui_transitions import create_page_transition
from ui_effects import get_effects_manager
from ui_toast import get_toast_manager
from ui_ripple_effect import add_ripple_effect
from ui_shimmer import add_shimmer_on_hover
# 页面模块和重量级组件延迟导入（在需要时按需 import，加速启动）
from screen_effect_overlay import ScreenEffectOverlayManager
from core.audio.audio_resource_health import collect_audio_resource_health
from core.gun_sound_profiles import sync_legacy_gun_sound_flags
from core.runtime.system_status_service import collect_runtime_status
from pages.audio_status_badge import create_badge_label, render_badges
from source_backup_manager import run_startup_source_backup


class NavGroupWidget(QWidget):
    """可折叠的导航分组组件"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._animating = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 组头：可点击的标题栏
        self.header = QPushButton()
        self.header.setObjectName("navGroupHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setCheckable(False)
        self.header.clicked.connect(self.toggle)
        self._title = title
        self._update_header_text()
        main_layout.addWidget(self.header)

        # 子项容器
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 2, 0, 0)
        self.content_layout.setSpacing(1)
        main_layout.addWidget(self.content)

    def _update_header_text(self):
        arrow = "▾" if self._expanded else "▸"
        self.header.setText(f"  {arrow}  {self._title}")

    def add_button(self, btn):
        self.content_layout.addWidget(btn)

    def toggle(self):
        if self._animating:
            return
        self._expanded = not self._expanded
        self._update_header_text()
        self.content.setVisible(self._expanded)

    def set_expanded(self, expanded):
        if self._expanded != expanded:
            self._expanded = expanded
            self._update_header_text()
            self.content.setVisible(self._expanded)


class ClickableLabel(QLabel):
    """轻量可点击标签，用于首页功能名跳转。"""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """主窗口"""

    # 线程安全的 Toast 信号，可从任何线程 emit
    _toast_signal = Signal(str, str, int)  # (message, toast_type, duration)
    # UP-035: 配置被整体改写（应用预设 / 恢复快照 / 导入分享）时收到广播。
    # 必须走 Signal 而不是直接回调——`core/presets/map_rules.py` 的按地图自动切预设
    # 是 GSI 事件驱动的、跑在**后台线程**上，在那儿直接碰 Qt 控件会崩。
    # Signal 的自动连接在跨线程时会排队到 GUI 线程，正是我们要的。
    _config_reloaded_signal = Signal(str)

    def __init__(self, auto_background_preload=True):
        super().__init__()
        self.logger = get_logger("GUI")
        self._auto_background_preload = auto_background_preload

        # 2.2.0 主窗构建子相位计时(起点=构造第一行)
        import time as _phase_t

        _phase_state = [_phase_t.perf_counter()]

        def _sub_phase(name):
            now = _phase_t.perf_counter()
            self.logger.info(f"[主窗相位] {name}: +{(now - _phase_state[0]) * 1000:.0f}ms")
            _phase_state[0] = now

        # 后台自动创建源码快照，避免文件损坏时无法回退
        self.config = config
        # UP-055: 这里原本直接 get_runtime_audio_manager()，把 pygame(约 400ms)
        # 拖进窗口显示前的主线程。实测本窗口只在两处用到它——音量设置与退出清理，
        # 两处都在 show 之后；各音效页面另有自己的引用。改为惰性属性，见下方 property。
        self._audio_manager = None
        _sub_phase("音频运行时管理器(延后)")
        self.theme_manager = get_theme_manager()  # 主题管理器
        _sub_phase("主题管理器构造")
        self.gsi_server = None  # 将在main_widget.py中设置
        
        # 初始化动画和效果管理器
        self.animation_manager = get_animation_manager()
        self.effects_manager = get_effects_manager()
        self.page_transition = None  # 页面过渡管理器，稍后初始化
        self.toast_manager = get_toast_manager()  # Toast通知管理器

        # 性能优化：窗口移动状态
        self._is_moving = False
        # 预创建窗口移动定时器，避免每次移动都创建新对象
        from PySide6.QtCore import QTimer
        self._move_restart_timer = QTimer()
        self._move_restart_timer.setSingleShot(True)
        self._move_restart_timer.timeout.connect(self._on_move_finished)
        
        # 加载保存的主题
        saved_theme = config.ui_theme if hasattr(config, 'ui_theme') else "dark"
        self.theme_manager.set_theme(saved_theme)
        _sub_phase("主题QSS生成+应用")
        
        # 注册主题变化回调
        self.theme_manager.register_theme_changed_callback(self._on_theme_changed)
        
        self.setWindowTitle(f"帆派助手 v{VERSION}")
        app_icon = QApplication.windowIcon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        # 紧凑模式状态
        self._compact_mode = getattr(config, 'compact_mode', False)
        if self._compact_mode:
            self.setMinimumSize(860, 640)
        else:
            self.setMinimumSize(1200, 800)
        
        # 根据屏幕分辨率自适应窗口大小；若开启记忆且有有效几何则优先恢复
        self._setup_window_size()
        self._restore_window_geometry()

        self.logger.info("初始化GUI...")
        
        # 页面懒加载相关
        self._loaded_pages = set()  # 已加载的页面ID
        self._pages_need_theme_refresh = set()  # 需要主题刷新的页面ID
        self._search_hit_target = None  # R4/UP-024: 当前被搜索高亮的控件
        self._is_closing = False  # 关闭流程标记，防止延迟任务继续触发副作用
        self._preload_skip_pages = {
            # 这些页面在构造时会启动热键/线程/子进程/设备，不适合启动阶段静默预加载
            "viewmodel",
            "magnifier",
            "flash",
            "voice_output",
            "kill_icon",
            "music",
        }
        self._expert_only_pages = {
            "audio_health",
            "audio_import_wizard",
            "audio_task_panel",
            "audio_replay",
            "config_snapshot",
            "preset_center",
        }

        # 创建击杀图标播放器
        from kill_icon_player import KillIconPlayer
        self.kill_icon_player = KillIconPlayer(self)
        
        # 创建准心动画系统（R8b/UP-054：两套渲染器并存一个发布周期）
        # 老实现把窗口建在主线程、却在工作线程刷新，违反 Win32 窗口线程亲和性，
        # 是「原生崩溃只能靠兼容模式跳过准心」的根因。Qt 版天生没有这条路
        # （QWidget 只能在主线程碰）。默认值与翻默认的前置条件见 config.crosshair_renderer。
        self.crosshair_animation = self._create_crosshair_renderer(config)

        # 屏幕特效管理器（与页面解耦，页面未打开也能触发）
        try:
            self.screen_effect_overlay = ScreenEffectOverlayManager(self.config, self)
        except Exception as e:
            self.screen_effect_overlay = None
            self.logger.error(f"Create screen effect manager failed: {e}")
        _sub_phase("击杀图标/准心/特效管理器")

        # 创建UI
        self._create_ui()
        _sub_phase("UI构建(导航+首页)")

        # 首页系统状态条定时刷新
        # UP-009: 原先每 2 秒在 GUI 线程做一次全量音频资源磁盘体检 + 读 CS2 目录下的
        # cfg 文件(实测 9~20ms/次),而且托盘隐藏后照跑不误——用户根本看不见状态条,
        # 却一直在为它付主线程 I/O。现在:间隔 2s→15s,且不可见时跳过整次刷新。
        # 状态条本就是"慢变量"(GSI 在跑没在跑、音频健不健康),15 秒粒度完全够用;
        # 真正需要即时反馈的地方另有 toast / action bar。
        from PySide6.QtCore import QTimer
        self._system_status_timer = QTimer(self)
        self._system_status_timer.timeout.connect(self._tick_system_status_strip)
        self._system_status_timer.start(15000)
        QTimer.singleShot(200, self._refresh_system_status_strip)

        # P3.2: 上次运行若有崩溃日志，询问是否发送给开发者（绝不自动上传）
        QTimer.singleShot(12000, self._maybe_prompt_crash_report)

        # P4.1: 全新安装首次启动弹三步引导（老用户由 onboarding_completed 豁免）
        QTimer.singleShot(900, self._maybe_show_onboarding)

        # 系统集成（对标主流）：系统托盘——开游戏时主窗可收进托盘后台常驻
        self._tray_icon = None
        self._tray_hint_shown = False
        self._force_exit = False
        self._init_system_tray()
        
        # 如果准心在启动时是启用状态，自动显示
        # 兼容(自愈)模式跳过 pygame 准心：faulthandler 实证——准心 pygame/SDL 与 Qt
        # 在个别机器(尤其缩放屏，SDL 与 Qt 的 DPI 感知不一致)上于 window.show() 并发
        # 抢视频资源，触发原生 abort(ucrtbase 0xc0000409，进程静默消失)。跳过 pygame
        # 准心后，window.show() 不再有并发冲突，用户至少能进入软件正常使用其余功能。
        # UP-010: 准心 pygame 窗口的创建实测占 344ms,原先在 MainWindow.__init__ 里
        # 同步做,把"窗口出现"整整推迟了这么久——而用户这时候连界面都还没看到。
        # 改为主窗显示后延迟创建:准心是覆盖在游戏上的东西,晚 1.2 秒出现没有任何影响,
        # 但首屏快 344ms 是实打实能感知的。
        # 注意:CrosshairPage 构造时并不会自己调 show_crosshair()(已核实),所以这条
        # 延迟路径是准心的唯一自动显示入口,不能因为"用户可能先切到准心页"就省掉。
        # _auto_show_crosshair_deferred 里做了幂等与"期间用户关掉了准心"的判断。
        if self.config.crosshair_enabled:
            if os.environ.get("FANPAI_SAFE_MODE_ACTIVE") == "1":
                self.logger.warning("兼容模式：已跳过 pygame 准心自动显示（规避与主窗渲染并发冲突导致的原生崩溃）")
            else:
                # UP-079: R8a 把 pygame 移出了 show 前路径，但它没有凭空消失——
                # 谁第一个碰它谁付这 400ms。准心的自动显示定时器恰好是那个倒霉蛋：
                # show 后 1200ms 在**主线程**首次触碰，实测冻结 426ms。
                # 那比"启动慢 400ms"更刺眼：窗口已经可交互了才卡住。
                # 下面几行的音乐控制栏早就用了同一招（等工作线程把 pygame import 热了
                # 再在主线程用，二次 import 是纯查表），这里照做。
                self._prewarm_pygame_async()
                QTimer.singleShot(1200, self._auto_show_crosshair_deferred)
        
        _sub_phase("定时器/托盘/准心收尾")
        self.logger.info("GUI初始化完成")

        # 延迟创建音乐控制栏（含 pygame 导入,实测主线程卡 ~320ms）
        # 2.2.0 卡顿治理:推迟到后台音频阶段(stage2,工作线程已把 pygame import 热了)
        # 之后创建——主线程二次 import 同模块为零成本,卡顿消失。
        # 兜底:若 8s 后后台阶段仍未触发(异常路径),仍强制创建,保证控制栏必然出现。
        from PySide6.QtCore import QTimer
        QTimer.singleShot(8000, self._create_music_control_bar)

        # 延迟刷新所有已加载页面的主题（修复首次启动时主题加载问题）
        # 使用500ms延迟确保Qt样式系统完全初始化，避免与页面加载撞车
        # 2.2.0 卡顿治理:初始主题刷新默认跳过——它对全树 unpolish/polish+递归重绘,
        # 实测制造 ~500ms 冻结+全屏闪烁(用户长期反馈的"闪一下");页面在全局 QSS
        # 就绪后构建,样式本就正确。万一某环境首屏样式异常,开 config.theme_refresh_on_start。
        if bool(getattr(config, "theme_refresh_on_start", False)):
            QTimer.singleShot(500, self._initial_theme_refresh)

        # 后台静默预加载所有页面（首屏显示后逐个加载，避免切换卡顿）
        if self._auto_background_preload:
            QTimer.singleShot(800, self._preload_remaining_pages)
        QTimer.singleShot(1500, self._start_source_backup)
        QTimer.singleShot(2200, self._start_audio_health_check)
        
        # 启动玩家ID周期性检查
        self._start_player_id_check()
        
        # 禁用滚轮调整UI控件（防止意外修改设置）
        self._disable_wheel_on_widgets()

    @property
    def audio_manager(self):
        """音频运行时管理器 —— 首次真正用到时才建（UP-055）。

        为什么值得延后：拿到它要先 `import pygame`，本机实测约 400ms
        （pkg_resources 219 + numpy 113），而这 400ms 原本落在窗口显示**之前**
        的主线程上。本窗口对它的全部用途是「音量设置」和「退出清理」，
        没有一处发生在 show 之前。

        注意退出清理不能走这个属性——那会为了 cleanup 反而把整套 pygame
        拉起来。退出链路改用 `peek_runtime_audio_manager()`。
        """
        if self._audio_manager is None:
            from core.audio.runtime_audio import get_runtime_audio_manager

            self._audio_manager = get_runtime_audio_manager()
        return self._audio_manager

    def _prewarm_pygame_async(self):
        """在工作线程里把 pygame 的 import 热掉（UP-079）。

        R8a 让 pygame 不再进 show 前的关键路径，代价是把「谁第一个碰它谁付 400ms」
        推给了后面的某个调用点。实测那个点就是准心自动显示定时器，而它跑在**主线程**
        ——10ms 心跳探针量到整段启动期唯一一次 >60ms 的间隔就是它，426.8ms。

        Python 的 import 有全局缓存、且导入机制自身带锁，工作线程先导一遍之后，
        主线程那次 `import pygame` 只是查 `sys.modules`，成本为零。
        失败也不要紧：主线程届时会自己导入，只是慢回原样。
        """
        import threading

        def _warm():
            try:
                import pygame  # noqa: F401
            except Exception:
                self.logger.debug("[准心] pygame 预热失败，主线程届时会自行导入", exc_info=True)

        threading.Thread(target=_warm, daemon=True, name="PygamePrewarm").start()

    def _cleanup_audio_manager(self):
        """退出时清理音频管理器，但绝不为此把它创建出来（UP-055）。"""
        from core.audio.runtime_audio import peek_runtime_audio_manager

        manager = peek_runtime_audio_manager()
        if manager is not None:
            manager.cleanup()

    def _start_source_backup(self):
        try:
            from threading import Thread
            Thread(
                target=lambda: run_startup_source_backup(self.logger),
                daemon=True,
                name="SourceBackup",
            ).start()
        except Exception as e:
            self.logger.warning(f"Start source auto-backup failed: {e}")

    def _start_audio_health_check(self):
        try:
            from threading import Thread
            Thread(
                target=self._run_audio_health_check,
                daemon=True,
                name="AudioHealthCheck",
            ).start()
        except Exception as e:
            self.logger.warning(f"Start audio health check failed: {e}")

    def _run_audio_health_check(self):
        """启动期后台体检并输出摘要日志。"""
        try:
            report = collect_audio_resource_health()
            summary = report.get("summary", {})
            if summary.get("ok", False):
                self.logger.info("[AudioHealth] OK")
            else:
                self.logger.warning(
                    "[AudioHealth] issues detected: "
                    f"missing_dirs={summary.get('missing_directories', 0)}, "
                    f"invalid_refs={summary.get('invalid_config_refs', 0)}, "
                    f"empty_style_dirs={summary.get('empty_style_dirs', 0)}"
                )
        except Exception as e:
            self.logger.warning(f"[AudioHealth] check failed: {e}")

    def _create_crosshair_renderer(self, config):
        """按 `config.crosshair_renderer` 选渲染器，两套接口逐个方法对齐。

        Qt 路径失败**必须能退回老实现**——准心是打开就用的功能，
        新渲染器万一在某台机器上建不起来，用户至少还有原来那套可用。
        """
        renderer = str(getattr(config, "crosshair_renderer", "pygame") or "pygame").lower()
        if renderer == "qt":
            try:
                from crosshair_overlay import CrosshairOverlayManager

                self._crosshair_win32_available = True
                self.logger.info("准心渲染器：Qt 透明置顶窗")
                return CrosshairOverlayManager(config, self)
            except Exception:
                self.logger.exception("Qt 准心渲染器创建失败，回退 pygame 实现")

        from crosshair_animation import CrosshairAnimation, win32_available
        self._crosshair_win32_available = win32_available
        return CrosshairAnimation(config, self)

    def _auto_show_crosshair_deferred(self):
        """UP-010: 主窗显示后再创建准心窗口（原先在 __init__ 里同步做，占 344ms）。"""
        try:
            if getattr(self, "_is_closing", False):
                return
            # 期间用户可能已经手动关掉了准心
            if not self.config.crosshair_enabled:
                return
            self.logger.info("准心已启用，自动显示")
            self.crosshair_animation.show_crosshair()
        except Exception as exc:
            self.logger.warning(f"准心延迟显示失败: {exc}")

    def showEvent(self, event):
        """UP-009: 从托盘/最小化恢复时立刻补一次状态刷新。

        定时刷新在不可见时会跳过，若不在这里补一次，用户重新打开窗口会先看到
        一份最长 15 秒前的旧状态。延迟 0ms 入队，不占本次显示帧。
        """
        super().showEvent(event)
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._refresh_system_status_strip)
        except Exception:
            pass

    def _tick_system_status_strip(self):
        """定时器入口（UP-009）：不可见时直接跳过，不做任何磁盘 I/O。

        收进托盘 / 最小化时用户看不到状态条，没有任何理由为它付主线程 I/O。
        重新显示时由 showEvent 立刻补一次刷新，用户不会看到过期数据。
        """
        try:
            if getattr(self, "_is_closing", False):
                return
            if not self.isVisible() or self.isMinimized():
                return
        except Exception:
            # 守卫本身抛异常(窗口已析构等)时不要 fail-open 去干那份重活——
            # 那正是我们要避开的主线程磁盘 I/O。跳过这一拍即可,下一拍再说。
            return
        self._refresh_system_status_strip()

    def _refresh_system_status_strip(self):
        status_label = getattr(self, "system_status_label", None)
        gsi_badge = getattr(self, "basic_gsi_badge", None)
        audio_badge = getattr(self, "basic_audio_badge", None)
        config_badge = getattr(self, "basic_config_badge", None)
        if status_label is None and gsi_badge is None and audio_badge is None and config_badge is None:
            return
        try:
            status = collect_runtime_status(self)
            gsi = status.gsi or {}
            audio = status.audio_health or {}
            gsi_running = bool(gsi.get("running"))
            audio_issue_count = int(audio.get("missing_directories", 0) or 0) + int(
                audio.get("invalid_config_refs", 0) or 0
            )
            audio_ok = bool(audio.get("ok"))
            config_dirty = bool(status.config_dirty)

            if gsi_badge is not None:
                # 对标修缮：GSI 启动失败（如端口被占）必须可见且带原因——
                # 此前 startup_error 已被采集但无任何 UI 消费，用户只见"未运行"。
                gsi_error = str(gsi.get("startup_error") or "")
                if gsi_error:
                    self._set_badge_label_state(gsi_badge, "GSI · 启动失败", "danger")
                    gsi_badge.setToolTip(f"{gsi_error}\n处理后在高级设置重选 CS2 目录或重启软件即可恢复。")
                else:
                    self._set_badge_label_state(
                        gsi_badge,
                        "GSI · 运行中" if gsi_running else "GSI · 未运行",
                        "positive" if gsi_running else "info",
                    )
                    gsi_badge.setToolTip("")

            if audio_badge is not None:
                audio_text = "音频 · 正常" if audio_ok else (
                    f"音频 · 需检查{audio_issue_count}" if audio_issue_count else "音频 · 需检查"
                )
                self._set_badge_label_state(
                    audio_badge,
                    audio_text,
                    "positive" if audio_ok else "warning",
                )

            if config_badge is not None:
                self._set_badge_label_state(
                    config_badge,
                    "配置 · 已保存" if not config_dirty else "配置 · 未保存",
                    "positive" if not config_dirty else "warning",
                )

            if status.level == "error" and status.last_error:
                runtime_summary = f"系统状态异常：{status.last_error}。"
            elif not audio_ok:
                if audio_issue_count:
                    runtime_summary = f"音频资源需要检查，当前发现 {audio_issue_count} 项异常。"
                else:
                    runtime_summary = "音频资源需要检查，建议先运行体检。"
            elif config_dirty:
                runtime_summary = "检测到未保存的配置修改，确认无误后记得保存。"
            elif gsi_running:
                runtime_summary = "系统状态正常，联动服务已就绪。"
            else:
                runtime_summary = "系统状态正常，未进入游戏时 GSI 未运行属于正常情况。"

            detail_text = " | ".join(
                [
                    "GSI: 运行中" if gsi_running else "GSI: 未运行",
                    "音频: 正常" if audio_ok else (
                        f"音频: 异常{audio_issue_count}" if audio_issue_count else "音频: 异常"
                    ),
                    "配置: 未保存" if config_dirty else "配置: 已保存",
                    f"最近异常: {status.last_error or '无'}",
                ]
            )
            self._basic_runtime_summary = runtime_summary
            self._basic_runtime_status_detail = detail_text
            self._basic_runtime_level = str(getattr(status, "level", "ok") or "ok").lower()
            self._update_basic_status_summary_label()
            self.logger.debug(f"[SystemStatus] level={status.level} err={status.last_error}")
        except Exception as exc:
            self._basic_runtime_summary = f"状态刷新失败：{exc}"
            self._basic_runtime_status_detail = self._basic_runtime_summary
            self._basic_runtime_level = "error"
            if gsi_badge is not None:
                self._set_badge_label_state(gsi_badge, "GSI · 刷新失败", "danger")
            if audio_badge is not None:
                self._set_badge_label_state(audio_badge, "音频 · 刷新失败", "danger")
            if config_badge is not None:
                self._set_badge_label_state(config_badge, "配置 · 刷新失败", "danger")
            self._update_basic_status_summary_label()

    def _run_audio_health_from_home(self):
        self._run_audio_health_check()
        self._refresh_system_status_strip()
        self.show_page("audio_health")

    def _open_log_directory(self):
        from resource_manager import ResourceManager
        import os

        log_dir = ResourceManager.get_app_data_path("logs")
        os.makedirs(log_dir, exist_ok=True)
        try:
            os.startfile(log_dir)  # type: ignore[attr-defined]
        except Exception as exc:
            self.logger.warning(f"Open log dir failed: {exc}")

    def _set_badge_label_state(self, label, text, tone="info"):
        if label is None:
            return
        label.setText(text)
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _update_basic_status_summary_label(self):
        status_label = getattr(self, "system_status_label", None)
        if status_label is None:
            return
        runtime_summary = str(getattr(self, "_basic_runtime_summary", "") or "").strip()
        if not runtime_summary:
            runtime_summary = "状态会在这里同步更新，未进入游戏时 GSI 未运行属于正常情况。"
        status_label.setText(runtime_summary)
        detail_text = str(getattr(self, "_basic_runtime_status_detail", "") or "").strip()
        status_label.setToolTip(detail_text or runtime_summary)
        status_card = getattr(self, "basic_status_card", None)
        if status_card is not None:
            status_card.setToolTip(detail_text or runtime_summary)
        status_badge_bar = getattr(self, "basic_status_badge_label", None)
        if status_badge_bar is not None:
            badges = []
            for attr_name in (
                "basic_theme_badge",
                "basic_mode_badge",
                "basic_gsi_badge",
                "basic_audio_badge",
                "basic_config_badge",
            ):
                label = getattr(self, attr_name, None)
                if label is None:
                    continue
                text = str(label.text() or "").strip()
                if not text:
                    continue
                badges.append((str(label.property("tone") or "info"), text))
            render_badges(status_badge_bar, badges, detail_tooltip=detail_text or runtime_summary)
        level = str(getattr(self, "_basic_runtime_level", "ok") or "ok").lower()
        status_label.setHidden(level not in {"warn", "error"})

    def _sync_basic_page_overview(self):
        theme_badge = getattr(self, "basic_theme_badge", None)
        if theme_badge is not None:
            theme_text = self.theme_combo.currentText().strip() if hasattr(self, "theme_combo") else ""
            if not theme_text:
                theme_text = getattr(self.config, "ui_theme", "dark")
            self._set_badge_label_state(theme_badge, f"主题 · {theme_text}", "info")

        mode_badge = getattr(self, "basic_mode_badge", None)
        if mode_badge is not None:
            is_expert = bool(getattr(self.config, "ui_expert_mode", False))
            mode_text = "专家模式" if is_expert else "普通模式"
            mode_tone = "warning" if is_expert else "positive"
            self._set_badge_label_state(mode_badge, f"界面 · {mode_text}", mode_tone)

        self._update_basic_status_summary_label()

    # ---------------- P4.1: 首次使用引导 ----------------

    def _maybe_show_onboarding(self):
        try:
            if bool(getattr(self.config, "onboarding_completed", True)):
                return
            if getattr(self, "_is_closing", False):
                return
            from dialogs.onboarding_dialog import OnboardingDialog

            dialog = OnboardingDialog(self)
            self._onboarding_dialog = dialog  # 防 GC
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            self.logger.info("首次使用引导已弹出")
        except Exception:
            self.logger.exception("首次引导弹出失败（忽略）")
            # 失败也标记完成，避免反复尝试
            try:
                self.config.onboarding_completed = True
                self.config.save_config()
            except Exception:
                pass

    # ---------------- P3.2: 崩溃日志自愿上报 ----------------

    def _maybe_prompt_crash_report(self):
        """发现新崩溃日志时询问用户是否发送；任何分支都不自动上传。"""
        try:
            if str(getattr(self.config, "crash_report_prompt", "ask")) == "never":
                return
            from core.crash_reporter import find_new_crash_logs, read_report_text

            logs = find_new_crash_logs(float(getattr(self.config, "crash_report_last_ts", 0.0)))
            if not logs:
                return
            newest_ts = max(p.stat().st_mtime for p in logs)
            report_text = read_report_text(logs[-3:])  # 最多带最近 3 份
            preview = "\n".join(report_text.splitlines()[:20])

            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QMessageBox

            # 对标修缮：改为非模态——模态 exec 会在启动 12 秒后打断正在
            # 操作的用户（本轮离屏审查中它直接卡死了渲染事件循环，实证）。
            box = QMessageBox(self)
            box.setWindowTitle("发现崩溃记录")
            box.setIcon(QMessageBox.Question)
            box.setText(f"上次运行检测到 {len(logs)} 份崩溃日志。是否发送给开发者帮助修复？")
            box.setInformativeText("仅发送崩溃堆栈文本（不含任何个人隐私信息）。")
            box.setDetailedText(preview)
            send_btn = box.addButton("发送并帮助改进", QMessageBox.AcceptRole)
            box.addButton("本次不发", QMessageBox.RejectRole)
            never_btn = box.addButton("不再询问", QMessageBox.DestructiveRole)
            box.setWindowModality(Qt.NonModal)

            def _on_choice(clicked, _newest=newest_ts, _text=report_text):
                try:
                    # 无论选择如何，本批日志都标记为已处理（避免每次启动重复打扰）
                    self.config.crash_report_last_ts = float(_newest)
                    if clicked is never_btn:
                        self.config.crash_report_prompt = "never"
                    self.config.save_config()
                    if clicked is send_btn:
                        self._send_crash_report_async(_text)
                except Exception:
                    self.logger.exception("崩溃上报选择处理异常（忽略）")

            box.buttonClicked.connect(_on_choice)
            self._crash_prompt_box = box  # 防 GC
            box.show()
        except Exception:
            self.logger.exception("崩溃上报询问流程异常（忽略）")

    def _send_crash_report_async(self, report_text):
        from config import VERSION

        def _worker():
            try:
                from core.crash_reporter import send_crash_report

                result = send_crash_report(report_text, VERSION)
                if result is True:
                    self.logger.info("崩溃报告已发送")
                    self.show_toast_safe("崩溃报告已发送，感谢反馈！", "success", 2600)
                elif result is None:
                    self.logger.info("后端暂未提供崩溃上报接口(404)，日志保留在本地")
                else:
                    self.logger.warning("崩溃报告发送失败，日志保留在本地")
                    self.show_toast_safe("发送失败，日志已保留在本地", "warning", 2600)
            except Exception:
                self.logger.exception("崩溃报告发送异常（忽略）")

        threading.Thread(target=_worker, name="CrashReportSender", daemon=True).start()

    def _apply_expert_mode_visibility(self):
        is_expert = bool(getattr(self.config, "ui_expert_mode", False))
        for page_id in self._expert_only_pages:
            btn = self.nav_buttons.get(page_id) if hasattr(self, "nav_buttons") else None
            if btn is not None:
                btn.setVisible(is_expert)
        if hasattr(self, "system_status_health_btn"):
            self.system_status_health_btn.setVisible(is_expert)
        if hasattr(self, "system_status_open_health_btn"):
            self.system_status_open_health_btn.setVisible(is_expert)
        if hasattr(self, "audio_task_panel_quick_btn"):
            self.audio_task_panel_quick_btn.setVisible(is_expert)
        if hasattr(self, "_sync_home_tool_rows"):
            self._sync_home_tool_rows()
        if hasattr(self, "_sync_basic_page_overview"):
            self._sync_basic_page_overview()

    def _on_ui_mode_changed(self, _index):
        is_expert = bool(self.ui_mode_combo.currentData())
        self.config.ui_expert_mode = is_expert
        self.config.save_config()
        self._apply_expert_mode_visibility()
        if not is_expert:
            current_page = None
            if hasattr(self, "content_stack") and self.content_stack.currentWidget():
                for pid, widget in self.pages.items():
                    if widget is self.content_stack.currentWidget():
                        current_page = pid
                        break
            if current_page in self._expert_only_pages:
                self.show_page("basic")
    
    def _setup_window_size(self):
        """根据屏幕分辨率智能设置窗口大小"""
        try:
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()

            if self._compact_mode:
                # 紧凑模式：固定 860x640，居中
                if screen:
                    geo = screen.availableGeometry()
                    x = geo.x() + (geo.width() - 860) // 2
                    y = geo.y() + (geo.height() - 640) // 2
                    self.setGeometry(x, y, 860, 640)
                else:
                    self.resize(860, 640)
                return

            if screen:
                available_geometry = screen.availableGeometry()
                screen_width = available_geometry.width()
                screen_height = available_geometry.height()

                self.logger.info(f"检测到屏幕分辨率: {screen_width}x{screen_height}")

                window_width = max(1200, min(1600, int(screen_width * 0.8)))
                window_height = max(800, min(1000, int(screen_height * 0.85)))

                x = (screen_width - window_width) // 2
                y = (screen_height - window_height) // 2

                self.setGeometry(x, y, window_width, window_height)
                self.logger.info(f"窗口大小已设置为: {window_width}x{window_height}, 位置: ({x}, {y})")

                if screen_width >= 1920 and screen_height >= 1080:
                    self.logger.info("检测到高分辨率屏幕，使用更大的窗口")
            else:
                self.resize(1200, 800)
                self.logger.warning("无法获取屏幕信息，使用默认窗口大小 1200x800")

        except Exception as e:
            self.resize(1200, 800)
            self.logger.error(f"设置窗口大小失败: {e}，使用默认大小")
    
    def moveEvent(self, event):
        """窗口移动事件：优化性能"""
        # 第一次移动时暂停定时器
        if not self._is_moving:
            self._is_moving = True
            if hasattr(self, 'player_id_timer') and self.player_id_timer.isActive():
                self.player_id_timer.stop()
        
        # 重置重启定时器（复用已创建的Timer对象）
        self._move_restart_timer.stop()
        self._move_restart_timer.start(500)
        
        super().moveEvent(event)
    
    def _on_move_finished(self):
        """窗口移动结束后的回调"""
        self._is_moving = False
        # 重启定时器
        if hasattr(self, 'player_id_timer'):
            self.player_id_timer.start(3000)
    
    def _disable_wheel_on_widgets(self):
        """递归为所有相关控件安装事件过滤器，禁用滚轮调整"""
        def install_filter_recursive(widget):
            """递归遍历所有子控件"""
            for child in widget.findChildren(QWidget):
                # 为特定类型的控件安装事件过滤器
                if isinstance(child, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
                    child.installEventFilter(self)
                    child.setFocusPolicy(Qt.StrongFocus)  # 确保可以通过点击获得焦点
        
        # 为整个窗口的所有子控件安装过滤器
        install_filter_recursive(self)
        self.logger.info("已禁用滚轮调整UI控件")
    
    def eventFilter(self, watched, event):
        """
        事件过滤器：
        1. 拦截滚轮事件，防止意外修改控件值——但把滚动转发给最近的可滚动祖先，
           否则光标停在下拉框/滑块上时整页都滚不动。

        R4/UP-025：这里原本还有第二套"卡片悬停阴影"控制器，已删除。
        `SettingsCard` 自己的 enterEvent/leaveEvent 已经在管这枚阴影
        （md_blur 24 ↔ lg_blur 40），两套控制器抢同一个 QGraphicsDropShadowEffect：
        eventFilter 先于控件自身的事件处理跑，Leave 时把 alpha 直接写成 30，
        而 SettingsCard 的动画只回滚 blur、不回滚 alpha。默认 md_alpha 是 120，
        于是鼠标**扫过一次**卡片，阴影就永久变成原来的 1/4，再也回不来。
        阴影所有权归 SettingsCard 唯一持有。
        """
        if event.type() == QEvent.Wheel:
            # 对于这些控件类型，不让滚轮改值
            if isinstance(watched, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
                # 控件未聚焦时：把滚轮转发给可滚动父容器，保证页面仍能滚动
                if not watched.hasFocus():
                    self._forward_wheel_to_scroll_area(watched, event)
                    return True  # 控件本身不处理（值不变）
        # S5: 空搜索框聚焦时给出路。放在这里而不是另写一个 eventFilter——
        # 同名方法后定义的会把上面整套滚轮拦截全部覆盖掉。
        try:
            self._search_box_focus_in(watched, event)
        except Exception:
            pass
        return super().eventFilter(watched, event)

    def _forward_wheel_to_scroll_area(self, widget, event):
        """把控件上的滚轮事件转发给最近的可滚动祖先。

        作用：滚轮不会误改下拉框/数字框/滑块的值，但页面照常滚动。
        逐级向上找 QAbstractScrollArea，把同一个 Wheel 事件发给它的 viewport。
        任何异常都静默吞掉——转发失败最多是"滚不动"，绝不能阻塞 UI。
        """
        try:
            from PySide6.QtWidgets import QAbstractScrollArea, QApplication
        except Exception:
            return
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                viewport = parent.viewport()
                if viewport is not None:
                    try:
                        QApplication.sendEvent(viewport, event)
                    except Exception:
                        pass
                return
            parent = parent.parentWidget()

    def _install_wheel_filter_on_widget(self, widget):
        """为指定控件及其所有子控件安装滚轮事件过滤器"""
        for child in widget.findChildren(QWidget):
            if isinstance(child, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
                child.installEventFilter(self)
                child.setFocusPolicy(Qt.StrongFocus)
    
    def _create_ui(self):
        """创建UI"""
        ds = get_design_system()
        # 主容器
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # 主布局（垂直，为播放控制栏留位置）
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 顶部内容区（侧边栏 + 页面内容）
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 创建侧边栏
        self.sidebar = self._create_sidebar()
        content_layout.addWidget(self.sidebar)

        # 右侧区域（汉堡按钮 + 内容堆栈）
        right_widget = QWidget()
        right_widget.setObjectName("rightShell")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # 紧凑模式顶栏（汉堡菜单按钮）
        self._compact_header = QWidget()
        self._compact_header.setFixedHeight(50)
        self._compact_header.setObjectName("compactHeader")
        compact_header_layout = QHBoxLayout(self._compact_header)
        compact_header_layout.setContentsMargins(ds.spacing.lg, 6, ds.spacing.lg, 6)
        compact_header_layout.setSpacing(10)

        self._hamburger_btn = QPushButton("☰")
        self._hamburger_btn.setObjectName("hamburgerButton")
        self._hamburger_btn.setFixedSize(38, 38)
        self._hamburger_btn.setCursor(Qt.PointingHandCursor)
        self._hamburger_btn.clicked.connect(self._toggle_sidebar_overlay)
        compact_header_layout.addWidget(self._hamburger_btn)

        self._compact_title = QLabel("基础设置")
        self._compact_title.setObjectName("compactTitle")
        self._compact_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        compact_header_layout.addWidget(self._compact_title)
        compact_header_layout.addStretch()

        # 对标主流：顶栏设置搜索（27页/389项配置不再靠记忆翻页）；Ctrl+F 聚焦
        self._create_settings_search_box()
        compact_header_layout.addWidget(self.settings_search_box)

        # 窗口模式切换按钮（两种模式都显示）
        self._mode_toggle_btn = QPushButton("⇔")
        self._mode_toggle_btn.setObjectName("modeToggleButton")
        self._mode_toggle_btn.setFixedSize(38, 38)
        self._mode_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._mode_toggle_btn.setToolTip("切换紧凑/完整模式")
        self._mode_toggle_btn.clicked.connect(self._toggle_compact_mode)
        compact_header_layout.addWidget(self._mode_toggle_btn)

        right_layout.addWidget(self._compact_header)

        # 创建内容区域
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentArea")
        self.content_stack.setAutoFillBackground(True)
        right_layout.addWidget(self.content_stack, 1)

        content_layout.addWidget(right_widget, 1)

        main_layout.addWidget(content_widget, 1)

        # 保存主布局引用，用于延迟添加音乐控制栏
        self._main_layout = main_layout
        self._content_widget = content_widget

        # 创建侧边栏浮层（紧凑模式用）
        self._sidebar_overlay = None
        self._overlay_bg = None
        self._overlay_buttons = {}

        # 应用初始紧凑模式状态
        self._apply_compact_mode(self._compact_mode, animate=False)

        # 创建页面
        self.pages = {}
        self._create_pages()
        
        # 初始化页面过渡管理器
        self.page_transition = create_page_transition(self.content_stack)
        # R1-3: 应用内快捷键(Ctrl+1..4 切分组 / F1 帮助 / Esc 收起)
        self._init_global_shortcuts()
        self.logger.info("页面过渡管理器已初始化")
        
        # 初始化Toast管理器的父窗口
        self.toast_manager.set_parent(self)
        self._toast_signal.connect(self._show_toast_slot)
        self.logger.info("Toast管理器已初始化")

        # UP-035: 订阅配置重载广播
        self._config_reloaded_signal.connect(self._on_config_reloaded)
        try:
            from core.config_reload_bus import subscribe

            subscribe(self._config_reload_bridge)
        except Exception:
            self.logger.exception("配置重载广播订阅失败（预设应用后页面将不会自动刷新）")

        # 应用统一样式系统（为组件设置objectName以匹配QSS选择器）
        try:
            apply_unified_styles(self)
        except Exception as e:
            self.logger.error(f"主窗口应用统一样式失败: {e}")

        # 应用主题样式表
        self._apply_style()
        
        # 添加现代化效果（涟漪、微光等）
        self._apply_modern_effects()
        
        # 显示第一个页面（无动画）
        self.show_page("basic", animated=False)

    @Slot(str, str, int)
    def _show_toast_slot(self, message, toast_type, duration):
        """Toast 信号的槽函数（在主线程执行）"""
        self.toast_manager.show(message, toast_type, duration)

    def show_toast_safe(self, message, toast_type="info", duration=3000):
        """线程安全的 Toast，可从任何线程调用"""
        self._toast_signal.emit(message, toast_type, duration)

    def _create_sidebar(self):
        """创建侧边栏"""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        # v2.2 紧凑化：220 → 200，给主内容区多 20px
        sidebar.setFixedWidth(200)
        sidebar.setFrameShape(QFrame.StyledPanel)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部固定区域（标题和版本）— v2.2 紧凑化：高度 96 → 76
        header_widget = QWidget()
        header_widget.setObjectName("sidebarBrand")
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(14, 16, 14, 10)
        header_layout.setSpacing(2)

        # 标题
        title = QLabel("帆派助手")
        title.setObjectName("sidebarTitleLabel")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)

        # 版本
        version = QLabel(f"v{VERSION}")
        version.setObjectName("sidebarVersionLabel")
        version.setFont(QFont("Microsoft YaHei", 9))
        version.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(version)

        header_layout.addSpacing(6)
        
        layout.addWidget(header_widget)
        
        # 可滚动的导航区域
        scroll_area = QScrollArea()
        scroll_area.setObjectName("sidebarScroll")  # 避免与外层sidebar重名
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 导航按钮容器
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(10, 10, 10, 10)
        nav_layout.setSpacing(5)
        
        # 导航按钮 - 可折叠分组
        nav_groups = [
            ("音效设置", [
                ("basic", "基础设置"),
                ("kill_sound", "击杀音效"),
                ("kill_voice", "击杀语音"),
                ("death_sound", "被击杀音效"),
                ("gun_sound", "枪声设置"),
                ("switch_weapon", "切枪音效"),
                ("reload_sound", "换弹音效"),
                ("special_sound", "特殊音效"),
            ]),
            ("视觉设置", [
                ("crosshair", "准心设置"),
                ("kill_icon", "击杀图标"),
                ("viewmodel", "局内视角"),
                ("magnifier", "开镜放大"),
                ("flash", "自定闪光"),
                ("hud_color", "HUD颜色"),
                ("screen_effects", "屏幕特效"),
            ]),
            ("媒体功能", [
                ("music", "音乐播放"),
                ("voice_output", "语音输出"),
            ]),
            ("工具与系统", [
                ("utility", "道具瞄点"),
                ("advanced", "高级设置"),
                ("audio_health", "音频体检"),
                ("audio_import_wizard", "资源导入向导"),
                ("audio_task_panel", "音频任务面板"),
                ("audio_replay", "音频事件回放"),
                ("config_snapshot", "配置快照"),
                ("preset_center", "预设中心"),
                ("about", "关于软件"),
            ]),
        ]

        self.nav_buttons = {}
        self.nav_groups = []
        self._page_to_group = {}  # page_id -> NavGroupWidget 映射
        self._page_names = {}  # page_id -> 显示名称
        # v5 Phase 5: 给每个导航按钮加 icon(替代之前用 4 空格占位)
        from widgets.icon_provider import get_page_icon
        for group_title, items in nav_groups:
            group_widget = NavGroupWidget(group_title)
            nav_layout.addWidget(group_widget)
            self.nav_groups.append(group_widget)

            for page_id, text in items:
                self._page_names[page_id] = text
                btn = QPushButton(f"  {text}")
                btn.setObjectName("navButton")
                btn.setCheckable(True)
                btn.setMinimumHeight(36)
                # v5 Phase 5: 侧栏 icon
                icon = get_page_icon(page_id, role="secondary", size=16)
                if not icon.isNull():
                    btn.setIcon(icon)
                    btn.setIconSize(QSize(16, 16))
                btn.clicked.connect(lambda checked, pid=page_id: self.show_page(pid))
                group_widget.add_button(btn)
                self.nav_buttons[page_id] = btn
                self._page_to_group[page_id] = group_widget
        
        # R1-6: 「常用」动态分组(本地使用频次 Top4,启动时计算,会话内只记录不重排)
        self._frequent_buttons = {}
        self.frequent_group = None
        try:
            if bool(getattr(self.config, "nav_frequent_enabled", True)):
                from core.page_usage_tracker import top_pages

                frequent_ids = top_pages(4, known_pages=self._page_names.keys())
                # 过滤专家模式门控页(非专家模式下不暴露入口)
                if not bool(getattr(self.config, "ui_expert_mode", False)):
                    frequent_ids = [p for p in frequent_ids if p not in self._expert_only_pages]
                if frequent_ids:
                    freq_group = NavGroupWidget("常用")
                    for page_id in frequent_ids:
                        text = self._page_names.get(page_id, page_id)
                        btn = QPushButton(f"  {text}")
                        btn.setObjectName("navButton")
                        btn.setCheckable(True)
                        btn.setMinimumHeight(36)
                        icon = get_page_icon(page_id, role="secondary", size=16)
                        if not icon.isNull():
                            btn.setIcon(icon)
                            btn.setIconSize(QSize(16, 16))
                        btn.clicked.connect(lambda checked, pid=page_id: self.show_page(pid))
                        freq_group.add_button(btn)
                        self._frequent_buttons[page_id] = btn
                    nav_layout.insertWidget(0, freq_group)
                    self.frequent_group = freq_group
        except Exception:
            self.logger.exception("常用分组初始化失败(侧栏按默认分组继续)")

        nav_layout.addStretch()
        
        scroll_area.setWidget(nav_container)
        layout.addWidget(scroll_area, 1)

        # 侧边栏底部：紧凑模式切换按钮
        sidebar_footer = QWidget()
        sidebar_footer.setObjectName("sidebarFooter")
        sidebar_footer_layout = QHBoxLayout(sidebar_footer)
        sidebar_footer_layout.setContentsMargins(12, 10, 12, 12)
        self._sidebar_mode_btn = QPushButton("紧凑模式  «")
        self._sidebar_mode_btn.setObjectName("modeToggleButton")
        self._sidebar_mode_btn.setFixedHeight(36)
        self._sidebar_mode_btn.setCursor(Qt.PointingHandCursor)
        self._sidebar_mode_btn.clicked.connect(self._toggle_compact_mode)
        sidebar_footer_layout.addWidget(self._sidebar_mode_btn)
        layout.addWidget(sidebar_footer)

        self._apply_expert_mode_visibility()

        return sidebar

    def _normalize_layout_metrics(self, layout, margin_map=None, spacing_map=None):
        """按映射表轻量校准布局节奏，避免大范围重排。"""
        if layout is None:
            return

        if margin_map:
            margins = layout.contentsMargins()
            current = (margins.left(), margins.top(), margins.right(), margins.bottom())
            target = margin_map.get(current)
            if target:
                layout.setContentsMargins(*target)

        if spacing_map:
            current_spacing = layout.spacing()
            target_spacing = spacing_map.get(current_spacing)
            if target_spacing is not None:
                layout.setSpacing(target_spacing)

    def _harmonize_page_chrome(self, page):
        """保守统一页面根层与卡片节奏，不触碰业务布局结构。"""
        root_margin_map = {
            # 底部音乐栏常驻时，去掉页面底部冗余留白，避免出现一条突兀的暗色缝隙。
            (20, 20, 20, 20): (24, 20, 24, 0),
            (24, 20, 24, 20): (24, 20, 24, 0),
            (24, 20, 24, 24): (24, 20, 24, 0),
        }
        root_spacing_map = {
            15: 16,
        }
        card_margin_map = {
            (20, 20, 20, 20): (18, 18, 18, 18),
            (16, 14, 16, 14): (18, 18, 18, 18),
            (15, 15, 15, 15): (18, 18, 18, 18),
            (25, 25, 25, 25): (18, 18, 18, 18),
        }
        card_spacing_map = {
            10: 12,
            15: 14,
            20: 16,
        }

        self._normalize_layout_metrics(page.layout(), root_margin_map, root_spacing_map)

        for scroll in page.findChildren(QScrollArea):
            content = scroll.widget()
            if content is not None:
                self._normalize_layout_metrics(content.layout(), root_margin_map, root_spacing_map)

        for card in page.findChildren(QFrame):
            if card.objectName() == "card":
                self._normalize_layout_metrics(card.layout(), card_margin_map, card_spacing_map)
    
    def _create_pages(self):
        """创建页面（懒加载模式：只初始化 basic 页面）"""
        # 只创建 basic 页面，其他页面按需加载
        import time as _ct

        _t0 = _ct.perf_counter()
        self.pages["basic"] = self._create_basic_page()
        self._harmonize_page_chrome(self.pages["basic"])
        self.content_stack.addWidget(self.pages["basic"])
        self._loaded_pages.add("basic")
        # 用与 _load_page 相同的日志格式:basic 是启动关键路径上唯一同步构建的页
        # (落在 [启动相位] 主窗构建 那 1.9~5.0s 里),原先没这行,ui_perf_probe 的
        # 建页耗时排行会整条漏掉它——而它恰恰是最该优化的那一页。
        self.logger.info(
            f"[懒加载] 页面 basic 加载完成 ({(_ct.perf_counter() - _t0) * 1000:.0f}ms)"
        )
    
    def _load_page(self, page_id):
        """懒加载页面"""
        if self._is_closing:
            return
        if page_id in self._loaded_pages:
            return  # 已加载，跳过
        import time as _lt

        _load_t0 = _lt.perf_counter()
        
        self.logger.info(f"[懒加载] 创建页面: {page_id}")
        
        # 创建页面实例（延迟导入，加速启动）
        page = None
        if page_id == "basic":
            page = self._create_basic_page()
        elif page_id == "kill_sound":
            from pages.kill_sound_page import KillSoundPage
            page = KillSoundPage()
        elif page_id == "kill_voice":
            from pages.kill_voice_page import KillVoicePage
            page = KillVoicePage()
        elif page_id == "kill_icon":
            from pages.kill_icon_page import KillIconPage
            page = KillIconPage()
            page.set_kill_icon_player(self.kill_icon_player)
        elif page_id == "crosshair":
            from pages.crosshair_page import CrosshairPage
            page = CrosshairPage()
            page.set_crosshair_animation(self.crosshair_animation)
        elif page_id == "death_sound":
            from pages.death_sound_page import DeathSoundPage
            page = DeathSoundPage()
        elif page_id == "gun_sound":
            from pages.gun_sound_page import GunSoundPage
            page = GunSoundPage()
        elif page_id == "switch_weapon":
            from pages.switch_weapon_page import SwitchWeaponPage
            page = SwitchWeaponPage()
        elif page_id == "reload_sound":
            from pages.reload_sound_page import ReloadSoundPage
            page = ReloadSoundPage()
        elif page_id == "special_sound":
            from pages.special_sound_page import SpecialSoundPage
            page = SpecialSoundPage()
        elif page_id == "viewmodel":
            from pages.viewmodel_page import ViewmodelPage
            page = ViewmodelPage()
        elif page_id == "music":
            from pages.music_page import MusicPage
            page = MusicPage()
        elif page_id == "voice_output":
            from pages.voice_output_page import VoiceOutputPage
            page = VoiceOutputPage()
        elif page_id == "utility":
            from pages.utility_page import UtilityPage
            page = UtilityPage()
        elif page_id == "magnifier":
            from pages.magnifier_page import MagnifierPage
            page = MagnifierPage(self.config)
            page.set_crosshair_component(self.crosshair_animation)
        elif page_id == "flash":
            from pages.flash_page import FlashPage
            page = FlashPage()
        elif page_id == "hud_color":
            from pages.hud_color_page import HudColorPage
            page = HudColorPage()
        elif page_id == "screen_effects":
            from pages.screen_effects_page import ScreenEffectsPage
            page = ScreenEffectsPage(self.screen_effect_overlay)
        elif page_id == "advanced":
            from pages.advanced_page import AdvancedPage
            page = AdvancedPage()
        elif page_id == "audio_health":
            from pages.audio_health_page import AudioHealthPage
            page = AudioHealthPage()
        elif page_id == "audio_import_wizard":
            from pages.audio_import_wizard_page import AudioImportWizardPage
            page = AudioImportWizardPage()
        elif page_id == "audio_task_panel":
            from pages.audio_task_panel_page import AudioTaskPanelPage
            page = AudioTaskPanelPage()
        elif page_id == "audio_replay":
            from pages.audio_replay_page import AudioReplayPage
            page = AudioReplayPage()
        elif page_id == "config_snapshot":
            from pages.config_snapshot_page import ConfigSnapshotPage
            page = ConfigSnapshotPage()
        elif page_id == "preset_center":
            from pages.preset_center_page import PresetCenterPage
            page = PresetCenterPage()
        elif page_id == "about":
            from pages.about_page import AboutPage
            page = AboutPage()
        
        if page:
            # 为页面根widget设置objectName（如果还没有设置的话）
            if not page.objectName():
                page.setObjectName("contentPage")
            
            # 设置自动填充背景（确保背景色正确显示）
            page.setAutoFillBackground(True)
            self._harmonize_page_chrome(page)
            
            # 添加页面到堆栈
            self.content_stack.addWidget(page)
            self.pages[page_id] = page
            self._loaded_pages.add(page_id)

            # 应用统一样式（为组件设置objectName以匹配QSS选择器）
            try:
                apply_unified_styles(page)
            except Exception as e:
                self.logger.error(f"[懒加载] 页面 {page_id} 应用样式失败: {e}")

            # 为新加载的页面安装滚轮事件过滤器
            self._install_wheel_filter_on_widget(page)

            self.logger.info(
                f"[懒加载] 页面 {page_id} 加载完成 ({(_lt.perf_counter() - _load_t0) * 1000:.0f}ms)"
            )

    def _preload_remaining_pages(self):
        """后台静默预加载所有未加载的页面（逐个加载，不阻塞UI）"""
        if self._is_closing:
            return
        all_page_ids = [
            "kill_sound", "kill_voice", "death_sound", "gun_sound",
            "switch_weapon", "reload_sound", "special_sound",
            "crosshair", "kill_icon", "magnifier", "flash", "viewmodel", "hud_color", "screen_effects",
            "music", "voice_output",
            "utility", "advanced", "audio_health", "audio_import_wizard",
            "audio_task_panel", "audio_replay", "config_snapshot", "preset_center",
            "about",
        ]
        if not bool(getattr(self.config, "ui_expert_mode", False)):
            all_page_ids = [pid for pid in all_page_ids if pid not in self._expert_only_pages]
        preload_candidates = [pid for pid in all_page_ids if pid not in self._preload_skip_pages]
        self._preload_queue = [pid for pid in preload_candidates if pid not in self._loaded_pages]
        self.logger.info(f"[预加载] 开始静默预加载 {len(self._preload_queue)} 个页面")
        self._preload_next()

    def _preload_next(self):
        """加载队列中的下一个页面"""
        if self._is_closing:
            self._preload_queue = []
            return
        if not self._preload_queue:
            self.logger.info("[预加载] 所有页面预加载完成")
            return
        page_id = self._preload_queue.pop(0)
        try:
            self._load_page(page_id)
        except Exception as e:
            self.logger.error(f"[预加载] 页面 {page_id} 加载失败: {e}")
        # 间隔 50ms 加载下一个，保持 UI 流畅
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._preload_next)

    def _create_music_control_bar(self):
        """延迟创建音乐控制栏（避免pygame导入阻塞首屏渲染;幂等,双触发安全）"""
        if getattr(self, "music_control_bar", None) is not None:
            return
        try:
            from music_control_bar import MusicControlBar
            self.music_control_bar = MusicControlBar(self)
            self.music_control_bar.open_music_page.connect(lambda: self.show_page("music"))
            self._main_layout.addWidget(self.music_control_bar)
            self.logger.info("音乐控制栏已创建")
        except Exception as e:
            self.logger.error(f"创建音乐控制栏失败: {e}")

    def _initial_theme_refresh(self):
        """初始主题刷新（修复首次启动时主题加载问题）"""
        try:
            self.logger.info("执行初始主题刷新...")
            
            # 刷新所有已加载的页面（只完整刷新当前可见页面，其他延迟刷新）
            current_widget = self.content_stack.currentWidget() if hasattr(self, 'content_stack') else None
            for page_id in self._loaded_pages:
                if page_id in self.pages:
                    page = self.pages[page_id]
                    # 强制重新应用样式
                    page.style().unpolish(page)
                    page.style().polish(page)
                    page.update()  # 异步重绘

                    # 只对当前可见页面做递归刷新，其他页面标记为需要刷新
                    if page is current_widget:
                        self._recursive_refresh_widget(page)
                    else:
                        self._pages_need_theme_refresh.add(page_id)
            
            # 刷新侧边栏及其子组件
            if hasattr(self, 'sidebar'):
                self.sidebar.style().unpolish(self.sidebar)
                self.sidebar.style().polish(self.sidebar)
                self.sidebar.update()  # 异步重绘
                self._recursive_refresh_widget(self.sidebar)
            
            # 刷新音乐控制栏及其子组件
            if hasattr(self, 'music_control_bar'):
                self.music_control_bar.style().unpolish(self.music_control_bar)
                self.music_control_bar.style().polish(self.music_control_bar)
                self.music_control_bar.update()  # 异步重绘
                self._recursive_refresh_widget(self.music_control_bar)
            
            self.logger.info("初始主题刷新完成")
        except Exception as e:
            self.logger.error(f"初始主题刷新失败: {e}")
    
    def _delayed_page_refresh(self, page, page_id):
        """延迟刷新页面样式（确保样式正确应用）"""
        try:
            # 再次强制刷新样式
            page.style().unpolish(page)
            page.style().polish(page)
            page.update()  # 异步重绘
            
            # 递归刷新所有子组件（包括深层嵌套的组件）
            self._recursive_refresh_widget(page)
            
            self.logger.info(f"[懒加载] 页面 {page_id} 延迟刷新完成")
        except Exception as e:
            self.logger.error(f"[懒加载] 页面 {page_id} 延迟刷新失败: {e}")
    
    def _recursive_refresh_widget(self, widget):
        """优化版：只刷新带objectName的关键组件"""
        try:
            # 只刷新带objectName的关键组件，避免遍历所有子组件
            # findChildren会返回所有层级的子组件，无需手动递归
            for child in widget.findChildren(QWidget):
                # 只处理有objectName的组件（这些通常是需要样式的关键组件）
                if child.objectName():
                    try:
                        child.style().unpolish(child)
                        child.style().polish(child)
                        child.update()
                    except Exception:
                        pass  # 忽略单个组件错误
        except Exception as e:
            self.logger.warning(f"递归刷新组件失败: {e}")
    
    def ensure_page_loaded(self, page_id):
        """确保页面已加载（提供给BackgroundLoader调用）。

        返回 True=已就绪/本次已建；False=当前不宜构建，调用方稍后重试。

        UP-015: `_show_page_skeleton` 里的 processEvents 只挡用户输入，挡不住
        定时器回调——预载定时器会在"用户切页正在建骨架"的当口插进来同步建一整页，
        把用户那次切页硬生生再拖 200~600ms。这里统一把关：正在为用户建页时，
        所有后台预载一律让路。
        """
        if getattr(self, "_is_closing", False):
            return False
        if page_id in self._loaded_pages:
            return True
        if getattr(self, "_page_loading", False):
            return False  # 用户正在切页，后台让路
        self._load_page(page_id)
        return page_id in self._loaded_pages
    
    def is_page_loaded(self, page_id):
        """检查页面是否已加载"""
        return page_id in self._loaded_pages

    # ---------------- 2.2.0: 空闲预构建高频页(切页零等待) ----------------

    def start_idle_preload(self):
        """后台资源就绪后调用:按使用频次预构建高频页,主线程切片不卡交互。

        90% 的切页发生在少数几页上(page_usage 实证)——空闲时每 250ms
        建一页,用户真正点过去时页面已就绪,骨架屏只兜冷门页的底。
        """
        if getattr(self, "_idle_preload_started", False):
            return
        self._idle_preload_started = True

        candidates = []
        try:
            from core.page_usage_tracker import top_pages

            candidates = list(top_pages(4, known_pages=self._page_names.keys()))
        except Exception:
            pass
        # 新装机无统计时的兜底高频页(按品类常识)
        for fallback in ("kill_sound", "crosshair", "music"):
            if fallback not in candidates:
                candidates.append(fallback)

        expert_ok = bool(getattr(self.config, "ui_expert_mode", False))
        skip = getattr(self, "_preload_skip_pages", set())
        # 独立队列：不能与 _preload_remaining_pages 的 _preload_queue 共用，
        # 两条 QTimer 链同时消费一个队列会漏建/重复调度
        self._idle_preload_queue = [
            pid for pid in candidates
            if pid in self._page_names
            and pid not in self._loaded_pages
            and pid not in skip  # 构造即起热键/线程/子进程的页,不许静默预载
            and (expert_ok or pid not in self._expert_only_pages)
        ][:4]

        if self._idle_preload_queue:
            from PySide6.QtCore import QTimer

            self.logger.info(f"[空闲预构建] 计划: {', '.join(self._idle_preload_queue)}")
            QTimer.singleShot(400, self._preload_next_page)

    def _preload_next_page(self):
        """切片建一页,再排下一片;任何异常都不中断后续页。"""
        from PySide6.QtCore import QTimer

        if getattr(self, "_is_closing", False):
            return
        queue = getattr(self, "_idle_preload_queue", None)
        if not queue:
            self.logger.info("[空闲预构建] 全部完成")
            return

        # UP-005: 这条链是 2.2.0 就有的,不在 R2 新写的调度器里,原先没有任何
        # 空闲门控——用户正在操作时它照样每 250ms 同步建一页。既然本轮的目标就是
        # "别在用户操作时干这个",这里也一起接上让路逻辑。
        try:
            from core.utils.idle_watcher import get_idle_watcher
            watcher = get_idle_watcher()
            if watcher is not None and not watcher.is_idle(3.0):
                QTimer.singleShot(300, self._preload_next_page)
                return
        except Exception:
            pass

        pid = queue[0]
        if pid not in self._loaded_pages:
            import time as _t

            t0 = _t.perf_counter()
            try:
                # UP-015: 用户正在切页时 ensure_page_loaded 返回 False。
                # 原先忽略返回值 + 已 pop 出队 → 这一页被永久丢弃,
                # 而日志还谎报"就绪"。让路重试,页留在队首。
                if self.ensure_page_loaded(pid) is False:
                    QTimer.singleShot(300, self._preload_next_page)
                    return
                self.logger.info(
                    f"[空闲预构建] {pid} 就绪 ({(_t.perf_counter() - t0) * 1000:.0f}ms)"
                )
            except Exception:
                self.logger.exception(f"[空闲预构建] {pid} 失败(跳过)")
        queue.pop(0)

        QTimer.singleShot(250, self._preload_next_page)

    # ---------------- R1-5: 首次切页骨架屏(通用,27 页共享一份) ----------------

    def _get_page_skeleton(self):
        """惰性构建骨架页:页头条 + 3 张灰卡,样式跟随主题 token。"""
        skeleton = getattr(self, "_page_skeleton", None)
        if skeleton is not None:
            return skeleton

        from PySide6.QtWidgets import QSizePolicy

        ds = get_design_system()
        skeleton = QWidget()
        skeleton.setObjectName("contentPage")
        skeleton.setAutoFillBackground(True)
        lay = QVBoxLayout(skeleton)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(ds.spacing.lg)

        def _bone(height, width_ratio=1.0):
            bone = QFrame()
            bone.setObjectName("skeletonBone")
            bone.setFixedHeight(height)
            bone.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            bone.setStyleSheet(
                "QFrame#skeletonBone {"
                " background-color: rgba(127,127,127,0.16);"
                f" border-radius: {ds.radius.md}px;"
                " }"
            )
            if width_ratio < 1.0:
                bone.setMaximumWidth(int(560 * width_ratio))
            return bone

        lay.addWidget(_bone(30, 0.4))   # 标题
        lay.addWidget(_bone(16, 0.7))   # 导语
        for _ in range(3):              # 卡片
            lay.addWidget(_bone(120))
        lay.addStretch()

        try:
            from ui_shimmer import add_shimmer_effect

            add_shimmer_effect(skeleton, duration=1200, loop=True)
        except Exception:
            pass  # 微光失败就静态灰条,无伤大雅

        self._page_skeleton = skeleton
        self.content_stack.addWidget(skeleton)
        return skeleton

    def _show_page_skeleton(self):
        """构建重页前先把骨架亮出来;只放行绘制事件,不放行用户输入(防重入)。"""
        try:
            from PySide6.QtCore import QEventLoop
            from PySide6.QtWidgets import QApplication

            skeleton = self._get_page_skeleton()
            self.content_stack.setCurrentWidget(skeleton)
            skeleton.repaint()
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass
    
    def _create_basic_page(self):
        """创建基础设置页面"""
        ds = get_design_system()
        page = QWidget()
        page.setObjectName("contentPage")  # 设置objectName以应用主题背景色
        page.setAutoFillBackground(True)  # 设置自动填充背景
        layout = QVBoxLayout(page)
        # UP-045: 与其余 19 页对齐到内容左边界 216px。原为 (24,20,24,0),
        # 叠上 scroll_layout 未设边距时 Qt 默认的 9px,实测左边界 233px——
        # 全站唯一偏得最多的一页,切到基础设置时内容会横向跳 17px。
        layout.setContentsMargins(16, 16, 16, 0)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(ds.spacing.lg)
        
        # 页面标题行（标题说明 + 主题选择）
        header_row = QHBoxLayout()
        header_row.setSpacing(ds.spacing.lg)

        title_column = QVBoxLayout()
        title_column.setSpacing(6)

        title = QLabel("基础设置")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title_column.addWidget(title)

        lead_label = QLabel("把常用开关、状态确认和基础维护收在同一页，日常使用尽量像工具面板一样直接。")
        lead_label.setObjectName("pageLeadLabel")
        lead_label.setWordWrap(True)
        title_column.addWidget(lead_label)
        header_row.addLayout(title_column, 1)

        header_controls = QHBoxLayout()
        header_controls.setSpacing(8)
        theme_label = QLabel("主题")
        theme_label.setObjectName("hintLabel")
        header_controls.addWidget(theme_label, 0, Qt.AlignVCenter)

        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(130)
        theme_items = [
            ("深色", "dark"), ("浅色", "light"),
            ("墨绿", "green"), ("紫夜", "purple"),
            ("深海", "ocean"), ("暖橙", "warm"),
            ("玫瑰", "rose"), ("高对比", "contrast"),
            ("极简", "minimal"),
        ]
        for display_name, key in theme_items:
            self.theme_combo.addItem(display_name, key)

        current_theme = self.config.ui_theme if hasattr(self.config, 'ui_theme') else "dark"
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        header_controls.addWidget(self.theme_combo)
        header_row.addLayout(header_controls)

        scroll_layout.addLayout(header_row)

        # 帮助面板
        from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
        install_help_panel(header_row, scroll_layout, PAGE_HELP_TEXTS["basic"])

        status_card = self._create_card("运行面板")
        self.basic_status_card = status_card
        status_layout = status_card.layout()
        status_layout.setSpacing(10)

        status_top = QHBoxLayout()
        status_top.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_top.addWidget(status_title)
        status_top.addStretch()
        status_layout.addLayout(status_top)

        self.basic_status_badge_label = create_badge_label()
        status_layout.addWidget(self.basic_status_badge_label)

        self.basic_theme_badge = QLabel()
        self.basic_theme_badge.setObjectName("badgeLabel")
        self.basic_theme_badge.hide()

        self.basic_mode_badge = QLabel()
        self.basic_mode_badge.setObjectName("badgeLabel")
        self.basic_mode_badge.hide()

        self.basic_gsi_badge = QLabel()
        self.basic_gsi_badge.setObjectName("badgeLabel")
        self._set_badge_label_state(self.basic_gsi_badge, "GSI · 待刷新", "info")
        self.basic_gsi_badge.hide()

        self.basic_audio_badge = QLabel()
        self.basic_audio_badge.setObjectName("badgeLabel")
        self._set_badge_label_state(self.basic_audio_badge, "音频 · 待刷新", "info")
        self.basic_audio_badge.hide()

        self.basic_config_badge = QLabel()
        self.basic_config_badge.setObjectName("badgeLabel")
        self._set_badge_label_state(self.basic_config_badge, "配置 · 待刷新", "info")
        self.basic_config_badge.hide()

        self.system_status_label = QLabel("状态会在这里同步更新，未进入游戏时 GSI 未运行属于正常情况。")
        self.system_status_label.setObjectName("hintLabel")
        self.system_status_label.setWordWrap(True)
        status_layout.addWidget(self.system_status_label)

        self.home_primary_tools_row = QWidget()
        primary_tools_layout = QHBoxLayout(self.home_primary_tools_row)
        primary_tools_layout.setContentsMargins(0, 2, 0, 0)
        primary_tools_layout.setSpacing(8)

        self.system_status_refresh_btn = self._create_home_tool_button(
            "刷新状态",
            self._refresh_system_status_strip,
            tooltip="立即刷新首页系统状态",
        )
        primary_tools_layout.addWidget(self.system_status_refresh_btn)

        self.home_reload_audio_btn = self._create_home_tool_button(
            "载入音频",
            self._reload_audio,
            primary=True,
            tooltip="重新载入音频资源与配置",
        )
        primary_tools_layout.addWidget(self.home_reload_audio_btn)

        self.home_custom_folder_btn = self._create_home_tool_button(
            "自定义目录",
            self._open_custom_folder,
            tooltip="打开自定义资源文件夹",
        )
        primary_tools_layout.addWidget(self.home_custom_folder_btn)

        self.system_status_logs_btn = self._create_home_tool_button(
            "日志目录",
            self._open_log_directory,
            tooltip="打开运行日志目录",
        )
        primary_tools_layout.addWidget(self.system_status_logs_btn)
        primary_tools_layout.addStretch()
        status_layout.addWidget(self.home_primary_tools_row)

        self.home_expert_tools_row = QWidget()
        expert_tools_layout = QHBoxLayout(self.home_expert_tools_row)
        expert_tools_layout.setContentsMargins(0, 0, 0, 0)
        expert_tools_layout.setSpacing(8)

        self.system_status_health_btn = self._create_home_tool_button(
            "立即体检",
            self._run_audio_health_from_home,
            tooltip="运行音频体检并跳转查看结果",
        )
        expert_tools_layout.addWidget(self.system_status_health_btn)

        self.system_status_open_health_btn = self._create_home_tool_button(
            "体检页面",
            lambda: self.show_page("audio_health"),
            tooltip="打开音频体检页面",
        )
        expert_tools_layout.addWidget(self.system_status_open_health_btn)

        self.audio_task_panel_quick_btn = self._create_home_tool_button(
            "任务面板",
            lambda: self.show_page("audio_task_panel"),
            tooltip="打开音频任务面板",
        )
        expert_tools_layout.addWidget(self.audio_task_panel_quick_btn)
        expert_tools_layout.addStretch()
        status_layout.addWidget(self.home_expert_tools_row)
        scroll_layout.addWidget(status_card)

        # 功能开关卡片（桌面端使用更紧凑的3列布局）
        switches_card = self._create_card("功能开关")
        switches_layout = switches_card.layout()

        # 创建网格布局来实现自适应多列
        from PySide6.QtWidgets import QGridLayout
        from ui_toggle_switch import ToggleSwitch
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(14)
        grid_layout.setVerticalSpacing(6)
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(2, 1)

        # 功能开关
        self.switches = {}
        switch_configs = [
            ("kill_sound", "击杀音效", "kill_sound_enabled"),
            ("kill_voice", "击杀语音", "kill_voice_enabled"),
            ("kill_icon", "击杀图标", "kill_icon_enabled"),
            ("gun_sound", "枪声替换", "gun_sound_enabled"),
            ("death_sound", "被击杀修改", "death_sound_enabled"),
            ("switch_weapon", "切枪音效", "switch_weapon_sound_enabled"),
            ("reload_sound", "换弹音效", "reload_sound_enabled"),
            ("crosshair", "准心", "crosshair_enabled"),
            ("magnifier", "开镜放大", "magnifier_enabled"),
            ("flash", "自定闪光", "flash_enabled"),
            ("dynamic_hud", "动态HUD", "hud_rules_enabled"),
            ("screen_effects", "屏幕特效", "screen_effects_enabled"),
            ("music", "音乐联动", "music_enabled"),
            ("utility", "道具瞄点", "utility_guide_enabled"),
            ("voice_output", "语音播放", "voice_output_enabled"),
            ("spectator", "观战静音", "spectator_mode_mute"),
        ]

        for index, (switch_id, text, config_key) in enumerate(switch_configs):
            # 每个开关：标签 + 弹簧 + ToggleSwitch
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(2, 1, 2, 1)
            row_layout.setSpacing(6)

            label = self._create_home_switch_label(switch_id, text)
            row_layout.addWidget(label)
            row_layout.addStretch()

            toggle = ToggleSwitch(checked=getattr(self.config, config_key, False))
            toggle.toggled.connect(
                lambda checked, key=config_key: self._on_switch_changed(key, checked)
            )
            # 开关标签联动：打开时文字变 accent 色
            toggle._label = label
            toggle.toggled.connect(lambda checked, lbl=label: self._update_switch_label_color(lbl, checked))
            self._update_switch_label_color(label, toggle.isChecked())
            row_layout.addWidget(toggle)

            row = index // 3
            col = index % 3
            grid_layout.addWidget(row_widget, row, col)

            self.switches[switch_id] = toggle
        
        switches_layout.addLayout(grid_layout)
        scroll_layout.addWidget(switches_card)
        
        # 将音量、玩家信息、游戏模式三个卡片横向排列（自适应）
        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)
        
        # 音量控制卡片
        volume_card = self._create_card("音量控制")
        self._configure_home_compact_card(volume_card, spacing=6)
        volume_layout = volume_card.layout()

        volume_slider_row = QHBoxLayout()
        volume_slider_row.setSpacing(6)
        volume_label = QLabel("音量")
        volume_label.setFixedWidth(36)
        volume_slider_row.addWidget(volume_label)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(int(self.config.volume * 100))
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_slider_row.addWidget(self.volume_slider, 1)
        
        self.volume_value_label = QLabel(f"{int(self.config.volume * 100)}%")
        self.volume_value_label.setMinimumWidth(45)
        self.volume_value_label.setAlignment(Qt.AlignCenter)
        volume_slider_row.addWidget(self.volume_value_label)
        
        volume_layout.addLayout(volume_slider_row)

        # 音量提示行（实时反映等级）
        self.volume_hint_label = QLabel()
        self.volume_hint_label.setObjectName("hintLabel")
        self.volume_hint_label.setWordWrap(True)
        self._refresh_volume_hint()
        volume_layout.addWidget(self.volume_hint_label)

        controls_row.addWidget(volume_card, 2)

        # 玩家信息卡片
        player_card = self._create_card("玩家信息")
        self._configure_home_compact_card(player_card, spacing=6)
        player_layout = player_card.layout()

        player_inner = QHBoxLayout()
        player_inner.setSpacing(8)
        self.player_label = QLabel()
        self.player_label.setWordWrap(False)
        self.player_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.player_label.setFixedHeight(28)
        player_inner.addWidget(self.player_label, 1)

        reset_btn = QPushButton("重置ID")
        reset_btn.setObjectName("secondaryButton")
        reset_btn.setFixedHeight(28)
        reset_btn.setMaximumWidth(100)
        reset_btn.clicked.connect(self._reset_player_id)
        player_inner.addWidget(reset_btn, 0, Qt.AlignVCenter)

        player_layout.addLayout(player_inner)

        # 玩家信息提示行
        player_hint = QLabel("ID 用于本地配置识别，重置后将清除当前关联设置。")
        player_hint.setObjectName("hintLabel")
        player_hint.setWordWrap(True)
        player_layout.addWidget(player_hint)

        self._refresh_home_player_label()
        controls_row.addWidget(player_card, 2)
        
        # 游戏模式卡片
        mode_card = self._create_card("游戏模式")
        self._configure_home_compact_card(mode_card, spacing=6)
        mode_layout = mode_card.layout()

        mode_inner = QVBoxLayout()
        mode_inner.setSpacing(6)

        mode_select_row = QHBoxLayout()
        mode_select_row.setSpacing(6)
        mode_label = QLabel("模式")
        mode_label.setFixedWidth(36)
        mode_select_row.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.setFixedHeight(30)
        self.mode_combo.addItems(["1. 官匹竞技", "2. aim rush", "3. 死斗模式"])
        self.mode_combo.setCurrentText(self.config.mode)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_select_row.addWidget(self.mode_combo, 1)
        mode_inner.addLayout(mode_select_row)

        ui_mode_row = QHBoxLayout()
        ui_mode_row.setSpacing(6)
        ui_mode_label = QLabel("界面")
        ui_mode_label.setFixedWidth(36)
        ui_mode_row.addWidget(ui_mode_label)
        self.ui_mode_combo = QComboBox()
        self.ui_mode_combo.setFixedHeight(30)
        self.ui_mode_combo.addItem("普通模式", False)
        self.ui_mode_combo.addItem("专家模式", True)
        current_expert = bool(getattr(self.config, "ui_expert_mode", False))
        self.ui_mode_combo.setCurrentIndex(1 if current_expert else 0)
        self.ui_mode_combo.currentIndexChanged.connect(self._on_ui_mode_changed)
        ui_mode_row.addWidget(self.ui_mode_combo, 1)
        mode_inner.addLayout(ui_mode_row)
        
        mode_layout.addLayout(mode_inner)
        controls_row.addWidget(mode_card, 2)
        
        scroll_layout.addLayout(controls_row)

        # 分类音量卡片：每类音效独立音量 + 响度归一开关
        category_card = self._create_card("分类音量")
        category_layout = category_card.layout()

        cat_hint = QLabel("为每类音效单独设音量（相对主音量的倍率）。例如把切枪声调小、击杀声保持最大，互不影响。")
        cat_hint.setObjectName("hintLabel")
        cat_hint.setWordWrap(True)
        category_layout.addWidget(cat_hint)

        self.category_volume_sliders = {}
        self.category_volume_labels = {}
        category_defs = [
            ("kill_sound", "击杀音效"),
            ("kill_voice", "击杀语音"),
            ("gun_sound", "枪声替换"),
            ("switch_weapon", "切枪音效"),
            ("reload_sound", "换弹音效"),
            ("death_sound", "被击杀音效"),
            ("special_sound", "特殊音效"),
        ]
        cat_vols = getattr(self.config, "category_volumes", {}) or {}
        for cat_key, cat_text in category_defs:
            cat_row = QHBoxLayout()
            cat_row.setSpacing(6)
            cat_name = QLabel(cat_text)
            cat_name.setFixedWidth(72)
            cat_row.addWidget(cat_name)

            cat_slider = QSlider(Qt.Horizontal)
            cat_slider.setMinimum(0)
            cat_slider.setMaximum(100)
            try:
                cat_init = int(round(float(cat_vols.get(cat_key, 1.0)) * 100))
            except (TypeError, ValueError):
                cat_init = 100
            cat_slider.setValue(max(0, min(100, cat_init)))
            cat_slider.valueChanged.connect(
                lambda value, k=cat_key: self._on_category_volume_changed(k, value)
            )
            cat_row.addWidget(cat_slider, 1)

            cat_value = QLabel(f"{cat_slider.value()}%")
            cat_value.setMinimumWidth(45)
            cat_value.setAlignment(Qt.AlignCenter)
            cat_row.addWidget(cat_value)

            self.category_volume_sliders[cat_key] = cat_slider
            self.category_volume_labels[cat_key] = cat_value
            category_layout.addLayout(cat_row)

        # 响度归一开关（默认关闭；对之后加载的音效生效）
        self.loudness_norm_check = QCheckBox("响度归一：拉平不同素材的音量差（开启后对之后加载的音效生效）")
        self.loudness_norm_check.setChecked(bool(getattr(self.config, "audio_loudness_normalize_enabled", False)))
        self.loudness_norm_check.stateChanged.connect(self._on_loudness_normalize_toggled)
        category_layout.addWidget(self.loudness_norm_check)

        scroll_layout.addWidget(category_card)

        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        self._apply_expert_mode_visibility()
        self._sync_home_tool_rows()
        self._sync_basic_page_overview()
        self._refresh_system_status_strip()
        
        return page

    @staticmethod
    def _get_home_switch_target_page(switch_id):
        page_map = {
            "kill_sound": "kill_sound",
            "kill_voice": "kill_voice",
            "kill_icon": "kill_icon",
            "gun_sound": "gun_sound",
            "death_sound": "death_sound",
            "switch_weapon": "switch_weapon",
            "reload_sound": "reload_sound",
            "crosshair": "crosshair",
            "magnifier": "magnifier",
            "flash": "flash",
            "dynamic_hud": "hud_color",
            "screen_effects": "screen_effects",
            "music": "music",
            "utility": "utility",
            "voice_output": "voice_output",
        }
        return page_map.get(switch_id)

    def _create_home_switch_label(self, switch_id, text):
        target_page = MainWindow._get_home_switch_target_page(switch_id)
        label = ClickableLabel(text) if target_page else QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 11))

        if target_page and isinstance(label, ClickableLabel):
            target_name = self._page_names.get(target_page, text)
            label.setCursor(Qt.PointingHandCursor)
            label.setToolTip(f"点击进入：{target_name}")
            label.clicked.connect(lambda pid=target_page: self.show_page(pid))

        return label

    def _create_home_tool_button(self, text, callback, *, primary=False, tooltip=None, minimum_width=112):
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setMinimumHeight(34)
        button.setMinimumWidth(minimum_width)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def _sync_home_tool_rows(self):
        for attr_name in ("home_primary_tools_row", "home_expert_tools_row"):
            row_widget = getattr(self, attr_name, None)
            if row_widget is None:
                continue
            has_visible_button = any(
                not button.isHidden()
                for button in row_widget.findChildren(QPushButton)
            )
            row_widget.setVisible(has_visible_button)
    
    def _create_card(self, title):
        """创建卡片容器.

        v5 Phase 8: 统一用 SettingsCard,让 basic 页 5 张卡跟进 v5 视觉骨架
        (semantic 色条 + elevation md + 后续 token 改动一改穿透).
        保留 v4 的视觉特化:
          - padding 24 (而非 SettingsCard 默认 14)
          - spacing 14 (而非默认 8)
          - title 用 cardTitle objectName + Microsoft YaHei 12 DemiBold
          - eventFilter 用于 hover shadow 增强
        """
        from widgets.settings_card import SettingsCard
        ds = get_design_system()
        card = SettingsCard(
            title=title,
            margins=(ds.container.card_padding,) * 4,
            spacing=14,
            semantic="config",  # v5 violet 色条
        )
        # v4 兼容:title_label 用 cardTitle 命名 + 自定义字体
        if card.title_label is not None:
            card.title_label.setObjectName("cardTitle")
            f = QFont("Microsoft YaHei", 12)
            f.setWeight(QFont.DemiBold)
            f.setLetterSpacing(QFont.PercentageSpacing, 98)
            card.title_label.setFont(f)
            # objectName 改了要重新触发 QSS 匹配
            card.title_label.style().unpolish(card.title_label)
            card.title_label.style().polish(card.title_label)

        # R4/UP-025: 不再给卡片装第二套 hover 阴影控制器（见 eventFilter 注释）。
        # SettingsCard 自己就管 hover 阴影，装了只会互相打架。
        return card

    def _configure_home_compact_card(self, card, *, spacing=8):
        layout = card.layout()
        if layout is None:
            return
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(spacing)

    def _home_player_label_text(self, player_id=None):
        value = str(player_id or "").strip() or "未记录"
        return f"当前玩家ID: {value}"

    def _refresh_home_player_label(self):
        if not hasattr(self, "player_label") or self.player_label is None:
            return

        full_text = self._home_player_label_text(getattr(self.config, "player_steamid", ""))
        width = max(0, self.player_label.width() - 6)
        if width > 0:
            display_text = self.player_label.fontMetrics().elidedText(full_text, Qt.ElideMiddle, width)
        else:
            display_text = full_text

        self.player_label.setText(display_text)
        self.player_label.setToolTip(full_text)

    def _flash_card_border(self, widget):
        """设置变更时，所在卡片左边框闪烁 accent 色"""
        # 向上查找最近的 card QFrame
        card = widget
        while card and not (isinstance(card, QFrame) and card.objectName() == "card"):
            card = card.parentWidget()
        if not card:
            return

        # 创建或复用左边框 overlay
        if not hasattr(card, '_flash_overlay'):
            overlay = QWidget(card)
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
            overlay.setFixedWidth(3)
            overlay.move(0, 0)
            overlay.resize(3, card.height())
            overlay.hide()
            card._flash_overlay = overlay
            card._flash_anim = None

        overlay = card._flash_overlay
        overlay.resize(3, card.height())

        colors = self.theme_manager.current_theme.colors
        accent = QColor(colors.accent_primary)

        # 用 QVariantAnimation 控制透明度
        if card._flash_anim and card._flash_anim.state() == QVariantAnimation.Running:
            card._flash_anim.stop()

        def set_alpha(alpha):
            c = QColor(accent)
            c.setAlpha(int(alpha))
            overlay.setStyleSheet(f"background-color: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});border-radius: 2px;")
            if alpha > 0 and not overlay.isVisible():
                overlay.show()
                overlay.raise_()
            elif alpha <= 0 and overlay.isVisible():
                overlay.hide()

        # 淡入
        fade_in = QVariantAnimation()
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(255.0)
        fade_in.setDuration(200)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in.valueChanged.connect(set_alpha)

        # 淡出
        fade_out = QVariantAnimation()
        fade_out.setStartValue(255.0)
        fade_out.setEndValue(0.0)
        fade_out.setDuration(200)
        fade_out.setEasingCurve(QEasingCurve.InCubic)
        fade_out.valueChanged.connect(set_alpha)

        group = QSequentialAnimationGroup()
        group.addAnimation(fade_in)
        group.addPause(300)
        group.addAnimation(fade_out)
        group.start()

        card._flash_anim = group

    def show_page(self, page_id, animated=True, force=False):
        """
        显示指定页面

        Args:
            page_id: 页面ID
            animated: 是否使用动画切换（默认True）
            force: 忽略"专家模式专属页在普通模式下不可达"这条门禁（UP-034）。
                   只给"用户明确要去那儿"的入口用——目前只有搜索跳转。
        """
        if (
            page_id in self._expert_only_pages
            and not bool(getattr(self.config, "ui_expert_mode", False))
            and not force
        ):
            # UP-034/D-17: 普通模式下这 6 个页面没有导航入口。**但静默 return 是最差的结果**
            # ——搜索能命中它们，用户点了却什么都不发生，看起来就是软件坏了。
            # 调用方传 force=True 表示"我知道它被隐藏了，临时打开"（见 _goto_search_result）。
            self.logger.info(f"普通模式下页面 {page_id} 已隐藏，未切换")
            return

        # UP-029: 未保存修改守卫必须跑在**骨架屏之前**。
        # 原先它在下面的"切换到页面"分支里,而 `_show_page_skeleton()` 已经先一步
        # `setCurrentWidget(skeleton)` 把当前页换掉了——等守卫执行时,
        # `content_stack.currentWidget()` 拿到的是骨架屏,它没有 `can_leave_page`,
        # 于是守卫静默失效。表现:在 hud_color / preset_center 改了东西没保存,
        # 切到一个**从没打开过**的页,不但不提示,编辑直接丢失
        # (切到已加载过的页反而正常,因为那条路径不走骨架屏——这也是它一直没被发现的原因)。
        leaving = self.content_stack.currentWidget() if hasattr(self, 'content_stack') else None
        if leaving is not None and self.pages.get(page_id) is not leaving:
            can_leave = getattr(leaving, 'can_leave_page', None)
            if callable(can_leave):
                try:
                    if not bool(can_leave()):
                        self._sync_nav_selection_to_current_page()
                        return
                except Exception as e:
                    self.logger.warning(f"Page leave check failed: {e}")

        # 如果页面未加载，先加载(R1-5: 先亮骨架屏再构建,杜绝首次切页白等)
        if page_id not in self._loaded_pages:
            if getattr(self, "_page_loading", False):
                return  # 构建期间忽略二次切页,防 processEvents 重入
            self._page_loading = True
            try:
                self._show_page_skeleton()
                self._load_page(page_id)
                # 新加载的页面需要刷新以应用当前主题
                if page_id in self.pages:
                    self.pages[page_id].update()  # 异步重绘
            finally:
                self._page_loading = False
        
        # 切换到页面
        if page_id in self.pages:
            new_widget = self.pages[page_id]

            # 离开守卫已在本方法开头执行过（UP-029：必须早于骨架屏），这里不再重复问一次
            # ——重复问会让用户在同一次切页里看到两个确认框。

            # 如果页面被标记为需要主题刷新，先刷新
            if page_id in self._pages_need_theme_refresh:
                self._pages_need_theme_refresh.discard(page_id)
                new_widget.style().unpolish(new_widget)
                new_widget.style().polish(new_widget)
                new_widget.update()
                self._recursive_refresh_widget(new_widget)
            
            # 使用动画切换（如果启用且页面过渡管理器已初始化）
            if animated and self.page_transition:
                self.page_transition.switch_page(new_widget, transition_type='fade_scale')
            else:
                # 直接切换（无动画）
                self.content_stack.setCurrentWidget(new_widget)
            
            # 更新侧边栏按钮状态（移除动画，避免布局问题）
            for btn_id, btn in self.nav_buttons.items():
                btn.setChecked(btn_id == page_id)
            # R1-6: 常用分组按钮选中态同步 + 记录使用
            for btn_id, btn in getattr(self, "_frequent_buttons", {}).items():
                btn.setChecked(btn_id == page_id)
            # R7/D-08: 选中态图标跟着换色（setChecked 只影响 QSS 的文字色，
            # QIcon 是位图、不受 QSS color 影响）
            self._current_page_id = page_id
            self._refresh_nav_icons(page_id)
            try:
                from core.page_usage_tracker import record_page_open

                record_page_open(page_id)
            except Exception:
                pass

            # 同步浮层按钮选中状态
            if hasattr(self, '_overlay_buttons') and self._overlay_buttons:
                for btn_id, btn in self._overlay_buttons.items():
                    btn.setChecked(btn_id == page_id)

            # 自动展开对应分组
            if page_id in self._page_to_group:
                self._page_to_group[page_id].set_expanded(True)

            # 更新紧凑模式顶栏标题
            if hasattr(self, '_compact_title') and page_id in self._page_names:
                self._compact_title.setText(self._page_names[page_id])

            # 紧凑模式下点击导航后关闭浮层
            if self._compact_mode and self._sidebar_overlay and self._sidebar_overlay.isVisible():
                self._hide_sidebar_overlay()

            self.logger.info(f"切换到页面: {page_id}")

    def _sync_nav_selection_to_current_page(self):
        """当切页被取消时，恢复导航按钮选中状态。"""
        if not hasattr(self, 'content_stack') or not hasattr(self, 'pages'):
            return

        current_widget = self.content_stack.currentWidget()
        current_page_id = None
        for page_id, widget in self.pages.items():
            if widget is current_widget:
                current_page_id = page_id
                break

        if not current_page_id:
            return

        for btn_id, btn in self.nav_buttons.items():
            btn.setChecked(btn_id == current_page_id)
        # R7/D-08: 切页被 dirty 守卫拦下时选中态会回滚，图标也要跟着回滚，
        # 否则会停在"另一页被选中"的颜色上
        self._current_page_id = current_page_id
        self._refresh_nav_icons(current_page_id)

        if hasattr(self, '_overlay_buttons') and self._overlay_buttons:
            for btn_id, btn in self._overlay_buttons.items():
                btn.setChecked(btn_id == current_page_id)

        if hasattr(self, '_compact_title') and current_page_id in self._page_names:
            self._compact_title.setText(self._page_names[current_page_id])

    # ========== 紧凑模式 ==========

    def _toggle_compact_mode(self):
        """切换紧凑/完整模式"""
        self._compact_mode = not self._compact_mode
        self._apply_compact_mode(self._compact_mode, animate=True)
        # 保存到配置
        self.config.compact_mode = self._compact_mode
        self.config.save_config()

    def _apply_compact_mode(self, compact, animate=False):
        """应用紧凑或完整模式"""
        if compact:
            # 紧凑模式：隐藏侧边栏，显示全局顶栏和汉堡入口
            self.sidebar.setVisible(False)
            self._compact_header.setVisible(True)
            self._hamburger_btn.setVisible(True)
            self._mode_toggle_btn.setText("⇔")
            self._mode_toggle_btn.setToolTip("切换到完整模式")
            self.setMinimumSize(860, 640)
            if animate:
                self._resize_window_centered(860, 640)
            else:
                self.resize(860, 640)
        else:
            # 完整模式：显示侧边栏，保留顶栏用于设置搜索入口，但隐藏汉堡按钮
            self.sidebar.setVisible(True)
            self._compact_header.setVisible(True)
            self._hamburger_btn.setVisible(False)
            self._mode_toggle_btn.setToolTip("切换到紧凑模式")
            self.setMinimumSize(1200, 800)
            if animate:
                self._resize_window_centered(1200, 800)
            else:
                self._setup_window_size()
            # 关闭浮层（如果有）
            self._hide_sidebar_overlay()

    def _resize_window_centered(self, w, h):
        """调整窗口大小并保持居中"""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            # 完整模式下根据屏幕自适应
            if not self._compact_mode:
                w = max(w, min(1600, int(geo.width() * 0.8)))
                h = max(h, min(1000, int(geo.height() * 0.85)))
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + (geo.height() - h) // 2
            self.setGeometry(x, y, w, h)
        else:
            self.resize(w, h)

    def _toggle_sidebar_overlay(self):
        """切换侧边栏浮层"""
        if self._sidebar_overlay and self._sidebar_overlay.isVisible():
            self._hide_sidebar_overlay()
        else:
            self._show_sidebar_overlay()

    def _show_sidebar_overlay(self):
        """显示侧边栏浮层（覆盖在内容区上方）"""
        # 半透明背景遮罩
        if not self._overlay_bg:
            self._overlay_bg = QWidget(self.centralWidget())
            self._overlay_bg.setObjectName("overlayBg")
            self._overlay_bg.setStyleSheet("background-color: rgba(0, 0, 0, 100);")
            self._overlay_bg.mousePressEvent = lambda e: self._hide_sidebar_overlay()

        central = self.centralWidget()
        self._overlay_bg.setGeometry(0, 0, central.width(), central.height())
        self._overlay_bg.raise_()
        self._overlay_bg.show()

        # 侧边栏浮层面板
        if not self._sidebar_overlay:
            self._sidebar_overlay = QFrame(self.centralWidget())
            self._sidebar_overlay.setObjectName("sidebarOverlay")
            self._sidebar_overlay.setFixedWidth(240)

            overlay_layout = QVBoxLayout(self._sidebar_overlay)
            overlay_layout.setContentsMargins(0, 0, 0, 0)
            overlay_layout.setSpacing(0)

            # 复用侧边栏的导航结构：创建导航按钮的镜像
            overlay_scroll = QScrollArea()
            overlay_scroll.setObjectName("sidebarScroll")
            overlay_scroll.setWidgetResizable(True)
            overlay_scroll.setFrameShape(QFrame.NoFrame)
            overlay_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            overlay_nav = QWidget()
            overlay_nav_layout = QVBoxLayout(overlay_nav)
            overlay_nav_layout.setContentsMargins(10, 15, 10, 10)
            overlay_nav_layout.setSpacing(5)

            # 标题
            overlay_title = QLabel("帆派助手")
            overlay_title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
            overlay_title.setAlignment(Qt.AlignCenter)
            overlay_nav_layout.addWidget(overlay_title)
            overlay_nav_layout.addSpacing(10)

            # 为每个导航按钮创建镜像按钮
            self._overlay_buttons = {}
            for group_widget in self.nav_groups:
                # 分组标题
                group_header = QLabel(group_widget._title)
                group_header.setObjectName("overlayGroupHeader")
                group_header.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
                group_header.setContentsMargins(10, 8, 0, 2)
                overlay_nav_layout.addWidget(group_header)

                # 按顺序遍历该分组下的页面
                for page_id in self._page_names:
                    if self._page_to_group.get(page_id) is not group_widget:
                        continue
                    overlay_btn = QPushButton(f"    {self._page_names[page_id]}")
                    overlay_btn.setObjectName("navButton")
                    overlay_btn.setCheckable(True)
                    overlay_btn.setMinimumHeight(36)
                    overlay_btn.setChecked(self.nav_buttons[page_id].isChecked())
                    overlay_btn.clicked.connect(
                        lambda checked, pid=page_id: self.show_page(pid)
                    )
                    overlay_nav_layout.addWidget(overlay_btn)
                    self._overlay_buttons[page_id] = overlay_btn

            overlay_nav_layout.addStretch()
            overlay_scroll.setWidget(overlay_nav)
            overlay_layout.addWidget(overlay_scroll)

        # 同步选中状态
        for page_id, btn in self._overlay_buttons.items():
            btn.setChecked(self.nav_buttons[page_id].isChecked())

        self._sidebar_overlay.setGeometry(0, 0, 240, central.height())
        self._sidebar_overlay.raise_()
        self._sidebar_overlay.show()

    def _hide_sidebar_overlay(self):
        """隐藏侧边栏浮层"""
        if self._overlay_bg:
            self._overlay_bg.hide()
        if self._sidebar_overlay:
            self._sidebar_overlay.hide()

    def resizeEvent(self, event):
        """窗口大小变化时更新浮层尺寸"""
        super().resizeEvent(event)
        if self._overlay_bg and self._overlay_bg.isVisible():
            central = self.centralWidget()
            self._overlay_bg.setGeometry(0, 0, central.width(), central.height())
        if self._sidebar_overlay and self._sidebar_overlay.isVisible():
            central = self.centralWidget()
            self._sidebar_overlay.setGeometry(0, 0, 240, central.height())
        if hasattr(self, "player_label"):
            self._refresh_home_player_label()

    def _update_switch_label_color(self, label, checked):
        """开关标签颜色联动（通过 objectName 切换 QSS 规则）"""
        label.setObjectName("switchLabelOn" if checked else "switchLabelOff")
        label.style().unpolish(label)
        label.style().polish(label)

    def _on_switch_changed(self, config_key, checked):
        """开关状态改变"""
        self.logger.info(f"开关状态改变: {config_key} = {checked}")
        setattr(self.config, config_key, checked)
        
        if config_key == "gun_sound_enabled":
            sync_legacy_gun_sound_flags(self.config)
        
        # 特殊处理：准心开关
        if config_key == "crosshair_enabled":
            if checked:
                if not getattr(self, "_crosshair_win32_available", False):
                    self.logger.error("准心功能需要pywin32库支持")
                    # 回滚内存值：方法开头已 setattr 为 True，若不回滚，
                    # 后续任何一次 save_config 会把"开"落盘，下次启动 UI 显示
                    # 已开但实际不生效（config/UI/磁盘三态不一致）
                    self.config.crosshair_enabled = False
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "提示", "准心功能需要额外组件(pywin32)才能使用。\n请重新安装帆派助手以获取完整功能。")
                    # 恢复复选框状态
                    sender = self.sender()
                    if sender:
                        sender.blockSignals(True)
                        sender.setChecked(False)
                        sender.blockSignals(False)
                    return
                # 显示准心(2.2.0: 首建较重,挪出点击帧;复显走快速路径毫秒级)
                if hasattr(self, 'crosshair_animation'):
                    self.logger.info("正在显示准心...")
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, self.crosshair_animation.show_crosshair)
            else:
                # 隐藏准心
                if hasattr(self, 'crosshair_animation'):
                    self.logger.info("正在隐藏准心...")
                    self.crosshair_animation.hide_crosshair()
        
        # 特殊处理：开镜放大开关
        # 2.2.0 丝滑化:建页/启停挪出点击帧——复选框即时回弹,重活下一拍做
        if config_key == "magnifier_enabled":
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._apply_magnifier_toggle(checked))

        # （Phase1-1.4：hud_color_enabled 已是 hud_rules_enabled 的 property 别名，
        #   原"兼容旧字段"手工镜像不再需要）

        # 特殊处理：屏幕特效总开关（实时同步到叠加层）
        if config_key == "screen_effects_enabled":
            if hasattr(self, 'screen_effect_overlay') and self.screen_effect_overlay:
                self.screen_effect_overlay.update_settings_from_config()
            if hasattr(self, 'pages') and 'screen_effects' in self.pages:
                page = self.pages.get('screen_effects')
                if page and hasattr(page, 'refresh_master_state'):
                    page.refresh_master_state()
        
        self.config.save_config()
        self.logger.info(f"配置已保存: {config_key} = {checked}")

        # 卡片边框闪烁反馈
        sender = self.sender()
        if sender:
            self._flash_card_border(sender)
    
    def _apply_magnifier_toggle(self, checked):
        """开镜放大的实际启停(点击帧之外执行,保证开关即时回弹)。"""
        magnifier_page = self.pages.get('magnifier')
        if not magnifier_page:
            self._load_page('magnifier')
            magnifier_page = self.pages.get('magnifier')
        if not magnifier_page:
            return
        if checked:
            self.logger.info("正在启用开镜放大...")
            magnifier_page.enable_magnifier()
            self.logger.info("✅ 开镜放大已启用")
        else:
            self.logger.info("正在禁用开镜放大...")
            magnifier_page.disable_magnifier()
            self.logger.info("❌ 开镜放大已禁用")

    def _on_volume_changed(self, value):
        """音量改变"""
        volume = value / 100.0
        self.config.volume = volume
        self.audio_manager.set_volume(volume)
        self.config.save_config()
        self.volume_value_label.setText(f"{value}%")
        self._refresh_volume_hint()

    def _on_category_volume_changed(self, key, value):
        """分类音量滑块改变：写入 config.category_volumes 并持久化（防抖保存）。"""
        try:
            vols = getattr(self.config, "category_volumes", None)
            if not isinstance(vols, dict):
                vols = {}
                self.config.category_volumes = vols
            vols[key] = max(0.0, min(1.0, value / 100.0))
            label = self.category_volume_labels.get(key)
            if label is not None:
                label.setText(f"{value}%")
            self.config.save_config()
        except Exception as e:
            self.logger.error(f"更新分类音量失败({key}): {e}")

    def _on_loudness_normalize_toggled(self, _state):
        """响度归一开关切换。对之后加载的音效生效。"""
        try:
            enabled = bool(self.loudness_norm_check.isChecked())
            self.config.audio_loudness_normalize_enabled = enabled
            self.config.save_config()
            self.logger.info(f"响度归一已{'开启' if enabled else '关闭'}（对之后加载的音效生效）")
        except Exception as e:
            self.logger.error(f"切换响度归一失败: {e}")

    def _refresh_volume_hint(self):
        """根据音量给出语义提示"""
        label = getattr(self, "volume_hint_label", None)
        if label is None:
            return
        v = int(getattr(self.config, "volume", 0) * 100)
        if v == 0:
            tip = "已静音 · 拖动滑块可恢复"
        elif v < 25:
            tip = f"{v}% · 偏低，可能在游戏中难以听清"
        elif v < 60:
            tip = f"{v}% · 适中，推荐用于多数场景"
        elif v < 90:
            tip = f"{v}% · 偏大，注意与游戏内音量配合"
        else:
            tip = f"{v}% · 接近最大，建议同步降低系统音量"
        label.setText(tip)
    
    def _on_mode_changed(self, mode):
        """游戏模式改变"""
        self.config.mode = mode
        self.config.save_config()
        self.logger.info(f"游戏模式: {mode}")

    def _on_theme_combo_changed(self, index):
        """首页主题下拉框切换"""
        theme_key = self.theme_combo.itemData(index)
        if not theme_key:
            return
        # R4/UP-030: 这里原本还有一句 `self._apply_style()`。
        # `set_theme()` 会同步触发 `_on_theme_changed` 回调，那里已经 apply 过一次，
        # 于是 42KB 的 QSS 被整表应用两遍——切主题的卡顿直接翻倍。
        # 高级设置页的同名处理器一直是只调 set_theme 的，首页这份属于漏改。
        self.theme_manager.set_theme(theme_key)
        self.config.ui_theme = theme_key
        self.config.save_config()
        self.logger.info(f"主题切换: {theme_key}")

        # 同步高级设置页面的主题下拉框（如果已加载）
        adv_page = self.pages.get('advanced')
        if adv_page and hasattr(adv_page, 'theme_combo'):
            adv_page.theme_combo.blockSignals(True)
            adv_idx = adv_page.theme_combo.findData(theme_key)
            if adv_idx >= 0:
                adv_page.theme_combo.setCurrentIndex(adv_idx)
            adv_page.theme_combo.blockSignals(False)
        if hasattr(self, "_sync_basic_page_overview"):
            self._sync_basic_page_overview()
    
    def _reset_player_id(self):
        """重置玩家ID"""
        self.config.reset_player_steamid()
        self._refresh_home_player_label()
        self.logger.info("玩家ID已重置")
    
    def _start_player_id_check(self):
        """启动玩家ID周期性检查"""
        # 使用QTimer定期检查（优化性能）
        from PySide6.QtCore import QTimer
        self.player_id_timer = QTimer(self)
        self.player_id_timer.timeout.connect(self._update_player_id_display)
        self.player_id_timer.start(3000)  # 每3秒检查一次（降低从1秒，玩家ID不会频繁变化）
        self.logger.info("玩家ID周期性检查已启动")
    
    def _update_player_id_display(self):
        """更新玩家ID显示"""
        current_text = self.player_label.toolTip() or self.player_label.text()
        current_id = current_text.replace("当前玩家ID: ", "")
        
        # 如果配置中的ID与显示不同，则更新
        config_id = self.config.player_steamid if self.config.player_steamid else "未记录"
        if current_id != config_id:
            self._refresh_home_player_label()
            self.logger.info(f"更新玩家ID显示: {config_id}")
    
    def _reload_audio(self):
        """重载音频"""
        from PySide6.QtWidgets import QMessageBox
        from core.audio.audio_task_runner import submit_reload_audio_task

        try:
            task_id = submit_reload_audio_task("basic_reload_audio")
            self.logger.info(f"[AudioTask] reload task submitted: {task_id}")
            if bool(getattr(self.config, "ui_expert_mode", False)):
                self.show_page("audio_task_panel")
            QMessageBox.information(
                self,
                "载入完成",
                "已提交音频重载任务，请在“音频任务面板”查看进度与结果。"
            )
        except Exception as e:
            self.logger.error(f"载入音频失败: {e}", exc_info=True)
            QMessageBox.warning(
                self,
                "载入失败",
                f"音频资源载入失败：{e}\n\n请检查自定义音频目录后重试。"
            )
    
    def _open_custom_folder(self):
        """打开自定义文件夹"""
        import os
        from config import get_config_dir
        
        folder_path = get_config_dir()
        try:
            if os.name == 'nt':
                os.startfile(folder_path)
            self.logger.info(f"打开文件夹: {folder_path}")
        except Exception as e:
            self.logger.error(f"打开文件夹失败: {e}")
    
    def _apply_style(self):
        """应用主题样式

        R4/UP-030: 加一道幂等闸。整表 setStyleSheet 会让 Qt 对整棵控件树重新
        解析 + polish，实测这是切主题时的主要开销；同一份 QSS 应用两遍纯属白花。
        字号档位变化会让 QSS 文本本身变化，所以这道闸不会挡住真正需要的重刷。
        """
        # 从主题管理器获取样式表
        stylesheet = get_stylesheet()

        # 对于极简主题，需要特殊处理：清空所有组件样式
        if self.theme_manager.current_theme_name == "minimal":
            # 极简主题**不走**幂等闸：它每次都要把新建页面的内联样式也扫一遍，
            # 而它的 QSS 恒为空串，用文本比对会把这件事整个跳掉。
            self._applied_stylesheet = None

            # 清空主窗口样式
            self.setStyleSheet("")

            # 清空所有子组件样式
            for widget in self.findChildren(QWidget):
                widget.setStyleSheet("")

            self.logger.info("已应用极简主题（系统默认样式）")
        else:
            if stylesheet == getattr(self, "_applied_stylesheet", None):
                self.logger.debug("主题样式未变化，跳过重复应用")
                return
            self._applied_stylesheet = stylesheet
            # 正常主题：应用样式表
            self.setStyleSheet(stylesheet)
            self.logger.info(f"已应用主题: {self.theme_manager.current_theme.name}")
            self.logger.info(f"样式表总长度: {len(stylesheet)} 字符")
    
    def _on_theme_changed(self):
        """主题变化回调"""
        self.logger.info("主题已变化，正在更新UI...")

        # 重新应用主题样式到主窗口
        self._apply_style()
        if hasattr(self, "_sync_basic_page_overview"):
            self._sync_basic_page_overview()

        # 只刷新当前可见页面，其他页面标记为需要刷新（切换时再刷新）
        if hasattr(self, 'pages') and hasattr(self, 'content_stack'):
            current_widget = self.content_stack.currentWidget()
            for page_id, page in self.pages.items():
                if page_id in self._loaded_pages:
                    if page is current_widget:
                        page.update()
                    else:
                        self._pages_need_theme_refresh.add(page_id)
        
        # 刷新音乐控制栏
        if hasattr(self, 'music_control_bar'):
            self.music_control_bar.refresh_icons()  # 刷新图标颜色以匹配新主题
            self.music_control_bar.update()
        
        # 刷新侧边栏
        if hasattr(self, 'sidebar'):
            self.sidebar.update()

        # v5 Phase 5+: 主题切换后重新生成 nav button icon 颜色
        # IconProvider 缓存按 (name, color) key,新颜色会触发 cache miss 自动用新色
        if hasattr(self, 'nav_buttons'):
            # R7/D-08: 换主题这条路原本一律刷成 secondary —— 会把当前选中项的图标
            # 刷回未选中色；而且只遍历 nav_buttons、漏了「常用」分组（既有缺陷）。
            # 走统一入口一并修掉。注意要先清掉幂等记账，否则颜色变了但 role 没变，
            # apply_nav_icon 会直接 return，图标停在旧主题的颜色上。
            for group in (self.nav_buttons, getattr(self, "_frequent_buttons", {})):
                for btn in (group or {}).values():
                    try:
                        btn.setProperty("fp_nav_icon_role", None)
                    except RuntimeError:
                        continue
            self._refresh_nav_icons()
        
        # R13: 搜索结果面板是独立顶层窗口，接不到这份 QSS，必须单独换一次调色板
        if hasattr(self, "_settings_search_completer"):
            self._apply_search_popup_theme()

        # 刷新内容区域
        if hasattr(self, 'content_stack'):
            self.content_stack.update()
        
        self.logger.info("主题更新完成")
    
    def _apply_modern_effects(self):
        """应用现代化效果（涟漪、微光等）"""
        try:
            # 为所有导航按钮添加涟漪效果
            for btn_id, btn in self.nav_buttons.items():
                try:
                    # 获取主题色
                    theme_color = QColor(self.theme_manager.get_color('accent_primary'))
                    theme_color.setAlpha(60)  # 半透明
                    add_ripple_effect(btn, theme_color)
                except Exception as e:
                    self.logger.warning(f"为按钮 {btn_id} 添加涟漪效果失败: {e}")
            
            # 为选中的导航按钮添加微光效果（仅一次）
            for btn_id, btn in self.nav_buttons.items():
                try:
                    if btn.isChecked():
                        add_shimmer_on_hover(btn, duration=1500)
                        break  # 只为当前选中的按钮添加
                except Exception as e:
                    self.logger.warning(f"为按钮 {btn_id} 添加微光效果失败: {e}")
            
            self.logger.info("现代化效果已应用")
        except Exception as e:
            self.logger.error(f"应用现代化效果失败: {e}")
    
    # ---------------- 对标主流：设置搜索（顶栏 + Ctrl+F） ----------------

    def _create_settings_search_box(self):
        """顶栏搜索框。下拉候选与回车跳转走**同一个**引擎（见 widgets/search_popup 的说明）。"""
        from PySide6.QtCore import QModelIndex
        from PySide6.QtGui import QKeySequence, QShortcut
        from PySide6.QtWidgets import QCompleter, QLineEdit

        from widgets.search_popup import SearchResultDelegate, build_model

        box = QLineEdit()
        box.setObjectName("settingsSearchBox")
        box.setPlaceholderText("搜索设置 / 功能…  (Ctrl+F)")
        box.setFixedHeight(34)
        # 原来是 setFixedWidth(220)。紧凑模式窗口只有 860 宽，顶栏还要塞
        # 汉堡键 + 标题 + 方形按钮，钉死 220 会把标题挤没。
        # 改成弹性区间，让布局按剩余空间分配。
        box.setMinimumWidth(170)
        box.setMaximumWidth(320)
        box.setClearButtonEnabled(True)

        self._search_model = build_model([], box)
        completer = QCompleter(self._search_model, box)
        # 关键：不让 QCompleter 自己过滤，原样显示我们喂进去的相关度排序结果
        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setMaxVisibleItems(8)
        completer.popup().setItemDelegate(SearchResultDelegate(completer.popup()))
        completer.popup().setUniformItemSizes(True)
        # 用 QModelIndex 重载：显示文案会重名（"准心大小"在准心设置和预设中心都有），
        # 只有 index 才能带出 page_id / 页签，靠字符串反解一定会串。
        completer.activated[QModelIndex].connect(self._on_search_row_activated)
        box.setCompleter(completer)
        box.textEdited.connect(self._on_search_text_edited)
        box.returnPressed.connect(self._on_search_return)

        self.settings_search_box = box
        self._settings_search_completer = completer
        self._search_rows = []          # 当前 model 对应的原始结果，回车取 [0] 用
        box.installEventFilter(self)    # 空框聚焦时给"最近搜索/常去页面"
        self._apply_search_popup_theme()

        # 把"项级索引装上了没有"写进每一份日志（实测 9ms，一次性）。
        #
        # 为什么值这 9ms：索引缺失时搜索会**静默降级**成只有页级——功能还能用、
        # 不报错、开发机上永远复现不出来（QA-001 就是这个形状：产物里少/多一个文件，
        # 只有真实用户机器上才暴露）。懒加载又意味着"日志里没有降级告警"证明不了
        # 任何事，用户不搜索就永远不会触发。所以这里主动问一次，把它变成
        # **每份日志都查得到的事实**，而不是等出事了再去猜。
        try:
            from core.settings_search import item_index_available

            if item_index_available():
                self.logger.info("[搜索] 项级索引已装载，设置项可直接搜索")
            else:
                self.logger.warning(
                    "[搜索] 项级索引缺失，已降级为仅页级搜索 —— "
                    "发布包可能漏带 _internal/core/search_index.json"
                )
        except Exception:
            self.logger.exception("[搜索] 项级索引自检失败")

        # Ctrl+F 全局（窗口内）聚焦搜索框
        shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        shortcut.activated.connect(self._focus_settings_search)
        self._search_shortcut = shortcut

    def _focus_settings_search(self):
        try:
            self.settings_search_box.setFocus()
            self.settings_search_box.selectAll()
            # 带文字时也要弹：Ctrl+F 已经把文字全选了，用户要么直接看结果、
            # 要么打字覆盖掉，两条路都比"面板不出来"强。
            self._reopen_search_popup()
        except Exception:
            pass

    def _apply_search_popup_theme(self):
        """让结果面板跟着主题走。

        ⚠ 离屏渲染实测：深色主题下这块 popup 仍然是**纯白**的。
        原因有两层，缺一不可：
          1. QSS 是 `self.setStyleSheet()` 打在 MainWindow 上的，而 completer 的
             popup 是个带 `Qt::Popup` 标志的独立顶层 QListView，不在那棵样式树里；
          2. 就算够得着，整份 QSS 里也**没有一条**针对裸 QListView 的规则
             （只有 `QComboBox QAbstractItemView`，那是给下拉框的）。
        所以直接改 palette，而不是再往 QSS 里加一条选择器 ——
        自绘 delegate 读的就是 `option.palette`，改这里才是改到点子上。
        深色 UI 上闪出一块白板，比没有结果面板还难受。
        """
        try:
            from PySide6.QtGui import QPalette

            from theme_manager import get_current_theme

            # ⚠ `current_theme` 是 property 不是方法，manager 上也没有
            # `get_current_theme()` —— 写错了会被下面的 except 静默吞掉，
            # 表现就是"深色主题下面板还是白的"，而日志里一个字都没有。
            colors = get_current_theme().colors
            popup = self._settings_search_completer.popup()
            base = QColor(getattr(colors, "bg_card", None) or colors.bg_secondary)

            # ⚠ 顺序和分工都不能改，这两条都是渲染实测出来的：
            #   1. QSS **只管边框**，颜色一律走 palette。第一版把 background 也写进
            #      QSS，结果浅色主题下背景跟着主题变白、而文字仍是深色主题那套浅灰
            #      —— 白字白底，整块面板几乎看不见。原因是 setStyleSheet 会触发
            #      re-polish，把我刚设进去的 palette 条目又冲掉一部分。
            #   2. 所以 setStyleSheet 要在 setPalette **之前**，让 palette 是最后一手。
            popup.setStyleSheet(
                f"QListView{{border:1px solid {colors.border_primary};"
                f"border-radius:6px;outline:0;}}"
            )
            pal = popup.palette()
            pal.setColor(QPalette.Base, base)
            pal.setColor(QPalette.Window, base)
            pal.setColor(QPalette.Text, QColor(colors.text_primary))
            pal.setColor(QPalette.WindowText, QColor(colors.text_primary))
            pal.setColor(QPalette.Highlight, QColor(colors.accent_primary))
            pal.setColor(QPalette.HighlightedText, QColor(colors.bg_primary))
            popup.setPalette(pal)
        except Exception:
            # 主题取不到就用系统默认色，搜索本身照常能用。
            # 但**必须留痕**：第一版这里写的是 debug，而我把取主题的 API 写错了
            # （`manager.get_current_theme()` 根本不存在），于是深色主题下面板一直是白的、
            # 日志里一个字都没有 —— 又一次静默失败。用 warning。
            self.logger.warning("搜索结果面板取主题色失败，沿用默认调色板", exc_info=True)

    # ---- 结果面板的数据供给 ----

    def _search_suggestion_rows(self, query=""):
        """空态/无结果时的出路：最近搜过什么 + 平时常去哪儿。

        搜不到东西时只弹一句"没有匹配"是把用户扔在原地。这里至少给几个能点的。
        """
        rows = []
        try:
            from core.search_history import recent

            for q in recent(4):
                if q == query:
                    continue
                rows.append({"kind": "recent", "text": q, "page_id": "",
                             "query": q, "subtitle": "最近搜索", "tab": "", "hit": ""})
        except Exception:
            pass
        try:
            from core.page_usage_tracker import top_pages

            candidates = list(top_pages(4, known_pages=self._page_names.keys()))
        except Exception:
            candidates = []
        for fallback in ("basic", "crosshair", "kill_sound"):
            if fallback not in candidates:
                candidates.append(fallback)
        hint = f"没找到「{query}」，也许你想去" if query else "常去的页面"
        for pid in candidates[:4]:
            rows.append({"kind": "suggest", "text": self._page_names.get(pid, pid),
                         "page_id": pid, "query": "", "subtitle": hint,
                         "tab": "", "hit": ""})
        return rows

    def _set_search_rows(self, rows):
        from widgets.search_popup import fill_model, subtitle_for

        for row in rows:
            row.setdefault("subtitle", "")
            if not row["subtitle"]:
                row["subtitle"] = subtitle_for(row)
        self._search_rows = rows
        # 复用同一个 model 就地换内容；理由见 widgets/search_popup.fill_model
        fill_model(self._search_model, rows)

    def _show_search_suggestions(self):
        self._set_search_rows(self._search_suggestion_rows())
        try:
            self._settings_search_completer.complete()
        except Exception:
            pass

    def _on_search_text_edited(self, text):
        """每次按键重建候选。实测 search_detailed 单次 0.2~2.6ms，够快。"""
        from core.settings_search import search_detailed

        query = str(text or "").strip()
        if not query:
            self._show_search_suggestions()
            return
        try:
            rows = search_detailed(query)
        except Exception:
            self.logger.exception("搜索失败")
            rows = []
        self._set_search_rows(rows if rows else self._search_suggestion_rows(query))
        try:
            self._settings_search_completer.complete()
        except Exception:
            pass

    def _search_box_focus_in(self, watched, event):
        """搜索框上"把结果面板重新打开"的三个入口。

        面板是 `Qt::Popup`，点窗口里任何别的地方它都会关掉——这是 Qt 的语义，
        改不了也不该改（否则它会一直浮在界面上挡东西）。真正的缺陷是**关了回不来**：
        原来只在"聚焦且框是空的"时弹一次，于是用户输入 → 点别处看一眼 → 点回搜索框，
        面板不回来，**必须把字删了重打**。这三个入口把它补上：

          FocusIn           点回搜索框
          MouseButtonPress  焦点没走、只是面板被关掉了（此时不会有 FocusIn）
          KeyPress ↓/↑      键盘用户的标准动作

        ⚠ 这段**必须挂在既有的 `eventFilter` 里**，不能另写一个同名方法：
        Python 后定义的会把先定义的整个覆盖掉，滚轮拦截那一整套就没了。
        """
        from PySide6.QtCore import QTimer as _QTimer

        if watched is not getattr(self, "settings_search_box", None):
            return
        etype = event.type()
        if etype not in (QEvent.FocusIn, QEvent.MouseButtonPress, QEvent.KeyPress):
            return
        if etype == QEvent.KeyPress and event.key() not in (Qt.Key_Down, Qt.Key_Up):
            return
        if self._search_popup_visible():
            return      # 已经开着：上下键要留给 completer 自己选行，别抢
        # 单发延迟：FocusIn 当帧弹 popup 会被紧随其后的焦点事件收掉
        _QTimer.singleShot(0, self._reopen_search_popup)

    def _search_popup_visible(self):
        try:
            return self._settings_search_completer.popup().isVisible()
        except Exception:
            return False

    def _reopen_search_popup(self):
        """按框里**当前**的文字重新出结果面板；空框则给「最近搜索 / 常去页面」。

        重新跑一遍搜索而不是把上次的行直接弹回来：中间可能已经换了主题、
        用过别的页（「常去」会变），拿旧行糊上去就是给用户看一份过期结果。
        实测单次 1~2ms。
        """
        box = getattr(self, "settings_search_box", None)
        if box is None or not box.hasFocus():
            # 这 0ms 里焦点可能已经跑了（比如用户点的是清除按钮又立刻点了别处），
            # 硬弹会弹出一个没人要的面板浮在界面上。
            return
        text = box.text().strip()
        if text:
            self._on_search_text_edited(text)
        else:
            self._show_search_suggestions()

    def _init_global_shortcuts(self):
        """R1-3: Ctrl+1..4 展开并跳到对应侧栏分组首页;F1 当前页帮助;Esc 收起帮助/搜索焦点。"""
        from PySide6.QtGui import QKeySequence, QShortcut

        self._app_shortcuts = []
        # 用 Alt+N 而非 Ctrl+N:音板槽位热键默认就是 ctrl+数字(keyboard 全局钩子),
        # 应用聚焦时 Ctrl+N 会双触发(切组+播放音板)——审计中实测发现的冲突。
        for idx in range(min(4, len(self.nav_groups))):
            sc = QShortcut(QKeySequence(f"Alt+{idx + 1}"), self)
            sc.activated.connect(lambda i=idx: self._goto_nav_group(i))
            self._app_shortcuts.append(sc)

        sc_help = QShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents), self)  # F1
        sc_help.activated.connect(self._toggle_current_page_help)
        self._app_shortcuts.append(sc_help)

        sc_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc_esc.activated.connect(self._on_escape_pressed)
        self._app_shortcuts.append(sc_esc)

    def _goto_nav_group(self, group_index):
        try:
            group = self.nav_groups[group_index]
            group.set_expanded(True)
            for page_id, g in self._page_to_group.items():
                if g is group:
                    self.show_page(page_id)
                    return
        except Exception:
            self.logger.exception(f"快捷键切分组失败: {group_index}")

    def _current_page_help_panel(self):
        try:
            from ui_help_panel import HelpPanel

            page = self.content_stack.currentWidget()
            if page is None:
                return None
            panels = page.findChildren(HelpPanel)
            return panels[0] if panels else None
        except Exception:
            return None

    def _toggle_current_page_help(self):
        panel = self._current_page_help_panel()
        if panel is not None:
            try:
                panel.toggle()
            except Exception:
                pass

    def _on_escape_pressed(self):
        """Esc 优先级:收起帮助面板 → 清搜索框焦点。都没有则不动(不抢其它 Esc 语义)。"""
        panel = self._current_page_help_panel()
        if panel is not None and getattr(panel, "_expanded", False):
            try:
                panel.collapse()
                return
            except Exception:
                pass
        try:
            if self.settings_search_box.hasFocus():
                self.settings_search_box.clearFocus()
        except Exception:
            pass

    def _on_search_row_activated(self, index):
        """用户在下拉里选了一行。数据从 index 的 UserRole 取，不从显示文字反解。"""
        from widgets.search_popup import ROLE_KIND, ROLE_PAGE_ID, ROLE_QUERY, ROLE_TAB

        try:
            kind = index.data(ROLE_KIND) or ""
            if kind == "recent":
                # 「最近搜索」是"再搜一次"，不是跳页
                query = index.data(ROLE_QUERY) or ""
                self.settings_search_box.setText(query)
                self._on_search_text_edited(query)
                return
            page_id = index.data(ROLE_PAGE_ID) or ""
            if not page_id:
                return
            self._goto_search_result(
                page_id,
                item_text=(index.data(Qt.DisplayRole) or "") if kind == "item" else "",
                tab_text=index.data(ROLE_TAB) or "",
            )
        except Exception:
            self.logger.exception("搜索结果跳转失败")

    def _on_search_return(self):
        """直接回车：取当前结果面板的第一条跳转（与下拉看到的顺序完全一致）。"""
        query = self.settings_search_box.text().strip()
        rows = [r for r in (self._search_rows or []) if r.get("kind") in ("item", "page")]
        if not rows and query:
            # 面板还没来得及建（比如粘贴后立刻回车），现算一次
            try:
                from core.settings_search import search_detailed

                rows = search_detailed(query)
            except Exception:
                rows = []
        if rows:
            top = rows[0]
            self._goto_search_result(
                top.get("page_id", ""),
                item_text=top.get("text", "") if top.get("kind") == "item" else "",
                tab_text=top.get("tab", ""),
            )
            return
        try:
            from ui_toast import toast_info

            toast_info("没有匹配的设置项，换个关键词试试", 2600)
        except Exception:
            pass

    def _goto_search_result(self, page_id, item_text="", tab_text=""):
        if not page_id:
            return
        try:
            query = self.settings_search_box.text()
            hidden = (
                page_id in self._expert_only_pages
                and not bool(getattr(self.config, "ui_expert_mode", False))
            )
            self.ensure_page_loaded(page_id)
            # UP-034/D-17: 命中被隐藏的页就临时打开它，而不是静默不动。
            self.show_page(page_id, force=True)
            self.settings_search_box.clear()
            self.settings_search_box.clearFocus()
            # 项级命中时按**索引里的项名**定位，比拿整条查询去页面上模糊找准得多：
            # 搜"准心 颜色"时 item_text 就是「准心颜色」，直接命中那一行。
            self._highlight_search_target(page_id, item_text or query, tab_text=tab_text)
            if query.strip():
                try:
                    from core.search_history import record

                    record(query)
                except Exception:
                    pass
            if hidden:
                self._offer_pin_hidden_page(page_id)
        except Exception:
            self.logger.exception(f"搜索跳转失败: {page_id}")

    def _offer_pin_hidden_page(self, page_id):
        """告诉用户「这页平时是藏着的」，并给一个一键固定显示的出路（D-17）。

        不解释的话用户下次还是找不到它——搜索能搜到、导航里却没有，
        那种"时有时无"比彻底藏起来更让人困惑。
        """
        try:
            from ui_toast import get_toast_manager

            name = self._page_names.get(page_id, page_id)
            get_toast_manager().show(
                f"「{name}」在普通模式下是隐藏的，已临时打开",
                toast_type="info", duration=8000,
                action_text="固定显示",
                action_callback=lambda: self._enable_expert_mode_from_toast(page_id),
            )
        except Exception:
            self.logger.exception("隐藏页提示失败（不影响跳转本身）")

    def _enable_expert_mode_from_toast(self, page_id):
        """把专家模式打开并落盘，让这些页面从此常驻导航。"""
        try:
            self.config.ui_expert_mode = True
            self.config.save_config()
            self._apply_expert_mode_visibility()
            from ui_toast import toast_success

            toast_success("已开启专家模式，这些页面会常驻左侧导航", 3000)
            self.logger.info(f"用户经搜索提示开启了专家模式（来自 {page_id}）")
        except Exception:
            self.logger.exception("开启专家模式失败")

    def _unsubscribe_config_reload(self):
        """退出时从配置重载总线摘掉自己（总线是模块级的，活得比窗口久）。"""
        try:
            from core.config_reload_bus import unsubscribe

            unsubscribe(self._config_reload_bridge)
        except Exception:
            pass

    def _config_reload_bridge(self, reason, changed_keys=()):
        """总线回调 → Signal。**可能在后台线程被调用**，这里只做转发。

        （地图规则的按地图自动切预设走 GSI 事件线程；在那儿直接刷控件会崩。）
        """
        try:
            self._config_reloaded_signal.emit(str(reason or ""))
        except RuntimeError:
            # 窗口已析构而总线还留着订阅——正常退出竞态，忽略
            pass

    def _on_config_reloaded(self, reason):
        """UP-035：配置被整体改写，让已加载的页面重读一遍。

        只刷**已加载**的页：没加载过的页下次构造时自然会读到新配置。
        每页独立 try/except——一个页面刷新失败不能让其余页面停在旧值上，
        那样反而制造出"一半新一半旧"的更糟状态。
        """
        refreshed, failed = 0, []
        for page_id in list(getattr(self, "_loaded_pages", ())):
            page = self.pages.get(page_id)
            loader = getattr(page, "load_settings", None) if page is not None else None
            if not callable(loader):
                continue
            try:
                loader()
                refreshed += 1
            except Exception:
                failed.append(page_id)
                self.logger.exception(f"[配置重载] 页面 {page_id} 刷新失败")
        self.logger.info(
            f"[配置重载] {reason}: 已刷新 {refreshed} 个已加载页面"
            + (f"，{len(failed)} 个失败: {failed}" if failed else "")
        )
        # 首页概览与状态条也读配置,一并同步
        for hook in ("_sync_basic_page_overview", "_tick_system_status_strip"):
            fn = getattr(self, hook, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def _find_setting_row(self, page, query):
        """UP-041: 在页面里找文案匹配 query 的**具体设置项**，返回它所在的行容器。

        匹配对象是用户真正看得见的文字：复选框/单选框的标签、字段名 QLabel。
        找到之后向上找一层"行"——单独高亮一个 QLabel 太细，用户看不出范围；
        高亮整行（label + 控件）才是"这就是你要的那一项"。

        返回 None 表示没命中，调用方退回卡片级定位（即改动前的行为）。
        """
        try:
            from PySide6.QtWidgets import QCheckBox, QLabel, QRadioButton, QWidget

            from core.settings_search import text_matches
            from widgets.settings_card import SettingsCard
        except Exception:
            return None

        # PySide6 的 findChildren 不接受类型元组，只能取全部 QWidget 再筛。
        # 顺带好处：findChildren(QWidget) 的顺序就是控件树顺序，
        # 于是"第一个命中"天然是页面上**最靠前**的那一项。
        wanted = (QCheckBox, QRadioButton, QLabel)
        best = None
        for widget in page.findChildren(QWidget):
            if not isinstance(widget, wanted):
                continue
            try:
                # 用 isVisibleTo(page) 而不是 isVisible()：后者要求整个窗口已显示，
                # 在"切页后还没画出来"的一拍里会把所有控件都当成不可见、直接全落空。
                # isVisibleTo 只看它到 page 这一段有没有被 hide()——
                # 正好能排掉折叠着的帮助面板内容，又不依赖窗口状态。
                if not widget.isVisibleTo(page):
                    continue
                text = widget.text().strip()
            except Exception:
                continue
            # 太短的文案（"："、"开"）匹配上多半是噪声；标题类留给卡片级去处理
            if len(text) < 2 or widget.objectName() in ("titleLabel", "cardTitle", "statusLabel"):
                continue
            if text_matches(query, text):
                best = widget
                break
        if best is None:
            return None

        # 向上找到"行"：停在卡片之前的最后一级容器。
        # **最多两级**——不设上限的话，控件直接挂在滚动内容上时会一路走到顶，
        # 把整块内容区当成"行"高亮，那还不如不定位。
        row, node, depth = best, best.parentWidget(), 0
        while node is not None and depth < 2:
            if node is page or isinstance(node, SettingsCard):
                break
            row, node = node, node.parentWidget()
            depth += 1
        return row

    def _refresh_nav_icons(self, page_id=None):
        """R7/D-08(UP-051): 让导航图标跟着选中态变色。

        原状：选中态只有 QSS 的 `color`（作用于文字）和 Python 的 setChecked，
        **没有任何一处换 icon** —— 文字变紫、图标还是灰的，选中项看着像半选。

        三条路都要覆盖：切页 / 切页被 dirty 守卫拦下回滚 / 换主题重建图标。
        「常用」分组的按钮是另一批对象，必须一起刷（换主题那条路今天就漏了它）。
        """
        try:
            from widgets.icon_provider import apply_nav_icon
        except Exception:
            return
        current = page_id
        if current is None:
            current = getattr(self, "_current_page_id", None)
        for group in (getattr(self, "nav_buttons", {}),
                      getattr(self, "_frequent_buttons", {})):
            for btn_id, btn in (group or {}).items():
                try:
                    apply_nav_icon(btn, btn_id, btn_id == current)
                except RuntimeError:
                    continue

    def _clear_search_highlight(self):
        """撤掉上一次搜索高亮（目标可能已随页面销毁，必须容错）。"""
        target = getattr(self, "_search_hit_target", None)
        self._search_hit_target = None
        if target is None:
            return
        try:
            target.setProperty("searchHit", None)
            target.style().unpolish(target)
            target.style().polish(target)
        except RuntimeError:
            # 底层 C++ 对象已析构（页面被销毁/重建）——高亮本就无处可撤，忽略
            pass

    def _step_search_highlight(self, target, state):
        """搜索高亮的一步：state ∈ {"true"(强), "fade"(弱), None(撤)}。"""
        if target is not getattr(self, "_search_hit_target", None):
            return  # 已被更新的一次搜索接管，这一步作废
        if state is None:
            self._clear_search_highlight()
            return
        try:
            target.setProperty("searchHit", state)
            target.style().unpolish(target)
            target.style().polish(target)
        except RuntimeError:
            self._search_hit_target = None

    def _activate_page_tab(self, page, tab_text):
        """把页面切到指定页签。

        项级索引里有 15 条落在页签里（比如特殊音效页的「C4」「回合」）。
        不先切页签，`_find_setting_row` 用 `isVisibleTo(page)` 过滤时
        非当前页签里的控件全是不可见的——搜到了却定位不到，比搜不到更费解。
        """
        if not tab_text:
            return
        try:
            from PySide6.QtWidgets import QTabWidget

            for tw in page.findChildren(QTabWidget):
                for i in range(tw.count()):
                    if tw.tabText(i).strip() == tab_text.strip():
                        tw.setCurrentIndex(i)
                        return
        except Exception:
            pass

    def _highlight_search_target(self, page_id, query, tab_text=""):
        """R1-2: 跳转后定位反馈——命中卡片标题则滚动到该卡并高亮,否则高亮页头。

        R4/UP-024：原实现用 `apply_glow()` 给目标装一个发光 QGraphicsDropShadowEffect，
        1.6 秒后 `setGraphicsEffect(None)`。两个后果：
          1. 卡片本来就有 elevation 阴影，`setGraphicsEffect` 会把它**顶掉并析构**；
             1.6 秒后又置 None，于是这张卡的阴影**永久消失**，切页也回不来。
          2. `SettingsCard._shadow` 仍指向那个已被 Qt 析构的 C++ 对象，
             之后每次 hover 都在 `_animate_shadow_blur` 里抛 RuntimeError。
        改法：完全不碰 graphicsEffect，改用动态属性 `searchHit` + QSS 边框高亮。
        分「强 1.2s → 弱 0.4s → 撤」三档，观感上是渐隐，但零动画开销
        （红线禁重动效）。边框只换颜色不换宽度，所以不会引起重排跳动。
        """
        try:
            from PySide6.QtCore import QTimer

            from core.settings_search import text_matches
            from widgets.settings_card import SettingsCard

            page = self.pages.get(page_id)
            if page is None:
                return

            self._activate_page_tab(page, tab_text)

            target = None
            q = str(query or "").strip()
            if q:
                # UP-041: 先试**控件行**级定位。原来只能定位到「页面 + 卡片标题」，
                # 389 项具体开关搜不到——用户搜"观战静音"只会被丢到基础设置页顶部，
                # 还得自己在一屏设置里找。
                # 这里不建 389 项的手工索引（维护成本高、写错了比没有更糟），
                # 而是在**已经建好的页面上**按控件文案就地匹配：命中就精确定位，
                # 命不中就退回下面的卡片级定位——也就是今天的行为，不会更差。
                target = self._find_setting_row(page, q)
            if target is None and q:
                for card in page.findChildren(SettingsCard):
                    title = ""
                    try:
                        title_label = getattr(card, "title_label", None)
                        title = title_label.text() if title_label is not None else ""
                    except Exception:
                        title = ""
                    if title and text_matches(q, title):
                        target = card
                        break
            if target is None:
                from widgets.page_header import PageHeader

                headers = page.findChildren(PageHeader)
                target = headers[0] if headers else page

            # 滚动到目标(若在滚动区内)
            try:
                from PySide6.QtWidgets import QScrollArea

                scroll = page.findChild(QScrollArea)
                if scroll is not None and target is not page:
                    scroll.ensureWidgetVisible(target, 0, 48)
            except Exception:
                pass

            # 先撤上一次的高亮，再接管（连续搜索时不会留下一堆亮着的卡）
            self._clear_search_highlight()
            self._search_hit_target = target
            # QSS 背景色要在非 QFrame 的目标（如 PageHeader）上生效，
            # 必须显式打开 styled background，否则属性设了也不画。
            try:
                target.setAttribute(Qt.WA_StyledBackground, True)
            except Exception:
                pass
            self._step_search_highlight(target, "true")
            QTimer.singleShot(1200, lambda t=target: self._step_search_highlight(t, "fade"))
            QTimer.singleShot(1600, lambda t=target: self._step_search_highlight(t, None))
        except Exception:
            # 高亮纯属锦上添花,任何异常都不能影响跳转本身
            pass

    # ---------------- 系统集成：托盘 / 关闭策略 / 窗口几何（对标主流） ----------------

    def _init_system_tray(self):
        """创建系统托盘图标（不可用环境自动降级为无托盘行为）。"""
        try:
            from PySide6.QtWidgets import QMenu, QSystemTrayIcon

            if not QSystemTrayIcon.isSystemTrayAvailable():
                self.logger.info("系统托盘不可用，关闭窗口将直接退出")
                return
            icon = self.windowIcon()
            if icon.isNull():
                icon = QApplication.windowIcon()
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip(f"帆派助手 v{VERSION}")

            menu = QMenu()
            show_action = menu.addAction("显示主界面")
            show_action.triggered.connect(self._restore_from_tray)
            menu.addSeparator()
            quit_action = menu.addAction("退出程序")
            quit_action.triggered.connect(self._quit_from_tray)
            tray.setContextMenu(menu)
            tray.activated.connect(self._on_tray_activated)
            tray.show()
            self._tray_icon = tray
            self._tray_menu = menu  # 防 GC
            self.logger.info("系统托盘已就绪")
        except Exception:
            self.logger.exception("初始化系统托盘失败（降级为无托盘）")
            self._tray_icon = None

    def _on_tray_activated(self, reason):
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
                self._restore_from_tray()
        except Exception:
            pass

    def _restore_from_tray(self):
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._force_exit = True
        self.close()

    def _hide_to_tray(self):
        self._save_window_geometry()
        self.hide()
        if self._tray_icon is not None and not self._tray_hint_shown:
            self._tray_hint_shown = True
            try:
                from PySide6.QtWidgets import QSystemTrayIcon

                self._tray_icon.showMessage(
                    "帆派助手仍在运行",
                    "已最小化到系统托盘，游戏内功能照常工作。双击托盘图标可重新打开。",
                    QSystemTrayIcon.Information,
                    3500,
                )
            except Exception:
                pass
        self.logger.info("主窗口已最小化到托盘")

    def _ask_close_action(self):
        """首次关闭询问：托盘还是退出。返回 'tray'/'exit'/None(取消)。"""
        from PySide6.QtWidgets import QCheckBox, QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("关闭帆派助手")
        box.setIcon(QMessageBox.Question)
        box.setText("要把帆派助手最小化到系统托盘，还是直接退出？")
        box.setInformativeText("最小化到托盘后，击杀音效等游戏内功能会继续工作。")
        remember = QCheckBox("记住我的选择（之后可在高级设置修改）")
        remember.setChecked(True)
        box.setCheckBox(remember)
        tray_btn = box.addButton("最小化到托盘", QMessageBox.AcceptRole)
        exit_btn = box.addButton("直接退出", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is tray_btn:
            choice = "tray"
        elif clicked is exit_btn:
            choice = "exit"
        else:
            return None
        if remember.isChecked():
            try:
                self.config.close_action = choice
                self.config.save_config()
            except Exception:
                self.logger.exception("保存关闭行为失败（忽略）")
        return choice

    def _save_window_geometry(self):
        """记忆窗口几何（normalGeometry，避免最大化把异常尺寸写入配置）。"""
        try:
            if not bool(getattr(self.config, "use_saved_size", True)):
                return
            geo = self.normalGeometry()
            if geo.width() >= 640 and geo.height() >= 480:
                self.config.window_geometry = [geo.x(), geo.y(), geo.width(), geo.height()]
        except Exception:
            self.logger.exception("保存窗口几何失败（忽略）")

    def _restore_window_geometry(self):
        """恢复记忆的窗口几何；越界/异常时回退自动尺寸。"""
        try:
            if not bool(getattr(self.config, "use_saved_size", True)):
                return
            saved = list(getattr(self.config, "window_geometry", []) or [])
            if len(saved) != 4:
                return
            x, y, w, h = (int(v) for v in saved)
            screen = QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
            if avail is not None:
                w = max(self.minimumWidth(), min(w, avail.width()))
                h = max(self.minimumHeight(), min(h, avail.height()))
                # 至少留出可拖动的标题栏区域在屏内
                x = max(avail.left() - w + 160, min(x, avail.right() - 160))
                y = max(avail.top(), min(y, avail.bottom() - 120))
            self.setGeometry(x, y, w, h)
            self.logger.info(f"已恢复上次窗口位置与大小: {w}x{h} @({x},{y})")
        except Exception:
            self.logger.exception("恢复窗口几何失败（按自动尺寸继续）")

    def closeEvent(self, event):
        """窗口关闭事件：按用户策略进托盘或真正退出。"""
        # 1) 关闭策略（托盘菜单"退出程序"会强制走退出）
        action = "exit" if self._force_exit else str(getattr(self.config, "close_action", "ask") or "ask")
        tray_ready = self._tray_icon is not None
        if action == "ask" and tray_ready:
            choice = self._ask_close_action()
            if choice is None:
                event.ignore()
                return
            action = choice
        if action == "tray" and tray_ready:
            event.ignore()
            self._hide_to_tray()
            return

        # 2) 真正退出
        self.logger.info("关闭窗口（退出程序）")

        # 全局未保存检查（不仅限当前页）
        for page_id, page in getattr(self, "pages", {}).items():
            can_leave = getattr(page, "can_leave_page", None)
            if callable(can_leave):
                try:
                    if not bool(can_leave()):
                        self.logger.info(f"窗口关闭取消：页面存在未保存修改 {page_id}")
                        self._force_exit = False
                        event.ignore()
                        return
                except Exception as exc:
                    self.logger.warning(f"Close leave-check failed on {page_id}: {exc}")

        self._save_window_geometry()

        # 标记关闭流程，阻止预加载/延迟任务继续创建页面
        self._is_closing = True
        if hasattr(self, "_preload_queue"):
            self._preload_queue = []
        if hasattr(self, "_system_status_timer"):
            self._system_status_timer.stop()
        if self._tray_icon is not None:
            try:
                self._tray_icon.hide()
            except Exception:
                pass

        # P2.4: 退出清理步骤化——逐步隔离 + 耗时日志。
        # 任一步骤异常/缓慢都不再能"卡住整个退出"且无从定位。
        self._run_shutdown_steps()
        event.accept()

    def _save_music_progress_on_close(self):
        """关闭时保存音乐播放进度（有有效曲目索引才保存，位置 0 也保存）。"""
        if not (hasattr(self, 'music_control_bar') and hasattr(self.music_control_bar, 'player')):
            return
        player = self.music_control_bar.player
        if hasattr(player, 'get_position') and hasattr(player, 'current_index'):
            if player.current_index >= 0:
                position = player.get_position()
                self.config.music_current_position = position
                self.config.music_current_index = player.current_index
                self.logger.info(f"关闭时保存播放进度: 曲目#{player.current_index}, 进度{position:.1f}秒")

    def _cleanup_gsi_handlers_on_close(self):
        """恢复枪声 Ducking 与 HUD 默认颜色（否则游戏内状态残留）。"""
        if not (hasattr(self, 'gsi_handlers') and isinstance(self.gsi_handlers, dict)):
            return
        sounds_handler = self.gsi_handlers.get('sounds')
        if sounds_handler and hasattr(sounds_handler, 'cleanup'):
            sounds_handler.cleanup()
            self.logger.info("枪声 Ducking 已恢复")
        # v2.1.1: HUD 颜色处理器需要 stop() 写回默认 HUD 颜色 + 停后台 effect_timer
        hud_color_handler = self.gsi_handlers.get('hud_color')
        if hud_color_handler and hasattr(hud_color_handler, 'stop'):
            hud_color_handler.stop()
            self.logger.info("HUD 颜色规则已恢复默认")

    def _flush_page_usage(self):
        """UP-016: 把去抖中的页面频次统计落盘（退出兜底）。"""
        try:
            from core.page_usage_tracker import flush
            flush()
        except Exception:
            pass  # 统计失败绝不影响退出

    def _cleanup_page_on_close(self, page_id):
        if hasattr(self, 'pages') and page_id in self.pages:
            self.pages[page_id].cleanup()

    def _run_shutdown_steps(self):
        """按表执行退出清理：每步独立 try + 计时，慢步骤（>1s)记 warning。

        v2.2.1: 增加硬超时看门狗——任一步骤阻塞导致整体清理超过 15s 时，
        先尽力落盘配置，然后 os._exit 强制退出，杜绝"关不掉"挂死。
        """
        import os as _os
        import threading as _threading
        import time as _time

        def _watchdog_fire():
            try:
                self.logger.error("退出清理超时(15s)，触发看门狗强制退出")
            except Exception:
                pass
            try:
                self.config.save_config_now()
            except Exception:
                pass
            _os._exit(0)

        watchdog = _threading.Timer(15.0, _watchdog_fire)
        watchdog.daemon = True
        watchdog.start()

        steps = [
            # UP-035: 先退订配置重载广播。总线是模块级的、活得比窗口久,
            # 不退订的话它会一直握着这个已析构窗口的方法引用——
            # 之后任何一次 apply_bundle() 都会往死对象上打,抛 RuntimeError。
            ("退订配置重载广播", self._unsubscribe_config_reload),
            ("保存音乐进度", self._save_music_progress_on_close),
            ("恢复GSI游戏内状态", self._cleanup_gsi_handlers_on_close),
            ("停止GSI服务器", lambda: self.gsi_server.stop() if getattr(self, 'gsi_server', None) else None),
            # UP-055: 不能走 self.audio_manager —— 那是惰性属性，本次运行若从没
            # 碰过音频，这一步会为了"清理"反而把 pygame 整套拉起来，把退出拖慢。
            # peek 只看已存在的实例（可能是 GSI 线程建的，不限于本窗口建的）。
            ("清理音频管理器", self._cleanup_audio_manager),
            ("清理击杀图标播放器", lambda: self.kill_icon_player.cleanup() if hasattr(self, 'kill_icon_player') else None),
            # 判 overlay_win 而非 is_visible：SW_HIDE 复用路径下 is_visible=False
            # 但窗口/绘制线程仍在，按 is_visible 判会漏销毁（残留置顶窗口+线程）
            ("隐藏准心叠加", lambda: self.crosshair_animation.destroy()
                if hasattr(self, 'crosshair_animation')
                and getattr(self.crosshair_animation, 'overlay_win', None) is not None else None),
            ("清理屏幕特效", lambda: self.screen_effect_overlay.cleanup()
                if getattr(self, 'screen_effect_overlay', None) else None),
            ("清理放大镜", lambda: self._cleanup_page_on_close('magnifier')),
            ("清理视角自动切换", lambda: self._cleanup_page_on_close('viewmodel')),
            ("注销语音输出热键", lambda: self._cleanup_page_on_close('voice_output')),
            ("停止闪光进程", lambda: self._cleanup_page_on_close('flash')),
            ("清理动画管理器", lambda: self.animation_manager.cleanup() if hasattr(self, 'animation_manager') else None),
            ("清理效果管理器", lambda: self.effects_manager.cleanup() if hasattr(self, 'effects_manager') else None),
            ("清理页面过渡", lambda: self.page_transition.cleanup()
                if getattr(self, 'page_transition', None) else None),
            ("落盘配置", lambda: self.config.save_config_now()),
            # UP-016: 页面频次统计改为去抖落盘,退出时兜底 flush 一次,
            # 否则最后几次切页的统计会丢(影响下次启动的「常用」分组与预载顺序)。
            ("落盘页面统计", self._flush_page_usage),
        ]
        total_start = _time.perf_counter()
        for name, fn in steps:
            step_start = _time.perf_counter()
            try:
                fn()
            except Exception as e:
                self.logger.warning(f"退出步骤[{name}]异常（继续退出）: {e}")
            elapsed = _time.perf_counter() - step_start
            if elapsed > 1.0:
                self.logger.warning(f"退出步骤[{name}]偏慢: {elapsed:.2f}s")
        watchdog.cancel()
        self.logger.info(f"退出清理完成，共 {len(steps)} 步，总耗时 {_time.perf_counter() - total_start:.2f}s")
