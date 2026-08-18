# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
CS2 Customizer — GSI 全对局信号模拟器 (full-match simulation harness)

不依赖 CS2 / 真实音频设备 / Windows。直接构造一整局 CS2 的 GSI 状态帧序列,
喂给全部 8 个 gsi_handler_* 处理器, 用 spy 组件捕获每个处理器的真实响应,
最后输出一份"哪个事件触发了什么"的逐帧 + 汇总报告。

用法 (沙盒 headless):
  LD_LIBRARY_PATH=~/.local/extralib xvfb-run -a python3 scripts/gsi_full_sim.py
"""
from __future__ import annotations
import os, sys, ctypes, types
from unittest.mock import MagicMock

# ---------------- 沙盒垫片 (Windows-only / 系统库缺失) ----------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
if not hasattr(ctypes, "windll"):
    ctypes.windll = MagicMock(name="windll")
if not hasattr(ctypes, "WinDLL"):
    ctypes.WinDLL = MagicMock(name="WinDLL")
if not hasattr(ctypes, "wintypes"):
    class _WT(types.ModuleType):
        _c = {}
        def __getattr__(self, n):
            if n.startswith("__"): raise AttributeError(n)
            return self._c.setdefault(n, type(n, (ctypes.c_void_p,), {}))
    _wt = _WT("ctypes.wintypes"); sys.modules["ctypes.wintypes"] = _wt; ctypes.wintypes = _wt
try:
    import tkinter  # noqa
except ModuleNotFoundError:
    _tk = types.ModuleType("tkinter")
    for _n in ("Tk","Toplevel","Label","Button","Frame","Entry","Canvas","StringVar","IntVar","BooleanVar"):
        setattr(_tk, _n, MagicMock())
    for _s in ("messagebox","filedialog","ttk","font","scrolledtext"):
        _m = types.ModuleType(f"tkinter.{_s}"); _m.__getattr__ = lambda n: MagicMock()
        sys.modules[f"tkinter.{_s}"] = _m; setattr(_tk, _s, _m)
    sys.modules["tkinter"] = _tk
import ctypes.util as _cul
_of = _cul.find_library
def _ff(name):
    r = _of(name)
    if r: return r
    for sfx in (".so.2",".so.1",".so"):
        c = os.path.expanduser(f"~/.local/extralib/lib{name}{sfx}")
        if os.path.exists(c): return c
    return None
_cul.find_library = _ff

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------- Spy 组件 ----------------
class SpyAudio:
    """记录所有被调用的播放方法; 未知方法自动当作 no-op 记录。
    显式提供处理器会读取的数据属性 (sounds/voices/风格目录), 避免 __getattr__ 误把
    数据属性当成方法返回。"""
    def __init__(self):
        self.calls = []
        # 处理器以 `key in audio_manager.sounds` / getattr(...) 形式读取的数据属性
        self.sounds = {}
        self.voices = {}
        self.weapon_kill_sound_styles = {}
        self.kill_sound_styles = []
        self.weapon_sounds_dir = ""
        self.kill_sounds_dir = ""
        self.weapon_kill_voice_styles = {}
        self.kill_voice_styles = []
        self.weapon_voices_dir = ""
        self.kill_voices_dir = ""
    def play_sound(self, key, channel_type="kill_sound", **k): self.calls.append(("play_sound", key, channel_type)); return True
    def play_voice(self, key, **k): self.calls.append(("play_voice", key)); return True
    def play_sound_with_fade(self, key, channel_type="round_sound", **k): self.calls.append(("play_sound_with_fade", key, channel_type)); return True
    def load_round_sound(self, rt, style): self.calls.append(("load_round_sound", rt, style)); return True
    def load_health_warning_sound(self, style): self.calls.append(("load_health_warning_sound", style)); return True
    def _load_sound_by_key(self, key): return True
    def _load_voice_by_key(self, key): return True
    def __getattr__(self, name):
        # 仅对真正未知的"方法调用"兜底; 数据属性已在 __init__ 显式给出
        def _rec(*a, **k):
            self.calls.append((name,) + tuple(str(x)[:40] for x in a)); return True
        return _rec

class SpyKeyboard:
    def press(self, *a, **k): pass
    def release(self, *a, **k): pass

class SpyComponent:
    """通用 spy: 记录任意属性访问/调用 (flash / image_player / magnifier / utility_display / dashboard)。"""
    def __init__(self, name): self._name = name; self.calls = []
    def __getattr__(self, attr):
        if attr.startswith("_"): raise AttributeError(attr)
        def _rec(*a, **k):
            self.calls.append(f"{attr}({', '.join(str(x)[:30] for x in a)})")
            return None
        return _rec

class SpyFlashComponent:
    def __init__(self):
        self.calls = []
        pm = self
        class _PM:
            def __init__(s): s.audio_auto_stop=True; s.audio_playing=False
            def update_flash_value(s, v): pm.calls.append(f"update_flash_value({v})")
            def force_clear_flash(s): pm.calls.append("force_clear_flash()")
            def stop_audio(s): pm.calls.append("stop_audio()")
        self.process_manager = _PM()

class SpyMusicPlayer:
    def __init__(self): self.calls=[]; self.is_playing=True; self.is_paused=False
    def __getattr__(self, attr):
        def _rec(*a, **k): self.calls.append(f"{attr}({', '.join(str(x)[:20] for x in a)})"); return None
        return _rec

class SpyGui:
    def __init__(self): self.dashboard = SpyComponent("status_dashboard")
    def get_status_dashboard(self): return self.dashboard

# ---------------- 装载处理器 ----------------
import gsi_handler_kills, gsi_handler_special, gsi_handler_sounds
import gsi_handler_flash, gsi_handler_utility, gsi_handler_hud_color
import gsi_handler_music, gsi_handler_stats
from config import config

# 注入 spy audio_manager
spy_audio = SpyAudio()
for mod in (gsi_handler_kills, gsi_handler_special, gsi_handler_sounds):
    if hasattr(mod, "audio_manager"):
        mod.audio_manager = spy_audio
gsi_handler_sounds.Controller = SpyKeyboard

# 打开所有功能开关
ENABLE = dict(
    kill_sound_enabled=True, kill_voice_enabled=True, kill_icon_enabled=True,
    flash_enabled=True, gun_sound_enabled=True, awp_enabled=True,
    death_sound_enabled=True, c4_sound_enabled=True, health_warning_enabled=True,
    round_sound_enabled=True, grenade_sound_enabled=True,
    switch_weapon_sound_enabled=True, reload_sound_enabled=True,
    music_enabled=True, music_game_link_enabled=True,
    spectator_mode_mute=False,
)
for k, v in ENABLE.items():
    try: setattr(config, k, v)
    except Exception: pass
config.player_steamid = "SIM_STEAM_001"
config.mode = "1. 官匹竞技"
try: config.save_config = lambda *a, **k: None
except Exception: pass
for attr, val in dict(
    death_sound_style="经典", c4_sound_style="经典", health_warning_style="经典",
    health_warning_threshold=35, round_start_style="经典", round_action_style="经典",
    round_win_style="经典", round_lose_style="经典", round_mvp_style="经典",
    awp_style="经典", awp_mute_duration=0.2,
).items():
    try: setattr(config, attr, val)
    except Exception: pass
try: config.grenade_sound_styles = {"hegrenade": "经典", "flashbang": "经典", "smokegrenade": "经典"}
except Exception: pass
try: config.weapon_switch_sounds = {"weapon_ak47": "经典", "weapon_awp": "经典"}
except Exception: pass
try: config.weapon_reload_sounds = {"weapon_ak47": "经典", "weapon_awp": "经典"}
except Exception: pass

# 实例化 8 个处理器
spy_flash = SpyFlashComponent()
spy_image = SpyComponent("image_player")
spy_magnifier = SpyComponent("magnifier")
spy_utility = SpyComponent("utility_display")
spy_music = SpyMusicPlayer()
spy_gui = SpyGui()

handlers = {}
init_errors = {}
def _mk(name, fn):
    try:
        handlers[name] = fn()
    except Exception as e:
        init_errors[name] = f"{type(e).__name__}: {e}"

_mk("kills", gsi_handler_kills.GSIHandlerKills)
_mk("special", gsi_handler_special.GSIHandlerSpecial)
_mk("sounds", gsi_handler_sounds.GSIHandlerSounds)
_mk("flash", gsi_handler_flash.GSIHandlerFlash)
_mk("utility", gsi_handler_utility.GSIHandlerUtility)
_mk("hud_color", gsi_handler_hud_color.GSIHandlerHudColor)
_mk("music", gsi_handler_music.GSIHandlerMusic)
_mk("stats", lambda: gsi_handler_stats.GSIHandlerStats(spy_gui))

# 连接 spy 组件
if "kills" in handlers:
    handlers["kills"].set_image_player(spy_image)
    # key 解析依赖真实音频资源目录(单测已覆盖), 此处桩成确定值以便观察"击杀->音效"信号流
    handlers["kills"]._get_weapon_kill_sound_key = lambda weapon, kills, hs=False: f"kill-{kills}" + ("-headshot" if hs else "")
    handlers["kills"]._get_weapon_kill_voice_key = lambda weapon, kills, hs=False: f"voice-{kills}"
if "flash" in handlers:
    handlers["flash"].set_flash_component(spy_flash)
if "sounds" in handlers and hasattr(handlers["sounds"], "set_magnifier_component"):
    handlers["sounds"].set_magnifier_component(spy_magnifier)
if "utility" in handlers and hasattr(handlers["utility"], "set_utility_display"):
    try: handlers["utility"].set_utility_display(spy_utility)
    except Exception: pass
if "music" in handlers:
    handlers["music"].player = spy_music

# ---------------- 构造一整局 CS2 GSI 帧序列 ----------------
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

# 帧序列: (标签, payload)
SCRIPT = [
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

# ---------------- 逐帧分发 ----------------
print("=" * 72)
print("  CS2 Customizer — GSI 全对局信号模拟  (24 帧 / 8 处理器)")
print("=" * 72)
print(f"  处理器实例化: {len(handlers)}/8 成功", f"  失败: {init_errors}" if init_errors else "")
print("-" * 72)

per_handler_calls = {n: 0 for n in handlers}
per_handler_errors = {n: [] for n in handlers}
frame_log = []

for idx, (label, payload) in enumerate(SCRIPT, 1):
    triggered = []
    audio_before = len(spy_audio.calls)
    flash_before = len(spy_flash.calls)
    music_before = len(spy_music.calls)
    img_before = len(spy_image.calls)
    dash_before = len(spy_gui.dashboard.calls)
    for name, h in handlers.items():
        try:
            h.process_data(payload)
            per_handler_calls[name] += 1
        except Exception as e:
            per_handler_errors[name].append(f"帧#{idx}[{label}] {type(e).__name__}: {e}")
    new_audio = spy_audio.calls[audio_before:]
    new_flash = spy_flash.calls[flash_before:]
    new_music = spy_music.calls[music_before:]
    new_img = spy_image.calls[img_before:]
    new_dash = spy_gui.dashboard.calls[dash_before:]
    if new_audio: triggered.append(f"audio:{new_audio}")
    if new_flash: triggered.append(f"flash:{new_flash}")
    if new_music: triggered.append(f"music:{new_music}")
    if new_img:   triggered.append(f"icon:{new_img}")
    if new_dash:  triggered.append(f"stats:{new_dash}")
    frame_log.append((idx, label, triggered))
    tag = " / ".join(triggered) if triggered else "(无副作用 — 状态更新帧)"
    print(f"  帧#{idx:>2} {label:<22} -> {tag}")

# ---------------- 汇总 ----------------
print("-" * 72)
print("  各处理器健康度:")
total_err = 0
for name in handlers:
    errs = per_handler_errors[name]
    total_err += len(errs)
    status = "OK" if not errs else f"!! {len(errs)} 处异常"
    print(f"    {name:<12} 处理 {per_handler_calls[name]:>2} 帧  {status}")
    for e in errs[:3]:
        print(f"        - {e}")
for name, err in init_errors.items():
    print(f"    {name:<12} 实例化失败: {err}")
    total_err += 1

print("-" * 72)
print("  音频事件汇总 (spy 捕获的 play_* 调用):")
from collections import Counter
ac = Counter()
for c in spy_audio.calls:
    if c[0] in ("play_sound", "play_voice", "play_sound_with_fade", "load_round_sound", "load_health_warning_sound"):
        ac[c[0]] += 1
for k, v in sorted(ac.items()):
    print(f"    {k:<24} x{v}")
print(f"  flash 组件调用: {len(spy_flash.calls)}  | music 组件调用: {len(spy_music.calls)}"
      f"  | 击杀图标调用: {len(spy_image.calls)}  | 统计面板调用: {len(spy_gui.dashboard.calls)}")
if "stats" in handlers:
    h = handlers["stats"]
    print(f"  stats 会话统计: 总击杀={h.total_kills} 总爆头={h.total_headshots} 总死亡={h.total_deaths} K/D={h._calculate_kd()}")

print("=" * 72)
frames_with_fx = sum(1 for _, _, t in frame_log if t)
verdict = "全部通过" if total_err == 0 else f"{total_err} 处异常"
print(f"  结论: {len(handlers)}/8 处理器在线, 24 帧全程分发, {frames_with_fx} 帧产生预期副作用, {verdict}")
print("=" * 72)
sys.exit(0 if total_err == 0 else 1)
