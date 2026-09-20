# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-674（批 110）：「导入资源」页 —— 玩家手上拿着一个 zip，这一页把他引到哪。

外审在批 109 报了三条（各 3/3），逐条实测之后修的是这些：

1. **开局那一颗紫的是「选择文件夹」**，而社区站下下来的是 `资源标题.zip` ——
   这一页自己的注释就写着这句话，界面却把压缩包那个入口排在次位、次色。
2. **「扫描素材」是弱化的、却又是可点的**。RN-450 当年把它的高亮拿掉，
   理由逐字是「未选目录时它却是唯一高亮，极易诱导玩家开局盲点导致报错」——
   ⭐⭐⭐ 那只治了"诱导"，**没治"点了报错"**：那颗按钮一直可点，
   开局点下去弹一句「请先选择压缩包或目录」。
   **一条教训修掉了它的一种机制，另一种机制照样活着**（RN-673 同形）。
3. **「两处拖拽区打架」**。实测机制不是打架：四处 `acceptDrops` 全为真、
   拖哪儿都能用。真正的毛病是**三句话在抢一个谁都没画出来的位置** ——
   页头 / 源输入框占位 / 第 2 步那个 400px 的框各说一遍"可以拖进来"，
   而拖着文件在窗口上方晃一圈，**一个像素都不变**。
   ⇒ 少说一句（输入框那句撤了），并把剩下那一处**真的画出来**。

⭐⭐⭐ 而打开渲染图之后逮到第四条，它是上面第 3 条的机制本身：
`QTextEdit.setPlaceholderText` 在屏幕上**只画第一行**。那个框原来挂着四行占位，
于是「扫描只看不写」「也可以点上面的…」**一个像素都没有**，
而 `test_the_preview_box_says_what_will_appear_there` 一直在为它们打绿。
**判据量的是字符串，用户看的是像素**（RN-673 第二次）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QImage
from PySide6.QtWidgets import QMessageBox

REPO = Path(__file__).resolve().parent.parent
WIZARD = REPO / "pages" / "audio_import_wizard_page.py"


@pytest.fixture
def page(qapp, monkeypatch):
    import pages.audio_import_wizard_page as mod

    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: 0)
    widget = mod.AudioImportWizardPage()
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.resize(1080, 760)
    widget.show()
    for _ in range(3):
        qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


_ALIVE: list = []          # ⚠ 见下


def _urls_mime(tmp_path) -> QMimeData:
    """⚠⚠ 返回的 QMimeData **必须被 Python 这边拿住**。

    ⭐ 事件不持有它；一松手 Qt 侧就回收，而 PySide 会把一个光秃秃的 QObject
      还给 `event.mimeData()` —— 这条判据第一版就是这么把自己测红的，
      也正是它逮出了产品里那两处没防的手写拖拽处理（RN-674）。
    """
    sample = tmp_path / "社区资源包.zip"
    sample.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sample))])
    _ALIVE.append(mime)
    return mime


def _render(widget, qapp) -> QImage:
    for _ in range(3):
        qapp.processEvents()
    img = QImage(widget.size(), QImage.Format_ARGB32)
    widget.render(img)
    return img


def _pixel_diff(a: QImage, b: QImage) -> int:
    n = 0
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return n


def _colour_gap(a, b) -> int:
    """两个颜色差多少（曼哈顿距离）。⛔ 不用「相等/不等」——深色差深色也不等。"""
    return (abs(a.red() - b.red()) + abs(a.green() - b.green())
            + abs(a.blue() - b.blue()))


def _ink_rows(img: QImage) -> int:
    """图里有几段**连续的、画着东西的**横行 —— 也就是"看得见几行字"。

    ⭐ 底色取右下角（那块永远是空的），不写死颜色 —— 主题可以换。
    """
    bg = img.pixel(img.width() - 4, img.height() - 4)
    runs, inside = 0, False
    for y in range(2, img.height() - 2):
        inked = any(img.pixel(x, y) != bg for x in range(4, img.width() - 4, 2))
        if inked and not inside:
            runs += 1
        inside = inked
    return runs


# ---------------------------------------- ① 开局引到压缩包那条路


