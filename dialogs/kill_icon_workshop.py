# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标素材工坊（KI-7）。

**为什么要有这一层**：KI-6 把五个击杀等级摊成一块清单板，每一格自带预览、
时长滑条、右键菜单，功能上是对的——但它被摆在了设置页的正中间。于是一个
只想"下载一套图标、拖进去、开着"的人，一进页面就要面对 30 多个可操作控件、
七八个概念（等级 / 爆头变体 / 帧率 / 定格 / 图集 / 帧序列 / 裁边 / 抠背景）。
**编辑器被当成了首页。**

参照物就在同一个软件里：击杀音效页没让用户逐帧调音频，准心页也没让用户
逐像素画十字。

所以这里把"做素材"整块搬进一个对话框：清单板、每格的节奏、导出、删除与撤销、
以及更深的那套（抠背景 / 裁边 / 手填行列 / 批量）都在这儿，一个都不少。
设置页只留"挑一套、开着、看效果"。

**这个对话框自己不做导入的活**：真正的转码走 `core.kill_icon_import`，
跑在 `KillIconImportTask` 的后台线程上（KI-5 起就是这样，整串解码打包在
UI 线程上会卡多久由用户素材大小决定）。

⚠ 判据不要去调 `_open_sprite_maker` / 任何 `exec()`：模态对话框在测试进程里
是**卡死不是失败**。要验的东西都摆在了非模态的方法上。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from core.kill_icon_library import LEVELS, delete_level, level_entry, restore_level
from core.utils.logger import get_logger
from kill_icon_overlay import fps_for_duration, load_level_animation
from resource_manager import ResourceManager
from widgets.drop_import_mixin import enable_file_drop
from widgets.kill_icon_import_task import KillIconImportTask
from widgets.kill_icon_level_grid import (
    DROP_EXTENSIONS, KillIconLevelGrid, columns_for_width
)


