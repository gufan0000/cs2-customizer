# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R8b-A · 准心 Qt 叠加层的门禁（UP-054）。

判据编号对应 [docs/ui-perf/06_R8b_准心Qt化_设计文档.md] §9-2。
每条都验过「把被测代码回退就变红」——这是本专项对新增判据的常规要求
（R8a 最贵的教训：判据锚错了东西，改坏了也全绿）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter

from crosshair_overlay import (
    CANVAS_PX,
    COLOR_MAP,
    IDLE_ANIMATIONS,
    KILL_DURATION_S,
    KILL_EFFECTS,
    PULSE_RATE_HZ,
    USER_STYLES,
    CrosshairAnimator,
    CrosshairFrame,
    CrosshairOverlayManager,
    CrosshairOverlayWindow,
    CrosshairState,
    compute_centered_geometry,
    dim,
    paint_crosshair,
    resolve_color,
)

REPO = Path(__file__).resolve().parent.parent


# ============================================================ D-1 主进程无 SDL 视频

#: 这三个模块整体跑在 `multiprocessing` 子进程里，SDL 与 Qt 天然隔离。
#: 名单是**白名单不是豁免**：新增任何一个都必须先说明它为什么不在主进程。
SUBPROCESS_SDL_MODULES = {
    "flash_process.py",
    "kill_icon_player.py",
    "utility_display.py",
}

#: R8b 期间的过渡名单。R8b-D 把默认渲染器切到 Qt、老实现进入兼容期后，
#: 这里要清空——**清空动作必须是一次显式提交**，不能靠这条判据自己变松。
MAIN_PROCESS_SDL_ALLOWED = {
    "crosshair_animation.py",
}


def _modules_touching_sdl_video():
    """扫根目录的 .py，找出谁在调 `pygame.display.*`。"""
    hits = set()
    for path in REPO.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            value = node.value
            if (isinstance(value, ast.Attribute) and value.attr == "display"
                    and isinstance(value.value, ast.Name) and value.value.id == "pygame"):
                hits.add(path.name)
                break
    return hits


def test_no_new_sdl_video_in_main_process():
    """R8b 的**目的本身**：主进程里不该再有 SDL 视频窗口。

    这是一条棘轮判据——它现在允许 `crosshair_animation.py`（老实现还在跑），
    但任何**新增**的主进程 SDL 视频调用会当场变红。
    根因见设计文档 §2：窗口建在主线程、却在工作线程刷新，
    违反 Win32 窗口线程亲和性；异常码 0x8001010d 与该机制吻合。
    """
    offenders = _modules_touching_sdl_video() - SUBPROCESS_SDL_MODULES
    assert offenders <= MAIN_PROCESS_SDL_ALLOWED, (
        f"主进程新增了 SDL 视频调用: {sorted(offenders - MAIN_PROCESS_SDL_ALLOWED)}。"
        "要么放子进程，要么用 crosshair_overlay 的 Qt 方案"
    )


