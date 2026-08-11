# -*- coding: utf-8 -*-
"""匿名使用统计客户端(R3-3,2026-06-12)。

原则(与崩溃上报同一套价值观):
- **默认关闭**,高级设置里明示开启;
- 上报内容用户可一键查看(高级设置「查看将上报的内容」);
- 白名单字段:安装ID哈希 / 版本 / 各页打开计数 / 少量功能开关位。
  无账号、无昵称、无系统标识、无文件路径;
- 24h 最多发一条;404/网络失败静默放弃,绝不打扰。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, Optional

import requests

from config import VERSION, config
from service_urls import TELEMETRY_BASE_URL

# 同 crash_reporter：开源版默认为空端点，上报短路。见 service_urls.py 的说明。
USAGE_REPORT_API_URL = f"{TELEMETRY_BASE_URL}/api/usage_report.php" if TELEMETRY_BASE_URL else ""
MIN_INTERVAL_SECONDS = 24 * 3600


def ensure_install_id() -> str:
    """惰性生成匿名安装 ID(uuid4 的 hex,与任何账号/硬件无关)。"""
    iid = str(getattr(config, "usage_install_id", "") or "")
    if len(iid) < 8:
        iid = uuid.uuid4().hex
        config.usage_install_id = iid
        config.save_config()
    return iid


def build_payload() -> Dict:
    """组装上报体——这也是「查看将上报的内容」展示的同一份数据。"""
    from core.page_usage_tracker import _load  # 本地统计文件

    page_opens = {}
    for pid, entry in _load().items():
        if isinstance(entry, dict):
            page_opens[str(pid)] = int(entry.get("count", 0))

    switches = {
        "crosshair": bool(getattr(config, "crosshair_enabled", False)),
        "magnifier": bool(getattr(config, "magnifier_enabled", False)),
        "flash": bool(getattr(config, "flash_enabled", False)),
        "osd": bool(getattr(config, "osd_enabled", True)),
        "map_preset": bool(getattr(config, "map_preset_enabled", False)),
        "nav_frequent": bool(getattr(config, "nav_frequent_enabled", True)),
        "expert_mode": bool(getattr(config, "ui_expert_mode", False)),
    }
    return {
        "install_id": ensure_install_id(),
        "version": str(VERSION),
        "page_opens": page_opens,
        "switches": switches,
    }


def should_send(now: Optional[float] = None) -> bool:
    if not bool(getattr(config, "usage_report_enabled", False)):
        return False
    last = float(getattr(config, "usage_last_sent_ts", 0) or 0)
    return (float(now or time.time()) - last) >= MIN_INTERVAL_SECONDS


def send_usage_report(timeout: int = 8) -> Optional[bool]:
    """发送一次。True=成功 False=失败 None=接口未部署(404)/未配置端点。"""
    # 同 crash_reporter：开源版默认无端点，构造请求前短路（理由见那边的注释）。
    if not USAGE_REPORT_API_URL:
        return None
    try:
        resp = requests.post(
            USAGE_REPORT_API_URL,
            json=build_payload(),
            timeout=timeout,
            headers={"User-Agent": "FanToolDesktop/2.1"},
        )
        if resp.status_code == 404:
            return None
        if resp.ok:
            config.usage_last_sent_ts = time.time()
            config.save_config()
            return True
        return False
    except requests.RequestException:
        return False


def schedule_startup_report(delay_seconds: int = 60) -> Optional[threading.Thread]:
    """启动后延迟发送(后台线程,不阻塞 UI;未开启则不起线程)。"""
    if not should_send():
        return None

    def _worker():
        time.sleep(max(1, delay_seconds))
        if should_send():
            send_usage_report()

    t = threading.Thread(target=_worker, name="UsageReport", daemon=True)
    t.start()
    return t
