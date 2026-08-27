# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""功能页上那颗**就地总开关**（RN-144 升级版 / RN-147 / RN-155）。

## 它要修的是什么

准心 / 屏幕特效 / 音效家族四页 / 击杀图标，首屏都写着总开关开没开
（「显示 · 未启用」「特效 · 未启用」「总开关 · 未开启」），
**而开关不在这一页** —— 它在「基础设置」那张「功能开关」卡里，
22 项导航里的一项、17 颗开关里的一颗。

⭐ **把状态摆出来而不给动作，比不摆更糟。** 不摆的话玩家至少不知道有这回事；
摆出来 = 明确告诉他"有个东西没开"，然后让他自己去翻。

## 为什么推翻了第一版的「去总开关」跳转

第一版给的是一颗跳过去的按钮。改完复跑，外审两轮合计 **15 发 15 中**反对：

    「本页无法直接开启功能，必须跳转至「基础设置」开启总开关，操作流程割裂。」

⚠ 后 6 发**看的是已经装好那颗按钮的画面** —— 它不是没看见跳转，
是看见了仍然判"这不够"。⭐ **一致性到这个量级就不再是怀疑清单，是结论。**

## 这个组件里唯一难的地方：**不许自己写 config**

`MainWindow._on_switch_changed` 上挂着一长串副作用 —— 准心的 pywin32 前置检查
与显隐、开镜放大的启停、死亡刷短视频的预热/收尾、屏幕特效的叠加层同步、
`sync_legacy_gun_sound_flags`、`save_config`、卡片边框闪烁。

**页内开关只要自己 `setattr(config, key, value)`，这些一个都拿不到。**
拿到的是"界面显示已开、功能根本没起"，而这件事**不会有任何一处报错**。

⇒ 所以它做的事是**去拨首页那颗开关**（`MainWindow.set_feature_enabled`），
让信号照常发出去、副作用照常跑完。
⭐ **同一件事只能有一条链路；第二条链路一定会缺东西，而缺的那部分不报错。**

## 第二个坑：写进去的值不等于实际的值

准心在缺 pywin32 时会把值**回滚**并提前 `return` —— 走不到函数末尾的广播。
所以拨完之后必须**回读 `config` 的实际值**再定自己的显示，
不能信任"我刚写进去的是 True"。这条同时也是判据盯的行为。
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from core.utils.logger import get_logger

#: 总开关**也**住在哪一页。各页共用一个真源 —— 页面 id 改了只改这里。
MASTER_SWITCH_PAGE_ID = "basic"
#: 那一页在导航里叫什么。写进 tooltip，别在各页抄字面量。
MASTER_SWITCH_PAGE_NAME = "基础设置"
#: 总开关那张卡叫什么（`gui_widget._create_basic_page` 里的「功能开关」）。
MASTER_SWITCH_CARD_NAME = "功能开关"
#: 开关行左边那个标签。刻意**不随状态改文案** —— 「这是总开关」是一条常驻事实，
#: 不是只在关着时才成立的提示。状态由开关自己的样子表达。
ROW_LABEL_TEXT = "总开关"
#: 开关旁边那个状态词。⭐ 一颗孤立的开关看不出是开还是关（没有对照物），
#: 一个词把它钉死；同时也让读屏软件读得出来。
STATE_ON_TEXT = "已开启"
STATE_OFF_TEXT = "未开启"

_logger = get_logger("MasterSwitchRow")


def same_switch_text(feature_name: str) -> str:
    """「这颗和首页那颗是同一个」这句话，只有一份。

    ⭐ 必须说清楚。不说的话用户会把它读成"本页专用开关"，
    而它其实是全局的 —— 在这儿关掉，首页那颗也跟着关。
    """
    return (f"「{feature_name}」的总开关。这一颗和「{MASTER_SWITCH_PAGE_NAME}」页"
            f"「{MASTER_SWITCH_CARD_NAME}」里的那一颗是**同一个**，改哪边都一样。")


