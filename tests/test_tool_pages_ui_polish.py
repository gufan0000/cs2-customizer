# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QBoxLayout, QSizePolicy

from config import config
from core.audio.audio_event_timeline import AudioEvent, get_audio_event_timeline
from core.audio.special_events import events_in_group
from core.config_snapshot_manager import SnapshotMeta

#: 回合事件的**分母拿事件表现算**，不写死。
#: 写死分母的代价见 core/audio/special_events 的模块 docstring：加事件时它不会
#: 报错，只会让"已选 4/5"这类文案悄悄对不上真实数量。
_ROUND_EVENT_COUNT = len(events_in_group("round"))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _visible_audio_status_chip_texts(status_bar) -> list[str]:
    layout = status_bar.layout()
    if layout is None:
        return []
    texts: list[str] = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            texts.append(widget.text())
    return texts


def test_audio_health_page_uses_status_badges(qapp, monkeypatch):
    import pages.audio_health_page as health_page_module

    report = {
        "audio": {"summary": {"ok": True}},
        "visual": {"summary": {"ok": False}},
        "summary": {
            "ok": False,
            "missing_directories": 1,
            "invalid_config_refs": 2,
            "empty_style_dirs": 0,
        },
    }

    monkeypatch.setattr(health_page_module, "collect_resource_system_health", lambda: report)
    monkeypatch.setattr(health_page_module, "format_resource_system_health", lambda _r: "health-report")
    monkeypatch.setattr(
        health_page_module,
        "apply_conservative_resource_fix",
        lambda: {
            "before": report,
            "after": report,
            "created_visual_directories": [],
            "audio_fix": {
                "created_directories": [],
                "reset_config_keys": [],
            },
        },
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)

    page = health_page_module.AudioHealthPage()

    # 体检扫描已改为后台线程（对标修缮：切页不再卡 UI）——等待报告渲染完成
    deadline = time.time() + 5.0
    while page._last_report is None and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert page._last_report is not None, "后台体检 5 秒内未完成"

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert "体检 · 发现问题" in chips
    assert "音频 · 正常" in chips
    assert "视觉 · 检查" in chips
    assert "项目 · 3 项" in chips
    assert "3" in page.summary_label.toolTip()
    assert "health-report" in page.report_text.toPlainText()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "立即体检"
    assert page.action_bar.primary_btn.text() == "一键修复（保守）"
    assert "当前状态：发现 3 项问题" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_advanced_page_action_bar_tracks_directory_state(qapp, monkeypatch, tmp_path):
    import pages.advanced_page as advanced_page_module

    valid_dir = tmp_path / "cs2"
    (valid_dir / "game" / "csgo" / "cfg").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(advanced_page_module, "find_cfg_path", lambda: "")
    # RN-141：调试徽章按界面模式显示（RN-138）。这条判据断言 4 颗，
    # 就必须自己把模式钉住 —— 否则它绿不绿取决于**同一次运行里前面跑过谁**
    # （共享配置目录跨文件累积，好几支测试会把专家模式存盘）。
    monkeypatch.setattr(config, "ui_expert_mode", True, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "csgo_dir", "", raising=False)
    monkeypatch.setattr(config, "ui_theme", "dark", raising=False)
    monkeypatch.setattr(config, "debug_mode", False, raising=False)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args, **_kwargs: 0)

    page = advanced_page_module.AdvancedPage()

    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert "目录 · 未设置" in chips
    assert page.action_bar.secondary_btn.text() == "选择目录"
    assert page.action_bar.primary_btn.text() == "重试自动检测"
    assert "当前目录未设置" in page.action_bar.message_label.text()

    monkeypatch.setattr(config, "csgo_dir", str(valid_dir), raising=False)
    page._auto_detected = False
    page._update_csgo_dir_display()

    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "目录 · 已配置" in chips
    # RN-132：目录配好之后不再高亮任何主按钮（这一页设置改完立即生效，
    # 没有「保存」这个动作）。这条断言原本钉的是旧设计 —— 改设计要连它一起改。
    assert not page.action_bar.primary_btn.isVisibleTo(page), (
        f"底栏又出现了主按钮「{page.action_bar.primary_btn.text()}」")
    assert "目录已配置" in page.action_bar.message_label.text()
    assert "主题 深色主题" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_audio_replay_page_status_strip_tracks_filters(qapp, monkeypatch):
    import pages.audio_replay_page as replay_module

    timeline = get_audio_event_timeline()
    timeline.clear()
    timeline.record(
        AudioEvent(
            timestamp=1.0,
            action="play",
            key="kill-1",
            channel_type="kill_sound",
            event_type="kill",
        )
    )
    timeline.record(
        AudioEvent(
            timestamp=2.0,
            action="drop",
            key="reload-ak",
            channel_type="reload",
            event_type="reload",
        )
    )

    monkeypatch.setattr(replay_module, "get_runtime_audio_manager", lambda: object())
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)

    page = replay_module.AudioReplayPage()
    assert page.empty_results_label.isHidden() is True
    page.action_edit.setText("play")
    page.event_edit.setText("kill")
    page.key_edit.setText("kill-1")
    page._refresh_events()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert "记录 · 1 条" in chips
    assert "动作 · play" in chips
    assert "事件 · kill" in chips
    assert "关键字 · kill-1" in chips
    assert "kill-1" in page.summary_label.toolTip()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "刷新事件"
    assert page.action_bar.primary_btn.text() == "导出 JSON"
    assert "当前筛选：动作 play / 事件 kill / 关键字 kill-1" in page.action_bar.message_label.text()

    page.table.selectRow(0)
    qapp.processEvents()
    assert page.action_bar.primary_btn.text() == "重放选中"
    assert "已选中 kill-1" in page.action_bar.message_label.text()

    page.action_edit.setText("missing")
    page.event_edit.setText("")
    page.key_edit.setText("")
    page._refresh_events()
    assert page.table.isVisible() is False
    assert page.empty_results_label.isHidden() is False

    page.deleteLater()
    timeline.clear()
    qapp.processEvents()


def test_config_snapshot_page_status_strip_tracks_selection(qapp, monkeypatch):
    import pages.config_snapshot_page as snapshot_page_module

    monkeypatch.setattr(config, "config_snapshot_max_keep", 12, raising=False)
    monkeypatch.setattr(
        snapshot_page_module,
        "list_snapshots",
        lambda: [
            SnapshotMeta(
                snapshot_id="20260314_111111_111111",
                reason="manual",
                created_at="2026-03-14T11:11:11",
                file_path="a.json",
                size=10,
                sha256="a" * 64,
            ),
            SnapshotMeta(
                snapshot_id="20260314_101010_101010",
                reason="auto",
                created_at="2026-03-14T10:10:10",
                file_path="b.json",
                size=11,
                sha256="b" * 64,
            ),
        ],
    )

    page = snapshot_page_module.ConfigSnapshotPage()
    page.table.selectRow(0)
    qapp.processEvents()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert "状态 · 已有快照" in chips
    assert "快照 · 2 份" in chips
    assert "保留 · 12 份" in chips
    assert any(text.startswith("选中 · 20260314_11111") for text in chips)
    assert "20260314_111111_111111" in page.summary_label.text()
    assert "2026-03-14T11:11:11" in page.status_card.toolTip()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "刷新快照"
    assert page.action_bar.primary_btn.text() == "恢复选中"
    assert "当前选中：20260314_11111…" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_audio_import_wizard_page_uses_compact_status_strip(qapp, monkeypatch, tmp_path):
    import pages.audio_import_wizard_page as wizard_module

    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    resources_root = tmp_path / "resources"
    resources_root.mkdir(parents=True, exist_ok=True)

    report = {
        "source_dir": str(source_dir),
        "resources_root": str(resources_root),
        "domain": "audio",
        "recognized": [
            {
                "source_path": str(source_dir / "kill_sounds" / "default" / "1.wav"),
                "target_rel_path": "kill_sounds/default/1.wav",
                "target_abs_path": str(resources_root / "kill_sounds" / "default" / "1.wav"),
                "spec_key": "kill_sounds",
                "spec_label": "击杀音效",
                "domain": "audio",
                "conflict": False,
            }
        ],
        "unrecognized": [],
        "summary": {
            "scanned_resource_files": 1,
            "recognized_count": 1,
            "unrecognized_count": 0,
            "conflict_count": 0,
            "importable_count": 1,
            "ok": True,
        },
    }
    import_result = {
        "dry_run": True,
        "overwrite_existing": False,
        "copied": [],
        "skipped_conflicts": [],
        "failed": [],
        "summary": {
            "copied_count": 1,
            "skipped_conflicts_count": 0,
            "failed_count": 0,
            "ok": True,
        },
    }

    monkeypatch.setattr(wizard_module, "scan_resource_import_candidates", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(wizard_module, "apply_resource_import_plan", lambda *_args, **_kwargs: import_result)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        wizard_module.ResourceManager,
        "get_app_data_path",
        lambda rel: str(resources_root if rel in ("resources", "resources/audio") else resources_root / rel),
    )

    page = wizard_module.AudioImportWizardPage()
    page.source_edit.setText(str(source_dir))
    page.dry_run_checkbox.setChecked(True)
    page._scan_source()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("源目录 · source") for text in chips)
    assert any(text.startswith("模式 · 音频") for text in chips)
    assert "策略 · 预演" in chips
    assert "扫描 · 1/0" in chips
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "扫描目录"
    assert page.action_bar.primary_btn.text() == "生成建议"
    assert "当前模式：音频 · 已扫描 1 个可识别条目、0 个冲突" in page.action_bar.message_label.text()

    page._run_import()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "结果 · 1/0/0" in chips
    assert "成功 1" in page.summary_label.toolTip()
    assert "kill_sounds/default/1.wav" in page.preview_text.toPlainText()
    assert page.action_bar.primary_btn.text() == "打开资源目录"
    assert "最近一次预演结果 1/0/0" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


class _DummyRunner(QObject):
    task_started = Signal(str, str)
    task_progress = Signal(str, int, str)
    task_finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.history: list[dict] = []

    def get_history(self, limit: int = 150):
        return list(self.history[-limit:])


