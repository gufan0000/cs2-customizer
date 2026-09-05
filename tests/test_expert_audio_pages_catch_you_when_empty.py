# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-520：这几页没东西可看的时候，得把人接住。

## 缺陷（外审改完复跑收敛出来的，且**逐条实测过**）

1. `audio_import_wizard` 第 2 步在扫描之前是一整块 400px 高的**纯黑框**，
   什么都不说（4/6 报「易误以为卡死或功能损坏」）。
   ⭐ **一个什么都不说的框，和一个坏掉的框长得一模一样。**
2. `audio_replay` 空状态那颗按钮把玩家送去「击杀音效」试听，
   **回来还得自己点一次刷新**（3/3）—— 而「回到这一页」本身就是「我试完了」的信号。

⚠⚠ 同一轮外审另外两条**被实测推翻**，没有进这个文件：
   · 「推进入口被塞在历史面板右下角」—— 实测偏离中线 **1px**，且是本页唯一的主按钮；
   · 「侧栏没有入口、跳走就回不来」—— 专家模式下有入口，普通模式经搜索跳入
     还会弹「已临时打开 + 固定显示」（D-17）。
   ⭐ 截图走的是普通模式（RN-134），**外审看见的不是真实用户看见的**。
   这两条留在这里做记录：判据不该照着一条没核实的抱怨去写。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

REPO = Path(__file__).resolve().parent.parent
WIZARD = REPO / "pages" / "audio_import_wizard_page.py"
REPLAY = REPO / "pages" / "audio_replay_page.py"


# ------------------------------------------- ① 扫描之前那块框要说话


@pytest.fixture
def wizard(qapp, monkeypatch):
    import pages.audio_import_wizard_page as mod
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    page = mod.AudioImportWizardPage()
    qapp.processEvents()
    yield page
    page.deleteLater()
    qapp.processEvents()


def test_the_preview_box_says_what_will_appear_there(wizard):
    assert not wizard.preview_text.toPlainText().strip(), (
        "这条判据假设扫描前预览是空的；现在它一上来就有内容了，判据失去了对象。")
    hint = wizard.preview_text.placeholderText()
    assert hint.strip(), (
        "第 2 步那个 400px 高的框在扫描前什么都不说 —— "
        "而一个什么都不说的框，和一个坏掉的框长得一模一样（RN-520）。")
    for must in ("还没有扫描结果", "只看不写"):
        assert must in hint, f"空状态提示里没有「{must}」：{hint!r}"


def test_the_empty_hint_names_the_button_by_reading_it(wizard):
    """⭐ 提示里点名的那颗按钮，名字要从按钮读 —— 不许再抄一份（RN-519）。"""
    assert wizard.scan_btn.text() in wizard.preview_text.placeholderText()

    tree = ast.parse(WIZARD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "setPlaceholderText"):
            for arg in node.args:
                for piece in ast.walk(arg):
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        assert "扫描目录" not in piece.value, (
                            "空状态提示把按钮名抄了一份 —— 改按钮名时它不会跟着动。")


# --------------------------------- ② 回到这一页 = 我试完了


def test_the_replay_page_refreshes_when_it_comes_back(qapp, monkeypatch):
    """重新显示时必须自己取一次，别让玩家再点一次刷新。"""
    import pages.audio_replay_page as mod
    from core.audio.audio_event_timeline import AudioEvent, get_audio_event_timeline

    timeline = get_audio_event_timeline()
    timeline.clear()
    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: object())
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)

    page = mod.AudioReplayPage()
    qapp.processEvents()
    try:
        assert page.table.rowCount() == 0, "起手就该是空的（阳性对照）"

        # 模拟「去别处试听了一次」——记录进来了，但本页还没动
        timeline.record(AudioEvent(timestamp=1.0, action="play", key="kill-1",
                                   channel_type="kill_voice", event_type="kill_voice"))
        assert page.table.rowCount() == 0, (
            "还没回到这一页，表就已经变了 —— 那说明有别的东西在后台刷它，"
            "这条判据量的就不是「回来时刷新」了。")

        page.hide()
        qapp.processEvents()
        page.show()          # ← 回到这一页
        qapp.processEvents()
        assert page.table.rowCount() == 1, (
            "回到这一页没有自动取最新记录 —— 玩家还得自己再点一次刷新（RN-520）。")
    finally:
        page.deleteLater()
        timeline.clear()
        qapp.processEvents()


def test_the_replay_page_does_not_poll_on_a_timer():
    """⛔ 不许用定时器解决这件事。

    定时器会让这一页的内容取决于「快照拍在第几秒」——
    那正是 RN-146 刚花一整批修掉的那类不确定性。
    """
    src = REPLAY.read_text(encoding="utf-8")
    assert "QTimer" not in src, (
        "回放页引入了 QTimer —— 内容会取决于快照拍在第几秒，"
        "而那正是 RN-146 刚花一整批修掉的那类不确定性。")
    # 空转守卫：源码读得到、且里面真有「刷新」这件事，这条才算量到了东西
    assert "_refresh_events" in src, "读到的不是回放页的源码？这条判据没了对象"
