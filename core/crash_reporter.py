# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""崩溃日志自愿上报（P3.2，2026-06-10）。

原则：
- **绝不自动上传**——发现新崩溃日志后询问用户，用户可"发送/本次不发/不再询问"。
- 预览和上传共用脱敏、限长处理；上报内容为堆栈文本 + 版本号。
- 后端接口未部署（404）或网络失败时静默放弃，日志仍保留在本地。

后端接口约定（/api/crash_report.php，POST JSON）：
  请求: {"version": "2.1.4", "client_ts": 1760000000, "report": "<纯文本堆栈>"}
  成功: {"status": "ok"}
  建议后端限频（如每 IP 每小时 10 条）、限长（64KB）、仅存文本。
"""
from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import List, Optional

import requests
from core.utils.log_filter import redact_text

from service_urls import TELEMETRY_BASE_URL

# 开源版默认 TELEMETRY_BASE_URL="" → 端点为空 → 下面的上报直接短路，一个字节都不外发。
# 这样 fork 出去的客户端不会继续打上游作者的服务器；自建服务端的人填上基址即可启用。
CRASH_REPORT_API_URL = f"{TELEMETRY_BASE_URL}/api/crash_report.php" if TELEMETRY_BASE_URL else ""
MAX_REPORT_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 96 * 1024


def prepare_report_text(text: str) -> str:
    """预览与上传使用同一份脱敏文本，同时按 JSON 转义后的大小限长。"""
    text = redact_text(str(text or ""))
    text = text.encode("utf-8")[:MAX_REPORT_BYTES].decode("utf-8", errors="ignore")
    budget = MAX_REQUEST_BYTES - 1024  # 版本、时间戳和字段名
    if len(json.dumps(text, ensure_ascii=False).encode("utf-8")) > budget:
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if len(json.dumps(text[:mid], ensure_ascii=False).encode("utf-8")) <= budget:
                low = mid
            else:
                high = mid - 1
        text = text[:low]
    return text


def _crash_log_dir() -> Path:
    appdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        return Path(appdata) / "CS2Customizer" / "logs"
    return Path("logs")


def find_new_crash_logs(since_epoch: float) -> List[Path]:
    """返回 mtime 晚于 since_epoch 的 bootstrap_crash_*.log，按时间升序。"""
    log_dir = _crash_log_dir()
    if not log_dir.is_dir():
        return []
    found = []
    try:
        for p in log_dir.glob("bootstrap_crash_*.log"):
            try:
                if p.stat().st_mtime > float(since_epoch or 0):
                    found.append(p)
            except OSError:
                continue
    except OSError:
        return []
    return sorted(found, key=lambda p: p.stat().st_mtime)


def read_report_text(paths: List[Path]) -> str:
    """合并读取崩溃日志文本，整体截断到 MAX_REPORT_BYTES。"""
    parts = []
    remaining = MAX_REPORT_BYTES
    for p in paths:
        if remaining <= 0:
            break
        try:
            with p.open("rb") as handle:
                raw = handle.read(remaining)
            remaining -= len(raw)
            parts.append(f"===== {p.name} =====\n" + raw.decode("utf-8", errors="replace"))
        except OSError:
            continue
    return prepare_report_text("\n\n".join(parts))


def send_crash_report(report_text: str, version: str, timeout: int = 8) -> Optional[bool]:
    """上传崩溃报告。

    返回 True=成功；False=失败（网络/服务端错误）；None=后端未部署接口(404)/未配置端点。
    """
    # 开源版默认没有端点。这里必须在**构造请求之前**短路——
    # 空 URL 交给 requests 会抛 MissingSchema，那是异常路径不是"没配置"，
    # 语义不同，且会在日志里留下看着像故障的噪音。
    if not CRASH_REPORT_API_URL:
        return None
    try:
        payload = json.dumps({
            "version": str(version)[:64],
            "client_ts": int(time.time()),
            "report": prepare_report_text(report_text),
        }, ensure_ascii=False).encode("utf-8")
        resp = requests.post(
            CRASH_REPORT_API_URL,
            data=payload,
            timeout=timeout,
            headers={"User-Agent": "CS2CustomizerDesktop/2.1", "Content-Type": "application/json; charset=utf-8"},
        )
        if resp.status_code == 404:
            return None
        if resp.ok:
            return True
        return False
    except requests.RequestException:
        return False
