#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
CS2 Customizer 2.0 - Widget版本
主窗口类
"""

# 注释来历：docs/notes/代码注释的来历_gui_widget.md
import os
import threading

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QScrollArea, QFrame,
    QSlider, QComboBox, QStackedWidget,
    QSpinBox, QDoubleSpinBox, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Qt, QEvent, QSize, Signal, Slot
from PySide6.QtGui import QFont, QColor, QIcon, QPainter

from config import config, VERSION
from core.utils.logger import get_logger
from theme_manager import (
    NAV_GROUP_PAD,
    NAV_GROUP_PAD_DENSE,
    NAV_ITEM_HEIGHT,
    NAV_ITEM_HEIGHT_DENSE,
    get_stylesheet,
    get_theme_manager,
)
from ui_design_system import get_design_system
from ui_style_applier import apply_unified_styles, keep_single_line
from ui_animations import get_animation_manager
from ui_transitions import create_page_transition
from ui_toast import get_toast_manager
from ui_ripple_effect import add_ripple_effect
from ui_shimmer import add_shimmer_on_hover
# 页面模块和重量级组件延迟导入（在需要时按需 import，加速启动）
from screen_effect_overlay import ScreenEffectOverlayManager
from core.audio.audio_resource_health import collect_audio_resource_health
from core.gun_sound_profiles import sync_legacy_gun_sound_flags
from core.page_traits import DEVICE_OWNING_PAGES
from core.runtime.system_status_service import GSI_LINK_TEXT, collect_runtime_status
from source_backup_manager import run_startup_source_backup
from core.utils.app_fonts import UI_FONT_FAMILY

#: 总览音量卡左边那列字的宽度：放得下「被击杀音效」，主音量和分类音量的滑条起点对齐。
HOME_VOLUME_LABEL_WIDTH = 76
#: 页面内容离窗边的左右留白（批 153）。
PAGE_MARGIN_H = 28


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
        self.header.setFocusPolicy(Qt.TabFocus)   # RN-640：同 navButton，点选不留焦点环
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setCheckable(False)
        self.header.clicked.connect(self.toggle)
        self._title = title
        self._update_header_text()
        main_layout.addWidget(self.header)

        # 子项容器
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        main_layout.addWidget(self.content)

    def _update_header_text(self):
        # 展开是常态，仅在收起时显示箭头。
        self.header.setText(self._title if self._expanded else f"▸ {self._title}")

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


def _app_icon_path():
    """窗口图标那张 icon.ico：打包后在 _MEIPASS 根上，源码运行时在本文件旁边。找不到返回 None。"""
    import sys

    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "icon.ico")
    return path if os.path.exists(path) else None


class BrandMark(QWidget):
    """侧栏品牌行的应用图标（批 153）。

    自己画而不用 QLabel.setPixmap：pixmap 建控件时就定死了倍率，窗口拖到缩放不同的屏上会糊；
    QIcon.paint 每次按当下那块屏挑尺寸。
    """

    def __init__(self, icon, size, parent=None):
        super().__init__(parent)
        self._icon = icon
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._icon.paint(painter, self.rect())


class MainWindow(QMainWindow):
    """主窗口"""

    # 线程安全的 Toast 信号，可从任何线程 emit
    _toast_signal = Signal(str, str, int)  # (message, toast_type, duration)
    # UP-035：配置重载可能来自 GSI 后台线程，必须经 Signal 排队到 GUI 线程操作控件。
    _config_reloaded_signal = Signal(str)
    # RN-195：首播通知可能来自加载/结束检测线程，必须经 Signal 在 GUI 线程建控制条。
    _music_playback_started_signal = Signal()

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
        # UP-055：音频只在显示后使用，惰性属性避免把 pygame 导入放进首屏路径。
        self._audio_manager = None
        _sub_phase("音频运行时管理器(延后)")
        self.theme_manager = get_theme_manager()  # 主题管理器
        _sub_phase("主题管理器构造")
        self.gsi_server = None  # 将在main_widget.py中设置
        
        # 初始化动画和效果管理器
        self.animation_manager = get_animation_manager()
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
        
        self.setWindowTitle(f"CS2 Customizer v{VERSION}")
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
        # RN-557：定时器按搜索代次撤销高亮，避免同一控件的旧定时器撤掉新高亮。
        self._search_hit_gen = 0
        self._is_closing = False  # 关闭流程标记，防止延迟任务继续触发副作用
        # 构造即起热键/线程/子进程/设备的页，不适合启动阶段静默预加载。
        # 取模块级 DEVICE_OWNING_PAGES（唯一真相源），拷一份免得实例改动串味。
        self._preload_skip_pages = set(DEVICE_OWNING_PAGES)
        self._expert_only_pages = {
            "audio_health",
            # ⭐ 2026-09-16：`audio_import_wizard` 从这里**移出去了**（用户在场）。
            #   它是"把下载来的素材装进软件"的唯一入口，而装素材不是专家操作 ——
            #   锁在专家模式里的后果是用户根本不知道有这个页面，
            #   只能自己开资源目录手动摆文件夹。
            "audio_task_panel",
            "audio_replay",
            "config_snapshot",
            "preset_center",
        }

        # 创建击杀图标播放器
        from kill_icon_player import KillIconPlayer
        self.kill_icon_player = KillIconPlayer(self)
        
        # QWidget 必须在主线程操作；渲染器默认值和切换前提见 config.crosshair_renderer。
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

        # UP-009：状态条是慢变量，每 15 秒刷新；窗口不可见时跳过磁盘 I/O。
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
        
        # UP-010：pygame/SDL 与 Qt 同时建窗可能触发原生崩溃，兼容模式跳过准心。
        # 准心的唯一自动显示入口延至主窗显示后，并检查幂等及期间关闭的情况。
        if self.config.crosshair_enabled:
            if os.environ.get("CS2C_SAFE_MODE_ACTIVE") == "1":
                self.logger.warning("兼容模式：已跳过 pygame 准心自动显示（规避与主窗渲染并发冲突导致的原生崩溃）")
            else:
                # UP-079：先在工作线程预热 pygame，避免延迟显示准心时首次导入卡住 GUI。
                self._prewarm_pygame_async()
                QTimer.singleShot(1200, self._auto_show_crosshair_deferred)
        
        _sub_phase("定时器/托盘/准心收尾")
        self.logger.info("GUI初始化完成")

        # RN-195：仅在实际播放过音乐后建常驻控制栏，避免空占内容区高度。
        from PySide6.QtCore import QTimer
        QTimer.singleShot(8000, self._create_music_control_bar_if_played)

        # 全局 QSS 就绪后建页，默认不做全树重刷；异常环境可启用 theme_refresh_on_start。
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
        """UP-055：首次使用才创建音频管理器；退出清理必须用 peek，避免为清理触发导入。"""
        if self._audio_manager is None:
            from core.audio.runtime_audio import get_runtime_audio_manager

            self._audio_manager = get_runtime_audio_manager()
        return self._audio_manager

    def _prewarm_pygame_async(self):
        """UP-079：后台预热 pygame，让主线程复用导入缓存；失败则由使用点正常导入。"""
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

        if not getattr(self, "_audio_tasks_stopped", True):
            self.logger.warning("音频维护仍在退出，跳过并发清理；由进程退出释放资源")
            return

        manager = peek_runtime_audio_manager()
        if manager is not None:
            manager.cleanup()

    def _stop_audio_tasks_on_close(self):
        from core.audio.audio_task_runner import stop_audio_tasks
        self._audio_tasks_stopped = stop_audio_tasks()
        if not self._audio_tasks_stopped:
            self.logger.warning("音频维护停止等待超时，后续阶段已取消")

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
        """按配置选渲染器；Qt 创建失败须能回退旧实现，保持准心可用。"""
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
        """UP-010：准心窗口延至主窗显示后创建，避免阻塞首屏。"""
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
        """UP-009：隐藏期间跳过了定时刷新，恢复显示时入队补刷，避免展示旧状态。"""
        super().showEvent(event)
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._refresh_system_status_strip)
        except Exception:
            pass

    def _tick_system_status_strip(self):
        """UP-009：不可见时跳过磁盘 I/O，重新显示由 showEvent 补刷。"""
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

    def _sync_sidebar_link(self, link, word, level, tooltip):
        """侧栏底部那行：游戏连上没有。值变了才动，这条路每隔几秒就走一次。"""
        label = getattr(self, "_sidebar_link_label", None)
        dot = getattr(self, "_sidebar_link_dot", None)
        if label is None or dot is None:
            return
        text = f"CS2 {word}"
        if label.text() != text:
            label.setText(text)
        label.setToolTip(tooltip)
        dot.setToolTip(tooltip)
        if dot.property("level") != level:
            dot.setProperty("level", level)
            dot.style().unpolish(dot)
            dot.style().polish(dot)

    def _refresh_system_status_strip(self):
        # ⚠ 就地 import，理由见 `_master_switch_page_id`（开源补丁盯着模块顶部那一整块）
        from core.cs2_video_mode import detect_display_mode
        from core.runtime.system_status_service import ReadinessView, readiness_view

        status_label = getattr(self, "system_status_label", None)
        if status_label is None:
            return
        try:
            status = collect_runtime_status(self)
            # 就绪状态按 GSI 数据链路判断，处理线程存活不等于游戏已推送数据。
            gsi_link = str(getattr(status, "gsi_link", "") or "stopped")
            link_word, link_level, link_fix = GSI_LINK_TEXT.get(gsi_link, GSI_LINK_TEXT["stopped"])
            gsi_error = str((status.gsi or {}).get("startup_error") or "")
            self._sync_sidebar_link(gsi_link, link_word, link_level, gsi_error or link_fix)
            # 这些页都写着「独占全屏会把它整个盖住」（`make_overlay_requirement_label` 的调用方）
            overlay_on = any(self.switches[switch_id].isChecked() for switch_id in (
                "crosshair", "flash", "kill_icon", "screen_effects", "fun_afterlife"))
            self._sync_home_readiness(readiness_view(status, detect_display_mode(), overlay_on=overlay_on))
            self._refresh_home_cards()
            self.logger.debug(f"[SystemStatus] level={status.level} err={status.last_error}")
        except Exception as exc:
            self._sync_home_readiness(ReadinessView("error", "状态刷新失败", str(exc), needs_setup=False))

    def _refresh_home_cards(self):
        """重新数失效的风格，再把卡片和侧栏的点刷一遍。只看目录在不在，回到总览时走一遍也不重。"""
        from core.audio.audio_resource_health import count_stale_styles

        self._home_stale_counts = count_stale_styles()
        self._sync_feature_cards()

    def _sync_home_readiness(self, view):
        """把算好的结论摆到总览状态条上。"""
        self._home_readiness = view
        strip = getattr(self, "basic_status_card", None)
        if strip is not None:
            strip.set_state(view.level, view.headline)
            strip.set_checks(view.checks)
            button = self.basic_onboarding_btn
            # RN-139：主按钮指向还没做的下一步。都做完了它就退成普通按钮，入口还在。
            wanted = "primaryButton" if view.needs_setup else "secondaryButton"
            if button.objectName() != wanted:
                button.setObjectName(wanted)
                button.style().unpolish(button)
                button.style().polish(button)
        self._sync_home_status_line()

    def _sync_home_status_line(self):
        """大字下面那一句：有事说修法；没事说开了几个，有风格失效再加一条去处理的链接。"""
        import html

        status_label = getattr(self, "system_status_label", None)
        view = getattr(self, "_home_readiness", None)
        if status_label is None or view is None:
            return
        if view.detail:
            status_label.setText(html.escape(view.detail))
            return
        parts = []
        switches = getattr(self, "switches", None) or {}
        if switches:
            parts.append(f"已开 {sum(t.isChecked() for t in switches.values())} / {len(switches)} 个功能")
        target = self._first_stale_feature()
        if target is not None:
            page_id, name, count = target
            parts.append(f'<a href="{page_id}">{html.escape(name)}有 {count} 项风格失效了，去处理</a>')
        status_label.setText(" · ".join(parts))

    def _first_stale_feature(self):
        """第一张「开着、但配的风格没了」的卡：(页面 id, 显示名, 项数)。"""
        stale = getattr(self, "_home_stale_counts", None) or {}
        for switch_id, card in (getattr(self, "feature_cards", None) or {}).items():
            count = stale.get(switch_id, 0)
            if count and self.switches[switch_id].isChecked():
                return self._get_home_switch_target_page(switch_id), card.accessibleName(), count
        count = stale.get("special_sound", 0)
        if count and self._special_sound_is_on():
            return "special_sound", "特殊音效", count
        return None

    def _special_sound_is_on(self):
        """特殊音效没有总开关，四类开了任何一类就算开着。"""
        return any(getattr(self.config, key, False) for key in (
            "grenade_sound_enabled", "c4_sound_enabled", "health_warning_enabled", "round_sound_enabled"))

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


    # ---------------- P4.1: 首次使用引导 ----------------

    def _show_onboarding_dialog(self):
        """RN-110：首启与手动重入共用三步引导，避免复制流程后内容漂移。"""
        from dialogs.onboarding_dialog import OnboardingDialog

        # 复用已打开的模态窗，避免覆盖唯一引用后旧窗被回收。
        existing = getattr(self, "_onboarding_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return existing

        dialog = OnboardingDialog(self)
        self._onboarding_dialog = dialog  # 防 GC
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _reopen_onboarding_guide(self):
        """基础设置页「重新上手引导」按钮。"""
        try:
            self._show_onboarding_dialog()
        except Exception:
            self.logger.exception("重新打开上手引导失败")
            # 不能静默：这个按钮是新用户的兜底入口，它自己再没反应就没别的路了。
            self.show_toast_safe(
                "上手引导打不开，详情见日志；CS2 目录也可以在「高级设置」里直接选。",
                "warning", 4200)

    def _maybe_show_onboarding(self):
        try:
            if bool(getattr(self.config, "onboarding_completed", True)):
                return
            if getattr(self, "_is_closing", False):
                return
            self._show_onboarding_dialog()
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
            preview = report_text

            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QMessageBox

            # 对标修缮：改为非模态——模态 exec 会在启动 12 秒后打断正在
            # 操作的用户（本轮离屏审查中它直接卡死了渲染事件循环，实证）。
            box = QMessageBox(self)
            box.setWindowTitle("发现崩溃记录")
            box.setIcon(QMessageBox.Question)
            box.setText(f"上次运行检测到 {len(logs)} 份崩溃日志。是否发送给开发者帮助修复？")
            box.setInformativeText("发送版本号和脱敏后的崩溃堆栈。发送前可在详情中检查完整内容。")
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

    def _make_nav_button(self, page_id, text):
        """主分组与常用分组共用导航按钮构造，保持尺寸、图标和样式一致。"""
        from widgets.icon_provider import get_page_icon
        from widgets.nav_button import NavButton

        btn = NavButton(f" {text}")
        btn.setObjectName("navButton")
        btn.setCheckable(True)
        btn.setFocusPolicy(Qt.TabFocus)   # RN-640：点选不留焦点环，Tab 上去才有（RN-546 只要键盘可见）
        icon = get_page_icon(page_id, role="secondary", size=16)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(QSize(16, 16))
        # RN-025：把 page_id 存在按钮本身，兼容不在 nav_buttons 表里的常用按钮。
        btn.setProperty("fp_page_id", page_id)
        btn.clicked.connect(lambda checked, pid=page_id: self.show_page(pid))
        return btn

    def _sync_expert_nav_buttons(self):
        """普通模式临时露出已打开的专家页入口，保证侧栏始终能指示当前位置。"""
        is_expert = bool(getattr(self.config, "ui_expert_mode", False))
        current = getattr(self, "_current_page_id", None)
        for page_id in self._expert_only_pages:
            btn = self.nav_buttons.get(page_id) if hasattr(self, "nav_buttons") else None
            if btn is not None:
                btn.setVisible(is_expert or page_id == current)

    def _apply_expert_mode_visibility(self):
        is_expert = bool(getattr(self.config, "ui_expert_mode", False))
        self._sync_expert_nav_buttons()
        # 项数变了，侧栏的档位要重算：内容比视口矮时变高变矮都不发 Resize
        self._apply_nav_density()
        if hasattr(self, "system_status_health_btn"):
            self.system_status_health_btn.setVisible(is_expert)
        if hasattr(self, "system_status_open_health_btn"):
            self.system_status_open_health_btn.setVisible(is_expert)
        if hasattr(self, "audio_task_panel_quick_btn"):
            self.audio_task_panel_quick_btn.setVisible(is_expert)
        if hasattr(self, "_sync_home_tool_rows"):
            self._sync_home_tool_rows()

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
        """拦截误改数值的滚轮并转发滚动；卡片阴影仅由 SettingsCard 持有。"""
        # RN-008：内容和视口的尺寸变化都需重算滚动；音乐条出现只会缩小视口。
        _scroll = getattr(self, "_sidebar_scroll", None)
        if (event.type() == QEvent.Resize
                and (watched is getattr(self, "_sidebar_nav_container", None)
                     or (_scroll is not None and watched is _scroll.viewport()))):
            page_id = getattr(self, "_current_page_id", None)
            # 重入保护：校正里会 activate() 布局，那有可能再发一次 Resize。
            if (not getattr(self, "_is_closing", False)
                    and not getattr(self, "_ensuring_nav_visible", False)
                    and self._nav_natural_geometry_changed(_scroll)):
                self._ensuring_nav_visible = True
                try:
                    self._apply_nav_density()
                    if page_id:
                        self._ensure_nav_button_visible(page_id)
                finally:
                    self._ensuring_nav_visible = False

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
        """向最近可滚动祖先的 viewport 转发滚轮，兼顾防误改与页面滚动；失败不阻塞 UI。"""
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

        # 紧凑档的顶栏：侧栏藏起来之后，搜索、账号、切档都住这儿。完整档没有这一条。
        self._compact_header = QWidget()
        self._compact_header.setFixedHeight(48)
        self._compact_header.setObjectName("compactHeader")
        compact_header_layout = QHBoxLayout(self._compact_header)
        compact_header_layout.setContentsMargins(ds.spacing.lg, 8, ds.spacing.lg, 8)
        compact_header_layout.setSpacing(8)
        self._compact_header_layout = compact_header_layout

        self._hamburger_btn = QPushButton()
        self._hamburger_btn.setObjectName("hamburgerButton")
        self._hamburger_btn.setFixedSize(32, 32)
        self._hamburger_btn.setIconSize(QSize(18, 18))
        self._hamburger_btn.setToolTip("显示导航")
        self._hamburger_btn.setAccessibleName("显示导航")
        self._refresh_hamburger_icon()
        self._hamburger_btn.setCursor(Qt.PointingHandCursor)
        self._hamburger_btn.clicked.connect(self._toggle_sidebar_overlay)
        compact_header_layout.addWidget(self._hamburger_btn)

        # 对标主流：设置搜索（27页/389项配置不再靠记忆翻页）；Ctrl+F 聚焦。
        # 只有一个框，跟着档位搬家（`_dock_search_box`）
        self._create_settings_search_box()
        compact_header_layout.addWidget(self.settings_search_box)
        compact_header_layout.addStretch()

        # RN-541：按钮直接说明切换结果，避免仅靠图标和悬停提示传达功能。
        self._mode_toggle_btn = QPushButton("⇔ 紧凑界面")
        # 与侧栏底部那个「紧凑模式 «」**不能共用 objectName**：那是宽文字按钮，
        # 这是方形图标按钮，两者的盒模型约束正好相反（见 _icon_button_qss）。
        self._mode_toggle_btn.setObjectName("modeToggleIconButton")
        # 32：QSS 里的 min/max-height 是**内容盒**（30），外面还有 1px 边框。
        self._mode_toggle_btn.setFixedHeight(32)
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
        # 批 153：200 → 216。字号到 14 之后「死亡刷短视频」后面还要留出状态点的位置
        sidebar.setFixedWidth(216)
        sidebar.setFrameShape(QFrame.StyledPanel)
        # 默认窗口 800 高放不下宽松档，先按紧凑档建，够高时 `_apply_nav_density` 再放宽
        sidebar.setProperty("navDense", True)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 搜索框位于品牌下方，页面标题作为内容区首行。
        header_widget = QWidget()
        header_widget.setObjectName("sidebarBrand")
        header_layout = QHBoxLayout(header_widget)
        # 左边距 20 + 图标 20：图标中线和下面导航图标的中线对齐，名字和导航文字左缘对齐
        header_layout.setContentsMargins(20, 12, 16, 8)
        header_layout.setSpacing(6)

        icon_path = _app_icon_path()
        if icon_path:
            header_layout.addWidget(BrandMark(QIcon(icon_path), 20), 0, Qt.AlignVCenter)

        # 标题
        title = QLabel("CS2 Customizer")
        title.setObjectName("sidebarTitleLabel")
        title.setFont(QFont(UI_FONT_FAMILY, 16, QFont.Bold))
        header_layout.addWidget(title)

        # 版本
        version = QLabel(f"v{VERSION}")
        version.setObjectName("sidebarVersionLabel")
        version.setFont(QFont(UI_FONT_FAMILY, 9))
        header_layout.addWidget(version, 0, Qt.AlignBottom)
        header_layout.addStretch()

        layout.addWidget(header_widget)

        # 搜索框的家。框只有一个，完整档住这里（`_dock_search_box`）
        search_host = QWidget()
        search_host.setObjectName("sidebarSearch")
        self._sidebar_search_layout = QVBoxLayout(search_host)
        self._sidebar_search_layout.setContentsMargins(12, 0, 12, 4)
        self._sidebar_search_layout.setSpacing(0)
        layout.addWidget(search_host)

        # 可滚动的导航区域
        scroll_area = QScrollArea()
        scroll_area.setObjectName("sidebarScroll")  # 避免与外层sidebar重名
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 切页后要把当前项滚进可视区，得留个引用。见 `_ensure_nav_button_visible`。
        self._sidebar_scroll = scroll_area
        
        # 导航按钮容器
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        # 普通模式可临时多出一个专家页入口，需为其留出高度，避免挤出末项。
        nav_layout.setContentsMargins(12, 0, 12, 4)
        nav_layout.setSpacing(0)
        
        # 导航按钮 - 可折叠分组
        nav_groups = [
            # RN-108：全局入口单独置顶成组，保证浮层、Alt 分组跳转和展开逻辑均能遍历。
            ("开始", [
                ("basic", "总览"),
                # ⭐⭐⭐ RN-673：原先排在最后一组，y=765 而侧栏视口只有 0~650 —— 看不见。
                ("audio_import_wizard", "导入资源"),
            ]),
            ("音效设置", [
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
                ("fun_afterlife", "死亡刷短视频"),
            ]),
            ("工具与系统", [
                ("utility", "道具瞄点"),
                ("advanced", "高级设置"),
                ("audio_health", "资源体检"),
                # ⚠ 「导入资源」已挪到「开始」组（RN-673）。
                ("audio_task_panel", "音频任务面板"),
                ("audio_replay", "音频事件回放"),
                ("config_snapshot", "软件设置快照"),
                ("preset_center", "预设中心"),
                ("about", "关于软件"),
            ]),
        ]

        self.nav_buttons = {}
        #: ⚠ **只装静态分组**，不含「常用」（它是 `insertWidget(0)` 插进布局的）。
        #:   要「侧栏里真实的分组顺序」请用 `_nav_groups_in_view()`（RN-025）。
        self.nav_groups = []
        # 保存布局句柄，真实分组顺序由 _nav_groups_in_view 现算，避免维护第二份清单。
        self._nav_layout = nav_layout
        self._page_to_group = {}  # page_id -> NavGroupWidget 映射
        self._page_names = {}  # page_id -> 显示名称
        for group_title, items in nav_groups:
            group_widget = NavGroupWidget(group_title)
            nav_layout.addWidget(group_widget)
            self.nav_groups.append(group_widget)

            for page_id, text in items:
                self._page_names[page_id] = text
                btn = self._make_nav_button(page_id, text)
                group_widget.add_button(btn)
                self.nav_buttons[page_id] = btn
                self._page_to_group[page_id] = group_widget
        
        # R1-6: 「常用」动态分组(本地使用频次 Top4,启动时计算,会话内只记录不重排)
        self._frequent_buttons = {}
        self.frequent_group = None
        try:
            if bool(getattr(self.config, "nav_frequent_enabled", False)):
                from core.page_usage_tracker import top_pages

                frequent_ids = top_pages(4, known_pages=self._page_names.keys())
                # 过滤专家模式门控页(非专家模式下不暴露入口)
                if not bool(getattr(self.config, "ui_expert_mode", False)):
                    frequent_ids = [p for p in frequent_ids if p not in self._expert_only_pages]
                if frequent_ids:
                    freq_group = NavGroupWidget("常用")
                    for page_id in frequent_ids:
                        text = self._page_names.get(page_id, page_id)
                        btn = self._make_nav_button(page_id, text)
                        freq_group.add_button(btn)
                        self._frequent_buttons[page_id] = btn
                    nav_layout.insertWidget(0, freq_group)
                    self.frequent_group = freq_group
        except Exception:
            self.logger.exception("常用分组初始化失败(侧栏按默认分组继续)")

        nav_layout.addStretch()
        
        scroll_area.setWidget(nav_container)
        # 分组和字体变化会在切页后改变内容高度，监听 Resize 重算，不能假定切页时布局已定。
        self._sidebar_nav_container = nav_container
        nav_container.installEventFilter(self)
        # RN-008：音乐条可能只缩小视口，视口 Resize 也必须触发重算。
        scroll_area.viewport().installEventFilter(self)
        layout.addWidget(scroll_area, 1)

        # 侧边栏底部：游戏连上没有 + 切到紧凑档
        sidebar_footer = QWidget()
        sidebar_footer.setObjectName("sidebarFooter")
        sidebar_footer_layout = QHBoxLayout(sidebar_footer)
        sidebar_footer_layout.setContentsMargins(18, 4, 12, 6)
        sidebar_footer_layout.setSpacing(8)
        self._sidebar_link_dot = QLabel()
        self._sidebar_link_dot.setObjectName("sidebarLinkDot")
        self._sidebar_link_dot.setFixedSize(8, 8)
        sidebar_footer_layout.addWidget(self._sidebar_link_dot)
        self._sidebar_link_label = QLabel("CS2 等游戏")
        self._sidebar_link_label.setObjectName("sidebarLinkLabel")
        self._sidebar_link_label.setProperty("fp_index_skip", True)
        sidebar_footer_layout.addWidget(self._sidebar_link_label)
        sidebar_footer_layout.addStretch()
        self._sidebar_mode_btn = QPushButton("紧凑界面")
        self._sidebar_mode_btn.setObjectName("modeToggleButton")
        self._sidebar_mode_btn.setToolTip("切换到紧凑模式")
        self._sidebar_mode_btn.setFixedHeight(24)   # 宽度跟字走：写死 64 时字大一档就差 2px（批 160）
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
        # 批 153：左右 20 → 28、上 16 → 20。内容离窗边和侧栏远一点，整屏才不显得挤
        page_margins = (PAGE_MARGIN_H, 20, PAGE_MARGIN_H, 0)
        root_margin_map = {
            # 底部音乐栏常驻时，去掉页面底部冗余留白，避免出现一条突兀的暗色缝隙。
            (16, 16, 16, 16): page_margins,
            (16, 16, 16, 0): page_margins,
            # 原来的统一值本身（关于、音乐两页手写的）：不认它，这两页的内容左缘就停在旧的 20
            (20, 16, 20, 0): page_margins,
            (20, 16, 20, 20): (PAGE_MARGIN_H, 20, PAGE_MARGIN_H, 20),
            (20, 20, 20, 20): page_margins,
            (24, 20, 24, 20): page_margins,
            (24, 20, 24, 24): page_margins,
        }
        root_spacing_map = {
            10: 12,
            15: 12,
            16: 12,
            20: 16,
        }
        card_margins = (20, 16, 20, 16)
        card_margin_map = {
            (14, 12, 14, 12): card_margins,
            (20, 20, 20, 20): card_margins,
            (16, 14, 16, 14): card_margins,
            (15, 15, 15, 15): card_margins,
            (25, 25, 25, 25): card_margins,
        }
        card_spacing_map = {
            10: 8,
            12: 8,
            15: 12,
            20: 12,
        }

        self._normalize_layout_metrics(page.layout(), root_margin_map, root_spacing_map)

        for scroll in page.findChildren(QScrollArea):
            content = scroll.widget()
            if content is not None:
                self._normalize_layout_metrics(content.layout(), root_margin_map, root_spacing_map)

        for card in page.findChildren(QFrame):
            if card.objectName() == "card":
                self._normalize_layout_metrics(card.layout(), card_margin_map, card_spacing_map)

        # 内容全在滚动区里的页，根布局没有左右边距，底栏的按钮和分隔线会贴着窗口边
        from widgets.page_action_bar import PageActionBar

        root = page.layout()
        for bar in page.findChildren(PageActionBar):
            index = root.indexOf(bar) if root is not None else -1
            if index >= 0 and root.contentsMargins().left() == 0:
                holder = QWidget(page)
                holder_layout = QVBoxLayout(holder)
                holder_layout.setContentsMargins(PAGE_MARGIN_H, 0, PAGE_MARGIN_H, 0)
                holder_layout.setSpacing(0)
                root.removeWidget(bar)
                holder_layout.addWidget(bar)
                root.insertWidget(index, holder)

        # 批 161：有固定底栏的页，滚到底时最后一行别贴着底栏那条分隔线
        if any(bar.objectName() == "pageActionBar" for bar in page.findChildren(PageActionBar)):
            from widgets.page_width import keep_scroll_end_clear, page_level_scrolls

            for scroll in page_level_scrolls(page):
                keep_scroll_end_clear(scroll)

        # 批 157：拉宽窗口时内容停在同一条右缘（放最后：上面会把底栏包进一层）
        from widgets.page_width import cap_page

        cap_page(page)
    
    def _create_pages(self):
        """创建页面（懒加载模式：只初始化 basic 页面）"""
        # 只创建 basic 页面，其他页面按需加载
        import time as _ct

        _t0 = _ct.perf_counter()
        self.pages["basic"] = self._create_basic_page()
        self._harmonize_page_chrome(self.pages["basic"])
        self.content_stack.addWidget(self.pages["basic"])
        self._loaded_pages.add("basic")
        # RN-442：basic 内联构建，不经过 _load_page，须在此补同一钩子。
        try:
            from PySide6.QtCore import QTimer as _QTimer
            from ui_style_applier import apply_compact_density, mark_compact_buttons
            _QTimer.singleShot(
                0, lambda p=self.pages["basic"]: mark_compact_buttons(p))
            apply_compact_density(self.pages["basic"], self._compact_mode)
        except Exception:
            self.logger.debug("[RN-442] 紧凑按钮标记失败(basic)", exc_info=True)
        # basic 是同步构建的首页，也需记录同格式耗时，避免性能排行漏掉首屏。
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
        elif page_id == "fun_afterlife":
            from pages.fun_page import FunPage
            page = FunPage(getattr(self, "afterlife_controller", None))
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
            # 内容页标题与侧栏选中项使用同名，保持当前位置一致。
            from widgets.page_header import PageHeader
            page_header = page.findChild(PageHeader)
            if page_header is not None and page_id in self._page_names:
                page_header.set_title(self._page_names[page_id])
            
            # 添加页面到堆栈
            self.content_stack.addWidget(page)
            self.pages[page_id] = page
            self._loaded_pages.add(page_id)
            # RN-442：样式表的最小尺寸须等 polish 后才生效，紧凑标记推迟一拍以免被覆盖。
            try:
                from PySide6.QtCore import QTimer as _QTimer
                from ui_style_applier import apply_compact_density, mark_compact_buttons
                _QTimer.singleShot(0, lambda p=page: mark_compact_buttons(p))
                # RN-548：布局 spacing/margins 不受 QSS polish 覆盖，密度调整无需推迟。
                apply_compact_density(page, self._compact_mode)
            except Exception:
                self.logger.debug("[RN-442] 紧凑按钮标记失败", exc_info=True)

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
            "music", "voice_output", "fun_afterlife",
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

    def _create_music_control_bar_if_played(self):
        """RN-195：播放后才构造控制栏，避免隐藏控件仍占资源；pygame 此时已后台预热。"""
        try:
            import music_player as _mp
        except Exception:
            # ⭐ 取不到判断依据时**照建** —— 见 `playback_has_ever_started` 里
            # 那段"两个失效方向不对称"的说明。
            self.logger.exception("音乐控制栏：取不到播放记录，按原样创建")
            self._create_music_control_bar()
            return

        # 先布好这条线再决定建不建：用户可能在**之后**才第一次按下播放，
        # 那时候控制条必须当场出现（音乐页自己没有任何播放控件）。
        self._arm_music_playback_watch(_mp)

        if not _mp.playback_has_ever_started():
            self.logger.info("音乐控制栏：这台机器还没放过音乐，先不创建（RN-195）")
            return
        self._create_music_control_bar()

    def _arm_music_playback_watch(self, music_player_module):
        """首播时必须建控制栏；音乐页只提供双击播放，暂停、下一首和音量均依赖此栏。"""
        if getattr(self, "_music_playback_watch_armed", False):
            return
        self._music_playback_started_signal.connect(
            self._create_music_control_bar, Qt.QueuedConnection)
        import weakref

        window_ref = weakref.ref(self)

        def _on_playback_started():
            window = window_ref()
            if window is None:
                return
            try:
                window._music_playback_started_signal.emit()
            except RuntimeError:
                pass  # 窗口的 C++ 那半边已经没了

        self._music_playback_started_listener = _on_playback_started
        music_player_module.add_playback_started_listener(_on_playback_started)
        self._music_playback_watch_armed = True

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
        """用户切页建骨架期间返回 False 让预载稍后重试，避免 processEvents 引入重入建页。"""
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
        """后台资源就绪后按使用频次切片预建页面，缩短高频页的首次切换等待。"""
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

        # UP-005：空闲预载也需让开用户交互，不能在操作期间同步建页。
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
                # UP-015：False 表示正在为用户建页；保留队首稍后重试，不能当成已就绪丢弃。
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
        """总览优先展示游戏就绪状态、功能开关与主音量。"""
        page = QWidget()
        page.setObjectName("contentPage")  # 设置objectName以应用主题背景色
        page.setAutoFillBackground(True)  # 设置自动填充背景
        layout = QVBoxLayout(page)
        # UP-045: 与其余页对齐到内容左边界。
        layout.setContentsMargins(16, 16, 16, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 24)
        scroll_layout.setSpacing(20)

        header_row = QHBoxLayout()
        title = QLabel("总览")
        title.setObjectName("titleLabel")
        title.setProperty("fp_search_text", "总览 基础设置")
        header_row.addWidget(title)
        header_row.addStretch()
        scroll_layout.addLayout(header_row)

        from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
        install_help_panel(header_row, scroll_layout, PAGE_HELP_TEXTS["basic"])

        # 批 153：状态一块、功能三块面板、音量和偏好两块卡。块和块之间只靠留白分开
        self._build_home_readiness(scroll_layout)
        self._build_home_features(scroll_layout)
        from widgets.home_overview import SplitRow

        volume_card = self._build_home_volume_card()
        prefs_card = self._build_home_prefs_card()
        self.home_split_row = SplitRow(volume_card, prefs_card, stretch=(3, 2))
        scroll_layout.addWidget(self.home_split_row)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        self._apply_expert_mode_visibility()
        self._sync_home_tool_rows()
        self._refresh_system_status_strip()

        return page

    def _build_home_readiness(self, parent_layout):
        from widgets.home_overview import ReadinessStrip

        self.basic_onboarding_btn = self._create_home_tool_button(
            # 不叫「重新上手引导」：对第一次用的人来说「重新」是个反向暗示。
            "打开上手引导",
            self._reopen_onboarding_guide,
            primary=True,
            tooltip="走一遍三步上手：选 CS2 安装目录 → 写入 GSI 配置 → 试听验证",
        )
        strip = ReadinessStrip(self.basic_onboarding_btn)
        self.basic_status_card = strip
        self.system_status_label = strip.detail_label
        self.system_status_label.linkActivated.connect(self.show_page)
        parent_layout.addWidget(strip)

    def _build_home_features(self, parent_layout):
        """三块功能面板。开关还是这 17 颗，拨它走的还是 `_on_switch_changed`。"""
        from ui_toggle_switch import ToggleSwitch
        from widgets.home_overview import FeatureCard, FeatureGrid, FeaturePanel
        from widgets.icon_provider import PAGE_ICON_MAP

        switch_configs = [
            ("kill_sound", "击杀音效", "kill_sound_enabled"),
            ("kill_voice", "击杀语音", "kill_voice_enabled"),
            ("kill_icon", "击杀图标", "kill_icon_enabled"),
            ("gun_sound", "枪声替换", "gun_sound_enabled"),
            ("death_sound", "被击杀音效", "death_sound_enabled"),
            ("switch_weapon", "切枪音效", "switch_weapon_sound_enabled"),
            ("reload_sound", "换弹音效", "reload_sound_enabled"),
            ("crosshair", "准心", "crosshair_enabled"),
            ("magnifier", "开镜放大", "magnifier_enabled"),
            ("flash", "自定闪光", "flash_enabled"),
            ("dynamic_hud", "HUD颜色", "hud_rules_enabled"),
            ("screen_effects", "屏幕特效", "screen_effects_enabled"),
            ("music", "音乐播放", "music_enabled"),
            ("utility", "道具瞄点", "utility_guide_enabled"),
            ("voice_output", "语音输出", "voice_output_enabled"),
            ("fun_afterlife", "死亡刷短视频", "fun_afterlife_enabled"),
            ("spectator", "观战静音", "spectator_mode_mute"),
        ]
        by_id = {switch_id: (text, key) for switch_id, text, key in switch_configs}
        groups = (
            ("声音", ("kill_sound", "kill_voice", "gun_sound", "death_sound", "switch_weapon", "reload_sound")),
            ("画面", ("crosshair", "kill_icon", "magnifier", "flash", "dynamic_hud", "screen_effects")),
            ("媒体与工具", ("music", "voice_output", "fun_afterlife", "utility", "spectator")),
        )

        self.switches = {}
        self.feature_cards = {}
        self._feature_group_labels = []
        self._switch_id_by_config_key: dict[str, str] = {}
        grid = FeatureGrid()
        self.feature_grid = grid
        for title, switch_ids in groups:
            panel = FeaturePanel(title)
            self._feature_group_labels.append((panel.count_label, switch_ids))
            for switch_id in switch_ids:
                text, config_key = by_id[switch_id]
                toggle = ToggleSwitch(checked=getattr(self.config, config_key, False))
                toggle.setAccessibleName(text)
                toggle.toggled.connect(
                    lambda checked, key=config_key: self._on_switch_changed(key, checked)
                )
                target_page = MainWindow._get_home_switch_target_page(switch_id)
                card = FeatureCard(
                    text, toggle,
                    icon_name=PAGE_ICON_MAP.get(target_page, "mdi.volume-off"),
                    has_page=bool(target_page),
                )
                if target_page:
                    card.setToolTip(f"点击进入：{self._page_names.get(target_page, text)}")
                    card.clicked.connect(lambda _checked=False, pid=target_page: self.show_page(pid))
                panel.add_card(card)
                self.feature_cards[switch_id] = card
                # ⚠ RN-089：`self.switches` 的真读者是 `sync_feature_switch`：配置从别处被改时
                # 靠它把开关拨回来。同时记下 config_key → switch_id 的反查。
                self.switches[switch_id] = toggle
                self._switch_id_by_config_key[config_key] = switch_id
            grid.add_panel(panel)
        parent_layout.addWidget(grid)
        self._sync_feature_cards()

    def _sync_feature_cards(self):
        """卡片、分组计数、状态条那句「已开」、侧栏小点都从开关现算。开关一动、状态一刷就走一遍。"""
        from core.feature_summary import feature_summary

        if not hasattr(self, "feature_cards"):
            return
        stale = getattr(self, "_home_stale_counts", None) or {}
        for switch_id, card in self.feature_cards.items():
            toggle = self.switches[switch_id]
            on = toggle.isChecked()
            self._update_switch_label_color(card.name_label, on)
            summary, tone = feature_summary(switch_id, self.config, stale.get(switch_id, 0)) if on else ("已关闭", "")
            card.set_state(on, summary, tone)
        for count_label, switch_ids in self._feature_group_labels:
            opened = sum(self.switches[switch_id].isChecked() for switch_id in switch_ids)
            count_label.setText(f"已开 {opened} / {len(switch_ids)}")
        self._sync_home_status_line()
        self.sync_nav_dots()

    def sync_nav_dots(self):
        """侧栏每项后面的小点：开着是绿的，开着但配的风格没了是黄的，关着没有点。"""
        from widgets.nav_button import DOT_NONE, DOT_ON, DOT_WARN

        if not hasattr(self, "switches") or not hasattr(self, "nav_buttons"):
            return
        stale = getattr(self, "_home_stale_counts", None) or {}

        def dot(on, stale_count):
            if not on:
                return DOT_NONE
            return DOT_WARN if stale_count else DOT_ON

        states = {"special_sound": dot(self._special_sound_is_on(), stale.get("special_sound", 0))}
        for switch_id, toggle in self.switches.items():
            target_page = self._get_home_switch_target_page(switch_id)
            if target_page:
                states[target_page] = dot(toggle.isChecked(), stale.get(switch_id, 0))
        for group in (self.nav_buttons, getattr(self, "_frequent_buttons", {})):
            for page_id, button in (group or {}).items():
                button.set_status_dot(states.get(page_id, DOT_NONE))

    def _refresh_home_icons(self):
        """换主题：图标都是位图，要按新颜色重画一遍。"""
        for card in (getattr(self, "feature_cards", None) or {}).values():
            card.refresh_icon()
        strip = getattr(self, "basic_status_card", None)
        if strip is not None:
            strip.refresh_icons()

    def _home_card(self, title):
        """总览下面两张卡的壳：抬头一行字，内容各自往 `card.body` 里放。"""
        from widgets.settings_card import SettingsCard

        card = SettingsCard(title, margins=(20, 16, 20, 20), spacing=14)
        card.setProperty("fp_home_card", True)
        return card

    def _build_home_volume_card(self):
        """主音量一行、分类音量两列、响度归一。分类音量是相对主音量的倍率。"""
        card = self._home_card("音量")

        row = QHBoxLayout()
        row.setSpacing(12)
        volume_label = keep_single_line(QLabel("主音量"))
        volume_label.setObjectName("switchLabelOn")
        volume_label.setFixedWidth(HOME_VOLUME_LABEL_WIDTH)
        row.addWidget(volume_label)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(int(self.config.volume * 100))
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.volume_slider, 1)

        self.volume_value_label = QLabel(f"{int(self.config.volume * 100)}%")
        self.volume_value_label.setObjectName("valueLabel")
        self.volume_value_label.setMinimumWidth(44)
        self.volume_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.volume_value_label)

        # 只有两头才说话（`_refresh_volume_hint`）
        self.volume_hint_label = keep_single_line(QLabel())
        self.volume_hint_label.setObjectName("hintLabel")
        self._refresh_volume_hint()
        row.addWidget(self.volume_hint_label)
        card.add_layout(row)

        divider = QFrame()
        divider.setObjectName("panelDivider")
        divider.setFixedHeight(1)
        card.add_widget(divider)

        self._build_home_category_volumes(card)
        card.add_stretch()
        return card

    def _build_home_category_volumes(self, card):
        """每类音效独立音量（相对主音量的倍率）+ 响度归一。"""
        from PySide6.QtWidgets import QGridLayout

        head = QHBoxLayout()
        head.setSpacing(8)
        title = keep_single_line(QLabel("分类音量"))
        title.setObjectName("panelSectionTitle")
        title.setToolTip("为每类音效单独设音量（相对主音量的倍率）。例如把切枪声调小、击杀声保持最大，互不影响。")
        head.addWidget(title)
        head.addStretch()
        card.add_layout(head)

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
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        cat_vols = getattr(self.config, "category_volumes", {}) or {}
        for index, (cat_key, cat_text) in enumerate(category_defs):
            row, block = index // 2, (index % 2) * 4
            cat_name = keep_single_line(QLabel(cat_text))
            cat_name.setObjectName("homeFieldLabel")
            cat_name.setFixedWidth(HOME_VOLUME_LABEL_WIDTH)
            grid.addWidget(cat_name, row, block)

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
            grid.addWidget(cat_slider, row, block + 1)

            cat_value = QLabel(f"{cat_slider.value()}%")
            cat_value.setObjectName("homeValueLabel")
            cat_value.setMinimumWidth(40)
            cat_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(cat_value, row, block + 2)

            self.category_volume_sliders[cat_key] = cat_slider
            self.category_volume_labels[cat_key] = cat_value
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(5, 1)
        grid.setColumnMinimumWidth(3, 20)

        # 响度归一开关（默认关闭；对之后加载的音效生效）。放在「分类音量」那一行右边，不夹在滑条中间
        self.loudness_norm_check = QCheckBox("响度归一")
        self.loudness_norm_check.setToolTip("拉平不同素材的音量差（开启后对之后加载的音效生效）")
        self.loudness_norm_check.setChecked(bool(getattr(self.config, "audio_loudness_normalize_enabled", False)))
        self.loudness_norm_check.stateChanged.connect(self._on_loudness_normalize_toggled)
        head.addWidget(self.loudness_norm_check)
        card.add_layout(grid)

    def _build_home_prefs_card(self):
        """其余全局设置：游戏模式、界面、主题、玩家 ID，底下是维护工具。一项一行，标签在左、控件在右。"""
        from PySide6.QtWidgets import QGridLayout

        card = self._home_card("偏好")
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        # 余下的宽度留在控件右边：摞成整行宽时控件还紧跟标签，不被推到最右（批 153 外审 S4，同朴素设置行）
        form.setColumnStretch(2, 1)
        # 控件这一列钉 240：玩家 ID 和「重置ID」挤在这一列里，按下拉框的首选宽排会把按钮字切掉
        form.setColumnMinimumWidth(1, 240)

        def add_row(text, widget):
            row = form.rowCount()
            label = keep_single_line(QLabel(text))
            label.setObjectName("homeFieldLabel")
            form.addWidget(label, row, 0)
            form.addWidget(widget, row, 1)

        def add_combo(text, combo):
            combo.setMinimumWidth(140)
            combo.setMaximumWidth(240)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            add_row(text, combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["1. 官匹竞技", "2. aim rush", "3. 死斗模式"])
        self.mode_combo.setCurrentText(self.config.mode)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        add_combo("游戏模式", self.mode_combo)

        self.ui_mode_combo = QComboBox()
        self.ui_mode_combo.addItem("普通模式", False)
        self.ui_mode_combo.addItem("专家模式", True)
        current_expert = bool(getattr(self.config, "ui_expert_mode", False))
        self.ui_mode_combo.setCurrentIndex(1 if current_expert else 0)
        self.ui_mode_combo.currentIndexChanged.connect(self._on_ui_mode_changed)
        add_combo("界面", self.ui_mode_combo)

        self.theme_combo = QComboBox()
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
        add_combo("主题", self.theme_combo)

        player_box = QWidget()
        # 和上面几个下拉框一样宽，按钮的右边和下拉框的右边对齐；长 ID 在这个宽度里从右边省略（RN-403）
        player_box.setMaximumWidth(240)
        player_row = QHBoxLayout(player_box)
        player_row.setContentsMargins(0, 0, 0, 0)
        player_row.setSpacing(8)
        self.player_label = QLabel()
        self.player_label.setWordWrap(False)
        self.player_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        player_row.addWidget(self.player_label, 1)

        reset_btn = QPushButton("重置ID")
        reset_btn.setObjectName("secondaryButton")
        reset_btn.setMaximumWidth(100)
        reset_btn.setToolTip("进过一次游戏后自动记上，不用手填。"
                             "ID 只用于本地配置识别；重置会清除当前关联的设置。")
        reset_btn.clicked.connect(self._reset_player_id)
        player_row.addWidget(reset_btn, 0, Qt.AlignVCenter)
        add_row("玩家", player_box)
        card.add_layout(form)
        self._refresh_home_player_label()

        divider = QFrame()
        divider.setObjectName("panelDivider")
        divider.setFixedHeight(1)
        card.add_widget(divider)

        self.home_primary_tools_row = QWidget()
        primary_tools_layout = QGridLayout(self.home_primary_tools_row)
        primary_tools_layout.setContentsMargins(0, 0, 0, 0)
        primary_tools_layout.setHorizontalSpacing(8)
        primary_tools_layout.setVerticalSpacing(8)

        self.system_status_refresh_btn = self._create_home_tool_button(
            "刷新状态",
            self._refresh_system_status_strip,
            tooltip="立即刷新总览的状态",
        )
        primary_tools_layout.addWidget(self.system_status_refresh_btn, 0, 0)

        self.home_reload_audio_btn = self._create_home_tool_button(
            "载入音频",
            self._reload_audio,
            tooltip="重新载入音频资源与配置",
        )
        primary_tools_layout.addWidget(self.home_reload_audio_btn, 0, 1)

        self.home_custom_folder_btn = self._create_home_tool_button(
            "自定义目录",
            self._open_custom_folder,
            tooltip="打开自定义资源文件夹",
        )
        primary_tools_layout.addWidget(self.home_custom_folder_btn, 1, 0)

        self.system_status_logs_btn = self._create_home_tool_button(
            "日志目录",
            self._open_log_directory,
            tooltip="打开运行日志目录",
        )
        primary_tools_layout.addWidget(self.system_status_logs_btn, 1, 1)
        # 多出来的宽度给空着的第三列：卡片摞成整宽时按钮不被拉成一长条
        primary_tools_layout.setColumnStretch(2, 1)
        card.add_widget(self.home_primary_tools_row)

        self.home_expert_tools_row = QWidget()
        expert_tools_layout = QHBoxLayout(self.home_expert_tools_row)
        expert_tools_layout.setContentsMargins(0, 0, 0, 0)
        expert_tools_layout.setSpacing(8)

        self.system_status_health_btn = self._create_home_tool_button(
            "立即体检",
            self._run_audio_health_from_home,
            tooltip="运行资源体检并跳转查看结果",
        )
        expert_tools_layout.addWidget(self.system_status_health_btn)

        self.system_status_open_health_btn = self._create_home_tool_button(
            "体检页面",
            lambda: self.show_page("audio_health"),
            tooltip="打开资源体检页面",
        )
        expert_tools_layout.addWidget(self.system_status_open_health_btn)

        self.audio_task_panel_quick_btn = self._create_home_tool_button(
            "任务面板",
            lambda: self.show_page("audio_task_panel"),
            tooltip="打开音频任务面板",
        )
        expert_tools_layout.addWidget(self.audio_task_panel_quick_btn)
        expert_tools_layout.addStretch()
        card.add_widget(self.home_expert_tools_row)
        card.add_stretch()
        return card

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
            "fun_afterlife": "fun_afterlife",
        }
        return page_map.get(switch_id)

    def _create_home_tool_button(self, text, callback, *, primary=False, tooltip=None, minimum_width=120):
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setMinimumHeight(32)
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
    
    def _home_player_label_text(self, player_id=None):
        """RN-403：缩短 ID 前缀并保留未记录状态，避免中间省略吃掉关键语义。"""
        value = str(player_id or "").strip() or "未记录"
        return f"ID · {value}"

    def _refresh_home_player_label(self):
        if not hasattr(self, "player_label") or self.player_label is None:
            return

        full_text = self._home_player_label_text(getattr(self.config, "player_steamid", ""))
        # RN-403：最小宽度需容纳未记录状态；长 ID 可右省略，全文放 tooltip。
        floor = self.player_label.fontMetrics().horizontalAdvance(
            self._home_player_label_text("未记录")) + 6
        if self.player_label.minimumWidth() < floor:
            self.player_label.setMinimumWidth(floor)
        width = max(0, self.player_label.width() - 6)
        if width > 0:
                # ⭐ RN-403：从右边切。中间省略会吃掉一句话里最要紧的那一截。
            display_text = self.player_label.fontMetrics().elidedText(
                full_text, Qt.ElideRight, width)
        else:
            display_text = full_text

        self.player_label.setText(display_text)
        self.player_label.setToolTip(full_text)


    def show_page(self, page_id, animated=True, force=False):
        """切换页面；force 仅供用户明确选择的入口绕过专家页门禁，animated 控制切换动画。"""
        if (
            page_id in self._expert_only_pages
            and not bool(getattr(self.config, "ui_expert_mode", False))
            and not force
        ):
            # UP-034：搜索可命中隐藏页，用户明确跳转时允许 force 临时打开。
            self.logger.info(f"普通模式下页面 {page_id} 已隐藏，未切换")
            return

        # UP-029：离开守卫必须早于骨架屏，否则 currentWidget 已被替换，原页守卫将失效。
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
            # RN-547：懒建控件须在最后一次 polish 后打标记，否则 QSS min-height 会盖回去。
            # 切页路径只扫描当前页，避免整窗开销。
            try:
                from ui_style_applier import apply_compact_density, mark_compact_buttons
                mark_compact_buttons(new_widget)
                # RN-548：帮助面板这类**懒建**的控件是在建页之后才出现的，
                # 它们身上的 layout 在 `_load_page` 那一刻还不存在。
                apply_compact_density(new_widget, self._compact_mode)
            except Exception:  # noqa: BLE001
                self.logger.debug("[RN-547] 紧凑标记失败(切页)", exc_info=True)

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
                self.page_transition.switch_page(new_widget)
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
            self._sync_expert_nav_buttons()
            if page_id == "basic":
                # 别的页刚配过枪、删过风格，回来这一屏得是新的
                self._refresh_home_cards()
            self._refresh_nav_icons(page_id)
            self._ensure_nav_button_visible(page_id)
            try:
                from core.page_usage_tracker import record_page_open

                record_page_open(page_id)
            except Exception:
                pass

            # 同步浮层按钮选中状态
            if hasattr(self, '_overlay_buttons') and self._overlay_buttons:
                for btn_id, btns in self._overlay_buttons.items():
                    for btn in btns:
                        btn.setChecked(btn_id == page_id)

            # 自动展开对应分组
            if page_id in self._page_to_group:
                self._page_to_group[page_id].set_expanded(True)

            # 紧凑模式下点击导航后关闭浮层
            if self._compact_mode and self._sidebar_overlay and self._sidebar_overlay.isVisible():
                self._hide_sidebar_overlay()

            self.logger.info(f"切换到页面: {page_id}")

    def _ensure_nav_button_visible(self, page_id):
        """切页或搜索跳转后保证当前导航项可见，维持当前位置指示。"""
        scroll = getattr(self, "_sidebar_scroll", None)
        btn = getattr(self, "nav_buttons", {}).get(page_id)
        if scroll is None or btn is None or not btn.isVisible():
            return

        # 按钮尚未布局定高时不要计算：ensureWidgetVisible 会只保证左上角点可见。
        if btn.height() <= 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda pid=page_id: self._ensure_nav_button_visible(pid))
            return
        try:
            # 上下各留一点余量，免得当前项正好贴在视口边缘上，看着像被截断
            scroll.ensureWidgetVisible(btn, 0, 24)

            self._nudge_nav_button_fully_into_view(scroll, btn)
            # ⚠ 还要**再补一次、而且要等布局落定之后**：上面两步在同一瞬间量的是同一份
            # 可能还没落定的几何，补一万次也没用；0ms 的 singleShot 排到本轮布局之后。
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                0, lambda s=scroll, b=btn: self._nudge_nav_button_fully_into_view(s, b))
        except Exception as e:
            # warning 而不是 debug：用户看不见这条日志，下次再红时它就是第一手证据
            self.logger.warning(f"导航项滚动定位失败: {e}")

    def _apply_nav_density(self):
        """宽松档（项高 28）放得下就用宽松档，放不下换紧凑档（24），默认窗口 800 高也一屏看全（批 153）。

        宽松档要多高是拿两档的差算出来的，不是切过去再量 —— 切过去量，临界高度上会来回翻。
        从紧凑档切回宽松档再多留 8px，字体度量差一两像素也翻不起来。
        """
        sidebar = getattr(self, "sidebar", None)
        scroll = getattr(self, "_sidebar_scroll", None)
        content = scroll.widget() if scroll is not None else None
        if sidebar is None or content is None:
            return
        dense = sidebar.property("navDense") is True
        items = [b for b in content.findChildren(QPushButton, "navButton") if b.isVisibleTo(content)]
        headers = [h for h in content.findChildren(QPushButton, "navGroupHeader")
                   if h.isVisibleTo(content)]
        roomy_needed = content.sizeHint().height()
        if dense:
            roomy_needed += ((NAV_ITEM_HEIGHT - NAV_ITEM_HEIGHT_DENSE) * len(items)
                             + (sum(NAV_GROUP_PAD) - sum(NAV_GROUP_PAD_DENSE)) * len(headers))
        available = scroll.viewport().height() + scroll.viewportMargins().bottom()
        want_dense = roomy_needed > available - (8 if dense else 0)
        if want_dense == dense:
            return
        sidebar.setProperty("navDense", want_dense)
        # 档位挂在侧栏上，子控件不会自己重新套样式；组头的高度还缓存在 sizeHint 里，补一个 StyleChange
        for widget in items + headers:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            QApplication.sendEvent(widget, QEvent(QEvent.StyleChange))

    def _nav_natural_geometry_changed(self, scroll) -> bool:
        """这次 Resize 是外界真变了，还是校正自己切底边距引起的（RN-732：不拦就自激）。
        「视口高 + 底边距」才是外界给的高度，边距怎么切它都不变。"""
        if scroll is None:
            return True
        content = scroll.widget()
        geometry = (
            scroll.viewport().height() + scroll.viewportMargins().bottom(),
            content.height() if content is not None else 0,
        )
        if geometry == getattr(self, "_nav_natural_geometry", None):
            return False
        self._nav_natural_geometry = geometry
        return True

    @staticmethod
    def _nudge_nav_button_fully_into_view(scroll, btn):
        """布局未落定会使 ensureWidgetVisible 少滚一截，滚后复测并补足当前项的可见范围。"""
        from PySide6.QtCore import QPoint

        viewport = scroll.viewport()
        bar = scroll.verticalScrollBar()
        # 先逼布局落定再量。`mapTo` 读的是**当前**几何，而侧栏刚换过选中态与图标，
        # 布局请求可能还挂在队列里 —— 拿陈旧几何去算，算出来的"没超出"是假的。
        try:
            content = scroll.widget()
            if content is not None and content.layout() is not None:
                content.layout().activate()
        except Exception:
            pass
        y = btn.mapTo(viewport, QPoint(0, 0)).y()
        # 高度取 max(height, sizeHint)，避免布局未定高时误把左上角可见当成整项可见。
        height = max(btn.height(), btn.sizeHint().height())
        overflow = (y + height) - viewport.height()
        if overflow > 0:
            bar.setValue(min(bar.maximum(), bar.value() + overflow))
        elif y < 0:
            bar.setValue(max(bar.minimum(), bar.value() + y))

        MainWindow._snap_nav_scroll_to_item_boundary(scroll, btn)

    @staticmethod
    def _snap_nav_scroll_to_item_boundary(scroll, keep_visible=None):
        """RN-060/178：对齐项顶边后裁掉底部余数；当前项可见性优先于边缘对齐。"""
        from PySide6.QtCore import QPoint

        # 每次都从"没有底边距"的状态重新量 —— 否则上一次吃掉的余数会进入这一次的
        # 视口高度，算出来的余数一次比一次小，最后收敛到一个跟内容无关的数。
        scroll.setViewportMargins(0, 0, 0, 0)

        bar = scroll.verticalScrollBar()
        if bar is None or bar.maximum() <= 0:
            return
        viewport = scroll.viewport()
        content = scroll.widget()
        if viewport is None or content is None:
            return

        from PySide6.QtWidgets import QAbstractButton

        # 项在**内容坐标系**里的顶边（不是视口坐标系 —— 那会随滚动变化）
        tops = sorted({
            btn.mapTo(content, QPoint(0, 0)).y()
            for btn in content.findChildren(QAbstractButton)
            if btn.isVisible() and btn.height() > 4
        })
        if not tops:
            return

        current = bar.value()
        if current in tops:
            MainWindow._trim_nav_viewport_to_item_boundary(scroll, keep_visible)
            return

        # RN-100：按距离同时尝试上下边界；项高不齐时只往上退可能把当前项挤出视口。
        below = [t for t in tops if t <= current]
        above = [t for t in tops if t > current]
        targets = []
        if below:
            targets.append(max(below))
        if above:
            targets.append(min(above))
        targets.sort(key=lambda t: abs(t - current))   # 就近优先

        def _keeps_visible() -> bool:
            if keep_visible is None:
                return True
            y = keep_visible.mapTo(viewport, QPoint(0, 0)).y()
            height = max(keep_visible.height(),
                         keep_visible.sizeHint().height())
            return y >= 0 and (y + height) <= viewport.height()

        for target in targets:
            bar.setValue(target)
            if bar.value() == target and _keeps_visible():
                MainWindow._trim_nav_viewport_to_item_boundary(scroll, keep_visible)
                return
        # 两个方向都会把当前项挤出去 —— 「当前项必须可见」优先（RN-008）
        bar.setValue(current)
        MainWindow._trim_nav_viewport_to_item_boundary(scroll, keep_visible)

    @staticmethod
    def _trim_nav_viewport_to_item_boundary(scroll, keep_visible=None):
        """RN-178：用底边距隐藏跨底边项，消除非整项视口的余数；不得隐藏当前项。"""
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QAbstractButton

        viewport = scroll.viewport()
        content = scroll.widget()
        if viewport is None or content is None:
            return
        limit = viewport.height()
        for btn in content.findChildren(QAbstractButton):
            if not btn.isVisible() or btn.height() <= 4:
                continue
            y = btn.mapTo(viewport, QPoint(0, 0)).y()
            if y < limit < y + btn.height():
                if keep_visible is not None and btn is keep_visible:
                    return
                scroll.setViewportMargins(0, 0, 0, max(0, limit - y))
                return

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
        self._ensure_nav_button_visible(current_page_id)

        if hasattr(self, '_overlay_buttons') and self._overlay_buttons:
            for btn_id, btns in self._overlay_buttons.items():
                for btn in btns:
                    btn.setChecked(btn_id == current_page_id)


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
        # RN-548：紧凑与完整档的间距调整共用入口，保证切回完整档时恢复原密度。
        try:
            from ui_style_applier import apply_compact_density
            apply_compact_density(self, bool(compact))
        except Exception:  # noqa: BLE001
            self.logger.debug("[RN-548] 紧凑密度切换失败", exc_info=True)
        if compact:
            # 紧凑模式：隐藏侧边栏，显示全局顶栏和汉堡入口
            self.sidebar.setVisible(False)
            self._dock_search_box(True)
            self._compact_header.setVisible(True)
            self._hamburger_btn.setVisible(True)
            self._mode_toggle_btn.setText("⇔ 完整界面")
            self._mode_toggle_btn.setToolTip("切换到完整模式")
            self.setMinimumSize(860, 640)
            if animate:
                self._resize_window_centered(860, 640)
            else:
                self.resize(860, 640)
        else:
            # 完整模式：显示侧边栏，保留顶栏用于设置搜索入口，但隐藏汉堡按钮
            self.sidebar.setVisible(True)
            self._dock_search_box(False)
            self._compact_header.setVisible(False)
            self._hamburger_btn.setVisible(False)
            self._mode_toggle_btn.setText("⇔ 紧凑界面")
            self._mode_toggle_btn.setToolTip("切换到紧凑模式")
            self.setMinimumSize(1200, 800)
            if animate:
                self._resize_window_centered(1200, 800)
            else:
                self._setup_window_size()
            # 关闭浮层（如果有）
            self._hide_sidebar_overlay()

    def _dock_search_box(self, compact):
        """搜索框只有一个，跟着档位搬家：下拉、最近搜索、Ctrl+F 都挂在这一个身上。"""
        box = self.settings_search_box
        if compact:
            self._sidebar_search_layout.removeWidget(box)
            self._compact_header_layout.insertWidget(1, box)
        else:
            self._compact_header_layout.removeWidget(box)
            self._sidebar_search_layout.addWidget(box)

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
            overlay_title = QLabel("CS2 Customizer")
            overlay_title.setFont(QFont(UI_FONT_FAMILY, 16, QFont.Bold))
            overlay_title.setAlignment(Qt.AlignCenter)
            overlay_nav_layout.addWidget(overlay_title)
            overlay_nav_layout.addSpacing(10)

            # 为每个导航按钮创建镜像按钮
            self._overlay_buttons = {}
            # RN-025/539：按真实布局遍历，静态 nav_groups 不含后来插入的常用组。
            for group_widget in self._nav_groups_in_view():
                # 分组标题
                group_header = QLabel(group_widget._title)
                group_header.setObjectName("overlayGroupHeader")
                group_header.setFont(QFont(UI_FONT_FAMILY, 10, QFont.Bold))
                group_header.setContentsMargins(10, 8, 0, 2)
                overlay_nav_layout.addWidget(group_header)

                # 页面顺序问分组本身；常用按钮不在 _page_to_group 反查表里。
                for page_id in self._pages_of_group(group_widget):
                    if page_id not in self.nav_buttons:
                        continue
                    overlay_btn = QPushButton(f"    {self._page_names[page_id]}")
                    overlay_btn.setObjectName("navButton")
                    overlay_btn.setCheckable(True)
                    overlay_btn.setFocusPolicy(Qt.TabFocus)   # RN-640，同上
                    overlay_btn.setChecked(self.nav_buttons[page_id].isChecked())
                    overlay_btn.clicked.connect(
                        lambda checked, pid=page_id: self.show_page(pid)
                    )
                    overlay_nav_layout.addWidget(overlay_btn)
                    # 一个 page_id 可有常用组和本组两颗镜像按钮，须全部同步，不能用字典覆盖。
                    self._overlay_buttons.setdefault(page_id, []).append(overlay_btn)

            overlay_nav_layout.addStretch()
            overlay_scroll.setWidget(overlay_nav)
            overlay_layout.addWidget(overlay_scroll)

        # 同步选中状态
        for page_id, btns in self._overlay_buttons.items():
            for btn in btns:
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
        name = "switchLabelOn" if checked else "switchLabelOff"
        if label.objectName() == name:
            return      # 状态条每 15 秒刷一遍，没变就不重新 polish
        label.setObjectName(name)
        label.style().unpolish(label)
        label.style().polish(label)

    def _find_feature_switch(self, config_key: str):
        """按配置键查首页开关；显式访问 switches 属性，保持 AST 判据可见，避免复制查表。"""
        if not hasattr(self, "switches") or not hasattr(self, "_switch_id_by_config_key"):
            return None
        switch_id = self._switch_id_by_config_key.get(config_key)
        return self.switches.get(switch_id) if switch_id else None

    def set_feature_enabled(self, config_key: str, enabled: bool) -> bool:
        """经首页开关统一触发配置与副作用；必须 toggle 发信号，不能 setChecked 或 blockSignals。
        找到并拨动开关返回 True。"""
        self.ensure_page_loaded(self._master_switch_page_id())
        toggle = self._find_feature_switch(config_key)
        if toggle is None:
            return False
        if toggle.isChecked() != bool(enabled):
            toggle.toggle()        # 与鼠标点它是同一条路
        return True

    def _master_switch_page_id(self) -> str:
        """总开关位置取 master_switch_link；就地导入以保留开源同步对顶部 import 块的补丁。"""
        from widgets.master_switch_link import MASTER_SWITCH_PAGE_ID

        return MASTER_SWITCH_PAGE_ID

    def _sync_master_switch_rows(self, config_key: str) -> int:
        """遍历已加载页同步总开关行并返回数量，避免额外注册表的生命周期维护。"""
        synced = 0
        for page in getattr(self, "pages", {}).values():
            row = getattr(page, "master_switch_row", None)
            if row is not None and getattr(row, "config_key", None) == config_key:
                row.refresh()
                synced += 1
        return synced

    def sync_feature_switch(self, config_key: str) -> bool:
        """将配置值同步到首页开关，避免页面与首页状态分叉；找到并同步返回 True。"""
        toggle = self._find_feature_switch(config_key)
        if toggle is None:
            return False
        value = bool(getattr(self.config, config_key, False))
        if toggle.isChecked() != value:
            toggle.blockSignals(True)          # 只同步显示，别再走一轮 _on_switch_changed
            toggle.setChecked(value)
            toggle.blockSignals(False)
        self._sync_feature_cards()
        return True

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
                    # 前面已把内存配置置 True，失败时需回滚，避免之后 save_config 持久化无效启用态。
                    self.config.crosshair_enabled = False
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "提示", "准心功能需要额外组件(pywin32)才能使用。\n请重新安装 CS2 Customizer 以获取完整功能。")
                    # lambda 调用下 sender() 为 None，必须按 switch_id 找回并复位开关。
                    self.sync_feature_switch(config_key)
                    # ⚠ 这条分支**提前 return**，跑不到函数末尾那次广播。
                    # 页内那一行必须也跟着弹回去，否则它会停在"开"的位置，
                    # 而功能其实没起（RN-144 升级版的判据专门盯这一条）。
                    self._sync_master_switch_rows(config_key)
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
        
        # 关闪光时须主动清叠加层；停止 GSI 转发只会让子进程停在最后一帧直至看门狗超时。
        if config_key == "flash_enabled" and not checked:
            pm = getattr(self.pages.get("flash"), "process_manager", None)
            if pm is not None and getattr(pm, "current_flash_value", 0):
                pm.force_clear_flash()
                pm.current_flash_value = 0

        # RN-454：关闭总开关须立即恢复音乐联动态，不能等 GSI 断流看门狗兜底。
        if config_key == "music_enabled" and not checked:
            try:
                from gsi_handler_music import get_music_gsi_handler

                handler = get_music_gsi_handler()
                if handler is not None:
                    handler.restore_game_link_state("关闭音乐联动总开关")
            except Exception:
                self.logger.exception("关闭音乐联动时恢复音乐状态失败")

        if config_key == "magnifier_enabled":
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._apply_magnifier_toggle(checked))

        # 关动态 HUD 时须重编默认色；移动/开火仍会 exec 运行时 cfg，否则停在最后一帧。
        if config_key == "hud_rules_enabled" and not checked:
            hud_handler = (getattr(self, "gsi_handlers", None) or {}).get("hud_color")
            if hud_handler is not None and hasattr(hud_handler, "stop"):
                hud_handler.stop()

        # 道具瞄点总开关需同步热键监听与键盘钩子，仅写 config 不能启停运行链路。
        if config_key == "utility_guide_enabled":
            utility_handler = (getattr(self, "gsi_handlers", None) or {}).get("utility")
            if utility_handler is not None:
                try:
                    if checked:
                        if getattr(utility_handler, "_runtime_ready", False):
                            utility_handler.init_hotkey_listener()
                    else:
                        utility_handler.stop_hotkey_listener()
                        display = getattr(utility_handler, "utility_display", None)
                        if display is not None:
                            display.hide()
                except Exception:
                    self.logger.exception("切换道具瞄点总开关时启停热键监听失败")

        # 特殊处理：死亡刷短视频总开关（开了就预热备好窗口，关了立刻收掉浏览器进程）
        if config_key == "fun_afterlife_enabled":
            controller = getattr(self, "afterlife_controller", None)
            if controller is not None:
                if checked:
                    controller.preheat()
                else:
                    controller.shutdown()
            page = self.pages.get("fun_afterlife") if hasattr(self, "pages") else None
            if page and hasattr(page, "_load_settings"):
                page._load_settings()

        # 击杀图标总开关必须预热/收掉素材，与页内开关走相同副作用链路。
        if config_key == "kill_icon_enabled":
            player = getattr(self, "kill_icon_player", None)
            if player is not None:
                if checked:
                    player.enable_kill_icons()
                else:
                    player.disable_kill_icons()

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

        # RN-144：首页拨动后广播到页内总开关行，与 set_feature_enabled 组成双向同步。
        self._sync_master_switch_rows(config_key)
        self._sync_feature_cards()

    
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
        """音量听不清才说话。默认就是 100%，那一头再说就成了每个人都看见的废话。"""
        label = getattr(self, "volume_hint_label", None)
        if label is None:
            return
        v = int(getattr(self.config, "volume", 0) * 100)
        if v == 0:
            tip = "已静音，拖动滑块可恢复"
        elif v < 25:
            tip = "偏低，可能在游戏中难以听清"
        else:
            tip = ""
        label.setText(tip)
        label.setVisible(bool(tip))
    
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
        # set_theme 已同步触发 _on_theme_changed 应用样式，此处再刷会重复整树 polish。
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
        # RN-403：与配置中的 ID 比较，不能从可变的显示文案反解。
        config_id = self.config.player_steamid if self.config.player_steamid else "未记录"
        if self._home_player_label_text(self.config.player_steamid) != (
                self.player_label.toolTip() or ""):
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
                "任务已提交",
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
        """QSS 相同则跳过整树 polish；字号变化会改变 QSS，仍会触发需要的重刷。"""
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
            # RN-442：QSS 落地后最小尺寸才有效，此时重扫紧凑标记；后建页面另由 _load_page 处理。
            try:
                from ui_style_applier import mark_compact_buttons
                mark_compact_buttons(self)
            except Exception:
                self.logger.debug("[RN-442] 紧凑按钮标记失败(整窗)", exc_info=True)
            self.logger.info(f"已应用主题: {self.theme_manager.current_theme.name}")
            self.logger.info(f"样式表总长度: {len(stylesheet)} 字符")
    
    def _on_theme_changed(self):
        """主题变化回调"""
        self.logger.info("主题已变化，正在更新UI...")

        # 重新应用主题样式到主窗口
        self._apply_style()
        self._refresh_home_icons()

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
            # 换主题先清图标幂等记账，再统一刷新选中态与常用分组，避免 role 不变时沿用旧色。
            for group in (self.nav_buttons, getattr(self, "_frequent_buttons", {})):
                for btn in (group or {}).values():
                    try:
                        btn.setProperty("fp_nav_icon_role", None)
                    except RuntimeError:
                        continue
            self._refresh_nav_icons()
        self._refresh_hamburger_icon()
        
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
        box.setPlaceholderText("搜索设置（Ctrl+F）")
        box.setFixedHeight(32)
        # 搜索框使用弹性宽度，为紧凑档顶栏的其余控件留空间。
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
        # 完整档框在侧栏里只有 184 宽，下拉不能跟着窄：一行要放下项名和所在页
        completer.popup().setMinimumWidth(380)
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

        # 启动即记录索引加载状态：懒搜索未触发时，没有降级告警也不能证明项级索引存在。
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
        """独立 Qt::Popup 不在主窗 QSS 树内，且裸 QListView 无配色规则；直接设置 delegate 读取的 palette。"""
        try:
            from PySide6.QtGui import QPalette

            from theme_manager import get_current_theme

            # current_theme 是 property；错误调用会被兜底吞掉并留下错误配色。
            colors = get_current_theme().colors
            popup = self._settings_search_completer.popup()
            base = QColor(getattr(colors, "bg_card", None) or colors.bg_secondary)

            # QSS 仅管边框且先于 setPalette；re-polish 会覆盖部分 palette，颜色必须最后设。
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
            # 取主题失败时保留系统默认色，并以 warning 留下可见诊断。
            self.logger.warning("搜索结果面板取主题色失败，沿用默认调色板", exc_info=True)

    # ---- 结果面板的数据供给 ----

    def _search_suggestion_rows(self, query=""):
        """无查询或无结果时给出最近搜索和常去页面，避免只有不可操作的空态。"""
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
        """每次编辑重建候选，保持结果与当前查询一致。"""
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
        """Qt::Popup 点外部就关闭，需由聚焦、点击或方向键重新打开。
        入口挂在既有 eventFilter，另定义同名方法会覆盖滚轮拦截。"""
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
        """按当前查询重建面板，避免主题或常用页变化后复用旧结果；空框显示历史和常用页。"""
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
        """R1-3: Alt+1..9 展开并跳到对应侧栏分组首页;F1 当前页帮助;Esc 收起帮助/搜索焦点。"""
        from PySide6.QtGui import QKeySequence, QShortcut

        self._app_shortcuts = []
        # Alt+数字避开音板 Ctrl+数字全局热键；按真实布局分组数分配，包含常用组，上限 9。
        for idx in range(min(9, len(self._nav_groups_in_view()))):
            sc = QShortcut(QKeySequence(f"Alt+{idx + 1}"), self)
            sc.activated.connect(lambda i=idx: self._goto_nav_group(i))
            self._app_shortcuts.append(sc)

        sc_help = QShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents), self)  # F1
        sc_help.activated.connect(self._toggle_current_page_help)
        self._app_shortcuts.append(sc_help)

        sc_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc_esc.activated.connect(self._on_escape_pressed)
        self._app_shortcuts.append(sc_esc)

    def _nav_groups_in_view(self):
        """RN-025：顺序从侧栏布局现算，包含不在静态 nav_groups 表里的常用组。"""
        layout = getattr(self, "_nav_layout", None)
        if layout is None:
            return list(getattr(self, "nav_groups", []))
        groups = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, NavGroupWidget):
                groups.append(widget)
        return groups or list(getattr(self, "nav_groups", []))

    @staticmethod
    def _pages_of_group(group):
        """按分组内按钮的 fp_page_id 取真实顺序，兼容不在反查表里的常用组。"""
        layout = getattr(group, "content_layout", None)
        if layout is None:
            return []
        pages = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is None:
                continue
            page_id = widget.property("fp_page_id")
            if page_id:
                pages.append(page_id)
        return pages

    @classmethod
    def _first_page_of_group(cls, group):
        """一个分组里的第一页。⭐ 只有一份实现（`_pages_of_group`），不抄第二遍。"""
        pages = cls._pages_of_group(group)
        return pages[0] if pages else None

    def _goto_nav_group(self, group_index):
        try:
            groups = self._nav_groups_in_view()
            group = groups[group_index]
            group.set_expanded(True)
            page_id = self._first_page_of_group(group)
            if page_id:
                self.show_page(page_id)
                return
            # 兜底：老路（按钮没带 fp_page_id 时）
            for pid, g in self._page_to_group.items():
                if g is group:
                    self.show_page(pid)
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
        """D-17：搜索打开隐藏页后提供固定入口，避免用户下次仍无法从导航找到它。"""
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
        """配置总线可能在 GSI 后台线程回调，只经 Signal 转发至 GUI 线程。"""
        try:
            self._config_reloaded_signal.emit(str(reason or ""))
        except RuntimeError:
            # 窗口已析构而总线还留着订阅——正常退出竞态，忽略
            pass

    def _on_config_reloaded(self, reason):
        """仅刷新已加载页，未加载页构造时自读新配置；逐页隔离异常，避免一页失败阻断其余页。"""
        refreshed, failed = 0, []
        changed_switches = []
        for key in getattr(self, "_switch_id_by_config_key", {}):
            toggle = self._find_feature_switch(key)
            value = bool(getattr(self.config, key, False))
            if toggle is not None and toggle.isChecked() != value:
                changed_switches.append((key, value))
        for page_id in list(getattr(self, "_loaded_pages", ())):
            page = self.pages.get(page_id)
            if page is None:
                continue
            try:
                from widgets.config_reload import reload_page_settings
                refreshed += int(reload_page_settings(page))
            except Exception:
                failed.append(page_id)
                self.logger.exception(f"[配置重载] 页面 {page_id} 刷新失败")
        self.logger.info(
            f"[配置重载] {reason}: 已刷新 {refreshed} 个已加载页面"
            + (f"，{len(failed)} 个失败: {failed}" if failed else "")
        )
        for key, value in changed_switches:
            # 恢复配置也走原有功能启停入口，避免界面已更新而运行时仍持有旧状态。
            try:
                self._on_switch_changed(key, value)
            except Exception:
                self.logger.exception(f"[配置重载] 功能 {key} 同步失败")
        for key in getattr(self, "_switch_id_by_config_key", {}):
            self.sync_feature_switch(key)
        for page in getattr(self, "pages", {}).values():
            row = getattr(page, "master_switch_row", None)
            if row is not None:
                row.refresh()
                self.sync_feature_switch(row.config_key)
        overlay = getattr(self, "screen_effect_overlay", None)
        if overlay is not None:
            overlay.update_settings_from_config()
        crosshair = getattr(self, "crosshair_animation", None)
        if crosshair is not None:
            crosshair.reload_settings()
        # 总览的卡片和状态条也读配置,一并同步
        for hook in ("_sync_feature_cards", "_tick_system_status_strip"):
            fn = getattr(self, hook, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def _find_setting_row(self, page, query, buttons=False):
        """按可见文案定位设置行；RN-744：按钮精确匹配同等，模糊匹配需 buttons=True；未中返回 None。"""
        try:
            from PySide6.QtWidgets import (
                QCheckBox,
                QLabel,
                QPushButton,
                QRadioButton,
                QStackedWidget,
                QWidget,
            )

            from core.settings_search import text_matches
            from widgets.settings_card import SettingsCard
        except Exception:
            return None

        # PySide6 findChildren 不接受类型元组，取全部 QWidget 后筛；遍历顺序保留页面控件次序。
        wanted = (QCheckBox, QRadioButton, QLabel, QPushButton)
        exact = str(query or "").strip().lower()
        best = None
        for widget in page.findChildren(QWidget):
            if not isinstance(widget, wanted):
                continue
            try:
                # isVisibleTo(page) 排除折叠内容且不依赖主窗已显示，切页未绘制时也能定位。
                if not widget.isVisibleTo(page):
                    continue
                text = str(widget.property("fp_search_text") or widget.text()).strip()
            except Exception:
                continue
            # 太短的文案（"："、"开"）匹配上多半是噪声；标题类留给卡片级去处理
            if len(text) < 2 or widget.objectName() in ("titleLabel", "cardTitle", "statusLabel"):
                continue
            if text.lower() == exact:
                best = widget
                break
            if best is None and isinstance(widget, QPushButton) == buttons and text_matches(query, text):
                best = widget
        if best is None:
            return None

        def is_whole_area(node):
            # 视口、滚动内容、页签层、页签页：高亮它们等于没定位
            parent = node.parentWidget()
            return (isinstance(node, QStackedWidget) or isinstance(parent, QStackedWidget)
                    or node.objectName() == "qt_scrollarea_viewport"
                    or (parent is not None and parent.objectName() == "qt_scrollarea_viewport"))

        # 行容器最多上溯两级并停在卡片前，避免把整块滚动内容误当成一行高亮。
        row, node, depth = best, best.parentWidget(), 0
        # 页面可以自己说「这就是一行」（`fp_setting_row`）：没有卡片的页面往上走两级就是整个页签。
        while node is not None and depth < 2 and not row.property("fp_setting_row"):
            if node is page or isinstance(node, SettingsCard) or is_whole_area(node):
                break
            row, node = node, node.parentWidget()
            depth += 1
        return row

    def _refresh_hamburger_icon(self):
        from widgets.icon_provider import get_themed_icon

        self._hamburger_btn.setIcon(get_themed_icon("mdi.menu", role="secondary", size=18))

    def _refresh_nav_icons(self, page_id=None):
        """切页、守卫回滚和换主题均须同步图标选中态，且包含常用分组的镜像按钮。"""
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

    def _step_search_highlight(self, target, state, gen=None):
        """RN-557：高亮步骤按搜索代次执行，避免旧定时器撤销同一目标上的新高亮。"""
        if gen is not None and gen != getattr(self, "_search_hit_gen", None):
            return  # 这一步是上一次搜索排的，已经过期
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
        """先激活目标页签，使 isVisibleTo(page) 能找到其内的设置项。"""
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
        """用 searchHit 属性分强、弱、撤三档高亮；仅换边框颜色，避免动画和重排。"""
        try:
            from core.settings_search import text_matches
            from widgets.settings_card import SettingsCard

            page = self.pages.get(page_id)
            if page is None:
                return

            self._activate_page_tab(page, tab_text)

            target = None
            q = str(query or "").strip()
            if q:
                # 直接在已建页面匹配控件文案，命中则定位行，未中再退回卡片定位，避免维护第二份索引。
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
            if target is None and q:
                target = self._find_setting_row(page, q, buttons=True)
            if target is None:
                from widgets.page_header import PageHeader

                headers = page.findChildren(PageHeader)
                target = headers[0] if headers else page

            self._reveal_widget(page, target)
        except Exception:
            # 高亮纯属锦上添花,任何异常都不能影响跳转本身
            pass

    def _reveal_widget(self, page, target):
        """RN-144：按控件对象统一滚动与高亮，供搜索和总开关跳转复用，不再二次模糊匹配。"""
        from PySide6.QtCore import QTimer

        # 滚动到目标(若在滚动区内)
        try:
            from PySide6.QtWidgets import QScrollArea

            # 一页可以有好几个滚动区（每个页签一个），不含目标的那个滚不动它（RN-744）
            node = target.parentWidget() if target is not page else None
            while node is not None:
                if isinstance(node, QScrollArea):
                    node.ensureWidgetVisible(target, 0, 48)
                node = node.parentWidget()
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
        self._search_hit_gen = getattr(self, "_search_hit_gen", 0) + 1
        gen = self._search_hit_gen
        self._step_search_highlight(target, "true", gen)
        QTimer.singleShot(1200, lambda t=target, g=gen: self._step_search_highlight(t, "fade", g))
        QTimer.singleShot(1600, lambda t=target, g=gen: self._step_search_highlight(t, None, g))

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
            tray.setToolTip(f"CS2 Customizer v{VERSION}")

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
                    "CS2 Customizer 仍在运行",
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
        box.setWindowTitle("关闭 CS2 Customizer")
        box.setIcon(QMessageBox.Question)
        box.setText("要把 CS2 Customizer 最小化到系统托盘，还是直接退出？")
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

    def _reset_screen_magnification(self):
        """RN-657：复位系统全屏放大变换。看门狗线程也叫它 ⇒ 任何线程上都要能跑。
        放大镜页没加载过 ⇒ 这次运行根本没碰过 Magnification API ⇒ 无事可做。"""
        page = getattr(self, 'pages', {}).get('magnifier') if hasattr(self, 'pages') else None
        reset = getattr(page, 'reset_screen_transform_now', None) if page is not None else None
        if callable(reset):
            reset()

    def _release_voice_output_on_close(self):
        """松开语音输出按下的开麦键。模块没导入过 ⇒ 这次运行从没按过键 ⇒ 无事可做
        （别为了清理去 import 它 —— 那会拉起 sounddevice/pygame 并枚举设备）。"""
        import sys as _sys
        mod = _sys.modules.get("voice_output_manager")
        manager = mod.peek_voice_output_manager() if mod is not None else None
        if manager is not None:
            manager.shutdown()

    def _run_shutdown_steps(self):
        """逐步隔离异常并计时；15 秒看门狗须先尽力落盘，再强制退出以免挂死。"""
        import os as _os
        import threading as _threading
        import time as _time

        def _watchdog_fire():
            try:
                self.logger.error("退出清理超时(15s)，触发看门狗强制退出")
            except Exception:
                pass
            # RN-657：强制退出后再无清理机会，须先复位会留在本进程之外的全屏放大。
            try:
                self._reset_screen_magnification()
            except Exception:
                pass
            try:
                self._release_voice_output_on_close()     # 同一类：漏了麦就一直开着
            except Exception:
                pass
            try:
                # RN-624：下一步 os._exit 不跑 atexit，写盘重试须在当前线程完成，不能排 daemon Timer。
                self.config.save_config_on_exit()
            except Exception:
                pass
            _os._exit(0)

        watchdog = _threading.Timer(15.0, _watchdog_fire)
        watchdog.daemon = True
        watchdog.start()

        steps = [
            # UP-035：总线活得比窗口久，先退订，避免后续广播调用已析构的 Qt 对象。
            ("退订配置重载广播", self._unsubscribe_config_reload),
            # RN-657：先复位系统放大，避免后续慢清理触发看门狗后把屏幕留在放大态。
            ("复位屏幕放大", self._reset_screen_magnification),
            # 漏掉的代价：游戏里麦一直开着（os._exit 之后没人再发抬起）。断点 `--only VOX`。
            ("松开语音开麦键", self._release_voice_output_on_close),
            ("保存音乐进度", self._save_music_progress_on_close),
            ("停止GSI服务器", lambda: self.gsi_server.stop() if getattr(self, 'gsi_server', None) else None),
            ("恢复GSI游戏内状态", self._cleanup_gsi_handlers_on_close),
            # UP-055：清理只 peek 已存在实例，不能通过惰性属性为清理创建整套音频运行时。
            ("停止音频维护任务", self._stop_audio_tasks_on_close),
            ("清理音频管理器", self._cleanup_audio_manager),
            ("清理击杀图标播放器", lambda: self.kill_icon_player.cleanup() if hasattr(self, 'kill_icon_player') else None),
            # 判 overlay_win 而非 is_visible：SW_HIDE 复用路径下 is_visible=False
            # 但窗口/绘制线程仍在，按 is_visible 判会漏销毁（残留置顶窗口+线程）
            ("隐藏准心叠加", lambda: self.crosshair_animation.destroy()
                if hasattr(self, 'crosshair_animation')
                and getattr(self.crosshair_animation, 'overlay_win', None) is not None else None),
            ("清理屏幕特效", lambda: self.screen_effect_overlay.cleanup()
                if getattr(self, 'screen_effect_overlay', None) else None),
            # 贴屏浏览器是独立进程，不在这里收掉就会在软件退出后残留在后台
            ("关闭贴屏浏览器", lambda: self.afterlife_controller.shutdown()
                if getattr(self, 'afterlife_controller', None) else None),
            ("清理放大镜", lambda: self._cleanup_page_on_close('magnifier')),
            ("清理视角自动切换", lambda: self._cleanup_page_on_close('viewmodel')),
            ("注销语音输出热键", lambda: self._cleanup_page_on_close('voice_output')),
            ("停止闪光进程", lambda: self._cleanup_page_on_close('flash')),
            ("清理动画管理器", lambda: self.animation_manager.cleanup() if hasattr(self, 'animation_manager') else None),
            ("清理页面过渡", lambda: self.page_transition.cleanup()
                if getattr(self, 'page_transition', None) else None),
            # RN-624: 退出路径上写盘失败要**当场**重试，不许排定时器 ——
            # 排了也等不到（看门狗的 os._exit 不跑 atexit）。预算见 config._EXIT_SAVE_*。
            ("落盘配置", lambda: self.config.save_config_on_exit()),
            # UP-016：退出兜底落盘去抖统计，避免丢失最后几次切页而影响常用分组和预载顺序。
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
