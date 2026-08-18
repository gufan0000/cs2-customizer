# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面的固有属性——**不依赖 Qt，可被任何脚本零成本导入**。

这里只放"关于页面的事实"，不放策略。目前只有一条：哪几页构造即占外部资源。

**为什么单独成模块**：这条事实同时约束产品与一整排离屏脚本，
而脚本里有 `bench_page_build` 这种**测量建页耗时**的——让它为了读一个常量
去 `import gui_widget`，会连带预热 Qt 与 `pages.audio_status_badge`，
**把它自己要测的东西提前捂热**，基准数从此不可比。
所以常量必须待在一个导入代价约等于零的地方。
"""
from __future__ import annotations

#: **构造即占用外部资源的页面** —— 这几页在 `__init__` 里就会注册全局热键、
#: 起线程/子进程或打开音频设备，因此谁都不能"顺手构造一下"它们。
#:
#: 约束到的地方：
#:   · 产品：启动阶段的静默预载要跳过（`gui_widget.MainWindow._preload_skip_pages`）；
#:   · 判据与审计脚本：离屏跑时构造它们会真的占设备、劫持用户的鼠标右键，
#:     那就是"打扰前台"（`layout_overflow_audit` / `ui_shot_capture` /
#:     `bench_page_build`、以及侧栏类判据都据此跳过）。
#:
#: ⚠ **别在别处另抄一份。** 抄出来的副本不会跟着这里变 —— 2026-08-16 的 CI
#: 连红就是这么来的：判据把设备页全构造了一遍，runner 上 `music` 那项断言失败，
#: 本机拿探针复现时**直接卡死在音乐页**。
#: 判据 `tests/test_no_hardcoded_page_lists.py` 会拦住新抄的副本。
#:
#: 注：审计脚本另有一层「中和」策略（把总开关在隔离配置里按成 False，从而安全地
#: 把 magnifier/kill_icon 纳回覆盖面）。那是**审计口径、不是产品事实**，留在脚本侧。
DEVICE_OWNING_PAGES = frozenset({
    "viewmodel",
    "magnifier",
    "flash",
    "voice_output",
    "kill_icon",
    "music",
})
