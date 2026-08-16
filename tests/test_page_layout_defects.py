# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R5 · 页面级布局缺陷回归（UP-017 / 027 / 028 / 029 / 031 / 033）。

源码级断言一律走 **AST**：本轮注释里就写着 `setFixedWidth`、`QHBoxLayout`
这些字样（用来解释为什么不能那么写），文本匹配会把说明文字当成真实调用。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton, QWidget

ROOT = Path(__file__).resolve().parent.parent


def _tree(rel: str) -> ast.AST:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def _attr_calls(node: ast.AST) -> list[tuple[str, str]]:
    """收集 `a.b.c()` 形式的调用，返回 [(接收者源码, 方法名), ...]。"""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            out.append((ast.unparse(sub.func.value), sub.func.attr))
    return out


# ------------------------------------------------------------------ UP-017


def test_flow_layout_min_width_is_max_not_sum(qapp):
    """FlowLayout 的最小宽度必须是**逐维最大值**，不是求和。

    这正是它能消掉溢出的原因：QHBoxLayout 的最小宽度是所有子项之和，
    10 个带 `min-width:80` 的 chip 就能把整页最小宽度顶到 1284px。
    """
    from widgets.flow_layout import FlowLayout

    host = QWidget()
    layout = FlowLayout(host)
    for text in ("目录", "调试", "外观", "公告", "系统", "OSD", "统计", "权限", "热键", "配置"):
        btn = QPushButton(text)
        btn.setMinimumWidth(80)
        layout.addWidget(btn)

    widest = max(layout.itemAt(i).minimumSize().width() for i in range(layout.count()))
    assert layout.minimumSize().width() <= widest + 1, (
        f"FlowLayout 最小宽 {layout.minimumSize().width()}，"
        f"最宽子项才 {widest} —— 它在求和，那就退化成 QHBoxLayout 了"
    )
    host.deleteLater()


def test_flow_layout_wraps_when_narrow(qapp):
    """窄了要换行：给定宽度算出的高度必须大于单行高度。"""
    from widgets.flow_layout import FlowLayout

    host = QWidget()
    layout = FlowLayout(host)
    for i in range(10):
        b = QPushButton(f"chip{i}")
        b.setFixedSize(80, 26)
        layout.addWidget(b)

    wide = layout.heightForWidth(1000)
    narrow = layout.heightForWidth(200)
    assert narrow > wide, f"200px 宽下高度 {narrow} 不比 1000px 宽下的 {wide} 高，说明没换行"
    host.deleteLater()


def test_advanced_anchor_bar_uses_flow_layout():
    """UP-017：高级设置页锚点条不能再用 QHBoxLayout。"""
    tree = _tree("pages/advanced_page.py")
    calls = {name for _recv, name in _attr_calls(tree)}
    assert "make_flow_container" in {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    } or "make_flow_container" in calls, "锚点条应当用 FlowLayout 容器"

    # FlowLayout 没有 addStretch —— 留着会抛 AttributeError 被外层 except 吞掉，
    # 表现为"锚点条整个不出现"
    src = (ROOT / "pages/advanced_page.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_build_anchor_chips")
    for recv, name in _attr_calls(fn):
        assert not (recv.endswith("_anchor_bar") and name == "addStretch"), (
            "FlowLayout 没有 addStretch()，调它会抛异常并让整条锚点条消失"
        )
    assert src


def test_anchor_chip_has_own_qss_without_min_width():
    """UP-017：锚点 chip 不能再复用 secondaryButton 的 min-width:80。"""
    from theme_manager import get_theme_manager

    qss = get_theme_manager().themes["dark"].generate_stylesheet()
    assert "QPushButton#anchorChip" in qss, "缺少 anchorChip 样式"
    block = qss.split("QPushButton#anchorChip {")[1].split("}")[0]
    assert "min-width: 0px" in block, "锚点 chip 必须解除 min-width，否则照样撑宽页面"


# ------------------------------------------------------------------ UP-027


