# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-430：登记册会**重复立案**，而 RN-198 那组棘轮结构性地看不见这件事。

RN-198 有四条对账判据，形态**完全一致**：
「同一个号在**别处**声称已修，而状态格还写着未结」。

而这里的病是**两个号在说同一件事**：

| 真源 | 重复立的 | 差别 |
|---|---|---|
| RN-103 状态胶囊长得像按钮 | RN-149（全站 20+ 页）、RN-183 后半（4 发 / 4 页）| 分母不同 |
| RN-181 缺少批量套用（35 发 / 10 页）| RN-106（音效四页）| 分母不同 |
| RN-109 「测试」按钮在不启用时仍可点 | RN-412（crosshair）| 分母写窄了 |
| RN-429 覆盖层的运行前提没说 | RN-409（只立了 crosshair 一页）| 分母写窄了 |

⭐⭐⭐ **判据看不见「重复」，因为重复不是自相矛盾。**
两行各自完全自洽 —— 一条说「胶囊像按钮」，另一条也说「胶囊像按钮」，
任何一致性判据都挑不出毛病。

## ⭐⭐ 而更值得记的是：**关系其实早就写下来了，只是写在散文里**

RN-412 的证据格逐字写着「**RN-109 族在 crosshair 上的实例**」，
还点名了 RN-258/272/288 是它在旧账里的三个实例，甚至直接写了
「本页顺带证明了 RN-109 的分母写窄了」。RN-183 写着「与 RN-107 族是一体两面」，
RN-149 写着「与 RN-144 是一对」。

⇒ **我一直认得出重复，我只是把它记在了机器读不到的地方。**
状态格照旧是「立案」，于是统计、排期、未结清单里它们仍然是两条。

⭐⭐⭐ **一条关系写在散文里，等于只写给恰好读到那一行的人。**
本判据要求的不是「发现重复」（那件事人做得挺好），而是
**把已经认出来的关系提升成一个机器读得到的格子**。

修法**不加列**：「并入 RN-xxx」本身就是一种结项状态，
而状态词表早就有双向判据看着（`test_the_status_vocabulary_does_not_rot`）。

⚠ **「并入」算「已结」是安全的，但它的安全性不是自带的** ——
它来自下面 ①② 两条：目标必须真实存在、且不许自己也是并入。
⭐ **一个「结项」状态的安全性，来自另一条判据保证它指向的东西真的还在。**
没有 ①②，「并入 RN-999」就是一句让条目凭空消失的咒语。

## 第二件事：旧账那 104 行的**归宿格**

RN-198 明写着旧账逐页表「没有状态列」是**已知且被声明的盲区**。
本判据不去动那张表的形状（重排要动 24 个页面小节），
而是把它已经有的**「主题」格当成归宿格**用，取值封闭为：

    RN-xxx（在册的号，随它走） | 已结 | 不成立 | —（还没定）

然后只断言一件事：**一页在页面清单里标了「已关档」，它名下的旧账行不许还是「—」。**

⭐ 这条判据首跑逮到 4 行（advanced ×2 / gun_sound ×2），逐条查实之后：

- `RN-210`（首屏摆调试密码框）**早被 RN-133 修掉了**（收进专家模式）；
- `RN-257`（原声保留 / 静音覆盖 术语抽象）**早被 RN-052 修掉了**
  —— `pages/gun_sound_page.py:344` 的注释逐字引用着这条外审原话；
- `RN-212`（锚点 chips 无激活态）**仍然成立**，且不止一页（advanced + magnifier）；
- `RN-254`（全自动武器被排除的原因未查明）**仍然开着**。

⭐⭐ 前两条是同一个形态，而且是本工程第二次撞到它：
**修的人把「这修的是哪一条」写清楚了 —— 写的是自己那个号。
旧账里那条描述同一件事的行，没有任何机制会被通知。**
⇒ 一页关档时，它名下的旧账行必须各自有归宿，这件事得有人看着。

