# -*- coding: utf-8 -*-
"""真机 GSI 采集器(2026-06-13)。

把 CS2 真实发出的 GSI 状态帧录成 .jsonl,供回归回放(喂 gsi_handler_* 管线)。

背景:
- 单元测试用的是手搓的 GSI 帧(scripts/gsi_live_sim.py,24 帧);真机 GSI 可能含
  手搓覆盖不到的字段/时序/边界。把真机一局录下来,就能把"真机验证"变成可回归样本。
- CS2 的 GSI 是游戏客户端在「实际运行(或回放 demo)」时通过 HTTP POST 实时发到
  本机 127.0.0.1:3000 的;**.dem 录像文件里不含 GSI**——所以采集必须在游戏运行时进行。

用法(Windows;需先关闭帆派助手以腾出 3000 端口,cfg 已指向 3000,无需改):
    1) 关闭帆派助手
    2) python scripts/gsi_capture.py            # 开始监听
    3) 打开 CS2 打一局死斗(或 console 里 playdemo 某录像),正常游戏
    4) 回到本窗口 Ctrl+C 结束
    5) 产出 tests/fixtures/gsi_captures/gsi_capture_<时间>.jsonl,发给助手生成回归用例

参数:
    --port 3000     监听端口(须与 gamestate_integration_fanpai.cfg 的 uri 端口一致)
    --out  <路径>   输出 jsonl(默认 tests/fixtures/gsi_captures/gsi_capture_<时间>.jsonl)
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "tests" / "fixtures" / "gsi_captures"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server 接口名)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        # CS2 期望 2xx 应答,否则会重试/报错
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.server.out_fp.write(line + "\n")
        self.server.out_fp.flush()
        self.server.frame_count += 1
        if self.server.frame_count % 20 == 0:
            print(f"  已采集 {self.server.frame_count} 帧...", flush=True)

    def log_message(self, *args):  # 静音默认 HTTP 访问日志
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="真机 GSI 采集器")
    ap.add_argument("--port", type=int, default=3000, help="监听端口(须与 GSI cfg 一致)")
    ap.add_argument("--out", default="", help="输出 jsonl 路径(默认自动按时间命名)")
    args = ap.parse_args()

    out_path = (
        Path(args.out)
        if args.out
        else DEFAULT_DIR / f"gsi_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    httpd = HTTPServer(("127.0.0.1", args.port), _Handler)
    httpd.out_fp = out_path.open("w", encoding="utf-8")
    httpd.frame_count = 0

    print("=" * 64)
    print("  帆派助手 — 真机 GSI 采集器")
    print(f"  监听 127.0.0.1:{args.port}    输出 {out_path}")
    print("  现在打开 CS2 游戏(或 playdemo);Ctrl+C 结束采集。")
    print("  注意:需先关闭帆派助手以释放 3000 端口。")
    print("=" * 64)
    t0 = time.time()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.out_fp.flush()
        httpd.out_fp.close()
        dur = time.time() - t0
        print(f"\n采集结束:{httpd.frame_count} 帧 / {dur:.0f}s -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
