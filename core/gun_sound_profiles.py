# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


DISABLED_GUN_SOUND_STYLES = {"", "0", "none", "off", "disabled", "不启用", "未启用"}


@dataclass(frozen=True)
class GunSoundProfile:
    gun_type: str
    display_name: str
    gsi_names: tuple[str, ...]
    style_key: str
    mute_duration_key: str
    duck_ratio_key: str
    legacy_enabled_key: str
    min_fire_interval: float
    default_mute_duration: float = 0.4
    default_duck_ratio: float = 0.18
    duck_ratio_scale: float = 1.0
    peak_ratio_scale: float = 0.62
    peak_ms: int = 55
    release_scale: float = 1.0
    burst_window: float = 0.24
    burst_duck_ratio_scale: float = 0.82
    burst_peak_ratio_scale: float = 0.52
    burst_peak_ms: int = 36
    burst_release_scale: float = 1.35
    burst_hold_scale: float = 1.12
    #: 游戏钉死的射击周期（秒，CS2 的 cycletime）。**35 把都填**：`min_fire_interval`
    #: 一律从这里算（× `FULL_AUTO_GATE_SCALE`），不再逐把手填一个猜的数。
    #: ⚠ 半自动的周期也是游戏钉死的（点得再快也快不过它）—— 2026-09-17 之前半自动
    #: 的闸门是手填的，Tec-9 0.09 对周期 0.12、沙鹰 0.18 对 0.224，余量只有 30~45ms，
    #: 而真实 GSI 包间隔 P5 就是 62ms：一次抖动就吃掉一发真开的枪。
    fire_period: float = 0.0
    #: 全自动（扣住扳机自己连发）。它决定两件事：扫射档用 `_FULL_AUTO_BURST` 的形状、
    #: 页面上哪几个页签要说「扫射会留一点原声」。半自动 / 单发为 False。
    automatic: bool = False


@dataclass(frozen=True)
class GunSoundDuckPlan:
    sustain_ratio: float
    peak_ratio: float
    peak_ms: int
    hold_duration: float
    release_ms: int
    is_burst: bool


_FAMILY_DEFAULTS = {
    "pistol": {
        "default_mute_duration": 0.24,
        "duck_ratio_scale": 0.70,
        "peak_ratio_scale": 0.38,
        "peak_ms": 46,
        "release_scale": 1.24,
        "burst_window": 0.24,
        "burst_duck_ratio_scale": 0.52,
        "burst_peak_ratio_scale": 0.28,
        "burst_peak_ms": 26,
        "burst_release_scale": 1.90,
        "burst_hold_scale": 1.30,
    },
    "smg": {
        "default_mute_duration": 0.20,
        "duck_ratio_scale": 0.62,
        "peak_ratio_scale": 0.30,
        "peak_ms": 34,
        "release_scale": 1.36,
        "burst_window": 0.18,
        "burst_duck_ratio_scale": 0.42,
        "burst_peak_ratio_scale": 0.20,
        "burst_peak_ms": 20,
        "burst_release_scale": 2.10,
        "burst_hold_scale": 1.42,
    },
    "rifle": {
        "default_mute_duration": 0.24,
        "duck_ratio_scale": 0.70,
        "peak_ratio_scale": 0.36,
        "peak_ms": 40,
        "release_scale": 1.28,
        "burst_window": 0.20,
        "burst_duck_ratio_scale": 0.48,
        "burst_peak_ratio_scale": 0.22,
        "burst_peak_ms": 24,
        "burst_release_scale": 2.00,
        "burst_hold_scale": 1.38,
    },
    "shotgun": {
        "default_mute_duration": 0.30,
        "duck_ratio_scale": 0.92,
        "peak_ratio_scale": 0.52,
        "peak_ms": 68,
        "release_scale": 1.10,
        "burst_window": 0.32,
        "burst_duck_ratio_scale": 0.78,
        "burst_peak_ratio_scale": 0.42,
        "burst_peak_ms": 40,
        "burst_release_scale": 1.26,
        "burst_hold_scale": 1.12,
    },
    "machine_gun": {
        "default_mute_duration": 0.22,
        "duck_ratio_scale": 0.58,
        "peak_ratio_scale": 0.26,
        "peak_ms": 30,
        "release_scale": 1.48,
        "burst_window": 0.16,
        "burst_duck_ratio_scale": 0.38,
        "burst_peak_ratio_scale": 0.18,
        "burst_peak_ms": 18,
        "burst_release_scale": 2.20,
        "burst_hold_scale": 1.50,
    },
    "special": {
        "default_mute_duration": 0.35,
        "duck_ratio_scale": 0.96,
        "peak_ratio_scale": 0.50,
        "peak_ms": 70,
        "release_scale": 1.12,
        "burst_window": 0.40,
        "burst_duck_ratio_scale": 0.84,
        "burst_peak_ratio_scale": 0.42,
        "burst_peak_ms": 42,
        "burst_release_scale": 1.26,
        "burst_hold_scale": 1.10,
    },
}