⚠ **这条判据只防未来，不追认过去**：`RN-249`（fun_afterlife 独占全屏）
同样早就被 `pages/fun_page.py:82` 说掉了一半，而 fun_afterlife 还没开工，
所以判据当下够不着它 —— 它是靠人查出来的，不是靠判据。**明写出来，不粉饰。**
"""
from __future__ import annotations

import re

import pytest

# ⚠ 解析器**直接复用** RN-198 那支，不抄第二份。
# 登记册的表结构只该有一个读法：抄一份出来，两边就会各自漂
# （RN-002 那 9 份名单、RN-198 号段声明的第二份副本，都是这么来的）。
from tests.test_renovation_registry_does_not_rot import (  # noqa: E402
    CAMPAIGN,
    RN_ID,
    _cell,
    _is_open,
    _rows,
    _status_word,
    _statuses,
)
from _denominator import must_scan

#: 归宿格允许的非 RN 取值。⚠ 故意**不含**「独立跟踪」这类词 ——
#: 一条要继续被跟踪的旧账行，正确形态是**升格**（在有状态格的表里开一行，
#: 归宿格指过去），不是在一个没有状态格的表里声称自己在被跟踪。
#: ⭐ 一个没地方记录进展的「在跟踪中」，和「没人管」在结果上没有区别。
HOME_WORDS = frozenset({"已结", "不成立"})
UNDECIDED = frozenset({"—", "-", ""})

_MERGE = re.compile(r"^并入\s*(RN-\d{3})")

#: 页面清单里那张**页面表**的表头。其它三张表（批次台账 / 里程碑 / 交叉链路）
#: 也有「状态」格，也会出现「已关档」⇒ 必须按表头挑，不能按关键字扫。
#: ⭐ 同 RN-189：分母要取真源，不是「凡是像的都算」。
PAGE_TABLE_HEADER = (
    "批次", "page_id", "显示名", "实现文件", "行数", "使用", "同名测试", "风险", "状态",
)


def _require_registry() -> str:
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程（登记册 + 档案）—— 这几条只在两个仓都在时可比")
    return (CAMPAIGN / "登记册.md").read_text(encoding="utf-8")


def _require_board() -> str:
    if CAMPAIGN is None:
        pytest.skip("同级目录里没有翻新工程（登记册 + 档案）—— 这几条只在两个仓都在时可比")
    board = CAMPAIGN / "页面清单与进度.md"
    assert board.is_file(), (
        f"找到了翻新工程目录却没有 {board.name} —— 那是**文件被挪走或改名了**，"
        "是腐烂本身，不是样本不可比（RN-140）。"
    )
    return board.read_text(encoding="utf-8")


def _merged(text: str) -> dict[str, str]:
    """所有「并入 RN-xxx」的条目 → 它指向的号。"""
    out: dict[str, str] = {}
    for rn, status in _statuses(text).items():
        m = _MERGE.match(re.sub(r"\*+", "", status).lstrip("⚠⭐⛔ "))
        if m:
            out[rn] = m.group(1)
    return out


def _old_ledger_rows(text: str) -> list[tuple[str, str, str]]:
    """旧账逐页表：(page_id, RN, 归宿格)。page_id 取自小节标题的第一个词。

    ⚠ 「归宿格」历史上取的是**主题**格 —— 那是当时唯一能表态的地方，
      因为这张表**没有状态列**。2026-09-02 批 41 补上状态列之后，
      归宿改由 `_old_ledger_status()` 从**状态**格读。
    ⭐⭐⭐ 而旧写法留下了一个很难看见的后果：`test_a_closed_page_has_no_homeless_old_ledger_rows`
      对 RN-250 / RN-267 一直是**绿**的 —— 不是因为它们有归宿，
      是因为有人把「已结」「不成立」这两个**结论**直接打进了主题格，
      而那条判据只问「主题格是不是 `—`」。
      ⇒ **一条判据被「写错格子」这件事满足了：错误的数据让它变绿。**
    """
    out: list[tuple[str, str, str]] = []
    page: str | None = None
    in_section = False
    header: tuple[str, ...] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line.startswith("## 三、")
            continue
        if in_section and line.startswith("### "):
            page = re.split(r"[（(\s]", line[4:].strip())[0]
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0] == "RN":
            header = tuple(cells)
            continue
        if header is None or "主题" not in header or page is None:
            continue
        if not RN_ID.match(cells[0].strip("* ")):
            continue
        home = _cell(header, cells, "主题") or ""
        out.append((page, cells[0].strip("* "), home))
    return out


def _closed_pages(board: str) -> set[str]:
    """页面清单里状态格写着「已关档」的 page_id。"""
    out: set[str] = set()
    header: tuple[str, ...] | None = None
    for line in board.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if tuple(cells) == PAGE_TABLE_HEADER:
            header = tuple(cells)
            continue
        if header is None or len(cells) != len(header):
            continue
        status = re.sub(r"\*+", "", cells[header.index("状态")]).strip()
        if status.startswith("已关档"):
            out.add(cells[header.index("page_id")])
    return out


# ------------------------------------------------------------------ 判据

def test_a_merge_points_at_a_row_that_actually_exists():
    """① 「并入」必须写成 `并入 RN-xxx`，且那个号在登记册里真的有一行。

    ⚠ 这条是「并入算已结」的**前提**。没有它，`并入 RN-999` 就是一句
    让条目凭空消失的咒语 —— 而且消失得毫无痕迹，因为它在统计里算结了。
    """
    text = _require_registry()
    known = must_scan(set(_statuses(text)) | {rn for _, rn, _ in _old_ledger_rows(text)},
                      "登记册里在册的 RN 号（主表 + 旧账表）", least=300)
    bad = []
    for rn, status in _statuses(text).items():
        bare = re.sub(r"\*+", "", status).lstrip("⚠⭐⛔ ")
        if not bare.startswith("并入"):
            continue
        m = _MERGE.match(bare)
        if m is None:
            bad.append(f"{rn}：状态写着「并入」却没给号 —— {status!r}")
        elif m.group(1) not in known:
            bad.append(f"{rn} 并入 {m.group(1)}，而登记册里没有 {m.group(1)} 这一行")
    assert not bad, "并入指向了不存在的条目：\n  " + "\n  ".join(bad)


def test_a_merge_does_not_point_at_another_merge():
    """② 禁止并入链：A 并入 B、B 又并入 C。

    ⭐ 链一旦允许，「真源是谁」就变成了要顺着走几跳才知道的事，
    而下一个人只会看第一跳。**真源必须一跳可达。**
    """
    text = _require_registry()
    merged = _merged(text)
    chained = [f"{a} → {b} → {merged[b]}" for a, b in merged.items() if b in merged]
    assert not chained, (
        "出现了并入链，真源不再一跳可达：\n  " + "\n  ".join(chained)
    )


# ⛔ 这里原本有第三条：「并入方不许在别的格子里还写着立案/待裁定」——
# 想做 RN-198 那条 `says_closed_somewhere_else` 的反向版。**写完当场撤掉了。**
#
# 它首跑逮到的唯一一条是 RN-412 的证据格：「RN-109 **立案**时的分母是……」
# —— 那句话说的是**另一条**的状态，不是它自己的。
#
# ⚠ 而这正是 RN-198 那支自己早就写下来的教训：`_status_word` 必须从**开头**读，
# 因为「那页已修、这页还在」说的是别的条目。我在同一份文档上又踩了一次，
# 只是换了个方向。
#
# ⭐⭐ 两个方向不对称，而不对称的原因是**信号的具体度**：
# 「已结（2026-08-18）」带日期、格式固定，几乎不可能是在说别人；
# 而「立案 / 待裁定」是散文里的常用词，**没有任何低噪声的写法**。
# ⇒ 与其打一场正则军备竞赛，不如承认这条没有可用信号。
# ⭐ **一条只能靠"请别在正文里用这个词"来维持绿的判据，
#   训练出来的不是更好的账目，是更别扭的散文。**


def test_the_home_cell_of_an_old_ledger_row_is_a_closed_vocabulary():
    """④ 旧账行的归宿格取值封闭：在册的 RN 号 / 已结 / 不成立 / —。

    ⭐ 分母守卫的一种：一个随便写的归宿格，会让下面那条
    「已关档的页不许有无归宿的行」在**看起来填了**的时候静默放行。
    """
    text = _require_registry()
    known = must_scan(set(_statuses(text)) | {rn for _, rn, _ in _old_ledger_rows(text)},
                      "登记册里在册的 RN 号（主表 + 旧账表）", least=300)
    bad = []
    for page, rn, home in must_scan(_old_ledger_rows(text), "旧账逐页表的行", least=80):
        bare = re.sub(r"\*+", "", home).strip()
        if bare in UNDECIDED or bare in HOME_WORDS:
            continue
        for token in re.split(r"\s*/\s*", bare):
            if not RN_ID.match(token):
                bad.append(f"{page} {rn}：归宿格 {home!r} 不在封闭词表里")
            elif token not in known:
                bad.append(f"{page} {rn}：归宿指向 {token}，而登记册里没有这一行")
    assert not bad, "\n  ".join(["旧账归宿格越界："] + bad)


def test_an_old_ledger_row_does_not_point_at_a_merged_entry():
    """⑤ 归宿不许指向一个**已经并入别人**的号。

    ⭐ 这条是并号动作的**收尾**：把 RN-106 并进 RN-181 之后，
    第三节那 4 行还指着 RN-106 ⇒ 下一个人从旧账出发，第一跳就落在
    一条已经不是真源的条目上。**并号不是改一格，是改一条边。**
    """
    text = _require_registry()
    merged = must_scan(_merged(text), "状态是「并入 RN-xxx」的条目", least=20)
    must_scan(_old_ledger_rows(text), "旧账逐页表的行", least=80)
    bad = [
        f"{page} {rn}：归宿指向 {token}，而 {token} 已并入 {merged[token]}"
        for page, rn, home in _old_ledger_rows(text)
        for token in re.split(r"\s*/\s*", re.sub(r"\*+", "", home).strip())
        if token in merged
    ]
    assert not bad, "\n  ".join(["旧账归宿指向了已被并入的条目："] + bad)


#: ⭐ 已关档的页名下**还没有人判过**的旧账行数。**只许变少。**
#:
#: 2026-09-02 批 41 首测：**0 行**。90 行旧账里 74 行的归宿早就写在「主题」格
#: （= 并入某条跨页主题）、4 行的结论写在别的格子里，真正没人判过的只有 **12 行**，
#: 而那 12 行**全部落在还没开工的页上**（about / audio_health / audio_import_wizard /
#: audio_replay / audio_task_panel / basic / hud_color）—— 那是合法的待办，不是欠账。
#:
#: ⚠⚠ **这个 0 推翻的是我自己的一个中间结论。** 补完状态列的第一版里，
#:   我把 90 行**一律**填成「未判定」，于是算出「已关档页上有 56 行 / 17 页」，
#:   并且差一点拿这个数去推翻判据模块头里那条「实测有 3 页，属合法噪声」的豁免。
#: ⭐⭐⭐ **那 56 是我自己造出来的** —— 把「归宿写在另一个格子里」误读成了
#:   「没有人判过」。⇒ **拿一个新分母去推翻旧结论之前，先确认新分母不是自己造的。**
#:   （本工程反复栽在分母上：批 34 三个错的分母、批 39 白名单当分母，
#:    这一次错的分母是我的，而它差点被写进档案当成一条"发现"。）
#:
#: ⛔ 调小它的唯一正当方式是**真的去判那几行**（已结 / 不成立 / 并入 / 立案），
#:   不是把 `未判定` 换成一个更好听的词。
#: ⭐ 它现在是 0，意味着这条判据从今往后是**硬约束**：
#:   一页要关档，它名下的旧账行必须先有人表态。
MAX_UNJUDGED_ON_CLOSED_PAGES = 0


def _old_ledger_status(text: str) -> dict[str, str]:
    """旧账逐页表：RN → 状态格（批 41 起这张表才有这一列）。"""
    out: dict[str, str] = {}
    in_section = False
    header: tuple[str, ...] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line.startswith("## 三、")
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0] == "RN":
            header = tuple(cells)
            continue
        if header is None or "状态" not in header:
            continue
        if not RN_ID.match(cells[0].strip("* ")):
            continue
        out[cells[0].strip("* ")] = _cell(header, cells, "状态") or ""
    return out


def test_a_closed_page_has_no_homeless_old_ledger_rows():
    """⑥ 一页标了「已关档」，它名下的旧账行不许还是「—」。

    ⭐ 关档的含义是「这一页自己那本账清了」。而旧账那张表原来没有状态列，
    于是它名下的行**从来没有被要求表态过** —— 关的是别的账。
    """
    board = _require_board()
    text = _require_registry()
    closed = must_scan(_closed_pages(board), "页面清单里标了「已关档」的页", least=10)
    must_scan(_old_ledger_rows(text), "旧账逐页表的行", least=80)
    homeless = [
        f"{page} {rn}"
        for page, rn, home in _old_ledger_rows(text)
        if page in closed and re.sub(r"\*+", "", home).strip() in UNDECIDED
        and not _old_ledger_status(text).get(rn, "").startswith(
            ("已结", "并入", "实测后不成立", "作废", "不修", "已修", "记录不做"))
    ]
    assert not homeless, (
        "这些页已关档，名下的旧账行却还没有归宿（既没随主题走，也没说已结/不成立）：\n  "
        + "\n  ".join(homeless)
    )


# --------------------------------------------------- 空转守卫（先证明看得见）

_SYNTHETIC_MERGE = """
| RN | 档案 | 镜头 | 级别 | 一句话 | 堆 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|
| RN-901 | 某页 | ②UX | S3 | 真源 | A | 立案 | — |
| RN-902 | 某页 | ②UX | S3 | 干净的并入 | A | **并入 RN-901** | 同一件事 |
| RN-903 | 某页 | ②UX | S3 | 并入了一个不存在的号 | A | 并入 RN-999 | — |
| RN-904 | 某页 | ②UX | S3 | 并入链的中段 | A | 并入 RN-902 | — |
"""

_SYNTHETIC_OLD = """
## 三、逐页发现

