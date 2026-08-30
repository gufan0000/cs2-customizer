# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 32 · `music`：这一页说的「怎么放」和「删了还能不能找回来」得是真的。

## 三条各自的实测起点（2026-08-31）

### ① 页面把新用户指向一条**此刻不存在**的控制栏（RN-455）

`music_control_bar` 由 `MainWindow._create_music_control_bar_if_played` 建，
而它的闸门是 `music_player.playback_has_ever_started()` —— **没放过音乐就不建**
（RN-195，批 9，我自己改的）。实测全新用户：

    playback_has_ever_started() = False   ⇒   win.music_control_bar is None

而同一屏上：

  · 页头副标题逐字写着「**底部控制栏是手动播放**」；
  · 帮助面板「使用方法」第 2 步写着「使用**底部控制栏**播放、暂停、切换曲目」，
    第 3 步「调整**音量滑块**控制播放音量」（那个滑块也长在控制栏上，
    页面上那两个滑块是「死亡音量 / 存活音量」，不是播放音量）。

⭐⭐⭐ **一个正确的收窄，把它自己的入口关在了自己后面。**
控制栏只在「放过音乐」之后才出现，而「放过音乐」这个动作原本就该由它来触发；
真正能触发它的只有**双击列表项**，而页面上提到双击的只有「列表切换」卡的一句
小字，措辞还是「立刻**切歌**」（切歌 ≠ 开始播放），且它在 y=1306、**露出 0%**。

⚠⚠ 而这条缺陷**只在一个从没被任何一轮出图拍到过的状态下显形**：
审计中和表把 `music_default_song_added` 钉成 True（对的，审计不许联网），
于是历轮拍的全是「离线新用户 · 空列表」；而真实的新用户联网后
`MusicPlayer.__init__` 会自动下载并加一首默认歌 ⇒ **有歌、没播过、没有控制栏**。
外审在这两档上的票数差得极远：

  | 场景 | 「说有底部控制栏却找不到播放控件」判高 |
  |---|---|
  | 空列表（历轮唯一拍到过的） | **1/8** |
  | 1 首默认歌（多数真实新用户） | **7/8** |
  | 5 首 + 控制栏在（老用户） | **0/8** |

⭐⭐ 空列表那一档之所以不报，是因为「没歌当然放不了」把问题遮住了 ——
**遮住它的不是产品做对了，是那一档本身让人问不出这个问题。**

### ② 三颗一模一样的红，唯一挽不回的那颗最不显眼（RN-457）

AST 实测：

  | 按钮 | 确认框 | `toast_undo` |
  |---|---|---|
  | 删除（整张歌单） | 有 | **有** |
  | 删除选中 | 有 | **有** |
  | 清空列表 | 有 | **没有** |

外审 18/18 发说「这三颗按钮的红色完全相同、**没有区分**危险程度」，
而 16/18 猜「删除」最难挽回、只有 2/18 提到「清空列表」。
⭐⭐⭐ **他们按「名字听起来多严重」排序，而那个排序和真实的可挽回性正好错开 ——
唯一真挽不回的那一颗，18 发里只有 2 发注意到。**

⇒ 修法不是「把颜色改得不一样」，是**把「三颗一样」这句话变成真的**：
给「清空列表」补上同样的 8 秒撤销。
⭐ 一句话被读错时，先问它是不是本来就该是真的。

### ③ 判据自己钉住了一个没人看得见的控件（RN-458）

`music_summary_label` 是 RN-009 那一族的又一个：`__init__` 里 `hide()`，
此后每次同步都往里写 9 行 115 字的详情，**全仓 0 处 `show()` / `setVisible()`**（AST）。

⭐⭐⭐ 但这一次多出来一层：**它身上挂着判据。**
`test_about_music_ui_polish` 逐字断言那 9 行里写了什么
（`"游戏联动：已启用" in page.music_summary_label.text()`），
`test_music_page_toolbar_state` 断言里面有 `"65%"`。
⇒ **一个死控件活下来的机制，是有人给它写了判据。**
而 RN-009 的棘轮只数「还剩几个」，数不出「有几个被判据焊死了」——
所以它从 M3-b 之后一直停在 18。