def test_the_opening_screen_points_at_the_archive_entry(page):
    """⭐ 开局那一颗紫的该是「选择压缩包 / 文件…」，不是「选择文件夹」。"""
    assert page.source_edit.text() == "", "阳性对照：这条量的是**还没选素材**那一屏"
    assert page.browse_archive_btn.objectName() == "primaryButton", (
        "开局的主按钮不是压缩包那个入口 —— 而玩家从社区站下下来的就是 zip。")
    assert page.browse_btn.objectName() == "secondaryButton"
    assert page.scan_btn.objectName() == "secondaryButton", (
        "没选素材时「扫描」又成了高亮 —— RN-450 逐字判过这会诱导玩家开局盲点。")


def test_the_scan_button_becomes_the_first_step_once_a_source_is_picked(page, qapp, tmp_path):
    page.source_edit.setText(str(tmp_path))
    qapp.processEvents()
    assert page.scan_btn.objectName() == "primaryButton"
    assert page.browse_archive_btn.objectName() == "secondaryButton", (
        "选好素材之后那一颗紫的还停在「选择压缩包」—— 主按钮必须是**当下**的第一步。")


def test_the_archive_entry_sits_before_the_folder_entry(page):
    """读序就是主次序：压缩包在左，文件夹在右。"""
    assert page.browse_archive_btn.x() < page.browse_btn.x(), (
        "「选择压缩包 / 文件…」排在「选择文件夹」右边 —— 主按钮不该藏在次按钮后面。")


def test_the_two_entries_are_built_in_the_order_they_are_shown(page):
    """⭐ 焦点链走**构造顺序**（`tab_order_audit.py`）——
    只调 `addWidget` 换位置会让 Tab 键的顺序和眼睛看到的顺序对不上。"""
    src = WIZARD.read_text(encoding="utf-8")
    assert src.index("self.browse_archive_btn = QPushButton") < src.index(
        "self.browse_btn = browse_btn = QPushButton"), (
        "压缩包那颗在屏幕上排前面，却在代码里后建 —— Tab 键会先跳到「选择文件夹」。")


# ---------------------------------------- ② 没东西可做的那一步，关掉


def test_scan_and_import_are_off_until_there_is_a_source(page):
    assert page.scan_btn.isEnabled() is False, (
        "没选素材时「扫描素材」仍可点 —— 点下去只会弹一句「请先选择压缩包或目录」。"
        "RN-450 当年只拿掉了它的高亮，没拿掉这条死胡同。")
    assert page.import_btn.isEnabled() is False, (
        "「开始导入」空点走的是同一个死胡同（`_run_import` 没报告就自己去扫描）。")
    for btn in (page.scan_btn, page.import_btn):
        assert btn.toolTip().strip(), (
            f"「{btn.text()}」被禁用了却不说为什么 —— "
            "一颗灰着又不解释的按钮，和一个坏掉的按钮长得一模一样。")


def test_the_page_does_not_repaint_the_disabled_state_by_itself(page):
    """⛔ 禁用态的**样子**不归这一页管（RN-150 已定全站口径）。

    ⚠⚠ 外审 S4 **3/3** 报「旁边两颗『打开…』比置灰的扫描更抢眼」——**现象是真的**：
    `#secondaryButton:disabled` 是 `background-color: transparent`，
    禁用之后屏幕上只剩一行灰字。
    ⭐⭐⭐ 但 `test_disabled_buttons_look_disabled.py` 逐字定过：次按钮启用/禁用
    都是透明露底，**差别在文字色和边框色上**。一页一页地改填充是绕开那条裁定，
    而且下一个主题就会漂。⇒ 真要改是主题层的事，单开一批带外审。

    ⚠ 我为此串行试了三版才停：① 选择器 `QPushButton:disabled` 特异度低一档，
    **设了不报错也不生效**；② 改成数"边上像素和内部不同"，深色边压深色底
    **数值不同而眼睛看不见**，判据绿在看不见的东西上；
    ③ 加了底色之后才发现 `ui_style_applier` 会把控件级样式整个抹掉
    （除非声明 `fp_keep_style`）—— 也就是说前两版**根本没跑在产品走的那条路上**。
    ⇒ 按 §0「同一件事三轮不稳就停」停下，这条判据钉住"已经停了"。
    """
    for btn in (page.scan_btn, page.import_btn):
        assert btn.styleSheet() == "", (
            f"「{btn.text()}」又被这一页单独刷了一层样式：{btn.styleSheet()!r} —— "
            "禁用态的样子归主题管（RN-150），页内覆盖会被 `ui_style_applier` 抹掉，"
            "而「抹掉」和「我改过了」在代码里长得一模一样。")


