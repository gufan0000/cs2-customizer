# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-407（批 16）：**总开关关着的时候，让整页停止假装已经生效。**

## 这条不是「把开关做大」——立案说法被自己的调研推翻了

RN-407 立案写的是「总开关默认关闭且**不够醒目**」。批 14 拿两个候选做了一次
方案调研（题面自写：问「一个没耐心的 CS2 玩家看到这一屏，**会不会以为他现在
调的这些设置已经在游戏里生效了**」），结果是：

| 主诉 | 现状 A | 只改预览的候选 C |
|---|---|---|
| 底栏「改动已自动保存，不用点任何按钮」 | 4/4 高 | **6/6 高** |
| 参数区全高亮、未置灰 ⇒ 以为在运行 | 4/4 高 | **6/6 高** |
| 预览框 | 4/4 高「仍渲染绿准心」 | **6/6 高「失去反馈，与底栏矛盾」** |
| **总开关不够醒目**（= 立案说法）| 3/4 中 | **0 发** |

⭐⭐⭐ **一屏上有三处在同时暗示同一件假事时，改掉一处不会降低那个印象，
只会制造一处矛盾。** 候选 C 把预览改诚实之后，底栏那句就成了屏幕上**唯一
还在撒谎**的东西，外审当场读成「认知冲突，不知所措」——**票数不降反升**。

⇒ 三件一起做，缺一不可：

1. **底栏回执带上前提**（`PageActionBar.set_effect_state`）；
2. **参数区降权**（`masterOff` 属性 + QSS）；
3. **预览说出后果**（`previewEffectCaption`）。

## 两条不许破的边界

⚠ **降权不是禁用。** RN-179 实测过「空库时 188 个控件可点却没反应」——
那是另一条缺陷，不是这条的解法。这里要的是「**可调、会保存，但现在不生效**」，
所以本模块**从不调用 `setEnabled`**，只改属性和文案。

⚠ **不许把预览关掉。** 那正是候选 C 走的那一步，判词是「失去反馈」6/6 高。
画照常画，旁边一句话把后果说清楚。

## 为什么用属性 + QSS，而不是 `QGraphicsOpacityEffect`

卡片自己挂着 elevation 阴影（`SettingsCard._apply_elevation` /
各页 `_create_shadow`）。`setGraphicsEffect` **一个控件只能挂一个** ——
换上不透明度就把阴影顶掉并析构了，这条坑仓里记过两次
（`gui_widget.py:4633` 的搜索高亮、`ui_transitions.py:7` 的转场）。
⇒ 走 QSS 属性态：只换颜色，不引起重排、不动 graphicsEffect。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFrame, QLabel, QPushButton, QRadioButton, QScrollArea,
    QSlider, QWidget,
)

from core.utils.logger import get_logger

#: 卡片上那个「现在不生效」的动态属性。⚠ 值必须是**字符串** `"true"` ——
#: QSS 的 `[masterOff="true"]` 比的是字符串，写 Python 的 `True` 匹配不上，
#: 而且**不会有任何一处报错**（判据绿、屏幕原样）。
CARD_DIM_PROPERTY = "masterOff"
#: 挂在**状态卡**上的那个属性 —— 它自己不降权（那是要去拨的开关所在的卡），
#: 但它里面那排状态胶囊要退成中性：关着的时候，一排彩色标签读起来就是
#: 「当前正在运行的配置清单」。⭐ 挂在祖先上而不是逐颗挂，是因为那排胶囊
#: 自己会因为 level 变化反复 repolish，属性挂在它们身上会被洗掉。
HOST_DIM_PROPERTY = "masterOffHost"
#: 那句话的 objectName。⚠ 它必须是 `QLabel`/`QFrame` 这类**自己会画 stylesheet
#: 背景**的控件，不许是裸 `QWidget` 子类 —— 批 14 的候选 B 就废在这儿，
#: 底色一个像素都没渲染出来。⭐ 一个没渲染出来的候选，拿去比就是在比两张一样的图。
NOTICE_OBJECT_NAME = "masterOffNotice"
#: 预览旁边那句话的 objectName。页面只要建一个这个名字的 QLabel，本模块就会管它。
PREVIEW_CAPTION_OBJECT_NAME = "previewEffectCaption"

