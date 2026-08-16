# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-7：击杀图标导入小窗——**最多问一个问题**。

KI-7 之前"把一张图变成击杀图标"散在三个入口：页面上拖一下、「导入图标包…」
按钮、「高级导入 / 批量」对话框。三条路问的问题不一样，出的错也不一样。
其中那个高级对话框上摆着风格下拉 + 等级下拉 + 裁边 + 抠背景 + 行列 ——
一个只想换套图标的人被迫先学会这套词汇。

现在收成一个入口，只问「用在几杀」；文件名认得出来（`3hs.gif`）连这一句
都预选好。裁边、抠背景、帧率、定格时长全部自动判。

⚠ 这份文件里**不许 `exec()` 这个小窗**：`QDialog.exec` 是模态的，测试进程里
没人去点，表现是整个 pytest 卡死（不是失败）。所以判据只碰构造出来的对象
和那几个纯函数。
"""
from __future__ import annotations

import os

import pytest
from PIL import Image

from dialogs.kill_icon_import_wizard import (
    FALLBACK_LEVEL, KillIconImportWizard, describe_probe, guess_target
)


def _write_gif(path, frames=4, size=(24, 18)):
    images = []
    for index in range(frames):
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        image.putpixel((index % size[0], 1), (255, 0, 0, 255))
        images.append(image.convert("P"))
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=100, loop=0, disposal=2)
    return str(path)


def _write_png(path, size=(20, 16)):
    Image.new("RGBA", size, (10, 200, 90, 255)).save(path)
    return str(path)


# ==================================================== 1. 从文件名认等级


@pytest.mark.parametrize("name,expected", [
    ("5.gif", (5, "", True)),
    ("3hs.webp", (3, "hs", True)),
    ("ace.png", (5, "", True)),
    ("双杀.png", (2, "", True)),
    ("headshot_4.png", (FALLBACK_LEVEL, "", False)),   # 前缀式不在别名表里
    ("我随便起的名字.webp", (FALLBACK_LEVEL, "", False)),
])
def test_the_level_is_guessed_from_the_file_name(name, expected):
    """认得出来就别问。社区素材包里文件名几乎都带等级。"""
    assert guess_target(f"C:/tmp/{name}") == expected


def test_a_folder_name_is_guessed_too(tmp_path):
    """帧序列的唯一形态就是文件夹，名字通常就是 `3` 或 `3hs`。

    ⚠ 判据要用**真的目录路径**：`guess_target` 会先剥掉末尾的分隔符，
    传一个假路径的话这一步永远走不到。
    """
    folder = tmp_path / "3hs"
    folder.mkdir()
    assert guess_target(str(folder)) == (3, "hs", True)
    assert guess_target(str(folder) + os.sep) == (3, "hs", True)


def test_an_unrecognised_name_still_lands_somewhere_sane():
    """认不出来也得给个默认值，不能把下拉留空让用户面对一个空框。"""
    kills, variant, guessed = guess_target("C:/tmp/whatever.webp")
    assert kills == FALLBACK_LEVEL and variant == "" and guessed is False


# ==================================================== 2. 一句话说清认出了什么


def test_the_summary_says_kind_frames_and_duration(tmp_path):
    path = _write_gif(tmp_path / "5.gif", frames=6)
    from core.kill_icon_import import probe_source

    text = describe_probe(probe_source(path))
    assert "动图" in text
    assert "6 帧" in text
    assert "24x18" in text


def test_a_static_image_is_described_as_a_hold_not_a_frame_rate(tmp_path):
    """静态图没有"速度"这回事，说"6 帧 @30FPS"只会让人困惑。"""
    path = _write_png(tmp_path / "boom.png")
    from core.kill_icon_import import probe_source

    text = describe_probe(probe_source(path))
    assert "静态图" in text
    assert "定格" in text
    assert "FPS" not in text


# ==================================================== 3. 小窗本身


def test_the_wizard_preselects_the_guessed_level(qapp, tmp_path):
    """认出来了就把下拉预选好——用户直接点「导入」，等于一个问题都没问。"""
    wizard = KillIconImportWizard(_write_gif(tmp_path / "3hs.gif"))
    assert wizard.target == (3, "hs")
    assert wizard.guessed is True
    assert "按文件名认出来的" in wizard.guess_label.text()
    wizard.deleteLater()


def test_the_wizard_says_so_when_it_could_not_guess(qapp, tmp_path):
    wizard = KillIconImportWizard(_write_gif(tmp_path / "随便.gif"))
    assert wizard.target == (FALLBACK_LEVEL, "")
    assert wizard.guessed is False
    assert "看不出" in wizard.guess_label.text()
    wizard.deleteLater()


def test_changing_the_dropdown_changes_the_target(qapp, tmp_path):
    """下拉改了，`target` 得跟着改——不然那一个问题问了也白问。"""
    wizard = KillIconImportWizard(_write_gif(tmp_path / "5.gif"))
    index = wizard.level_combo.findData("2hs")
    assert index >= 0, "下拉里没有「2 杀 · 爆头专属」这一项"
    wizard.level_combo.setCurrentIndex(index)
    assert wizard.target == (2, "hs")
    wizard.deleteLater()


def test_the_dropdown_actually_shows_the_guessed_level(qapp, tmp_path):
    """**下拉里选中的那一项**必须就是会导入的那一格。

    第一版判据只看 `wizard.target`，而它读的是构造时算好的字段——下拉预选
    失败（`findData` 拿元组比 QVariant 恒 -1、静默退回第一项）时判据照样绿，
    用户看到的却是「1 杀」而实际会导入到 3 杀。**判据要读用户看见的那一份。**
    """
    wizard = KillIconImportWizard(_write_gif(tmp_path / "3hs.gif"))
    assert wizard.level_combo.currentData() == "3hs"
    assert "3 杀" in wizard.level_combo.currentText()
    assert "爆头" in wizard.level_combo.currentText()
    assert wizard.target == (3, "hs")
    wizard.deleteLater()


def test_every_level_and_variant_is_reachable_from_the_dropdown(qapp, tmp_path):
    """五个等级 × 普通/爆头 = 十项，一项都不能少。

    少一项的后果是"某个格子只能从工坊里换"，而用户不会知道为什么。
    """
    wizard = KillIconImportWizard(_write_png(tmp_path / "x.png"))
    reachable = {wizard.level_combo.itemData(i)
                 for i in range(wizard.level_combo.count())}
    assert reachable == {f"{k}{v}" for k in range(1, 6) for v in ("", "hs")}
    wizard.deleteLater()


def test_warnings_are_shown_up_front_not_after_the_fact(qapp, tmp_path):
    """GIF 的硬白边要在**按下导入之前**说，导完再说就晚了。"""
    wizard = KillIconImportWizard(_write_gif(tmp_path / "5.gif"))
    assert wizard.warning_label.isVisibleTo(wizard) is True
    assert "GIF" in wizard.warning_label.text()
    wizard.deleteLater()


def test_a_clean_source_does_not_show_an_empty_warning_box(qapp, tmp_path):
    """没警告就别留一个空框在那儿——空控件也是复杂度。"""
    path = tmp_path / "5.webp"
    frames = [Image.new("RGBA", (20, 16), (0, 0, 0, 0)) for _ in range(4)]
    for index, frame in enumerate(frames):
        frame.putpixel((index, 1), (255, 255, 255, 255))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=100, loop=0)

    wizard = KillIconImportWizard(str(path))
    assert wizard.warning_label.isHidden() is True
    wizard.deleteLater()


def test_the_wizard_shows_a_thumbnail(qapp, tmp_path):
    """看得见才敢按。小窗上没有预览的话，用户只能靠文件名赌。"""
    wizard = KillIconImportWizard(_write_png(tmp_path / "5.png"))
    assert wizard.thumb.has_image is True
    wizard.deleteLater()


def test_an_unreadable_source_raises_instead_of_opening_a_broken_window(qapp, tmp_path):
    """探测失败就别开窗——调用方会把这句话翻成页内提示条。

    开一个"什么都没有"的小窗再让用户点取消，是最差的那种反馈。
    """
    from core.kill_icon_import import KillIconImportError

    bad = tmp_path / "clip.mp4"
    bad.write_bytes(b"not really a video")
    with pytest.raises(KillIconImportError) as excinfo:
        KillIconImportWizard(str(bad))
    # 而且这句话要给出路，不能只说"不支持"
    assert "WebP" in str(excinfo.value) or "ffmpeg" in str(excinfo.value)


# ==================================================== 4. 不许再问多余的问题


def test_the_wizard_asks_exactly_one_question(qapp, tmp_path):
    """棘轮：小窗上只许有一个输入控件。

    这是 KI-7 的核心承诺。想加"顺手也让用户选一下要不要裁边"的时候，
    这条会先红——那些选项属于素材工坊。
    """
    from PySide6.QtWidgets import (
        QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QSlider, QWidget
    )

    wizard = KillIconImportWizard(_write_gif(tmp_path / "5.gif"))
    # PySide 的 findChildren 只吃**一个**类型，给元组会抛 TypeError。
    # 拿全部子控件再自己筛，同时也就不会漏掉子类。
    inputs = [
        w for w in wizard.findChildren(QWidget)
        if isinstance(w, (QComboBox, QSlider, QLineEdit, QAbstractSpinBox))
        # QComboBox 内部自带一个 QLineEdit 之类的子控件，只数直接摆出来的那些
        and w.parent() is not None
        and not isinstance(w.parent(), (QComboBox, QAbstractSpinBox))
    ]
    assert len(inputs) == 1, (
        f"小窗上有 {len(inputs)} 个输入控件："
        f"{[type(w).__name__ for w in inputs]}。KI-7 说好最多问一个问题，"
        f"裁边/抠背景/行列这些属于素材工坊。"
    )
    # 按钮只许有确定与取消两个（QDialogButtonBox 自带）
    buttons = [b for b in wizard.findChildren(QAbstractButton) if b.isVisibleTo(wizard)]
    assert len(buttons) <= 2, f"小窗上有 {len(buttons)} 个按钮：{[b.text() for b in buttons]}"
    wizard.deleteLater()


def test_probing_does_not_decode_every_frame(monkeypatch, tmp_path):
    """小窗打开那一下不许把整套帧解出来。

    `probe_source(analyze=True)` 要读像素做"要不要抠背景/裁边"的判断，那是
    整套解码——600 帧的素材会让小窗卡在打开那一刻。这条钉住调用参数：
    抠背景/裁边的判断留到真正导入时（那一步本来就在后台线程上）。
    """
    import dialogs.kill_icon_import_wizard as wizard_module

    seen = {}

    def _spy(path, *args, **kwargs):
        seen["analyze"] = kwargs.get("analyze", False)
        from core.kill_icon_import import probe_source as real

        return real(path, *args, **kwargs)

    monkeypatch.setattr(wizard_module, "probe_source", _spy)
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:      # 纯函数路径也要能单跑
        QApplication([])
    wizard = KillIconImportWizard(_write_gif(tmp_path / "5.gif"))
    assert seen.get("analyze") is False, "小窗把整套帧解了一遍"
    wizard.deleteLater()
