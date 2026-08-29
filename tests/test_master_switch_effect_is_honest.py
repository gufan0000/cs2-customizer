# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-407（批 16）：**总开关关着的时候，整页要停止假装已经生效。**

## 这条不是「把开关做大」

立案写的是「总开关默认关闭且**不够醒目**」。批 14 做了一次方案调研，
把那句话推翻了 —— 「开关不够醒目」在那一轮里**排最后**（3/4 中），
而候选 C 一上它就**消失了**（0 发）。真正的主诉是**同一屏上有三处在同时暗示
「已经生效」**：

| 主诉 | 现状 A | 只改预览的候选 C |
|---|---|---|
| 底栏「改动已自动保存，不用点任何按钮」 | 4/4 高 | **6/6 高** |
| 参数区全高亮、未置灰 ⇒ 以为在运行 | 4/4 高 | **6/6 高** |
| 预览框 | 4/4 高「仍渲染绿准心」 | **6/6 高「失去反馈，与底栏矛盾」** |

⭐⭐⭐ **改掉其中一处不会降低那个印象，只会制造一处矛盾。**
候选 C 把预览改诚实之后，底栏那句就成了屏幕上**唯一还在撒谎**的东西，
外审当场读成「认知冲突，不知所措」——**票数不降反升**。

⇒ 三件一起做，缺一不可：
  ① 底栏回执**带上前提**；
  ② 参数区**降权**（⚠ **不是禁用** —— RN-179 记过「188 个控件可点却没反应」，
     要的是「**可调，但明说不生效**」）；
  ③ 预览**说出后果**（⚠ 不是把预览关掉 —— 那正是候选 C 造出矛盾的那一步）。

⚠⚠ 底栏那句回执是**批 10 我自己加的**（RN-174 的修法之一）。它在总开关开着时
是真话，关着时是假话 —— ⭐ **一句只在某个状态下为真的回执，在别的状态里就是一句谎。**

## 这份判据在防什么

1. **三句话只有一份**（抄进页面就会各自漂）；
2. **每一页都真的被管到**（不是只有我改过的那几页）；
3. **降权不等于禁用**（RN-179）；
4. **属性有人消费**（QSS 里没有对应选择器的话，`masterOff` 就是个空转属性——
   判据全绿而屏幕上一个像素都没变）；
5. **扫描器自己没瞎**（本会话已经有两次「判据只扫到 22/28 页还报绿」）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from widgets import master_switch_effect as eff        # noqa: E402
from widgets.page_action_bar import PageActionBar      # noqa: E402

# ⭐ **故意 import，不抄。** 「哪些页有就地总开关」这份分母的真源是
# `test_master_switch_row.EXPECTED_KEYS`；在这里抄一份的话，下次有人加一页
# 只会改那一份，而这一份**永远绿着**（同 RN-198 那条「抄了修好之前的版本」）。
from test_master_switch_row import EXPECTED_KEYS       # noqa: E402

#: 有**静态预览面**的页 —— 只有它们能做第③件事。
#: 其余的页不是"漏了"，是**没有可说后果的东西**（screen_effects 的「预览」是
#: 底栏两颗按钮，是一个动作而不是一块常驻画面）。
PAGES_WITH_A_PREVIEW = {
    "crosshair": "preview_frame",          # 156×156 的静态准心预览框
    "flash": "basic_preview_widget",       # FlashPreviewWidget 实时合成
    "kill_icon": "hero_preview",           # KillIconPreview 播当前图标
}


# ============================================================ 一、文案只有一份


def _page_sources() -> list[Path]:
    return sorted((REPO / "pages").glob("*.py"))