⇒ 下面那条 `test_no_judge_pins_text_inside_a_control_nobody_can_see`
是给**判据自己**加的一道：不许断言用户永远看不到的文字。
详情文本本身留着（它喂 `music_overview_card` 的 tooltip，那个用户悬停得到）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "pages" / "music_page.py"
HELP = REPO / "ui_help_panel.py"

#: 「在控制栏出现之前怎么开始放」——页面必须自己说出来的那个动作。
#: ⚠ 只钉**动作**，不钉整句话：文案还会被润色，钉整句等于禁止润色。
START_PLAYING_WORD = "双击"

#: 指向那条**可能不在场**的控制栏的说法。出现它就必须同屏给出 `START_PLAYING_WORD`。
#: ⚠ 只钉「控制栏」三个字，不钉「底部控制栏 / 底部音乐控制栏 / 底部常驻控制栏」
#: 那一串具体写法 —— 第一版列了三种，改完文案换成「窗口底部会常驻一条控制栏」，
#: 三种一个都不匹配，判据当场变成**空转**（`hits` 为空）。
#: ⭐ **一条按枚举写法匹配的判据，会被一次正常的润色绕开。**
BAR_WORDS = ("控制栏",)


def _page_src() -> str:
    return PAGE.read_text(encoding="utf-8")


