# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes
import math
import random
import sys
import time

from PySide6.QtCore import QLineF, QObject, QPointF, QRect, QRectF, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from core.utils.logger import get_logger


DEFAULT_SCREEN_EFFECT_PRESET = "impact_sparks"
DEFAULT_SCREEN_EFFECT_PLAY_MODE = "streak"
SCREEN_EFFECT_PLAY_MODES = ("steady", "streak", "chaos")

SCREEN_EFFECT_PRESETS = {
    "lite_competitive": {
        "label": "轻量竞技",
        "color": "#ff684d",
        "spark_color": "#ffe7cf",
        "duration_ms": 300,
        "edge_ratio": 0.080,
        "edge_alpha": 0.40,
        "particle_count": 90,
        "particle_speed_min": 420.0,
        "particle_speed_max": 790.0,
        "particle_size_min": 1.1,
        "particle_size_max": 2.6,
        "particle_life_min_ms": 120,
        "particle_life_max_ms": 260,
        "particle_drag": 0.915,
        "spark_alpha": 0.72,
        "trail_alpha": 0.12,
        "wave2_ratio": 0.28,
        "wave2_delay_ms": 56,
        "wave3_ratio": 0.00,
        "wave3_delay_ms": 0,
        "spawn_mode": "edges",
        "pulse_freq_hz": 3.6,
        "pulse_amount": 0.08,
        "headshot_duration_scale": 1.10,
        "headshot_edge_alpha_scale": 1.15,
        "headshot_particle_scale": 1.22,
        "headshot_spark_alpha_scale": 1.12,
    },
    "impact_sparks": {
        "label": "冲击火花",
        "color": "#ff4b35",
        "spark_color": "#ffe1c5",
        "duration_ms": 420,
        "edge_ratio": 0.106,
        "edge_alpha": 0.55,
        "particle_count": 150,
        "particle_speed_min": 550.0,
        "particle_speed_max": 1020.0,
        "particle_size_min": 1.3,
        "particle_size_max": 3.3,
        "particle_life_min_ms": 150,
        "particle_life_max_ms": 320,
        "particle_drag": 0.902,
        "spark_alpha": 0.86,
        "trail_alpha": 0.22,
        "wave2_ratio": 0.28,
        "wave2_delay_ms": 56,
        "wave3_ratio": 0.16,
        "wave3_delay_ms": 118,
        "spawn_mode": "edges",
        "pulse_freq_hz": 5.1,
        "pulse_amount": 0.14,
        "headshot_duration_scale": 1.13,
        "headshot_edge_alpha_scale": 1.21,
        "headshot_particle_scale": 1.30,
        "headshot_spark_alpha_scale": 1.18,
    },
    "frenzy_kill": {
        "label": "狂热击杀",
        "color": "#ff3b2f",
        "spark_color": "#ffe8cc",
        "duration_ms": 540,
        "edge_ratio": 0.128,
        "edge_alpha": 0.66,
        "particle_count": 220,
        "particle_speed_min": 660.0,
        "particle_speed_max": 1260.0,
        "particle_size_min": 1.4,
        "particle_size_max": 4.0,
        "particle_life_min_ms": 180,
        "particle_life_max_ms": 380,
        "particle_drag": 0.892,
        "spark_alpha": 0.95,
        "trail_alpha": 0.34,
        "wave2_ratio": 0.30,
        "wave2_delay_ms": 64,
        "wave3_ratio": 0.20,
        "wave3_delay_ms": 140,
        "spawn_mode": "edges",
        "pulse_freq_hz": 6.2,
        "pulse_amount": 0.22,
        "headshot_duration_scale": 1.15,
        "headshot_edge_alpha_scale": 1.25,
        "headshot_particle_scale": 1.36,
        "headshot_spark_alpha_scale": 1.24,
    },
    "blue_storm": {
        "label": "电磁风暴",
        "color": "#3ea3ff",
        "spark_color": "#d8f4ff",
        "duration_ms": 590,
        "edge_ratio": 0.120,
        "edge_alpha": 0.58,
        "particle_count": 190,
        "particle_speed_min": 560.0,
        "particle_speed_max": 1120.0,
        "particle_size_min": 1.2,
        "particle_size_max": 3.4,
        "particle_life_min_ms": 210,
        "particle_life_max_ms": 430,
        "particle_drag": 0.906,
        "spark_alpha": 0.84,
        "trail_alpha": 0.42,
        "wave2_ratio": 0.30,
        "wave2_delay_ms": 82,
        "wave3_ratio": 0.18,
        "wave3_delay_ms": 170,
        "spawn_mode": "left_right",
        "pulse_freq_hz": 4.6,
        "pulse_amount": 0.20,
        "headshot_duration_scale": 1.14,
        "headshot_edge_alpha_scale": 1.20,
        "headshot_particle_scale": 1.30,
        "headshot_spark_alpha_scale": 1.18,
    },
    "neon_pulse": {
        "label": "霓虹脉冲",
        "color": "#ff44ae",
        "spark_color": "#f2fcff",
        "duration_ms": 640,
        "edge_ratio": 0.118,
        "edge_alpha": 0.60,
        "particle_count": 200,
        "particle_speed_min": 500.0,
        "particle_speed_max": 1060.0,
        "particle_size_min": 1.3,
        "particle_size_max": 3.6,
        "particle_life_min_ms": 220,
        "particle_life_max_ms": 480,
        "particle_drag": 0.908,
        "spark_alpha": 0.88,
        "trail_alpha": 0.48,
        "wave2_ratio": 0.32,
        "wave2_delay_ms": 88,
        "wave3_ratio": 0.20,
        "wave3_delay_ms": 188,
        "spawn_mode": "center",
        "pulse_freq_hz": 7.0,
        "pulse_amount": 0.28,
        "headshot_duration_scale": 1.16,
        "headshot_edge_alpha_scale": 1.24,
        "headshot_particle_scale": 1.30,
        "headshot_spark_alpha_scale": 1.24,
    },
    "toxic_surge": {
        "label": "剧毒涌动",
        "color": "#5ad65e",
        "spark_color": "#efffd5",
        "duration_ms": 610,
        "edge_ratio": 0.116,
        "edge_alpha": 0.58,
        "particle_count": 176,
        "particle_speed_min": 520.0,
        "particle_speed_max": 1040.0,
        "particle_size_min": 1.4,
        "particle_size_max": 3.8,
        "particle_life_min_ms": 220,
        "particle_life_max_ms": 450,
        "particle_drag": 0.900,
        "spark_alpha": 0.86,
        "trail_alpha": 0.32,
        "wave2_ratio": 0.28,
        "wave2_delay_ms": 82,
        "wave3_ratio": 0.18,
        "wave3_delay_ms": 176,
        "spawn_mode": "top_bottom",
        "pulse_freq_hz": 5.3,
        "pulse_amount": 0.18,
        "headshot_duration_scale": 1.15,
        "headshot_edge_alpha_scale": 1.22,
        "headshot_particle_scale": 1.28,
        "headshot_spark_alpha_scale": 1.20,
    },
    "amber_overdrive": {
        "label": "琥珀超载",
        "color": "#ff9f2f",
        "spark_color": "#fff4ce",
        "duration_ms": 690,
        "edge_ratio": 0.136,
        "edge_alpha": 0.64,
        "particle_count": 236,
        "particle_speed_min": 590.0,
        "particle_speed_max": 1180.0,
        "particle_size_min": 1.5,
        "particle_size_max": 4.3,
        "particle_life_min_ms": 230,
        "particle_life_max_ms": 520,
        "particle_drag": 0.895,
        "spark_alpha": 0.92,
        "trail_alpha": 0.40,
        "wave2_ratio": 0.32,
        "wave2_delay_ms": 96,
        "wave3_ratio": 0.22,
        "wave3_delay_ms": 210,
        "spawn_mode": "corners",
        "pulse_freq_hz": 4.8,
        "pulse_amount": 0.16,
        "headshot_duration_scale": 1.18,
        "headshot_edge_alpha_scale": 1.24,
        "headshot_particle_scale": 1.34,
        "headshot_spark_alpha_scale": 1.22,
    },
    "frost_shock": {
        "label": "寒霜震爆",
        "color": "#8dc8ff",
        "spark_color": "#f6fcff",
        "duration_ms": 670,
        "edge_ratio": 0.124,
        "edge_alpha": 0.57,
        "particle_count": 184,
        "particle_speed_min": 470.0,
        "particle_speed_max": 960.0,
        "particle_size_min": 1.2,
        "particle_size_max": 3.3,
        "particle_life_min_ms": 250,
        "particle_life_max_ms": 560,
        "particle_drag": 0.914,
        "spark_alpha": 0.82,
        "trail_alpha": 0.40,
        "wave2_ratio": 0.30,
        "wave2_delay_ms": 96,
        "wave3_ratio": 0.22,
        "wave3_delay_ms": 208,
        "spawn_mode": "top_bottom",
        "pulse_freq_hz": 4.0,
        "pulse_amount": 0.14,
        "headshot_duration_scale": 1.18,
        "headshot_edge_alpha_scale": 1.22,
        "headshot_particle_scale": 1.26,
        "headshot_spark_alpha_scale": 1.18,
    },
}


