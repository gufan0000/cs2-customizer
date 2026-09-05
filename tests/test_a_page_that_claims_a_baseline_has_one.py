# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面清单说「锁基线 / 已关档」的页，基线目录里必须真有那份基线。

## 缺陷（RN-521）

批 46 把专家音频四页的状态格写成「**盘点·锁基线**」，而那一笔提交
**一个基线文件都没碰**：`tests/baselines/renovation/` 下四页一个目录都没有。
两批之后（批 49）要关档时才发现 —— `--verify` 直接答「没有基线，先 --capture」。

⭐⭐⭐ 更要命的是它**没有任何判据会红**：结构基线与指纹那两条判据的分母是
「**基线目录里已经有的那些页**」（`_pages_with_baseline()` 走 `BASELINE_DIR.iterdir()`）——
一页没有基线，它就**天生不在分母里**，于是「这一页没人看着」这件事本身，
恰恰是它躲开所有看守的方式。

⚠ 这是 RN-483（闭集守卫拿自己的白名单当分母）、RN-511（按命名约定划分母）之后
**同一形态第三次**。这一次的白名单是「磁盘上已经存在的目录」。
⇒ 分母必须来自**另一侧**：页面清单里**声称**锁过基线的那些页。

## 这条判据的分母

`CS2 Customizer_翻新工程/页面清单与进度.md` 的页面表里，状态格含「锁基线」或「已关档」
的每一页。⭐ 声称在先、证据在后 —— 谁声称，谁就进分母。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO / "tests" / "baselines" / "renovation"

#: 状态格里出现这些词，就等于声称「这一页的基线已经在库里了」
CLAIMS_BASELINE = ("锁基线", "已关档")

#: 基线三件套里，**每一页都必须有**的那几份。
#: ⚠ `full.png` / `compact.png` 是本机像素、不进 CI（见 `renovation_baseline` ③），
#:   所以这里只钉进 CI 的那三份。
REQUIRED_FILES = ("structure.json", "fingerprint.json", "bench.json")


def _board() -> str:
    board = REPO.parent / "CS2 Customizer_翻新工程" / "页面清单与进度.md"
    if not board.exists():
        pytest.skip("同级目录里没有翻新工程 —— 这条只在两个仓都在时可比")
    return board.read_text(encoding="utf-8")


def _pages_claiming_a_baseline() -> list[tuple[str, str]]:
    """页面表里声称锁过基线的页。返回 (page_id, 状态格前 20 字)。"""
    out = []
    for line in _board().splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 9:
            continue
        page_id = cells[1]
        status = cells[8]
        if not re.fullmatch(r"[a-z][a-z0-9_]+", page_id):
            continue
        if any(word in status for word in CLAIMS_BASELINE):
            out.append((page_id, re.sub(r"\*+", "", status)[:20]))
    return out


def test_every_page_claiming_a_baseline_actually_has_one():
    claimed = _pages_claiming_a_baseline()
    assert len(claimed) >= 20, (
        f"只认出 {len(claimed)} 页声称锁过基线 —— 识别器多半瞎了（表结构变了？），"
        "而不是真的这么少。⭐ 这条判据的价值全在分母上。")

    missing = []
    for page_id, status in claimed:
        page_dir = BASELINE_DIR / page_id
        if not page_dir.is_dir():
            missing.append(f"{page_id}（状态='{status}'）：基线目录根本不存在")
            continue
        gone = [f for f in REQUIRED_FILES if not (page_dir / f).is_file()]
        if gone:
            missing.append(f"{page_id}（状态='{status}'）：缺 {gone}")

    assert not missing, (
        "这些页在页面清单里**声称**锁过基线，而基线并不在库里：\n  "
        + "\n  ".join(missing)
        + "\n⇒ 跑 `python scripts/renovation_baseline.py --capture <页>`。\n"
          "（批 46 把四页写成「盘点·锁基线」而那一笔提交一个基线文件都没碰，"
          "两批之后才发现 —— 因为基线判据的分母是「磁盘上已有的目录」，"
          "**没有基线的页天生不在分母里**。RN-483 / RN-511 之后同一形态第三次。）")


def test_the_baseline_dir_has_no_page_the_board_never_heard_of():
    """反向：库里有基线、清单里却没这一页 —— 那份基线没人对账。"""
    if not BASELINE_DIR.is_dir():
        pytest.skip("还没有任何基线")
    on_disk = must_scan(
        {d.name for d in BASELINE_DIR.iterdir()
         if d.is_dir() and not d.name.startswith("_")},
        "基线库里的页目录")
    board = _board()
    orphans = sorted(p for p in on_disk if p not in board)
    assert not orphans, (
        f"这些页有基线，页面清单里却找不到它们：{orphans}\n"
        "要么页改名了（基线跟着改），要么这份基线已经没有对应的页了。")