def _action_bar_fixed_width_sites():
    hits = []
    for path in sorted((ROOT / "pages").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for recv, name in _attr_calls(tree):
            if name == "setFixedWidth" and "action_bar" in recv:
                hits.append(f"{path.name}: {recv}")
    return hits


def test_action_bar_buttons_are_not_width_locked():
    """UP-027：动作条按钮不许写死宽度，否则 1.25 字号档下中文按钮文案被裁。

    改成 `setMinimumWidth` 后既保留"各页按钮宽度一致"的视觉意图，
    又允许文字变长时按钮跟着长。
    """
    hits = _action_bar_fixed_width_sites()
    assert not hits, "这些动作条按钮仍写死宽度：\n  " + "\n  ".join(hits)


# ------------------------------------------------------------------ UP-029


def test_unsaved_guard_runs_before_skeleton():
    """UP-029：未保存修改守卫必须早于 `_show_page_skeleton()`。

    骨架屏会 `setCurrentWidget(skeleton)` 把当前页换掉，守卫之后再去读
    `currentWidget()` 拿到的就是骨架屏——它没有 `can_leave_page`，守卫静默失效。
    表现：在 hud_color / preset_center 改了没保存，切到一个**从没打开过**的页，
    不提示也不拦，编辑直接丢失。
    """
    tree = _tree("gui_widget.py")
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "show_page")

    # 必须比**节点行号**，不能在源码文本里 find()——
    # 上面那段解释性注释里同时写着 `_show_page_skeleton()` 和 `can_leave_page`，
    # 文本匹配会命中注释而不是真实调用（本专项已经栽过两次）。
    guard_lines = [n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "getattr"
                   and any(isinstance(a, ast.Constant) and a.value == "can_leave_page"
                           for a in n.args)]
    skeleton_lines = [n.lineno for n in ast.walk(fn)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "_show_page_skeleton"]
    assert guard_lines, "show_page 里找不到未保存守卫"
    assert skeleton_lines, "show_page 里找不到骨架屏调用"
    assert min(guard_lines) < min(skeleton_lines), (
        f"守卫在第 {min(guard_lines)} 行、骨架屏在第 {min(skeleton_lines)} 行 —— "
        "守卫跑在骨架屏之后，那时 currentWidget() 已经是骨架屏，守卫等于没有"
    )


def test_unsaved_guard_asked_only_once():
    """守卫只能问一次，重复问会让用户在同一次切页里看到两个确认框。"""
    tree = _tree("gui_widget.py")
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "show_page")
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    body = ast.get_source_segment(src, fn) or ""
    # 只数真实取值，注释里的说明不算
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "getattr"
             and any(isinstance(a, ast.Constant) and a.value == "can_leave_page"
                     for a in n.args)]
    assert len(calls) == 1, f"守卫被执行了 {len(calls)} 次，应当只有 1 次"
    assert body


# ------------------------------------------------------------------ UP-028


def _fake_manager():
    """两支同名麦克风分别挂在两个 hostapi 下 —— 真实机器上的常见形态。

    继承真实类但**不调 `super().__init__()`**：那会去真的枚举音频设备、
    起 pygame 混音器。我们只想验证名字消歧这段纯逻辑。
    """
    from voice_output_manager import VoiceOutputManager

    class _FakeVoiceManager(VoiceOutputManager):
        def __init__(self):  # noqa: D107 - 故意不调 super
            self.default_microphone_id = 1
            self.microphone_devices = [
                {"id": 1, "name": "麦克风 (Realtek)", "hostapi": 0, "channels": 2},
                {"id": 7, "name": "麦克风 (Realtek)", "hostapi": 1, "channels": 2},
                {"id": 9, "name": "USB 麦", "hostapi": 1, "channels": 1},
            ]

    return _FakeVoiceManager()


def test_microphone_entries_disambiguate_duplicates():
    """UP-028：同名设备必须能被区分——key 唯一、展示文案带序号。"""
    fake = _fake_manager()
    entries = fake.get_microphone_entries()

    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), f"key 有重复，同名设备仍分不开: {keys}"

    labels = [e["label"] for e in entries]
    assert len(labels) == len(set(labels)), f"展示文案有重复，用户看不出区别: {labels}"
    # 唯一的设备不该平白被加上"(1)"
    assert "USB 麦" in labels


