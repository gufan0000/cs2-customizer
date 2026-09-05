# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-3：击杀图标设置页。

这一轮改的三件事各自对应一个"用户实际会卡住的地方"：

1. **总开关不在这一页**。原来开关在主界面的功能列表里，用户在这页把风格、
   位置、帧率调了半天，其实总开关是关的，页面一个字都不提。
2. **调节奏靠 FPS**。用户想要的是"这个图标在屏幕上待多久"，而不是每秒几帧。
3. **看效果只能真弹一次全屏叠加层**。换个风格、动一下位置都要弹一次去看，
   反馈链长到没法用。

判据里最要紧的是最后一条（示意图与真实落点逐像素对账）：示意图这种东西
一旦和实际实现分了家，是**没有任何症状**的——它照样画得很好看，只是画错了。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

import pages.kill_icon_page as page_module
from config import config
from kill_icon_overlay import (
    KillIconAnimation,
    compute_overlay_geometry,
    compute_scaled_size,
)
from widgets.kill_icon_preview import REFERENCE_SCREEN, KillIconPositionMap
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent


class _StubPlayer:
    def __init__(self, frames=30, fps=30):
        self._frames = frames
        self._fps = fps
        self.loaded_styles = []
        self.fps_updates = []
        self.play_calls = []
        self.enabled = []
        self.position_updates = []
        self.scale_updates = []

    def load_style(self, style):
        self.loaded_styles.append(style)
        return True

    def get_style_fps(self, _style, _kills):
        return self._fps

    def get_style_frame_count(self, _style, _kills):
        return self._frames

    def update_fps_for_style(self, style, kills, fps):
        self.fps_updates.append((style, kills, fps))
        return True

    def play_icon(self, kills, fps=None):
        self.play_calls.append((kills, fps))

    def enable_kill_icons(self):
        self.enabled.append(True)

    def disable_kill_icons(self):
        self.enabled.append(False)

    def update_position_offset(self, x, y):
        self.position_updates.append((x, y))

    def update_scale(self, scale):
        self.scale_updates.append(scale)

    def preview_position_and_scale(self, kills, seconds):
        self.play_calls.append((kills, seconds))


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """拦掉所有 QMessageBox。

    ⚠ 不是"图省事"：`_save_fps_settings` 结束时会弹一个模态框，测试进程里
    没人去点它，用例会**永久挂住**（不是失败，是卡死，整个 pytest 停在那儿）。
    而且模态框是真的会画到用户屏幕上的——测试不该打扰前台。

    ⚠ **钩子挂在 Qt 类本身，不挂在"页面模块里那个名字"上**（2026-08-20）：
    原来写的是 `page_module.QMessageBox`，于是这道防线的前提变成了
    「页面必须 import 这个名字」。删掉页里最后一处 QMessageBox 用法（那两个
    全仓零调用的老接口）之后，`ruff` 让我顺手摘掉了 import —— 16 个用例当场
    `AttributeError`。**防线挂在一个可以被无关改动拿掉的东西上。**
    ⇒ 拦某一类行为，就挂在那类行为的**出口**上，别挂在某个调用者的引用上。
    """
    from PySide6.QtWidgets import QMessageBox

    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, **k: 0), raising=False)


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(page_module.ResourceManager, "list_kill_icon_styles",
                        lambda: ["classic"])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_icon_style", "classic", raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_x", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_y", 0, raising=False)
    monkeypatch.setattr(config, "kill_icon_scale", 1.0, raising=False)
    # 页面建起来时会去磁盘找素材做预览。这里按到"没素材"上，
    # 需要素材的用例自己 monkeypatch。
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)

    widget = page_module.KillIconPage()
    yield widget
    widget.deleteLater()


# ==================================================== 1. 总开关进页面


def test_enable_switch_lives_on_the_page(page, monkeypatch):
    """开关必须能在这一页开——原来它只在主界面的功能列表里。

    ⚠ **2026-08-21（RN-155）换了形态**：它原本是 `enabled_check`，一个
    普通 `QCheckBox`，夹在「入场淡入」「爆头用专属图标」两个**子选项**中间。
    外审 5/6 票「导入素材后极易因没开开关而在局内失效」⇒ 提到状态卡上，
    与它显示的那条状态并排，用的是和首页那 17 颗**同一个** `ToggleSwitch`。

    ⭐ 这条判据守的东西没变（"这一页要能开"），只是**它现在守的是位置和分量**：
    单页夹具起不出主窗口，而就地开关**故意**要经主窗口那条唯一链路
    （副作用全挂在那儿）—— 所以"拨了会怎样"挪到
    `tests/test_master_switch_row.py` 去判，那儿有真的主窗口。
    ⚠ 别为了让这条判据能跑就给组件加一条"没有主窗口就自己写 config"的退路：
    那正是这次要消灭的第二条链路。
    """
    row = getattr(page, "master_switch_row", None)
    assert row is not None, "击杀图标页没有总开关行 —— 又只能去首页开了"
    assert row.config_key == "kill_icon_enabled", (
        f"总开关行拨的是 {row.config_key!r}，不是击杀图标的总开关")
    assert page.status_card.isAncestorOf(row), (
        "总开关不在状态卡里 —— 状态在一处、动作在另一处，等于没修")


