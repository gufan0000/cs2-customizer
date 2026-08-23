# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-195：音乐控制条只在**放过音乐之后**才存在。

背景（登记册 RN-195）：这条常驻栏原本由 `QTimer.singleShot(8000, ...)`
**无条件**建出来，跟有没有放过音乐无关；一出现就永久吃掉内容区 42px
（实测：完整档可视区 750→708，紧凑档 650→608，两档都正好 42px）。

裁定收窄成「**只做不建，不做撤走**」：
  · 「出现」这个事件今天已经存在（8 秒定时器），侧栏视口校正那条路被
    RN-008 走通过、且有判据看着；
  · 「消失」是全新事件，而且「放着放着控制条不见了」本身就是坏体验。

⭐ **但「只做一半路」不等于可以只做启动那一半。** 实测确认：
`pages/music_page.py` 自己**一个播放控件都没有**（第 31 行原话：
「播放控制栏已移至全局」），用户唯一的播放入口是双击曲目
（`music_page.py:1019 → player.play(row)`），而暂停/下一首/音量**全在这条栏上**。
⇒ 首次播放时控制条必须**当场**出现，否则用户连暂停都点不到。
**一个把用户扔进没有出口的状态的"收窄"，不是收窄，是新缺陷。**
下面 `test_first_play_in_this_session_makes_the_bar_appear` 守的就是这一半。
"""
from __future__ import annotations

import ast

import pathlib

import pytest
from PySide6.QtWidgets import QApplication

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------
# 一、谓词本身：「放过音乐」怎么判
# --------------------------------------------------------------------------

def _fresh_predicate(monkeypatch, *, cfg_index, live_index=None):
    """把谓词的两个输入都**钉死**再问它。

    ⚠ 不钉死不行：`tests/conftest.py` 那个配置目录是**跨轮次累积**的
    （为了 csgo_dir 可复现），本机跑久了 `music_current_index` 完全可能
    不是默认值。RN-141 的原话——判据的前置状态要么它自己钉，要么统一钉死，
    **不许"看命"**。
    """
    import music_player as mp
    from config import config

    monkeypatch.setattr(config, "music_current_index", cfg_index, raising=False)
    if live_index is None:
        monkeypatch.setattr(mp, "music_player", None, raising=False)
    else:
        class _Stub:
            current_index = live_index

        monkeypatch.setattr(mp, "music_player", _Stub(), raising=False)
    return mp.playback_has_ever_started()


def test_pristine_config_means_never_played(monkeypatch):
    assert _fresh_predicate(monkeypatch, cfg_index=-1) is False


def test_a_saved_track_index_means_played_before(monkeypatch):
    assert _fresh_predicate(monkeypatch, cfg_index=0) is True
    assert _fresh_predicate(monkeypatch, cfg_index=7) is True


def test_playing_in_this_session_counts_even_if_config_says_never(monkeypatch):
    """本会话按下播放时 `play()` 先同步写 `current_index`，配置要等加载完成才写。

    ⇒ 光看配置会在「按下播放 → 曲目加载完成」这段窗口里答错。
    """
    assert _fresh_predicate(monkeypatch, cfg_index=-1, live_index=3) is True


@pytest.mark.parametrize("junk", ["", None, "第三首", object()])
def test_a_value_it_cannot_classify_falls_toward_building_the_bar(monkeypatch, junk):
    """⭐ **认不出来的值，必须朝「建」那一边倒。**

    这个判断的两个失效方向**不对称**：
      · 误判成「没放过」= 把用户唯一的播放控制面整个拿掉（音乐页没有任何
        播放控件），用户放着音乐却连暂停都找不到；
      · 误判成「放过」= 多占 42px。
    ⇒ 分不出类的时候，选那个只会难看、不会致残的方向。
    （批 8 的 `_is_open()` 是同一条：认不出的状态一律按「没结」算。）
    """
    assert _fresh_predicate(monkeypatch, cfg_index=junk) is True


# --------------------------------------------------------------------------
# 二、主窗：不是先建再 hide，是**不建**
# --------------------------------------------------------------------------

def _window(app, monkeypatch, *, cfg_index):
    import music_player as mp
    import gui_widget
    from config import config

    monkeypatch.setattr(config, "music_current_index", cfg_index, raising=False)
    monkeypatch.setattr(mp, "music_player", None, raising=False)
    win = gui_widget.MainWindow(auto_background_preload=False)
    return win


def test_never_played_means_the_bar_is_not_built_at_all(app, monkeypatch):
    """⚠ 断言的是 `is None`（没建），**不是** `isVisible() is False`（建了藏起来）。

    RN-009 那个「建出来就 hide 的死控件」是本仓的前科：藏起来的控件
    照样占内存、照样被主题刷新遍历、照样有人往里写文案，而且**照样骗过
    "它不在屏幕上"这类判据**。这里要的是它压根不存在。
    """
    win = _window(app, monkeypatch, cfg_index=-1)
    try:
        win._create_music_control_bar_if_played()
        app.processEvents()
        assert getattr(win, "music_control_bar", None) is None
    finally:
        win.deleteLater()
        app.processEvents()


def test_played_before_means_the_bar_is_there_on_startup(app, monkeypatch):
    win = _window(app, monkeypatch, cfg_index=0)
    try:
        win._create_music_control_bar_if_played()
        app.processEvents()
        assert getattr(win, "music_control_bar", None) is not None
    finally:
        win.deleteLater()
        app.processEvents()


def test_first_play_in_this_session_makes_the_bar_appear(app, monkeypatch):
    """本批最要紧的一条：**没放过 → 不建 → 一放就出现**。

    走的是真实通知路径（`music_player.notify_playback_started()`），
    不是直接调 `_create_music_control_bar()` —— 直接调只能证明"建得出来"，
    证明不了"用户按下播放的时候有人会去建它"。
    """
    import music_player as mp

    win = _window(app, monkeypatch, cfg_index=-1)
    try:
        win._create_music_control_bar_if_played()
        app.processEvents()
        assert getattr(win, "music_control_bar", None) is None, "前置不成立：这时候不该有条"

        mp.notify_playback_started()
        for _ in range(3):
            app.processEvents()
        assert getattr(win, "music_control_bar", None) is not None, (
            "用户按下播放之后控制条没有出现 —— 音乐页自己没有任何播放控件，"
            "这意味着他连暂停都点不到")
    finally:
        win.deleteLater()
        app.processEvents()


def test_the_bar_takes_room_from_the_content_area_so_this_is_not_cosmetic(app, monkeypatch):
    """把「省下来的是什么」量出来，别停在"少一条栏"。

    实测 42px：完整档 750→708、紧凑档 650→608。这条判据只断言**有变化**，
    不写死 42 —— 按像素写死的断言是**一台机器的事实**（RN-196 的教训，
    公开仓 CI 上当场假红）。
    """
    win = _window(app, monkeypatch, cfg_index=-1)
    try:
        win.show()
        app.processEvents()
        before = win.content_stack.height()
        win._create_music_control_bar()
        for _ in range(3):
            app.processEvents()
        after = win.content_stack.height()
        assert after < before, (
            f"控制条建出来之后内容区没有变矮（{before} -> {after}）"
            f"—— 那么 RN-195 省下来的就不是内容区的高度，整条裁定的前提要重看")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


# --------------------------------------------------------------------------
# 三、接线：通知是不是真的挂在「开始播放」上
# --------------------------------------------------------------------------

def test_play_track_is_the_one_place_that_announces_playback():
    """用 AST 查「有没有 X」，不用 grep —— 截断会给出"没有"，
    而"没有"往往正是断言的全部内容。
    """
    src = (REPO / "music_player.py").read_text(encoding="utf-8")
    tree = next(
        (n for n in ast.walk(ast.parse(src))
         if isinstance(n, ast.FunctionDef) and n.name == "_play_track"),
        None,
    )
    assert tree is not None, "music_player.py 里找不到 _play_track"
    called = {
        node.func.id if isinstance(node.func, ast.Name) else
        (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert "notify_playback_started" in called, (
        "`_play_track` 没有通告「开始播放」。它是 play/play_current/next/previous "
        "以及自动续播的**唯一**汇合点；通知不挂在这里，就得挂到每一个入口上，"
        "而漏掉任何一个都意味着用户放着音乐却没有控制条")


_DEFERRED_ENTRY_SITES = ("gui_widget.py", "main_widget.py")


@pytest.mark.parametrize("rel", _DEFERRED_ENTRY_SITES)
def test_every_deferred_entry_point_goes_through_the_conditional_creator(rel):
    """两处延迟创建（8 秒兜底、后台 stage2）**都**必须走条件入口。

    这是本条最现实的回退形态：有人收到一份"我的控制条不见了"的反馈，
    随手把某一处改回无条件建 —— 另一处还是条件的，于是"建不建"有了两份判断，
    而结论取决于**哪个定时器先到**。⭐ 本仓的老病：同一个事实有第二份副本，
    它就不再是事实，是两个会互相打架的猜测。
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    unconditional = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if getattr(func, "attr", "") != "singleShot":
            continue
        for arg in node.args[1:]:
            name = getattr(arg, "attr", None) or getattr(arg, "id", None)
            if name == "_create_music_control_bar":
                unconditional.append(node.lineno)
    assert not unconditional, (
        f"{rel} 第 {unconditional} 行把音乐控制条**无条件**排进了定时器。"
        f"延迟创建的入口只有一个：`_create_music_control_bar_if_played`。"
        f"（`_create_music_control_bar` 本身仍是无条件的建造者 —— 首播那条"
        f"通知路径和量图工装都直接用它，那是对的。）")