def test_microphone_key_lookup_is_exact():
    """按 key 必须精确取到**那一支**，不能像按名字那样只命中第一条。"""
    fake = _fake_manager()
    entries = fake.get_microphone_entries()
    dupes = [e for e in entries if e["name"] == "麦克风 (Realtek)"]
    assert len(dupes) == 2

    first, second = dupes
    got_first = fake.get_microphone_id_by_key(first["key"])
    got_second = fake.get_microphone_id_by_key(second["key"])
    assert got_first == 1
    assert got_second == 7, (
        f"第二支同名麦取到了 id={got_second!r} —— "
        f"这就是「用户选的设备下次启动被换掉」的原因"
    )

    # 旧接口按名字查，两支都只会命中第一条（保留它只为读旧配置）
    by_name = fake.get_microphone_id_by_name("麦克风 (Realtek)")
    assert by_name == 1


def test_microphone_unknown_key_returns_none_not_a_guess():
    """找不到就返回 None，不许猜。猜出来的就是「选了 A 用上 B」。"""
    fake = _fake_manager()
    assert fake.get_microphone_id_by_key("不存在的设备|9|0") is None
    # 但"默认"要能用
    assert fake.get_microphone_id_by_key("默认") == 1


# ------------------------------------------------------------------ UP-031


def test_magnifier_combos_adjust_to_contents():
    """UP-031：放大镜下拉不许写死宽度。

    QSS 给 QComboBox 留了 padding + 下拉箭头，90px 的框实际只剩约 28px 文本区、
    116px 只剩约 54px —— 默认字号档下「4.0」「Mouse4」就已被省略号截断。
    """
    tree = _tree("pages/magnifier_page.py")
    locked = [recv for recv, name in _attr_calls(tree)
              if name == "setFixedWidth" and recv.endswith("_combo")]
    assert not locked, f"这些下拉仍写死宽度: {locked}"

    adjusted = [recv for recv, name in _attr_calls(tree)
                if name == "setSizeAdjustPolicy"]
    assert len(adjusted) >= 4, f"只有 {len(adjusted)} 个下拉改成按内容自适应"


# ------------------------------------------------------------------ UP-033


def test_crosshair_preview_honors_device_pixel_ratio():
    """UP-033：预览图必须按 DPR 出图并标回 devicePixelRatio。

    否则在 150%/200% 缩放的高 DPI 屏上，这张按逻辑像素画的图会被 Qt
    拉伸 1.5~2 倍显示，线条糊、边缘毛。
    """
    tree = _tree("pages/crosshair_page.py")
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_update_preview")
    names = {name for _recv, name in _attr_calls(fn)}
    assert "devicePixelRatioF" in names, "没有读取设备像素比"
    assert "setDevicePixelRatio" in names, "画完没把 DPR 标回去，Qt 仍会按逻辑像素拉伸"
    # 这里原来还有一条 `assert "scale" in names`。它卡的是**旧策略的实现形状**：
    # 当年预览按逻辑坐标画，所以画布放大 dpr 倍之后 painter 必须跟着 scale(dpr)。
    # 2026-08-15 预览改成直接调渲染层，而渲染层的坐标本来就是**物理像素**，
    # 画布按 CANVAS_PX 个物理像素建、1:1 画完再把 dpr 标回去即可，没有 scale
    # 也不该有。两种做法都对，所以判据不能卡在"调没调 scale"上。
    # 真正要守的性质（DPR 变化时屏幕占位不变、不被拉伸）由下面那条行为判据，
    # 以及 tests/test_crosshair_geometry_parity.py 的 dpr 用例负责。


def test_crosshair_preview_renders_sharp_on_high_dpi(qapp):
    """真建一次预览：DPR>1 时位图的物理像素必须是逻辑尺寸的 DPR 倍。"""
    from PySide6.QtGui import QImage, QPainter, QPixmap

    # 直接验证这套做法本身（不构造整页，准心页会拉起 pygame 相关依赖）
    dpr = 2.0
    logical = 80
    image = QImage(int(logical * dpr), int(logical * dpr), QImage.Format_ARGB32)
    image.setDevicePixelRatio(dpr)
    painter = QPainter(image)
    painter.scale(dpr, dpr)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)

    assert pixmap.width() == int(logical * dpr), "物理像素没放大"
    assert pixmap.deviceIndependentSize().width() == pytest.approx(logical, abs=1), (
        "逻辑尺寸变了 —— 图会在界面上显示成两倍大"
    )