def _help_text_for_music() -> str:
    """帮助面板里 `music` 那一条的正文（走 AST，不做括号配对）。"""
    tree = ast.parse(HELP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "music":
                return ast.literal_eval(value)
    pytest.fail("帮助面板里找不到 music 那一条 —— 这条判据已经瞎了")


# ------------------------------------------------ ① 别指向不在场的控制栏

def _sentences_naming_the_bar(text: str) -> list[str]:
    """把文本切成句子，挑出提到那条控制栏的。

    ⚠ 分句用中文标点 + `<br>`：帮助面板是 HTML 片段。
    """
    flat = re.sub(r"<[^>]+>", "\n", text)
    parts = re.split(r"[。；;\n]+", flat)
    return [p.strip() for p in parts if p.strip() and any(w in p for w in BAR_WORDS)]


def _mentions_the_real_entrance(text: str) -> bool:
    return START_PLAYING_WORD in re.sub(r"<[^>]+>", "", text)


def test_the_bar_sentence_detector_is_not_blind():
    """⭐ 先证明它看得见东西，再让它去断言「没问题」（RN-169）。"""
    synthetic = "放本地音乐或在线 URL。底部控制栏是手动播放；这里只管自动接管。"
    assert _sentences_naming_the_bar(synthetic), "分句器没认出那条控制栏 —— 已经瞎了"
    assert not _mentions_the_real_entrance(synthetic), (
        "阳性对照写错了：这段合成文案本该不含真正的入口"
    )


def test_the_page_header_does_not_point_at_a_bar_that_may_not_be_there():
    """页头提到那条控制栏时，必须同时说出**在它出现之前**怎么开始放。

    ⇒ 不是禁止提控制栏（它对老用户是真的），是禁止**只**提它。
    """
    src = _page_src()
    m = re.search(r'description=\(?\s*"([^"]+)"', src) or re.search(
        r'description="([^"]+)"', src)
    assert m, "页头 description 读不出来 —— 判据瞎了（PageHeader 改写法了？）"
    lead = m.group(1)
    if _sentences_naming_the_bar(lead):
        assert _mentions_the_real_entrance(lead), (
            f"页头副标题把「底部控制栏」说成播放入口，却没说在它出现之前怎么开始放：\n"
            f"  {lead}\n"
            f"⚠ 全新用户 `playback_has_ever_started()` 为假 ⇒ 那条栏**根本没建**"
            f"（RN-195，批 9）。这句话对他是假的。\n"
            f"⇒ 把真正的入口（{START_PLAYING_WORD}列表里的歌）写进这一句。"
        )


def test_the_help_panel_does_not_point_at_a_bar_that_may_not_be_there():
    """帮助面板「使用方法」同理 —— 第 2 步原来直接写「使用底部控制栏播放」。"""
    text = _help_text_for_music()
    hits = _sentences_naming_the_bar(text)
    assert hits, "帮助面板里一句都没提到那条控制栏 —— 要么它被删干净了，要么判据瞎了"
    assert _mentions_the_real_entrance(text), (
        "帮助面板教用户用「底部控制栏」放音乐，全篇却没说在它出现之前怎么开始放。\n"
        + "\n".join(f"  · {h}" for h in hits)
        + f"\n⇒ 补上「{START_PLAYING_WORD}」那一步。"
    )


def test_the_empty_playlist_hint_says_how_to_start_playing():
    """空列表那一项原来只说「使用底部操作栏添加音乐」——只讲加，不讲放。"""
    src = _page_src()
    m = re.search(r'QListWidgetItem\("(播放列表为空[^"]*)"\)', src)
    assert m, "空列表那一项读不出来 —— 判据瞎了"
    hint = m.group(1)
    assert START_PLAYING_WORD in hint, (
        f"空列表引导只讲了怎么加，没讲加完怎么放：\n  {hint!r}\n"
        f"⇒ 这一页没有任何播放控件，加完之后用户唯一能做的就是{START_PLAYING_WORD}。"
    )


# ------------------------------------------------ ② 同色的红必须同样能撤销

def _danger_buttons_and_their_slots(src: str) -> dict[str, str]:
    """`style_as_danger_button(x)` 涂过的按钮 → 它 `clicked` 绑的方法名。"""
    tree = ast.parse(src)
    danger: dict[str, str | None] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "style_as_danger_button" and n.args \
                and isinstance(n.args[0], ast.Name):
            danger.setdefault(n.args[0].id, None)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "connect" \
                and isinstance(n.func.value, ast.Attribute) \
                and n.func.value.attr == "clicked" \
                and isinstance(n.func.value.value, ast.Name) \
                and n.func.value.value.id in danger and n.args:
            tgt = n.args[0]
            if isinstance(tgt, ast.Attribute):
                danger[n.func.value.value.id] = tgt.attr
    return {k: v for k, v in danger.items() if v}


def _slots_with_undo(src: str) -> set[str]:
    """哪些处理函数里**真的调了** `toast_undo(...)`。

    ⚠⚠ **第一版是 `"toast_undo" in ast.dump(f)`，回退验证判它假绿。**
    因为 `_clear_playlist` 里那句 `from ui_toast import toast_undo` 也在树里 ——
    把调用删掉、只留 import，这条判据照样绿。
    ⭐⭐⭐ **用 AST 拿到树，然后对树做字符串匹配，等于绕了一圈又回到 grep** ——
    而「查有没有调用一律走 AST」这条规矩，防的正是这个。
    ⇒ 只认 `ast.Call`，且被调的名字解析出来是 `toast_undo`。
    """
    tree = ast.parse(src)
    out = set()
    for f in ast.walk(tree):
        if not isinstance(f, ast.FunctionDef):
            continue
        for n in ast.walk(f):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else "")
            if name == "toast_undo":
                out.add(f.name)
                break
    return out


#: 合成源码：两颗红，一颗有撤销一颗没有。**阳性对照不碰真文件。**
_SYNTHETIC_PAGE = '''
from page_theme_helper import style_as_danger_button


class P:
    def build(self):
        wipe_btn = QPushButton("清空")
        style_as_danger_button(wipe_btn)
        wipe_btn.clicked.connect(self._wipe)
        drop_btn = QPushButton("删除")
        style_as_danger_button(drop_btn)
        drop_btn.clicked.connect(self._drop)

    def _wipe(self):
        self.store.clear()

    def _drop(self):
        backup = list(self.store)
        self.store.pop()
        toast_undo("已删除", lambda: None)
'''


