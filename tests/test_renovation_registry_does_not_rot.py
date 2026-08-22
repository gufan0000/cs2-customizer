# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-198：翻新工程登记册是**唯一真相源，却是唯一一个没有判据看着的真相源**。

它腐烂的形态**从来只有一种**：活干完了、代码里写清楚了、档案里也写清楚了，
**就是没回登记册把状态那一格改掉**。于是那一条在统计里继续躺着，
下一轮开工的人（包括我）会把它当成真的待办发给用户。

2026-08-23 一次性对账查出 **14 条**（其中 9 条是判据写完当场咬出来的）：

| 怎么被发现的 | 条目 |
|---|---|
| 批 7 收工自查（人眼）| RN-114 / RN-115 / RN-116 / RN-119 |
| 裁定 RN-026 时读代码（人眼）| RN-026 |
| **判据首跑**：别的格子里写着「已结（日期）」| RN-075 / RN-077 / RN-078 / RN-079 / RN-083 |
| **判据首跑**：产品代码里点名 | RN-003 / RN-027 / RN-028 / RN-029 |

⭐⭐ **14 次同一种错，说明它不是「忘了」。** 一条纪律如果只靠人记得，
它的失效率就是人的失效率；而登记册是全工程唯一一个**没有棘轮**的真相源 ——
代码有判据、基线有指纹、审计有裁定行，只有它靠自觉。

⭐ 顺带一个值得记的数：人眼两轮盘点（批 7 + 裁定日）共找出 5 条，
**判据首跑当场再找出 9 条** —— 而那两轮人眼都是带着「就是要找腐烂」的目的去看的。
⇒ 又一次印证本工程第一条教训：**人眼盘点必然漏，只能靠判据扫。**

## 这几条判据分别看得见什么（⭐ 分母要说清楚，别假装全覆盖）

- `says_closed_somewhere_else`：**零噪声，同一行之内就能判**。14 条里它一个人抓 9 条 ——
  因为「已结（日期）」被写进了**证据格或一句话格**，就是没写进状态格。
  ⇒ 那个反复出现的形态：**把结论写在一个不会被统计到的地方，等于没写。**
- `product_code_names_it`：跨仓（本仓产品代码 → 登记册），抓 RN-003/026/027/028/029。
  ⚠ 这条有噪声：代码里点名一个 RN **也可能是在引用它作为先例或族名**
  （「RN-107 族」「RN-156 刚踩过」），所以配了一张**双向断言**的允许清单。
- ⛔ **看不见的两类，明写出来，不粉饰**：
  ① 一次动刀既没在档案留台账、代码里也没写注释 —— 没有任何机械信号；
  ② 旧账逐页表那 104 条（34%）**没有状态列**（堆和状态挤在一格），
     状态类判据够不着它们。这是**已知且被声明**的盲区，见 `KNOWN_TABLE_SHAPES`。

## 跨仓的事

登记册在**另一个仓**（一个纯文档仓：没有 CI、没有测试），
所以这几条只在**两个仓都在本机**时跑得起来，CI 与开源版里 skip。
⚠ 按 RN-140 的教训，skip 条件描述的必须是「样本可不可比」——
所以另配了一条反面守卫：**目录在而文件不在，是腐烂，不是 skip 的理由。**
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _find_campaign() -> Path | None:
    """找到翻新工程目录（登记册 + 档案所在的那个同级目录）。

    ⚠ **故意不写死目录名。** 写死会踩两个坑：
      ① 那个名字带闭源品牌，派生开源版时会被机械替换成一个**两个仓里都不存在**
         的路径，于是判据在那边永远 skip，而说明读起来像真有那么个东西（是虚构）；
      ② 目录改名时判据会静默变成"永远 skip"，而不是报错。
    ⇒ 按**特征**找：同级目录里同时有 `登记册.md` 和 `档案/` 的那一个。
    """
    for sibling in sorted(REPO.parent.iterdir() if REPO.parent.is_dir() else []):
        if not sibling.is_dir():
            continue
        if (sibling / "登记册.md").is_file() and (sibling / "档案").is_dir():
            return sibling
    return None


CAMPAIGN = _find_campaign()
REGISTRY = (CAMPAIGN / "登记册.md") if CAMPAIGN else None
ARCHIVE = (CAMPAIGN / "档案") if CAMPAIGN else None

RN_ID = re.compile(r"^RN-\d{3}$")
RN_ANY = re.compile(r"RN-(\d{3})")

