# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R3-3 匿名使用统计:默认关、payload 白名单、24h 节流、安装ID 稳定。"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config import config
from core import usage_reporter as ur


@pytest.fixture(autouse=True)
def clean_state():
    old = (
        getattr(config, "usage_report_enabled", False),
        getattr(config, "usage_install_id", ""),
        getattr(config, "usage_last_sent_ts", 0.0),
    )
    config.usage_report_enabled = False
    config.usage_install_id = ""
    config.usage_last_sent_ts = 0.0
    yield
    (config.usage_report_enabled, config.usage_install_id, config.usage_last_sent_ts) = old


def test_disabled_by_default_no_send():
    assert ur.should_send() is False
    assert ur.schedule_startup_report(1) is None


def test_install_id_generated_once_and_stable():
    a = ur.ensure_install_id()
    b = ur.ensure_install_id()
    assert a == b
    assert len(a) == 32
    int(a, 16)  # 合法 hex


def test_payload_whitelist_only():
    config.usage_report_enabled = True
    payload = ur.build_payload()
    assert set(payload.keys()) == {"install_id", "version", "page_opens", "switches"}
    # 绝不允许出现这些敏感面
    flat = str(payload).lower()
    for forbidden in ("email", "steam", "token", "c:\\", "users", "gufan"):
        assert forbidden not in flat, f"payload 泄漏敏感字段: {forbidden}"
    assert all(isinstance(v, int) for v in payload["page_opens"].values())
    assert all(isinstance(v, bool) for v in payload["switches"].values())


def test_throttle_24h():
    config.usage_report_enabled = True
    config.usage_last_sent_ts = time.time()
    assert ur.should_send() is False
    config.usage_last_sent_ts = time.time() - 25 * 3600
    assert ur.should_send() is True


def test_send_handles_network_failure(monkeypatch):
    # 开源版 TELEMETRY_BASE_URL 默认为空 → send_usage_report 在构造请求前短路返回 None。
    # 这条判据要量的是"网络失败时的行为"，所以先注入一个端点把它推到网络路径上。
    monkeypatch.setattr(ur, "USAGE_REPORT_API_URL", "https://example.invalid/api/usage_report.php")
    import requests

    config.usage_report_enabled = True

    def boom(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(ur.requests, "post", boom)
    assert ur.send_usage_report() is False
