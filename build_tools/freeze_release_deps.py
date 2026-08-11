# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""锁定发版依赖(2026-06-13)。

为什么:requirements_qt.txt / requirements-ci.txt 用 `>=` 只锁下限——能自动拿
安全补丁,但打包时实际装的版本取决于构建机当时的环境,**不可复现**;PySide6 /
numpy 等出大版本可能悄悄破包或改行为。本脚本把当前环境冻成精确版本底片。

用法(在构建机上、正式打包发布前跑一次):
    python build_tools/freeze_release_deps.py

产出:仓库根 requirements.lock.txt = 当前环境 `pip freeze` 精确快照(可 git 入库,
作该次发布的依赖溯源)。日常开发 / CI 仍用 requirements*.txt 的 `>=`,
只有发版打包以本锁定文件为准(pip install -r requirements.lock.txt)。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock.txt"


def main() -> int:
    try:
        frozen = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"],
            text=True,
            encoding="utf-8",
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"pip freeze 失败: {exc}")
        return 1

    header = (
        "# CS2 Customizer · 发版依赖锁定文件(自动生成,请勿手改)\n"
        f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Python:   {sys.version.split()[0]}  ({sys.executable})\n"
        f"# 平台:     {sys.platform}\n"
        "# 用途:发版打包以此锁定版本为准;日常/CI 仍用 requirements*.txt(>=)。\n"
        "# 重新生成: python build_tools/freeze_release_deps.py\n"
        "# 按锁定安装: pip install -r requirements.lock.txt\n\n"
    )
    LOCK.write_text(header + frozen, encoding="utf-8")
    pkgs = [ln for ln in frozen.splitlines() if ln.strip() and not ln.startswith("#")]
    print(f"已写出 {LOCK}（{len(pkgs)} 个包）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