#: 去抖闸门 = 射击周期 × 这个数（2026-09-17 先给全自动，同日晚上推到 35 把）。
#: ⭐ 这道闸原本是给「半自动极限连点」去抖的；可半自动的周期同样由游戏钉死 ——
#: 玩家点得再快，两发之间也不会短于 cycletime。所以「拦掉两发间隔 < 周期一半的那一包」
#: 永远只拦重报，不拦真开的枪；而手填的闸门（Tec-9 0.09 / 沙鹰 0.18）离周期只差
#: 30~45ms，真实 GSI 包间隔 P5 62ms / P25 100ms / P50 126ms 的抖动足够吃掉一发。
#: 隔壁会话拿 2026-03 两份真实对局日志过旧步枪闸门 0.09s：**AK 白丢 15%**；
#: 改成周期 × 0.5 拿回 12 个点。⚠ 竞品一道闸都没有、实际效果可以 —— 闸门宁低勿高。
FULL_AUTO_GATE_SCALE = 0.5

#: 闸门的绝对上限（秒）。⭐⭐⭐ 它把「周期填错」从缺陷降级成无害（RN-655）：
#: 跨包的两次递减至少隔一个包间隔（实测 P5 62ms），同包重报由 `fired_this_frame` 拦 ⇒
#: 闸门低于 62ms 就永远拦不到真开的枪。⛔ 不许抬到 62ms 以上。
GATE_CEILING_SECONDS = 0.060

#: 一包里最多按几发处理（包间隔 P50 126ms ÷ 快枪周期 70ms ≈ 1.8 发/包）。
#: 超过它就不是「打了这么多发」而是账本对不上 ⇒ 只重记不出声（RN-655）。
MAX_SHOTS_PER_PACKET = 3

#: 包在队列里躺超过这么久就不再为它出声（账本照常更新）。0.5s ≈ 四个包都没轮到我，
#: 正常抖动碰不到；而队列 100 深，一次卡顿能攒出十几秒积压（RN-655）。
STALE_PACKET_SECONDS = 0.5

#: 全自动枪扫射时的压声形状（`is_burst` 分支），三个数覆盖族默认：
#:  · `burst_window` 0.30 —— GSI 包间隔 P50 就有 126ms、尾部更长，族默认 0.16~0.20
#:    会把同一梭子的相邻两包判成「两次单发」，每包都走一遍深压 + 峰值 ⇒ 抽吸感。
#:    两发隔 300ms 对全自动枪来说仍是同一次扣扳机（点射也算），一律按扫射处理。
#:  · `burst_duck_ratio_scale` / `burst_peak_ratio_scale` 1.10 —— **原声留 ~20%
#:    当节奏骨架，且不再逐包下探**（峰值 = 持续 ⇒ 平的）。竞品实测好用的机制正是
#:    这一条：它每包把游戏音量钉在 20%，500ms 的淡回永远走不完；自定义枪声（100%）
#:    盖在原声扫射（20%）之上，**原声的逐发节奏把「一包一发」漏掉的那几发补齐了**。
#:    我方旧值把步枪扫射压到 8.6%、机枪 6.8%，正好把骨架一起抹掉。
#:    ⚠ 这是「能解释竞品观测」的假设，不是本机实测；进游戏 A/B 的第一个变量就是它
#:    （`M7_进游戏验证清单.md`）。数值随「原声保留」滑块走：默认 18% × 1.10 ≈ 20%。
_FULL_AUTO_BURST = {
    "burst_window": 0.30,
    "burst_duck_ratio_scale": 1.10,
    "burst_peak_ratio_scale": 1.10,
}


