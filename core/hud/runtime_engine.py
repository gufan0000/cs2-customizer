"""
Runtime HUD rule evaluator driven by GSI data.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from core.hud.rule_model import (
    HUD_STATE_KEYS,
    normalize_hud_rules,
)


SNIPER_WEAPONS = {"weapon_awp", "weapon_ssg08", "weapon_scar20", "weapon_g3sg1"}
PISTOL_WEAPONS = {
    "weapon_glock",
    "weapon_hkp2000",
    "weapon_usp_silencer",
    "weapon_elite",
    "weapon_p250",
    "weapon_fiveseven",
    "weapon_tec9",
    "weapon_cz75a",
    "weapon_deagle",
    "weapon_revolver",
}
RIFLE_WEAPONS = {
    "weapon_ak47",
    "weapon_m4a1",
    "weapon_m4a1_silencer",
    "weapon_famas",
    "weapon_galilar",
    "weapon_aug",
    "weapon_sg556",
}


@dataclass
class RuntimeOutput:
    color: int | None
    rule_id: str = ""
    effect: str = "solid"


@dataclass
class _Candidate:
    rule_id: str
    rule: dict
    priority: int
    triggered_at: float
    marker: object


class RuntimeHudEngine:
    def __init__(self, rules=None, profile="balanced_default"):
        self._profile = profile
        self._rules = normalize_hud_rules(rules or {}, profile=self._profile)
        self.reset_state()

    def set_rules(self, rules, profile="balanced_default"):
        self._profile = profile
        self._rules = normalize_hud_rules(rules or {}, profile=self._profile)

    def reset_state(self):
        self.previous_health = 100
        self.previous_round_phase = ""
        self.previous_round_kills = 0
        self.previous_round_killhs = 0
        self.previous_active_weapon = ""
        self.player_alive = True
        self.team_side = ""

        self._event_until = {}
        self._event_triggered_at = {}
        self._state_until = {}
        self._state_triggered_at = {}

        self._last_active_marker = None
        self._effect_activation = {}

    def evaluate(self, data, now=None):
        if now is None:
            now = time.time()

        player = data.get("player")
        if not player:
            return RuntimeOutput(None)

        # 跳过观战他人的视角：观战时 player.steamid 变成被观战者，而
        # activity 仍是 "playing"（旧判定被 activity 条件短路，观战数据会
        # 驱动 HUD 并污染 previous_* 边沿检测）。provider.steamid 恒为本机。
        provider_steamid = data.get("provider", {}).get("steamid")
        player_steamid = player.get("steamid")
        if provider_steamid and player_steamid and player_steamid != provider_steamid:
            return RuntimeOutput(None)

        state = player.get("state", {})
        health = state.get("health", 100)
        round_kills = state.get("round_kills", 0)
        round_killhs = state.get("round_killhs", 0)
        self.team_side = player.get("team", "").lower()

        active_weapon = self._get_active_weapon(data)
        weapon_cat = self._classify_weapon(active_weapon)

        round_info = data.get("round", {})
        round_phase = round_info.get("phase", "")

        bomb_state = ""
        bomb_data = data.get("bomb")
        if isinstance(bomb_data, dict):
            bomb_state = bomb_data.get("state", "")
        elif isinstance(bomb_data, str):
            bomb_state = bomb_data

        self._detect_events(
            now=now,
            health=health,
            round_kills=round_kills,
            round_killhs=round_killhs,
            round_phase=round_phase,
            round_info=round_info,
        )

        # 更新前序状态
        self.previous_health = health
        self.previous_round_kills = round_kills
        self.previous_round_killhs = round_killhs
        self.previous_round_phase = round_phase
        self.previous_active_weapon = active_weapon
        if health > 0:
            self.player_alive = True

        candidate = self._pick_candidate(
            now=now,
            health=health,
            bomb_state=bomb_state,
            weapon_cat=weapon_cat,
            round_phase=round_phase,
        )
        if not candidate:
            return RuntimeOutput(None)

        marker = (candidate.rule_id, candidate.marker)
        if marker != self._last_active_marker:
            self._effect_activation[candidate.rule_id] = now
            self._last_active_marker = marker

        color = self._resolve_effect_color(candidate.rule_id, candidate.rule, now)
        if color is None or color < 0:
            return RuntimeOutput(None)
        return RuntimeOutput(color=color, rule_id=candidate.rule_id, effect=candidate.rule.get("effect", "solid"))

    def _duration_to_until(self, now, duration_ms):
        if duration_ms <= 0:
            return now
        return now + duration_ms / 1000.0

    def _trigger_event(self, key, now, duration_ms):
        self._event_triggered_at[key] = now
        self._event_until[key] = self._duration_to_until(now, duration_ms)

    def _trigger_state_window(self, key, now, duration_ms):
        self._state_triggered_at[key] = now
        self._state_until[key] = self._duration_to_until(now, duration_ms)

    def _detect_events(self, now, health, round_kills, round_killhs, round_phase, round_info):
        event_rules = self._rules.get("event_rules", {})
        state_rules = self._rules.get("state_rules", {})

        # 连杀
        if round_kills >= 3 and round_kills > self.previous_round_kills:
            rule = event_rules.get("multi_kill", {})
            if rule.get("enabled", False):
                self._trigger_event("multi_kill", now, rule.get("duration_ms", 0))

        # 爆头
        if round_killhs > self.previous_round_killhs:
            rule = event_rules.get("headshot_kill", {})
            if rule.get("enabled", False):
                self._trigger_event("headshot_kill", now, rule.get("duration_ms", 0))

        # 击杀
        if round_kills > self.previous_round_kills:
            rule = event_rules.get("kill", {})
            if rule.get("enabled", False):
                self._trigger_event("kill", now, rule.get("duration_ms", 0))

        # 死亡
        if health == 0 and self.previous_health > 0:
            self.player_alive = False
            rule = event_rules.get("death", {})
            if rule.get("enabled", False):
                self._trigger_event("death", now, rule.get("duration_ms", 0))

        # 回合结果
        if round_phase == "over" and self.previous_round_phase != "over":
            win_team = round_info.get("win_team", "").lower()
            if self.team_side and win_team:
                won = (win_team == self.team_side)
                key = "round_win" if won else "round_lose"
                rule = state_rules.get(key, {})
                if rule.get("enabled", False):
                    duration_ms = rule.get("duration_ms", 2500)
                    self._trigger_state_window(key, now, duration_ms)
                    other_key = "round_lose" if won else "round_win"
                    self._state_until[other_key] = 0
                    self._state_triggered_at[other_key] = 0

        if round_phase == "freezetime" and self.previous_round_phase != "freezetime":
            self._state_until["round_win"] = 0
            self._state_until["round_lose"] = 0

    def _event_active(self, key, now):
        return now < self._event_until.get(key, 0)

    def _state_window_active(self, key, now):
        return now < self._state_until.get(key, 0)

    def _candidate_from_rule(self, rule_id, rule, trigger_time, marker):
        if not rule.get("enabled", False):
            return None
        main = rule.get("main", -1)
        if not isinstance(main, int) or main < 0:
            return None
        return _Candidate(
            rule_id=rule_id,
            rule=rule,
            priority=int(rule.get("priority", 100)),
            triggered_at=float(trigger_time),
            marker=marker,
        )

    def _pick_candidate(self, now, health, bomb_state, weapon_cat, round_phase):
        event_rules = self._rules.get("event_rules", {})
        state_rules = self._rules.get("state_rules", {})
        candidates = []

        # 事件优先
        for key in ("death", "multi_kill", "headshot_kill", "kill"):
            if self._event_active(key, now):
                rule = event_rules.get(key, {})
                candidate = self._candidate_from_rule(
                    key,
                    rule,
                    self._event_triggered_at.get(key, 0),
                    self._event_triggered_at.get(key, 0),
                )
                if candidate:
                    candidates.append(candidate)

        # 低血量
        low_rule = event_rules.get("low_health", {})
        threshold = int(low_rule.get("threshold", 20))
        if 0 < health <= threshold:
            candidate = self._candidate_from_rule("low_health", low_rule, now, ("low_health", threshold))
            if candidate:
                candidates.append(candidate)

        # 炸弹
        if bomb_state == "planted":
            rule = state_rules.get("bomb_planted", {})
            candidate = self._candidate_from_rule("bomb_planted", rule, now, "bomb_planted")
            if candidate:
                candidates.append(candidate)

        # 回合胜负（有时间窗）
        for key in ("round_win", "round_lose"):
            if self._state_window_active(key, now):
                rule = state_rules.get(key, {})
                candidate = self._candidate_from_rule(
                    key,
                    rule,
                    self._state_triggered_at.get(key, 0),
                    self._state_triggered_at.get(key, 0),
                )
                if candidate:
                    candidates.append(candidate)

        # 武器状态
        if weapon_cat:
            key = f"weapon_{weapon_cat}"
            if key in HUD_STATE_KEYS:
                rule = state_rules.get(key, {})
                candidate = self._candidate_from_rule(key, rule, now, key)
                if candidate:
                    candidates.append(candidate)

        # 回合阶段
        if round_phase == "live":
            rule = state_rules.get("round_live", {})
            candidate = self._candidate_from_rule("round_live", rule, now, "round_live")
            if candidate:
                candidates.append(candidate)
        elif round_phase == "freezetime":
            rule = state_rules.get("round_start", {})
            candidate = self._candidate_from_rule("round_start", rule, now, "round_start")
            if candidate:
                candidates.append(candidate)

        # 默认
        default_color = self._rules.get("default_color", -1)
        if isinstance(default_color, int) and default_color >= 0:
            candidates.append(
                _Candidate(
                    rule_id="default",
                    rule={
                        "enabled": True,
                        "effect": "solid",
                        "main": default_color,
                        "alt": -1,
                        "interval_ms": 250,
                        "duty_cycle": 0.5,
                        "priority": 100,
                    },
                    priority=100,
                    triggered_at=0,
                    marker="default",
                )
            )

        if not candidates:
            return None

        candidates.sort(key=lambda c: (c.priority, c.triggered_at), reverse=True)
        return candidates[0]

    def _resolve_effect_color(self, rule_id, rule, now):
        main = rule.get("main", -1)
        alt = rule.get("alt", -1)
        effect = rule.get("effect", "solid")

        if not isinstance(main, int) or main < 0:
            return None
        if effect == "solid" or not isinstance(alt, int) or alt < 0:
            return main

        activated_at = self._effect_activation.get(rule_id, now)
        if effect == "flash":
            flash_ms = max(0, int(rule.get("flash_ms", 120)))
            if now < activated_at + flash_ms / 1000.0:
                return alt
            return main

        if effect == "blink":
            interval = max(50, int(rule.get("interval_ms", 250)))
            elapsed_ms = max(0.0, (now - activated_at) * 1000.0)
            phase = int(elapsed_ms // interval) % 2
            return main if phase == 0 else alt

        if effect == "pulse":
            interval = max(50, int(rule.get("interval_ms", 250)))
            duty = float(rule.get("duty_cycle", 0.5))
            duty = min(0.95, max(0.05, duty))
            elapsed_ms = max(0.0, (now - activated_at) * 1000.0)
            cycle_pos = elapsed_ms % interval
            return main if cycle_pos <= interval * duty else alt

        return main

    def _get_active_weapon(self, data):
        weapons = data.get("player", {}).get("weapons", {})
        for w in weapons.values():
            if isinstance(w, dict) and w.get("state") == "active":
                return w.get("name", "")
        return ""

    def _classify_weapon(self, weapon_name):
        if not weapon_name:
            return ""
        if weapon_name in SNIPER_WEAPONS:
            return "sniper"
        if weapon_name in RIFLE_WEAPONS:
            return "rifle"
        if weapon_name in PISTOL_WEAPONS:
            return "pistol"
        if weapon_name.startswith("weapon_knife"):
            return "knife"
        return ""

