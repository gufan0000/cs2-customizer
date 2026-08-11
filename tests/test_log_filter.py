# -*- coding: utf-8 -*-
"""A5 日志脱敏过滤器单元测试。

保证：
1. 常见敏感字段被正确脱敏（token/api_key/password/Bearer/steamid/用户目录/邮箱）
2. 无敏感信息的普通日志不被改动
3. 过滤器异常时 LogRecord 原样返回（不阻塞日志链）
4. SensitiveFilter 的 filter() 永远返回 True（不丢日志）
"""
from __future__ import annotations

import logging
import os
import sys
import unittest

# 允许在项目根目录直接运行 `python -m unittest tests.test_log_filter`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.utils.log_filter import SensitiveFilter, redact_text  # noqa: E402


class TestRedactText(unittest.TestCase):
    # ------ token / api_key / password ------
    def test_token_kv_equal(self):
        self.assertEqual(redact_text("token=abcdef123456"), "token=***")

    def test_token_kv_colon(self):
        self.assertEqual(redact_text("token: abcdef123456"), "token: ***")

    def test_token_json(self):
        out = redact_text('{"token": "abcdef123456", "other": "x"}')
        self.assertIn("***", out)
        self.assertNotIn("abcdef123456", out)

    def test_api_key(self):
        self.assertEqual(redact_text("api_key=XYZ-123"), "api_key=***")

    def test_password(self):
        self.assertEqual(redact_text("password=MyP@ss"), "password=***")

    def test_refresh_token(self):
        self.assertEqual(redact_text("refresh_token=r123"), "refresh_token=***")

    # ------ Bearer ------
    def test_bearer_token(self):
        self.assertEqual(
            redact_text("Authorization: Bearer abc.def.ghi"),
            "Authorization: Bearer ***",
        )

    # ------ steamid ------
    def test_steamid(self):
        # 保留末 4 位
        out = redact_text("steamid=76561198012345678")
        self.assertEqual(out, "steamid=***5678")

    def test_steam_id_underscore(self):
        out = redact_text("steam_id=76561198012345678")
        self.assertEqual(out, "steam_id=***5678")

    # ------ 用户目录 ------
    def test_windows_user_dir(self):
        out = redact_text("路径: C:\\Users\\gufan\\CS2Customizer\\logs")
        self.assertIn("C:\\Users\\***\\", out)
        self.assertNotIn("gufan", out)

    def test_unix_style_user_dir(self):
        out = redact_text("path=C:/Users/gufan/appdata")
        self.assertIn("C:/Users/***/", out)

    # ------ 邮箱 ------
    def test_email(self):
        # 用 RFC 2606 保留域名做夹具：既不是任何人的真实邮箱，也不会随品牌改名而失效。
        out = redact_text("联系 someone@example.com 即可")
        self.assertEqual(out, "联系 ***@example.com 即可")

    # ------ 无敏感数据不动 ------
    def test_plain_message_unchanged(self):
        msg = "加载风格成功: kill_default, 耗时 123ms"
        self.assertEqual(redact_text(msg), msg)

    def test_number_not_redacted(self):
        # 普通数字/文件大小不应被误杀
        msg = "文件大小 76561198 bytes"
        self.assertEqual(redact_text(msg), msg)

    def test_timestamp_not_redacted(self):
        msg = "[2026-04-19 13:31:45] 开始加载"
        self.assertEqual(redact_text(msg), msg)

    # ------ 鲁棒性 ------
    def test_none_or_empty(self):
        self.assertEqual(redact_text(""), "")
        self.assertIsNone(redact_text(None))  # type: ignore[arg-type]

    def test_non_string_returned_as_is(self):
        # redact_text 接到非字符串应原样返回
        self.assertEqual(redact_text(12345), 12345)  # type: ignore[arg-type]


class TestSensitiveFilter(unittest.TestCase):
    def _make_record(self, msg: str, args=None) -> logging.LogRecord:
        return logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg=msg, args=args, exc_info=None,
        )

    def test_filter_returns_true_always(self):
        f = SensitiveFilter()
        r = self._make_record("token=abcdef")
        self.assertTrue(f.filter(r))

    def test_filter_redacts_message(self):
        f = SensitiveFilter()
        r = self._make_record("token=abcdef")
        f.filter(r)
        self.assertIn("***", r.getMessage())
        self.assertNotIn("abcdef", r.getMessage())

    def test_filter_handles_args(self):
        # logger.info("token=%s", "abc") 的场景
        f = SensitiveFilter()
        r = self._make_record("token=%s", args=("abcdef",))
        f.filter(r)
        # 应被替换，args 清空避免二次格式化
        self.assertIn("***", r.getMessage())
        self.assertIsNone(r.args)

    def test_filter_preserves_plain_message(self):
        f = SensitiveFilter()
        r = self._make_record("加载风格: default")
        f.filter(r)
        self.assertEqual(r.getMessage(), "加载风格: default")

    def test_disabled_filter_does_nothing(self):
        f = SensitiveFilter(enabled=False)
        r = self._make_record("token=abcdef")
        f.filter(r)
        self.assertEqual(r.getMessage(), "token=abcdef")

    def test_filter_never_raises_on_bad_record(self):
        # 构造异常情形：getMessage 会抛（msg 格式化失败）
        f = SensitiveFilter()

        class BadRecord:
            def getMessage(self):
                raise RuntimeError("boom")

        # filter 接到异常 record 时，应当捕获并返回 True（不丢日志）
        self.assertTrue(f.filter(BadRecord()))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