def test_qt_overlay_does_not_import_pygame():
    """新渲染器一行 pygame 都不该有——否则这轮就白做了。"""
    source = (REPO / "crosshair_overlay.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "pygame" not in imported


# ============================================================ D-2 物理像素几何

@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_canvas_is_100_physical_pixels_at_every_dpr(dpr):
    """画布的**物理**边长必须锁死 100，不随 Windows 缩放变。

    反例（也是最容易写出来的那版）：直接 `setGeometry(..., 100, 100)`。
    那在 125% 屏上是 125 物理像素，准心整体放大 25%——用户当场就能看出来。
    """
    _x, _y, w, h = compute_centered_geometry((0, 0, 2560, 1440), dpr)
    assert abs(w * dpr - CANVAS_PX) <= 1.0, f"dpr={dpr} 时物理宽 {w * dpr}"
    assert abs(h * dpr - CANVAS_PX) <= 1.0, f"dpr={dpr} 时物理高 {h * dpr}"


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("screen", [(0, 0, 2560, 1440), (0, 0, 1920, 1080), (-1920, 0, 1920, 1080)])
def test_canvas_center_matches_screen_center_within_one_pixel(dpr, screen):
    """准心中心与屏幕中心的物理偏差 ≤1px。差几个像素的准心比没有还糟。"""
    x, y, w, h = compute_centered_geometry(screen, dpr)
    sx, sy, sw, sh = screen
    dx = ((x + w / 2) - (sx + sw / 2)) * dpr
    dy = ((y + h / 2) - (sy + sh / 2)) * dpr
    assert abs(dx) <= 1.0 and abs(dy) <= 1.0, f"偏移 ({dx:.2f}, {dy:.2f}) 物理像素"


# ============================================================ D-3 逐样式渲染非空

def _render(frame) -> QImage:
    img = QImage(CANVAS_PX, CANVAS_PX, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    paint_crosshair(painter, frame)
    painter.end()
    return img


def _opaque_pixels(img: QImage) -> int:
    return sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if img.pixelColor(x, y).alpha() > 0
    )


@pytest.mark.parametrize("style", USER_STYLES)
def test_every_user_style_draws_something(style):
    """四个用户可选样式都得画得出东西。

    「画得出来」是自动化能保证的下限；观感对不对仍需人工回归（设计文档 R-5）。
    """
    frame = CrosshairFrame(style=style, custom_points=((15, 10), (15, 20), (10, 15), (20, 15)))
    assert _opaque_pixels(_render(frame)) > 0, f"样式 {style} 渲染出空白帧"


#: 期望值**独立写死**，不从 `COLOR_MAP` 反查。
#: 第一版判据就是拿 `resolve_color()` 当期望值的——那是同义反复：
#: 把 cyan 改成 (0,254,255) 做变异测试，判据纹丝不动全绿。
#: 与 R8a 那条「对比度判据自己调产品函数现算前景色」是同一个错。
#: 这些是 CS 玩家惯用的准心色，值本身就是契约（用户存量配置指向这些名字）。
EXPECTED_RGB = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
}


def test_color_table_has_exactly_the_six_documented_colors():
    assert set(COLOR_MAP) == set(EXPECTED_RGB), "颜色表增删了颜色，UI 的选项要同步"