def test_they_come_back_on_the_moment_a_source_appears(page, qapp, tmp_path):
    page.source_edit.setText(str(tmp_path))
    qapp.processEvents()
    assert page.scan_btn.isEnabled() is True
    assert page.import_btn.isEnabled() is True
    assert page.scan_btn.toolTip() == "", "源选好了，那句「先选中素材」还挂在 tooltip 上"


def test_the_dead_end_these_judges_guard_is_really_there(page, monkeypatch):
    """⭐ 先验尺子：把禁用撤掉，空点「扫描」确实会撞上一句提示。

    ⛔ 不先证明"逮得住"，上面那两条只是"没人在看"（批 108 的教训）。
    """
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: said.append(a[2] if len(a) > 2 else ""))
    page.scan_btn.setEnabled(True)
    page.scan_btn.click()
    assert said and "请先选择" in str(said[0]), (
        f"空点扫描没有撞上那句提示（拿到 {said!r}）—— 那上面两条判据就没有对象了。")


# ---------------------------------------- ③ 投放区要看得见


def test_dragging_a_file_lights_up_the_drop_zone(page, qapp, tmp_path):
    """⛔ 不量 `styleSheet()` 那个字符串 —— 那是"我设过"，不是"看得见"。

    ⭐ RN-673 刚教过：`isVisible()` 为真不等于屏幕上看得见。⇒ 渲染成图，逐像素比。
    """
    box = page.preview_text
    calm = _render(box, qapp)
    qapp.sendEvent(page, QDragEnterEvent(box.rect().center(), Qt.CopyAction,
                                         _urls_mime(tmp_path), Qt.LeftButton, Qt.NoModifier))
    hot = _render(box, qapp)
    assert _pixel_diff(calm, hot) > 0, (
        "拖着文件经过这一页，屏幕上一个像素都没变 —— "
        "界面上三句话都在说「可以拖进来」，而投放区一处都没画出来（RN-674）。")


def test_the_highlight_goes_away_again(page, qapp, tmp_path):
    """离开和放下**都**要复原 —— 高亮留在屏上等于一直在说"松手即可放入"。"""
    box = page.preview_text
    mime = _urls_mime(tmp_path)
    calm = _render(box, qapp)

    qapp.sendEvent(page, QDragEnterEvent(box.rect().center(), Qt.CopyAction, mime,
                                         Qt.LeftButton, Qt.NoModifier))
    qapp.sendEvent(page, QDragLeaveEvent())
    assert _pixel_diff(calm, _render(box, qapp)) == 0, "拖出去之后高亮没撤"

    qapp.sendEvent(page, QDragEnterEvent(box.rect().center(), Qt.CopyAction, mime,
                                         Qt.LeftButton, Qt.NoModifier))
    qapp.sendEvent(page, QDropEvent(box.rect().center().toPointF(), Qt.CopyAction, mime,
                                    Qt.LeftButton, Qt.NoModifier))
    assert _pixel_diff(calm, _render(box, qapp)) == 0, "放下之后高亮没撤"


def test_the_highlight_colour_is_read_fresh_every_time(page, qapp, tmp_path, monkeypatch):
    """⛔ 颜色不许在 `__init__` 里算一份存着 —— 主题随时可换。

    （RN-672 那条「对话框 `setStyleSheet` 是构造时的快照」同族。）
    """
    import theme_manager

    monkeypatch.setattr(theme_manager, "get_color", lambda _name: "#0bada5")
    qapp.sendEvent(page, QDragEnterEvent(page.preview_text.rect().center(), Qt.CopyAction,
                                         _urls_mime(tmp_path), Qt.LeftButton, Qt.NoModifier))
    assert "#0bada5" in page.preview_text.styleSheet(), (
        "高亮颜色不是拖拽那一刻现取的 —— 换主题之后它会停在旧的品牌色上。")


