# SPDX-License-Identifier: GPL-3.0-or-later
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


class HelpButton(QPushButton):
    """圆形 "?" 帮助按钮 (24x24)

    ⚠ **样式必须留在全局 QSS 里（`theme_manager` 的 `QPushButton#helpButton`），
    这里一个字都不许写内联样式。** 原先是在这儿 `setStyleSheet()` 按主题现算的，
    结果 23 个页面的帮助按钮**全部变成一个无字灰胶囊**，成因是三级串联：

      1. `ui_style_applier` 的清扫器在建页后递归 `setStyleSheet("")`
         （只放过声明了 `fp_keep_style` 的控件，本类从没声明过）
         → 内联样式被抹光，落到通用 `QPushButton` 规则上；
      2. 通用规则的 `min-height` 把最小高顶到 42，而 `setFixedSize(24, 24)`
         只压得住**最大**高 —— **Qt 在 min > max 时取 min**，于是 24×42，
         `border-radius: 12px` 再也画不出圆；
      3. 通用规则的横向 padding（≥12px×2）把 24px 宽吃成负数，
         「?」需要 7px 无处可画 → **整个字消失**。

    而 config_snapshot / audio_health / preset_center 等 5 个页面的正文
    明写着「点右上角「?」看用法」—— 文案指着一个用户看不见的按钮。

    走全局 QSS 之后，主题切换由 theme_manager 重刷样式表统一负责，
    既不需要注册回调，也不存在"被清扫"这条路径。
    """

    def __init__(self, parent=None):
        super().__init__("?", parent)
        self.setObjectName("helpButton")
        # 28 而不是 24：QSS 里写的 min/max 是内容盒尺寸（24），加上 1.5px 边框
        # 实际就是 28。这里必须跟 QSS 算出来的最终值一致——写小了 Qt 会取 min，
        # 又变回那个"最大压不住最小"的形变。
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("查看帮助")


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

        # RN-148：这块内容实测有 243px 在视口外，而它**一直没有边缘提示器**。
        # 全站的滚动区靠 `ui_style_applier._style_scrollarea()` 装，
        # 探针实测它对这一个 **0 次调用** —— 不是被那句 `except Exception: pass`
        # 吞了，是**压根没走到它**（这个面板不在那次遍历的树里）。
        # ⭐ 那句静默的 except 正是它能躺住的原因：**失败和没走到长得一模一样**，
        # 所以"装没装上"永远不会有人知道。
        # ⇒ 修法不是去修遍历，是**让这个面板自己装**：
        # 一个控件要不要有边缘提示，是它自己的事，
        # 不该取决于"有没有人恰好遍历到它"。
        from ui_effects import install_scroll_shadow

        install_scroll_shadow(scroll)

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
#
# ⚠ **只许有这一份定义。** 这里原先是「先定义 16 键、再 `.update()` 23 键」两块，
# 而后者把前者的 16 键**逐条全覆盖** —— 那 237 行文案从写下那天起就没被读到过，
# 却一直在被人读、被人改。判据 `tests/test_ui_help_panel_texts.py` 会拦住再来一次。
#
# 2026-03 帮助文案统一校准（这一份的编写口径）：
# 1. 资源类功能写清实际目录结构
# 2. CFG / GSI 类功能写清自动生成位置
# 3. 无需手动放文件的功能明确说明“无需额外放文件”
PAGE_HELP_TEXTS = {
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
        "1. 在本页状态卡最上面打开「总开关」<br>"
        "2. 选择准心形状（十字、圆点、圆环等）<br>"
        "3. 调整准心的颜色、大小、粗细等参数<br>&nbsp;&nbsp;&nbsp;• 中心间隙：让准心中间留空，不挡住要瞄的那个点<br>&nbsp;&nbsp;&nbsp;• 黑色描边：亮地板/沙地上看不清准星时开它<br>&nbsp;&nbsp;&nbsp;• 中心点、不透明度、自定义颜色（六个固定色不够用时）<br>"
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
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "击杀图标会在击杀敌人时把一段动画叠在屏幕上（只有你自己看得见）。<br><br>"
        "<b>三步就好</b><br>"
        "1. 打开这一页的「总开关」<br>"
        "2. 在「风格库」里点一张卡就换——卡片上有缩略图和「素材齐不齐」<br>"
        "3. 点「在屏幕上试播」，位置和大小所见即所得；不顺眼点「调整位置和大小」<br><br>"
        "<b>装一套新的</b><br>"
        "• <b>把图标包(.zip)、动图或图片拖到这一页上</b>，或点「＋ 导入」<br>"
        "• zip 图标包是一整套风格，直接装完 5 个等级，一句都不问<br>"
        "• 单个素材会弹一个小窗问「用在几杀」；文件名带等级（<code>3hs.gif</code>）"
        "就已经替你选好了，直接按「导入」<br>"
        "• 裁透明边、抠纯色背景、帧率、定格时长都是自动判的，不用管<br><br>"
        "<b>关于格式</b><br>"
        "• 想要干净的半透明边缘请用 WebP 动图 / APNG / PNG 序列<br>"
        "• GIF 的透明度是 1-bit 的（像素只能全透明或全不透明），边缘会有硬白边<br>"
        "• 静态图片会作为单帧图标定格显示<br>"
        "• 视频（mp4/webm）不支持，请先转成 WebP 动图或 GIF<br>"
        "• 超过 1024 像素的帧会自动等比缩小；各帧尺寸不一会居中对齐<br><br>"
        "<b>想自己做一套 → 素材工坊</b><br>"
        "• 页面底部「打开素材工坊」：五个击杀等级摊成一块板，每一格自己就能"
        "换素材、调时长、循环预览<br>"
        "• 拖到哪一格就进哪一格，不再问「用在几杀」<br>"
        "• 每一格右键：替换、导入爆头专属、导出、删除；删除可撤销<br>"
        "• 「导出图标包」把整套风格打成 zip，可以直接发给别人<br>"
        "• 「高级导入 / 批量」里能抠背景色、裁透明边、手填图集行列、按 1~5 批量导入<br>"
        "• 展示时长改完要点「保存播放设置」才会写进风格配置<br><br>"
        "<b>显示效果</b><br>"
        "• 入场淡入 / 收尾渐隐：渐隐挂在动画播完之后，不会吃掉素材本身的收尾动作<br>"
        "• 爆头专属图标：要先在工坊里给某个等级导入爆头素材，没导过就用普通图标<br><br>"
        "<b>素材放在哪儿</b><br>"
        "1. 每套风格一个目录：<code>AppData/Local/CS2Customizer/resources/kill_icons/风格名/</code><br>"
        "2. 每个击杀等级一张图集加一份配置，例如 <code>1.png + 1.json</code>；"
        "爆头是 <code>1hs.png + 1hs.json</code><br>"
        "3. 正常用不着手动进去——导入会自动转好放好；工坊里的"
        "「打开素材文件夹」能直接开到这里"
    ),
    "death_sound": (
        "<b>功能说明</b><br>"
        "被击杀音效会在玩家被击杀时播放自定义音效。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "3. 点击「保存到CFG」后，会写入 <code>CS2/game/csgo/cfg/cs2customizer.cfg</code>（<b>需先在「高级设置」里配置好 CS2 目录，否则保存会失败</b>）<br>"
        "4. 游戏内输入 <code>exec cs2customizer.cfg</code> 可立即加载；如需自动加载，可把这句写进 <code>autoexec.cfg</code>"
    ),
    "magnifier": (
        "<b>功能说明</b><br>"
        "开镜放大功能会在使用狙击枪开镜时放大屏幕中心区域，也支持联动局内灵敏度。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        # ⚠ RN-075：第 1 步原来写「在基础设置中启用」—— 而本页**自己的第一个页签
        # 就叫「基础设置」**，里面没有任何总开关，所以照着做只会在原地打转。
        # ⚠ 第 2 步原来写「在「基础」选项卡」—— 本页**没有**叫「基础」的页签
        # （它叫「基础设置」），属 RN-056 家族：文案点名了一个不存在的控件。
        # ⚠⚠ RN-401：这一步原来写「点本页的「启用自定闪光」直接开」——
        # 而那颗按钮**RN-192 就已经删掉了**（启用归状态卡上的总开关，
        # 底栏那颗只管启动后台监听）。RN-192 当场改了页头、也在现场注释里写下
        # 「文案点名的控件名必须跟调用方一起走（RN-167）」，**却没人打开这个文件**。
        # ⭐ 而 RN-167 那条棘轮本该逮住它，只因为正则要求动词紧挨引号
        # （「点**本页的**「启用…」」中间夹了方位词）⇒ 整条不在分母里。
        # ⚠⚠ RN-087：这后半句「也可以去导航里的「基础设置」页…」是**批 10 我自己加的**，
        # 2026-08-26 删掉。两条理由：
        #   ① 它是「开关还住在哪儿」的**第二份副本** —— 开关再搬一次家它就烂了
        #     （RN-163 的原话：给"上次那个 bug"写的文案，挡不住同一类的下一个）；
        #   ② ⭐ 更糟的是它在**这一页**特别容易读错：本页自己的第一个页签就叫
        #     「基础设置」，而紧接着的第 2 步写的是「回到**本页**「基础设置」页签」——
        #     相邻两行里两个「基础设置」指的是两个不同的东西，全靠限定词撑着。
        # ⭐ **需要加限定词才不会读错的指路，本身就该删掉。**
        "1. 在本页打开「自定闪光」总开关，再点「启动」开始后台监听<br>"
        "2. 回到本页「基础设置」页签调整闪光颜色、透明度和过渡方式<br>"
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
        "音乐播放器支持本地音乐文件和在线 URL。“音乐联动”开关只控制游戏是否自动接管音乐。<br><br>"
        "<b>使用方法</b><br>"
        # ⚠⚠ RN-455（批 32）：第 2 步原来写「使用底部控制栏播放、暂停、切换曲目」，
        #   第 3 步写「调整音量滑块控制播放音量」——**那两样都长在底部控制栏上**，
        #   而那条栏**放过音乐才建**（RN-195/批 9）。于是这份「使用方法」的第 2 步
        #   对每一个还没放过音乐的人都指着一个不存在的东西，而真正的入口（双击）
        #   一个字都没提。⭐ 顺序也反了：**先说怎么让它出现，再说它能干什么。**
        "1. 点击底部的“添加音乐”导入本地音乐文件，或用“添加 URL”粘贴在线链接<br>"
        "2. <b>双击列表里的歌名开始播放</b>——这一页本身没有播放按钮<br>"
        "3. 放起来之后，窗口底部会常驻一条音乐控制栏，暂停 / 切歌 / 音量都在那儿<br>"
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
        # ⭐⭐⭐ RN-451（批 30）：下面那条「语音输出 — 输入文字后按快捷键」
        #   **从 2026-04-19 的 2.0 重构前基线就在，而这个功能从来没有存在过**
        #   （这一页 0 个文本输入控件，全仓 0 个 TTS 引擎，AST 实测）。
        #   它还活过了 RN-001 那一轮（删掉 237 行从没被读到过的帮助文案）——
        #   没被读，所以也没被证伪；然后在 2026-08-16 被当成真源抄进了页头。
        #   ⭐⭐⭐ **一份没人读的文档不会被证伪，但它会被当成真源抄走。**
        "语音输出页面包含虚拟声卡设置、音板和音效转发三个部分。<br><br>"
        "<b>前置准备</b><br>"
        "1. 安装 VB-Cable 虚拟声卡驱动（页面内提供安装按钮）<br>"
        "2. 在 CS2 设置中将麦克风设为「CABLE Output (VB-Audio Virtual Cable)」<br><br>"
        "<b>文件与配置位置</b><br>"
        "1. 语音输出和音效转发本身无需固定素材目录，重点是先装好 VB-Cable。<br>"
        "2. 音板槽位可以直接选择任意本地音频文件，不需要拷进软件目录。<br>"
        "3. 槽位、快捷键、PTT 和模式等设置保存在 <code>AppData/Local/CS2Customizer/config.json</code>。<br>"
        "4. 如果需要备份 / 迁移，导出配置默认建议保存为 <code>AppData/Local/CS2Customizer/voice_output_config.json</code><br><br>"
        "<b>各模块说明</b><br>"
        "• <b>虚拟声卡设置</b> — 装好 VB-Cable，再选麦克风、调主音量和播放模式<br>"
        "• <b>音板</b> — 为每个槽位设置音频文件和快捷键，游戏中按键即可播放<br>"
        "• <b>音效转发</b> — 开启后，勾选需要转发的音效类型，队友即可通过语音听到对应效果"
    ),
    "utility": (
        "<b>功能说明</b><br>"
        "道具瞄点功能提供游戏内覆盖层，帮助学习 CS2 道具投掷点位，自动根据阵营显示对应道具。<br><br>"
        "<b>使用方法</b><br>"
        "1. 在本页状态卡最上面打开「总开关」<br>"
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
        "1. 点「立即体检」，软件会扫描各功能的资源目录<br>"
        "2. 报告会列出：缺失的目录、配置里选了但文件不存在的风格、连杀档位不全的风格等<br>"
        "3. 对能自动处理的问题，可用「一键修复（保守）」补齐缺失目录 / 清理无效引用<br><br>"
        "<b>注意事项</b><br>"
        "• 体检是只读检查，不会删你的音频文件<br>"
        "• 若某功能没声音，先来这里体检，往往能直接看出是「没放文件」还是「选错风格」"
    ),
}
