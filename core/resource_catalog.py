"""Unified resource catalog for audio/visual asset roots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
KILL_ICON_EXTENSIONS = IMAGE_EXTENSIONS + (".json",)
CROSSHAIR_EXTENSIONS = (".xchr", ".json")


@dataclass(frozen=True)
class ResourceSpec:
    key: str
    label: str
    target_rel_root: str
    domain: str
    extensions: tuple[str, ...]
    aliases: tuple[str, ...] = ()

    @property
    def root_name(self) -> str:
        return self.target_rel_root.replace("\\", "/").split("/")[-1]


RESOURCE_SPECS: tuple[ResourceSpec, ...] = (
    ResourceSpec("kill_sounds", "击杀音效", "audio/kill_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS),
    ResourceSpec("kill_voices", "击杀语音", "audio/kill_voices", "audio", DEFAULT_AUDIO_EXTENSIONS),
    ResourceSpec("weapon_kill_sounds", "武器击杀音效", "audio/weapon_kill_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS),
    ResourceSpec("weapon_kill_voices", "武器击杀语音", "audio/weapon_kill_voices", "audio", DEFAULT_AUDIO_EXTENSIONS),
    ResourceSpec("death", "被击杀音效", "audio/death", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("death_sound",)),
    ResourceSpec("switch_weapons", "切枪音效", "audio/switch_weapons", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("switch_weapon", "switch_sounds")),
    ResourceSpec("reload_sounds", "换弹音效", "audio/reload_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("reload_sound",)),
    ResourceSpec("grenade_sounds", "投掷物音效", "audio/grenade_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("grenade_sound",)),
    ResourceSpec("c4_sounds", "C4 音效", "audio/c4_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("c4_sound",)),
    ResourceSpec("health_warning", "血量警告", "audio/health_warning", "audio", DEFAULT_AUDIO_EXTENSIONS),
    ResourceSpec("round_sounds", "回合音效", "audio/round_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("round_sound",)),
    ResourceSpec("gun_sounds", "枪声替换", "audio/gun_sounds", "audio", DEFAULT_AUDIO_EXTENSIONS, aliases=("gun_sound",)),
    ResourceSpec("flash_images", "闪光图片", "flash_images", "visual", IMAGE_EXTENSIONS),
    ResourceSpec("flash_audio", "闪光音频", "flash_audio", "visual", DEFAULT_AUDIO_EXTENSIONS),
    ResourceSpec("kill_icons", "击杀图标", "kill_icons", "visual", KILL_ICON_EXTENSIONS),
    ResourceSpec("utility_guides", "道具瞄点", "utility_guides", "visual", IMAGE_EXTENSIONS),
    ResourceSpec("crosshair", "准心文件", "crosshair", "visual", CROSSHAIR_EXTENSIONS),
)


def iter_resource_specs(domains: Sequence[str] | None = None) -> List[ResourceSpec]:
    if not domains:
        return list(RESOURCE_SPECS)
    normalized = {str(domain or "").strip().lower() for domain in domains if str(domain or "").strip()}
    return [spec for spec in RESOURCE_SPECS if spec.domain in normalized]


def resolve_import_domain(value: str | None) -> tuple[str, ...]:
    key = str(value or "audio").strip().lower()
    if key == "all":
        return ("audio", "visual")
    if key == "visual":
        return ("visual",)
    return ("audio",)


def build_spec_lookup(domains: Sequence[str] | None = None) -> dict[str, ResourceSpec]:
    lookup: dict[str, ResourceSpec] = {}
    for spec in iter_resource_specs(domains=domains):
        lookup[spec.key.lower()] = spec
        lookup[spec.root_name.lower()] = spec
        for alias in spec.aliases:
            lookup[str(alias).strip().lower()] = spec
    return lookup


def get_resource_spec(key: str) -> ResourceSpec | None:
    lookup = build_spec_lookup()
    return lookup.get(str(key or "").strip().lower())

