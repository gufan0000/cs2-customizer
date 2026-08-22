# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared status badge helpers for audio setting pages."""

from __future__ import annotations

import os
from typing import Iterable, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from core.audio.audio_resource_health import collect_audio_resource_health


DISABLED_STYLE_VALUES = {"", "0", "none", "off", "disabled", "不启用", "未启用"}


def _restyle_widget(widget: QWidget):
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class AudioStatusBadgeBar(QFrame):
    """Reusable chip container for concise status badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("audioStatusBar")
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._chip_pool: list[QLabel] = []
        self._detail_tooltip = ""

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._layout.addStretch(1)

    def _ensure_chip_pool(self, target_count: int):
        while len(self._chip_pool) < target_count:
            chip = QLabel(self)
            chip.setObjectName("audioStatusChip")
            chip.setAlignment(Qt.AlignCenter)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            chip.setTextInteractionFlags(Qt.NoTextInteraction)
            chip.setMinimumHeight(28)
            chip.hide()
            self._chip_pool.append(chip)
            self._layout.insertWidget(len(self._chip_pool) - 1, chip, 0, Qt.AlignLeft | Qt.AlignVCenter)

    def set_detail_tooltip(self, text: str | None):
        self._detail_tooltip = str(text or "").strip()
        self._apply_detail_tooltip()

    def _apply_detail_tooltip(self):
        for idx, chip in enumerate(self._chip_pool):
            if chip.isHidden():
                chip.setToolTip("")
                continue
            chip.setToolTip(self._detail_tooltip if idx == 2 and self._detail_tooltip else "")
        self.setToolTip(self._detail_tooltip if self._detail_tooltip else "")

    def set_badges(self, badges: Sequence[tuple[str, str]]):
        badge_list = list(badges or [])
        self._ensure_chip_pool(len(badge_list))

        for idx, chip in enumerate(self._chip_pool):
            if idx >= len(badge_list):
                chip.hide()
                chip.setText("")
                chip.setProperty("level", "")
                chip.setToolTip("")
                _restyle_widget(chip)
                continue

            level, text = badge_list[idx]
            chip.setText(str(text))
            chip.setProperty("level", str(level or "info"))
            chip.show()
            _restyle_widget(chip)

        self._apply_detail_tooltip()
        self._lock_in_chip_height()

    def _lock_in_chip_height(self):
        """把整条的最小高钉在芯片自己要的高度上（RN-185）。

        ⭐⭐ 这条是**外审逮住的、我自己刚引入的退步**：RN-180 给八页加了一张空库
        引导卡，紧凑档（860×640）竖向本来就紧，于是布局挑了这条**没有下限**的
        徽章条来压 —— 实测 **条高 13px 而芯片要 40px**，四颗芯片只剩顶上一道圆弧，
        文字整个没了。A/B 决定性：有引导卡 13px / 把卡收掉 44px。

        ⚠ 而**每一条既有判据都是绿的**：
          · 排版审计第 4 条问的是「同排芯片高度**是否一致**」——
            ⭐ **四颗一起被压扁，恰好就是一致的**；
          · 纵向裁切那条问「装不下且滚不动」——这一页滚得动；
          · 内层滚动那条（本批新加）也不适用。
        ⇒ ⭐ **一条只看"齐不齐"的判据，看不见"全都不对"。**
          齐平是必要条件，不是充分条件，而判据只写了必要的那一半。

        钉下限之后，竖向不够时被压的是**下面能滚的那块**，不是这条状态摘要。
        """
        visible = [c for c in self._chip_pool if not c.isHidden()]
        if not visible:
            self.setMinimumHeight(0)
            return
        need = max(c.sizeHint().height() for c in visible)
        margins = self._layout.contentsMargins()
        target = need + margins.top() + margins.bottom()

        # ⚠⚠ **只许抬，不许压。** 第一版直接 `setMinimumHeight(target)`，
        # 结果 `crosshair` 的滚动内容整整矮了 16px（1196→1180，A/B 实测）：
        # Qt 的 `qSmartMinSize` **一旦读到显式的 minimumSize 就不再看
        # minimumSizeHint** —— 于是我设的 28 把布局本来推导出的 44 顶掉了。
        # ⭐ 一个名字叫「设下限」的动作，实际效果是**把下限调低了**。
        #   指纹基线逮住了它；否则这 16px 会跟着这一批悄悄进产品。
        # ⚠ 「原本的下限」要取 `sizeHint()`，**不是** `minimumSizeHint()`：
        # 这条的竖向 sizePolicy 是 `Fixed`，而 Qt 的 `qSmartMinSize` 对 Fixed
        # 用的就是 sizeHint（min = max = sizeHint）。第二版取了 minimumSizeHint
        # （28）照样比 sizeHint（44）小，那 16px 一点没修回来。
        # ⭐ **改完要再量一次同一个数**：我这一处连着两版都以为修好了，
        #   两次都是指纹基线把我按回来的。
        self.setMinimumHeight(0)
        natural = self.sizeHint().height()
        self.setMinimumHeight(max(target, natural))


def create_badge_bar() -> AudioStatusBadgeBar:
    return AudioStatusBadgeBar()


def create_badge_label() -> AudioStatusBadgeBar:
    """Compatibility alias for legacy call sites."""
    return create_badge_bar()


def render_badges(
    bar: QWidget,
    badges: Sequence[Tuple[str, str]],
    detail_tooltip: str | None = None,
) -> None:
    if isinstance(bar, AudioStatusBadgeBar):
        bar.set_detail_tooltip(detail_tooltip)
        bar.set_badges(badges)
        return

    # Fallback path for any unexpected legacy usage.
    fallback = [str(text) for _level, text in badges]
    if hasattr(bar, "setText"):
        bar.setText("  |  ".join(fallback))


def is_style_enabled(style_value) -> bool:
    return str(style_value or "").strip().lower() not in DISABLED_STYLE_VALUES


def count_enabled_styles(values: Iterable) -> int:
    return sum(1 for value in values if is_style_enabled(value))


def resolve_style(configured, available: Iterable) -> str:
    """把配置里的原始值解析成**这一行真正在显示的那个值**。

    RN-046：这条知识全仓要且只要一份。它长期以每页各写一份的形式存在，
    而每一份都只做了一半 —— 只判"是不是 0"，**不判"这个风格还在不在"**。
    后果是同一屏上两个数字永久对不上（RN-026 → RN-033 → 这一轮）：

        顶部徽章  「已配置 · 2」   ← 数的是配置里的原始值
        每一行    「不启用」×2     ← `combo.findData(值)` 找不到就回落到第 0 项

    ⚠ 上一轮把实现上提进了 `SoundPageBase`，但那个基类只服务四页；
    `gun_sound` / `special_sound` / `death_sound` 的数据模型各不相同，于是
    "各写一份 or 强行并基类"看着像唯一的两个选项 —— 都不对。
    真正共用的东西是**一个纯函数**：它不碰数据模型，所以数据模型不同不妨碍共用。

    ⚠ 判"不启用"用的是宽口径 `is_style_enabled`（含 ""/none/off/…），
    比各页原来的 `== "0"` 更严。这是**有意收紧**：`combo.findData("")`
    同样找不到、同样显示「不启用」，所以宽口径才是"和屏幕一致"的那一个。
    """
    if not is_style_enabled(configured):
        return "0"
    value = str(configured).strip()
    return value if value in {str(item) for item in (available or ())} else "0"


def stale_style_name(configured, available: Iterable) -> str:
    """「配过、但那个风格已经不在了」时返回它的名字；否则空串。

    这是唯一**可行动**的信息。只把数字改对（2 → 0）会让用户更困惑：
    他明明选过东西，页面却说什么都没配。所以两件事要一起做 ——
    数字说实话 + 明说"有 N 项失效，重新选一个即可"。
    """
    if not is_style_enabled(configured):
        return ""
    return "" if resolve_style(configured, available) != "0" else str(configured).strip()


def build_health_detail_tooltip(health: dict, max_items: int = 2) -> str:
    """Build concise tooltip text for resource health anomalies."""
    if not health or health.get("ok", True):
        return ""

    lines: list[str] = []
    for path in (health.get("missing", []) or [])[:max_items]:
        lines.append(f"缺失目录: {path}")
    for issue in (health.get("invalid", []) or [])[:max_items]:
        key = str(issue.get("key", "")).strip()
        reason = str(issue.get("reason", "")).strip()
        expected = str(issue.get("expected_path", "")).strip()
        lines.append(f"失效引用: {key} ({reason}) {expected}")

    if not lines:
        for path in (health.get("empty", []) or [])[:max_items]:
            lines.append(f"空目录: {path}")

    return "\n".join(lines[: max(1, max_items * 2)])


def resource_badge(health: dict) -> Tuple[str, str]:
    """把资源体检结果翻成**一颗徽章**（等级, 文案）。**七个音效页共用这一份。**

    RN-035：原先七页各写一份

        ("success" if health["ok"] else "danger",
         "资源 · 正常" if health["ok"] else f"资源 · 异常 {health['issue_count']}")

    七份都把「素材目录还不存在」判成**红色异常**——而那正是**全新安装的样子**。
    实测（2026-08-17，全新配置）：`death_sound` / `switch_weapon` / `reload_sound`
    三页各亮一个红色「资源 · 异常 1」，而"异常"的全部内容是一行
    `缺失目录: ...\\resources\\audio\\switch_weapons`，且这行字**只在 tooltip 里**
    （屏幕上那个 `summary_label` 是 RN-009 那个建出来就 hide 的死控件）。
    ⇒ 新用户第一次打开就看见红字报错、又查不到原因，**第一反应是软件坏了**。
    外审 S4 六发里有五发独立指出这一条，措辞几乎一样。

    "还没放素材"不是异常，是起点。把起点画成红色，等于把每个新用户都吓一次。

    分级只认三件事，优先级从高到低：

      · `invalid` —— **配了、但指的东西不在**（`invalid_config_refs`）。
        这才是真异常：用户明确选过一个风格，而它没了。红。
      · `missing` —— 素材目录还没建。全新状态。info（不刺眼），
        文案直接说"待添加"，而不是"异常"。
      · `empty`   —— 目录在、里面没有可用音频。黄。

    ⚠ 故意**不改** `collect_category_health()` 里 `ok` 的定义 ——
    那个字段还有别的消费者（tooltip、音频体检页），在这里换语义会牵连一片。
    这个函数只负责"怎么画"，不负责"什么算健康"。
    """
    health = health or {}
    invalid = list(health.get("invalid", []) or [])
    missing = list(health.get("missing", []) or [])
    empty = list(health.get("empty", []) or [])

    if invalid:
        return "danger", f"资源 · 异常 {len(invalid)}"
    if missing:
        return "info", "素材 · 待添加"
    if empty:
        return "warn", "素材 · 有空目录"
    return "success", "资源 · 正常"


def resource_hint(health: dict) -> str:
    """屏幕上要说的那句人话；健康就返回空串。**七页共用。**

    ⚠ **2026-08-22（RN-168）：`open_label` 参数已删。**
    它是 RN-056 拿血换来的（那句话点名了一个按钮，而按钮名按页不同：
    六个音效页那颗叫「打开音频资源」，`special_sound` 那颗叫「打开当前资源」），
    但 **RN-153 把这句话改成不再点名任何按钮之后，它就没有读者了** ——
    而 `special_sound_page` 还在一本正经地传它，docstring 还在讲它多重要，
    甚至还有一条回退断点在守它。
    ⭐⭐ **一个参数可以活成纪念碑**：传进去、没人读、没有任何东西报错。
    它是被**回退验证判假绿**才暴露的 —— 那条断点模拟的缺陷早就造不出来了。
    ⇒ 假绿的断点不只是"少了一道防线"，它还是**一根指向死代码的指针**。

    RN-056 那条教训本身仍然成立，只是不再由这个参数承载：
    **单一真相源不等于文案可以照搬** —— 一句话只要提到界面上的某个东西，
    那个东西就得跟着调用方走。现在改由「不点名按钮」来保证。
    判据：`test_gun_special_sound_truth.py::test_hint_only_names_buttons_that_exist`
    仍在（它是通用的），另加 `test_no_dead_parameters_in_the_shared_badge_helpers`。

    RN-035 的另一半：徽章只有 6 个字的位置，说不清"接下来该干什么"。
    而原先唯一的解释在 tooltip 里，且内容是一条绝对路径 —— 对玩家毫无意义。

    ⚠ 这句话必须落在**可见**的控件上。别再写进 `summary_label`
    （RN-009：那个控件建出来就 `hide()`，全仓没有任何地方再显示它，
    kill_sound 那轮我就往里写过一次，等于没写）。
    """
    health = health or {}
    if health.get("invalid"):
        return (f"有 {len(health['invalid'])} 项配置指向的素材已经不在了，"
                "重新选一个风格即可；也可以到「工具与系统 - 音频体检」看明细。")
    if health.get("missing"):
        # ⚠ 这句话第一版写的是「还没有这一类的素材目录 —— **这是全新状态，
        # 不是出错**。点右下角「打开音频资源」把音频放进去，再点「刷新风格列表」。」
        # 改完复跑外审，十发里**五发**独立说它"文字冗余、玩家根本不读，
        # 关键指引反而被忽略"。
        # ⭐ 根因是我自己绕回去了：那句"不是出错"的辩解，是**因为徽章当时是红的**
        # 才需要写；而同一轮已经把徽章改成 info（「素材 · 待添加」）了 ——
        # 徽章不再报错，辩解就成了纯噪音。**修好了病因，就该把当初的止痛药撤掉。**
        # ⚠ 2026-08-21（RN-153）：这句话原来写「点右下角「打开音频资源」…」——
        # 而空库时那颗按钮**已经换成「去社区拿一套…」了**，于是它同时犯了两个错：
        # 点名一个当下不存在的按钮，还描述了它的位置。
        # ⭐ 与 RN-163 完全同一个形状：**一处改动不会去通知描述它的文案**，
        # 而这一句还藏在共用的徽章助手里，改按钮的人根本看不到它。
        # ⇒ 只陈述事实，不点名按钮、不说位置 —— 具体怎么办由底栏那句话讲。
        return "还没有素材：放入音频后点「刷新风格列表」就能用。"
    if health.get("empty"):
        return "有风格目录是空的：补进 mp3 / wav / ogg 后点「刷新风格列表」。"
    return ""


def _extract_root(path: str, audio_root: str) -> str:
    if not path:
        return ""
    try:
        rel = os.path.relpath(path, audio_root)
    except Exception:
        return ""
    if rel.startswith(".."):
        return ""
    parts = rel.split(os.sep)
    if not parts:
        return ""
    return parts[0].strip().lower()


def collect_category_health(category_roots: Iterable[str]) -> dict:
    report = collect_audio_resource_health()
    roots = {str(root).strip().lower() for root in category_roots if str(root).strip()}
    audio_root = str(report.get("audio_root", ""))

    missing = []
    for path in report.get("missing_directories", []) or []:
        if _extract_root(str(path), audio_root) in roots:
            missing.append(str(path))

    empty = []
    for path in report.get("empty_style_dirs", []) or []:
        if _extract_root(str(path), audio_root) in roots:
            empty.append(str(path))

    invalid = []
    for issue in report.get("invalid_config_refs", []) or []:
        expected_path = str(issue.get("expected_path", ""))
        if _extract_root(expected_path, audio_root) in roots:
            invalid.append(issue)

    return {
        "ok": not missing and not invalid,
        "missing": missing,
        "empty": empty,
        "invalid": invalid,
        "issue_count": len(missing) + len(invalid),
    }
