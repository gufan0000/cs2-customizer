# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""make_session 重试配置单测(无需联网)。"""
from core.net.http_session import make_session


def test_session_has_retry_adapter():
    s = make_session(total=3, backoff=0.5)
    for scheme in ("http://", "https://"):
        retries = s.get_adapter(scheme).max_retries
        assert retries.total == 3
        assert float(retries.backoff_factor) == 0.5
        assert 502 in retries.status_forcelist
        assert 503 in retries.status_forcelist
        assert 504 in retries.status_forcelist


def test_post_not_status_retried_but_get_is():
    s = make_session()
    retries = s.get_adapter("https://").max_retries
    methods = getattr(retries, "allowed_methods", None) or getattr(retries, "method_whitelist", None)
    assert methods is not None
    assert "GET" in methods
    assert "POST" not in methods  # 非幂等 POST 不按状态码重试


def test_default_total_positive():
    assert make_session().get_adapter("https://").max_retries.total >= 1
