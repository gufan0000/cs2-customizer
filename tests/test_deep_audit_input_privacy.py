# SPDX-License-Identifier: GPL-3.0-or-later
"""导入内容与实际上报请求的行为边界。"""
import json
from types import SimpleNamespace

import pytest

from core.io_validation import validate_voice_config, validate_crosshair_import


@pytest.mark.parametrize("data", [
    {"slots": {"0": "broken"}}, {"slots": {"9999999999": {}}},
    {"slots": {"0": {"volume": float("nan")}}},
    {"slots": {"0": {"audio": 12}}}, {"volume": float("inf")},
    {"volume": -1}, {"mode": "invalid"},
])
def test_invalid_voice_import_is_rejected_as_a_whole(data):
    ok, cleaned, errors = validate_voice_config(data)
    assert not ok and not cleaned and errors


@pytest.mark.parametrize("data", ["x", {}, [[1, "x"]], [{"x": 1}], [[31, 1]], [[True, 1]]])
def test_invalid_crosshair_import_is_rejected(data):
    assert validate_crosshair_import({"crosshair_data": data})[0] is False


def test_voice_legacy_list_normalizes_and_flash_edited_style_roundtrips():
    from core.presets.payload_validation import validate_payload
    ok, cleaned, _ = validate_voice_config({"slots": [{"audio": "voice.wav", "volume": 1.2}]})
    assert ok and cleaned["voice_output_slots"]["0"]["audio"] == "voice.wav"
    assert not validate_payload({"flash_style_params": {"wave": {"speed": 1.2}}}, {"flash_style_params"})
    assert validate_payload({"flash_style_params": {"wave": {"speed": float("nan")}}}, {"flash_style_params"})


@pytest.mark.parametrize("expiry,user", [("not-number", {}), (float("inf"), {}), ([], {}), (1, "bad-user")])
def test_malformed_session_has_uniform_error(monkeypatch, expiry, user):
    auth = pytest.importorskip("account_auth_client")
    client = auth.CS2CustomizerAuthClient()
    monkeypatch.setattr(client, "_request", lambda *a, **k: {"token": "fake", "expires_in": expiry, "user": user})
    for operation in (lambda: client.login("fake@example.invalid", "fake"), lambda: client.refresh("fake")):
        with pytest.raises(auth.AuthClientError):
            operation()


@pytest.mark.parametrize("text", ["中" * 21000, "\\\n" * 32768], ids=["chinese", "escaped"])
def test_crash_preview_matches_redacted_wire_and_server_limit(tmp_path, monkeypatch, text):
    from core import crash_reporter as reporter
    report = tmp_path / "bootstrap_crash_test.log"
    canaries = "password='fake secret with spaces' token=fake_token\nC:\\Users\\FakeUser\\app.py"
    report.write_text(canaries + "\n" + text, encoding="utf-8")
    preview = reporter.read_report_text([report])
    captured = {}
    def post(url, **kw):
        captured.update(kw)
        return SimpleNamespace(status_code=200, ok=True)
    monkeypatch.setattr(reporter.requests, "post", post)
    monkeypatch.setattr(reporter, "CRASH_REPORT_API_URL", "https://example.invalid/api/crash_report.php")
    assert reporter.send_crash_report(preview, "2.3.1")
    payload = json.loads(captured["data"])
    assert payload["report"] == preview
    assert len(captured["data"]) <= reporter.MAX_REQUEST_BYTES
    for secret in ("fake secret with spaces", "fake_token", "FakeUser"):
        assert secret not in preview
    assert len(preview.encode("utf-8")) <= reporter.MAX_REPORT_BYTES
