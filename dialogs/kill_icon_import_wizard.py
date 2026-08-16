# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标导入小窗（KI-7）：**最多问一个问题**。

KI-7 之前，"把一张图变成击杀图标"这件事散在三个地方：页面上拖一下走一条路、
「导入图标包…」按钮走一条路、「高级导入 / 批量」对话框里又是一整套风格下拉 +
等级下拉 + 裁边 + 抠背景 + 行列。三条路问的问题不一样，出的错也不一样。

现在收成一个入口：不管拖进来的是 zip / gif / webp / apng / png 序列文件夹 /
单张图，都到这里。这里只问一句「用在几杀」，其余全部自己判：

| 以前要用户回答 | 现在 |
|---|---|
| 用在几杀 | 文件名认得出来就预选好（`3hs.gif` → 3 杀 · 爆头） |
| 是不是爆头素材 | 同上，从文件名的 `hs`/`headshot`/`爆头` 认 |
| 要不要裁透明边 | 自动（并集包围盒，见 `core/kill_icon_import`） |
| 要不要抠掉纯色背景 | 自动（`analyze_frames` 判纯色底才抠） |
| 帧率 / 定格多久 | 自动（动图读原始 duration；静态图给默认定格时长） |
| 图集几行几列 | 自动（同名 JSON 优先；`guess_grid` 只认无歧义的） |

判错了怎么办：去素材工坊改。**能力一条没删，只是从"问用户"改成"自己做"。**

⚠ 探测走 `probe_source(analyze=False)`：`analyze=True` 要把整套帧解出来读像素，
600 帧的素材会让这个小窗卡在打开那一下。抠背景/裁边的判断留到真正导入时
（那一步本来就在后台线程上）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout
)

from core.kill_icon_import import (
    KillIconImportError, parse_level_name, probe_source
)
from core.kill_icon_library import LEVELS
from widgets.kill_icon_style_strip import KillIconStyleThumb

#: 认出等级时的默认落点。认不出来就用它——5 杀是最常单独换的那一格。
FALLBACK_LEVEL = 5

LEVEL_LABELS = {1: "1 杀", 2: "2 杀", 3: "3 杀", 4: "4 杀", 5: "5 杀 · ACE"}

KIND_LABELS = {
    "animation": "动图",
    "sequence": "PNG 帧序列",
    "spritesheet": "图集",
}


def describe_probe(probe) -> str:
    """一句话说清"我认出了什么"。用户据此判断要不要继续。"""
    kind = KIND_LABELS.get(getattr(probe, "kind", ""), "素材")
    frames = int(getattr(probe, "frame_count", 0) or 0)
    width = int(getattr(probe, "frame_width", 0) or 0)
    height = int(getattr(probe, "frame_height", 0) or 0)
    if frames <= 1:
        hold = float(getattr(probe, "hold_seconds", 0.0) or 0.0)
        timing = f"定格 {hold:.1f} 秒" if hold else "单帧"
        return f"认出来了：{kind} · 静态图 · {width}x{height} · {timing}"
    return (f"认出来了：{kind} · {frames} 帧 · {width}x{height} · "
            f"约 {getattr(probe, 'duration', 0.0):.1f} 秒")


def guess_target(path):
    """从文件名猜 `(kills, variant)`。猜不出来返回 `(FALLBACK_LEVEL, "")`。

    目录也认：帧序列的形态就是一个文件夹，名字通常就是 `3` 或 `3hs`。
    """
    name = os.path.basename(str(path).rstrip("\\/"))
    parsed = parse_level_name(name)
    if parsed is None:
        return (FALLBACK_LEVEL, "", False)
    kills, variant = parsed
    return (kills, variant, True)


