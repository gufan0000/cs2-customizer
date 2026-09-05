# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-429：本软件画在**游戏画面**上的东西，在 CS2 独占全屏下一个像素都出不来。

玩家在准心页 / 击杀图标页 / 屏幕特效页配了半天，进游戏什么都没有 ——
他不会想到是显示模式的问题，他会判定「这软件坏了」。
那正是 RN-407 家族整整六批在防的同一种误判。

## ⭐⭐ 分母：三种自动取法全部失败，所以它必须是**声明**

| 取法 | 结果 |
|---|---|
| 页面**一跳** import 了含 `WindowStaysOnTopHint` 的模块 | **漏**：只得到 crosshair / screen_effects / advanced |
| **传递闭包** | **滥**：`ui_toast`（软件自己的气泡）把几乎每一页都拉了进来 |
| 两跳 + 给 `ui_toast` 之类标 False | 仍然**漏 kill_icon** |

根因值得单记：

> ⭐⭐⭐ **「这一页配的东西会画在游戏画面上」这件事，在代码里根本没有一条边。**
> `kill_icon_page` 只负责**配置**，真正播放它的是 GSI 事件链上的
> `kill_icon_player` —— 页面和它的覆盖层之间没有任何 import 关系。

⇒ 唯一诚实的分母是**页面自己声明** `DRAWS_OVER_THE_GAME`，并配双向断言。
这不是退让，是**把一个代码里不存在的事实变成代码里存在的事实** ——
和批 21 是同一条教训的第二次应用（关系写在人的脑子里，机器读不到 ⇒ 提升成格子）。

## 阳性对照是免费的

`advanced`（OSD 提示）与 `fun_afterlife`（贴屏浏览器）**早就在正文里写了**这条前提。
它们声明 True 之后，本组判据对它们**天然是绿的** ——
⭐ **没有阳性对照的尺子，和一把只会读出一种答案的尺子分不开**（批 17）。
它们证明这几条判据认的是「这一页说没说」，不是「这一页有没有用我那个共用件」。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ⚠ **离屏主窗夹具直接复用，不自己再写一份。** 它做的中和不止「离屏」一件：
# `CS2C_SAFE_MODE_ACTIVE`、`_audit_neutralize`、拦 `QMessageBox`、
# 逐键快照/还原总开关。而 `kill_icon` 是**设备页**（`DEVICE_OWNING_PAGES`）——
# ⭐ 抄一份中和逻辑，漏掉其中任何一条就是**真的去起设备**，
#   而那条铁律（不打扰前台）没有判据看着，只有用户看得见。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

#: ⚠ 别名再导出：直接 `import main_window` 会被参数名遮蔽（ruff F811），
#: 而那个遮蔽是**真的**——同名参数确实盖住了模块级的名字，只是 pytest 靠
#: 名字查夹具所以照样能跑。⭐ 一条 `# noqa` 压住的警告里，藏着一个真问题。
main_window = _shared_main_window

PAGES = REPO / "pages"

#: 覆盖层模块必须表态的常量名：这层东西画给**游戏**看，还是画给**软件自己**看。
MODULE_FLAG = "DRAWN_OVER_THE_GAME"
#: 页面必须表态的常量名：这一页配的东西，进游戏后靠覆盖层显示吗。
PAGE_FLAG = "DRAWS_OVER_THE_GAME"

#: 机器信号：谁在建置顶窗口。⚠ 它只是**分母守卫的触发器**，不是分母本身 ——
#: `ui_toast` 也置顶，但玩家不会指望在 CS2 里看到它。
TOP_HINT = "WindowStaysOnTopHint"

#: ⚠ `.claude` 必须在这儿：本仓里躺着一份**残留的 git worktree**
#: （`.claude/worktrees/…`），里面是整个仓的另一份拷贝。第一版漏了它，
#: 判据当场把那份拷贝里的 `probe_r9b_splash.py` 和一支**测试**报成了产品模块。
#: ⭐ 一个「扫全仓」的分母，会把仓里恰好躺着的任何东西都算成产品。
_SKIP_DIRS = (".build", "build", "dist", "tests", "scripts", "_archive", ".claude", ".git")

#: 那句话必须同时把**该怎么做**和**否则会怎样**说清楚，各给一组同义写法。
#:
#: ⚠⚠ **这是同义词表，不是文案规范。** 第一版只认「无边框窗口 / 独占全屏」
#: 两个词，首跑当场把两个**阳性对照**判红 —— `advanced` 写的是「全屏独占」
#: （词序反的），`fun_afterlife` 写的是「全屏窗口化」。
#: ⭐⭐ **它们用不同的词说了同一件事，而我的判据在按我的词表认。**
#: 那样的判据量的不是「这一页说没说」，是「这一页有没有照我的话抄」。
#: ⇒ 判据认语义、不认措辞；⚠ 但它终究只能匹配文本，所以**列成数据、
#:   并明写它是同义词表** —— 有人换第三种说法时，红的是这张表，不是那一页。
SAY_WHAT_TO_DO = ("无边框窗口", "全屏窗口化", "窗口化", "窗口模式")
SAY_WHAT_BREAKS = ("独占全屏", "全屏独占")


