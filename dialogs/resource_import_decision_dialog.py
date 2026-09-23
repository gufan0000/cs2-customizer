# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""认不出来的时候，让用户选 —— 但要选得省力（2026-09-16，资源导入统一化）。

全套设计见 `docs/资源导入_设计方案_v1_20260916.md`。这里只记两条交互判断：

⭐⭐ **对着"组"选一次，不是对着文件选 N 次。** 一个包里三十个文件同属一坨，
问三十遍和问一遍拿到的信息完全一样。

⭐⭐ **拿不准时一个都不预选。** `Group.preselect` 在 `unsure` 档返回 None，
这里照办 —— 预选一个等于替用户瞎猜，而他看到已选好的下拉框会默认它是对的，
选错了还是静默的（文件进错目录，那一类的页面上空空如也）。

⚠ 每一组旁边**必须摆出证据**（「这 12 个文件都在 `AK47/` 下，分成 3 个子目录」）。
用户是看着这个做判断的；只给一个下拉框，他也不知道该选什么。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.resource_catalog import RESOURCE_SPECS
from core.resource_identify import UNSURE
from core.resource_placement import NEEDS_BUCKET, layers_needed
from core.resource_readback import known_buckets, style_name_problem
from widgets.settings_card import SettingsCard


def _bucket_label(spec_key: str, value: str) -> str:
    """下拉框里给人看的那一行。⭐ 武器给中文/通用名，别只给代号 ——
    `m4a1` 是 M4A4、`m4a1_silencer` 才是 M4A1-S，只看代号必选错。"""
    if spec_key == "round_sounds":
        return _ROUND_LABELS.get(value, value)
    try:
        from core.gun_sound_profiles import GUN_SOUND_PROFILE_LIST

        for profile in GUN_SOUND_PROFILE_LIST:
            if str(profile.gun_type).lower() == str(value).lower():
                return f"{profile.display_name}（{value}）"
    except Exception:
        pass
    return str(value)


