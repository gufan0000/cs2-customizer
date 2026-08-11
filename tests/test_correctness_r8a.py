# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R8a 正确性与数据安全回归（UP-070/072/073/074/075 + UP-071 的 about 页）。

这批用例的共同点：被修的缺陷**此前都在"绿灯"下存活了很久**——
要么异常被 except 吞掉（UP-074），要么判据根本没覆盖那个维度（UP-072/071），
要么测试只断言了 objectName 相等、没断言样式存在（UP-073）。
所以这里的断言尽量往"真实构造 + 真实产物"上打，别只读源码文本。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from core import config_snapshot_manager as snap_mod


ROOT = Path(__file__).resolve().parent.parent


def _strip_qss_comments(qss: str) -> str:
    """剥掉 /* */ 注释再做文本断言。

    R7 栽过：theme_manager 模板里的注释会**原样进入 QSS 产物**，
    于是 "QSS 里有没有 X" 的断言命中的是解释这件事的注释本身。
    """
    return re.sub(r"/\*.*?\*/", "", qss, flags=re.S)


# ---------------------------------------------------------------- UP-075

def _snapshot_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"

    class _CfgObj:
        def save_config_now(self):
            return None

        def load_config(self):
            return None

    monkeypatch.setattr(snap_mod, "config", _CfgObj())
    monkeypatch.setattr(snap_mod, "get_config_dir", lambda: str(cfg_dir))
    monkeypatch.setattr(snap_mod, "get_config_path", lambda: str(cfg_file))
    return cfg_file


def test_restore_snapshot_is_itself_undoable(tmp_path, monkeypatch):
    """UP-075：恢复前必须先给"当前配置"建快照，否则「恢复」本身不可回滚。"""
    cfg_file = _snapshot_env(tmp_path, monkeypatch)

    cfg_file.write_text(json.dumps({"v": "old"}), encoding="utf-8")
    old_snap = snap_mod.create_snapshot("old")

    cfg_file.write_text(json.dumps({"v": "current"}), encoding="utf-8")

    result = snap_mod.restore_snapshot(old_snap.snapshot_id)
    assert result.ok
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["v"] == "old"

    # 关键：恢复动作自己也要留下后悔药
    assert result.backup_id, "恢复前没有为当前配置建快照——此次恢复不可撤销"

    back = snap_mod.restore_snapshot(result.backup_id)
    assert back.ok
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["v"] == "current", (
        "用恢复前快照回滚后没拿回原配置"
    )


def test_restore_snapshot_leaves_no_temp_file(tmp_path, monkeypatch):
    """原子替换的临时文件不能残留——**成功路径和失败路径都不许留**。

    ⚠ 这条用例的第一版只测了成功路径，而成功路径下 `os.replace` 本来就会把临时文件
    消费掉，所以哪怕把整个 finally 清理删掉它也照样绿。对抗复核指出后补了失败路径。
    """
    cfg_file = _snapshot_env(tmp_path, monkeypatch)
    cfg_file.write_text(json.dumps({"v": 1}), encoding="utf-8")
    snap = snap_mod.create_snapshot("s")
    cfg_file.write_text(json.dumps({"v": 2}), encoding="utf-8")

    assert snap_mod.restore_snapshot(snap.snapshot_id).ok
    leftovers = list(cfg_file.parent.glob("*.restore.tmp"))
    assert not leftovers, f"成功路径残留临时文件: {leftovers}"

    # 失败路径：copy2 成功、os.replace 抛异常 —— 临时文件必须被清掉
    def _boom(src, dst):
        raise OSError("模拟替换失败")

    monkeypatch.setattr(snap_mod.os, "replace", _boom)
    result = snap_mod.restore_snapshot(snap.snapshot_id)
    assert not result.ok
    leftovers = list(cfg_file.parent.glob("*.restore.tmp"))
    assert not leftovers, f"失败路径残留临时文件: {leftovers}"


def test_restore_rejects_corrupted_snapshot(tmp_path, monkeypatch):
    """快照文件损坏时必须拒绝恢复，而不是把坏内容写进 config.json 还报成功。"""
    cfg_file = _snapshot_env(tmp_path, monkeypatch)
    cfg_file.write_text(json.dumps({"v": "good"}), encoding="utf-8")
    snap = snap_mod.create_snapshot("s")

    # 模拟同步冲突/断电把快照截断
    Path(snap.file_path).write_text('{"v": "trun', encoding="utf-8")
    cfg_file.write_text(json.dumps({"v": "current"}), encoding="utf-8")

    result = snap_mod.restore_snapshot(snap.snapshot_id)
    assert not result.ok, "损坏的快照被当成好的恢复了"
    assert "checksum" in result.error or "JSON" in result.error
    # 关键：用户当前的配置一个字节都不能被动
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["v"] == "current"


