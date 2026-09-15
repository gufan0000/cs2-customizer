# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 37 · RN-473：**为「可复现」而选的固定沙箱目录，自己成了不可复现的来源。**

## 怎么撞上的：CI 逮到一条本机绿、CI 红的

批 36 给 `utility` 锁的关档基线，在 CI 上对不上，差的是同一条 `hintLabel` 的内容：

    本机锁的： 「地图」和「阵营」要进对局才认得出来（软件从游戏里实时读）
    CI  跑的： 「地图」和「阵营」现在还认不出来：软件要先往 CS2 里写一份配置文件才读得到…

这两句话是我批 36 亲手写的**同一个 if 的两支**，判据也已经按批 36 的教训
「两支各打桩跑一遍」写好了 —— **判据是对的，基线不是**。

## 根因不是我以为的那个

第一直觉：`_gsi_cfg_ready()` 里有一条 `find_cfg_path()` 的兜底，它会**全盘搜**
真实 Steam 安装 ⇒ 绕过审计沙箱。听起来完全成立。
**实测：审计模式下走完全站 28 页，`find_cs2_install_dir` 被调用 0 次。**

真因在别处：审计沙箱 `%TEMP%/cs2customizer_audit_game_sandbox` 是一个**固定路径**，
而它的 `game/csgo/cfg/` 里躺着一份 **2026-08-14 写下的** `gamestate_integration_cs2customizer.cfg`
—— 18 天前某一轮审计跑的时候，产品自己写进去的。于是：

    我这台机器：沙箱里有 GSI cfg ⇒ 页面走「已装好」那一支
    CI  的机器：沙箱是刚建的空目录 ⇒ 页面走「还没装」那一支

⭐⭐⭐ **那个固定路径是为了「可复现」才选的**（`_audit_sandbox` 的注释逐字写着：
「路径必须固定，不能用 mkdtemp：`page_fingerprint.py` 要求同一份代码跑两次得出同一个指纹」）。
它确实让**路径**可复现了，代价是让**内容**不可复现 ——
因为固定目录会攒东西，而攒进去的正是**产品自己写的产物**。
⇒ **一台被审计跑过 N 次的机器，越来越不像一台新机器。**

## ⭐⭐ 同一条教训，前一次逐字写在同一个文件的注释里

`tests/conftest.py` 里 RN-141 那段：
「上面这个配置目录是**固定路径、跨轮次累积**的（为了 csgo_dir 可复现）。
代价是本机跑久了它会攒下一堆设置，而 CI 每次都是全新配置 ——
于是『不钉前置状态的判据』在两边给出不同结论。」

那次的处置是给 **config** 钉了两个键（`csgo_dir` / `ui_expert_mode`）。
而**同一个沙箱的另一半 —— 游戏目录里的文件 —— 一个字都没钉**。
⭐ **认出了「固定路径会攒东西」这条规律，却只在当时被咬到的那一半上做了处置。**

## 修法：沙箱开跑时清成「没被本软件写过」的样子

⛔ 不是删整个目录 —— 那会连目录形状一起没掉，而形状是刻意建出来的。
只清**本软件自己写的那几个产物**，名单显式列出：越界的文件不碰。

⚠ 清理点在**开跑时**，不是收尾时：审计跑的过程中产品会往里写（那是沙箱的正常工作），
收尾清会和「审计只读」的口径打架，也挡不住进程被砍断。