def test_status_strip_says_when_the_master_switch_is_off(page):
    """关着的时候状态条要明说。这一页最容易发生的事就是"调了半天没反应"。"""
    config.kill_icon_enabled = False
    page._sync_status_strip()
    assert "未开启" in page.status_card.toolTip()


# ==================================================== 2. 时长而不是帧率
#
# KI-7 把"每个等级待多久"整块搬进了素材工坊——那是做素材的人才关心的东西，
# 而这一页要服务的是"下载一套、拖进去、开着"的人。下面四条判据跟着搬到了
# `tests/test_kill_icon_workshop_ki7.py`，形状没变，只是宿主换了。
#
# 留在这里的是**这一页真正的反面**：它不许再长出这些控件来。


def test_the_page_does_not_grow_the_editor_back(page):
    """设置页上不许再出现逐等级的编辑控件。

    KI-6 那一版把清单板摆在页面正中，于是只想换套图标的人一进来就要面对
    30 多个可操作控件。这条判据是那次教训的棘轮：想加"顺手也能在这儿调一下
    节奏"的时候，它会先红。要加请加到工坊里去。
    """
    for gone in ("level_grid", "fps_sliders", "fps_labels", "save_fps_btn",
                 "_save_fps_settings"):
        assert not hasattr(page, gone), (
            f"设置页上又出现了 {gone}：逐等级的编辑属于素材工坊"
            f"（dialogs/kill_icon_workshop.py），不属于这一页"
        )


def test_the_page_keeps_the_controls_a_normal_user_needs(page):
    """反过来也要钉住：该留的一个都不能被顺手搬走。

    只验"控件在不在"是不够的——单验存在的判据挡不住"控件还在但没接线"。
    接线由本文件里各自的行为判据管（开关、滑条、试播、拖拽）。
    """
    # ⚠ `enabled_check` 于 2026-08-21（RN-155）换成了状态卡上的
    # `master_switch_row` —— **是搬家不是删除**，所以这里换名字继续钉。
    for kept in ("master_switch_row", "fade_check", "headshot_check",
                 "test_btn", "adjust_toggle_btn", "style_strip",
                 "x_slider", "y_slider", "scale_slider", "position_map"):
        assert hasattr(page, kept), f"设置页丢了 {kept}"
    assert not hasattr(page, "enabled_check"), (
        "「开启击杀图标」那个旧复选框又回来了 —— 它和总开关行是同一个功能的"
        "两个开关（RN-107 族）")


# ==================================================== 3. 页内预览


def test_preview_uses_the_same_loader_as_the_overlay(page, monkeypatch):
    """预览喂进去的素材必须来自**运行时那个装载器**。

    页面自己另写一段"读图片"的代码是这类功能最常见的分家方式：预览看着好好的，
    真打起来却是另一套（或者反过来）。
    """
    animation = KillIconAnimation(
        frames=(QImage(10, 8, QImage.Format_ARGB32),), fps=20,
        frame_width=10, frame_height=8,
    )
    calls = []

    def _fake_loader(style, level, *args, **kwargs):
        calls.append((style, level))
        return animation

    monkeypatch.setattr(page_module, "load_level_animation", _fake_loader)
    monkeypatch.setattr(page, "_ready_levels", lambda style=None: [3])
    page._refresh_preview()

    assert calls[-1] == ("classic", 3)
    assert page.preview_widget.has_frames is True


def test_preview_reports_missing_assets_instead_of_going_blank(page, monkeypatch):
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)
    page._refresh_preview()
    assert page.preview_widget.has_frames is False


def test_page_does_not_reimplement_drawing(page):
    """页面里不许出现第二套绘制代码。

    准心那边的教训：预览是另一套独立绘制代码，结果十字预览大了一倍、
    点准心随粗细漂移，两套几何各画各的，只有肉眼能发现。
    """
    tree = ast.parse((REPO / "pages" / "kill_icon_page.py").read_text(encoding="utf-8"))
    # ⭐ 分母是这一页的调用点；页面被搬空之后「没有第二套绘制」自动成立。
    must_scan([n for n in ast.walk(tree) if isinstance(n, ast.Call)],
              "pages/kill_icon_page.py 里的函数调用", least=20)
    painters = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "QPainter"
    ]
    assert not painters, "设置页又开始自己画了；几何和绘制只能有一份"


