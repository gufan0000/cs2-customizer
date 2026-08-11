"""Audio playback policy: priority and preemption decisions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


PRIORITY_PROFILE_KILL_PREEMPT_V1 = {
    "kill": 100,
    "headshot": 110,
    "kill_voice": 95,
    "round_mvp": 90,
    "round_win": 88,
    "round_lose": 88,
    "round_start": 55,
    "round_action": 60,
    "c4": 80,
    "health_warning": 70,
    "grenade": 45,
    "switch_weapon": 25,
    "reload": 22,
    "gun_fire": 35,
    "death": 40,
    "default": 50,
}

# 抢占组：同组事件互相 preempt、永不因优先级差被 drop。
# 背景：击杀(100)与爆头(110)共用通道 ch1，爆头声未播完时来普通击杀，
# 按纯优先级会 lower_priority drop —— 这一杀就永久静音（"爆头+补枪"双杀常见）。
# 玩家预期是"每一杀都要响"，新杀切旧声优于静音，故击杀家族归为同组。
PREEMPT_GROUPS = {
    "kill": "kill_family",
    "headshot": "kill_family",
}


def resolve_preempt_group(event_type: str | None) -> str | None:
    """返回事件所属的抢占组名；不在任何组则返回 None。"""
    et = str(event_type or "default").strip().lower()
    return PREEMPT_GROUPS.get(et)


@dataclass
class PlaybackRequest:
    key: str
    channel_type: str
    event_type: str = "default"
    priority: int = PRIORITY_PROFILE_KILL_PREEMPT_V1["default"]
    allow_preempt: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass
class PlaybackDecision:
    action: str  # play|drop|preempt
    reason: str
    request: PlaybackRequest
    active: Optional[PlaybackRequest] = None


def resolve_priority(
    event_type: str | None,
    *,
    explicit_priority: int | None = None,
    profile: str = "kill_preempt_v1",
) -> int:
    if explicit_priority is not None:
        return int(explicit_priority)
    et = str(event_type or "default").strip().lower()
    # Reserved for future profiles.
    mapping: Dict[str, int] = PRIORITY_PROFILE_KILL_PREEMPT_V1
    return int(mapping.get(et, mapping["default"]))


def decide_channel_action(
    new_request: PlaybackRequest,
    active_request: PlaybackRequest | None,
    *,
    channel_busy: bool,
) -> PlaybackDecision:
    """
    Decision logic (kill_preempt_v1):
    - idle channel: play
    - busy channel + no active metadata: follow new request preempt flag
    - busy channel + higher priority new request + allow_preempt: preempt
    - otherwise drop
    """
    if not channel_busy:
        return PlaybackDecision(
            action="play",
            reason="channel_idle",
            request=new_request,
            active=active_request,
        )

    if active_request is None:
        if new_request.allow_preempt:
            return PlaybackDecision(
                action="preempt",
                reason="busy_no_active_metadata_preempt",
                request=new_request,
                active=None,
            )
        return PlaybackDecision(
            action="drop",
            reason="busy_no_active_metadata_drop",
            request=new_request,
            active=None,
        )

    if not new_request.allow_preempt:
        return PlaybackDecision(
            action="drop",
            reason="preempt_disabled",
            request=new_request,
            active=active_request,
        )

    # 同抢占组：无条件切入，不比优先级（如爆头声占道时的普通击杀，见 PREEMPT_GROUPS 注释）
    new_group = resolve_preempt_group(new_request.event_type)
    if new_group is not None and new_group == resolve_preempt_group(active_request.event_type):
        return PlaybackDecision(
            action="preempt",
            reason=f"same_preempt_group({new_group})",
            request=new_request,
            active=active_request,
        )

    if new_request.priority > active_request.priority:
        return PlaybackDecision(
            action="preempt",
            reason=f"higher_priority({new_request.priority}>{active_request.priority})",
            request=new_request,
            active=active_request,
        )

    if new_request.priority == active_request.priority:
        return PlaybackDecision(
            action="preempt",
            reason="same_priority_preempt",
            request=new_request,
            active=active_request,
        )

    return PlaybackDecision(
        action="drop",
        reason=f"lower_priority({new_request.priority}<{active_request.priority})",
        request=new_request,
        active=active_request,
    )