def test_the_undo_check_catches_a_red_button_without_undo():
    """⭐ 阳性对照：合成页里 `_wipe` 没有撤销，必须被逮住。"""
    danger = _danger_buttons_and_their_slots(_SYNTHETIC_PAGE)
    undo = _slots_with_undo(_SYNTHETIC_PAGE)
    assert set(danger.values()) == {"_wipe", "_drop"}, danger
    naked = sorted(s for s in danger.values() if s not in undo)
    assert naked == ["_wipe"], f"阳性对照应当且只应当逮住 _wipe，实际 {naked}"


def test_every_red_button_on_the_music_page_can_be_undone():
    """⭐⭐ 同一屏上被涂成同一种红的按钮，**可挽回性必须一致**。

    否则那三颗一样的红就是在说一句假话，而用户没有别的信息可以依据 ——
    实测他们改用「名字听起来多严重」排序，结果和真相正好错开。
    """
    src = _page_src()
    danger = _danger_buttons_and_their_slots(src)
    assert len(danger) >= 3, (
        f"只认出 {len(danger)} 颗红按钮（{sorted(danger)}）—— 这一页实测有三颗"
        "（删除 / 删除选中 / 清空列表）。分母不对，这条判据已经瞎了。"
    )
    undo = _slots_with_undo(src)
    naked = sorted(slot for slot in danger.values() if slot not in undo)
    assert not naked, (
        "这几颗按钮跟旁边那几颗红得一模一样，却没有撤销兜底：\n"
        + "\n".join(f"  {slot}" for slot in naked)
        + "\n⇒ 要么补上 `toast_undo`，要么别让它跟有兜底的那几颗长得一样。"
    )


# ------------------------ ②b 撤销要真的把东西放回屏幕上，不是"调过 toast_undo"

def test_the_real_player_serves_its_own_list_not_the_config():
    """⭐⭐ 先钉住下面那个假播放器**在被测维度上**跟真的一样。

    ⚠ 上一条只查「有没有调 `toast_undo`」，那是**零件好使**；
    这一页真正出过的事故是「调了，但撤销写错了地方」——
    ⭐ **只测「零件好使」证明不了「零件装上了」**（批 10 / 批 12 各栽过一次）。

    下面那条行为判据要用假播放器，而假播放器只有在**复现同一个不对称**
    时才有意义：真源是 `player.playlist`，它由 `_save_playlist()` **单向**
    写进 `config.music_playlists`；`get_playlist()` 交的是前者，不是后者。
    ⇒ 这里用 AST 把这个不对称钉死。它一变，下面那条就该重写，而不是继续绿着。
    """
    tree = ast.parse((REPO / "music_player.py").read_text(encoding="utf-8"))
    funcs = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}
    for name in ("get_playlist", "_save_playlist", "restore_playlist"):
        assert name in funcs, f"`MusicPlayer.{name}` 不见了 —— 这条判据已经瞎了"
    served = ast.dump(funcs["get_playlist"])
    assert "playlist" in served and "music_playlists" not in served, (
        "`get_playlist()` 现在会去读 config 了 —— 那个不对称没了，"
        "下面那条行为判据用的假播放器**不再是真播放器的忠实模型**，请重写它。"
    )
    saved = ast.dump(funcs["_save_playlist"])
    assert "music_playlists" in saved, (
        "`_save_playlist()` 不再往 config 写 —— 同上，假件的前提变了。"
    )


class _RecordingPlayer:
    """只保留被测那一半的假播放器：**列表是真源，config 是下游。**"""

    def __init__(self, store, name="默认"):
        self.store = store                 # 扮演 config.music_playlists
        self.current_playlist_name = name
        self.playlist = [dict(t) for t in store.get(name, [])]
        self.current_index = -1
        self.is_playing = False
        self.is_paused = False
        self.on_playlist_update = None
        self.on_playlist_change = None

    # —— 真源侧 ——
    def get_playlist(self):
        return list(self.playlist)

    def _save(self):
        self.store[self.current_playlist_name] = [dict(t) for t in self.playlist]

    def remove_track(self, index):
        if 0 <= index < len(self.playlist):
            self.playlist.pop(index)
            self._save()

    def clear_playlist(self):
        self.playlist.clear()
        self._save()

    def restore_playlist(self, tracks):
        self.playlist = [dict(t) for t in (tracks or [])]
        self._save()

    # —— 页面还会碰到的边角 ——
    def get_all_playlists(self):
        return list(self.store.keys())

    def switch_playlist(self, name):
        self.current_playlist_name = name
        self.playlist = [dict(t) for t in self.store.get(name, [])]

    def get_current_track(self):
        return None

    def set_play_mode(self, mode):
        pass