def _string_constants(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_the_three_sentences_have_exactly_one_source():
    """⭐ 三句话谁都不许自己抄一份。

    抄一份的后果不是"重复"，是**两份会分头漂**：批 10 抄进 crosshair 判据的
    那份 `CLICK_CONTEXT` 抄的是**修好之前**的版本，于是它红不起来。
    """
    sentences = (eff.NOTICE_OFF_TEXT, eff.ACTION_BAR_ON_TEXT,
                 eff.ACTION_BAR_OFF_TEXT, eff.PREVIEW_ON_TEXT,
                 eff.PREVIEW_OFF_TEXT)
    offenders = []
    for path in _page_sources():
        for lineno, value in _string_constants(path):
            for sentence in sentences:
                if sentence and sentence in value:
                    offenders.append((path.name, lineno, value[:40]))
    assert not offenders, (
        f"这几页把 master_switch_effect 里的句子抄了一份：{offenders}\n"
        "⭐ 抄一份不是问题，抄了「修好之前的版本」才是——统一从模块里取。")


def test_the_off_copy_says_the_consequence_not_the_direction():
    """⭐⭐ 说**后果**，不说**去哪**。

    RN-144 那一轮外审的原话：「需要额外文字硬指引 ⇒ 总开关层级与可见性严重不足，
    属于**打补丁式的无效引导**」。批 10 又试了一次「把前提写进文案」，
    票数**一票没少**。⇒ 指路是症状，不是修法。
    """
    for text in (eff.NOTICE_OFF_TEXT, eff.ACTION_BAR_OFF_TEXT, eff.PREVIEW_OFF_TEXT):
        assert "游戏里" in text, f"没说后果落在哪儿：{text}"
        for direction in ("右上角", "左上角", "下面那张", "页面底部", "基础设置"):
            assert direction not in text, (
                f"这句在指路而不是说后果：{text}（出现了「{direction}」）\n"
                "⭐ 需要用文字指路的控件，就是放错了地方。")


def test_the_off_copy_promises_the_controls_still_work():
    """⚠ RN-179：**降权不是禁用。**

    那一轮实测过「188 个控件可点却没反应」。这一次要的是
    「**可调，但明说不生效**」—— 所以这句话必须**自己说出**「还能调、还会存」。
    """
    text = eff.NOTICE_OFF_TEXT
    assert "保存" in text, f"没说「改了还会存下来」：{text}"
    assert "不生效" in text, (
        f"没说「现在不生效」：{text}\n"
        "⭐ 这三个字是唯一对听觉/视觉/行为都成立的说法，见下面那条判据。")
    assert len(text) <= 24, (
        f"这句话有 {len(text)} 个字，塞不进开关行剩下的那段横向空间：{text}\n"
        "⭐ 它必须**在同一行上**说完 —— 换行就要长高，而紧凑档没有那 20px。")
    assert any(w in text for w in ("照常", "可以调", "照调")), (
        f"没说「现在仍然可以调」：{text}\n"
        "不说的话它读起来就是「这一片废了」，那正是 RN-179 那条缺陷。")


def test_the_sitewide_sentences_do_not_pick_a_sense():
    """⭐⭐⭐ **一句要铺到全站的文案，不许挑一种感官说话。**

    ⚠ 第一版写的是「…但游戏里现在**看不到**」。这句话铺在 15 页上，
    其中 **8 页是音效**（枪声 / 被击杀 / 击杀 / 换弹 / 切枪 / 音乐 / 语音 / 特殊）。
    外审复跑跨页复现、措辞独立：

        「枪声设置页却提示『游戏里现在看不到』，玩家会下意识认为
          『枪声本来就看不到、只要听得到就行』…**反向佐证了枪声已生效**」

    ⇒ 它不是「说得不够准」，是**给了玩家一个把整条警告判为「与我无关」的理由**。
    ⭐ 「不生效」对听觉、视觉、行为一样成立。

    ⚠ 预览那句话**不在这条判据里**：它只挂在真的有画面的三页上
    （crosshair / flash / kill_icon），那里说「看不到」是精确的。
    """
    for name, text in (("NOTICE_OFF_TEXT", eff.NOTICE_OFF_TEXT),
                       ("ACTION_BAR_OFF_TEXT", eff.ACTION_BAR_OFF_TEXT),
                       ("ACTION_BAR_ON_TEXT", eff.ACTION_BAR_ON_TEXT)):
        for sense in ("看不到", "看不见", "听不到", "听不见", "显示不出"):
            assert sense not in text, (
                f"{name} 里出现了只对一种感官成立的说法「{sense}」：{text}\n"
                "⭐ 这句话同时铺在画面页和音效页上。")


def test_the_negation_comes_first_in_the_off_receipt():
    """⭐⭐ **写在转折之后的否定，等于没写。**

    第一版是「改动已自动保存，但总开关关着——游戏里现在还看不到。」
    外审复跑跨页 6 发以上同一条判词：
    「视线只扫到前七个字『改动已自动保存』，**不会去读破折号后面的补充说明**」。
    """
    text = eff.ACTION_BAR_OFF_TEXT
    head = text[:8]
    assert "总开关" in head or "不生效" in head, (
        f"这句回执的前 8 个字里没有否定：{text}\n"
        "⭐ 读的人在读到转折之前就走了。")
    assert not text.startswith("改动已自动保存"), (
        f"又以「改动已自动保存」开头了：{text}")


def test_the_on_copy_answers_the_question_the_off_copy_answers():
    """⭐ 开着的时候也要有回执。

    批 10 加那句「改动已自动保存」是为了回答一个 **5/6 票**的困惑
    （「我改的东西保存了吗」）。这一批把那句话收进 `PageActionBar`，
    **不许顺手把那个回答弄丢**。
    """
    assert "保存" in eff.ACTION_BAR_ON_TEXT or "生效" in eff.ACTION_BAR_ON_TEXT
    assert "按钮" in eff.ACTION_BAR_ON_TEXT, (
        f"开着的时候没回答「要不要点什么按钮」：{eff.ACTION_BAR_ON_TEXT}")


# ==================================================== 二、底栏回执（第①件）


class _FakeRow:
    """一颗只会报「我开着没」的假开关行。"""

    def __init__(self, checked):
        self.checked = checked

    def is_checked(self):
        return self.checked


def _bar_on_a_fake_page(checked):
    """一张挂着总开关的假页面 + 它的底栏。

    ⭐ 走的是**真的那条解析路**（底栏自己往上找那颗开关），
    而不是塞一个布尔进去 —— 塞布尔的判据证明不了产品里那条路通不通。
    """
    page = QWidget()
    page.master_switch_row = _FakeRow(checked)
    layout = QVBoxLayout(page)
    bar = PageActionBar(page)
    layout.addWidget(bar)
    return page, bar


def test_the_action_bar_receipt_follows_the_master_switch(qapp):
    page, bar = _bar_on_a_fake_page(True)
    bar.set_message("当前样式：十字。")
    assert eff.ACTION_BAR_ON_TEXT in bar.message_label.text()
    assert "当前样式：十字。" in bar.message_label.text()

    page.master_switch_row.checked = False
    bar.refresh_effect_state()
    assert eff.ACTION_BAR_OFF_TEXT in bar.message_label.text(), (
        "拨了总开关，底栏那句回执没跟着变 —— "
        "⭐ 一句只在某个状态下为真的回执，在别的状态里就是一句谎。")
    assert "当前样式：十字。" in bar.message_label.text(), "页面自己那段状态被吃掉了"
    page.deleteLater()


def test_the_receipt_needs_no_one_to_come_and_tell_it(qapp):
    """⭐⭐ **回执的真源是那颗开关自己，不是「有没有人通知过我」。**

    第一版把状态存成一个布尔，由 `MasterSwitchRow` 在 `singleShot(0)` 里拨过来
    —— 于是「页面刚建好、事件循环还没转」的那一瞬间底栏一个字都不说。
    ⚠ 那不是少刷新一次，是**回执的正确性依赖了一次时序**（同 RN-417）。
    这条判据**一次都不调 refresh**：建完就该是对的。
    """
    page, bar = _bar_on_a_fake_page(False)
    bar.set_message("状态。")
    assert eff.ACTION_BAR_OFF_TEXT in bar.message_label.text()
    page.deleteLater()


def test_the_receipt_survives_the_page_writing_a_new_message(qapp):
    """⚠ 页面会在**任意时刻**再调一次 `set_message` —— 回执不能被它冲掉。

    ⭐⭐ **一条守卫的输入如果能被一次常规操作顺手改写，那条守卫就不是守卫**
    （RN-419）。这里的常规操作就是页面自己的 `_sync_action_bar`。
    """
    page, bar = _bar_on_a_fake_page(False)
    for text in ("第一次", "第二次", "第三次"):
        bar.set_message(text)
        assert eff.ACTION_BAR_OFF_TEXT in bar.message_label.text(), (
            f"页面写了一次「{text}」就把回执冲掉了")
    page.deleteLater()


def test_a_bar_nobody_told_about_the_switch_says_nothing_extra(qapp):
    """没有总开关的页（about / account / …）不该凭空多出一句话。"""
    bar = PageActionBar()
    bar.set_message("原样")
    assert bar.message_label.text() == "原样"
    bar.deleteLater()


def test_no_page_still_writes_the_old_unconditional_receipt():
    """⚠⚠ 批 10 那句 **无条件**的「改动已自动保存，不用点任何按钮。」

    它是这条缺陷里票数最高的一项（现状 4/4 高、候选 C 6/6 高）。
    收进 `PageActionBar` 之后，**任何一页都不许再自己写一份**。
    """
    offenders = []
    for path in _page_sources():
        for lineno, value in _string_constants(path):
            if "不用点任何按钮" in value:
                offenders.append((path.name, lineno))
    assert not offenders, (
        f"这几页还在自己写那句无条件回执：{offenders}\n"
        "⭐ 它在总开关开着时是真话，关着时是假话。")


# ================================================ 三、参数区降权（第②件）


@pytest.fixture(scope="module")
def main_window(qapp):
    """离屏主窗口。**铁律：不弹真窗口、不弹模态框。**

    ⚠⚠ **module 作用域是必须的，不是优化。** 这份判据有 6 条 ×15 页的参数化用例；
    函数级夹具等于建 90 次主窗口，实测跑 **375 秒**，而 `build_tools/run_tests.py`
    每个文件只给 **300 秒** —— 而且它撞上超时不是记一条红，是
    `subprocess.TimeoutExpired` **把整台门禁掀翻**（那一轮连汇总都没打出来）。
    ⭐⭐ **一条跑不完的判据不是判据；一条会掀翻门禁的判据比没有更坏。**
    （顺手把 `run_tests.py` 的超时改成「记一条红」——见那边的注释。）
    ⚠ 用 `pytest.MonkeyPatch()` 手工开合，不能用 `monkeypatch` 夹具：那是函数级的。

    ⚠⚠ **这份判据会真的去拨 15 颗总开关，而配置目录是全仓共用、跨轮次累积的**
    （`tests/conftest.py` 自己写着：固定路径，RN-141 只钉死了 `csgo_dir` 和
    `ui_expert_mode` 两项）。第一版没把值放回去，结果
    `voice_output_enabled` 被留在 True，
    `test_tool_pages_ui_polish.test_voice_output_page_status_card_tracks_runtime_and_forwarding`
    当场红 —— 它断言底栏最后一句是「当前标签：语音设置」，而开着的时候
    热键注册会在那之后再写一句「音板快捷键已就绪」。
    ⭐⭐ **一个共享的、跨轮次累积的前置状态，会把「我这一条判据改了什么」
    变成「别人那一条判据看到了什么」** —— 而中间隔着一个进程、一个文件、
    和一段谁都没写下来的因果。
    ⇒ 这里逐键快照 + 还原，并在拆夹具时**断言真的还原成功了**。
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    before = {key: getattr(config, key, None) for key in EXPECTED_KEYS.values()}
    neutral.apply(config)
    config.compact_mode = False
    # ⚠ 钉死这颗**子开关**（产品默认 True，见 `config.py:549`）。
    # 不钉的话 `screen_effects` 那条级联的差值在本机和 CI 上不一样 ——
    # 本机那个跨轮次累积的配置目录里它是 False，四个控件拨之前就已经关着。
    # ⭐ **判据的前置状态要么它自己钉，要么 conftest 统一钉死；不许「看命」**（RN-141）。
    monkeypatch.setattr(config, "screen_edge_flash_enabled", True, raising=False)
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    # ⚠ RN-157：模态框在测试进程里是**卡死**不是失败。
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    qapp.processEvents()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()
    # ⭐ 拨过的开关**逐颗放回去**，并且落盘一次 —— 不落盘的话内存里是对的、
    #   文件里还留着我拨过的值，下一个进程读到的是后者。
    for key, value in before.items():
        setattr(config, key, value)
    config.__class__.save_config(config)
    still_off = {k: (getattr(config, k, None), v)
                 for k, v in before.items() if getattr(config, k, None) != v}
    monkeypatch.undo()
    assert not still_off, f"这些总开关没还原回去：{still_off}"


def _open(win, qapp, page_id):
    win.ensure_page_loaded(page_id)
    win.show_page(page_id, animated=False, force=True)
    qapp.processEvents()
    page = win.pages.get(page_id)
    assert page is not None, f"{page_id} 没加载出来"
    return page


def _set_switch(page, qapp, checked):
    page.master_switch_row.set_checked_by_user(checked)
    qapp.processEvents()


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_every_parameter_card_is_de_emphasised_when_the_switch_is_off(
        main_window, qapp, page_id):
    """⭐⭐ 总开关关着 ⇒ 这一页的参数卡**全部**降权，一张都不许漏。

    漏一张的后果不是"少改了一处"，是那一张会变成屏幕上**唯一还在发亮**的卡，
    读起来就成了「只有这一块是活的」—— 比全都不改更坏。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, False)
    left = eff.undimmed_cards(page)
    assert not left, (
        f"{page_id}：总开关关着，还有 {len(left)} 张参数卡没降权 —— "
        f"{[c.objectName() or type(c).__name__ for c in left]}")

    _set_switch(page, qapp, True)
    stuck = [c for c in eff.parameter_cards(page)
             if c.property(eff.CARD_DIM_PROPERTY)]
    assert not stuck, (
        f"{page_id}：总开关开着，还有 {len(stuck)} 张卡挂着降权标记 —— "
        "那等于告诉玩家「开了也没用」。")


