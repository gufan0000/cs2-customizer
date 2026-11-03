# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QSlider, QComboBox, QPushButton,
                               QFrame, QScrollArea, QButtonGroup, QDialog,
                               QMessageBox, QFileDialog, QSizePolicy, QCheckBox,
                               QGridLayout, QStyle)
from PySide6.QtCore import Qt, QTimer, QEvent
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
from widgets.crosshair_stage import SCENE_LABELS, ColorSwatch, CrosshairStage, SegmentRadio
from widgets.overlay_requirement import make_overlay_requirement_label
from widgets.status_strip import StatusStrip
from ui_style_applier import keep_single_line

#: RN-429：准心由 `crosshair_overlay` 画在游戏画面上。
DRAWS_OVER_THE_GAME = True

#: 滑杆那一格的行距、列距（批 157，原 6 / 8）
SLIDER_ROW_VSPACING = 12
SLIDER_ROW_HSPACING = 12


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
    #: 批 153 正文 14px 起：1.25 倍字号下「绘制 / 导入 / 导出准心」三颗按钮一行要 364。
    #: 按钮的布局下限被样式表 min-width 钉在字宽以下，`minimumSizeHint` 算不出这一行，只能靠这个下限
    PANEL_MIN_WIDTH = 368

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

        # R1-8: 拖 .xchr/.json 准心文件进页面即导入
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, (".xchr", ".json"), self._on_crosshair_file_dropped)
        except Exception:
            self.logger.exception("准心页拖拽导入初始化失败(不影响其它功能)")

        # RN-415：先把滑块原本的说明存下来（禁用时要换一句话，切回去要换回来），
        # 再按当前样式过一遍可用性。⚠ 存**建页时**那一份 —— 等它被换过之后再存，
        # 存下来的就是那句替换文案了（同 RN-093「锚点会随代码一起腐烂」的形态）。
        self._original_slider_tips = {
            attr: getattr(self, attr).toolTip()
            for names in self.STYLE_DEAD_SLIDERS.values() for attr in names
            if getattr(self, attr, None) is not None
        }
        self.load_settings()

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
        
        main_layout.addWidget(self._create_overview_card())

        # 批 146：左边一大块预览，右边一栏参数。调参数时预览一直在眼前，不用来回滚。
        body = QHBoxLayout()
        body.setSpacing(16)
        self.preview_column = self._create_preview_column()
        body.addWidget(self.preview_column, 1)
        self.parameter_scroll = self._create_parameter_panel()
        # 批 160：栏里内容变宽（换了样式、填进数据）不会发 StyleChange，栏宽要跟着布局请求重算
        self.parameter_scroll.widget().installEventFilter(self)
        body.addWidget(self.parameter_scroll, 0)
        main_layout.addLayout(body, 1)

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
        # 「绘制准心」只留在参数栏最下面那一颗。
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
        # 全页唯一的紫按钮是参数栏里那颗「绘制准心」——
        # 那也确实是这一页唯一一个"点了会发生新事情"的动作（RN-139/RN-186：
        # **「主」是相对的，两颗紫的等于零颗**）。
        # ⚠ 「导出准心」没数据时**置灰而不是藏掉**：藏掉的话用户看到的是
        #   "这个功能不存在"，而不是"还没有东西可导"（同 RN-197）。
        self.action_bar.configure_extra("导入准心", self._import_crosshair, visible=True)
        # RN-410（批 27）：这句话原来只躺在页尾（y=1000），而这颗按钮在 y=681 ——
        # 说明在**按钮下方 319px、折线之外**，而按钮自己的 tooltip 是空的。
        # ⭐ 解释要放在困惑发生的地方；这颗按钮就是困惑发生的地方。
        self.action_bar.extra_btn.setToolTip(
            "收本软件导出的 .xchr（.json 也能直接拖进页面）；"
            "CS2 官方分享码（CSGO-…）在上面「CS2 分享码」一栏粘贴。")
        self.action_bar.configure_secondary("导出准心", self._export_crosshair, visible=True)
        self.action_bar.secondary_btn.setEnabled(custom_points > 0)
        self.action_bar.secondary_btn.setToolTip(
            "" if custom_points > 0
            else f"还没有自定义准心数据——先点「{self.draw_button.text()}」画一个")
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
        custom_points = len(getattr(config, "crosshair_custom_data", []) or [])
        if custom_points > 0:
            custom_text = f"已保存 {custom_points} 个自定义点，可继续微调后导入或导出。"
        elif self._custom_style_is_blank():
            # RN-406：样式已经切到「自定义」了，这里就不再是一句软建议。
            # ⭐ 同一句话在两种状态下的**性质**不同：一种是"这样会更好"，
            # 另一种是"不做这件事，功能就是坏的"。
            custom_text = "样式已选「自定义」，但一个点都还没画 —— 现在准心不会显示。"
        else:
            custom_text = ""
        self.custom_summary_label.setText(custom_text)
        self.custom_summary_label.setToolTip(custom_text)
        self.custom_summary_label.setVisible(bool(custom_text))

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
            ("positive" if enabled else "warning", f"显示 · {'已开启' if enabled else '未开启'}"),
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
        self.status_card.setToolTip(detail_text)
        self._sync_panel_summaries()
        self._sync_action_bar()

    def _create_overview_card(self):
        card = StatusStrip()
        self.status_card = card
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # RN-144 升级版（第二稿）：总开关**独占卡片第一行、贴左边**。
        # 外审 6/6 票「玩家调完准心进游戏不显示，会以为软件坏了」；
        # 第一版的跳转按钮被复跑 15/15 判"仍然割裂"；
        # 第二版把开关塞在状态行右端，又被 84 发里的 12 发判"藏在角落"。
        # ⭐ 同一个角落位置，装什么都会被判"够不着" —— **位置本身就是那个缺陷**。
        self.master_switch_row = make_master_switch_row(
            self, "crosshair_enabled", "准心")

        self.status_badge_label = create_badge_label()
        layout.addWidget(self.status_badge_label)

        # RN-429：准心是**画在游戏画面上**的覆盖层，独占全屏下一个像素都出不来。
        # ⚠ 这一页原来**全仓零命中**，而页头只说了「不改动游戏的任何配置文件」
        #   —— 那句话让人更相信「装好就能用」。外审改前一轮 6 发判高。
        layout.addWidget(make_overlay_requirement_label("准心"))


        return card
    
    def _create_card(self):
        """创建标准卡片"""
        card = QFrame()
        card.setObjectName("card")
        return card
    
    def _create_preview_column(self):
        """左边：预览舞台和底色切换。调参数时它一直在眼前。"""
        column = QWidget()
        # ⚠ 这个 objectName 不是样式钩子，是给**焦点巡检**用的：Tab 是一列一列走的（RN-122）
        column.setObjectName("layoutColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.preview_frame = CrosshairStage()
        self.preview_frame.setAccessibleName("准心预览")
        stage_layout = QVBoxLayout(self.preview_frame)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel()
        self.preview_label.setObjectName("crosshairPreviewLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        keep_single_line(self.preview_label)
        stage_layout.addWidget(self.preview_label, 0, Qt.AlignCenter)

        # ⭐⭐ RN-414（批 27）：选中「自定义」而一个点都没画时，**这块预览框就是入口**。
        # ⚠ 不能就地再放一颗「绘制准心」：`test_draw_crosshair_appears_exactly_once`
        #   明令这一屏只许有一颗（RN-404 族）。
        # ⭐ **看着可点的东西，要么真的可点，要么别长那个样子。**
        self.preview_frame.setToolTip("")
        self.preview_frame.mouseReleaseEvent = self._on_preview_clicked
        self._preview_is_entry = False
        layout.addWidget(self.preview_frame, 1)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.scene_group = QButtonGroup(self)
        scene_radios = []
        for scene, name in SCENE_LABELS.items():
            radio = SegmentRadio(name)
            radio.setToolTip("换个底色，看准心在亮处、暗处和烟里还清不清楚")
            radio.setChecked(scene == self.preview_frame.scene())
            radio.toggled.connect(
                lambda checked, s=scene: self.preview_frame.set_scene(s) if checked else None)
            self.scene_group.addButton(radio)
            scene_radios.append(radio)
        row.addWidget(self._make_segment_frame(scene_radios), 0)

        # RN-407 第③件：预览**照常画**，但要说清楚它意味着什么。
        # ⚠ 候选 C 那一轮试的是「关着就别渲染」，6/6 判高「失去反馈，与底栏矛盾」
        #   —— 比它想修的那条还重。⭐ 说后果，别撤反馈。
        from widgets.master_switch_effect import make_preview_effect_caption

        self.preview_effect_caption = make_preview_effect_caption()
        row.addWidget(self.preview_effect_caption, 1)
        layout.addLayout(row)
        return column

    @staticmethod
    def _make_segment_frame(radios):
        frame = QFrame()
        frame.setObjectName("segmentGroup")
        frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        for radio in radios:
            row.addWidget(radio)
        return frame

    @staticmethod
    def _make_section_title(text, search_text=""):
        title = QLabel(text)
        title.setObjectName("panelSectionTitle")
        keep_single_line(title)
        if search_text:
            title.setProperty("fp_search_text", search_text)
        return title

    @staticmethod
    def _make_divider():
        line = QFrame()
        line.setObjectName("panelDivider")
        line.setFixedHeight(1)
        return line

    def _create_parameter_panel(self):
        """右边：一栏参数。窗口矮时只有这一栏滚，预览不动。

        RN-115（用户裁定 2026-08-19）：**先让人选准心，再让人调参数**，样式和颜色排最上面。
        ⚠ **创建顺序 = Tab 焦点顺序**：这里的调用顺序就是从上到下的版面顺序。
        """
        panel = self._create_card()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._add_style_section(layout)
        self._add_color_section(layout)
        layout.addWidget(self._make_divider())
        self._add_slider_section(layout)
        layout.addWidget(self._make_divider())
        self._add_effect_section(layout)
        layout.addWidget(self._make_divider())
        self._add_sharecode_section(layout)
        layout.addWidget(self._make_divider())
        self._add_custom_section(layout)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("layoutColumn")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        return scroll

    def _sync_panel_width(self):
        """参数栏宽度：下限和内容最小宽取大的。

        ⚠ 滚动区的最小宽不看内容，横向滚动条又关着：字号放大时内容会被裁掉，所以要现算。
        """
        panel = self.parameter_scroll.widget()
        bar = self.parameter_scroll.style().pixelMetric(
            QStyle.PM_ScrollBarExtent, None, self.parameter_scroll)
        # 批 160：样式表的 min-width 比字宽小，栏里这几颗按钮的下限按字钉住，字大一档才不会被挤成省略号
        action_bar = getattr(self, "action_bar", None)
        buttons = [self._kill_test_btn] + ([action_bar.extra_btn, action_bar.secondary_btn, action_bar.primary_btn]
                                           if action_bar is not None else [])
        for button in buttons:
            button.setMinimumWidth(button.sizeHint().width())
        need = panel.minimumSizeHint().width() + bar
        if action_bar is not None:
            need = max(need, action_bar.minimumSizeHint().width())
        self.parameter_scroll.setFixedWidth(max(self.PANEL_MIN_WIDTH, need))

    def showEvent(self, event):
        self._sync_panel_width()
        super().showEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange) and hasattr(self, "parameter_scroll"):
            self._sync_panel_width()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.LayoutRequest and watched is self.parameter_scroll.widget():
            self._sync_panel_width()
        return super().eventFilter(watched, event)

    def _add_style_section(self, layout):
        layout.addWidget(self._make_section_title("样式", "准心样式"))
        self.style_group = QButtonGroup(self)
        radios = []
        for style_value, style_name in CROSSHAIR_STYLE_LABELS.items():
            radio = SegmentRadio(style_name)
            self.style_group.addButton(radio)
            radio.setProperty("style_value", style_value)
            if style_value == config.crosshair_style:
                radio.setChecked(True)
            radio.toggled.connect(lambda checked, s=style_value: self._on_style_changed(s) if checked else None)
            radios.append(radio)
        layout.addWidget(self._make_segment_frame(radios))

    def _add_color_section(self, layout):
        from crosshair_overlay import COLOR_MAP

        layout.addWidget(self._make_section_title("颜色", "准心颜色"))
        self.color_group = QButtonGroup(self)
        colors = [
            ("red", "红色"),
            ("green", "绿色"),
            ("blue", "蓝色"),
            ("yellow", "黄色"),
            ("cyan", "青色"),
            ("white", "白色")
        ]
        row = QHBoxLayout()
        row.setSpacing(2)
        for color_code, color_name in colors:
            radio = ColorSwatch(COLOR_MAP[color_code], color_name)
            self.color_group.addButton(radio)
            radio.setProperty("color_value", color_code)
            row.addWidget(radio)
            if color_code == config.crosshair_color:
                radio.setChecked(True)
            radio.toggled.connect(lambda checked, c=color_code: self._on_color_changed(c) if checked else None)
        row.addStretch()
        layout.addLayout(row)

        # 六个固定色名之外的任意颜色。留着色名不动，清空自定义色就回到色名——
        # 存量配置指向的是那六个名字，不能替换掉。
        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        self.custom_color_btn = QPushButton("自定义颜色…")
        style_as_secondary_button(self.custom_color_btn)
        self.custom_color_btn.clicked.connect(self._on_custom_color_picked)
        custom_row.addWidget(self.custom_color_btn)

        self.clear_custom_color_btn = QPushButton("恢复")
        style_as_secondary_button(self.clear_custom_color_btn)
        self.clear_custom_color_btn.clicked.connect(self._on_custom_color_cleared)
        custom_row.addWidget(self.clear_custom_color_btn)
        custom_row.addStretch()
        layout.addLayout(custom_row)
        self._sync_custom_color_button()

    def _add_slider_row(self, grid, row, title, accessible_name, value_range, value, on_change,
                        value_text, tip=""):
        label = QLabel(title)
        keep_single_line(label)
        # 这一页不用再写「准心大小」，可用户搜的还是这几个字（索引和跳转都读它）
        label.setProperty("fp_search_text", accessible_name)
        grid.addWidget(label, row, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setAccessibleName(accessible_name)
        slider.setMinimum(value_range[0])
        slider.setMaximum(value_range[1])
        slider.setValue(value)
        if tip:
            slider.setToolTip(tip)
        slider.valueChanged.connect(on_change)
        grid.addWidget(slider, row, 1)
        value_label = QLabel(value_text)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        keep_single_line(value_label)
        # 数值列按最宽的「100%」留宽：拖到 100% 时滑杆不再被挤短一截
        value_label.setMinimumWidth(value_label.fontMetrics().horizontalAdvance("100%"))
        grid.addWidget(value_label, row, 2)
        return slider, value_label

    def _add_slider_section(self, layout):
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        # 批 157：五根滑杆挤在一起，名字贴着滑杆（codex 设计建议）
        grid.setHorizontalSpacing(SLIDER_ROW_HSPACING)
        grid.setVerticalSpacing(SLIDER_ROW_VSPACING)
        grid.setColumnStretch(1, 1)

        self.size_slider, self.size_value_label = self._add_slider_row(
            grid, 0, "大小", "准心大小", (5, 50), config.crosshair_size,
            self._on_size_changed, str(config.crosshair_size),
            "建议先确定整体大小，再微调粗细，这样更容易找到既清晰又不遮挡视线的平衡点。")
        self.thickness_slider, self.thickness_value_label = self._add_slider_row(
            grid, 1, "粗细", "准心粗细", (1, 10), config.crosshair_thickness,
            self._on_thickness_changed, str(config.crosshair_thickness))
        # 中心间隙。默认 0 = 两条线穿过圆心，正好糊住你要瞄的那个点；
        # 这是这次补齐里对实战影响最直接的一项。
        gap = int(getattr(config, "crosshair_gap", 0) or 0)
        self.gap_slider, self.gap_value_label = self._add_slider_row(
            grid, 2, "中心间隙", "中心间隙", (0, 20), gap,
            self._on_gap_changed, str(gap),
            "准星中心留空多少像素。0 表示两条线穿过圆心，会挡住瞄准点。")
        # 描边。纯色细线在亮地板/沙地上基本看不见，这是可见性的主要手段。
        outline = int(getattr(config, "crosshair_outline", 0) or 0)
        self.outline_slider, self.outline_value_label = self._add_slider_row(
            grid, 3, "黑色描边", "黑色描边", (0, 4), outline,
            self._on_outline_changed, str(outline),
            "给准星描一圈黑边，亮色地面上更容易看清。0 为不描边。")
        alpha = max(0, int((255 if getattr(config, "crosshair_alpha", None) is None else config.crosshair_alpha)) * 100 // 255)
        self.alpha_slider, self.alpha_value_label = self._add_slider_row(
            grid, 4, "不透明度", "不透明度", (0, 100), alpha,
            self._on_alpha_changed, f"{alpha}%")
        layout.addLayout(grid)

        self.dot_checkbox = QCheckBox("显示中心点")
        self.dot_checkbox.setToolTip("在准星中心叠一个实心点，配合中心间隙使用效果最好")
        self.dot_checkbox.setChecked(bool(getattr(config, "crosshair_dot", False)))
        self.dot_checkbox.toggled.connect(self._on_dot_toggled)
        layout.addWidget(self.dot_checkbox)

    def _add_effect_section(self, layout):
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        animation_label = QLabel("动画")
        animation_label.setProperty("fp_search_text", "动画效果")
        keep_single_line(animation_label)
        grid.addWidget(animation_label, 0, 0)
        self.animation_combo = QComboBox()
        self.animation_combo.setAccessibleName("准心动画")
        self.animation_combo.setToolTip("动画只影响显示节奏，不会改变准心的基础形态。")
        self.animation_combo.addItems([
            "无动画", "呼吸效果", "脉冲效果", "变色效果", "旋转效果",
            "扩散效果", "弹跳效果", "闪烁效果", "抖动效果"
        ])
        self.animation_combo.currentIndexChanged.connect(self._on_animation_changed)
        grid.addWidget(self.animation_combo, 0, 1, 1, 2)

        kill_label = QLabel("击杀联动")
        keep_single_line(kill_label)
        grid.addWidget(kill_label, 1, 0)
        self.kill_effect_combo = QComboBox()
        self.kill_effect_combo.setAccessibleName("击杀联动效果")
        self.kill_effect_combo.addItems([
            "关闭联动", "脉冲效果", "爆炸效果", "旋转效果", "抖动效果",
            "X形闪烁", "彩虹冲击波", "破碎重组", "多重脉冲", "霓虹扩散",
            "十字星辉"
        ])
        self.kill_effect_combo.currentIndexChanged.connect(self._on_kill_effect_changed)
        # 批 160：按最长项定最小宽的话，字大一档后窄栏里会把「试一下」挤成省略号
        for combo in (self.animation_combo, self.kill_effect_combo):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(5)
        grid.addWidget(self.kill_effect_combo, 1, 1)

        test_btn = self._kill_test_btn = QPushButton("试一下")
        test_btn.setToolTip("要先打开总开关，否则看不到联动效果。")
        style_as_secondary_button(test_btn)
        test_btn.clicked.connect(self._test_kill_effect)
        grid.addWidget(test_btn, 1, 2)
        layout.addLayout(grid)

    def _add_sharecode_section(self, layout):
        """批 130：粘贴 CS2 分享码套到 CS2 Customizer 准心；把当前准心导出成分享码（复制到剪贴板）。"""
        from PySide6.QtWidgets import QLineEdit

        layout.addWidget(self._make_section_title("CS2 分享码"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.sharecode_edit = QLineEdit()
        self.sharecode_edit.setAccessibleName("准心分享码")
        self.sharecode_edit.setPlaceholderText("粘贴 CSGO- 开头的分享码")
        self.sharecode_edit.setToolTip(
            "导入只换样式、颜色、粗细、长度、间隙、描边和中心点；"
            "游戏里在「准星 → 分享或导入」粘贴导出的码。")
        self.sharecode_edit.setClearButtonEnabled(True)
        self.sharecode_edit.returnPressed.connect(self._import_sharecode)
        row.addWidget(self.sharecode_edit, 1)
        import_btn = QPushButton("导入")
        style_as_secondary_button(import_btn)
        import_btn.clicked.connect(self._import_sharecode)
        row.addWidget(import_btn)
        layout.addLayout(row)
        export_btn = QPushButton("复制分享码")
        export_btn.setToolTip("把当前准心转成 CS2 分享码，复制到剪贴板。")
        style_as_secondary_button(export_btn)
        export_btn.clicked.connect(self._export_sharecode)
        layout.addWidget(export_btn)
        self.sharecode_result_label = QLabel("")
        self.sharecode_result_label.setObjectName("hintLabel")
        self.sharecode_result_label.setWordWrap(True)
        self.sharecode_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sharecode_result_label.hide()
        layout.addWidget(self.sharecode_result_label)

    def _show_sharecode_result(self, text):
        self.sharecode_result_label.setText(text)
        self.sharecode_result_label.show()

    def _add_custom_section(self, layout):
        """自己画的准心和导入导出。全页唯一的紫按钮是「绘制准心」（RN-139/RN-186）。"""
        self.draw_button = QPushButton("绘制准心")
        self.draw_button.setToolTip("画完会自动切到「自定义」样式")
        self.draw_button.clicked.connect(self._open_custom_editor)
        self.action_bar = PageActionBar(None, inline=True)
        self.action_bar.adopt_button(self.draw_button, primary=True)
        style_as_primary_button(self.draw_button)
        # 批 160：三颗挤一排会把栏撑宽、预览挤出页面，主按钮独占一行；没有同排按钮撑高度，摘掉 fp_short 免得被压成 23px
        self.draw_button.setProperty("fp_short", False)
        layout.addWidget(self.draw_button)
        layout.addWidget(self.action_bar)

        self.custom_summary_label = QLabel("")
        self.custom_summary_label.setObjectName("hintLabel")
        self.custom_summary_label.setWordWrap(True)
        self.custom_summary_label.hide()
        layout.addWidget(self.custom_summary_label)

    @staticmethod
    def _screen_height_px() -> int:
        """游戏所在屏（取主屏）的物理像素高：分享码按出码屏高等比缩放时要用。"""
        from PySide6.QtGui import QGuiApplication

        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return 0
        return int(round(scr.size().height() * scr.devicePixelRatio()))

    def _import_sharecode(self):
        import core.crosshair_sharecode as cs

        code = self.sharecode_edit.text().strip()
        try:
            values, notes = cs.to_cs2customizer(code, self._screen_height_px())
        except cs.ShareCodeError as e:
            self._show_sharecode_result(f"⚠️ 没导入：{e}")
            return
        for key, value in values.items():
            setattr(config, key, value)
        config.save_config()
        for button in self.style_group.buttons():
            if button.property("style_value") == values["crosshair_style"]:
                button.setChecked(True)
                break
        self.load_settings()
        self._update_crosshair_system()
        self._update_preview()
        self._sync_overview_status()
        tail = ("；" + "；".join(notes)) if notes else ""
        self._show_sharecode_result(
            f"✓ 已导入：{self._format_style_text(values['crosshair_style'])} · {values['crosshair_color_custom']} · "
            f"粗 {values['crosshair_thickness']} · 间隙 {values['crosshair_gap']} · 全长 {values['crosshair_size']}{tail}")
        self.logger.info(f"准心分享码已导入: {code} → {values}；{notes}")

    def _export_sharecode(self):
        from PySide6.QtGui import QGuiApplication

        import core.crosshair_sharecode as cs

        try:
            code = cs.from_cs2customizer(config, self._screen_height_px())
        except cs.ShareCodeError as e:
            self._show_sharecode_result(f"⚠️ 没导出：{e}")
            return
        QGuiApplication.clipboard().setText(code)
        self.sharecode_edit.setText(code)
        self._show_sharecode_result(
            f"✓ 已复制到剪贴板：{code}（游戏里在「准星 → 分享或导入」粘贴）")

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

    #: RN-415：`_paint_custom` 画的是一张 30×30 的像素画，**没有"中心间隙"这个概念**
    #: —— 图案自己就带着它的空隙。实测（改两个值比像素）：自定义样式下
    #: `size` / `thickness` / `outline` / `alpha` 四条都改得动画面，
    #: **只有 `gap` 一个像素都不动**。
    #: ⚠ 不能反过来"让 gap 对自定义生效"：那要去改用户手画的图案，
    #:   而 `_paint_custom` 的 docstring 明写着换算方式不许动
    #:   （「否则用户存量的自定义图案会整体缩放变形」）。
    #: ⇒ 只在自定义样式下把它禁掉，并且**说出为什么**。
    STYLE_DEAD_SLIDERS = {"custom": ("gap_slider",)}

    #: 那几条被禁掉时该说的话。⚠ 原来的 tooltip 是「准星中心留空多少像素。
    #: 0 表示两条线穿过圆心，会挡住瞄准点。」—— 在自定义样式下**那是假的**。
    #: ⭐ 一句只在某些状态下为真的说明，在别的状态里就是一句谎（RN-407 原话）。
    DEAD_SLIDER_REASON = {
        "gap_slider": "自定义准心是你自己画的图案，中心间隙由图案本身决定 ——"
                      "这条滑块只对「十字 / T 型」这类内置样式有用。",
    }

    def _on_preview_clicked(self, event):
        """预览框被点了。⚠ **只有它此刻真的是入口时才响应。**

        ⭐ 反过来的守卫和正面一样重要：一个"有时候能点、有时候不能点、
        而外观从不变化"的东西，比一个从来不能点的还糟
        （批 26 那条的另一面）。所以可点与否**只由 `_preview_is_entry` 说了算**，
        而它和外观（手型光标 + 那句「点这里开始画」）由同一处同时设置。
        """
        from PySide6.QtCore import Qt as _Qt

        if not self._preview_is_entry:
            return
        if event is not None and event.button() != _Qt.LeftButton:
            return
        self._open_custom_editor()

    def _sync_preview_entry(self):
        """预览框此刻是不是「点这里开始画」的入口 —— 外观与行为一起切。"""
        from PySide6.QtCore import Qt as _Qt

        is_entry = bool(self._custom_style_is_blank())
        self._preview_is_entry = is_entry
        if not hasattr(self, "preview_frame"):
            return
        self.preview_frame.setCursor(
            _Qt.PointingHandCursor if is_entry else _Qt.ArrowCursor)
        self.preview_frame.setProperty("clickable", "true" if is_entry else None)
        self.preview_frame.setToolTip(
            "点这里打开绘制板，画一个自己的准心" if is_entry else "")
        for widget in (self.preview_frame, self.preview_label):
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)

    def _sync_slider_availability(self):
        """让「改不动画面的滑块」在那个样式下**看得出来改不动**。

        ⭐ 这是 RN-145 / RN-439 那一族的第三次现身：
        **门禁条件要跟着含义走** —— 这里含义由**样式**决定，不由控件决定。
        ⚠ 禁用而不是藏掉：藏掉的话用户下次切回十字会发现「刚才那条滑块呢」，
          而且**藏起来的东西不会解释自己为什么不在**（RN-197 那条规矩）。
        """
        style_value = str(getattr(config, "crosshair_style", "") or "")
        dead = set(self.STYLE_DEAD_SLIDERS.get(style_value, ()))
        for attr in {name for names in self.STYLE_DEAD_SLIDERS.values()
                     for name in names}:
            slider = getattr(self, attr, None)
            if slider is None:
                continue
            is_dead = attr in dead
            slider.setEnabled(not is_dead)
            if is_dead:
                slider.setToolTip(self.DEAD_SLIDER_REASON.get(attr, ""))
            elif attr in self._original_slider_tips:
                slider.setToolTip(self._original_slider_tips[attr])

    def _on_style_changed(self, style_value):
        """准心样式改变"""
        config.crosshair_style = style_value
        config.save_config()
        self._update_preview()
        self._update_crosshair_system()
        self._sync_overview_status()
        # RN-415：样式换了，「哪几条滑块还说得上话」也跟着换。
        self._sync_slider_availability()
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
                alpha=max(0, min(255, int((255 if getattr(config, "crosshair_alpha", None) is None else config.crosshair_alpha)))),
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
                # ⭐ RN-414（批 27）：这块框现在**就是入口**，所以第三行要把
                # 「点这里」说出来 —— 手型光标只有把鼠标移过去才看得到，
                # 而实测的困惑发生在**还没移过去**的时候（3/3「不知道」）。
                self.preview_label.setText(
                    "还没画过自定义准心\n游戏里不会显示准心\n\n点这里开始画")
            else:
                self.preview_label.setText("")
                pixmap = QPixmap.fromImage(image)
                pixmap.setDevicePixelRatio(dpr)
                self.preview_label.setPixmap(pixmap)
            self._sync_preview_entry()

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

            # ⛔ 已经是「自定义」时 setChecked 不发 toggled ⇒ 游戏里还是旧图案。直接推一次。断点 `--only SWEEP`。
            self._update_crosshair_system()
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
            previous = config.crosshair_custom_data, config.crosshair_style
            config.crosshair_custom_data = cleaned["crosshair_custom_data"]
            config.crosshair_style = "custom"
            if config.save_config_now() is False:
                config.crosshair_custom_data, config.crosshair_style = previous
                raise OSError("准心配置保存失败")
            
            # 切换到自定义准心样式
            for button in self.style_group.buttons():
                if button.property("style_value") == "custom":
                    button.setChecked(True)
                    break

            self._update_crosshair_system()   # 同上：已是「自定义」时不会经信号推
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
        """加载设置，不把控件显示精度写回配置。"""
        from widgets.config_reload import block_control_signals
        with block_control_signals(self):
            self._load_settings_values()

    def _load_settings_values(self):
        # 加载大小和粗细
        self.size_slider.setValue(config.crosshair_size)
        self.thickness_slider.setValue(config.crosshair_thickness)
        self.gap_slider.setValue(int(getattr(config, "crosshair_gap", 0) or 0))
        self.outline_slider.setValue(int(getattr(config, "crosshair_outline", 0) or 0))
        self.alpha_slider.setValue(
            max(0, int((255 if getattr(config, "crosshair_alpha", None) is None else config.crosshair_alpha)) * 100 // 255)
        )
        self.dot_checkbox.setChecked(bool(getattr(config, "crosshair_dot", False)))
        self._sync_custom_color_button()
        
        for name in ("size", "thickness", "gap", "outline"):
            getattr(self, f"{name}_value_label").setText(str(getattr(config, f"crosshair_{name}")))
        self.alpha_value_label.setText(f"{self.alpha_slider.value()}%")
        for group, key, prop in ((self.style_group, "crosshair_style", "style_value"),
                                 (self.color_group, "crosshair_color", "color_value")):
            for button in group.buttons():
                button.setChecked(button.property(prop) == getattr(config, key))
        
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
        self._sync_slider_availability()
