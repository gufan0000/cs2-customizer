"""
统一帮助面板组件
每个页面标题旁的 "?" 按钮 + 可折叠帮助卡片
"""

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QScrollArea
)
from PySide6.QtGui import QFont
from theme_manager import get_theme_manager


class HelpButton(QPushButton):
    """圆形 "?" 帮助按钮 (24x24)"""

    def __init__(self, parent=None):
        super().__init__("?", parent)
        self.setObjectName("helpButton")
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("查看帮助")
        self._tm = get_theme_manager()
        self._apply_style()
        self._tm.register_theme_changed_callback(self._apply_style)

    def _apply_style(self):
        c = self._tm.current_theme.colors
        self.setStyleSheet(f"""
            QPushButton#helpButton {{
                background: transparent;
                color: {c.accent_primary};
                border: 1.5px solid {c.accent_primary};
                border-radius: 12px;
                font-size: 13px;
                font-weight: 700;
                padding: 0px;
            }}
            QPushButton#helpButton:hover {{
                background: {c.accent_primary};
                color: white;
            }}
        """)

    def deleteLater(self):
        try:
            self._tm.unregister_theme_changed_callback(self._apply_style)
        except Exception:
            pass
        super().deleteLater()


class HelpPanel(QWidget):
    """可折叠帮助卡片，固定高度 + 内部滚动"""

    EXPAND_DURATION = 200
    COLLAPSE_DURATION = 150
    PANEL_HEIGHT = 280

    def __init__(self, help_text: str, parent=None):
        super().__init__(parent)
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)

        # 卡片
        self._card = QFrame()
        self._card.setObjectName("helpCard")
        self._card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(16, 10, 12, 10)
        card_layout.setSpacing(6)

        # 标题行：帮助 + ×
        top_row = QHBoxLayout()
        title = QLabel("帮助")
        title.setObjectName("helpCardTitle")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        top_row.addWidget(title)
        top_row.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("helpCloseButton")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.collapse)
        top_row.addWidget(close_btn)
        card_layout.addLayout(top_row)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setObjectName("helpScrollArea")

        content = QLabel(help_text)
        content.setObjectName("helpContent")
        content.setWordWrap(True)
        content.setTextFormat(Qt.RichText)
        content.setFont(QFont("Microsoft YaHei", 13))
        content.setContentsMargins(0, 4, 8, 4)
        scroll.setWidget(content)

        card_layout.addWidget(scroll, 1)

        outer.addWidget(self._card)

        # 动画
        self._anim = QPropertyAnimation(self, b"maximumHeight")
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        # 初始隐藏
        self.setMaximumHeight(0)
        self._card.setVisible(False)

    # PLACEHOLDER_METHODS

    def toggle(self):
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        if self._expanded:
            return
        self._expanded = True
        self._card.setVisible(True)

        self._anim.stop()
        self._anim.setDuration(self.EXPAND_DURATION)
        self._anim.setStartValue(0)
        self._anim.setEndValue(self.PANEL_HEIGHT)
        self._anim.start()

    def collapse(self):
        if not self._expanded:
            return
        self._expanded = False
        self._anim.stop()
        self._anim.setDuration(self.COLLAPSE_DURATION)
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(0)
        self._anim.finished.connect(self._on_collapsed)
        self._anim.start()

    def _on_collapsed(self):
        try:
            self._anim.finished.disconnect(self._on_collapsed)
        except Exception:
            pass
        self._card.setVisible(False)


def install_help_panel(header_layout, parent_layout, help_text, insert_after_index=None):
    """
    在标题行插入 "?" 按钮，在标题行下方插入帮助面板。

    header_layout: 标题所在的 QHBoxLayout
    parent_layout: 标题行的父 QVBoxLayout（帮助面板插入到这里）
    help_text: HTML 帮助文本
    insert_after_index: 帮助面板在 parent_layout 中的插入位置（None=自动检测）
    """
    btn = HelpButton()
    # 在 stretch 之前插入按钮
    stretch_idx = None
    for i in range(header_layout.count()):
        item = header_layout.itemAt(i)
        if item.spacerItem():
            stretch_idx = i
            break
    if stretch_idx is not None:
        header_layout.insertWidget(stretch_idx + 1, btn)
    else:
        header_layout.addWidget(btn)

    panel = HelpPanel(help_text)
    btn.clicked.connect(panel.toggle)

    # 找到 header_layout 在 parent_layout 中的位置
    if insert_after_index is not None:
        idx = insert_after_index
    else:
        idx = 0
        for i in range(parent_layout.count()):
            item = parent_layout.itemAt(i)
            if item.layout() is header_layout:
                idx = i + 1
                break
            elif item.widget() and item.layout() is header_layout:
                idx = i + 1
                break
        else:
            idx = 1  # fallback: 插在第二个位置

    parent_layout.insertWidget(idx, panel)
    return btn, panel


# ========== 各页面帮助文本 ==========