def _clamp_float(value, minimum, maximum, fallback):
    try:
        return max(minimum, min(maximum, float(value)))
    except Exception:
        return fallback


def _clamp_int(value, minimum, maximum, fallback):
    try:
        return max(minimum, min(maximum, int(value)))
    except Exception:
        return fallback


def _resolve_color(value, fallback):
    if isinstance(value, QColor) and value.isValid():
        return QColor(value)
    if isinstance(value, str):
        color = QColor(value.strip())
        if color.isValid():
            return color
    return QColor(fallback)


def _normalize_preset(value, fallback=DEFAULT_SCREEN_EFFECT_PRESET):
    key = ""
    if isinstance(value, str):
        key = value.strip().lower()
    if key in SCREEN_EFFECT_PRESETS:
        return key
    return fallback


def _normalize_play_mode(value, fallback=DEFAULT_SCREEN_EFFECT_PLAY_MODE):
    key = ""
    if isinstance(value, str):
        key = value.strip().lower()
    if key in SCREEN_EFFECT_PLAY_MODES:
        return key
    return fallback


def _mix_color(color_a, color_b, weight):
    t = _clamp_float(weight, 0.0, 1.0, 0.5)
    inv_t = 1.0 - t
    out = QColor(
        int(color_a.red() * inv_t + color_b.red() * t),
        int(color_a.green() * inv_t + color_b.green() * t),
        int(color_a.blue() * inv_t + color_b.blue() * t),
    )
    out.setAlpha(255)
    return out


