# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-195：量图工装里「音乐控制条在不在」必须是**定下来的**，不是碰运气的。

## 事故形态（2026-08-23 本机实测，不是推想）

主窗里这条栏由 `QTimer.singleShot(8000, ...)` 建出来，而**量图是在同一个
事件循环里连着跑的**。跑一轮 28 页指纹，定时器在 **8.00s** 开火：

    7.79s  bar=无  config_snapshot
    8.00s  bar=有  preset_center      <-- 世界在这里换了
    8.11s  bar=有  about

⇒ 前 26 页量的是可视区 750 的世界，最后 2 页量的是 708 的世界，**同一份产物
里两种坐标系混着**。而分界线离边界只有 0.11 秒 —— 换台机器、页数多两个少
两个，分界就挪到别处。

⭐ 这不是"偶尔会错"，是**结论取决于机器多快，不取决于代码**。

## 两类工装的正确口径**不一样**（这是本文件存在的理由）

它们问的不是同一个问题：

  · **审计**（`layout_overflow_audit.py`）问「用户会不会看到溢出」
    ⇒ 要**最坏的那一档**：控制条**在**。
    放过一次音乐的用户永远停在这一档 —— RN-195 只做「不建」，**不做「撤走」**。

  · **基线**（`page_fingerprint.py` / `ui_shot_capture.py`）问
    「这一页跟我锁基线的时候比，变了没有」
    ⇒ 要**可复现的那一档**：全新配置下产品自己的决定。
    RN-195 之后那就是**不建**（`music_current_index == -1`）。

⭐⭐ 以前两者都靠同一个 8 秒定时器碰运气，碰巧审计碰对了、基线碰错了。
**同一个不确定性，喂给两个问题，只会有一个碰巧对。**

## 怎么用

    import _audit_music_bar as _mbar
    print(_mbar.pin(win, app, _mbar.MODE_WORST_CASE))   # 或 MODE_PRISTINE
    ...  # 逐页量
    _mbar.assert_stable(win)                            # 跑完回验

