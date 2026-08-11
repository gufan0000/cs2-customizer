"""Shared status badge helpers for audio setting pages."""

from __future__ import annotations

import os
from typing import Iterable, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from core.audio.audio_resource_health import collect_audio_resource_health


DISABLED_STYLE_VALUES = {"", "0", "none", "off", "disabled", "不启用", "未启用"}


def _restyle_widget(widget: QWidget):
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class AudioStatusBadgeBar(QFrame):
    """Reusable chip container for concise status badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("audioStatusBar")
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._chip_pool: list[QLabel] = []
        self._detail_tooltip = ""

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._layout.addStretch(1)

    def _ensure_chip_pool(self, target_count: int):
        while len(self._chip_pool) < target_count:
            chip = QLabel(self)
            chip.setObjectName("audioStatusChip")
            chip.setAlignment(Qt.AlignCenter)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            chip.setTextInteractionFlags(Qt.NoTextInteraction)
            chip.setMinimumHeight(28)
            chip.hide()
            self._chip_pool.append(chip)
            self._layout.insertWidget(len(self._chip_pool) - 1, chip, 0, Qt.AlignLeft | Qt.AlignVCenter)

    def set_detail_tooltip(self, text: str | None):
        self._detail_tooltip = str(text or "").strip()
        self._apply_detail_tooltip()

    def _apply_detail_tooltip(self):
        for idx, chip in enumerate(self._chip_pool):
            if chip.isHidden():
                chip.setToolTip("")
                continue
            chip.setToolTip(self._detail_tooltip if idx == 2 and self._detail_tooltip else "")
        self.setToolTip(self._detail_tooltip if self._detail_tooltip else "")

    def set_badges(self, badges: Sequence[tuple[str, str]]):
        badge_list = list(badges or [])
        self._ensure_chip_pool(len(badge_list))

        for idx, chip in enumerate(self._chip_pool):
            if idx >= len(badge_list):
                chip.hide()
                chip.setText("")
                chip.setProperty("level", "")
                chip.setToolTip("")
                _restyle_widget(chip)
                continue

            level, text = badge_list[idx]
            chip.setText(str(text))
            chip.setProperty("level", str(level or "info"))
            chip.show()
            _restyle_widget(chip)

        self._apply_detail_tooltip()


def create_badge_bar() -> AudioStatusBadgeBar:
    return AudioStatusBadgeBar()


def create_badge_label() -> AudioStatusBadgeBar:
    """Compatibility alias for legacy call sites."""
    return create_badge_bar()


def render_badges(
    bar: QWidget,
    badges: Sequence[Tuple[str, str]],
    detail_tooltip: str | None = None,
) -> None:
    if isinstance(bar, AudioStatusBadgeBar):
        bar.set_detail_tooltip(detail_tooltip)
        bar.set_badges(badges)
        return

    # Fallback path for any unexpected legacy usage.
    fallback = [str(text) for _level, text in badges]
    if hasattr(bar, "setText"):
        bar.setText("  |  ".join(fallback))


def is_style_enabled(style_value) -> bool:
    return str(style_value or "").strip().lower() not in DISABLED_STYLE_VALUES


def count_enabled_styles(values: Iterable) -> int:
    return sum(1 for value in values if is_style_enabled(value))


def build_health_detail_tooltip(health: dict, max_items: int = 2) -> str:
    """Build concise tooltip text for resource health anomalies."""
    if not health or health.get("ok", True):
        return ""

    lines: list[str] = []
    for path in (health.get("missing", []) or [])[:max_items]:
        lines.append(f"缺失目录: {path}")
    for issue in (health.get("invalid", []) or [])[:max_items]:
        key = str(issue.get("key", "")).strip()
        reason = str(issue.get("reason", "")).strip()
        expected = str(issue.get("expected_path", "")).strip()
        lines.append(f"失效引用: {key} ({reason}) {expected}")

    if not lines:
        for path in (health.get("empty", []) or [])[:max_items]:
            lines.append(f"空目录: {path}")

    return "\n".join(lines[: max(1, max_items * 2)])


def _extract_root(path: str, audio_root: str) -> str:
    if not path:
        return ""
    try:
        rel = os.path.relpath(path, audio_root)
    except Exception:
        return ""
    if rel.startswith(".."):
        return ""
    parts = rel.split(os.sep)
    if not parts:
        return ""
    return parts[0].strip().lower()


def collect_category_health(category_roots: Iterable[str]) -> dict:
    report = collect_audio_resource_health()
    roots = {str(root).strip().lower() for root in category_roots if str(root).strip()}
    audio_root = str(report.get("audio_root", ""))

    missing = []
    for path in report.get("missing_directories", []) or []:
        if _extract_root(str(path), audio_root) in roots:
            missing.append(str(path))

    empty = []
    for path in report.get("empty_style_dirs", []) or []:
        if _extract_root(str(path), audio_root) in roots:
            empty.append(str(path))

    invalid = []
    for issue in report.get("invalid_config_refs", []) or []:
        expected_path = str(issue.get("expected_path", ""))
        if _extract_root(expected_path, audio_root) in roots:
            invalid.append(issue)

    return {
        "ok": not missing and not invalid,
        "missing": missing,
        "empty": empty,
        "invalid": invalid,
        "issue_count": len(missing) + len(invalid),
    }
