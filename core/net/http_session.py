# -*- coding: utf-8 -*-
"""共用 HTTP Session 工厂：给请求挂重试/退避(2026-06-13)。

正规软件对网络请求应能容忍瞬时抖动(超时/连接重置/502/503/504)而非一次失败
就放弃。本工厂返回带 urllib3 Retry 的 requests.Session：
- connect 错误(连接尚未建立)对所有方法重试——此时请求未到服务端，
  重发 POST 也是安全的；
- read 错误与 502/503/504 状态码仅对幂等方法(GET/HEAD/OPTIONS)重试
  (受 allowed_methods 门控)——**不重试 POST**，避免登录/上传等非幂等
  请求在"已到达服务端但响应丢失"时被重复提交；
- raise_on_status=False：最终响应交回调用方按原逻辑处理。
兼容新旧 urllib3(allowed_methods / method_whitelist 命名差异)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅供类型标注，运行时不导入
    import requests

_IDEMPOTENT = frozenset(["GET", "HEAD", "OPTIONS"])


def _retry_class():
    """惰性取 urllib3 的 Retry；取不到就降级为无重试。

    UP-056：`requests` 在本机要 ~200ms。此前本模块在**顶层**导入它，于是任何
    `from core.net.http_session import make_session` 的调用方（包括 gui_widget
    经 account_auth_client 的那条链）都会在 import 阶段付掉这 200ms，
    哪怕整个进程一次网络请求都不发。改为用到时才导。
    """
    try:
        from urllib3.util.retry import Retry

        return Retry
    except Exception:  # pragma: no cover - urllib3 缺失则降级为无重试
        return None


def _build_retry(total: int, backoff: float):
    Retry = _retry_class()
    if Retry is None:
        return None
    kwargs = dict(
        total=total,
        connect=total,
        read=total,
        backoff_factor=backoff,
        status_forcelist=(502, 503, 504),
        raise_on_status=False,
    )
    try:
        return Retry(allowed_methods=_IDEMPOTENT, **kwargs)
    except TypeError:  # 旧版 urllib3
        return Retry(method_whitelist=_IDEMPOTENT, **kwargs)


def make_session(total: int = 2, backoff: float = 0.3) -> "requests.Session":
    """返回带重试/退避的 Session。total=额外重试次数(不含首次)。"""
    import requests
    from requests.adapters import HTTPAdapter

    session = requests.Session()
    retry = _build_retry(total, backoff)
    if retry is not None:
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session