class EdgeParticleOverlay(QWidget):
    def __init__(self):
        super().__init__(None)
        self.logger = get_logger("EdgeParticleOverlay")
        self._windows_style_applied = False

        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        transparent_flag = getattr(Qt, "WindowTransparentForInput", None)
        if transparent_flag is None and hasattr(Qt, "WindowType"):
            transparent_flag = getattr(Qt.WindowType, "WindowTransparentForInput", None)
        if transparent_flag is not None:
            flags |= transparent_flag
        no_focus_flag = getattr(Qt, "WindowDoesNotAcceptFocus", None)
        if no_focus_flag is None and hasattr(Qt, "WindowType"):
            no_focus_flag = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
        if no_focus_flag is not None:
            flags |= no_focus_flag
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self._tick)

        self._active = False
        self._start_time = 0.0
        self._last_tick = 0.0
        self._elapsed_ms = 0.0

        self._duration_ms = 420
        self._edge_width = 56
        self._peak_edge_alpha = 0.55
        self._base_color = QColor("#ff4b35")
        self._spark_color = QColor("#ffe1c5")

        self._particle_count = 150
        self._particle_speed_min = 550.0
        self._particle_speed_max = 1020.0
        self._particle_size_min = 1.3
        self._particle_size_max = 3.3
        self._particle_life_min_s = 0.150
        self._particle_life_max_s = 0.320
        self._particle_drag = 0.902
        self._spark_alpha = 0.86
        self._trail_alpha = 0.22
        self._ring_enabled = False
        self._ring_alpha = 0.22
        self._ring_thickness = 2.6
        self._ring_duration_ms = 320
        self._ring_start_ratio = 0.08
        self._ring_end_ratio = 0.84
        self._ring_color = QColor("#ffe1c5")

        self._spawn_mode = "edges"
        self._pulse_freq_hz = 5.1
        self._pulse_amount = 0.14

        self._pending_waves = []
        self._particles = []
        self._runtime_quality_scale = 1.0
        self._quality_scale_last = 1.0
        self._paint_cost_ema_ms = 0.0

    def play(self, style):
        style = style or {}
        self._refresh_geometry()

        min_edge_ref = max(1, min(self.width(), self.height()))

        self._duration_ms = _clamp_int(style.get("duration_ms", 420), 140, 1400, 420)
        self._peak_edge_alpha = _clamp_float(style.get("edge_alpha", 0.55), 0.05, 1.0, 0.55)

        edge_ratio = _clamp_float(style.get("edge_ratio", 0.10), 0.03, 0.25, 0.10)
        self._edge_width = max(8, int(min_edge_ref * edge_ratio))
        self._edge_width = min(self._edge_width, max(8, min_edge_ref // 3))

        self._base_color = _resolve_color(style.get("color", "#ff4b35"), QColor("#ff4b35"))
        self._spark_color = _resolve_color(style.get("spark_color", "#ffe1c5"), QColor("#ffe1c5"))

        requested_particle_count = _clamp_int(style.get("particle_count", 150), 18, 260, 150)
        self._quality_scale_last = self._compute_quality_scale()
        self._particle_count = _clamp_int(
            int(requested_particle_count * self._quality_scale_last),
            12,
            260,
            requested_particle_count,
        )
        self._particle_speed_min = _clamp_float(style.get("particle_speed_min", 550.0), 80.0, 2600.0, 550.0)
        self._particle_speed_max = _clamp_float(style.get("particle_speed_max", 1020.0), 120.0, 2800.0, 1020.0)
        if self._particle_speed_max < self._particle_speed_min:
            self._particle_speed_min, self._particle_speed_max = self._particle_speed_max, self._particle_speed_min

        self._particle_size_min = _clamp_float(style.get("particle_size_min", 1.3), 0.5, 8.0, 1.3)
        self._particle_size_max = _clamp_float(style.get("particle_size_max", 3.3), 0.7, 10.0, 3.3)
        if self._particle_size_max < self._particle_size_min:
            self._particle_size_min, self._particle_size_max = self._particle_size_max, self._particle_size_min

        life_min_ms = _clamp_int(style.get("particle_life_min_ms", 150), 50, 1200, 150)
        life_max_ms = _clamp_int(style.get("particle_life_max_ms", 320), 70, 1800, 320)
        if life_max_ms < life_min_ms:
            life_min_ms, life_max_ms = life_max_ms, life_min_ms
        self._particle_life_min_s = life_min_ms / 1000.0
        self._particle_life_max_s = life_max_ms / 1000.0
        self._particle_drag = _clamp_float(style.get("particle_drag", 0.902), 0.50, 0.995, 0.902)
        self._spark_alpha = _clamp_float(style.get("spark_alpha", 0.86), 0.10, 1.0, 0.86)
        self._trail_alpha = _clamp_float(style.get("trail_alpha", 0.22), 0.0, 1.0, 0.22)

        self._spawn_mode = str(style.get("spawn_mode", "edges") or "edges").strip().lower()
        self._pulse_freq_hz = _clamp_float(style.get("pulse_freq_hz", 5.1), 0.0, 15.0, 5.1)
        self._pulse_amount = _clamp_float(style.get("pulse_amount", 0.14), 0.0, 0.60, 0.14)
        # 屏蔽中心扩散圆环，避免影响瞄准注意力
        self._ring_enabled = False
        self._ring_alpha = _clamp_float(style.get("ring_alpha", 0.22), 0.0, 1.0, 0.22)
        self._ring_thickness = _clamp_float(style.get("ring_thickness", 2.6), 1.0, 14.0, 2.6)
        self._ring_duration_ms = _clamp_int(style.get("ring_duration_ms", int(self._duration_ms * 0.85)), 80, 1800, 320)
        self._ring_start_ratio = _clamp_float(style.get("ring_start_ratio", 0.08), 0.0, 1.2, 0.08)
        self._ring_end_ratio = _clamp_float(style.get("ring_end_ratio", 0.84), 0.05, 1.5, 0.84)
        self._ring_color = _resolve_color(style.get("ring_color", self._spark_color), self._spark_color)

        w2 = _clamp_float(style.get("wave2_ratio", 0.28), 0.0, 0.8, 0.28)
        w3 = _clamp_float(style.get("wave3_ratio", 0.16), 0.0, 0.8, 0.16)
        if w2 + w3 > 0.92:
            scale = 0.92 / (w2 + w3)
            w2 *= scale
            w3 *= scale
        first_ratio = max(0.08, 1.0 - w2 - w3)

        first_count = max(1, int(self._particle_count * first_ratio))
        second_count = max(0, int(self._particle_count * w2))
        third_count = max(0, self._particle_count - first_count - second_count)

        now = time.perf_counter()
        blend_retrigger = bool(style.get("blend_retrigger", True))
        retriggering = self._active and blend_retrigger

        if retriggering:
            self._elapsed_ms = max(0.0, self._elapsed_ms * 0.35)
            self._start_time = now - (self._elapsed_ms / 1000.0)
        else:
            self._particles = []
            self._pending_waves = []
            self._start_time = now
            self._elapsed_ms = 0.0

        base_delay = self._elapsed_ms if retriggering else 0.0

        if second_count > 0:
            self._pending_waves.append({
                "delay_ms": base_delay + _clamp_int(style.get("wave2_delay_ms", 56), 8, 1000, 56),
                "count": second_count,
            })
        if third_count > 0:
            self._pending_waves.append({
                "delay_ms": base_delay + _clamp_int(style.get("wave3_delay_ms", 118), 8, 1400, 118),
                "count": third_count,
            })
        self._pending_waves.sort(key=lambda x: x["delay_ms"])

        self._spawn_particles(first_count)

        self._active = True
        self._last_tick = now

        self.show()
        self.raise_()
        self._apply_windows_click_through()
        self._update_frame_interval()
        if not self._frame_timer.isActive():
            self._frame_timer.start()
        self.update()

    def cleanup(self):
        self._active = False
        self._frame_timer.stop()
        self._pending_waves = []
        self._particles = []
        self.hide()
        self.update()

    def _refresh_geometry(self):
        screens = QApplication.screens()
        if not screens:
            return

        geometry = QRect()
        for screen in screens:
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)

    def _screen_quality_scale(self):
        try:
            screen = QApplication.primaryScreen()
            if not screen:
                return 1.0
            geo = screen.geometry()
            pixels = int(geo.width()) * int(geo.height())
        except Exception:
            return 1.0

        if pixels >= 7600000:
            return 0.72
        if pixels >= 5000000:
            return 0.82
        if pixels >= 3600000:
            return 0.90
        return 1.0

    def _compute_quality_scale(self):
        screen_scale = self._screen_quality_scale()
        runtime_scale = _clamp_float(self._runtime_quality_scale, 0.55, 1.0, 1.0)
        return _clamp_float(screen_scale * runtime_scale, 0.55, 1.0, 1.0)

    def _update_quality_by_paint_cost(self):
        if self._paint_cost_ema_ms > 10.5 and self._runtime_quality_scale > 0.60:
            self._runtime_quality_scale = max(0.60, self._runtime_quality_scale - 0.05)
        elif self._paint_cost_ema_ms < 4.8 and self._runtime_quality_scale < 1.0:
            self._runtime_quality_scale = min(1.0, self._runtime_quality_scale + 0.02)

    def _update_frame_interval(self):
        interval = 16
        particle_n = len(self._particles)
        if self._paint_cost_ema_ms > 10.0 or particle_n > 220:
            interval = 24
        elif self._paint_cost_ema_ms > 7.2 or particle_n > 170:
            interval = 20

        if self._frame_timer.interval() != interval:
            self._frame_timer.setInterval(interval)

    def _spawn_due_waves(self, elapsed_ms):
        if not self._pending_waves:
            return
        remain = []
        for wave in self._pending_waves:
            if elapsed_ms + 0.5 >= wave["delay_ms"]:
                self._spawn_particles(wave["count"])
            else:
                remain.append(wave)
        self._pending_waves = remain

    def _tick(self):
        if not self._active and not self._particles:
            self._frame_timer.stop()
            return

        now = time.perf_counter()
        dt = max(0.001, min(0.050, now - self._last_tick))
        self._last_tick = now
        self._elapsed_ms = max(0.0, (now - self._start_time) * 1000.0)

        self._spawn_due_waves(self._elapsed_ms)
        self._update_particles(dt)
        self._update_frame_interval()

        if self._elapsed_ms >= self._duration_ms and not self._particles and not self._pending_waves:
            self.cleanup()
            return

        self.update()

    def _spawn_point(self):
        width = float(self.width())
        height = float(self.height())
        if width <= 0 or height <= 0:
            return None

        edge_depth = max(4.0, self._edge_width * 0.85)
        mode = self._spawn_mode

        if mode == "corners":
            corner = random.randrange(4)
            ox = random.uniform(0.0, edge_depth * 1.1)
            oy = random.uniform(0.0, edge_depth * 1.1)
            if corner == 0:
                return ox, oy
            if corner == 1:
                return width - ox, oy
            if corner == 2:
                return ox, height - oy
            return width - ox, height - oy

        if mode == "left_right":
            y = random.uniform(0.0, height)
            if random.randrange(2) == 0:
                return random.uniform(0.0, edge_depth), y
            return random.uniform(width - edge_depth, width), y

        if mode == "top_bottom":
            x = random.uniform(0.0, width)
            if random.randrange(2) == 0:
                return x, random.uniform(0.0, edge_depth)
            return x, random.uniform(height - edge_depth, height)

        if mode == "center":
            cx = width * 0.5
            cy = height * 0.5
            r = min(width, height) * random.uniform(0.02, 0.07)
            a = random.uniform(0.0, math.tau)
            return cx + math.cos(a) * r, cy + math.sin(a) * r

        side = random.randrange(4)
        if side == 0:
            return random.uniform(0.0, width), random.uniform(0.0, edge_depth)
        if side == 1:
            return random.uniform(0.0, width), random.uniform(height - edge_depth, height)
        if side == 2:
            return random.uniform(0.0, edge_depth), random.uniform(0.0, height)
        return random.uniform(width - edge_depth, width), random.uniform(0.0, height)

    def _spawn_particles(self, count):
        width = float(self.width())
        height = float(self.height())
        if width <= 0 or height <= 0:
            return

        cx = width * 0.5
        cy = height * 0.5
        for _ in range(int(count)):
            point = self._spawn_point()
            if not point:
                continue
            x, y = point

            dx = cx - x
            dy = cy - y
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                a = random.uniform(0.0, math.tau)
                nx, ny = math.cos(a), math.sin(a)
            else:
                nx, ny = dx / dist, dy / dist

            if self._spawn_mode == "center":
                nx, ny = -nx, -ny

            jitter = random.uniform(-0.65, 0.65)
            cos_a = math.cos(jitter)
            sin_a = math.sin(jitter)
            jx = nx * cos_a - ny * sin_a
            jy = nx * sin_a + ny * cos_a

            speed = random.uniform(self._particle_speed_min, self._particle_speed_max)
            life = random.uniform(self._particle_life_min_s, self._particle_life_max_s)
            size = random.uniform(self._particle_size_min, self._particle_size_max)

            mix = random.uniform(0.0, 0.35)
            color = _mix_color(self._spark_color, self._base_color, mix)
            self._particles.append({
                "x": x,
                "y": y,
                "px": x,
                "py": y,
                "vx": jx * speed,
                "vy": jy * speed,
                "age": 0.0,
                "life": life,
                "size": size,
                "alpha": random.uniform(0.52, 1.0),
                "color": color,
            })

    def _update_particles(self, dt):
        if not self._particles:
            return

        damping = self._particle_drag ** (dt * 60.0)
        width = float(self.width())
        height = float(self.height())
        margin = 120.0
        alive = []

        for p in self._particles:
            p["age"] += dt
            if p["age"] >= p["life"]:
                continue

            p["px"] = p["x"]
            p["py"] = p["y"]
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vx"] *= damping
            p["vy"] *= damping

            if -margin <= p["x"] <= width + margin and -margin <= p["y"] <= height + margin:
                alive.append(p)

        self._particles = alive

    def _edge_alpha(self):
        if self._duration_ms <= 0:
            return 0.0

        t = self._elapsed_ms / float(self._duration_ms)
        if t >= 1.0:
            return 0.0

        if t < 0.14:
            envelope = t / 0.14
        else:
            envelope = (1.0 - t) ** 1.35

        pulse = 1.0
        if self._pulse_freq_hz > 0.0 and self._pulse_amount > 0.0:
            pulse += math.sin(t * math.tau * self._pulse_freq_hz) * self._pulse_amount * (1.0 - t)

        return self._peak_edge_alpha * max(0.0, envelope * pulse)

    def _particle_global_alpha(self):
        if self._duration_ms <= 0:
            return 1.0

        t = self._elapsed_ms / float(self._duration_ms)
        if t < 0.10:
            return 0.42 + 0.58 * (t / 0.10)
        if t <= 1.0:
            return max(0.15, (1.0 - t) ** 0.48)
        return 0.0

    def _apply_windows_click_through(self):
        if self._windows_style_applied:
            return
        if not sys.platform.startswith("win"):
            return

        try:
            hwnd = int(self.winId())
            if not hwnd:
                return

            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            ws_ex_toolwindow = 0x00000080
            ws_ex_noactivate = 0x08000000

            style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            style |= ws_ex_layered | ws_ex_transparent | ws_ex_toolwindow | ws_ex_noactivate
            user32.SetWindowLongW(hwnd, gwl_exstyle, style)
            self._windows_style_applied = True
        except Exception as e:
            self.logger.debug(f"Apply window click-through style failed: {e}")

    def paintEvent(self, event):
        if not self._active and not self._particles:
            return

        paint_start = time.perf_counter()
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(Qt.NoPen)

        edge_alpha = self._edge_alpha()
        if edge_alpha > 0.001:
            self._paint_edges(painter, edge_alpha)

        if self._ring_enabled:
            self._paint_ring(painter)

        if self._particles:
            self._paint_particles(painter, self._particle_global_alpha())

        painter.end()
        paint_cost_ms = (time.perf_counter() - paint_start) * 1000.0
        if self._paint_cost_ema_ms <= 0.0:
            self._paint_cost_ema_ms = paint_cost_ms
        else:
            self._paint_cost_ema_ms = self._paint_cost_ema_ms * 0.82 + paint_cost_ms * 0.18
        self._update_quality_by_paint_cost()

    def _paint_edges(self, painter, alpha):
        edge = max(1, int(self._edge_width))
        width = self.width()
        height = self.height()
        if edge <= 0 or width <= 0 or height <= 0:
            return

        edge = min(edge, width // 2, height // 2)
        if edge <= 0:
            return

        color_main = QColor(self._base_color)
        color_main.setAlpha(int(255 * max(0.0, min(1.0, alpha))))
        color_mid = QColor(self._base_color)
        color_mid.setAlpha(int(255 * max(0.0, min(1.0, alpha * 0.36))))
        color_zero = QColor(self._base_color)
        color_zero.setAlpha(0)

        top_grad = QLinearGradient(0.0, 0.0, 0.0, float(edge))
        top_grad.setColorAt(0.0, color_main)
        top_grad.setColorAt(0.40, color_mid)
        top_grad.setColorAt(1.0, color_zero)
        painter.fillRect(0, 0, width, edge, top_grad)

        bottom_grad = QLinearGradient(0.0, float(height), 0.0, float(height - edge))
        bottom_grad.setColorAt(0.0, color_main)
        bottom_grad.setColorAt(0.40, color_mid)
        bottom_grad.setColorAt(1.0, color_zero)
        painter.fillRect(0, height - edge, width, edge, bottom_grad)

        left_grad = QLinearGradient(0.0, 0.0, float(edge), 0.0)
        left_grad.setColorAt(0.0, color_main)
        left_grad.setColorAt(0.40, color_mid)
        left_grad.setColorAt(1.0, color_zero)
        painter.fillRect(0, 0, edge, height, left_grad)

        right_grad = QLinearGradient(float(width), 0.0, float(width - edge), 0.0)
        right_grad.setColorAt(0.0, color_main)
        right_grad.setColorAt(0.40, color_mid)
        right_grad.setColorAt(1.0, color_zero)
        painter.fillRect(width - edge, 0, edge, height, right_grad)

    def _paint_ring(self, painter):
        if self._ring_duration_ms <= 0:
            return

        t = max(0.0, min(1.0, self._elapsed_ms / float(self._ring_duration_ms)))
        if t >= 1.0 and self._elapsed_ms > self._ring_duration_ms:
            return

        alpha = self._ring_alpha * ((1.0 - t) ** 1.15)
        if alpha <= 0.001:
            return

        width = float(self.width())
        height = float(self.height())
        if width <= 0.0 or height <= 0.0:
            return

        diag = math.hypot(width, height)
        start_r = diag * self._ring_start_ratio
        end_r = diag * self._ring_end_ratio
        radius = start_r + (end_r - start_r) * (t ** 0.85)

        color = QColor(self._ring_color)
        color.setAlpha(int(255 * max(0.0, min(1.0, alpha))))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, self._ring_thickness + (1.0 - t) * 1.4, Qt.SolidLine, Qt.RoundCap))
        center_x = width * 0.5
        center_y = height * 0.5
        painter.drawEllipse(QPointF(center_x, center_y), radius, radius)
        painter.restore()

    def _paint_particles(self, painter, global_alpha):
        if global_alpha <= 0.001:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        global_alpha = max(0.0, min(1.0, global_alpha * self._spark_alpha))

        for p in self._particles:
            life_ratio = p["age"] / max(1e-6, p["life"])
            life_ratio = max(0.0, min(1.0, life_ratio))
            local_alpha = (1.0 - life_ratio) ** 1.6
            alpha = p["alpha"] * local_alpha * global_alpha
            if alpha <= 0.01:
                continue

            color = QColor(p["color"])
            color.setAlpha(int(255 * max(0.0, min(1.0, alpha))))

            if self._trail_alpha > 0.001:
                trail = alpha * self._trail_alpha * (1.0 - life_ratio)
                if trail > 0.01:
                    trail_color = QColor(color)
                    trail_color.setAlpha(int(255 * max(0.0, min(1.0, trail))))
                    painter.setPen(QPen(trail_color, max(1.0, p["size"] * 0.42), Qt.SolidLine, Qt.RoundCap))
                    x2 = p["x"] - (p["x"] - p["px"]) * 0.85
                    y2 = p["y"] - (p["y"] - p["py"]) * 0.85
                    painter.drawLine(QLineF(p["x"], p["y"], x2, y2))
                    painter.setPen(Qt.NoPen)

            painter.setBrush(color)
            size = p["size"] * (0.62 + (1.0 - life_ratio) * 0.62)
            painter.drawEllipse(QRectF(p["x"] - size * 0.5, p["y"] - size * 0.5, size, size))

        painter.restore()


