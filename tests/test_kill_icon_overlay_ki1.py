# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-1：击杀图标从 pygame 子进程搬到 Qt 叠加层。

这个功能在迁移前是**零渲染测试**的——播放循环跑在 multiprocessing 子进程里，
画面靠 SDL 出，测试够不着。所以这份文件的第一价值不是"验新代码"，是让这条链
第一次有判据。三类判据分别对应三种"不报错的错"：

1. **时间轴算错**——帧号/透明度只要有一处对不上，表现是图标闪一下就没、或者
   卡在最后一帧不走。纯函数逐点验。
2. **几何算错**——高 DPI 屏上把物理像素当逻辑像素传给 `setGeometry`，
   图标会整体放大 25% 且偏移跟着漂。这是本次迁移最可能翻车的地方
   （准心 R8b 就栽在这里过）。
3. **透明度退化**——老实现是 `LWA_COLORKEY` 纯黑抠图，二值透明。
   如果哪天有人"顺手"把渲染改回去，纯黑像素会重新变成洞。这里钉死
   「纯黑必须是不透明的黑」。
"""
from __future__ import annotations

import ast
import json
import os
import threading
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

import kill_icon_overlay as overlay
from kill_icon_overlay import (
    MAX_HOLD_SECONDS,
    KillIconAnimation,
    clamp_fps,
    clamp_hold,
    compute_overlay_geometry,
    compute_scaled_size,
    duration_for_fps,
    fps_for_duration,
    load_frame_sequence,
    load_sprite_sheet,
    playback_state,
    render_frame_to_image,
    scale_animation,
)
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent


def _solid(width, height, color=(255, 0, 0, 255)):
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(*color))
    return image


def _write_sheet(directory, name, frame_w, frame_h, frames, cols=None, fps=30,
                 declared_frames=None):
    """在磁盘上造一张图集 + JSON，每帧填不同的红色分量以便区分。"""
    cols = cols or frames
    rows = (frames + cols - 1) // cols
    sheet = QImage(frame_w * cols, frame_h * rows, QImage.Format_ARGB32)
    sheet.fill(QColor(0, 0, 0, 0))
    for index in range(frames):
        left = (index % cols) * frame_w
        top = (index // cols) * frame_h
        for x in range(frame_w):
            for y in range(frame_h):
                sheet.setPixelColor(left + x, top + y, QColor(index + 1, 0, 0, 255))
    directory.mkdir(parents=True, exist_ok=True)
    sprite_path = directory / f"{name}.png"
    sheet.save(str(sprite_path), "PNG")
    (directory / f"{name}.json").write_text(
        json.dumps({
            "frame_width": frame_w,
            "frame_height": frame_h,
            "frames": declared_frames if declared_frames is not None else frames,
            "cols": cols,
            "rows": rows,
            "fps": fps,
        }),
        encoding="utf-8",
    )
    return sprite_path, directory / f"{name}.json"


# ==================================================== 1. 播放时间轴


def test_frames_advance_at_the_declared_rate():
    """10 帧 @10fps：第 0.05 秒在第 0 帧，第 0.35 秒在第 3 帧。"""
    assert playback_state(0.0, 10, 10)[0] == 0
    assert playback_state(0.05, 10, 10)[0] == 0
    assert playback_state(0.35, 10, 10)[0] == 3
    assert playback_state(0.95, 10, 10)[0] == 9


def test_playback_ends_exactly_when_the_frames_run_out():
    """没有淡出时，播完就是播完——多留一拍就是"图标赖着不走"。"""
    assert playback_state(0.99, 10, 10) is not None
    assert playback_state(1.0, 10, 10) is None
    assert playback_state(5.0, 10, 10) is None


def test_fade_out_is_a_tail_after_the_animation_not_a_dimmed_ending():
    """淡出挂在动画**之后**，定格最后一帧渐隐；不许把收尾动作压暗。

    回退验证：把 `playback_state` 改成"最后 fade_out 秒开始压暗"，
    第 0.95 秒的不透明度会掉到 1.0 以下，这条立刻变红。
    """
    # 动画本体 1.0s，尾巴 0.4s
    assert playback_state(0.95, 10, 10, 0.0, 0.4)[1] == pytest.approx(1.0)

    index, opacity = playback_state(1.2, 10, 10, 0.0, 0.4)
    assert index == 9, "尾巴期间应当定格在最后一帧"
    assert opacity == pytest.approx(0.5, abs=0.01)

    assert playback_state(1.4, 10, 10, 0.0, 0.4) is None


def test_fade_in_ramps_from_zero():
    assert playback_state(0.0, 10, 10, 0.2, 0.0)[1] == pytest.approx(0.0)
    assert playback_state(0.1, 10, 10, 0.2, 0.0)[1] == pytest.approx(0.5)
    assert playback_state(0.2, 10, 10, 0.2, 0.0)[1] == pytest.approx(1.0)


def test_dirty_metadata_does_not_raise():
    """素材 JSON 是用户自己导入的。坏数据的正确表现是"不显示"，不是把 GSI 线程炸掉。"""
    assert playback_state(0.1, 0, 10) is not None      # fps=0 被夹回 1
    assert playback_state(0.1, "x", 10) is not None    # 非数字帧率
    assert playback_state(0.1, 30, 0) is None          # 没有帧
    assert playback_state(-5.0, 30, 10)[0] == 0        # 负数时间


def test_single_frame_icon_is_visible_at_all(monkeypatch):
    """KI-4：单帧素材必须靠 `hold` 才看得见。

    这是 KI-4 之前最难发现的一个洞：拖一张静态 PNG 进来，1 帧 @30fps 只有
    **0.033 秒**——用户看到"导入成功"弹窗，然后游戏里什么都没有，全程零报错。
    静态图标是完全合理的需求，而且是新手最可能第一个拖进来的东西。

    回退验证：把 `playback_state` 里的 `+ clamp_hold(hold)` 删掉，
    第 1.0 秒立刻变成 None，这条当场变红。
    """
    assert playback_state(0.5, 30, 1) is None, "没有定格时，1 帧 @30fps 早就播完了"

    assert playback_state(0.5, 30, 1, hold=1.5) is not None
    assert playback_state(1.4, 30, 1, hold=1.5)[0] == 0, "定格期间画的仍是那一帧"
    assert playback_state(1.6, 30, 1, hold=1.5) is None


def test_hold_sits_between_the_animation_and_the_fade_out():
    """定格插在动画与渐隐**之间**，两段都停在最后一帧上。

    顺序搞反（先渐隐再定格）的表现是"图标淡出之后又亮回来"。
    """
    # 10 帧 @10fps = 1.0s 动画 + 0.5s 定格 + 0.4s 渐隐
    assert playback_state(1.2, 10, 10, 0.0, 0.4, 0.5)[1] == pytest.approx(1.0)
    assert playback_state(1.2, 10, 10, 0.0, 0.4, 0.5)[0] == 9

    index, opacity = playback_state(1.7, 10, 10, 0.0, 0.4, 0.5)
    assert index == 9
    assert opacity == pytest.approx(0.5, abs=0.01)

    assert playback_state(1.9, 10, 10, 0.0, 0.4, 0.5) is None


def test_hold_defaults_to_the_old_behaviour():
    """`hold` 是 KI-4 唯一新增的格式字段。老素材读不到它，行为必须逐字节等价。"""
    for elapsed in (0.0, 0.3, 0.99, 1.0, 2.0):
        assert playback_state(elapsed, 10, 10, 0.1, 0.2) == \
               playback_state(elapsed, 10, 10, 0.1, 0.2, 0.0)

    assert clamp_hold(None) == 0.0
    assert clamp_hold("x") == 0.0
    assert clamp_hold(-3) == 0.0
    assert clamp_hold(999) == MAX_HOLD_SECONDS


def test_duration_and_fps_are_inverse():
    """设置页把"FPS"换成"展示时长"，靠的就是这一对互逆函数。"""
    assert duration_for_fps(30, 30) == pytest.approx(1.0)
    assert fps_for_duration(30, 1.0) == 30
    assert fps_for_duration(30, 2.0) == 15
    # 取整误差必须落在"夹得住"的范围里，不能算出 0 或负数
    assert fps_for_duration(1, 100.0) == clamp_fps(1)
    assert fps_for_duration(600, 0.001) == 60


# ==================================================== 2. 几何


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_icon_keeps_its_physical_size_at_every_dpr(dpr):
    """图标在屏幕上有多大，必须与 Windows 缩放无关。

    反例（也是迁移时最容易写出来的那版）：直接把物理尺寸交给 `setGeometry`。
    那在 125% 屏上会变成 1.25 倍大——用户当场就能看出来。
    """
    _x, _y, w, h = compute_overlay_geometry((0, 0, 1920, 1080), dpr, 400, 300)
    assert w == pytest.approx(round(400 / dpr), abs=1)
    assert h == pytest.approx(round(300 / dpr), abs=1)


def test_default_position_matches_the_pygame_era_formula():
    """落点公式照抄老实现，一个像素都不许动。

    用户存量的偏移值是**相对这个基准**调出来的：基准一动，所有老用户的
    图标位置会集体偏移，而且没有任何报错。
    """
    screen_w, screen_h, icon_w, icon_h = 1920, 1080, 400, 300
    expected_x = (screen_w - icon_w) // 2
    expected_y = (screen_h * 3) // 4 - icon_h // 2 + 50

    x, y, _w, _h = compute_overlay_geometry((0, 0, screen_w, screen_h), 1.0, icon_w, icon_h)
    assert (x, y) == (expected_x, expected_y)


def test_offsets_are_physical_pixels():
    base = compute_overlay_geometry((0, 0, 1920, 1080), 1.0, 400, 300)
    moved = compute_overlay_geometry((0, 0, 1920, 1080), 1.0, 400, 300, 30, -20)
    assert moved[0] - base[0] == 30
    assert moved[1] - base[1] == -20


def test_secondary_screen_origin_is_respected():
    """副屏的窗口坐标要带上那块屏的原点，否则图标画回主屏。"""
    x, _y, _w, _h = compute_overlay_geometry((1920, 0, 2560, 1440), 1.0, 400, 300)
    assert x > 1920


def test_scaled_size_keeps_the_source_aspect_ratio():
    """宽高比取素材自己的，不按 base_height 拉伸——用户素材什么比例我们管不着。"""
    assert compute_scaled_size(700, 500, 350, 1.0) == (350, 250)
    assert compute_scaled_size(700, 500, 350, 2.0) == (700, 500)
    # 正方形素材不该被压成 350x250
    assert compute_scaled_size(200, 200, 350, 1.0) == (350, 350)


def test_scaled_size_survives_dirty_scale():
    assert compute_scaled_size(700, 500, 350, None)[0] > 0
    assert compute_scaled_size(700, 500, 350, "x")[0] > 0
    assert compute_scaled_size(0, 0, 350, 1.0)[0] > 0


# ==================================================== 3. 真 alpha（防回潮）


def test_pure_black_stays_opaque_black():
    """老实现用 `LWA_COLORKEY` 把纯黑当透明抠掉，素材里任何纯黑像素都会变成洞。

    这条判据钉的就是那个失效模式：**纯黑必须是不透明的黑**。
    谁要是把渲染改回抠图路线，这里当场变红。
    """
    frame = QImage(4, 4, QImage.Format_ARGB32)
    frame.fill(QColor(0, 0, 0, 255))
    rendered = render_frame_to_image(frame)

    color = rendered.pixelColor(2, 2)
    assert color.alpha() == 255, "纯黑被当成透明抠掉了——回到 colorkey 老路上了"
    assert (color.red(), color.green(), color.blue()) == (0, 0, 0)


def test_partial_alpha_is_preserved():
    """半透明像素要真的半透明——这是 colorkey 时代做不到的事。"""
    frame = QImage(4, 4, QImage.Format_ARGB32)
    frame.fill(QColor(255, 0, 0, 128))
    rendered = render_frame_to_image(frame)
    assert 100 < rendered.pixelColor(2, 2).alpha() < 160


def test_render_opacity_multiplies_into_alpha():
    frame = QImage(4, 4, QImage.Format_ARGB32)
    frame.fill(QColor(255, 0, 0, 255))
    assert render_frame_to_image(frame, 1.0).pixelColor(2, 2).alpha() == 255
    faded = render_frame_to_image(frame, 0.5).pixelColor(2, 2).alpha()
    assert 100 < faded < 160


# ==================================================== 4. 素材装载


def test_sprite_sheet_is_sliced_in_order(tmp_path):
    sprite, meta = _write_sheet(tmp_path, "1", 8, 6, frames=4, cols=2, fps=24)
    animation = load_sprite_sheet(str(sprite), str(meta))

    assert animation.frame_count == 4
    assert animation.fps == 24
    assert (animation.frame_width, animation.frame_height) == (8, 6)
    # 每帧的红色分量是帧序号+1，顺序错了这里立刻能看出来
    assert [f.pixelColor(1, 1).red() for f in animation.frames] == [1, 2, 3, 4]


def test_over_declared_frame_count_slices_what_is_actually_there(tmp_path):
    """JSON 说有 10 帧、图集只画得下 4 帧：切 4 帧，别整套丢弃。

    用户手搓 JSON 或换了图集忘了改数字，这是很常见的一种坏法。
    整套丢弃的表现是"图标完全不出现"，比少几帧糟得多。
    """
    sprite, meta = _write_sheet(tmp_path, "2", 8, 6, frames=4, cols=2, declared_frames=10)
    animation = load_sprite_sheet(str(sprite), str(meta))
    assert animation.frame_count == 4


def test_missing_frame_size_is_rejected(tmp_path):
    sprite, _meta = _write_sheet(tmp_path, "3", 8, 6, frames=2)
    bad_meta = tmp_path / "3bad.json"
    bad_meta.write_text(json.dumps({"fps": 30}), encoding="utf-8")
    assert load_sprite_sheet(str(sprite), str(bad_meta)) is None


def test_legacy_frame_directory_still_loads(tmp_path):
    """老格式（一个目录一堆图）必须继续认——存量用户的资源就是这样的。"""
    frames_dir = tmp_path / "1"
    frames_dir.mkdir()
    for index in range(3):
        _solid(10, 10, (index + 1, 0, 0, 255)).save(str(frames_dir / f"frame-{index:03d}.png"))
    meta = tmp_path / "1.json"
    meta.write_text(json.dumps({"fps": 12}), encoding="utf-8")

    animation = load_frame_sequence(str(frames_dir), str(meta))
    assert animation.frame_count == 3
    assert animation.fps == 12
    assert [f.pixelColor(5, 5).red() for f in animation.frames] == [1, 2, 3]


def test_empty_sources_return_none(tmp_path):
    assert load_frame_sequence(str(tmp_path / "nope")) is None
    assert load_sprite_sheet(str(tmp_path / "nope.png"), str(tmp_path / "nope.json")) is None


def test_scaling_produces_the_requested_size():
    animation = KillIconAnimation(frames=(_solid(700, 500),), fps=30,
                                  frame_width=700, frame_height=500)
    frames = scale_animation(animation, 350, 250)
    assert (frames[0].width(), frames[0].height()) == (350, 250)


# ==================================================== 5. 结构性判据


def test_kill_icon_modules_do_not_import_pygame():
    """迁移的**目的本身**：这条链上不该再有 pygame。

    留一份 pygame 兜底渲染器是很诱人的，但准心那次留了之后，代价是长期维护
    一个"新参数一个都不支持"的第二渲染路径。这里不重蹈——回退靠 git，不靠双栈。
    """
    for name in ("kill_icon_player.py", "kill_icon_overlay.py"):
        tree = ast.parse((REPO / name).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "pygame" not in imported, f"{name} 又把 pygame 引回来了"


def test_geometry_helpers_are_pure_functions():
    """几何/时间轴必须能离屏验——不许悄悄依赖 QWidget 或屏幕。

    判据落在"模块顶层不 import QtWidgets"上：`kill_icon_overlay` 只负责
    纯函数与绘制，窗口在 `kill_icon_player`。混进来一次，这些判据就得建窗口才能跑，
    而建窗口的测试在这个项目里是要打扰前台的。
    """
    tree = ast.parse((REPO / "kill_icon_overlay.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    # ⭐ 分母是这个模块的 import 面。它一空（文件被搬空/改名后重建），
    #   「没有 QtWidgets」就变成一句自动为真的话。
    must_scan(modules, "kill_icon_overlay.py 的 from-import 模块名", least=2)
    assert not any(m.startswith("PySide6.QtWidgets") for m in modules)


def test_play_from_another_thread_does_not_touch_widgets(qapp, monkeypatch):
    """GSI 线程调 `play_images` 只许 emit 信号，不许当场动窗口。

    这是搬进主进程后**新出现**的一类风险：老实现跨进程发命令，天然安全；
    现在渲染就在主线程，若直接调用就成了"在别的线程里动 QWidget"
    ——UP-054 的老根因。

    判据做法：在没有事件循环的工作线程里调用，然后断言窗口没被创建。
    队列连接的信号要等回到主线程才投递，所以"当场就建了窗口"必然是直连。
    """
    import kill_icon_player
    from config import config as config_obj

    monkeypatch.setattr(config_obj, "kill_icon_enabled", True, raising=False)
    player = kill_icon_player.KillIconPlayer()
    try:
        player._catalog = {}
        player._scaled = {}

        errors = []

        def _call():
            try:
                player.play_icon(2)
            except Exception as exc:  # pragma: no cover - 出错才有内容
                errors.append(exc)

        thread = threading.Thread(target=_call)
        thread.start()
        thread.join(timeout=2)

        assert not errors, errors
        assert player._window is None, "跨线程调用当场建了窗口——信号连成直连了"
    finally:
        player.cleanup()


def test_player_keeps_only_one_pixel_copy(qapp, tmp_path, monkeypatch):
    """装载完成后，内存里每个等级只许留**一份**像素。

    第一版把原始帧也留着（理由是"改缩放时不用重读盘"）。实测：缩放 100% 时
    留两份和留一份**一样多**——`QImage::scaled` 目标尺寸与源相同时返回的是同一个
    隐式共享对象；但缩放 150% 时两份要 564MB、一份 475MB，多出来的 89MB 是白付的。

    判据落在"元数据表里不许出现 QImage"上，而不是量进程内存：内存数字受别的
    功能影响太大，量不出因果——这一点也是那次排查的教训，当时正是拿两次会话的
    进程内存差去推断，推出来的因果**是错的**。
    """
    import kill_icon_player
    from resource_manager import ResourceManager

    def _resolver(relative_path):
        normalized = relative_path.replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / normalized)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(_resolver))
    style_dir = tmp_path / "resources" / "kill_icons" / "风格"
    _write_sheet(style_dir, "1", 8, 6, frames=3)

    player = kill_icon_player.KillIconPlayer()
    try:
        player._load_worker("风格", player._load_token + 1)
        # 后台线程那步在本用例里是同步调的，结果通过信号回来；直接取一次装载结果
        assets = {}
        for kills in (1,):
            animation = overlay.load_level_animation("风格", kills)
            assets[(kills, "")] = (
                kill_icon_player.LevelInfo(animation.frame_count, animation.fps,
                                           animation.frame_width, animation.frame_height),
                scale_animation(animation, 16, 12),
            )
        player._handle_assets_ready("风格", player._load_token, assets)

        assert player._scaled, "预缩放结果没进来"
        for info in player._catalog.values():
            assert not isinstance(info, KillIconAnimation), (
                "元数据表里又存回整套帧了——每个等级会多占一份完整像素副本")
            for field in info:
                from PySide6.QtGui import QImage as _QImage

                assert not isinstance(field, _QImage)
    finally:
        player.cleanup()


def test_headshot_falls_back_to_the_normal_icon(qapp):
    """爆头素材是**可选覆写**。没备 `<等级>hs` 时必须退回普通图标，不是不显示。"""
    import kill_icon_player

    player = kill_icon_player.KillIconPlayer()
    try:
        animation = KillIconAnimation(frames=(_solid(10, 10),), fps=30,
                                      frame_width=10, frame_height=10)
        player.current_style = "不存在的风格"      # 逼它只走内存，不去读盘
        player._catalog = {(3, ""): kill_icon_player.LevelInfo(1, 30, 10, 10)}
        player._scaled = {(3, ""): animation.frames}

        # KI-4 起 `_frames_for` 连定格时长一起返回（单帧素材靠它才看得见）
        frames, fps, hold = player._frames_for(3, "hs")
        assert frames, "没有爆头素材时应当退回普通图标"
        assert fps == 30
        assert hold == 0.0

        assert player._frames_for(4, "")[0] == (), "没有的等级就是没有，不许乱退回别的等级"
    finally:
        player.cleanup()