def test_audio_task_panel_page_status_strip_tracks_runtime_state(qapp, monkeypatch):
    import pages.audio_task_panel_page as task_panel_module

    runner = _DummyRunner()
    monkeypatch.setattr(task_panel_module, "get_audio_task_runner", lambda: runner)

    page = task_panel_module.AudioTaskPanelPage()
    assert page.summary_label.isHidden() is True
    assert page.table.isVisible() is False
    assert page.empty_history_label.isHidden() is False
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "任务 · 空闲" in chips
    assert "历史 · 0 条" in chips
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is True
    assert page.action_bar.secondary_btn.text() == "刷新历史"
    assert "当前没有后台音频任务历史" in page.action_bar.message_label.text()

    page._on_task_started("abc123", "ui-check")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "任务 · 运行中" in chips
    assert "进度 · 1%" in chips
    assert "当前任务：abc123 · 进度 1%" in page.action_bar.message_label.text()

    page._on_task_progress("abc123", 55, "处理中")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "进度 · 55%" in chips
    assert "进度 55%" in page.action_bar.message_label.text()

    runner.history = [
        {
            "task_id": "abc123",
            "task_type": "reload_audio",
            "reason": "ui-check",
            "started_at": 1.0,
            "finished_at": 2.0,
            "duration": 1.0,
            "success": True,
            "message": "任务完成",
        }
    ]
    page._on_task_finished("abc123", True, "任务完成")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "任务 · 空闲" in chips
    assert "历史 · 1 条" in chips
    assert "结果 · 成功" in chips
    assert page.table.isHidden() is False
    assert page.empty_history_label.isHidden() is True
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.primary_btn.text() == "定位最新任务"
    assert "最近任务：abc123 · 成功" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_preset_center_page_status_strip_tracks_dirty_state(qapp, monkeypatch):
    import pages.preset_center_page as preset_page_module

    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        preset_page_module,
        "export_bundle",
        lambda selected: {
            "schema": "cs2customizer_preset_bundle",
            "schema_version": 1,
            "items": [{"type": item, "payload": {"enabled": True}} for item in selected],
        },
    )
    monkeypatch.setattr(
        preset_page_module,
        "validate_bundle",
        lambda _bundle: type("Validation", (), {"ok": True, "errors": []})(),
    )
    monkeypatch.setattr(
        preset_page_module,
        "apply_bundle",
        lambda bundle, mode="merge": type(
            "ApplyResult",
            (),
            {"ok": True, "applied_types": [item["type"] for item in bundle.get("items", [])], "errors": []},
        )(),
    )

    page = preset_page_module.PresetCenterPage()
    page.resize(1280, 900)
    page.show()
    qapp.processEvents()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert "范围 · 5 类" in chips  # v2 默认勾选 +准心/自定闪光(R2-1)
    assert "模式 · 合并" in chips
    assert "内容 · 5 项" in chips
    assert "状态 · 已同步" in chips
    assert "当前预览范围" in page.preview_meta_label.text()
    assert "合并会尽量保留现有配置" in page.mode_hint_label.text()
    assert page.workbench_content_layout.direction() == QBoxLayout.LeftToRight

    page.cb_special.setChecked(False)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "范围 · 4 类" in chips
    assert "状态 · 待应用" in chips

    page.mode_combo.setCurrentIndex(1)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "模式 · 覆盖" in chips
    assert "覆盖" in page.status_card.toolTip()
    assert "覆盖" in page.summary_label.toolTip()
    assert "覆盖会直接替换对应模块" in page.mode_hint_label.text()

    page.resize(960, 900)
    qapp.processEvents()
    assert page.workbench_content_layout.direction() == QBoxLayout.TopToBottom

    page.deleteLater()
    qapp.processEvents()


class _DummyUtilityDisplay:
    def __init__(self):
        self.utility_data = {}

    def load_map_utilities(self, map_name, team):
        if map_name == "de_mirage" and team == "CT":
            self.utility_data = {
                "A 点": ["烟", "闪"],
                "B 点": ["火"],
            }
        else:
            self.utility_data = {}


def test_utility_page_status_strip_tracks_loaded_utilities(qapp):
    import pages.utility_page as utility_page_module

    page = utility_page_module.UtilityPage()
    page.set_utility_display(_DummyUtilityDisplay())
    page._do_update_map_info("de_mirage", "CT")

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    assert any(text.startswith("热键 ·") for text in chips)
    assert any(text.startswith("地图 ·") for text in chips)
    assert any(text == "阵营 · CT" for text in chips)
    assert any(text == "道具 · 3 项" for text in chips)
    assert "3" in page.status_card.toolTip()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "打开道具文件夹"
    assert page.action_bar.primary_btn.text() == "刷新道具列表"
    assert "当前标签：基础设置" in page.action_bar.message_label.text()

    page.tab_widget.setCurrentIndex(2)
    qapp.processEvents()
    manage_chips = _visible_audio_status_chip_texts(page.manage_context_badge_label)
    assert any(text.startswith("地图 · ") for text in manage_chips)
    assert "阵营 · CT" in manage_chips
    assert "道具 · 3 项" in manage_chips
    assert "已载入 3 项道具" in page.manage_context_label.text()
    assert page.empty_utility_state_widget.isHidden() is True
    assert page.utility_list_text.isHidden() is False
    assert page.action_bar.primary_btn.text() == "打开当前阵营文件夹"
    assert "当前标签：道具管理" in page.action_bar.message_label.text()
    assert "已载入 3 项道具" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_utility_page_manage_tab_shows_empty_state_without_runtime_context(qapp):
    import pages.utility_page as utility_page_module

    page = utility_page_module.UtilityPage()
    page.set_utility_display(_DummyUtilityDisplay())
    page._do_update_map_info("", "")
    page.tab_widget.setCurrentIndex(2)
    qapp.processEvents()

    assert page.utility_list_text.isHidden() is True
    assert page.empty_utility_state_widget.isHidden() is False
    assert "未在游戏中" in page.empty_utility_list_label.text()
    assert "进入对局后" in page.empty_utility_list_label.text()
    assert "等待进入对局" in page.empty_utility_title_label.text()
    assert "自动识别当前地图与阵营" in page.empty_utility_meta_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_crosshair_page_action_bar_tracks_custom_data_state(qapp, monkeypatch):
    import pages.crosshair_page as crosshair_page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_enabled", True, raising=False)
    monkeypatch.setattr(config, "crosshair_style", "crosshair", raising=False)
    monkeypatch.setattr(config, "crosshair_color", "green", raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "pulse", raising=False)
    monkeypatch.setattr(config, "crosshair_kill_effect", "pulse", raising=False)
    monkeypatch.setattr(config, "crosshair_size", 18, raising=False)
    monkeypatch.setattr(config, "crosshair_thickness", 3, raising=False)
    monkeypatch.setattr(config, "crosshair_custom_data", [], raising=False)

    page = crosshair_page_module.CrosshairPage()

    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 6
    assert "显示 · 已启用" in chips
    assert "样式 · 十字" in chips
    assert "颜色 · 绿色" in chips
    assert "当前预览：十字 · 绿色 · 18/3 · 显示已启用" in page.preview_summary_label.text()
    assert "当前档位：大小 18 · 粗细 3" in page.size_summary_label.text()
    assert "当前样式：十字" in page.style_summary_label.text()
    assert "当前颜色：绿色" in page.color_summary_label.text()
    assert "当前动画：脉冲效果" in page.animation_summary_label.text()
    assert "当前联动：脉冲效果" in page.kill_effect_summary_label.text()
    assert "当前还没有自定义点" in page.custom_summary_label.text()
    assert page.preview_frame.width() == 156
    assert page.preview_frame.height() == 156
    # ⚠⚠ RN-174（批 10）：这几行原来断言的是
    #     主按钮可见、且文案是「绘制准心」（有数据时变「导出准心」）
    # —— 也就是**把那条缺陷钉在了原地**：一颗会变身的主按钮 + 与卡片里
    # 那颗同名同槽的重复按钮。⭐ 与下面 `test_viewmodel_...` 里 RN-009 那条注释
    # 是同一个形状：**判据要求缺陷必须存在，于是清理它反而会让判据变红。**
    # 现在：底栏没有主按钮（这一页没有"应用"动作），导入/导出都是次级。
    assert page.action_bar.extra_btn.isHidden() is False
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is True
    assert page.action_bar.extra_btn.text() == "导入准心"
    assert page.action_bar.secondary_btn.text() == "导出准心"
    assert page.action_bar.secondary_btn.isEnabled() is False  # 还没画过，没东西可导
    assert "自动保存" in page.action_bar.message_label.text()
    assert "当前样式：十字" in page.action_bar.message_label.text()
    assert "还没有自定义准心数据" in page.action_bar.message_label.text()

    monkeypatch.setattr(config, "crosshair_custom_data", [(15, 14), (15, 16)], raising=False)
    page._on_style_changed("custom")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "样式 · 自定义" in chips
    assert "当前样式：自定义 · 已保存 2 个自定义点" in page.style_summary_label.text()
    assert "当前已保存 2 个自定义点" in page.custom_summary_label.text()
    # 有数据之后：底栏动作组**不变**，只是「导出准心」从置灰变成可点。
    assert page.action_bar.primary_btn.isHidden() is True
    assert page.action_bar.secondary_btn.text() == "导出准心"
    assert page.action_bar.secondary_btn.isEnabled() is True
    assert "已保存 2 个自定义点" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_viewmodel_page_status_strip_tracks_dirty_state(qapp, monkeypatch):
    import pages.viewmodel_page as viewmodel_page_module

    monkeypatch.setattr(config, "crosshair_reset_enabled", True, raising=False)
    monkeypatch.setattr(config, "viewmodel_auto_switch_enabled", False, raising=False)
    monkeypatch.setattr(config, "viewmodel_auto_switch_key", "V", raising=False)
    monkeypatch.setattr(config, "viewmodel_auto_switch_interval", 3.0, raising=False)
    monkeypatch.setattr(config, "viewmodel_cycle_key", "CAPSLOCK", raising=False)
    monkeypatch.setattr(config, "viewmodel_presets", [], raising=False)

    page = viewmodel_page_module.ViewmodelPage()

    # ⚠ RN-009：这里原来是 `assert page.summary_label.isHidden() is True` ——
    # **判据把缺陷钉在了原地**：它要求那个「建出来就 hide、全仓没人再显示」的死控件
    # 必须存在、且必须是隐藏的。于是清理它反而会让判据变红。
    # 改成断言那份详情**真的到了用户能看到的地方**（状态卡 tooltip）。
    assert not hasattr(page, "summary_label")
    assert "准星回正：已启用" in page.status_card.toolTip()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    assert any(text == "CFG · 已同步" for text in chips)
    assert any(text == "准星回正 · 开" for text in chips)
    assert any(text == "预设 · 5 组" for text in chips)
    assert "当前准星回正：已启用" in page.crosshair_summary_label.text()
    assert "当前循环键：CAPSLOCK · 自动切换未启用" in page.viewmodel_summary_label.text()
    assert "当前状态：CFG已同步" in page.cfg_summary_label.text()
    assert "当前共 5 组预设" in page.presets_summary_label.text()
    assert "预设1(F5)" in page.presets_summary_label.text()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "启用自动切换"
    assert page.action_bar.primary_btn.text() == "保存到CFG"
    assert "当前状态：CFG已同步" in page.action_bar.message_label.text()

    page.cycle_key_input.setText("ALT")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "CFG · 待同步" for text in chips)
    assert any(text == "循环键 · ALT" for text in chips)
    assert "当前循环键：ALT" in page.viewmodel_summary_label.text()
    assert "当前状态：CFG待同步" in page.cfg_summary_label.text()
    assert "当前状态：CFG待同步" in page.action_bar.message_label.text()
    assert "循环键 ALT" in page.action_bar.message_label.text()

    page.auto_switch_key_input.setText("B")
    assert "B" in page.status_card.toolTip()
    assert "（B）" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