def test_the_recording_player_reproduces_the_bug_when_undo_writes_to_config():
    """⭐ 阳性对照：**假播放器必须能重现原来那个 bug**，否则它证明不了修好了。

    模拟旧写法（撤销只往 `store` 里插回）⇒ `get_playlist()` 一动不动。
    """
    store = {"默认": [{"title": "a"}, {"title": "b"}]}
    player = _RecordingPlayer(store)
    player.remove_track(1)
    assert len(player.get_playlist()) == 1
    store["默认"].insert(1, {"title": "b"})          # ← 旧写法：只写下游
    assert len(player.get_playlist()) == 1, (
        "假播放器没能重现那个不对称 —— 它对 config 的改动有反应，"
        "而真播放器没有。这个假件是坏的。"
    )
    player.restore_playlist([{"title": "a"}, {"title": "b"}])   # ← 新写法
    assert len(player.get_playlist()) == 2


@pytest.mark.parametrize("action", ["_delete_selected", "_clear_playlist"])
def test_undo_actually_puts_the_tracks_back_on_screen(action, monkeypatch):
    """⭐⭐⭐ 撤销要把曲目放回**屏幕**，不是放回配置文件。

    2026-08-31 实测原状：点完「删除选中」的撤销之后
    **config 5 首、`player.playlist` 4 首、屏幕 4 首** ——
    用户看到什么都没发生，以为撤销坏了；而那首歌躺在配置里，
    下次启动会自己回来，在此之前任何一次删除都会把它再覆盖掉。
    ⭐ **写在下游的撤销，会安静地把内存和磁盘拆成两份。**
    """
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    import pages.music_page as mod
    import ui_toast

    tracks = [{"title": f"t{i}", "path": f"D:/{i}.mp3", "duration": 60}
              for i in range(4)]
    store = {"默认": [dict(t) for t in tracks]}
    player = _RecordingPlayer(store)
    monkeypatch.setattr(mod, "get_music_player", lambda: player)
    monkeypatch.setattr(mod.config, "music_playlists", store, raising=False)
    monkeypatch.setattr(mod.config, "music_current_playlist", "默认", raising=False)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.Ok))
    captured = {}
    monkeypatch.setattr(ui_toast, "toast_undo",
                        lambda text, cb, *a, **k: captured.update(cb=cb, text=text))

    page = mod.MusicPage()
    try:
        app.processEvents()
        before = page.playlist_widget.count()
        assert before == len(tracks), f"起点就不对：屏幕上 {before} 行"

        if action == "_delete_selected":
            page.playlist_widget.item(1).setSelected(True)
            page._on_playlist_selection_changed()
        getattr(page, action)()
        app.processEvents()
        assert page.playlist_widget.count() < before or \
            "播放列表为空" in page.playlist_widget.item(0).text(), "删除本身没生效"

        assert "cb" in captured, (
            f"`{action}` 一颗红按钮，删完**没有给撤销** —— "
            "而旁边那两颗同样红的给了。"
        )
        captured["cb"]()
        app.processEvents()
        assert page.playlist_widget.count() == before, (
            f"点了撤销，屏幕上还是 {page.playlist_widget.count()} 行（应当 {before}）。\n"
            f"player 手上 {len(player.get_playlist())} 首、config 里 "
            f"{len(store['默认'])} 首 —— 这两个数不一样就是**撤销写错了地方**。"
        )
        assert len(player.get_playlist()) == len(store["默认"]) == before, (
            "内存和磁盘对不上 —— 撤销只改了其中一边。"
        )
    finally:
        page.deleteLater()
        app.processEvents()


