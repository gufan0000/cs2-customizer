#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from PySide6.QtCore import QEvent, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

import music_player as music_player_module
from config import config
from core.utils.logger import get_logger
from music_player import PLAY_MODE_LABELS, get_music_player, normalize_music_play_mode
from ui_animations import get_animation_manager

DEFAULT_TRACK_TITLE = "未播放"
UNKNOWN_TITLE = "未知标题"
UNKNOWN_ARTIST = "未知艺术家"
MINI_TRACK_PREFIX = "\u266a"
PLAY_STATE_IDLE = "idle"
PLAY_STATE_PAUSED = "paused"
PLAY_STATE_ACTIVE = "active"


class ClickableInfoCard(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setProperty("hovered", False)
        self.setProperty("pressed", False)

    def _refresh_state(self):
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def enterEvent(self, event):
        self.setProperty("hovered", True)
        self._refresh_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", False)
        self.setProperty("pressed", False)
        self._refresh_state()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setProperty("pressed", True)
            self._refresh_state()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.property("pressed"):
            self.setProperty("pressed", False)
            self._refresh_state()
            if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)


class MusicControlBar(QWidget):
    open_music_page = Signal()
    # 播放器回调可能来自加载线程/Timer线程，经 queued signal 切回主线程再碰控件
    _track_changed_sig = Signal(object)
    _state_changed_sig = Signal(bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("musicControlBar")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.logger = get_logger("MusicControlBar")
        self.player = None
        self._player_callbacks_bound = False
        self._track_changed_sig.connect(self.on_track_change)
        self._state_changed_sig.connect(self.on_state_change)
        self.animation_manager = get_animation_manager()

        self.is_expanded = bool(getattr(config, "music_bar_expanded", True))
        self.expanded_height = 112
        self.collapsed_height = 42
        self.is_dragging = False
        self.progress_save_counter = 0
        self.pre_mute_volume = int(config.music_volume * 100)
        self._mini_track_text = f"{MINI_TRACK_PREFIX} {DEFAULT_TRACK_TITLE}"
        self._track_title_text = DEFAULT_TRACK_TITLE
        self._track_artist_text = "点击打开音乐页"

        initial_height = self.expanded_height if self.is_expanded else self.collapsed_height
        self.setMinimumHeight(initial_height)
        self.setMaximumHeight(initial_height)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.init_ui()
        self._sync_bar_heights()
        self._apply_bar_mode(self.is_expanded)
        QTimer.singleShot(0, self._sync_bar_heights)

        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(1000)

        self.update_ui_state()

    def _get_existing_player(self):
        return getattr(music_player_module, "music_player", None)

    def _bind_player_callbacks(self, player):
        if player is None:
            return None
        if getattr(self, "player", None) is not player:
            self.player = player
            self._player_callbacks_bound = False
        if not getattr(self, "_player_callbacks_bound", False):
            # 绑到信号 emit 而非方法本身：播放器从工作线程回调时，
            # 直接调用会跨线程操作 Qt 控件（setText/setIcon），偶发崩溃
            if hasattr(player, "on_track_change"):
                player.on_track_change = self._track_changed_sig.emit
            if hasattr(player, "on_state_change"):
                player.on_state_change = lambda playing, paused: self._state_changed_sig.emit(
                    bool(playing), bool(paused)
                )
            self._player_callbacks_bound = True
        return player

    def _get_bound_player(self, create=False):
        player = getattr(self, "player", None)
        if player is None:
            player = get_music_player() if create else self._get_existing_player()
        return self._bind_player_callbacks(player)

    def _ensure_player(self):
        return self._get_bound_player(create=True)

    def _create_colored_icon(self, standard_icon, color):
        icon = self.style().standardIcon(standard_icon)
        pixmap = icon.pixmap(QSize(64, 64))
        colored_pixmap = QPixmap(pixmap.size())
        colored_pixmap.fill(Qt.transparent)

        painter = QPainter(colored_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), color)
        painter.end()

        return QIcon(colored_pixmap)

    def _get_icon_color(self):
        from theme_manager import get_theme_manager

        theme_manager = get_theme_manager()
        if theme_manager.current_theme_name == "dark":
            return QColor(255, 255, 255, 255)
        if theme_manager.current_theme_name == "light":
            return QColor(60, 60, 60, 255)
        return QColor(100, 100, 100, 255)

    def _create_themed_icon(self, standard_icon):
        return self._create_colored_icon(standard_icon, self._get_icon_color())

    def refresh_icons(self):
        player = self._get_bound_player(create=False)
        is_playing = bool(getattr(player, "is_playing", False))
        is_paused = bool(getattr(player, "is_paused", False))

        if is_playing and not is_paused:
            icon = self._create_themed_icon(QStyle.SP_MediaPause)
            self.play_pause_btn.setIcon(icon)
            self.mini_play_btn.setIcon(icon)
        else:
            icon = self._create_themed_icon(QStyle.SP_MediaPlay)
            self.play_pause_btn.setIcon(icon)
            self.mini_play_btn.setIcon(icon)

        self.prev_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaSkipBackward))
        self.next_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaSkipForward))

        self._update_mode_ui()
        self._update_volume_ui(self.volume_slider.value())
        self._apply_bar_mode(self.is_expanded)
        self._update_play_state_visual(is_playing, is_paused)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.mini_bar = QWidget()
        self.mini_bar.setObjectName("miniBar")
        self.mini_bar.setAttribute(Qt.WA_StyledBackground, True)
        mini_layout = QHBoxLayout(self.mini_bar)
        mini_layout.setContentsMargins(18, 0, 18, 2)
        mini_layout.setSpacing(10)

        self.mini_track_label = QLabel(f"{MINI_TRACK_PREFIX} {DEFAULT_TRACK_TITLE}")
        self.mini_track_label.setObjectName("musicMiniTrackLabel")
        self.mini_track_label.setFont(QFont("Microsoft YaHei", 10))
        self.mini_track_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.mini_track_label.setFixedHeight(self.mini_track_label.fontMetrics().height() + 4)
        self.mini_track_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mini_track_label.setToolTip(DEFAULT_TRACK_TITLE)
        mini_layout.addWidget(self.mini_track_label, 1)

        self.mini_play_btn = QPushButton()
        self.mini_play_btn.setObjectName("actionButton")
        self.mini_play_btn.setFixedSize(30, 30)
        self.mini_play_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaPlay))
        self.mini_play_btn.setIconSize(QSize(17, 17))
        self.mini_play_btn.setToolTip("播放")
        self.mini_play_btn.clicked.connect(self.toggle_play_pause)
        self.mini_play_btn.setCursor(Qt.PointingHandCursor)
        mini_layout.addWidget(self.mini_play_btn)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("actionButton")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.setIcon(self._create_themed_icon(QStyle.SP_TitleBarUnshadeButton))
        self.toggle_btn.setIconSize(QSize(14, 14))
        self.toggle_btn.setToolTip("收起播放栏")
        self.toggle_btn.clicked.connect(self.toggle_expand)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        mini_layout.addWidget(self.toggle_btn)

        main_layout.addWidget(self.mini_bar)

        self.full_controls = QWidget()
        self.full_controls.setObjectName("musicFullControls")
        self.full_controls.setAttribute(Qt.WA_StyledBackground, True)
        full_layout = QVBoxLayout(self.full_controls)
        full_layout.setContentsMargins(18, 2, 18, 8)
        full_layout.setSpacing(6)

        self._create_progress_bar(full_layout)
        self._create_main_controls(full_layout)
        main_layout.addWidget(self.full_controls)

    def _create_progress_bar(self, parent_layout):
        progress_container = QWidget()
        progress_container.setObjectName("musicProgressRow")
        progress_container.setAttribute(Qt.WA_StyledBackground, True)
        progress_layout = QHBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)

        self.current_time_label = QLabel("0:00")
        self.current_time_label.setObjectName("musicTimeLabel")
        self.current_time_label.setFont(QFont("Microsoft YaHei", 9))
        self.current_time_label.setFixedWidth(35)
        progress_layout.addWidget(self.current_time_label)

        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setObjectName("slider")
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        self.progress_slider.sliderPressed.connect(self.on_progress_press)
        self.progress_slider.sliderMoved.connect(self.on_progress_drag)
        self.progress_slider.sliderReleased.connect(self.on_progress_release)
        progress_layout.addWidget(self.progress_slider, 1)

        self.total_time_label = QLabel("0:00")
        self.total_time_label.setObjectName("musicTimeLabel")
        self.total_time_label.setFont(QFont("Microsoft YaHei", 9))
        self.total_time_label.setFixedWidth(35)
        progress_layout.addWidget(self.total_time_label)

        parent_layout.addWidget(progress_container)

    def _create_main_controls(self, parent_layout):
        controls_container = QWidget()
        controls_container.setObjectName("musicControlsRow")
        controls_container.setAttribute(Qt.WA_StyledBackground, True)
        controls_layout = QHBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(16)

        self.song_info_btn = ClickableInfoCard()
        self.song_info_btn.setObjectName("musicInfoButton")
        self.song_info_btn.clicked.connect(lambda: self.open_music_page.emit())
        self.song_info_btn.setCursor(Qt.PointingHandCursor)
        self.song_info_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.song_info_btn.setMinimumWidth(0)
        self.song_info_btn.setMaximumWidth(420)
        self.song_info_btn.setMinimumHeight(56)

        song_info_layout = QVBoxLayout(self.song_info_btn)
        song_info_layout.setContentsMargins(12, 8, 12, 8)
        song_info_layout.setSpacing(2)

        self.track_title_label = QLabel(DEFAULT_TRACK_TITLE)
        self.track_title_label.setObjectName("musicTrackTitle")
        self.track_title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.track_title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.track_title_label.setFixedHeight(self.track_title_label.fontMetrics().height() + 6)
        self.track_title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        song_info_layout.addWidget(self.track_title_label)

        self.track_artist_label = QLabel("点击打开音乐页")
        self.track_artist_label.setObjectName("musicTrackArtist")
        self.track_artist_label.setFont(QFont("Microsoft YaHei", 9))
        self.track_artist_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.track_artist_label.setFixedHeight(self.track_artist_label.fontMetrics().height() + 5)
        self.track_artist_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        song_info_layout.addWidget(self.track_artist_label)

        controls_layout.addWidget(self.song_info_btn, 1, Qt.AlignVCenter)

        self.playback_group = QWidget()
        playback_layout = QHBoxLayout(self.playback_group)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(8)

        self.prev_btn = QPushButton()
        self.prev_btn.setObjectName("actionButton")
        self.prev_btn.setFixedSize(30, 30)
        self.prev_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaSkipBackward))
        self.prev_btn.setIconSize(QSize(16, 16))
        self.prev_btn.setToolTip("上一首 (Ctrl+Left)")
        self.prev_btn.clicked.connect(self.play_previous)
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        playback_layout.addWidget(self.prev_btn)

        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setObjectName("primaryButton")
        self.play_pause_btn.setFixedSize(44, 36)
        self.play_pause_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setIconSize(QSize(18, 18))
        self.play_pause_btn.setToolTip("播放 (Space)")
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        self.play_pause_btn.setCursor(Qt.PointingHandCursor)
        playback_layout.addWidget(self.play_pause_btn)

        self.next_btn = QPushButton()
        self.next_btn.setObjectName("actionButton")
        self.next_btn.setFixedSize(30, 30)
        self.next_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaSkipForward))
        self.next_btn.setIconSize(QSize(16, 16))
        self.next_btn.setToolTip("下一首 (Ctrl+Right)")
        self.next_btn.clicked.connect(self.play_next)
        self.next_btn.setCursor(Qt.PointingHandCursor)
        playback_layout.addWidget(self.next_btn)

        self.playback_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        controls_layout.addWidget(self.playback_group, 0, Qt.AlignCenter)

        utility_group = QWidget()
        utility_group.setObjectName("musicUtilityGroup")
        utility_group.setAttribute(Qt.WA_StyledBackground, True)
        utility_group.setFixedHeight(40)
        right_layout = QHBoxLayout(utility_group)
        right_layout.setContentsMargins(10, 4, 10, 4)
        right_layout.setSpacing(8)

        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("actionButton")
        self.mode_btn.setFixedSize(28, 28)
        self.mode_btn.setIconSize(QSize(16, 16))
        self.mode_btn.setToolTip("播放模式: 顺序播放")
        self.mode_btn.clicked.connect(self.cycle_play_mode)
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        right_layout.addWidget(self.mode_btn)

        self.volume_btn = QPushButton()
        self.volume_btn.setObjectName("actionButton")
        self.volume_btn.setFixedSize(28, 28)
        self.volume_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaVolume))
        self.volume_btn.setIconSize(QSize(16, 16))
        self.volume_btn.setToolTip("音量控制")
        self.volume_btn.clicked.connect(self.toggle_mute)
        self.volume_btn.setCursor(Qt.PointingHandCursor)
        right_layout.addWidget(self.volume_btn)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("slider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(config.music_volume * 100))
        self.volume_slider.setFixedWidth(92)
        self.volume_slider.valueChanged.connect(self.on_volume_change)
        right_layout.addWidget(self.volume_slider)

        controls_layout.addWidget(utility_group, 0, Qt.AlignRight)
        parent_layout.addWidget(controls_container)

    def _repolish_widget(self, widget):
        if widget is None:
            return
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _sync_bar_heights(self):
        mini_height = max(40, self.mini_bar.sizeHint().height())
        full_height = max(0, self.full_controls.sizeHint().height())
        target_expanded = max(112, mini_height + full_height)
        target_collapsed = max(42, mini_height)

        self.expanded_height = target_expanded
        self.collapsed_height = target_collapsed

        target_height = self.expanded_height if self.is_expanded else self.collapsed_height
        if self.minimumHeight() != target_height:
            self.setMinimumHeight(target_height)
        if self.maximumHeight() != target_height:
            self.setMaximumHeight(target_height)

    def _set_elided_text(self, label, text):
        clean_text = str(text or "")
        width = max(0, label.width() - 2)
        if width > 0:
            clean_text = label.fontMetrics().elidedText(clean_text, Qt.ElideRight, width)
        label.setText(clean_text)

    def _refresh_track_labels(self):
        self._set_elided_text(self.mini_track_label, self._mini_track_text)
        self._set_elided_text(self.track_title_label, self._track_title_text)
        self._set_elided_text(self.track_artist_label, self._track_artist_text)

    def _format_time_label(self, seconds):
        total_seconds = max(0, int(float(seconds or 0)))
        minutes = total_seconds // 60
        remainder = total_seconds % 60
        return f"{minutes}:{remainder:02d}"

    def _apply_progress_display(self, current_seconds, total_seconds):
        total = max(0.0, float(total_seconds or 0))
        current = max(0.0, float(current_seconds or 0))
        if total > 0:
            current = min(current, total)
            progress = int((current / total) * 1000)
        else:
            progress = 0

        self.progress_slider.blockSignals(True)
        self.progress_slider.setValue(progress)
        self.progress_slider.blockSignals(False)
        self.current_time_label.setText(self._format_time_label(current))
        self.total_time_label.setText(self._format_time_label(total))

    def _get_saved_track_from_config(self):
        playlists = getattr(config, "music_playlists", {}) or {}
        playlist_name = str(getattr(config, "music_current_playlist", "") or "")
        playlist = playlists.get(playlist_name)
        if playlist is None:
            playlist = playlists.get("默认", [])
        if not isinstance(playlist, list):
            return None

        try:
            index = int(getattr(config, "music_current_index", -1))
        except (TypeError, ValueError):
            return None

        if index < 0 or index >= len(playlist):
            return None

        track = playlist[index]
        return track if isinstance(track, dict) and track else None

    def _apply_saved_state_from_config(self):
        track = self._get_saved_track_from_config()
        if not track:
            return False

        self.on_track_change(track)
        self._apply_progress_display(
            getattr(config, "music_current_position", 0),
            track.get("duration", 0),
        )
        self.on_state_change(False, False)
        return True

    def _clean_track_value(self, value):
        text = str(value or "").strip()
        return text

    def _format_track_title(self, track):
        title = self._clean_track_value(track.get("title") or track.get("name"))
        if title:
            return title

        raw_path = self._clean_track_value(track.get("path") or track.get("_resolved_path"))
        if raw_path:
            normalized_path = raw_path.replace("\\", "/").split("?", 1)[0]
            filename = os.path.basename(normalized_path)
            if filename:
                return filename
            return raw_path

        return UNKNOWN_TITLE

    def _format_track_artist(self, track):
        artist = self._clean_track_value(
            track.get("artist") or track.get("album_artist") or track.get("uploader") or track.get("album")
        )
        if artist:
            return artist

        track_type = self._clean_track_value(track.get("type"))
        if track_type == "local":
            return "本地音频"
        if track_type == "url":
            return "网络音频"
        return ""

    def _get_display_track(self, player=None):
        player = player or self._get_bound_player(create=False)
        if player is None:
            return None

        track = getattr(player, "current_track", None)
        if isinstance(track, dict) and track:
            return track

        getter = getattr(player, "get_current_track", None)
        if callable(getter):
            try:
                track = getter()
            except Exception:
                track = None

        if isinstance(track, dict) and track:
            return track
        return None

    def _update_play_state_visual(self, is_playing, is_paused):
        if is_playing and not is_paused:
            play_state = PLAY_STATE_ACTIVE
        elif is_playing:
            play_state = PLAY_STATE_PAUSED
        else:
            play_state = PLAY_STATE_IDLE

        for widget in (getattr(self, "song_info_btn", None),):
            if widget is not None and widget.property("playState") != play_state:
                widget.setProperty("playState", play_state)
                self._repolish_widget(widget)

    def _update_mode_ui(self, mode=None):
        mode_icons = {
            "sequence": QStyle.SP_MediaPlay,
            "shuffle": QStyle.SP_BrowserReload,
            "repeat_one": QStyle.SP_BrowserStop,
            "repeat_all": QStyle.SP_BrowserReload,
        }
        normalized_mode = normalize_music_play_mode(mode or config.music_play_mode)
        label = PLAY_MODE_LABELS.get(normalized_mode, PLAY_MODE_LABELS["sequence"])
        self.mode_btn.setIcon(self._create_themed_icon(mode_icons.get(normalized_mode, QStyle.SP_MediaPlay)))
        self.mode_btn.setToolTip(f"播放模式: {label}")
        return normalized_mode

    def _update_volume_ui(self, value):
        if value == 0:
            self.volume_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaVolumeMuted))
        else:
            self.volume_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaVolume))


    def _apply_bar_mode(self, expanded):
        self.mini_bar.setVisible(True)
        self.full_controls.setVisible(expanded)

        if hasattr(self, "toggle_btn"):
            if expanded:
                self.toggle_btn.setIcon(self._create_themed_icon(QStyle.SP_TitleBarUnshadeButton))
                self.toggle_btn.setToolTip("收起播放栏")
            else:
                self.toggle_btn.setIcon(self._create_themed_icon(QStyle.SP_TitleBarShadeButton))
                self.toggle_btn.setToolTip("展开播放栏")

    def toggle_expand(self):
        if self.is_expanded:
            target_height = self.collapsed_height
        else:
            target_height = self.expanded_height

        self.min_height_animation = QPropertyAnimation(self, b"minimumHeight")
        self.min_height_animation.setDuration(300)
        self.min_height_animation.setStartValue(self.minimumHeight())
        self.min_height_animation.setEndValue(target_height)
        self.min_height_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.max_height_animation = QPropertyAnimation(self, b"maximumHeight")
        self.max_height_animation.setDuration(300)
        self.max_height_animation.setStartValue(self.maximumHeight())
        self.max_height_animation.setEndValue(target_height)
        self.max_height_animation.setEasingCurve(QEasingCurve.InOutCubic)

        self.animation_group = QParallelAnimationGroup()
        self.animation_group.addAnimation(self.min_height_animation)
        self.animation_group.addAnimation(self.max_height_animation)
        self.animation_group.start()

        self.is_expanded = not self.is_expanded
        self._apply_bar_mode(self.is_expanded)
        config.music_bar_expanded = self.is_expanded
        config.save_config()

    def play_previous(self):
        self._ensure_player().previous()

    def play_next(self):
        self._ensure_player().next()

    def toggle_play_pause(self):
        try:
            player = self._ensure_player()
            if player.is_playing:
                if player.is_paused:
                    player.resume()
                    self.logger.info("恢复播放")
                else:
                    player.pause()
                    self.logger.info("暂停播放")
            else:
                playlist = player.get_playlist()
                if playlist:
                    # 从停止态恢复时优先续播当前/上次曲目，而不是恒定回第一首
                    index = player.current_index if 0 <= player.current_index < len(playlist) else 0
                    player.play(index)
                    self.logger.info("开始播放")
        except Exception as e:
            self.logger.error(f"播放控制失败: {e}")

    def cycle_play_mode(self):
        modes = ["sequence", "shuffle", "repeat_one", "repeat_all"]

        current = normalize_music_play_mode(config.music_play_mode)
        current_index = modes.index(current) if current in modes else 0
        next_mode = modes[(current_index + 1) % len(modes)]

        config.music_play_mode = next_mode
        config.save_config()

        player = self._get_bound_player(create=False)
        if player is not None:
            player.set_play_mode(next_mode)

        self._update_mode_ui(next_mode)
        self.logger.info(f"播放模式已切换: {PLAY_MODE_LABELS[next_mode]}")

    def toggle_mute(self):
        if self.volume_slider.value() > 0:
            self.pre_mute_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
        else:
            self.volume_slider.setValue(self.pre_mute_volume or 50)

    def on_volume_change(self, value):
        volume = value / 100.0
        config.music_volume = volume
        config.save_config()

        player = self._get_bound_player(create=False)
        if player is not None:
            player.set_volume(volume)

        self._update_volume_ui(value)

    def on_progress_press(self):
        self.is_dragging = True

    def on_progress_release(self):
        self.is_dragging = False
        value = self.progress_slider.value()
        try:
            player = self._get_bound_player(create=False)
            if player is None or not hasattr(player, "get_current_track") or not hasattr(player, "seek"):
                return
            current_track = player.get_current_track()
            if not current_track:
                return
            duration = current_track.get("duration", 0)
            if duration > 0:
                position = (value / 1000.0) * duration
                player.seek(position)
                self.logger.info(f"跳转到 {position:.1f} 秒")
        except Exception as e:
            self.logger.error(f"拖动进度条失败: {e}")

    def on_progress_drag(self, value):
        try:
            player = self._get_bound_player(create=False)
            if player is None or not hasattr(player, "get_current_track"):
                return
            current_track = player.get_current_track()
            if not current_track:
                return
            duration = current_track.get("duration", 0)
            if duration > 0:
                position = (value / 1000.0) * duration
                current_min = int(position // 60)
                current_sec = int(position % 60)
                self.current_time_label.setText(f"{current_min}:{current_sec:02d}")
        except Exception:
            pass

    def update_progress(self):
        if self.is_dragging:
            return

        try:
            player = self._get_bound_player(create=False)
            if player is None or not hasattr(player, "get_progress"):
                self._apply_saved_state_from_config()
                return

            display_track = self._get_display_track(player)
            if display_track:
                self.on_track_change(display_track)

            current, total = player.get_progress()
            if total <= 0:
                return

            self._apply_progress_display(current, total)

            self.progress_save_counter += 1
            if self.progress_save_counter >= 10:
                self.progress_save_counter = 0
                config.music_current_position = current
                config.music_current_index = player.current_index
                config.save_config()
        except Exception:
            pass

    def on_track_change(self, track):
        if track:
            title = self._format_track_title(track)
            artist = self._format_track_artist(track)
            self._track_title_text = title
            self.track_title_label.setToolTip(title)
            self._track_artist_text = artist or "点击打开音乐页"
            self.track_artist_label.setToolTip(self._track_artist_text)

            mini_text = f"{MINI_TRACK_PREFIX} {title}"
            if artist:
                mini_text += f" - {artist}"
            self._mini_track_text = mini_text
            self.mini_track_label.setToolTip(mini_text)
            self._refresh_track_labels()

            duration = track.get("duration", 0)
            if duration > 0:
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                self.total_time_label.setText(f"{minutes}:{seconds:02d}")
            return

        self._track_title_text = DEFAULT_TRACK_TITLE
        self.track_title_label.setToolTip(DEFAULT_TRACK_TITLE)
        self._track_artist_text = "点击打开音乐页"
        self.track_artist_label.setToolTip(self._track_artist_text)
        self._mini_track_text = f"{MINI_TRACK_PREFIX} {DEFAULT_TRACK_TITLE}"
        self.mini_track_label.setToolTip(DEFAULT_TRACK_TITLE)
        self._refresh_track_labels()
        self.total_time_label.setText("0:00")
        self.current_time_label.setText("0:00")

    def on_state_change(self, is_playing, is_paused):
        if is_playing and not is_paused:
            self.play_pause_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaPause))
            self.play_pause_btn.setToolTip("暂停")
            self.mini_play_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaPause))
        else:
            self.play_pause_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaPlay))
            self.play_pause_btn.setToolTip("播放")
            self.mini_play_btn.setIcon(self._create_themed_icon(QStyle.SP_MediaPlay))
        self._update_play_state_visual(is_playing, is_paused)

    def update_ui_state(self):
        self._update_mode_ui()
        self._update_volume_ui(self.volume_slider.value())

        player = self._get_bound_player(create=False)
        if player is None:
            if not self._apply_saved_state_from_config():
                self.on_track_change(None)
                self.on_state_change(False, False)
            return

        current_track = self._get_display_track(player)
        self.on_track_change(current_track)
        self.on_state_change(bool(getattr(player, "is_playing", False)), bool(getattr(player, "is_paused", False)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_track_labels()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_bar_heights)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange, QEvent.PaletteChange):
            QTimer.singleShot(0, self._sync_bar_heights)
