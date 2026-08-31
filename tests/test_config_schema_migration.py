# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""配置 schema 迁移框架测试（P4.2）。"""
from __future__ import annotations

import config as config_module
from config import Config, CONFIG_SCHEMA_VERSION


def test_new_config_is_latest_schema():
    cfg = Config.__new__(Config)
    # 不跑完整 __init__，直接验证迁移把"无文件"当最新
    cfg.config_schema_version = 0
    cfg._do_save_config = lambda: None  # 隔离落盘
    cfg._run_schema_migrations(None)  # None=无配置文件（新装）
    assert cfg.config_schema_version == CONFIG_SCHEMA_VERSION


def test_legacy_config_without_version_is_upgraded():
    cfg = Config.__new__(Config)
    cfg.config_schema_version = CONFIG_SCHEMA_VERSION
    saved = {"flag": False}

    def _fake_save():
        saved["flag"] = True

    cfg._do_save_config = _fake_save
    # 旧配置：没有 config_schema_version 字段 → 视为版本 0
    cfg._run_schema_migrations({"some_old_field": 1})
    assert cfg.config_schema_version == CONFIG_SCHEMA_VERSION
    # 发生过版本提升 → 应触发一次落盘固化
    assert saved["flag"] is True


def test_current_version_config_no_resave():
    cfg = Config.__new__(Config)
    cfg.config_schema_version = CONFIG_SCHEMA_VERSION
    saved = {"flag": False}
    cfg._do_save_config = lambda: saved.__setitem__("flag", True)
    # 已是最新版本的配置 → 不应重复落盘
    cfg._run_schema_migrations({"config_schema_version": CONFIG_SCHEMA_VERSION})
    assert cfg.config_schema_version == CONFIG_SCHEMA_VERSION
    assert saved["flag"] is False


def test_migration_runs_registered_function(monkeypatch):
    calls = []

    def _fake_migrate(cfg, raw):
        calls.append(raw.get("config_schema_version", 0))

    # 临时注册 0->1 迁移 + 把目标版本抬到 1（当前就是1，但确保函数被调用）
    monkeypatch.setattr(config_module, "CONFIG_MIGRATIONS", {0: _fake_migrate})
    cfg = Config.__new__(Config)
    cfg.config_schema_version = CONFIG_SCHEMA_VERSION
    cfg._do_save_config = lambda: None
    cfg._run_schema_migrations({"config_schema_version": 0})
    assert calls == [0]
    assert cfg.config_schema_version == CONFIG_SCHEMA_VERSION


# ==================================================================== 批 33
# RN-454：撤掉 `music_game_link_enabled` 之后的 v1→v2 迁移
# ====================================================================

def _migrated(raw):
    """拿一份原始配置字典跑一遍迁移，返回迁移后的 config 对象。"""
    from config import Config

    cfg = Config.__new__(Config)
    cfg.music_enabled = bool(raw.get("music_enabled", False))
    cfg.config_schema_version = 0
    cfg._do_save_config = lambda: None      # 迁移完会想落盘，这里不写磁盘
    cfg._run_schema_migrations(dict(raw, config_schema_version=1))
    return cfg


def test_the_migration_keeps_a_user_who_had_turned_linking_off():
    """⭐⭐⭐ **迁移的方向要朝「保住用户已经表达过的意图」那边倒。**

    老用户里只有一种组合会被这一撤改变行为：
    **总开关开着、子开关自己关掉了** —— 他今天是「不联动」，
    而撤掉子开关之后总开关说了算，他会**突然开始联动**。
    ⇒ 把总开关一并关上，保住他当初表达的那个意思。

    ⚠ 反过来做（保住某个键的字面值）在这里根本无从谈起：那个键要没了。
    """
    cfg = _migrated({"music_enabled": True, "music_game_link_enabled": False})
    assert cfg.music_enabled is False, (
        "「总开关开 + 子开关关」= 不联动。撤掉子开关后总开关必须跟着关，"
        "否则这个用户下次进游戏音乐会自己动起来。"
    )


import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("raw", [
    {"music_enabled": True, "music_game_link_enabled": True},     # 本来就联动
    {"music_enabled": False, "music_game_link_enabled": True},    # 本来就不联动
    {"music_enabled": False, "music_game_link_enabled": False},   # 两个都关
    {"music_enabled": True},                                      # 没写过子开关（默认 True）
])
def test_the_migration_leaves_every_other_combination_alone(raw):
    """另外三种组合语义不变 —— ⭐ 迁移只许动那**一个**会变意思的格子。"""
    before = bool(raw.get("music_enabled", False))
    assert _migrated(raw).music_enabled is before, f"这一组不该被动：{raw}"


def test_the_migration_is_actually_registered():
    """⭐ 先证明它真的挂在表上，再让上面那几条去断言它的行为。

    ⚠ `CONFIG_MIGRATIONS` 在批 33 之前**一直是空的** —— 这个框架写好了、
    接线了、有 4 条测试，但**从来没有跑过一个真正的迁移**。
    ⭐⭐ **一条从没被走过的通路，和一条走不通的通路，平时长得一模一样。**
    """
    from config import CONFIG_MIGRATIONS, CONFIG_SCHEMA_VERSION

    assert CONFIG_SCHEMA_VERSION >= 2
    assert 1 in CONFIG_MIGRATIONS, "v1→v2 的迁移没注册，上面那几条在测一个不会被调用的函数"
    for v in range(1, CONFIG_SCHEMA_VERSION):
        assert v in CONFIG_MIGRATIONS, (
            f"v{v}→v{v+1} 没有迁移函数 —— `_run_schema_migrations` 会在这里 break，"
            "后面的迁移全部静默跳过。⭐ 版本号只许和迁移函数一起往上抬。"
        )
