# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面使用频次追踪(R1-6,2026-06-12)。

给侧栏「常用」分组供数:本地 JSON 记录每页打开次数与最近使用时间,
排序 = 次数 × 时间衰减(14 天半衰期)。纯本地,不上报任何数据。

借鉴 utility_usage_tracker 的成熟模式;独立成模块避免把"道具瞄点统计"
和"页面统计"耦在一起。
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Dict, List

from config import get_app_data_dir

# 这些页不进「常用」:basic 是首页本就置顶;about 无复访价值
EXCLUDED_PAGES = {"basic", "about"}

_HALF_LIFE_DAYS = 14.0


def _store_path() -> str:
    d = get_app_data_dir("usage")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "page_usage.json")


# ==================== 内存缓存 + 去抖落盘（UP-016）====================
# 原先每次切页都在点击帧同步「读一次 JSON + 写一次 JSON」。切页本就是用户
# 最敏感的交互,不该在那一帧碰磁盘。现在:进程内缓存一次读取,写入去抖 5 秒,
# 并在退出时兜底 flush。统计精度不受影响(计数与时间戳都在内存里先更新)。
_cache: Dict[str, Dict] | None = None
_cache_mtime: float = -1.0
_dirty = False
_flush_timer = None
_FLUSH_DELAY_S = 5.0
# 去抖落盘跑在 threading.Timer 线程上,而 record_page_open 在 GUI 线程改同一个
# dict——不加锁的话,flush 里 json.dump 遍历到一半被插入新键会抛 RuntimeError
# (dictionary changed size during iteration),线程里抛出去就是静默丢数据,
# 更糟的是可能写出半截 JSON 把统计文件写坏。
_lock = threading.RLock()


def _read_from_disk() -> Dict[str, Dict]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _disk_mtime() -> float:
    try:
        return os.path.getmtime(_store_path())
    except Exception:
        return -1.0


def _load() -> Dict[str, Dict]:
    """取统计数据（调用方必须已持有 _lock）。

    缓存 + mtime 校验:省掉每次切页的 JSON 解析,但文件被外部改动(测试夹具、
    手工编辑、配置恢复)时仍能读到新内容——语义与改造前一致。
    一次 stat() 的成本相对 JSON 解析可忽略。
    """
    global _cache, _cache_mtime
    mtime = _disk_mtime()
    if _cache is None or (not _dirty and mtime != _cache_mtime):
        _cache = _read_from_disk()
        _cache_mtime = mtime
    return _cache


def _write_to_disk(data: Dict[str, Dict]) -> None:
    """原子写盘：先写临时文件再 os.replace 替换。

    原先是 open(path, "w") 直接截断再写——写到一半被打断(退出看门狗 os._exit、
    断电、异常)就会留下半截 JSON,下次启动 json.load 失败返回 {},用户的「常用」
    分组与预载顺序全部清零。os.replace 在同一分区上是原子的,要么旧的要么新的。
    """
    path = _store_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        # 统计失败绝不影响主流程


def _save(data: Dict[str, Dict]) -> None:
    """立即落盘(测试/重置用)。日常写入请走 _schedule_flush。"""
    global _cache, _dirty, _cache_mtime
    with _lock:
        _cache = data
        _dirty = False
        snapshot = dict(data)
    _write_to_disk(snapshot)
    with _lock:
        _cache_mtime = _disk_mtime()


def flush() -> None:
    """把待写数据落盘。退出链路应调用一次,避免丢掉最后几次统计。

    会先取消挂起的去抖 Timer:退出链路有看门狗(超时 os._exit),让一个 daemon
    Timer 在那之后才醒过来写盘,写到一半被切断就白搭——干脆在这里同步写完。

    这个函数会被 threading.Timer 线程调用,而 GUI 线程同时可能在 record_page_open
    里改 _cache。所以先在锁内做一份浅拷贝快照再写盘——直接把活字典交给 json.dump
    遍历,遇到并发插入会抛 RuntimeError(dict changed size during iteration),
    在 Timer 线程里就是静默丢数据,严重时还会写出半截 JSON 把统计文件写坏。
    """
    global _dirty, _cache_mtime, _flush_timer
    with _lock:
        try:
            if _flush_timer is not None:
                _flush_timer.cancel()
                _flush_timer = None
        except Exception:
            pass
        if not _dirty or _cache is None:
            return
        snapshot = dict(_cache)
        _dirty = False
    _write_to_disk(snapshot)
    with _lock:
        _cache_mtime = _disk_mtime()


def _schedule_flush() -> None:
    """去抖落盘:5 秒内的连续切页只写一次。调用方必须已持有 _lock。"""
    global _flush_timer
    try:
        if _flush_timer is not None:
            _flush_timer.cancel()
        _flush_timer = threading.Timer(_FLUSH_DELAY_S, flush)
        _flush_timer.daemon = True
        _flush_timer.start()
    except Exception:
        flush()  # 起不了定时器就直接写,别把数据丢了


def record_page_open(page_id: str) -> None:
    global _dirty
    pid = str(page_id or "")
    if not pid or pid in EXCLUDED_PAGES:
        return
    with _lock:
        data = _load()
        entry = data.get(pid) or {"count": 0, "last_used": 0.0}
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_used"] = time.time()
        data[pid] = entry
        _dirty = True
        _schedule_flush()


def _score(entry: Dict) -> float:
    count = max(0, int(entry.get("count", 0)))
    last = float(entry.get("last_used", 0.0) or 0.0)
    age_days = max(0.0, (time.time() - last) / 86400.0)
    decay = math.pow(0.5, age_days / _HALF_LIFE_DAYS)
    return count * decay


def top_pages(n: int = 4, known_pages=None) -> List[str]:
    """返回得分最高的 n 个页面 id;known_pages 给定时过滤掉已下线的页。"""
    with _lock:
        data = dict(_load())  # 拷贝一份再算分,避免遍历途中被并发改动
    items = [
        (pid, _score(entry))
        for pid, entry in data.items()
        if pid not in EXCLUDED_PAGES and isinstance(entry, dict)
    ]
    if known_pages is not None:
        known = set(known_pages)
        items = [(pid, s) for pid, s in items if pid in known]
    items = [(pid, s) for pid, s in items if s > 0.01]
    items.sort(key=lambda t: -t[1])
    return [pid for pid, _ in items[:n]]


def reset() -> None:
    """清空统计(给测试/重置设置用)。

    必须先取消待写的去抖 Timer,否则"重置所有设置"之后 5 秒,那个 Timer 会把
    重置前的旧数据又写回磁盘。
    """
    global _flush_timer
    with _lock:
        try:
            if _flush_timer is not None:
                _flush_timer.cancel()
                _flush_timer = None
        except Exception:
            pass
    _save({})
