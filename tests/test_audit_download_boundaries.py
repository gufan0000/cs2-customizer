# SPDX-License-Identifier: GPL-3.0-or-later
from unittest.mock import Mock

import pytest

from core.update_download import open_update_response
from core.utils.log_filter import redact_text


def response(url, status=200, location=None):
    return Mock(url=url, status_code=status, headers={"Location": location} if location else {})


@pytest.mark.parametrize("url", ["http://cdn.example/a.exe", "https://127.0.0.1/a",
                                 "https://127.1/a", "https://2130706433/a", "https://0x7f000001/a",
                                 "https://user:pass@cdn.example/a", "file:///a.exe"])
def test_unsafe_initial_url_never_sends_request(url):
    get = Mock()
    with pytest.raises(ValueError):
        open_update_response(get, url)
    get.assert_not_called()


def test_redirect_validated_before_request_and_response_closed():
    first = response("https://cdn.example/a", 302, "http://cdn.example/b")
    get = Mock(return_value=first)
    with pytest.raises(ValueError):
        open_update_response(get, first.url)
    assert get.call_count == 1
    first.close.assert_called_once()


def test_valid_https_cdn_redirect_and_loop_limit():
    first = response("https://app.example/a", 302, "https://cdn.example/a.exe")
    last = response("https://cdn.example/a.exe")
    get = Mock(side_effect=[first, last])
    assert open_update_response(get, first.url) is last
    assert all(c.kwargs["allow_redirects"] is False for c in get.call_args_list)
    first.close.assert_called_once()
    loop = response(first.url, 302, first.url)
    with pytest.raises(ValueError):
        open_update_response(Mock(return_value=loop), first.url)


@pytest.mark.parametrize("query", ["signature=SECRET", "SIG=SECRET", "%73ignature=SECRET",
                                   "sig=a&sig=SECRET", "url=https%3A%2F%2Fx.example%2F%3Fsig%3DSECRET"])
def test_signed_query_is_never_logged(query):
    assert "SECRET" not in redact_text("download https://cdn.example/a?" + query)


def test_bare_signature_and_url_userinfo_are_redacted():
    assert "SECRET" not in redact_text("signature=SECRET")
    assert "SECRET" not in redact_text("https://u:SECRET@cdn.example/a")
