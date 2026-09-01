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


def test_no_page_asks_the_machine_where_cs2_is_installed(qapp, monkeypatch):
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
    """
    import cfg_utils

    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setenv("CS2C_NO_ACCOUNT_SESSION", "1")

    import _audit_neutralize as neutral
    import _ui_mode
    from _audit_sandbox import restore_config_persistence, sandbox_external_writes
    from config import config

    sandbox_external_writes(verbose=False)
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
