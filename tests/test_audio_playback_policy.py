from __future__ import annotations

from core.audio.audio_playback_policy import PlaybackRequest, decide_channel_action, resolve_priority


def test_resolve_priority_defaults():
    assert resolve_priority("kill") > resolve_priority("reload")
    assert resolve_priority(None) == resolve_priority("default")


def test_policy_preempts_lower_priority():
    active = PlaybackRequest(key="reload-ak", channel_type="kill_sound", event_type="reload", priority=20, allow_preempt=True)
    new = PlaybackRequest(key="kill-1", channel_type="kill_sound", event_type="kill", priority=100, allow_preempt=True)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "preempt"


def test_policy_drops_when_preempt_disabled():
    active = PlaybackRequest(key="kill-1", channel_type="kill_sound", event_type="kill", priority=100, allow_preempt=True)
    new = PlaybackRequest(key="reload-ak", channel_type="kill_sound", event_type="reload", priority=20, allow_preempt=False)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "drop"


def test_kill_after_headshot_preempts_not_drops():
    """v2.2.1 核心修复：爆头声(110)占道时，普通击杀(100)必须切入而不是被 drop。

    旧行为 lower_priority drop 会让"爆头+补枪"双杀的第二声永久静音。
    """
    active = PlaybackRequest(key="kill-hs-1", channel_type="kill_sound", event_type="headshot", priority=110, allow_preempt=True)
    new = PlaybackRequest(key="kill-2", channel_type="kill_sound", event_type="kill", priority=100, allow_preempt=True)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "preempt"
    assert "same_preempt_group" in decision.reason


def test_headshot_after_kill_still_preempts():
    active = PlaybackRequest(key="kill-1", channel_type="kill_sound", event_type="kill", priority=100, allow_preempt=True)
    new = PlaybackRequest(key="kill-hs-2", channel_type="kill_sound", event_type="headshot", priority=110, allow_preempt=True)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "preempt"


def test_non_group_lower_priority_still_drops():
    """抢占组不改变组外规则：死亡声(40)撞上正在播的击杀(100)仍应 drop。"""
    active = PlaybackRequest(key="kill-1", channel_type="kill_sound", event_type="kill", priority=100, allow_preempt=True)
    new = PlaybackRequest(key="death-a", channel_type="kill_sound", event_type="death", priority=40, allow_preempt=True)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "drop"


def test_group_respects_preempt_disabled():
    """allow_preempt=False 的请求即便同组也不得抢占。"""
    active = PlaybackRequest(key="kill-hs-1", channel_type="kill_sound", event_type="headshot", priority=110, allow_preempt=True)
    new = PlaybackRequest(key="kill-2", channel_type="kill_sound", event_type="kill", priority=100, allow_preempt=False)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "drop"