#: 总开关关着时，**跟在那颗开关后面同一行**的那句话。
#: ⭐ 说的是**后果**，不是**去哪** —— RN-144 与批 10 两轮独立证据：
#:   「补一句指路」票数一票不掉，因为「需要用文字指路的控件，就是放错了地方」。
#: ⚠ 同时必须自己说出「还能调、还会存」，否则它读起来就是「这一片废了」（RN-179）。
#:
#: ⚠⚠ **为什么这么短、又为什么在同一行上**：第一版做成了开关行下面的一条警示横幅
#: （两行文案 + 底色 + 描边），开关行 24px → **63px**。紧凑档排版审计当场判红：
#: 状态卡在滚动区**外面**的那 9 页，这 39px 是从 548px 的可视区里硬扣的 ——
#: `kill_voice` / `reload_sound` / `switch_weapon` 的在册纵向裁切从 64px 恶化到
#: **107px**，`magnifier` 82→125，`flash` / `gun_sound` 还多出两条**全新**的整页溢出。
#: ⭐⭐ **把话说清楚，不等于可以把它塞在任何地方** —— 固定不动的那块屏幕是稀缺资源。
#: ⇒ 收成一行，塞进开关行本来就空着的那段横向空间：常态零新增高度，
#:   真挤不下时 `wordWrap` 兜住（多一行 ~20px，仍比横幅省一半）。
#:
#: ⚠⚠⚠ **第一版写的是「…但游戏里现在看不到」，那在一半页面上是一句错话。**
#: 这句话铺在 15 页上，其中 8 页是**音效**（枪声/被击杀/击杀/换弹/切枪/音乐/语音）。
#: 外审复跑当场逮到，措辞独立、跨页复现：
#:   「枪声设置页却提示『游戏里现在看不到』，玩家会下意识认为
#:     『枪声本来就看不到、只要听得到就行』…**反向佐证了枪声已生效**，
#:     彻底破坏了防呆提示的作用」
#: ⭐⭐⭐ **一句要铺到全站的文案，不许挑一种感官说话** ——
#:   「看不到」对画面页是精确，对音效页是**给了它一个不适用的理由**，
#:   而玩家会顺着那个理由把整条警告判为「与我无关」。
#:   ⇒ 一律说「**不生效**」：它对听觉、视觉、行为一样成立。
#:
#: ⚠⚠ **同一个错我在同一批里犯了两次。** 第二版把否定挪到了**底栏那句**的句首，
#: 却把这一句留成了「照常可调、改了会保存，但游戏里不生效」——
#: 外审第三轮 8 发以上同一条判词：
#:   「只扫到前半句『照常可调、改了会保存』，**误当成功能已激活且保存就生效**」
#: ⭐⭐ **把否定放句首这条规矩，要在每一句上各做一遍** ——
#:   我以为我修的是「那句话」，其实修的只是「那一处」。
#: ⚖ **RN-424（批 18）：这一句的语序反过来了 —— 肯定在前。**
#: 批 16 为了让人看见「不生效」，把否定放到了句首（RN-407，那条判断是对的）。
#: ⚠ **但同一个动作，把「可以调」挤进了没人读的后半截。**
#: 实测（判断题 + **地板对照**）问「他知不知道现在就可以先把参数调好」：
#:   两句话都拿掉 = **知道 0/45（0%）**；批 16 的写法 = **知道 26/45（57%）**。
#: ⇒ 那句话是真的有效的，而它只走到 57%；19 发「不知道」的措辞几乎完全一致：
#:   「**以为必须先打开总开关才能开始配置**，关着的时候调了不会保存或不起作用」。
#: ⭐⭐ **两句话分工**：这一句（紧挨着那颗开关）回答「我现在能干什么」，
#:   底栏那句回答「我改的东西生不生效」——那一句的否定仍然在句首。
#: ⭐ 同一屏上两句话都用同一个语序，等于把同一个后半截丢了两次。
NOTICE_OFF_TEXT = "现在可以调、改了会保存；游戏里还不生效"

