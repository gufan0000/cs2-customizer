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


def _profile(
    gun_type: str,
    display_name: str,
    family: str,
    min_fire_interval: float,
    *,
    gsi_names: tuple[str, ...] | None = None,
    **overrides,
) -> GunSoundProfile:
    settings = dict(_FAMILY_DEFAULTS[family])
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
    _profile("glock", "Glock-18", "pistol", 0.10, default_mute_duration=0.20),
    _profile(
        "usp",
        "USP-S",
        "pistol",
        0.10,
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
    _profile("hkp2000", "P2000", "pistol", 0.10, default_mute_duration=0.20),
    _profile("p250", "P250", "pistol", 0.09, default_mute_duration=0.20),
    _profile("fiveseven", "Five-SeveN", "pistol", 0.09, default_mute_duration=0.20),
    _profile("cz75a", "CZ75-Auto", "pistol", 0.08, default_mute_duration=0.18),
    _profile("elite", "Dual Berettas", "pistol", 0.08, default_mute_duration=0.18),
    _profile(
        "deagle",
        "Desert Eagle",
        "pistol",
        0.18,
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
        0.35,
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
    _profile("tec9", "Tec-9", "pistol", 0.09, default_mute_duration=0.20),
    _profile("mac10", "MAC-10", "smg", 0.07),
    _profile("mp9", "MP9", "smg", 0.07),
    _profile("mp7", "MP7", "smg", 0.07),
    _profile("ump45", "UMP-45", "smg", 0.08),
    _profile("p90", "P90", "smg", 0.06, default_mute_duration=0.22),
    _profile("bizon", "PP-Bizon", "smg", 0.06, default_mute_duration=0.22),
    _profile("mp5sd", "MP5-SD", "smg", 0.07),
    _profile("ak47", "AK-47", "rifle", 0.09),
    _profile("m4a1", "M4A4", "rifle", 0.09),
    _profile("m4a1_silencer", "M4A1-S", "rifle", 0.09),
    _profile("famas", "FAMAS", "rifle", 0.09),
    _profile("galilar", "Galil AR", "rifle", 0.09),
    _profile("aug", "AUG", "rifle", 0.09),
    _profile("sg556", "SG 553", "rifle", 0.09),
    _profile(
        "awp",
        "AWP",
        "special",
        0.75,
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
        0.90,
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
        0.12,
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
        0.12,
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
        0.80,
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
    _profile("xm1014", "XM1014", "shotgun", 0.24, default_mute_duration=0.24),
    _profile(
        "mag7",
        "MAG-7",
        "shotgun",
        0.45,
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
        0.45,
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
    _profile("m249", "M249", "machine_gun", 0.06),
    _profile("negev", "Negev", "machine_gun", 0.05),
    _profile("taser", "Zeus x27", "special", 0.80, gsi_names=("weapon_taser",)),
)

GUN_SOUND_PROFILES = {profile.gun_type: profile for profile in GUN_SOUND_PROFILE_LIST}
GUN_SOUND_WEAPON_TYPES = tuple(profile.gun_type for profile in GUN_SOUND_PROFILE_LIST)
FULL_AUTO_GUN_SOUND_WEAPON_TYPES = (
    "cz75a",
    "mac10",
    "mp9",
    "mp7",
    "ump45",
    "p90",
    "bizon",
    "mp5sd",
    "ak47",
    "m4a1",
    "m4a1_silencer",
    "famas",
    "galilar",
    "aug",
    "sg556",
    "m249",
    "negev",
)
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