def _profile(
    gun_type: str,
    display_name: str,
    family: str,
    *,
    fire_period: float,
    automatic: bool = False,
    gsi_names: tuple[str, ...] | None = None,
    **overrides,
) -> GunSoundProfile:
    """`fire_period` = CS2 的 cycletime（秒），35 把都要给；闸门从它算，不接受手填。"""
    if not fire_period or fire_period <= 0:
        raise ValueError(f"{gun_type}: 每把枪都要给游戏的射击周期 fire_period")
    settings = dict(_FAMILY_DEFAULTS[family])
    if automatic:
        settings.update(_FULL_AUTO_BURST)
    settings["fire_period"] = float(fire_period)
    settings["automatic"] = bool(automatic)
    min_fire_interval = min(
        round(float(fire_period) * FULL_AUTO_GATE_SCALE, 3),
        GATE_CEILING_SECONDS,
    )
    settings.update(overrides)
    default_mute_duration = float(settings.pop("default_mute_duration", 0.4))
    return GunSoundProfile(
        gun_type=gun_type,
        display_name=display_name,
        gsi_names=gsi_names or (f"weapon_{gun_type}",),
        style_key=f"{gun_type}_style",
        mute_duration_key=f"{gun_type}_mute_duration",
        duck_ratio_key=f"{gun_type}_duck_ratio",
        legacy_enabled_key=f"{gun_type}_enabled",
        min_fire_interval=float(min_fire_interval),
        default_mute_duration=default_mute_duration,
        **settings,
    )


GUN_SOUND_TAB_GROUPS = (
    ("手枪", ("glock", "usp", "hkp2000", "p250", "fiveseven", "cz75a", "elite", "deagle", "revolver", "tec9")),
    ("冲锋枪", ("mac10", "mp9", "mp7", "ump45", "p90", "bizon", "mp5sd")),
    ("步枪", ("ak47", "m4a1", "m4a1_silencer", "famas", "galilar", "aug", "sg556")),
    ("狙击枪", ("awp", "ssg08", "scar20", "g3sg1")),
    ("霰弹枪", ("nova", "xm1014", "mag7", "sawedoff")),
    ("机枪", ("m249", "negev")),
    ("特殊", ("taser",)),
)


