# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""敏感信息脱敏日志过滤器。

设计原则：
1. **保守**：只对"明显键值对形式"的敏感字段做替换，不主动识别纯数字/纯
   base64（避免误杀时间戳、文件大小、哈希值等无害数据）。
2. **零破坏**：若过滤过程自身异常，静默返回原始消息，绝不抛出导致日志丢失。
3. **可开关**：通过 `CS2Customizer.logging.sanitize = False` 全局禁用（用户需要诊断原始
   日志时），以及实例化参数 `enabled=False`。

覆盖的敏感字段（在 `message` 文本中做正则替换）：
- `token=XXX` / `token: XXX` / `"token": "XXX"` → `token=***`
- `api_key=XXX` → `api_key=***`
- `password=XXX` → `password=***`
- `Authorization: Bearer XXX` → `Authorization: Bearer ***`
- `steamid=<17 位数字>` → `steamid=***<末 4 位>`
- Windows 用户目录 `C:\\Users\\<name>\\` → `C:\\Users\\***\\`（保留首字母）
- 邮箱 `xxx@yyy.zzz` → `***@yyy.zzz`
"""
from __future__ import annotations

import logging
import re
from typing import Final, Iterable, Pattern, Tuple

__all__ = ["SensitiveFilter", "redact_text"]


# 每条规则是 (pattern, replacement)；pattern 使用命名分组以便替换保留上下文
_RULES: Final[Tuple[Tuple[Pattern[str], str], ...]] = (
    # token / api_key / password / secret = "xxxx" 或 = xxxx 或 : xxxx
    # 也兼容 JSON 风格："token": "xxxx"（key 后可带闭合引号）
    (
        re.compile(
            r"(?P<key>(?:access[_-]?token|refresh[_-]?token|api[_-]?key|secret"
            r"|password|passwd|pwd|token))"
            r"(?P<sep>[\"']?\s*[:=]\s*[\"']?)"
            r"(?P<val>[^\s\"',}\]\)]+)",
            re.IGNORECASE,
        ),
        r"\g<key>\g<sep>***",
    ),
    # Authorization: Bearer xxxxx  或 Authorization=Bearer xxxxx
    (
        re.compile(
            r"(?P<prefix>Authorization\s*[:=]\s*Bearer\s+)(?P<val>[A-Za-z0-9._\-]+)",
            re.IGNORECASE,
        ),
        r"\g<prefix>***",
    ),
    # steamid=<17 位数字>，保留末 4 位方便定位但不泄露完整 id
    (
        re.compile(
            r"(?P<key>steam[_-]?id|steamid64)(?P<sep>\s*[:=]\s*[\"']?)"
            r"(?P<head>\d{1,13})(?P<tail>\d{4})",
            re.IGNORECASE,
        ),
        r"\g<key>\g<sep>***\g<tail>",
    ),
    # Windows 用户目录：C:\Users\<name>\ 或 C:/Users/<name>/
    (
        re.compile(
            r"(?P<drive>[A-Za-z]:[\\/])Users[\\/](?P<user>[^\\/\s\"',]+)(?P<tail>[\\/])"
        ),
        r"\g<drive>Users\g<tail>***\g<tail>",
    ),
    # 邮箱：保留域名
    (
        re.compile(
            r"(?<![A-Za-z0-9._%+\-])"
            r"(?P<local>[A-Za-z0-9._%+\-]+)@(?P<domain>[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
        ),
        r"***@\g<domain>",
    ),
)


def redact_text(text: str, rules: Iterable[Tuple[Pattern[str], str]] = _RULES) -> str:
    """对文本做脱敏替换。异常时原样返回（保证日志链不断）。"""
    if not isinstance(text, str) or not text:
        return text
    try:
        redacted = text
        for pattern, repl in rules:
            redacted = pattern.sub(repl, redacted)
        return redacted
    except Exception:
        # 任何正则异常都不能影响日志输出
        return text


class SensitiveFilter(logging.Filter):
    """对 LogRecord 的最终消息做脱敏。

    注意：
    - 作用于 `record.getMessage()` 的结果字符串；% 风格的 args 已被格式化。
    - 替换后写回 `record.msg`，并把 `record.args` 清空，避免下游 formatter
      再次尝试 % 拼接（会因缺参数 raise）。
    """

    def __init__(self, name: str = "", enabled: bool = True) -> None:
        super().__init__(name)
        self.enabled = enabled

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.enabled:
            return True
        try:
            original_message = record.getMessage()
            redacted_message = redact_text(original_message)
            if redacted_message is not original_message:
                record.msg = redacted_message
                record.args = None
        except Exception:
            # 过滤失败时保持原样，绝不阻断日志
            pass
        return True