class ResourceImportDecisionDialog(QDialog):
    """每一组一张卡：证据 + 类别下拉 + （按需）风格名 / 回合事件。"""

    def __init__(self, groups, parent=None, default_style_name=""):
        """`default_style_name` 是包里写好的名字（清单 `name` 或包文件名）。

        ⭐ 预填而不是留空：用户改一个字比从零想一个名字省力，
        而多数时候包名就是他想要的那个名字。
        """
        super().__init__(parent)
        self.setWindowTitle("这些素材是什么？")
        self.setMinimumWidth(560)
        self._groups = list(groups or [])
        self._default_style_name = str(default_style_name or "").strip()
        self._rows = []

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        lead = QLabel(
            "软件认不准下面这些素材属于哪一类。"
            "选好之后它会自动摆进对应的目录，你不用自己建文件夹。"
        )
        lead.setWordWrap(True)
        outer.addWidget(lead)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        body = QVBoxLayout(holder)
        body.setSpacing(12)
        for group in self._groups:
            body.addWidget(self._build_card(group))
        body.addStretch()
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        # ⭐ 按钮为什么灰着，要**在按钮旁边**说 —— 一个灰掉却不解释的确定键，
        #   用户只会以为软件卡住了。
        self._hint_label = QLabel("", parent=self)
        self._hint_label.setObjectName("formHint")
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        outer.addWidget(self._hint_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.button(QDialogButtonBox.Ok).setText("按上面的选择导入")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self._sync_ok()

    # ------------------------------------------------------------------ 建卡

    def _build_card(self, group):
        # ⭐ 用正规组件而不是手搓 `QFrame#card`：左色条、标题层级、语义配色
        #   都在组件里，手搓的那个一样都没有（棘轮 `HANDROLLED_CARD_MAX` 也守着这件事）。
        preselect = group.preselect
        evidence = preselect.evidence if preselect else (
            group.guesses[0].evidence if group.guesses else [])
        card = SettingsCard(
            title=f"{len(group.paths)} 个文件",
            description=" · ".join(str(line) for line in evidence) or None,
            semantic="warning" if group.confidence == UNSURE else "info",
        )
        layout = card.body

        sample = QLabel("例如：" + "、".join(group.paths[:3]) +
                        ("…" if len(group.paths) > 3 else ""))
        sample.setWordWrap(True)
        sample.setObjectName("hintLabel")
        layout.addWidget(sample)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        combo = QComboBox()
        # ⭐ 拿不准时第一项是一句**空提示**，而不是某个类别 ——
        #   下拉框不许自己带着一个看起来已经选好的答案。
        if group.confidence == UNSURE or preselect is None:
            combo.addItem("请选择…", "")
        for guess in group.guesses:
            combo.addItem(guess.label, guess.spec_key)
        # 候选之外的类别也要给，否则识别器漏判时用户就没路可走了。
        offered = {guess.spec_key for guess in group.guesses}
        for spec in RESOURCE_SPECS:
            if spec.key not in offered:
                combo.addItem(f"{spec.label}（其它）", spec.key)
        if preselect is not None:
            index = combo.findData(preselect.spec_key)
            combo.setCurrentIndex(max(0, index))
        elif getattr(group, "remembered", ""):
            # ⭐ 学习表记得上次的答案，但这个形状**原理上分不清**几个类
            #   （`dir1/audio` 底下坐着七类）⇒ 还是问，只是把上次那个摆在
            #   已选状态上，用户一眼确认即可。
            #   ⚠ 与 `preselect` 的区别：那个意思是"不用问了"，这个是
            #   "还要问，但别让你重新找一遍"。
            index = combo.findData(group.remembered)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(self._sync_ok)
        form.addRow("这是：", combo)

        style_edit = QLineEdit()
        style_edit.setText(self._default_style_name)
        style_edit.setPlaceholderText("给这套素材起个名字，设置页的下拉框里会显示它")
        style_edit.textChanged.connect(self._sync_ok)
        form.addRow("风格名：", style_edit)

        # ⚠⚠ 这一格原来**写死成回合事件**，于是「这套素材属于哪一把武器」
        #   那个问题在 UI 上**根本没有地方回答** —— 归类器问得出来，
        #   对话框答不上来，那一组只能整组落进「未识别」。
        # ⭐ 改成按类别换内容的一格：回合事件 / 武器 / 投掷物各用各的候选。
        round_combo = QComboBox()
        round_combo.currentIndexChanged.connect(self._sync_ok)
        # ⛔ 每张卡一个，放进 row —— 以前是 `self._bucket_label`，建完最后一张卡就只剩它，
        #    改前面任何一张的类别，换字的都是最后一张。断点 `--only SWEEP`。
        bucket_label = QLabel("回合事件：")
        form.addRow(bucket_label, round_combo)

        layout.addLayout(form)
        row = {
            "group": group, "combo": combo, "style": style_edit,
            "round": round_combo, "form": form, "bucket_label": bucket_label,
        }
        self._rows.append(row)
        combo.currentIndexChanged.connect(lambda _i, r=row: self._sync_row(r))
        self._sync_row(row)
        return card

    # ------------------------------------------------------------- 按类别显隐

    def _sync_row(self, row):
        """⭐ 只问这一类真的需要的东西。

        `death` 不需要风格名（文件本身就是风格），只有 `round_sounds` 需要回合事件。
        多问一格，用户就会以为那一格是必填的。
        """
        spec_key = str(row["combo"].currentData() or "")
        needs_style = bool(spec_key) and layers_needed(spec_key) > 0
        # 源路径自带的层够用时也不必问 —— 但对话框不重算那件事，
        # 交给 `plan_placements`：它在层数够时会忽略这里填的名字。
        row["form"].setRowVisible(1, needs_style)
        self._fill_bucket(row, spec_key)
        self._sync_ok()

    def _fill_bucket(self, row, spec_key):
        """按类别换掉那一格的内容：回合事件 / 武器 / 投掷物。

        ⭐ 候选**从产品自己的表现读**（`resource_readback.known_buckets`），
        ⛔ 不在对话框里另抄一张武器名单 —— 抄出来那份从抄完就开始漂。
        """
        needed = bool(spec_key) and spec_key in NEEDS_BUCKET
        combo = row["round"]
        wanted = known_buckets(spec_key) if needed else None
        if row.get("bucket_for") != spec_key:
            row["bucket_for"] = spec_key
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("请选择…", "")
            if needed:
                if wanted:
                    for value in sorted(wanted):
                        combo.addItem(_bucket_label(spec_key, value), value)
                else:
                    # 投掷物这类产品不挑固定名字的，给一格自由填的提示项
                    combo.setEditable(True)
                    combo.lineEdit().setPlaceholderText("例如 flashbang / smoke")
            combo.blockSignals(False)
        if needed:
            label = NEEDS_BUCKET.get(spec_key, "分类")
            row["bucket_label"].setText(f"{label}：")
        row["form"].setRowVisible(2, needed)

    def _sync_ok(self, *_args):
        """⛔ 没选完不许点确定 —— 半套决定落盘比不落盘更难收拾。"""
        ready = True
        problem = ""
        for row in self._rows:
            spec_key = str(row["combo"].currentData() or "")
            if not spec_key:
                ready = False
                break
            if spec_key == "round_sounds" and not str(row["round"].currentData() or ""):
                ready = False
                break
            # ⚠⚠ 这一格原来**完全没查**：风格名清空照样能点确定，而那一组
            #   随后会被 `plan_placements` 判成"还缺风格名"整组丢掉，
            #   报告里只剩一行没有文件名的「未识别」—— 用户按了确定，
            #   什么都没发生，也没有任何一句话解释。
            # ⭐ 校验走产品自己的 `validate_style_name`（保留名、非法字符、
            #   首尾点号都在里面），⛔ 不在对话框里另写一套。
            if row["form"].isRowVisible(1):
                trouble = style_name_problem(row["style"].text())
                if trouble:
                    ready = False
                    problem = trouble
                    break
        if getattr(self, "_hint_label", None) is not None:
            self._hint_label.setText(problem)
            self._hint_label.setVisible(bool(problem))
        if getattr(self, "_ok_button", None) is not None:
            self._ok_button.setEnabled(ready)

    # ------------------------------------------------------------------ 结果

    def decisions(self):
        """`[{"paths": [...], "spec_key": ..., "style_name": ..., "bucket": ...}]`"""
        result = []
        for row in self._rows:
            spec_key = str(row["combo"].currentData() or "")
            if not spec_key:
                continue
            result.append({
                "paths": list(row["group"].paths),
                "spec_key": spec_key,
                "style_name": row["style"].text().strip(),
                "bucket": str(row["round"].currentData() or ""),
            })
        return result


#: 回合子事件的中文说法。⚠ **值**必须是产品认的那 8 个目录名，不能本地化 ——
#: 产品按目录名去找音频，写错一个字那一档就永远不响。
_ROUND_LABELS = {
    "start": "回合开始",
    "action": "自由活动结束（开打）",
    "win": "本回合胜利",
    "lose": "本回合失败",
    "mvp": "拿到 MVP",
    "match_start": "比赛开始",
    "match_end": "比赛结束",
    "halftime": "半场交换",
}