def _module_files() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for f in REPO.rglob("*.py"):
        rel = f.relative_to(REPO).as_posix()
        if rel.split("/")[0] in _SKIP_DIRS:
            continue
        out.setdefault(f.stem, f)
    return out


def _flag_of(path: Path, name: str):
    """读模块级 `NAME = True/False`；没有就返回 None。⚠ 走 AST，不 import。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                if isinstance(node.value, ast.Constant) and isinstance(
                        node.value.value, bool):
                    return node.value.value
    return None


def _visible_text(page) -> str:
    """**这一页渲染出来之后，屏幕上真正有的字。**

    ⚠⚠ 第一版扫的是页面源码里的字符串字面量，首跑把我刚改好的三页全判红 ——
    因为那句话住在**共用件** `widgets/overlay_requirement.py` 里，
    页面文件里一个字都没有。
    ⭐⭐ **判据问的必须是「屏幕上有没有」，不是「这个文件里有没有」** ——
    源码位置只是一个代理，而代理会漏（RN-427 那条教训的第三次现身）。

    ⚠ 帮助面板**不算**：它藏在一颗按钮后面，`isVisibleTo` 为假，
    自然不进这里。而这条前提要在玩家**开始配之前**看到 ——
    ⭐ 「解释性文字放在困惑发生的位置之前」，放在别处等于没放
    （`screen_effects` 这条前提原来就只写在折叠面板里）。
    """
    from PySide6.QtWidgets import QLabel

    return "\n".join(
        label.text() for label in page.findChildren(QLabel)
        if label.isVisibleTo(page) and label.text()
    )


def _page_files() -> list[Path]:
    return sorted(PAGES.glob("*_page.py"))


def _declared_pages(value: bool) -> list[Path]:
    return [p for p in _page_files() if _flag_of(p, PAGE_FLAG) is value]


# ------------------------------------------------------------------ 判据

def test_every_always_on_top_module_says_who_it_is_drawn_for():
    """① 分母守卫：凡是建置顶窗口的产品模块，必须**表态**。

    ⭐ 不许沉默 —— 将来有人新写一个覆盖层，这条会当场红，
    逼他回答「这层是画给游戏看的吗」。而那个答案**机器推不出来**：
    `crosshair_overlay` 和 `ui_toast` 在代码上长得一模一样。
    """
    silent = []
    for name, path in must_scan(sorted(_module_files().items()),
                                "候选的产品模块文件", least=20):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if TOP_HINT not in text:
            continue
        if _flag_of(path, MODULE_FLAG) is None:
            silent.append(path.relative_to(REPO).as_posix())
    assert not silent, (
        f"这些模块建了置顶窗口却没表态 `{MODULE_FLAG}`：\n  "
        + "\n  ".join(silent)
        + f"\n⭐ 加一行 `{MODULE_FLAG} = True/False`（True = 画在游戏画面上，"
          "玩家会在 CS2 里看它；False = 软件自己的 UI）。"
    )


#: 页面模块名 → 主窗里的 page_id。
_PAGE_IDS = {
    "crosshair_page": "crosshair",
    "kill_icon_page": "kill_icon",
    "screen_effects_page": "screen_effects",
    "advanced_page": "advanced",
    "fun_page": "fun_afterlife",
}


def test_every_page_that_draws_over_the_game_says_so_out_loud(main_window, qapp):
    """② 声明 True 的页面，**屏幕上**必须有那条前提。

    ⚠ 判的是「这一页说没说」，不是「用没用共用件」，也不是「有没有照我的措辞抄」
    —— `advanced` 与 `fun_afterlife` 用它们自己的话写的，照样算过。
    """
    missing, checked = [], []
    for path in _declared_pages(True):
        page_id = _PAGE_IDS.get(path.stem)
        assert page_id, (
            f"{path.name} 声明了 {PAGE_FLAG}，但本判据不知道它的 page_id —— "
            "补进 `_PAGE_IDS`，别让它静默躲开。"
        )
        main_window.ensure_page_loaded(page_id)
        main_window.show_page(page_id, animated=False, force=True)
        qapp.processEvents()
        page = main_window.pages.get(page_id)
        assert page is not None, f"{page_id} 没加载出来"
        text = _visible_text(page)
        checked.append(page_id)
        gaps = []
        if not any(w in text for w in SAY_WHAT_TO_DO):
            gaps.append("没说该把显示模式改成什么")
        if not any(w in text for w in SAY_WHAT_BREAKS):
            gaps.append("没说独占全屏下会怎样")
        if gaps:
            missing.append(f"{page_id}：{'；'.join(gaps)}")
    assert len(checked) >= 5, f"只量到 {checked} —— 分母塌了"
    assert not missing, (
        "这些页面配的东西画在游戏画面上，屏幕上却没说这条前提：\n  "
        + "\n  ".join(missing)
        + "\n⭐ 玩家配完进游戏什么都没有，他判定的是「这软件坏了」。"
    )


def test_a_page_that_can_reach_an_in_game_overlay_is_not_silent():
    """③ 交叉核对：能够到「画给游戏看」的覆盖层的页面，不许不表态。

    ⚠ 这条**抓不住 kill_icon**（页面与它的覆盖层之间没有 import 边），
    所以它不是分母，只是**一条从另一个方向来的交叉判据** ——
    它保证「有 import 关系摆在那儿」的页面至少被问过一次。
    ⭐ 两条互不覆盖的判据一起用，比一条自称完备的强。
    """
    mods = _module_files()
    in_game = {n for n, p in mods.items() if _flag_of(p, MODULE_FLAG) is True}
    if not in_game:
        pytest.skip("还没有任何模块声明自己画在游戏上 —— 判据 ① 会先红")

    def imports(path: Path) -> set[str]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return set()
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out |= {a.name.split(".")[-1] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    out.add(node.module.split(".")[-1])
                out |= {a.name.split(".")[-1] for a in node.names}
        return out & set(mods)

    silent = []
    for page in must_scan(_page_files(), "pages/ 下的页面文件", least=20):
        reach, frontier = set(), {page.stem}
        for _ in range(2):                      # 两跳
            nxt: set[str] = set()
            for m in frontier:
                nxt |= imports(mods[m]) - reach if m in mods else set()
            reach |= nxt
            frontier = nxt
        if reach & in_game and _flag_of(page, PAGE_FLAG) is None:
            silent.append(page.name)
    assert not silent, (
        f"这些页面两跳内就够得到一个画在游戏上的覆盖层，却没表态 `{PAGE_FLAG}`：\n  "
        + "\n  ".join(silent)
    )


def test_the_requirement_does_not_fade_with_the_master_switch(main_window, qapp):
    """⑤ 这条前提**与总开关无关**，所以它不许跟着总开关变淡。

    ⭐ 开关关着的时候玩家正在配 —— **那恰恰是最需要看到它的时刻**。
    批 16~20 建立的「关着 ⇒ 整页降权」如果把它一起卷进去，
    就等于「越需要越看不见」。

    ⚠ 量的是**像素**，不是属性。批 19 的教训：属性设上了、QSS 写对了，
    屏幕上照样可以一个像素都不变；反过来也一样 ——
    「我没给它设降权属性」证明不了「它没被降权」，
    因为祖先选择器够得着后代。
    """
    from widgets.overlay_requirement import overlay_requirement_label

    checked = []
    for path in _declared_pages(True):
        page_id = _PAGE_IDS[path.stem]
        main_window.ensure_page_loaded(page_id)
        main_window.show_page(page_id, animated=False, force=True)
        qapp.processEvents()
        page = main_window.pages.get(page_id)
        label = overlay_requirement_label(page)
        if label is None:          # advanced / fun 用自己的话写的，没有这个控件
            continue
        row = getattr(page, "master_switch_row", None)
        if row is None:
            continue
        row.set_checked_by_user(True)
        qapp.processEvents()
        on = label.grab().toImage()
        on_px = on.constBits().tobytes()
        row.set_checked_by_user(False)
        qapp.processEvents()
        off = label.grab().toImage()
        off_px = off.constBits().tobytes()
        checked.append(page_id)
        assert on_px == off_px, (
            f"{page_id}：总开关一关，这条运行前提就跟着变淡了 —— "
            "而玩家正是在开关还关着的时候读它。"
        )
    assert len(checked) >= 3, f"只量到 {checked} —— 分母塌了"


def test_the_declaration_has_not_quietly_emptied_itself():
    """④ 反空转：声明 True 的页面数不许塌。

    ⚠ ② 是一条「断言没有坏东西」的判据 —— **任何缩小分母的破坏都只会让它更绿**
    （批 21 刚拿一条假绿断点换来的教训）。所以分母要单独断言。

    ⭐ 而且必须点名两个**阳性对照**：`advanced` 与 `fun_afterlife` 早在
    本批之前就用自己的话写了这条前提。它们绿，证明 ② 认的是「说没说」，
    不是「有没有用我那个共用件」。
    """
    names = {p.stem for p in _declared_pages(True)}
    assert len(names) >= 5, (
        f"只有 {len(names)} 页声明自己画在游戏上（{sorted(names)}）—— "
        "实测应有 5 页：crosshair / kill_icon / screen_effects / advanced / fun。"
    )
    for control in ("advanced_page", "fun_page"):
        assert control in names, (
            f"阳性对照 {control} 不在声明清单里 —— "
            "少了它，判据 ② 就只能证明「我改过的页面被我改过了」。"
        )
