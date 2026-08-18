# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""离屏审计的「中和」策略 —— **全仓唯一一份**（RN-005 / RN-059）。

## 这是什么

`core/page_traits.DEVICE_OWNING_PAGES` 记的是**产品事实**（哪几页构造时会碰
外部资源）。本文件记的是**审计口径**：把那些副作用按页中和掉之后，
离屏脚本就能安全地把它们纳回覆盖面。两者刻意分开，因为一个是事实、一个是策略。

## RN-005：这张表曾经在 5 支脚本里各有一份，内容 1~3 项不等

    build_search_index      1 项（magnifier）
    page_fingerprint        1 项（magnifier）
    layout_overflow_audit   2 项（magnifier / kill_icon）
    ui_shot_capture         2 项（magnifier / kill_icon）
    tab_order_audit         3 项（music / magnifier / kill_icon），名字还叫 NEUTRALIZE

后果是量出来的（2026-08-17）：

    flash          被 5/5 支脚本跳过   ← 零覆盖
    viewmodel      被 5/5 支脚本跳过   ← 零覆盖
    voice_output   被 5/5 支脚本跳过   ← 零覆盖
    music          被 4/5 支跳过
    kill_icon      被 2/5 支跳过（没有指纹基线）
    magnifier      被 0/5 支跳过

**flash(1507 行) + viewmodel(823) + voice_output(1935) = 4265 行界面，
从来没有排版审计、没有指纹基线、没有截图、没有焦点巡检。**
而 `music` 的那条中和条件（挡默认曲目下载）明明已经在 `tab_order_audit` 里
验证过了，另外四支不知道 —— 同 RN-002 / RN-031 / RN-032 一模一样的病。

## 为什么这三页其实可以纳入（探针实测，不是推理）

在 `keyboard` / `mouse` / `socket` / `subprocess` / `Thread.start` 五个库边界上
架探针、全新隔离配置、`WA_DontShowOnScreen`，逐页切过去各静置 1.5 秒：

    页面           网络   子进程   热键库调用   注册中心新增绑定   可见窗口
    flash          0      0        0            0                  0
    viewmodel      0      0        0            0                  0
    voice_output   0      0        0            0                  0
    music          **1**  0        0            0                  0   ← MusicAddSong 线程
    magnifier      0      0        0            0                  0
    kill_icon      0      0        0            0                  0

热键之所以一条都没有：它们是按**用户配置里已有的绑定**注册的，隔离配置里空的。
唯一真实的副作用是 `music` 那次到发布服务器的下载（UP-087 早就诊断过）。

⚠ 但"这一次没注册"不等于"以后不会"。所以中和分**三层**，不靠运气：

  第一层（保证）：`CS2C_NO_GLOBAL_HOTKEYS=1` —— 见
      `core/hotkeys/registry.hotkeys_disabled()`。闸门一开，
      **无论配置里有什么**，注册中心只记账不挂钩。
  第二层（按页）：下面这张表把各页"会起线程/子进程/发网络"的那个开关按掉。
  第三层（保证，RN-072）：`block_modal_dialogs()` —— 模态框一律不许 `exec`。
      构造期弹框在离屏下不可见但**照样阻塞**，一页挂死就是整支脚本挂死。
      这一层同时是**发现通道**：`blocked_dialogs()` 会告诉你谁想弹框。

