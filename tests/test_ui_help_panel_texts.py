from __future__ import annotations

import ui_help_panel


def test_help_texts_explain_resource_or_config_locations():
    expected_markers = {
        "basic": ["AppData/Local/FanTool/config.json", "AppData/Local/FanTool/resources/"],
        "advanced": ["AppData/Local/FanTool/config.json", "gamestate_integration_fanpai.cfg"],
        "crosshair": ["AppData/Local/FanTool/resources/crosshair/", ".xchr"],
        "kill_sound": ["resources/audio/kill_sounds/风格名/", "resources/audio/weapon_kill_sounds/武器名/风格名/"],
        "kill_voice": ["resources/audio/kill_voices/风格名/", "resources/audio/weapon_kill_voices/武器名/风格名/"],
        "kill_icon": ["AppData/Local/FanTool/resources/kill_icons/风格名/", "1.png + 1.json"],
        "death_sound": ["AppData/Local/FanTool/resources/audio/death/", "按文件名识别风格"],
        "gun_sound": ["resources/audio/gun_sounds/武器名/风格名/"],
        "switch_weapon": ["resources/audio/switch_weapons/武器名/风格名/"],
        "reload_sound": ["resources/audio/reload_sounds/武器名/风格名/"],
        "special_sound": ["resources/audio/", "round_sounds/start/风格名/start.mp3"],
        "viewmodel": ["AppData/Local/FanTool/config.json", "CS2/game/csgo/cfg/fanpai.cfg"],
        "magnifier": ["AppData/Local/FanTool/config.json", "fanpai_magnifier_runtime.cfg"],
        "flash": ["resources/flash_images/风格名/", "resources/flash_audio/风格名/"],
        "music": ["无需放到软件固定目录", "AppData/Local/FanTool/config.json"],
        "voice_output": ["无需固定素材目录", "AppData/Local/FanTool/voice_output_config.json"],
        "utility": ["AppData/Local/FanTool/resources/utility_guides/", "道具名_站位"],
        "hud_color": ["AppData/Local/FanTool/config.json", "fanpai_hud_runtime.cfg"],
    }

    for key, markers in expected_markers.items():
        text = ui_help_panel.PAGE_HELP_TEXTS[key]
        for marker in markers:
            assert marker in text, f"{key} help text missing marker: {marker}"