def _first_accent_control(page):
    """参数卡里第一个带品牌强调色的控件（滑块 / 单选框）。"""
    from PySide6.QtWidgets import QRadioButton, QSlider

    for card in eff.parameter_cards(page):
        for kind in (QSlider, QRadioButton):
            for widget in card.findChildren(kind):
                if widget.isVisibleTo(page) and widget.width() > 4:
                    return widget
    return None


def _pixels_of(widget) -> bytes:
    """抓一个控件此刻的像素。

    ⚠⚠ **RN-433：这里必须把 QImage 先落到一个变量上。** 原来写的是一行链式：

        widget.grab().toImage().bits().tobytes()

    `bits()` 返回的是**指向那张 QImage 缓冲区的裸指针**，而链式写法里
    `QPixmap` 和 `QImage` 都是**没有任何 Python 引用的临时对象** ——
    `.tobytes()` 执行时它们可能已经被回收，于是读的是**已释放的内存**。
    实测：同一条判据连跑四次，**崩一次**（`Windows fatal exception:
    access violation`，rc=139），另外三次正常通过。

    ⭐⭐ 而它的**失败方式**才是要害：这不是"判据变红"，是**进程当场死掉**。
    `revert_verify` 的基线阶段只看 `returncode == 0` ⇒ 报成「基线就不绿」，
    **整台回退验证停摆**，而真正的原因一个字都没提（同 RN-194）。
    ⇒ ⭐ **一条判据的失败方式不止「红」一种；而只有「红」那一种会说人话。**

    ⚠ 更该记的是它活了多久：这条判据是批 19 写的，**两轮收工门禁全绿**
    （批 19、批 20）。⭐ **一次没发生的崩溃，和一条正常工作的判据，长得一模一样。**
    """
    image = widget.grab().toImage()          # ← 引用留住，别让它变成临时对象
    return image.constBits().tobytes()


def test_the_pixel_grab_keeps_the_image_alive():
    """RN-433：抓像素时不许把 QImage 当临时对象用。

    ⚠ **这条必须是静态的（走 AST），不能靠"多跑几次看崩不崩"** ——
    悬空指针是**随机**崩的（实测 4 次崩 1 次），
    而一条随机失败的判据在回退验证里会给出时红时绿的结果。
    ⭐ **一条判据要能被验证，它的失败必须是确定的。**

    形状：`x.toImage().bits()` / `x.toImage().constBits()` ——
    即**在一个 `toImage()` 的返回值上直接取缓冲区**，中间没落到变量上。
    """
    src = Path(__file__).read_text(encoding="utf-8")
    dangling = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in ("bits", "constBits"):
            continue
        inner = fn.value
        if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "toImage"):
            dangling.append(node.lineno)

    assert not dangling, (
        f"第 {dangling} 行在 `toImage()` 的返回值上直接取缓冲区 —— "
        "那张 QImage 没有任何 Python 引用，取到的是**指向已释放内存的裸指针**，"
        "进程会随机 access violation（不是判据变红，是当场死掉）。\n"
        "⭐ 先把 QImage 落到一个变量上，再 `constBits()`。"
    )


