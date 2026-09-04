# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-092：阻断级的门必须读**审计自己打的裁定行**，不许读进程退出码。

**这条是被一次假红逼出来的。** 2026-08-17 的 CI 运行 `41217bf`：
焦点巡检 28 个页面全部 0 处错位、打印「== 焦点巡检 通过 ==」和「RESULT rc=0」，
**0.66 秒后进程退出码 1、无 traceback**，整个 M3-b 里程碑的 CI 被这条假红盖掉。

RN-068 早就诊断出「退出码在 Qt 退出期不可靠」并让审计打了那行机器可读的裁定，
**但没有人去读它** —— CI 那一步仍然是 `run: python scripts/tab_order_audit.py`，
判定权还在退出码手里。
⇒ ⭐ **修复交付了一条可信通道，却没有把门接到那条通道上，等于没修。**
这是「判据/工装自身腐烂」之外的另一种半截修复：**通道建好了、消费者没换。**

反方向的坑更致命且已在 QA 台账里：门禁脚本的非零退出码被产品退出链路**洗成 0**。
所以这道门的设计是**洗不成假绿**的：裁定行缺失一律按失败处理。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github" / "workflows" / "ci.yml"
GATE = REPO / ".github" / "verdict.ps1"

#: UP-091：`scripts/` 里两个**语法都不合法**的历史损坏文件（双重编码的 mojibake +
#: 未闭合字符串）。它们 import 不进来、`ruff.toml` 里排除着、任何 AST 判据也读不了。
#: 处置待用户拍板 —— 在那之前，这张表让「跳过它们」这件事**是被断言的**，
#: 而不是悄悄发生的。
# ⭐ 2026-08-26（RN-199）：**空了** —— 随整条教程流水线删除。
KNOWN_UNPARSEABLE = ()

#: 跑这些脚本的步骤就是「阻断级的门」，必须走裁定行。
#: ⚠⚠ **RN-511（2026-09-04 批 46）：这条正则原来写的是 `scripts/*audit*.py`** ——
#:   分母是「**脚本名里带 audit 的步骤**」，而不是「**会决定 CI 红绿的步骤**」。
#:   于是批 45 加进 CI 的「搜索索引同步(阻断级)」跑的是 `build_search_index.py`，
#:   **结构上进不了这条判据的分母**，它拿 `$LASTEXITCODE` 当裁定用了一整批，
#:   而这份文件的 docstring 从头到尾讲的就是不许这么干。
#: ⭐⭐⭐ **一条守着某个纪律的判据，如果分母按命名约定划，
#:   那么第一个不守命名约定的违规者天生在它看不见的地方。**
#:   （同 RN-483：闭集守卫拿自己的白名单当分母。）
#: ⇒ 分母改成「**每一个跑 `python scripts/*.py` 的步骤**」：CI 里跑仓内脚本的步骤
#:   全都是门（`pip` / `ruff` / `run_tests` 都不在 `scripts/` 下），
#:   新加一道门天生进分母，不用谁记得来改这条正则。
AUDIT_SCRIPT_RE = re.compile(r"python\s+(scripts/[A-Za-z0-9_]+\.py)")
VERDICT_CALL_RE = re.compile(r"verdict\.ps1\s+-Name\s+(\w+)\s+-LogPath\s+(\S+)")


def _audit_steps() -> list[tuple[str, str, str]]:
    """返回 (步骤名, 审计脚本相对路径, run 脚本全文)。"""
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    out = []
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run") or ""
            m = AUDIT_SCRIPT_RE.search(run)
            if m:
                out.append((step.get("name", "<无名>"), m.group(1), run))
    return out