### somepage（2→2）
| RN | G级 | 级别 | 位置 | 一句话 | 主题 | 堆 |
|---|---|---|---|---|---|---|
| RN-911 | 高 | S3 | 某处 | 有归宿 | RN-901 | B? |
| RN-912 | 高 | S3 | 某处 | 没归宿 | — | B? |
"""

_SYNTHETIC_BOARD = """
| 批次 | page_id | 显示名 | 实现文件 | 行数 | 使用 | 同名测试 | 风险 | 状态 |
|---|---|---|---|---|---|---|---|---|
| P0 | somepage | 某页 | pages/x.py | 1 | 1 | 有 | | **已关档**（都清了）|
| P0 | otherpage | 另一页 | pages/y.py | 1 | 1 | 有 | | 未开工 |

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M9 | 一条**不该**被认成页面的行 | **已关档** |
"""


def test_every_reader_skips_cleanly_when_there_is_no_campaign(monkeypatch):
    """⭐⭐ 本模块**自己**的 skip 路径，不能靠 RN-198 那支替它验。

    ⚠ 那支有一条同名判据，但它 monkeypatch 的是**它自己模块**的 `CAMPAIGN`；
    本模块是 `from … import CAMPAIGN`，拿到的是**导入那一刻的值**，
    改那边不影响这边。⇒ 两支各验各的。

    而本机验不出真实条件：开源仓副本和私有仓是**同级目录**，
    `_find_campaign()` 在那份「开源仓」里照样找得到登记册
    ⇒ **两个仓都跑绿，公开 CI 照样红**（RN-198 那支就是这么红过一次的）。
    ⇒ 与其指望某个环境替我制造那个条件，不如自己把它造出来（RN-142）。

    ⚠ **这条判据被写过两遍。** 第一遍写在 2026-08-28 批 21 的中途，
    而当时 `revert_verify` 正在后台跑 —— 它启动时给要改的文件做了快照，
    收尾一句「所有文件已还原至改动前状态」把我这段**一起还原掉了**。
    ⭐⭐ RN-093 记的是「它跑着的时候不许并行跑测试」，而真正的危险面更宽：
    **它跑着的时候，仓里的文件不归我。** 它把这件事说成一句客气话，
    不是「我刚删掉了你写的东西」。
    """
    import sys as _sys
    monkeypatch.setattr(_sys.modules[__name__], "CAMPAIGN", None)

    for name, fn in (("_require_registry", _require_registry),
                     ("_require_board", _require_board)):
        with pytest.raises(BaseException) as caught:
            fn()
        assert caught.typename == "Skipped", (
            f"{name}() 在「没有翻新工程」时抛的是 {caught.typename}，不是 skip —— "
            "公开 CI 上会当场红，而本机因为镜像与私有仓同级而永远发现不了。"
        )


def test_the_parsers_actually_see_the_synthetic_input():
    """⭐ 先证明这几个解析器看得见东西，再让判据去断言「没问题」。

    一个把登记册解析成 0 行的解析器，会让上面每一条断言**无条件通过**。
    """
    assert _merged(_SYNTHETIC_MERGE) == {
        "RN-902": "RN-901", "RN-903": "RN-999", "RN-904": "RN-902",
    }
    assert _old_ledger_rows(_SYNTHETIC_OLD) == [
        ("somepage", "RN-911", "RN-901"),
        ("somepage", "RN-912", "—"),
    ]
    assert _closed_pages(_SYNTHETIC_BOARD) == {"somepage"}, (
        "页面清单里另外三张表也有「状态」格、也写「已关档」—— "
        "必须按表头挑，不能按关键字扫。"
    )


def test_the_synthetic_defects_are_actually_caught():
    """把上面几条判据的判定逻辑原样跑在合成数据上，逐个确认它们咬得动。"""
    merged = _merged(_SYNTHETIC_MERGE)
    known = {c[0].strip("* ") for _, c in _rows(_SYNTHETIC_MERGE)}

    assert "RN-999" not in known and merged["RN-903"] == "RN-999", "① 咬不动"
    assert merged["RN-904"] in merged, "② 咬不动：并入链没被认出来"
    # ⚠ 这一条第一版写反了：我写的是 `_status_word("并入 RN-901") is None`
    # —— 那钉住的是**缺陷本身**（「并入还没进词表」），于是它会在这批把词表补好的
    # 那一刻变红。RN-141 那个形态，本工程第八次。
    # ⭐ **判据要钉住修好之后该成立的事，不是钉住此刻的现状。**
    assert _status_word("并入 RN-901") == "并入", (
        "「并入」不在 STATUS_WORDS 里 —— 那 RN-198 的 `_is_open` 会把它判成**没结**，"
        "并入的条目仍然出现在未结清单里，本批等于白做。"
    )
    assert not _is_open("并入 RN-901"), (
        "「并入」被判成还开着 —— 那真源和并入方会被重复计一次，"
        "统计上和没并过一模一样。"
    )

    homeless = [rn for _, rn, home in _old_ledger_rows(_SYNTHETIC_OLD)
                if home.strip() in UNDECIDED]
    assert homeless == ["RN-912"], "⑥ 咬不动：无归宿的行没被认出来"


def test_unjudged_old_ledger_rows_on_closed_pages_only_shrink():
    """⭐⭐⭐ 已关档的页名下，还挂着多少行**从来没有人判过**的旧账。**棘轮，只许变少。**

    这个数在 2026-09-02 批 41 之前是**量不出来的**：那张表没有状态列，
    机器读不到「判没判过」。补上之后首测 **0 行** —— 90 行里 74 行的归宿
    早就写在「主题」格（并入某条跨页主题），真正没人判过的 12 行
    **全部落在还没开工的页上**。

    ⚠⚠ **这条判据的首测值推翻的是我自己**：补列的第一版我把 90 行一律填成
      「未判定」，算出「56 行 / 17 页」，并且差一点拿它去推翻判据模块头里
      那条「`已关档` 而名下仍有未结条目，实测有 **3 页**，属合法噪声」的豁免。
    ⭐⭐⭐ 那 56 是我自己造出来的 —— 把「归宿写在另一个格子里」
      误读成了「没有人判过」。**拿一个新分母去推翻旧结论之前，
      先确认新分母不是自己造的。**

    ⭐ 现在它是 0，于是这条从「待判清单的棘轮」变成一条**硬约束**：
      一页要关档，它名下的旧账行必须先有人表态。
    """
    board = _require_board()
    text = _require_registry()
    closed = _closed_pages(board)
    status = _old_ledger_status(text)
    unjudged = sorted(
        f"{page} {rn}"
        for page, rn, _home in _old_ledger_rows(text)
        if page in closed and status.get(rn, "").startswith("未判定")
    )
    # 空转守卫：分母塌了（表没解析到 / 页面表没解析到）时，上面那个列表天然为空。
    assert len(status) >= 90, f"旧账表只解析到 {len(status)} 行状态 —— 分母塌了"
    assert len(closed) >= 10, f"只认出 {len(closed)} 个已关档页 —— 分母塌了"
    assert len(unjudged) <= MAX_UNJUDGED_ON_CLOSED_PAGES, (
        f"已关档页名下「未判定」的旧账行从 {MAX_UNJUDGED_ON_CLOSED_PAGES} "
        f"涨到了 {len(unjudged)} 行：\n  " + "\n  ".join(unjudged[-12:]) +
        "\n⇒ 要么把新关档那一页的旧账行判掉，要么它还不该关档。"
    )


def test_the_real_registry_is_not_read_as_empty():
    """真登记册上的分母守卫：解析到 0 行时，上面每一条都是绿的。

    ⚠ 三个数分开断言 —— 「旧账表塌了」和「这一批恰好没有并入」是两件事
    （批 19 那条反空转断言改了三版才把这两件分开）。
    """
    text = _require_registry()
    board = _require_board()
    assert len(_old_ledger_rows(text)) >= 90, "旧账逐页表解析塌了"
    assert len(_closed_pages(board)) >= 10, "页面清单的页面表解析塌了"
    assert len(_merged(text)) >= 3, (
        "登记册里一条「并入」都没有 —— 要么这批并号没落盘，"
        "要么状态格的写法漂了，两种情况下 ①②⑤ 都是空转的。"
    )
