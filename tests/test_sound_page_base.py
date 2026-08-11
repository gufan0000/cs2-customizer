# -*- coding: utf-8 -*-
"""UP-057 · SoundPageBase 契约回归。

抽基类这类重构最怕的不是"跑不起来"，而是**悄悄改掉了某一页的行为**——
四个页面原本各有一份实现，合并时任何一处细微差异都会变成静默的行为漂移。
所以这里逐条锁住合并前核对过的那些差异点。

结构层面另有 `scripts/page_fingerprint.py` 兜底：重构前后 6 个页面
2472 个控件的类型/名字/文案/几何逐条比对，实测完全一致。
"""
from __future__ import annotations

import inspect

import pytest

CLUSTER = {
    "kill_sound": ("KillSoundPage", "kill_sound"),
    "kill_voice": ("KillVoicePage", "kill_voice"),
    "switch_weapon": ("SwitchWeaponPage", "switch_weapon"),
    "reload_sound": ("ReloadSoundPage", "reload_sound"),
}


def _page_class(module_name: str, cls_name: str):
    import importlib

    return getattr(importlib.import_module(f"pages.{module_name}_page"), cls_name)


@pytest.mark.parametrize("module_name", sorted(CLUSTER))
def test_cluster_pages_inherit_base(module_name):
    from pages.sound_page_base import SoundPageBase

    cls_name, _category = CLUSTER[module_name]
    assert issubclass(_page_class(module_name, cls_name), SoundPageBase)


@pytest.mark.parametrize("module_name", sorted(CLUSTER))
def test_sound_category_is_declared(module_name):
    """基类靠 SOUND_CATEGORY 决定传给 StyleCreatorDialog 的类别。

    忘了声明会退化成空串，对话框拿到空类别 —— 不会抛异常，只会静默建错地方。
    """
    cls_name, category = CLUSTER[module_name]
    assert _page_class(module_name, cls_name).SOUND_CATEGORY == category


@pytest.mark.parametrize("module_name", sorted(CLUSTER))
def test_shared_methods_come_from_base_not_copies(module_name):
    """这五个方法必须只剩基类一份——留着副本等于没抽。"""
    from pages import sound_page_base

    cls_name, _ = CLUSTER[module_name]
    cls = _page_class(module_name, cls_name)
    for name in ("_compact_text", "_open_audio_resource_root",
                 "_on_audio_files_dropped", "_open_style_creator", "showEvent"):
        owner = inspect.getsourcefile(getattr(cls, name))
        assert owner == sound_page_base.__file__, (
            f"{cls_name}.{name} 仍定义在 {owner}，没有真正合并到基类"
        )


def test_compact_text_matches_every_original_call_site():
    """合并前四页的默认值不同（未设置/12 与 未分组/8），必须确认没改到行为。

    核对结论：四页各调一次，**实际参数完全一致**（都是 '未分组', 8），
    只是两页显式传参、两页靠默认值。所以基类取后者那套默认值，行为不变。
    """
    from pages.sound_page_base import SoundPageBase

    compact = SoundPageBase._compact_text
    # 默认值就是原 switch_weapon / reload_sound 的那套
    assert compact("") == "未分组"
    assert compact("一二三四五六七八九") == "一二三四五六七…"
    assert len(compact("一二三四五六七八九")) == 8
    # 显式传参路径（原 kill_sound / kill_voice 的调用形态）结果相同
    assert compact("一二三四五六七八九", "未分组", 8) == "一二三四五六七…"
    assert compact("短", "未分组", 8) == "短"


def test_reload_sound_keeps_its_preselect_weapon():
    """reload_sound 比其余三页多传一个 preselect_weapon，钩子必须留住这个差异。"""
    cls = _page_class("reload_sound", "ReloadSoundPage")
    assert "_style_creator_extra_kwargs" in cls.__dict__, (
        "reload_sound 没有覆盖钩子，preselect_weapon 会在合并中丢失"
    )
    src = inspect.getsource(cls._style_creator_extra_kwargs)
    assert "preselect_weapon" in src


@pytest.mark.parametrize("module_name", sorted(set(CLUSTER) - {"reload_sound"}))
def test_other_pages_do_not_preselect(module_name):
    """其余三页不该凭空多出预选武器——那是 reload_sound 独有的。"""
    from pages.sound_page_base import SoundPageBase

    cls_name, _ = CLUSTER[module_name]
    cls = _page_class(module_name, cls_name)
    assert cls._style_creator_extra_kwargs is SoundPageBase._style_creator_extra_kwargs


def test_auto_refresh_cooldown_unchanged():
    """四页原本各写一份 10 秒冷却，合并后必须还是 10 秒。"""
    from pages.sound_page_base import SoundPageBase

    assert SoundPageBase.AUTO_REFRESH_COOLDOWN == 10.0


def test_gun_sound_is_deliberately_not_in_the_cluster():
    """gun_sound 实测与其余各页只有 45~64% 相似，**故意**不并入基类。

    留这条断言是为了存档这个决定：下一个人看到"音效页有基类而 gun_sound 没继承"
    时，不用重新调查一遍才知道那不是遗漏。
    """
    from pages.gun_sound_page import GunSoundPage
    from pages.sound_page_base import SoundPageBase

    assert not issubclass(GunSoundPage, SoundPageBase)
