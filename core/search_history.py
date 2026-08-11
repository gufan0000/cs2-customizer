# -*- coding: utf-8 -*-
"""最近搜索记录（S5，2026-08-10）。

搜索框空着的时候不该是一片空白 —— 用户上次搜过什么、常去哪几页，
本来就是最好的入口。这里只存**最近成功跳转过的查询词**，纯本地、不上报。

刻意做得比 `page_usage_tracker` 简单：写入频率极低（只在用户真的跳转时写一次），
不需要去抖，也不需要缓存 + mtime 校验。但**原子写盘**照抄——半截 JSON
会让下次启动读不出历史，那是白丢数据。
"""
from __future__ import annotations

import json
import os
import threading
from typing import List

from config import get_app_data_dir

MAX_ENTRIES = 8
# 太短的查询存下来没意义（用户下次不会想点"a"），太长的多半是误粘贴
_MIN_LEN, _MAX_LEN = 2, 40

_lock = threading.RLock()


def _store_path() -> str:
    d = get_app_data_dir("usage")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "search_history.json")


def _read() -> List[str]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return [str(x) for x in data if isinstance(x, str)]
    except Exception:
        pass
    return []


def _write(items: List[str]) -> None:
    """原子写：先临时文件再 os.replace（同 page_usage_tracker 的理由）。"""
    path = _store_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        # 历史记录失败绝不影响搜索本身


def record(query: str) -> None:
    """记一条最近搜索（去重后置顶）。"""
    q = str(query or "").strip()
    if not (_MIN_LEN <= len(q) <= _MAX_LEN):
        return
    with _lock:
        items = [x for x in _read() if x != q]
        items.insert(0, q)
        _write(items[:MAX_ENTRIES])


def recent(n: int = 5) -> List[str]:
    with _lock:
        return _read()[:max(0, n)]


def clear() -> None:
    """清空（给"重置设置"和测试用）。"""
    with _lock:
        _write([])