def test_the_de_emphasis_actually_changes_pixels(main_window, qapp):
    """⭐⭐⭐ **判据绿不代表屏幕上有东西 —— 那就去量屏幕。**

    ⚠⚠ 这条是回退验证逼出来的。我原本拿
    `test_every_parameter_card_is_de_emphasised_when_the_switch_is_off` 去守
    「控件降权」那条修复，**它是假绿的**：那条判据查的是卡片上那个属性，
    而属性设上了、QSS 规则也写对了，屏幕上**照样可以一个像素都不变** ——
    因为**改祖先的动态属性不会让后代重算样式**，得点名 repolish。
    ⭐ 这正是我在出图时用肉眼撞见的那个坑，而当时没有任何一条判据看得见它。

    ⇒ 直接抓那个控件自己的像素，开/关各一张，必须不一样。
    ⚠ 抓**控件本身**而不是整张卡：卡片标题的字色是另一条规则改的，
      拿整张卡去比会被标题的变化喂成绿（同 RN-198「抄了修好之前的版本」的形态）。
    """
    checked = []
    for page_id in sorted(EXPECTED_KEYS):
        page = _open(main_window, qapp, page_id)
        widget = _first_accent_control(page)
        if widget is None:
            continue
        _set_switch(page, qapp, True)
        qapp.processEvents()
        on_pixels = _pixels_of(widget)
        _set_switch(page, qapp, False)
        qapp.processEvents()
        off_pixels = _pixels_of(widget)
        assert on_pixels != off_pixels, (
            f"{page_id}：总开关关着，`{type(widget).__name__}` 画出来的像素"
            "跟开着时**一模一样** —— 降权在屏幕上没有发生。\n"
            "⭐ 改祖先的动态属性不会让后代重算样式，要点名 repolish。")
        checked.append(page_id)
    assert len(checked) >= 6, (
        f"只在 {len(checked)} 页上找到了带强调色的控件（{checked}）——"
        "扫描器八成瞎了，这条判据正在空转。")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_the_card_holding_the_switch_is_never_de_emphasised(
        main_window, qapp, page_id):
    """⚠ 装着总开关的那张卡**不许**降权。

    把「你要去拨的那颗开关所在的卡」一起调暗，等于把出口也调暗了。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, False)
    host = eff.status_card_of(page)
    assert host is not None, f"{page_id}：找不到装着总开关的那张卡"
    assert not host.property(eff.CARD_DIM_PROPERTY), (
        f"{page_id}：把总开关自己那张卡也调暗了")
    assert host not in eff.parameter_cards(page)


#: 拨总开关时，**页面自己**（不是降权）会关掉的控件，逐条写明依据。
#: ⭐ 每一条都要指到源码行 —— 一张没有理由的豁免表，跟没有判据是一回事。
#: ⚠ 这些**与 RN-407 立的规矩相反**（关着时应「可调但明说不生效」），
#:   已就此立案 **RN-420**：它们不是这一批的漏网，是一个需要单独裁的取舍。
#:
#: ⚠⚠ **这张表第一版是「看命」的，被公开仓 CI 当场逮到。**
#: 本机只报出 `screen_effects: checkBox` 一条，CI 上是**整条级联**——
#: `screen_effects_page.py:371-374` 那四个控件由 `edge_enabled`
#: （= 总开关 **且** 子开关 `screen_edge_flash_enabled`）决定，
#: 而本机那个**跨轮次累积**的配置目录里这颗子开关恰好是 `False`，
#: 四个控件**拨之前就已经是关的**，于是「拨完新增的禁用」这个差值里看不见它们。
#: ⭐⭐ **我在同一批里，一边给别人的判据钉前置状态（RN-141 第四例），
#:   一边写了一条自己不钉的。** ⇒ 夹具已把这颗子开关钉在产品默认值 `True` 上。
#: ⭐ 顺带记账：**公开仓 CI 这一次又逮到了本机三样门禁全绿的东西**
#:   —— 那正是 RN-418 差点被我判死的那条依赖。
DISABLED_BY_THE_PAGE_ITSELF = {
    "flash": (("primaryButton",),
              "flash_page.py:303 `_sync_action_bar` 里 `primary_btn.setEnabled(enabled)`"
              "——「启动闪光」在总开关关着时点了也起不来，是**动作按钮**不是参数"),
    "screen_effects": (("checkBox", "comboBox", "primaryButton", "secondaryButton"),
                       "screen_effects_page.py:370-374：子开关本体由总开关决定"
                       "（RN-011 那一轮就是这么定的）；另外三类由 `edge_enabled` 决定"
                       "（两颗下拉 + 底栏两颗预览按钮）"),
}


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_the_de_emphasis_itself_never_disables_anything(main_window, qapp, page_id):
    """⚠⚠ **RN-179：降权不是禁用。** —— 这一条量的是**降权自己**。

    直接调 `apply_effect_state`，绕开页面自己的 `_sync_enabled_state`。
    ⭐ 拨开关那条路上会同时跑好几段代码，量到的差值分不清是谁干的；
      要证明「**我这一段**没禁用任何东西」，就得单独跑我这一段。
      （同 RN-417：量不稳的东西，就去量决定它的规则。）
    这条判据**没有豁免表**，一条都不许有。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, True)
    enabled_before = {id(w) for w in page.findChildren(QWidget) if w.isEnabled()}
    eff.apply_effect_state(page, False)
    qapp.processEvents()
    turned_off = [w for w in page.findChildren(QWidget)
                  if id(w) in enabled_before and not w.isEnabled()]
    assert not turned_off, (
        f"{page_id}：降权顺手禁用了 {len(turned_off)} 个控件 —— "
        f"{[w.objectName() or type(w).__name__ for w in turned_off][:8]}\n"
        "⭐ RN-179：可点却没反应，和不能点，是两条不同的缺陷；这两条都不要。")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_flipping_the_switch_off_disables_only_what_is_declared(
        main_window, qapp, page_id):
    """⭐ 端到端：拨了开关之后，被关掉的控件必须**逐个**在豁免表里写着理由。

    ⚠ 这条**不是**上一条的重复：上一条证明「我没禁用」，这条盯的是
    「这一页一共禁用了什么」——多出一个来，就说明有人在别处又加了一条。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, True)
    enabled_before = {id(w) for w in page.findChildren(QWidget) if w.isEnabled()}
    _set_switch(page, qapp, False)
    newly_off = [w for w in page.findChildren(QWidget)
                 if id(w) in enabled_before and not w.isEnabled()]
    # ⚠ 只报这几棵子树的**根**：Qt 的禁用是往下传的，一颗关掉的下拉框会把
    # 它内部的 `qt_scrollarea_viewport` 一串都带上 —— 那不是「又多禁用了一个控件」。
    # ⭐ **量一件事的时候，要量它的因，不要连着量它的果。**
    off_ids = {id(w) for w in newly_off}
    roots = [w for w in newly_off
             if not (w.parentWidget() is not None and id(w.parentWidget()) in off_ids)]
    turned_off = sorted({w.objectName() or type(w).__name__ for w in roots})
    declared = DISABLED_BY_THE_PAGE_ITSELF.get(page_id)
    expected = sorted(declared[0]) if declared else []
    assert turned_off == expected, (
        f"{page_id}：拨关总开关关掉了 {turned_off}，而豁免表写的是 {expected}\n"
        "⇒ 要么这是新加的禁用（RN-179 那条缺陷又长出来了），"
        "要么豁免表过期了。两种都要人去看一眼。")


def test_the_disabled_exception_table_is_not_stale():
    """⭐ 豁免表里点名的那两行源码得**真的还在**（防止改完之后表空转）。"""
    for page_id, (_control, reason) in DISABLED_BY_THE_PAGE_ITSELF.items():
        path = REPO / "pages" / f"{page_id}_page.py"
        assert path.exists(), f"{page_id} 的实现文件没了，豁免表过期"
        assert "setEnabled" in path.read_text(encoding="utf-8"), (
            f"{page_id} 里已经没有任何 setEnabled 了，这条豁免可以删："
            f"{reason}")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_the_notice_only_exists_while_the_switch_is_off(main_window, qapp, page_id):
    """⭐ 只在需要的时候才存在（RN-195）。

    开着的时候还挂一条「总开关关着」的横幅，那是屏幕上第二处假话。
    """
    page = _open(main_window, qapp, page_id)
    notice = page.master_switch_row.effect_notice
    _set_switch(page, qapp, False)
    assert notice.isVisibleTo(page), f"{page_id}：关着却没有那句话"
    assert eff.NOTICE_OFF_TEXT in notice.text()
    _set_switch(page, qapp, True)
    assert not notice.isVisibleTo(page), f"{page_id}：开着还挂着「现在看不到」"


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_saying_it_costs_no_extra_height(main_window, qapp, page_id):
    """⭐⭐ **固定不动的那块屏幕是稀缺资源。**

    第一版把这句话做成开关行下面的一条警示横幅，开关行 24px → **63px**。
    紧凑档排版审计当场判红：状态卡在滚动区外面的 9 页，那 39px 是从 548px 的
    可视区里硬扣的（`kill_voice` 的在册纵向裁切 64 → 107px，还多出两条全新溢出）。
    ⇒ 现在它坐在开关行本来就空着的那段横向空间里。这条判据把
    「说出来**不许**顺手长高」钉死。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, True)
    qapp.processEvents()
    on_height = page.master_switch_row.sizeHint().height()
    _set_switch(page, qapp, False)
    qapp.processEvents()
    off_height = page.master_switch_row.sizeHint().height()
    assert off_height <= on_height, (
        f"{page_id}：关着的时候开关行从 {on_height}px 长到了 {off_height}px。\n"
        "⭐ 把话说清楚，不等于可以把它塞在任何地方 —— 紧凑档只有 548px 可视区，"
        "而 RN-196 那 6 条在册纵向裁切债还欠着。")