⛔ **不许两处各写一份**：`tests/conftest.py` 和 `scripts/_audit_sandbox.py`
都要准备这个目录，而这正是 RN-002（一张名单被抄 9 份）的形状。
"""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


def _sandbox_cfg_dir() -> Path:
    import _audit_sandbox

    return _audit_sandbox.sandbox_dir() / "game" / "csgo" / "cfg"


def test_the_reset_wipes_what_the_product_itself_wrote():
    """把产物放回去，清一次，它们必须消失。

    ⭐ 破坏验证内建在用例里：先造出缺陷（写一份 GSI cfg），再证明清理咬得动它。
    不先造，这条断言在一台干净机器上恒绿 —— 那正是它要防的那种绿。
    """
    import _audit_sandbox

    cfg_dir = _sandbox_cfg_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    planted = cfg_dir / "gamestate_integration_cs2customizer.cfg"
    planted.write_text('"cs2customizer" { "uri" "http://127.0.0.1:3000" }', encoding="utf-8")
    assert planted.exists(), "阳性对照：文件没种进去"

    removed = _audit_sandbox.reset_sandbox_game_dir()

    assert not planted.exists(), (
        "清理没咬动 `gamestate_integration_cs2customizer.cfg` —— "
        "而它正是让 utility 的基线在本机和 CI 上分叉的那一份"
    )
    assert "gamestate_integration_cs2customizer.cfg" in removed, (
        f"清理要**说出**自己删了什么（这是发现通道，不是消音器），实际返回：{removed}"
    )


def test_the_reset_does_not_touch_what_it_did_not_write():
    """越界的文件不许碰 —— 沙箱是临时目录，但不是"随便删"的许可证。"""
    import _audit_sandbox

    cfg_dir = _sandbox_cfg_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    stranger = cfg_dir / "somebody_elses_notes.txt"
    stranger.write_text("not ours", encoding="utf-8")
    try:
        _audit_sandbox.reset_sandbox_game_dir()
        assert stranger.exists(), "清理动了不是本软件写的文件"
    finally:
        stranger.unlink(missing_ok=True)


def test_sandboxing_external_writes_starts_from_a_clean_game_dir():
    """`sandbox_external_writes()` 走完之后，沙箱里不许还留着上一轮的产物。

    这是**接线**判据：清理函数写对了，但没人在开跑时调它，等于没写
    （本仓已有三次「闸门在某支脚本里没接上」：RN-005 / RN-059 / RN-073）。
    """
    import _audit_sandbox

    cfg_dir = _sandbox_cfg_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "gamestate_integration_cs2customizer.cfg").write_text("stale", encoding="utf-8")

    # 幂等锁会让第二次调用直接返回，所以先解掉——判据要测的是它**这一次**做了什么
    _audit_sandbox._SANDBOX_DIR = None
    try:
        _audit_sandbox.sandbox_external_writes(verbose=False)
    finally:
        _audit_sandbox.restore_config_persistence()

    # ⭐ 分母守卫：名单空了 / 目录没了，下面那条否定断言会**静默全绿**。
    assert len(_audit_sandbox.PRODUCT_WRITTEN_CFGS) >= 3, (
        "产物名单被改瘦了 —— 名单一空，这条判据就永远绿")
    assert cfg_dir.is_dir(), "沙箱的 cfg 目录不存在 —— 沙箱化没建出目录形状"
    leftovers = sorted(
        p.name for p in cfg_dir.glob("*") if p.name in _audit_sandbox.PRODUCT_WRITTEN_CFGS
    )
    assert not leftovers, (
        f"沙箱化跑完，游戏目录里还留着上一轮的产物：{leftovers}\n"
        "⇒ 这台机器上的基线锁的是「跑过 N 轮之后的样子」，而 CI 锁的是「新机器」"
    )


def test_the_test_harness_and_the_audit_scripts_share_one_implementation():
    """`conftest` 不许自己再写一份沙箱准备逻辑 —— 一份名单只准有一处（RN-002）。"""
    text = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    called = any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == "reset_sandbox_game_dir")
            or (isinstance(n.func, ast.Attribute) and n.func.attr == "reset_sandbox_game_dir")
        )
        for n in ast.walk(tree)
    )
    assert called, (
        "conftest 没调 `reset_sandbox_game_dir()` —— "
        "于是 pytest 跑在一个攒了 N 轮产物的目录上，而 CI 每次都是新的"
    )
    assert "PRODUCT_WRITTEN_CFGS" not in text, (
        "conftest 里出现了第二份产物名单。名单只准有一处（`_audit_sandbox`），"
        "抄一份的代价是改一处忘一处不会报错（RN-002 那份被抄 9 遍的设备页名单）"
    )


def test_no_page_asks_the_machine_where_cs2_is_installed(qapp, monkeypatch, tmp_path):
    """⭐⭐ 审计口径下走完全站：不许有任何人去问机器「你把 CS2 装哪了」。

    ⚠⚠ **这条是被一次假的实测逼出来的。** 我第一次架这支探针时量到
    `find_cs2_install_dir` **被调用 0 次**，据此判定"全盘搜不是根因"，
    转头去查别的。清掉沙箱之后同一支探针量到 **1 次** —— 就在 `utility` 页。

    成因是一个 `if not ready:` 短路：沙箱里攒着那份 18 天前的 GSI cfg
    ⇒ 第一支就为真 ⇒ 后面那条全盘搜**从来没被走到**。
    ⭐⭐⭐ **一个短路会把它后面那一项从任何实测里藏起来，
      而「没被调用」看起来和「不存在」一模一样。**
    ⇒ 所以这条判据不是"顺手加的第三条"，它是那次误判的替代品：
      探针只在我恰好制造的那个状态下有效，判据每一轮都在。

    ⛔ 为什么"问一下"就算错：`config.csgo_dir` 是审计沙箱能控制的**唯一**入口
    （`_audit_sandbox` 就是靠改它来隔离的）。绕过它去全盘搜，等于绕过整个沙箱 ——
    页面于是开始描述**这台机器**，而基线以为自己锁的是**这个软件**。

    ⚠⚠⚠ **RN-553（批 67）：这条判据的回退断点只在并行分片下砍不动。**
    它原来靠 `sandbox_external_writes()` 顺手把游戏目录清干净来保证短路会落空 ——
    而那个沙箱路径是**固定**的（`%TEMP%/cs2customizer_audit_game_sandbox`，RN-473 当初
    为了「同一份代码跑两次得同一个指纹」故意钉死的），于是它在 6 个并行分片之间是
    **一份共享可变状态**：别的分片里产品往里写了一份 GSI cfg，这里的 `ready` 就
    提前为真、短路生效、探针量到 0 次 —— 和「产品没去全盘搜」长得一模一样。
    ⭐⭐⭐ **当初为「可复现」而钉死的那条固定路径，在并行之下正是不可复现的来源** ——
      这正是 RN-473 那条教训往上一层的同一句话。
    ⇒ 判据自己钉住它依赖的那件事：把 `config.csgo_dir` 指到**本判据私有**的空目录，
      短路必然落空，跑串行还是并行都不影响。⛔ 不许靠重跑掩盖。
    """
    import cfg_utils

    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setenv("CS2C_NO_ACCOUNT_SESSION", "1")

    import _audit_neutralize as neutral
    import _ui_mode
    from _audit_sandbox import restore_config_persistence, sandbox_external_writes
    from config import config

    sandbox_external_writes(verbose=False)
    # RN-553：本判据私有的空游戏目录 —— 建出 cfg 那一层但**不放** GSI cfg，
    # 好让 `utility` 那个 `if not ready:` 短路必定落空（阴性对照就是这一半）。
    private_dir = tmp_path / "cs2_private"
    (private_dir / "game" / "csgo" / "cfg").mkdir(parents=True)
    was_dir = getattr(config, "csgo_dir", "")
    config.csgo_dir = str(private_dir)
    neutral.apply(config)

    asked: list[str] = []
    real = cfg_utils.find_cs2_install_dir
    monkeypatch.setattr(
        cfg_utils, "find_cs2_install_dir",
        lambda *a, **kw: (asked.append("x"), real(*a, **kw))[1])

    import gui_widget
    from PySide6.QtCore import Qt

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        qapp.processEvents()
        pages = [p for p in win._page_names.keys() if p not in neutral.unsafe_pages()]
        neutral.apply(config, pages)
        for pid in pages:
            _ui_mode.goto(win, pid)
            for _ in range(3):
                qapp.processEvents()
        assert not asked, (
            f"审计跑里有人去全盘搜 CS2 安装目录（{len(asked)} 次）—— "
            "那条路绕过了 `config.csgo_dir`，也就绕过了整个审计沙箱。\n"
            "⇒ 页面开始描述「这台机器」，而基线以为自己锁的是「这个软件」"
        )
    finally:
        win.close()
        qapp.processEvents()
        config.csgo_dir = was_dir
        restore_config_persistence()


def test_the_utility_hint_follows_the_configured_dir_only(qapp, tmp_path):
    """`utility` 那句 GSI 指路，两支都要**只由 `config.csgo_dir` 决定**。

    ⭐ 带阳性对照：不放 cfg ⇒ 「去设目录」那一支；放一份 ⇒ 「进对局」那一支。
      少了任何一半，这条都可能在一个恒定的答案上假绿。
    """
    from config import config
    from pages.utility_page import UtilityPage

    cfg_dir = tmp_path / "game" / "csgo" / "cfg"
    cfg_dir.mkdir(parents=True)
    old = getattr(config, "csgo_dir", "")
    try:
        config.csgo_dir = str(tmp_path)
        page = UtilityPage()
        assert page._gsi_cfg_ready() is False, "目录里没有 GSI cfg，却答「已装好」"

        (cfg_dir / "gamestate_integration_cs2customizer.cfg").write_text("x", encoding="utf-8")
        page2 = UtilityPage()   # 新实例：`_gsi_cfg_ready` 的结果是缓存的
        assert page2._gsi_cfg_ready() is True, "目录里有 GSI cfg，却答「还没装」"
        page.deleteLater()
        page2.deleteLater()
    finally:
        config.csgo_dir = old


def test_the_sandbox_stays_inside_the_temp_dir():
    """⛔ 安全阀：清理只在临时目录里发生。

    这份代码删文件，而它删的目录来自一个**环境变量可覆盖**的路径
    （`CS2C_AUDIT_SANDBOX_DIR`，为了出对外截图时不带用户名）。
    ⇒ 有人把它指到真实 CS2 目录上时，清理必须拒绝，而不是照删。
    """
    import _audit_sandbox

    real_looking = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive")
    removed = _audit_sandbox.reset_sandbox_game_dir(real_looking)
    assert removed == [], (
        "清理对一个临时目录之外的路径动手了 —— 那可能是用户真实的 CS2 安装"
    )
    assert str(tempfile.gettempdir()).lower() in str(_audit_sandbox.sandbox_dir()).lower(), (
        "默认沙箱路径不在临时目录里了，上面那条安全阀要跟着重想"
    )


#: 会**落盘**、而且会改变下一个测试看到的窗口形状的配置键。
#: ⚠ 分母只放「形状类」的：改了它，别人建出来的窗口就不一样了。
_SHAPE_KEYS = ("compact_mode", "music_bar_expanded", "ui_expert_mode",
               "ui_font_scale")

#: 真的把形状键拨到**非默认档**、又没还回去的文件。
#: ⚠ 它们不是豁免，是**在册存量**（RN-572）：这条判据只保证不再新增。
#:
#: ⭐⭐⭐ 这张表批 72 有 5 行、批 72 补正涨到 9 行、批 73 缩到 4 行 ——
#:   **三次都不是「事情变好或变坏」，三次都是尺子在变**：
#:   ① 批 72：`_SHAPE_KEYS` 里三个名字拼错（`expert_mode` 实为 `ui_expert_mode`），
#:      那几格永远匹配不到 ⇒ 表偏小；
#:   ② 批 72 补正：名字修对 ⇒ 5 → 9；
#:   ③ 批 73：发现判据查的是「有没有赋值」而它声称查的是「有没有拨走」——
#:      实测 9 行里 **5 行赋的是产品默认值或当场拨了回来**，从来就不是违规 ⇒ 9 → 4。
#:   ⭐ **一张台账连着三次变动，一次真实的质量变化都没有。**
#:      所以每一行都要写清「它是哪一种」，否则读表的人只会看到一个上下跳的数字。
#:
#: 出表的五个（批 73 复核，各自的理由）：
#:   · `test_audit_measures_the_whole_page.py` —— 只写 `compact_mode = False`（**默认值**）
#:   · `test_the_bottom_bar_stops_shouting.py` —— 同上，且先调了 `block_config_persistence()`
#:   · `test_idle_preload.py` —— `ui_expert_mode = False`（默认值），随后从变量赋回
#:   · `test_compact_mode_layout_r11.py` —— 拨 True 之后**当场拨回 False**
#:   · `test_no_layout_self_talk_sitewide.py` —— 同上
#:
#: ⚠⚠ **已知的宽松，写下来而不是假装没有**：后两个是「拨走 → 用 → 拨回」的**直线**写法，
#:   中途抛异常就还不回去（正是本批给 `test_the_audit_says_which_worst_case_it_pinned`
#:   的夹具补 `try/finally` 的那个理由）。判据接受它，是因为不接受会把大量正当写法判红；
#:   ⇒ 这条宽松记在这里，不新增判据（v4 §四-2 冻结账本类判据仍然有效）。
_KNOWN_UNRESTORED = {
    # 四处全是 `ui_expert_mode = True` 且没有任何还原。
    "test_audit_can_see_every_page.py",
    "test_design_w5.py",
    "test_search_jump_r13.py",
    "test_search_sticky_r14.py",
}


def test_every_shape_key_is_a_real_config_attribute():
    """⭐⭐⭐ **先证明这张分母表上的名字真的存在。**

    ⚠ 这条是补上来的：第一版 `_SHAPE_KEYS` 写了五个名字，其中
    `expert_mode` / `font_scale` / `sidebar_collapsed` **根本不是 config 的属性**
    （真名是 `ui_expert_mode` / `ui_font_scale`）—— 于是那三格永远匹配不到任何东西，
    而扫描照常返回、判据照常绿。
    ⭐ **一张分母表可以有一半是拼错的名字，而它看起来和覆盖完整一模一样。**
    """
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from config import config

    missing = [k for k in _SHAPE_KEYS if not hasattr(config, k)]
    assert not missing, (
        f"这些名字不在 config 上：{missing}\n"
        f"⇒ 它们在扫描里永远匹配不到，等于分母少了几格。config 上现有的相近名字："
        f"{sorted(n for n in dir(config) if any(w in n for w in ('expert', 'font_scale', 'sidebar', 'compact', 'music_bar')))}")


#: 掐掉**全部**落盘的机制 —— 它一上，任何形状键都还得回去，与键无关。
_BLANKET_RESTORES = ("block_config_persistence",)

#: 显式把值写回去的落盘入口。⚠ 名字是 `save_config_now`，不是 `save`。
_EXPLICIT_RESTORE = "save_config_now"


def _call_name(node) -> str:
    """`foo.bar(...)` → `bar`；`bar(...)` → `bar`；认不出回空串。"""
    import ast

    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


#: 这几个键的**产品默认值**（`config.py` 里 `__init__` 写的那一份）。
#: ⚠ 拨到默认值**不是违规** —— 那正是别人期望看到的窗口。
_SHAPE_DEFAULTS = {"compact_mode": False, "music_bar_expanded": False,
                   "ui_expert_mode": False, "ui_font_scale": 1.0}


def test_the_declared_defaults_match_the_product():
    """空转守卫：上面那张默认值表必须跟产品对得上，否则整条判据量错东西。"""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from config import config

    wrong = {k: (v, getattr(config, k, "<没有这个属性>"))
             for k, v in _SHAPE_DEFAULTS.items()
             if getattr(config, k, object()) != v}
    # ⚠ 只在「全新配置」下才严格相等；这里放宽成类型一致 + 名字存在，
    #   免得跑测试的机器上有人真的开着紧凑档就把这条判红（RN-146 那一族）。
    assert set(_SHAPE_DEFAULTS) == set(_SHAPE_KEYS), (
        f"默认值表和分母表对不上：{set(_SHAPE_DEFAULTS) ^ set(_SHAPE_KEYS)}")
    for key, (declared, actual) in wrong.items():
        assert type(actual) is type(declared), (
            f"`{key}` 的类型变了：声明 {declared!r}、实际 {actual!r} —— "
            f"默认值表要跟着改")


def _pin_mode_expands(arg, src: str) -> bool:
    """`pin(win, app, <这个参数>)` 会不会把 `music_bar_expanded` 拨成 True。

    ⭐ 三种写法都要认，否则又是一个「按记号划分母」的洞：
    `mbar.MODE_EXPANDED`（属性）、`"expanded"`（字面量）、`music_bar`（变量）。
    ⚠ 变量那种解析不出来 ⇒ **看这个文件里有没有可能产生 `expanded` 这个档**：
      产生不了就不算拨（实测 `test_preset_center_tells_the_truth.py` 参数化的两个
      取值是 `"auto"`/`"on"` —— 一个不碰、一个拨成默认值 False，都无害）；
      有可能就算拨，不确定落到会多报的那一侧（RN-434 的口径）。
    """
    import ast

    if arg is None:
        return True
    if isinstance(arg, ast.Attribute):
        return arg.attr == "MODE_EXPANDED"
    if isinstance(arg, ast.Constant):
        return arg.value == "expanded"
    return "MODE_EXPANDED" in src or '"expanded"' in src


def _keys_pinned_in(node, src: str = "") -> set:
    """这一段语法树里，哪几个形状键被**拨到了非默认档**。

    ⚠⚠⚠ 批 73 补正 · **它原来查的是「有没有动过」，而它声称查的是「有没有拨走」。**
    实测：在册那张表里有四处赋的是 `config.compact_mode = False` ——
    **False 就是产品默认值**，那不是拨走，那是拨回来。
    ⭐⭐⭐ **一张「在册违规」表，里面可以有几处根本不是违规 ——
      因为判据查的东西和它声称查的东西不是一件事，
      而表看起来一直在忠实记录。**（同 F30 那条：名字承诺的比函数体做的多）

    ⚠⚠ 批 73 补正 · **间接拨的那一半原来结构上看不见。**
    `music_bar_expanded` 在全仓**没有任何一个测试**写字面
    `config.music_bar_expanded = …` —— 它一律经 `_audit_music_bar.pin()` 去拨，
    于是这半个分母**恒为 0**，而扫描照常返回、判据照常绿。
    ⭐ **一个只认字面赋值的扫描，看不见经函数拨的那一半。**
    ⇒ 只有 `MODE_EXPANDED` 算拨走（它把键设成 `True`）；`MODE_WORST_CASE`
      设成 `False`＝默认，`MODE_PRISTINE` 压根不碰。档位认不出来时**算拨走**
      —— 不确定要落到会多报的那一侧（RN-434 的口径）。
    """
    import ast

    pinned = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if not (isinstance(tgt, ast.Attribute) and tgt.attr in _SHAPE_KEYS
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "config"):
                    continue
                # 非常量右值（`config.x = kept`）是**还原**那一侧，不算拨走。
                if isinstance(sub.value, ast.Constant):
                    if sub.value.value != _SHAPE_DEFAULTS[tgt.attr]:
                        pinned.add(tgt.attr)
        elif isinstance(sub, ast.Call) and _call_name(sub) == "pin":
            mode = sub.args[2] if len(sub.args) >= 3 else None
            if _pin_mode_expands(mode, src):
                pinned.add("music_bar_expanded")
    return pinned


def _restored_in(node, key: str) -> bool:
    """这一段语法树里，`key` 有没有被还回去。

    ⚠⚠ 批 73 补正 · **豁免原来是整个文件的子串匹配**
    （`"save_config_now" in src or "monkeypatch.setattr(config" in src`）——
    实测三处免检全部靠**异键的 monkeypatch**（`crosshair_enabled` /
    `screen_edge_flash_enabled`）或**一段字符串字面量**（子进程探针脚本里
    写着 `config.save_config_now()`）蒙混过关。
    ⭐⭐⭐ **一个文件级的豁免，只要这个文件里任何一个角落出现过那个词就成立 ——
      而拨那个键的地方可能离它十万八千里。**
    ⇒ 收紧成两条：① 掐全部落盘（与键无关）；
      ② 或者**在拨它的这同一段代码里**有显式还原 / 针对**这个键**的 monkeypatch。
    """
    import ast

    for sub in ast.walk(node):
        # 第三种合格写法：**把它拨回去** —— 赋回默认常量，或从存好的变量赋回。
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if not (isinstance(tgt, ast.Attribute) and tgt.attr == key
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "config"):
                    continue
                if not isinstance(sub.value, ast.Constant):
                    return True                     # `config.x = kept`
                if sub.value.value == _SHAPE_DEFAULTS[key]:
                    return True                     # `config.x = False`
            continue
        if not isinstance(sub, ast.Call):
            continue
        name = _call_name(sub)
        if name in _BLANKET_RESTORES or name == _EXPLICIT_RESTORE:
            return True
        # `monkeypatch.setattr(config, "<这个键>", …)` —— 必须点名同一个键。
        if (name == "setattr" and len(sub.args) >= 2
                and isinstance(sub.args[0], ast.Name) and sub.args[0].id == "config"
                and isinstance(sub.args[1], ast.Constant)
                and sub.args[1].value == key):
            return True
    return False


def _shape_offenders():
    """哪些测试文件把形状键拨到非默认档、却没有**真的把它还回去**。

    ⚖ **粒度定在「文件」，但豁免必须是一次真正的函数调用。**
    ⚠ 我第一版把粒度收到「拨它的那个函数」，理由是「借与还是一对」——
      跑下来它把 `test_the_audit_says_which_worst_case_it_pinned.py` 判成违规，
      而那个文件是**夹具借、夹具的 finally 还**，用例函数只管用。
      ⭐ **夹具借、夹具还，是正当形状** —— 收到函数级会把它一起判掉。
    ⇒ 退回文件级，但把三个漏洞堵死（这三个正是实测蒙混过关的路子）：
      ① 字符串字面量里写着 `config.save_config_now()`（子进程探针脚本）；
      ② 注释里出现那个词；
      ③ `monkeypatch.setattr(config, "别的键", …)` —— **异键**也能当豁免。
      走 AST 只认 `Call` 节点、且 `setattr` 必须点名**同一个键**，三条一起失效。
    """
    import ast

    here = Path(__file__).resolve().parent
    offenders = {}
    scanned = 0
    for path in sorted(here.glob("test_*.py")):
        src = path.read_text(encoding="utf-8", errors="ignore")
        scanned += 1
        tree = ast.parse(src)
        bad = sorted(key for key in _keys_pinned_in(tree, src)
                     if not _restored_in(tree, key))
        if bad:
            offenders[path.name] = bad
    return scanned, offenders


def _tests_that_pin_a_shape():
    """在册之外的违规者（`_KNOWN_UNRESTORED` 是存量，不是豁免）。"""
    scanned, offenders = _shape_offenders()
    return scanned, [f"{name}: {keys}" for name, keys in sorted(offenders.items())
                     if name not in _KNOWN_UNRESTORED]


#: 三个**实测蒙混过关**的豁免写法 + 三个真该放行的写法。
#: ⭐ 这一组是这条判据自己的对照：批 72 那版豁免是整文件子串匹配，
#:   下面前三条在那一版下全都判「已还原」，而它们一个都没还。
_EXEMPTION_CASES = [
    ("异键的 monkeypatch 不算还原", False, '''
def fx(monkeypatch):
    config.compact_mode = True
    monkeypatch.setattr(config, "crosshair_enabled", False, raising=False)
'''),
    ("字符串字面量里的还原不算还原", False, '''
def fx(tmp_path):
    config.compact_mode = True
    probe.write_text("config.save_config_now()\\n")
'''),
    ("注释里的还原不算还原", False, '''
def fx():
    config.compact_mode = True
    # 记得 config.save_config_now()
'''),
    ("同键的 monkeypatch 算还原", True, '''
def fx(monkeypatch):
    config.compact_mode = True
    monkeypatch.setattr(config, "compact_mode", False, raising=False)
'''),
    ("显式落盘还原算还原", True, '''
def fx():
    config.compact_mode = True
    yield
    config.compact_mode = kept
    config.save_config_now()
'''),
    ("掐掉全部落盘算还原", True, '''
def fx():
    block_config_persistence()
    config.compact_mode = True
'''),
]


@pytest.mark.parametrize("why, ok, src",
                         _EXEMPTION_CASES,
                         ids=[c[0] for c in _EXEMPTION_CASES])
def test_the_exemption_cannot_be_talked_into(why, ok, src):
    """⭐⭐⭐ **豁免必须是一次真正的调用，不是这个词在文件里出现过。**

    批 72 那一版写的是
    `if "save_config_now" in src or "monkeypatch.setattr(config" in src`，
    于是**注释、字符串字面量、以及针对别的键的 monkeypatch** 全都能当豁免用 ——
    而实测三处免检正是靠这三条路过的关。
    ⭐ 同本批第 N 次：**一个词出现过，和它真的在起作用，是两件事。**
    """
    import ast

    tree = ast.parse(src)
    pinned = _keys_pinned_in(tree, src)
    assert "compact_mode" in pinned, f"[{why}] 连「拨了」都没看出来 —— 判据在空转"
    assert _restored_in(tree, "compact_mode") is ok, (
        f"[{why}] 还原判定给出了 {not ok}，应为 {ok}")


def test_pinning_to_the_default_value_is_not_a_violation():
    """⭐⭐⭐ `config.compact_mode = False` 是**拨回来**，不是拨走。

    ⚠ 批 72 那一版不看值，于是「在册违规表」里有五行根本不是违规
    （见 `_KNOWN_UNRESTORED` 上面那段账）。
    ⭐ **判据查的东西和它声称查的东西不是一件事，而表看起来一直在忠实记录。**
    """
    import ast

    default = ast.parse("def fx():\n    config.compact_mode = False\n")
    assert not _keys_pinned_in(default), "赋默认值被当成了拨走"
    walked = ast.parse("def fx():\n    config.compact_mode = True\n")
    assert _keys_pinned_in(walked) == {"compact_mode"}, "赋非默认值竟然没算拨走"


@pytest.mark.parametrize("arg, expect", [
    ("mbar.MODE_EXPANDED", True),
    ('"expanded"', True),
    ("mbar.MODE_WORST_CASE", False),      # 它把键设成 False ＝ 默认值
    ("mbar.MODE_PRISTINE", False),        # 它压根不碰这个键
])
def test_the_indirect_pin_is_in_the_denominator(arg, expect):
    """⭐ 经 `pin()` 拨的那一半，原来结构上看不见（全仓零个字面赋值）。"""
    import ast

    src = f"def fx(win, app):\n    mbar.pin(win, app, {arg})\n"
    got = "music_bar_expanded" in _keys_pinned_in(ast.parse(src), src)
    assert got is expect, f"pin({arg}) 判成 {got}，应为 {expect}"


def test_the_known_unrestored_list_has_not_gone_stale():
    """⭐ 在册存量表只能变小：修好一个就从表里删一个。

    ⚠⚠ 批 73 补正 · **原来它判的是「这个文件还拨不拨形状」，不是
    「它还算不算违规」** —— 于是给在册文件补上还原代码之后，只要那句赋值还在，
    它就永远留在册上，`_KNOWN_UNRESTORED` **只能涨不能缩**，成了永久免检区
    （RN-469 那个形状）。⇒ 改成用**同一套违规判定**来对账。
    """
    _scanned, offenders = _shape_offenders()
    still = set(offenders) & _KNOWN_UNRESTORED
    assert still, (
        "在册的文件里一个都不再违规了 —— 多半是这支扫描瞎了，而不是全修好了。")
    gone = sorted(_KNOWN_UNRESTORED - set(offenders))
    assert not gone, (
        f"这些已经不再违规（拨了但还回去了，或者压根不拨了），"
        f"从 `_KNOWN_UNRESTORED` 里删掉：{gone}")


def test_a_test_that_pins_a_window_shape_puts_it_back():
    """⭐⭐⭐ **钉一个档的人，负责把它还回去。**

    配置会落盘到几路 worker **共用**的那份测试配置里。把 `compact_mode` /
    `music_bar_expanded` 拨过去不还，下一个建窗口的测试就从紧凑档 + 展开的
    音乐条开始 —— 而它报出来的是「只找到 0 个导航项」，
    **读起来像那条判据自己瞎了，不像有人改了世界**。

    实测（批 72 第二轮全量）：`test_ui_visual_r1_fixes` 四条当场红，
    而同一份代码第一轮全绿 —— ⚠ **只在某些 worker 分配下复现**。
    ⭐ 一条时好时坏的门禁比没有门禁更坏。

    ⚠ 还的时候方法名叫 `save_config_now`，不叫 `save`。我第一版写
    `getattr(config, "save", None)` + `if callable(...)`，拿到 None 于是
    **还了个寂寞**：断言全绿、配置照样是脏的。
    ⭐ **一个软兜底在名字写错时，长得跟成功一模一样。**
    """
    scanned, offenders = _tests_that_pin_a_shape()
    assert scanned >= 100, (
        f"只扫到 {scanned} 个测试文件 —— 这支扫描多半瞎了，"
        f"而分母为空的绿和真的没问题在报告上一模一样。")
    assert not offenders, (
        "这些测试把会落盘的「窗口形状」配置拨到非默认档，却没有还回去：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 夹具收尾时 `setattr` 回原值再 `config.save_config_now()`。")