@pytest.mark.parametrize("color_name", sorted(EXPECTED_RGB))
def test_every_color_reaches_the_canvas(color_name):
    """六种颜色都要**按期望的 RGB** 落到画布上——颜色表改错值是无声故障。"""
    frame = CrosshairFrame(style="crosshair", color=resolve_color(color_name), size=40)
    center = _render(frame).pixelColor(CANVAS_PX // 2, CANVAS_PX // 2)
    assert (center.red(), center.green(), center.blue()) == EXPECTED_RGB[color_name]


def test_custom_style_without_points_draws_nothing_instead_of_crashing():
    """没存过自定义点时不该抛异常——这是新用户切到「自定义」的默认状态。"""
    assert _opaque_pixels(_render(CrosshairFrame(style="custom", custom_points=()))) == 0


def test_rotation_actually_changes_the_picture():
    """旋转不生效是最容易悄悄漏掉的一类回退（画面还在，就是不转）。"""
    base = _render(CrosshairFrame(style="crosshair", size=40))
    turned = _render(CrosshairFrame(style="crosshair", size=40, rotation=45.0))
    assert base != turned


def test_t_shape_was_wired_up_in_r9a():
    """UP-086 的结论存档：R8b 迁移时 `t_shape` 故意没带过来（当时全仓够不着），
    R9-A 补进 UI 当第五个样式。留这条是为了让下一个人不用重查一遍历史。
    """
    assert "t_shape" in USER_STYLES
    assert _opaque_pixels(_render(CrosshairFrame(style="t_shape", size=40))) > 0


# ============================================================ D-3 / D-5 空闲动画

def _walk(animator, state, fps, seconds, t0=0.0):
    """按给定帧率把动画跑一段，返回每帧的 frame。"""
    step = 1.0 / fps
    frames = []
    n = int(seconds * fps)
    for i in range(n):
        frames.append(animator.advance(state, t0 + i * step))
    return frames


@pytest.mark.parametrize("animation", IDLE_ANIMATIONS)
def test_every_idle_animation_produces_drawable_frames(animation):
    """九个空闲动画每一个都得画得出东西（设计文档 §8-3 的清单）。"""
    animator = CrosshairAnimator(rng=__import__("random").Random(7))
    state = CrosshairState(animation=animation, size=40)
    for frame in _walk(animator, state, 24, 1.0):
        assert _opaque_pixels(_render(frame)) > 0, f"动画 {animation} 出现空白帧"


@pytest.mark.parametrize("animation", ["breathing", "color", "rotate", "wave", "bounce", "blink"])
def test_phase_animations_track_wall_clock_not_frame_count(animation):
    """同一个时刻，24FPS 与 60FPS 必须给出**同一帧**。

    老实现是 `animation_phase += 0.05` **每帧**推进，所以帧率一变动画速度就变。
    R8b 恰好要动帧率策略（静态准心从 tick(1) 改成完全不跑定时器），
    不解耦的话「省一点帧」会顺带把用户的动画调慢——那是没人会想到去查的回退。
    """
    state = CrosshairState(animation=animation, size=40)

    slow = _walk(CrosshairAnimator(), state, 24, 2.0)
    fast = _walk(CrosshairAnimator(), state, 60, 2.0)

    # 两边都取 t=1.0 那一帧（24FPS 的第 24 帧、60FPS 的第 60 帧）
    a, b = slow[24], fast[60]
    assert a.size == b.size
    assert a.thickness == b.thickness
    assert a.color.getRgb() == b.color.getRgb()
    assert abs(a.rotation - b.rotation) < 1e-6
    assert abs(a.center.y() - b.center.y()) < 1e-6


def test_pulse_frequency_is_independent_of_frame_rate():
    """D-5：`pulse` 每秒触发次数不随帧率变。

    老实现写的是「每帧 1% 概率」——那等于把动画频率钉死在 24FPS 上。
    这里换成泊松过程（每帧概率 = 频率 × dt），两个帧率下的期望次数一致。
    """
    import random

    seconds = 4000.0
    counts = {}
    for fps in (24, 60):
        animator = CrosshairAnimator(rng=random.Random(20260809))
        state = CrosshairState(animation="pulse")
        step, starts, last = 1.0 / fps, 0, 0.0
        # ⚠ 必须**边跑边数**：`_walk` 是急切求值，跑完再看 `_pulse_until`
        # 只能看到最后一次的值（第一版判据就是这么写的，数出来恒为 0）
        for i in range(int(seconds * fps)):
            animator.advance(state, i * step)
            if animator._pulse_until != last:
                last = animator._pulse_until
                starts += 1
        counts[fps] = starts

    expected = PULSE_RATE_HZ * seconds
    for fps, got in counts.items():
        assert abs(got - expected) / expected < 0.2, f"{fps}FPS 触发 {got} 次，期望约 {expected}"
    ratio = counts[24] / counts[60]
    assert 0.8 < ratio < 1.25, f"两个帧率触发次数比 {ratio:.2f}，没解耦"


def test_static_crosshair_needs_no_timer_at_all():
    """静态准心不该有定时器——比老实现的 `clock.tick(1)` 再省一步。"""
    assert not CrosshairAnimator.needs_timer(CrosshairState(animation="none"))
    assert CrosshairAnimator.needs_timer(CrosshairState(animation="breathing"))
    assert CrosshairAnimator.needs_timer(CrosshairState(animation="none"), kill_active=True)


def test_dim_no_longer_clamps_away_from_pure_black():
    """老实现给 `dim_color` 加了 `max(1, ...)` 下限，因为纯黑是分层窗口的透明色键。

    Qt 走逐像素 alpha，钳制没有存在意义了。这条断言存档「为什么可以删」，
    并顺带证明**六种可选颜色都不受影响**（都是饱和色，×0.7 后没有一个接近纯黑）。
    """
    from PySide6.QtGui import QColor

    assert dim(QColor(0, 0, 0, 255), 0.7).getRgb()[:3] == (0, 0, 0)  # 老实现会给 (1,1,1)
    for name in COLOR_MAP:
        dimmed = dim(resolve_color(name), 0.7)
        assert max(dimmed.red(), dimmed.green(), dimmed.blue()) >= 178


# ============================================================ D-3 击杀联动

@pytest.mark.parametrize("effect", [e for e in KILL_EFFECTS if e != "none"])
def test_every_kill_effect_draws_something_for_its_whole_duration(effect):
    """十个击杀联动，整个 0.8 秒里每一帧都得画得出东西。

    这里逐帧扫是有必要的：`shatter` 会在 30%/70% 两处切样式、
    `explosion` 的缩放因子在 progress=1 附近会掉到接近 0——
    只抽查首尾帧的话，中段的空白帧根本露不出来。
    """
    animator = CrosshairAnimator(rng=__import__("random").Random(11))
    state = CrosshairState(kill_effect=effect, size=24)
    assert animator.trigger_kill(state, 0.0)

    step = 1.0 / 24
    n = int(KILL_DURATION_S / step)
    blanks = [
        round(i * step, 4)
        for i in range(n)
        if _opaque_pixels(_render(animator.advance(state, i * step))) == 0
    ]
    assert not blanks, f"联动 {effect} 在 t={blanks} 处画出空白帧"


def test_kill_effect_expires_on_its_own():
    """0.8 秒后必须自己停——否则定时器永远停不下来，静态准心也在空转。"""
    animator = CrosshairAnimator()
    state = CrosshairState(kill_effect="pulse")
    animator.trigger_kill(state, 0.0)
    assert animator.kill_active(0.5)
    assert not animator.kill_active(KILL_DURATION_S + 0.01)

    animator.advance(state, KILL_DURATION_S + 0.01)
    assert not CrosshairAnimator.needs_timer(state, animator.kill_active(KILL_DURATION_S + 0.02))


def test_kill_effect_none_never_triggers():
    animator = CrosshairAnimator()
    assert not animator.trigger_kill(CrosshairState(kill_effect="none"), 0.0)
    assert not animator.kill_active(0.1)


@pytest.mark.parametrize("effect", ["rainbow_wave", "neon_wave", "x_overlay"])
def test_overlay_effects_actually_emit_overlays(effect):
    """这三个联动**不改准心本身**，而是另外画环/星辉。

    只断言「画出了非空帧」会漏掉它们——准心本来就在那儿，
    额外图元一个没画也是非空的。所以这条判据盯的是 overlays 通道本身。
    """
    animator = CrosshairAnimator()
    state = CrosshairState(kill_effect=effect, size=24)
    animator.trigger_kill(state, 0.0)
    seen = [len(animator.advance(state, t).overlays) for t in (0.1, 0.3, 0.5)]
    assert all(n > 0 for n in seen), f"{effect} 没产出额外图元: {seen}"


def test_shatter_fragments_are_generated_once_per_kill():
    """碎片在触发那一刻生成，之后只按进度外扩——不能每帧重新随机。

    每帧重随机的话碎片会原地乱抖，而不是往外炸开。
    """
    animator = CrosshairAnimator(rng=__import__("random").Random(3))
    state = CrosshairState(kill_effect="shatter", style="crosshair", size=24)
    animator.trigger_kill(state, 0.0)
    a = animator.advance(state, 0.05).shatter_fragments
    b = animator.advance(state, 0.10).shatter_fragments
    assert a and a == b, "碎片每帧都在重新生成"


def test_kill_effect_stacks_on_top_of_idle_animation():
    """联动叠在空闲动画**之上**（顺序与老实现一致），不是二选一。"""
    animator = CrosshairAnimator()
    state = CrosshairState(animation="breathing", kill_effect="explosion", size=20)
    idle_only = animator.advance(state, 0.2).size
    animator.trigger_kill(state, 0.2)
    with_kill = animator.advance(state, 0.3).size
    assert with_kill > idle_only


# ============================================================ D-6 线程模型

class _FakeKillHandler:
    def __init__(self):
        self.callbacks = []

    def register_kill_callback(self, cb):
        self.callbacks.append(cb)


class _FakeConfig:
    crosshair_size = 20
    crosshair_thickness = 2
    crosshair_color = "green"
    crosshair_style = "crosshair"
    crosshair_animation = "none"
    crosshair_kill_effect = "pulse"
    crosshair_custom_data = []


def test_kill_events_cross_threads_through_a_queued_signal():
    """GSI 事件从**服务器线程**来，Qt 控件只能在主线程碰。

    所以 `on_kill_event` 只许 emit，改状态的活挂在信号槽上由 Qt 排队投递。
    写成 DirectConnection 等于没改——那正好回到 UP-054 的根因
    「在别的线程里动窗口」上。这条判据盯的就是「它确实是个信号」。
    """
    from PySide6.QtCore import SignalInstance

    manager = CrosshairOverlayManager(_FakeConfig())
    try:
        assert isinstance(manager._kill_signal, SignalInstance), (
            "击杀事件不是走信号——跨线程直接改状态会退回 UP-054 的老路"
        )
    finally:
        manager.destroy()
        manager.deleteLater()


#: 调用方持有准心对象时用的变量名（gui_widget / crosshair_page / magnifier_page）
CROSSHAIR_HOLDER_NAMES = {"crosshair_animation", "crosshair_component"}
CROSSHAIR_CALLER_FILES = ("gui_widget.py", "main_widget.py",
                          "pages/crosshair_page.py", "pages/magnifier_page.py")


def _attributes_callers_actually_use():
    """从**真实调用点**反推接口，而不是手写一份名单。

    第一版判据是拿 `hasattr(CrosshairAnimationSystem, name)` 对着手写名单查的，
    当场被 `is_visible` 判红——那是**实例**属性不是类属性，判据自己错了。
    改成扫调用点：名单会跟着代码走，加了新调用也守得住。
    （与 UP-085 同一个道理：判据锚在实现形态上就会误判。）
    """
    def _is_holder(node):
        return isinstance(node, ast.Attribute) and node.attr in CROSSHAIR_HOLDER_NAMES

    used = set()
    for rel in CROSSHAIR_CALLER_FILES:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # 点号访问：self.crosshair_animation.show_crosshair()
            if isinstance(node, ast.Attribute) and _is_holder(node.value):
                used.add(node.attr)
            # 字符串访问：getattr(self.crosshair_animation, "overlay_win", None)
            # —— 第一版只扫点号，`overlay_win` 就这么漏掉了（gui_widget:4091 用的正是它）
            elif (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                    and node.args and _is_holder(node.args[0])
                    and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                used.add(node.args[1].value)
    return used


def test_manager_exposes_everything_the_call_sites_use():
    """Qt 实现必须撑得住调用方现在用到的每一个属性。

    少一个就是运行期 AttributeError——而准心是**打开就用**的功能，
    这种错会直接摔在用户脸上，测试里不接线就更看不见。
    """
    used = _attributes_callers_actually_use()
    assert len(used) >= 6, f"只扫出 {used}，调用点扫描八成失效了"

    manager = CrosshairOverlayManager(_FakeConfig())
    try:
        missing = sorted(name for name in used if not hasattr(manager, name))
        assert not missing, f"Qt 实现缺少调用方要用的: {missing}"
    finally:
        manager.destroy()
        manager.deleteLater()


def test_magnifier_can_save_and_restore_the_whole_crosshair():
    """放大镜进出时要把准心整套存下来再还原（`magnifier_page.py:1568-1574`）。

    它是靠 `getattr(component, 'size'/'thickness'/'color'/'style'/
    'animation_style'/'kill_effect', 默认值)` 读回来的。这六项少一个，
    退出放大镜后准心就被还原成**别的样子**，而且一个错都不报——
    上面那条按调用点扫描的判据正是在接线前抓到了这个。
    """
    manager = CrosshairOverlayManager(_FakeConfig())
    try:
        manager.update_settings(33, 4, "cyan", "circle", "wave", "explosion")
        saved = (manager.size, manager.thickness, manager.color,
                 manager.style, manager.animation_style, manager.kill_effect)
        assert saved == (33, 4, "cyan", "circle", "wave", "explosion")

        # 放大镜期间改成红色小点
        manager.update_settings(5, 5, "red", "dot", "none", "none")
        # 退出还原
        manager.update_settings(*saved)
        assert (manager.size, manager.thickness, manager.color, manager.style,
                manager.animation_style, manager.kill_effect) == saved
    finally:
        manager.destroy()
        manager.deleteLater()


def test_update_settings_accepts_the_keyword_names_callers_use():
    """`magnifier_page` 全部用**关键字**调 `update_settings`，参数名是契约的一部分。

    把 `animation_style` 改成更顺眼的 `animation` 就会当场 TypeError。
    """
    manager = CrosshairOverlayManager(_FakeConfig())
    try:
        manager.update_settings(size=5, thickness=5, color="red", style="dot",
                                animation_style="none", kill_effect="none")
        assert manager.style == "dot"
    finally:
        manager.destroy()
        manager.deleteLater()


def test_kill_event_is_ignored_while_hidden():
    """准心没显示时收到击杀不该起动画——老实现也是这个行为。"""
    manager = CrosshairOverlayManager(_FakeConfig())
    try:
        manager.on_kill_event(True)
        assert not manager._animator.kill_active(manager._now())
    finally:
        manager.destroy()
        manager.deleteLater()


def test_register_kill_handler_wires_the_callback():
    manager = CrosshairOverlayManager(_FakeConfig())
    handler = _FakeKillHandler()
    try:
        manager.register_kill_handler(handler)
        assert manager.on_kill_event in handler.callbacks
    finally:
        manager.destroy()
        manager.deleteLater()


def test_static_crosshair_leaves_no_timer_running():
    """静态准心不跑定时器（设计文档 §5-3）——这是比老实现 tick(1) 更省的一步。"""
    manager = CrosshairOverlayManager(_FakeConfig())
    try:
        manager.update_settings(20, 2, "green", "crosshair", "none", "none")
        assert not manager._timer.isActive()
        manager.update_settings(20, 2, "green", "crosshair", "breathing", "none")
        manager._visible = True
        manager._sync_timer()
        assert manager._timer.isActive()
    finally:
        manager.destroy()
        manager.deleteLater()


# ============================================================ D-6 灰度开关与回退

def test_renderer_defaults_to_qt_after_live_verification():
    """R8b-E：默认值已翻到 `qt`。

    翻之前跑了 22 项真窗口验收（`scripts/verify_r8b_live.py`）：几何偏差 0px、
    点击穿透实测、Z 序高于非置顶全屏窗口、全程不抢前台焦点、
    4 样式/6 色/9 动画/10 联动逐帧有像素；外加整软件真机跑测 + pygame 对照组。

    这条断言的作用不是"锁死 qt"，而是让**回退成为一次显式修改**——
    真出问题时改回 `pygame` 会同时改红这里，谁改的、为什么改，一眼能看见。

    ⚠ 判据必须**读源码里的默认值**，不能构造 `Config()` 去读属性：
    `Config.__init__` 会加载配置文件，而测试隔离目录里存着上一轮跑出来的值。
    第一版就是那么写的——它测的是**持久化的值**，不是默认值，
    翻默认值那次当场判红才暴露出来（此前"通过"只是碰巧两者相同）。
    """
    import ast

    tree = ast.parse((REPO / "config.py").read_text(encoding="utf-8"))
    found = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Attribute) and target.attr == "crosshair_renderer"
        and isinstance(target.value, ast.Name) and target.value.id == "self"
    ]
    assert found == ["qt"], f"config.py 里的默认值是 {found}，期望 ['qt']"