`pin()` 只是「我打算量哪一档」，`assert_stable()` 才是「这一轮真的全程都在
那一档」。⚠ 少了回验，一条在途中冒出来的控制条照样能混过去 —— 那正是上面
那份实测里发生的事。
"""
from __future__ import annotations

MODE_WORST_CASE = "on"        # 强制建出来（折叠态）：阻断级审计跑这一档
MODE_PRISTINE = "auto"        # 不干预：全新配置下产品自己的决定（= 不建）
MODE_EXPANDED = "expanded"    # 建出来**并展开**：RN-571，见下面那段裁定

_ATTR_MODE = "_audit_music_bar_mode"
_ATTR_EXPECTED = "_audit_music_bar_expected"


def _present(win) -> bool:
    return getattr(win, "music_control_bar", None) is not None


def _config():
    """拿产品的 config 单例。拿不到就静默跳过 —— 这条工装不该把审计带崩。"""
    try:
        from config import config
        return config
    except Exception:
        return None


def _set_expanded(win, app, want: bool) -> None:
    """把控制条**推到**展开或折叠（RN-571）。

    ⚠ 不能只写 `config.music_bar_expanded = …` 就完事：控件在 `__init__`
    里已经读过一次那个值，只有**后建**的才跟着走。所以两头都要做 ——
    先改配置（给「后建」的那条路），再直接推控件（给「已经建好」的那条路）。

    ⭐ 两个方向都要推。只推「展开」的话，一个先前被展开过的控制条
    在阻断档上会**原样留着**，而阻断档要的是折叠 —— 那就是「钉了个寂寞」。
    """
    bar = getattr(win, "music_control_bar", None)
    if bar is None or bool(getattr(bar, "is_expanded", False)) == want:
        return
    toggle = getattr(bar, "_apply_bar_mode", None)
    if callable(toggle):
        bar.is_expanded = want
        toggle(want)
        sync = getattr(bar, "_sync_bar_heights", None)
        if callable(sync):
            sync()
        app.processEvents()
        app.processEvents()


def pin(win, app, mode: str) -> str:
    """钉住这一轮的档位，返回一句给报告打印的话。"""
    if mode not in (MODE_WORST_CASE, MODE_PRISTINE, MODE_EXPANDED):
        raise ValueError(f"未知的音乐控制条档位: {mode!r}")

    # ⚠⚠⚠ RN-571（2026-09-08 批 71）：**「最坏」有两个自由度，这里以前只钉了一个。**
    #
    # ① 控制条在不在 —— 原来只钉了这个；
    # ② 它是**展开**还是**折叠** —— `MusicControlBar.is_expanded` 读
    #    `config.music_bar_expanded`（默认 **False** ⇒ 42px 折叠；展开 112~128px）。
    #    两档差 **86px 可视区**，而报告行一直笼统地说「最坏那一档」。
    # ⭐⭐⭐ **一条规矩被写下来、还配了工装，而工装只实现了那条规矩的一半 ——
    #   报告行照样宣称它实现了全部。**⇒ 报告行现在**逐字说明钉的是哪一档**。
    #
    # ⚖ **裁定（批 71）：阻断级审计仍跑「在 + 折叠」，展开档改成显式可选。**
    #   两个状态性质不同：控制条建出来是**不可逆**的（RN-195：只做「不建」不做
    #   「撤走」，放过一次音乐就永远在），而展开是**一键可收回**的。
    #   把一个可逆状态当强制基线，代价是实测出来的这个数 ——
    #   **紧凑档 40 处、完整档 4 处**纵向缺口要立刻进棘轮表当豁免。
    #   ⭐ 把数写下来，这才算裁定而不是绕开：那 44 处是**真的**，
    #     只是它们归 RN-571 单独排期，不在本批塞进一张 44 行的豁免表。
    if mode in (MODE_WORST_CASE, MODE_EXPANDED):
        create = getattr(win, "_create_music_control_bar", None)
        if callable(create):
            create()
            app.processEvents()
            app.processEvents()
    # ⚠⚠ **钉一个档 = 把它推到那个状态，不是「碰巧它就是那样」。**
    # 第一版我只给展开档加了推手，阻断档仍旧「建出来就算数」——
    # 判据当场逮到：同一进程里先跑过展开档，再 `pin(MODE_WORST_CASE)`
    # 报的是**展开、127px**。⭐⭐⭐ 这正是本条缺陷本身的形状：
    # **声称钉住一个档，实际只做了一半** —— 我在修它的那一版里又犯了一次。
    # ⇒ 这也解释了先前那个谜：同一条命令一次报 42px 一次报 128px，
    #   **门的严格度一直随残留配置漂**，而报告行两次长得一样。
    if mode in (MODE_WORST_CASE, MODE_EXPANDED):
        want = (mode == MODE_EXPANDED)
        config = _config()
        if config is not None:
            config.music_bar_expanded = want
        _set_expanded(win, app, want)

    setattr(win, _ATTR_MODE, mode)
    setattr(win, _ATTR_EXPECTED, _present(win))

    bar = getattr(win, "music_control_bar", None)
    height = bar.height() if bar is not None else 0
    # ⭐ RN-571：**把钉的是哪一档逐字说出来。** 以前只说「最坏那一档」，
    #   而同一句话下面既可能是 42px 也可能是 128px —— 读的人无从分辨。
    shape = "展开" if getattr(bar, "is_expanded", False) else "折叠"
    if mode == MODE_EXPANDED:
        return (f"音乐控制条：**建出来并展开**（{shape}，占 {height}px）—— "
                f"这一档量的是「用户把它展开之后」的世界（RN-571，非阻断档）")
    if mode == MODE_WORST_CASE:
        return (f"音乐控制条：**强制建出来**（{shape}，占 {height}px）—— "
                f"阻断档量的是「控制条在」这个**不可逆**的状态"
                f"（放过一次音乐就永远是这一档）；"
                f"「展开」是可逆的，归 `MODE_EXPANDED`（RN-571）")
    return ("音乐控制条：**按全新配置的样子**（没放过音乐 ⇒ 不建，RN-195）—— "
            "基线要的是可复现，不是最坏")


def assert_stable(win) -> None:
    """跑完一轮再验一次：控制条的有/无**不许在途中变过**。

    ⚠ 这条不是形式主义。8 秒定时器现在仍然存在（只是变成了条件触发），
    而"这台机器上恰好有播放记录"就足以让它在量到一半时开火。
    那种产物读起来完全正常 —— 页与页之间差的那 42px 会被当成页面本身的差异。
    """
    expected = getattr(win, _ATTR_EXPECTED, None)
    if expected is None:
        raise AssertionError(
            "这一轮没有调用过 `pin()` —— 控制条的档位没人钉，等于交给 8 秒定时器决定")
    actual = _present(win)
    if actual != expected:
        mode = getattr(win, _ATTR_MODE, "?")
        raise AssertionError(
            f"音乐控制条在这一轮中途变了（档位 {mode}：开始 "
            f"{'有' if expected else '无'} → 结束 {'有' if actual else '无'}）。"
            f"这一批产物里前后两段量的不是同一个可视区，**不可用**。"
            f"多半是这台机器上有播放记录，8 秒定时器在量到一半时开火了 —— "
            f"用全新配置目录重跑（`_pristine_config.use_pristine_config_dir`）。")
