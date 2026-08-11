# -*- coding: utf-8 -*-
"""首次使用三步引导（P4.1，2026-06-10）。

只对全新安装用户弹出一次（老用户由 config.onboarding_completed 豁免）。
三步：① 确认 CS2 目录 → ② 写入/校验 GSI 配置 → ③ 提示去试听。
设计为"轻量、健壮、可跳过"——任意步骤异常都不阻断；关闭即视为完成，
避免反复打扰。真正的功能调参仍在各功能页，这里只做最小可用引导。
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from config import config
from core.utils.logger import get_logger
from page_theme_helper import style_as_primary_button, style_as_secondary_button

logger = get_logger("Onboarding")


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("onboardingDialog")
        self.setWindowTitle("欢迎使用 CS2 Customizer · 快速上手")
        self.setModal(True)
        self.resize(560, 420)
        self._build_ui()
        self._refresh_states()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("三步开始使用")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        intro = QLabel("跟着下面三步走，就能让 CS2 Customizer 和 CS2 联动起来。随时可以「跳过」，之后在「高级设置 / 基础设置」里也能完成。")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # 第 1 步：CS2 目录
        layout.addWidget(self._step_header("第 1 步 · 选择 CS2 安装目录"))
        self.dir_label = QLabel("")
        self.dir_label.setObjectName("hintLabel")
        self.dir_label.setWordWrap(True)
        layout.addWidget(self.dir_label)
        row1 = QHBoxLayout()
        self.dir_btn = QPushButton("选择 CS2 目录")
        self.dir_btn.setFixedHeight(34)
        style_as_secondary_button(self.dir_btn)
        self.dir_btn.clicked.connect(self._choose_dir)
        row1.addWidget(self.dir_btn)
        row1.addStretch(1)
        layout.addLayout(row1)

        # 第 2 步：GSI 配置
        layout.addWidget(self._step_header("第 2 步 · 写入 GSI 联动配置"))
        self.gsi_label = QLabel("")
        self.gsi_label.setObjectName("hintLabel")
        self.gsi_label.setWordWrap(True)
        layout.addWidget(self.gsi_label)
        row2 = QHBoxLayout()
        self.gsi_btn = QPushButton("写入 / 校验 GSI 配置")
        self.gsi_btn.setFixedHeight(34)
        style_as_secondary_button(self.gsi_btn)
        self.gsi_btn.clicked.connect(self._write_gsi)
        row2.addWidget(self.gsi_btn)
        row2.addStretch(1)
        layout.addLayout(row2)

        # 第 3 步：试听（对标修缮：在引导内完成第一次"听到声音"的成功体验）
        layout.addWidget(self._step_header("第 3 步 · 先在这里试听一下"))
        self.preview_label = QLabel(
            "点击试听，确认能听到击杀音效；进游戏击杀时就是这个声音。想换音效/调音量，去左侧「击杀音效」「基础设置」。"
        )
        self.preview_label.setObjectName("hintLabel")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        row3 = QHBoxLayout()
        self.preview_btn = QPushButton("试听击杀音效")
        self.preview_btn.setFixedHeight(34)
        style_as_secondary_button(self.preview_btn)
        self.preview_btn.clicked.connect(self._preview_kill_sound)
        row3.addWidget(self.preview_btn)
        row3.addStretch(1)
        layout.addLayout(row3)

        layout.addStretch(1)

        # 底部按钮
        btn_row = QHBoxLayout()
        skip_btn = QPushButton("跳过")
        skip_btn.setFixedHeight(36)
        style_as_secondary_button(skip_btn)
        skip_btn.clicked.connect(self._finish)
        btn_row.addWidget(skip_btn)
        btn_row.addStretch(1)
        done_btn = QPushButton("完成，开始使用")
        done_btn.setFixedHeight(36)
        done_btn.setMinimumWidth(150)
        style_as_primary_button(done_btn)
        done_btn.clicked.connect(self._finish)
        btn_row.addWidget(done_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _step_header(text):
        lab = QLabel(text)
        lab.setObjectName("statusLabel")
        return lab

    def _refresh_states(self):
        # 状态用「已完成/待处理」文字而非 ✓/✗ 符号——个别字体环境符号会缺字形
        csgo_dir = str(getattr(config, "csgo_dir", "") or "")
        if csgo_dir and os.path.isdir(csgo_dir):
            self.dir_label.setText(f"【已完成】当前目录：{csgo_dir}")
        else:
            self.dir_label.setText("【待选择】请选择 Counter-Strike 根目录（软件会自动校验 game/csgo/cfg）。")

        try:
            from cfg_utils import find_cfg_path

            cfg_dir = find_cfg_path()
            if cfg_dir:
                self.gsi_label.setText("【已完成】GSI 配置就绪。如未生效，点下方按钮重写一次。")
            else:
                self.gsi_label.setText("【待写入】选好目录后点下方按钮，把 GSI 配置写进 CS2。")
        except Exception:
            self.gsi_label.setText("选好目录后点下方按钮写入 GSI 配置。")

    def _preview_kill_sound(self):
        """引导内试听一发击杀音（黄金路径的 aha moment）。"""
        try:
            from core.audio.runtime_audio import get_runtime_audio_manager

            am = get_runtime_audio_manager()
            try:
                am.ensure_styles_scanned()
            except Exception:
                pass
            played = False
            for key in ("kill-1", "kill-2", "kill-3"):
                try:
                    if am.play_sound(key, channel_type="kill_sound", event_type="preview", priority=50):
                        played = True
                        break
                except Exception:
                    continue
            if played:
                self.preview_label.setText("【已完成】听到了吗？进游戏击杀时就是这个声音。音量在「基础设置」可调。")
            else:
                self.preview_label.setText(
                    "暂时没有可用的击杀音效资源——首次启动资源可能还在后台准备，稍后到「击杀音效」页试听即可。"
                )
        except Exception:
            logger.exception("引导试听失败（忽略）")
            self.preview_label.setText("试听暂不可用，稍后到「击杀音效」页试听即可。")

    def _choose_dir(self):
        try:
            path = QFileDialog.getExistingDirectory(self, "选择 CS2 安装目录")
            if not path:
                return
            config.csgo_dir = path
            config.save_config()
            logger.info(f"引导：设置 CS2 目录 {path}")
            # 顺手尝试写入 GSI（成功与否都在 _refresh_states 体现）
            self._write_gsi(silent=True)
        except Exception:
            logger.exception("引导：选择目录失败（忽略）")
        finally:
            self._refresh_states()

    def _write_gsi(self, silent=False):
        try:
            from cfg_utils import ensure_cfg_exists, ensure_cs2customizer_cfg_exists

            csgo_dir = str(getattr(config, "csgo_dir", "") or "")
            if not (csgo_dir and os.path.isdir(csgo_dir)):
                if not silent:
                    self.gsi_label.setText("请先在第 1 步选择有效的 CS2 目录。")
                return
            ensure_cfg_exists(csgo_dir)
            try:
                ensure_cs2customizer_cfg_exists(csgo_dir)
            except Exception:
                pass
            logger.info("引导：GSI 配置已写入/校验")
        except Exception:
            logger.exception("引导：写入 GSI 配置失败（忽略）")
        finally:
            self._refresh_states()

    def _finish(self):
        try:
            config.onboarding_completed = True
            config.save_config()
        except Exception:
            logger.exception("引导：保存完成标记失败（忽略）")
        self.accept()

    def closeEvent(self, event):
        # 直接关闭窗口也视为完成，避免下次启动重复弹
        try:
            if not config.onboarding_completed:
                config.onboarding_completed = True
                config.save_config()
        except Exception:
            pass
        super().closeEvent(event)
