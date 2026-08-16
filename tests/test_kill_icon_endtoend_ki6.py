# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-6：那些"本来以为只能人肉测"的部分。

这份文件里的每一条，最初都被我列进了"必须用户自己测"的清单，后来发现
都能验——记在这里是为了下次别再轻易把东西划进那张清单：

1. **真实拖放**：不是查"过滤器接线对不对"，是真造 `QDragEnterEvent` /
   `QDropEvent` 发给控件，看它接不接、handler 收到什么。
2. **叠加层画出来长什么样**：把叠加层窗口离屏渲染成 QImage，逐像素量
   淡入淡出、半透明边缘、纯黑不透明。**全程不映射到屏幕**，不打扰前台。
3. **GIF 硬边到底有多硬**：不靠"看着像"，量边缘上有多少像素是半透明的。
4. **打开素材文件夹**：真调 `os.startfile` 会弹资源管理器（打扰前台），
   但"传给它的路径对不对"是能验的，而那才是会错的地方。
"""
from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QPainter

import pages.kill_icon_page as page_module
from config import config
from kill_icon_overlay import (
    FADE_IN_SECONDS, FADE_OUT_SECONDS, KillIconAnimation, paint_frame,
    playback_state, render_frame_to_image,
)

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


# ==================================================== 1. 真实拖放事件


#: 造出来的 QMimeData 必须由 Python 侧一直持有——见 `_send`。
_MIME_KEEPALIVE = []


def _send(widget, event_class, paths):
    """真造一个拖放事件发给控件，返回"接不接"。

    ⚠ 三个坑，都是写这份文件时踩出来的：

    1. 必须走 `QApplication.sendEvent`，**不能**直接 `widget.event(...)`
       ——事件过滤器挂在 `QCoreApplication::notify` 上，直接调 `event()` 会
       绕过它，于是永远显示"不接受"。
    2. `QMimeData` 要在 Python 侧留住。让它被回收之后，事件里取回来的是个
       光秃秃的 `QObject`，产品代码里那句 `mime.hasUrls()` 会在**事件过滤器
       内部**抛 AttributeError。
    3. 结果要**立刻取成 bool** 再断言。Qt 处理完就销毁事件对象，而 pytest
       断言失败时会去 `repr` 表达式里的对象——表现是整个进程 access violation
       崩掉，不是用例失败。
    """
    from PySide6.QtWidgets import QApplication

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    _MIME_KEEPALIVE.append(mime)
    event = event_class(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    return bool(event.isAccepted())


def _send_drag_enter(widget, paths):
    return _send(widget, QDragEnterEvent, paths)


def _send_drop(widget, paths):
    """完整走一遍 DragEnter → Drop。

    Qt 不会把 Drop 投给一个没有正在拖拽的控件——实测只发 Drop 收不到。
    真实世界里也不存在"没有 enter 的 drop"，所以判据照着真实顺序走。
    """
    _send(widget, QDragEnterEvent, paths)
    return _send(widget, QDropEvent, paths)


@pytest.fixture
def cell(qapp):
    from widgets.kill_icon_level_grid import KillIconLevelCell

    widget = KillIconLevelCell(3)
    widget.resize(220, 260)
    yield widget
    widget.preview.stop()
    widget.deleteLater()


def test_a_real_drop_of_a_folder_reaches_the_handler(cell, tmp_path):
    """真造一个拖放事件发过去，看格子接不接。

    KI-6 之前这里是断的：拖拽过滤器按后缀匹配，而目录路径永远不以扩展名
    结尾——`DragEnter` 都不接受，鼠标是禁止图标，什么提示都没有。
    而帧序列的唯一形态就是文件夹。
    """
    folder = tmp_path / "帧序列"
    folder.mkdir()
    seen = []
    cell.files_dropped.connect(lambda kills, paths: seen.append((kills, paths)))

    assert _send_drag_enter(cell, [folder]) is True, "文件夹连拖进来都不让"
    assert _send_drop(cell, [folder]) is True

    assert seen, "拖放事件没有到达 handler"
    kills, paths = seen[0]
    assert kills == 3
    assert os.path.normcase(os.path.normpath(paths[0])) == \
        os.path.normcase(os.path.normpath(str(folder)))


@pytest.mark.parametrize("name", ["a.gif", "a.webp", "anim.png", "b.jpg",
                                  "sheet.json", "pack.zip"])
def test_a_real_drop_of_each_supported_file_is_accepted(cell, tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"x")
    assert _send_drag_enter(cell, [path]) is True, f"{name} 拖不进来"


@pytest.mark.parametrize("name", ["song.mp3", "clip.mp4", "readme.txt"])
def test_a_real_drop_of_an_unsupported_file_is_not_accepted(cell, tmp_path, name):
    """不认的后缀连接都不接——鼠标就显示禁止图标，用户不用等到松手才知道。"""
    path = tmp_path / name
    path.write_bytes(b"x")
    assert _send_drag_enter(cell, [path]) is False


def test_dropping_several_files_at_once_passes_them_all(cell, tmp_path):
    names = ["1.gif", "2.webp", "3.png"]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    seen = []
    cell.files_dropped.connect(lambda kills, paths: seen.append(paths))

    _send_drop(cell, [tmp_path / n for n in names])
    assert seen and len(seen[0]) == 3


def test_a_real_drop_onto_the_settings_page_reaches_the_handler(qapp, monkeypatch, tmp_path):
    """KI-7：设置页本身也得接得住拖放——那才是用户最先试的地方。

    页面上没有等级格子了（那些搬进了素材工坊），所以这里验的是
    "事件到没到 handler"，至于到了之后问不问「用在几杀」由
    tests/test_kill_icon_page_ki3.py 管。
    """
    monkeypatch.setattr(page_module.ResourceManager, "list_kill_icon_styles",
                        lambda: ["classic"])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_icon_style", "classic", raising=False)
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)

    page = page_module.KillIconPage()
    page.resize(900, 600)
    try:
        seen = []
        # ⚠ 换 `_on_files_dropped` 是没用的：`enable_file_drop` 在建页时就把
        # 那个**绑定方法**抓走了，之后改实例属性它照样调老的（然后真的起一次
        # 后台导入）。要拦就拦它内部下一跳——那一跳是调用时才查的。
        page._import_paths = lambda paths: seen.append(list(paths))

        pack = tmp_path / "包.zip"
        pack.write_bytes(b"x")
        folder = tmp_path / "帧序列"
        folder.mkdir()

        assert _send_drag_enter(page, [pack]) is True, "zip 图标包拖不到页面上"
        assert _send_drop(page, [pack]) is True
        assert _send_drop(page, [folder]) is True, "帧序列文件夹拖不到页面上"

        assert len(seen) == 2
        assert seen[0][0].endswith("包.zip")
    finally:
        page.deleteLater()


# ==================================================== 2. 叠加层画出来长什么样


def _composite_over_game(frame, opacity, background=(30, 60, 90, 255)):
    """把一帧按给定不透明度合成到"游戏画面"上，返回合成结果。

    走的是 `paint_frame` —— 叠加层真正用的那一个函数，不是另写一套。
    """
    canvas = QImage(frame.width(), frame.height(), QImage.Format_ARGB32_Premultiplied)
    canvas.fill(QColor(*background))
    painter = QPainter(canvas)
    paint_frame(painter, frame, dpr=1.0, opacity=opacity)
    painter.end()
    return canvas


def _soft_edge_pixels(image):
    """半透明像素有多少个——真 alpha 与二值抠图的分水岭。"""
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = image.pixelColor(x, y).alpha()
            if 0 < alpha < 255:
                count += 1
    return count


def _round_icon(size=64, soft=True):
    """一个带抗锯齿边缘的圆——模拟真实素材（边缘一圈半透明像素）。"""
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, soft)
    painter.setBrush(QColor(255, 200, 60, 255))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, size - 8, size - 8)
    painter.end()
    return image


def test_the_overlay_really_blends_instead_of_punching_holes(qapp):
    """半透明边缘必须真的和游戏画面混色。

    老 pygame 版靠 `LWA_COLORKEY` 纯黑抠图，透明是**二值**的：要么全透明
    要么全不透明，边缘永远硬锯齿。这条量的是"合成之后边上有没有中间色"。
    """
    icon = _round_icon()
    assert _soft_edge_pixels(icon) > 50, "测试素材本身就没有软边，这条判据没意义"

    composed = _composite_over_game(icon, 1.0)
    # 边上应当出现"既不是纯背景也不是纯图标色"的过渡像素
    background = QColor(30, 60, 90)
    icon_color = QColor(255, 200, 60)
    blended = 0
    for y in range(composed.height()):
        for x in range(composed.width()):
            color = composed.pixelColor(x, y)
            if color != background and color != icon_color:
                blended += 1
    assert blended > 50, f"边缘没有混色（只有 {blended} 个过渡像素）＝退回二值抠图了"


def test_fade_in_and_fade_out_actually_change_what_is_drawn(qapp):
    """淡入淡出不是"设了个参数"，要真的画出来更淡。"""
    icon = _round_icon()
    center = (icon.width() // 2, icon.height() // 2)

    samples = []
    for opacity in (0.0, 0.25, 0.5, 0.75, 1.0):
        composed = _composite_over_game(icon, opacity)
        samples.append(composed.pixelColor(*center).red())

    assert samples == sorted(samples), f"不透明度上升红色分量却没跟着走：{samples}"
    assert samples[0] < samples[-1] - 60, "0% 与 100% 画出来几乎一样＝淡入没生效"


def test_a_whole_playback_is_visible_from_start_to_finish(qapp):
    """按真实时间轴走一遍，确认每一拍都画得出东西、且首尾是淡的。"""
    frames = tuple(_round_icon() for _ in range(10))
    animation = KillIconAnimation(frames=frames, fps=10, frame_width=64,
                                  frame_height=64)

    timeline = []
    elapsed = 0.0
    while elapsed < animation.duration + FADE_OUT_SECONDS + 0.1:
        state = playback_state(elapsed, animation.fps, animation.frame_count,
                               FADE_IN_SECONDS, FADE_OUT_SECONDS)
        if state is None:
            break
        index, opacity = state
        assert render_frame_to_image(frames[index], opacity) is not None
        timeline.append((round(elapsed, 3), index, round(opacity, 3)))
        elapsed += 1 / 60.0

    assert timeline, "整段播放一帧都没画出来"
    assert timeline[0][2] < 0.2, "开头没有淡入"
    assert timeline[-1][2] < 0.3, "结尾没有淡出"
    assert max(t[2] for t in timeline) == pytest.approx(1.0, abs=0.02)
    assert timeline[-1][1] == animation.frame_count - 1, "结尾没有定格在最后一帧"


def test_pure_black_pixels_stay_opaque_when_composited(qapp):
    """纯黑必须是"不透明的黑"，不是洞。

    老实现把纯黑当透明色抠掉，素材里任何纯黑像素都会变成洞。
    """
    icon = QImage(16, 16, QImage.Format_ARGB32)
    icon.fill(QColor(0, 0, 0, 255))
    composed = _composite_over_game(icon, 1.0, background=(200, 40, 40, 255))
    assert composed.pixelColor(8, 8) == QColor(0, 0, 0), "纯黑被抠成洞了"


# ==================================================== 3. GIF 的硬边有多硬


def _import_and_measure(tmp_path, source, style, kills):
    """导入一段素材，量它边缘上有多少半透明像素。"""
    from core.kill_icon_import import convert_to_style

    class _RM:
        def get_kill_icon_sprite_sheet_paths(self, s, k, variant=""):
            directory = tmp_path / "kill_icons" / s
            return (str(directory / f"{k}{variant}.png"),
                    str(directory / f"{k}{variant}.json"))

        def get_kill_icon_legacy_frames_dir(self, s, k):
            return None

    result = convert_to_style(source, style, kills, resource_manager=_RM())
    sheet = Image.open(result["sprite_path"]).convert("RGBA")
    alphas = [p[3] for p in sheet.getdata()]
    return {
        "soft": sum(1 for a in alphas if 0 < a < 255),
        "opaque": sum(1 for a in alphas if a == 255),
        "warnings": result["warnings"],
    }


def _soft_circle(size=64):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(255, 200, 60, 255))
    # 手工做一圈半透明描边，模拟抗锯齿
    for step, alpha in enumerate((200, 140, 80, 40)):
        draw.ellipse((2 + step, 2 + step, size - 2 - step, size - 2 - step),
                     outline=(255, 200, 60, alpha), width=1)
    return image


def test_gif_loses_the_soft_edge_and_webp_keeps_it(tmp_path):
    """把"GIF 边缘会有硬白边"这句话量成数字。

    这条不是为了证明我们做得好——恰恰相反，它钉的是**这个损失真实存在**，
    所以导入 GIF 时那句警告必须一直在。哪天有人觉得警告啰嗦想删掉，
    先看看这两个数。
    """
    circle = _soft_circle()

    webp = tmp_path / "soft.webp"
    circle.save(webp, lossless=True)
    gif = tmp_path / "soft.gif"
    circle.save(gif)

    webp_stat = _import_and_measure(tmp_path, webp, "软边", 1)
    gif_stat = _import_and_measure(tmp_path, gif, "硬边", 1)

    assert webp_stat["soft"] > 100, f"WebP 也没保住软边：{webp_stat}"
    assert gif_stat["soft"] == 0, f"GIF 居然有半透明像素：{gif_stat}"
    assert any("1-bit" in w or "硬白边" in w for w in gif_stat["warnings"]), \
        "GIF 的这个损失必须在导入时说出来"


# ==================================================== 4. 打开素材文件夹


def test_open_folder_hands_the_right_path_to_the_shell(qapp, monkeypatch, tmp_path):
    """真调 `os.startfile` 会弹资源管理器（打扰前台），但路径算错才是会出事的地方。

    KI-7 之后这个按钮在素材工坊上——设置页只留"挑一套、放哪儿、开没开"。
    """
    import dialogs.kill_icon_workshop as workshop_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(workshop_module, "load_level_animation", lambda *a, **k: None)

    workshop = workshop_module.KillIconWorkshop("classic")
    try:
        style_dir = tmp_path / "resources" / "kill_icons" / "classic"
        style_dir.mkdir(parents=True)
        monkeypatch.setattr(workshop_module.ResourceManager, "get_kill_icon_style_dir",
                            staticmethod(lambda style: str(tmp_path / "resources" /
                                                           "kill_icons" / style)))
        opened = []
        monkeypatch.setattr(os, "startfile", lambda path: opened.append(path),
                            raising=False)

        workshop._open_style_folder()
        assert opened == [str(style_dir)]

        # 目录不存在时不许去调 shell，而是页内说一句
        monkeypatch.setattr(workshop_module.ResourceManager, "get_kill_icon_style_dir",
                            staticmethod(lambda style: str(tmp_path / "不存在")))
        opened.clear()
        workshop._open_style_folder()
        assert opened == []
        assert workshop.notice_frame.isHidden() is False
    finally:
        workshop.level_grid.stop_previews()
        workshop.deleteLater()
