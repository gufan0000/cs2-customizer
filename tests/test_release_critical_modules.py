# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-003：新功能链路上线了，打包关键模块清单要跟着走。

`build_release.CRITICAL_ARCHIVE_MODULES` 是发布产物的**最后一道守门**：
打包完之后翻 PyInstaller 归档，清单里的模块一个查不到就当场炸。

**它烂掉的方式很安静**：清单从 2.1.3 起就没动过，而 2.2.4 最大的新功能
——击杀图标一整条链路——**一个模块都不在册**。真漏了的话，
`verify_onefile_archive` 照样通过、安装包照样出得来，用户装上之后那个功能是死的，
**发布链路全程不报一声**。

⇒ 这条判据做成**棘轮**：页面直接依赖的每一个本仓链路根，
要么在清单里，要么在下面 `KNOWN_UNLISTED` 里带着理由挂账。
**新加一条链路而两边都没登记，判据就红** —— 逼人做一次决定，
而不是像 RN-003 那样悄悄躺一年。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build_tools"))

REPO = Path(__file__).resolve().parent.parent

#: 击杀图标链路——RN-003 补的那一批，**掉了任何一个这条判据都要红**。
KILL_ICON_CHAIN = {
    "kill_icon_overlay", "kill_icon_player",
    "core.kill_icon_import", "core.kill_icon_library", "core.kill_icon_pack",
}

#: 已知不在硬清单里的链路根，**每条都要写清为什么**。
#: 共同理由：它们都由 `main_widget` / `gui_widget` 在模块层静态 import，
#: PyInstaller 的静态图必然收得进去；硬清单留给"曾经漏过"和"新上线"的那些。
#: ⚠ 往这里加东西之前先问一句：**它是不是也可能悄悄掉？**
KNOWN_UNLISTED = {
    "cfg_utils", "config", "core.audio", "core.cfg_compiler",
    "core.config_snapshot_manager", "core.crosshair_reset", "core.diagnostics",
    "core.fun", "core.gun_sound_profiles", "core.hotkeys", "core.hud",
    "core.io_validation", "core.magnifier_sensitivity", "core.presets",
    "core.resource_health", "core.resource_import_wizard", "core.runtime",
    # 批 48（RN-508）：内部记号 → 用户看得懂的话的词表。
    # `audio_replay_page` 在**模块层** `from core.audio_event_text import ...`
    # ⇒ 打包必然收，不需要进 CRITICAL_ARCHIVE_MODULES。
    # ⚠ 另一份 `core.health_report_text` **不进这张表**：页面不直接 import 它
    #   （走 `core.resource_health` 转手），它不是链路根 —— 反向断言当场点名。
    "core.audio_event_text",
    "core.usage_reporter", "core.utils", "crosshair_overlay",
    # ⚠ `gsi_handler_music` 在批 33 从这张表里**摘掉了**，不是因为它变危险了，
    #   而是因为它**不再是页面链路根**：RN-454 撤掉音乐页那颗子开关时，
    #   页面里唯一那句 `from gsi_handler_music import ...` 跟着走了，
    #   恢复联动态的动作搬到了 `gui_widget._on_switch_changed`。
    #   它仍由 `main_widget:1301` 模块层 import ⇒ 打包照收。
    #   ⭐ **一次「把动作搬到正确的开关上」，顺带改变了另一张表的成员资格** ——
     #  而逮到它的是「挂账表不许留已经不是链路根的模块」那条反向判据。
    "flash_process_manager", "gsi_handler_utility",
    "music_player", "page_theme_helper", "screen_effect_overlay",
    # ⚠ 2026-08-21（RN-153）：`service_urls` **又从页面链上下来了**。
    # 那道「开源版没有社区站」的守卫从 kill_icon 页搬进了
    # `widgets/community_library`（八个页面要共用同一张地址表，
    # 同一道守卫散成 N 份就是 N 个会漏的地方）——
    # 于是 pages/ 底下再没有人直接 import 它，挂账表里留着就成了腐烂条目。
    # ⭐ 这条一来一回正好说明**挂账表必须有"不许留死条目"的反面守卫**：
    # 加进来容易，没人会想起来摘。
    "theme_manager", "ui_design_system", "ui_help_panel",
    "ui_osd", "ui_style_applier", "ui_toast", "voice_output_manager",
}


def _local_top_level() -> set[str]:
    return {p.stem for p in REPO.glob("*.py")}


def _page_chain_roots() -> set[str]:
    """页面**直接** import 的本仓模块，收敛到"链路根"这一层。

    `core.audio.audio_manager` → `core.audio`；顶层模块保持原样。
    """
    local = _local_top_level()
    roots: set[str] = set()
    for path in sorted((REPO / "pages").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                head = name.split(".")[0]
                if head == "core":
                    roots.add(".".join(name.split(".")[:2]))
                elif head in local:
                    roots.add(head)
    return roots


def _critical() -> list[str]:
    from build_release import CRITICAL_ARCHIVE_MODULES
    return list(CRITICAL_ARCHIVE_MODULES)


def test_the_extractor_actually_sees_the_pages():
    """空转守卫：认不出页面依赖，下面那条棘轮就永远绿。"""
    roots = _page_chain_roots()
    assert len(roots) >= 30, (
        f"只认出 {len(roots)} 个链路根（2026-08-18 实测 42）——"
        "抽取器多半瞎了，下面的棘轮在空转。")


def test_the_kill_icon_chain_is_registered():
    """RN-003 本体：击杀图标那五个模块必须在硬清单里。"""
    missing = sorted(KILL_ICON_CHAIN - set(_critical()))
    assert not missing, (
        f"击杀图标链路又不在打包关键模块清单里了：{missing}\n"
        "漏打包不会报错——安装包照样出得来，用户装上之后这个功能是死的。")


def test_every_page_chain_root_is_either_guarded_or_written_off():
    """棘轮：新链路上线必须做一次决定，不许无声无息地不在册。"""
    known = set(_critical()) | KNOWN_UNLISTED
    unaccounted = sorted(_page_chain_roots() - known)
    assert not unaccounted, (
        "这些链路根既不在 CRITICAL_ARCHIVE_MODULES，也没在 KNOWN_UNLISTED 里挂账：\n"
        + "\n".join(f"  {m}" for m in unaccounted)
        + "\n\n二选一：\n"
        "  · 它可能被打包漏掉（懒加载 / 只在函数里 import / 靠字符串找）"
        "⇒ 加进 CRITICAL_ARCHIVE_MODULES；\n"
        "  · 它由 main_widget/gui_widget 静态 import、必然进包"
        "⇒ 加进 KNOWN_UNLISTED **并写明理由**。\n"
        "RN-003 就是这一格空着的时候，击杀图标整条链路躺了一年没人发现。")


def test_the_write_off_list_does_not_rot():
    """挂账表里不许留已经不存在的模块——那是另一种腐烂。"""
    stale = sorted(KNOWN_UNLISTED - _page_chain_roots())
    assert not stale, (
        f"KNOWN_UNLISTED 里这些模块页面已经不 import 了，删掉：{stale}")
