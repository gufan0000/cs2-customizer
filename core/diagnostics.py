# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""诊断信息汇总(P2③,2026-06-13)。

把"复制诊断信息"从只有版本/系统,扩成正规软件级支持包的可复用部件:
最关键的是**脱敏后的最近日志尾部**(排障第一线索),用 log_filter 脱敏,
绝不泄露 token/路径/邮箱。其余运行时字段由调用方(about 页)就地拼接。
纯逻辑,可单测。
"""
from __future__ import annotations

import glob
import os
from typing import Callable, Optional


def read_recent_log_tail(
    logs_dir: str,
    max_lines: int = 40,
    redactor: Optional[Callable[[str], str]] = None,
) -> str:
    """返回最新 *.log 文件末尾 max_lines 行(经 redactor 脱敏)。无日志/异常返回空串。"""
    try:
        if not logs_dir or not os.path.isdir(logs_dir):
            return ""
        candidates = glob.glob(os.path.join(logs_dir, "*.log"))
        if not candidates:
            return ""
        newest = max(candidates, key=os.path.getmtime)
        with open(newest, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = "\n".join(ln.rstrip("\n") for ln in lines[-max_lines:])
        if redactor is not None:
            try:
                tail = redactor(tail)
            except Exception:
                return ""  # 脱敏失败宁可不给日志,绝不泄露原文
        return tail
    except OSError:
        return ""