class KillIconImportWizard(QDialog):
    """一个素材 → 一个等级。只问「用在几杀」。

    用法：

        wizard = KillIconImportWizard(path, parent=page)
        if wizard.exec() == QDialog.Accepted:
            kills, variant = wizard.target

    构造时就会探测；探测失败会抛 `KillIconImportError`，由调用方翻成提示条
    （**不要**在这里弹第二个模态框说"打不开"——用户点一次导入不该看两个窗）。
    """

    def __init__(self, path, parent=None, kills=None, variant=""):
        super().__init__(parent)
        self.path = str(path)
        self.probe = probe_source(self.path)      # 失败就往上抛，调用方翻译

        guessed_kills, guessed_variant, self.guessed = guess_target(self.path)
        self._kills = int(kills if kills is not None else guessed_kills)
        self._variant = str(variant or guessed_variant)

        self.setWindowTitle("导入击杀图标")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        self.summary_label = QLabel(describe_probe(self.probe))
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.thumb = KillIconStyleThumb(self, box=(132, 84))
        self.thumb.set_image(self._load_thumbnail(), placeholder="无预览")
        body.addWidget(self.thumb, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(6)

        target_row = QHBoxLayout()
        target_row.setSpacing(8)
        target_row.addWidget(QLabel("用在"))
        self.level_combo = QComboBox()
        self.level_combo.setMinimumWidth(150)
        # userData 存**字符串**不存元组：`findData` 走的是 QVariant 比较，
        # 元组过一趟 QVariant 之后 `findData((3, "hs"))` 恒返回 -1，
        # 于是"按文件名预选"会静默退回第一项。而 `target` 那时读的是自己存的
        # 字段，判据照样绿——**下拉里显示的和真正会导入的等级对不上，零症状**。
        for kills_value in LEVELS:
            self.level_combo.addItem(LEVEL_LABELS[kills_value], f"{kills_value}")
            self.level_combo.addItem(f"{LEVEL_LABELS[kills_value]} · 爆头专属",
                                     f"{kills_value}hs")
        index = self.level_combo.findData(f"{self._kills}{self._variant}")
        self.level_combo.setCurrentIndex(max(0, index))
        self.level_combo.currentIndexChanged.connect(self._on_target_changed)
        self._on_target_changed()      # 以下拉里选中的那一项为准，不以字段为准
        target_row.addWidget(self.level_combo)
        target_row.addStretch()
        right.addLayout(target_row)

        self.guess_label = QLabel("")
        self.guess_label.setObjectName("hintLabel")
        self.guess_label.setWordWrap(True)
        self.guess_label.setText(
            f"按文件名认出来的，不对就在上面改。（{os.path.basename(self.path)}）"
            if self.guessed else
            "文件名里看不出用在几杀，帮它选一个。"
        )
        right.addWidget(self.guess_label)

        self.warning_label = QLabel("")
        self.warning_label.setObjectName("hintLabel")
        self.warning_label.setWordWrap(True)
        warnings = list(getattr(self.probe, "warnings", []) or [])
        if warnings:
            self.warning_label.setText("\n".join(f"⚠ {w}" for w in warnings[:2]))
        else:
            self.warning_label.hide()
        right.addWidget(self.warning_label)
        right.addStretch()

        body.addLayout(right, 1)
        layout.addLayout(body)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Ok).setText("导入")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    # ------------------------------------------------------------------ 状态

    @property
    def target(self):
        return (self._kills, self._variant)

    def _on_target_changed(self, _index=None):
        """真源是下拉里选中的那一项。字段只是它的缓存。"""
        data = str(self.level_combo.currentData() or "")
        if not data:
            return
        variant = "hs" if data.endswith("hs") else ""
        digits = data[: -len(variant)] if variant else data
        if digits.isdigit():
            self._kills, self._variant = int(digits), variant

    def _load_thumbnail(self):
        """第一帧当预览。**读不出来就算了**——预览没有比导入更重要。

        这里不复用 `load_level_thumbnail`：那个走的是"已入库的风格资源"的
        路径，而这里手上是一个还没入库的任意文件。
        """
        from PySide6.QtGui import QImage

        path = self.path
        if os.path.isdir(path):
            from core.kill_icon_import import _sorted_sequence_files

            try:
                files = _sorted_sequence_files(path)
            except Exception:
                return None
            path = files[0] if files else ""
        if not path or not os.path.isfile(path):
            return None
        image = QImage(path)
        return None if image.isNull() else image


def wizard_target_for(path, parent=None):
    """开一次小窗，返回 `(kills, variant)`；用户取消返回 None。

    探测异常原样往上抛，调用方翻成页内提示条。
    """
    wizard = KillIconImportWizard(path, parent=parent)
    if wizard.exec() != QDialog.Accepted:
        return None
    return wizard.target


__all__ = [
    "FALLBACK_LEVEL",
    "KillIconImportError",
    "KillIconImportWizard",
    "describe_probe",
    "guess_target",
    "wizard_target_for",
]
