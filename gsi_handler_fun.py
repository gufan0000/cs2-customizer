# SPDX-License-Identifier: GPL-3.0-or-later
"""整活功能事件源：死亡 / 复活 / 中断 三类边沿。

只负责从 GSI 数据里识别边沿并回调，不碰任何窗口、UI 或线程调度——
窗口编排在 core/fun/afterlife.py，这样这层可以脱离 Qt 与游戏纯逻辑单测。

自我识别用 `provider.steamid` 而不是 `player.steamid`：
死亡后 CS2 会自动切到观战队友，此时 `player` 整个节点变成队友的数据
（activity 仍是 playing、health 是队友的血量），而 `provider.steamid`
恒为本机玩家。用它做门，观战帧会被整体跳过，`last_health` 停在 0 不被
队友血量覆盖，自己复活那一帧才构成 0 → >0 的复活边沿。
"""
import time

from config import config
from core.utils.logger import get_logger

logger = get_logger("GSIHandlerFun")

# 一次死亡在 GSI 里会持续很多帧，冷却防止重复触发
DEATH_COOLDOWN = 5.0


class GSIHandlerFun:
    def __init__(self, on_death=None, on_respawn=None, on_abort=None):
        """三个回调都在 GSI 处理线程上被调用，实现方自己负责跨线程。"""
        self._on_death = on_death
        self._on_respawn = on_respawn
        self._on_abort = on_abort

        self.last_health = None      # None = 尚无基线，首帧不判边沿
        self.death_cooldown = 0.0
        self.last_map_name = ""
        self.triggers_this_match = 0
        self.is_dead = False

        logger.info("整活 GSI handler 已初始化")

    # ---- 对外 ----

    def set_callbacks(self, *, on_death=None, on_respawn=None, on_abort=None):
        if on_death is not None:
            self._on_death = on_death
        if on_respawn is not None:
            self._on_respawn = on_respawn
        if on_abort is not None:
            self._on_abort = on_abort

    def process_data(self, data):
        if not bool(getattr(config, "fun_afterlife_enabled", False)):
            # 关闭期间也要跟着更新基线，否则关闭期死过一次，
            # 重新打开时陈旧的 last_health>0 会和 health==0 组成假死亡边沿
            self._sync_baseline(data)
            return

        map_data = data.get("map") or {}
        map_name = str(map_data.get("name", "") or "")

        # 离开对局（回主菜单）或换图：收回窗口并重置本局状态
        if not map_data:
            self._reset_match("离开对局")
            return
        if map_name and map_name != self.last_map_name:
            if self.last_map_name:
                self._reset_match(f"换图 {self.last_map_name} → {map_name}")
            self.last_map_name = map_name
            self.triggers_this_match = 0

        if not self._mode_allowed(map_data):
            self._sync_baseline(data)
            return

        self._process_health_edges(data)

    # ---- 内部 ----

    def _self_steamid(self, data):
        """本机玩家 steamid。provider 节点不受观战切换影响，优先用它。"""
        provider = data.get("provider") or {}
        sid = str(provider.get("steamid", "") or "").strip()
        if sid:
            return sid
        return str(getattr(config, "player_steamid", "") or "").strip()

    def _own_player_state(self, data):
        """只在这一帧确实是"本人"时返回 state，观战别人时返回 None。"""
        player = data.get("player") or {}
        if str(player.get("activity", "") or "") != "playing":
            return None
        own = self._self_steamid(data)
        if not own:
            # 认不出自己就一律不动作（fail-closed）：宁可不触发，
            # 也不能在观战队友死亡时把窗口糊到人脸上
            return None
        if str(player.get("steamid", "") or "") != own:
            return None
        state = player.get("state")
        return state if isinstance(state, dict) else None

    def _sync_baseline(self, data):
        state = self._own_player_state(data)
        if state and "health" in state:
            self.last_health = state["health"]

    def _mode_allowed(self, map_data):
        allowed = getattr(config, "fun_afterlife_modes", None)
        if not allowed:
            return False  # 没勾任何模式 = 不生效
        mode = str(map_data.get("mode", "") or "").strip().lower()
        return mode in {str(m).strip().lower() for m in allowed}

    def _process_health_edges(self, data):
        state = self._own_player_state(data)
        if state is None or "health" not in state:
            # 观战别人 / 菜单帧：不更新基线，死亡期间的 0 要保留到自己复活
            return

        current = state["health"]
        prev = self.last_health
        self.last_health = current

        if prev is None:
            return  # 首帧只建基线

        now = time.time()

        if current == 0 and prev > 0:
            if now < self.death_cooldown:
                return
            self.death_cooldown = now + DEATH_COOLDOWN
            limit = int(getattr(config, "fun_afterlife_max_per_match", 0) or 0)
            if limit > 0 and self.triggers_this_match >= limit:
                logger.info(f"本局触发次数已达上限 {limit}，跳过")
                return
            self.triggers_this_match += 1
            self.is_dead = True
            logger.info(f"检测到死亡（本局第 {self.triggers_this_match} 次）")
            self._fire(self._on_death, "on_death")
        elif current > 0 and prev == 0:
            if not self.is_dead:
                return
            self.is_dead = False
            logger.info("检测到复活")
            self._fire(self._on_respawn, "on_respawn")

    def _reset_match(self, reason):
        self.last_map_name = ""
        self.last_health = None
        self.triggers_this_match = 0
        if self.is_dead:
            self.is_dead = False
            logger.info(f"中断整活：{reason}")
            self._fire(self._on_abort, "on_abort", reason)

    def _fire(self, cb, name, *args):
        if cb is None:
            return
        try:
            cb(*args)
        except Exception:
            # 回调炸了不能带崩 GSI 处理线程——它还带着音效/闪光等一串 handler
            logger.exception(f"整活回调 {name} 执行失败")
