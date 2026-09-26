# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 124（批 116 挪来）：音频时间线是环形缓冲，满了之后每进一条就静默丢一条最老的。

排障时「回放」页上看到的第一条不是真的第一条，而页面上一个字都没有 ——
用户会以为「那一声根本没播」。⇒ 记下被顶掉几条，页面上说一句，并指到「导出」。
"""
from __future__ import annotations

from core.audio.audio_event_timeline import AudioEventTimeline


def _fill(timeline, n):
    for i in range(n):
        timeline.record_dict(action="play", key=f"k{i}")


def test_nothing_is_counted_until_the_ring_is_full():
    timeline = AudioEventTimeline(max_events=200)
    _fill(timeline, 200)
    assert timeline.dropped_count() == 0


def test_every_record_past_the_limit_pushes_one_out_and_clear_resets():
    timeline = AudioEventTimeline(max_events=200)
    _fill(timeline, 230)
    assert timeline.dropped_count() == 30
    assert timeline.query(limit=0, filters={})[0].key == "k30", "最老的 30 条确实没了"
    timeline.clear()
    assert timeline.dropped_count() == 0


def test_the_replay_page_says_it_and_points_at_export(qapp, monkeypatch):
    import pages.audio_replay_page as replay

    timeline = AudioEventTimeline(max_events=200)
    monkeypatch.setattr(replay, "get_audio_event_timeline", lambda: timeline)
    page = replay.AudioReplayPage()
    page._refresh_events()
    assert not page.overwritten_label.isVisibleTo(page), "没丢过就不该说"
    _fill(timeline, 205)
    page._refresh_events()
    text = page.overwritten_label.text()
    assert page.overwritten_label.isVisibleTo(page)
    assert "5 条" in text and "200" in text and page.export_btn.text() in text, text