#: 底栏那句回执。⚠⚠ 批 10 加的版本是**无条件**的
#: 「改动已自动保存，不用点任何按钮。」——
#: ⭐ **一句只在某个状态下为真的回执，在别的状态里就是一句谎。**
#:
#: ⚠⚠ **否定必须排在句首。** 第一版写的是
#:   「改动已自动保存，但总开关关着——游戏里现在还看不到。」
#: 外审复跑跨页 6 发以上同一条判词：
#:   「视线只扫到前七个字『改动已自动保存』，**不会去读破折号后面的补充说明**」
#:   「没耐心读完破折号后面的否定说明，误以为改了随时生效」
#: ⭐⭐ **写在转折之后的否定，等于没写** —— 读的人在读到转折之前就走了。
#:   （官网那轮的同一条规律：解释性文字放在困惑发生的**位置之前**，
#:     放页尾等于没放。这次是同一件事在**句内**的版本。）
ACTION_BAR_ON_TEXT = "改动已自动保存，不用点任何按钮，现在就在游戏里生效。"
ACTION_BAR_OFF_TEXT = "总开关关着——现在改的东西在游戏里不生效（改动仍会自动保存）。"

#: ⚠⚠ 上面那两句里都写着「自动保存 / 不用点任何按钮」，而批 16 把它当成了
#: **全站事实**铺到了 15 页上。批 24 实测：**15 页里有 2 页不是**
#: （`hud_color` 摆着「保存 HUD 规则」、`magnifier` 摆着「应用」「应用偏移」）——
#: 于是同一行底栏里，左边说「不用点任何按钮」，右边就是那颗必须点的按钮。
#:
#: ⭐⭐ **一句被当成全站事实的话，只要有一页不成立，它在那一页就是假的** ——
#:   而共用件让它假得整整齐齐，15 页一个模子。
#: ⭐ 这是 RN-427（用容器类型当代理）的另一个形态：那次代理错的是「谁该降权」，
#:   这次错的是「谁会自动保存」。**共用件省的是重复，不是判断。**
#:
#: ⇒ 那句话跟着**这一页的真实行为**走：页面写 `SAVES_AUTOMATICALLY = False`
#:   就换成手动存的说法。⚠ 语序仍照批 18 的账：**否定排在句首**。
#: ⚠⚠ 第一版写的是「这一页要点一下保存才写进游戏；总开关已开着。」——
#: 外审当轮 **3 发判高**：「顶部显示『已存下』，底栏又提示需手动保存，状态矛盾」。
#: 查实：两句**都是真话** —— 胶囊说的是「此刻没有未保存的改动」，
#: 底栏说的是「这一页的机制是手动保存」。⭐⭐ 又一次
#: **一句真话被读成另一件事**（同 RN-426）：并排放着，后一句读起来像「你还没保存」。
#:
#: ⇒ ⭐ 分工收干净：**共用回执只管「总开关生不生效」，存没存交给页面自己说**
#:   （`hud_color` 的 `_refresh_dirty_ui` 两态都已经写清楚了）。
#:   开着的时候共用回执**什么都不加** —— 那件事页面自己在说，
#:   再说一遍就是 RN-183 那族（同一件事说三遍）。
ACTION_BAR_ON_TEXT_MANUAL = ""
ACTION_BAR_OFF_TEXT_MANUAL = "总开关关着——现在改的东西在游戏里不生效。"

#: 页面属性名：这一页的改动是不是自动就存下去了。⚠ 默认 **True**——
#: 全站 13/15 页确实如此，而**默认值要落在多数那一边**，
#: 否则每加一页都要记得声明一次，而「靠人记得」正是这一族缺陷的来源。
AUTO_SAVE_ATTR = "SAVES_AUTOMATICALLY"


def saves_automatically(page) -> bool:
    return bool(getattr(page, AUTO_SAVE_ATTR, True))

#: 预览旁边那句话。⚠ 预览**照常渲染**，这句话只负责说清楚它意味着什么。
PREVIEW_ON_TEXT = "这就是游戏里现在的样子。"
PREVIEW_OFF_TEXT = "总开关关着——这里画的东西，游戏里现在看不到。"