GUN_SOUND_PROFILE_LIST = (
    # 半自动：`fire_period` 同样是 CS2 的 cycletime（60 / RPM）—— 玩家点得再快也快不过它。
    _profile("glock", "Glock-18", "pistol", fire_period=0.150, default_mute_duration=0.20),
    _profile(
        "usp",
        "USP-S",
        "pistol",
        fire_period=0.170,
        gsi_names=("weapon_usp_silencer",),
        default_mute_duration=0.20,
        duck_ratio_scale=0.68,
        peak_ratio_scale=0.36,
        peak_ms=48,
        release_scale=1.22,
        burst_window=0.24,
        burst_duck_ratio_scale=0.50,
        burst_peak_ratio_scale=0.26,
        burst_peak_ms=28,
        burst_release_scale=1.95,
        burst_hold_scale=1.34,
    ),
    _profile("hkp2000", "P2000", "pistol", fire_period=0.170, default_mute_duration=0.20),
    _profile("p250", "P250", "pistol", fire_period=0.150, default_mute_duration=0.20),
    _profile("fiveseven", "Five-SeveN", "pistol", fire_period=0.150, default_mute_duration=0.20),
    _profile("cz75a", "CZ75-Auto", "pistol", fire_period=0.100, automatic=True, default_mute_duration=0.18),
    _profile("elite", "Dual Berettas", "pistol", fire_period=0.120, default_mute_duration=0.18),
    _profile(
        "deagle",
        "Desert Eagle",
        "pistol",
        fire_period=0.224,
        default_mute_duration=0.40,
        duck_ratio_scale=0.74,
        peak_ratio_scale=0.44,
        peak_ms=60,
        release_scale=1.24,
        burst_window=0.30,
        burst_duck_ratio_scale=0.54,
        burst_peak_ratio_scale=0.30,
        burst_peak_ms=40,
        burst_release_scale=1.82,
        burst_hold_scale=1.24,
    ),
    _profile(
        "revolver",
        "R8 Revolver",
        "pistol",
        fire_period=0.300,   # 主火每发要先扣住扳机再击发，两发实际 ≥0.4s；取下界（闸门宁低勿高）
        default_mute_duration=0.40,
        duck_ratio_scale=0.90,
        peak_ratio_scale=0.52,
        peak_ms=70,
        release_scale=1.20,
        burst_window=0.34,
        burst_duck_ratio_scale=0.76,
        burst_peak_ratio_scale=0.44,
        burst_peak_ms=48,
        burst_release_scale=1.38,
        burst_hold_scale=1.12,
    ),
    _profile("tec9", "Tec-9", "pistol", fire_period=0.120, default_mute_duration=0.20),
    # 全自动：`fire_period` = CS2 的射击周期（60 / RPM），闸门由它算出。
    _profile("mac10", "MAC-10", "smg", fire_period=0.075, automatic=True),         # 800 RPM
    _profile("mp9", "MP9", "smg", fire_period=0.070, automatic=True),              # 857 RPM
    _profile("mp7", "MP7", "smg", fire_period=0.080, automatic=True),              # 750 RPM
    _profile("ump45", "UMP-45", "smg", fire_period=0.090, automatic=True),         # 666 RPM
    _profile("p90", "P90", "smg", fire_period=0.070, automatic=True, default_mute_duration=0.22),
    _profile("bizon", "PP-Bizon", "smg", fire_period=0.080, automatic=True, default_mute_duration=0.22),
    _profile("mp5sd", "MP5-SD", "smg", fire_period=0.080, automatic=True),         # 750 RPM
    _profile("ak47", "AK-47", "rifle", fire_period=0.100, automatic=True),         # 600 RPM
    _profile("m4a1", "M4A4", "rifle", fire_period=0.090, automatic=True),          # 666 RPM
    _profile("m4a1_silencer", "M4A1-S", "rifle", fire_period=0.100, automatic=True),
    _profile("famas", "FAMAS", "rifle", fire_period=0.090, automatic=True),        # 666 RPM
    _profile("galilar", "Galil AR", "rifle", fire_period=0.090, automatic=True),   # 666 RPM
    _profile("aug", "AUG", "rifle", fire_period=0.100, automatic=True),            # 600 RPM
    _profile("sg556", "SG 553", "rifle", fire_period=0.110, automatic=True),       # 545 RPM
    _profile(
        "awp",
        "AWP",
        "special",
        fire_period=1.463,
        default_mute_duration=0.50,
        duck_ratio_scale=1.00,
        peak_ratio_scale=0.54,
        peak_ms=78,
        release_scale=1.05,
        burst_window=0.34,
        burst_duck_ratio_scale=0.92,
        burst_peak_ratio_scale=0.46,
        burst_peak_ms=54,
        burst_release_scale=1.18,
        burst_hold_scale=1.10,
    ),
    _profile(
        "ssg08",
        "SSG 08",
        "special",
        fire_period=1.250,
        default_mute_duration=0.40,
        duck_ratio_scale=0.96,
        peak_ratio_scale=0.54,
        peak_ms=82,
        release_scale=1.08,
        burst_window=0.36,
        burst_duck_ratio_scale=0.88,
        burst_peak_ratio_scale=0.46,
        burst_peak_ms=58,
        burst_release_scale=1.20,
        burst_hold_scale=1.10,
    ),
    _profile(
        "scar20",
        "SCAR-20",
        "rifle",
        fire_period=0.250,
        default_mute_duration=0.40,
        duck_ratio_scale=0.68,
        peak_ratio_scale=0.34,
        peak_ms=44,
        release_scale=1.30,
        burst_window=0.26,
        burst_duck_ratio_scale=0.48,
        burst_peak_ratio_scale=0.24,
        burst_peak_ms=24,
        burst_release_scale=2.00,
        burst_hold_scale=1.36,
    ),
    _profile(
        "g3sg1",
        "G3SG1",
        "rifle",
        fire_period=0.250,
        default_mute_duration=0.40,
        duck_ratio_scale=0.68,
        peak_ratio_scale=0.34,
        peak_ms=44,
        release_scale=1.30,
        burst_window=0.26,
        burst_duck_ratio_scale=0.48,
        burst_peak_ratio_scale=0.24,
        burst_peak_ms=24,
        burst_release_scale=2.00,
        burst_hold_scale=1.36,
    ),
    _profile(
        "nova",
        "Nova",
        "shotgun",
        fire_period=0.882,
        default_mute_duration=0.30,
        duck_ratio_scale=0.94,
        peak_ratio_scale=0.52,
        peak_ms=72,
        release_scale=1.08,
        burst_window=0.34,
        burst_duck_ratio_scale=0.82,
        burst_peak_ratio_scale=0.42,
        burst_peak_ms=46,
        burst_release_scale=1.22,
        burst_hold_scale=1.10,
    ),
    _profile("xm1014", "XM1014", "shotgun", fire_period=0.350, default_mute_duration=0.24),
    _profile(
        "mag7",
        "MAG-7",
        "shotgun",
        fire_period=0.850,
        default_mute_duration=0.30,
        duck_ratio_scale=0.90,
        peak_ratio_scale=0.50,
        peak_ms=60,
        release_scale=1.10,
        burst_window=0.30,
        burst_duck_ratio_scale=0.76,
        burst_peak_ratio_scale=0.40,
        burst_peak_ms=36,
        burst_release_scale=1.30,
        burst_hold_scale=1.15,
    ),
    _profile(
        "sawedoff",
        "Sawed-Off",
        "shotgun",
        fire_period=0.850,
        default_mute_duration=0.30,
        duck_ratio_scale=0.90,
        peak_ratio_scale=0.50,
        peak_ms=60,
        release_scale=1.10,
        burst_window=0.30,
        burst_duck_ratio_scale=0.76,
        burst_peak_ratio_scale=0.40,
        burst_peak_ms=36,
        burst_release_scale=1.30,
        burst_hold_scale=1.15,
    ),
    _profile("m249", "M249", "machine_gun", fire_period=0.080, automatic=True),    # 750 RPM
    _profile("negev", "Negev", "machine_gun", fire_period=0.075, automatic=True),  # 800 RPM
    _profile("taser", "Zeus x27", "special", fire_period=0.800, gsi_names=("weapon_taser",)),  # 单发后充能，取下界
)

