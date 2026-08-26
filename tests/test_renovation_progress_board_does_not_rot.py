# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-408：**页面清单与进度**这份文件只在开工时被读，从不在收工时被写。

## 它烂成什么样（2026-08-26 实测）

翻新工程的纪律里，这份文件是**开工三读**的第二读（总纲 → 页面清单 → 当页档案）。
而**收工六件套**里没有它（档案 / 登记册 / 外审台账 / 提交 / CI / 同步面）。

于是：

| 实况 | 后果 |
|---|---|
| 最后一次改动早于批 9 与批 10 落地 | 里面**没有批 9、没有批 10 的任何记录** |
| `crosshair` 那一行仍写着「排在批 10，**做完即关档**」 | 批 10 做完了，而 RN-406（**S2 功能缺陷**）挂在这一页上 ⇒ **这句话今天是假的** |
| M3 看板仍写「剩 crosshair / kill_icon / hud_color」 | 下一轮开工的人（包括我）照着一份过期的地图排工 |

⭐⭐ **一份只在开工时读、从不在收工时写的文件，必然腐烂 ——
而且腐烂的正是下一个人开工要读的那一份。**

⚠ 根因不是"忘了"。RN-198 给登记册配棘轮时，写下的话是
「制度自己漏了一项时，遵守它的人不会自动补上」；四天后同一件事换了个文件又发生一次。
⭐ **一个教训只修在它被发现的那条通路上，等于只修了一份副本。**

## 这几条判据分别看得见什么（⭐ 分母要说清楚，别假装全覆盖）

- `every_batch_the_registry_tagged_has_a_row`：**零噪声，跨文件对账**。
  批号从登记册的**状态格**里读（`已结（…）·批 9`），不从行文里读 ——
  行文里的「批 11」「批 12」是**排期**，不是**记录**。
  ⭐ 这个区分是拿批 10 换来的：那一轮我写过一条判据，被一句
  **预告**（「排在批 10，做完即关档」）里的同一个字面量喂成了绿。
  ⇒ **一个字符串出现过，不等于那件事发生过。**
- `no_gaps_in_the_batch_log`：另一条腿。上面那条的分母只有"状态格带批号"的批次，
  而早期几批的条目根本没打批号标签（批 1 就是）。**两条腿方向不同**：
  一条从登记册往台账查，一条查台账自己连不连得上。
- `a_page_in_progress_has_something_open`：**只查得动中间那几个状态**。
  ⭐ **「零未结条目」有两个成因**：一个是干完了（`已关档`），
  一个是**还没开始看**（`未开工`）—— 后者有 7 页，全是正常的。
  只有卡在 `盘点/锁基线/找茬/待裁定/动刀/验收` 而名下一条未结都没有的，
  才无歧义地是"活干完了没回来改状态"。
- ⛔ **看不见的三类，明写出来，不粉饰**：
  ① **反方向查不了**：`已关档` 而名下仍有未结条目，实测有 3 页
     （screen_effects / flash / viewmodel），但那是**合法**的 ——
     本工程的既定结论是「**关档只表示那一页自己那本账清了，不表示它不会再被碰到**」。
     ⇒ 这一向永远有噪声，不做判据。
  ② 旧账逐页表那 104 条**连页面列都没有**（表形是 `RN/G级/级别/位置/…`），
     所以它们不参与任何页级对账。同 RN-198 声明的盲区。
  ③ 台账行里"内容"那一格写得对不对，机器读不出来。

## 跨仓的事

页面清单和登记册在**另一个仓**（纯文档仓，没有 CI、没有测试），
所以数据类断言在两仓不同在时 skip；逻辑守卫拿合成输入跑，哪儿都跑得起来。
⚠ 目录在而文件不在，是腐烂，不是 skip 的理由（RN-140）。
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ⭐ **故意 import，不抄。** 批 10 刚踩过：我把 `CLICK_CONTEXT` 抄了一份到隔壁判据里，
# 抄的是**修好之前**的窄版本，于是那条回退断点假绿了一整轮。
# ⇒ 「结没结」「怎么切表」这套解析只许有一份。
from test_renovation_registry_does_not_rot import (  # noqa: E402
    CAMPAIGN,
    _cell,
    _is_open,
    _rows,
    _statuses,
)