_logger = get_logger("MasterSwitchEffect")


# --------------------------------------------------------------------- 找卡片


def _is_card(widget: QWidget) -> bool:
    """一张「卡」= objectName 叫 card 的 QFrame。

    ⚠ 不能只认 `SettingsCard`：15 页里有一半仍在用各页自己的
    `_create_card()`（裸 QFrame，objectName 直接设成 card）。
    只认类的话那一半**结构上不可见**，而判据会绿。

    ⚠ 上面那句话**不许写成源码形态**：UP-097 那条棘轮按正则数「把 objectName
    设成 card」的处数，它数不出「这是在调用」还是「这是在谈论」，
    于是一句解释性注释会被算成一处新的手搓卡片。
    ⭐ **一条按正则数「有没有做某件事」的棘轮，会把「谈论那件事」也算进去。**
    """
    return isinstance(widget, QFrame) and widget.objectName() == "card"


def status_card_of(page) -> QWidget | None:
    """装着总开关的那张卡。

    ⭐ 从开关行**往上找**，不认 `page.status_card` 这个属性名 ——
    属性名是各页各叫各的（`status_card` / `overview_card` / 局部变量都有），
    而「开关住在哪张卡里」是一条结构事实，问结构比问名字硬。
    """
    row = getattr(page, "master_switch_row", None)
    if row is None:
        return None
    node = row.parentWidget()
    while node is not None and node is not page:
        if _is_card(node):
            return node
        node = node.parentWidget()
    return None


def parameter_cards(page) -> list[QWidget]:
    """这一页上**该降权**的卡。

    排除两类：装着总开关的那张卡本身，以及它内部嵌的卡。
    ⭐ 把「你要去拨的那颗开关所在的卡」也调暗，等于把出口一起调暗了。
    """
    host = status_card_of(page)
    out = []
    for card in page.findChildren(QFrame):
        if not _is_card(card):
            continue
        if host is not None and (card is host or host.isAncestorOf(card)):
            continue
        out.append(card)
    return out


#: 强调色在这里编码的是**当前值/状态**的那几类控件 —— 打着勾的框、
#: 选中的单选、拉到某个位置的滑块。它们是「这一片是活的」这个信号的来源。
#: ⚠⚠ **`QPushButton` 不在里面**，这是拿三次分母划错换来的：
#:   一颗紫色的主按钮编码的是「这是主要动作」，不是「这件事正在发生」。
#:   外审枚举轮点名的全是打勾/滑块/胶囊，**一次都没点过「去社区拿一套」
#:   这类号召按钮**；把它们一起退成灰，等于把唯一该点的东西也调暗了
#:   （RN-179 那条空库引导正指着它们）。
#: ⭐⭐ **同一种颜色可以承担两个意思，分母要按「它在这儿说什么」划，
#:   不按「它是什么控件」划。**
_VALUE_ACCENT = (QCheckBox, QRadioButton, QSlider)


def parameter_area_controls(page) -> list[QWidget]:
    """这一页**参数区**里所有带品牌强调色的控件（RN-427，批 19）。

    ⚠⚠ **批 16 把「参数区」等同于「objectName 叫 card 的 QFrame」** ——
    那是一个**代理**，而代理会漏：`music` 的「允许游戏状态自动控制音乐」和
    `voice_output` 的三颗转发复选框住在 **`QGroupBox`** 里，一张卡都不沾，
    于是降权**一个像素都没够着**（开/关两态逐像素完全相同），
    而当时的判据问的是「每张卡有没有被降权」——15 页全绿。
    ⭐⭐⭐ **一个用容器类型当代理的分母，会漏掉所有没用那个容器的地方。**

    ⚠ 而我第一版换的代理**同样是坏的**：拿「不在状态卡里」当「在参数区里」，
    当场把**底栏操作按钮**和**页头那颗「?」**扫了进去 —— 那是动作和页面外壳，
    不是参数。⭐ **连着两次用排除法划分母，两次都漏。**

    ⇒ 改用一条**真实的结构边界**：参数区 = **页面主滚动区里的内容**。
    状态卡在滚动区**外面**（15 页里有 9 页如此，批 16 量过），
    底栏和页头也在外面 —— 这不是命名约定，是版面本身。

    ⭐ 实现和判据**共用这一个定义**：各写一份的话，判据会去量一个和产品
    不一样的分母，然后全绿。
    """
    host = status_card_of(page)
    row = getattr(page, "master_switch_row", None)
    out = []
    for area in page.findChildren(QScrollArea):
        inner = area.widget()
        if inner is None:
            continue
        for w in inner.findChildren(QWidget):
            if not isinstance(w, _VALUE_ACCENT):
                continue
            if host is not None and (w is host or host.isAncestorOf(w)):
                continue
            if row is not None and (w is row or row.isAncestorOf(w)):
                continue
            out.append(w)
    return out


