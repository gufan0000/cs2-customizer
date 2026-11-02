# SPDX-License-Identifier: GPL-3.0-or-later
"""Budget decisions use synthetic readings only; never run a wall-clock benchmark."""
from __future__ import annotations

import json

import pytest

import health_table as health


@pytest.fixture
def fake_measurement(monkeypatch, tmp_path):
    readings = dict.fromkeys(health.METRIC_KEYS, 10.0)
    for state in health.STATES:
        readings[f"{state}_processes"] = 1
        readings[f"{state}_sample_seconds"] = 10.0
        readings[f"{state}_rejected_windows"] = 0
    limits = dict.fromkeys(health.METRIC_KEYS, 10.0)
    path = tmp_path / "budget.json"
    path.write_text(json.dumps(limits), encoding="utf-8")
    calls = []

    def measured(idle):
        calls.append(idle)
        return dict(readings)

    monkeypatch.setattr(health, "run_once", measured)
    monkeypatch.setattr(health, "package_table", lambda: None)
    return readings, limits, path, calls


def test_check_green_at_the_limit(fake_measurement, capsys):
    _, _, path, calls = fake_measurement
    assert health.main(["--check", "--budget", str(path)]) == 0
    output = capsys.readouterr().out
    assert "✅ 预算检查通过" in output
    assert len(calls) == 3


@pytest.mark.parametrize("key", health.METRIC_KEYS)
def test_check_red_over_any_limit(key, fake_measurement, capsys):
    readings, _, path, _ = fake_measurement
    readings[key] = 10.001
    assert health.main(["--check", "--budget", str(path), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["check"]["passed"] is False
    assert result["check"]["error"] is None
    assert result["check"]["exceeded"] == [f"{key}: 10.001 > 10.0"]


def test_check_lists_all_exceeded_metrics(fake_measurement, capsys):
    readings, _, path, _ = fake_measurement
    readings["shown_cpu_percent"] = 100
    readings["first_kill_sound_ms"] = 1000
    assert health.main(["--check", "--budget", str(path)]) == 1
    output = capsys.readouterr().out
    assert "❌ 超预算" in output
    assert "shown_cpu_percent: 100" in output
    assert "first_kill_sound_ms: 1000" in output


@pytest.mark.parametrize("key", health.METRIC_KEYS)
def test_missing_budget_item_is_an_error(key, fake_measurement, capsys):
    _, limits, path, _ = fake_measurement
    del limits[key]
    path.write_text(json.dumps(limits), encoding="utf-8")
    assert health.main(["--check", "--budget", str(path), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["check"]["passed"] is False
    assert "missing=" in result["check"]["error"]
    assert key in result["check"]["error"]


@pytest.mark.parametrize("bad", [None, True, "10", -1, float("nan"), float("inf")])
def test_invalid_limit_is_an_error(bad, fake_measurement):
    readings, limits, path, _ = fake_measurement
    limits["shown_cpu_percent"] = bad
    path.write_text(json.dumps(limits), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid budget"):
        health.check_budget(readings, path)


@pytest.mark.parametrize("bad", [None, True, "10", -1, float("nan"), float("inf")])
def test_invalid_reading_is_an_error(bad, fake_measurement):
    readings, _, path, _ = fake_measurement
    readings["shown_cpu_percent"] = bad
    with pytest.raises(ValueError, match="invalid reading"):
        health.check_budget(readings, path)


def test_missing_reading_is_an_error(fake_measurement):
    readings, _, path, _ = fake_measurement
    del readings["tray_cpu_percent"]
    with pytest.raises(ValueError, match="invalid reading: tray_cpu_percent"):
        health.check_budget(readings, path)


@pytest.mark.parametrize("content", ["[]", "null", "{", '{"typo": 10}'])
def test_malformed_budget_is_an_error(content, fake_measurement, capsys):
    _, _, path, _ = fake_measurement
    path.write_text(content, encoding="utf-8")
    assert health.main(["--check", "--budget", str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["check"]["error"]


def test_missing_budget_file_is_an_error(fake_measurement, tmp_path, capsys):
    assert health.main(["--check", "--budget", str(tmp_path / "missing.json")]) == 1
    assert "❌ 预算错误" in capsys.readouterr().out


def test_incomplete_samples_fail_without_a_performance_claim(fake_measurement, monkeypatch, capsys):
    monkeypatch.setattr(health, "run_once", lambda idle: None)
    assert health.main(["--check"]) == 1
    assert "样本不完整" in capsys.readouterr().out


def test_checked_in_budget_has_complete_numeric_limits():
    limits = json.loads(health.BUDGET_PATH.read_text(encoding="utf-8"))
    assert len(health.METRIC_KEYS) >= 78  # 分母：28 页首开 + 28 页再开 + 三态 + 旧读数
    assert set(limits) == set(health.METRIC_KEYS)
    assert not health.check_budget(dict.fromkeys(health.METRIC_KEYS, 0), health.BUDGET_PATH)


@pytest.mark.parametrize("invalid", [
    (1, 90, 100, frozenset({1})),  # context counter fell when a thread exited
    (1, 110, 100, frozenset({2})),  # turnover even if aggregate counter grew
    (-1, 110, 100, frozenset({1})),  # CPU counter regression
])
def test_counter_window_rejects_turnover_without_clamping_to_zero(invalid):
    initial = {10: (0, 100, 100, frozenset({1}))}
    final = {10: (1, 120, 100, frozenset({1}))}
    snapshots = iter([initial, {10: invalid}, initial, final])
    times = iter([0, 10, 10, 20])
    waits = []
    before, after, elapsed, rejected = health.counter_window(
        lambda starting: next(snapshots), waits.append, lambda: next(times))
    assert (before, after, elapsed, rejected) == (initial, final, 10, 1)
    assert waits == [10, 10]


def test_counter_window_rejects_process_churn_and_eventual_failure():
    snapshots = iter([{10: (0, 0, 100, frozenset({1}))}, {}] * 3)
    times = iter(range(0, 60, 10))
    with pytest.raises(RuntimeError, match="3 attempts"):
        health.counter_window(lambda starting: next(snapshots), lambda _: None, lambda: next(times))