def test_a_drop_anywhere_on_the_page_reaches_the_one_handler(page, qapp, tmp_path):
    """四处 `acceptDrops` 都为真，但**只能有一个** handler 干活。"""
    seen = []
    page._scan_source = lambda *_a, **_k: seen.append(1)
    for target in (page, page.source_edit, page.preview_text, page.preview_text.viewport()):
        page.source_edit.setText("")
        seen.clear()
        mime = _urls_mime(tmp_path)
        qapp.sendEvent(target, QDragEnterEvent(target.rect().center(), Qt.CopyAction, mime,
                                               Qt.LeftButton, Qt.NoModifier))
        qapp.sendEvent(target, QDropEvent(target.rect().center().toPointF(), Qt.CopyAction,
                                          mime, Qt.LeftButton, Qt.NoModifier))
        assert len(seen) == 1, (
            f"把素材放到 {type(target).__name__} 上，扫描触发了 {len(seen)} 次 —— "
            "0 次是放了没反应，2 次是同一个包被处理两遍。")
        assert page.source_edit.text().endswith(".zip")


def test_only_one_place_claims_to_be_the_drop_zone(page):
    """⭐ 两处都自称投放区，用户就得猜该往哪儿放（外审 3/3）。"""
    assert "拖" not in page.source_edit.placeholderText(), (
        f"源输入框又自称投放区了：{page.source_edit.placeholderText()!r} —— "
        "投放区只有一个（第 2 步那个框），而且它拖上去真会亮。")
    assert "拖到这里" in page.preview_text.toPlainText(), (
        "那个会亮的框反而不说自己是投放区了")


def test_the_source_placeholder_has_a_single_source(page, qapp):
    """⚠ 这一句原来在 `_init_ui` 和 `_on_mode_changed` 里各写一遍 ——
    而这个文件自己的注释就记着「改了一处等于没改」。"""
    before = page.source_edit.placeholderText()
    page.mode_combo.setCurrentIndex(1)          # 音频 → 视觉
    qapp.processEvents()
    after = page.source_edit.placeholderText()
    assert before != after and "视觉" in after, "换模式之后占位文案没跟着走"
    assert "拖" not in after, "换个模式，那句「也可以直接拖进来」就又回来了"

    tree = ast.parse(WIZARD.read_text(encoding="utf-8"))
    literals = [
        piece.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "setPlaceholderText"
        for arg in node.args
        for piece in ast.walk(arg)
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
    ]
    assert all("素材文件" not in text for text in literals), (
        f"源输入框的占位文案又被抄成字面量了：{literals!r}")


def test_a_reclaimed_mime_object_does_not_blow_up_the_event_loop(page, qapp):
    """⭐⭐⭐ 拿到的不一定是个像样的 QMimeData。

    Qt 侧对象被提前回收时 PySide 会还你一个光秃秃的 QObject；
    `dragEnterEvent` 直接点 `.hasUrls()` 就在 **Qt 的 notify 循环内部**
    抛 AttributeError —— 而那一侧连 try 都没有。
    ⚠ 这条判据不是想出来的：批 110 写上面那几条时，测试里的 QMimeData
      被回收了，产品当场抛了这个异常。
    """
    from PySide6.QtCore import QObject

    class _Degenerate:
        def mimeData(self):
            return QObject()            # ← 没有 hasUrls

        def acceptProposedAction(self):
            pass

        def ignore(self):
            pass

    page.dragEnterEvent(_Degenerate())  # 不许抛
    page.dropEvent(_Degenerate())       # 不许抛