#: 状态卡里那条胶囊的标题（RN-428，批 20）。
#: ⚠⚠ 立案时我写的说法是「**「当前」这两个字在说时间**」——**枚举一遍就推翻了**：
#: `crosshair` 有 7 条「当前X」摘要，而它在外审枚举轮 **3/3 报 NONE**。
#: 触发误读的是**描述「某件事发生时会自动做什么」**的条目
#: （「阵亡后自动继续播放」「本地监听开启」「事件 · 2 项」「地图 · 未检测到」），
#: 而「当前样式：点」这种**静态属性**不会。
#: ⭐⭐ **一个读起来像实时读数 / 像规则引擎的东西，光是存在就在暗示有个进程在跑。**
#: ⇒ 不逐句改那些摘要，只改这一处**共用**的标题：它一次性给整条胶囊重新定性。
STRIP_TITLE_ON = "当前状态"
STRIP_TITLE_OFF = "当前配置"
#: 那个标题的 objectName。15 页统一（各页各建一个 QLabel，但名字一致）。
STRIP_TITLE_OBJECT_NAME = "statusLabel"


def status_strip_title(page) -> QWidget | None:
    """状态卡里那条胶囊的标题控件；找不到就 None。

    ⭐ 认**位置 + objectName + 它现在说的那两个词**三条一起 ——
    状态卡里叫 `statusLabel` 的标签不止一个（还有别的说明文字），
    只有这一个是那条胶囊的抬头。
    """
    host = status_card_of(page)
    if host is None:
        return None
    for label in host.findChildren(QLabel):
        if label.objectName() != STRIP_TITLE_OBJECT_NAME:
            continue
        if label.text() in (STRIP_TITLE_ON, STRIP_TITLE_OFF):
            return label
    return None


def undimmed_cards(page) -> list[QWidget]:
    """检查器：现在**还没**降权的参数卡。判据拿它数数。"""
    return [c for c in parameter_cards(page) if not c.property(CARD_DIM_PROPERTY)]


# ----------------------------------------------------------------- 预览那句话


def make_preview_effect_caption() -> QLabel:
    """预览旁边那句话。页面把它加在预览面**紧下方**就行，内容由本模块写。

    ⭐ 解释性文字要放在困惑发生的**位置**上。官网那两轮 6 发的判词是
    「藏在底部小字里」—— **放页尾等于没放**。
    """
    label = QLabel(PREVIEW_OFF_TEXT)
    label.setObjectName(PREVIEW_CAPTION_OBJECT_NAME)
    label.setWordWrap(True)
    return label


def make_master_switch_notice() -> QLabel:
    """总开关关着时跟在那颗开关后面的那句话。

    ⭐ 只在关着的时候存在（RN-195）：开着还挂一句「现在看不到」，
    那是屏幕上第二处假话。
    ⚠ `wordWrap` 开着是兜底，不是常态 —— 见 `NOTICE_OFF_TEXT` 上那段账。
    """
    label = QLabel(NOTICE_OFF_TEXT)
    label.setObjectName(NOTICE_OBJECT_NAME)
    label.setWordWrap(True)
    return label


# ------------------------------------------------------------------- 总装配


