# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import ast
from pathlib import Path

import ui_help_panel

REPO = Path(__file__).resolve().parent.parent


def test_help_texts_are_defined_exactly_once():
    """`PAGE_HELP_TEXTS` 只许有一处定义，且不许再拿 `.update()` 往上叠（RN-001）。

    原先是「先定义 16 键、再 `.update()` 23 键」两块，而后者把前者的 16 键
    **逐条全覆盖** —— 那 237 行文案从写下那天起就没被读到过一次。
    没人发现，是因为**下面那条判据查的是最终字典**：两块并存时它照样绿。
    改文案的人还会挑到上面那块去改，改完当然"没生效"。

    这条判据换个角度问：**源码里有几处在往这个表里塞东西**。
    """
    src = (REPO / "ui_help_panel.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    defs, updates = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE_HELP_TEXTS" for t in node.targets):
            defs.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("update", "setdefault") \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "PAGE_HELP_TEXTS":
            updates.append(node.lineno)

    assert len(defs) == 1, (
        f"PAGE_HELP_TEXTS 有 {len(defs)} 处定义（行 {defs}）——"
        "后一处会把前一处整块盖掉，前面那些文案就成了没人读得到的死文字")
    assert not updates, (
        f"有人又用 .update()/.setdefault() 往 PAGE_HELP_TEXTS 上叠（行 {updates}）。"
        "要改文案就直接改那唯一一份定义 —— 叠加会让同一个键出现两份，"
        "改了上面那份的人会发现「怎么改了没生效」")


def test_help_texts_explain_resource_or_config_locations():
    expected_markers = {
        "basic": ["AppData/Local/CS2Customizer/config.json", "AppData/Local/CS2Customizer/resources/"],
        "advanced": ["AppData/Local/CS2Customizer/config.json", "gamestate_integration_cs2customizer.cfg"],
        "crosshair": ["AppData/Local/CS2Customizer/resources/crosshair/", ".xchr"],
        "kill_sound": ["resources/audio/kill_sounds/风格名/", "resources/audio/weapon_kill_sounds/武器名/风格名/"],
        "kill_voice": ["resources/audio/kill_voices/风格名/", "resources/audio/weapon_kill_voices/武器名/风格名/"],
        "kill_icon": ["AppData/Local/CS2Customizer/resources/kill_icons/风格名/", "1.png + 1.json"],
        "death_sound": ["AppData/Local/CS2Customizer/resources/audio/death/", "按文件名识别风格"],
        "gun_sound": ["resources/audio/gun_sounds/武器名/风格名/"],
        "switch_weapon": ["resources/audio/switch_weapons/武器名/风格名/"],
        "reload_sound": ["resources/audio/reload_sounds/武器名/风格名/"],
        "special_sound": ["resources/audio/", "round_sounds/start/风格名/start.mp3"],
        "viewmodel": ["AppData/Local/CS2Customizer/config.json", "CS2/game/csgo/cfg/cs2customizer.cfg"],
        "magnifier": ["AppData/Local/CS2Customizer/config.json", "cs2customizer_magnifier_runtime.cfg"],
        "flash": ["resources/flash_images/风格名/", "resources/flash_audio/风格名/"],
        "music": ["无需放到软件固定目录", "AppData/Local/CS2Customizer/config.json"],
        "voice_output": ["无需固定素材目录", "AppData/Local/CS2Customizer/voice_output_config.json"],
        "utility": ["AppData/Local/CS2Customizer/resources/utility_guides/", "道具名_站位"],
        "hud_color": ["AppData/Local/CS2Customizer/config.json", "cs2customizer_hud_runtime.cfg"],
    }

    for key, markers in expected_markers.items():
        text = ui_help_panel.PAGE_HELP_TEXTS[key]
        for marker in markers:
            assert marker in text, f"{key} help text missing marker: {marker}"
