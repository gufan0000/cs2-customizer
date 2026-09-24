# SPDX-License-Identifier: GPL-3.0-or-later
"""`round_kills` 涨了但不是枪打的 —— 击杀归属的单一真源（批 115，登记册 RN-683 / RN-684）。

炸弹炸死的人头记在下包者名下；扔雷切枪后雷炸死人，这包推断不出开火。
纯状态机（不碰 config / 音频 / Qt），按帧喂、传入 `now`；消费方各持一个实例。
⚠ 口径：**宁漏不错**，认不准就退回原来的判定。
"""
from __future__ import annotations

#: 炸弹由「未爆」变「已爆」之后，多久之内新增的人头算炸弹的。
#: 爆炸扣血与记人头在服务器同一 tick，正常是同一包；留 1 秒吸收 GSI 分包抖动。
BOMB_KILL_WINDOW_S = 1.0

#: 会致死的投掷物 ⇒ 扔出后多久之内的击杀可以归给它。
#: 手雷引信约 1.6 秒 + 飞行；燃烧瓶/燃烧弹落地后烧约 7 秒 + 飞行。
LETHAL_GRENADE_WINDOWS_S = {
    "weapon_hegrenade": 5.0,
    "weapon_molotov": 10.0,
    "weapon_incgrenade": 10.0,
}

#: 所有投掷物（投掷检测用；闪光/烟雾/诱饵扔出去也要播投掷音效，只是不参与击杀归属）。
ALL_GRENADES = (
    "weapon_hegrenade", "weapon_flashbang", "weapon_smokegrenade",
    "weapon_molotov", "weapon_incgrenade", "weapon_decoy",
)


def bomb_state(data) -> str:
    """这一帧的炸弹状态（小写）。`round.bomb` 优先，其次 `bomb.state` / `bomb`（字符串）。"""
    if not isinstance(data, dict):
        return ""
    round_data = data.get("round")
    if isinstance(round_data, dict):
        value = round_data.get("bomb")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    bomb = data.get("bomb")
    if isinstance(bomb, dict):
        value = bomb.get("state")
        if isinstance(value, str):
            return value.strip().lower()
    if isinstance(bomb, str):
        return bomb.strip().lower()
    return ""


class BombKillFilter:
    """记下炸弹「变成已爆」的那一刻；那之后很短窗口内、本帧没开火的人头算炸弹的。

    ⚠ 只看「变成已爆」那一刻而不是「现在是已爆」：回合结束后 `round.bomb` 会一直
    停在 exploded，那段时间里拿枪补的人头（`_is_round_end_kill_delta` 放行的那种）
    是真击杀，不能被吞。
    """

    def __init__(self, window_s: float = BOMB_KILL_WINDOW_S):
        self.window_s = window_s
        self._previous_state = ""
        self._exploded_at = None

    def observe(self, data, now: float) -> None:
        state = bomb_state(data)
        if state == "exploded" and self._previous_state != "exploded":
            self._exploded_at = now
        elif state != "exploded":
            self._exploded_at = None
        self._previous_state = state

    def is_bomb_kill(self, now: float, fired: bool = False) -> bool:
        """本帧新增的人头是不是炸弹炸的。`fired` = 本帧推断出了开火（那就是枪杀）。"""
        if fired or self._exploded_at is None:
            return False
        return now - self._exploded_at <= self.window_s


def _grenade_count(entry) -> int:
    try:
        return int(entry.get("ammo_reserve", 1) or 0)
    except (TypeError, ValueError):
        return 1


def grenade_counts(weapons, names=ALL_GRENADES) -> dict:
    """weapons 快照里每种投掷物的数量（`ammo_reserve`，缺字段按 1 个算）。"""
    counts = {name: 0 for name in names}
    if not isinstance(weapons, dict):
        return counts
    for entry in weapons.values():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        if name in counts:
            counts[name] += _grenade_count(entry)
    return counts


def active_weapon(weapons) -> str:
    if not isinstance(weapons, dict):
        return ""
    for entry in weapons.values():
        if isinstance(entry, dict) and entry.get("state") == "active":
            return str(entry.get("name", "") or "")
    return ""


def thrown_grenade(previous_active: str, previous_counts: dict, counts: dict) -> str:
    """上一帧举着某种投掷物、这一帧它少了一个 ⇒ 扔出去了，返回它的名字；否则空串。

    special 处理器（投掷音效）和本模块的投掷物追踪共用这一条判定。
    """
    if previous_active not in counts:
        return ""
    if counts.get(previous_active, 0) < previous_counts.get(previous_active, 0):
        return previous_active
    return ""


class GrenadeKillTracker:
    """记住「刚扔出去的致死投掷物」，供击杀武器解析认领。

    清空时机：任何一次开枪（那之后的击杀更可能是枪）、回合切换、观战切人。
    ⚠ 击杀之后**不**清：一颗雷可以分两包炸死两个人，一团火可以烧死好几个。
    """

    def __init__(self, windows=None):
        self.windows = dict(windows or LETHAL_GRENADE_WINDOWS_S)
        self._previous_active = ""
        self._previous_counts = {}
        self._pending = ""
        self._pending_at = 0.0

    def reset(self) -> None:
        self._previous_active = ""
        self._previous_counts = {}
        self._pending = ""

    def observe(self, weapons, now: float) -> None:
        counts = grenade_counts(weapons)
        thrown = thrown_grenade(self._previous_active, self._previous_counts, counts)
        if thrown in self.windows:
            self._pending = thrown
            self._pending_at = now
        self._previous_active = active_weapon(weapons)
        self._previous_counts = counts

    def note_gun_fired(self) -> None:
        self._pending = ""

    def claim(self, now: float, is_headshot: bool = False) -> str:
        """这次击杀能不能归给刚扔出去的投掷物。能 ⇒ 返回武器名；不能 ⇒ 空串。"""
        if not self._pending or is_headshot:
            return ""
        if now - self._pending_at > self.windows.get(self._pending, 0.0):
            self._pending = ""
            return ""
        return self._pending
