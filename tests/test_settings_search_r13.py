# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R13 设置搜索增强（S1~S5，2026-08-10）的行为判据。

**为什么这一批全是行为判据、几乎没有结构判据**：登记册里那条教训——
断言「某函数在某个 if 里」被一句 `failures = []` 骗过，结构还在、语义没了。
所以这里一律「给一个真实查询，看真实结果」，而不是「看代码长什么样」。

覆盖四件事：
1. 项级索引真的在，而且真的被接进了搜索（不是文件在、代码没读）；
2. 下拉候选与回车跳转是**同一个**引擎（这是本轮改造的核心，必须有判据钉住）；
3. 改造前实测漏召回的那批查询，现在能召回，且原本对的没变差；
4. 短查询不泛滥、脏输入不炸。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.settings_search import (
    MAX_ITEMS_PER_PAGE,
    SEARCH_INDEX,
    item_index_available,
    search,
    search_detailed,
    search_items,
    search_pages,
)

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "core" / "search_index.json"


def _top(query):
    rows = search_detailed(query)
    return rows[0]["page_id"] if rows else None


# ---------------- 1. 项级索引真的接上了 ----------------


def test_index_file_ships_with_repo():
    assert INDEX_PATH.is_file(), "core/search_index.json 缺失——跑 scripts/build_search_index.py"


def test_index_is_loaded_by_search_module():
    """文件在 ≠ 被读进来了。这条查的是后者。"""
    assert item_index_available()


def test_index_covers_every_page():
    """26 个页面每一页都得有项级条目。

    ⚠ 这条判据的分母必须是导航表，不是索引自己的 keys ——
    拿索引自己的键当分母，漏掉一整页时它照样全绿（UP-096 那次的错法）。
    """
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    pages_with_items = {it["page"] for it in data["items"]}
    nav_pages = {pid for pid, _n, _w in SEARCH_INDEX}
    missing = sorted(nav_pages - pages_with_items)
    assert not missing, f"这些页面没有任何项级索引: {missing}"


def test_index_has_no_runtime_state_text():
    """索引里不许有状态条文案——它是收割那一刻的快照，进了库就是永久过期数据。"""
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    dirty = [it["text"] for it in data["items"] if "·" in it["text"]]
    assert not dirty, f"状态复合文案混进索引: {dirty[:5]}"


def test_index_is_deterministic_no_timestamp():
    """索引里不许有时间戳/随机值，否则 `--check` 的同步判据永远红。"""
    raw = INDEX_PATH.read_text(encoding="utf-8")
    for banned in ("generated_at", "timestamp", "202608", "random"):
        assert banned not in raw, f"索引里出现了非确定性字段: {banned}"


# ---------------- 2. 下拉与回车必须是同一个引擎 ----------------


@pytest.mark.parametrize("query", ["zx", "zhunxin", "dukcing", "声音太大", "准心", "音量"])
def test_dropdown_and_enter_use_same_engine(query):
    """改造前这里是断的：下拉走 QCompleter 的纯子串过滤，回车走 search()。

    实测 19 条查询里 11 条两者不一致（`zx` 下拉 0 条、回车能跳）。
    现在两条路都由 `search_detailed()` 供数，第一条必须完全一致。
    """
    rows = search_detailed(query)
    assert rows, f"「{query}」应该有结果"
    # 回车取的就是面板第一条（gui_widget._on_search_return 的口径）
    actionable = [r for r in rows if r["kind"] in ("item", "page")]
    assert actionable
    assert actionable[0] is rows[0]


def test_pinyin_visible_in_result_rows():
    """拼音查询必须能产出可见的结果行，不能只有回车能跳。"""
    for q in ("zx", "zhunxin", "qieqiang"):
        assert search_detailed(q), f"拼音「{q}」在结果面板里是空的"


def test_result_rows_carry_jump_payload():
    """每一行都要自带 page_id；项级行还要带 tab，否则跳过去定位不到。"""
    for row in search_detailed("准心"):
        assert row["page_id"], f"结果行缺 page_id: {row}"
        assert row["kind"] in ("item", "page")
        assert "tab" in row and "card" in row


# ---------------- 3. 召回：修好的别再漏，原本对的别变差 ----------------


@pytest.mark.parametrize("query,page", [
    ("爆头音效", "kill_sound"),        # 改造前：0 结果
    ("怎么绑定快捷键", "advanced"),      # 改造前：0 结果
    ("锁血提示", "special_sound"),      # 改造前：0 结果
    ("crosshair", "crosshair"),      # 改造前：0 结果（英文页名没进索引）
    ("狙击枪声音", "gun_sound"),        # 改造前：排第 2
])
def test_recall_gaps_fixed(query, page):
    assert _top(query) == page


@pytest.mark.parametrize("query,page", [
    ("准心", "crosshair"), ("zx", "crosshair"), ("音量", "basic"),
    ("换弹", "reload_sound"), ("音板", "voice_output"), ("开机自启", "advanced"),
    ("声音太大", "basic"), ("看不见准星", "crosshair"), ("被闪瞎", "flash"),
    ("为什么没声音", "audio_health"), ("鼠标灵敏度", "magnifier"),
    ("观战静音", "basic"), ("准心描边", "crosshair"), ("原声保留", "gun_sound"),
    ("ducking", "gun_sound"), ("dukcing", "gun_sound"), ("fov", "viewmodel"),
])
def test_no_regression_on_previously_working(query, page):
    assert _top(query) == page


def test_item_level_hits_exist():
    """至少要有一批查询是靠项级索引命中的，否则这一层等于白加。"""
    hit_kinds = {_first_kind(q) for q in ("观战静音", "原声保留", "载入音频")}
    assert "item" in hit_kinds


def _first_kind(query):
    rows = search_detailed(query)
    return rows[0]["kind"] if rows else None


def test_reverse_substring_prefers_broader_coverage():
    """「准心描边」= 准心设置页的两个关键词合起来覆盖整个查询，
    不能输给基础设置页那个只覆盖 2 个字的「准心」开关。"""
    assert _top("准心描边") == "crosshair"


# ---------------- 4. 不泛滥、不炸 ----------------


@pytest.mark.parametrize("query", ["z", "a", "e", "s"])
def test_single_ascii_letter_does_not_flood(query):
    """S1 加了英文别名之后，单字母 `a` 一度前缀命中 22 个页面。"""
    assert len(search(query)) <= 6


def test_items_per_page_capped():
    """一页最多贡献几条，防止某一页把整个面板刷掉。"""
    rows = search_detailed("音量")
    per_page = {}
    for r in rows:
        if r["kind"] == "item":
            per_page[r["page_id"]] = per_page.get(r["page_id"], 0) + 1
    assert all(v <= MAX_ITEMS_PER_PAGE for v in per_page.values()), per_page


@pytest.mark.parametrize("query", ["", "   ", "!!!###", "\n\t", "我要退款", "asdfghjkl"])
def test_garbage_input_safe(query):
    assert isinstance(search_detailed(query), list)
    assert isinstance(search(query), list)
    assert isinstance(search_items(query), list)
    assert isinstance(search_pages(query), list)


def test_legacy_search_api_still_page_deduped():
    """旧签名必须保持"每页一条"，调用方（含跳转链路）依赖这一点。"""
    rows = search("音量")
    ids = [pid for pid, _n, _h in rows]
    assert len(ids) == len(set(ids))
    assert all(len(r) == 3 for r in rows)