三层都要，缺一层就退回"靠隔离配置恰好是空的"。
"""
from __future__ import annotations

import os

#: 构造前要按页写进 config 的值。**每一条都要有"它挡住了什么"的注释。**
NEUTRALIZE: dict[str, dict[str, object]] = {
    # UP-101：构造时 `_setup_key_detection()` 注册全局热键，会劫持鼠标右键。
    # 关掉走 `disable_magnifier()` 分支，UI 照常完整构建。
    "magnifier": {"magnifier_enabled": False},
    # 总开关按 False，构造这一页不会创建任何叠加窗口。
    "kill_icon": {"kill_icon_enabled": False},
    # UP-087：隔离目录是新的 ⇒ `music_default_song_added` 为假 ⇒
    # `MusicPlayer.__init__` 当场去下载默认曲目「CS的LEMON」。
    # **这是唯一被探针实测到的真实网络副作用**：审计工具不该有网络副作用
    # （结果会依赖外网可达性，构造耗时也被绑在一次 HTTP 上）。置真即可，UI 照常。
    "music": {"music_default_song_added": True},
    # RN-059：`flash_enabled` 为真时 `_init_flash_process()` 会起闪光进程。
    # 隔离配置里它本来就是 False —— 显式按掉是为了**不依赖"恰好是默认值"**：
    # 万一哪天有人把审计指到一份真配置上，这里就是唯一的挡板。
    "flash": {"flash_enabled": False},
    # RN-059：`viewmodel_auto_switch_enabled` 为真时 `__init__` 末尾会
    # `_start_auto_switch()` 起线程（那个线程注册热键、按周期发按键）。
    "viewmodel": {"viewmodel_auto_switch_enabled": False},
    # RN-059：这一页在 `__init__` 里**无条件**调 `_start_global_hotkey_listener()`，
    # 没有任何配置开关能挡 —— 挡它的是上面第一层那道闸门（`CS2C_NO_GLOBAL_HOTKEYS`）。
    # 这里按掉 PTT，是为了连"按住说话"那条监听也一起免掉。
    "voice_output": {"voice_output_ptt_enabled": False},
}


def enable_audit_mode() -> None:
    """打开第一层：这个进程一律不注册真实全局热键。

    **必须在 import 产品模块之前调**（和 `_pristine_config` 同一时机）——
    注册中心读的是 `os.environ`，而页面可能在构造时就注册。
    """
    os.environ["CS2C_NO_GLOBAL_HOTKEYS"] = "1"
    # ⚠ 游戏目录那条出口**不在这里**，走 `scripts/_audit_sandbox.py`（UP-090）。
    # 我一度想在这儿加一个 `CS2C_NO_GAME_DIR_WRITES` 禁写闸门，是错的：
    # 那会让 `csgo_dir` 留空 ⇒ 页面走「未配置 CS2 目录」分支 ⇒ 文案和布局都变，
    # 等于把被审计对象改掉了。`_audit_sandbox` 刻意选的是**重定向**而不是禁写，
    # 理由就写在它的注释里。⇒ 那条出口只有一份实现，别在这里造第二份。


#: RN-072：审计期间被挡下来的模态框。**这是个发现通道，不是消音器。**
_BLOCKED: list[str] = []
#: 被 `block_modal_dialogs()` 换掉的原函数，供 `unblock_modal_dialogs()` 还原。
_ORIGINALS: dict = {}


def blocked_dialogs() -> list[str]:
    """审计期间有哪些模态框想弹出来。构造期弹框本身就是缺陷，判据要能读到它。"""
    return list(_BLOCKED)


def block_modal_dialogs() -> None:
    """第三层：模态框一律不许 `exec`，改成记账 + 返回一个安全默认值。

    ⭐ 为什么必须有这一层：`AdvancedPage.__init__` 在**构造期**弹
    `QMessageBox.information`（RN-072）。离屏下这个框不可见但**照样阻塞**，
    于是**任何**构造这一页的离屏脚本都永久挂死 —— 建页耗时基线因此从来没跑完过
    整表，而它只在 `config.csgo_dir` 为空时触发，**隔离配置永远是空的**，
    所以这条在工装里必然踩、在真机上几乎不踩。

    ⚠ 这一层刻意**不放进** `enable_audit_mode()`：那个必须保持零 Qt 依赖
    （`bench_page_build` 要在 import 产品页面之前调它，不能把 Qt 提前捂热）。
    本函数要在 `QApplication` 建好之后调。

    ⚠ 默认值一律选**最保守**的那个：问答框返回"否"、文件框返回空。
    "点了确定"绝不能由工装替用户按。
    """
    from PySide6.QtWidgets import (
        QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox,
    )

    def _note(what: str, ret):
        _BLOCKED.append(what)
        return ret

    # 可逆：判据要在同一个进程里"关掉闸门再量一次"（空转守卫），
    # 而这一层动的是**类属性**，不还原会漏进同一轮的其它用例里。
    for owner, name in ((QMessageBox, "information"), (QMessageBox, "warning"),
                        (QMessageBox, "critical"), (QMessageBox, "about"),
                        (QMessageBox, "aboutQt"), (QMessageBox, "question"),
                        (QDialog, "exec"), (QMenu, "exec"),
                        (QFileDialog, "getOpenFileName"), (QFileDialog, "getOpenFileNames"),
                        (QFileDialog, "getSaveFileName"), (QFileDialog, "getExistingDirectory"),
                        (QInputDialog, "getText"), (QInputDialog, "getInt"),
                        (QInputDialog, "getItem"), (QInputDialog, "getDouble")):
        _ORIGINALS.setdefault((owner, name), owner.__dict__.get(name, getattr(owner, name)))

    sb = QMessageBox.StandardButton
    for name, ret in (("information", sb.Ok), ("warning", sb.Ok), ("critical", sb.Ok),
                      ("about", None), ("aboutQt", None), ("question", sb.No)):
        setattr(QMessageBox, name,
                staticmethod(lambda *a, _n=name, _r=ret, **kw: _note(f"QMessageBox.{_n}", _r)))

    QDialog.exec = lambda self, *a, **kw: _note(
        f"{type(self).__name__}.exec", QDialog.DialogCode.Rejected)
    QMenu.exec = lambda self, *a, **kw: _note(f"{type(self).__name__}(QMenu).exec", None)
    for name, ret in (("getOpenFileName", ("", "")), ("getOpenFileNames", ([], "")),
                      ("getSaveFileName", ("", "")), ("getExistingDirectory", "")):
        setattr(QFileDialog, name,
                staticmethod(lambda *a, _n=name, _r=ret, **kw: _note(f"QFileDialog.{_n}", _r)))
    for name, ret in (("getText", ("", False)), ("getInt", (0, False)),
                      ("getItem", ("", False)), ("getDouble", (0.0, False))):
        setattr(QInputDialog, name,
                staticmethod(lambda *a, _n=name, _r=ret, **kw: _note(f"QInputDialog.{_n}", _r)))


def unblock_modal_dialogs() -> None:
    """把模态框还原成真的。只给判据用（"关掉闸门再量一次"那种空转守卫）。"""
    for (owner, name), original in _ORIGINALS.items():
        setattr(owner, name, original)
    _ORIGINALS.clear()


def apply(config, page_ids=None) -> list[str]:
    """打开第二层：把表里的开关写进 config。返回被中和的页 id（供覆盖面报告用）。

    `page_ids` 给定时只中和其中出现的页；不给就全表都写
    （多写几个开关无害 —— 那些页本来也要么被拍、要么不存在）。
    """
    touched = []
    for page_id, overrides in NEUTRALIZE.items():
        if page_ids is not None and page_id not in page_ids:
            continue
        for attr, value in overrides.items():
            setattr(config, attr, value)
        touched.append(page_id)
    return sorted(touched)


def describe(page_ids=None) -> str:
    """人能读的一行，给覆盖面报告用（UP-096：覆盖面每次都要报）。"""
    items = []
    for page_id in sorted(NEUTRALIZE):
        if page_ids is not None and page_id not in page_ids:
            continue
        pairs = ", ".join(f"{k}={v}" for k, v in NEUTRALIZE[page_id].items())
        items.append(f"{page_id}（{pairs}）")
    return "; ".join(items)


def unsafe_pages() -> frozenset:
    """中和之后**仍然**不能构造的页。

    RN-059 之后这个集合是**空的** —— 六页全部可纳入。
    留着这个函数是因为"以后可能又出现一个真的中和不了的页"，
    而且脚本侧的报告逻辑要有个统一出口；**不是**为了兼容旧写法。
    """
    from core.page_traits import DEVICE_OWNING_PAGES

    return frozenset(DEVICE_OWNING_PAGES) - set(NEUTRALIZE)
