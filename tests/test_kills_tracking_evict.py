# -*- coding: utf-8 -*-
"""kills handler per-steamid 跟踪字典无界增长防护(P3⑥)。"""
import gsi_handler_kills


def _fill(h, n):
    for i in range(n):
        sid = f"sid_{i}"
        h.previous_round_kills[sid] = i
        h.previous_total_kills[sid] = i
        h.previous_match_kills[sid] = i
        h.played_sounds_this_round[sid] = set()
        h.new_round_start_time[sid] = 0.0
        h.await_round_kill_reset[sid] = False
        h.played_kill_levels[sid] = set()
        h.previous_round_killhs[sid] = 0


def test_no_evict_under_cap():
    h = gsi_handler_kills.GSIHandlerKills()
    _fill(h, 3)
    h._evict_tracking_if_needed("sid_1")
    assert len(h.previous_round_kills) == 3  # 未超限,不动


def test_evict_keeps_current_player():
    h = gsi_handler_kills.GSIHandlerKills()
    _fill(h, 200)  # 远超 64 上限(模拟长时间观战大服)
    h.previous_round_kills["sid_7"] = 99
    h._evict_tracking_if_needed("sid_7")
    # 清理后只保留当前玩家
    assert "sid_7" in h.previous_round_kills
    assert h.previous_round_kills["sid_7"] == 99
    assert len(h.previous_round_kills) == 1
    assert len(h.played_kill_levels) <= 1


def test_evict_drops_all_when_keep_absent():
    h = gsi_handler_kills.GSIHandlerKills()
    _fill(h, 100)
    h._evict_tracking_if_needed("not_present")
    assert len(h.previous_round_kills) == 0
