# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-172（批 90 落地）：`build_search_index.py --check` 的退出码**结构上不可信**。

## 今天实测的数（2026-09-13，连跑 6 次，`H:/tmp/b90_rn172_exitcode.py`）

| 次 | 退出码 | 内容判定 |
|---|---|---|
| 1 | **3221226505**（`0xC0000409`）| 索引与代码同步 |
| 2~6 | 0 | 索引与代码同步 |

⇒ **约 1/6 的运行会带着一个原生层崩溃码退出，而它的裁定是对的。**
立案那天（2026-08-14）拿到的是 `1 / 127 / 0 / 3221226505` 四种，今天仍然复现得出来。

## 为什么不去修那个崩溃

`0xC0000409` 是 `teardown()` 里 **Qt 原生层**的栈保护触发，早于任何 Python 层接管：
`_teardown_guarded` 的 `except SystemExit` / `except Exception` 都接不住它，
它的看门狗 Timer 也来不及响（崩溃是瞬时的）。
⭐ 而 RN-092 / RN-511 早就把这条路走通了：**裁定从退出码里搬出来，改成裁定行**
（`announce("search_index", code)` 落在退出链路**之前**）。
⇒ 本条要守的不是「让退出码变准」，是**「别再有人回去读它」**。

## ⛔⛔ 既有那支退出码判据看不见这件事，而它读起来像看得见