# --------------------------------- ③ 判据不许钉住一个没人看得见的控件

def _invisible_label_attrs(src: str) -> set[str]:
    """本文件里「建了、hide 了、没人 show」的 `self.<x>` 标签名。"""
    tree = ast.parse(src)
    created, hidden, shown = set(), set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and t.attr.endswith("_label"):
                    created.add(t.attr)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            owner = n.func.value
            if isinstance(owner, ast.Attribute) and owner.attr.endswith("_label"):
                if n.func.attr == "hide":
                    hidden.add(owner.attr)
                elif n.func.attr in ("show", "setVisible"):
                    shown.add(owner.attr)
    return (created & hidden) - shown


def test_the_invisible_label_detector_is_not_blind():
    synthetic = '''
class P:
    def build(self):
        self.ghost_label = QLabel("")
        self.ghost_label.hide()
        self.real_label = QLabel("")
        self.real_label.hide()
        self.real_label.show()
'''
    assert _invisible_label_attrs(synthetic) == {"ghost_label"}


def test_no_judge_pins_text_inside_a_control_nobody_can_see():
    """⭐⭐⭐ **一个死控件活下来的机制，是有人给它写了判据。**

    RN-009 的棘轮只数「还剩几个」。它数不出「有几个被判据焊死了」，
    于是那几个的删除成本被悄悄抬高了一整级 —— 而抬高它的正是我们自己。

    这里只管 `music_page`：它是本批清的那一个。
    ⛔ 不冒充全站覆盖 —— 别的页各自那一份，跟着各自那一批走。
    """
    ghosts = _invisible_label_attrs(_page_src())
    assert not ghosts or ghosts == set(), (
        f"`pages/music_page.py` 里还有建了就 hide、没人 show 的标签：{sorted(ghosts)}\n"
        "⇒ 它每次同步都被写进几十个字，而那些字一个像素都不会出现在屏幕上。"
    )
    #: ⚠ 只盯 music 页那一个名字。第一版的条件写成
    #:   `"music" in attr or "music_page" in src and attr == "summary_label"`
    #: —— 优先级把它变成「任何提到 music_page 的测试文件里，**任何一页**的
    #: `summary_label` 断言都算」，于是它去诬告别的页。
    #: ⭐ **一个分母悄悄扩大了的判据，报出来的东西看着跟真缺陷一模一样。**
    pinned = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # 注释里留个名字是档案，不是判据
            if re.search(r"\.music_summary_label\b", line):
                pinned.append(f"{path.name}:{line_no}  {line.strip()[:60]}")
    assert not pinned, (
        "还有判据在断言 music 页那个没人看得见的标签：\n"
        + "\n".join("  " + p for p in pinned)
        + "\n⇒ 改成断言用户真的够得着的那一处（`music_overview_card` / "
        "`status_card` 的 tooltip）。"
    )


# ------------------------- ③b 第一屏上要能做这一页是干什么的那件事

