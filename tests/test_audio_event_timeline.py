from __future__ import annotations

from core.audio.audio_event_timeline import AudioEvent, AudioEventTimeline


class _DummyAudioManager:
    def __init__(self):
        self.calls = []

    def play_sound(self, key, channel_type="kill_sound", event_type=None, **_kwargs):
        self.calls.append((key, channel_type, event_type))
        return key != "bad"


def test_audio_event_timeline_query_export_and_replay(tmp_path):
    timeline = AudioEventTimeline(max_events=50)
    timeline.record(AudioEvent(timestamp=1.0, action="play", key="kill-1", channel_type="kill_sound", event_type="kill"))
    timeline.record(AudioEvent(timestamp=2.0, action="drop", key="reload-ak", channel_type="reload", event_type="reload"))
    timeline.record(AudioEvent(timestamp=3.0, action="play", key="bad", channel_type="kill_sound", event_type="kill"))

    filtered = timeline.query(limit=10, filters={"action": "play"})
    assert len(filtered) == 2

    out = tmp_path / "timeline.json"
    timeline.export_json(str(out))
    assert out.exists()

    mgr = _DummyAudioManager()
    result = timeline.replay(filtered, mgr)
    assert result["requested"] == 2
    assert result["played"] == 1
    assert result["failed"] == 1

