from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QSlider, QRadioButton, QComboBox, QPushButton,
                               QFrame, QScrollArea, QButtonGroup, QDialog,
                               QMessageBox, QFileDialog, QSizePolicy)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QMouseEvent
from config import config, get_app_data_dir
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from page_theme_helper import style_as_primary_button, style_as_secondary_button
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
import os
import json


#: 样式的中文名——**这是本文件里唯一一份**。
#: R9-A 之前同一份清单在这个文件里抄了三遍（`_format_style_text` 的表、
#: 单选按钮组、预览绘制的 if/elif），加第五个样式时得同时改三处，
#: 漏一处就是「选得中但显示成十字」这类不报错的错。
#: 顺序即单选按钮从左到右的顺序；键集必须等于 `crosshair_overlay.USER_STYLES`，
#: `tests/test_crosshair_style_catalog_r9a.py` 盯着这件事。
CROSSHAIR_STYLE_LABELS = {
    "crosshair": "十字",
    "dot": "点",
    "circle": "圆圈",
    "t_shape": "T 型",
    "custom": "自定义",
}
DEFAULT_STYLE = "crosshair"


class CrosshairEditorWidget(QWidget):
    """自定义准心绘制画布"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("CrosshairEditorWidget")
        
        # 画板参数
        self.canvas_size = 300
        self.grid_cells = 30
        self.cell_size = self.canvas_size / self.grid_cells
        
        # 活动单元格集合
        self.active_cells = set()
        
        # 中心点（红色标记，不可修改）
        self.center_cell = (self.grid_cells // 2, self.grid_cells // 2)
        
        # 设置固定大小
        self.setFixedSize(self.canvas_size, self.canvas_size)
        
        # 加载已保存的自定义准心数据
        if hasattr(config, 'crosshair_custom_data') and config.crosshair_custom_data:
            for x, y in config.crosshair_custom_data:
                self.active_cells.add((x, y))
    
    def clear_canvas(self):
        """清空画布"""
        self.active_cells.clear()
        self.update()
    
    def get_crosshair_data(self):
        """获取准心数据"""
        return list(self.active_cells)
    
    def paintEvent(self, event):
        """绘制画布"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制背景
        painter.fillRect(0, 0, self.canvas_size, self.canvas_size, QColor(0, 0, 0))
        
        # 绘制网格线
        pen = QPen(QColor(60, 60, 60), 1)
        painter.setPen(pen)
        
        for i in range(self.grid_cells + 1):
            # 垂直线
            x = i * self.cell_size
            painter.drawLine(int(x), 0, int(x), self.canvas_size)
            # 水平线
            y = i * self.cell_size
            painter.drawLine(0, int(y), self.canvas_size, int(y))
        
        # 绘制中心点（红色）
        center_x, center_y = self.center_cell
        painter.fillRect(
            int(center_x * self.cell_size),
            int(center_y * self.cell_size),
            int(self.cell_size),
            int(self.cell_size),
            QColor(255, 0, 0)
        )
        
        # 绘制激活的单元格（白色）
        for cell_x, cell_y in self.active_cells:
            if (cell_x, cell_y) != self.center_cell:  # 不覆盖中心点
                painter.fillRect(
                    int(cell_x * self.cell_size),
                    int(cell_y * self.cell_size),
                    int(self.cell_size),
                    int(self.cell_size),
                    QColor(255, 255, 255)
                )
    
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        self._toggle_cell(event.position())
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件（拖动绘制）"""
        if event.buttons() & Qt.LeftButton:
            self._toggle_cell(event.position())
    
    def _toggle_cell(self, pos):
        """切换单元格状态"""
        # 获取点击的单元格坐标
        cell_x = int(pos.x() // self.cell_size)
        cell_y = int(pos.y() // self.cell_size)
        
        # 确保不超出网格范围
        if 0 <= cell_x < self.grid_cells and 0 <= cell_y < self.grid_cells:
            # 检查是否点击了中心点（不可修改）
            if (cell_x, cell_y) == self.center_cell:
                return
            
            # 切换单元格状态
            if (cell_x, cell_y) in self.active_cells:
                self.active_cells.remove((cell_x, cell_y))
            else:
                self.active_cells.add((cell_x, cell_y))
            
            # 重绘
            self.update()


class CrosshairEditorDialog(QDialog):
    """自定义准心编辑器对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("CrosshairEditorDialog")
        
        self.setWindowTitle("自定义准心编辑器")
        self.setFixedSize(400, 450)
        self.setModal(True)
        
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # 标题
        title = QLabel("绘制自定义准心")
        title.setObjectName("subtitleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # 说明
        info = QLabel("在下方网格中绘制您的自定义准心\n中心位置会被标记为红色")
        info.setObjectName("hintLabel")
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # 画布框架
        canvas_frame = QFrame()
        canvas_frame.setObjectName("card")
        canvas_layout = QVBoxLayout(canvas_frame)
        
        # 创建画板
        self.canvas = CrosshairEditorWidget(self)
        canvas_layout.addWidget(self.canvas, alignment=Qt.AlignCenter)
        
        layout.addWidget(canvas_frame)
        
        # 按钮行
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        # 清除按钮
        clear_btn = QPushButton("清除")
        clear_btn.setFixedWidth(100)
        clear_btn.setFixedHeight(34)
        style_as_secondary_button(clear_btn)
        clear_btn.clicked.connect(self.canvas.clear_canvas)
        button_layout.addWidget(clear_btn)
        
        button_layout.addStretch()
        
        # 保存按钮
        save_btn = QPushButton("保存")
        save_btn.setFixedWidth(100)
        save_btn.setFixedHeight(34)
        style_as_primary_button(save_btn)
        save_btn.clicked.connect(self.accept)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)

