# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-7：素材工坊——被搬走的那一半，一个功能都不能少。

拆两层最大的风险不是"简单层不够简单"，而是**搬家途中掉东西**：某个功能在
设置页上删掉了，工坊里却没接上，而它平时没人点，掉了也不会有人当场发现。

所以这份文件的重心是「**KI-6 有的，工坊里还得有**」：
逐等级的节奏（多帧存帧率、单帧存定格时长）、删除与撤销、导出一格、
导出整包、打开素材目录、每一格自己就是拖拽目标、高级导入入口。

⚠ 不许 `exec()`：`QDialog.exec` / `QMenu.exec` 都是模态的，测试进程里没人去
点，表现是整个 pytest **卡死而不是失败**。工坊的方法都设计成可以直接调。
"""
from __future__ import annotations

import os

import pytest

import dialogs.kill_icon_workshop as workshop_module
from config import config
from core.kill_icon_library import LEVELS
from _denominator import must_scan


class _StubPlayer:
    def __init__(self, frames=30, fps=30, hold=0.0):
        self._frames = frames
        self._fps = fps
        self._hold = hold
        self.fps_updates = []
        self.hold_updates = []
        self.play_calls = []
        self.loaded_styles = []

    def load_style(self, style):
        self.loaded_styles.append(style)
        return True

    def get_style_fps(self, _style, _kills):
        return self._fps

    def get_style_hold(self, _style, _kills):
        return self._hold

    def get_style_frame_count(self, _style, _kills):
        return self._frames

    def update_fps_for_style(self, style, kills, fps):
        self.fps_updates.append((style, kills, fps))
        return True

    def update_hold_for_style(self, style, kills, hold):
        self.hold_updates.append((style, kills, hold))
        return True

    def play_icon(self, kills, fps=None):
        self.play_calls.append((kills, fps))


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """拦掉文件对话框。不拦是**卡死不是失败**。"""
    monkeypatch.setattr(workshop_module.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)
    monkeypatch.setattr(workshop_module.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)


def _workshop(monkeypatch, player=None, style="classic"):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(workshop_module, "load_level_animation",
                        lambda *a, **k: None, raising=False)
    return workshop_module.KillIconWorkshop(style, player=player or _StubPlayer())


@pytest.fixture
def workshop(qapp, monkeypatch):
    dialog = _workshop(monkeypatch)
    yield dialog
    dialog.level_grid.stop_previews()
    dialog.deleteLater()


def _sync_import(workshop):
    """让后台导入在当前线程里跑完。

    导入跑在工作线程上（600 帧 1024px 的素材做完整串是秒级的，跑在 UI 线程上
    就是点完"导入"界面卡死）。判据不该 sleep 等线程——把 `start` 换成同步执行，
    信号照常走。
    """
    task = workshop._import_task

    def _sync_start(fn, label="导入"):
        try:
            result = fn(lambda *_a: None, lambda: False)
        except Exception as exc:                      # noqa: BLE001 - 转成信号
            from core.kill_icon_import import KillIconImportCancelled

            if isinstance(exc, KillIconImportCancelled):
                task.cancelled.emit()
            else:
                task.failed.emit(str(exc))
            return True
        task.finished.emit(result)
        return True

    task.start = _sync_start
    return task


# ============================================ 1. 搬家清单：KI-6 有的都还在


@pytest.mark.parametrize("name", [
    "level_grid",          # 五格清单板
    "save_fps_btn",        # 保存播放设置
    "advanced_btn",        # 高级导入 / 批量
    "export_pack_btn",     # 导出图标包
    "open_dir_btn",        # 打开素材文件夹
    "notice_frame",        # 页内提示条
    "undo_btn",            # 撤销
    "progress_frame",      # 后台导入进度
    "cancel_btn",          # 取消导入
])
def test_everything_that_moved_here_is_actually_here(workshop, name):
    """搬家清单。少一个就是"这个功能悄悄没了"，而它平时没人点。"""
    assert hasattr(workshop, name), f"从设置页搬过来的 {name} 没接上"


def test_all_five_levels_are_present(workshop):
    assert sorted(workshop.level_grid.cells) == list(LEVELS)


# ============================================ 2. 逐等级的节奏（从 KI-6 搬来）


def test_slider_is_seconds_and_lands_as_frame_rate(qapp, monkeypatch):
    """滑条量秒数，落盘仍是帧率——素材 JSON 的格式一个字节没变。"""
    shop = _workshop(monkeypatch, player=_StubPlayer(frames=30))
    shop.level_grid.cells[1].duration_slider.setValue(20)       # 2.0 秒
    shop._save_timing()
    assert ("classic", 1, 15) in shop.player.fps_updates        # 30 帧 / 2 秒
    shop.deleteLater()


def test_label_shows_the_rounded_back_duration_not_the_raw_slider_value(qapp, monkeypatch):
    """帧率必须是整数，所以时长会被取整"吸"到附近的值上。

    显示用户拖的原值会让他量出来对不上；标签上是**换算回来**的真实时长。
    """
    from kill_icon_overlay import duration_for_fps, fps_for_duration

    shop = _workshop(monkeypatch, player=_StubPlayer(frames=30))
    shop.level_grid.cells[1].duration_slider.setValue(17)       # 用户拖到 1.7 秒
    text = shop.level_grid.cells[1].timing_label.text()

    fps = fps_for_duration(30, 1.7)
    assert f"{duration_for_fps(30, fps):.2f} 秒" in text
    assert f"{fps} FPS" in text
    shop.deleteLater()


def test_levels_without_assets_are_disabled_not_silently_saved(qapp, monkeypatch):
    """没素材的等级把滑条禁掉，而不是让用户拖了个寂寞。"""
    shop = _workshop(monkeypatch, player=_StubPlayer(frames=0))
    assert shop.level_grid.cells[3].duration_slider.isEnabled() is False
    assert shop.level_grid.cells[3].timing_label.text() == "无素材"

    shop._save_timing()
    assert shop.player.fps_updates == [], "没有素材的等级不该往配置里写东西"
    shop.deleteLater()


def test_existing_frame_rate_is_restored_as_a_duration(qapp, monkeypatch):
    """打开工坊时读的是风格里存的帧率，回填到滑条上要换算成秒。"""
    shop = _workshop(monkeypatch, player=_StubPlayer(frames=60, fps=30))  # = 2 秒
    assert shop.level_grid.cells[1].duration_slider.value() == 20
    shop.deleteLater()


def test_a_static_asset_restores_its_hold_not_a_frame_rate(qapp, monkeypatch):
    """单帧素材回填的是**定格时长**。

    1 帧 @30fps 只有 0.033 秒，肉眼看不见——`hold_seconds` 就是为这个加的，
    而它是运行时格式唯一的扩展，回填走错了这条路用户会以为滑条坏了。
    """
    shop = _workshop(monkeypatch, player=_StubPlayer(frames=1, fps=30, hold=2.4))
    assert shop.level_grid.cells[1].duration_slider.value() == 24
    assert "定格" in shop.level_grid.cells[1].timing_label.text()
    shop.deleteLater()


# ============================================ 3. 删除、撤销、导出


def test_deleting_a_level_offers_an_undo(workshop, monkeypatch):
    """删错了的代价是"用户手上那份原素材可能已经没了"。"""
    monkeypatch.setattr(workshop_module, "delete_level", lambda *a: "TOKEN")
    monkeypatch.setattr(workshop, "_reload_player", lambda: None)
    workshop._delete_level(3, "")
    assert workshop.undo_btn.isHidden() is False
    assert workshop._undo_token == "TOKEN"


def test_deleting_marks_the_workshop_dirty_so_the_page_reloads(workshop, monkeypatch):
    """在工坊里删了东西，关窗后设置页必须重扫。

    不然用户回到页面看到的还是"素材齐全"，而那一格已经空了。
    """
    monkeypatch.setattr(workshop_module, "delete_level", lambda *a: "TOKEN")
    assert workshop.changed is False
    workshop._delete_level(3, "")
    assert workshop.changed is True, "改过素材却没告诉设置页"


def test_exporting_a_pack_runs_in_the_background(workshop, monkeypatch):
    """逐帧目录要先转成图集，实测默认风格（519 帧）要 4 秒——不能占 UI 线程。"""
    import core.kill_icon_pack as pack_module

    monkeypatch.setattr(workshop_module.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("C:/tmp/classic.zip", "")))
    seen = {}

    def _fake_export(style, path, progress=None):
        seen.update(style=style, path=path, has_progress=progress is not None)
        return {"style": style, "path": path, "levels": [1, 2], "size": 4096}

    monkeypatch.setattr(pack_module, "export_pack", _fake_export)
    _sync_import(workshop)

    workshop._export_pack()
    assert seen["style"] == "classic"
    assert seen["has_progress"] is True, "打包没有报进度，长任务会显得像卡死"
    assert "已导出" in workshop.notice_label.text()


def test_the_folder_path_is_computed_before_it_is_handed_to_the_shell(workshop, monkeypatch):
    """「打开素材文件夹」真调 `os.startfile` 会在用户屏幕上弹窗，判据不能跑。

    但会出错的地方全在**算这个路径**这一段，那一段是可以验的：
    风格没选、目录不存在，都必须返回空串而不是把一个假路径丢给系统。
    """
    assert workshop.style_folder() == "", "目录不存在时不该交给系统去开"

    monkeypatch.setattr(workshop_module.ResourceManager, "get_kill_icon_style_dir",
                        staticmethod(lambda style: os.path.dirname(__file__)))
    assert workshop.style_folder() == os.path.dirname(__file__)

    workshop.style_name = ""
    assert workshop.style_folder() == "", "没选风格时不该交给系统去开"


def test_opening_a_missing_folder_says_so_instead_of_doing_nothing(workshop):
    workshop._open_style_folder()
    assert workshop.notice_frame.isHidden() is False
    assert "没有素材目录" in workshop.notice_label.text()


# ============================================ 4. 导入


def test_dropping_onto_a_level_cell_targets_that_level(workshop, monkeypatch):
    """每一格自己就是拖拽目标。

    用户已经用"拖到哪一格"表达了意图，不该再弹小窗问一遍。
    """
    import core.kill_icon_import as import_module

    recorded = {}

    def _fake_convert(source, style, kills, **kwargs):
        recorded.update(style=style, kills=kills, variant=kwargs.get("variant", ""))
        return {"frames": 8, "fps": 20, "kills": kills, "variant": "", "warnings": [],
                "style": style, "hold_seconds": 0.0}

    monkeypatch.setattr(import_module, "convert_to_style", _fake_convert)
    monkeypatch.setattr(workshop, "_reload_player", lambda: None)
    asked = []
    monkeypatch.setattr(workshop, "_ask_target", lambda path: asked.append(path))
    _sync_import(workshop)

    workshop.level_grid.cells[5].files_dropped.emit(5, ["C:/tmp/ace.webp"])

    assert recorded["kills"] == 5
    assert asked == [], "拖到某一格上还去问「用在几杀」是多余的"


def test_dropping_on_the_window_asks_which_level(workshop, monkeypatch):
    """拖到窗口空白处就不知道目标了，这时候才问。"""
    import core.kill_icon_import as import_module

    recorded = {}
    monkeypatch.setattr(import_module, "convert_to_style",
                        lambda source, style, kills, **kw: recorded.update(kills=kills) or
                        {"frames": 3, "fps": 10, "kills": kills, "variant": "",
                         "warnings": [], "style": style, "hold_seconds": 0.0})
    monkeypatch.setattr(workshop, "_reload_player", lambda: None)
    monkeypatch.setattr(workshop, "_ask_target", lambda path: (2, "hs"))
    _sync_import(workshop)

    workshop._on_files_dropped(["C:/tmp/whatever.webp"])
    assert recorded["kills"] == 2


def test_a_zip_is_refused_here_with_a_way_out(workshop):
    """zip 是"一整套风格"，在工坊里按单个等级处理会把它拆错。

    但**不能默默不动**——要告诉用户去哪儿拖。
    """
    assert workshop.import_paths(["C:/tmp/pack.zip"], 3) is False
    assert "设置页" in workshop.notice_label.text()


def test_import_failures_are_reported_not_swallowed(workshop, monkeypatch):
    import core.kill_icon_import as import_module

    def _boom(*_args, **_kwargs):
        raise import_module.KillIconImportError("这个文件读不出来")

    monkeypatch.setattr(import_module, "convert_to_style", _boom)
    _sync_import(workshop)

    workshop.import_paths(["C:/tmp/bad.gif"], 1)
    assert workshop.notice_frame.isHidden() is False
    assert "失败" in workshop.notice_label.text()
    assert "读不出来" in workshop.notice_label.text()


def test_cancelling_an_import_changes_nothing(workshop, monkeypatch):
    import core.kill_icon_import as import_module

    def _cancel(*_args, **_kwargs):
        raise import_module.KillIconImportCancelled()

    monkeypatch.setattr(import_module, "convert_to_style", _cancel)
    _sync_import(workshop)

    workshop.import_paths(["C:/tmp/x.gif"], 1)
    assert "已取消" in workshop.notice_label.text()


# ============================================ 5. 试播


def test_testing_a_level_uses_the_slider_value_not_the_stored_one(workshop):
    """在工坊里调完节奏、还没保存就想听个响——试播必须用**当前滑条**的值。

    用存盘值的话，用户会以为"拖了没用"。
    """
    from kill_icon_overlay import fps_for_duration

    workshop.level_grid.cells[2].duration_slider.setValue(30)   # 3.0 秒
    workshop.test_level(2)
    assert workshop.player.play_calls[-1] == (2, fps_for_duration(30, 3.0))


# ============================================ 6. 列数与排版


def test_the_grid_columns_follow_the_viewport_not_the_window(workshop):
    """列数按**滚动可视区**算，不是按窗口宽。

    两者差一条滚动条的宽度；按窗口宽算会让板子比可视区宽，横向溢出。
    KI-6 在设置页上就是这么让排版审计亮红的（352px）。
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent /
              "dialogs" / "kill_icon_workshop.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_update_columns")
    names = {getattr(node, "attr", "") for node in ast.walk(fn)}
    assert "viewport" in names, "列数没有按滚动可视区算"