REPO = Path(__file__).resolve().parent.parent

#: 页面清单那份文件。⚠ 名字不带任何品牌，可以写死；
#: 它所在的**目录**仍然按特征发现（见 RN-198 的 `_find_campaign`）。
BOARD = (CAMPAIGN / "页面清单与进度.md") if CAMPAIGN else None

RN_ID = re.compile(r"RN-\d{3}")

#: 页面清单里允许出现的表形。⭐ 分母守卫：新加一张判据读不懂的表，
#: 里面的行会**静默**躲开下面所有断言。
PAGE_TABLE_SHAPE = ("批次", "page_id", "显示名", "实现文件", "行数", "使用", "同名测试", "风险", "状态")
LINK_TABLE_SHAPE = ("批次", "编号", "档案", "锚点", "状态")
BATCH_LOG_SHAPE = ("批", "日期", "内容", "关档", "立案", "外审")
KNOWN_BOARD_SHAPES = {PAGE_TABLE_SHAPE, LINK_TABLE_SHAPE, BATCH_LOG_SHAPE}

#: 页面表里**不是页面**的行（家族基类等）。双向断言：清单里的每一条都必须还在表里。
NON_PAGE_ROWS = {
    "（家族）sound_page_base": "武器音效基类，随家族走，不在导航里注册",
}

#: 页状态取值。⚠ 与总纲 §「状态取值」同义，但这里要机械分三类。
STATUS_NOT_STARTED = "未开工"
STATUS_CLOSED = "已关档"
#: ⭐ 只有这几个中间态才查得动「名下有没有未结条目」。
STATUS_IN_PROGRESS = ("盘点", "锁基线", "找茬", "待裁定", "动刀", "验收")


# --------------------------------------------------------------- 读文件

def _require_board() -> str:
    """⚠ 自己负责 skip，别指望调用方先调过别的。

    RN-198 那一轮的原话：第一版没有这一行，于是唯一一条不先读登记册的判据
    在公开 CI 上 `AttributeError: 'NoneType' has no glob`，
    而**本机两个仓都跑绿**——因为本机的开源仓副本和私有仓是同级目录。
    """
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程（登记册 + 档案）—— 这几条只在两个仓都在时可比")
    return BOARD.read_text(encoding="utf-8")


def _board_rows(text: str) -> list[tuple[tuple[str, ...], list[str]]]:
    """把页面清单切成 (表头, 数据行)。

    ⚠ 表头只认「首格是已声明表形的首格」那一行 —— 同 RN-198，
    别按空行分表（那份登记册的表中间就是有空行的，第一版因此把分母从 66% 缩到 13%，
    而且**不报错**）。
    """
    firsts = {shape[0] for shape in KNOWN_BOARD_SHAPES}
    out: list[tuple[tuple[str, ...], list[str]]] = []
    header: tuple[str, ...] | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0] in firsts and len(cells) > 1:
            header = tuple(cells)
            continue
        if header is not None and len(cells) == len(header):
            out.append((header, cells))
    return out


def _page_rows(text: str) -> list[list[str]]:
    return [c for h, c in _board_rows(text) if h == PAGE_TABLE_SHAPE]


def _batch_rows(text: str) -> list[list[str]]:
    return [c for h, c in _board_rows(text) if h == BATCH_LOG_SHAPE]


def _strip(cell: str) -> str:
    return re.sub(r"\*+", "", cell).strip()


# --------------------------------------------------------- 产品侧的页面真源

