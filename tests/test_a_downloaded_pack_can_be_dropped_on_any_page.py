# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 123：下好的包拖到哪一页都能装上 —— 「放进资源目录 → 刷新」那两步砍掉。

外审两轮 6/6 + 6/6（特殊音效页）：「顶上去社区拿、底下放目录再刷新，下完不知道怎么生效」。
RN-193 那条注释早就判过：三步被劈在两个区域里，**换个说法治不好**。⇒ 改结构：

1. 空库引导的各页直接收整包（zip / rar / 7z / 文件夹），转交「导入资源」去问、去装、能撤销；
2. 「拖到这一页」写进卡里那句话，紧挨着「去社区拿」；底栏只剩「手动放也行」；
3. 装完切回原来那一页，风格列表当场重扫（特殊音效 / 枪声 / 闪光三页进页本来**不**重扫，
   音效页有 10 秒冷却 ⇒ 「导入成功、回来下拉里没有」）。

分母不是手写的：凡是用了空库引导（`empty_library_message`）的页、以及音效页基类的子类，都得收整包。
"""
from __future__ import annotations

import inspect
import os
import zipfile

import pytest
from PySide6.QtCore import QEvent, QMimeData, QUrl

from core import resource_generation


class _FakeEvent:
    def __init__(self, paths, etype=QEvent.Type.Drop):
        self._etype = etype
        self._mime = QMimeData()
        self._mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        self.accepted = False

    def type(self):
        return self._etype

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True


def _send(page, event) -> bool:
    """像 Qt 那样把事件交给这一页上的过滤器（后装的先问，谁认了谁拦下）。"""
    for filt in reversed(getattr(page, "_file_drop_filters", []) or []):
        if filt.eventFilter(page, event):
            return True
    return False


def _pack(tmp_path):
    path = tmp_path / "社区下的包.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("round_sounds/win/清脆/1.mp3", b"ID3____")
    return path


# ──────────────────────────── 纯逻辑：资源代数

def test_a_page_hears_about_an_import_once():
    class Page:
        pass

    page = Page()
    assert resource_generation.take_news(page) is False, "第一次问 = 刚建出来刚扫过，不算错过"
    resource_generation.bump()
    assert resource_generation.take_news(page) is True
    assert resource_generation.take_news(page) is False, "同一次导入只该让它重扫一次"


# ──────────────────────────── 真主窗口

@pytest.fixture
def main_window(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    import _audit_neutralize as neutral
    from config import config

    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    neutral.apply(config)
    config.compact_mode = False
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    # 转交之后导入页会开始识别 —— 那一段有它自己的判据；这里只量「有没有交到它手上」
    import pages.audio_import_wizard_page as importer

    monkeypatch.setattr(importer.AudioImportWizardPage, "_scan_source", lambda self: None)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)          # §3：不许弹真窗口
    win.show()
    win.resize(1280, 800)
    qapp.processEvents()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _pages_with_the_empty_library_guide(win):
    """分母：用了空库引导的页 + 音效页基类的子类。从真窗口里数，不手写清单。"""
    from pages.sound_page_base import SoundPageBase

    found = {}
    for page_id in list(getattr(win, "_page_names", {}) or {}):
        if page_id == "audio_import_wizard":
            continue
        win.ensure_page_loaded(page_id)
        page = win.pages.get(page_id)
        if page is None:
            continue
        import sys

        module_file = getattr(sys.modules.get(type(page).__module__), "__file__", "") or ""
        try:
            source = open(module_file, encoding="utf-8").read() if module_file.endswith(".py") else ""
        except OSError:
            source = ""
        if isinstance(page, SoundPageBase) or "empty_library_message(" in source:
            found[page_id] = page
    return found


def test_every_page_that_says_go_get_a_pack_also_takes_the_pack(main_window, tmp_path):
    pages = _pages_with_the_empty_library_guide(main_window)
    assert len(pages) >= 8, sorted(pages)          # 四个音效页 + 被击杀 + 枪声 + 特殊音效 + 闪光
    pack = _pack(tmp_path)
    missing = [pid for pid, page in pages.items()
               if not _send(page, _FakeEvent([pack], QEvent.Type.DragEnter))]
    assert not missing, f"这些页叫人去社区拿包，拖进来却是禁止图标：{missing}"


def test_a_pack_dropped_on_the_special_sound_page_lands_in_the_importer(main_window, tmp_path):
    main_window.ensure_page_loaded("special_sound")
    page = main_window.pages["special_sound"]
    pack = _pack(tmp_path)
    event = _FakeEvent([pack])
    assert _send(page, event) and event.accepted
    importer = main_window.pages.get("audio_import_wizard")
    assert importer is not None and os.path.normpath(importer.source_edit.text()) == os.path.normpath(str(pack)), "没交到导入页手上"
    assert main_window.content_stack.currentWidget() is importer, "交过去了但人还停在原页"


def test_a_single_audio_file_still_makes_a_new_style_here(main_window, tmp_path, monkeypatch):
    """整包走导入；**单个音频**仍是这一页自己的「新建风格」—— 两个过滤器并存，不许互相抢。"""
    main_window.ensure_page_loaded("kill_sound")
    page = main_window.pages["kill_sound"]
    opened = []
    monkeypatch.setattr(type(page), "_open_style_creator", lambda self, initial_files=None: opened.append(initial_files))
    mp3 = tmp_path / "1.mp3"
    mp3.write_bytes(b"ID3")
    assert _send(page, _FakeEvent([mp3]))
    assert opened and [os.path.normpath(p) for p in opened[0]] == [os.path.normpath(str(mp3))]
    assert main_window.pages.get("audio_import_wizard") is None or \
        main_window.content_stack.currentWidget() is not main_window.pages["audio_import_wizard"]


@pytest.mark.parametrize("page_id,refresher", [
    ("special_sound", "_refresh_style_catalog"),
    ("gun_sound", "_refresh_style_catalog"),
    ("kill_sound", "_refresh_style_catalog"),      # 有 10 秒冷却的那一类
])
def test_coming_back_after_an_import_rescans_the_page(main_window, monkeypatch, page_id, refresher):
    main_window.ensure_page_loaded(page_id)
    page = main_window.pages[page_id]
    calls = []
    monkeypatch.setattr(page, refresher, lambda *a, **k: calls.append(1))
    page._last_auto_refresh = 10 ** 9          # 冷却里：不导入就不该重扫
    from PySide6.QtGui import QShowEvent

    page.showEvent(QShowEvent())
    before = len(calls)
    resource_generation.bump()                  # 导入资源页装完一个包
    page.showEvent(QShowEvent())
    assert len(calls) == before + 1, "导入成功、回来下拉里没有"


def test_the_empty_state_says_drop_it_here_next_to_the_button(qapp):
    from widgets.community_library import EmptyLibraryCallout, empty_library_message

    callout = EmptyLibraryCallout()
    callout.show_for(what="风格", cta_text="去社区拿一套", callback=lambda: None)
    assert "拖到这一页" in callout.title.text(), "「拿到之后怎么办」又回到了页尾"
    assert "拖到这一页" in empty_library_message("风格")
    source = inspect.getsource(__import__("widgets.community_library", fromlist=["_"]).guide_empty_library)
    assert "手动放也行" in source and "下载好的包放进资源目录" not in source


def test_a_wrapper_named_after_a_category_is_content_not_a_shell(tmp_path):
    """端到端逮到：`round_sounds/win/清脆/1.wav` 被当外壳剥成 `win/清脆/1.wav`，
    问用户时第一猜成了「枪声替换」。名字就是类别目录的那层不剥；包名那层照剥。"""
    from core.resource_import_source import open_source

    def paths_of(entries):
        z = tmp_path / f"p{len(entries)}_{entries[0].split('/')[0]}.zip"
        with zipfile.ZipFile(z, "w") as archive:
            for e in entries:
                archive.writestr(e, b"RIFF____WAVE")
        source = open_source(str(z))
        try:
            return list(source.paths), source.stripped_root
        finally:
            source.cleanup()

    assert paths_of(["round_sounds/win/清脆/1.wav"]) == (["round_sounds/win/清脆/1.wav"], "")
    assert paths_of(["我的回合包/win/1.wav"]) == (["win/1.wav"], "我的回合包")


def test_the_importer_announces_every_write():
    import pages.audio_import_wizard_page as importer

    run = inspect.getsource(importer.AudioImportWizardPage._run_import)
    undo = inspect.getsource(importer.AudioImportWizardPage._undo_last_import)
    assert "resource_generation.bump()" in run and "resource_generation.bump()" in undo, \
        "导入 / 撤销之后不报 ⇒ 切回原来那一页，下拉里看不见刚装的包"
