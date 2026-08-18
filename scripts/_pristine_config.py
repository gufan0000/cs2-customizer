# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""工装用的「全新用户配置目录」——**唯一真相源**（RN-032）。

## 为什么要有这个文件

审计/基线/截图/耗时/索引这一类工装，量的都是"软件在某个确定状态下长什么样"。
那个"确定状态"必须是**全新用户的默认设置**，否则量出来的东西只对开发机成立。

原先六个脚本各写一份下面这三行：

    _tmp = Path(tempfile.gettempdir()) / "cs2customizer_xxx"
    (_tmp / "config").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))

**六份都是错的，而且错得一模一样。** `config.migrate_old_config()` 在**源码运行**时
会把仓库根那份 `config.json` 复制进目标目录（那是给"老版本就地升级"用的迁移路径），
而那个文件**没有被 git 跟踪**——它只存在于开发机上。于是所谓"空目录"里
装的其实是**开发者的个人配置**（实测 357 个键、37 把武器配着风格）。

RN-031 只修了 `renovation_baseline.py` 那一处，剩下五处继续带病：
实测 `cs2customizer_ui_shots` / `cs2customizer_layout_audit` / `cs2customizer_bench` /
`cs2customizer_search_index` / `cs2customizer_renovation_baseline` 里
`death_sound_style` 全都是个人配置里的 `"2"`（全新用户应为 `"0"`）。
⇒ **像素基线、排版审计、耗时基线、搜索索引全是在个人配置上产出的**，
而"全新用户的空状态"从来没被任何一条判据看过。

⭐ 这是 RN-002（同一份名单硬抄多份）与 RN-031（迁移泄漏）叠在一起的产物：
**只要还有第二份副本，修好一份就等于没修。**

## 挡住迁移的办法

迁移只在"目标不存在"时发生，所以先落一个空的 `{}` 占位配置。
这也正是**真实全新用户**的状态：装的是冻结包，`migrate_old_config` 直接早退。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

#: 占位配置的内容。空对象即可 —— 产品侧所有默认值都在 `config.py` 里，
#: 这里只是让"目标已存在"成立，把迁移挡在门外。
PLACEHOLDER = "{}"


def use_pristine_config_dir(name: str, *, force: bool = False) -> Path:
    """把本进程的配置/日志目录钉在一个**可复现的全新用户目录**上，返回该目录。

    `name` 是 `%TEMP%` 下的目录名（各工装沿用原来的名字，便于排查）。

    ⚠ **默认：已经有人设过 `CS2C_CONFIG_DIR` 就不接管。**
    pytest 的 `conftest.py` 会先把配置目录指到 `cs2customizer_test_config`，
    而好几支测试是 **in-process** 导入这些脚本的（`test_correctness_r8a` 用
    `spec_from_file_location` 载 `layout_overflow_audit`、
    `test_search_index_*` 直接 `import build_search_index`）。
    那种场合下抢占环境变量会把测试自己的配置目录掀掉。
    所以默认保留原来 `setdefault` 的语义：**外面定了就听外面的。**

    ⚠⚠ `force=True` 用于**专门为"取全新基线"而起的子进程**
    （`renovation_baseline.structure_of`）。那种进程必须无条件钉死 ——
    它是被 pytest 起的，会继承 conftest 那个**跨文件跨轮次累积**的配置目录，
    不 force 就等于把 RN-031 的修法整个作废，而且失效时毫无声响。
    """
    tmp = Path(tempfile.gettempdir()) / name
    if os.environ.get("CS2C_CONFIG_DIR") and not force:
        return tmp

    # 每次重建：复用目录等于让状态跨轮次累积，那正是 `cs2customizer_test_config`
    # 当年造出 10 处假红的原因（见 renovation_baseline.structure_of 的注释）。
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "logs").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "config.json").write_text(PLACEHOLDER, encoding="utf-8")

    os.environ["CS2C_CONFIG_DIR"] = str(tmp / "config")
    if force:
        os.environ["CS2C_LOG_DIR"] = str(tmp / "logs")
    else:
        os.environ.setdefault("CS2C_LOG_DIR", str(tmp / "logs"))
    return tmp
