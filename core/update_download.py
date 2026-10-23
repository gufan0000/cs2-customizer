# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded HTTPS-only redirect handling for verified installer downloads."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit


def validate_update_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    if (parts.scheme.lower() != "https" or not host or parts.username is not None
            or parts.password is not None or any(c.isspace() for c in url)
            or "%" in host or "\\" in parts.netloc):
        raise ValueError("更新地址必须是有效的 https 地址，且不能包含登录信息")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("更新地址不能指向本地设备")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            address = None
            if "." not in host:
                raise ValueError("更新地址必须使用完整主机名") from None
    if address is not None and not address.is_global:
        raise ValueError("更新地址不能指向本地设备")
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("更新地址端口无效")
    return url


def open_update_response(get, url, *, max_redirects=5):
    seen = set()
    for _ in range(max_redirects + 1):
        validate_update_url(url)  # before every request, including the first
        if url in seen:
            raise ValueError("更新地址出现循环重定向")
        seen.add(url)
        response = get(url, stream=True, timeout=30, allow_redirects=False,
                       headers={"User-Agent": "CS2CustomizerDesktop/2.1"})
        try:
            validate_update_url(getattr(response, "url", None) or url)
            if response.status_code not in (301, 302, 303, 307, 308):
                response.raise_for_status()
                return response
            location = response.headers.get("Location")
            if not location:
                raise ValueError("更新重定向缺少目标地址")
            url = urljoin(url, location)
        except Exception:
            response.close()
            raise
        response.close()
    raise ValueError("更新地址重定向次数过多")
