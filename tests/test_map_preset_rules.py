# -*- coding: utf-8 -*-
"""R2-4 按地图自动切预设:规则存取、GSI 去重触发、总开关门控、坏数据安全。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from config import config
from core.presets.map_rules import (
    MapPresetApplier,
    MapPresetHandler,
    delete_rule,
    get_rule,
    list_rules,
    save_rule,
)


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    """apply_bundle→config.save_config 的防抖定时器需要 QApplication,
    否则解释器退出时 Qt fail-fast(0xC0000409)。"""
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_rules():
    config.map_preset_rules = {}
    config.map_preset_enabled = True
    yield
    config.map_preset_rules = {}
    config.map_preset_enabled = False


def test_save_get_delete_rule():
    assert save_rule("DE_Dust2 ", ["crosshair"])  # 名字归一化
    assert get_rule("de_dust2") is not None
    assert list_rules() == ["de_dust2"]
    assert delete_rule("de_dust2")
    assert list_rules() == []


def test_save_rule_rejects_empty():
    assert not save_rule("", ["crosshair"])
    assert not save_rule("de_mirage", [])


def test_applier_applies_once_per_map():
    save_rule("de_mirage", ["crosshair"])
    applier = MapPresetApplier()
    assert applier.on_map("de_mirage") is True
    assert applier.on_map("de_mirage") is False  # 同图去重
    assert applier.on_map("de_dust2") is False   # 无规则
    assert applier.on_map("de_mirage") is True   # 离图回图重新触发


def test_applier_respects_master_switch():
    save_rule("de_nuke", ["crosshair"])
    config.map_preset_enabled = False
    applier = MapPresetApplier()
    assert applier.on_map("de_nuke") is False


def test_corrupt_rule_bundle_is_ignored():
    config.map_preset_rules = {"de_train": {"bundle": {"schema": "evil"}}}
    applier = MapPresetApplier()
    assert applier.on_map("de_train") is False


def test_gsi_handler_never_raises():
    handler = MapPresetHandler()
    handler.process_data(None)
    handler.process_data({})
    handler.process_data({"map": {}})
    handler.process_data({"map": {"name": "de_inferno"}})
    handler.process_data({"map": 123})  # 异常 payload 也不许炸


def test_handler_applies_via_gsi_payload():
    config.crosshair_size = 11
    save_rule("de_ancient", ["crosshair"])  # 捕获 size=11
    handler = MapPresetHandler()
    # 改动当前配置后,GSI 报图应套回保存值
    config.crosshair_size = 99
    handler.process_data({"map": {"name": "de_ancient"}})
    assert config.crosshair_size == 11