def test_the_music_page_still_has_no_transport_controls_of_its_own():
    """**前提判据**：上面那条 live 路径为什么不能省，全靠这个事实。

    如果哪天音乐页长出了自己的播放/暂停键，「首次播放必须当场建条」这条
    结论要**重新裁一次**（用户届时有别的出口了）。判据在这里替我记着，
    免得那时候没人想起来这条依赖。

    ⭐ 这是批 8 那条教训的正向用法：**一个结论所依赖的事实，要有判据看着**，
    否则事实变了而结论还挂在墙上。
    """
    src = (REPO / "pages" / "music_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    transport = {"播放", "暂停", "下一首", "上一首"}
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "QPushButton":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.strip() in transport:
                    hits.append(arg.value.strip())
    assert not hits, (
        f"音乐页出现了自己的播放控件 {hits} —— RN-195「首次播放必须当场建条」"
        f"的理由是「控制条是唯一的播放控制面」，这个前提已经不成立了，回去重裁")


# --------------------------------------------------------------------------
# 四、量图工装：控制条在不在，必须是**定下来的**，不许靠 8 秒定时器碰运气
# --------------------------------------------------------------------------

_HARNESSES = (
    "scripts/layout_overflow_audit.py",
    "scripts/page_fingerprint.py",
    "scripts/ui_shot_capture.py",
)


@pytest.mark.parametrize("rel", _HARNESSES)
def test_every_measuring_harness_pins_the_music_bar(rel):
    """实测（2026-08-23，本机 28 页指纹循环）：8 秒定时器在 **8.00s** 开火，
    最后两页（preset_center / about）量的是**有控制条**的世界，前 26 页是没有的。
    离分界线只有 0.11 秒 —— 换台机器、多两页少两页，分界就挪。

    ⭐⭐ 两类工装的正确口径**不一样**，因为它们问的问题不一样：
      · 审计问「用户会不会看到溢出」⇒ 要**最坏**那一档（条**在**）；
      · 基线问「这一页跟锁的时候比变了没有」⇒ 要**可复现**那一档
        （全新配置下产品自己的决定 = 不建）。
    以前两者都靠同一个定时器碰运气，碰巧审计碰对了、基线碰错了。
    ⇒ 三支都必须显式调 `_audit_music_bar.pin()`，且跑完再 `assert_stable()`。
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "pin" in called, f"{rel} 没有显式钉住音乐控制条的档位"
    assert "assert_stable" in called, (
        f"{rel} 钉了却没有回验 —— 钉住只是「我打算量哪一档」，"
        f"回验才是「这一轮真的全程都在那一档」")


def test_the_two_harness_modes_actually_differ(app, monkeypatch):
    """反空转：`pin` 的两个档位必须真的产生不同的世界。

    ⚠ 一个"两个分支返回同一个东西"的开关，读起来像在做选择，实际什么也没选。
    """
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import _audit_music_bar as amb
    import music_player as mp
    from config import config

    monkeypatch.setattr(config, "music_current_index", -1, raising=False)
    monkeypatch.setattr(mp, "music_player", None, raising=False)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        amb.pin(win, app, amb.MODE_PRISTINE)
        assert getattr(win, "music_control_bar", None) is None
        amb.assert_stable(win)

        amb.pin(win, app, amb.MODE_WORST_CASE)
        assert getattr(win, "music_control_bar", None) is not None
        amb.assert_stable(win)
    finally:
        win.deleteLater()
        app.processEvents()


def test_a_bar_that_shows_up_mid_run_is_caught(app, monkeypatch):
    """守卫的守卫：`assert_stable` 必须真的会红。

    这正是 RN-195 描述的事故形态 —— 一轮量到一半，世界换了。
    """
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import _audit_music_bar as amb
    import music_player as mp
    from config import config

    monkeypatch.setattr(config, "music_current_index", -1, raising=False)
    monkeypatch.setattr(mp, "music_player", None, raising=False)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        amb.pin(win, app, amb.MODE_PRISTINE)
        win._create_music_control_bar()   # 模拟 8 秒定时器在量到一半时开火
        app.processEvents()
        with pytest.raises(AssertionError):
            amb.assert_stable(win)
    finally:
        win.deleteLater()
        app.processEvents()