class CrosshairPage(QWidget):
    """准心设置页面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("CrosshairPage")
        
        # 准心配置
        self.crosshair_animation = None  # 准心动画系统将在gui_widget中设置
        
        # 自定义准心编辑器相关
        self.canvas_size = 300
        self.grid_cells = 30
        self.cell_size = self.canvas_size / self.grid_cells
        self.active_cells = set()
        
        self._init_ui()
        self.load_settings()

        # R1-8: 拖 .xchr/.json 准心文件进页面即导入
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, (".xchr", ".json"), self._on_crosshair_file_dropped)
        except Exception:
            self.logger.exception("准心页拖拽导入初始化失败(不影响其它功能)")

        self.logger.info("准心设置页面初始化完成")
    
    def set_crosshair_animation(self, animation_system):
        """设置准心动画系统引用"""
        self.crosshair_animation = animation_system
        self.logger.debug("准心动画系统已设置")
    
    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        # UP-047: 页头改用 PageHeader。本页标题行右侧还挂着一条提示，
        # 用 add_title_action 追加——它加在 stretch 之后，与原来的顺序一致。
        header = PageHeader(
            "准心设置",
            description="这里负责准心的形态、颜色、动效和击杀联动，参数调整尽量保持像工具面板一样直达。",
            title_font_size=None,
            spacing=12,
            title_spacing=None,  # 沿用 Qt 默认间距：写死 10 会让右上角的 "?" 挪 2px
        )
        hint_label = QLabel("显示开关由基础设置统一控制")
        hint_label.setObjectName("hintLabel")
        header.add_title_action(hint_label)

        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["crosshair"])
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # 滚动内容容器
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(12)
        scroll_layout.setContentsMargins(0, 0, 6, 0)

        overview_card = self._create_overview_card()
        scroll_layout.addWidget(overview_card)
        
        top_tools_row = QHBoxLayout()
        top_tools_row.setSpacing(12)
        preview_card = self._create_preview_card()
        # v5 Phase 7: 重新分配空间.原 280-340px 限制让预览太瘦,改为 Expanding 让 4:5 stretch.
        preview_card.setMinimumWidth(360)
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        size_thickness_card = self._create_size_thickness_card()
        size_thickness_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        style_card = self._create_style_card()
        color_card = self._create_color_card()
        style_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        color_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        controls_column = QWidget()
        controls_column_layout = QVBoxLayout(controls_column)
        controls_column_layout.setContentsMargins(0, 0, 0, 0)
        controls_column_layout.setSpacing(12)
        controls_column_layout.addWidget(size_thickness_card)

        # UP-067(R5): 原本是写死的两列 QHBoxLayout。QHBoxLayout 的最小宽度是
        # 两张卡最小宽之和,于是"样式+颜色"这一行把 controls_column 顶到 600px,
        # 加上 preview_card 的 360px 下限,整行最小 972px —— 1.25 字号档下
        # 超出可视区 16px,而本页滚动区是纵向滚,右边那一小条就够不到了。
        # 换成 ResponsiveGrid:窄的时候自动落成单列,最小宽只等于较宽的那一张卡。
        from widgets.responsive_grid import ResponsiveGrid

        style_color_grid = ResponsiveGrid(breakpoints=[(560, 2), (0, 1)], spacing=12)
        style_color_grid.addItem(style_card)
        style_color_grid.addItem(color_card)
        controls_column_layout.addWidget(style_color_grid)
        controls_column_layout.addStretch(1)

        # v5 Phase 7: 4:5 stretch 让预览和控件区接近 50/50
        top_tools_row.addWidget(preview_card, 4, Qt.AlignTop)
        top_tools_row.addWidget(controls_column, 5)
        scroll_layout.addLayout(top_tools_row)

        effect_row = QHBoxLayout()
        effect_row.setSpacing(12)
        animation_card = self._create_animation_card()
        kill_effect_card = self._create_kill_effect_card()
        animation_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        kill_effect_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        effect_row.addWidget(animation_card, 1)
        effect_row.addWidget(kill_effect_card, 1)
        scroll_layout.addLayout(effect_row)
        
        # 自定义准心操作卡片
        custom_card = self._create_custom_card()
        custom_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        scroll_layout.addWidget(custom_card)
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        main_layout.addWidget(self.action_bar, 0)

    def _create_badge_label(self):
        badge = QLabel()
        badge.setObjectName("badgeLabel")
        badge.setAlignment(Qt.AlignCenter)
        return badge

    def _set_badge_state(self, label, text, tone="info"):
        label.setText(text)
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _format_style_text(self, style_value):
        return CROSSHAIR_STYLE_LABELS.get(
            str(style_value or ""), CROSSHAIR_STYLE_LABELS[DEFAULT_STYLE]
        )

    def _format_color_text(self, color_value):
        color_map = {
            "red": "红色",
            "green": "绿色",
            "blue": "蓝色",
            "yellow": "黄色",
            "cyan": "青色",
            "white": "白色",
        }
        return color_map.get(str(color_value or ""), "绿色")

    def _format_animation_text(self, animation_value):
        animation_map = {
            "none": "无动画",
            "breathing": "呼吸效果",
            "pulse": "脉冲效果",
            "color": "变色效果",
            "rotate": "旋转效果",
            "wave": "扩散效果",
            "bounce": "弹跳效果",
            "blink": "闪烁效果",
            "shake": "抖动效果",
        }
        return animation_map.get(str(animation_value or ""), "无动画")

    def _format_kill_effect_text(self, effect_value):
        effect_map = {
            "none": "关闭联动",
            "pulse": "脉冲效果",
            "explosion": "爆炸效果",
            "rotate": "旋转效果",
            "shake": "抖动效果",
            "x_flash": "X形闪烁",
            "rainbow_wave": "彩虹冲击波",
            "shatter": "破碎重组",
            "multi_pulse": "多重脉冲",
            "neon_wave": "霓虹扩散",
            "x_overlay": "十字星辉",
        }
        return effect_map.get(str(effect_value or ""), "关闭联动")

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        style_value = str(getattr(config, "crosshair_style", "crosshair") or "crosshair")
        color_value = str(getattr(config, "crosshair_color", "green") or "green")
        animation_value = str(getattr(config, "crosshair_animation", "none") or "none")
        kill_effect_value = str(getattr(config, "crosshair_kill_effect", "none") or "none")
        custom_points = len(getattr(config, "crosshair_custom_data", []) or [])

        self.action_bar.configure_secondary("导入准心", self._import_crosshair, visible=True)
        if custom_points > 0:
            self.action_bar.configure_primary("导出准心", self._export_crosshair, visible=True)
        else:
            self.action_bar.configure_primary("绘制准心", self._open_custom_editor, visible=True)

        action_message = (
            f"当前样式：{self._format_style_text(style_value)} · 颜色 {self._format_color_text(color_value)}"
            f" · 动效 {self._format_animation_text(animation_value)}"
            f" · 联动 {self._format_kill_effect_text(kill_effect_value)}"
        )
        if custom_points > 0:
            action_message += f" · 已保存 {custom_points} 个自定义点。"
        else:
            action_message += " · 还没有自定义准心数据。"
        self.action_bar.set_message(action_message)

    def _sync_panel_summaries(self):
        enabled = bool(getattr(config, "crosshair_enabled", False))
        style_value = str(getattr(config, "crosshair_style", "crosshair") or "crosshair")
        color_value = str(getattr(config, "crosshair_color", "green") or "green")
        animation_value = str(getattr(config, "crosshair_animation", "none") or "none")
        kill_effect_value = str(getattr(config, "crosshair_kill_effect", "none") or "none")
        size_value = int(getattr(config, "crosshair_size", 20) or 20)
        thickness_value = int(getattr(config, "crosshair_thickness", 2) or 2)
        custom_points = len(getattr(config, "crosshair_custom_data", []) or [])

        if hasattr(self, "preview_summary_label"):
            preview_text = (
                f"当前预览：{self._format_style_text(style_value)} · {self._format_color_text(color_value)}"
                f" · {size_value}/{thickness_value} · {'显示已启用' if enabled else '显示未启用'}"
            )
            self.preview_summary_label.setText(preview_text)
            self.preview_summary_label.setToolTip(preview_text)

        if hasattr(self, "size_summary_label"):
            size_text = f"当前档位：大小 {size_value} · 粗细 {thickness_value}"
            self.size_summary_label.setText(size_text)
            self.size_summary_label.setToolTip(size_text)

        if hasattr(self, "style_summary_label"):
            style_text = f"当前样式：{self._format_style_text(style_value)}"
            if custom_points:
                style_text += f" · 已保存 {custom_points} 个自定义点"
            self.style_summary_label.setText(style_text)
            self.style_summary_label.setToolTip(style_text)

        if hasattr(self, "color_summary_label"):
            color_text = f"当前颜色：{self._format_color_text(color_value)} · 建议优先选择高反差颜色"
            self.color_summary_label.setText(color_text)
            self.color_summary_label.setToolTip(color_text)

        if hasattr(self, "animation_summary_label"):
            animation_text = f"当前动画：{self._format_animation_text(animation_value)}"
            self.animation_summary_label.setText(animation_text)
            self.animation_summary_label.setToolTip(animation_text)

        if hasattr(self, "kill_effect_summary_label"):
            kill_text = f"当前联动：{self._format_kill_effect_text(kill_effect_value)}"
            self.kill_effect_summary_label.setText(kill_text)
            self.kill_effect_summary_label.setToolTip(kill_text)

        if hasattr(self, "custom_summary_label"):
            if custom_points > 0:
                custom_text = f"当前已保存 {custom_points} 个自定义点，可继续微调后导入或导出。"
            else:
                custom_text = "当前还没有自定义点，先绘制一个常用模板会更高效。"
            self.custom_summary_label.setText(custom_text)
            self.custom_summary_label.setToolTip(custom_text)

    def _sync_overview_status(self):
        enabled = bool(getattr(config, "crosshair_enabled", False))
        style_value = str(getattr(config, "crosshair_style", "crosshair") or "crosshair")
        color_value = str(getattr(config, "crosshair_color", "green") or "green")
        animation_value = str(getattr(config, "crosshair_animation", "none") or "none")
        kill_effect_value = str(getattr(config, "crosshair_kill_effect", "none") or "none")
        size_value = int(getattr(config, "crosshair_size", 20) or 20)
        thickness_value = int(getattr(config, "crosshair_thickness", 2) or 2)
        custom_points = len(getattr(config, "crosshair_custom_data", []) or [])

        badges = [
            ("positive" if enabled else "warning", f"显示 · {'已启用' if enabled else '未启用'}"),
            ("info", f"样式 · {self._format_style_text(style_value)}"),
            ("info", f"颜色 · {self._format_color_text(color_value)}"),
            ("info", f"大小 · {size_value} / {thickness_value}"),
            (
                "positive" if animation_value != "none" else "info",
                f"动效 · {self._format_animation_text(animation_value)}",
            ),
            (
                "positive" if kill_effect_value != "none" else "warning",
                f"联动 · {self._format_kill_effect_text(kill_effect_value)}",
            ),
        ]

        compact_parts = [
            self._format_style_text(style_value),
            self._format_color_text(color_value),
            f"{size_value}/{thickness_value}",
            self._format_kill_effect_text(kill_effect_value),
        ]
        if animation_value != "none":
            compact_parts.append(self._format_animation_text(animation_value))
        if style_value == "custom" and custom_points:
            compact_parts.append(f"自定义 {custom_points} 点")

        compact_summary = " · ".join(compact_parts)
        if not enabled:
            compact_summary = f"显示关闭 · {compact_summary}"
        self.crosshair_summary_label.setText(compact_summary)

        detail_parts = [
            f"当前为“{self._format_style_text(style_value)}”准心",
            f"大小 {size_value}",
            f"粗细 {thickness_value}",
            f"颜色 {self._format_color_text(color_value)}",
            f"动画 {self._format_animation_text(animation_value)}",
            f"击杀联动为“{self._format_kill_effect_text(kill_effect_value)}”",
        ]
        if style_value == "custom":
            detail_parts.append(f"已保存 {custom_points} 个自定义像素点")
        detail_text = "，".join(detail_parts) + "。"
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.crosshair_summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_panel_summaries()
        self._sync_action_bar()

    def _create_overview_card(self):
        card = self._create_card()
        self.status_card = card
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        status_row = QHBoxLayout()

        title = QLabel("当前状态")
        title.setObjectName("statusLabel")
        status_row.addWidget(title)
        status_row.addStretch()

        layout.addLayout(status_row)

        self.status_badge_label = create_badge_label()
        layout.addWidget(self.status_badge_label)

        self.crosshair_summary_label = QLabel("")
        self.crosshair_summary_label.setObjectName("hintLabel")
        self.crosshair_summary_label.setWordWrap(True)
        self.crosshair_summary_label.hide()
        layout.addWidget(self.crosshair_summary_label)

        return card
    
    def _create_card(self):
        """创建标准卡片"""
        card = QFrame()
        card.setObjectName("card")
        shadow = self._create_shadow()
        card.setGraphicsEffect(shadow)
        return card
    
    def _create_shadow(self):
        """创建阴影效果"""
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(0, 2)
        return shadow
    
    def _create_preview_card(self):
        """创建预览卡片"""
        card = self._create_card()
        card.setToolTip("这里展示当前配置的静态预览，实际显示仍以基础设置中的准心开关为准。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("准心预览")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.preview_summary_label = QLabel("")
        self.preview_summary_label.setObjectName("hintLabel")
        self.preview_summary_label.setWordWrap(True)
        layout.addWidget(self.preview_summary_label)

        # 预览框
        preview_frame = QFrame()
        preview_frame.setFixedSize(156, 156)
        self.preview_frame = preview_frame
        
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_label)
        
        # 居中预览框
        preview_container = QHBoxLayout()
        preview_container.addStretch()
        preview_container.addWidget(preview_frame)
        preview_container.addStretch()
        layout.addLayout(preview_container)
        layout.addStretch()
        
        return card
    
    def _create_size_thickness_card(self):
        """创建准心大小和粗细卡片（合并）"""
        card = self._create_card()
        card.setToolTip("建议先确定整体大小，再微调粗细，这样更容易找到既清晰又不遮挡视线的平衡点。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("大小与粗细")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.size_summary_label = QLabel("")
        self.size_summary_label.setObjectName("hintLabel")
        self.size_summary_label.setWordWrap(True)
        layout.addWidget(self.size_summary_label)

        # 大小设置
        size_header = QHBoxLayout()
        size_title = QLabel("准心大小")
        size_header.addWidget(size_title)
        size_header.addStretch()
        
        self.size_value_label = QLabel(str(config.crosshair_size))
        size_header.addWidget(self.size_value_label)
        layout.addLayout(size_header)
        
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setMinimum(5)
        self.size_slider.setMaximum(50)
        self.size_slider.setValue(config.crosshair_size)
        self.size_slider.valueChanged.connect(self._on_size_changed)
        layout.addWidget(self.size_slider)
        
        # 粗细设置
        thickness_header = QHBoxLayout()
        thickness_title = QLabel("准心粗细")
        thickness_header.addWidget(thickness_title)
        thickness_header.addStretch()
        
        self.thickness_value_label = QLabel(str(config.crosshair_thickness))
        thickness_header.addWidget(self.thickness_value_label)
        layout.addLayout(thickness_header)
        
        self.thickness_slider = QSlider(Qt.Horizontal)
        self.thickness_slider.setMinimum(1)
        self.thickness_slider.setMaximum(10)
        self.thickness_slider.setValue(config.crosshair_thickness)
        self.thickness_slider.valueChanged.connect(self._on_thickness_changed)
        layout.addWidget(self.thickness_slider)
        
        return card
    
    def _create_style_card(self):
        """创建准心样式卡片"""
        card = self._create_card()
        card.setToolTip("普通样式适合快速切换，自定义样式更适合长期固定使用。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("准心样式")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.style_summary_label = QLabel("")
        self.style_summary_label.setObjectName("hintLabel")
        self.style_summary_label.setWordWrap(True)
        layout.addWidget(self.style_summary_label)

        # 样式选择（Radio Buttons）
        # 用 FlowLayout 而不是 QHBoxLayout：QHBoxLayout 的最小宽度是所有子项之和，
        # R9-A 加到第五个样式后，1.25 倍字号下实测把本页撑出 10 处水平溢出。
        # FlowLayout 的最小宽度只等于最宽的那一个，放不下自动换行。（同 UP-017）
        from widgets.flow_layout import make_flow_container

        style_wrap, style_layout = make_flow_container(h_spacing=10, v_spacing=6)

        self.style_group = QButtonGroup(self)

        for style_value, style_name in CROSSHAIR_STYLE_LABELS.items():
            radio = QRadioButton(style_name)
            self.style_group.addButton(radio)
            radio.setProperty("style_value", style_value)
            radio.toggled.connect(lambda checked, s=style_value: self._on_style_changed(s) if checked else None)
            style_layout.addWidget(radio)

            if style_value == config.crosshair_style:
                radio.setChecked(True)

        # FlowLayout 没有 addStretch——它本来就是左对齐 + 自动换行
        layout.addWidget(style_wrap)

        return card
    
    def _create_color_card(self):
        """创建准心颜色卡片"""
        card = self._create_card()
        card.setToolTip("优先选择与你常用地图和显示器环境反差更稳定的颜色。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("准心颜色")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.color_summary_label = QLabel("")
        self.color_summary_label.setObjectName("hintLabel")
        self.color_summary_label.setWordWrap(True)
        layout.addWidget(self.color_summary_label)

        # 颜色选择（Radio Buttons）
        self.color_group = QButtonGroup(self)
        
        colors = [
            ("red", "红色"),
            ("green", "绿色"),
            ("blue", "蓝色"),
            ("yellow", "黄色"),
            ("cyan", "青色"),
            ("white", "白色")
        ]
        
        # 分两行显示
        for row in range(2):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(10)
            
            for col in range(3):
                idx = row * 3 + col
                if idx < len(colors):
                    color_code, color_name = colors[idx]
                    radio = QRadioButton(color_name)
                    self.color_group.addButton(radio)
                    radio.setProperty("color_value", color_code)
                    radio.toggled.connect(lambda checked, c=color_code: self._on_color_changed(c) if checked else None)
                    row_layout.addWidget(radio)
                    
                    if color_code == config.crosshair_color:
                        radio.setChecked(True)
            
            row_layout.addStretch()
            layout.addLayout(row_layout)
        
        return card
    
    def _create_animation_card(self):
        """创建动画效果卡片"""
        card = self._create_card()
        card.setToolTip("动画只影响显示节奏，不会改变准心的基础形态。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("动画效果")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.animation_summary_label = QLabel("")
        self.animation_summary_label.setObjectName("hintLabel")
        self.animation_summary_label.setWordWrap(True)
        layout.addWidget(self.animation_summary_label)

        # 动画选择下拉框
        row_layout = QHBoxLayout()
        row_layout.setSpacing(8)
        
        label = QLabel("动画")
        row_layout.addWidget(label)
        
        self.animation_combo = QComboBox()
        animation_options = [
            "无动画", "呼吸效果", "脉冲效果", "变色效果", "旋转效果",
            "扩散效果", "弹跳效果", "闪烁效果", "抖动效果"
        ]
        self.animation_combo.addItems(animation_options)
        self.animation_combo.setFixedHeight(36)
        self.animation_combo.currentIndexChanged.connect(self._on_animation_changed)
        row_layout.addWidget(self.animation_combo)
        
        row_layout.addStretch()
        layout.addLayout(row_layout)
        
        return card
    
    def _create_kill_effect_card(self):
        """创建击杀联动卡片"""
        card = self._create_card()
        card.setToolTip("测试前需要先在基础设置中启用准心显示，否则看不到联动效果。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("击杀联动")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.kill_effect_summary_label = QLabel("")
        self.kill_effect_summary_label.setObjectName("hintLabel")
        self.kill_effect_summary_label.setWordWrap(True)
        layout.addWidget(self.kill_effect_summary_label)

        # 击杀联动选择
        row_layout = QHBoxLayout()
        row_layout.setSpacing(8)
        
        label = QLabel("联动")
        row_layout.addWidget(label)
        
        self.kill_effect_combo = QComboBox()
        kill_effect_options = [
            "关闭联动", "脉冲效果", "爆炸效果", "旋转效果", "抖动效果",
            "X形闪烁", "彩虹冲击波", "破碎重组", "多重脉冲", "霓虹扩散",
            "十字星辉"
        ]
        self.kill_effect_combo.addItems(kill_effect_options)
        self.kill_effect_combo.setFixedHeight(36)
        self.kill_effect_combo.currentIndexChanged.connect(self._on_kill_effect_changed)
        row_layout.addWidget(self.kill_effect_combo)
        
        # 测试按钮
        test_btn = QPushButton("测试")
        test_btn.setFixedWidth(80)
        test_btn.setFixedHeight(36)
        style_as_secondary_button(test_btn)
        test_btn.clicked.connect(self._test_kill_effect)
        row_layout.addWidget(test_btn)
        
        row_layout.addStretch()
        layout.addLayout(row_layout)
        
        return card
    
    def _create_custom_card(self):
        """创建自定义准心操作卡片"""
        card = self._create_card()
        card.setToolTip("绘制完成后会自动切换到自定义样式；导入和导出可用于保留常用模板。")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("自定义准心")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.custom_summary_label = QLabel("")
        self.custom_summary_label.setObjectName("hintLabel")
        self.custom_summary_label.setWordWrap(True)
        layout.addWidget(self.custom_summary_label)

        # 按钮行
        # Phase1-1.7: 去重——"导入/导出准心"已由页面底部操作栏统一承担
        # （导入常驻、导出在有自定义点时出现），卡片内只保留情境动作"绘制准心"。
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # 绘制准心按钮
        draw_btn = QPushButton("绘制准心")
        draw_btn.setFixedWidth(112)
        draw_btn.setFixedHeight(36)
        style_as_primary_button(draw_btn)
        draw_btn.clicked.connect(self._open_custom_editor)
        btn_layout.addWidget(draw_btn)

        import_export_hint = QLabel("导入 / 导出在页面底部操作栏。")
        import_export_hint.setObjectName("hintLabel")
        btn_layout.addWidget(import_export_hint)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return card
    def _on_size_changed(self, value):
        """准心大小改变"""
        self.size_value_label.setText(str(value))
        config.crosshair_size = value
        config.save_config()
        self._update_preview()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.debug(f"准心大小更新: {value}")
    
    def _on_thickness_changed(self, value):
        """准心粗细改变"""
        self.thickness_value_label.setText(str(value))
        config.crosshair_thickness = value
        config.save_config()
        self._update_preview()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.debug(f"准心粗细更新: {value}")
    
    def _on_style_changed(self, style_value):
        """准心样式改变"""
        config.crosshair_style = style_value
        config.save_config()
        self._update_preview()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.info(f"准心样式更新: {style_value}")
    
    def _on_color_changed(self, color_value):
        """准心颜色改变"""
        config.crosshair_color = color_value
        config.save_config()
        self._update_preview()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.info(f"准心颜色更新: {color_value}")
    
    def _on_animation_changed(self):
        """动画效果改变"""
        animation_text = self.animation_combo.currentText()
        animation_value = self._get_animation_value(animation_text)
        config.crosshair_animation = animation_value
        config.save_config()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.info(f"准心动画更新: {animation_text} -> {animation_value}")
    
    def _on_kill_effect_changed(self):
        """击杀联动改变"""
        effect_text = self.kill_effect_combo.currentText()
        effect_value = self._get_kill_effect_value(effect_text)
        config.crosshair_kill_effect = effect_value
        config.save_config()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.info(f"击杀联动更新: {effect_text} -> {effect_value}")
    
    def _test_kill_effect(self):
        """测试击杀联动效果"""
        if not self.crosshair_animation or not self.crosshair_animation.is_visible:
            QMessageBox.information(self, "提示", "请先在基础设置中启用准心以测试击杀联动效果")
            return
        
        effect_value = config.crosshair_kill_effect
        if effect_value == "none":
            QMessageBox.information(self, "提示", "请先选择一个击杀联动效果")
            return
        
        # 触发击杀动画效果
        self.crosshair_animation.on_kill_event(True)
        self.logger.info("触发击杀联动测试")
    
    def _get_animation_value(self, animation_text):
        """将UI选项转换为内部动画值"""
        animation_map = {
            "无动画": "none",
            "呼吸效果": "breathing",
            "脉冲效果": "pulse",
            "变色效果": "color",
            "旋转效果": "rotate",
            "扩散效果": "wave",
            "弹跳效果": "bounce",
            "闪烁效果": "blink",
            "抖动效果": "shake"
        }
        return animation_map.get(animation_text, "none")
    
    def _get_kill_effect_value(self, effect_text):
        """获取当前选择的击杀效果值"""
        effect_map = {
            "关闭联动": "none",
            "脉冲效果": "pulse",
            "爆炸效果": "explosion",
            "旋转效果": "rotate",
            "抖动效果": "shake",
            "X形闪烁": "x_flash",
            "彩虹冲击波": "rainbow_wave",
            "破碎重组": "shatter",
            "多重脉冲": "multi_pulse",
            "霓虹扩散": "neon_wave",
            "十字星辉": "x_overlay"
        }
        return effect_map.get(effect_text, "none")
    
    def _update_preview(self):
        """更新准心预览"""
        try:
            # 创建准心图像
            size = config.crosshair_size
            thickness = config.crosshair_thickness
            color = config.crosshair_color
            style = config.crosshair_style
            
            # 限制预览大小
            preview_size = min(40, size)
            img_size = preview_size * 2
            
            # UP-033: 按设备像素比出图。原来直接按逻辑像素建 QImage 又不设
            # devicePixelRatio，于是在 150%/200% 缩放的高 DPI 屏上，这张图会被
            # Qt 拉伸到 1.5~2 倍显示——线条糊、边缘毛。
            # 做法：画布放大 dpr 倍、painter 先 scale(dpr)，下面所有绘制代码
            # 仍然按逻辑坐标写（一行都不用改），最后把 dpr 标回图上让 Qt 正确缩放。
            dpr = float(self.preview_label.devicePixelRatioF() or 1.0)
            if dpr <= 0:
                dpr = 1.0

            # 创建QImage
            image = QImage(int(img_size * dpr), int(img_size * dpr), QImage.Format_ARGB32)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.transparent)
            
            # 绘制准心
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.scale(dpr, dpr)
            
            # 设置颜色
            color_map = {
                "red": QColor(255, 0, 0),
                "green": QColor(0, 255, 0),
                "blue": QColor(0, 0, 255),
                "yellow": QColor(255, 255, 0),
                "cyan": QColor(0, 255, 255),
                "white": QColor(255, 255, 255)
            }
            pen_color = color_map.get(color, QColor(0, 255, 0))
            pen = QPen(pen_color, thickness)
            painter.setPen(pen)
            
            center = preview_size
            
            # 绘制不同样式的准心
            if style == "crosshair":
                # 十字准心
                painter.drawLine(center, center - preview_size, center, center + preview_size)
                painter.drawLine(center - preview_size, center, center + preview_size, center)
            elif style == "dot":
                # 点准心（PySide6 的 drawEllipse 无 float 四参重载，必须取整）
                dot_size = int(max(2, preview_size // 4) * (thickness / 2))
                painter.setBrush(pen_color)
                painter.drawEllipse(center - dot_size, center - dot_size, dot_size * 2, dot_size * 2)
            elif style == "circle":
                # 圆圈准心
                circle_size = max(5, preview_size // 2)
                painter.drawEllipse(center - circle_size, center - circle_size, circle_size * 2, circle_size * 2)
            elif style == "t_shape":
                # T 型准心：横杆整条 + 竖杆只向下半条
                # 与 `crosshair_overlay._paint_t_shape` 同一套几何，改一边要改两边
                painter.drawLine(center - preview_size, center, center + preview_size, center)
                painter.drawLine(center, center, center, center + preview_size)
            elif style == "custom" and hasattr(config, 'crosshair_custom_data') and config.crosshair_custom_data:
                # 自定义准心
                scale = preview_size / 15
                for point in config.crosshair_custom_data:
                    x, y = point
                    abs_x = center + (x - 15) * scale
                    abs_y = center + (y - 15) * scale
                    pixel_size = max(1, int(thickness))
                    painter.setBrush(pen_color)
                    painter.drawRect(
                        int(abs_x - pixel_size / 2), int(abs_y - pixel_size / 2), pixel_size, pixel_size
                    )
            
            painter.end()
            
            # 转换为QPixmap并显示（fromImage 会继承 image 的 devicePixelRatio）
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(dpr)
            self.preview_label.setPixmap(pixmap)
            
        except Exception as e:
            self.logger.error(f"更新预览失败: {e}")
    
    def _update_crosshair_system(self):
        """更新准心动画系统的设置"""
        if not self.crosshair_animation:
            return
        
        if not self.crosshair_animation.is_visible:
            return
        
        size = config.crosshair_size
        thickness = config.crosshair_thickness
        color = config.crosshair_color
        style = config.crosshair_style
        animation_style = config.crosshair_animation
        kill_effect = config.crosshair_kill_effect
        
        self.crosshair_animation.update_settings(
            size, thickness, color, style, animation_style, kill_effect
        )
        self.logger.debug("准心动画系统设置已更新")
    
    def _open_custom_editor(self):
        """打开自定义准心编辑器"""
        dialog = CrosshairEditorDialog(self)
        
        if dialog.exec() == QDialog.Accepted:
            # 保存准心数据
            config.crosshair_custom_data = dialog.canvas.get_crosshair_data()
            config.save_config()
            
            # 切换到自定义准心样式
            for button in self.style_group.buttons():
                if button.property("style_value") == "custom":
                    button.setChecked(True)
                    break
            
            # 更新预览
            self._update_preview()
            self._sync_overview_status()
            
            QMessageBox.information(self, "成功", "自定义准心已保存并应用")
            self.logger.info("自定义准心已保存")
    
    def _export_crosshair(self):
        """导出自定义准心到文件"""
        if not hasattr(config, 'crosshair_custom_data') or not config.crosshair_custom_data:
            QMessageBox.information(self, "提示", "没有自定义准心数据可以导出")
            return
        
        # 准备导出数据
        export_data = {
            "crosshair_data": config.crosshair_custom_data,
            "description": "CS2 Customizer 自定义准心"
        }
        
        # 确保准心目录存在
        crosshair_dir = get_app_data_dir("resources/crosshair")
        os.makedirs(crosshair_dir, exist_ok=True)
        
        # 让用户选择保存文件名
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "导出准心",
            os.path.join(crosshair_dir, "my_crosshair.xchr"),
            "准心文件 (*.xchr);;所有文件 (*.*)"
        )
        
        if not file_name:
            return
        
        # 保存文件
        try:
            with open(file_name, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "成功", f"准心已导出到\n{file_name}")
            self.logger.info(f"准心已导出到: {file_name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", "导出准心失败：目标位置可能无写入权限，请换个位置后重试。")
            self.logger.error(f"导出准心失败: {e}")
    
    def _import_crosshair(self):
        """从文件加载自定义准心"""
        # 确保准心目录存在
        crosshair_dir = get_app_data_dir("resources/crosshair")
        os.makedirs(crosshair_dir, exist_ok=True)
        
        # 让用户选择要加载的文件
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "加载准心",
            crosshair_dir,
            "准心文件 (*.xchr);;所有文件 (*.*)"
        )
        
        if not file_name:
            return
        self._load_crosshair_file(file_name)

    def _on_crosshair_file_dropped(self, paths):
        """R1-8: 拖 .xchr/.json 进页面即导入(取第一个)。"""
        if paths:
            self._load_crosshair_file(paths[0])

    def _load_crosshair_file(self, file_name):
        """加载准心文件(对话框与拖拽共用)。"""
        # 加载文件
        try:
            from core.io_validation import load_json_checked, validate_crosshair_import
            import_data = load_json_checked(file_name)
            ok, cleaned, errors = validate_crosshair_import(import_data)
            if not ok:
                QMessageBox.warning(self, "导入未完成", "这不是有效的准心文件（格式或字段不正确），请确认后重试。")
                self.logger.warning(f"准心导入被拒: {errors}")
                return

            # 更新准心数据
            config.crosshair_custom_data = cleaned["crosshair_custom_data"]
            config.save_config()
            
            # 切换到自定义准心样式
            for button in self.style_group.buttons():
                if button.property("style_value") == "custom":
                    button.setChecked(True)
                    break
            
            # 更新预览
            self._update_preview()
            self._sync_overview_status()
            
            QMessageBox.information(self, "成功", "准心已加载并应用")
            self.logger.info(f"准心已加载: {file_name}")
        except ValueError as e:
            QMessageBox.warning(self, "导入未完成", "文件过大或不是有效的准心文件，请确认后重试。")
            self.logger.warning(f"准心导入校验失败: {e}")
        except Exception as e:
            QMessageBox.critical(self, "错误", "加载准心失败：文件可能被占用或损坏，请稍后重试。")
            self.logger.error(f"加载准心失败: {e}")
    
    def load_settings(self):
        """加载设置"""
        # 加载大小和粗细
        self.size_slider.setValue(config.crosshair_size)
        self.thickness_slider.setValue(config.crosshair_thickness)
        
        # 加载样式（已在创建时设置）
        # 加载颜色（已在创建时设置）
        
        # 加载动画设置
        animation_map = {
            "none": "无动画",
            "breathing": "呼吸效果",
            "pulse": "脉冲效果",
            "color": "变色效果",
            "rotate": "旋转效果",
            "wave": "扩散效果",
            "bounce": "弹跳效果",
            "blink": "闪烁效果",
            "shake": "抖动效果"
        }
        saved_animation = getattr(config, 'crosshair_animation', "none")
        animation_text = animation_map.get(saved_animation, "无动画")
        index = self.animation_combo.findText(animation_text)
        if index >= 0:
            self.animation_combo.setCurrentIndex(index)
        
        # 加载击杀联动设置
        kill_effect_map = {
            "none": "关闭联动",
            "pulse": "脉冲效果",
            "explosion": "爆炸效果",
            "rotate": "旋转效果",
            "shake": "抖动效果",
            "x_flash": "X形闪烁",
            "rainbow_wave": "彩虹冲击波",
            "shatter": "破碎重组",
            "multi_pulse": "多重脉冲",
            "neon_wave": "霓虹扩散",
            "x_overlay": "十字星辉"
        }
        saved_kill_effect = getattr(config, 'crosshair_kill_effect', "none")
        kill_effect_text = kill_effect_map.get(saved_kill_effect, "关闭联动")
        index = self.kill_effect_combo.findText(kill_effect_text)
        if index >= 0:
            self.kill_effect_combo.setCurrentIndex(index)
        
        # 更新预览
        self._update_preview()
        self._sync_overview_status()
        
        self.logger.debug("准心设置加载完成")

