# -*- coding: utf-8 -*-
"""R1-2 设置搜索拼音层:全拼/首字母命中、降级安全、通用匹配器。"""
import pytest

from core.settings_search import pinyin_aliases, search, text_matches


def _top_page(query):
    results = search(query)
    return results[0][0] if results else None


def test_pinyin_engine_available():
    # CI/本机都应装了 pypinyin;若降级,后续用例会暴露
    assert pinyin_aliases("准心") != ()


@pytest.mark.parametrize(
    "query,expected_page",
    [
        ("zx", "crosshair"),        # 首字母 → 准心
        ("zhunxin", "crosshair"),   # 全拼 → 准心
        ("jsyx", "kill_sound"),     # 击杀音效
        ("yinyue", "music"),        # 音乐播放
        ("yueqiang", "switch_weapon"),  # 切枪(关键词"切枪"qieqiang? 用别名验证)
    ],
)
def test_pinyin_query_hits_expected_page(query, expected_page):
    if query == "yueqiang":
        pytest.skip("占位:见下方专用用例")
    assert _top_page(query) == expected_page


def test_pinyin_initials_qieqiang():
    assert _top_page("qq") in ("switch_weapon", "crosshair", "music", "kill_sound", "viewmodel", "utility")
    assert _top_page("qieqiang") == "switch_weapon"


def test_chinese_exact_still_wins_over_pinyin():
    # 中文直击权重必须不低于拼音
    assert _top_page("准心") == "crosshair"
    assert _top_page("音乐") == "music"


def test_short_ascii_does_not_flood():
    # 单字母不应产生 contains 级泛滥(只允许 startswith 档)
    results = search("z")
    assert len(results) <= 12


def test_text_matches_for_card_titles():
    assert text_matches("zx", "准心样式")
    assert text_matches("yanse", "准心颜色")
    assert text_matches("颜色", "准心颜色")
    assert not text_matches("xyz", "准心颜色")
    assert not text_matches("", "准心颜色")


def test_search_empty_and_garbage_safe():
    assert search("") == []
    assert search("   ") == []
    assert isinstance(search("!!!###"), list)


# ---- 2.2.1 增强：拼写容错 / 反向子串 / 多词 / 口语模糊 ----

def _top(query):
    r = search(query)
    return r[0][0] if r else None


@pytest.mark.parametrize("query,page", [
    ("zunxin", "crosshair"),     # 拼写漏字母(缺h)
    ("zhunxn", "crosshair"),     # 拼写漏字母(缺i)
    ("dukcing", "gun_sound"),    # 英文打错 ducking
])
def test_typo_tolerance(query, page):
    assert _top(query) == page


@pytest.mark.parametrize("query,page", [
    ("声音太大", "basic"),         # 反向子串: 长句含"声音"
    ("血少提醒", "special_sound"),  # 反向子串: 含"血少"
    ("看不见准星", "crosshair"),
    ("变声", "voice_output"),
    ("换肤", "advanced"),
    ("狙击镜", "magnifier"),
    ("烟怎么扔", "utility"),
])
def test_colloquial_vague_queries(query, page):
    assert _top(query) == page


def test_multi_word_query():
    assert _top("准心 颜色") == "crosshair"
    assert _top("音乐 联动") == "music"


def test_enhanced_no_flood():
    # 增强后短查询仍不泛滥
    assert len(search("z")) <= 12
    assert len(search("a")) <= 12