#: 状态格必须**以**其中一个词开头（后面爱写什么补充都行）。
#: 这不是为了统一措辞——是为了让下面几条判据能机械地分出「结没结」。
#: ⚠ 双向断言：清单里的每个词都必须真的还在被用，否则它就腐烂成古董了。
STATUS_WORDS = (
    "已结", "已批已结", "部分结", "已修", "作废", "移交", "不修",
    "记录不做", "实测后不成立",          # ↑ 结了
    "已裁", "新立", "立案", "待裁定",     # ↑ 没结（已裁 = 批了但还没做）
)
CLOSED_WORDS = frozenset(
    {"已结", "已批已结", "部分结", "已修", "作废", "移交", "不修",
     "记录不做", "实测后不成立"}
)

#: 登记册允许出现的表形。⭐ 这条是**分母守卫**：新加一张判据读不懂的表，
#: 里面的条目就会静默地躲开下面所有断言（同 RN-189「分母要取真源，不是自己那张表」）。
KNOWN_TABLE_SHAPES = {
    ("RN", "档案", "镜头", "级别", "一句话", "堆", "状态", "证据"),
    ("RN", "档案", "镜头", "级别", "一句话", "堆", "状态", "修法 / 证据"),
    ("RN", "主题", "涉及", "级别", "堆", "状态"),
    #: 旧账逐页表：它把「堆」和「状态」挤在同一格 ⇒ **没有状态列**。
    #: ⚠ 于是 104 条（34%）躲开了状态类判据。这是**已知且被声明的盲区**，
    #: 不是疏忽——重排这张表要动 24 个页面小节，代价与收益不匹配。
    ("RN", "G级", "级别", "位置", "一句话", "主题", "堆"),
}

#: 产品代码里点名了某个 RN，但那是**把它当先例/族名引用**，不是「这条修好了」。
#: ⚠ 双向断言：每一条都必须 ① 仍被代码点名 ② 在登记册里仍未结。
#: 任何一头不成立就说明这张表该改了。
CITED_AS_PRECEDENT = {
    "RN-045": "对比度那条的病根，被 gui_widget 当先例引用",
    "RN-102": "「同屏重复入口」是跨页主题；代码引用的是这一类，不是这一条",
    "RN-107": "「同屏状态自相矛盾」族，十余处引用全是族名",
    "RN-154": "「修一个问题时留下的旧形态」，被引用为教训",
    "RN-156": "「语义补丁的上下文窗口看不见」，被引用为刚踩过的坑",
}

#: 扫哪些目录算「产品代码」。⛔ 故意不含 `tests/` 与 `scripts/`：
#: 判据和工装里点名一个 RN 太常见了（讲教训、写空转守卫的由来），噪声压过信号。
PRODUCT_DIRS = ("pages", "core", "widgets", "build_tools")


# --------------------------------------------------------------- 读登记册

def _require_registry() -> str:
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程（登记册 + 档案）—— 这几条只在两个仓都在时可比")
    return REGISTRY.read_text(encoding="utf-8")


def _rows(text: str) -> list[tuple[tuple[str, ...], list[str]]]:
    """把登记册切成 (表头, 数据行)。

    ⚠ **表头只认「首格恰好是 RN」那一行。** 第一版按「空行分表」切，
    而登记册的表中间是有空行的 ⇒ 82 条数据行被当成了表头，
    判据的分母当场从 66% 缩到 13%，而它**不会报错**。
    ⭐ 一个解析器算错分母时，长得和「这份文档很干净」一模一样。
    """
    out: list[tuple[tuple[str, ...], list[str]]] = []
    header: tuple[str, ...] | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0] == "RN":
            header = tuple(cells)
            continue
        if header is not None and RN_ID.match(cells[0].strip("* ")):
            out.append((header, cells))
    return out


def _cell(header: tuple[str, ...], cells: list[str], name: str) -> str | None:
    if name not in header:
        return None
    i = header.index(name)
    return re.sub(r"\*+", "", cells[i]).strip() if len(cells) > i else None


def _statuses(text: str) -> dict[str, str]:
    return {
        cells[0].strip("* "): st
        for header, cells in _rows(text)
        if (st := _cell(header, cells, "状态")) is not None
    }


