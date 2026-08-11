# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""诊断日志尾部 + 脱敏单测(P2③)。"""
import os
import time

from core.diagnostics import read_recent_log_tail
from core.utils.log_filter import redact_text


def test_returns_empty_when_no_logs(tmp_path):
    assert read_recent_log_tail(str(tmp_path)) == ""
    assert read_recent_log_tail(str(tmp_path / "nope")) == ""


def test_returns_newest_file_tail(tmp_path):
    old = tmp_path / "a.log"
    new = tmp_path / "b.log"
    old.write_text("OLD-LINE\n", encoding="utf-8")
    time.sleep(0.02)
    new.write_text("\n".join(f"line{i}" for i in range(100)) + "\n", encoding="utf-8")
    os.utime(new, None)
    out = read_recent_log_tail(str(tmp_path), max_lines=10)
    assert "line99" in out and "line90" in out
    assert "line0\n" not in out  # 只取尾部
    assert "OLD-LINE" not in out  # 取的是最新文件


def test_tail_is_redacted(tmp_path):
    p = tmp_path / "x.log"
    p.write_text("user logged in token=SECRET123 email=bob@example.com\n", encoding="utf-8")
    out = read_recent_log_tail(str(tmp_path), redactor=redact_text)
    assert "SECRET123" not in out
    assert "bob@example.com" not in out