def test_restore_stays_ok_when_reload_fails(tmp_path, monkeypatch):
    """文件已经换好了就不能报"恢复失败"——那会让用户以为可以继续用旧值。"""
    cfg_file = _snapshot_env(tmp_path, monkeypatch)
    cfg_file.write_text(json.dumps({"v": "old"}), encoding="utf-8")
    snap = snap_mod.create_snapshot("s")
    cfg_file.write_text(json.dumps({"v": "current"}), encoding="utf-8")

    class _CfgBoom:
        def save_config_now(self):
            return None

        def load_config(self):
            raise ValueError("模拟重载失败")

    monkeypatch.setattr(snap_mod, "config", _CfgBoom())

    result = snap_mod.restore_snapshot(snap.snapshot_id)
    assert result.ok, "磁盘上已经换成快照了，却报恢复失败"
    assert result.error, "重载失败必须如实告知（降级为 warning，不是静默）"
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["v"] == "old"


def test_restore_without_existing_config_reports_no_backup(tmp_path, monkeypatch):
    """没有 config.json 时不该假装建了后悔药——backup_id 必须为空。"""
    cfg_file = _snapshot_env(tmp_path, monkeypatch)
    cfg_file.write_text(json.dumps({"v": 1}), encoding="utf-8")
    snap = snap_mod.create_snapshot("s")
    cfg_file.unlink()

    result = snap_mod.restore_snapshot(snap.snapshot_id)
    assert result.ok
    assert result.backup_id == ""


# ---------------------------------------------------------------- UP-074

def test_theme_manager_has_no_chip_text_attribute():
    """`_chip_text` 是 Theme 的方法，ThemeManager 上没有。

    这条断言是"缺陷为什么能长期存活"的存档：调用点被 try/except 包着，
    AttributeError 每次都被吞掉，于是那段代码从写下起就没执行过而无人察觉。
    """
    from theme_manager import Theme, ThemeManager

    assert hasattr(Theme, "_chip_text")
    assert not hasattr(ThemeManager, "_chip_text")