class ScreenEffectOverlayManager(QObject):
    _kill_signal = Signal(bool)
    _preview_signal = Signal(bool)

    def __init__(self, config_obj, parent=None):
        super().__init__(parent)
        self.logger = get_logger("ScreenEffectOverlay")
        self.config = config_obj
        self.overlay = EdgeParticleOverlay()

        self._enabled = False
        self._preset = DEFAULT_SCREEN_EFFECT_PRESET
        self._play_mode = DEFAULT_SCREEN_EFFECT_PLAY_MODE
        self._combo_window_s = 3.4
        self._kill_timestamps = []
        self._chaos_preset_pool = [
            "impact_sparks",
            "frenzy_kill",
            "blue_storm",
            "neon_pulse",
            "toxic_surge",
            "amber_overdrive",
            "frost_shock",
        ]
        self._last_chaos_preset = None

        self._kill_signal.connect(self._handle_kill)
        self._preview_signal.connect(self._handle_preview)
        self.update_settings_from_config()

    def update_settings_from_config(self):
        self._enabled = bool(
            getattr(self.config, "screen_effects_enabled", False)
            and getattr(self.config, "screen_edge_flash_enabled", True)
        )
        self._preset = self._resolve_active_preset()
        self._play_mode = _normalize_play_mode(getattr(self.config, "screen_effects_play_mode", DEFAULT_SCREEN_EFFECT_PLAY_MODE))
        if not self._enabled:
            self.overlay.cleanup()

    def on_kill_event(self, is_headshot):
        self._kill_signal.emit(bool(is_headshot))

    def preview(self, is_headshot=False):
        self._preview_signal.emit(bool(is_headshot))

    def cleanup(self):
        self.overlay.cleanup()

    @Slot(bool)
    def _handle_kill(self, is_headshot):
        now = time.perf_counter()
        combo = self._record_kill_and_get_combo(now)
        self._play(is_headshot, force=False, combo_count=combo)

    @Slot(bool)
    def _handle_preview(self, is_headshot):
        self._play(is_headshot, force=True, combo_count=3 if is_headshot else 1)

    def _play(self, is_headshot, force=False, combo_count=1):
        if not force and not self._enabled:
            return
        style = self._build_style(is_headshot, combo_count=max(1, int(combo_count)))
        self.overlay.play(style)

    def _record_kill_and_get_combo(self, now):
        self._kill_timestamps.append(now)
        cutoff = now - self._combo_window_s
        self._kill_timestamps = [t for t in self._kill_timestamps if t >= cutoff]
        return len(self._kill_timestamps)

    def _pick_chaos_preset(self, combo_count, is_headshot):
        pool = list(self._chaos_preset_pool)
        if not pool:
            return self._preset

        if self._last_chaos_preset in pool and len(pool) > 1:
            # 随机模式避免连续重复同一风格
            pool = [p for p in pool if p != self._last_chaos_preset]

        base_weights = {
            "impact_sparks": 1.0,
            "frenzy_kill": 1.12,
            "blue_storm": 1.0,
            "neon_pulse": 1.04,
            "toxic_surge": 0.98,
            "amber_overdrive": 1.08,
            "frost_shock": 0.96,
        }

        combo_boost = max(0, min(combo_count - 1, 6))
        weights = []
        for key in pool:
            w = base_weights.get(key, 1.0)
            if combo_boost >= 2 and key in ("frenzy_kill", "amber_overdrive", "neon_pulse"):
                w *= 1.0 + combo_boost * 0.09
            if is_headshot and key in ("frenzy_kill", "amber_overdrive", "blue_storm"):
                w *= 1.18
            weights.append(max(0.01, w))

        picked = random.choices(pool, weights=weights, k=1)[0]
        self._last_chaos_preset = picked
        return picked

    def _resolve_active_preset(self):
        raw_preset = getattr(self.config, "screen_effects_preset", None)
        preset = _normalize_preset(raw_preset, fallback=None)
        if preset:
            return preset

        preset = self._infer_preset_from_legacy()
        try:
            self.config.screen_effects_preset = preset
        except Exception:
            pass
        return preset

    def _infer_preset_from_legacy(self):
        intensity = _clamp_float(getattr(self.config, "screen_edge_flash_intensity", 0.35), 0.05, 1.0, 0.35)
        thickness = _clamp_int(getattr(self.config, "screen_edge_flash_thickness", 12), 2, 80, 12)
        duration = _clamp_int(getattr(self.config, "screen_edge_flash_duration_ms", 260), 80, 2500, 260)
        headshot_boost = _clamp_float(getattr(self.config, "screen_edge_flash_headshot_boost", 1.25), 1.0, 3.0, 1.25)

        score = (
            intensity * 0.55
            + (thickness / 80.0) * 0.20
            + min(1.0, duration / 420.0) * 0.15
            + min(1.0, (headshot_boost - 1.0) / 1.2) * 0.10
        )
        if score <= 0.30:
            return "lite_competitive"
        if score >= 0.58:
            return "frenzy_kill"
        return DEFAULT_SCREEN_EFFECT_PRESET

    def _build_style(self, is_headshot, combo_count):
        mode = self._play_mode
        preset_key = self._preset
        combo_boost = max(0, min(combo_count - 1, 5))

        if mode == "chaos" and self._chaos_preset_pool:
            should_randomize = combo_count >= 2 or random.random() < 0.45
            if should_randomize:
                preset_key = self._pick_chaos_preset(combo_count, is_headshot)

        style = dict(SCREEN_EFFECT_PRESETS.get(preset_key, SCREEN_EFFECT_PRESETS[DEFAULT_SCREEN_EFFECT_PRESET]))
        style["blend_retrigger"] = mode != "steady"

        if mode == "steady":
            duration_jitter = random.uniform(0.99, 1.03)
            particle_jitter = random.uniform(0.97, 1.04)
        elif mode == "chaos":
            duration_jitter = random.uniform(0.94, 1.12)
            particle_jitter = random.uniform(0.90, 1.12)
        else:
            duration_jitter = random.uniform(0.96, 1.07)
            particle_jitter = random.uniform(0.92, 1.08)

        style["duration_ms"] = _clamp_int(int(style.get("duration_ms", 420) * duration_jitter), 140, 1400, 420)
        style["particle_count"] = _clamp_int(int(style.get("particle_count", 150) * particle_jitter), 18, 260, 150)

        if mode in ("streak", "chaos") and combo_boost > 0:
            style["duration_ms"] = _clamp_int(
                int(style.get("duration_ms", 420) * (1.0 + combo_boost * 0.06)),
                140,
                1600,
                420,
            )
            style["edge_alpha"] = _clamp_float(
                style.get("edge_alpha", 0.55) * (1.0 + combo_boost * 0.05),
                0.05,
                1.0,
                0.55,
            )
            style["particle_count"] = _clamp_int(
                int(style.get("particle_count", 150) * (1.0 + combo_boost * 0.12)),
                18,
                260,
                170,
            )
            style["spark_alpha"] = _clamp_float(
                style.get("spark_alpha", 0.86) * (1.0 + combo_boost * 0.04),
                0.10,
                1.0,
                0.90,
            )
            style["trail_alpha"] = _clamp_float(
                style.get("trail_alpha", 0.22) * (1.0 + combo_boost * 0.09),
                0.0,
                1.0,
                0.28,
            )
            style["wave2_ratio"] = _clamp_float(style.get("wave2_ratio", 0.28) + combo_boost * 0.03, 0.0, 0.52, 0.35)
            style["wave3_ratio"] = _clamp_float(style.get("wave3_ratio", 0.16) + combo_boost * 0.04, 0.0, 0.38, 0.24)
            style["pulse_amount"] = _clamp_float(style.get("pulse_amount", 0.14) * (1.0 + combo_boost * 0.10), 0.0, 0.60, 0.22)
            if combo_boost >= 3:
                style["wave3_delay_ms"] = _clamp_int(int(style.get("wave3_delay_ms", 180) * 0.82), 40, 1200, 110)

        if not is_headshot:
            style["ring_enabled"] = combo_boost >= 2 or mode == "chaos"
            style["ring_alpha"] = _clamp_float(0.12 + combo_boost * 0.05 + (0.05 if mode == "chaos" else 0.0), 0.0, 0.9, 0.24)
            style["ring_thickness"] = _clamp_float(2.2 + combo_boost * 0.55, 1.0, 14.0, 2.8)
            style["ring_duration_ms"] = _clamp_int(int(style.get("duration_ms", 420) * 0.85), 100, 1600, 360)
            style["ring_color"] = style.get("spark_color", style.get("color", "#ffffff"))
            return style

        d = _clamp_float(style.get("headshot_duration_scale", 1.13), 1.0, 1.8, 1.13)
        e = _clamp_float(style.get("headshot_edge_alpha_scale", 1.21), 1.0, 2.0, 1.21)
        p = _clamp_float(style.get("headshot_particle_scale", 1.30), 1.0, 2.0, 1.30)
        s = _clamp_float(style.get("headshot_spark_alpha_scale", 1.18), 1.0, 2.0, 1.18)

        style["duration_ms"] = _clamp_int(int(style.get("duration_ms", 420) * d), 160, 1700, 460)
        style["edge_alpha"] = _clamp_float(style.get("edge_alpha", 0.55) * e, 0.05, 1.0, 0.66)
        style["particle_count"] = _clamp_int(int(style.get("particle_count", 150) * p), 18, 260, 190)
        style["spark_alpha"] = _clamp_float(style.get("spark_alpha", 0.86) * s, 0.10, 1.0, 0.96)
        style["trail_alpha"] = _clamp_float(style.get("trail_alpha", 0.22) * 1.12, 0.0, 1.0, 0.30)

        base_color = _resolve_color(style.get("color", "#ff4b35"), QColor("#ff4b35"))
        spark_color = _resolve_color(style.get("spark_color", "#ffe1c5"), QColor("#ffe1c5"))
        style["color"] = _mix_color(base_color, QColor("#ffd47d"), 0.24).name()
        style["spark_color"] = _mix_color(spark_color, QColor("#fff9e6"), 0.32).name()

        style["ring_enabled"] = True
        style["ring_alpha"] = _clamp_float(0.22 + combo_boost * 0.05 + (0.04 if mode == "chaos" else 0.0), 0.0, 0.95, 0.32)
        style["ring_thickness"] = _clamp_float(2.8 + combo_boost * 0.65, 1.0, 14.0, 3.6)
        style["ring_duration_ms"] = _clamp_int(int(style.get("duration_ms", 460) * 0.90), 120, 1800, 440)
        style["ring_start_ratio"] = 0.06
        style["ring_end_ratio"] = 0.92 if mode == "chaos" else 0.84
        style["ring_color"] = style.get("spark_color", style.get("color", "#ffffff"))
        return style