class KillIconWorkshop(QDialog):
    """素材工坊。关掉之后设置页会 `library_changed` 收到一枪并重刷。"""

    library_changed = Signal()

    def __init__(self, style_name, player=None, parent=None):
        super().__init__(parent)
        self.logger = get_logger("KillIconWorkshop")
        self.style_name = str(style_name or "")
        self.player = player
        self._undo_token = None
        self._dirty = False
        self._changed = False

        self._import_task = KillIconImportTask(self)
        self._import_task.progress.connect(self._on_import_progress)
        self._import_task.finished.connect(self._on_import_finished)
        self._import_task.failed.connect(self._on_import_failed)
        self._import_task.cancelled.connect(self._on_import_cancelled)

        self.setWindowTitle(f"素材工坊 — {self.style_name or '未选择风格'}")
        self.setModal(True)
        self.resize(880, 640)
        self.setMinimumSize(560, 420)

        self._init_ui()
        self.reload_styles()
        self.refresh()

    # ------------------------------------------------------------------ 建窗

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # ---- 顶栏：现状 + 风格切换器
        #
        # 切换器是补上来的：没有它的话，想给另一套图标补素材就得「完成」→ 回
        # 设置页点另一张卡 → 再点「打开素材工坊」。工坊本来就是"做素材"的地方，
        # 做素材的人手里往往不止一套。
        header = QHBoxLayout()
        header.setSpacing(8)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        header.addWidget(self.summary_label, 1)

        header.addWidget(QLabel("风格："))
        self.style_combo = QComboBox()
        self.style_combo.setMinimumWidth(150)
        self.style_combo.setToolTip("在这儿换一套来编辑；关窗之后设置页也会跟着用这一套")
        self.style_combo.currentTextChanged.connect(self._on_style_switched)
        header.addWidget(self.style_combo)
        layout.addLayout(header)

        # ---- 页内提示条（取代弹窗；还能挂「撤销」，弹窗关掉就没了）
        self.notice_frame = QFrame()
        self.notice_frame.setObjectName("card")
        notice_layout = QHBoxLayout(self.notice_frame)
        notice_layout.setContentsMargins(10, 6, 10, 6)
        notice_layout.setSpacing(8)
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("hintLabel")
        self.notice_label.setWordWrap(True)
        notice_layout.addWidget(self.notice_label, 1)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("secondaryButton")
        self.undo_btn.setFixedHeight(26)
        self.undo_btn.clicked.connect(self._undo_last_delete)
        self.undo_btn.hide()
        notice_layout.addWidget(self.undo_btn)
        dismiss_btn = QPushButton("知道了")
        dismiss_btn.setObjectName("secondaryButton")
        dismiss_btn.setFixedHeight(26)
        dismiss_btn.clicked.connect(self._clear_notice)
        notice_layout.addWidget(dismiss_btn)
        self.notice_frame.hide()
        layout.addWidget(self.notice_frame)

        # ---- 进度条（导入跑在后台线程上）
        self.progress_frame = QFrame()
        progress_layout = QHBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("hintLabel")
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(14)
        progress_layout.addWidget(self.progress_bar, 1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.setFixedHeight(26)
        self.cancel_btn.clicked.connect(self._import_task.cancel)
        progress_layout.addWidget(self.cancel_btn)
        self.progress_frame.hide()
        layout.addWidget(self.progress_frame)

        # ---- 清单板（放进滚动区：五格折行之后能比窗口高）
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(8)

        self.level_grid = KillIconLevelGrid()
        self.level_grid.files_dropped.connect(self._on_level_files_dropped)
        self.level_grid.duration_changed.connect(self._on_duration_changed)
        self.level_grid.action_triggered.connect(self._on_level_action)
        holder_layout.addWidget(self.level_grid)
        holder_layout.addStretch()
        self.scroll_area.setWidget(holder)
        layout.addWidget(self.scroll_area, 1)

        # ---- 底栏
        #
        # 五个按钮并排要 660px，而窗口最小宽是 560——直接用一行 QHBoxLayout
        # 的话，用户把窗口拖窄就会把按钮压扁/挤出去。所以摆成网格，
        # 列数跟着宽度折行（和上面清单板是同一套办法）。
        self.button_grid = QGridLayout()
        self.button_grid.setSpacing(8)
        self._button_columns = 0

        self.save_fps_btn = QPushButton("保存播放设置")
        self.save_fps_btn.setObjectName("actionButton")
        self.save_fps_btn.setFixedHeight(34)
        self.save_fps_btn.setMinimumWidth(120)
        self.save_fps_btn.clicked.connect(self._save_timing)

        self.advanced_btn = QPushButton("高级导入 / 批量…")
        self.advanced_btn.setObjectName("secondaryButton")
        self.advanced_btn.setFixedHeight(34)
        self.advanced_btn.setMinimumWidth(156)
        self.advanced_btn.setToolTip("抠背景、裁透明边、手填图集行列、按 1~5 批量导入")
        self.advanced_btn.clicked.connect(self._open_sprite_maker)

        self.export_pack_btn = QPushButton("导出图标包…")
        self.export_pack_btn.setObjectName("secondaryButton")
        self.export_pack_btn.setFixedHeight(34)
        self.export_pack_btn.setMinimumWidth(120)
        self.export_pack_btn.clicked.connect(self._export_pack)

        self.open_dir_btn = QPushButton("打开素材文件夹")
        self.open_dir_btn.setObjectName("secondaryButton")
        self.open_dir_btn.setFixedHeight(34)
        self.open_dir_btn.setMinimumWidth(130)
        self.open_dir_btn.clicked.connect(self._open_style_folder)

        self.close_btn = QPushButton("完成")
        self.close_btn.setObjectName("actionButton")
        self.close_btn.setFixedHeight(34)
        self.close_btn.setMinimumWidth(90)
        self.close_btn.clicked.connect(self.accept)

        self._buttons = [self.save_fps_btn, self.advanced_btn, self.export_pack_btn,
                         self.open_dir_btn, self.close_btn]
        layout.addLayout(self.button_grid)

        # 拖到窗口空白处 = 拖到某一格之外的地方，走小窗问一句用在几杀
        enable_file_drop(self, DROP_EXTENSIONS, self._on_files_dropped,
                         accept_directories=True)

        self._update_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_layout()

    def _update_layout(self):
        self._update_columns()
        self._update_button_columns()

    def _update_columns(self):
        # 列数按**滚动可视区**算，不是按窗口宽：两者能差出一条滚动条的宽度，
        # 按窗口宽算会让板子比可视区宽，横向溢出。
        if not hasattr(self, "level_grid"):
            return
        viewport = self.scroll_area.viewport().width() if hasattr(self, "scroll_area") else 0
        self.level_grid.set_columns(columns_for_width(viewport or self.width()))

    #: 五个按钮并排实测要 660px，而窗口最小宽是 560。窄了就折成两列，
    #: 不是把按钮压扁（写死宽度 + 中文文案 + 字号缩放 = 截断，UP-094 的教训）。
    BUTTONS_ONE_ROW_WIDTH = 700

    def _update_button_columns(self):
        if not getattr(self, "_buttons", None):
            return
        columns = len(self._buttons) if self.width() >= self.BUTTONS_ONE_ROW_WIDTH else 2
        if columns == self._button_columns:
            return
        self._button_columns = columns
        for button in self._buttons:
            self.button_grid.removeWidget(button)
        for index, button in enumerate(self._buttons):
            self.button_grid.addWidget(button, index // columns, index % columns)

    # ------------------------------------------------------------------ 风格

    def reload_styles(self):
        """把风格库喂给切换器。**不发信号**——这是"读回来"，不是用户在切。

        当前风格即使已经从磁盘上消失也要留在列表里：否则 `clear()` 之后
        `findText` 落空、下拉静默停在第一项，而 `self.style_name` 还是老的，
        标题栏和下拉从此各说各话。
        """
        try:
            styles = list(ResourceManager.list_kill_icon_styles() or [])
        except Exception as exc:
            self.logger.error(f"扫描风格失败: {exc}")
            styles = []
        if self.style_name and self.style_name not in styles:
            styles.insert(0, self.style_name)

        blocked = self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItems(styles)
        index = self.style_combo.findText(self.style_name)
        if index >= 0:
            self.style_combo.setCurrentIndex(index)
        self.style_combo.blockSignals(blocked)
        self.style_combo.setEnabled(len(styles) > 1)

    def _on_style_switched(self, name):
        """换一套来编辑。**同时也换掉正在用的那一套。**

        不这么做就会分家：工坊改素材靠 `player.load_style()`，播放器只有一个
        "当前风格"，切了就是切了。与其让设置页和播放器指着两套，不如让这一次
        切换一路传到底——关窗时设置页会把选中卡片同步过来。
        """
        name = str(name or "")
        if not name or name == self.style_name:
            return
        # 先把没落盘的节奏落掉：切过去再切回来，改动就找不回来了
        if self._dirty:
            self._apply_timing()
        self.style_name = name
        self.setWindowTitle(f"素材工坊 — {name}")
        self._changed = True
        if self.player:
            try:
                self.player.load_style(name)
            except Exception as exc:
                self.logger.error(f"切换风格失败: {exc}")
        self.refresh()

    # ------------------------------------------------------------------ 刷新

    def frame_count(self, kills):
        """这个等级有多少帧。数不出来返回 0——调用方据此把滑条禁掉。"""
        if not self.player or not self.style_name:
            return 0
        try:
            return int(self.player.get_style_frame_count(self.style_name, kills) or 0)
        except Exception:
            return 0

    def ready_levels(self):
        return [k for k in LEVELS if self.frame_count(k) > 0]

    def refresh(self):
        """把当前风格的五个等级重新喂给清单板。"""
        for kills in LEVELS:
            frames = self.frame_count(kills)
            cell = self.level_grid.cells.get(kills)
            if cell is None:
                continue
            cell.set_frame_count(frames)
            if frames <= 0:
                cell.set_timing_seconds(1.0)
                continue
            cell.set_timing_seconds(self._stored_seconds(kills, frames))

        for kills in LEVELS:
            entry = self._entry_for(kills)
            animation = None
            headshot = False
            if self.style_name:
                try:
                    animation = load_level_animation(self.style_name, kills)
                    headshot = load_level_animation(self.style_name, kills, "hs") is not None
                except Exception as exc:
                    self.logger.error(f"预览素材装载失败: {exc}")
            self.level_grid.set_state(kills, entry, animation, headshot)
            if animation is not None:
                # set_state 会把滑条按 entry 重置，节奏要再回填一次
                self.level_grid.cells[kills].set_timing_seconds(
                    self._stored_seconds(kills, self.frame_count(kills))
                )

        self._dirty = False
        self.save_fps_btn.setText("保存播放设置")
        self._sync_summary()

    def _stored_seconds(self, kills, frames):
        """风格里存的节奏换算成秒。单帧素材量的是定格时长。"""
        if frames <= 0 or not self.player:
            return 1.0
        fps = self.player.get_style_fps(self.style_name, kills)
        hold = 0.0
        if hasattr(self.player, "get_style_hold"):
            try:
                hold = float(self.player.get_style_hold(self.style_name, kills) or 0.0)
            except Exception:
                hold = 0.0
        if frames == 1 and hold:
            return hold
        return frames / float(max(1, fps))

    def _entry_for(self, kills):
        """这一格的现状。磁盘是唯一真源，但帧数以播放器为准（它有缓存）。"""
        try:
            entry = level_entry(self.style_name, kills) if self.style_name else None
        except Exception:
            entry = None
        if entry is None:
            from core.kill_icon_library import LevelEntry

            entry = LevelEntry(kills=kills)
        frames = self.frame_count(kills)
        if frames > 0:
            entry.frames = frames
            entry.kind = entry.kind or "sheet"
        return entry

    def _sync_summary(self):
        ready = self.ready_levels()
        missing = [k for k in LEVELS if k not in ready]
        self.summary_label.setText(
            f"风格「{self.style_name or '未选择'}」 · 已备素材 {len(ready)}/{len(LEVELS)} 个等级"
            + (f"（缺 {'、'.join(f'{k} 杀' for k in missing)}）" if missing else "")
            + (" · 播放设置尚未保存" if self._dirty else "")
        )

    # ------------------------------------------------------------------ 提示

    def _show_notice(self, message, undo_token=None):
        self._undo_token = undo_token
        self.notice_label.setText(message)
        self.notice_frame.show()
        self.undo_btn.setVisible(bool(undo_token))

    def _clear_notice(self):
        self._undo_token = None
        self.notice_frame.hide()
        self.undo_btn.hide()

    def _undo_last_delete(self):
        token = self._undo_token
        if not token:
            return
        if restore_level(token):
            self._clear_notice()
            self._reload_player()
            self._show_notice("已撤销，素材放回去了。")
        else:
            self._show_notice("撤销失败：这一格已经被新的素材占了。")

    # ------------------------------------------------------------------ 导入

    def _run_import(self, fn, label):
        if self._import_task.running:
            self._show_notice("上一次导入还没跑完，等一下再来。")
            return False
        self._clear_notice()
        self.progress_label.setText(label)
        self.progress_bar.setRange(0, 0)
        self.progress_frame.show()
        return self._import_task.start(fn, label)

    def _on_import_progress(self, done, total, stage):
        self.progress_label.setText(stage)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)

    def _on_import_finished(self, result):
        self.progress_frame.hide()
        if not (isinstance(result, dict) and "exported" in result):
            self._reload_player()
        self._show_notice(self.describe_result(result))

    def _on_import_failed(self, message):
        self.progress_frame.hide()
        self._show_notice(f"导入失败：{message}")

    def _on_import_cancelled(self):
        self.progress_frame.hide()
        self._show_notice("已取消，什么都没改。")

    def describe_result(self, result):
        if not isinstance(result, dict):
            return "导入完成。"

        if "exported" in result:
            exported = result["exported"]
            return (f"已导出「{exported['style']}」到 "
                    f"{os.path.basename(exported['path'])}"
                    f"（{len(exported['levels'])} 个等级，"
                    f"{exported['size'] // 1024} KB）")

        hold = result.get("hold_seconds") or 0.0
        timing = (f"定格 {hold:.1f} 秒" if result.get("frames") == 1 and hold
                  else f"{result.get('frames')} 帧 @ {result.get('fps')} FPS")
        lines = [
            f"已导入到「{result.get('style')}」的 {result.get('kills')} 杀"
            f"{'（爆头专用）' if result.get('variant') else ''}：{timing}"
        ]
        lines.extend(f"⚠ {w}" for w in (result.get("warnings") or [])[:3])
        return "\n".join(lines)

    def import_paths(self, paths, kills, variant=""):
        """把一批路径导进某个等级。"""
        from core.kill_icon_import import convert_to_style

        assets = [p for p in paths if not str(p).lower().endswith(".zip")]
        if not assets:
            self._show_notice("工坊里只处理单个素材；图标包(.zip)请在设置页上导入。")
            return False

        style = self.style_name or "默认"

        def _work(progress, cancel):
            result = None
            for path in assets:
                result = convert_to_style(path, style, kills, variant=variant,
                                          progress=progress, cancel=cancel)
            return result

        return self._run_import(_work, f"正在导入 {kills} 杀素材…")

    def _on_files_dropped(self, paths):
        """拖到窗口空白处：不知道用在哪一格，问一句。"""
        if not paths:
            return
        target = self._ask_target(paths[0])
        if target is None:
            return
        self.import_paths(paths, target[0], target[1])

    def _ask_target(self, path):
        """开导入小窗问「用在几杀」。取消返回 None。"""
        from dialogs.kill_icon_import_wizard import (
            KillIconImportError, wizard_target_for
        )

        try:
            return wizard_target_for(path, parent=self)
        except KillIconImportError as exc:
            self._show_notice(str(exc))
            return None

    def _on_level_files_dropped(self, kills, paths):
        """拖到某一格上：就进那一格。用户已经用位置表达了意图，不再问一遍。"""
        self.import_paths(paths, int(kills))

    def _choose_files_for(self, kills, variant):
        path, _filter = QFileDialog.getOpenFileName(
            self, f"选择 {kills} 杀的素材", "",
            "图片与动图 (*.gif *.webp *.png *.apng *.avif *.jpg *.jpeg *.bmp);;"
            "图集配置 (*.json);;所有文件 (*.*)")
        if path:
            self.import_paths([path], kills, variant)

    # ------------------------------------------------------------------ 每格

    def _on_level_action(self, action, kills):
        kills = int(kills)
        if action == "test":
            self.test_level(kills)
        elif action == "replace":
            self._choose_files_for(kills, "")
        elif action == "import_hs":
            self._choose_files_for(kills, "hs")
        elif action == "export":
            self._export_level(kills)
        elif action == "delete":
            self._delete_level(kills, "")
        elif action == "delete_hs":
            self._delete_level(kills, "hs")

    def test_level(self, kills):
        if not self.player:
            self._show_notice("图标播放器未初始化。")
            return
        frames = self.frame_count(kills)
        cell = self.level_grid.cells.get(int(kills))
        seconds = cell.seconds if cell else 0.0
        fps = fps_for_duration(frames, seconds) if frames > 1 else None
        self.player.play_icon(kills, fps)

    def _on_duration_changed(self, kills, _seconds=None):
        cell = self.level_grid.cells.get(int(kills))
        if cell is not None and not cell.is_static:
            frames = self.frame_count(kills)
            if frames > 0:
                cell.preview.set_fps(fps_for_duration(frames, cell.seconds))
        self._dirty = True
        self.save_fps_btn.setText("保存播放设置 *")
        self._sync_summary()

    def _apply_timing(self):
        """多帧素材换算成帧率落盘；单帧素材落的是定格时长。返回落了几个等级。

        对一张静态图来说"播放速度"没有意义，滑条量的直接就是"停多久"。

        单独拎出来是因为**关窗时也必须落一次**（见 `done`）：滑条一动，
        `_on_duration_changed` 立刻把预览的播放速度改了——用户眼里动画**已经
        变快了**，这时候点「完成」把改动扔掉就是静默数据丢失。第一版正是如此：
        `close_btn` 直接接 `accept`，全部提示只有按钮上一个 `*`。
        """
        if not self.player:
            return 0

        saved = 0
        for kills in LEVELS:
            frames = self.frame_count(kills)
            if frames <= 0:
                continue
            cell = self.level_grid.cells.get(kills)
            seconds = cell.seconds if cell else 0.0
            if frames == 1 and hasattr(self.player, "update_hold_for_style"):
                if self.player.update_hold_for_style(self.style_name, kills, seconds):
                    saved += 1
                continue
            fps = fps_for_duration(frames, seconds)
            if self.player.update_fps_for_style(self.style_name, kills, fps):
                saved += 1

        if saved > 0:
            self._dirty = False
            self.save_fps_btn.setText("保存播放设置")
            self._changed = True
        return saved

    def _save_timing(self):
        if not self.player:
            self._show_notice("图标播放器未初始化。")
            return
        saved = self._apply_timing()
        self._show_notice(f"已保存 {saved} 个击杀等级的播放设置。" if saved > 0
                          else "当前风格没有可保存的击杀等级。")
        self._sync_summary()

    def _export_level(self, kills):
        """把一格导成 `<等级>.png` + `.json`，方便单独分享或手工改。

        走 `convert_to_style(..., output_paths=...)` 而不是自己拷两个文件：
        逐帧目录的老素材也得能导出去，而"目录 → 图集"的转换只有那一条路。
        """
        from core.kill_icon_import import KillIconImportError, convert_to_style

        entry = self._entry_for(kills)
        if not self.style_name or not entry.exists:
            self._show_notice("这一格还没有素材。")
            return

        path, _filter = QFileDialog.getSaveFileName(
            self, f"导出 {kills} 杀素材", f"{kills}.png", "PNG 图集 (*.png)")
        if not path:
            return

        source = entry.json_path if entry.kind == "sheet" else entry.legacy_dir
        json_path = os.path.splitext(path)[0] + ".json"
        try:
            result = convert_to_style(source, self.style_name, kills,
                                      output_paths=(path, json_path))
        except (KillIconImportError, OSError) as exc:
            self._show_notice(f"导出失败：{exc}")
            return
        self._show_notice(
            f"已导出 {kills} 杀：{os.path.basename(result['sprite_path'])}"
            f" + {os.path.basename(result['json_path'])}")

    def _delete_level(self, kills, variant):
        if not self.style_name:
            return
        try:
            token = delete_level(self.style_name, kills, variant)
        except OSError as exc:
            self._show_notice(f"删除失败：{exc}")
            return
        if not token:
            self._show_notice("这一格本来就没有素材。")
            return
        self._reload_player()
        self._show_notice(
            f"已删除「{self.style_name}」的 {kills} 杀{'爆头' if variant else ''}素材。",
            undo_token=token)

    # ------------------------------------------------------------------ 其它

    def _export_pack(self):
        from core.kill_icon_pack import export_pack

        if not self.style_name:
            self._show_notice("还没有可导出的风格。")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "导出图标包", f"{self.style_name}.zip", "图标包 (*.zip)")
        if not path:
            return

        # 也走后台：逐帧目录要先转成图集，实测默认风格（519 帧）要 4 秒。
        def _work(progress, _cancel):
            return {"exported": export_pack(self.style_name, path, progress=progress)}

        self._run_import(_work, "正在打包…")

    def style_folder(self):
        """要交给资源管理器打开的那个目录。没有就返回空串。

        单独拎出来是因为**真调 `os.startfile` 会在用户屏幕上弹窗**，判据不能跑；
        而会出错的地方全在"算这个路径"这一段，那一段是可以验的。
        """
        if not self.style_name:
            return ""
        directory = ResourceManager.get_kill_icon_style_dir(self.style_name)
        return directory if directory and os.path.isdir(directory) else ""

    def _open_style_folder(self):
        directory = self.style_folder()
        if not directory:
            self._show_notice("这个风格还没有素材目录。")
            return
        try:
            os.startfile(directory)     # noqa: S606 - Windows 打开资源管理器
        except Exception as exc:
            self._show_notice(f"打不开目录：{exc}")

    def _open_sprite_maker(self):
        """更深的那一层：抠背景 / 裁边 / 手填行列 / 批量。"""
        try:
            from dialogs.sprite_sheet_maker import SpriteSheetMaker

            maker = SpriteSheetMaker(self)
            maker.exec()
            self._reload_player()
        except Exception as exc:
            self._show_notice("无法打开制作工具，请稍后重试。")
            self.logger.error(f"打开制作工具失败: {exc}")

    def _reload_player(self):
        """素材变了：让播放器重装当前风格，再刷一遍板子。"""
        self._changed = True
        if self.player and self.style_name:
            try:
                self.player.load_style(self.style_name)
            except Exception as exc:
                self.logger.error(f"重载风格失败: {exc}")
        self.refresh()
        self.library_changed.emit()

    def done(self, result):
        # 关窗**一定**先落盘。走 done() 而不是 accept()：叉掉窗口、按 Esc、
        # 点「完成」最后都汇到这儿，只拦其中一条等于没拦。
        # 这个对话框也没有"取消"的语义——导入/删除/切风格早就即时生效了，
        # 唯独节奏是攒着的，那才是不一致的地方。
        if self._dirty:
            self._apply_timing()
        self.level_grid.stop_previews()
        super().done(result)

    @property
    def changed(self) -> bool:
        """这次开窗有没有动过素材/节奏。设置页据此决定要不要重扫。"""
        return self._changed


def open_workshop(style_name, player=None, parent=None):
    """开一次工坊，返回它有没有改过东西。"""
    workshop = KillIconWorkshop(style_name, player=player, parent=parent)
    workshop.exec()
    return workshop.changed


__all__ = ["KillIconWorkshop", "open_workshop"]