# ==================================================== 4. 位置示意图对账


def _render(widget, width=320, height=180):
    """把控件画进一张离屏图。

    ⚠ 用 `render(image)` 这个重载，别自己开 QPainter 再 `render(painter)`：
    后者要求同时给 targetOffset，少给一个参数会抛 TypeError，而此时那支
    QPainter 还挂在 QImage 上没 `end()`——**表现不是用例失败，是整个 pytest
    进程卡死在退出阶段**（这里真踩过一次，排查花的时间比写这条判据还长）。
    """
    widget.resize(width, height)
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    return image


def _highlight_bbox(image):
    """找出示意图里那块高亮矩形（蓝色系）的包围盒。"""
    left = top = 10 ** 6
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > 0 and color.blue() > color.red() + 30 and color.blue() > 90:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    return None if right < 0 else (left, top, right, bottom)


@pytest.mark.parametrize("offset", [(0, 0), (120, -80), (-150, 60)])
def test_position_map_matches_the_real_overlay_geometry(qapp, offset):
    """示意图上的落点必须与叠加层真正会用的落点一致。

    这条是逐像素对账，不是"看它有没有调那个函数"：示意图画错了是**没有症状**的
    ——它照样画得很好看，只是画的位置不对，而用户会照着它调位置。

    回退验证：把 `KillIconPositionMap` 里的落点改成"按比例自己估一个"，
    这三组参数至少有两组会当场变红。
    """
    widget = KillIconPositionMap()
    widget.set_target(offset[0], offset[1], 1.0, (350, 250))
    image = _render(widget)

    bbox = _highlight_bbox(image)
    assert bbox is not None, "示意图上没画出图标矩形"

    screen_w, screen_h = REFERENCE_SCREEN
    icon_w, icon_h = compute_scaled_size(350, 250, 350, 1.0)
    x, y, w, h = compute_overlay_geometry((0, 0, screen_w, screen_h), 1.0,
                                          icon_w, icon_h, *offset)

    # 把期望落点换算到控件坐标系里，比中心点（比边界更稳，不受描边影响）
    area = widget.rect().adjusted(4, 4, -5, -5)
    ratio = min(area.width() / screen_w, area.height() / screen_h)
    map_x = area.x() + (area.width() - screen_w * ratio) / 2
    map_y = area.y() + (area.height() - screen_h * ratio) / 2

    expected_cx = map_x + (x + w / 2) * ratio
    expected_cy = map_y + (y + h / 2) * ratio
    actual_cx = (bbox[0] + bbox[2]) / 2
    actual_cy = (bbox[1] + bbox[3]) / 2

    assert abs(actual_cx - expected_cx) <= 2, f"水平落点对不上: {actual_cx} vs {expected_cx}"
    assert abs(actual_cy - expected_cy) <= 2, f"垂直落点对不上: {actual_cy} vs {expected_cy}"
    widget.deleteLater()


def test_position_map_follows_the_sliders(page):
    """拖滑条时示意图要跟着动，否则它就是一张装饰画。"""
    page.x_slider.setValue(40)
    page.y_slider.setValue(-30)
    assert page.position_map._offset == (40, -30)

    page.scale_slider.setValue(150)
    assert page.position_map._scale == pytest.approx(1.5)


# ==================================================== 5. 拖拽导入


def _run_import_synchronously(page, monkeypatch):
    """让后台导入在当前线程里跑完。

    KI-5 把导入挪到了工作线程（600 帧 1024px 的素材做完整串是秒级的，
    跑在 UI 线程上就是点完"导入"界面卡死）。判据不该去 sleep 等线程——
    把 `start` 换成同步执行，信号照常走。
    """
    task = page._import_task

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

    monkeypatch.setattr(task, "start", _sync_start)
    return task