def test_the_dialog_fits_its_own_minimum_size(workshop):
    """工坊被拖到最小尺寸时不许横向溢出。

    排版审计只走 `pages/` 下的页面，**对话框它一个都不量**——这块没人看着，
    所以这条判据得自己写。五格清单板的最小宽是"列数 × 每格硬下限"，
    列数又按可视区算，两者错配就会撑破窗口（KI-6 在设置页上溢出过 352px）。
    """
    minimum = workshop.minimumSize()
    workshop.resize(minimum)
    workshop._update_layout()
    needed = workshop.layout().minimumSize().width()
    assert needed <= minimum.width(), (
        f"工坊内容最小宽 {needed}px，超过窗口最小宽 {minimum.width()}px"
    )


def test_no_button_text_gets_elided(workshop, qapp):
    """底栏按钮的文案不许被打省略号。

    **排版审计不量对话框**（它只走 `pages/`），所以这条得自己写；口径照抄
    `scripts/layout_overflow_audit._elided_buttons`：向 style 要文字实际可用区，
    再跟字形宽度比。不能用 `sizeHint().width() > width()` —— 那条会被 QSS 的
    padding 带偏，实测在别处误报过 9 个页面。
    """
    from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

    workshop.resize(880, 640)
    workshop.show()
    qapp.processEvents()
    try:
        elided = []
        for btn in must_scan(workshop.findChildren(QPushButton),
                             "素材工坊上的按钮", least=3):
            text = btn.text().strip()
            if not btn.isVisible() or not text or btn.width() <= 0:
                continue
            opt = QStyleOptionButton()
            btn.initStyleOption(opt)
            avail = btn.style().subElementRect(
                QStyle.SE_PushButtonContents, opt, btn).width()
            need = btn.fontMetrics().horizontalAdvance(text)
            if avail > 0 and need > avail + 1:
                elided.append((text, avail, need))
        assert not elided, f"这些按钮的文案放不下：{elided}"
    finally:
        workshop.hide()


def test_closing_stops_the_previews(workshop):
    """五格预览各自挂着 60Hz 定时器，关窗不停就是白烧 CPU。"""
    stopped = []
    for cell in workshop.level_grid.cells.values():
        cell.preview.stop = lambda c=cell: stopped.append(c.kills)
    workshop.done(0)
    assert sorted(stopped) == list(LEVELS)