@pytest.mark.parametrize("renderer,expected", [
    ("qt", "CrosshairOverlayManager"),
    ("pygame", "CrosshairAnimationSystem"),
    ("", "CrosshairAnimationSystem"),          # 空串按老实现走，别崩
    ("Qt", "CrosshairOverlayManager"),         # 大小写不该决定用户拿到哪套渲染器
])
def test_renderer_flag_picks_the_right_implementation(renderer, expected):
    """两条路都必须是**活的**——留着但已经烂掉的回退路等于没有回退路。"""
    import gui_widget

    class _Cfg(_FakeConfig):
        crosshair_renderer = renderer

    made = {}

    class _Stub:
        logger = __import__("logging").getLogger("stub")

        def _create_crosshair_renderer(self, cfg):
            return gui_widget.MainWindow._create_crosshair_renderer(self, cfg)

    obj = _Stub()._create_crosshair_renderer(_Cfg())
    made["name"] = type(obj).__name__
    try:
        assert made["name"] == expected
    finally:
        if hasattr(obj, "deleteLater"):
            obj.destroy()
            obj.deleteLater()


def test_new_renderer_is_packaged_exactly_like_the_old_one():
    """打包可达性：新渲染器必须和老渲染器被打包链**同等对待**。

    两者都是从 `gui_widget.py` 里**函数级** import 的根模块。今天
    `crosshair_animation` / `screen_effect_overlay` 都不在 hiddenimports 里
    却照样进包（PyInstaller 自己的静态分析能看见函数体里的 import），
    所以 `crosshair_overlay` 不需要特殊照顾。

    本轮已实跑打包核实：PYZ 归档里 `crosshair_overlay` 与 `crosshair_animation`
    同在。这条判据守的是**将来**——万一有人把老的加进某张名单而忘了新的，
    打包版会只在 `crosshair_renderer=qt` 时炸，源码跑一切正常。
    """
    import sys as _sys

    _sys.path.insert(0, str(REPO / "build_tools"))
    try:
        import build_release
    finally:
        _sys.path.pop(0)

    hidden = set(build_release.collect_local_hidden_imports(REPO, REPO))
    obfuscated = set(build_release.DEFAULT_OBFUSCATE_TARGETS)
    critical = set(build_release.CRITICAL_LOCAL_MODULES)

    for bucket, name in ((hidden, "hiddenimports"),
                         (critical, "CRITICAL_LOCAL_MODULES")):
        assert ("crosshair_overlay" in bucket) == ("crosshair_animation" in bucket), (
            f"两个准心渲染器在 {name} 里待遇不一致——打包版会只在一条路径上炸"
        )
    assert ("crosshair_overlay.py" in obfuscated) == ("crosshair_animation.py" in obfuscated)