def test_no_handwritten_drag_handler_touches_mimedata_directly():
    """⛔ 全仓扫一遍：手写的拖拽处理里不许再出现 `.mimeData().hasUrls()` 之类。

    ⭐ 防法在 `widgets/drop_import_mixin.py` 里躺了很久，而另外两处手写的
    **一处都没照做** —— 所以这条教训得是一条扫得到分母的判据，不是一段注释。
    """
    import os

    # ⛔ `.claude/` 底下是整个仓的**副本**（worktree 落脚处）——
    #   不排除它，每个文件会被数两遍，而这种污染只朝「有」的方向失效（RN-561）。
    skip = {".git", ".claude", "__pycache__", "node_modules", ".pytest_cache",
            "build", "dist"}
    offenders, scanned, handlers = [], 0, 0
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(root) / name
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            scanned += 1
            for node in ast.walk(tree):
                if not (isinstance(node, ast.FunctionDef)
                        and node.name in ("dragEnterEvent", "dragMoveEvent", "dropEvent")):
                    continue
                handlers += 1
                for piece in ast.walk(node):
                    if (isinstance(piece, ast.Call)
                            and getattr(piece.func, "attr", None) == "mimeData"):
                        offenders.append(f"{path.relative_to(REPO)}::{node.name}")
    assert scanned > 100, f"只扫到 {scanned} 个 .py —— 这条判据没有分母"
    assert handlers >= 3, (
        f"全仓只找到 {handlers} 个手写拖拽处理 —— 少于批 110 当时的 4 个，"
        "要么被删了要么改名了，这条判据的分母得重新核一遍")
    assert not offenders, (
        "这些手写拖拽处理直接点了 `event.mimeData()`，"
        f"没走 `urls_from_drop`（RN-674）：{sorted(set(offenders))}")


# ---------------------------------------- ④ 空状态要**整段**看得见


def test_the_empty_state_is_all_on_screen(page, qapp):
    """⭐⭐⭐ `setPlaceholderText` 只画得出第一行 —— 所以空状态走正文。"""
    box = page.preview_text
    # ⚠ 三段，不是四段：紧凑档只露得出一行多一点，所以「只看不写」并回了首行，
    #   让切口落在空行上（S3 3/3 报过一次「第二行被底栏切成两半」）。
    assert _ink_rows(_render(box, qapp)) >= 3, (
        "第 2 步那个框只画得出一两行 —— 那几句话又回到占位里去了，"
        "而占位在屏幕上只有第一行（RN-674）。")
    for must in ("拖到这里", "不用先解压", "只看不写"):
        assert must in box.toPlainText(), f"空状态里没有「{must}」"


def test_this_ruler_would_catch_the_placeholder_way(page, qapp):
    """⭐ 先验：把空状态改回"四行占位"的写法，上面那条判据必须当场红。

    ⛔ 不先证明"逮得住"，「≥4 行」只是"没人在看"。
    """
    box = page.preview_text
    four_lines = "第一行\n\n第二行\n\n第三行\n\n第四行"
    box.setPlainText("")
    box.setPlaceholderText(four_lines)
    rows = _ink_rows(_render(box, qapp))
    assert rows <= 2, (
        f"占位文案居然画出了 {rows} 段 —— 那 Qt 的行为变了，"
        "RN-674 整条推理的前提（占位只画第一行）要重新验一遍。")


def test_switching_mode_does_not_blank_the_big_box(page, qapp):
    """⚠ 原来是 `clear()` —— 换个模式，RN-520 修掉的纯黑框就原地复活。"""
    page.mode_combo.setCurrentIndex(2)          # → 全部
    qapp.processEvents()
    assert page.preview_text.toPlainText().strip(), (
        "换了导入模式，第 2 步又变回一整块什么都不说的黑框（RN-520 只修了开局那一次）。")


# ---------------------------------------- ⑤ 分母守卫


def test_the_widgets_these_judges_watch_are_all_here(page):
    """⛔ 控件改名/搬家时，上面那些判据要当场红，不许静静地少量几条。"""
    for name in ("source_edit", "browse_btn", "browse_archive_btn",
                 "scan_btn", "import_btn", "preview_text", "mode_combo"):
        assert hasattr(page, name), f"这一页不再有 `{name}` —— RN-674 的判据少了对象"
    assert page.browse_archive_btn.text() == "选择压缩包 / 文件…"
    assert page.scan_btn.text() == "扫描素材"