def test_gui_widget_does_not_call_chip_text_on_manager():
    """用 AST 而不是文本匹配——避免命中解释这件事的注释（R7 栽过四次）。"""
    tree = ast.parse((ROOT / "gui_widget.py").read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "_chip_text":
            continue
        owner = node.value
        # self.theme_manager._chip_text(...) —— 挂在 manager 上就是错的
        if isinstance(owner, ast.Attribute) and owner.attr == "theme_manager":
            bad.append(node.lineno)
    assert not bad, f"gui_widget 第 {bad} 行仍在 ThemeManager 上调 _chip_text"


# 注：这里原本还有一条「账号入口按钮字色过 AA」的判据（真建窗口、真调
# `_apply_account_button_style`、从 stylesheet 产物里取字色）。开源裁剪把账号入口
# 整条链路去掉了，判据没有被测对象，随功能一并移除。


# ---------------------------------------------------------------- UP-073

# 全站能被派到按钮上的 objectName。原先这份名单是从 `widgets.app_button`
# 的 `_VARIANT_OBJECT_NAMES` 读的，R8-W5 把零引用的 AppButton 删掉之后
# 改为在这里显式列出——**故意不从产品代码推导**：判据一旦回去读被测代码
# 自己的声明，就又变成同义反复（R8a 在对比度判据上栽过一次，见 README
# 「判据的判据」）。新增按钮语义时手动往这张表里加一行。
_BUTTON_OBJECT_NAMES = (
    "primaryButton",    # page_theme_helper.style_as_primary_button
    "secondaryButton",  # page_theme_helper.style_as_secondary_button
    "dangerButton",     # page_theme_helper.style_as_danger_button
    "ghostButton",      # page_theme_helper.style_as_ghost_button
    "actionButton",     # ui_style_applier 的兜底派名
    "iconButton",       # 各页图标按钮
)


def test_every_button_object_name_has_qss_rules():
    """UP-073：任何会被派到按钮上的 objectName 都必须在 QSS 里有规则。

    此前的测试只断言 `AppButton.ghost("d").objectName() == "ghostButton"`，
    而 QSS 里一条 `#ghostButton` 都没有——断言全绿，按钮却完全没样式。
    """
    from theme_manager import ThemeManager

    tm = ThemeManager()
    for theme_name, theme in tm.themes.items():
        if theme_name == "minimal":
            continue  # 走系统原生样式，不生成组件级 QSS
        qss = _strip_qss_comments(theme.generate_stylesheet())
        for object_name in _BUTTON_OBJECT_NAMES:
            assert f"#{object_name}" in qss, (
                f"{theme_name} 主题的 QSS 里没有 #{object_name}"
                f"（会产出一颗完全没样式的按钮）"
            )


# ---------------------------------------------------------------- UP-070

@pytest.mark.parametrize(
    "text",
    ["删除全部记录", "移除设备", "保存设置", "确定", "取消", "关闭窗口", "delete all"],
)
def test_style_applier_never_guesses_semantics_from_text(text):
    """UP-070：语义色必须声明，不能按文案猜。

    按文案猜的两头都会错：「删除本地缓存」（可再生）被染红，
    而「重置所有设置」（当场不可逆）因为没写"删"字反而是灰的。
    """
    from PySide6.QtWidgets import QPushButton

    from ui_style_applier import StyleApplier

    button = QPushButton(text)
    StyleApplier()._style_button(button)
    assert button.objectName() == "actionButton", (
        f"「{text}」被按文案猜成了 {button.objectName()}"
    )


def test_style_manager_dialog_constructs_with_danger_button():
    """R7 在这个对话框里加了 style_as_danger_button(...) 却漏了 import ——
    打开"风格管理"会当场 NameError。

    能活下来是因为：R7 量"红按钮几个"时只构造了**页面**，没构造对话框；
    而 ruff 的 F821 早报了，只是 CI 的 lint 步骤本来就红着（13 处既有错误），
    真信号被噪声埋了。所以这里既补构造断言，也把 lint 清到零。
    """
    from dialogs.style_manager_dialog import StyleManagerDialog

    dialog = StyleManagerDialog("kill_sound", "击杀音效", ["风格A", "风格B"])
    try:
        assert dialog.delete_btn.objectName() == "dangerButton"
    finally:
        dialog.deleteLater()


def test_style_applier_respects_explicit_object_name():
    from PySide6.QtWidgets import QPushButton

    from ui_style_applier import StyleApplier

    button = QPushButton("删除")
    button.setObjectName("dangerButton")
    StyleApplier()._style_button(button)
    assert button.objectName() == "dangerButton"


# ---------------------------------------------------------------- UP-071 / 072

def test_about_page_content_is_scrollable():
    """UP-071：about 页整页没有滚动区，1200×800 下内容够不到也滚不动。"""
    from PySide6.QtWidgets import QScrollArea

    from pages.about_page import AboutPage

    page = AboutPage()
    try:
        scrolls = page.findChildren(QScrollArea)
        assert scrolls, "about 页没有滚动区——窗口变矮时下半截无法触达"
    finally:
        page.deleteLater()


def test_layout_audit_has_a_vertical_criterion():
    """UP-072：审计脚本必须真的有纵向判据。

    「某某维度全绿」只有在那个维度真有判据时才有意义——
    about 页正是因为纵向无判据才长期无人发现。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_layout_audit", ROOT / "scripts" / "layout_overflow_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "_vertical_clip_of")


def test_vertical_criterion_catches_unscrollable_overflow():
    """判据本身要能抓到人造的"装不下且滚不动"。"""
    import importlib.util

    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    spec = importlib.util.spec_from_file_location(
        "_layout_audit2", ROOT / "scripts" / "layout_overflow_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QScrollArea

    app = QApplication.instance()

    def _build(height):
        """真的给几何、真的布局——判据里 `min(avail_h, scope.height())` 依赖真实高度。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        for _ in range(10):
            label = QLabel("x")
            label.setMinimumHeight(100)
            layout.addWidget(label)
        page.setAttribute(Qt.WA_DontShowOnScreen, True)
        page.resize(600, height)
        page.show()
        app.processEvents()
        return page

    tight = _build(300)
    roomy = _build(5000)
    try:
        # 需要 1000+ px，只给 300px，且没有滚动区
        assert module._vertical_clip_of(tight, 300) is not None
        # 给足空间就不该报
        assert module._vertical_clip_of(roomy, 5000) is None
    finally:
        tight.deleteLater()
        roomy.deleteLater()

    # 回归 R8a 复核查出的两个漏：判据此前对这两种形状都恒返回 None
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()
    inner_layout = QVBoxLayout(inner)
    for _ in range(30):
        lbl = QLabel("x")
        lbl.setMinimumHeight(100)
        inner_layout.addWidget(lbl)
    sa.setWidget(inner)
    sa.setAttribute(Qt.WA_DontShowOnScreen, True)
    sa.resize(600, 414)
    sa.show()
    app.processEvents()
    try:
        # ① 范围本身就是滚动区（utility 的两个页签就是）：
        #    findChildren 不含自身，旧实现会去量滚动区外壳的 minimumSizeHint(恒 ~60px)
        assert module._vertical_clip_of(sa, 414) is not None, "scope 自身是滚动区时判据失效"
    finally:
        sa.deleteLater()

    # ② 页头很高 + 一个能滚的滚动区：
    #    旧实现"只要找到能滚的滚动区就整体 return None"，滚动区之外的固定内容被压扁看不见
    page2 = QWidget()
    lay2 = QVBoxLayout(page2)
    head = QLabel("页头")
    head.setMinimumHeight(900)
    lay2.addWidget(head)
    sa2 = QScrollArea()
    sa2.setWidgetResizable(True)
    sa2.setWidget(QWidget())
    lay2.addWidget(sa2, 1)
    page2.setAttribute(Qt.WA_DontShowOnScreen, True)
    page2.resize(600, 750)
    page2.show()
    app.processEvents()
    try:
        assert module._vertical_clip_of(page2, 750) is not None, "滚动区之外的固定内容被压扁却漏报"
    finally:
        page2.deleteLater()