def test_pygame_path_is_still_constructible():
    """D-6：老实现要保留一个发布周期，且必须还能真的建起来。"""
    from crosshair_animation import CrosshairAnimationSystem

    system = CrosshairAnimationSystem(_FakeConfig(), None)
    assert system.is_visible is False
    assert system.overlay_win is None


# ============================================================ D-4 窗口属性齐全

def test_window_recipe_is_complete():
    """五个 Qt 标志 + 三个 Qt 属性，缺一项就破「不打扰前台」。

    少 `WA_ShowWithoutActivating` → 准心一出现就抢焦点，把全屏游戏切出去；
    少 `WA_TransparentForMouseEvents` / `WindowTransparentForInput` →
    准心正好盖在屏幕正中，会吃掉那一片的鼠标点击。
    """
    win = CrosshairOverlayWindow()
    try:
        flags = win.windowFlags()
        for name in ("FramelessWindowHint", "WindowStaysOnTopHint", "Tool",
                     "WindowTransparentForInput", "WindowDoesNotAcceptFocus"):
            flag = getattr(Qt, name, None) or getattr(Qt.WindowType, name, None)
            assert flag is not None, f"这个 Qt 版本找不到 {name}"
            assert flags & flag, f"窗口缺少标志 {name}"

        for attr in ("WA_TranslucentBackground", "WA_ShowWithoutActivating",
                     "WA_TransparentForMouseEvents"):
            assert win.testAttribute(getattr(Qt, attr)), f"窗口缺少属性 {attr}"

        assert not win.isVisible(), "叠加层不该在构造时就显示出来"
    finally:
        win.deleteLater()


def test_window_paints_without_a_screen_mapping():
    """窗口要能在不映射到屏幕的情况下完成绘制。

    这既是测试环境的需要，也是「不打扰前台」的底线：
    任何自动化验收都不该让准心真的闪到用户屏幕上。
    """
    win = CrosshairOverlayWindow()
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.resize(CANVAS_PX, CANVAS_PX)
        win.set_frame(CrosshairFrame(style="crosshair", size=40,
                                     center=QPointF(CANVAS_PX / 2, CANVAS_PX / 2)))
        win.show()
        win.repaint()
        assert win.isVisible()
    finally:
        win.close()
        win.deleteLater()
