# -*- coding: utf-8 -*-
"""R13 索引与代码的同步判据（快档，2026-08-10）。

`core/search_index.json` 是**离线生成**的。页面上的控件文案改了而没重跑生成器，
索引就会悄悄过期：新开关搜不到、被删掉的项搜得到却跳过去什么也没有。
这类漂移不会报错，只会让搜索一天天变差 —— 正是需要判据钉住的形状。

**分两档，这里是快档**：只跑静态 AST 通道（不建 Qt 窗口，<1 秒），
能逮住"源码里新写了一个 `QCheckBox("…")` 但没重跑生成器"。

**慢档在生成器自己身上**：`python scripts/build_search_index.py --check`
会把两条通道都跑一遍再逐字节比对，能连工厂构建的控件一起管。
它要建 26 个页面（约 4 分钟），不适合进每次跑的测试集 ——
所以这里如实写清楚：**本文件只覆盖静态那一半，不是全覆盖。**
（UP-096 的教训：任何"某维度全绿"的结论，先说清楚分母是多少。）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

INDEX_PATH = ROOT / "core" / "search_index.json"


def _index():
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def test_static_channel_items_are_all_in_the_index():
    """静态通道现在收到的每一条，索引里都得有。"""
    from build_search_index import harvest_static, merge

    data = _index()
    page_names = data["pages"]
    fresh, _covered = harvest_static(page_names)

    # 索引是合并 + 文档频率过滤之后的结果，所以比对时要套同一把过滤尺子，
    # 否则被当成通用词丢掉的（"AWP" 之类）会被误报成"漏了"。
    dropped = set(data.get("generic_dropped", []))
    want = {(it["page"], it["text"]) for it in fresh if it["text"] not in dropped}
    have = {(it["page"], it["text"]) for it in data["items"]}
    missing = sorted(want - have)
    assert not missing, (
        f"源码里有这些设置项，索引里没有（共 {len(missing)} 条，改了页面文案就要重跑 "
        f"scripts/build_search_index.py）：{missing[:10]}"
    )
    assert merge is not None


def test_index_pages_match_navigation():
    """索引声明的页面表必须与导航表一致——多一页少一页都说明索引过期了。"""
    from core.settings_search import SEARCH_INDEX

    data = _index()
    assert set(data["pages"]) == {pid for pid, _n, _w in SEARCH_INDEX}


def test_index_declares_its_own_coverage_honestly():
    """索引必须自带覆盖面自述，且两条通道合起来不留白。"""
    data = _index()
    cov = data["coverage"]
    union = set(cov["runtime_pages"]) | set(cov["static_pages"])
    assert union == set(data["pages"]), (
        f"这些页两条通道都没覆盖到：{sorted(set(data['pages']) - union)}"
    )
    assert cov["total_pages"] == len(data["pages"])
    # 运行时跳过的页必须真的被静态通道兜住，不能只是"跳过了"就算数
    for pid in cov["runtime_skipped"]:
        assert pid in cov["static_pages"], f"{pid} 运行时跳过了，静态通道也没兜住"


def test_noise_filters_are_actually_doing_something():
    """过滤器不能是摆设：真给它脏输入，必须真的被挡掉。

    行为判据而不是结构判据——断言"函数里有那个正则"会被一句
    `return s` 骗过（登记册那条教训）。
    """
    from build_search_index import normalize

    for dirty in ("GSI · 未运行", "音频 · 需检查13", "0.3秒", "150ms",
                  "保存", "使用说明", "⚠️ 出错了", "先勾选要打包的模块，范围越清晰"):
        assert normalize(dirty) == "", f"这条脏文案没被挡住: {dirty!r}"
    for clean in ("观战静音", "原声保留", "启用回合音效", "按地图切换预设"):
        assert normalize(clean) == clean, f"这条正常设置项被误杀了: {clean!r}"