`tests/test_search_index_check_exit_code.py` 的进程层用例**把 `build` 和 `teardown`
都换成了桩** —— 所以它证明的是「**teardown 是空操作时**，退出码管线是对的」，
而真实的那次崩溃**正好发生在 teardown 里**。
⭐⭐⭐ **一支专门测退出码的判据，把产生错误退出码的那一段桩掉了。**
（那支判据本身没写错 —— 它要跑得快就必须桩掉 Qt。错的是**把它读成全覆盖**。）
"""
from __future__ import annotations

import re
from pathlib import Path

from _denominator import must_scan

ROOT = Path(__file__).resolve().parents[1]

#: 这个脚本的裁定**只能**从这两条通道读。
VERDICT_CHANNELS = ("verdict.ps1", "parse_verdict", "announce(")

#: 扫这些地方找「谁在跑这个脚本」。
#: ⛔ **不扫 `tests/`** —— 本条守的是「**门禁**别拿退出码当结论」，
#:   而 `tests/test_search_index_check_exit_code.py` 恰恰是**专门测那个退出码**的判据，
#:   它读 `returncode` 是它的职责。⭐ 第一版把 `tests/` 也扫进来，当场把那支判据
#:   和 `test_the_index_gate_is_wired_into_ci.py` 一起报成违规 ——
#:   **一条规则的分母里混进了「它要保护的那件事本身」。**
SCAN_DIRS = ("scripts", "build_tools", ".github")

SCRIPT = "build_search_index.py"


def _files():
    out = []
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and p.suffix in {".py", ".yml", ".yaml", ".ps1"}:
                if p.name == Path(__file__).name:
                    continue
                out.append(p)
    return out


def test_the_scan_actually_finds_the_script():
    """⭐ 分母守卫：扫不到调用点的话，下面那条否定断言必然全绿。"""
    hits = [p for p in _files()
            if SCRIPT in p.read_text(encoding="utf-8", errors="replace")]
    assert len(hits) >= 5, (
        f"只扫到 {len(hits)} 个提到 `{SCRIPT}` 的文件 —— 这支扫描多半自己瞎了。")


def test_no_consumer_judges_this_script_by_its_exit_code():
    """⭐⭐⭐ 本条守的那件事：**没有人拿这个脚本的退出码当结论。**

    判法：找出「真的去跑这个脚本」的地方，再看它同一段里有没有读裁定的通道。
    ⚠ 这是一条**保守**的检查 —— 它只认那几个已知的裁定通道名，
    宁可要求多写一个 `parse_verdict` / `verdict.ps1`，也不去猜「这段大概是安全的」。
    """
    scanned = _files()
    must_scan(scanned, "scripts / build_tools / .github 下会跑脚本的文件", least=20)

    offenders = []
    for p in scanned:
        text = p.read_text(encoding="utf-8", errors="replace")
        if f"{SCRIPT} --check" not in text and f'"{SCRIPT}", "--check"' not in text:
            continue
        # 纯叙述（注释 / 文档字符串里提到它）不算调用点：要求同文件里有
        # 「真的起进程」的痕迹。
        runs = any(k in text for k in ("subprocess", "run:", "run: |", "$ErrorActionPreference"))
        if not runs:
            continue
        if any(ch in text for ch in VERDICT_CHANNELS):
            continue
        offenders.append(p.relative_to(ROOT).as_posix())

    assert not offenders, (
        "这些地方跑了 `build_search_index.py --check`，却没有任何一条读裁定行的通道：\n  "
        + "\n  ".join(offenders)
        + "\n⭐⭐⭐ 这个脚本的退出码实测 **1/6 会是 `0xC0000409`**（原生层崩溃），"
        "而它的裁定同时是对的。\n"
        "⇒ 读 `announce()` 打出来的裁定行（CI 走 `.github/verdict.ps1`，"
        "本机走 `scripts/gate.py` 的 `parse_verdict`），**别读退出码**。")


def test_the_verdict_line_is_printed_before_the_exit_path():
    """⭐ 上面那条的前提：裁定行必须在**退出链路之前**落地。

    ⛔ 它要是排在 `_teardown_guarded` 之后，崩溃那 1/6 就会连裁定行都没有 ——
    而「没有裁定行」按规矩算失败 ⇒ 变成 1/6 的假红，比现在更坏。

    ⛔⛔ **只在 `main()` 的函数体里比先后。** 本条第一版拿整份源码的字符下标比，
    当场判红 —— 因为 `_teardown_guarded` 的**定义**在文件第 622 行，
    而 `announce(...)` 的**调用**在 `main()` 里、更靠后。
    ⭐⭐⭐ **定义的位置和调用的位置是两件事**（RN-620 原样复发，这次犯在我自己
    这一批新写的判据上）。
    """
    import ast

    src = (ROOT / "scripts" / SCRIPT).read_text(encoding="utf-8")
    tree = ast.parse(src)
    main_fn = next((n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main_fn is not None, "`build_search_index.py` 里找不到 `main()`。"
    body = ast.get_source_segment(src, main_fn) or ""

    i_announce = body.find('announce("search_index"')
    i_teardown = body.find("_teardown_guarded(handles")
    assert i_announce >= 0, "`main()` 里不再打裁定行了 —— 那这一族判据全部作废。"
    assert i_teardown >= 0, "`main()` 里找不到 `_teardown_guarded(handles` 这一步。"
    assert i_announce < i_teardown, (
        "裁定行排到了收尾清理之后 —— 而收尾清理实测 1/6 会带着原生崩溃码退出。\n"
        "⭐ 那一刻裁定行还没打出来 ⇒ 读的人拿到「没有结论」⇒ 按失败处理。")


def test_the_existing_exit_code_judge_says_out_loud_what_it_cannot_see():
    """⭐⭐⭐ 那支退出码判据把 `teardown` 桩掉了 —— 这句话必须写在它自己文件里。

    ⛔ 不写的话，下一个人（包括我）会把「退出码判据全绿」读成
    「退出码可信」，而它证明的只是「**teardown 是空操作时**管线是对的」。
    ⚠ 本条查的是**那份文件里有没有这句自述**，不是查它的实现 ——
    实现本来就该桩掉 Qt（否则它跑不到 1 秒）。
    """
    p = ROOT / "tests" / "test_search_index_check_exit_code.py"
    text = p.read_text(encoding="utf-8")
    assert re.search(r"看不见|覆盖不到|桩掉的那一段", text), (
        f"{p.name} 里没有一句说明它**看不见什么**。\n"
        "它的进程层用例把 `build` 和 `teardown` 都换成了桩，而真实的那次崩溃"
        "（1/6，`0xC0000409`）正好发生在 `teardown` 里。\n"
        "⭐ 一支专门测退出码的判据，把产生错误退出码的那一段桩掉了 —— "
        "这件事不写在它自己文件里，就没有人会知道。")
