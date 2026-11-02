# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""音效页「有内容」的世界（批 146）。

干净配置下素材库是空的：音效页只有一块引导卡，武器板根本不显示，
工装量到的是用户不会长期停留的那张脸（1.25 档「手雷/道具」折行被裁，只有这一档才看得到）。
这里往**干净配置目录**造几个假风格，不碰真实素材。
"""
from __future__ import annotations

import os
import struct
import wave

PAGES = ("kill_sound", "kill_voice", "switch_weapon", "reload_sound",
         "death_sound", "gun_sound", "special_sound")
#: 最后一个专门试省略号：风格名是用户自己起的，长短没有上限。
STYLES = ("雷霆", "冰河", "赛博", "复古街机", "暮光", "一个很长很长的风格名字用来试省略号")
SOME_WEAPONS = ("weapon_ak47", "weapon_m4a1", "weapon_awp", "weapon_glock", "weapon_usp_silencer",
                "weapon_mp9", "weapon_deagle", "weapon_nova", "weapon_negev", "weapon_knife")


#: 枪声页的目录按枪：只造几把，另外几十把是空的，那才是真实的样子。
GUNS = ("ak47", "m4a1", "awp", "glock", "usp", "mp9", "deagle", "nova", "negev")


def _write_wav(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(struct.pack("<h", 0) * 800)


def seed_styles(win, app, config) -> None:
    """造风格、配上几把枪，让 `PAGES` 里建好的页重读一遍。"""
    from core.audio.audio_manager import AudioManager
    from core.audio.special_events import events_in_group
    from resource_manager import ResourceManager

    root = ResourceManager.get_app_data_path("resources/audio")
    for style in STYLES:
        for level in range(1, 6):
            _write_wav(os.path.join(root, "kill_sounds", style, f"{level}.wav"))
            _write_wav(os.path.join(root, "kill_voices", style, f"{level}.wav"))
        for weapon in SOME_WEAPONS:
            _write_wav(os.path.join(root, "switch_weapons", weapon, style, "a.wav"))
            _write_wav(os.path.join(root, "reload_sounds", weapon, style, "a.wav"))
        _write_wav(os.path.join(root, "death", f"{style}.wav"))
        for gun in GUNS:
            _write_wav(os.path.join(root, "gun_sounds", gun, style, "a.wav"))
        for grenade in AudioManager.GRENADE_TYPES:
            _write_wav(os.path.join(root, "grenade_sounds", grenade, style, "a.wav"))
        _write_wav(os.path.join(root, "c4_sounds", style, "a.wav"))
        _write_wav(os.path.join(root, "health_warning", style, "a.wav"))
        for event in events_in_group("round"):
            _write_wav(os.path.join(root, "round_sounds", event.subdir, style, "a.wav"))

    mapping = {weapon: STYLES[index % 3] for index, weapon in enumerate(SOME_WEAPONS)}
    for key in ("weapon_kill_sounds", "weapon_kill_voices", "weapon_switch_sounds", "weapon_reload_sounds"):
        getattr(config, key).update(mapping)
    config.death_sound_style = STYLES[0]
    for index, gun in enumerate(GUNS):
        setattr(config, f"{gun}_style", STYLES[index % 3])
    config.grenade_sound_styles["hegrenade"] = STYLES[0]
    for page_id in PAGES:
        page = win.pages.get(page_id)
        if page is not None:
            page._refresh_style_catalog()
    app.processEvents()