def test_hud_color_page_status_strip_tracks_dirty_state(qapp, monkeypatch):
    import pages.hud_color_page as hud_page_module
    from core.hud.rule_model import get_default_hud_rules, normalize_hud_rules

    profile = "balanced_default"
    rules = normalize_hud_rules(get_default_hud_rules(profile), profile=profile)

    monkeypatch.setattr(config, "hud_rules_profile", profile, raising=False)
    monkeypatch.setattr(config, "hud_rules", rules, raising=False)
    monkeypatch.setattr(config, "hud_rules_enabled", True, raising=False)
    monkeypatch.setattr(config, "csgo_dir", "", raising=False)

    page = hud_page_module.HudColorPage()
    page.resize(1280, 900)
    page.show()
    qapp.processEvents()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    # RN-162（批 4）：开关搬进同一张卡之后这条徽章改说功能词。
    # ⚠ 徽章不许再叫「总开关 · …」—— 那颗开关就在同一张卡上，
    # 一行里说两遍（RN-163 在 kill_icon / screen_effects 上逮到的同一条）。
    assert "生效 · 规则已启用" in chips
    assert not any(text.startswith("总开关 · ") for text in chips), (
        f"徽章又在复述那颗就在同一张卡上的开关：{chips}")
    # ⚠ RN-426（批 24）：这颗徽章原来写「保存 · 已同步」。那句话**是真的**
    #   （由 `_dirty` 决定，说的是「你的改动已经写出去了」），但「同步」一词两义 ——
    #   它同时指「写盘」和「在游戏里跑起来」，而玩家读的是后一个。
    #   ⭐⭐ **一句真话被读成另一件事，和一句假话，要用两种修法。**
    assert "保存 · 已存下" in chips
    initial_event_badge = next(text for text in chips if text.startswith("事件 · "))
    assert "当前预设：" in page.preset_summary_label.text()
    assert page.preset_content_layout.direction() == QBoxLayout.LeftToRight

    page.key_widgets["1"]["enabled"].setChecked(True)
    page.event_checkboxes["kill"].setChecked(True)

    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "保存 · 有改动没存" in chips  # RN-426：同上，去掉一词两义的「同步」
    assert "数字键 · 1 项" in chips
    updated_event_badge = next(text for text in chips if text.startswith("事件 · "))
    assert updated_event_badge != initial_event_badge or "项" in updated_event_badge
    assert page.status_card.toolTip()
    assert "数字键 1 项" in page.preset_summary_label.text()

    page.resize(960, 900)
    qapp.processEvents()
    assert page.preset_content_layout.direction() == QBoxLayout.TopToBottom

    page.deleteLater()
    qapp.processEvents()


class _DummyOverlay:
    def __init__(self):
        self.updated = 0
        self.previews = []

    def update_settings_from_config(self):
        self.updated += 1

    def preview(self, is_headshot=False):
        self.previews.append(bool(is_headshot))


def test_screen_effects_page_status_strip_tracks_auto_saved_state(qapp, monkeypatch):
    import pages.screen_effects_page as screen_page_module

    monkeypatch.setattr(config, "screen_effects_enabled", True, raising=False)
    monkeypatch.setattr(config, "screen_edge_flash_enabled", True, raising=False)
    monkeypatch.setattr(config, "screen_effects_preset", "blue_storm", raising=False)
    monkeypatch.setattr(config, "screen_effects_play_mode", "chaos", raising=False)

    overlay = _DummyOverlay()
    page = screen_page_module.ScreenEffectsPage(overlay_manager=overlay)
    page.resize(1280, 900)
    page.show()
    qapp.processEvents()

    # RN-009: 这里原先是 `assert page.summary_label.isHidden() is True` ——
    # 断言一个永远看不见的控件保持看不见，等于给死代码发了张出生证
    # （同样的写法在 13 条判据里各有一份）。那个控件已删；
    # 状态详情真正的承载者是状态卡的 tooltip，改断它。
    assert "总开关：已开启" in (page.status_card.toolTip() or ""), \
        "状态详情没挂在状态卡的 tooltip 上——那是用户唯一看得到它的地方"
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    # ⚠ 2026-08-21（RN-163）：这颗徽章从「总开关 · …」改名了 ——
    # 同一行右端现在就是那颗总开关，一行里说两遍。
    assert "特效 · 开启" in chips
    assert "边缘特效 · 开启" in chips
    assert any(text.startswith("预设 · ") for text in chips)
    assert page.preset_summary_name_label.text() == "电磁风暴"
    assert "粒子" in page.preset_summary_meta_label.text()
    assert "狂欢随机" in page.preset_summary_hint_label.text()
    assert page.top_overview_layout.direction() == QBoxLayout.LeftToRight

    page.resize(960, 900)
    qapp.processEvents()
    assert page.top_overview_layout.direction() == QBoxLayout.TopToBottom

    page.enable_edge_flash_checkbox.setChecked(False)

    assert overlay.updated >= 1
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "边缘特效 · 关闭" in chips
    assert page.status_card.toolTip()

    page._preview_headshot()
    assert overlay.previews[-1] is True

    page.deleteLater()
    qapp.processEvents()


class _DummyKillIconPlayer:
    def __init__(self):
        self.loaded_styles = []
        self.position_updates = []
        self.scale_updates = []
        self.fps_updates = []
        self.play_calls = []
        self.preview_calls = []

    def load_style(self, style):
        self.loaded_styles.append(style)
        return True

    def get_style_fps(self, _style, kills):
        return {1: 24, 2: 28, 3: 32, 4: 36, 5: 40}[kills]

    def get_style_frame_count(self, _style, _kills):
        # KI-3：滑条量的是"展示时长"，落盘的仍是帧率，中间靠帧数换算。
        # 假播放器不给这个数的话，页面会认为"这个等级没素材"，把滑条禁掉。
        return 30

    def update_position_offset(self, offset_x, offset_y):
        self.position_updates.append((offset_x, offset_y))

    def update_scale(self, scale):
        self.scale_updates.append(scale)

    def update_fps_for_style(self, style, kills, fps):
        self.fps_updates.append((style, kills, fps))
        return True

    def play_icon(self, kills, fps):
        self.play_calls.append((kills, fps))

    def preview_position_and_scale(self, kills, seconds):
        self.preview_calls.append((kills, seconds))


def test_kill_icon_page_status_strip_tracks_adjustments(qapp, monkeypatch):
    """KI-7：这一页只回答"用哪一套 · 放哪儿 · 开没开"。

    KI-6 那一版的状态条有七条，把「时长 · 1.5-5.0s」「预览 · 已连接」这类
    **只有做素材的人才关心**的数摆在了首屏；逐等级的编辑也整块摆在页面正中。
    用户的原话是「有点复杂有点乱」。现在编辑整块搬进素材工坊，
    这一页的状态条压到四条（那些数退进详情文案，鼠标停上去能看到）。
    """
    import pages.kill_icon_page as kill_icon_page_module

    monkeypatch.setattr(kill_icon_page_module.ResourceManager, "list_kill_icon_styles", lambda: ["classic", "modern"])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_icon_style", "classic", raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_x", 12, raising=False)
    monkeypatch.setattr(config, "kill_icon_offset_y", -8, raising=False)
    monkeypatch.setattr(config, "kill_icon_scale", 1.1, raising=False)
    monkeypatch.setattr(kill_icon_page_module, "load_level_animation", lambda *a, **k: None)
    monkeypatch.setattr(kill_icon_page_module, "style_summary",
                        lambda style, *a, **k: {"levels": [1, 2, 3, 4, 5], "missing": [],
                                                "headshot_levels": [], "frames": 100})
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)

    player = _DummyKillIconPlayer()
    page = kill_icon_page_module.KillIconPage()
    page.set_kill_icon_player(player)
    page.resize(1400, 900)
    page.show()
    qapp.processEvents()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    # ⚠ 2026-08-21（RN-163）：这颗徽章从「总开关 · …」改名了 ——
    # 同一行右端现在就是那颗总开关，一行里说两遍。
    assert any(text.startswith("显示 · ") for text in chips)
    assert any(text.startswith("素材 · ") for text in chips)
    assert any(text.startswith("风格 · classic") for text in chips)
    assert "位置 · 12/-8 · 110%" in chips
    # 退下去的信息不是丢掉，是收进详情
    assert "预览组件：已连接" in page.status_card.toolTip()
    assert "当前风格：classic" in page.style_summary_label.text()
    assert "素材 5/5 个等级" in page.style_summary_label.text()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "打开素材工坊"
    assert page.action_bar.primary_btn.text() == "在屏幕上试播"
    assert "当前风格：classic" in page.action_bar.message_label.text()

    # 换风格靠点卡片，不是下拉框——换之前就看得见长什么样
    page.style_strip.style_selected.emit("modern")
    page.adjust_toggle_btn.setChecked(True)
    page.x_slider.setValue(30)
    page.y_slider.setValue(-15)
    page.scale_slider.setValue(125)

    assert player.loaded_styles[-1] == "modern"
    assert player.position_updates[-1] == (30, -15)
    assert player.scale_updates[-1] == 1.25
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "位置 · 30/-15 · 125%" in chips
    assert any(text.startswith("风格 · modern") for text in chips)
    assert "当前位置：X 30 / Y -15 · 缩放 125%" in page.adjust_summary_label.text()
    assert "30 / Y -15" in page.status_card.toolTip()
    assert "125%" in page.status_card.toolTip()

    page.deleteLater()
    qapp.processEvents()


