# -*- coding: utf-8 -*-
"""
帆派助手 — 活体 GSI 模拟器 (live HTTP simulation)

与 gsi_full_sim.py 不同: 本脚本不在进程内调 handler, 而是把一整局 CS2 的
GSI 状态帧通过真实 HTTP POST 打到正在运行的帆派助手 GSI 服务器
(http://127.0.0.1:3000), 跑通完整管线:
    Flask 收包 -> data_queue -> process_data 线程 -> 8 个 handler -> 真实音效/准心/闪光/放大镜/音乐/HUD

用法 (在已启动 app 的 Windows 上):
    python scripts/gsi_live_sim.py             # 默认每帧间隔 1.2s
    python scripts/gsi_live_sim.py --delay 0.6 # 加速
    python scripts/gsi_live_sim.py --url http://127.0.0.1:3000

帧序列与 gsi_full_sim.py 完全一致 (同一份真实 schema), 便于两套结果交叉印证。
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
import urllib.error

SID = "SIM_STEAM_001"


def frame(round_no=1, phase="live", map_phase="live", activity="playing", health=100,
          round_kills=0, round_killhs=0, match_kills=0, mvps=0, flashed=0,
          weapon="weapon_ak47", weapon_state="active", ammo_clip=30, team="CT",
          bomb=None, map_name="de_dust2"):
    d = {
        "provider": {"name": "Counter-Strike: Global Offensive", "steamid": SID},
        "map": {"name": map_name, "round": round_no, "phase": map_phase,
                "team_ct": {"score": 0}, "team_t": {"score": 0}},
        "round": {"phase": phase},
        "player": {
            "steamid": SID, "name": "SimPlayer", "team": team, "activity": activity,
            "match_stats": {"kills": match_kills, "deaths": 0, "mvps": mvps, "score": 0},
            "state": {"health": health, "armor": 100, "flashed": flashed,
                      "round_kills": round_kills, "round_killhs": round_killhs,
                      "money": 5000, "equip_value": 4000},
            "weapons": {"weapon_0": {"name": weapon, "state": weapon_state,
                                     "type": "Rifle", "ammo_clip": ammo_clip,
                                     "ammo_clip_max": 30, "ammo_reserve": 90}},
        },
    }
    if bomb is not None:
        d["bomb"] = bomb
    return d


def _build_script():
    return [
    ("菜单/热身",            frame(round_no=0, phase="warmup", map_phase="warmup", activity="menu", health=100)),
    ("R1 冻结期",            frame(round_no=1, phase="freezetime", health=100, weapon="weapon_knife", weapon_state="active")),
    ("R1 出生(满血)",        frame(round_no=1, phase="live", health=100, weapon="weapon_knife")),
    ("切枪 刀->AK47",        frame(round_no=1, phase="live", health=100, weapon="weapon_ak47", weapon_state="active")),
    ("换弹 AK47",            frame(round_no=1, phase="live", health=100, weapon="weapon_ak47", weapon_state="reloading", ammo_clip=0)),
    ("换弹完成",             frame(round_no=1, phase="live", health=100, weapon="weapon_ak47", ammo_clip=30)),
    ("第1杀",               frame(round_no=1, phase="live", health=90, round_kills=1, match_kills=1, weapon="weapon_ak47")),
    ("第2杀(双杀)",          frame(round_no=1, phase="live", health=85, round_kills=2, match_kills=2, weapon="weapon_ak47")),
    ("第3杀(爆头)",          frame(round_no=1, phase="live", health=80, round_kills=3, round_killhs=1, match_kills=3, weapon="weapon_ak47")),
    ("被闪光",               frame(round_no=1, phase="live", health=80, round_kills=3, round_killhs=1, match_kills=3, flashed=255)),
    ("闪光消退",             frame(round_no=1, phase="live", health=80, round_kills=3, round_killhs=1, match_kills=3, flashed=80)),
    ("闪光结束",             frame(round_no=1, phase="live", health=80, round_kills=3, round_killhs=1, match_kills=3, flashed=0)),
    ("投掷手雷",             frame(round_no=1, phase="live", health=80, round_kills=3, match_kills=3, weapon="weapon_hegrenade", weapon_state="active")),
    ("切回 AK47",            frame(round_no=1, phase="live", health=80, round_kills=3, match_kills=3, weapon="weapon_ak47")),
    ("残血警告(20血)",       frame(round_no=1, phase="live", health=20, round_kills=3, round_killhs=1, match_kills=3)),
    ("C4 安放",              frame(round_no=1, phase="live", map_phase="live", health=20, round_kills=3, match_kills=3, bomb="planted")),
    ("阵亡(0血)",            frame(round_no=1, phase="live", activity="playing", health=0, round_kills=3, round_killhs=1, match_kills=3)),
    ("R1 结束(胜利+MVP)",    frame(round_no=1, phase="over", map_phase="live", activity="playing", health=0, round_kills=3, match_kills=3, mvps=1)),
    ("R2 冻结期",            frame(round_no=2, phase="freezetime", health=100, weapon="weapon_knife")),
    ("R2 出生",              frame(round_no=2, phase="live", health=100, weapon="weapon_ak47")),
    ("R2 第1杀",             frame(round_no=2, phase="live", health=100, round_kills=1, match_kills=4, weapon="weapon_ak47")),
    ("换图 dust2->mirage",   frame(round_no=1, phase="freezetime", health=100, weapon="weapon_knife", map_name="de_mirage", team="T")),
    ("换图后出生",           frame(round_no=1, phase="live", health=100, weapon="weapon_awp", map_name="de_mirage", team="T")),
    ("AWP 开火(弹药下降)",   frame(round_no=1, phase="live", health=100, weapon="weapon_awp", ammo_clip=4, map_name="de_mirage", team="T")),
    ]


SCRIPT = _build_script()


def post_frame(url, payload, timeout=3.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ms = int((time.time() - t0) * 1000)
        return resp.status, resp.read().decode("utf-8", "ignore")[:60], ms


def main():
    global SID, SCRIPT
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:3000")
    ap.add_argument("--delay", type=float, default=1.2, help="帧间隔秒数")
    ap.add_argument("--steamid", default=SID,
                    help="模拟玩家 SteamID; 须与运行时 config.player_steamid 一致才不会被观战静音过滤")
    args = ap.parse_args()
    # 用指定 steamid 重建帧序列 (frame() 读取全局 SID)
    if args.steamid != SID:
        SID = args.steamid
        SCRIPT = _build_script()

    print("=" * 72)
    print("  帆派助手 — 活体 GSI 模拟 (HTTP POST 到运行中的服务器)")
    print(f"  目标: {args.url}   帧数: {len(SCRIPT)}   帧间隔: {args.delay}s")
    print("=" * 72)

    # 探活
    try:
        st, _, ms = post_frame(args.url, frame(round_no=0, phase="warmup",
                                               map_phase="warmup", activity="menu"))
        print(f"  [探活] 服务器在线, HTTP {st} ({ms}ms)")
    except urllib.error.URLError as e:
        print(f"  [探活失败] 无法连接 {args.url} : {e}")
        print("  请确认帆派助手已启动且 GSI 服务器监听 3000。")
        return 2

    print("-" * 72)
    ok = 0
    fail = 0
    for idx, (label, payload) in enumerate(SCRIPT, 1):
        try:
            st, _, ms = post_frame(args.url, payload)
            ok += 1
            print(f"  帧#{idx:>2} {label:<22} -> HTTP {st} ({ms}ms)")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  帧#{idx:>2} {label:<22} -> 失败: {type(e).__name__}: {e}")
        time.sleep(args.delay)

    print("-" * 72)
    print(f"  完成: {ok} 帧成功 / {fail} 帧失败 / 共 {len(SCRIPT)} 帧")
    print("  提示: 现在去看 app 的准心/闪光/放大镜等效果, 并检查 FanTool 日志确认各 handler 触发。")
    print("=" * 72)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