def _status_word(status: str) -> str | None:
    """状态格开头的那个词。⚠ **必须是开头** ——

    写在句中的「已结」不算（「那页已修、这页还在」说的是**别的条目**，
    收得宽一点就会开始诬告）。

    ⚠ 星号在这里自己去掉一次，别指望调用方先 `_cell()` 过。
    第一版把去星号的活留给了调用方，于是判据本体是对的、
    而**直接考它的空转守卫全红** —— 一个只在某条特定调用路径上成立的函数，
    等于给自己埋了一个只有换个入口才会现形的坑。
    """
    bare = re.sub(r"\*+", "", status).lstrip("⚠⭐⛔ ")
    for word in sorted(STATUS_WORDS, key=len, reverse=True):
        if bare.startswith(word):
            return word
    return None


def _is_open(status: str) -> bool:
    """⚠ **认不出来的状态，一律按「没结」算。**

    第一版写的是 `word is not None and word not in CLOSED_WORDS`，
    于是 `已进 P1 档案，待动刀` 这种认不出的状态被判成**结了**，
    当场躲开下面全部三条对账判据（RN-019 就是这么漏掉的）。
    ⭐ **一个分不出类的值，失效方向必须朝"要查"那一边倒** ——
    否则「判据读不懂它」和「它没问题」在结果上长得一模一样。
    """
    word = _status_word(status)
    return word is None or word not in CLOSED_WORDS


# ------------------------------------------------- 空转守卫（不碰真登记册）

#: 一份**合成**的登记册片段：一行干净的、一行腐烂的。
#: ⭐ 上面那些判据都要跳过（登记册在另一个仓，CI 和开源版里没有），
#: 于是「它们还咬不咬得动」在那两个环境里**永远没人验**。
#: 这一组拿合成输入直接考判据的分类函数 —— **不依赖另一个仓，哪儿都跑得起来。**
#: 依据是本工程的老教训：一条判据必须先证明自己看得见缺陷，再去断言缺陷不在。
_SYNTHETIC = """
| RN | 档案 | 镜头 | 级别 | 一句话 | 堆 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|
| RN-901 | 某页 | ①功能 | S3 | 干净的一行 | A | **已结（2026-01-02）** | 有判据 |
| RN-902 | 某页 | ①功能 | S3 | 腐烂：证据格说已结 | A | 新立 | ⇒ **已结（2026-01-02）**：改完了 |
| RN-903 | 某页 | ①功能 | S3 | 腐烂：状态词没登记过 | A | 大概做完了吧 | — |
| RN-904 | 某页 | ①功能 | S3 | 干净的未结 | B | 待裁定 | 等用户 |
"""


def test_the_parser_reads_a_synthetic_registry_correctly():
    rows = _rows(_SYNTHETIC)
    assert [c[0] for _, c in rows] == ["RN-901", "RN-902", "RN-903", "RN-904"]
    st = _statuses(_SYNTHETIC)
    assert st["RN-901"] == "已结（2026-01-02）"
    assert st["RN-902"] == "新立"


def test_open_and_closed_are_told_apart_and_unknown_falls_to_open():
    """⭐ 失效方向：认不出来的状态必须倒向「要查」那一边。"""
    assert not _is_open("**已结（2026-08-18）**·⚠ 对账补记")
    assert not _is_open("部分结（余 20 页）")
    assert _is_open("新立")
    assert _is_open("待裁定")
    assert _is_open("已裁（2026-08-23）·待实施")     # 批了但还没做 = 没结
    assert _is_open("大概做完了吧"), (
        "认不出来的状态被判成「结了」—— 那它会静默躲开全部对账判据。"
        "RN-019 当初就是这么漏掉的。"
    )


def test_the_status_word_is_read_from_the_front_not_from_anywhere():
    """⚠ 必须是**开头**那个词。写在句中的「已结」不算 ——

    否则「那页已修、这页还在」这种描述**别的条目**的句子会把自己判成结了。
    """
    assert _status_word("已结（2026-01-02）") == "已结"
    assert _status_word("⚠ **已结**（补记）") == "已结"
    assert _status_word("那页已修、这页还在") is None


def test_a_rotten_row_is_actually_detected_in_the_synthetic_registry():
    """把真判据的判定逻辑原样跑在合成数据上：902 必须被逮住，901/904 不许被冤枉。"""
    claim = re.compile(r"已结（\d{4}-\d{2}-\d{2}")
    caught = []
    for header, cells in _rows(_SYNTHETIC):
        status = _cell(header, cells, "状态")
        if not status or not _is_open(status):
            continue
        for name in header:
            if name in ("RN", "状态"):
                continue
            other = _cell(header, cells, name)
            if other and claim.search(other):
                caught.append(cells[0])
                break
    assert caught == ["RN-902"], (
        f"合成数据里应当且只应当逮住 RN-902，实际逮住 {caught} —— "
        "判据要么瞎了（漏 902），要么会冤枉干净的行。"
    )


