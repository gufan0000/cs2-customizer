# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""「去社区拿一套」这条路，全仓只从这里走（RN-145 / RN-153）。

## 它存在的理由有两个，都很具体

**一、跨发行版的那道门只开一次。**
`service_urls.py` 是**开源版自己所有**的文件 —— 开源版那一份里没有社区站
（那是闭源商业版的运营资产）。所以每一处用到社区地址的代码都得
`try: from service_urls import ... except ImportError`。
⚠ RN-157 就是这么炸的：一处漏了守卫，判据同步到开源仓之后**挂死 300 秒**。
⇒ 那道 `try/except` 在这里写**一次**，八个页面直接问这个模块。

**二、"没有社区站"必须是一个真实的产品形态，不是一个坏掉的按钮。**
`category_url()` 查不到就回空串，调用方据此**换一条真的走得通的路**
（例如退回「打开音频资源」）。
⭐ **一颗指向空地址的按钮比没有按钮更糟** —— 它看起来是出路，点下去什么也没有。
"""
from __future__ import annotations

from core.utils.logger import get_logger

try:
    # ⚠ **结构上可选**，不靠同步管道打补丁：开源版的 `service_urls.py`
    # 归它自己所有，里面没有社区站。
    from service_urls import COMMUNITY_CATEGORY_URLS
except ImportError:                      # pragma: no cover - 只有开源版会走到
    COMMUNITY_CATEGORY_URLS = {}

_logger = get_logger("CommunityLibrary")


def category_url(key: str) -> str:
    """这一类资源在社区站的地址；没有就回空串。

    ⚠ 回空串**不是异常**，是"这个发行版没有社区站"这一形态的正常取值。
    调用方必须据此换一条路，别把空串塞进 `openUrl`。
    """
    return str(COMMUNITY_CATEGORY_URLS.get(key, "") or "")


def has_category(key: str) -> bool:
    return bool(category_url(key))


class EmptyLibraryCallout:
    """空库时那张「第一步在这里」的卡。**全仓唯一一份**（RN-180）。

    ⭐⭐ 它存在的理由，是一条我自己写下来又自己没照做的教训。
    CLAUDE.md 里早就有：「**解释性文字放在困惑发生的位置之前，不是页尾；
    放页尾 = 没放**」—— 那是做官网那一轮拿两轮外审换来的。而 RN-153/165 我把
    社区 CTA 放进的正是**底部操作栏**，也就是页尾。外审 **20 发 / 跨 9 页**：
    「核心流程倒置」「玩家会在满屏不可用的控件里乱点受挫」。

    ⭐ **教训是按场景归档的，而缺陷不认场景。** 那条写在「网站」小节里，
    而我当时在做桌面版，于是它一次都没被想起来。

    修法在 `kill_icon` 上已经验证过（RN-171，外审 6/6 → 0/6）：
    把第一步放到**空白发生的地方**，底栏只留第二、三步。
    """

    def __init__(self, parent=None):
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

        from widgets.settings_card import SettingsCard

        # ⚠ 用 `SettingsCard.make(...)`，**不许手搓 `QFrame` + objectName("card")**。
        # 第一版就是手搓的，回退验证当场把 `test_handrolled_cards_do_not_grow`
        # 判成假绿 —— 那条棘轮盯的是"手搓卡片的处数不许再涨"，我一加就把它顶到了上限，
        # 于是它再也逮不住下一处。⭐ **一条数量棘轮，被我自己的新代码吃掉了余量。**
        # 上下内边距压到 8（默认 12）：紧凑档实测改成一行之后还差 **4px**，
        # 而"差 4px"和"差 54px"在 Qt 眼里是同一件事 —— 照样会去挤别人。
        self.frame, outer = SettingsCard.make(
            margins=(14, 8, 14, 8), spacing=6, parent=parent)

        # ⚠⚠ **一行，不是三行。** 第一版是「标题 / 按钮 / 提示」竖着堆，高 125px。
        # 紧凑档（860×640）本来就只剩 590px 可用，加上它之后布局最小高 644 ——
        # **超了 54px**，Qt 于是把上面那张状态卡压掉 51px，
        # 徽章直接画到了「当前分类 · 手枪」那行字上面。外审复跑 **3/3 × 3 页**报「重叠」。
        #
        # ⭐⭐ 这是同一处缺陷的**第二形态**：第一版我把状态卡压扁了（RN-185），
        #   钉住高度之后压不动了，于是改成了**重叠**。
        #   ⇒ **给一个被挤的容器加下限，挤压不会消失，只会换个样子出现。**
        #     真正要减的是总高，不是某一段的弹性。
        #
        # 提示那一行删掉不丢信息：第 2、3 步本来就写在底栏那句话里，
        # 而外审同一轮也在报「顶部/中部/底部三处重复」。
        row = QHBoxLayout()
        row.setSpacing(12)
        self.title = QLabel("")
        self.title.setObjectName("statusLabel")
        self.title.setWordWrap(True)
        row.addWidget(self.title, 1)

        self.button = QPushButton("")
        self.button.setMinimumHeight(36)
        self.button.setMinimumWidth(180)
        row.addWidget(self.button, 0)
        outer.addLayout(row)

        #: 兼容旧判据/调用方：提示已并进底栏那句话，这里保留一个空标签。
        self.hint = QLabel("")
        self.hint.setObjectName("hintLabel")
        self.hint.setWordWrap(True)
        self.hint.hide()

        self.frame.hide()

    def show_for(self, *, what: str, cta_text: str, callback) -> None:
        """⚠ 这里原来还收 `keep_text` / `refresh_label` 两个参数，用来拼提示行。
        提示行并进底栏那句话之后**没人读它们了**，而调用方还照传 ——
        批 4 立的死参数棘轮（RN-168）在同一批里就把我逮住了。
        ⭐ **一个参数可以活成纪念碑：调用方照传、函数体不读、无人报错。**
        """
        from page_theme_helper import style_as_primary_button

        self.title.setText(f"还没有任何可用{what} —— 本软件不带素材。")
        self.button.setText(cta_text)
        try:                                  # 重复接会叠加，先断干净
            self.button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.button.clicked.connect(lambda: callback())
        style_as_primary_button(self.button)
        # RN-439：这颗按钮开的是浏览器 —— 总开关关着它照样成立，
        # 所以降权不许把它压成中性灰。⭐ 一处声明覆盖七页，
        # 因为「空了该长什么样」在批 3 就已经收成了这唯一一份（RN-165）。
        from widgets.master_switch_effect import mark_ungoverned_by_master

        mark_ungoverned_by_master(self.button)
        # 提示行已并进底栏那句话（RN-185/186 那一轮把这张卡压成一行）。
        # 留空是为了不在同一屏上把第 2、3 步说两遍。
        self.hint.setText("")
        self.frame.show()

    def hide(self) -> None:
        self.frame.hide()


def guide_empty_library(bar, *, empty: bool, category_key: str, cta_text: str,
                        keep_text: str, keep_callback, message: str,
                        callout: "EmptyLibraryCallout | None" = None,
                        what: str = "风格",
                        refresh_label: str = "刷新风格列表") -> bool:
    """风格库空的时候，把底栏改成一条**走得通的路**。回报有没有真的改。

    ⭐ **"打开一个空文件夹"不是一条路** —— 全新安装时那颗最抢眼的按钮
    点开是个空目录，而用户手上没有文件。

    ⚠ **`keep_text` / `keep_callback` 不是可选装饰，是第二步。**
    RN-153 第一版把原来那颗「打开资源目录」整个换掉了，外审当场两发独立点破：
    「文案提示『放进资源目录』却没有打开目录的入口，从社区下载后卡在找路径」。
    ⭐ **我修好了第一步（去哪儿拿），却顺手删掉了第二步（放哪儿去）** ——
    一条三步的路，只把第一步做顺是走不通的。
    ⇒ 这里强制要求调用方把那颗按钮交出来，由本函数挪到 extra 位保住它。

    ⚠ 没有社区站时（开源版）**什么都不做、回报 False**，让调用方保持原样 ——
    一颗指向空地址的按钮比没有按钮更糟。

    ⭐ 这个函数是**全仓唯一一份**空库引导。八个页面的"库空不空"各问各的
    （数据结构完全不同），但"空了该长什么样"只有这一处 ——
    否则八页会长出八个略有差别的空状态，而没有任何东西会发现它们不一样。
    """
    # 单独一行是为了给回退断点一个**唯一**的锚点：原来直接写
    # `if callout is not None:`，而同一句在上面的空状态收尾里也有一份，
    # 断点因"锚点出现 2 次"当场失效。⭐ 断点的锚点必须唯一，这也是产品代码的事。
    use_callout = callout is not None

    if not empty or not has_category(category_key):
        if use_callout:
            callout.hide()
            # ⚠ 借了要还：空库态把底栏主按钮降成了次级档（RN-186），
            # 库补上就得还回去，否则这一页从此再没有主按钮 ——
            # 那是一次静默的视觉主次丢失，而**没有任何一处会报错**（同 RN-153）。
            from page_theme_helper import style_as_primary_button

            style_as_primary_button(bar.primary_btn)
        return False

    if use_callout:
        # RN-180：第一步进卡里（空白发生的地方），底栏留第二、三步。
        # ⭐ 不许两边都放 —— RN-171 在 `kill_icon` 上的原话是
        # 「「去拿一套图标包」在页面出现 3 次，缺乏唯一明确的首步行动点」。
        callout.show_for(what=what, cta_text=cta_text,
                         callback=lambda: open_category(category_key))
        # ⚠ 底栏**原样不动**。这里一度写成 `configure_extra(keep_text, ...)`，
        # 而底栏主按钮本来就是那颗「打开音频资源」—— 等于造出两颗同名按钮。
        # 原来的 CTA 模式要借 extra 位，是因为主位被 CTA 占了；
        # CTA 搬进卡里之后那个"借"就不该再发生。⭐ **修法搬家了，它的配套动作也要跟着走。**
        # 只把「新建风格 / 风格工具」收掉：一个全新用户此刻手上什么都没有，
        # 让他"自己做一个"正是 RN-171 判掉的那种行动冲突。
        bar.extra_btn.setMenu(None)
        bar.configure_extra("", None, visible=False)
        # ⚠⚠ RN-186：**底栏那颗要降级。** 引导卡那颗已经是 `primaryButton`（紫），
        # 而底栏主按钮天生也是紫的 —— 空库时两颗紫的同屏，外审当场报
        # 「同时存在两个高亮紫色主按钮，首步动作焦点冲突」「不知先点哪个」。
        # ⭐ 本仓早就判过这件事（RN-139：**两颗紫的等于零颗 ——「主」是相对的**），
        #   可那条判据只盯 `basic` **一页**，而规则是全站的。
        #   ⇒ **判据的页面范围就是它的分母**：一条只保一页的规则，
        #     读起来跟"这条规则在生效"一模一样。
        from page_theme_helper import style_as_secondary_button

        style_as_secondary_button(bar.primary_btn)
        # ⚠ 文案不许再描述版面。原来这里写的是「第 1 步在上面那张卡里」——
        # 外审 3/3 判「用生硬文字打补丁」「视线上下割裂」，而本仓有一条专门的
        # `test_no_layout_self_talk_sitewide` 判据，**它没逮住这一句**。
        # ⭐ 编号本身就够了：写着「第 2 步」的人自然知道第 1 步在别处，
        #   不必再告诉他往哪儿看（RN-187）。
        # ⚠⚠ RN-193：这句话在一轮之内被外审判了**两次，方向相反**。
        #   第一版写「第 1 步在上面那张卡里」⇒ 判「用生硬文字打补丁」（RN-187）；
        #   去掉指路、只留「第 2 步 / 第 3 步」⇒ 判「直接从第 2 步开始，
        #   与第 1 步脱节，新手找不到第一步」。
        # ⭐⭐ 两轮都对，而且都不是在说措辞 —— 它们说的是同一件事：
        #   **三步被劈在两个区域里**。换个说法治不好被劈开这件事。
        # ⇒ 干脆不编号：编号才会产生"第 1 步去哪了"这个问题。
        #   卡里那颗按钮是行动，这里说的是拿到之后怎么办，各自完整。
        bar.set_message(
            f"下载好的包放进资源目录（点「{keep_text}」），再点「{refresh_label}」。")
        return True

    bar.configure_primary(cta_text, lambda: open_category(category_key), visible=True)
    # 第二步：原来那颗「打开…文件夹」挪到 extra 位。
    # ⚠ 有些页的 extra 是个带 QMenu 的按钮（风格工具），得先把菜单摘掉，
    # 否则点它弹的还是菜单、回调根本不会跑。
    bar.extra_btn.setMenu(None)
    bar.configure_extra(keep_text, keep_callback, visible=True)
    bar.set_message(message)
    return True


#: 下拉框里等于"什么都没选"的占位项。只剩这些 = 没得选。
_PLACEHOLDER_ITEMS = {"不启用", "未启用", "不使用", "无", "关闭", "默认", ""}
#: 「点了也不会有反应」的按钮文案。
_DEAD_BUTTON_WORDS = ("测试", "试听", "预览", "播放")
#: 置灰前的原状，存在控件自己身上 —— 借了要还（同 RN-153 那条）。
_PREV_ENABLED = "_cs2customizer_dim_prev_enabled"
_PREV_TOOLTIP = "_cs2customizer_dim_prev_tooltip"


def _nothing_to_pick(combo) -> bool:
    """这个下拉框有没有东西可选。"""
    if combo.count() == 0:
        return True
    return all(combo.itemText(i).strip() in _PLACEHOLDER_ITEMS
               for i in range(combo.count()))


def _combo_driving(button, scope):
    """这颗按钮试听的是哪个下拉框选中的东西；找不到就 None。

    从按钮往上走，第一个**恰好含一个下拉框**的祖先就是它那一行。
    上界是 `scope`（整页）—— 这个上界就是"这颗按钮到底受不受风格库支配"的判据：
    `flash` 的「25%预览」住在底部操作栏（0 个下拉框），再往上是整页（4 个），
    永远凑不出"恰好一个" ⇒ 不配对、不置灰。它预览的是软件自己合成的颜色叠加，
    一个素材都不用，**本来就该是亮的**。
    """
    from PySide6.QtWidgets import QComboBox

    anc = button.parentWidget()
    for _ in range(8):
        if anc is None:
            return None
        combos = anc.findChildren(QComboBox)
        if len(combos) == 1:
            return combos[0]
        if anc is scope:
            return None
        anc = anc.parentWidget()
    return None


def _own_enabled(widget) -> bool:
    """这颗控件**它自己**那面开关，跟祖先关没关无关（RN-421）。

    ⚠⚠ 这里以前写的是 `widget.isEnabled()`，而 `isEnabled()` 在**任何一层祖先
    被禁用时都返回 False**。只要有任何一层祖先容器是禁用的，这里就会把一颗
    **本来好好的**控件记成「它原本就是灰的」；等库补上之后，下面那行按这份
    错误的原状还回去（`setEnabled(False)`）——
    **那颗控件从此永久变灰，且没有任何一处报错**。

    ⚠ 这条是 RN-421 那个**已被撤回**的实验（总开关关着时整张参数卡禁用）
    顺带挖出来的。实验撤了，**而这个读数本来就是错的**：撤回的是那条产品改动，
    不是这条修正。⭐ **一次没走通的尝试，未必没有走通的部分。**

    ⭐⭐ **一个只在自己那条路径上正确的读数，会在别人叠上来的那一刻变成谎话** ——
    而它坏的方式是「记错了，然后忠实地还原成错的」，看起来完全像在守规矩。
    ⇒ 问 `isEnabledTo(parent)`：那是它自己那面开关，祖先怎么样都不影响。
    """
    parent = widget.parentWidget()
    return bool(widget.isEnabledTo(parent) if parent is not None
                else widget.isEnabled())


def _set_dim(widget, dim: bool, reason: str) -> int:
    """置灰 / 还原一个控件，并记住它原来的样子。回报这次置灰了几个。"""
    prev = widget.property(_PREV_ENABLED)
    if dim:
        if prev is None:                     # 只在**第一次**置灰时记原状
            widget.setProperty(_PREV_ENABLED, _own_enabled(widget))
            widget.setProperty(_PREV_TOOLTIP, widget.toolTip())
        widget.setEnabled(False)
        widget.setToolTip(reason)
        return 1
    if prev is not None:
        # ⚠ 还原成**它自己原来的样子**，不是无脑 `setEnabled(True)` ——
        # 有的控件本来就因为别的原因是灰的（没选风格、总开关没开），
        # 一律置真会把那些状态一起洗掉，那是一次静默的功能变化。
        widget.setEnabled(bool(prev))
        widget.setToolTip(str(widget.property(_PREV_TOOLTIP) or ""))
        widget.setProperty(_PREV_ENABLED, None)
        widget.setProperty(_PREV_TOOLTIP, None)
    return 0


def dim_controls_with_nothing_to_pick(scope, *, reason: str) -> int:
    """把「没得选」的下拉框和它那一行的试听按钮置灰。回报置灰了几个（RN-179）。

    ⭐⭐ **一个可点却什么都不做的控件，比一个置灰的控件更糟。**
    置灰说的是「你还没准备好」；可点却无反应说的是「这软件坏了」——
    外审 21 发跨 9 页的原话正是「误以为功能损坏 / 界面卡死」。
    实测原状：`switch_weapon` 39 个下拉框 + 39 颗试听按钮全部可点，
    七页合计 **188 个**。

    ⭐ 范围是**算出来的，不是抄出来的**：问的是每个控件"你有没有东西可选"，
    不是"这一页的库空不空"。第一版按后者写，当场诬告了 `flash` 的 4 个下拉框
    和 5 颗预览按钮（闪光是软件自己合成的颜色叠加，一个素材都不用）。
    ⇒ **分母划错的判据不只是漏，它还会逼人去改对的代码**（RN-167 同款）。

    ⚠ 两个方向都走：库补上了就照原样还回去。只置灰不还原等于一次静默的功能丢失。
    """
    from PySide6.QtWidgets import QAbstractButton, QComboBox

    dimmed = 0
    dead_ids = set()
    for combo in scope.findChildren(QComboBox):
        if _nothing_to_pick(combo):
            dead_ids.add(id(combo))
            dimmed += _set_dim(combo, True, reason)
        else:
            _set_dim(combo, False, "")

    for btn in scope.findChildren(QAbstractButton):
        if not any(word in btn.text() for word in _DEAD_BUTTON_WORDS):
            continue
        driver = _combo_driving(btn, scope)
        if driver is None:
            continue
        if id(driver) in dead_ids:
            dimmed += _set_dim(btn, True, reason)
        else:
            _set_dim(btn, False, "")
    return dimmed


def dim_reason(what: str = "风格") -> str:
    """置灰时那句 tooltip。**说清楚是"还没准备好"，不是"坏了"。**"""
    return (f"还没有任何可用{what} —— 先用上面那颗按钮去社区拿一个包，"
            "放进资源目录再回来选。")


def empty_library_message(what: str, refresh_label: str = "刷新风格列表") -> str:
    """空库时底栏那句话。**先承认软件本来就不带素材**，再给三步。

    ⭐ 不说"本来就没有"的话，用户会以为是自己装坏了（RN-145 的原话）。
    """
    return (f"还没有任何可用{what} —— 本软件不带素材。三步：去社区拿一个包 → "
            f"用旁边那颗按钮打开资源目录放进去 → 点「{refresh_label}」。")


def open_category(key: str) -> bool:
    """用系统浏览器打开这一类资源的社区页面。回报有没有真的打开。"""
    url = category_url(key)
    if not url:
        _logger.warning(f"这个发行版没有社区站分类 {key!r}，未打开")
        return False
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl(url)))
