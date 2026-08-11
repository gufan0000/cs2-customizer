# -*- coding: utf-8 -*-
"""R2-2 内置精选包:三包全部通过 schema 校验且可应用;页面装配。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.presets.preset_center import apply_bundle, validate_bundle
from core.presets.starter_packs import get_pack_bundle, list_packs


def test_three_packs_listed():
    packs = list_packs()
    assert len(packs) == 3
    ids = [p[0] for p in packs]
    assert ids == ["clean_alerts", "esports_minimal", "full_experience"]


@pytest.mark.parametrize("pack_id", ["clean_alerts", "esports_minimal", "full_experience"])
def test_pack_validates_and_applies(pack_id):
    bundle = get_pack_bundle(pack_id)
    v = validate_bundle(bundle)
    assert v.ok, v.errors
    r = apply_bundle(bundle, mode="merge")
    assert r.ok, r.errors
    assert r.applied_types


def test_unknown_pack_raises():
    with pytest.raises(KeyError):
        get_pack_bundle("nope")


def test_preset_page_has_starter_card():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from pages.preset_center_page import PresetCenterPage

    page = PresetCenterPage()
    try:
        assert page.starter_combo.count() == 3
        assert page.starter_apply_btn.text() == "一键应用"
    finally:
        page.deleteLater()
        app.processEvents()