GUN_SOUND_PROFILES = {profile.gun_type: profile for profile in GUN_SOUND_PROFILE_LIST}
GUN_SOUND_WEAPON_TYPES = tuple(profile.gun_type for profile in GUN_SOUND_PROFILE_LIST)
#: 射速由游戏钉死的那些枪（`fire_period > 0`）—— 闸门与压声形状按扫射处理。
AUTOMATIC_GUN_TYPES = tuple(
    profile.gun_type for profile in GUN_SOUND_PROFILE_LIST if profile.automatic
)
SEMI_AUTO_GUN_TYPES = tuple(
    profile.gun_type for profile in GUN_SOUND_PROFILE_LIST if not profile.automatic
)
#: ⚠ 这张名单从仓库首个提交起写死了 17 把全自动枪，**上方无一字解释，536 个提交没人回头看**
#: （RN-254 → RN-432）。2026-09-17 查实（隔壁会话考古 + 本机复核）：**排除没有技术原因** ——
#: 2.0 重构把档案扩到 35 把、七个页签写好、六族连发参数调好之后，用它把运行期集合
#: 收回到前身版本（2025-11，10 把半自动）已经发过货的那一档。真实对局 GSI 包间隔
#: 与步枪射速同量级（P50 126ms vs AK 100ms），竞品走同一条 `ammo_clip` 递减链路全武器可用。
#: ⇒ 名单**清空**；⛔ 常量名保留（契约快照 `x8_contract.json` 与判据点名它），
#: 它现在只是一个「万一要临时下架某把枪」的开关，默认没有任何一把在里面。
FULL_AUTO_GUN_SOUND_WEAPON_TYPES: tuple[str, ...] = ()
SUPPORTED_GUN_SOUND_PROFILE_LIST = tuple(
    profile
    for profile in GUN_SOUND_PROFILE_LIST
    if profile.gun_type not in FULL_AUTO_GUN_SOUND_WEAPON_TYPES
)
SUPPORTED_GUN_SOUND_PROFILES = {
    profile.gun_type: profile for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST
}
SUPPORTED_GUN_SOUND_WEAPON_TYPES = tuple(
    profile.gun_type for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST
)
SUPPORTED_GUN_SOUND_TAB_GROUPS = tuple(
    (
        tab_name,
        tuple(
            weapon_type
            for weapon_type in weapon_types
            if weapon_type in SUPPORTED_GUN_SOUND_WEAPON_TYPES
        ),
    )
    for tab_name, weapon_types in GUN_SOUND_TAB_GROUPS
    if any(weapon_type in SUPPORTED_GUN_SOUND_WEAPON_TYPES for weapon_type in weapon_types)
)
LEGACY_GUN_SOUND_ENABLED_KEYS = tuple(profile.legacy_enabled_key for profile in GUN_SOUND_PROFILE_LIST)


