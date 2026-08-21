# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""翻新工程：已关档页面的结构基线不许悄悄变（总纲 §9.1）。

**这是整个翻新工程唯一进 CI 的那一条腿。** 另外两条（含几何的完整指纹、
两档像素）都是字体相关的，只能在本机跑 —— runner 的字体跟这台机器不一样，
把它们放进 CI 只会天天假红，然后被所有人无视。

判据只问一件事：**这一页还是不是原来那些控件、文案还是不是那些字。**
类型 / objectName / 启用态 / 文案，四样，与字体无关。

采集口径**直接复用 `scripts/renovation_baseline._structure_of`**，不在这里
重写一遍 —— 判据与取基线的工具用同一段代码，才不会出现"基线是这么采的、
判据是那么采的"这种谁也说不清的差异。（RN-002 刚教过一次：同一份知识抄两遍，
抄的时候都对，漂了才发作。）

新增一页基线：`python scripts/renovation_baseline.py --capture <page_id>`
改版获批后换基线：加 `--accept`。**A 堆改动绝不该用到 --accept** ——
A 堆的定义就是"基线逐字节等同"，对不上就说明它不是 A 堆（总纲 §4⑥）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO / "tests" / "baselines" / "renovation"

sys.path.insert(0, str(REPO / "scripts"))


def _pages_with_baseline() -> list[str]:
    if not BASELINE_DIR.exists():
        return []
    return sorted(d.name for d in BASELINE_DIR.iterdir()
                  if d.is_dir() and (d / "structure.json").exists())


def test_baseline_dir_is_sane():
    """基线目录要么不存在（工程还没开工），要么里面每一页都齐活。

    半拉子目录（有 png 没 structure.json）说明上一次 capture 中途挂了，
    那种基线拿来验收会给出"通过"的假象。
    """
    if not BASELINE_DIR.exists():
        pytest.skip("翻新工程尚未取任何基线")
    for d in sorted(p for p in BASELINE_DIR.iterdir() if p.is_dir()):
        assert (d / "structure.json").exists(), (
            f"{d.name} 有基线目录却没有 structure.json —— "
            "多半是 capture 跑了一半挂了。重跑 --capture，别留半拉子基线。"
        )


@pytest.mark.parametrize("page_id", _pages_with_baseline())
def test_page_structure_matches_baseline(page_id):
    from _page_structure import diff
    import renovation_baseline as rb

    base = json.loads(
        (BASELINE_DIR / page_id / "structure.json").read_text(encoding="utf-8"))
    # 走子进程：页面结构随设置而变，而 conftest 的配置目录是**跨文件跨轮次累积**的。
    # 在本进程里直接建页，量到的是"这台机器攒下的设置"下的样子，不是基线的含义。
    now = rb._structure_via_subprocess([page_id])[page_id]
    diffs = diff(base, now)

    assert not diffs, (
        f"「{page_id}」的结构与已关档基线对不上（{len(diffs)} 处）：\n  "
        + "\n  ".join(diffs[:25])
        + "\n\n这一页已经关档，结构变了就必须有说法："
        "\n  · 是 A 堆改动？那它不该改变结构 —— 回去看改了什么。"
        "\n  · 是获批的 B 堆改动？跑 --capture --accept 换基线，并在档案里记上裁定号。"
    )


def test_structure_projection_scrubs_machine_specific_paths():
    r"""结构投影里不许留绝对路径 —— 否则这条判据在别人机器上必红。

    ⚠ 2026-08-17 由 CI 逼出来的：`kill_voice` 的状态文案带一句
    「缺失目录: C:\Users\21108\AppData\Local\Temp\cs2customizer_...」，
    本机存进基线、runner 上量到 `C:\Users\RUNNER~1\...` ——
    **这类页面的 CI 结构判据永远不可能通过**，而红的原因跟被判的那次改动毫无关系。
    判据只要有一次"不是我的错也会红"，人就会开始无视它，那它就等于没有。
    """
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import _page_structure

    cases = [
        (r"缺失目录: C:\Users\21108\AppData\Local\Temp\cs2customizer_x\audio", "C:"),
        (r"缺失目录: C:\Users\RUNNER~1\AppData\Local\Temp\cs2customizer_x\audio", "RUNNER"),
        ("找不到 /home/gufan/resources/audio 这个目录", "/home/"),
        ("读取 D:/游戏/csgo/cfg 失败", "D:/"),
    ]
    for text, marker in cases:
        got = _page_structure._scrub_machine_paths(text)
        assert marker not in got, f"路径没被抹掉：{text!r} → {got!r}"
        assert "<路径>" in got, f"抹是抹了，但没留占位符，差异会看不懂：{got!r}"

    # 反面：不含路径的正常文案一个字都不许动，否则这条判据就管太宽了。
    plain = "总开关：已关闭\n当前分类：手枪\n当前分类已配置：0/10"
    assert _page_structure._scrub_machine_paths(plain) == plain

    # 两台机器的同一段文案，抹完必须一模一样 —— 这才是这件事的真正目的。
    a = _page_structure._scrub_machine_paths(cases[0][0])
    b = _page_structure._scrub_machine_paths(cases[1][0])
    assert a == b, f"抹完还是不一样，CI 照样会红：{a!r} vs {b!r}"


def test_the_structure_probe_survives_a_log_line_after_the_json(monkeypatch):
    """⭐⭐ RN-166：JSON 后面跟一行日志，取投影不许当成「结构对不上」。

    子进程的日志是**异步**落到同一个流上的 —— 一条
    `[WARNING] [AudioHealth] issues detected: ...` 完全可能排在 JSON **之后**。
    原来的 `json.loads(标记之后的全部内容)` 那时抛 JSONDecodeError，
    而它冒出来的样子是「这一页的结构和基线对不上」。

    ⭐ **一个解析错误伪装成了一次内容差异。**
    后果很具体：人会去**改基线**（我照着重锁了三轮），
    而真正的毛病在工装里，基线越改越偏。

    ⚠ **这条判据的第一版也是假绿的（回退验证 0/1）**：它在自己体内又写了一遍
    `raw_decode`，压根没碰产品那段代码 —— 把工装改回 `json.loads` 它照样绿。
    ⭐ **判据必须去调那段真代码**；测一份复制品测的是我抄得对不对。
    ⇒ 现在打桩 `rb._run`，让真正的 `_structure_via_subprocess` 去解析这段脏输出。
    """
    import json

    import renovation_baseline as rb

    payload = json.dumps({"demo": [{"type": "QLabel"}]})
    noisy = (f"启动日志\n{rb._EMIT_MARKER}\n{payload}\n"
             "[WARNING] [AudioHealth] issues detected: missing_dirs=12\n")
    monkeypatch.setattr(rb, "_run", lambda argv: (0, noisy))

    got = rb._structure_via_subprocess(["demo"])
    assert got == {"demo": [{"type": "QLabel"}]}, (
        f"日志排在 JSON 后面就把取数搞挂了：{got!r}")


def test_the_structure_probe_still_blows_up_on_real_garbage(monkeypatch):
    """反面守卫：**真的坏掉的输出仍然要炸**。

    ⭐ 少了这条，上面那条的修法可以退化成「什么都吞」——
    那样一次真正的取数失败会变成「结构没差异」，也就是**一次静默的假绿**。
    """
    import renovation_baseline as rb

    monkeypatch.setattr(rb, "_run",
                        lambda argv: (0, f"{rb._EMIT_MARKER}\n这不是 JSON"))
    with pytest.raises(AssertionError, match="JSON"):
        rb._structure_via_subprocess(["demo"])