def _delivered_name(script_rel: str) -> str | None:
    """脚本自己在 `deliver("<名>", ...)` 里报的名字。

    ⚠ 用 `utf-8-sig` 读：`scripts/` 里有带 BOM 的文件，`utf-8` 会把 BOM 留在
    首字符，`ast.parse` 当场 SyntaxError —— 而那不是"这个脚本有问题"，
    是**读法**有问题。RN-194 加分母判据时踩到的。
    """
    tree = ast.parse((REPO / script_rel).read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        # ⭐ `deliver()` = 打完就 `os._exit`；`announce()` = 只打、还要跑收尾。
        #   两者都是**同一条裁定通道**，判据认名字必须两个都认 ——
        #   只认一个的话，用另一个的脚本就成了「CI 读得到、判据看不见」。
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) in ("deliver", "announce")
                and node.args and isinstance(node.args[0], ast.Constant)):
            return node.args[0].value
    return None


def test_the_extractor_actually_sees_the_audit_steps():
    """空转守卫：认不出审计步骤，下面两条就全成了摆设。"""
    steps = _audit_steps()
    assert len(steps) >= 5, (
        f"只认出 {len(steps)} 个门禁步骤（对比度 / 排版完整 / 排版紧凑 / 焦点 / 搜索索引，至少 5 个）。"
        f"\n识别规则或 ci.yml 的写法变了，下面的判据在空转。")


def test_the_gate_script_exists():
    assert GATE.exists(), f"{GATE} 不在 —— CI 那几步会直接找不到文件"


def test_every_blocking_audit_step_reads_the_verdict_line():
    bad = []
    for name, script, run in _audit_steps():
        if not VERDICT_CALL_RE.search(run):
            bad.append(f"  「{name}」跑 {script}，但没调用 verdict.ps1 —— 它在拿退出码当裁定")
    assert not bad, (
        "有阻断级的门还在用进程退出码判定（RN-092）：\n" + "\n".join(bad)
        + "\nQt 退出期会把退出码往两个方向改写：`41217bf` 那次被改成 1（假红），"
        "而非零被洗成 0（假绿）也已在 QA 台账里。\n"
        "写法见同文件里已经改好的那几步。")


def test_the_verdict_name_matches_what_the_script_delivers():
    """名字对不上 = 这道门永远红（或者更糟：永远读不到自己那一行）。"""
    bad = []
    for name, script, run in _audit_steps():
        m = VERDICT_CALL_RE.search(run)
        if not m:
            continue                      # 上一条判据管这个
        asked = m.group(1)
        delivered = _delivered_name(script)
        if delivered != asked:
            bad.append(f"  「{name}」：CI 要 -Name {asked}，而 {script} 打的是 {delivered!r}")
    assert not bad, (
        "CI 读的裁定名和脚本打的对不上（RN-092）：\n" + "\n".join(bad)
        + "\n⚠ 这种错**只会表现为『门一直红』**，很容易被当成产品问题去查。")


