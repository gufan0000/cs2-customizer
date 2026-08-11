# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
击杀图标制作工具 (Sprite Sheet Maker)
将PNG图片序列合并为Sprite Sheet，提高加载性能
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QFileDialog, QMessageBox, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PIL import Image
import os
import json
import re
from core.utils.logger import get_logger
from theme_manager import get_theme_manager


class SpriteSheetMaker(QDialog):
    """Sprite Sheet 制作工具"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self.folder_path = ""
        
        self.setWindowTitle("击杀图标制作工具")
        self.setFixedSize(630, 580)
        
        # 应用主题样式
        self.theme_manager = get_theme_manager()
        self.setStyleSheet(self.theme_manager.get_stylesheet())
        
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # 标题
        title = QLabel("Sprite Sheet 制作工具")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 说明文本
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_layout = QVBoxLayout(info_frame)
        
        info_lines = []
        info_lines.append("将多张图片序列合并为一张Sprite Sheet，提高加载和播放性能。")
        info_lines.append("")
        info_lines.append("使用步骤:")
        info_lines.append("1. 选择包含图片序列的文件夹")
        info_lines.append("2. 设置每秒帧数（FPS）- 这将保存在配置文件中")
        info_lines.append("3. 点击'生成并保存'按钮")
        info_lines.append("4. 选择保存位置")
        info_lines.append("")
        info_lines.append("支持格式: PNG图片序列（自动识别文件名中的数字进行排序）")
        info_lines.append("输出格式: PNG Sprite Sheet + JSON配置文件")
        info_text = QLabel("\n".join(info_lines))
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_frame)
        
        # 输入区域
        input_frame = QFrame()
        input_layout = QVBoxLayout(input_frame)
        input_layout.setSpacing(12)
        
        # 文件夹选择
        folder_frame = QFrame()
        folder_frame.setFrameShape(QFrame.Shape.NoFrame)
        folder_layout = QHBoxLayout(folder_frame)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        
        folder_layout.addWidget(QLabel("图片文件夹:"))
        
        self.folder_entry = QLineEdit()
        self.folder_entry.setReadOnly(True)
        self.folder_entry.setMinimumWidth(300)
        folder_layout.addWidget(self.folder_entry)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.setObjectName("actionButton")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._select_folder)
        folder_layout.addWidget(browse_btn)
        
        input_layout.addWidget(folder_frame)
        
        # FPS设置
        fps_frame = QFrame()
        fps_frame.setFrameShape(QFrame.Shape.NoFrame)
        fps_layout = QHBoxLayout(fps_frame)
        fps_layout.setContentsMargins(0, 0, 0, 0)
        
        fps_layout.addWidget(QLabel("帧率 (FPS):"))
        
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setMinimum(1)
        self.fps_slider.setMaximum(60)
        self.fps_slider.setValue(30)
        self.fps_slider.setMinimumWidth(200)
        self.fps_slider.valueChanged.connect(self._update_fps_label)
        fps_layout.addWidget(self.fps_slider)
        
        self.fps_label = QLabel("30")
        self.fps_label.setFixedWidth(30)
        fps_layout.addWidget(self.fps_label)
        
        fps_layout.addStretch()
        
        input_layout.addWidget(fps_frame)
        
        layout.addWidget(input_frame)
        
        # 预览区域
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(preview_frame)
        
        preview_layout.addWidget(QLabel("预览:"))
        
        self.preview_label = QLabel("请选择文件夹")
        self.preview_label.setMinimumHeight(72)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setWordWrap(True)
        self.preview_label.setObjectName("previewLabel")
        preview_layout.addWidget(self.preview_label)
        
        layout.addWidget(preview_frame)
        
        # 按钮区域
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        generate_btn = QPushButton("生成并保存")
        generate_btn.setFixedHeight(36)
        generate_btn.setFixedWidth(150)
        generate_btn.setObjectName("primaryButton")
        generate_btn.clicked.connect(self._generate_sprite_sheet)
        button_layout.addWidget(generate_btn)
        
        batch_btn = QPushButton("批量处理")
        batch_btn.setObjectName("actionButton")
        batch_btn.setFixedHeight(36)
        batch_btn.setFixedWidth(150)
        batch_btn.clicked.connect(self._batch_process)
        button_layout.addWidget(batch_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryButton")
        close_btn.setFixedHeight(36)
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(close_btn)
        
        layout.addWidget(button_frame)
    
    def _update_fps_label(self, value):
        """更新FPS显示"""
        self.fps_label.setText(str(value))
    
    def _extract_number(self, filename):
        """从文件名中提取数字用于排序"""
        numbers = re.findall(r'\d+', filename)
        if numbers:
            return int(numbers[-1])
        return 0
    
    def _smart_sort_files(self, files):
        """智能排序文件列表"""
        return sorted(files, key=self._extract_number)
    
    def _select_folder(self):
        """选择文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择包含图片序列的文件夹"
        )
        if folder:
            self.folder_path = folder
            self.folder_entry.setText(folder)
            self._update_preview(folder)
    
    def _update_preview(self, folder):
        """更新预览"""
        try:
            files = [f for f in os.listdir(folder) if f.lower().endswith('.png')]
            files = self._smart_sort_files(files)
            
            if files:
                preview_text = f"找到 {len(files)} 张图片\n"
                preview_text += "排序后顺序:\n"
                preview_text += f"第一张: {files[0]}\n"
                if len(files) > 1:
                    preview_text += f"第二张: {files[1]}\n"
                preview_text += f"最后一张: {files[-1]}"
                
                self.preview_label.setText(preview_text)
            else:
                self.preview_label.setText("文件夹中没有找到PNG图片")
        except Exception as e:
            self.preview_label.setText(f"读取文件夹失败: {e}")
    
    def _generate_sprite_sheet(self):
        """生成Sprite Sheet"""
        if not self.folder_path:
            QMessageBox.warning(self, "提示", "请先选择图片文件夹")
            return
        
        try:
            files = [f for f in os.listdir(self.folder_path) if f.lower().endswith('.png')]
            files = self._smart_sort_files(files)
            
            if not files:
                QMessageBox.warning(self, "提示", "文件夹中没有找到PNG图片")
                return
            
            # 加载所有图片
            images = []
            for file in files:
                img = Image.open(os.path.join(self.folder_path, file))
                images.append(img)
            
            # 获取图片尺寸
            width, height = images[0].size
            frame_count = len(images)
            
            # 计算Sprite Sheet尺寸
            max_width = 4096
            cols = min(frame_count, max_width // width)
            if cols == 0:
                cols = 1
            rows = (frame_count + cols - 1) // cols
            
            # 创建Sprite Sheet
            sprite_sheet = Image.new('RGBA', (width * cols, height * rows), (0, 0, 0, 0))
            
            # 拼接图片
            for i, img in enumerate(images):
                x = (i % cols) * width
                y = (i // cols) * height
                sprite_sheet.paste(img, (x, y))
            for img in images:  # 拼接完即关闭源图,释放文件句柄(原先依赖 GC)
                img.close()

            # 选择保存位置
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存Sprite Sheet",
                "spritesheet.png",
                "PNG文件 (*.png)"
            )
            
            if save_path:
                # 保存图片
                sprite_sheet.save(save_path, 'PNG', optimize=True)
                
                # 保存配置文件
                json_path = save_path.replace('.png', '.json')
                metadata = {
                    'frame_width': width,
                    'frame_height': height,
                    'frames': frame_count,
                    'cols': cols,
                    'rows': rows,
                    'fps': self.fps_slider.value(),
                    'loop': False,
                    'version': 1
                }
                
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                
                QMessageBox.information(
                    self,
                    "成功",
                    f"Sprite Sheet 已生成并保存!\n\n"
                    f"图片: {os.path.basename(save_path)}\n"
                    f"配置: {os.path.basename(json_path)}\n"
                    f"尺寸: {width * cols} x {height * rows}\n"
                    f"帧数: {frame_count}"
                )
                
                self.logger.info(f"Sprite Sheet生成成功: {save_path}")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成失败: {e}")
            self.logger.error(f"生成Sprite Sheet失败: {e}")
    
    def _batch_process(self):
        """批量处理多个文件夹"""
        QMessageBox.information(
            self,
            "批量处理说明",
            "批量处理功能：\n\n"
            "1. 选择包含多个子文件夹的目录\n"
            "2. 每个子文件夹应包含一组图片序列\n"
            "3. 子文件夹名称应为数字（1-5）\n"
            "4. 将生成对应的 1.png, 2.png 等文件"
        )
        
        root_folder = QFileDialog.getExistingDirectory(
            self,
            "选择包含多个图片文件夹的根目录"
        )
        if not root_folder:
            return
        
        output_folder = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录"
        )
        if not output_folder:
            return
        
        success_count = 0
        fail_count = 0
        fps = self.fps_slider.value()
        
        # 处理每个子文件夹
        for subfolder in os.listdir(root_folder):
            subfolder_path = os.path.join(root_folder, subfolder)
            if os.path.isdir(subfolder_path):
                try:
                    # 检查文件夹名是否为数字（1-5）
                    if subfolder.isdigit() and 1 <= int(subfolder) <= 5:
                        output_name = subfolder
                    else:
                        output_name = subfolder
                    
                    # 获取PNG文件并排序
                    files = [f for f in os.listdir(subfolder_path) if f.lower().endswith('.png')]
                    files = self._smart_sort_files(files)
                    
                    if not files:
                        continue
                    
                    # 加载图片并生成Sprite Sheet
                    images = [Image.open(os.path.join(subfolder_path, f)) for f in files]
                    width, height = images[0].size
                    frame_count = len(images)
                    
                    # 计算布局
                    max_width = 4096
                    cols = min(frame_count, max_width // width)
                    if cols == 0:
                        cols = 1
                    rows = (frame_count + cols - 1) // cols
                    
                    sprite_sheet = Image.new('RGBA', (width * cols, height * rows), (0, 0, 0, 0))
                    
                    for i, img in enumerate(images):
                        x = (i % cols) * width
                        y = (i // cols) * height
                        sprite_sheet.paste(img, (x, y))
                    for img in images:  # 每个子目录拼接完即关闭,避免跨目录循环累积句柄
                        img.close()

                    # 保存
                    save_path = os.path.join(output_folder, f"{output_name}.png")
                    sprite_sheet.save(save_path, 'PNG', optimize=True)
                    
                    # 保存配置
                    json_path = save_path.replace('.png', '.json')
                    metadata = {
                        'frame_width': width,
                        'frame_height': height,
                        'frames': frame_count,
                        'cols': cols,
                        'rows': rows,
                        'fps': fps,
                        'loop': False,
                        'version': 1
                    }
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)
                    
                    success_count += 1
                    self.logger.info(f"批量处理成功: {subfolder} -> {output_name}.png")
                    
                except Exception as e:
                    self.logger.error(f"处理 {subfolder} 失败: {e}")
                    fail_count += 1
        
        QMessageBox.information(
            self,
            "批量处理完成",
            f"处理完成!\n\n"
            f"成功: {success_count} 个\n"
            f"失败: {fail_count} 个"
        )