def resolve_gun_sound_style(style) -> str:
    if isinstance(style, dict):
        if style.get("enabled") is False:
            return "0"
        style = style.get("style", "0")
    if style is None:
        return "0"
    normalized = str(style).strip()
    if normalized.lower() in DISABLED_GUN_SOUND_STYLES:
        return "0"
    return normalized


def gun_sound_style_enabled(style) -> bool:
    return resolve_gun_sound_style(style).lower() not in DISABLED_GUN_SOUND_STYLES


def is_gun_sound_master_enabled(cfg) -> bool:
    if bool(getattr(cfg, "gun_sound_enabled", False)):
        return True
    return any(bool(getattr(cfg, key, False)) for key in LEGACY_GUN_SOUND_ENABLED_KEYS)


def sync_legacy_gun_sound_flags(cfg) -> bool:
    enabled = bool(getattr(cfg, "gun_sound_enabled", False))
    changed = False
    for key in LEGACY_GUN_SOUND_ENABLED_KEYS:
        if getattr(cfg, key, False) != enabled:
            setattr(cfg, key, enabled)
            changed = True
    return changed


def _clamp_ratio(value: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.18
    return max(0.0, min(1.0, numeric))


def _clamp_time_ms(value: float) -> int:
    try:
        numeric = int(float(value))
    except Exception:
        numeric = 120
    return max(0, min(2000, numeric))


def is_gun_sound_burst(profile: GunSoundProfile, shot_interval: float | None) -> bool:
    if shot_interval is None:
        return False
    try:
        normalized = float(shot_interval)
    except Exception:
        return False
    if normalized <= 0:
        return False
    return normalized <= profile.burst_window


def build_gun_sound_duck_plan(
    cfg,
    profile: GunSoundProfile,
    *,
    is_burst: bool,
    hold_duration: float | None = None,
) -> GunSoundDuckPlan:
    base_ratio = _clamp_ratio(
        getattr(
            cfg,
            profile.duck_ratio_key,
            getattr(cfg, "gun_sound_duck_ratio", profile.default_duck_ratio),
        )
    )
    base_release_ms = _clamp_time_ms(getattr(cfg, "gun_sound_duck_release_ms", 120))

    sustain_scale = profile.burst_duck_ratio_scale if is_burst else profile.duck_ratio_scale
    peak_scale = profile.burst_peak_ratio_scale if is_burst else profile.peak_ratio_scale
    release_scale = profile.burst_release_scale if is_burst else profile.release_scale
    peak_ms = profile.burst_peak_ms if is_burst else profile.peak_ms

    sustain_ratio = _clamp_ratio(base_ratio * sustain_scale)
    peak_ratio = min(sustain_ratio, _clamp_ratio(base_ratio * peak_scale))
    release_ms = _clamp_time_ms(base_release_ms * release_scale)

    try:
        resolved_hold = float(
            hold_duration
            if hold_duration is not None
            else getattr(cfg, profile.mute_duration_key, profile.default_mute_duration)
        )
    except Exception:
        resolved_hold = profile.default_mute_duration
    resolved_hold = max(0.0, resolved_hold)
    if is_burst:
        resolved_hold = max(resolved_hold, resolved_hold * profile.burst_hold_scale)

    return GunSoundDuckPlan(
        sustain_ratio=sustain_ratio,
        peak_ratio=peak_ratio,
        peak_ms=max(0, int(peak_ms)),
        hold_duration=resolved_hold,
        release_ms=release_ms,
        is_burst=is_burst,
    )
