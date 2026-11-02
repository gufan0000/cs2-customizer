# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-571：**「最坏那一档」有两个自由度，工装只钉了一个，报告行却宣称钉了全部。**

音乐控制条的高度由两件事决定：

1. **在不在** —— `pin(MODE_WORST_CASE)` 钉的就是这个（RN-195）；
2. **展开还是折叠** —— `MusicControlBar.is_expanded` 读 `config.music_bar_expanded`
   （默认 `False` ⇒ **42px**；展开 ⇒ **112~128px**）。两档差 **86px 可视区**。

在这条判据之前，`pin()` 只做第 1 件，而它返回的那句话逐字写着
「审计量的是用户可能遇到的**最坏那一档**」——
⭐⭐⭐ **一条规矩被写下来、还配了工装，而工装只实现了那条规矩的一半，
报告行照样宣称它实现了全部。**

实测代价（批 71，`--themes dark,light --scales 1.0,1.1,1.25`）：

| 档 | 可视区（紧凑 860×640） | 纵向缺口 |
|---|---|---|
| 折叠 42px（审计一直跑的） | 548px | **0 处** |
| 展开 128px | 462px | **40 处**（完整档另有 **4 处**）|

⇒ RN-196 那张 `KNOWN_COMPACT_DEBT` 从批 65 起是空的，
**不是因为债还清了，是因为尺子在量更轻的那一档。**

⚖ **本批的裁定：阻断档仍是「在 + 折叠」，展开档改成显式可选。**
两个状态性质不同 —— 控制条建出来**不可逆**（RN-195：只做「不建」不做「撤走」），
而展开**一键可收回**。把可逆状态当强制基线，代价是那 44 处要立刻进豁免表。
⭐ 把数写下来才算裁定：那 44 处是**真的**，归 RN-571 单独排期。

这支判据钉三件事：
① 展开档存在，且它真的比折叠档高（不是一个只改名字的档）；
② 报告行**逐字说明钉的是哪一档** —— 这正是当初骗过我的那一行；
③ `MODE_PRISTINE` 不受影响（基线要的是可复现，不是最坏）。