def test_dropping_a_file_asks_which_level_then_imports_there(page, monkeypatch):
    """KI-7：拖一个单独的素材进来，会问一句「用在几杀」。

    KI-6 是"进当前关注的那一格"——可 KI-7 的简单层根本没有"当前关注的等级"
    这个概念（那是工坊里的事）。猜错了用户还得自己去别处翻，**问一句比猜错强**；
    而文件名认得出来时那一句其实也不用回答，小窗已经预选好了。
    """
    import core.kill_icon_import as import_module

    recorded = {}

    def _fake_convert(source, style, kills, **kwargs):
        recorded.update(source=source, style=style, kills=kills,
                        variant=kwargs.get("variant", ""))
        return {"frames": 12, "fps": 24, "kills": kills, "variant": "", "warnings": [],
                "style": style, "hold_seconds": 0.0}

    monkeypatch.setattr(import_module, "convert_to_style", _fake_convert)
    monkeypatch.setattr(page, "_reload_after_import", lambda style=None: None)
    # 小窗是模态的（`exec`），测试里一调就卡死——只把"它回答了什么"喂进来。
    asked = []
    monkeypatch.setattr(page, "_ask_target",
                        lambda path: asked.append(path) or (3, ""))
    _run_import_synchronously(page, monkeypatch)

    page._on_files_dropped(["C:/tmp/boom.webp"])

    assert asked == ["C:/tmp/boom.webp"], "拖单个素材必须先问一句用在几杀"
    assert recorded["style"] == "classic"
    assert recorded["kills"] == 3


def test_cancelling_the_wizard_imports_nothing(page, monkeypatch):
    """小窗里点「取消」= 什么都不做。不该"取消了但已经写进去了"。"""
    import core.kill_icon_import as import_module

    called = []
    monkeypatch.setattr(import_module, "convert_to_style",
                        lambda *a, **k: called.append(a))
    monkeypatch.setattr(page, "_ask_target", lambda path: None)
    _run_import_synchronously(page, monkeypatch)

    assert page._on_files_dropped(["C:/tmp/boom.webp"]) is None
    assert called == [], "用户取消了却还是导入了"


def test_a_dropped_zip_goes_through_the_pack_importer(page, monkeypatch):
    """zip 是"一整套风格"，不该被当成某一个等级的素材。"""
    import core.kill_icon_pack as pack_module

    recorded = {}

    def _fake_import_pack(path, **kwargs):
        recorded["path"] = path
        return {"style": "霓虹", "imported": [], "levels": [(1, "")], "failed": [],
                "warnings": [], "author": "", "loose": False}

    monkeypatch.setattr(pack_module, "import_pack", _fake_import_pack)
    monkeypatch.setattr(page, "_reload_after_import", lambda style=None: None)
    _run_import_synchronously(page, monkeypatch)

    page._on_files_dropped(["C:/tmp/pack.zip"])
    assert recorded["path"] == "C:/tmp/pack.zip"
    assert "霓虹" in page.notice_label.text()


def test_folders_can_be_dropped_at_all(page, tmp_path):
    """KI-6：文件夹拖进来必须**有反应**。

    KI-6 之前拖拽过滤器是按后缀匹配的，而目录路径永远不以扩展名结尾——
    DragEnter 都不接受，鼠标是禁止图标，什么提示都没有。而帧序列的唯一形态
    就是文件夹，等于最主流的社区素材根本拖不进来（页面上还写着"拖进来就能导入"）。

    ⚠ 这条判据第一版只验了"`accept_directories` 这个开关有没有打开"，
    没验**过滤器真的会放行一个目录**——把过滤逻辑改坏它照样绿。判据要落在
    行为上，不是落在接线上。
    """
    from PySide6.QtCore import QMimeData, QUrl

    folder = tmp_path / "帧序列"
    folder.mkdir()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])

    class _FakeDropEvent:
        def mimeData(self):
            return mime

    def _matched(widget):
        filters = getattr(widget, "_file_drop_filters", [])
        assert filters, "没有装拖拽过滤器"
        # QUrl.toLocalFile 回来的是正斜杠，规范化一下再比
        return [os.path.normcase(os.path.normpath(p))
                for f in filters for p in f._matched_paths(_FakeDropEvent())]

    expected = [os.path.normcase(os.path.normpath(str(folder)))]
    assert _matched(page) == expected, "页面不认文件夹"
    # 每一格自己也要能接文件夹——那一侧的判据在 test_kill_icon_grid_ki6.py 里，
    # KI-7 之后清单板的宿主是素材工坊，不再是这一页。


def test_drop_failures_are_reported_not_swallowed(page, monkeypatch):
    """KI-6：导入结果从弹窗改成页内提示条，失败照样要说出来。

    提示条比弹窗强的地方是它能挂一个「撤销」——弹窗关掉就没了。
    """
    import core.kill_icon_import as import_module

    def _boom(*_args, **_kwargs):
        raise import_module.KillIconImportError("这个文件读不出来")

    monkeypatch.setattr(import_module, "convert_to_style", _boom)
    monkeypatch.setattr(page, "_ask_target", lambda path: (1, ""))
    _run_import_synchronously(page, monkeypatch)

    page._on_files_dropped(["C:/tmp/bad.gif"])
    assert page.notice_frame.isHidden() is False
    assert "失败" in page.notice_label.text()
    assert "读不出来" in page.notice_label.text()