class _DummySpecialSoundAudioManager:
    def __init__(self):
        self.grenade_sound_styles = {
            "hegrenade": ["impact"],
            "flashbang": ["flash"],
            "smoke": [],
            "molotov": [],
            "incgrenade": [],
            "decoy": [],
        }
        self.c4_sound_styles = ["beacon"]
        self.health_warning_styles = ["warning"]
        self.round_start_styles = ["start"]
        self.round_action_styles = ["action"]
        self.round_win_styles = ["win"]
        self.round_lose_styles = ["lose"]
        self.round_mvp_styles = ["mvp"]
        self.play_calls = []
        self.scan_calls = []

    def ensure_styles_scanned(self):
        return None

    def scan_grenade_sound_styles(self):
        self.scan_calls.append("grenade")
        return self.grenade_sound_styles

    def scan_c4_sound_styles(self):
        self.scan_calls.append("c4")
        return self.c4_sound_styles

    def scan_health_warning_styles(self):
        self.scan_calls.append("health")
        return self.health_warning_styles

    def scan_round_sound_styles(self):
        self.scan_calls.append("round")
        return {
            "start": self.round_start_styles,
            "action": self.round_action_styles,
            "win": self.round_win_styles,
            "lose": self.round_lose_styles,
            "mvp": self.round_mvp_styles,
        }

    def play_sound(self, key: str, channel_type: str = "round_sound", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_special_sound_page_status_card_tracks_threshold_and_volume(qapp, monkeypatch):
    import pages.special_sound_page as special_sound_page_module

    dummy = _DummySpecialSoundAudioManager()
    monkeypatch.setattr(special_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        special_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(
        config,
        "grenade_sound_styles",
        {"hegrenade": "impact", "flashbang": "flash", "smoke": "0", "molotov": "0", "incgrenade": "0", "decoy": "0"},
        raising=False,
    )
    monkeypatch.setattr(config, "c4_sound_style", "beacon", raising=False)
    monkeypatch.setattr(config, "health_warning_style", "warning", raising=False)
    monkeypatch.setattr(config, "round_start_style", "start", raising=False)
    monkeypatch.setattr(config, "round_action_style", "action", raising=False)
    monkeypatch.setattr(config, "round_win_style", "win", raising=False)
    monkeypatch.setattr(config, "round_lose_style", "0", raising=False)
    monkeypatch.setattr(config, "round_mvp_style", "mvp", raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "health_warning_enabled", True, raising=False)
    monkeypatch.setattr(config, "health_warning_threshold", 18, raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "round_sound_volume", 0.65, raising=False)

    page = special_sound_page_module.SpecialSoundPage()
    page.resize(1500, 960)
    page.show()
    qapp.processEvents()

    assert page.summary_label.isHidden() is True
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前标签" in page.action_bar.message_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("模块 · 3/4") for text in chips)
    assert any(text.startswith("风格 · 8") for text in chips)
    # RN-053：第三颗徽章跟着当前页签走（原来无论在哪个页签都写「回合音量」）。
    # 默认停在「投掷物」，所以这里该看到投掷物自己的数，看不到回合音量。
    assert any(text.startswith("投掷物 · 2/6") for text in chips), chips
    assert not any("回合音量" in text for text in chips), chips
    for index in range(page.tab_widget.count()):
        page.tab_widget.setCurrentIndex(index)
        page._refresh_status_badge()
        tab_chips = _visible_audio_status_chip_texts(page.status_badge_label)
        name = page.tab_widget.tabText(index)
        if name == "回合":
            assert any("65%" in text for text in tab_chips), tab_chips
        else:
            assert not any("回合音量" in text for text in tab_chips), (name, tab_chips)
    page.tab_widget.setCurrentIndex(0)
    page._refresh_status_badge()
    assert "当前已选 2/6 类" in page.grenade_summary_label.text()
    assert "模块已启用" in page.grenade_summary_label.text()
    # RN-054：C4 有三个事件（安放/拆除/爆炸），原文「当前风格：beacon」只说了安放那一个
    assert "已选 1/3 项" in page.c4_summary_label.text()
    assert "模块已关闭" in page.c4_summary_label.text()
    assert "阈值 18 · 当前风格：warning · 模块已启用" in page.health_summary_label.text()
    assert f"音量 65% · 已选 4/{_ROUND_EVENT_COUNT} · 模块已启用" in page.round_summary_label.text()
    assert "阈值 18" in page.status_card.toolTip()
    grenade_index = page.grenade_grid.indexOf(page.grenade_cards[2])
    grenade_row, grenade_col, _, _ = page.grenade_grid.getItemPosition(grenade_index)
    assert (grenade_row, grenade_col) == (0, 2)
    round_index = page.round_grid.indexOf(page.round_cards[2])
    round_row, round_col, _, _ = page.round_grid.getItemPosition(round_index)
    assert (round_row, round_col) == (0, 2)

    page._on_threshold_changed(25)
    page._on_round_volume_changed(40)
    page._on_c4_enabled_toggled(True)

    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("模块 · 4/4") for text in chips)
    page.tab_widget.setCurrentIndex(
        [page.tab_widget.tabText(i) for i in range(page.tab_widget.count())].index("回合"))
    page._refresh_status_badge()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any("40%" in text for text in chips), chips
    assert "已选 1/3 项" in page.c4_summary_label.text()
    assert "模块已启用" in page.c4_summary_label.text()
    assert "阈值 25 · 当前风格：warning · 模块已启用" in page.health_summary_label.text()
    assert f"音量 40% · 已选 4/{_ROUND_EVENT_COUNT} · 模块已启用" in page.round_summary_label.text()
    assert "阈值 25" in page.summary_label.toolTip()
    assert "音量 40%" in page.status_card.toolTip()

    page.resize(980, 960)
    qapp.processEvents()
    grenade_index = page.grenade_grid.indexOf(page.grenade_cards[2])
    grenade_row, grenade_col, _, _ = page.grenade_grid.getItemPosition(grenade_index)
    assert (grenade_row, grenade_col) == (1, 0)
    round_index = page.round_grid.indexOf(page.round_cards[2])
    round_row, round_col, _, _ = page.round_grid.getItemPosition(round_index)
    assert (round_row, round_col) == (1, 0)

    page.deleteLater()
    qapp.processEvents()


def test_special_sound_page_refresh_style_catalog_preserves_selection(qapp, monkeypatch):
    import pages.special_sound_page as special_sound_page_module

    dummy = _DummySpecialSoundAudioManager()
    monkeypatch.setattr(special_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        special_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles", {"hegrenade": "impact"}, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "beacon", raising=False)
    monkeypatch.setattr(config, "health_warning_style", "warning", raising=False)
    monkeypatch.setattr(config, "round_start_style", "start", raising=False)
    monkeypatch.setattr(config, "round_action_style", "action", raising=False)
    monkeypatch.setattr(config, "round_win_style", "win", raising=False)
    monkeypatch.setattr(config, "round_lose_style", "lose", raising=False)
    monkeypatch.setattr(config, "round_mvp_style", "mvp", raising=False)

    page = special_sound_page_module.SpecialSoundPage()

    dummy.grenade_sound_styles["hegrenade"].append("impact-alt")
    dummy.c4_sound_styles.append("pulse")
    dummy.health_warning_styles.append("panic")
    dummy.round_win_styles.append("victory-alt")

    page._refresh_style_catalog()

    grenade_combo = page.grenade_combos["hegrenade"]
    grenade_options = [grenade_combo.itemText(i) for i in range(grenade_combo.count())]
    assert "impact-alt" in grenade_options
    assert grenade_combo.currentData() == "impact"

    c4_options = [page.c4_style_combo.itemText(i) for i in range(page.c4_style_combo.count())]
    assert "pulse" in c4_options
    assert page.c4_style_combo.currentData() == "beacon"

    health_options = [page.health_style_combo.itemText(i) for i in range(page.health_style_combo.count())]
    assert "panic" in health_options
    assert page.health_style_combo.currentData() == "warning"

    round_win_combo = page.round_combos["win"]
    round_win_options = [round_win_combo.itemText(i) for i in range(round_win_combo.count())]
    assert "victory-alt" in round_win_options
    assert round_win_combo.currentData() == "win"
    assert dummy.scan_calls[-4:] == ["grenade", "c4", "health", "round"]

    page.deleteLater()
    qapp.processEvents()


class _DummyKillSoundAudioManager:
    def __init__(self):
        self.kill_sound_styles = ["arcade"]
        self.weapon_kill_sound_styles = {
            "weapon_ak47": ["ak-special"],
            "weapon_awp": ["sniper"],
        }
        self.load_calls = []
        self.unload_calls = []
        self.play_calls = []
        self.scan_calls = []

    def ensure_styles_scanned(self):
        return None

    def scan_kill_sound_styles(self):
        self.scan_calls.append("global")
        return self.kill_sound_styles

    def scan_weapon_kill_sound_styles(self):
        self.scan_calls.append("weapon")
        return self.weapon_kill_sound_styles

    def load_kill_sound_for_weapon(self, weapon, style, include_headshot=False):
        self.load_calls.append((weapon, style, include_headshot))
        return True

    def unload_kill_sound_for_weapon(self, weapon, style):
        self.unload_calls.append((weapon, style))
        return True

    def play_sound(self, key: str, channel_type: str = "kill_sound", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_kill_sound_page_status_card_tracks_tab_scope(qapp, monkeypatch):
    import pages.kill_sound_page as kill_sound_page_module

    dummy = _DummyKillSoundAudioManager()
    monkeypatch.setattr(kill_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        kill_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "weapon_kill_sounds",
        {"weapon_glock": "arcade", "weapon_ak47": "ak-special"},
        raising=False,
    )

    page = kill_sound_page_module.KillSoundPage()

    assert page.summary_label.isHidden() is True
    assert dummy.load_calls == []
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前分类" in page.action_bar.message_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("已配置 · 2") for text in chips)
    assert "当前分类：手枪" in page.status_card.toolTip()
    assert "当前分类已配置：1/10" in page.status_card.toolTip()
    assert page.category_overview_title_label.text() == "当前分类 · 手枪"
    assert "本分类已配置 1/10" in page.category_overview_meta_label.text()
    assert "已配置示例" in page.category_overview_hint_label.text()

    page.tab_widget.setCurrentIndex(page.tab_widget.indexOf(page.tab_widget.widget(2)))
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any("步枪 1/7" in text for text in chips)
    assert page.category_overview_title_label.text() == "当前分类 · 步枪"

    page.tab_widget.setCurrentIndex(page.tab_widget.indexOf(page.tab_widget.widget(3)))
    qapp.processEvents()
    page.weapon_rows["weapon_awp"].style_combo.setCurrentText("sniper")

    assert config.weapon_kill_sounds["weapon_awp"] == "sniper"
    assert dummy.load_calls[-1] == ("weapon_awp", "sniper", True)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("已配置 · 3") for text in chips)
    assert any("狙击枪 1/4" in text for text in chips)

    page.deleteLater()
    qapp.processEvents()


def test_kill_sound_page_refresh_style_catalog_preserves_selection(qapp, monkeypatch):
    import pages.kill_sound_page as kill_sound_page_module

    dummy = _DummyKillSoundAudioManager()
    monkeypatch.setattr(kill_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        kill_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_glock": "arcade"}, raising=False)

    page = kill_sound_page_module.KillSoundPage()

    dummy.kill_sound_styles.append("retro")
    dummy.weapon_kill_sound_styles["weapon_glock"] = ["glock-alt"]
    page._refresh_style_catalog()

    combo = page.weapon_rows["weapon_glock"].style_combo
    options = [combo.itemText(i) for i in range(combo.count())]
    assert "retro" in options
    assert "glock-alt" in options
    assert combo.currentText() == "arcade"
    assert dummy.scan_calls == ["global", "weapon"]

    page.deleteLater()
    qapp.processEvents()


class _DummyKillVoiceStatusAudioManager:
    def __init__(self):
        self.kill_voice_styles = ["styleV"]
        self.weapon_kill_voice_styles = {
            "weapon_ak47": ["ak-voice"],
            "weapon_awp": ["sniper-voice"],
        }
        self.weapon_voices_dir = "voices/weapon"
        self.kill_voices_dir = "voices/common"
        self._sounds = {}
        self.load_calls = []
        self.unload_calls = []
        self.scan_calls = []

    def ensure_styles_scanned(self):
        return None

    def scan_kill_voice_styles(self):
        self.scan_calls.append("global")
        return self.kill_voice_styles

    def scan_weapon_kill_voice_styles(self):
        self.scan_calls.append("weapon")
        return self.weapon_kill_voice_styles

    def load_kill_voice_for_weapon(self, weapon, style):
        self.load_calls.append((weapon, style))
        return True

    def unload_kill_voice_for_weapon(self, weapon, style):
        self.unload_calls.append((weapon, style))
        return True


def test_kill_voice_page_status_card_tracks_tab_scope(qapp, monkeypatch):
    import pages.kill_voice_page as kill_voice_page_module

    dummy = _DummyKillVoiceStatusAudioManager()
    monkeypatch.setattr(kill_voice_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        kill_voice_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "weapon_kill_voices",
        {"weapon_glock": "styleV", "weapon_ak47": "ak-voice"},
        raising=False,
    )

    page = kill_voice_page_module.KillVoicePage()

    assert page.summary_label.isHidden() is True
    assert page.category_overview_title_label.text() == "当前分类 · 手枪"
    assert "本分类已配置 1/10" in page.category_overview_meta_label.text()
    assert "已配置示例" in page.category_overview_hint_label.text()
    assert dummy.load_calls == []
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前分类" in page.action_bar.message_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("已配置 · 2") for text in chips)
    assert "当前分类：手枪" in page.status_card.toolTip()
    assert "试听策略" in page.status_card.toolTip()

    page.tab_widget.setCurrentIndex(page.tab_widget.indexOf(page.tab_widget.widget(2)))
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any("步枪 1/7" in text for text in chips)

    page.tab_widget.setCurrentIndex(page.tab_widget.indexOf(page.tab_widget.widget(3)))
    qapp.processEvents()
    page.weapon_rows["weapon_awp"].style_combo.setCurrentText("sniper-voice")

    assert config.weapon_kill_voices["weapon_awp"] == "sniper-voice"
    assert dummy.load_calls[-1] == ("weapon_awp", "sniper-voice")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("已配置 · 3") for text in chips)
    assert any("狙击枪 1/4" in text for text in chips)

    page.deleteLater()
    qapp.processEvents()


def test_kill_voice_page_refresh_style_catalog_preserves_selection(qapp, monkeypatch):
    import pages.kill_voice_page as kill_voice_page_module

    dummy = _DummyKillVoiceStatusAudioManager()
    monkeypatch.setattr(kill_voice_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        kill_voice_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {"weapon_ak47": "ak-voice"}, raising=False)

    page = kill_voice_page_module.KillVoicePage()

    dummy.kill_voice_styles.append("caster-pack")
    dummy.weapon_kill_voice_styles["weapon_ak47"] = ["ak-voice", "ak-alt"]
    page._refresh_style_catalog()

    combo = page.weapon_rows["weapon_ak47"].style_combo
    options = [combo.itemText(i) for i in range(combo.count())]
    assert "caster-pack" in options
    assert "ak-alt" in options
    assert combo.currentText() == "ak-voice"
    assert dummy.scan_calls == ["global", "weapon"]

    page.deleteLater()
    qapp.processEvents()


class _DummyGunSoundAudioManager:
    def __init__(self):
        self.gun_sounds_dir = "gun_sounds"
        self.play_calls = []

    def ensure_styles_scanned(self):
        return None

    def play_sound(self, key: str, channel_type: str = "gun_sound", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_gun_sound_page_status_card_tracks_category_and_tuning(qapp, monkeypatch):
    import pages.gun_sound_page as gun_sound_page_module

    saved = []
    dummy = _DummyGunSoundAudioManager()
    monkeypatch.setattr(gun_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        gun_sound_page_module.GunSoundPage,
        "_scan_gun_sounds",
        lambda self: setattr(self, "weapon_styles", {"awp": ["styleAwp"], "xm1014": ["styleXm"]}),
    )
    monkeypatch.setattr(
        gun_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    for profile in gun_sound_page_module.SUPPORTED_GUN_SOUND_PROFILE_LIST:
        monkeypatch.setattr(config, profile.style_key, "0", raising=False)
        monkeypatch.setattr(config, profile.mute_duration_key, profile.default_mute_duration, raising=False)
        monkeypatch.setattr(config, profile.duck_ratio_key, profile.default_duck_ratio, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)
    monkeypatch.setattr(config, "awp_mute_duration", 0.5, raising=False)
    monkeypatch.setattr(config, "awp_duck_ratio", 0.18, raising=False)
    monkeypatch.setattr(config, "xm1014_style", "0", raising=False)
    monkeypatch.setattr(config, "xm1014_mute_duration", 0.3, raising=False)
    monkeypatch.setattr(config, "xm1014_duck_ratio", 0.22, raising=False)

    page = gun_sound_page_module.GunSoundPage()

    assert page.summary_label.isHidden() is True
    assert saved == []
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前分类" in page.action_bar.message_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("已配置 · 1") for text in chips)
    assert "原声保留范围" in page.status_card.toolTip()
    assert "静音覆盖范围" in page.status_card.toolTip()

    assert page.weapon_rows["awp"]["style_combo"].sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert page.weapon_rows["awp"]["duck_slider"].sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert page.weapon_rows["awp"]["duration_slider"].sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding

    shotgun_index = next(
        index for index, (_name, weapons) in enumerate(page._tab_groups) if "xm1014" in weapons
    )
    shotgun_total = len(page._tab_groups[shotgun_index][1])
    page.tab_widget.setCurrentIndex(shotgun_index)
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.endswith(f"0/{shotgun_total}") for text in chips)

    page.weapon_rows["xm1014"]["style_combo"].setCurrentIndex(1)
    page.weapon_rows["xm1014"]["duck_slider"].setValue(35)
    page.weapon_rows["xm1014"]["duration_slider"].setValue(4)

    assert config.xm1014_style == "styleXm"
    assert config.xm1014_duck_ratio == pytest.approx(0.35)
    assert config.xm1014_mute_duration == pytest.approx(0.4)
    assert len(saved) >= 3
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("已配置 · 2") for text in chips)
    assert any(text.endswith(f"1/{shotgun_total}") for text in chips)

    page._test_gun_sound("xm1014")
    assert ("gun-xm1014-styleXm", "gun_sound") in dummy.play_calls

    page.deleteLater()
    qapp.processEvents()


def test_gun_sound_page_refresh_preserves_current_mapping(qapp, monkeypatch):
    import pages.gun_sound_page as gun_sound_page_module

    dummy = _DummyGunSoundAudioManager()
    scan_results = [
        {"awp": ["styleAwp"], "xm1014": ["styleXm"]},
        {"awp": ["styleAwp", "styleAlt"], "xm1014": ["styleXm"]},
    ]

    monkeypatch.setattr(gun_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        gun_sound_page_module.GunSoundPage,
        "_scan_gun_sounds",
        lambda self: setattr(self, "weapon_styles", scan_results.pop(0)),
    )
    monkeypatch.setattr(
        gun_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    for profile in gun_sound_page_module.SUPPORTED_GUN_SOUND_PROFILE_LIST:
        monkeypatch.setattr(config, profile.style_key, "0", raising=False)
        monkeypatch.setattr(config, profile.mute_duration_key, profile.default_mute_duration, raising=False)
        monkeypatch.setattr(config, profile.duck_ratio_key, profile.default_duck_ratio, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)
    monkeypatch.setattr(config, "xm1014_style", "styleXm", raising=False)

    page = gun_sound_page_module.GunSoundPage()

    assert page.weapon_rows["awp"]["style_combo"].currentData() == "styleAwp"
    page._refresh_style_catalog()
    qapp.processEvents()

    assert page.weapon_rows["awp"]["style_combo"].currentData() == "styleAwp"
    assert page.weapon_rows["awp"]["style_combo"].findData("styleAlt") >= 0
    assert "当前分类" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


class _DummyReloadAudioManager:
    def __init__(self):
        self.reload_sounds_dir = "reload_sounds"
        self._sounds = {}
        self.load_calls = []
        self.play_calls = []

    def ensure_styles_scanned(self):
        return None

    def load_sound(self, key, path, category, **kwargs):
        self._sounds[key] = type("S", (), {"loaded": True, "path": path})()
        self.load_calls.append((key, path, category, kwargs))
        return True

    def play_sound(self, key: str, channel_type: str = "reload", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_reload_sound_page_status_card_tracks_category_scope(qapp, monkeypatch):
    import pages.reload_sound_page as reload_sound_page_module

    saved = []
    dummy = _DummyReloadAudioManager()
    monkeypatch.setattr(reload_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        reload_sound_page_module.ReloadSoundPage,
        "_scan_reload_styles",
        lambda self: setattr(self, "weapon_reload_styles", {"weapon_ak47": ["styleReload"], "weapon_awp": ["styleAwp"]}),
    )
    monkeypatch.setattr(
        reload_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(reload_sound_page_module.os.path, "exists", lambda path: True)
    monkeypatch.setattr(reload_sound_page_module, "find_first_audio_file", lambda *_args, **_kwargs: "reload.wav")
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_ak47": "styleReload", "weapon_awp": "0"}, raising=False)

    page = reload_sound_page_module.ReloadSoundPage()

    assert page.summary_label.isHidden() is True
    assert saved == []
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前分类" in page.action_bar.message_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("已配置 · 1") for text in chips)
    assert "测试策略" in page.status_card.toolTip()
    assert page.category_overview_title_label.text() == "当前分类 · 手枪"
    assert "本分类已配置 0/10" in page.category_overview_meta_label.text()
    assert "已配置示例" in page.category_overview_hint_label.text()

    page.tab_widget.setCurrentIndex(3)
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.endswith("0/4") for text in chips)
    assert page.category_overview_title_label.text() == "当前分类 · 狙击枪"

    page.weapon_rows["weapon_awp"].style_combo.setCurrentIndex(1)

    assert config.weapon_reload_sounds["weapon_awp"] == "styleAwp"
    assert saved == [True]
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("已配置 · 2") for text in chips)
    assert any(text.endswith("1/4") for text in chips)
    assert "本分类已配置 1/4" in page.category_overview_meta_label.text()
    assert "测试会按需加载首个可用音频文件" in page.category_overview_hint_label.text()

    page._test_reload_sound("weapon_awp")
    assert any(call[0] == "reload-weapon_awp-styleAwp" for call in dummy.load_calls)
    assert ("reload-weapon_awp-styleAwp", "reload") in dummy.play_calls

    page.deleteLater()
    qapp.processEvents()


def test_reload_sound_page_refresh_preserves_current_mapping(qapp, monkeypatch):
    import pages.reload_sound_page as reload_sound_page_module

    dummy = _DummyReloadAudioManager()
    scan_results = [
        {"weapon_ak47": ["styleReload"], "weapon_awp": ["styleAwp"]},
        {"weapon_ak47": ["styleReload", "styleAlt"], "weapon_awp": ["styleAwp"]},
    ]

    monkeypatch.setattr(reload_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        reload_sound_page_module.ReloadSoundPage,
        "_scan_reload_styles",
        lambda self: setattr(self, "weapon_reload_styles", scan_results.pop(0)),
    )
    monkeypatch.setattr(
        reload_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_ak47": "styleReload", "weapon_awp": "styleAwp"}, raising=False)

    page = reload_sound_page_module.ReloadSoundPage()

    assert page.weapon_rows["weapon_ak47"].get_current_style() == "styleReload"
    page._refresh_style_catalog()
    qapp.processEvents()

    assert page.weapon_rows["weapon_ak47"].get_current_style() == "styleReload"
    assert "当前分类" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


class _DummyDeathSoundAudioManager:
    def __init__(self):
        self.death_sounds_dir = "death"
        self._sounds = {}
        self.load_calls = []
        self.play_calls = []

    def ensure_styles_scanned(self):
        return None

    def load_sound(self, key, path, category, **kwargs):
        self._sounds[key] = type("S", (), {"loaded": True, "path": path})()
        self.load_calls.append((key, path, category, kwargs))
        return True

    def play_sound(self, key: str, channel_type: str = "death_sound", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_death_sound_page_status_card_tracks_style_selection(qapp, monkeypatch):
    import pages.death_sound_page as death_sound_page_module

    saved = []
    dummy = _DummyDeathSoundAudioManager()
    monkeypatch.setattr(death_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        death_sound_page_module,
        "list_unique_audio_stems",
        lambda *_args, **_kwargs: ["styleDeath", "styleAlt"],
    )
    monkeypatch.setattr(
        death_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(death_sound_page_module, "find_audio_by_stem", lambda *_args, **_kwargs: "death.wav")
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "death_sound_style", "styleDeath", raising=False)

    page = death_sound_page_module.DeathSoundPage()
    page.resize(1280, 900)
    page.show()
    qapp.processEvents()

    assert page.summary_label.isHidden() is True
    assert saved == []
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("风格 · styleDeath") for text in chips)
    assert any(text.startswith("候选 · 2") for text in chips)
    assert "当前风格：styleDeath" in page.status_card.toolTip()
    assert "测试策略" in page.status_card.toolTip()
    assert page.style_overview_name_label.text() == "styleDeath"
    assert "候选 2 个" in page.style_overview_meta_label.text()
    assert page.top_content_layout.direction() == QBoxLayout.LeftToRight

    page.style_combo.setCurrentIndex(page.style_combo.findData("styleAlt"))
    qapp.processEvents()

    assert config.death_sound_style == "styleAlt"
    assert saved == [True]
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("风格 · styleAlt") for text in chips)
    assert page.style_overview_name_label.text() == "styleAlt"

    page.resize(900, 900)
    qapp.processEvents()
    assert page.top_content_layout.direction() == QBoxLayout.TopToBottom

    page._test_sound()
    assert any(call[0] == "death-styleAlt" for call in dummy.load_calls)
    assert ("death-styleAlt", "death_sound") in dummy.play_calls

    page.deleteLater()
    qapp.processEvents()


def test_death_sound_page_action_bar_refresh_preserves_current_style(qapp, monkeypatch):
    import pages.death_sound_page as death_sound_page_module

    dummy = _DummyDeathSoundAudioManager()
    scan_results = [
        ["styleDeath", "styleAlt"],
        ["styleDeath", "styleAlt", "styleNew"],
    ]

    monkeypatch.setattr(death_sound_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        death_sound_page_module,
        "list_unique_audio_stems",
        lambda *_args, **_kwargs: scan_results.pop(0),
    )
    monkeypatch.setattr(
        death_sound_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "death_sound_style", "styleAlt", raising=False)

    page = death_sound_page_module.DeathSoundPage()

    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前风格" in page.action_bar.message_label.text()
    assert page.style_combo.currentData() == "styleAlt"

    page._refresh_style_catalog()
    qapp.processEvents()

    assert page.style_combo.currentData() == "styleAlt"
    assert page.style_combo.findData("styleNew") >= 0
    assert "当前风格" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


class _DummySwitchWeaponAudioManager:
    def __init__(self):
        self.switch_weapons_dir = "switch_weapons"
        self._sounds = {}
        self.load_calls = []
        self.play_calls = []

    def ensure_styles_scanned(self):
        return None

    def load_sound(self, key, path, category, **kwargs):
        self._sounds[key] = type("S", (), {"loaded": True, "path": path})()
        self.load_calls.append((key, path, category, kwargs))
        return True

    def play_sound(self, key: str, channel_type: str = "switch_weapon", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_switch_weapon_page_status_card_tracks_category_scope(qapp, monkeypatch):
    import pages.switch_weapon_page as switch_weapon_page_module

    saved = []
    dummy = _DummySwitchWeaponAudioManager()
    monkeypatch.setattr(switch_weapon_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        switch_weapon_page_module.SwitchWeaponPage,
        "_scan_switch_weapon_styles",
        lambda self: setattr(
            self,
            "weapon_switch_styles",
            {"weapon_ak47": ["styleSwitch"], "weapon_awp": ["styleAwp"]},
        ),
    )
    monkeypatch.setattr(
        switch_weapon_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(switch_weapon_page_module.os.path, "exists", lambda path: True)
    monkeypatch.setattr(switch_weapon_page_module, "find_first_audio_file", lambda *_args, **_kwargs: "switch.wav")
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "weapon_switch_sounds",
        {"weapon_ak47": "styleSwitch", "weapon_awp": "0"},
        raising=False,
    )

    page = switch_weapon_page_module.SwitchWeaponPage()

    assert page.summary_label.isHidden() is True
    assert page.category_overview_title_label.text() == "当前分类 · 手枪"
    assert "本分类已配置 0/10" in page.category_overview_meta_label.text()
    assert "已配置示例" in page.category_overview_hint_label.text()
    assert saved == []
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert "当前分类" in page.action_bar.message_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("已配置 · 1") for text in chips)
    assert "当前分类：手枪" in page.status_card.toolTip()
    assert "测试策略" in page.status_card.toolTip()

    page.tab_widget.setCurrentIndex(3)
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.endswith("0/4") for text in chips)

    page.weapon_rows["weapon_awp"].style_combo.setCurrentIndex(1)

    assert config.weapon_switch_sounds["weapon_awp"] == "styleAwp"
    assert saved == [True]
    assert "本分类已配置 1/4" in page.category_overview_meta_label.text()
    assert "测试会按需加载首个可用音频文件" in page.category_overview_hint_label.text()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("已配置 · 2") for text in chips)
    assert any(text.endswith("1/4") for text in chips)

    page._test_switch_sound("weapon_awp")
    assert any(call[0] == "switch-weapon_awp-styleAwp" for call in dummy.load_calls)
    assert ("switch-weapon_awp-styleAwp", "switch_weapon") in dummy.play_calls

    page.deleteLater()
    qapp.processEvents()


def test_switch_weapon_page_refresh_preserves_current_mapping(qapp, monkeypatch):
    import pages.switch_weapon_page as switch_weapon_page_module

    dummy = _DummySwitchWeaponAudioManager()
    scan_results = [
        {"weapon_ak47": ["styleSwitch"], "weapon_awp": ["styleAwp"]},
        {"weapon_ak47": ["styleSwitch", "styleAlt"], "weapon_awp": ["styleAwp"]},
    ]

    monkeypatch.setattr(switch_weapon_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        switch_weapon_page_module.SwitchWeaponPage,
        "_scan_switch_weapon_styles",
        lambda self: setattr(self, "weapon_switch_styles", scan_results.pop(0)),
    )
    monkeypatch.setattr(
        switch_weapon_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "weapon_switch_sounds",
        {"weapon_ak47": "styleSwitch", "weapon_awp": "styleAwp"},
        raising=False,
    )

    page = switch_weapon_page_module.SwitchWeaponPage()

    assert page.weapon_rows["weapon_ak47"].get_current_style() == "styleSwitch"
    page._refresh_style_catalog()
    qapp.processEvents()

    assert page.weapon_rows["weapon_ak47"].get_current_style() == "styleSwitch"
    assert "当前分类" in page.action_bar.message_label.text()

    page.deleteLater()
    qapp.processEvents()


class _DummyVoiceOutputManager:
    def __init__(self):
        self.vb_cable_device_id = 7
        self.microphone_passthrough_active = False
        self.play_calls = []
        self.stop_calls = 0
        self.last_microphone = None

    def get_microphone_list(self):
        return ["默认", "USB Mic"]

    def start_microphone_passthrough(self, microphone):
        self.microphone_passthrough_active = True
        self.last_microphone = microphone
        return True

    def stop_microphone_passthrough(self):
        self.microphone_passthrough_active = False

    def get_sound_duration(self, _path):
        return 0.5

    def play_audio_with_ptt_protocol(self, **kwargs):
        self.play_calls.append(kwargs)
        return True

    def stop_playback(self):
        self.stop_calls += 1


class _DummyMusicPlayer:
    def __init__(self):
        self.on_playlist_update = None
        self.on_playlist_change = None
        self.current_playlist_name = "默认"
        self.current_index = 0
        self.is_paused = False
        self.is_playing = False
        self.play_mode = "repeat_all"
        self._playlists = ["默认", "收藏"]
        self._playlist = [
            {"title": "Inferno Pulse", "artist": "CS2Customizer", "duration": 182, "type": "local", "path": "a.mp3"},
            {"title": "Dust Loop", "artist": "CS2Customizer", "duration": 201, "type": "local", "path": "b.mp3"},
            {"title": "Mirage Radio", "artist": "", "duration": 0, "type": "url", "path": "https://example.com/live"},
        ]

    def get_playlist(self):
        return list(self._playlist)

    def get_all_playlists(self):
        return list(self._playlists)

    def switch_playlist(self, name):
        self.current_playlist_name = name

    def get_current_track(self):
        if 0 <= self.current_index < len(self._playlist):
            return self._playlist[self.current_index]
        return None

    def set_play_mode(self, play_mode):
        self.play_mode = play_mode

    def play(self, row):
        self.current_index = row
        self.is_playing = True
        self.is_paused = False

    def create_playlist(self, name):
        if name in self._playlists:
            return False
        self._playlists.append(name)
        return True

    def rename_playlist(self, current, new):
        if current not in self._playlists or new in self._playlists:
            return False
        index = self._playlists.index(current)
        self._playlists[index] = new
        if self.current_playlist_name == current:
            self.current_playlist_name = new
        return True

    def delete_playlist(self, name):
        if name not in self._playlists:
            return False
        self._playlists.remove(name)
        if self.current_playlist_name == name:
            self.current_playlist_name = self._playlists[0] if self._playlists else ""
        return True

    def add_track(self, path):
        self._playlist.append({"title": path, "artist": "", "duration": 0, "type": "local", "path": path})

    def remove_track(self, row):
        if 0 <= row < len(self._playlist):
            self._playlist.pop(row)

    def clear_playlist(self):
        self._playlist = []


def test_music_page_status_cards_track_link_mode_and_playlist(qapp, monkeypatch):
    import pages.music_page as music_page_module

    dummy = _DummyMusicPlayer()
    monkeypatch.setattr(music_page_module, "get_music_player", lambda: dummy)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    # ⚠⚠ **钉住这一页的总开关**（RN-141 第 7 例，RN-425 逼出来的）。
    # 这条判据断言胶囊写「联动 · **已启用**」，而那三个字现在是**三态**的：
    # 子开关开着但总开关关着 ⇒ 「已配置」（配好了，但没在跑）。
    # 它以前碰巧一直绿，只因为那时候这句话**根本不看总开关** ——
    # 也就是说它断言的正是那句假话。⭐ **一条判据钉住的如果是缺陷本身，
    #   它就会在缺陷被修掉的那天变红，而那是它唯一一次说真话。**
    monkeypatch.setattr(config, "music_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_play_mode", "repeat_all", raising=False)
    monkeypatch.setattr(config, "music_current_playlist", "默认", raising=False)
    monkeypatch.setattr(config, "music_death_action", "play", raising=False)
    monkeypatch.setattr(config, "music_death_volume_custom", False, raising=False)
    monkeypatch.setattr(config, "music_death_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.4, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_fade_out_duration", 0.5, raising=False)

    page = music_page_module.MusicPage()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    assert "联动 · 已启用" in chips
    assert "模式 · 列表循环" in chips
    assert "列表 · 默认" in chips
    assert "曲目 · 3 首" in chips
    assert "播放 · 已就绪" in chips
    assert "当前策略：联动已启用" in page.link_policy_label.text()
    assert "阵亡后自动开始/继续播放" in page.death_summary_label.text()
    assert "存活时自动降低到 40%" in page.alive_summary_label.text()
    assert "当前模式：列表循环" in page.play_mode_summary_label.text()
    assert "当前曲目：Inferno Pulse" in page.playlist_meta_label.text()
    assert "来源 本地 2 / URL 1" in page.playlist_meta_label.text()
    assert page.playlist_widget.maximumHeight() == 320
    assert page.action_bar.secondary_btn.text() == "刷新列表"
    assert page.action_bar.primary_btn.text() == "添加音乐"

    page.playlist_widget.item(1).setSelected(True)
    qapp.processEvents()
    assert "已选 1 首" in page.action_bar.message_label.text()

    page.play_mode_group.button(1).click()
    qapp.processEvents()
    assert dummy.play_mode == "shuffle"
    assert "当前默认模式为随机播放" in page.play_mode_hint_label.text()

    page.game_link_checkbox.setChecked(False)
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert "联动 · 已关闭" in chips
    # ⚠ 措辞在批 18 统一了：同一个状态原来有两个词 —— 胶囊写「联动 · 已关闭」、
    # 摘要写「联动未启用」。⭐ **一个状态两个说法，读的人会去找那个不存在的区别。**
    assert "联动已关闭" in page.link_policy_label.text()
    assert page.link_content_frame.isEnabled() is False

    page.deleteLater()
    qapp.processEvents()


def test_music_page_compact_top_section_avoids_horizontal_clipping(qapp, monkeypatch):
    import pages.music_page as music_page_module

    dummy = _DummyMusicPlayer()
    monkeypatch.setattr(music_page_module, "get_music_player", lambda: dummy)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_play_mode", "repeat_all", raising=False)
    monkeypatch.setattr(config, "music_current_playlist", "默认", raising=False)
    monkeypatch.setattr(config, "music_death_action", "play", raising=False)
    monkeypatch.setattr(config, "music_death_volume_custom", False, raising=False)
    monkeypatch.setattr(config, "music_death_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.4, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_fade_out_duration", 0.5, raising=False)

    page = music_page_module.MusicPage()
    page.resize(1180, 860)
    page.show()
    qapp.processEvents()

    assert page.top_settings_row.direction() == QBoxLayout.TopToBottom
    assert page.link_content_layout.direction() == QBoxLayout.TopToBottom
    assert page.settings_scroll.horizontalScrollBar().maximum() == 0

    page.deleteLater()
    qapp.processEvents()


def test_voice_output_page_status_card_tracks_runtime_and_forwarding(qapp, monkeypatch):
    import pages.voice_output_page as voice_output_page_module

    dummy = _DummyVoiceOutputManager()
    monkeypatch.setattr(voice_output_page_module, "get_voice_output_manager", lambda: dummy)
    monkeypatch.setattr(voice_output_page_module.keyboard, "add_hotkey", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_output_page_module.keyboard, "remove_hotkey", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_output_page_module.keyboard, "hook", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(voice_output_page_module.keyboard, "unhook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    # ⚠⚠ **这一条前置状态原来是"看命"的**（2026-08-27 批 16 逮到）。
    # 下面断言底栏最后一句是「当前标签：语音设置 …」，而 `voice_output_enabled`
    # 一旦为真，`register_hotkeys` 会在那之后**再写一句**「音板快捷键已就绪（N 个）」
    # 把它冲掉。判据不钉这个值，靠的是那个**跨轮次累积**的共享配置目录里恰好是 False
    # —— 别处一条判据拨了一次总开关，这一条就红，而红的原因跟被判的改动无关。
    # ⭐ RN-141 那条规矩的第四个实例：**判据的前置状态要么它自己钉，要么 conftest
    #   统一钉死；不许"看命"。**
    monkeypatch.setattr(config, "voice_output_enabled", False, raising=False)
    monkeypatch.setattr(config, "voice_output_volume", 0.65, raising=False)
    monkeypatch.setattr(config, "voice_output_mode", "覆盖", raising=False)
    monkeypatch.setattr(config, "voice_output_also_local", True, raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_enabled", True, raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_key", "V", raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_delay", 500, raising=False)
    monkeypatch.setattr(config, "voice_output_stop_key", "F8", raising=False)
    monkeypatch.setattr(config, "voice_output_microphone", "USB Mic", raising=False)
    monkeypatch.setattr(
        config,
        "voice_output_slots",
        {"0": {"audio": "demo.wav", "key": "ctrl+1", "volume": 0.8, "name": "Demo Clip"}},
        raising=False,
    )
    monkeypatch.setattr(config, "sfx_forwarding_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "sfx_forwarding_options",
        {
            "kill_sound": True,
            "kill_voice": False,
            "switch_weapon": True,
            "reload_sound": False,
            "gun_sound": False,
            "death_sound": False,
            "special_sound": True,
            "round_sound": False,
        },
        raising=False,
    )

    page = voice_output_page_module.VoiceOutputPage()

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text.startswith("驱动 · 已就绪") for text in chips)
    assert any(text.startswith("模式 · 覆盖") for text in chips)
    assert any(text.startswith("槽位 · 1/5") for text in chips)
    assert any(text.startswith("转发 · 3/8") for text in chips)
    assert "虚拟驱动已就绪" in page.driver_hint_label.text()
    assert "当前路由：覆盖" in page.routing_summary_label.text()
    assert "当前麦克风：USB Mic" in page.config_summary_label.text()
    assert "主音量：65%" in page.status_card.toolTip()
    assert "PTT：V · 已启用" in page.status_card.toolTip()
    assert "中断键：F8" in page.status_card.toolTip()
    # ⚠ 2026-08-30（RN-448·批 29）：「最近操作：就绪」已改。
    #   「就绪」是建出来就写死的初始占位符，而同一屏上徽章写着「驱动 · 待安装」；
    #   「最近状态」这个词又同时能读成「现在是否就绪」。外审 S4 13 处提及。
    assert "最近操作：还没有操作" in page.summary_label.toolTip()
    # ⭐ RN-452（批 31）：底栏次位原来是「使用说明」，而「驱动与说明」卡里
    #   紧挨着「安装驱动」还有一颗一模一样的 —— 外审窗口图 8 发 8/8 报的就是这一对，
    #   而两颗都是 `secondaryButton`（**一颗紫的都不是**）。说明归那张卡，底栏空着。
    assert page.action_bar.secondary_btn.isHidden() is True
    assert page.driver_help_button.text() == "使用说明"
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.primary_btn.text() == "添加槽位"
    assert "当前标签：语音设置" in page.action_bar.message_label.text()
    assert "最近操作：还没有操作" in page.action_bar.message_label.text()

    page.tab_widget.setCurrentIndex(1)
    qapp.processEvents()
    # ⭐ RN-452：底栏原来是「导出配置」，接的是「输入设备与配置」卡里那颗「导出」
    #   的同一个方法 —— **文案不同、动作相同**，所以按文案找重复的判据看不见它。
    assert page.action_bar.primary_btn.isHidden() is True
    assert page.export_button.text() == "导出"
    assert "当前标签：音效转发" in page.action_bar.message_label.text()
    assert "转发已启用 3/8" in page.action_bar.message_label.text()

    page._set_status_text("▶ 播放: Demo Clip")
    assert "最近操作：▶ 播放: Demo Clip" in page.status_card.toolTip()
    assert "最近操作：▶ 播放: Demo Clip" in page.action_bar.message_label.text()

    page._update_volume(40)
    assert "主音量：40%" in page.status_card.toolTip()

    page._update_sfx_forwarding(Qt.CheckState.Unchecked)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "转发 · 未启用" for text in chips)
    assert "音效转发：未启用（3/8）" in page.status_card.toolTip()
    assert "转发未启用 3/8" in page.action_bar.message_label.text()

    monkeypatch.setattr(
        config,
        "voice_output_slots",
        {"0": {"audio": "reloaded.wav", "key": "ctrl+2", "volume": 0.55, "name": "Reloaded Clip"}},
        raising=False,
    )
    page._reload_slots_from_config()
    assert page.soundboard_slots[0]["audio_label"].text() == "Reloaded Clip"
    assert page.soundboard_slots[0]["preview_button"].isEnabled() is True
    assert page.soundboard_slots[0]["volume_label"].text() == "55%"

    page.cleanup()
    page.deleteLater()
    qapp.processEvents()


def test_voice_output_page_compact_toolbar_layout_stays_visible(qapp, monkeypatch):
    import pages.voice_output_page as voice_output_page_module

    dummy = _DummyVoiceOutputManager()
    monkeypatch.setattr(voice_output_page_module, "get_voice_output_manager", lambda: dummy)
    monkeypatch.setattr(voice_output_page_module.keyboard, "add_hotkey", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_output_page_module.keyboard, "remove_hotkey", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_output_page_module.keyboard, "hook", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(voice_output_page_module.keyboard, "unhook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "voice_output_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "voice_output_mode", "覆盖", raising=False)
    monkeypatch.setattr(config, "voice_output_also_local", True, raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_enabled", True, raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_key", "V", raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_delay", 500, raising=False)
    monkeypatch.setattr(config, "voice_output_stop_key", "F8", raising=False)
    monkeypatch.setattr(config, "voice_output_microphone", "默认", raising=False)
    monkeypatch.setattr(config, "voice_output_slots", {}, raising=False)
    monkeypatch.setattr(config, "sfx_forwarding_enabled", False, raising=False)
    monkeypatch.setattr(config, "sfx_forwarding_options", {}, raising=False)

    page = voice_output_page_module.VoiceOutputPage()
    page.resize(1320, 860)
    page.show()
    qapp.processEvents()

    assert page.control_frame.height() >= page.control_frame.layout().sizeHint().height()
    assert page.soundboard_tools_frame.height() >= page.soundboard_tools_frame.layout().sizeHint().height()
    assert page.stop_key_button.y() == page.ptt_key_button.y()
    assert abs(page.stop_key_button.geometry().center().y() - page.ptt_enabled_check.geometry().center().y()) <= 8

    page.cleanup()
    page.deleteLater()
    qapp.processEvents()


class _DummyFlashProcessManager:
    def __init__(self, _config):
        self.is_running = False
        self.calls = []

    def update_settings(self, **kwargs):
        self.calls.append(("settings", kwargs))

    def update_fade_settings(self, **kwargs):
        self.calls.append(("fade", kwargs))

    def update_flash_style(self, style):
        self.calls.append(("style", style))

    def update_style_parameters(self, params):
        self.calls.append(("params", params))

    def load_flash_image(self, style):
        self.calls.append(("image", style))

    def update_image_rotation(self, rotation):
        self.calls.append(("image_rotation", rotation))

    def update_audio_enabled(self, enabled):
        self.calls.append(("audio_enabled", enabled))

    def update_audio_style(self, style):
        self.calls.append(("audio_style", style))

    def update_audio_volume(self, volume):
        self.calls.append(("audio_volume", volume))

    def update_auto_stop_setting(self, enabled):
        self.calls.append(("audio_stop", enabled))

    def start_process(self, width, height):
        self.is_running = True
        self.calls.append(("start", width, height))

    def stop_process(self):
        self.is_running = False
        self.calls.append(("stop",))

    def preview_flash(self, intensity, duration):
        self.calls.append(("preview", intensity, duration))

    def play_test_audio(self):
        self.calls.append(("test_audio",))


def test_flash_page_status_card_tracks_media_and_preview(qapp, tmp_path, monkeypatch):
    import pages.flash_page as flash_page_module

    app_data = tmp_path / "appdata"
    (app_data / "resources" / "flash_images" / "poster").mkdir(parents=True, exist_ok=True)
    (app_data / "resources" / "flash_audio" / "beep").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(flash_page_module, "FlashProcessManager", _DummyFlashProcessManager)
    monkeypatch.setattr(flash_page_module, "get_app_data_dir", lambda: str(app_data))
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "flash_enabled", True, raising=False)
    monkeypatch.setattr(config, "flash_bg_color", "red", raising=False)
    monkeypatch.setattr(config, "flash_max_opacity", 0.75, raising=False)
    monkeypatch.setattr(config, "flash_fade_in_enabled", True, raising=False)
    monkeypatch.setattr(config, "flash_fade_out_enabled", False, raising=False)
    monkeypatch.setattr(config, "flash_style", "blur", raising=False)
    monkeypatch.setattr(config, "flash_style_params", {"blur": {"blur_factor": 0.3, "blur_layers": 5}}, raising=False)
    monkeypatch.setattr(config, "flash_image_style", "poster", raising=False)
    monkeypatch.setattr(config, "flash_image_rotation", "random", raising=False)
    monkeypatch.setattr(config, "flash_image_opacity", 0.4, raising=False)
    monkeypatch.setattr(config, "flash_image_position", (0.2, 0.8), raising=False)
    monkeypatch.setattr(config, "flash_image_size", (0.45, 0.55), raising=False)
    monkeypatch.setattr(config, "flash_audio_enabled", True, raising=False)
    monkeypatch.setattr(config, "flash_audio_style", "beep", raising=False)
    monkeypatch.setattr(config, "flash_audio_rotation", "sequence", raising=False)
    monkeypatch.setattr(config, "flash_audio_volume", 0.6, raising=False)
    monkeypatch.setattr(config, "flash_audio_auto_stop", True, raising=False)

    page = flash_page_module.FlashPage()
    page.resize(1400, 960)
    page.show()
    qapp.processEvents()

    # ⚠ RN-009：同上 —— 原来这一行要求死控件存在且隐藏。
    # 本用例下面已经在断言 `status_card.toolTip()` 里有那几行详情，覆盖没丢。
    assert not hasattr(page, "summary_label")
    assert page.basic_top_layout.direction() == QBoxLayout.LeftToRight
    assert page.basic_overview_title_label.text() == "红色背景 · 75%"
    assert page.basic_overview_meta_label.text() == "模糊 · 图像+音频 · 淡入开 / 淡出关"
    assert page.basic_overview_hint_label.text() == "图片 poster · 音频 beep · 状态 就绪 · 运行 已就绪"
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    assert any(text.startswith("效果 · 已启用") for text in chips)
    assert any(text.startswith("样式 · 模糊") for text in chips)
    assert any(text.startswith("媒体 · 图像+音频") for text in chips)
    assert any(text.startswith("页面 · 基础设置") for text in chips)
    assert any(text.startswith("运行 · 已就绪") for text in chips)
    assert "背景：红色 75%" in page.status_card.toolTip()
    assert "图片：poster · 轮换 random · 不透明度 40%" in page.status_card.toolTip()
    assert "音频：已启用 · beep · 轮换 sequence · 音量 60%" in page.status_card.toolTip()
    assert page.action_bar.secondary_btn.isHidden() is False
    assert page.action_bar.primary_btn.isHidden() is False
    assert page.action_bar.secondary_btn.text() == "重置设置"
    assert page.action_bar.primary_btn.text() == "前往效果预览"
    assert "当前页面：基础设置" in page.action_bar.message_label.text()

    page.tab_widget.setCurrentIndex(3)
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("页面 · 音频设置") for text in chips)
    assert page.action_bar.secondary_btn.text() == "刷新音频列表"
    assert page.action_bar.primary_btn.text() == "打开音频文件夹"
    assert "当前页面：音频设置" in page.action_bar.message_label.text()

    page._on_audio_enabled_toggled(False)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("媒体 · 图像") for text in chips)
    assert "音频：未启用 · beep · 轮换 sequence · 音量 60%" in page.status_card.toolTip()
    assert "音频 关闭" in page.basic_overview_hint_label.text()

    page.tab_widget.setCurrentIndex(4)
    qapp.processEvents()
    assert page.action_bar.secondary_btn.text() == "50%预览"
    assert page.action_bar.primary_btn.text() == "自定义强度预览"

    page._do_preview(0.5)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("运行 · 预览中") for text in chips)
    assert ("preview", 0.5, page.preview_duration) in page.process_manager.calls
    assert "当前页面：效果预览" in page.action_bar.message_label.text()
    assert "状态 预览中... (50%, 3秒)" in page.basic_overview_hint_label.text()

    page.resize(980, 960)
    qapp.processEvents()
    assert page.basic_top_layout.direction() == QBoxLayout.TopToBottom

    page.cleanup()
    page.deleteLater()
    qapp.processEvents()


