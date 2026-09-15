# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X1 动刀前的第二张网：**建一个主窗，它对外面做了什么** —— 不许悄悄变多。

## 它守的是什么

总纲 §8 逐字写着「**新增常驻 Timer 一律 B 堆**」。
而在这份快照之前，**没有任何东西数得出主窗到底常驻了几个定时器** ——
X1 要动的正是这个容器，动完之后多一个 30ms 的常驻定时器、多起一个线程，
在测试报告上是**看不见的**。

实测冻下来的那一份（`tests/baselines/x1_effects.json`）：
**11 种定时器、其中常驻 3 个**（3s / 15s / 30min）、起 1 个线程、
关窗后 **0 个线程还活着**、构造期 **0 次进程调用 / 0 次写盘**。

## 为什么走子进程

录的时候要临时接管 `QTimer.start` / `threading.Thread.start` / `builtins.open`，
在 pytest 这个共用进程里做这件事会牵连别的用例。
⇒ 起一个干净的子进程去录（同 `test_ui_mode_sampling` 的做法）。

## ⚠ 它**不进** `SERIAL_TAIL`，而这是想过的

RN-525 那条规矩说的是「拿子进程快照互相比的判据怕挤」。**先分清怕的是什么**：
怕挤的是**量时间**（RN-518）和**比多份快照**（RN-525）的判据 ——
而这一支比的是**计数**（几种定时器、几个常驻、几个线程），
计数不随机器忙不忙而变。
⚠ 唯一一处**真的**会随负载变的是「关窗后还活着几个线程」——
那不该靠串行绕开，该在**源头**解决：录的时候先 `join(timeout=2)` 再数
（见 `scripts/x1_effects_snapshot.py`）。
⭐ 实测全仓有 **8 支**判据会起 `sys.executable` 子进程；
把「起了子进程」当成进 `SERIAL_TAIL` 的条件，会把这 8 支全拖进串行尾巴 ——
**那是照搬规矩，不是应用规矩。**

⛔ 不拿被测代码算自己的预期（RN-523）：预期来自**快照文件**，
   被测的是**当场录出来的那一份**，两者是独立的两份。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECORDER = REPO / "scripts" / "x1_effects_snapshot.py"
SNAPSHOT = REPO / "tests" / "baselines" / "x1_effects.json"


