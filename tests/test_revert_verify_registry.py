# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""回退验证台自身的登记册体检（2026-08-12 建立）。

**为什么需要它**：`scripts/revert_verify.py` 是本项目验证"判据不是假绿"的工具，
但它自己没人验。它的每条断点由三部分组成——目标文件、要替换的锚点文本、
要跑的判据 selector——**三者任何一个失效都不会有人知道**：

- 锚点文本对不上：脚本报"跳过"，一条断点静默退出验证。
- selector 指向不存在的测试：pytest 返回"not found"，脚本把它当成**基线不绿**，
  于是**整个分组在跑第一条之前就中止**。

第二种真的发生了。开源裁剪把在线更新下载器连同它的判据一起移除了
（那是闭源版功能），但 `revert_verify.py` 里那条 QA-007 断点留了下来，
指着一个本仓库不存在的测试。结果：**`--only QA` 这一整组在开源仓库里从来没跑通过**，
而输出写的是"基线就不绿"——看起来像产品有问题，其实是登记册过期。

这个文件就两条判据，都很便宜，但它们盯的是"工具本身还能不能用"。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "revert_verify.py"


def _load_reverts():
    spec = importlib.util.spec_from_file_location("_revert_verify_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.REVERTS


REVERTS = _load_reverts()


def test_registry_is_not_empty():
    assert REVERTS, "回退验证台一条断点都没有，这个文件的两条判据会变成空跑"


@pytest.mark.parametrize(
    "revert",
    REVERTS,
    ids=[f"{r.group}:{r.name}" for r in REVERTS],
)
def test_every_breakpoint_anchor_still_exists(revert):
    """每条断点要替换的锚点文本，必须还在目标文件里。

    锚点对不上时脚本只会打一行"跳过"，那条断点就静默失效了——
    而它存在的意义正是"确认某条判据不是假绿"。
    """
    # ⭐ 「这个检出里根本没有这个产品文件」是**不适用**，不是腐烂 ——
    #   开源版是功能子集，`build_tools/oss_sync/`、`pages/account_page.py`
    #   这些在这边不存在，落在它们上面的断点没有对象。
    #   上游的 `scripts/revert_verify.py` 这一批已经把「不适用」和「失效」分开了
    #   （不适用不计入退出码），这支体检跟上，否则同一件事两处结论相反。
    # ⛔ 只对**文件不存在**放行；文件在而锚点对不上，仍然是腐烂，照红。
    if not revert.path.is_file():
        pytest.skip(f"功能子集里没有这个产品文件，本条不适用：{revert.path.name}")
    text = revert.path.read_text(encoding="utf-8")
    assert revert.old in text, (
        f"锚点文本已不在 {revert.path.name} 里（产品代码变了）。"
        "请更新这条断点的 old/new，而不是留着它静默跳过。"
    )


def test_every_selector_resolves_to_a_real_test():
    """每条断点的 selector 必须真能收集到用例。

    这条是那次真实事故的直接补丁：selector 指向不存在的测试时，脚本会把
    "not found" 当成基线不绿，**整组在第一条之前就中止**，
    而报错文字让人以为是产品坏了。

    用 `--collect-only` 收集 selector，比逐条起 pytest 快得多。

    ⚠⚠ 2026-08-30（批 27）：**这条判据被它自己撑破过一次。**
    登记册长到 361 条 selector 时，一次性拼出来的命令行是 **33232 字符**，
    而 Windows `CreateProcess` 的上限是 **32767** —— 于是 `subprocess.run`
    抛 `FileNotFoundError: [WinError 206] 文件名或扩展名太长`，
    **判据红了，但红的理由和它要防的事情毫无关系**，报错文字还让人以为是产品坏了
    （和 RN-093「基线不绿」那次是同一个陷阱的两种写法）。
    ⭐ **一条会随登记册一起变长的判据，必须自己声明它的长度上界** ——
      而最好的声明方式不是断言"别超"，是**分批，让上界根本不存在**。
    ⇒ 现在按字符预算切块跑。切块引入一个新的假绿风险（某一块整体崩掉时
      它一行 `not found` 都不会打，于是"没发现问题"和"没跑成"长得一样），
      所以下面对**每一块**都验了它确实产出了 pytest 的收集输出。
    """
    # ⭐ 同上一条：产品文件在这个检出里根本没有时，它的判据也不该期待存在
    #   （开源版是功能子集：`build_tools/oss_sync/` 那一整套都不在）。
    #   ⛔ 只放行「产品文件不在」这一种；文件在而判据名没了，仍然是腐烂，照红。
    selectors = sorted({r.selector for r in REVERTS if r.path.is_file()})
    #: 命令行字符预算。真实上限 32767，留一半余量给解释器绝对路径与固定参数——
    #: 这个数只影响跑几趟，给小了不会错，只会慢一点。
    budget = 16000
    chunks: list[list[str]] = [[]]
    used = 0
    for sel in selectors:
        if chunks[-1] and used + len(sel) + 1 > budget:
            chunks.append([])
            used = 0
        chunks[-1].append(sel)
        used += len(sel) + 1

    marker = "not found: "
    reported: set[str] = set()
    for chunk in chunks:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *chunk],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # ⚠ pytest 打的是**绝对路径**：`ERROR: not found: H:\...\tests\x.py::name`。
        # 本条判据的第一版写成 `f"not found: {selector}" in output`（selector 是仓库
        # 相对路径），中间隔着绝对路径前缀，于是永远匹配不上——判据自己假绿，
        # 而它要防的恰恰是假绿。所以这里改成：先把"not found"的目标解析出来，
        # 再用后缀匹配。
        normalized = ((proc.stdout or "") + (proc.stderr or "")).replace("\\", "/")
        # 分块之后必须验"这一块真的跑起来了"：pytest 收集成功会打
        # `N tests collected`，有找不到的会打 `error`/`not found`。
        # 两样都没有 ⇒ 这一块根本没执行到收集（环境炸了 / 参数被吃掉），
        # 此时它贡献的"零条 not found"是假的。
        assert ("collected" in normalized or marker in normalized), (
            f"这一块 {len(chunk)} 条 selector 的 pytest 收集没有产出任何结果，"
            "这一块贡献的『没问题』是假的：\n"
            f"  returncode={proc.returncode}\n  输出前 500 字：{normalized[:500]}"
        )
        reported |= {
            line.split(marker, 1)[1].strip()
            for line in normalized.splitlines()
            if marker in line
        }
    missing = [s for s in selectors if any(t.endswith(s) for t in reported)]
    assert not missing, (
        "这些断点的 selector 指向不存在的用例：\n  " + "\n  ".join(missing) + "\n"
        "开源裁剪移除某个功能时，要连同它在本登记册里的断点一起删掉。"
    )