def _local_gate_registry() -> dict[str, str]:
    """`scripts/gate.py` 里的 `AUDITS` 表（走 AST，不读文本）。"""
    tree = ast.parse((REPO / "scripts" / "gate.py").read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(getattr(t, "id", None) == "AUDITS" for t in targets):
            return {k.value: v.value for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError("scripts/gate.py 里找不到 AUDITS 表")


def test_the_local_gate_covers_every_audit_that_delivers_a_verdict():
    """本机入口的分母 = 「所有会交裁定的审计」，不是「我记得的那几个」。

    ⭐ RN-194。这条判据是 RN-189 那个教训的直接搬用：**一张只列出
    「已经接进来的东西」的表，永远发现不了漏了谁**。所以分母不取
    `AUDITS` 自己，取 `scripts/` 下所有调用了 `deliver(...)` 的脚本 ——
    新加一道审计而忘了接进本机入口，这条当场红。
    """
    delivering = {}
    unparseable = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.name == "_audit_verdict.py":
            continue
        try:
            name = _delivered_name(f"scripts/{path.name}")
        except SyntaxError:
            unparseable.append(path.name)
            continue
        if name:
            delivering[name] = path.name

    # ⭐ 跳过解析不了的文件是必要的，但**跳过谁必须是被断言的**：
    # 静默跳过等于给分母开了一个会自己长大的洞（RN-186 那条只盯一页的棘轮
    # 就是这么废掉的）。这两个是 UP-091 在册的历史损坏文件（mojibake +
    # 未闭合字符串，`ast.parse` / `ruff` 都过不去，`ruff.toml` 里也排除着），
    # 处置待用户拍板；**第三个出现就该在这里当场红**。
    # ⚠ **不能写成 `== KNOWN_UNPARSEABLE`**：开源版把这两个文件整个排除掉了，
    # 于是那边 `scripts/` 里一个坏文件都没有，等号断言当场假红。
    # ⭐ **开源版是另一个分母** —— 一条照闭源版文件集写死的棘轮，在子集仓里
    # 不是"更严"，是"错"。（开源同步的验收门逮到的，2026-08-23。）
    # 所以分两向断言，每一向都只在它真正成立的范围里问：
    extra = sorted(set(unparseable) - set(KNOWN_UNPARSEABLE))
    assert not extra, (
        f"scripts/ 里多出解析不了的文件：{extra}\n"
        "任何扫 `scripts/` 的 AST 判据都会**静默漏掉**它 —— 修好它，"
        "或者写进 KNOWN_UNPARSEABLE 并说明理由。")

    present = {n for n in KNOWN_UNPARSEABLE if (REPO / "scripts" / n).exists()}
    healed = sorted(present - set(unparseable))
    assert not healed, (
        f"这些在册的损坏文件现在能解析了：{healed}\n"
        "UP-091 已处置的话，把它们从 KNOWN_UNPARSEABLE 里删掉（棘轮只许收紧）。")

    registry = _local_gate_registry()
    missing = {n: s for n, s in delivering.items() if n not in registry}
    assert not missing, (
        "这些审计会打裁定行，却进不了本机入口 `python scripts/gate.py <名>`：\n"
        + "\n".join(f"  {n} ← scripts/{s}" for n, s in sorted(missing.items()))
        + "\n⇒ 它们在本机只能靠 `echo $?` 判定，而那个数会被 Qt 退出期改写"
          "（RN-194 实测 9 次里 3 次假红）。")

    wrong = {n: (registry[n], s) for n, s in delivering.items()
             if n in registry and registry[n] != s}
    assert not wrong, (
        "本机入口里的脚本名和实际交裁定的脚本对不上：\n"
        + "\n".join(f"  {n}: 表里写 {a}，实际是 {b}" for n, (a, b) in sorted(wrong.items())))


def test_the_local_gate_does_not_reimplement_the_verdict_rule():
    """裁定规则在 Python 侧只准有一份 —— `_audit_verdict.parse_verdict`。

    ⚠ 抄一份正则出来最省事，也最容易漂：CI 那边取的是**最后一条**匹配行，
    本机这边要是取第一条，两道门就会在"审计中途重跑过一次"时给出不同结论。
    """
    tree = ast.parse((REPO / "scripts" / "gate.py").read_text(encoding="utf-8-sig"))
    imported = any(
        isinstance(n, ast.ImportFrom) and n.module == "_audit_verdict"
        and any(a.name == "parse_verdict" for a in n.names)
        for n in ast.walk(tree))
    assert imported, "gate.py 没有从 `_audit_verdict` 取 `parse_verdict`"

    # ⚠ 断言**结构**，不是文本：第一版写的是「源码里不许出现 RESULT 这个词」，
    # 结果被自己 docstring 里那句实测记录判红了 —— 而那句话正是这条判据存在的理由。
    # ⭐ 判据去看文本就会把「说明」和「实现」当成一回事（RN-189 同款）。
    used_re = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "re"]
    assert not used_re, (
        "gate.py 自己调了 `re.*` —— 裁定行的匹配规则要从 `_audit_verdict.parse_verdict` 取。\n"
        "抄一份正则出来最省事也最容易漂：CI 那边取的是**最后一条**匹配行，"
        "这边要是取第一条，两道门在「审计中途重跑过」时会给出不同结论。")


def test_parse_verdict_takes_the_last_line_and_treats_missing_as_unknown():
    """裁定规则本身的正反两面 —— 规则错了，上面几条判据全是空转。

    「取最后一条」不是随手定的：审计中途可能因为重试打出不止一行，
    CI 的 `Select-Object -Last 1` 也是这个口径，两边必须一致。
    """
    import sys as _sys

    _sys.path.insert(0, str(REPO / "scripts"))
    from _audit_verdict import parse_verdict

    assert parse_verdict("RESULT layout rc=0", "layout") == 0
    assert parse_verdict("RESULT layout rc=3", "layout") == 3
    assert parse_verdict("RESULT layout rc=-1", "layout") == -1
    # 取最后一条
    assert parse_verdict("RESULT layout rc=1\nRESULT layout rc=0", "layout") == 0
    assert parse_verdict("RESULT layout rc=0\nRESULT layout rc=1", "layout") == 1
    # 名字要对得上，别读到隔壁那道门的裁定
    assert parse_verdict("RESULT focus rc=0", "layout") is None
    # 读不到 = 不知道，交给调用方按失败处理（不许当成 0）
    assert parse_verdict("一切正常，全绿", "layout") is None
    assert parse_verdict("", "layout") is None
    # 不许被半行骗到
    assert parse_verdict("RESULT layout rc=", "layout") is None
    assert parse_verdict("前缀 RESULT layout rc=0", "layout") is None


def test_each_audit_step_writes_its_own_log_file():
    """两道排版审计共用一个日志名的话，后一道会读到前一道的裁定。"""
    logs = {}
    for name, _script, run in _audit_steps():
        m = VERDICT_CALL_RE.search(run)
        if m:
            logs.setdefault(m.group(2), []).append(name)
    clashes = {log: names for log, names in logs.items() if len(names) > 1}
    assert not clashes, (
        "多个审计步骤写同一个日志文件，后一道会读到前一道的裁定：\n"
        + "\n".join(f"  {log} ← {', '.join(names)}" for log, names in clashes.items()))


def test_the_local_gate_runs_the_index_script_in_check_mode():
    """门禁脚本如果还有别的模式，本机入口必须把它钉在「门」那一档。

    RN-511。`build_search_index.py` 不带 `--check` 时**不是一道门**：
    它会直接重写 `core/search_index.json`，而且一行裁定都不打。
    ⭐⭐ 所以「忘了给开关」的后果不是「少测一点」，
      是**本机那一跑去改了产品文件**，然后门报「没有结论」。
    """
    tree = ast.parse((REPO / "scripts" / "gate.py").read_text(encoding="utf-8-sig"))
    table = None
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(getattr(t, "id", None) == "DEFAULT_ARGS" for t in targets):
            table = {k.value: [e.value for e in v.elts]
                     for k, v in zip(node.value.keys, node.value.values)}
    assert table is not None, (
        "`scripts/gate.py` 里找不到 `DEFAULT_ARGS` —— "
        "带模式开关的门禁脚本会被本机入口"
        "用**默认模式**跑起来。")
    assert table.get("search_index") == ["--check"], (
        f"本机入口跑 search_index 时给的参数是 "
        f"{table.get('search_index')!r}，不是 `['--check']`。\n"
        "⭐ 不带 `--check` 它就不是一道门，"
        "而是一个**会写盘的生成器**。")

    # ⭐ 光有表不够：这张表得**真的被拼进命令行**。
    src = (REPO / "scripts" / "gate.py").read_text(encoding="utf-8-sig")
    assert "DEFAULT_ARGS.get(name" in src, (
        "`DEFAULT_ARGS` 定义了却没拼进 `cmd` —— "
        "那和没有它一模一样（同批 45："
        "补齐清单不等于补齐那件事）。")
