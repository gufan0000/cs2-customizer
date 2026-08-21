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


def resource_hint(health: dict, open_label: str = "打开音频资源") -> str:
    """屏幕上要说的那句人话；健康就返回空串。**七页共用。**

    ⭐ `open_label` 是拿血换来的参数（RN-056）。这句话里点名了一个按钮，
    而**按钮名是按页不同的**：六个音效页那颗叫「打开音频资源」，
    `special_sound` 那颗叫「打开当前资源」（它按当前页签开不同目录）。
    我把这个共享提示搬到 special_sound 上之后，页面就在指挥用户去点一个
    **本页不存在的按钮** —— 改完复跑外审，8 发里 **4 发独立**报
    「引导文案提示点击『打开音频资源』，而右下角实际按钮是『打开当前资源』」。
    ⇒ **单一真相源不等于文案可以照搬。**一句话只要提到界面上的某个东西，
      那个东西就得跟着调用方走，否则"收敛"就制造出了新的不一致。
    判据：`test_gun_special_sound_truth.py::test_hint_only_names_buttons_that_exist`。

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
