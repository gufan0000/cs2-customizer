# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QSlider, QRadioButton, QComboBox, QPushButton,
                               QFrame, QScrollArea, QButtonGroup, QDialog,
                               QMessageBox, QFileDialog, QSizePolicy, QCheckBox)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QMouseEvent
from config import config, get_app_data_dir
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from page_theme_helper import style_as_primary_button, style_as_secondary_button
from widgets.master_switch_link import make_master_switch_row
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

    #: RN-116：换动画之后预览示意多久（毫秒）。**有限**是这条设计的全部要害——
    #: 用户裁定里明确否决了"常驻定时器"那个方案。
    PREVIEW_BURST_MS = 1500

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

        # RN-116（用户裁定 2026-08-19：**要示意，但不要常驻定时器**）：
        # 换动画/击杀联动时把预览播一小段再停回静止。预览本来按相位 0 出图，
        # 也就是各动画的**静止形态** —— 换句话说改了动画预览一个像素都不变，
        # 玩家只能盲选。
        # ⚠ 定时器只在这一小段里活着：`_stop_preview_burst` 与 `hideEvent` 各有一条出口。
        self.preview_burst_timer = QTimer(self)
        self.preview_burst_timer.setInterval(50)          # 20fps 够看清动效了
        self.preview_burst_timer.timeout.connect(self._tick_preview_burst)
        self._burst_elapsed_ms = 0
        self._burst_animator = None

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
            # ⚠⚠ RN-174：这里原来写「改完点右下角「绘制准心」写进游戏。」——
            # **三个分句全假**：
            #   ① 「改完点」：参数每改一项，各自的槽里当场 save_config()；
            #   ② 「写进游戏」：那颗按钮不写任何游戏文件，它打开的是 30×30 手绘板；
            #   ③ 「「绘制准心」」：画过之后底栏主按钮就叫「导出准心」了。
            # 外审 5/6 票报「找不到保存 / 应用入口」—— **现象是真的，成因全反**：
            # 这一页压根没有"应用入口"这个东西。
            # ⭐⭐ 票数衡量的是「玩家困惑是真的」，不是「外审对成因的归因是对的」。
            # ⚠ 原建议「改名为『应用到游戏』」会变成一句**新的**假话（它不写游戏）。
            # ⭐ 文案不许替代码编一个借口。
            # ⚠⚠ 第一版改成「改哪一项当场就生效——…」，**外审当场指出它还是半真话**
            # （4/6 判高）：「总开关默认关闭，玩家调完参数直接进游戏会发现没效果」。
            # 确实如此 —— `crosshair_enabled` 关着的时候，"当场就生效"是假的。
            # ⭐ 我把三句假话改成一句真话时，漏掉了那句真话**自己的前提**。
            description="调准心的形状、颜色、动效和击杀联动。总开关打开后，改哪一项当场就生效——"
                        "准心是本软件画在画面上的覆盖层，不改动游戏的任何配置文件。",
            title_font_size=None,
            spacing=12,
            title_spacing=None,  # 沿用 Qt 默认间距：写死 10 会让右上角的 "?" 挪 2px
        )
        # ⚠ 2026-08-21（RN-144 升级版）：这里原来写的是
        # 「显示开关由基础设置统一控制」—— **总开关搬到本页状态卡上之后，
        # 那句话就变成假的了**，而它自己不会知道。
        # ⭐ RN-138 同一个形状：改了一处，指向它的文案不会跟着改。
        # ⚠ 这里一度写「开关就在下面那张卡的右上角」。外审当场点破：
        #   「需要额外文字硬指引 ⇒ 总开关层级与可见性严重不足，
        #     属于打补丁式的无效引导」
        # ⭐ **指路是症状，不是修法。** 开关已挪到状态卡第一行最左边，
        # 这句指路随之删掉 —— 留着既是错的，也是那个病的证据。
        # ⚠⚠ RN-174：这条小字原文是「调完直接进游戏看效果」——
        # 它和页头描述在说**同一件事**，而且和第一版页头犯**同一个错**：
        # 总开关关着的时候，"调完直接进游戏就看到"是假的。
        # ⭐ 外审同一轮报「顶部胶囊栏、各卡片副标题、底部栏三处重复堆叠，
        #   信息冗余严重且分散操作焦点」—— 这条正是那堆重复里的一条。
        # ⇒ 删掉，把带前提的那一句话**只放一处**（页头 description）。
        # ⭐ 同一件事说三遍，任何一遍变假都不会有人发现 —— 因为没人知道有三遍。
        #
        # ⚠ 连带删掉的 RN-121 那条 `keep_single_line(hint_label)`：它防的是
        #   「这条小字在标题行里折行、把整条标题行撑高」。标签没了，那个风险
        #   也就没了 —— 但**判据里那一格必须跟着删掉，不许留着空转**
        #   （`tests/test_single_line_hints_stay_single_line.py`）。

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
        # ⚠ **创建顺序 = Tab 焦点顺序**，所以它必须跟着版面顺序走。
        # RN-115 把「样式/颜色」提到「大小与粗细」前面之后，这里如果还按老顺序建，
        # 焦点就会先跳到下面的滑块再跳回上面的单选钮 ——
        # `tests/test_tab_order_model_r8d.py` 当场逮住（要 3 步才能排成阅读顺序）。
        # ⇒ 改版面时**同时**问一句：键盘走一遍还是这个顺序吗？
        style_card = self._create_style_card()
        color_card = self._create_color_card()
        animation_card = self._create_animation_card()
        kill_effect_card = self._create_kill_effect_card()
        size_thickness_card = self._create_size_thickness_card()
        for _card in (style_card, color_card, animation_card,
                      kill_effect_card, size_thickness_card):
            _card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        controls_column = QWidget()
        # ⚠ 这个 objectName 不是样式钩子，是给**焦点巡检**用的：
        # Tab 是一列一列走的，而审计默认把并排两列的卡片按 y 交错成"阅读序"，
        # 于是本页被判"焦点错位 3 处"（RN-122）。标出"我是一列"之后，
        # 审计按它自己写着的原则「读完左列再读右列」分组，与键盘实际行为一致。
        controls_column.setObjectName("layoutColumn")
        controls_column_layout = QVBoxLayout(controls_column)
        controls_column_layout.setContentsMargins(0, 0, 0, 0)
        controls_column_layout.setSpacing(12)

        # UP-067(R5): 原本是写死的两列 QHBoxLayout。QHBoxLayout 的最小宽度是
        # 两张卡最小宽之和,于是"样式+颜色"这一行把 controls_column 顶到 600px,
        # 加上 preview_card 的 360px 下限,整行最小 972px —— 1.25 字号档下
        # 超出可视区 16px,而本页滚动区是纵向滚,右边那一小条就够不到了。
        # 换成 ResponsiveGrid:窄的时候自动落成单列,最小宽只等于较宽的那一张卡。
        from widgets.responsive_grid import ResponsiveGrid

        style_color_grid = ResponsiveGrid(breakpoints=[(560, 2), (0, 1)], spacing=12)
        style_color_grid.addItem(style_card)
        style_color_grid.addItem(color_card)

        # RN-115（用户裁定 2026-08-19）：**先让人选准心，再让人调参数。**
        # 原顺序是「大小与粗细」在前、「样式/颜色」在后，于是这一页最核心的选择
        # 落在首屏之外（完整档视口 546px，样式卡从 y=630 起；紧凑档视口只有 386px）。
        # 外审两档 10 发都指着这块，措辞是"被截断/被遮挡"——实测机制是**可滚的首屏之外**。
        controls_column_layout.addWidget(style_color_grid)
        controls_column_layout.addWidget(size_thickness_card)
        controls_column_layout.addStretch(1)

        # RN-114：预览卡只有 239px 高，而右边这一列 570px —— 差出来的部分在完整档里
        # 就是左半列一块 455×203、什么都没有的方块。把两张效果卡挪进左列填上。
        preview_column = QWidget()
        preview_column.setObjectName("layoutColumn")     # 同上（RN-122）
        preview_column_layout = QVBoxLayout(preview_column)
        preview_column_layout.setContentsMargins(0, 0, 0, 0)
        preview_column_layout.setSpacing(12)
        preview_column_layout.addWidget(preview_card)
        preview_column_layout.addWidget(animation_card)
        preview_column_layout.addWidget(kill_effect_card)
        preview_column_layout.addStretch(1)
        self.preview_column = preview_column

        # v5 Phase 7: 4:5 stretch 让预览和控件区接近 50/50
        top_tools_row.addWidget(preview_column, 4, Qt.AlignTop)
        top_tools_row.addWidget(controls_column, 5)
        scroll_layout.addLayout(top_tools_row)


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


    def _custom_style_is_blank(self):
        """样式选的是「自定义」，而一个点都还没画 —— 此刻屏幕上什么都不会有。

        RN-406。⭐ **这个判断全页只许有一份**：它同时决定四个地方的说法
        （状态徽章的色阶与文案、紧凑摘要、样式卡副文案、自定义卡副文案）。
        抄成四份，改一处就会造出「同屏两处说法不一致」（RN-107 族）。

        依据的事实在 `crosshair_overlay._paint_custom`：`if not points: return`。
        那条事实由 `tests/test_crosshair_custom_style_is_honest.py` 单独看着 ——
        ⭐ **一句文案所依赖的事实，要有判据看着。**
        """
        if str(getattr(config, "crosshair_style", "") or "") != "custom":
            return False
        return not (getattr(config, "crosshair_custom_data", None) or [])

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

        # ⚠⚠ RN-174-B / C：这里原来是
        #     有数据 ⇒ 主按钮「导出准心」；没数据 ⇒ 主按钮「绘制准心」
        # 一个位置、一样的视觉重量，**两件毫不相干的事轮流坐**。
        # 而「绘制准心」在自定义准心卡片里**本来就有一颗**（同名同槽同功能），
        # 于是没数据时这一屏上有两颗一模一样的按钮。
        #
        # ⭐ 主按钮**可以**随状态变，前提是那几个状态是**同一条流程的相邻两步**
        #   —— 闪光页「启动」→「前往效果预览」就是（RN-192，外审驱动的改法）。
        #   而「绘制」和「导出」不是一条流程的两步，是两件无关的事共用一个槽。
        #
        # 「绘制准心」只留在自定义准心卡片里那一颗 —— 用户想「我要自己画一个」
        # 的时候人就在那张卡上（那里有点数摘要和格式说明）。
        #
        # ⚠⚠ 第一版修法（把主按钮固定成「导出准心」、没数据时置灰）**当场被外审否掉**：
        #   「置灰的『导出准心』极易被误认为是『保存/应用』按钮，
        #     导致玩家误以为当前修改未生效」（2/6 判中）
        #   「自动生效缺少明确反馈或『应用』按钮，不读说明的玩家会反复寻找保存入口」
        # ⭐⭐ 一颗**灰着的、紫色的、蹲在右下角的**按钮，形状本身就在说
        #   「这里有个保存动作，只是现在不能点」—— 而这一页根本没有保存动作。
        #   ⇒ 我把 5/6 票那条原始困惑**换了个样子留在原地**。
        #
        # 现在：底栏**不放主按钮**。导入 / 导出都是次级，位置固定、两种状态都在场。
        # 全页唯一的紫按钮是自定义准心卡片里那颗「绘制准心」——
        # 那也确实是这一页唯一一个"点了会发生新事情"的动作（RN-139/RN-186：
        # **「主」是相对的，两颗紫的等于零颗**）。
        # ⚠ 「导出准心」没数据时**置灰而不是藏掉**：藏掉的话用户看到的是
        #   "这个功能不存在"，而不是"还没有东西可导"（同 RN-197）。
        self.action_bar.configure_extra("导入准心", self._import_crosshair, visible=True)
        self.action_bar.configure_secondary("导出准心", self._export_crosshair, visible=True)
        self.action_bar.secondary_btn.setEnabled(custom_points > 0)
        self.action_bar.secondary_btn.setToolTip(
            "" if custom_points > 0
            else "还没有自定义准心数据——先在「自定义准心」卡片里绘制一个")
        self.action_bar.configure_primary("", None, visible=False)

        # ⭐ RN-174：底栏这行字要**先回答那个 5/6 票的困惑**（"我改的东西保存了吗"），
        # 再报状态。原来它只报状态，于是玩家在整页找不到任何"已保存"的回执，
        # 就会去找一颗保存按钮 —— 而那颗按钮不存在。
        # ⚠⚠ RN-407（批 16）：那句回执**已经不在这儿了**。批 10 我写的是无条件的
        #   「改动已自动保存，不用点任何按钮。」——它在总开关开着时是真话，
        #   关着时是假话，而外审对它的判词是现状 4/4 高、候选 C 6/6 高。
        #   现在它由 `PageActionBar.set_effect_state()` 按总开关的实际状态拼，
        #   本页只负责报**状态**那一截。⭐ 一句只在某个状态下为真的回执，
        #   在别的状态里就是一句谎。
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
            if self._custom_style_is_blank():
                # RN-406：他刚点完「自定义」，这张卡要当场回答
                # 「所以现在屏幕上是什么」——答案是**什么都没有**。
                # ⚠ 主句是后果，不是指路：批 10 刚实测过「补一句指路」票数一票不掉。
                style_text += " —— 还没画过，屏幕上不会出现准心"
            elif custom_points:
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
            elif self._custom_style_is_blank():
                # RN-406：样式已经切到「自定义」了，这里就不再是一句软建议。
                # ⭐ 同一句话在两种状态下的**性质**不同：一种是"这样会更好"，
                # 另一种是"不做这件事，功能就是坏的"。
                custom_text = "样式已选「自定义」，但一个点都还没画 —— 现在准心不会显示。"
            else:
                custom_text = "当前还没有自定义点，先绘制一个常用模板会更高效。"
            self.custom_summary_label.setText(custom_text)
            self.custom_summary_label.setToolTip(custom_text)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页那条状态文案重算一遍。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致，RN-107 族。
        """
        self._sync_overview_status()

    def _sync_overview_status(self):
        enabled = bool(getattr(config, "crosshair_enabled", False))
        style_value = str(getattr(config, "crosshair_style", "crosshair") or "crosshair")
        color_value = str(getattr(config, "crosshair_color", "green") or "green")
        animation_value = str(getattr(config, "crosshair_animation", "none") or "none")
        kill_effect_value = str(getattr(config, "crosshair_kill_effect", "none") or "none")
        size_value = int(getattr(config, "crosshair_size", 20) or 20)
        thickness_value = int(getattr(config, "crosshair_thickness", 2) or 2)
        custom_points = len(getattr(config, "crosshair_custom_data", []) or [])

        # RN-406：选中「自定义」而一个点都没画时，`_paint_custom` 直接 return ——
        # 屏幕上一个像素都不画，而这一格原来写的是 `样式 · 自定义`（info 色），
        # 和「十字」「圆圈」那些**完全正常**的状态长得一模一样。
        # ⭐ 让**颜色**携带「现在能不能用」这个信息，是这条修法里唯一结构性的部分；
        #   文案只加五个字（⚠ 徽章文案改长会让芯片换行、比同排另外四颗高一截 ——
        #   那条是拿 kill_sound 那一轮换来的，而排版审计三条判据一条都看不见它）。
        blank_custom = self._custom_style_is_blank()
        style_text = self._format_style_text(style_value)
        badges = [
            ("positive" if enabled else "warning", f"显示 · {'已启用' if enabled else '未启用'}"),
            ("warning" if blank_custom else "info",
             f"样式 · {style_text}（未绘制）" if blank_custom else f"样式 · {style_text}"),
            ("info", f"颜色 · {self._format_color_text(color_value)}"),
            ("info", f"大小 · {size_value} / {thickness_value}"),
            (
                "positive" if animation_value != "none" else "info",
                f"动效 · {self._format_animation_text(animation_value)}",
            ),
            (
                # ⚠ 这里原来是 `else "warning"` ——「关闭联动」是**默认值**，
                # 一个完全正常的状态，却常年顶着一颗橙色警示。外审改前那一轮
                # 5 发点名它「极易误导玩家以为是系统报警或必须配置的异常项」。
                # ⭐⭐ 而它同时在**稀释真警告**：RN-406 刚在同一排加了一颗
                #   「样式 · 自定义（未绘制）」——那颗是真的。
                #   **两颗橙的等于零颗**（RN-139「两颗紫的等于零颗」的徽章版）。
                "positive" if kill_effect_value != "none" else "info",
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
        if style_value == "custom":
            # ⚠⚠ 原来是 `if style_value == "custom" and custom_points:` ——
            # **有点时才说，0 点时整句消失**。⭐ 一个在最需要说话的时候恰好闭嘴的
            # 提示，比没有这个提示更糟：它让「一切正常」和「什么都画不出来」
            # 在紧凑档里长得一模一样。
            compact_parts.append(
                f"自定义 {custom_points} 点" if custom_points else "自定义未绘制")

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

        # RN-144 升级版（第二稿）：总开关**独占卡片第一行、贴左边**。
        # 外审 6/6 票「玩家调完准心进游戏不显示，会以为软件坏了」；
        # 第一版的跳转按钮被复跑 15/15 判"仍然割裂"；
        # 第二版把开关塞在状态行右端，又被 84 发里的 12 发判"藏在角落"。
        # ⭐ 同一个角落位置，装什么都会被判"够不着" —— **位置本身就是那个缺陷**。
        self.master_switch_row = make_master_switch_row(
            self, "crosshair_enabled", "准心")
        layout.addWidget(self.master_switch_row)

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
        card.setToolTip("这里展示当前配置的静态预览；游戏里显不显示，看总开关。")
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

        # RN-407 第③件：预览**照常画**，但要说清楚它意味着什么。
        # ⚠ 候选 C 那一轮试的是「关着就别渲染」，6/6 判高「失去反馈，与底栏矛盾」
        #   —— 比它想修的那条还重。⭐ 说后果，别撤反馈。
        # 位置在预览框**紧下方**：解释性文字要放在困惑发生的地方，
        # 放页尾等于没放（官网那两轮 6 发的判词是「藏在底部小字里」）。
        from widgets.master_switch_effect import make_preview_effect_caption

        self.preview_effect_caption = make_preview_effect_caption()
        layout.addWidget(self.preview_effect_caption)
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

        # 中心间隙。默认 0 = 两条线穿过圆心，正好糊住你要瞄的那个点；
        # 这是这次补齐里对实战影响最直接的一项。
        gap_header = QHBoxLayout()
        gap_title = QLabel("中心间隙")
        gap_header.addWidget(gap_title)
        gap_header.addStretch()
        self.gap_value_label = QLabel(str(getattr(config, "crosshair_gap", 0)))
        gap_header.addWidget(self.gap_value_label)
        layout.addLayout(gap_header)

        self.gap_slider = QSlider(Qt.Horizontal)
        self.gap_slider.setMinimum(0)
        self.gap_slider.setMaximum(20)
        self.gap_slider.setValue(int(getattr(config, "crosshair_gap", 0) or 0))
        self.gap_slider.setToolTip("准星中心留空多少像素。0 表示两条线穿过圆心，会挡住瞄准点。")
        self.gap_slider.valueChanged.connect(self._on_gap_changed)
        layout.addWidget(self.gap_slider)

        # 描边。纯色细线在亮地板/沙地上基本看不见，这是可见性的主要手段。
        outline_header = QHBoxLayout()
        outline_title = QLabel("黑色描边")
        outline_header.addWidget(outline_title)
        outline_header.addStretch()
        self.outline_value_label = QLabel(str(getattr(config, "crosshair_outline", 0)))
        outline_header.addWidget(self.outline_value_label)
        layout.addLayout(outline_header)

        self.outline_slider = QSlider(Qt.Horizontal)
        self.outline_slider.setMinimum(0)
        self.outline_slider.setMaximum(4)
        self.outline_slider.setValue(int(getattr(config, "crosshair_outline", 0) or 0))
        self.outline_slider.setToolTip("给准星描一圈黑边，亮色地面上更容易看清。0 为不描边。")
        self.outline_slider.valueChanged.connect(self._on_outline_changed)
        layout.addWidget(self.outline_slider)

        # 透明度
        alpha_header = QHBoxLayout()
        alpha_title = QLabel("不透明度")
        alpha_header.addWidget(alpha_title)
        alpha_header.addStretch()
        self.alpha_value_label = QLabel(
            f"{int(getattr(config, 'crosshair_alpha', 255) or 255) * 100 // 255}%"
        )
        alpha_header.addWidget(self.alpha_value_label)
        layout.addLayout(alpha_header)

        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setMinimum(10)
        self.alpha_slider.setMaximum(100)
        self.alpha_slider.setValue(
            max(10, int(getattr(config, "crosshair_alpha", 255) or 255) * 100 // 255)
        )
        self.alpha_slider.valueChanged.connect(self._on_alpha_changed)
        layout.addWidget(self.alpha_slider)

        self.dot_checkbox = QCheckBox("显示中心点")
        self.dot_checkbox.setToolTip("在准星中心叠一个实心点，配合中心间隙使用效果最好")
        self.dot_checkbox.setChecked(bool(getattr(config, "crosshair_dot", False)))
        self.dot_checkbox.toggled.connect(self._on_dot_toggled)
        layout.addWidget(self.dot_checkbox)

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

        # 六个固定色名之外的任意颜色。留着色名不动，清空自定义色就回到色名——
        # 存量配置指向的是那六个名字，不能替换掉。
        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        self.custom_color_btn = QPushButton("自定义颜色…")
        self.custom_color_btn.setFixedHeight(32)
        style_as_secondary_button(self.custom_color_btn)
        self.custom_color_btn.clicked.connect(self._on_custom_color_picked)
        custom_row.addWidget(self.custom_color_btn)

        self.clear_custom_color_btn = QPushButton("恢复")
        self.clear_custom_color_btn.setFixedWidth(64)
        self.clear_custom_color_btn.setFixedHeight(32)
        style_as_secondary_button(self.clear_custom_color_btn)
        self.clear_custom_color_btn.clicked.connect(self._on_custom_color_cleared)
        custom_row.addWidget(self.clear_custom_color_btn)
        custom_row.addStretch()
        layout.addLayout(custom_row)
        self._sync_custom_color_button()

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
        card.setToolTip("测试前需要先打开总开关，否则看不到联动效果。")
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

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # RN-119（用户裁定 2026-08-19）：说清楚导入到底收什么。
        # 玩家手里的准心几乎都是 CS2 官方分享码（CSGO-xxxxx-…），而这里只认
        # 本软件导出的 json —— 不写明就是"点了才发现不支持"。
        # ⚠ 措辞不许承诺没做的事：分享码解码没实现，就写"暂不支持"，
        #   判据 test_the_copy_does_not_promise_share_code_support 盯着这件事。
        self.custom_hint_label = QLabel(
            "导入 / 导出在页面底部操作栏，只认本软件导出的 .json；"
            "CS2 官方分享码（CSGO-…）暂不支持。"
        )
        self.custom_hint_label.setObjectName("hintLabel")
        self.custom_hint_label.setWordWrap(True)
        layout.addWidget(self.custom_hint_label)

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
    
    def _apply_style_extra(self, attr, value, label=None, label_text=None):
        """新增样式参数的公共落盘路径：存配置 → 刷预览 → 刷渲染器 → 刷概览。"""
        setattr(config, attr, value)
        if label is not None:
            label.setText(label_text)
        config.save_config()
        self._update_preview()
        self._update_crosshair_system()
        self._sync_overview_status()
        self.logger.debug(f"{attr} 更新: {value}")

    def _on_gap_changed(self, value):
        self._apply_style_extra("crosshair_gap", int(value), self.gap_value_label, str(value))

    def _on_outline_changed(self, value):
        self._apply_style_extra("crosshair_outline", int(value), self.outline_value_label, str(value))

    def _on_alpha_changed(self, value):
        # 滑块是百分比，配置存 0-255
        self._apply_style_extra(
            "crosshair_alpha", max(0, min(255, int(value) * 255 // 100)),
            self.alpha_value_label, f"{value}%",
        )

    def _on_dot_toggled(self, checked):
        self._apply_style_extra("crosshair_dot", bool(checked))

    def _on_custom_color_picked(self):
        from PySide6.QtWidgets import QColorDialog

        current = str(getattr(config, "crosshair_color_custom", "") or "") or "#00ff00"
        picked = QColorDialog.getColor(QColor(current), self, "选择准星颜色")
        if not picked.isValid():
            return
        self._apply_style_extra("crosshair_color_custom", picked.name())
        self._sync_custom_color_button()

    def _on_custom_color_cleared(self):
        """清空自定义色 = 回到上面那六个色名。"""
        self._apply_style_extra("crosshair_color_custom", "")
        self._sync_custom_color_button()

    def _sync_custom_color_button(self):
        if not hasattr(self, "custom_color_btn"):
            return
        value = str(getattr(config, "crosshair_color_custom", "") or "").strip()
        self.custom_color_btn.setText(f"自定义颜色：{value}" if value else "自定义颜色…")
        self.clear_custom_color_btn.setVisible(bool(value))

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
        self._start_preview_burst()      # RN-116：让玩家在选之前看见它长什么样
        self.logger.info(f"准心动画更新: {animation_text} -> {animation_value}")
    
    def _on_kill_effect_changed(self):
        """击杀联动改变"""
        effect_text = self.kill_effect_combo.currentText()
        effect_value = self._get_kill_effect_value(effect_text)
        config.crosshair_kill_effect = effect_value
        config.save_config()
        self._update_crosshair_system()
        self._sync_overview_status()
        self._start_preview_burst()      # RN-116：同上
        self.logger.info(f"击杀联动更新: {effect_text} -> {effect_value}")
    
    def _test_kill_effect(self):
        """测试击杀联动效果"""
        if not self.crosshair_animation or not self.crosshair_animation.is_visible:
            QMessageBox.information(self, "提示", "请先打开总开关，再测试击杀联动效果")
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
    
    # ------------------------------------------------------------ RN-116 示意播放
    def _start_preview_burst(self):
        """换了动画/联动之后，把预览播 `PREVIEW_BURST_MS` 毫秒再停回静止。"""
        try:
            from crosshair_overlay import CrosshairAnimator
        except Exception:
            self.logger.exception("预览示意启动失败（不影响设置本身）")
            return
        self._burst_animator = CrosshairAnimator()
        self._burst_elapsed_ms = 0
        if not self.preview_burst_timer.isActive():
            self.preview_burst_timer.start()
        self._update_preview()

    def _tick_preview_burst(self):
        self._burst_elapsed_ms += self.preview_burst_timer.interval()
        if self._burst_elapsed_ms >= self.PREVIEW_BURST_MS:
            self._stop_preview_burst()
            return
        self._update_preview()

    def _stop_preview_burst(self):
        """示意结束：停表、回到静止形态。

        ⚠ 这个方法有两个调用点（到点、离开页面），**两个都不能省**：
        少了前者它就成了常驻定时器，少了后者它就成了"藏起来的常驻定时器"。
        """
        if self.preview_burst_timer.isActive():
            self.preview_burst_timer.stop()
        self._burst_animator = None
        self._burst_elapsed_ms = 0
        self._update_preview()

    def hideEvent(self, event):
        """页面被切走时停掉示意 —— 看不见的动画只是在烧 CPU。"""
        self._stop_preview_burst()
        super().hideEvent(event)

    def _update_preview(self):
        """更新准心预览——**直接调渲染层，不再自己画一遍**。

        原来这里有一整套独立的绘制分支，和 `crosshair_overlay.paint_crosshair`
        的几何对不上，而且是每个样式各错各的：
          · 十字 / T 型：预览半长 = size，实际 = size//2 —— 预览是实际的 **2 倍**
          · 点：预览半径**乘了 thickness/2**，实际与粗细无关 —— 调粗细时预览
            会变大而游戏里纹丝不动
          · 圆圈：碰巧一致
        所以"切样式时哪个更大"的相对关系在预览里就是错的。

        这个文件顶部的注释已经为同类问题痛斥过一次（样式中文名当年抄了三遍），
        只是那次抄的是文案、这次抄的是几何。修法一样：**只留一份**。
        预览现在是 1:1 物理像素，所见即游戏里所得。
        """
        try:
            from crosshair_overlay import (
                CANVAS_PX,
                CrosshairAnimator,
                CrosshairState,
                paint_crosshair,
            )

            custom_color = str(getattr(config, "crosshair_color_custom", "") or "").strip()
            state = CrosshairState(
                size=int(getattr(config, "crosshair_size", 20) or 20),
                thickness=int(getattr(config, "crosshair_thickness", 2) or 2),
                color=custom_color or str(getattr(config, "crosshair_color", "green") or "green"),
                style=str(getattr(config, "crosshair_style", "crosshair") or "crosshair"),
                animation=str(getattr(config, "crosshair_animation", "none") or "none"),
                kill_effect="none",  # 预览是静态的，不放击杀联动
                custom_points=tuple(
                    tuple(p) for p in (getattr(config, "crosshair_custom_data", ()) or ())
                ),
                gap=max(0, int(getattr(config, "crosshair_gap", 0) or 0)),
                outline=max(0, int(getattr(config, "crosshair_outline", 0) or 0)),
                dot=bool(getattr(config, "crosshair_dot", False)),
                alpha=max(0, min(255, int(getattr(config, "crosshair_alpha", 255) or 255))),
            )
            # now=0.0 且动画器是全新的 → 相位 0 = 各动画的静止形态，结果确定
            # RN-116：示意播放期间沿用**同一个** animator 并推进相位，
            # 这样看到的就是动画本身，而不是它的静止形态。
            if self.preview_burst_timer.isActive() and self._burst_animator is not None:
                frame = self._burst_animator.advance(state, self._burst_elapsed_ms / 1000.0)
            else:
                frame = CrosshairAnimator().advance(state, 0.0)

            # UP-033: 按设备像素比出图。frame 的坐标是**物理像素**，所以画布就按
            # CANVAS_PX 个物理像素建，再把 dpr 标回图上让 Qt 缩到对应的逻辑尺寸——
            # 这样预览在屏幕上占的物理像素数与游戏里完全相同。
            dpr = float(self.preview_label.devicePixelRatioF() or 1.0)
            if dpr <= 0:
                dpr = 1.0

            # ⚠ **不要在 QImage 上设 devicePixelRatio**。设了之后 QPainter 的
            # 坐标系会变成逻辑像素，而 frame 的坐标是物理像素——1.25 档下这张
            # 100px 的画布会被当成 80px 用，预览反而比游戏里小、还糊。
            # DPR 只标在 pixmap 上：位图仍是 CANVAS_PX 个真实像素，Qt 按 dpr
            # 缩到 CANVAS_PX/dpr 个逻辑像素显示，屏幕上占的物理像素恰好不变。
            image = QImage(CANVAS_PX, CANVAS_PX, QImage.Format_ARGB32)
            image.fill(Qt.transparent)

            painter = QPainter(image)
            paint_crosshair(painter, frame)
            painter.end()

            # RN-406：选中「自定义」而一个点都没画时，`paint_crosshair` 画出来的
            # 是一张**全透明**的图 —— 预览框于是变成一个纯黑的大方块。
            # ⭐ 那正是缺陷的现场，而现场上一个字都没有：**它长得像渲染坏了**，
            #   而不是像「你还没画」。⇒ 这里不放图，放话。
            if self._custom_style_is_blank():
                self.preview_label.setPixmap(QPixmap())
                # ⚠ 措辞要短到**不会在窄卡片里折出半个词**：第一版
                # 「此时游戏里不会显示任何准心」实测折成
                # 「…不会显示任何 / 准心」，断在词中间。
                self.preview_label.setText("还没画过自定义准心\n游戏里不会显示准心")
                self.preview_label.setWordWrap(True)
            else:
                self.preview_label.setText("")
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
        self.gap_slider.setValue(int(getattr(config, "crosshair_gap", 0) or 0))
        self.outline_slider.setValue(int(getattr(config, "crosshair_outline", 0) or 0))
        self.alpha_slider.setValue(
            max(10, int(getattr(config, "crosshair_alpha", 255) or 255) * 100 // 255)
        )
        self.dot_checkbox.setChecked(bool(getattr(config, "crosshair_dot", False)))
        self._sync_custom_color_button()
        
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