def _registered_page_ids() -> set[str]:
    """从 `gui_widget.py` 的 `nav_groups` 字面量里读页面 id。

    ⭐ **走 AST，不建窗口**：这是一条文档判据，为了核对一张表而去起一个
    主窗（连带设备页、定时器、音频）是不成比例的；而 `nav_groups` 是个静态字面量。
    ⚠ 同时这也是**唯一真源**——页面清单不许自己维护第二份页面名单。
    """
    tree = ast.parse((REPO / "gui_widget.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "nav_groups" for t in node.targets):
            continue
        if not isinstance(node.value, ast.List):
            continue
        ids: set[str] = set()
        for group in node.value.elts:
            if not isinstance(group, ast.Tuple) or len(group.elts) != 2:
                continue
            items = group.elts[1]
            if not isinstance(items, ast.List):
                continue
            for item in items.elts:
                if isinstance(item, ast.Tuple) and item.elts:
                    first = item.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        ids.add(first.value)
        return ids
    return set()


# ---------------------------------------------------- 批号：只认状态格里的

def _batches_the_registry_tagged() -> set[int]:
    """登记册**状态格**里打过标签的批号。

    ⭐⭐ **只认状态格，不认行文。** 行文里的「批 11」「批 12」是排期；
    状态格里的「已结（2026-08-23）·批 10」才是记录。
    ⚠ 这个区分是拿批 10 换来的：那一轮有一条判据被一句**预告**里的
    同一个字面量喂成了绿（「排在批 10，做完即关档」）。
    ⇒ **一个字符串出现过，不等于那件事发生过。**
    """
    out: set[int] = set()
    for status in _statuses(_registry_text()).values():
        for n in re.findall(r"批\s*(\d{1,2})", status):
            out.add(int(n))
    return out


def _registry_text() -> str:
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程（登记册 + 档案）")
    return (CAMPAIGN / "登记册.md").read_text(encoding="utf-8")


def _open_entries_by_page(page_ids: set[str]) -> dict[str, list[str]]:
    """每个页面 id 名下**未结**的 RN 条目。

    ⚠ **失效方向朝"别诬告"那边倒**：登记册的「档案」格写法很杂
    （`magnifier（紧凑档）`、`voice_output / music`、`magnifier + utility + 帮助面板 ×9`），
    所以用**包含**匹配而不是相等匹配。少算一条未结 ⇒ 会去诬告一个其实还有活的页；
    多算一条 ⇒ 最多是漏报。⭐ 同 RN-198 的 `_is_open`：
    **分不出类的值，失效方向必须朝安全那边倒**，而这里"安全"是不冤枉。
    """
    out: dict[str, list[str]] = {pid: [] for pid in page_ids}
    for header, cells in _rows(_registry_text()):
        status = _cell(header, cells, "状态")
        owner = _cell(header, cells, "档案")
        if not status or not owner or not _is_open(status):
            continue
        for pid in page_ids:
            if re.search(r"(?<![A-Za-z_])" + re.escape(pid) + r"(?![A-Za-z_])", owner):
                out[pid].append(cells[0].strip("* "))
    return out


# ------------------------------------------------- 空转守卫（不碰真文件）

#: 合成的页面清单片段：一行干净的、一行腐烂的。
#: ⭐ 上面那些数据断言在开源仓和 CI 里都会 skip，
#: 于是「它们还咬不咬得动」在那两个环境里**永远没人验**。
_SYNTHETIC_BOARD = """
| 批次 | page_id | 显示名 | 实现文件 | 行数 | 使用 | 同名测试 | 风险 | 状态 |
|---|---|---|---|---|---|---|---|---|
| P0 | alpha | 甲页 | pages/a.py | 10 | 1 | 有 | | **已关档**（做完了）|
| P0 | beta | 乙页 | pages/b.py | 10 | 1 | 有 | | **验收**（还剩两条）|
| P9 | gamma | 丙页 | pages/c.py | 10 | 1 | 0 | 无测 | 未开工 |
| P0 | delta | 丁页 | pages/d.py | 10 | 1 | 有 | | **动刀中**（其实早做完了）|

| 批 | 日期 | 内容 | 关档 | 立案 | 外审 |
|---|---|---|---|---|---|
| 批 1 | 2026-01-01 | 甲页 | RN-901 | — | 0 发 |
| 批 3 | 2026-01-03 | 丙页 | RN-903 | RN-904 | 0 发 |
"""

_SYNTHETIC_REGISTRY = """
| RN | 档案 | 镜头 | 级别 | 一句话 | 堆 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|
| RN-901 | alpha | ①功能 | S3 | 甲页那条 | A | **已结（2026-01-01）·批 1** | — |
| RN-902 | beta | ①功能 | S3 | 乙页那条 | A | 立案 | — |
| RN-903 | gamma | ①功能 | S3 | 丙页那条 | A | 立案 | — |
| RN-904 | gamma | ①功能 | S3 | 丙页第二条 | B | 立案（批 3 外审）| — |
"""


def test_the_synthetic_parser_reads_both_tables():
    rows = _board_rows(_SYNTHETIC_BOARD)
    pages = [c[1] for h, c in rows if h == PAGE_TABLE_SHAPE]
    batches = [c[0] for h, c in rows if h == BATCH_LOG_SHAPE]
    assert pages == ["alpha", "beta", "gamma", "delta"]
    assert batches == ["批 1", "批 3"]


def test_the_batch_gap_check_actually_catches_a_gap():
    """合成台账里有 批 1 / 批 3 ⇒ 缺 批 2，必须被逮住。"""
    nums = sorted(int(re.search(r"(\d+)", c[0]).group(1)) for c in _batch_rows(_SYNTHETIC_BOARD))
    missing = [n for n in range(1, max(nums) + 1) if n not in nums]
    assert missing == [2], f"缺口检查算出 {missing}，应当且只应当是 [2]"


def test_the_cross_file_batch_check_actually_catches_a_missing_row():
    """合成登记册里状态格打过 批 1 与 批 3 —— 再造一条 批 4 出来，必须被逮住。"""
    logged = {int(re.search(r"(\d+)", c[0]).group(1)) for c in _batch_rows(_SYNTHETIC_BOARD)}
    tagged = set()
    for header, cells in _rows(_SYNTHETIC_REGISTRY):
        status = _cell(header, cells, "状态") or ""
        tagged |= {int(n) for n in re.findall(r"批\s*(\d{1,2})", status)}
    assert tagged == {1, 3}, (
        f"从合成登记册的状态格里读出 {sorted(tagged)} —— 应当是 [1, 3]。"
        "⚠ 「批 3」写在 RN-904 的状态格里（`立案（批 3 外审）`），"
        "而 RN-903 的证据格里什么都没有 —— 这条判据只该看状态格。"
    )
    assert not (tagged - logged), "合成数据本身应当是对上的"
    assert 4 not in logged, "合成台账里不该有 批 4"


def test_the_in_progress_check_catches_a_page_that_should_have_closed():
    """`delta` 挂着「动刀中」而合成登记册里它名下一条未结都没有 ⇒ 必须被逮住。

    ⭐ 同时验另外两个方向**不许**被冤枉：
    `gamma` 是 `未开工`（零未结是因为还没人看过），`alpha` 是 `已关档`。
    """
    page_ids = {c[1] for h, c in _board_rows(_SYNTHETIC_BOARD) if h == PAGE_TABLE_SHAPE}
    opens = {pid: [] for pid in page_ids}
    for header, cells in _rows(_SYNTHETIC_REGISTRY):
        status = _cell(header, cells, "状态")
        owner = _cell(header, cells, "档案")
        if not status or not owner or not _is_open(status):
            continue
        for pid in page_ids:
            if re.search(r"(?<![A-Za-z_])" + re.escape(pid) + r"(?![A-Za-z_])", owner):
                opens[pid].append(cells[0].strip("* "))
    caught = sorted(
        c[1] for h, c in _board_rows(_SYNTHETIC_BOARD)
        if h == PAGE_TABLE_SHAPE
        and _strip(c[8]).startswith(STATUS_IN_PROGRESS)
        and not opens[c[1]]
    )
    assert caught == ["delta"], (
        f"合成数据里应当且只应当逮住 delta，实际 {caught} —— "
        "要么判据瞎了，要么它会去冤枉 未开工 / 已关档 的页。"
    )


# ------------------------------------------------------------ 分母守卫

def test_the_board_is_there_when_the_campaign_is():
    """⚠ 找到了工程目录、页面清单却不在 —— 那是腐烂，不是 skip 的理由（RN-140）。"""
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程")
    assert BOARD.is_file(), f"找到了翻新工程目录，但页面清单不见了：{BOARD}"


def test_the_parser_actually_sees_the_page_table():
    """⭐ 先证明这条判据看得见东西，再让它去断言「没问题」（RN-169）。"""
    rows = _page_rows(_require_board())
    assert len(rows) >= 28, (
        f"只解析出 {len(rows)} 行页面 —— 产品里注册着 28 个页面，"
        "说明解析器瞎了（多半是表头识别改坏了）。一个把表解析成 0 行的解析器，"
        "会让下面每一条断言都无条件通过。"
    )


def test_the_board_table_shapes_are_a_closed_set():
    """新加一张判据读不懂的表，里面的行会静默躲开所有断言。"""
    text = _require_board()
    shapes = set()
    firsts = {shape[0] for shape in KNOWN_BOARD_SHAPES}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(c.strip() for c in line.strip().strip("|").split("|"))
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0] in firsts and len(cells) > 1:
            shapes.add(cells)
    unknown = sorted(shapes - KNOWN_BOARD_SHAPES)
    assert not unknown, (
        f"页面清单里出现了没见过的表形：{unknown}\n"
        "把它加进 KNOWN_BOARD_SHAPES，并**说清楚它会不会躲开下面的对账**。"
    )


def test_the_board_lists_exactly_the_pages_the_product_registers():
    """⭐ 页面名单的真源是 `gui_widget.nav_groups`，页面清单不许维护第二份。

    ⚠⚠ **这条判据横跨两个仓**（这边的产品代码 × 那边的文档），
    所以它必须先回答一个问题：**这两边是同一个产品吗？**

    第一版没问，当场在**派生的功能子集**里红了：那份清单描述的是完整产品（28 页），
    而子集里 `account` 整页不存在（连实现文件都被排除掉了）⇒ 判据报「清单多了 account」。
    ⭐ 本机的镜像与主仓是**同级目录**，于是它用**子集的产品代码**去比**完整产品的文档** ——
    一个现实中不存在的组合。⭐⭐ **本机的镜像不是任何一个真实环境的忠实模型。**

    ⇒ 改法不是放宽，是把"差在哪"说清楚：**多出来的页，必须是这个 checkout 里
    连实现文件都没有的页**（实现文件那一列表里就写着）。少了一页则永远是硬错。
    """
    registered = _registered_page_ids()
    assert len(registered) >= 20, (
        f"从 gui_widget.nav_groups 只读出 {len(registered)} 个页面 —— "
        "AST 抽取器瞎了（那个字面量改写法了？）。"
    )
    listed, non_pages, impl = set(), set(), {}
    for cells in _page_rows(_require_board()):
        pid = _strip(cells[1])
        if re.fullmatch(r"[a-z_]+", pid):
            listed.add(pid)
            m = re.search(r"[\w/]+\.py", cells[3])
            impl[pid] = m.group(0) if m else ""
        else:
            non_pages.add(pid)
    assert not (registered - listed), (
        f"页面清单少了：{sorted(registered - listed)}\n"
        "产品里加了页面，这张表要跟着走。"
    )
    still_here = sorted(
        pid for pid in (listed - registered)
        if impl.get(pid) and (REPO / impl[pid]).exists()
    )
    assert not still_here, (
        f"页面清单里有这几页，产品的导航里却没注册，而它们的实现文件还在：{still_here}\n"
        "⇒ 要么页面被摘出导航了（那是缺陷），要么这张表过期了。\n"
        "（实现文件也一并不在的，算派生子集的正常缺项，不报。）"
    )
    assert non_pages == set(NON_PAGE_ROWS), (
        f"非页面行对不上：多 {sorted(non_pages - set(NON_PAGE_ROWS))}、"
        f"少 {sorted(set(NON_PAGE_ROWS) - non_pages)}"
    )


# ------------------------------------------------------------ 三条对账

def test_every_batch_the_registry_tagged_has_a_row_on_the_board():
    """⭐⭐ **本条是 RN-408 的主刀。** 登记册状态格里打过标签的批，台账里必须有一行。

    实测（2026-08-26）：批 9 与批 10 都做完了、都推了、档案和登记册都写了，
    **页面清单里一个字都没有**。而下一轮开工的人要读的正是这份文件。
    """
    logged = {int(re.search(r"(\d+)", _strip(c[0])).group(1))
              for c in _batch_rows(_require_board()) if re.search(r"\d", c[0])}
    tagged = _batches_the_registry_tagged()
    missing = sorted(tagged - logged)
    assert not missing, (
        f"这几批在登记册的状态格里有记录，页面清单的批次台账里却没有：{missing}\n"
        "收工时把这一批补进批次台账（批 / 日期 / 内容 / 关档 / 立案 / 外审）。\n"
        "⭐ 这份文件是开工三读的第二读——它过期，下一轮就按过期的地图排工。"
    )


def test_the_batch_log_has_no_gaps():
    """另一条腿：早期几批的条目根本没在状态格里打批号（批 1 就是），
    上面那条够不着它们。这条只查台账自己连不连得上。
    """
    nums = sorted(int(re.search(r"(\d+)", _strip(c[0])).group(1))
                  for c in _batch_rows(_require_board()) if re.search(r"\d", c[0]))
    assert nums, "批次台账是空的（或者表头改了写法）—— 这条判据已经瞎了"
    assert nums[0] == 1, f"批次台账从 批 {nums[0]} 开始，缺前面的"
    missing = [n for n in range(1, nums[-1] + 1) if n not in nums]
    assert not missing, f"批次台账缺口：{missing}"
    assert len(nums) == len(set(nums)), f"批次台账里有重号：{nums}"


def test_a_batch_row_only_claims_closures_the_registry_agrees_with():
    """⭐ 台账不许吹牛：「关档」那一格点名的 RN，登记册里必须真的已结。

    ⚠ 反向也查：「立案」那一格点名的 RN 必须在登记册里存在
    （悬空引用 = 那条根本没入册，而台账让人以为入了）。
    """
    text = _registry_text()
    status = _statuses(text)
    #: ⚠⚠ **「存不存在」和「结没结」是两个分母。**
    #: 第一版拿 `status` 当"在册名单"用，当场诬告 RN-254 —— 它确实在册，
    #: 只是住在**没有状态列**的旧账逐页表里（104 条都是）。
    #: ⭐ 一个分母答不了另一个分母的问题，而两者长得很像："都是从登记册里读出来的一堆 RN 号"。
    on_file = {cells[0].strip("* ") for _, cells in _rows(text)}
    assert len(on_file) > len(status), (
        "在册条目数没有多于「有状态格」的条目数 —— 旧账逐页表没被解析到，"
        "这条判据的存在性检查已经瞎了。"
    )
    bad_closed, dangling, unknowable = [], [], []
    for cells in _batch_rows(_require_board()):
        batch = _strip(cells[0])
        for rid in RN_ID.findall(cells[3]):
            if rid not in on_file:
                dangling.append((batch, "关档", rid))
            elif rid not in status:
                #: 在册但没有状态列 ⇒ 机器判不了它结没结。**别装作查过。**
                unknowable.append((batch, rid))
            elif _is_open(status[rid]):
                bad_closed.append((batch, rid, status[rid][:28]))
        for rid in RN_ID.findall(cells[4]):
            if rid not in on_file:
                dangling.append((batch, "立案", rid))
    assert not unknowable, (
        "批次台账把这几条写进了「关档」格，而它们住在**没有状态列**的旧账表里，"
        "机器核不了：\n" +
        "\n".join(f"  {b}  {rid}" for b, rid in unknowable) +
        "\n⇒ 要么把它挪进有状态列的表，要么别声称它关档了。"
    )
    assert not bad_closed, (
        "批次台账声称这几条关档了，登记册里它们还是未结：\n" +
        "\n".join(f"  {b}  {rid}  登记册状态={st!r}" for b, rid, st in bad_closed)
    )
    assert not dangling, (
        "批次台账点名了登记册里不存在的 RN：\n" +
        "\n".join(f"  {b}  「{col}」格  {rid}" for b, col, rid in dangling)
    )


def test_a_page_in_progress_has_something_open_in_the_registry():
    """⭐ 卡在中间态而名下一条未结都没有 = 活干完了没回来改状态。

    ⛔ 只查中间态。`未开工`（零未结是因为还没人看过，实测 7 页）与
    `已关档`（反方向有合法噪声，实测 3 页）都不在分母里 —— 见模块头。
    """
    board = _require_board()
    page_ids = {_strip(c[1]) for c in _page_rows(board) if re.fullmatch(r"[a-z_]+", _strip(c[1]))}
    opens = _open_entries_by_page(page_ids)
    bad = []
    for cells in _page_rows(board):
        pid, st = _strip(cells[1]), _strip(cells[8])
        if pid in page_ids and st.startswith(STATUS_IN_PROGRESS) and not opens[pid]:
            bad.append((pid, st[:20]))
    assert not bad, (
        "这几页在页面清单里还挂着中间态，而登记册里它们名下一条未结都没有：\n" +
        "\n".join(f"  {pid}  状态={st!r}" for pid, st in bad) +
        "\n要么该关档了，要么该立的案没入册。"
    )


def test_the_closing_checklist_is_enumerated_in_exactly_one_place():
    """⭐⭐ **同一件事说五遍，任何一遍变假都不会有人发现 —— 因为没人知道有五遍。**

    2026-08-26 实测：收工清单在 `CLAUDE.md` 与总纲里**一共复述了五遍**，
    而且**总纲内部就有两个不同的数**（§9 风险表和 §14 开头写「四件套」，
    §14 末尾写「六件套」，而 `CLAUDE.md` 当时是「六件套」）。

    ⇒ 唯一真源是 `CLAUDE.md`（那份每次开工自动加载的）。总纲只许留指针。
    ⭐ 副本里连**那个数字**都不留 —— 一个会漂的数，留在副本里就一定会漂。

    机械判法：总纲里凡是同时出现「收工」和「件套」的行，**不许**带枚举符号 `①`。
    """
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程")
    charters = sorted(CAMPAIGN.glob("总纲*.md"))
    assert len(charters) == 1, f"总纲不是恰好一份：{[p.name for p in charters]}"
    text = charters[0].read_text(encoding="utf-8")
    assert "收工" in text, "总纲里连「收工」两个字都没有了 —— 这条判据已经瞎了"
    enumerated = [
        line.strip()[:70] for line in text.splitlines()
        if "收工" in line and "件套" in line and "①" in line
    ]
    assert not enumerated, (
        "总纲里又长出了一份收工清单的**枚举**副本：\n" +
        "\n".join("  " + line for line in enumerated) +
        "\n⇒ 只留指针（「见 `CLAUDE.md` §2」），别复述内容，更别写那个数字。"
    )
    assert "CLAUDE.md" in text, (
        "总纲里没有指向唯一真源的指针 —— 删了副本却没留指路牌，"
        "下一个人会以为总纲漏了这一节，然后再抄一份回来。"
    )


def test_the_page_status_vocabulary_does_not_rot():
    """双向断言：三类状态词都必须真的还在被用，否则清单变成古董。"""
    used = [_strip(c[8]) for c in _page_rows(_require_board())]
    assert any(s.startswith(STATUS_NOT_STARTED) for s in used), "没有一页是 未开工 了？"
    assert any(s.startswith(STATUS_CLOSED) for s in used), "没有一页是 已关档 了？"
    unknown = sorted({
        s[:12] for s in used
        if not s.startswith((STATUS_NOT_STARTED, STATUS_CLOSED) + STATUS_IN_PROGRESS)
    })
    assert not unknown, (
        f"这些页状态开头不是已登记的词：{unknown}\n"
        "把机器要读的那个词放最前面，细节写在后面的括号里。"
    )
