#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
后台资源加载器
实现三阶段异步加载策略，加速软件启动
"""

from PySide6.QtCore import QThread, Signal
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger
from resource_manager import ResourceManager


class BackgroundLoader(QThread):
    """后台加载器 - 只负责非UI资源加载"""
    
    # 信号定义
    stage_started = Signal(str, str)  # (stage_id, stage_name)
    stage_progress = Signal(str, int)  # (stage_id, progress 0-100)
    stage_completed = Signal(str)  # (stage_id)
    all_completed = Signal()
    error_occurred = Signal(str, str)  # (stage_id, error_message)
    
    # GSI连接请求信号（在主线程执行）
    connect_gsi_requested = Signal()
    
    def __init__(self, window, gsi_components, parent=None):
        super().__init__(parent)
        self.logger = get_logger("BackgroundLoader")
        self.window = window
        self.gsi_components = gsi_components
        self._is_cancelled = False
    
    def run(self):
        """执行后台加载（只负责非UI资源）"""
        try:
            # 阶段 2: 音频扫描
            self._load_stage_2()
            
            # 阶段 3: GSI连接（通过信号在主线程执行）
            self._load_stage_3()
            
            # 全部完成
            self.all_completed.emit()
            self.logger.info("✅ 所有资源加载完成!")
            
        except Exception as e:
            self.logger.error(f"后台加载失败: {e}", exc_info=True)
            self.error_occurred.emit("background", str(e))
    
    def _load_stage_2(self):
        """阶段 2: 音频资源扫描"""
        if self._is_cancelled:
            return
        
        self.stage_started.emit("stage2", "音频资源扫描")
        self.logger.info("📦 阶段 2: 扫描音频资源...")
        
        try:
            ResourceManager.copy_resources_to_appdata()
            audio_manager = get_runtime_audio_manager()
            
            # 扫描音频风格
            self.stage_progress.emit("stage2", 30)
            audio_manager.ensure_styles_scanned()
            self.logger.info("  ✓ 音频风格扫描完成")
            
            # 加载启用的音效
            self.stage_progress.emit("stage2", 60)
            audio_manager.load_all_enabled_sounds()
            self.logger.info(f"  ✓ 已加载 {len(audio_manager.sounds)} 个音效和 {len(audio_manager.voices)} 个语音")
            
            self.stage_progress.emit("stage2", 100)
            self.stage_completed.emit("stage2")
            self.logger.info("✓ 阶段 2 完成")
            
        except Exception as e:
            self.logger.error(f"阶段 2 加载失败: {e}", exc_info=True)
            self.error_occurred.emit("stage2", str(e))
    
    def _load_stage_3(self):
        """阶段 3: 请求主线程连接GSI"""
        if self._is_cancelled:
            return
        
        self.stage_started.emit("stage3", "GSI服务器启动")
        self.logger.info("📦 阶段 3: 请求启动GSI...")
        
        try:
            # 发送信号请求主线程连接GSI
            self.connect_gsi_requested.emit()
            
            self.stage_progress.emit("stage3", 100)
            self.stage_completed.emit("stage3")
            self.logger.info("✓ 阶段 3 完成")
            
        except Exception as e:
            self.logger.error(f"阶段 3 加载失败: {e}", exc_info=True)
            self.error_occurred.emit("stage3", str(e))
    
    def cancel(self):
        """取消加载"""
        self._is_cancelled = True
        self.logger.info("后台加载已取消")