#: 身上带**品牌强调色**的那几类控件 —— 它们才是「这一片是活的」这个信号的来源。
#: ⭐ 第一版只降了卡片外壳（标题字色 + 竖杠），外审复跑 39/43 照旧报
#:   「所有控件均为高亮紫色激活态 ⇒ 以为正在运行」：**说话的那个东西我没动**。
_ACCENT_BEARING = (QCheckBox, QPushButton, QRadioButton, QSlider)


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def apply_effect_state(page, enabled: bool) -> None:
    """把「现在到底生不生效」这件事，一次性铺到这一页的三个地方。

    ⭐ 三件一起做是这条缺陷的**结论**，不是实现上的偷懒：
    单做任何一件都只会把矛盾挪个地方（批 14 已实证）。
    """
    enabled = bool(enabled)

    # ① 底栏回执。⚠ 走 findChildren 而不是 `page.action_bar` ——
    #    属性名有一天被谁改掉的话，这里会**静默**失效。
    from widgets.page_action_bar import PageActionBar

    for bar in page.findChildren(PageActionBar):
        bar.refresh_effect_state()

    # ② 参数区降权。⚠ 全程**不碰 setEnabled**（RN-179）。
    value = None if enabled else "true"
    for card in parameter_cards(page):
        if card.property(CARD_DIM_PROPERTY) == value:
            continue
        card.setProperty(CARD_DIM_PROPERTY, value)
        _repolish(card)
        # ⚠⚠ **改祖先的动态属性，不会让后代重算样式。** Qt 把解析好的样式
        # 按控件缓存着；`polish()` 只作用在它自己身上。
        # ⭐ 实测（批 16 第二轮出图）：QSS 规则写对了、判据也绿，
        #   而屏幕上那些紫色滑块和单选框**一个像素都没变** ——
        #   因为没人叫它们重算。⇒ 凡是被祖先选择器管到的后代，都要点名 repolish。
        for child in card.findChildren(QWidget):
            if isinstance(child, _ACCENT_BEARING) or (
                    isinstance(child, QLabel) and child.objectName() == "cardTitle"):
                _repolish(child)

    # ②c 参数区里**编码当前值**的控件，属性挂在**它们自己身上**（RN-427）。
    # ⚠ 上面那一步只够得着住在 card 里的控件，而 `music` / `voice_output`
    #   有 4 颗住在 `QGroupBox` 里 —— 降权对它们**一个像素都没动过**，
    #   而判据当时问的是「每张卡有没有被降权」，15 页全绿。
    # ⭐⭐⭐ **一个用容器类型当代理的分母，会漏掉所有没用那个容器的地方。**
    for widget in parameter_area_controls(page):
        if widget.property(CARD_DIM_PROPERTY) == value:
            continue
        widget.setProperty(CARD_DIM_PROPERTY, value)
        _repolish(widget)

    # ②b 状态胶囊组退成中性。⚠ 挂在状态卡（祖先）上，见 HOST_DIM_PROPERTY。
    host = status_card_of(page)
    if host is not None and host.property(HOST_DIM_PROPERTY) != value:
        host.setProperty(HOST_DIM_PROPERTY, value)
        _repolish(host)
        for chip in host.findChildren(QLabel):
            if chip.objectName() == "audioStatusChip":
                _repolish(chip)

    # ②d 那条胶囊的**标题**（RN-428）：没在跑的时候，它列的是配置。
    title = status_strip_title(page)
    if title is not None:
        title.setText(STRIP_TITLE_ON if enabled else STRIP_TITLE_OFF)

    # ③ 预览说出后果。⚠ 预览**照常渲染**——把它关掉才是那条 6/6 高的判词。
    caption = PREVIEW_ON_TEXT if enabled else PREVIEW_OFF_TEXT
    for label in page.findChildren(QLabel):
        if label.objectName() != PREVIEW_CAPTION_OBJECT_NAME:
            continue
        label.setText(caption)
        label.setToolTip(caption)


def apply_effect_state_safely(page, enabled: bool) -> None:
    """同上，但把异常吞掉只记日志 —— 它挂在开关的信号链上，不许拖垮拨动。"""
    try:
        apply_effect_state(page, enabled)
    except Exception as exc:                       # pragma: no cover - 防御
        _logger.error(f"总开关生效状态没能铺到页面上: {exc}")
