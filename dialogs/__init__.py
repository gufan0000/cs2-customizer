# SPDX-License-Identifier: GPL-3.0-or-later
"""对话框模块 - 包含各种功能对话框

⚠ **这里不 import 任何子模块，一个都不要加。** 全部按模块路径导：
`from dialogs.add_url_dialog import AddURLDialog`。

两条理由：

1. **启动路径连坐**。`dialogs` 这个包在很多地方只为拿其中一个对话框就被 import，
   而在这里 eager import 会把被导那个模块的整条依赖链挂到所有调用点上——
   `kill_icon_workshop` 就会顺带拉起 `widgets/kill_icon_level_grid` →
   `KillIconPreview` → `kill_icon_overlay`。`tests/test_lazy_imports_r8a.py`
   盯的就是这类连坐。
2. **开源版少几个对话框**。`add_url_dialog` 属于音乐功能，开源版不含它。
   包级 eager import 会让开源版一 `import dialogs` 就 ImportError，
   于是同步管道不得不为这个文件长期挂一个语义补丁。空 `__init__` 让
   "少带一个文件"自然成立，那个补丁就删掉了——补丁集本该随时间趋近于零。
"""