def test_magnifier_page_status_card_tracks_runtime_and_weapon_scope(qapp, monkeypatch):
    import pages.magnifier_page as magnifier_page_module

    class _DummyThemeManager:
        def register_theme_changed_callback(self, _callback):
            return None

        def unregister_theme_changed_callback(self, _callback):
            return None

    monkeypatch.setattr(magnifier_page_module, "install_help_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(magnifier_page_module, "get_theme_manager", lambda: _DummyThemeManager())
    monkeypatch.setattr(magnifier_page_module, "magnification_available", True)
    monkeypatch.setattr(magnifier_page_module, "MagInitialize", lambda: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagUninitialize", lambda: True, raising=False)
    monkeypatch.setattr(
        magnifier_page_module,
        "MagSetFullscreenTransform",
        lambda *_args, **_kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(magnifier_page_module, "MagShowSystemCursor", lambda *_args, **_kwargs: True, raising=False)
    monkeypatch.setattr(
        magnifier_page_module.user32,
        "GetSystemMetrics",
        lambda index: 1920 if index == 0 else 1080,
        raising=False,
    )
    monkeypatch.setattr(magnifier_page_module.MagnifierPage, "_setup_key_detection", lambda self: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "magnifier_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "magnifier",
        {
            "zoom_factor": 2.0,
            "primary_hotkey": "右键",
            "secondary_hotkey": "右键",
            "trigger_mode": "长按触发",
            "sensitivity_sync_enabled": False,
            "base_sensitivity": 1.0,
            "sensitivity_multiplier": 0.82,
            "sync_trigger_key": "SCROLLLOCK",
            "weapon_settings": {
                "weapon_awp": True,
                "weapon_hegrenade": False,
            },
            "zoom_settings": {"2.0": {"x_offset": 0, "y_offset": 0}},
        },
        raising=False,
    )

    page = magnifier_page_module.MagnifierPage(config)

    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 5
    assert any(text.startswith("开关 · 已启用") for text in chips)
    assert any(text.startswith("倍率 · 2.0x") for text in chips)
    assert any(text.startswith("触发 · 长按") for text in chips)
    assert any(text.startswith("分类 · 手枪") for text in chips)
    assert any(text.startswith("运行 · 待命") for text in chips)
    assert page.base_sensitivity_input.isEnabled() is True
    assert page.sensitivity_multiplier_input.isEnabled() is True
    assert "预设开镜灵敏度" in page.sensitivity_preview_label.text()
    assert "当前档位：2.0x" in page.zoom_profile_label.text()
    assert "当前触发：长按触发" in page.trigger_summary_label.text()
    assert "当前记录：X 0 / Y 0" in page.offset_profile_label.text()
    assert "当前状态：开镜放大已启用" in page.status_card.toolTip()
    assert "当前武器：未识别" in page.status_card.toolTip()
    assert "主武器热键：右键 · 手枪热键：右键" in page.status_card.toolTip()
    assert "灵敏度联动：未启用 · 预设" in page.status_card.toolTip()
    # ⚠⚠ 2026-08-30（RN-277·批 28）：**这四行原来钉的是缺陷本身** ——
    #   原文逐字要求 `primary_btn.text() == "全选武器"`，而下面还有一行
    #   要求全选之后它变成 `"全不选武器"`。那颗按钮是全页唯一的高亮控件，
    #   54 把武器默认全勾 ⇒ 每个新用户看到的就是「全不选武器」，
    #   点一下 54 个复选框全清空、当场落盘、没有确认也没有撤销。
    #   外审行为题 12 发：「点它是靠近目标还是反方向」**12/12「反方向」**。
    # ⭐ 这是 RN-084 那一族的又一个实例：**一条要求缺陷必须存在的判据** ——
    #   它比「判据假绿」更隐蔽，假绿是没人看着，这个是**有人按着不让改**。
    # ⇒ 底栏两个槽位现在都空着（这一页没有该由底栏承担的动作），
    #   而「全选 / 全不选 / 应用」三颗仍在各自的卡里 ——
    #   由 `test_the_loudest_button_is_not_the_undo_button.py` 的三条反向守卫钉住。
    assert page.action_bar.secondary_btn.isHidden() is True
    assert page.action_bar.primary_btn.isHidden() is True
    assert page.action_bar.secondary_btn.text() == ""
    assert page.action_bar.primary_btn.text() == ""
    # 底栏那句话现在负责回答「我到底要不要点什么」（本页 SAVES_AUTOMATICALLY=False，
    # 共用回执不替它说存不存 —— 批 24 定的分工）。
    assert "改完就存下了" in page.action_bar.message_label.text()
    assert "应用" in page.action_bar.message_label.text()
    assert "已勾选" in page.action_bar.message_label.text()

    page.base_sensitivity_input.setFocus()
    page.base_sensitivity_input.selectAll()
    QTest.keyClicks(page.base_sensitivity_input, "1.25")
    page.sensitivity_multiplier_input.setFocus()
    page.sensitivity_multiplier_input.selectAll()
    QTest.keyClicks(page.sensitivity_multiplier_input, "0.73")
    qapp.processEvents()
    page._on_sensitivity_values_changed()
    assert config.magnifier["base_sensitivity"] == pytest.approx(1.25)
    assert config.magnifier["sensitivity_multiplier"] == pytest.approx(0.73)
    assert "已更新灵敏度预设" in page.status_card.toolTip()

    page.update_current_weapon("weapon_awp")
    qapp.processEvents()
    assert "当前武器：AWP" in page.status_card.toolTip()
    # ⚠ 底栏那句话不再复述「当前武器」（RN-277 重写时删的，另见旧账 RN-279 →
    #   RN-445：现象没了，但「软件认没认出武器」这个问题一个字都没被回答）。
    #   它仍然在状态卡的详情里 —— 上一行就是。

    page.weapon_tabview.setCurrentIndex(3)
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("分类 · 狙击枪") for text in chips)
    assert "当前分类：狙击枪" in page.status_card.toolTip()

    page._select_all_weapons()
    qapp.processEvents()
    # ⭐ 原来这里断言它变成「全不选武器」—— 那正是缺陷。现在断言它**保持空着**：
    #   底栏不该跟着勾选状态长出一颗破坏性按钮。
    assert page.action_bar.primary_btn.text() == ""
    assert page.action_bar.primary_btn.isHidden() is True

    page.trigger_mode_combo.setCurrentText("单击切换")
    qapp.processEvents()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text.startswith("触发 · 切换") for text in chips)
    assert "触发方式：单击切换" in page.status_card.toolTip()

    page.cleanup()
    page.deleteLater()
    qapp.processEvents()
