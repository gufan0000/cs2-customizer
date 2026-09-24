# SPDX-License-Identifier: GPL-3.0-or-later
"""「哪一个是我」—— 本机玩家 steamid 的单一真源（RN-685，批 115）。

观战时 `player` 节点是被观战者，**`provider.steamid` 恒为本机**。`config.player_steamid`
只是兜底：它是第一帧记下的，第一帧在观战就记成别人。口径：provider 优先，config 兜底。
"""
from __future__ import annotations


def provider_steamid(data) -> str:
    provider = data.get("provider") if isinstance(data, dict) else None
    if isinstance(provider, dict):
        return str(provider.get("steamid", "") or "").strip()
    return ""


def resolve_self_steamid(data, fallback: str = "") -> str:
    """本机玩家的 steamid：`provider.steamid` 优先，取不到才用 `fallback`（config 里记的那个）。"""
    return provider_steamid(data) or str(fallback or "").strip()


def is_self(data, fallback: str = "") -> bool:
    """这一帧的 `player` 块是不是本人。认不出自己（两边都空）时按「是」—— 与旧行为一致。"""
    player = data.get("player") if isinstance(data, dict) else None
    player_sid = str((player or {}).get("steamid", "") or "").strip() if isinstance(player, dict) else ""
    own = resolve_self_steamid(data, fallback)
    return (not own) or (not player_sid) or player_sid == own