PAGE_HELP_TEXTS = {
    "basic": (
        "<b>功能说明</b><br>"
        "基础设置页面是所有功能的总控中心，包含全局开关和音量控制。<br><br>"
        "<b>使用方法</b><br>"
        "1. 打开对应功能的开关以启用该功能<br>"
        "2. 拖动音量滑块调整各功能的独立音量<br>"
        "3. 右上角可切换应用主题（深色/浅色/自定义）<br>"
        "4. 所有开关和音量设置会自动保存<br><br>"
        "<b>注意事项</b><br>"
        "• 部分功能需要先在「高级设置」中配置 CS2 目录才能正常工作<br>"
        "• 音效类功能需要 GSI 服务正常运行（软件启动时自动配置）<br>"
        "• 关闭总开关会同时停止该功能的所有音效播放"
    ),
    "kill_sound": (
        "<b>功能说明</b><br>"
        "击杀音效会在击杀敌人时播放自定义音效，支持按武器类别和连杀数分别配置不同风格。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「击杀音效」开关<br>"
        "2. 切换到对应武器类别选项卡（步枪、手枪、冲锋枪等）<br>"
        "3. 为每把武器选择音效风格，下拉菜单中显示所有可用风格<br>"
        "4. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效</b><br>"
        "1. 打开目录 <code>AppData/Local/CS2Customizer/resources/audio/kill_sounds/</code><br>"
        "2. 在对应武器文件夹中创建自定义风格文件夹<br>"
        "3. 放入 MP3/WAV/OGG 格式的音频文件（按击杀数命名：1、2 ...）<br>"
        "4. 文件夹名称会自动显示在下拉菜单中"
    ),
    "kill_voice": (
        "<b>功能说明</b><br>"
        "击杀语音会在击杀敌人时播放语音播报，支持连杀递进效果（如 Double Kill、Triple Kill）。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「击杀语音」开关<br>"
        "2. 切换到对应武器类别选项卡<br>"
        "3. 为每把武器选择语音风格<br>"
        "4. 点击「测试」按钮可预听当前选择的语音<br><br>"
        "<b>自定义语音</b><br>"
        "1. 打开目录 <code>AppData/Local/CS2Customizer/resources/audio/kill_voices/</code><br>"
        "2. 在对应武器文件夹中创建自定义风格文件夹<br>"
        "3. 放入 MP3/WAV/OGG 格式的音频文件（按击杀数命名：1、2 ...）<br>"
        "4. 文件夹名称会自动显示在下拉菜单中"
    ),
    "kill_icon": (
        "<b>功能说明</b><br>"
        "击杀图标会在击杀敌人时在屏幕上显示动画效果，仅支持 Sprite Sheet（精灵图）格式。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「击杀图标」开关<br>"
        "2. 选择一个图标风格<br>"
        "3. 调整图标大小、显示位置和 FPS 播放速度<br>"
        "4. 点击「预览」查看动画效果<br><br>"
        "<b>格式要求</b><br>"
        "• 仅支持 Sprite Sheet 格式（单张图片包含所有动画帧）<br>"
        "• 每个击杀数需要独立的精灵图和配置文件（如 1.png + 1.json）<br>"
        "• JSON 配置文件中包含帧数、FPS 等播放参数<br><br>"
        "<b>自定义图标</b><br>"
        "1. 在 <code>AppData/Local/CS2Customizer/resources/kill_icons/</code> 创建风格文件夹<br>"
        "2. 使用页面底部的「Sprite Sheet 制作工具」将 PNG 序列帧合并为精灵图<br>"
        "3. 工具会自动生成 .png + .json 配置文件<br>"
        "4. FPS 设置修改后需点击保存按钮才会更新配置文件"
    ),
    "crosshair": (
        "<b>功能说明</b><br>"
        "准心功能为游戏提供覆盖式自定义准心，叠加在游戏画面上方，不影响游戏内的鼠标操作。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「自定义准心」开关<br>"
        "2. 选择准心形状（十字、圆点、圆环等）<br>"
        "3. 调整准心的颜色、大小、粗细等参数<br>"
        "4. 可选开启动画效果（如击杀时的缩放动画）<br>"
        "5. 所有设置实时生效，准心会立即显示在屏幕中央<br><br>"
        "<b>注意事项</b><br>"
        "• 准心为屏幕覆盖层，不会被游戏检测<br>"
        "• 设置会自动保存，下次启动时自动恢复"
    ),
    "death_sound": (
        "<b>功能说明</b><br>"
        "被击杀音效会在玩家被击杀时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「被击杀音效」开关<br>"
        "2. 从下拉菜单选择音效风格<br>"
        "3. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效</b><br>"
        "1. 打开目录 <code>AppData/Local/CS2Customizer/resources/audio/death/</code><br>"
        "2. 创建自定义风格文件夹，放入 MP3/WAV/OGG 格式的音频文件<br>"
        "3. 文件夹名称会自动显示在下拉菜单中"
    ),
    "gun_sound": (
        "<b>功能说明</b><br>"
        "枪声替换功能会在检测到开火后，短暂压制原始枪声并播放自定义音效，尽量保留射击反馈。当前仅开放半自动/单发武器：手枪、狙击枪、霰弹枪、宙斯；自动武器暂未开放。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「枪声替换」开关<br>"
        "2. 进入对应武器选项卡，为每把武器单独选择「枪声风格」；保持“不启用”则不会替换<br>"
        "3. 调整「原声音量保留」决定替换时保留多少原始枪声，默认 18%<br>"
        "4. 调整「静音覆盖时长」控制对原始枪声的压制窗口；数值越长覆盖越彻底<br>"
        "5. 点击「测试」按钮预听当前武器的替换效果，再按实际手感微调<br><br>"
        "<b>调校建议</b><br>"
        "• 单发/慢射速武器通常可以适当增加静音覆盖时长<br>"
        "• 节奏更快的手枪建议适当缩短静音覆盖时长，避免连续开火时糊成一片<br>"
        "• 如果想保留更多原枪声质感，可以适当提高「原声音量保留」<br><br>"
        "<b>自定义枪声</b><br>"
        "1. 打开目录 <code>AppData/Local/CS2Customizer/resources/audio/gun_sounds/</code><br>"
        "2. 在对应武器文件夹中创建自定义风格文件夹<br>"
        "3. 放入 MP3/WAV/OGG 格式的音频文件<br>"
        "4. 文件夹名称会自动显示在下拉菜单中"
    ),
    "switch_weapon": (
        "<b>功能说明</b><br>"
        "切枪音效会在切换武器时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「切枪音效」开关<br>"
        "2. 为每把武器选择切枪音效风格<br>"
        "3. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效</b><br>"
        "1. 打开目录 <code>AppData/Local/CS2Customizer/resources/audio/switch_weapons/</code><br>"
        "2. 创建自定义风格文件夹，放入 MP3/WAV/OGG 格式的音频文件<br>"
        "3. 文件夹名称会自动显示在下拉菜单中"
    ),
    "reload_sound": (
        "<b>功能说明</b><br>"
        "换弹音效会在武器换弹时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「换弹音效」开关<br>"
        "2. 为每把武器选择换弹音效风格<br>"
        "3. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效</b><br>"
        "1. 打开目录 <code>AppData/Local/CS2Customizer/resources/audio/reload_sounds/</code><br>"
        "2. 创建自定义风格文件夹，放入 MP3/WAV/OGG 格式的音频文件<br>"
        "3. 文件夹名称会自动显示在下拉菜单中"
    ),
    "special_sound": (
        "<b>功能说明</b><br>"
        "特殊音效包含四类自定义音效，分别在不同的选项卡中配置：<br>"
        "• <b>投掷物音效</b> — 投掷手雷/闪光/烟雾等道具时播放<br>"
        "• <b>C4音效</b> — 安装C4炸弹时播放<br>"
        "• <b>血量警告</b> — 血量首次降到设定阈值以下时播放警告音<br>"
        "• <b>回合音效</b> — 回合开始/行动开始/胜利/失败/MVP 时播放<br><br>"
        "<b>使用方法</b><br>"
        "1. 切换到对应音效类别的选项卡<br>"
        "2. 启用该类别的开关<br>"
"3. 为每个事件选择音效风格<br>"
        "4. 点击「测试」按钮预听效果<br><br>"
        "<b>自定义音效</b><br>"
        "各类音效的自定义目录均在 <code>AppData/Local/CS2Customizer/resources/audio/</code> 下：<br>"
        "• 投掷物：<code>grenade_sounds/投掷物类型/风格名/throw.mp3</code><br>"
        "• C4：<code>c4_sounds/风格名/planted.mp3</code><br>"
        "• 血量警告：<code>health_warning/风格名/warning.mp3</code><br>"
        "• 回合音效：<code>round_start/风格名/start.mp3</code>（其他类似）<br>"
        "创建风格文件夹并放入 MP3/WAV/OGG 文件，文件夹名称会自动显示在下拉菜单中。"
    ),
    "viewmodel": (
        "<b>功能说明</b><br>"
        "局内视角设置可以配置持枪视角预设（FOV、位置偏移）和准心快速回正功能，通过 CFG 文件写入游戏配置生效。<br><br>"
        "<b>持枪视角预设</b><br>"
        "1. 设置多组视角预设，每组可调整 FOV、X/Y/Z 偏移量<br>"
        "2. 为每组预设绑定快捷键，游戏内按键即可切换<br>"
        "3. 设置循环切换按键（默认 CAPSLOCK），可在所有预设间循环<br><br>"
        "<b>准心快速回正</b><br>"
        "开启后，按下开火键时准心跟随后坐力（cl_crosshair_recoil 1），松开时瞬间回正（设为 0），无曲线动画。<br><br>"
        "<b>保存与生效</b><br>"
        "1. 调整完参数后点击「保存设置到CFG」按钮<br>"
        "2. CFG 文件会写入 CS2 目录下的 <code>game/csgo/cfg/cs2customizer.cfg</code><br>"
        "3. 游戏内打开控制台输入 <code>exec cs2customizer.cfg</code> 加载配置<br>"
        "4. 也可将 exec 命令写入 autoexec.cfg 实现自动加载"
    ),
    "magnifier": (
        "<b>功能说明</b><br>"
        "开镜放大功能会在使用狙击枪开镜时放大屏幕中心区域，模拟更高倍率的瞄准镜效果。也支持联动局内灵敏度，在放大激活时切到更低倍率的手感。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「开镜放大」开关<br>"
        "2. 调整放大倍率（越大放大越明显）<br>"
        "3. 可选启用「开镜灵敏度联动」，填写你在 CS2 中的基础 sensitivity 和开镜倍率<br>"
        "4. 调整放大区域大小<br>"
        "5. 选择触发的武器类型（AWP、Scout 等）<br><br>"
        "<b>注意事项</b><br>"
        "• 此功能需要以管理员身份运行程序<br>"
        "• 放大效果为屏幕覆盖层，不修改游戏文件<br>"
        "• 开镜/关镜状态通过 GSI 自动检测<br>"
        "• 灵敏度联动会写入 <code>cs2customizer.cfg</code> 和 <code>cs2customizer_magnifier_runtime.cfg</code><br>"
        "• 当前游戏会话首次启用灵敏度联动时，如未生效，请在控制台执行一次 <code>exec cs2customizer.cfg</code>"
    ),
    "flash": (
        "<b>功能说明</b><br>"
        "自定闪光功能可以替代游戏默认的闪白效果，支持自定义颜色、图片叠加和音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「自定闪光」开关<br>"
        "2. 在「基础」选项卡调整闪光颜色、透明度和持续时间<br>"
        "3. 在「风格」选项卡选择闪光样式或自定义图片<br>"
        "4. 可选添加自定义闪光音效<br>"
        "5. 在「预览」选项卡调整预览强度和持续时间，点击按钮测试效果<br><br>"
        "<b>自定义素材</b><br>"
        "• 闪光图片：支持 PNG/JPG 格式，放入 <code>AppData/Local/CS2Customizer/resources/flash_images/</code> 目录<br>"
        "• 闪光音效：支持 MP3/WAV/OGG 格式，放入 <code>AppData/Local/CS2Customizer/resources/flash_audio/</code> 目录"
    ),
    "music": (
        "<b>功能说明</b><br>"
        "音乐播放器支持本地音乐文件和在线 URL。底部控制栏负责手动播放；“音乐联动”开关只控制游戏是否自动接管音乐。<br><br>"
        "<b>使用方法</b><br>"
        "1. 点击添加按钮导入本地音乐文件或粘贴在线 URL<br>"
        "2. 使用底部控制栏播放、暂停、切换曲目<br>"
        "3. 调整音量滑块控制播放音量<br>"
        "4. 选择播放模式（顺序播放/随机播放/单曲循环/列表循环）<br><br>"
        "<b>游戏联动</b><br>"
        "开启“音乐联动”后，玩家死亡时可自动开始/继续播放，存活时可自动暂停或降低音量；关闭后仍可手动播放，但游戏状态不会再自动影响音乐。"
    ),
    "voice_output": (
        "<b>功能说明</b><br>"
        "语音输出页面包含三个功能模块：<br>"
        "• <b>语音输出</b> — 将文字转为语音通过虚拟声卡输出到游戏内语音<br>"
        "• <b>音板</b> — 绑定快捷键快速播放预设音频到游戏语音<br>"
        "• <b>音效转发</b> — 将击杀音效等转发到游戏语音让队友听到<br><br>"
        "<b>前置准备</b><br>"
        "1. 安装 VB-Cable 虚拟声卡驱动（页面内提供安装按钮）<br>"
        "2. 在 CS2 设置中将麦克风设为「CABLE Output (VB-Audio Virtual Cable)」<br><br>"
        "<b>语音输出</b><br>"
        "输入文字后按快捷键即可将语音输出到游戏内。<br><br>"
        "<b>音板</b><br>"
        "为每个槽位设置音频文件和快捷键，游戏中按键即可播放。<br><br>"
        "<b>音效转发</b><br>"
        "开启后，勾选需要转发的音效类型，队友即可通过语音听到你的击杀音效等。建议在「覆盖」或「自动」模式下使用，「混音」模式可能有回声。"
    ),
    "utility": (
        "<b>功能说明</b><br>"
        "道具瞄点功能提供游戏内覆盖层，帮助学习 CS2 道具投掷点位，自动根据阵营显示对应道具。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「道具瞄点」开关<br>"
        "2. 设置快捷键和显示模式（长按显示 / 切换显示）<br>"
        "3. 进入游戏后按快捷键打开菜单<br>"
        "4. 用数字键 1-9 选择道具，数字键 0 返回上级，ESC 关闭<br><br>"
        "<b>文件夹结构</b><br>"
        "道具图片存放在 <code>resources/utility_guides/</code> 下：<br>"
        "<code>地图名/T或CT/分类名/道具名_站位.jpg + 道具名_瞄准.jpg</code><br>"
        "例如：<code>de_dust2/T/A点进攻/Xbox烟_站位.jpg</code><br><br>"
        "<b>自定义道具</b><br>"
        "1. 在对应地图的 T 或 CT 文件夹下创建分类文件夹<br>"
        "2. 添加成对的图片（站位图 + 瞄准图），命名格式为「道具名_站位」和「道具名_瞄准」<br>"
        "3. 支持 JPG/PNG 格式，点击「刷新道具列表」即可加载"
    ),
    "hud_color": (
        "<b>功能说明</b><br>"
        "HUD 颜色规则让你的 HUD 根据游戏事件自动变色。选一个预设方案，开关你想要的事件即可。<br><br>"
        "<b>数字键颜色（纯 CFG）</b><br>"
        "数字键 1-9 的颜色映射写入 cs2customizer.cfg，软件关闭时仍可用。<br>"
        "游戏中按数字键切换武器时会同时切换 HUD 颜色。<br><br>"
        "<b>事件响应（需软件）</b><br>"
        "击杀、爆头、连杀、被击杀、低血量等事件由软件通过 GSI 实时检测并变色。<br>"
        "WASD 移动键会自动加载颜色变化，只要你在移动就会实时刷新。<br><br>"
        "<b>预设方案</b><br>"
        "• <b>平衡默认</b> — 适合大多数玩家<br>"
        "• <b>竞技简洁</b> — 减少视觉干扰，效果简洁<br>"
        "• <b>炫彩增强</b> — 丰富的闪烁和脉冲效果<br>"
        "• <b>纯击杀</b> — 只响应击杀/爆头/连杀<br>"
        "• <b>战术信息</b> — 侧重低血量、炸弹、回合状态<br><br>"
        "<b>保存与生效</b><br>"
        "1. 点击「保存 HUD 规则」<br>"
        "2. 游戏内输入 <code>exec cs2customizer.cfg</code><br>"
        "3. 运行软件后事件响应自动生效"
    ),
    "advanced": (
        "<b>功能说明</b><br>"
        "高级设置包含 CS2 目录配置、GSI 服务器状态监控和其他系统级选项。<br><br>"
        "<b>CS2 目录设置</b><br>"
        "首次使用必须设置 CS2 安装目录，软件会自动在 <code>game/csgo/cfg/</code> 下生成 GSI 配置文件。<br><br>"
        "<b>GSI 状态</b><br>"
        "GSI（Game State Integration）是 CS2 提供的游戏状态接口，软件通过它获取击杀、死亡、武器切换等事件。状态显示为绿色表示正常运行。<br><br>"
        "<b>注意事项</b><br>"
        "• 修改 CS2 目录后需要重启软件<br>"
        "• 如果 GSI 状态异常，检查 CS2 目录是否正确并确认游戏已启动"
    ),
}