# --------------------------------------------------------------- 空转守卫

def test_the_parser_actually_sees_the_registry():
    """⭐ 先证明这几条判据看得见东西，再让它们去断言「没问题」。

    一个把登记册解析成 0 行的解析器，会让下面每一条断言都**无条件通过**。
    RN-169 的教训：**一条判据必须先证明自己看得见缺陷，再去断言缺陷不在。**
    """
    rows = _rows(_require_registry())
    assert len(rows) >= 250, (
        f"只解析出 {len(rows)} 条 —— 登记册在册条目远多于此，"
        "说明解析器瞎了（多半是表头识别或分隔行判定改坏了）。"
    )
    with_status = sum(1 for h, _ in rows if "状态" in h)
    assert with_status >= len(rows) * 0.6, (
        f"只有 {with_status}/{len(rows)} 条落在有状态列的表里，"
        "低于既有分母 —— 是不是新加了一张没有状态列的表？"
    )


def test_a_half_present_campaign_is_rot_not_a_reason_to_skip():
    """⚠ skip 只准因为「翻新工程整个不在」（开源仓 / CI）。

    找到了目录、里面却缺东西，是**文件被挪走或改名了**，那是腐烂本身，
    不是样本不可比。⭐ RN-140：skip 条件描述的必须是「样本可不可比」，
    不是「环境看起来正不正常」。
    """
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程")
    assert REGISTRY.is_file(), f"找到了翻新工程目录，但登记册不见了：{REGISTRY}"
    assert ARCHIVE.is_dir(), f"找到了翻新工程目录，但档案目录不见了：{ARCHIVE}"
    assert any(ARCHIVE.glob("*.md")), f"档案目录是空的：{ARCHIVE}"


# --------------------------------------------------------------- 号段与重号

def test_no_rn_number_is_used_twice():
    """RN-101 事故：同一个号在同一份登记册里指两件事。"""
    seen: dict[str, int] = {}
    for _, cells in _rows(_require_registry()):
        rid = cells[0].strip("* ")
        seen[rid] = seen.get(rid, 0) + 1
    dups = sorted(r for r, n in seen.items() if n > 1)
    assert not dups, f"重号：{dups}"


def test_every_rn_number_falls_inside_a_declared_segment():
    """⭐ **号段是一种没人守着的约定** —— RN-101 事故的原话，至今仍然如此。

    这条判据把它变成有人守着的：段定义从登记册表头**当数据读出来**，
    不写在判据里（写在判据里就是第二份副本）。
    """
    text = _require_registry()
    head = text.split("---", 1)[0]
    segments = [(int(a), int(b)) for a, b in re.findall(r"RN-(\d{3})~(\d{3})", head)]
    assert len(segments) >= 4, (
        f"表头里只读出 {len(segments)} 个号段 —— 段声明的写法变了，这条判据已经瞎了。"
        "号段必须以 `RN-xxx~yyy` 的形式写在登记册开头。"
    )
    # ⭐ 破坏验证当场逮到的：段声明被抄了第二份（编号段那行 + 下面的说明各一份），
    # 于是「从编号段那行删掉一段」这个破坏**判据看不见** —— 它从副本里照样读得到。
    # ⇒ **判据的输入有第二份副本时，它就不再是判据。**
    dups = sorted({s for s in segments if segments.count(s) > 1})
    assert not dups, (
        f"这些号段在表头里被声明了不止一次：{dups}\n"
        "段声明只许有一处（「编号段」那一行）。说明文字里提到号段时，"
        "别写成 `RN-xxx~yyy` 的形式，否则它会变成判据读得到的第二份副本。"
    )
    bad = sorted(
        rid for _, cells in _rows(text)
        if (rid := cells[0].strip("* "))
        and not any(lo <= int(rid[3:]) <= hi for lo, hi in segments)
    )
    assert not bad, (
        f"这些号不在任何已声明的号段里：{bad}\n"
        f"已声明的段：{segments}\n"
        "要么号编错了，要么表头那行段声明漏了一段。"
    )


# --------------------------------------------------------------- 状态格