def test_the_sitewide_scan_really_reached_every_page(main_window, qapp):
    """⭐⭐ **扫描器自己会瞎，而瞎了的时候它是绿的。**

    本会话已经栽过两次：一次按 `unsafe_pages()` 先过滤、一次写了
    `win.show_page(...)` 而专家页会**静默 return** —— 两次都只扫到 22/28 页。
    这一条把「到底走到几页」变成一个可断言的数。
    """
    reached = []
    for page_id in sorted(EXPECTED_KEYS):
        page = _open(main_window, qapp, page_id)
        if getattr(page, "master_switch_row", None) is not None:
            reached.append(page_id)
    assert set(reached) == set(EXPECTED_KEYS), (
        f"只走到 {len(reached)}/{len(EXPECTED_KEYS)} 页："
        f"缺 {sorted(set(EXPECTED_KEYS) - set(reached))}")


def test_the_checker_can_still_see_an_undimmed_card(qapp):
    """⭐⭐⭐ **空转守卫**：拿一张**合成**的页面证明检查器还认得出缺陷。

    ⚠ 不用仓库里现成的页 —— RN-199 刚踩过：那条乱码判据的自检拿的是
    「仓库里恰好还留着的 42 个坏文件」，把语料删掉就等于把
    「探测器还认不认得出缺陷」的证明一起删掉了。
    """
    page = QWidget()
    layout = QVBoxLayout(page)
    host = QFrame()
    host.setObjectName("card")
    layout.addWidget(host)
    victim = QFrame()
    victim.setObjectName("card")
    layout.addWidget(victim)

    # 没有总开关行 ⇒ 没有"宿主卡"，两张都算参数卡；一张都没降权。
    assert len(eff.undimmed_cards(page)) == 2, "检查器数不出没降权的卡"
    victim.setProperty(eff.CARD_DIM_PROPERTY, "true")
    assert len(eff.undimmed_cards(page)) == 1, "降权过的卡还被算成没降权"
    host.setProperty(eff.CARD_DIM_PROPERTY, "true")
    assert eff.undimmed_cards(page) == [], "全降权了还报有漏网的"
    page.deleteLater()


# ============================================ 四、属性有人消费（不许空转）


def _stylesheet_for(theme_name: str) -> str:
    from theme_manager import get_theme_manager
    return get_theme_manager().themes[theme_name].generate_stylesheet()


def _themed_names() -> list[str]:
    from theme_manager import get_theme_manager
    # minimal 走系统原生样式（`generate_stylesheet` 返回空串），审它只会产生假警报。
    return [n for n in get_theme_manager().themes if n != "minimal"]


@pytest.mark.parametrize("theme_name", _themed_names())
def test_the_dim_property_is_actually_consumed_by_the_stylesheet(theme_name):
    """⭐⭐ **一个没人消费的属性，是一条静默失效的措施。**

    `setProperty("masterOff", "true")` 本身**不改变任何一个像素**；
    只有 QSS 里存在对应选择器才会。判据全绿而屏幕原样，正是 RN-411 那一族
    「坏得没有任何一处报错」。
    """
    qss = _stylesheet_for(theme_name)
    selector = f'QFrame#card[{eff.CARD_DIM_PROPERTY}="true"]'
    assert selector in qss, f"{theme_name} 的样式表里没有 {selector}"
    assert f'{selector} QLabel#cardTitle' in qss, (
        f"{theme_name}：卡片标题没有降权规则，降权在图上看不出来")
    assert f'QLabel#{eff.NOTICE_OBJECT_NAME}' in qss, (
        f"{theme_name}：那句话没有底色规则 —— "
        "⭐ 批 14 的候选 B 就是这么废掉的：`QWidget` 子类默认不画 stylesheet 背景，"
        "一个没渲染出来的候选，拿去比就是在比两张一样的图。")


#: 关着的时候必须**退掉品牌强调色**的那几类控件。
#: ⭐⭐ 这份名单是外审复跑逼出来的：第一版只降了卡片外壳（标题字色 + 左侧竖杠），
#: **43 发里 39 发照旧报**「所有控件均为高亮紫色激活态且未置灰 ⇒ 以为正在运行」。
#: ⭐ **「这一片是活的」这个信号不是外壳发出来的，是这些控件发出来的。**
ACCENT_SELECTORS = (
    "QSlider::sub-page:horizontal",
    "QSlider::handle:horizontal",
    "QRadioButton::indicator",
    "QCheckBox::indicator:checked",
    "QPushButton#primaryButton",
)


@pytest.mark.parametrize("theme_name", _themed_names())
def test_the_accent_bearing_controls_go_neutral_when_it_is_off(theme_name):
    """⭐⭐ 降权要降在**说话的那个东西**上。

    ⚠ 这条判据里的每一个选择器都对应外审点过名的一处；少一个，
    那一类控件就会在关着的时候继续用品牌紫喊「我在运行」。
    """
    qss = _stylesheet_for(theme_name)
    prefix = f'QFrame#card[{eff.CARD_DIM_PROPERTY}="true"] '
    for selector in ACCENT_SELECTORS:
        assert prefix + selector in qss, (
            f"{theme_name}：`{selector}` 在总开关关着时没有降权规则。\n"
            "⭐ 外审 39/43 报的正是「控件全是高亮紫色 ⇒ 以为在运行」。")


@pytest.mark.parametrize("theme_name", _themed_names())
def test_the_neutral_colour_is_still_a_legal_ui_colour(theme_name):
    """⚠ 降权不许把可读性一起降掉。

    · 中性色压在卡片底上 ≥ **3:1**（WCAG 给非文字 UI 元件的那一档 ——
      滑块填充、单选框圈属于这一类）；
    · 主按钮上的**字**压在中性底上 ≥ **4.5:1**（那是正文档）。
    ⭐ 第二条是实测逮出来的：只取黑白里较好的那一端，墨绿 4.37、玫瑰 4.45，
      **两个都差一口气**。「改了配色一定要重算对比度」每次都能逮到一个。
    """
    from core.utils.contrast import AA_NORMAL, contrast_ratio, ensure_contrast
    from theme_manager import get_theme_manager

    theme = get_theme_manager().themes[theme_name]
    c = theme.colors
    idle = c.text_tertiary
    assert contrast_ratio(idle, c.bg_card) >= 3.0, (
        f"{theme_name}：降权后的控件只有 {contrast_ratio(idle, c.bg_card):.2f}:1，"
        "看不见了 —— 那不是降权，是消失。")
    idle_text = ensure_contrast(theme._on_color(idle), (idle,), AA_NORMAL)
    assert contrast_ratio(idle_text, idle) >= AA_NORMAL
    assert idle_text in _stylesheet_for(theme_name), (
        f"{theme_name}：主按钮降权后的字色没走 ensure_contrast，"
        "等于绕开了对比度守卫")


@pytest.mark.parametrize("theme_name", _themed_names())
def test_nothing_that_means_standing_by_is_painted_in_a_lit_up_colour(theme_name):
    """⭐⭐⭐ **在这套深色界面里，任何一块饱和的色都读作「亮着 = 在运行」。**

    ⚠ 第二版把那句「现在不生效」做成了**橙底橙字**（沿用 warning chip 那一套）。
    外审第三轮 12 发以上同一条判词：
      「橙黄色背景**误当成已激活的运行指示灯**」
      「橙色提示条视觉上类似高亮状态条**而非阻断警告**」
    —— 和当初逼我把状态胶囊改成中性的**是同一条**：
    ⭐ **「未启用」用橙色写，写得越醒目越像「已启用」。**

    ⇒ 全站一套状态语言：**中性 = 没在跑，品牌色 = 在跑**。
    这条判据守着「表示没在跑的东西，不许用会被读成『在跑』的颜色」。
    """
    from core.utils.contrast import AA_NORMAL, contrast_ratio
    from theme_manager import get_theme_manager

    theme = get_theme_manager().themes[theme_name]
    c = theme.colors
    qss = _stylesheet_for(theme_name)
    block = qss[qss.index(f"QLabel#{eff.NOTICE_OBJECT_NAME}"):]
    block = block[:block.index("}")]
    for lit in (c.accent_primary, c.accent_warm):
        assert lit not in block, (
            f"{theme_name}：那句「现在不生效」还在用会被读成「亮着」的颜色 {lit}\n"
            f"block={block!r}")
    # 中性不等于看不清：字压在薄染底上要 ≥4.5:1。
    bg = theme._blend_hex(c.text_tertiary, 30, c.bg_card)
    ratio = contrast_ratio(c.text_secondary, bg)
    assert ratio >= AA_NORMAL, f"{theme_name}：那句话只有 {ratio:.2f}:1"


