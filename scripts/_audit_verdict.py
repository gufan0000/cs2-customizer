# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""门禁脚本的**裁定交付通道**：把判定结果从退出码里搬出来。

**为什么需要它**（RN-068 → RN-092）：

Qt/keyboard/音频这些库在解释器退出期还会跑析构，退出码在那一段路上**两个方向都被洗过**：

- 洗成 **1**：`tab_order_audit` 在 CI 上打印「通过 / RESULT rc=0」，
  0.66 秒后进程 exit code 1，无 traceback（2026-08-17 `41217bf` 实录）。⇒ **假红**。
- 洗成 **0**：发布门禁脚本的非零退出码被产品退出链路吞掉（QA 台账在册）。⇒ **假绿**，更致命。

⇒ **裁定不该经过那段路。** 审计自己算完就打一行机器可读的裁定，
CI 读那一行、不读退出码。退出码保留为**辅助信号**（不一致时发警告，不做裁定）。

用法：

    from _audit_verdict import deliver
    if __name__ == "__main__":
        deliver("focus", main())

CI 侧的对应读法见 `.github/workflows/ci.yml`；判据见
`tests/test_ci_gates_read_the_verdict_line.py`。
"""
from __future__ import annotations

import os
import sys
import threading
import traceback

#: 裁定行的格式。**改这里就要同步改 CI 和判据**（判据会自己红给你看）。
VERDICT_PREFIX = "RESULT"


def make_teardown_noise_visible() -> None:
    """退出期的异常照样打出来 —— `deliver()` 里的 `os._exit` 不是为了掩盖它。

    `sys.unraisablehook` 收的是 `__del__` / 弱引用回调这类"没法抛给谁"的异常，
    它们默认只打一行 `Exception ignored in:`，在 CI 长日志里极易被忽略。
    """

    def _unraisable(unraisable):
        print("!! [退出期·unraisable]", unraisable.exc_type.__name__,
              unraisable.exc_value, flush=True)
        traceback.print_tb(unraisable.exc_traceback)

    def _thread_hook(args):
        print("!! [退出期·线程]", args.exc_type.__name__, args.exc_value, flush=True)

    sys.unraisablehook = _unraisable
    threading.excepthook = _thread_hook


def deliver(name: str, rc: int) -> None:
    """打出裁定行并立刻退出，不给退出链路改写的机会。

    `name` 是审计名（`focus` / `layout` / `contrast` …），
    让一条流水线里几道门的裁定行彼此可分辨。
    """
    rc = int(rc)
    print(f"{VERDICT_PREFIX} {name} rc={rc}", flush=True)
    if name == "focus":
        # ⚠ 兼容：`tests/test_audit_can_see_every_page.py` 与既有档案里都写着
        # `RESULT rc=<n>` 这个旧格式。多打一行比改判据安全。
        print(f"{VERDICT_PREFIX} rc={rc}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