class MasterSwitchRow(QWidget):
    """状态卡上的「总开关」一行：标签 + 与首页同款的 ToggleSwitch。

    对外只有三个动作：`is_checked()` / `set_checked_by_user()` / `refresh()`。
    ⚠ 没有 `set_checked()` 是**故意的** —— 一个"只改显示不改功能"的入口
    正是三态不一致的来源。要改显示只能通过 `refresh()`（从 config 回读）。
    """

    def __init__(self, page, config_key: str, feature_name: str, parent=None):
        super().__init__(parent)
        # 延迟导入：与首页那 17 颗用**同一个**控件类，视觉才会一致。
        from ui_toggle_switch import ToggleSwitch

        self._page = page
        self.config_key = config_key
        self.feature_name = feature_name
        self._syncing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ⚠ **开关放最左边，不是最右边。**
        # 第一版把这一行塞在状态卡右上角（原来那颗跳转按钮的位置），外审 84 发里
        # **12 发说"藏在角落/位置太偏"、15 发说"配完极易漏开"，七页全中**。
        # 最尖锐的一条直接点破了我为此加的那句提示文案：
        #   「『开关就在下面那张卡的右上角』说明总开关层级与可见性严重不足，
        #     属于打补丁式的无效引导」
        # ⭐ **需要用文字指路的控件，就是放错了地方** —— 指路是症状，不是修法。
        # 左上角是这张卡的第一个扫视落点，总开关就该在那儿。
        self._toggle = ToggleSwitch(checked=self._config_value())
        self._toggle.toggled.connect(self._on_user_toggled)
        layout.addWidget(self._toggle)

        self._label = QLabel(ROW_LABEL_TEXT)
        self._label.setObjectName("statusLabel")
        layout.addWidget(self._label)

        # 状态词跟在开关旁边。⭐ 开关自己只表达"开没开"这个**姿态**，
        # 姿态要靠对比才读得出来（一颗孤立的开关看不出是开还是关）；
        # 一个词把它钉死。
        self._state_label = QLabel("")
        self._state_label.setObjectName("hintLabel")
        layout.addWidget(self._state_label)

        # RN-407 第②件的**说话**部分：「可调、会保存、但现在不生效」。
        # ⭐ 做成这个组件自己的一部分，而不是让 15 页各插一条 ——
        #   「关着的时候有没有把后果说出来」这件事因此**结构上不可能漏一页**。
        # ⚠ 它坐在开关行本来就空着的那段横向空间里，占的是 stretch 的位置：
        #   常态**零新增高度**。理由见 `NOTICE_OFF_TEXT` 上那段紧凑档的账。
        from widgets.master_switch_effect import make_master_switch_notice

        self.effect_notice = make_master_switch_notice()
        layout.addWidget(self.effect_notice, 1)
        layout.addStretch(0)

        self._sync_state_text()
        self.setToolTip(same_switch_text(feature_name))

    def showEvent(self, event):
        """页面第一次露面时把三件套铺一遍。

        ⚠ 构造那一刻页面还没搭完（状态卡通常是第一张，参数卡都还不存在），
        铺过去只会扫到 0 张卡 —— 所以要等，但**不能用 `singleShot(0)` 等**。
        ⭐ 实测（批 16）：往事件队列里多塞一个 0ms 定时器，会让别处
        `processEvents()` 那一下**多冲掉一批排队的工作**，
        `voice_output` 底栏当场换了一句话（两处都在写同一行，谁最后写谁赢），
        一条既有判据当场红。**它跟这次改动毫无关系，是被时序顺手带偏的。**
        ⇒ 挂在 `showEvent` 上：要显示才需要，且不往队列里加任何东西。
        另一半在 `refresh()` 里 —— 那条管的是「拨了就跟着变」。
        """
        super().showEvent(event)
        self._apply_effect_state()

    def _sync_state_text(self) -> None:
        self._state_label.setText(
            STATE_ON_TEXT if self._toggle.isChecked() else STATE_OFF_TEXT)
        # 开着的时候那条说明**整个不存在**（RN-195）：
        # 开着还挂一条「总开关关着」，那是屏幕上第二处假话。
        notice = getattr(self, "effect_notice", None)
        if notice is not None:
            notice.setVisible(not self._toggle.isChecked())

    def _apply_effect_state(self) -> None:
        from widgets.master_switch_effect import apply_effect_state_safely

        if self._page is None:
            return
        apply_effect_state_safely(self._page, self._toggle.isChecked())

    # ------------------------------------------------------------ 对外三件

    def is_checked(self) -> bool:
        return bool(self._toggle.isChecked())

    def set_checked_by_user(self, checked: bool) -> None:
        """当作"用户拨了它"来处理 —— 判据和任何程序化入口都走这里。

        ⚠ 不要拿它当"设置显示值"用：它会真的去开/关功能。
        """
        checked = bool(checked)
        if self._toggle.isChecked() != checked:
            # ⚠ 必须是 `toggle()`：`ToggleSwitch.setChecked()` **不发 `toggled`**
            # （只有鼠标点击走的 `toggle()` 发）。写成 setChecked 的话开关会
            # 变个样子然后**什么都不发生**。详见 `gui_widget.set_feature_enabled`。
            self._toggle.toggle()
        else:
            self._on_user_toggled(checked)     # 值没变也补跑一次，语义是「他按了」

    def refresh(self) -> None:
        """从 `config` 回读实际值，只改显示、不触发功能。

        主窗口在总开关变化后会把这一下广播给所有页内开关行；
        `_on_user_toggled` 自己也会调它（因为**写进去的值不等于实际的值**）。
        """
        value = self._config_value()
        if self._toggle.isChecked() != value:
            self._syncing = True
            try:
                self._toggle.blockSignals(True)
                self._toggle.setChecked(value)
            finally:
                self._toggle.blockSignals(False)
                self._syncing = False
        self._sync_state_text()
        # RN-407：三件套跟着一起铺（底栏回执 / 参数区降权 / 预览说后果）。
        # ⚠ 排在 `_notify_page()` **之前**：页面那个钩子里往往会重写底栏文案，
        # 而底栏那句回执是它自己回读这颗开关现算的 —— 先铺一次，
        # 页面随后那次 `set_message` 会带着正确的回执一起渲染。
        self._apply_effect_state()
        # ⭐ **无条件**通知页面，哪怕开关自己没动。
        # 用户拨的就是这一颗时，`isChecked()` 早就是新值了 —— 上面那段会跳过，
        # 而页面上那条「总开关 · 未开启」的徽章**还停在旧文案**。
        # 这正是 RN-107 族（同屏两处说法不一致）的制造方式：
        # 一个"值没变就早退"的优化，把"别人还没同步过"这件事一起早退掉了。
        self._notify_page()

    def _notify_page(self) -> None:
        """让页面把自己那条状态文案重算一遍。

        钩子名全仓统一叫 `on_master_switch_synced` —— 各页内部的状态方法
        叫什么都行（`_sync_status_strip` / `_sync_overview_status` /
        `_refresh_status_badge` 各不相同），但**对外只认这一个名字**。
        """
        hook = getattr(self._page, "on_master_switch_synced", None)
        if not callable(hook):
            return
        try:
            hook()
        except Exception as exc:                      # pragma: no cover - 防御
            _logger.error(f"{self.config_key} 的页面状态刷新失败: {exc}")

    # ------------------------------------------------------------ 内部

    def _config_value(self) -> bool:
        from config import config

        return bool(getattr(config, self.config_key, False))

    def _main_window(self):
        window = self._page.window() if self._page is not None else None
        return window if hasattr(window, "set_feature_enabled") else None

    def _on_user_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        window = self._main_window()
        if window is None:
            # 页面还没进窗口树（单页构造的测试夹具就是这种）。
            # ⚠ 只记日志、不自己写 config —— 自己写就绕开了副作用那条唯一链路。
            _logger.warning(f"{self.config_key} 的就地开关找不到主窗口，本次拨动未生效")
            self.refresh()
            return
        if not window.set_feature_enabled(self.config_key, bool(checked)):
            _logger.warning(f"首页没有 {self.config_key} 对应的开关，就地开关空转")
        # ⭐ 回读实际值，**不信任刚写进去的那个**：
        # 前置不满足时（例如准心缺 pywin32）产品会回滚并提前 return，
        # 走不到主窗口末尾那次广播。
        self.refresh()


def make_master_switch_row(page, config_key: str, feature_name: str) -> MasterSwitchRow:
    """建一行总开关，接线一次接好。"""
    return MasterSwitchRow(page, config_key, feature_name)
