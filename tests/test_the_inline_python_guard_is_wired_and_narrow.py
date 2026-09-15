# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-602：那条「要跑 Python 就先落盘」的规矩，现在有一个 PreToolUse 钩子在守。

⭐⭐⭐ 这支判据存在的理由是一句**被实测证伪的自信**。批 81 我把 CLAUDE.md 里
那条禁令从「Python 不走 heredoc」改写成点名动作，并在旁边逐字写下
「⚠ 判据管不着这一条（那是我和 shell 之间的事）」——
**然后在十五分钟之内又犯了第五次**（`python - 2>/dev/null`，一个连活都没干的残留前缀）。

⇒ ⭐⭐ **前四次我都把它归因成「没记住规矩」，于是每次的修法都是「再写清楚一点」；
而第五次发生在规矩刚写完的时候** —— 它不是记忆问题，是手上的习惯，
而习惯只有机械拦截挡得住。

这支判据守两件事，缺一不可：
 ① **钩子还接着线**（settings.json 里那一项没被谁顺手删掉）；
 ② **它还是窄的** —— ⚠ 首测当场撞上 RN-601 那条教训的翻版：第一版把
    `grep -n 'python -c' CLAUDE.md` 也拦了。⭐⭐⭐ **一个禁止某种写法的拦截器，
    会连同「讨论那种写法」一起禁掉**，而本工程的日常就是大量地讨论它
    （登记册、档案、提交信息）。⇒ 阳性对照里必须有「讨论它」的样本。
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest
from _denominator import must_scan

WORKSPACE = Path(__file__).resolve().parent.parent.parent
HOOK = WORKSPACE / ".claude" / "hooks" / "no_inline_python.py"
SETTINGS = WORKSPACE / ".claude" / "settings.json"

#: ⛔ 这些必须被拦。第一条就是批 81 那次违规的**原样命令**。
MUST_BLOCK = (
    'python - 2>/dev/null; sed -i "s/a/b/" x.md',
    'python -c "import io; print(1)"',
    "python -c 'print(1)'",
    'python3 -c "print(1)"',
    "cd /h/tmp && python - <<EOF\nprint(1)\nEOF",
    "python <<'PY'\nprint(1)\nPY",
    "echo 'print(1)' | python",
    "cat x.py | python3",
    # ⭐⭐⭐ RN-612（批 84）：下面这三条**钩子原来全部放行**。
    # 第一条是当天第六次违规的原样命令 —— 而它之所以漏，是因为 stdin 那一条
    # 写成了「`-` 后面跟着 行尾 / 操作符 / 重定向」这**一张枚举表**，
    # 而这一次 `-` 后面跟的是另一个参数。
    # ⚠⚠ 更要紧的是：**这张 MUST_BLOCK 自己也是一张枚举表** ——
    # 它当时收的是「已经发生过的八种形态」，所以第九种形态
    # **同时躲过了钩子和这支判据**。⇒ 判据和它守的东西共享同一个盲区时，
    # 判据绿不代表守住了，只代表这两张表是同一张。
    "python - --help 2>/dev/null; grep -n x a.py",
    "python - < H:/tmp/x.py",
    "python - --version",
)

#: ⛔ 这些必须放行。后两条是**讨论它**，不是用它 —— 见模块头。
MUST_PASS = (
    "python H:/tmp/b81_fix.py",
    "python -m pytest tests/ -q",
    "python -m ruff check .",
    "python build_tools/run_tests.py",
    "python scripts/dead_code_sweep.py --source modules",
    "grep -n 'python -c' CLAUDE.md",
    "git commit -m 'python -c 的禁令'",
)


def _load():
    if not HOOK.exists():
        pytest.skip(f"钩子不在这个克隆里：{HOOK}")
    spec = importlib.util.spec_from_file_location("_rn602_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_guard_is_still_wired_into_settings():
    """① 钩子还接着线 —— ⭐ 一个没接线的钩子和没有钩子，在行为上一模一样。"""
    if not SETTINGS.exists():
        pytest.skip(f"工作区设置不在这个克隆里：{SETTINGS}")
    cfg = json.loads(io.open(SETTINGS, encoding="utf-8").read())
    entries = cfg.get("hooks", {}).get("PreToolUse", [])
    must_scan(entries, "PreToolUse 钩子项", least=1)
    wired = [
        h for e in entries if e.get("matcher") == "Bash"
        for h in e.get("hooks", [])
        if "no_inline_python" in (h.get("command") or "")
    ]
    assert wired, (
        "`.claude/settings.json` 里没有把 no_inline_python 挂到 Bash 的 PreToolUse 上。\n"
        "⇒ RN-602 那条规矩又回到了「只靠我记得」的状态，而它已经这么失效过五次。"
    )


def test_the_guard_catches_every_shape_that_actually_happened():
    """② 该拦的都拦得住 —— 八种形态里前四种是**真发生过的**，不是设想的。"""
    mod = _load()
    must_scan(MUST_BLOCK, "该拦的命令样本", least=6)
    missed = [c for c in MUST_BLOCK if mod.offending(c) is None]
    assert not missed, "这些写法没被拦下：" + "; ".join(repr(c) for c in missed)


def test_the_guard_does_not_also_ban_talking_about_it():
    """③ 阳性对照的另一半：**讨论它不等于用它**。

    ⭐ RN-601 已经吃过一次同款：那一行在描述「正文里不许出现竖线」时
    自己写了一根竖线，当场把自己那一行切多了一格。
    """
    mod = _load()
    must_scan(MUST_PASS, "该放行的命令样本", least=5)
    over = [(c, mod.offending(c)) for c in MUST_PASS if mod.offending(c) is not None]
    assert not over, "这些该放行却被拦了：" + "; ".join(f"{c!r}→{w}" for c, w in over)


def test_the_guard_fails_open_when_it_cannot_understand_the_input():
    """④ ⛔ 失效方向必须朝「放行」倒。

    ⭐⭐⭐ 一个守规矩的钩子，自己崩掉时如果朝「拦」倒，就会把整夜的 Bash 全堵死 ——
    而那种故障**长得和「Claude 卡住了」一模一样**，没人在场时尤其贵。
    """
    mod = _load()
    assert mod.offending("") is None
    for weird in ("$(echo python) -c", "PYTHON_C=1 make build", "pythonic -c 说明"):
        assert mod.offending(weird) is None or True  # 不苛求，只要不炸
    # 真正的失效对照：喂给 main() 的不是合法 JSON 时必须 exit 0
    import subprocess
    import sys
    p = subprocess.run([sys.executable, str(HOOK)], input="不是 json",
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, "喂坏输入时钩子没有朝『放行』倒 —— 它会堵死所有 Bash"
