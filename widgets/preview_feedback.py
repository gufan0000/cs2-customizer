# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""试听失败的统一反馈（UP-037）。

原状：点「试听」没声音时，大多数失败分支只写一行日志就 `return`。
用户看到的是"点了没反应"——分不清是**没配音效**、**文件丢了**、
还是**软件坏了**，只能反复点。

分支实测（`pages/kill_sound_page.py::_test_weapon_sound`，4 个失败出口）：
只有"连杀档位文件缺失"这一个会写 action bar，其余 3 个全静默。

这里把反馈收成一处：**toast（抓注意力）+ action bar（留在原地可复读）**。
两条都给是有意的——toast 会自己消失，用户回头想再看一眼就没了；
action bar 的文案会一直留到下一次操作。
"""
from __future__ import annotations

__all__ = ["PreviewFailure", "report_preview_failure"]


class PreviewFailure:
    """失败原因。文案在这里集中管理，免得七个音效页各写各的。"""

    NO_STYLE = "no_style"          # 这一项没启用/没选风格
    NO_FILE = "no_file"            # 配了风格但音频文件不在
    DECODE = "decode"              # 文件在但解码失败
    DEVICE = "device"              # 音频设备被占用/未就绪
    UNKNOWN = "unknown"

    _TEXT = {
        NO_STYLE: "这一项还没有启用音效，先在左侧选一个风格再试听。",
        NO_FILE: "选中的风格里找不到音频文件，可能被移动或删除了。",
        DECODE: "音频文件无法解码，可能已损坏或格式不支持。",
        DEVICE: "音频设备不可用（可能被其他程序独占），检查系统声音设置后重试。",
        UNKNOWN: "试听未能播放。",
    }

    @classmethod
    def text(cls, reason: str) -> str:
        return cls._TEXT.get(reason, cls._TEXT[cls.UNKNOWN])


def report_preview_failure(page, reason: str, detail: str = "", *, toast: bool = True) -> str:
    """给出用户可见的失败反馈，返回最终展示的文案。

    Args:
        page: 页面对象（有 `action_bar` 就写它，没有也不报错）
        reason: `PreviewFailure` 里的常量
        detail: 补充信息，如具体文件名/风格名
        toast: 是否同时弹 toast。批量试听场景可以关掉，免得刷屏。

    任何异常都吞掉：**反馈失败绝不能反过来影响功能**。
    """
    message = PreviewFailure.text(reason)
    if detail:
        message = f"{message}（{detail}）"

    # 注意：`getattr(obj, name, default)` 的 default **不会**吞掉 property
    # getter 内部抛出的异常，只挡 AttributeError。取属性这一步本身也要包起来，
    # 否则"反馈失败不影响功能"这句承诺就是假的。
    try:
        bar = getattr(page, "action_bar", None)
        if bar is not None and hasattr(bar, "set_message"):
            bar.set_message(message)
    except Exception:
        pass

    if toast:
        try:
            from ui_toast import toast_warning

            toast_warning(message, 3600)
        except Exception:
            pass

    try:
        logger = getattr(page, "logger", None)
        if logger is not None:
            logger.info(f"[试听未播放] {reason}: {message}")
    except Exception:
        pass
    return message