def test_the_playlist_comes_before_the_link_settings_in_the_source():
    """⭐⭐ RN-456 的**主判据**：滚动内容里，播放列表必须排在联动设置**之前**。

    ⚠⚠ 这条本来是拿真几何量的（「曲目列表整个落在第一屏 584px 内」），
    而那条在**测试进程里恒 skip** —— conftest 把平台钉成 offscreen，
    字体库为空，量出来的版面用户从没见过（批 26 那条）。
    ⭐ **一条永远 skip 的判据不是判据。**
    ⇒ 主判据改成**字体无关**的那一半：源码里的先后顺序。几何那条留着当附加，
      有字体时才跑（本机跑得到，CI 上 skip）。

    ⚠ 走 AST 读 `init_ui` 里 `scroll_layout` 的调用次序 —— 不是 grep 行号：
    `_create_playlist_management()` 建在哪儿不重要，**加进布局的次序**才重要。
    """
    tree = ast.parse(_page_src())
    init = next((f for f in ast.walk(tree)
                 if isinstance(f, ast.FunctionDef) and f.name == "init_ui"), None)
    assert init is not None, "`init_ui` 不见了 —— 判据瞎了"
    order: list[str] = []
    for n in ast.walk(init):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if not (isinstance(n.func.value, ast.Name)
                and n.func.value.id == "scroll_layout"):
            continue
        if n.func.attr not in ("addWidget", "addLayout") or not n.args:
            continue
        a = n.args[0]
        name = a.id if isinstance(a, ast.Name) else (
            a.attr if isinstance(a, ast.Attribute) else "<?>")
        order.append(name)
    assert len(order) >= 3, f"只读出 {order} —— 布局改写法了，判据已经瞎了"
    assert "playlist_group" in order and "top_settings_row" in order, (
        f"认不出这两块了：{order}"
    )
    assert order.index("playlist_group") < order.index("top_settings_row"), (
        f"播放列表又排到联动设置后面去了：{order}\n"
        "⭐ 这一页叫「音乐播放」：列表是**内容**，联动是**配置**，内容在前。\n"
        "⚠ 而页头逐字写着「双击列表里的歌就开始放」——\n"
        "  实测把列表放在后面时，外审 **8/8** 报「提示双击列表里的歌，"
        "但界面完全看不到歌曲列表」。"
    )


def test_the_playlist_is_above_the_fold(monkeypatch):
    """⭐⭐⭐ RN-456：一个叫「音乐播放」的页面，第一屏上得能看见歌。

    改前实测（1280×900，滚动视口 684 / 内容 1613）：**第一屏只装得下 42%**，
    24 个可交互控件里 12 个露出 0%，而露出 0% 的正好是「播放模式」四选一
    加上**整个播放列表区** —— 第一屏上一件跟「放音乐」有关的事都做不了。

    ⚠⚠ **这条判据不许去数「露出 0% 的有几个」。**
    把列表提到联动之前以后，那个数从 12 **变成了 16** —— 因为联动那 12 个
    参数控件掉到了折线下面。⭐⭐⭐ **一个只数「藏了几个」的判据，
    会把这次改动判成退步**；而这次搬的不是「少藏一点」，是「藏对的东西」。
    ⇒ 判据钉**对象**：这一页的主体（曲目列表和它的操作）必须在第一屏上。

    ⚠ 走真窗口量几何。字体缺失时几何没有意义（批 26 那条：判据跑在一个
    没有中文字体的进程里，量的是用户没见过的版面）⇒ 字体库为空就 skip。
    """
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QListWidget

    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        pytest.skip("字体库为空 —— 这里量的几何跟用户看到的版面不是一回事")

    import pages.music_page as mod

    class _P:
        current_playlist_name = "默认"
        current_index = -1
        is_playing = False
        is_paused = False
        on_playlist_update = None
        on_playlist_change = None

        def __init__(self):
            self.playlist = [{"title": f"曲目{i}", "path": f"D:/{i}.mp3",
                              "duration": 60} for i in range(3)]

        def get_playlist(self):
            return list(self.playlist)

        def get_all_playlists(self):
            return ["默认"]

        def switch_playlist(self, name):
            pass

        def get_current_track(self):
            return None

        def set_play_mode(self, mode):
            pass

    monkeypatch.setattr(mod, "get_music_player", _P)
    page = mod.MusicPage()
    try:
        page.resize(1042, 800)          # 内容区实测宽度，视口高给足
        app.processEvents()
        scroll = page.settings_scroll
        content = scroll.widget()
        #: 真实产品在 1280×800 / 1280×900 两档下的滚动视口高（实测 584 / 684）。
        #: 取**小的那一档**：判据要挡的是最坏情况。
        VIEWPORT = 584
        lw = page.playlist_widget
        assert isinstance(lw, QListWidget)
        top = lw.mapTo(content, lw.rect().topLeft()).y()
        bottom = top + lw.height()
        assert lw.height() > 0, "曲目列表高度为 0 —— 判据瞎了"
        assert bottom <= VIEWPORT, (
            f"曲目列表落在第一屏之外：y={top}..{bottom}，而滚动视口只有 {VIEWPORT}px。\n"
            "⭐ 页头写着「双击列表里的歌就开始放」—— 那句话指向的东西必须看得见。\n"
            "改完复跑实测：话写上去而列表还在折线下，外审 **8/8** 报"
            "「提示双击列表里的歌，但界面完全看不到歌曲列表」（改前 0 发）。"
        )
        #: 反向：别把联动那一整组挤没了 —— 它得还在页面里（在折线下是可以的）。
        assert page.game_link_checkbox.isVisibleTo(page), (
            "「允许游戏状态自动控制音乐」不见了 —— 搬列表不是删联动。"
        )
    finally:
        page.deleteLater()
        app.processEvents()


