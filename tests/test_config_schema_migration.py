# -*- coding: utf-8 -*-
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
