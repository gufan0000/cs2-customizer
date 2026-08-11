# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R9-D（UP-057 第二阶段）：四个武器音效页的建页骨架上提到基类。

**这一轮最该防的错，我自己先犯了一次**：把 `kill_voice` 的 `TEST_LEVELS`
漏写成 None，于是那一页 36 个连杀档位按钮凭空消失。单元测试全绿、ruff 全绿，
是**页面指纹**（558 → 522 个控件）把它逮住的。所以下面既有"结构没退化"的判据，
也有一条直接盯住每页参数取值的判据——参数写错不会报错，只会静静少一批控件。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAGES = REPO / "pages"

WEAPON_PAGES = {
    "kill_sound_page.py": "KillSoundPage",
    "kill_voice_page.py": "KillVoicePage",
    "switch_weapon_page.py": "SwitchWeaponPage",
    "reload_sound_page.py": "ReloadSoundPage",
}

HOOKS = ("_weapon_styles", "_configured_style", "_style_options_for", "_test_weapon")


def _class_methods(fname: str, clsname: str) -> set[str]:
    tree = ast.parse((PAGES / fname).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == clsname:
            return {
                item.name for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"{fname} 里找不到类 {clsname}")


@pytest.mark.parametrize("fname,clsname", sorted(WEAPON_PAGES.items()))
def test_pages_do_not_reimplement_the_shared_skeleton(fname, clsname):
    """四页都不许再自己写 `_create_category_tab`——它已经在基类里。

    回退验证：把任一页的实现粘回去，本条立刻变红。
    """
    methods = _class_methods(fname, clsname)
    assert "_create_category_tab" not in methods, (
        f"{fname} 又自己实现了 _create_category_tab，应当用基类的那份"
    )


@pytest.mark.parametrize("fname,clsname", sorted(WEAPON_PAGES.items()))
def test_pages_implement_every_hook(fname, clsname):
    """基类留的四个钩子，每页都得实现——漏一个就是运行时 NotImplementedError。"""
    methods = _class_methods(fname, clsname)
    missing = [h for h in HOOKS if h not in methods]
    assert not missing, f"{fname} 少实现了钩子：{missing}"


def test_only_the_two_kill_pages_offer_kill_streak_levels():
    """连杀档位试听只有击杀音效 / 击杀语音两页有——这是我上面说的那个坑。

    `TEST_LEVELS` 写错不会抛异常，只会让页面少掉一批按钮。这条把四页的取值钉死。
    回退验证：把 kill_voice 的 TEST_LEVELS 删掉，本条立刻变红。
    """
    from pages.kill_sound_page import KillSoundPage
    from pages.kill_voice_page import KillVoicePage
    from pages.reload_sound_page import ReloadSoundPage
    from pages.switch_weapon_page import SwitchWeaponPage

    assert KillSoundPage.TEST_LEVELS == [1, 2, 3, 4, 5]
    assert KillVoicePage.TEST_LEVELS == [1, 2, 3, 4, 5]
    assert SwitchWeaponPage.TEST_LEVELS is None
    assert ReloadSoundPage.TEST_LEVELS is None


def test_style_tools_menu_matches_the_original_shape():
    """底部动作条的「风格工具」形态：击杀两页是下拉菜单，切枪/换弹是单按钮。

    同样是"写错也不报错"的一类参数——菜单变按钮，用户就少了「管理风格」入口。
    """
    from pages.kill_sound_page import KillSoundPage
    from pages.kill_voice_page import KillVoicePage
    from pages.reload_sound_page import ReloadSoundPage
    from pages.switch_weapon_page import SwitchWeaponPage

    assert KillSoundPage.STYLE_TOOLS_MENU is True
    assert KillVoicePage.STYLE_TOOLS_MENU is True
    assert SwitchWeaponPage.STYLE_TOOLS_MENU is False
    assert ReloadSoundPage.STYLE_TOOLS_MENU is False


def test_every_page_declares_its_own_title_and_help_key():
    """标题/副标题/帮助键都进了类属性，不许留空——留空会建出一个没标题的页。"""
    import importlib

    for fname, clsname in WEAPON_PAGES.items():
        module = importlib.import_module(f"pages.{fname[:-3]}")
        cls = getattr(module, clsname)
        assert cls.PAGE_TITLE.strip(), f"{clsname} 没有 PAGE_TITLE"
        assert cls.PAGE_LEAD.strip(), f"{clsname} 没有 PAGE_LEAD"
        assert (cls.HELP_KEY or cls.SOUND_CATEGORY).strip(), f"{clsname} 没有帮助键"


def test_help_keys_all_exist():
    """帮助键必须在 PAGE_HELP_TEXTS 里真有——写错了是建页时 KeyError。"""
    import importlib

    from ui_help_panel import PAGE_HELP_TEXTS

    for fname, clsname in WEAPON_PAGES.items():
        module = importlib.import_module(f"pages.{fname[:-3]}")
        cls = getattr(module, clsname)
        key = cls.HELP_KEY or cls.SOUND_CATEGORY
        assert key in PAGE_HELP_TEXTS, f"{clsname} 的帮助键 {key!r} 不存在"


def test_base_class_hooks_fail_loudly_when_not_overridden():
    """基类的钩子必须是 `raise NotImplementedError`，不能给个"看起来能用"的默认值。

    给默认值的后果是新页面忘了覆盖时**静默拿到错的风格表**，
    比直接炸出来难查得多。
    """
    from pages.sound_page_base import SoundPageBase

    dummy = SoundPageBase()
    for hook in HOOKS:
        with pytest.raises(NotImplementedError):
            getattr(dummy, hook)("weapon_ak47")