# 2026-03 帮助文案统一校准：
# 1. 资源类功能写清实际目录结构
# 2. CFG / GSI 类功能写清自动生成位置
# 3. 无需手动放文件的功能明确说明“无需额外放文件”
PAGE_HELP_TEXTS.update({
    "basic": (
        "<b>功能说明</b><br>"
        "基础设置页面是所有功能的总控中心，负责开关、音量和主题等全局项。<br><br>"
        "<b>使用方法</b><br>"
        "1. 打开对应功能的开关以启用该功能<br>"
        "2. 拖动音量滑块调整各功能的独立音量<br>"
        "3. 右上角可切换应用主题（深色 / 浅色 / 自定义）<br>"
        "4. 所有开关和音量设置会自动保存<br><br>"
        "<b>文件与配置位置</b><br>"
        "1. 本页无需手动放资源文件。<br>"
        "2. 基础开关、音量、主题等设置保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "3. 音效、图片、图标等素材统一放在 <code>AppData/Local/CS2Customizer/resources/</code> 下，具体子目录请看各功能页右上角问号说明。<br><br>"
        "<b>注意事项</b><br>"
        "• 部分功能需要先在「高级设置」中配置 CS2 目录才能正常工作<br>"
        "• 音效类功能需要 GSI 服务正常运行（软件启动时自动配置）<br>"
        "• 关闭总开关会同时停止该功能的所有音效播放"
    ),
    "advanced": (
        "<b>功能说明</b><br>"
        "高级设置包含 CS2 目录配置、GSI 服务状态监控和其他系统级选项。<br><br>"
        "<b>CS2 目录设置</b><br>"
        "首次使用必须设置 CS2 安装目录，软件会基于这个路径自动补齐游戏侧配置。<br><br>"
        "<b>文件与配置位置</b><br>"
        "1. 本页无需手动放素材文件。<br>"
        "2. 你选择的 CS2 目录会写入 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "3. 软件会自动在 <code>CS2/game/csgo/cfg/gamestate_integration_cs2customizer.cfg</code> 生成或更新 GSI 配置文件。<br>"
        "4. 其他需要写入游戏的功能（如视角、HUD、灵敏度联动）会在同一目录下生成 <code>cs2customizer.cfg</code> 等文件。<br><br>"
        "<b>GSI 状态</b><br>"
        "GSI（Game State Integration）是 CS2 提供的游戏状态接口，软件通过它获取击杀、死亡、武器切换等事件。状态显示为绿色表示正常运行。<br><br>"
        "<b>注意事项</b><br>"
        "• 修改 CS2 目录后建议重启软件<br>"
        "• 如果 GSI 状态异常，先检查 CS2 目录是否正确，再确认游戏是否已启动"
    ),
    "crosshair": (
        "<b>功能说明</b><br>"
        "准心功能为游戏提供覆盖式自定义准心，叠加在游戏画面上方，不影响游戏内的鼠标操作。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「自定义准心」开关<br>"
        "2. 选择准心形状（十字、圆点、圆环等）<br>"
        "3. 调整准心的颜色、大小、粗细等参数<br>"
        "4. 可选开启动画效果（如击杀时的缩放动画）<br>"
        "5. 所有设置实时生效，准心会立即显示在屏幕中央<br><br>"
        "<b>文件与配置位置</b><br>"
        "1. 常规准心样式无需额外放文件，直接调参数即可。<br>"
        "2. 自定义准心导入 / 导出的默认目录为 <code>AppData/Local/CS2Customizer/resources/crosshair/</code>。<br>"
        "3. 导出的文件格式为 <code>.xchr</code>；导入成功后会写回 <code>AppData/Local/CS2Customizer/config.json</code>。<br><br>"
        "<b>注意事项</b><br>"
        "• 准心为屏幕覆盖层，不会被游戏检测<br>"
        "• 如果只是本机使用，不导入 / 导出文件也完全可以"
    ),
    "kill_sound": (
        "<b>功能说明</b><br>"
        "击杀音效会在击杀敌人时播放自定义音效，支持通用风格和武器专属风格两套资源结构。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「击杀音效」开关<br>"
        "2. 切换到对应武器类别选项卡（步枪、手枪、冲锋枪等）<br>"
        "3. 为每把武器选择音效风格，下拉菜单中会合并显示通用风格和武器专属风格<br>"
        "4. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效目录</b><br>"
        "1. 通用连杀风格放在 <code>AppData/Local/CS2Customizer/resources/audio/kill_sounds/风格名/</code><br>"
        "2. 武器专属风格放在 <code>AppData/Local/CS2Customizer/resources/audio/weapon_kill_sounds/武器名/风格名/</code><br>"
        "3. 目录内建议按击杀数命名：<code>1~5</code>，爆头可用 <code>1-headshot</code> 这类文件名；支持 MP3/WAV/OGG<br>"
        "4. 放完后点击页面里的「刷新风格列表」，武器专属目录会优先覆盖对应武器"
    ),
    "kill_voice": (
        "<b>功能说明</b><br>"
        "击杀语音会在击杀敌人时播放语音播报，支持通用风格和武器专属风格。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「击杀语音」开关<br>"
        "2. 切换到对应武器类别选项卡<br>"
        "3. 为每把武器选择语音风格<br>"
        "4. 点击「测试」按钮可预听当前选择的语音<br><br>"
        "<b>自定义语音目录</b><br>"
        "1. 通用语音风格放在 <code>AppData/Local/CS2Customizer/resources/audio/kill_voices/风格名/</code><br>"
        "2. 武器专属语音风格放在 <code>AppData/Local/CS2Customizer/resources/audio/weapon_kill_voices/武器名/风格名/</code><br>"
        "3. 目录内建议按击杀数命名：<code>1~5</code>，爆头可用 <code>1-headshot</code>；支持 MP3/WAV/OGG<br>"
        "4. 放完后点击「刷新风格列表」，同名武器专属风格会优先于通用风格"
    ),
    "kill_icon": (
        "<b>功能说明</b><br>"
        "击杀图标会在击杀敌人时在屏幕上显示动画效果，仅支持 Sprite Sheet（精灵图）格式。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「击杀图标」开关<br>"
        "2. 选择一个图标风格<br>"
        "3. 调整图标大小、显示位置和 FPS 播放速度<br>"
        "4. 点击「预览」查看动画效果<br><br>"
        "<b>格式要求与目录</b><br>"
        "1. 每套风格放在 <code>AppData/Local/CS2Customizer/resources/kill_icons/风格名/</code><br>"
        "2. 每个击杀数需要独立的精灵图和配置文件，例如 <code>1.png + 1.json</code>、<code>2.png + 2.json</code><br>"
        "3. JSON 配置文件中包含帧数、FPS 等播放参数<br>"
        "4. 也可以先用页面底部的「Sprite Sheet 制作工具」生成后再保存进对应风格目录"
    ),
    "death_sound": (
        "<b>功能说明</b><br>"
        "被击杀音效会在玩家被击杀时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「被击杀音效」开关<br>"
        "2. 从下拉菜单选择音效风格<br>"
        "3. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效目录</b><br>"
        "1. 被击杀音效使用扁平文件结构，不是风格文件夹。<br>"
        "2. 直接把文件放到 <code>AppData/Local/CS2Customizer/resources/audio/death/</code><br>"
        "3. 程序会按文件名识别风格，例如 <code>anime.mp3</code>、<code>impact.wav</code> 会显示成 anime / impact<br>"
        "4. 支持 MP3/WAV/OGG，新增后点击「刷新风格列表」即可"
    ),
    "gun_sound": (
        "<b>功能说明</b><br>"
        "枪声替换功能会在检测到开火后，短暂压制原始枪声并播放自定义音效，尽量保留射击反馈。<br>"
        "当前开放的是手枪、狙击枪、霰弹枪、宙斯电击枪等半自动 / 单发武器；连发武器（步枪、冲锋枪、机枪）暂未开放。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「枪声替换」开关<br>"
        "2. 进入对应武器选项卡，为每把武器单独选择「枪声风格」<br>"
        "3. 调整「原声保留」（原始枪声音量，默认 18%）和「静音覆盖时长」（压低原声的时长），用测试按钮试听<br><br>"
        "<b>调校建议</b><br>"
        "• 单发 / 慢射速武器（AWP、沙鹰）可适当增加「静音覆盖时长」，让自定义音更完整<br>"
        "• 手枪等快射速武器建议缩短覆盖时长，避免连续开火时声音糊成一片<br>"
        "• 想保留原枪声质感，可调高「原声保留」音量<br><br>"
        "<b>自定义枪声目录</b><br>"
        "1. 每把武器的目录结构为 <code>AppData/Local/CS2Customizer/resources/audio/gun_sounds/武器名/风格名/</code><br>"
        "2. 风格文件夹里放 1 个或多个 MP3/WAV/OGG 文件即可，程序会取可用音频进行测试和播放<br>"
        "3. 放完后点击「刷新风格列表」，对应武器页就会出现这个风格"
    ),
    "switch_weapon": (
        "<b>功能说明</b><br>"
        "切枪音效会在切换武器时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「切枪音效」开关<br>"
        "2. 为每把武器选择切枪音效风格<br>"
        "3. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效目录</b><br>"
        "1. 目录结构为 <code>AppData/Local/CS2Customizer/resources/audio/switch_weapons/武器名/风格名/</code><br>"
        "2. 风格文件夹里放 1 个或多个 MP3/WAV/OGG 文件即可<br>"
        "3. 放完后点击「刷新风格列表」，对应武器会显示新的风格"
    ),
    "reload_sound": (
        "<b>功能说明</b><br>"
        "换弹音效会在武器换弹时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「换弹音效」开关<br>"
        "2. 为每把武器选择换弹音效风格<br>"
        "3. 点击「测试」按钮可预听当前选择的音效<br><br>"
        "<b>自定义音效目录</b><br>"
        "1. 目录结构为 <code>AppData/Local/CS2Customizer/resources/audio/reload_sounds/武器名/风格名/</code><br>"
        "2. 风格文件夹里放 1 个或多个 MP3/WAV/OGG 文件即可<br>"
        "3. 放完后点击「刷新风格列表」，对应武器会显示新的风格"
    ),
    "special_sound": (
        "<b>功能说明</b><br>"
        "特殊音效包含投掷物、C4、血量警告和回合音效四类，各自在不同游戏事件时触发：<br>"
        "• 投掷物：投掷手雷 / 闪光弹 / 烟雾弹 / 燃烧弹时<br>"
        "• C4：安装炸弹（下包）时<br>"
        "• 血量警告：血量首次降到你设定的阈值以下时（低于阈值只提醒一次，回血后重置）<br>"
        "• 回合音效：回合开始、你所在队伍胜利 / 失败、以及你拿到 MVP 时<br><br>"
        "<b>使用方法</b><br>"
        "1. 切换到对应音效类别的选项卡<br>"
        "2. 启用该类别的开关<br>"
        "3. 为每个事件选择音效风格<br>"
        "4. 点击「测试」按钮预听效果<br><br>"
        "<b>自定义音效目录</b><br>"
        "所有目录都在 <code>AppData/Local/CS2Customizer/resources/audio/</code> 下：<br>"
        "• 投掷物：<code>grenade_sounds/投掷物类型/风格名/throw.mp3</code><br>"
        "• C4：<code>c4_sounds/风格名/planted.mp3</code><br>"
        "• 血量警告：<code>health_warning/风格名/warning.mp3</code><br>"
        "• 回合音效：<code>round_sounds/start/风格名/start.mp3</code>、<code>round_sounds/action/风格名/action.mp3</code>、<code>round_sounds/win/风格名/win.mp3</code>、<code>round_sounds/lose/风格名/lose.mp3</code>、<code>round_sounds/mvp/风格名/mvp.mp3</code><br>"
        "新增素材后点击底部「刷新风格列表」或重新进入页面即可"
    ),
    "viewmodel": (
        "<b>功能说明</b><br>"
        "局内视角设置可以配置持枪视角预设（FOV、位置偏移）和准心快速回正功能，通过 CFG 文件写入游戏配置生效。<br><br>"
        "<b>持枪视角预设</b><br>"
        "1. 设置多组视角预设，每组可调整 FOV（视野大小）、X/Y/Z 偏移量（枪模在屏幕上的位置）<br>"
        "2. 为每组预设绑定快捷键，游戏内按键即可切到那组视角<br>"
        "3. 设置循环切换按键（默认 CAPSLOCK），按一下切到下一组预设<br><br>"
        "<b>自动循环切换</b><br>"
        "1. 勾选「启用自动循环切换」后，按住 / 按下「激活按键」（默认 V），会每隔设定的「切换间隔」秒自动切到下一组预设<br>"
        "2. 适合想让持枪视角不断变化的玩法；不需要时关掉即可<br><br>"
        "<b>文件与生效位置</b><br>"
        "1. 这个功能无需额外放素材文件。<br>"
        "2. 页面参数保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "3. 点击「保存设置到CFG」后，会写入 <code>CS2/game/csgo/cfg/cs2customizer.cfg</code>（<b>需先在「高级设置」里配置好 CS2 目录，否则保存会失败</b>）<br>"
        "4. 游戏内输入 <code>exec cs2customizer.cfg</code> 可立即加载；如需自动加载，可把这句写进 <code>autoexec.cfg</code>"
    ),
    "magnifier": (
        "<b>功能说明</b><br>"
        "开镜放大功能会在使用狙击枪开镜时放大屏幕中心区域，也支持联动局内灵敏度。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「开镜放大」开关<br>"
        "2. 调整放大倍率和放大区域大小<br>"
        "3. 如需灵敏度联动，填写你在 CS2 中的基础 sensitivity 和联动倍率<br>"
        "4. 选择触发的武器类型（AWP、Scout 等）<br><br>"
        "<b>文件与生效位置</b><br>"
        "1. 这个功能无需额外放素材文件。<br>"
        "2. 参数保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "3. 灵敏度联动会生成 <code>CS2/game/csgo/cfg/cs2customizer.cfg</code> 和 <code>CS2/game/csgo/cfg/cs2customizer_magnifier_runtime.cfg</code><br>"
        "4. 当前游戏会话首次启用联动时，如未生效，请在控制台执行一次 <code>exec cs2customizer.cfg</code><br><br>"
        "<b>注意事项</b><br>"
        "• 此功能需要以管理员身份运行程序<br>"
        "• 放大效果为屏幕覆盖层，不会修改游戏画面资源"
    ),
    "flash": (
        "<b>功能说明</b><br>"
        "自定闪光功能可以替代游戏默认的闪白效果，支持自定义颜色、图片叠加和音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「自定闪光」开关<br>"
        "2. 在「基础」选项卡调整闪光颜色、透明度和过渡方式<br>"
        "3. 在「图片设置」中选择图片风格，在「音频设置」中选择闪光音效<br>"
        "4. 在「效果预览」里调整强度和持续时间并测试<br><br>"
        "<b>自定义素材目录</b><br>"
        "1. 图片风格目录：<code>AppData/Local/CS2Customizer/resources/flash_images/风格名/</code><br>"
        "2. 同一套 PNG/JPG 图片放进对应风格文件夹后，点击「刷新样式列表」即可出现<br>"
        "3. 音频风格目录：<code>AppData/Local/CS2Customizer/resources/flash_audio/风格名/</code><br>"
        "4. 风格文件夹里放 1 个或多个 MP3/WAV/OGG 文件，点击「刷新音频列表」后即可选择"
    ),
    "music": (
        "<b>功能说明</b><br>"
        "音乐播放器支持本地音乐文件和在线 URL。底部控制栏负责手动播放；“音乐联动”开关只控制游戏是否自动接管音乐。<br><br>"
        "<b>使用方法</b><br>"
        "1. 点击添加按钮导入本地音乐文件或粘贴在线 URL<br>"
        "2. 使用底部控制栏播放、暂停、切换曲目<br>"
        "3. 调整音量滑块控制播放音量<br>"
        "4. 选择播放模式（顺序播放 / 随机播放 / 单曲循环 / 列表循环）<br><br>"
        "<b>文件与配置位置</b><br>"
        "1. 本地音乐无需放到软件固定目录，可以直接添加任意磁盘里的文件。<br>"
        "2. 播放列表、当前曲目、播放进度和联动规则保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "3. 如果你后来移动或删除本地音频文件，列表里的原路径会失效，需要重新导入。<br><br>"
        "<b>游戏联动</b><br>"
        "开启“音乐联动”后，玩家死亡时可自动开始 / 继续播放，存活时可自动暂停或降低音量；关闭后仍可手动播放，但游戏状态不会再自动影响音乐。"
    ),
    "voice_output": (
        "<b>功能说明</b><br>"
        "语音输出页面包含语音输出、音板和音效转发三个模块。<br><br>"
        "<b>前置准备</b><br>"
        "1. 安装 VB-Cable 虚拟声卡驱动（页面内提供安装按钮）<br>"
        "2. 在 CS2 设置中将麦克风设为「CABLE Output (VB-Audio Virtual Cable)」<br><br>"
        "<b>文件与配置位置</b><br>"
        "1. 语音输出和音效转发本身无需固定素材目录，重点是先装好 VB-Cable。<br>"
        "2. 音板槽位可以直接选择任意本地音频文件，不需要拷进软件目录。<br>"
        "3. 槽位、快捷键、PTT 和模式等设置保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "4. 如果需要备份 / 迁移，导出配置默认建议保存为 <code>AppData/Local/CS2Customizer/voice_output_config.json</code><br><br>"
        "<b>各模块说明</b><br>"
        "• <b>语音输出</b> — 输入文字后按快捷键即可将语音送进游戏语音<br>"
        "• <b>音板</b> — 为每个槽位设置音频文件和快捷键，游戏中按键即可播放<br>"
        "• <b>音效转发</b> — 开启后，勾选需要转发的音效类型，队友即可通过语音听到对应效果"
    ),
    "utility": (
        "<b>功能说明</b><br>"
        "道具瞄点功能提供游戏内覆盖层，帮助学习 CS2 道具投掷点位，自动根据阵营显示对应道具。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在基础设置中启用「道具瞄点」开关<br>"
        "2. 设置快捷键和显示模式（长按显示 / 切换显示）<br>"
        "3. 进入游戏后按快捷键打开菜单<br>"
        "4. 用数字键 1-9 选择道具，数字键 0 返回上级，ESC 关闭<br><br>"
        "<b>文件夹结构</b><br>"
        "道具图片统一放在 <code>AppData/Local/CS2Customizer/resources/utility_guides/</code> 下：<br>"
        "<code>地图名/T或CT/分类名/道具名_站位.jpg + 道具名_瞄准.jpg</code><br>"
        "例如：<code>AppData/Local/CS2Customizer/resources/utility_guides/de_dust2/T/A点进攻/Xbox烟_站位.jpg</code><br><br>"
        "<b>自定义道具</b><br>"
        "1. 在对应地图的 T 或 CT 文件夹下创建分类文件夹<br>"
        "2. 添加成对的图片（站位图 + 瞄准图），命名格式为「道具名_站位」和「道具名_瞄准」<br>"
        "3. 支持 JPG/PNG 格式，点击「刷新道具列表」即可加载"
    ),
    "hud_color": (
        "<b>功能说明</b><br>"
        "HUD 颜色规则让你的 HUD 根据游戏事件自动变色。选一个预设方案，开关你想要的事件即可。<br><br>"
        "<b>数字键颜色（纯 CFG）</b><br>"
        "数字键 1-9 的颜色映射写入 cs2customizer.cfg，软件关闭时仍可用。游戏中按数字键切换武器时会同时切换 HUD 颜色。<br><br>"
        "<b>事件响应（需软件）</b><br>"
        "击杀、爆头、连杀、被击杀、低血量等事件由软件通过 GSI 实时检测并变色；运行期额外颜色会由软件动态写入。<br><br>"
        "<b>文件与生效位置</b><br>"
        "1. 这个功能无需额外放资源文件。<br>"
        "2. 规则参数保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "3. 点击「保存 HUD 规则」后会写出 <code>CS2/game/csgo/cfg/cs2customizer.cfg</code><br>"
        "4. 软件运行期还会按需更新 <code>CS2/game/csgo/cfg/cs2customizer_hud_runtime.cfg</code><br>"
        "5. 首次使用请在游戏控制台执行 <code>exec cs2customizer.cfg</code>"
    ),
    "preset_center": (
        "<b>功能说明</b><br>"
        "预设中心把你勾选的一整套设置（HUD 颜色、屏幕特效、特殊音效等）打包成「预设」，方便一键切换或分享给别人。<br><br>"
        "<b>怎么用</b><br>"
        "1. 勾选想打包的功能范围，保存成一个预设<br>"
        "2. 想换一整套体验时，选中预设点应用即可<br>"
        "3. 「导出」会生成一个预设文件，把它发给朋友，对方拖进自己的预设中心就能导入<br><br>"
        "<b>合并 / 覆盖</b><br>"
        "• 合并：只把预设里有的项覆盖过来，保留你其它的设置<br>"
        "• 覆盖：用预设整套替换当前设置<br>"
        "• 无论哪种，应用前都会自动存一份「配置快照」，随时能在快照页回滚<br><br>"
        "<b>按地图自动切换</b><br>"
        "把当前勾选范围存成某张地图的预设后，进入这张图时会自动套用那套设置（套用前同样自动快照）。"
    ),
    "screen_effects": (
        "<b>功能说明</b><br>"
        "屏幕特效会在你击杀或爆头时，在屏幕边缘播放一段特效（如火花、边框闪动），增强击杀反馈。它和「自定闪光」不同——闪光是替换被闪时的白屏，屏幕特效是给自己的击杀加演出。<br><br>"
        "<b>怎么用</b><br>"
        "1. 打开开关，选一个「特效预设」（不同预设是不同的视觉风格）<br>"
        "2. 选「演出模式」（特效的播放方式，如拖尾 / 迸发）<br>"
        "3. 需要游戏正在运行、GSI 正常，击杀时才会触发<br><br>"
        "<b>注意事项</b><br>"
        "• 特效为屏幕覆盖层，只在触发的一瞬间渲染，不占用平时性能<br>"
        "• 全屏独占模式下覆盖层可能不可见，建议 CS2 使用「无边框窗口」模式"
    ),
    "config_snapshot": (
        "<b>功能说明</b><br>"
        "配置快照就是给你当前的全部设置「拍张照片」存下来，作为一个可回滚的安全点。改坏了、试了新配置不满意，随时能一键还原到之前某个快照。<br><br>"
        "<b>怎么用</b><br>"
        "1. 点「创建快照」手动存一份当前配置<br>"
        "2. 应用预设、云端套用等有风险的操作前，软件也会自动存一份快照<br>"
        "3. 在列表里选一个快照点「恢复」，就会回到那时候的设置<br><br>"
        "<b>注意事项</b><br>"
        "• 快照存的是设置本身（config.json），不含音频 / 图片素材<br>"
        "• 恢复会覆盖当前设置，建议恢复前先给现状也存一份快照"
    ),
    "audio_health": (
        "<b>功能说明</b><br>"
        "音频体检会检查你的音效 / 图片等资源是否完整，帮你回答「为什么这个音效不响」。<br><br>"
        "<b>怎么用</b><br>"
        "1. 点「开始体检」，软件会扫描各功能的资源目录<br>"
        "2. 报告会列出：缺失的目录、配置里选了但文件不存在的风格、连杀档位不全的风格等<br>"
        "3. 对能自动处理的问题，可用「一键保守修复」补齐缺失目录 / 清理无效引用<br><br>"
        "<b>注意事项</b><br>"
        "• 体检是只读检查，不会删你的音频文件<br>"
        "• 若某功能没声音，先来这里体检，往往能直接看出是「没放文件」还是「选错风格」"
    ),
})