def test_every_status_cell_starts_with_a_declared_word():
    """状态格必须**以**一个已登记的词开头，后面随便补充。

    ⚠ 这条不是在管措辞。它是下面三条对账判据的**前提**：
    一个分不出「结没结」的状态格，会让对账判据静默失效。
    """
    bad = [
        (rid, st) for rid, st in _statuses(_require_registry()).items()
        if _status_word(st) is None
    ]
    assert not bad, (
        "这些状态格开头不是已登记的状态词（把机器要读的那个词放最前面，"
        "细节写在后面的括号里）：\n" +
        "\n".join(f"  {rid}: {st[:60]!r}" for rid, st in bad) +
        f"\n可用的词：{list(STATUS_WORDS)}"
    )


def test_the_status_vocabulary_does_not_rot():
    """双向断言：清单里的每个词都必须真的还在被用。"""
    used = {w for st in _statuses(_require_registry()).values()
            if (w := _status_word(st))}
    antiques = sorted(set(STATUS_WORDS) - used)
    assert not antiques, (
        f"这些状态词已经没有任何条目在用了：{antiques} —— 从清单里删掉，"
        "否则它会一直替一个不存在的写法留门。"
    )


def test_the_registry_table_shapes_are_a_closed_set():
    """⭐ 分母守卫：新加一张判据读不懂的表，里面的条目会**静默**躲开所有断言。"""
    shapes = {h for h, _ in _rows(_require_registry())}
    unknown = sorted(shapes - KNOWN_TABLE_SHAPES)
    assert not unknown, (
        f"登记册里出现了没见过的表形：{unknown}\n"
        "要么把它改成已有的表形，要么把它加进 KNOWN_TABLE_SHAPES 并"
        "**说清楚它会不会躲开状态类判据**。"
    )


# --------------------------------------------------------------- 三条对账

def test_a_row_that_says_closed_somewhere_else_says_it_in_the_status_cell():
    """⭐⭐ **同一行之内的自相矛盾** —— 14 条腐烂里这一条一个人抓 9 条，且零噪声。

    形态永远一样：动刀的人把「⇒ **已结（2026-08-18）**」追加在**别的格子**里
    （证据格 5 次、一句话格 4 次），状态格原封不动还是「新立」。
    于是这一条在统计里继续躺着待办，下一轮开工的人当成真待办发给用户。

    ⭐ **把结论写在一个不会被统计到的地方，等于没写。**

    ⚠ 判据故意只认**带日期**的 `已结（YYYY-MM-DD` —— 不带日期的「已修」「已关档」
    在行文里太常见（「那页已修、这页还在」就是在说**另一条**），
    收得宽一点点就会开始诬告。**宁可少抓，不可错抓**：一条会误报的判据，
    三轮之后就没人再看它说什么了。
    """
    claim = re.compile(r"已结（\d{4}-\d{2}-\d{2}")
    bad = []
    for header, cells in _rows(_require_registry()):
        rid = cells[0].strip("* ")
        status = _cell(header, cells, "状态")
        if not status or not _is_open(status):
            continue
        for name in header:
            if name in ("RN", "状态"):
                continue
            other = _cell(header, cells, name)
            if other and (m := claim.search(other)):
                bad.append((rid, status[:24], name, m.group(0)))
                break
    assert not bad, (
        "这些条目在**别的格子**里写着已结，而**状态格**还是未结：\n" +
        "\n".join(f"  {rid}  状态={st!r}  「{col}」格里写着 {c!r}"
                  for rid, st, col, c in bad)
    )


#: 档案里**列「这一批做了什么」的表**。落进这些表的 RN = 那次真的动过刀。
#: ⚠ 第一版这条判据是**按行匹配**关键词的（一行里同时出现 RN 号和「关档」就算），
#: 当场误报：`档案/crosshair.md` 那句「RN-120/121 已于 2026-08-20 关档；
#: 剩 RN-174…待裁定」把「关档」算到了 RN-174 头上。
#: ⭐ **档案里「做完了」这件事在行文里没有统一写法，但在表头上有** ——
#: 所以改成认表头，不认措辞。
ARCHIVE_CHANGELOG_HEADERS = {
    ("RN", "做了什么"),
    ("RN", "做了什么", "判据"),
    ("RN", "裁定", "落地", "复跑"),
    ("RN", "裁定", "落地"),
    ("RN", "落地", "复跑结果"),
}
#: 同样以 RN 开头、但**不是**改动台账的表（发现清单、待办清单）。
#: 两张表都要声明，是为了让「出现第三种表头」当场红 —— 否则新表会静默躲开对账。
ARCHIVE_NON_CHANGELOG_HEADERS = {
    ("RN", "一句话"),
    ("RN", "内容"),
    ("RN", "镜头", "来源", "一句话", "堆"),
    ("RN", "镜头", "级别", "一句话", "堆"),
}


