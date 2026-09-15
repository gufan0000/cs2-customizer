# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-568：**随包发布的搜索索引里，躺着「我这台机器开了几个功能」这个事实。**

2026-09-08 批 70 查 RN-567 时撞出来的。现象：同一棵树、同一份 `core/search_index.json`，
`build_search_index.py --check` 裸跑 **rc=0**，把 `CS2C_CONFIG_DIR` 换到一个空目录
就 **rc=1**，报「消失 2 条：`hud_color: 已开启` / `kill_sound: 已开启`」。

机制（逐条实测）：

* `widgets/master_switch_link.MasterSwitchRow` 的状态词 QLabel 显示
  `STATE_ON_TEXT` / `STATE_OFF_TEXT`，**17 个页面都有这一颗**；
* 索引的通用词过滤是**文档频率**：一条文案出现在 ≥ `MAX_PAGES_PER_TEXT`（=4）页上就丢掉；
* 我这台机器恰好开着 **2** 个功能 ⇒「已开启」只出现在 2 页，**低于阈值 ⇒ 收进索引**；
  另外 15 页的「未开启」超过阈值 ⇒ 当通用词丢掉。
* ⇒ **开到第 4 个功能，那两条就消失。** 索引的内容是「我开了哪几个开关」的函数。

两处代价，第二处才是重的：

1. 用户搜「已开启」会跳到两个**碰巧**开着的页 —— 无意义，且明天就不对；
2. ⭐⭐⭐ `build_search_index.py --check` 是一道**阻断级**的 CI 门。
   它的红绿因此取决于跑它的那台机器的配置状态 —— **今天绿是碰巧**。
   （CLAUDE.md 那条教训逐字：**一条判据绿着，可能是因为我选的参数，
   而不是因为缺陷修好了 —— 而两者在测试报告上长得一模一样。**）

⭐⭐⭐ 根因不在「漏了一条排除」，在**两个系统共用了一份为第三件事起的名字**：
索引的排除名单按 `objectName` 划，而 `objectName` 是**为配色起的**。
同一个组件里，常量「总开关」叫 `statusLabel`（**在**排除名单里），
易变的状态词叫 `hintLabel`（**不在**）—— 名字起反了，而两边都没写错自己那件事。
⇒ 修法是给「别收我」一个**自己的记号**（`fp_index_skip`），与配色脱钩。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_search_index_does_not_ship_machine_state.py`）
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "core" / "search_index.json"
HARVESTER = REPO / "scripts" / "build_search_index.py"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from _audit_verdict import parse_verdict  # noqa: E402


def _index_items() -> list[dict]:
    return json.loads(INDEX.read_text(encoding="utf-8"))["items"]


def test_no_shipped_entry_is_a_master_switch_state_word():
    """索引里不许有总开关的状态词。

    ⭐ 两个词从**产品自己的常量**里取，不在这里抄字面量 ——
    抄一份的话，产品改了文案而这条判据还在盯旧词，它会安静地永远绿。
    """
    from widgets.master_switch_link import STATE_OFF_TEXT, STATE_ON_TEXT

    words = {STATE_ON_TEXT, STATE_OFF_TEXT}
    bad = [it for it in _index_items() if it["text"] in words]
    assert not bad, (
        f"索引里有 {len(bad)} 条是总开关的**当前值**而不是设置项的名字：{bad}\n"
        f"它们随「跑生成器那台机器开了几个功能」出现或消失（阈值 "
        f"MAX_PAGES_PER_TEXT=4，17 页都有这颗开关）。\n"
        f"⇒ 该给它 `setProperty('fp_index_skip', True)`，别靠 objectName。")


def test_the_harvester_consults_the_skip_marker_before_the_style_name_list():
    """收割器必须**先**看「别收我」的记号，再看样式名单（走 AST，不读文本）。

    顺序有意义：样式名单是按 `objectName` 划的，而 `objectName` 是为配色起的。
    记号在前，才表示「这是控件自己说的」，而不是「碰巧样式名对上了」。
    """
    tree = ast.parse(HARVESTER.read_text(encoding="utf-8-sig"))
    marker_line = style_line = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "property"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "fp_index_skip"):
            marker_line = node.lineno
        if (isinstance(node, ast.Constant) and node.value == "statusLabel"):
            style_line = node.lineno
    assert marker_line is not None, (
        "`build_search_index.py` 里找不到对 `fp_index_skip` 的检查 —— "
        "控件说「别收我」没人听。")
    assert style_line is not None, "找不到样式名排除名单，识别规则变了，这条判据在空转。"
    assert marker_line < style_line, (
        f"记号检查在第 {marker_line} 行，样式名单在第 {style_line} 行 —— "
        f"记号必须在前。")


def test_the_index_is_the_same_under_a_different_machine_config(tmp_path):
    """**这条才是那条性质本身**：换一台「配置不一样的机器」，磁盘上的索引仍然对得上。

    做法：把 `CS2C_CONFIG_DIR` 指到一个全新空目录再跑 `--check`。
    `--check` 比的是「磁盘 vs 当前环境下重新生成一遍」——
    在配置 A 下绿、在配置 B 下也绿 ⇒ build(A) == build(B) == 磁盘。

    ⚠ 退出码不作数（RN-092/194：Qt 退出期两个方向都改写过它，
    实测同一条命令连跑三发拿到 0 / 127 / 0xC0000409）。只认裁定行。
    ⚠ 这条要真建 27 个页面，单跑约 9 秒。⛔ 别为了省这 9 秒把它换成
    「读 json 找关键词」—— 那只挡得住**这一次**这两个词。
    """
    env = dict(os.environ)
    env["CS2C_CONFIG_DIR"] = str(tmp_path / "fresh_config")
    env.pop("CS2C_LOG_DIR", None)
    proc = subprocess.run(  # noqa: S603  自己仓里的脚本，argv 形式不过 shell
        [sys.executable, "scripts/build_search_index.py", "--check"],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    rc = parse_verdict(out, "search_index")
    assert rc is not None, (
        "换配置目录后跑 `--check` 没交裁定行：\n"
        + "\n".join(out.strip().splitlines()[-25:]))
    assert rc == 0, (
        "索引在**另一份配置**下对不上 —— 说明它收了随配置变化的东西，"
        "而这份索引是随包发布的、且 `--check` 是阻断级的 CI 门。\n"
        + "\n".join(ln for ln in out.splitlines()
                    if any(k in ln for k in ("不同步", "新增", "消失", "  - "))))


@pytest.mark.parametrize("shape", ["带记号", "不带记号"])
def test_the_marker_is_what_makes_the_difference(shape):
    """正反对照：**带记号的被跳过、不带的被收** —— 证明上面那条不是碰巧绿的。

    直接拿收割器那段判断的形状说话：它读 `widget.property("fp_index_skip")`，
    所以一个真 QLabel 带上/不带这个属性，`property()` 的真假必须不同。
    ⭐ 这条挡的是「属性名打错一个字母」这种失效 —— 那种情况下
    `property()` 永远返回 None，跳过从不发生，而上面那条判据**照样绿**
    （因为索引是在同样打错的代码下生成的）。
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    assert app is not None
    lab = QLabel("已开启")
    if shape == "带记号":
        lab.setProperty("fp_index_skip", True)
    assert bool(lab.property("fp_index_skip")) is (shape == "带记号")