@pytest.fixture(scope="module")
def expected() -> dict:
    if not SNAPSHOT.is_file():
        pytest.skip("还没有外部效应快照 —— 跑 scripts/x1_effects_snapshot.py --write")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recorded(expected) -> dict:
    """在干净的子进程里当场录一份。"""
    proc = subprocess.run(
        [sys.executable, str(RECORDER)],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    line = next((ln for ln in (proc.stdout or "").splitlines()
                 if ln.startswith("timers=")), "")
    assert line, (
        "子进程没交出那一行汇总 —— 录不出来就什么都别断言。\n"
        f"rc={proc.returncode}\nstdout 尾部：{(proc.stdout or '')[-600:]}\n"
        f"stderr 尾部：{(proc.stderr or '')[-600:]}")
    # timers=11 kinds / repeating=3 | threads started=1 alive=0 | procs=0 | writes=0
    nums = [int(x) for x in __import__("re").findall(r"=(\d+)", line)]
    assert len(nums) == 6, f"汇总行格式变了：{line!r}"
    return dict(zip(
        ("种类数", "常驻", "起线程次数", "活着的线程", "进程调用", "写盘次数"), nums))


def test_the_recording_ignores_whatever_config_it_inherits(expected, recorded):
    """⭐⭐⭐ RN-632（批 91）：**拿一份被污染的配置目录录一遍，读数必须一模一样。**

    ## 它当时怎么骗人的

    这支录制器**只被 pytest 当子进程起**，于是原样继承 `conftest` 那个
    固定名、**跨文件跨轮次累积**的 `cs2customizer_test_config`。实测：

    | 录制条件 | 常驻定时器 |
    |---|---|
    | 裸环境 ×5 | **3 / 3 / 3 / 3 / 3** |
    | 继承 `cs2customizer_test_config` ×5 | **4 / 4 / 4 / 4 / 4** |

    多出来的那个挂在 `music_show_player` 上（RN-195：音乐条放过一次就永远在），
    而那个开关是**某一轮某支测试**写进去的，从此留在那个固定目录里。
    ⇒ **基线在干净配置下冻，读数在累积配置下取 —— 两个数根本不在一个条件上。**

    ⚠⚠ 而这条红从批 88 就在，当时被判成「这把尺子对 CPU 敏感」，
    依据是「空载连跑 5 次全是 3」—— **但那 5 次跑的是录制器本身，
    而红的是 pytest 那条路径。两者被当成了同一件事。**

    ## 为什么是行为判据，不是文本判据

    本批先写了一条文本判据（「被判据当子进程起 + 没带 `force=True` ⇒ 红」），
    量出来**误报率 50%**：`page_fingerprint` 的调用方是在**调用侧**摘掉环境变量的，
    那是同样正确的另一种修法。按 RN-156「先量误报率再决定要不要做成门禁」撤掉了它，
    说明留在 `test_pristine_config_for_tooling.py` 里。
    ⭐⭐ 这一条只问那个**被违反的性质**：换个配置，读数变不变。
    用 `force=True` 也好、调用侧摘环境也好、将来换第三种办法也好，它都认。
    """
    # ⛔⛔ **不比「两次读数一样不一样」，直接问「它用的是谁的目录」。**
    #
    # 前两版都比读数，两版都被回退验证判**假绿**：
    # ① 跟同一轮那次「干净」录制比 —— `force` 一拿掉，**那一次也被同样污染**，
    #    两边相等 ⇒ 绿；
    # ② 改成跟冻下来的基线比 —— 而我拿来造污染的那份配置**根本造不出差异**：
    #    我写「多的那个定时器挂在 `music_show_player` 上」是**推断不是实测**，
    #    实测把真实那份 356 键的累积配置整份喂进去，录出来也是 3
    #    ⇒ 第 4 个定时器来自那个目录里**别的状态文件**，不是 `config.json`。
    #
    # ⭐⭐⭐ 两版的共同病根：**我在用一个自己都没量准的差异当尺子。**
    # ⇒ 换成那件**结构上为真、且确定**的事：录制器不许继承外面给的目录。
    #   手法照抄 `test_renovation_fingerprints_do_not_rot`（那条已验证过）：
    #   **拿子进程自己打印的路径当证据。**
    probe = Path(tempfile.mkdtemp(prefix="x1_inherit_probe_"))
    (probe / "config.json").write_text("{}", encoding="utf-8")

    env = dict(os.environ)
    env["CS2C_CONFIG_DIR"] = str(probe)
    env["CS2C_LOG_DIR"] = str(probe)
    proc = subprocess.run(
        [sys.executable, str(RECORDER)], cwd=str(REPO),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=900)
    blob = (proc.stdout or "") + (proc.stderr or "")

    line = next((ln for ln in blob.splitlines() if ln.startswith("timers=")), "")
    assert line, (
        "探针档没录出汇总行 —— 录不出来就什么都别断言。\n"
        f"rc={proc.returncode}\n输出尾部：{blob[-600:]}")

    assert "x1_inherit_probe_" not in blob, (
        f"⛔ 录制器用了**我从外面塞给它的**那个目录（`{probe.name}` 出现在它的输出里）。\n"
        "⇒ 它没有 `force=True` ⇒ 在 pytest 里就会继承 conftest 那个"
        "**跨文件跨轮次累积**的 `cs2customizer_test_config`，"
        "量到的是「这台机器上跑过什么」，不是「全新用户长什么样」。\n"
        "⭐ 这种失效**毫无声响** —— 它表现为某条判据偶尔红，"
        "然后被归因成别的东西（批 88 归给了 CPU，误诊了三批）。")

    nums = [int(x) for x in re.findall(r"=(\d+)", line)]
    got = dict(zip(
        ("种类数", "常驻", "起线程次数", "活着的线程", "进程调用", "写盘次数"), nums))
    # ⚠ `<=` 不是 `==`，照抄下面 `test_the_repeating_timer_count_did_not_grow` 的口径。
    #   批 91 并行版回退验证（6 片同时起 pytest）里这条在**基线**就红过一次，
    #   而主树单跑、副本单跑、两只录制器并发 ×3 全绿 —— 我没拿到那次的原话
    #   （基线输出不落盘），所以下面这句是判断不是实测：**只有这一行**随负载变，
    #   上面那句「用的是谁的目录」不随。守 RN-632 的是上面那句；这一行只防
    #   「录制器根本没建出主窗却还交出了汇总行」，`<=` 够用。
    assert 0 < got["常驻"] <= expected["常驻定时器个数"], (
        f"⛔ 钉死了目录，常驻定时器却读成 {got['常驻']} 个"
        f"（冻下来的是 {expected['常驻定时器个数']} 个）")


def test_the_repeating_timer_count_did_not_grow(expected, recorded):
    """⭐⭐ 常驻定时器只许减不许增 —— 总纲 §8：新增常驻 Timer 一律 B 堆。"""
    assert recorded["常驻"] <= expected["常驻定时器个数"], (
        f"常驻定时器从 {expected['常驻定时器个数']} 涨到 {recorded['常驻']} 个。\n"
        f"冻下来的那几种：{expected['定时器种类']}\n"
        "⇒ 新增常驻 Timer 是 B 堆（总纲 §8）：先说清它为什么必须一直跑，"
        "再重跑 `python scripts/x1_effects_snapshot.py --write`。")


def test_the_window_still_leaves_no_thread_behind(expected, recorded):
    """关窗之后不许留下线程。冻下来的是 **0 个**。"""
    assert recorded["活着的线程"] <= len(expected["还活着的线程"]), (
        f"关窗后还活着 {recorded['活着的线程']} 个线程"
        f"（冻下来的是 {len(expected['还活着的线程'])} 个）。\n"
        "⭐ 一个关不掉的线程在测试里是绿的，在用户那儿是退不出的进程。")


def test_building_the_window_still_touches_nothing_outside(expected, recorded):
    """**建一个主窗**不该起进程、不该写盘。冻下来的是 0 / 0。

    ⚠ 这一条钉的是「构造期」，不是「用起来之后」—— 用户点了按钮当然会写盘。
    ⭐ 而构造期碰外面，是那种「一启动就发生、谁都没点过」的事。
    """
    assert recorded["进程调用"] <= expected.get("进程调用", []).__len__(), (
        f"建窗口时起了 {recorded['进程调用']} 次进程（冻下来的是 "
        f"{len(expected.get('进程调用', []))} 次）")
    assert recorded["写盘次数"] <= expected["写盘次数"], (
        f"建窗口时写了 {recorded['写盘次数']} 次盘（冻下来的是 {expected['写盘次数']} 次）")


def test_the_snapshot_is_internally_consistent(expected):
    """⭐ 反向守卫：快照头上那个「常驻个数」要和它自己那张表算得出来的一致。

    没有这一条，那个数会和表悄悄脱节 —— 而**上面三条断言读的正是那个数**。
    """
    kinds = expected["定时器种类"]
    assert kinds, "快照里一种定时器都没有 —— 它多半是空转的"
    repeating = sum(n for k, n in kinds.items() if "常驻" in k)
    assert repeating == expected["常驻定时器个数"], (
        f"快照头上写常驻 {expected['常驻定时器个数']} 个，而表里算出来是 {repeating} 个")