def _archive_tables() -> list[tuple[tuple[str, ...], list[str]]]:
    out: list[tuple[tuple[str, ...], list[str]]] = []
    header: tuple[str, ...] | None = None
    for md in sorted(ARCHIVE.glob("*.md")):
        header = None
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("|"):
                header = None
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if cells[0] == "RN":
                header = tuple(cells)
                continue
            if header is not None:
                out.append((header, cells))
    return out


def test_the_archive_table_shapes_are_a_closed_set():
    """分母守卫：新出现一种以 RN 开头的档案表，必须先表态它算不算改动台账。"""
    shapes = {h for h, _ in _archive_tables()}
    known = ARCHIVE_CHANGELOG_HEADERS | ARCHIVE_NON_CHANGELOG_HEADERS
    unknown = sorted(shapes - known)
    assert not unknown, (
        f"档案里出现了没表态过的表形：{unknown}\n"
        "它算「这一批做了什么」还是「发现清单」？加进对应的那张表。"
    )


def test_a_change_log_entry_is_not_still_open_in_the_registry():
    """⭐ 档案的改动台账里写着做了，登记册不许还挂着未结。

    它的独占战果是 **RN-019**：那条的修法是**删掉一个重复函数** ——
    删掉的代码不会在产品代码里留下任何注释，所以上面那条跨仓判据永远看不见它。
    ⭐ **一次"删除"型的修复，是所有"从代码里找证据"的判据的共同盲区。**
    """
    status = _statuses(_require_registry())
    done: set[str] = {
        rid for header, cells in _archive_tables()
        if header in ARCHIVE_CHANGELOG_HEADERS
        and RN_ID.match(rid := cells[0].strip("* "))
    }
    bad = sorted(
        (rid, status[rid][:30]) for rid in done
        if rid in status and _is_open(status[rid])
    )
    assert not bad, (
        "档案的改动台账里写着这一批做了它，登记册里还挂着未结：\n" +
        "\n".join(f"  {rid}  状态={st!r}" for rid, st in bad)
    )


def _product_code_citations() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    files = [p for d in PRODUCT_DIRS for p in (REPO / d).rglob("*.py")]
    files += list(REPO.glob("*.py"))
    for p in files:
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in RN_ANY.finditer(body):
            hits.setdefault("RN-" + m.group(1), []).append(p.name)
    return hits


def test_product_code_that_names_an_rn_is_not_still_open():
    """产品代码里点名一个 RN，通常是在解释「这段代码为什么长这样」= 那条做完了。

    ⚠ 也可能是把它当**先例/族名**引用 —— 那些走 `CITED_AS_PRECEDENT`。
    """
    status = _statuses(_require_registry())
    hits = _product_code_citations()
    bad = sorted(
        (rid, status[rid][:24], sorted(set(where))[:3])
        for rid, where in hits.items()
        if rid in status and _is_open(status[rid]) and rid not in CITED_AS_PRECEDENT
    )
    assert not bad, (
        "产品代码里点名了这些 RN，而登记册里它们还是未结：\n" +
        "\n".join(f"  {rid}  状态={st!r}  出现在 {w}" for rid, st, w in bad) +
        "\n如果确实是把它当先例/族名引用，加进 CITED_AS_PRECEDENT 并写明理由。"
    )


def test_the_precedent_allowlist_does_not_rot():
    """双向断言：允许清单里的每一条都必须 ① 仍被代码点名 ② 仍未结。

    ⭐ 一张只增不减的允许清单，会慢慢变成「这里不用查」的免检区。
    """
    status = _statuses(_require_registry())
    hits = _product_code_citations()
    gone = sorted(rid for rid in CITED_AS_PRECEDENT if rid not in hits)
    closed = sorted(
        rid for rid in CITED_AS_PRECEDENT
        if rid in status and not _is_open(status[rid])
    )
    assert not gone, f"这些已经不再被产品代码点名，从允许清单里删掉：{gone}"
    assert not closed, (
        f"这些已经结了，允许清单不该再替它们留门：{closed}"
    )
