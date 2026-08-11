# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""QA-014：VB-Cable 驱动包下载必须有超时，且不能把慢链路误杀。

原实现 `urllib.request.urlretrieve(url, path)` —— 这个 API 不接受 timeout，
而全仓没有任何 `socket.setdefaulttimeout`，所以默认超时是 None。
对端 accept 后不发数据、或 body 传到一半断流，安装线程**永久阻塞**：
UI 永远停在「正在下载VB-Cable驱动...」，finally 里的 rmtree 跑不到。

三条判据全部只用回环 socket，不联外网、不建 QWidget：
- 判据 1（主判据，回退即红）：断流必须放弃；
- 判据 2（防错修，回退时保持绿）：慢但活着的链路必须下完 —— 专抓"把 per-op
  超时写成总时限"这种比原缺陷更糟的改法（它打的是正常用户）；
- 判据 3：无限流必须被上限截断。
"""
from __future__ import annotations

import hashlib
import socket
import threading
import time
from pathlib import Path

import pytest

from pages.voice_output_page import _download_to_file


class _StallServer:
    """回环 HTTP 服务端：按脚本发 body，可中途永久静默。"""

    def __init__(self, body: bytes, *, mode: str, chunk: int = 4096, gap: float = 0.0,
                 declare_length: bool = True, endless: bool = False):
        self.body = body
        self.mode = mode              # "stall" | "slow"
        self.chunk = chunk
        self.gap = gap
        self.declare_length = declare_length
        self.endless = endless
        self._stop = threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/pack.zip"

    def _serve(self):
        self.sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.recv(65536)
            head = "HTTP/1.1 200 OK\r\nContent-Type: application/zip\r\n"
            if self.declare_length and not self.endless:
                head += f"Content-Length: {len(self.body)}\r\n"
            head += "Connection: close\r\n\r\n"
            conn.sendall(head.encode())
            if self.endless:
                filler = b"\xab" * 65536
                while not self._stop.is_set():
                    conn.sendall(filler)
                return
            if self.mode == "stall":
                conn.sendall(self.body[: self.chunk])
                self._stop.wait(60)          # 之后永久静默
                return
            for i in range(0, len(self.body), self.chunk):
                conn.sendall(self.body[i:i + self.chunk])
                if self.gap:
                    time.sleep(self.gap)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture
def payload() -> bytes:
    return bytes((i * 7 + 3) % 256 for i in range(200_000))


def test_download_gives_up_when_peer_stalls_mid_body(tmp_path, payload):
    """对端传到一半断流 → 必须抛错退出，不能永久阻塞。"""
    server = _StallServer(payload, mode="stall", chunk=4096)
    dest = tmp_path / "pack.zip"
    box: dict = {}

    def worker():
        try:
            _download_to_file(server.url, str(dest), timeout=2)
            box["ok"] = True
        except BaseException as exc:      # noqa: BLE001 —— 就是要看它抛没抛
            box["err"] = exc

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    # 用 join 超时当看门狗：回退时线程留活，测试立刻判红而不是把套件挂死
    th.join(20)
    server.close()

    assert not th.is_alive(), "下载线程 20 秒后仍在阻塞 —— 没有超时（QA-014）"
    assert "err" in box, f"应该抛错，实际正常返回：{box}"


def test_slow_but_alive_download_still_succeeds(tmp_path, payload):
    """慢但一直在传的链路必须下完。

    这条专门逮「把 per-op 超时写成总时限」的错修：那样跨境慢链路会被误杀，
    本来能装上的用户装不上了 —— 比原缺陷更严重，因为它打的是正常用户。
    总耗时 ~3s 远大于 timeout=1。
    """
    server = _StallServer(payload, mode="slow", chunk=20_000, gap=0.3)
    dest = tmp_path / "pack.zip"
    try:
        written = _download_to_file(server.url, str(dest), timeout=1)
    finally:
        server.close()

    assert written == len(payload)
    assert hashlib.sha256(Path(dest).read_bytes()).hexdigest() == \
        hashlib.sha256(payload).hexdigest(), "慢链路下完了但内容不对"


def test_endless_stream_is_capped(tmp_path, payload):
    """不给 Content-Length 的无限流必须被上限截断，别把系统盘写爆。"""
    server = _StallServer(payload, mode="slow", endless=True, declare_length=False)
    dest = tmp_path / "pack.zip"
    cap = 2 * 1024 * 1024
    try:
        with pytest.raises(Exception):
            _download_to_file(server.url, str(dest), timeout=5, max_bytes=cap)
    finally:
        server.close()

    assert dest.is_file()
    assert dest.stat().st_size <= cap, f"落盘 {dest.stat().st_size} 字节，突破上限 {cap}"