批 145：减字之后那 44 处全部还清，申报表清空，展开档也一处都不许有。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_audit_says_which_worst_case_it_pinned.py`）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import _audit_music_bar as mbar  # noqa: E402


def test_there_is_a_mode_for_the_expanded_bar():
    assert hasattr(mbar, "MODE_EXPANDED"), (
        "没有展开档 —— 「最坏」那两个自由度里的第二个又没人钉了")
    assert len({mbar.MODE_WORST_CASE, mbar.MODE_PRISTINE, mbar.MODE_EXPANDED}) == 3, (
        "三个档位的取值撞车了")


def test_an_unknown_mode_is_refused():
    """空转守卫：档位名打错不许静默走默认路径。"""
    with pytest.raises(ValueError):
        mbar.pin(object(), object(), "没有这一档")


@pytest.fixture(scope="module")
def window():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from _audit_neutralize import enable_audit_mode
    from config import config

    enable_audit_mode()
    # ⭐⭐⭐ **借了要还。** 这个夹具会把 `compact_mode` 拨成紧凑、
    # `pin(MODE_EXPANDED)` 会把 `music_bar_expanded` 拨成展开 —— 而配置会**落盘**
    # 到几路 worker 共用的那份测试配置里，下一个建窗口的测试就从那一档开始。
    # 实测代价（批 72 第二轮全量）：`test_ui_visual_r1_fixes` 四条当场红，
    # 报的却是「只找到 0 个导航项」——**读起来像那条判据自己瞎了**。
    # ⚠ 而它**只在某些 worker 分配下复现**（同一份代码第一轮全绿）——
    #   一条时好时坏的门禁比没有门禁更坏。
    # ⇒ 同 RN-571 再上一层：**钉一个档的人，负责把它还回去。**
    kept = {k: getattr(config, k, None)
            for k in ("compact_mode", "music_bar_expanded")}
    # ⚠⚠ 批 73 补正：**还原必须走 `finally`。**
    #   原来它写在 `yield` 之后的直线上 —— 只要 `MainWindow(...)` 建 28 页时抛一次
    #   异常，夹具就在 `yield` 之前中断，**还原和 `save_config_now()` 一步都不跑**，
    #   而上面那行已经把 `compact_mode` 拨成紧凑了 ⇒ 正是 RN-572 的原形复发。
    #   ⭐⭐ **借了要还，而「还」这一步自己也得防中断** ——
    #     借的动作总是先发生的，出错的机会全落在借完到还之间那一段。
    win = None
    try:
        config.compact_mode = True
        app = QApplication.instance() or QApplication([])
        import gui_widget

        win = gui_widget.MainWindow(auto_background_preload=False)
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        app.processEvents()
        win.setMinimumSize(860, 640)
        win.resize(860, 640)
        app.processEvents()
        yield win, app
    finally:
        if win is not None:
            win.close()
        for key, value in kept.items():
            setattr(config, key, bool(value))
        # ⚠ 方法叫 `save_config_now`，不叫 `save` —— 我第一版写的 `getattr(config, "save")`
        #   拿到 None，于是**还了个寂寞**：断言全绿，配置照样是脏的。
        #   ⭐ 一个 `if callable(...)` 的软兜底，在名字写错时长得跟成功一模一样。
        config.save_config_now()


def test_the_expanded_mode_really_is_taller(window):
    """展开档必须**真的更高** —— 否则它只是一个换了名字的折叠档。

    ⭐ 这一条是本条缺陷的直接指纹：当初 `pin` 少做的那一半，
    表现出来就是「两档量到同一个高度」。
    """
    win, app = window
    mbar.pin(win, app, mbar.MODE_WORST_CASE)
    bar = getattr(win, "music_control_bar", None)
    assert bar is not None, "阻断档连控制条都没建出来"
    collapsed = bar.height()

    mbar.pin(win, app, mbar.MODE_EXPANDED)
    expanded = bar.height()

    assert expanded > collapsed + 40, (
        f"展开档 {expanded}px 并不比折叠档 {collapsed}px 高多少 —— "
        f"`pin(MODE_EXPANDED)` 没真的把它展开。\n"
        f"⚠ 实测参考：折叠 42px / 展开 112~128px，两档差 86px 可视区。")


def test_the_report_line_names_the_shape_it_pinned(window):
    """报告行必须**逐字说出**钉的是折叠还是展开。

    ⭐⭐⭐ 这正是当初骗过我的那一行：它笼统地说「最坏那一档」，
    而同一句话下面既可能是 42px 也可能是 128px —— 读的人无从分辨，
    于是「审计跑在最坏档上」这句话没有任何东西在核。
    """
    win, app = window
    # ⛔⛔ RN-598（批 78）：**先把它推到展开** —— 这一行是这条判据的前置状态，不是多余动作。
    #   回退验证逮到过一条假绿：断点把 `_set_expanded(win, app, want)` 改成
    #   `… if want else None`（＝只推展开、不再推回折叠），而这条判据**照样绿** ——
    #   因为音乐条本来就折叠着，「推」和「不推」结果一样。
    #   ⭐⭐⭐ **RN-571 那条教训（钉一个档 = 把它推到那个状态）对判据自己同样成立：
    #     一条判据能不能看见差别，取决于它跑之前世界是什么样 —— 而那也得由它自己钉住。**
    #   ⚠ 而它此前一直没被报出来：并行版把它分到某一片，那一片进程里的残留状态恰好让它红。
    #     ⭐ **一条判据绿不绿，可以取决于它前面跑过谁。**
    mbar.pin(win, app, mbar.MODE_EXPANDED)
    said_collapsed = mbar.pin(win, app, mbar.MODE_WORST_CASE)
    said_expanded = mbar.pin(win, app, mbar.MODE_EXPANDED)

    # ⚠⚠ 批 73 补正：**不许查「那两个字在不在」。**
    #   `MODE_EXPANDED` 那句散文自己就写着「建出来并**展开**」和
    #   「用户把它**展开**之后」—— 两次「展开」与 `{shape}` 槽位的真假毫无关系，
    #   把 `is_expanded` 写反（或改名导致恒假）照样绿。
    # ⭐⭐⭐ **同一个病在同一个文件里有两处，批 72 我只修了子进程输出那一处。**
    #   ⇒ 认**槽位**，并且**把高度读出来判** —— 折叠 42px、展开 112~128px，
    #     这样「报告行说的档」和「它实际量到的高度」必须对得上。
    def _slot(line: str) -> tuple[str, int]:
        found = re.search(r"（(展开|折叠)，占 (\d+)px）", line)
        assert found, f"报告行里没有「（档位，占 Npx）」这个槽位：{line}"
        return found.group(1), int(found.group(2))

    shape_collapsed, px_collapsed = _slot(said_collapsed)
    shape_expanded, px_expanded = _slot(said_expanded)
    assert (shape_collapsed, shape_expanded) == ("折叠", "展开"), (
        f"两档报出来的档位名不对：阻断档说「{shape_collapsed}」、"
        f"展开档说「{shape_expanded}」")
    assert px_collapsed < 100, (
        f"阻断档那一行说折叠，量到的却是 {px_collapsed}px —— "
        f"折叠是 42px，这个数说明它其实是展开的")
    assert px_expanded > 100, (
        f"展开档那一行说展开，量到的却是 {px_expanded}px —— "
        f"展开是 112~128px，这个数说明它并没有真的展开")
    assert said_collapsed != said_expanded, "两档报出来的话一模一样"


def test_pristine_mode_is_not_dragged_into_this(window):
    """基线那一档不许被顺手改成「最坏」。

    ⭐ 两类工装问的不是同一个问题：审计问「用户会不会看到溢出」（要最坏），
    基线问「这一页跟锁基线时比变了没有」（要**可复现**）。
    一个不确定性喂给两个问题，只会有一个碰巧对（本文件模块头那段实测）。
    """
    win, app = window
    said = mbar.pin(win, app, mbar.MODE_PRISTINE)
    assert "可复现" in said or "全新配置" in said, (
        f"基线档那一行的口径变了：{said}")


# ────────────────────────── RN-196（批 72）：把那 44 处**记成数** ──────────────
#
# 批 71 只把数写进了文档。⭐ 而文档里的数不会被任何东西核 —— 同族第五次
# （RN-408 / 468 / 560 / 567 都是「清单里那一格会被跳过」）。
# ⇒ 批 72 把它变成审计里的一张**声明表**：展开档跑出来只要没有变坏就是绿的，
#   变坏或冒出新页面就是红的。表只能变小。
#
# ⚠ 展开档按**页**对账，不按页签：那 34 处页签级缺口全部来自同一个动作
#   （展开控制条吃掉 86px），逐页签记 34 行只是把同一件事抄 34 遍。

def test_the_expanded_mode_owes_nothing():
    """批 145：减字之后展开档不欠债了，几张表都必须是空的，不许再长回来。"""
    import layout_overflow_audit as audit

    assert not audit.KNOWN_EXPANDED_DEBT_COMPACT, "紧凑档的展开档申报表又有东西了"
    assert not audit.KNOWN_EXPANDED_DEBT_FULL, "完整档的展开档申报表又有东西了"
    assert not audit.KNOWN_COMPACT_DEBT, "阻断档那张表不空了"


@pytest.mark.parametrize("label, expanded, expect", [
    ("kill_sound", False, "kill_sound"),          # 整页级：两档都走棘轮
    ("kill_sound", True, "kill_sound"),
    ("kill_sound/手枪", False, None),              # 页签级：阻断档一律判红
    ("kill_sound/手枪", True, "kill_sound"),       # 展开档折算到页
    ("kill_sound/手雷/道具", True, "kill_sound"),   # 页签名里带斜杠也要折对
])
def test_only_the_expanded_mode_ratchets_tab_level_hits(label, expanded, expect):
    """⭐ 阻断档的严格度**一点没松**：页签级命中照旧直接判红。

    这条是本次改动最容易出错的地方 —— 我改的是「命中怎么归类」，
    而阻断档和申报档共用同一段归类代码。
    """
    import layout_overflow_audit as audit

    got = audit.ratchet_label(label, expanded)
    assert got == expect, (
        f"{label!r} 在 expanded={expanded} 下归到了 {got!r}，应为 {expect!r}")


def test_a_worse_number_still_turns_the_gate_red():
    """申报表是**棘轮**，不是豁免：变坏要红，不再命中只提醒。"""
    import layout_overflow_audit as audit

    pid, px = "kill_sound", 29
    table = {(pid, "clip"): (px, "判据自带的样本（真表批 145 清空了）")}

    fresh, worse, loose = audit._split_known([(pid, px)], "clip", table)
    assert not fresh and not worse, f"原数照抄却判红了：{fresh} {worse}"

    fresh, worse, loose = audit._split_known([(pid, px + 20)], "clip", table)
    assert worse, f"{pid} 从 {px} 变坏到 {px + 20} 竟然没红"

    fresh, worse, loose = audit._split_known([("某个新页面", 30)], "clip", table)
    assert fresh, "冒出一个没申报过的页面竟然没红"

    fresh, worse, loose = audit._split_known([], "clip", table)
    assert loose and not fresh and not worse, (
        "全部不再命中时应当只提醒不判红 —— "
        "「不再命中」既可能是修好了，也可能只是这台机器渲染得不一样，"
        "而判据分不出这两者（`_split_known` 的原话）。")


def test_no_page_falls_off_the_cliff_unannounced():
    """⭐⭐⭐ 真的**跑一遍**展开档，确认没有页面掉下去。

    ⭐⭐⭐ **一道门只有在有人跑那一档时才是门，否则它只是一段文档。**
    而 RN-408 / 468 / 560 / 567 同族四次都证明：写进收工清单的那一格会被跳过。
    ⇒ 只能让它自动跑。**用审计自己的默认主题×字号，一个参数都不许我挑**：
    实测挑参数当场出事 —— `--themes dark --scales 1.0` 只要 11 秒，可那一档下
    六页**一页都不命中**。
    ⭐⭐⭐ **一个我自己挑出来的参数档，会给出一个分母为空的绿。**
    ⇒ 走默认六个组合，**两档各一轮**（紧凑 ~26s + 完整 ~32s）。

    ⚠⚠ **只判「有没有页面掉下去」，不判「差了几个像素」。** 后者是一台机器的事实：
    2026-08-22 公开仓 `e265ab1` 上，四页纵向债在 CI 那台机器上**根本不复现**。
    """
    for compact in (True, False):
        _check_one_expanded_run(compact=compact)


def test_the_audit_also_measures_the_pages_with_content():
    """批 146：干净配置下音效页是空库，武器板不显示。审计要再量一遍有风格的样子，而且要真量到。"""
    output = _run_audit_in_a_box(["--themes", "dark", "--scales", "1.25", "--no-dialogs"])
    assert "有内容的一遍" in output, output[-2000:]
    assert "造的风格没进页面" not in output, output[-2000:]


def test_the_seed_covers_every_page_with_a_library():
    """干净配置下这些页都是空库，版面从来没被量过（批 146 的盲区，批 147 三页改版后更大）。"""
    import _audit_seed

    assert {"kill_sound", "kill_voice", "switch_weapon", "reload_sound",
            "death_sound", "gun_sound", "special_sound"} <= set(_audit_seed.PAGES)


def _run_audit_in_a_box(extra_args: list[str]) -> str:
    """起一个子进程跑审计，**把它关进一个自己的世界里**，回报它的全部输出。

    ⭐⭐⭐ **子进程必须拿一份自己的配置目录。**
    第一版直接继承 pytest 的环境 ⇒ 审计把 `compact_mode=True` /
    `music_bar_expanded=True` **写进了几路 worker 共用的那份测试配置**，
    下一个建窗口的测试于是从紧凑档 + 展开的音乐条开始。
    实测代价：`test_ui_visual_r1_fixes` 四条当场红，而它报的是
    「只找到 0 个导航项」——**读起来像那条判据自己瞎了，不像有人改了世界**。
    ⚠ 而它**只在某些 worker 分配下复现**（第一轮全绿、第二轮四条红）——
      一条时好时坏的门禁比没有门禁更坏。

    ⚠⚠⚠ 批 73 补正 · **我为隔离而设的那个变量，把隔离机制关掉了。**
    只设 `CS2C_CONFIG_DIR` 是不够的：`_pristine_config.use_pristine_config_dir`
    的语义是「**外面定了就听外面的**」（它是 `setdefault` 那一路），于是我这一设
    就让它整段早退 —— 而它早退掉的正是**落一个空占位 `config.json`** 那一步。
    没有占位文件，`config.migrate_old_config()` 认为「目标不存在」，
    就把**仓库根上开发者自己那份 `config.json`** 拷进沙箱。
    ⇒ 这条判据量的于是不是「全新用户」，是**我的个人配置**（RN-031 原形复发）。
    ⇒ 修法：自己把占位文件落进去，内容取 `_pristine_config.PLACEHOLDER` 这个真源，
      **不在这里抄第二份 `"{}"`**。

    ⚠⚠ 批 73 补正 · **游戏沙箱也要隔离。** `_audit_sandbox.sandbox_dir()` 默认是
    `%TEMP%/cs2customizer_audit_game_sandbox` 这个**固定名**，而 `conftest.py` 逐字写着
    「并行的几路共用它是有意为之」—— 那句话说的是 in-process 的几路 worker，
    不包括这里这个会 `reset_sandbox_game_dir()` 清空它的子进程。
    ⭐ 它有现成的逃生门 `CS2C_AUDIT_SANDBOX_DIR`，用它。
    """
    import os
    import subprocess
    import tempfile

    from _pristine_config import PLACEHOLDER

    env = dict(os.environ)
    box = tempfile.mkdtemp(prefix="cs2customizer_expanded_audit_")
    cfg_dir = os.path.join(box, "config")
    env["CS2C_CONFIG_DIR"] = cfg_dir
    env["CS2C_LOG_DIR"] = os.path.join(box, "logs")
    env["CS2C_AUDIT_SANDBOX_DIR"] = os.path.join(box, "game_sandbox")
    os.makedirs(cfg_dir, exist_ok=True)
    os.makedirs(env["CS2C_LOG_DIR"], exist_ok=True)
    # ⭐ 占位文件就是「挡住迁移」的那一步（见上面 ⚠⚠⚠）。
    with open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as handle:
        handle.write(PLACEHOLDER)

    proc = subprocess.run(
        [sys.executable, "scripts/layout_overflow_audit.py", *extra_args],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900, env=env)
    return proc.stdout + proc.stderr


def _check_one_expanded_run(*, compact: bool) -> None:
    """跑一档展开审计并核它。`compact=False` 那一档是批 73 才补上的（那之前一次都没跑过）。"""
    args = ["--music-bar-expanded"] + (["--compact"] if compact else [])
    which = "紧凑档" if compact else "完整档"
    out = _run_audit_in_a_box(args)

    # ⚠ 看**裁定行**，不看退出码：退出链路会把 `$?` 洗成 0（RN-172 那一族）。
    verdict = re.search(r"^RESULT layout rc=(\d+)$", out, re.M)
    assert verdict, (
        f"[{which}] 审计没给出裁定行 —— 它可能在给出结论之前就死了：\n{out[-2000:]}")

    # ⭐ 阳性对照：这一轮真的跑在**展开**档上（认槽位，不认那两个字）。
    shape = re.search(r"（展开，占 (\d+)px）", out)
    assert shape, (
        f"[{which}] 报告行里没有「（展开，占 Npx）」这个槽位 —— 这一轮多半跑在"
        f"折叠档上（`--music-bar-expanded` 那条接线坏了？），"
        f"而折叠档下一页都不命中，本判据会全绿。\n{out[-1500:]}")
    assert int(shape.group(1)) > 100, (
        f"[{which}] 钉出来的音乐条只有 {shape.group(1)}px —— "
        f"折叠 42px、展开 112~128px，这个数说明它并没有真的展开。")

    # 批 145：外壳的那一路接着没有，看报告行那个数（这一轮真的量了）。
    assert re.search(r"含外壳 [1-9]\d* 个", out), (
        f"[{which}] 报告行说外壳一个都没量 —— `_shell_scopes` 那一路断了。\n{out[-1500:]}")

    # ⚠ 批 73：打印里去掉了「整页」两个字（展开档下那个 pid 可能是页签折算上来的，
    #   写「整页」会让人拿着一个在整页上量不出来的数去复现）。
    fresh = re.findall(r"\[([^\]]+)\] \(新\) 最小高超出可视区 (\d+)px", out)
    assert not fresh, (
        f"[{which}] 展开档有页面掉下去了：{fresh}\n"
        f"⇒ 批 145 起这一档一处都不欠。要么这一页真的变坏了，要么这台机器的字体度量不同"
        f"（`_split_known` 记过 e265ab1 那次）—— 两种都要人看一眼，不许静默。")
