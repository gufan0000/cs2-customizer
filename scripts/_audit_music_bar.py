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

MODE_WORST_CASE = "on"        # 强制建出来：审计要量用户可能遇到的最坏那一档
MODE_PRISTINE = "auto"        # 不干预：全新配置下产品自己的决定（= 不建）

_ATTR_MODE = "_audit_music_bar_mode"
_ATTR_EXPECTED = "_audit_music_bar_expected"


def _present(win) -> bool:
    return getattr(win, "music_control_bar", None) is not None


def pin(win, app, mode: str) -> str:
    """钉住这一轮的档位，返回一句给报告打印的话。"""
    if mode not in (MODE_WORST_CASE, MODE_PRISTINE):
        raise ValueError(f"未知的音乐控制条档位: {mode!r}")

    if mode == MODE_WORST_CASE:
        create = getattr(win, "_create_music_control_bar", None)
        if callable(create):
            create()
            app.processEvents()
            app.processEvents()

    setattr(win, _ATTR_MODE, mode)
    setattr(win, _ATTR_EXPECTED, _present(win))

    bar = getattr(win, "music_control_bar", None)
    height = bar.height() if bar is not None else 0
    if mode == MODE_WORST_CASE:
        return (f"音乐控制条：**强制建出来**（占 {height}px）—— 审计量的是"
                f"用户可能遇到的最坏那一档（放过一次音乐就永远是这一档）")
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