@pytest.mark.parametrize("theme_name", _themed_names())
def test_the_status_chips_stop_looking_like_running_indicators(theme_name):
    """⭐ 那排状态胶囊在关着时读起来像「当前正在运行的配置清单」。

    外审 43 发里 **16 发**把那颗**橙色**的「未启用」读成了「运行中/已激活」
    的高亮指示灯 —— 深色底上的橙色对 CS2 玩家就是「点亮了」。
    ⭐ **按警示色着色而不按状态着色，颜色照样不携带信息。**
    """
    qss = _stylesheet_for(theme_name)
    assert (f'QFrame#card[{eff.HOST_DIM_PROPERTY}="true"] QLabel#audioStatusChip'
            in qss), f"{theme_name}：状态胶囊组没有降权规则"


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_the_status_chips_follow_the_switch(main_window, qapp, page_id):
    page = _open(main_window, qapp, page_id)
    host = eff.status_card_of(page)
    _set_switch(page, qapp, False)
    assert host.property(eff.HOST_DIM_PROPERTY), f"{page_id}：关着，胶囊组没降权"
    _set_switch(page, qapp, True)
    assert not host.property(eff.HOST_DIM_PROPERTY), f"{page_id}：开着还降着权"


@pytest.mark.parametrize("theme_name", _themed_names())
def test_the_de_emphasised_title_uses_a_token_that_already_has_a_guard(theme_name):
    """⭐ 降权用的是**已经有对比度守卫的那个 token**，不是我另调一个灰。

    `text_secondary` 由 `test_theme_contrast.test_body_text_meets_aa` 盯着
    （九个主题、三种背景全部 ≥4.5:1）。换成随手写的灰值就绕开了那条守卫 ——
    而「改了配色一定要重算对比度」这条是拿官网那轮换来的
    （卡片底色加深一档，`#198754` 当场从达标掉到 4.30:1）。
    """
    from core.utils.contrast import AA_NORMAL, contrast_ratio
    from theme_manager import get_theme_manager

    theme = get_theme_manager().themes[theme_name]
    c = theme.colors
    qss = _stylesheet_for(theme_name)
    selector = f'QFrame#card[{eff.CARD_DIM_PROPERTY}="true"] QLabel#cardTitle'
    block = qss[qss.index(selector):]
    block = block[:block.index("}")]
    assert c.text_secondary in block, (
        f"{theme_name}：降权字色不是 text_secondary（block={block!r}）")
    ratio = contrast_ratio(c.text_secondary, c.bg_card)
    assert ratio >= AA_NORMAL, f"{theme_name} 降权后的卡片标题只有 {ratio:.2f}:1"


# ================================================== 五、预览说后果（第③件）


@pytest.mark.parametrize("page_id", sorted(PAGES_WITH_A_PREVIEW))
def test_the_preview_says_what_it_means(main_window, qapp, page_id):
    """⭐ 预览要**说出后果**，而不是被关掉。

    ⚠ 候选 C 那一轮把预览改成不渲染，**6/6 判高**「失去反馈，与底栏矛盾」。
    ⇒ 画照常画，旁边一句话说清楚「这东西游戏里现在看不看得到」。
    """
    page = _open(main_window, qapp, page_id)
    captions = [w for w in page.findChildren(QLabel)
                if w.objectName() == eff.PREVIEW_CAPTION_OBJECT_NAME]
    assert captions, f"{page_id}：预览旁边没有那句话"
    _set_switch(page, qapp, False)
    assert all(c.text() == eff.PREVIEW_OFF_TEXT for c in captions), \
        f"{page_id}：关着的时候预览没说后果"
    _set_switch(page, qapp, True)
    assert all(c.text() == eff.PREVIEW_ON_TEXT for c in captions), \
        f"{page_id}：开着的时候预览没说「这就是现在的样子」"


@pytest.mark.parametrize("page_id", sorted(PAGES_WITH_A_PREVIEW))
def test_the_preview_is_still_being_drawn_when_the_switch_is_off(
        main_window, qapp, page_id):
    """⚠⚠ **不许把预览关掉。** 这正是候选 C 造出矛盾的那一步。

    「失去反馈」是 6/6 高 —— 比它想修的那条还重。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, False)
    surface = getattr(page, PAGES_WITH_A_PREVIEW[page_id], None)
    assert surface is not None, f"{page_id}：预览面不见了"
    assert surface.isVisibleTo(page), (
        f"{page_id}：总开关关着就把预览藏了 —— "
        "外审对这一步的判词是「失去反馈，与底栏矛盾」，6/6 高。")


def test_the_preview_list_is_not_stale(main_window, qapp):
    """⭐ 名单里的页得**真的**有那个预览面（防止改名之后名单空转）。"""
    for page_id, attr in sorted(PAGES_WITH_A_PREVIEW.items()):
        page = _open(main_window, qapp, page_id)
        assert getattr(page, attr, None) is not None, (
            f"{page_id} 上已经没有 `{attr}` 了 —— 这份名单过期了")


def test_pages_without_a_preview_are_not_quietly_missing_one(main_window, qapp):
    """⭐⭐ **反面守卫**：名单外的页，得确认它是「没有可说的」而不是「漏了」。

    ⚠ 一张只列白名单的表，读起来是"这几页做了"，实际是"凡是做了的都做了"
    —— 分母由结论决定（RN-189 那条判据栽过一模一样的）。
    """
    missed = []
    for page_id in sorted(set(EXPECTED_KEYS) - set(PAGES_WITH_A_PREVIEW)):
        page = _open(main_window, qapp, page_id)
        for attr in ("preview_frame", "basic_preview_widget", "hero_preview",
                     "preview_widget"):
            surface = getattr(page, attr, None)
            if isinstance(surface, QWidget):
                missed.append((page_id, attr))
    assert not missed, (
        f"这几页其实有预览面，却不在名单里：{missed}\n"
        "⇒ 要么补进 PAGES_WITH_A_PREVIEW，要么写明为什么它不算预览。")


def test_the_notice_leads_with_what_he_can_do_now():
    """⚖ **RN-424：开关旁那句话，要先说「现在能干什么」，再说「还不生效」。**

    批 16 为了让人看见「不生效」，把否定放到了句首（RN-407，那条是对的：
    ⭐ 写在转折之后的否定等于没写）。⚠ **但那同时把「可以调」挤进了
    没人读的后半截** —— 于是产生了另一条缺陷。

    实测（批 18，判断题 + **地板对照**）：问「他知不知道现在就可以先把参数
    调好、调好之后再打开总开关」——

    | 屏 | 知道 | 不知道 |
    |---|---|---|
    | 把这两句话**都拿掉**（地板对照）| **0/45（0%）** | 45/45 |
    | 批 16 的写法（否定在句首）| **26/45（57%）** | 19/45 |

    ⇒ 两件事同时成立：**那句话是真的有效的**（0% → 57%，每一发「知道」都
    逐字引用了它），**而它只走到 57%**。19 发「不知道」的措辞几乎完全一致：
    「**以为必须先打开总开关才能开始配置**，关着的时候调了不会保存或不起作用。」

    ⭐⭐ **这两句话分工**：开关旁那句回答「我现在能干什么」（肯定在前），
    底栏那句回答「我改的东西生不生效」（否定在前，见上面那条判据）。
    ⭐ 同一屏上两句话都用同一个语序，等于把同一个后半截丢了两次。

    ⚠ **这跟「别再试第四版文案」不冲突**：那条禁令是对 **RN-407 那条缺陷**
    说的（连续四轮文字打不动「以为已生效」）。在 RN-424 这条轴上，文案
    **恰恰是有效成分**。⭐ **「文案打不动」是对某一条缺陷说的，
    不是对文案这个手段说的。**
    """
    text = eff.NOTICE_OFF_TEXT
    head = text[:6]
    assert any(w in head for w in ("可以调", "现在可以", "照常")), (
        f"这句话的前 6 个字里没有「你现在能干什么」：{text}\n"
        "⭐ 读的人在读到分号之前就走了 —— 而这一句的职责正是那半截。")
    assert "不生效" in text, (
        f"把「不生效」丢了：{text}\n"
        "⚠ 语序换了，内容一个字都不许少 —— 那是 RN-407 那条轴。")
    negation = text.index("不生效")
    affordance = min(text.index(w) for w in ("可以调", "照常") if w in text)
    assert affordance < negation, (
        f"「能干什么」排在「不生效」后面了：{text}")


#: 「这东西正在跑」的说法。总开关关着时，屏幕上一个字都不该这么说。
ENABLED_CLAIMS = ("已启用", "已开启", "运行中", "生效中")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_nothing_on_screen_claims_to_be_enabled_while_the_switch_is_off(
        main_window, qapp, page_id):
    """⭐⭐ **批 16 把状态胶囊退成了中性色，却没有动它说的话。**

    颜色不再喊「运行中」了，**字还在喊**。实测（批 18，RN-407 那条轴的复跑）：
    `music` 一页在总开关关着时仍然写着

        状态胶囊「联动 · **已启用**」
        「当前策略：**联动已启用** · 阵亡后自动开始/继续播放 · …」

    因为 `link_enabled` 只读子开关 `music_game_link_enabled`，
    **完全不看总开关** `music_enabled`。

    ⚠ 这处缺陷**在批 16 就已经在屏幕上了**（现状截图里逐字可见），
    只是当时那一轮 45 发一次都没报。批 18 换了开关旁那句话的语序之后，
    **同一页 2/45 判「会以为已生效」** ——
    ⭐⭐ **我的改动没有造出那处缺陷，但它把注意力从「不生效」挪开了，
    于是那处一直都在的矛盾被读到了。**
    ⇒ 不是撤回语序，是把那句假话改掉。

    ⭐ 顺带一条：这解释了批 16 为什么会漏 ——
    **它审的是「我改的那三件东西」，而缺陷在「页面自己算出来的那句话」里。**
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, False)
    offenders = []
    for label in page.findChildren(QLabel):
        if label.isHidden():
            continue
        text = (label.text() or "").strip()
        hit = [c for c in ENABLED_CLAIMS if c in text]
        if hit:
            offenders.append(f"[{label.objectName() or 'QLabel'}] {text[:60]}")
    assert not offenders, (
        f"{page_id}：总开关关着，屏幕上还有 {len(offenders)} 处在说「已启用」——\n  "
        + "\n  ".join(offenders) +
        "\n⭐ 一句只在某个状态下为真的话，在别的状态里就是一句谎。")


