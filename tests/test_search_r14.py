# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R14 搜索增强的判据：片段覆盖(S7) + 同义词(S8) + 卡片标题进索引(S9)。

这一轮修的是用户实际打字时暴露的三个洞（2026-08-11 真机反馈）：

1. **中文不分词**——`_tokenize` 只按空格切，中文用户不打空格，于是「准心回正」
   整串是一个 token，页面上那项叫「启用准心快速回正」，不是子串就一分不给。
   实测 22 条常见说法里 9 条召回不全，一半栽在这里。
2. **没有同义词**——界面写「准心」，用户打「准星」；写「灵敏度」，用户打「鼠标速度」。
3. **卡片标题不在索引里**——搜「CFG 同步」「准心快速回正」返回**空**，连跳都跳不过去。

跳转链路那半边在 `test_search_sticky_r14.py` / `test_search_jump_r13.py`
（QA-018 的教训：搜得到 ≠ 跳得到，两条通道要分开量）。
"""
from __future__ import annotations

import ast
import json
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from core.settings_search import (  # noqa: E402
    SYNONYM_GROUPS,
    SYNONYM_PENALTY,
    _cover_len,
    _cover_score,
    _query_variants,
    _score_text,
    search,
    search_detailed,
    text_matches,
)

INDEX = json.loads((ROOT / "core" / "search_index.json").read_text(encoding="utf-8"))
ITEMS = INDEX["items"]


def _pages(query):
    return [r["page_id"] for r in search_detailed(query)]


def _top(query):
    rows = search_detailed(query)
    return rows[0]["page_id"] if rows else None


# ================= S7 片段覆盖：中文查询要能被切开匹配 =================


@pytest.mark.parametrize("query,page_id", [
    ("准心回正", "viewmodel"),        # 改造前：第一位是基础设置页那个孤零零的「准心」
    ("准星回正", "viewmodel"),        # 同上 + 还要过一层同义词
    ("循环切换", "viewmodel"),
    ("同步cfg", "viewmodel"),         # 中英混排，且顺序和界面上是反的
])
def test_fragment_cover_recalls_composed_queries(query, page_id):
    assert page_id in _pages(query), (
        f"「{query}」召回不到 {page_id}，前 3 条是 "
        f"{[(r['page_id'], r['text']) for r in search_detailed(query)[:3]]}"
    )


def test_fragment_cover_demands_most_of_the_query():
    """覆盖率门槛不许调松。

    ⚠ 这条守的是一次实测翻车：门槛设 0.5 时，「锁血提示」被高级设置页的
    「启用游戏内提示」勾走（只对上「提示」两个字，2/4），「准心描边」被
    「准心大小」勾走。**半个查询对得上就算命中，等于把查询里最没信息量的
    那半个字当成了证据。**
    """
    assert _top("锁血提示") == "special_sound"
    top3 = [r["text"] for r in search_detailed("锁血提示")[:3]]
    assert "启用游戏内提示" not in top3, f"「提示」两个字就把它勾出来了: {top3}"
    assert _top("准心描边") == "crosshair"


def test_fragments_do_not_stitch_across_word_boundaries():
    """片段必须**整段**落在同一条文案里，不许东拼西凑。

    「音量心」不是任何设置项，但「音量」和「准心」分别存在——
    如果覆盖算法允许跨文案拼接，它会凭空命中一堆东西。
    """
    assert _cover_len("准心描边", "准心大小") == 2      # 只解释了「准心」
    assert _cover_score("准心描边", "准心大小") == 0    # 2/4 达不到门槛
    assert _cover_len("音量心", "音量设置") == 2       # 「心」在别处，不算


def test_page_level_does_not_use_fragment_cover():
    """页级只认**整词**落在查询里，不做碎片覆盖。

    ⚠ 这条守的是一次实测翻车：试过把一页 40 个关键词拼成一条算片段覆盖，
    结果查「声音太大」时，凡是词表里有任何**含**「声音」的词的页面全部 46 分
    并列涌出——「打死人声音」里的「声音」也算命中，音频体检还反超了基础设置。
    页级词表是**手写别名**，一个词要么整体相关要么不相关；
    项级文案是界面标签，查询本来就该匹配它的一部分。
    两层用不同尺子不是不一致，是因为被量的东西不是一种东西。
    """
    rows = search_detailed("声音太大")
    assert rows and rows[0]["page_id"] == "basic"
    noise = [r["page_id"] for r in rows if r["page_id"] != "basic"]
    assert not noise, f"含「声音」的词表页全被碎片勾出来了: {noise}"


def test_full_coverage_outranks_partial_coverage():
    """满覆盖必须**明显**赢过半覆盖，而不是险胜。

    差距要大到不会被别的因子（主属页加权 1.15/0.75、多词覆盖率折扣）抹平——
    上一轮就是按覆盖字数算、只差 2 分，被加权抹平后排序还是错的。
    """
    full = _score_text("准心回正", "启用准心快速回正")     # 4/4
    part = _score_text("准心回正", "准心")                # 2/4 → 走整词反向子串档
    assert full > part + 5, f"满覆盖 {full} 只比半覆盖 {part} 高一点，排序会被别的因子翻掉"


def test_whole_item_name_inside_a_long_query_still_matches():
    """整项名字落在长查询里的老行为不能被新门槛误伤。

    「观战静音功能」含完整的「观战静音」，覆盖率只有 4/6 < 0.75，
    但那是**实打实的整项名字**，不受碎片门槛约束。
    """
    assert _score_text("观战静音功能", "观战静音") > 0
    assert "basic" in _pages("观战静音功能")


# ================= S8 同义词 =================


@pytest.mark.parametrize("query,page_id", [
    ("准星", "crosshair"),
    ("鼠标速度", "magnifier"),
    ("话筒", "voice_output"),
    ("生命值", "special_sound"),
    ("声音大小", "basic"),
    ("键位", "advanced"),
])
def test_synonym_recall(query, page_id):
    """界面上的词和用户嘴里的词经常不是一个。改造前这几条全是空或错页。"""
    assert page_id in _pages(query), (
        f"同义词「{query}」召回不到 {page_id}: {search_detailed(query)[:3]}")


def test_synonym_never_beats_the_word_the_user_typed():
    """打「crosshair」要到准心设置**页**，不是别处一个恰好叫「准心」的开关。

    ⚠ 这条是 SYNONYM_PENALTY 那个数字的**唯一理由**，改动它必须先过这里：
    变体的精确命中(100)乘完必须低于原词对页面的关键词精确命中(90)。
    penalty=0.94 时 100×0.94=94 > 90，基础设置页那个「准心」开关会顶掉整页。
    """
    assert _top("crosshair") == "crosshair"
    assert 100 * SYNONYM_PENALTY < 90, (
        f"同义词惩罚 {SYNONYM_PENALTY} 太轻：变体精确命中 "
        f"{100 * SYNONYM_PENALTY:.0f} 分会压过原词的页面精确命中 90 分"
    )


def test_synonym_groups_are_symmetric():
    """组内两两互通。写成单向表迟早漏一边（搜 A 能到 B、搜 B 到不了 A）。"""
    for group in SYNONYM_GROUPS:
        assert len(group) >= 2, f"单元素同义词组没有意义: {group}"
        for term in group:
            variants = set(_query_variants(term.lower()))
            for other in group:
                if other.lower() == term.lower():
                    continue
                assert other.lower() in variants, (
                    f"同义词单向了：「{term}」展不出「{other}」")


@pytest.mark.parametrize("term", [g[0] for g in SYNONYM_GROUPS])
def test_synonyms_do_not_flood(term):
    """同义词是拿召回换精度的，不能换过头把结果面板刷满。"""
    rows = search_detailed(term)
    assert len(rows) <= 24, f"「{term}」返回 {len(rows)} 条"
    pages = _pages(term)
    assert len(set(pages)) <= 10, f"「{term}」糊到 {len(set(pages))} 个页面上了"


def test_variant_count_is_bounded():
    """变体数不封顶的话，每多一个就多跑一遍全部档位 × 428 条索引。"""
    from core.settings_search import MAX_QUERY_VARIANTS

    for group in SYNONYM_GROUPS:
        for term in group:
            assert len(_query_variants(term.lower())) <= MAX_QUERY_VARIANTS


# ================= S9 卡片标题进索引 =================


@pytest.mark.parametrize("title,page_id", [
    ("CFG 同步", "viewmodel"),
    ("准心快速回正", "viewmodel"),
    ("准心样式", "crosshair"),
])
def test_card_titles_are_indexed(title, page_id):
    """卡片标题**要**能搜到。

    改造前它们被显式跳过（理由是"由页级+卡片级定位负责"），实测站不住：
    搜「CFG 同步」结果面板是**空的**，连跳都跳不过去。
    去重键是 (page, text)，卡片名和卡内控件名不会撞，"会出重复项"的担心不成立。
    """
    hit = [i for i in ITEMS if i["page"] == page_id and i["text"] == title]
    assert hit, f"卡片标题「{title}」没进索引"
    assert hit[0]["kind"] == "card"
    assert page_id in _pages(title)


def test_card_context_coverage_did_not_regress():
    """card 字段的覆盖面。原来 369 条里 222 条为空——因为只认 `SettingsCard`，
    而准心设置那 28 项走的是页面自己手写的 `_create_card()`，一条都收不到。
    现在按 QSS 不变量（objectName == "card" / "cardTitle"）认，两套都能覆盖。
    """
    with_card = sum(1 for i in ITEMS if i["card"])
    assert with_card >= 200, f"只有 {with_card}/{len(ITEMS)} 条带卡片上下文"
    crosshair = [i for i in ITEMS if i["page"] == "crosshair"]
    assert sum(1 for i in crosshair if i["card"]) >= len(crosshair) // 2, (
        "准心设置页（手写 _create_card）的卡片上下文又丢了")


def test_unsafe_pages_get_card_titles_from_the_static_channel():
    """运行时通道进不去的页（局内视角等），卡片名要由静态通道兜住。

    `SettingsCard.make(...)` 在 AST 里是 Attribute(attr='make')，
    只看 `fn.attr` 会得到 'make' 什么都对不上——全仓 65 处卡片一个没收到。
    """
    skipped = set(INDEX["coverage"]["runtime_skipped"])
    assert skipped, "不安全页名单空了？那这条判据就没在量东西"
    # ⚠ 期望从**源码**里数出来，不是我拍的：music / voice_output 两页压根没用卡片，
    #   硬要求它们有卡片标题，红的是判据不是产品。
    checked = 0
    for pid in sorted(skipped):
        src = (ROOT / "pages" / f"{pid}_page.py").read_text(encoding="utf-8")
        expected = src.count("SettingsCard.make(")
        if not expected:
            continue
        checked += 1
        cards = [i for i in ITEMS if i["page"] == pid and i["kind"] == "card"]
        assert cards, (
            f"{pid}_page.py 里有 {expected} 处 SettingsCard.make，"
            f"索引里一条卡片标题都没有")
    assert checked >= 2, f"只对上 {checked} 个页面，这条判据说明不了问题"


def test_ast_recognizes_the_factory_form():
    """结构性兜底：直接量 AST 归一化函数，别等索引里看不见了才发现。"""
    from build_search_index import _ast_ctor_name

    tree = ast.parse("SettingsCard.make('标题', '说明')\nQCheckBox('开关')\n")
    names = [_ast_ctor_name(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert "SettingsCard" in names, "SettingsCard.make 没被认出来"
    assert "QCheckBox" in names


def test_index_has_no_runtime_status_snapshots():
    """索引里不许有"收割那一刻的状态"。

    「当前样式：十字」这种进了索引就是一份**永远过期**的数据——用户搜「十字」
    跳过去，那儿写的可能是「圆圈」。中点复合文案（99 条）上一轮已经挡掉，
    这一轮补上「标签：值」这一种。
    """
    labeled = [i["text"] for i in ITEMS if re.search(r"[:：]\s*\S", i["text"])]
    dotted = [i["text"] for i in ITEMS if re.search(r"[·・]", i["text"])]
    assert not labeled, f"「标签：值」型状态快照：{labeled}"
    assert not dotted, f"中点复合状态文案：{dotted}"


def test_status_filter_is_measured_on_the_function_not_only_the_artifact():
    """直接量 `normalize()` 这个纯函数。

    ⚠ 上面那条读的是**产物** JSON。产物是离线生成的（跑一次 6 分钟），
    所以回退验证把生成器改坏时，磁盘上的 JSON 一个字都不会变——上面那条**照样绿**。
    这类"判据量的是快照、改了源头也不红"的假绿，登记册里已经记过四种错法。
    这条补上：判据和被改的代码之间要有一条**当场生效**的路径。
    """
    from build_search_index import normalize

    for snapshot in ("当前样式：十字", "当前权限：普通用户", "任务历史: 0 条",
                     "GSI · 未运行", "音频 · 需检查13"):
        assert normalize(snapshot) == "", f"状态快照没被挡掉: {snapshot}"
    # 反向：稳定的字段名和真设置项不许误伤
    for keep in ("当前风格：", "启用准心快速回正", "CFG 同步", "切换间隔(秒)"):
        assert normalize(keep), f"真设置项被误杀: {keep}"


# ================= 跨层：搜得到就必须定位得到 =================


@pytest.mark.parametrize("query,text", [
    ("准星", "启用准心快速回正"),      # 同义词
    ("准心回正", "启用准心快速回正"),   # 片段覆盖
    ("话筒", "麦克风"),
])
def test_locator_agrees_with_the_engine(query, text):
    """下拉里搜到的，跳过去必须也能在页面上定位到那一行。

    ⚠ QA-018 的直接应用：`text_matches`（页内定位）和 `search_*`（下拉）
    是两条通道。只要它们用的不是同一套匹配规则，就会出现
    "下拉里有、跳过去什么也没高亮"——而两边各自的判据都是绿的。
    """
    assert search_detailed(query), f"引擎搜不到「{query}」，这条判据前提就不成立"
    assert text_matches(query, text), (
        f"下拉能搜到「{query}」，但页内定位器认不出「{text}」")


BUDGET_QUERIES = ("准星", "准心快速回正", "zx", "音量 大小", "开机自启动怎么关")

#: 每条查询量 BUDGET_ROUNDS 批、每批 BUDGET_REPEATS 次，**取最好的一批**。
#:
#: 为什么不取均值：原来这条判据取的是一批 30 次的均值，本机实测 1~3ms、
#: 阈值 12ms，看着余量很大。2026-08-12 它在 GitHub 的共享 runner 上量到
#: **31.5ms 把 CI 打红**，而那次提交一行搜索代码都没碰（改的是图标和品牌图）。
#:
#: 均值对**偶发调度停顿**极其敏感：共享 runner 上别人的作业抢一次 CPU，
#: 30 次里有一次卡住，均值就能翻十倍。最小值不受这个影响 ——
#: "最快能跑多快"才是这台机器的真实算力，而真的性能回归会把最小值一起抬上去。
#: ⇒ **墙钟预算类判据一律取多批的最小值，不要取均值。**
BUDGET_ROUNDS = 5
BUDGET_REPEATS = 30

#: 单次搜索的上限（毫秒）。沿用原值，这次只改统计口径、不动松紧。
#:
#: ⚠ 已知它偏松：实测把 `_grams` 和 `_query_variants` 两个热路径缓存全拆掉，
#: 最坏查询也只到 10.05ms，仍在 12ms 以内 —— 也就是说 **2.7 倍的回归它抓不住**，
#: 它守的确实只是"别再涨一个量级"。要收紧得先拿到 runner 上的干净基线，
#: 否则容易换成另一种抖。
SEARCH_BUDGET_MS = 12.0


def _search_batch_ms(query: str) -> float:
    t0 = time.perf_counter()
    for _ in range(BUDGET_REPEATS):
        search_detailed(query)
    return (time.perf_counter() - t0) / BUDGET_REPEATS * 1000


def test_search_stays_within_frame_budget():
    """每按一次键跑一次。同义词层是拿时间换召回的，得有个上限盯着。

    基线（无同义词/无覆盖层）0.25ms，现在 1~3ms，换来 22 条常见说法
    从 13 条召回全变成 22 条全召回。这里守的是"别再涨一个量级"。

    统计口径为什么是"多批取最小"，见 `BUDGET_ROUNDS` 的说明。
    """
    worst = 0.0
    slowest_query = ""
    for query in BUDGET_QUERIES:
        search_detailed(query)                   # 预热 lru_cache
        best = min(_search_batch_ms(query) for _ in range(BUDGET_ROUNDS))
        if best > worst:
            worst, slowest_query = best, query
    assert worst < SEARCH_BUDGET_MS, (
        f"最慢的查询「{slowest_query}」要 {worst:.1f}ms，一帧都放不下了"
    )


def test_legacy_search_signature_still_works():
    """`search()` 是页内定位等处的旧接口，签名不能变。"""
    out = search("准星")
    assert out and isinstance(out[0], tuple) and len(out[0]) == 3
    assert len({pid for pid, _n, _h in out}) == len(out), "旧接口应该按页去重"