# ------------------------------------------------ ④ 同一件事别说五遍

#: 「底部（常驻）播放器」在「播放设置」这张卡里出现的处数上限。**只许调小。**
#: 2026-08-31 起点 **5**（可见文字 4 + tooltip 1），而卡里真正的内容只有 4 个单选钮；
#: 本批删掉两句改写、删掉一句**从建页那一刻就被覆盖掉、一次都没生效过**的静态 tooltip
#: ⇒ 3。⭐ 外审 18/18 全部答对了「这个设置管的是底部播放器」——
#: 说明这件事**早就传达成功了**，多说的四遍是纯成本。
MAX_BOTTOM_PLAYER_MENTIONS = 3


def _bottom_player_mentions(src: str) -> list[str]:
    """`_create_play_settings` / `_sync_play_settings_panel` 里提到它的**源码字面量**。

    ⚠⚠ 第一版把 f-string **和它自己的片段各数了一遍** —— 起点算成 9，
    而屏幕上只有 5 处。⭐ 一个数错了的起点，会让棘轮从第一天起就是松的
    （它会容忍 4 处重复，而我以为它只容忍 0 处）。
    ⇒ f-string 只算它自己，`ast.walk` 顺带走到的那些片段全部跳过。

    ⚠ 这里数的是**源码里有几处这么写**，不是**屏幕上出现几次**（`detail_text`
    一处源码喂了两个 tooltip）。两个数不一样，别混着读。
    """
    tree = ast.parse(src)
    out: list[str] = []
    for f in ast.walk(tree):
        if not isinstance(f, ast.FunctionDef):
            continue
        if f.name not in ("_create_play_settings", "_sync_play_settings_panel"):
            continue
        consumed: set[int] = set()
        joined = [n for n in ast.walk(f) if isinstance(n, ast.JoinedStr)]
        for js in joined:
            for part in ast.walk(js):
                if part is not js:
                    consumed.add(id(part))
            text = "".join(
                v.value for v in js.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if "底部" in text and "播放器" in text:
                out.append(text)
        for n in ast.walk(f):
            if id(n) in consumed:
                continue
            if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and "底部" in n.value and "播放器" in n.value:
                out.append(n.value)
    return out


def test_the_play_mode_card_does_not_say_the_same_thing_five_times():
    said = _bottom_player_mentions(_page_src())
    assert said, "一处都没找到 —— 这条判据已经瞎了（函数改名了？）"
    assert len(said) <= MAX_BOTTOM_PLAYER_MENTIONS, (
        f"「底部…播放器」在播放设置这张卡里说了 {len(said)} 遍，上限 "
        f"{MAX_BOTTOM_PLAYER_MENTIONS}：\n"
        + "\n".join(f"  · {s}" for s in said)
        + "\n⇒ 那张卡真正的内容只有 4 个单选钮。"
    )
    assert len(said) >= MAX_BOTTOM_PLAYER_MENTIONS, (
        f"只剩 {len(said)} 处了，该把 MAX_BOTTOM_PLAYER_MENTIONS 收到这个数 ——"
        "棘轮不收紧等于没有棘轮。"
    )