def _accent_rgb():
    """品牌强调色（当前主题）。⭐ 从主题取，不写死 —— 写死的话换主题就静默失效。"""
    from theme_manager import get_theme_manager
    tm = get_theme_manager()
    raw = tm.current_theme.colors.accent_primary.lstrip("#")
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


def _accent_pixels(widget, rgb, tol=12):
    """这颗控件身上有多少个像素在用品牌强调色。"""
    img = widget.grab().toImage()
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - rgb[0]) <= tol and abs(c.green() - rgb[1]) <= tol
                    and abs(c.blue() - rgb[2]) <= tol):
                n += 1
    return n


def test_the_parameter_area_definition_can_still_find_controls(main_window, qapp):
    """⚠ 反空转 —— 而它必须是**聚合**的，不能逐页钉。

    第一版逐页钉「这一页必须找得出控件」，全量跑时 5 个音效页当场误报：
    那几页库是空的，**根本不建那些参数行**（显示的是空库引导卡）——
    ⭐ **这一页的分母本来就可以是空的。**
    ⚠ 而且它只在**全量跑**时红、单独跑绿，因为库空不空取决于前面哪个
    测试动过那个共享配置目录（RN-141 那一族）。

    ⭐⭐ **「分母塌了」和「这一页此刻恰好什么都没有」是两件事，
    而一条反空转断言很容易把它们混成一件。**
    ⇒ 改成问一句聚合的：这个定义在 15 页里**至少还能在大多数页上找出控件**。
    它塌掉（比如有人把 `_VALUE_ACCENT` 判空）时会立刻红，
    而某一页恰好空着不会。

    ⚠ 这条存在的理由见另一条判据的账：产品和判据**共用同一个分母定义**，
    ⭐⭐⭐ **单一真相源让它们一致，也让它们一起错** —— 定义一塌，
    产品不降权、判据也同时看不见任何东西，于是全绿。
    """
    found = {}
    for page_id in sorted(EXPECTED_KEYS):
        page = _open(main_window, qapp, page_id)
        found[page_id] = len(eff.parameter_area_controls(page))
    lively = [p for p, n in found.items() if n]
    assert len(lively) >= 10, (
        f"15 页里只有 {len(lively)} 页找得出参数区控件：{found}\n"
        "⭐ 这个分母定义多半塌了 —— 而它一塌，产品和判据会一起瞎。")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_no_control_in_the_parameter_area_stays_brand_coloured(
        main_window, qapp, page_id):
    """⭐⭐ **降权的分母是「谁在发亮」，不是「谁住在一张卡里」。**

    批 16 把「参数区」等同于 `objectName == "card"` 的 QFrame，
    判据也照着问「每张卡有没有被降权」—— 15 页全绿。
    ⚠ 而实测（批 19）：`music` 的「允许游戏状态自动控制音乐」和 `voice_output`
    的三颗转发复选框住在 **`QGroupBox`** 里，**不在任何 card 里** ⇒
    降权一个像素都没够着，开/关两态**逐像素完全相同**。
    外审枚举轮当场点名其中一颗：「**紫色**勾选框…让人以为此刻已经开启生效」。

    ⭐⭐⭐ **一个用容器类型当代理的分母，会漏掉所有没用那个容器的地方，
    而判据会因为「卡都降权了」而全绿。**（同 RN-425：批 16 审的是
    「我改的那三件东西」，不是「屏幕上还有什么在发亮」。）

    ⇒ 这条判据按**它开着时用不用强调色**划分母，直接抓像素：
    开着时身上有品牌色的控件，关着时必须显著变少。
    ⚠ 状态卡（那颗要去拨的开关所在的卡）不在分母里 —— 调暗出口等于把门锁上。
    """
    page = _open(main_window, qapp, page_id)
    rgb = _accent_rgb()
    host = eff.status_card_of(page)
    row = getattr(page, "master_switch_row", None)

    def in_the_way_out(w):
        if host is not None and (w is host or host.isAncestorOf(w)):
            return True
        return row is not None and (w is row or row.isAncestorOf(w))

    _set_switch(page, qapp, True)
    watched = []
    # ⭐ 分母走 `parameter_area_controls` —— **产品和判据共用同一个定义**。
    #   各写一份的话，判据会去量一个和产品不一样的分母，然后全绿。
    for w in eff.parameter_area_controls(page):
        if w.isHidden() or in_the_way_out(w):
            continue
        if w.width() < 4 or w.height() < 4:
            continue
        lit = _accent_pixels(w, rgb)
        if lit >= 20:                     # 开着时真的在用强调色的，才进分母
            watched.append((w, lit))

    # ⚠⚠ **反空转，而且这一条是回退验证逼出来的。**
    # 分母走 `parameter_area_controls`（产品和判据共用同一个定义），
    # 于是把那个定义弄坏时 —— 产品不再降权、判据的分母也同时变空 ——
    # **两边一起瞎，判据照样全绿**。
    # ⭐⭐⭐ **单一真相源让实现和判据保持一致，也让它们一起错。**
    # ⇒ 共用定义可以，但「这个定义还认得出东西吗」必须独立断言一次。

    _set_switch(page, qapp, False)
    qapp.processEvents()
    offenders = []
    for w, lit_on in watched:
        lit_off = _accent_pixels(w, rgb)
        if lit_off > lit_on * 0.3:        # 基本没退
            offenders.append(
                f"{type(w).__name__}:{(w.text() if hasattr(w, 'text') else '') or w.objectName() or '?'}"
                f"（开 {lit_on}px → 关 {lit_off}px）")
    assert not offenders, (
        f"{page_id}：总开关关着，参数区里还有 {len(offenders)} 个控件在用品牌强调色画——\n  "
        + "\n  ".join(offenders[:6]) +
        "\n⭐ 「这一片是活的」这个信号就是它们发出来的。")


