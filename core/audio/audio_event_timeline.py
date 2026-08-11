# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory audio event timeline for diagnostics and replay."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List


@dataclass
class AudioEvent:
    timestamp: float
    action: str
    key: str = ""
    channel_type: str = ""
    event_type: str = ""
    reason: str = ""
    success: bool = True
    meta: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class AudioEventTimeline:
    def __init__(self, max_events: int = 2000):
        self._max_events = max(200, int(max_events))
        self._events: deque[AudioEvent] = deque(maxlen=self._max_events)
        self._lock = threading.Lock()

    def record(self, event: AudioEvent) -> None:
        with self._lock:
            self._events.append(event)

    def record_dict(self, **kwargs) -> None:
        self.record(AudioEvent(timestamp=time.time(), **kwargs))

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def query(self, limit: int, filters: dict) -> List[AudioEvent]:
        with self._lock:
            events = list(self._events)
        if filters:
            events = [event for event in events if _match_filters(event, filters)]
        if limit > 0:
            events = events[-limit:]
        return events

    def export_json(self, path: str) -> str:
        payload = [event.to_dict() for event in self.query(limit=0, filters={})]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path

    def replay(self, events: Iterable[AudioEvent], audio_manager) -> Dict[str, int]:
        requested = 0
        played = 0
        failed = 0
        for event in events:
            if str(event.action).lower() not in {"play", "preempt"}:
                continue
            requested += 1
            try:
                ok = bool(
                    audio_manager.play_sound(
                        event.key,
                        channel_type=event.channel_type or "kill_sound",
                        event_type=event.event_type or None,
                    )
                )
                if ok:
                    played += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {"requested": requested, "played": played, "failed": failed}


def _match_filters(event: AudioEvent, filters: Dict[str, object]) -> bool:
    action = str(filters.get("action", "") or "").strip().lower()
    channel = str(filters.get("channel_type", "") or "").strip().lower()
    event_type = str(filters.get("event_type", "") or "").strip().lower()
    key_contains = str(filters.get("key_contains", "") or "").strip().lower()

    if action and event.action.lower() != action:
        return False
    if channel and event.channel_type.lower() != channel:
        return False
    if event_type and event.event_type.lower() != event_type:
        return False
    if key_contains and key_contains not in event.key.lower():
        return False
    return True


_timeline_lock = threading.Lock()
_timeline_instance: AudioEventTimeline | None = None


def get_audio_event_timeline() -> AudioEventTimeline:
    global _timeline_instance
    if _timeline_instance is None:
        with _timeline_lock:
            if _timeline_instance is None:
                _timeline_instance = AudioEventTimeline()
    return _timeline_instance

