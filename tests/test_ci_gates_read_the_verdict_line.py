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

#: 跑这些脚本的步骤就是「阻断级的门」，必须走裁定行。
AUDIT_SCRIPT_RE = re.compile(r"python\s+(scripts/[A-Za-z0-9_]*audit[A-Za-z0-9_]*\.py)")
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
    """脚本自己在 `deliver("<名>", ...)` 里报的名字。"""
    tree = ast.parse((REPO / script_rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "deliver"
                and node.args and isinstance(node.args[0], ast.Constant)):
            return node.args[0].value
    return None


def test_the_extractor_actually_sees_the_audit_steps():
    """空转守卫：认不出审计步骤，下面两条就全成了摆设。"""
    steps = _audit_steps()
    assert len(steps) >= 4, (
        f"只认出 {len(steps)} 个审计步骤（对比度 / 排版完整 / 排版紧凑 / 焦点，至少 4 个）。"
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