#: 页面自己的「刷新一下底栏/状态」入口。⭐ 名字是**列出来的**，不是猜的：
#: 判据会断言每一页至少命中一个，命不中就红 —— 否则它会安静地什么都没验。
REFRESH_ENTRIES = ("_sync_action_bar", "_refresh_dirty_ui", "_update_action_bar",
                   "_sync_status_strip", "_sync_overview_status", "_update_status",
                   "_refresh_status_badge", "_sync_community_guidance",
                   "_refresh_style_overview")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_the_receipt_survives_the_page_refreshing_itself(main_window, qapp, page_id):
    """⭐⭐ **一条守卫的输入如果能被一次常规操作顺手改写，那条守卫就不是守卫。**

    批 16 把这句话写进了 `PageActionBar._render_message` 的注释里，并把守卫
    建在**入口**（`set_message`）上：页面随时再调一次，回执照样会被重新拼回去。

    ⚠⚠ 而 `hud_color` 拿到的是**入口里面那个控件**：
    `self.save_hint_label = self.action_bar.message_label`，
    然后直接 `setText(...)` —— 实测（批 19）：

        拨完开关：       「总开关关着——…不生效…」+ 页面自己那句   ✓
        跑一次 `_refresh_dirty_ui()`：  只剩页面自己那句           ✗

    而 `_refresh_dirty_ui` 在**用户改任何一个设置时都会跑**。
    ⇒ **玩家一动手，那条回执就没了**，剩下的那句还恰好在说
    「点保存，设置才会生效」（外审：「误以为只要点保存就会在游戏内生效，
    无需开启总开关」）。

    ⭐⭐ **守卫建在入口上，而那一页拿到了入口里面那个控件的引用** ——
    这不是有人绕过规则，是规则的边界**没有覆盖到它自己暴露出去的那个引用**。
    ⭐ 所以这条判据不钉「hud_color 那一处」，钉的是**行为**：
    页面自己刷新一遍之后，回执必须还在。
    """
    page = _open(main_window, qapp, page_id)
    _set_switch(page, qapp, False)
    # ⚠ 批 24：回执现在有两套 —— 自动保存的页一套、手动保存的页另一套
    #   （`SAVES_AUTOMATICALLY`）。这条判据钉的是**行为**（刷新之后回执还在），
    #   所以它要问「这一页该用哪一句」，而不是写死其中一句。
    #   ⭐ 一条钉行为的判据，不该把某个具体取值抄进自己身上。
    expected = (eff.ACTION_BAR_OFF_TEXT if eff.saves_automatically(page)
                else eff.ACTION_BAR_OFF_TEXT_MANUAL)
    assert expected and expected in page.action_bar.message_label.text(), (
        f"{page_id}：拨完开关，底栏那条回执就没出现")

    import inspect

    called = []
    for name in REFRESH_ENTRIES:
        fn = getattr(page, name, None)
        if not callable(fn):
            continue
        # ⚠ 只调**不用给参数**的那些。第一版没查签名，`death_sound` 的
        # `_refresh_style_overview(style)` 当场把判据炸成 TypeError ——
        # ⭐ 那会读成「这一页坏了」，而其实是判据自己调错了。
        try:
            sig = inspect.signature(fn)
            if any(prm.default is inspect.Parameter.empty
                   and prm.kind in (prm.POSITIONAL_ONLY,
                                    prm.POSITIONAL_OR_KEYWORD)
                   for prm in sig.parameters.values()):
                continue
        except (TypeError, ValueError):        # 签名读不到就别碰
            continue
        fn()
        called.append(name)
        qapp.processEvents()
    # ⚠ 反空转：一个方法都没调到的话，下面那条断言**永远为真**。
    assert called, (
        f"{page_id}：一个刷新入口都没命中 —— 这条判据在这一页上是空转的。\n"
        "⭐ 名单在 REFRESH_ENTRIES，页面换了名字就把新名字加进去。")
    assert expected in page.action_bar.message_label.text(), (
        f"{page_id}：页面自己刷新了一遍（{called}），底栏那条回执被冲掉了。\n"
        "⭐ 页面要改底栏那句话，只能走 `action_bar.set_message(...)`，"
        "不许直接对 `message_label` 写字。")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_the_status_strip_is_titled_by_what_it_actually_lists(
        main_window, qapp, page_id):
    """⚖ **RN-428：那条胶囊的标题叫「当前状态」，而它列的是配置。**

    ⚠⚠ 本条立案时我写的说法是「**「当前」这两个字在说时间**」——
    **枚举一遍就把它推翻了**：`crosshair` 有 **7 条**「当前X」摘要
    （当前样式：点 / 当前颜色：红色 / 当前档位…），而它在外审枚举轮
    **3/3 报 NONE**。⇒ 触发误读的不是那两个字。

    真正在触发的是**描述「某件事发生时会自动做什么」**的条目：

        music        「当前策略：**阵亡后自动开始/继续播放** · 存活时自动降低到 20%」
        voice_output 「当前路由：… **本地监听开启**」
        hud_color    「**事件 · 2 项**」
        utility      「地图 · **未检测到**」（探测器语气）

    而「当前样式：点」是**静态属性**，没有「在跑」的东西可想象。
    ⭐⭐ **一个读起来像实时读数 / 像规则引擎的东西，光是存在就在暗示
    有个进程在跑；而一个静态属性不会。**

    ⇒ 这条改动**不去逐句改那些摘要**，只改一处**共用**的东西：
    胶囊组的标题。它一次性给整条胶囊重新定性 ——
    关着的时候，那一条列的是**配置**，不是**状态**。
    ⭐ 标题是这条胶囊里唯一一个「说这一整条是什么」的位置。
    """
    page = _open(main_window, qapp, page_id)
    label = eff.status_strip_title(page)
    # ⚠ 反空转：找不到那个标题的话，下面两条断言**永远为真**。
    assert label is not None, (
        f"{page_id}：在状态卡里没找到那条胶囊的标题 —— "
        "这条判据在这一页上是空转的（多半是标题改了名或搬了家）。")

    _set_switch(page, qapp, True)
    assert label.text() == eff.STRIP_TITLE_ON, (
        f"{page_id}：开着的时候标题是「{label.text()}」，该是「{eff.STRIP_TITLE_ON}」")

    _set_switch(page, qapp, False)
    assert label.text() == eff.STRIP_TITLE_OFF, (
        f"{page_id}：关着的时候标题还写着「{label.text()}」——"
        f"该是「{eff.STRIP_TITLE_OFF}」。\n"
        "⭐ 没在跑的时候，那一条列的是配置，不是状态。")
