# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-621 的复现探针：闪光样式参数改完，**重启之后回到默认值**。

## 链路（全部走产品代码，不抄）

  ① 照 `pages/flash_page._on_param_changed` 往
     `config.flash_style_params[当前样式][参数名]` 写一次 —— 这一段是**页面的写法**，
     探针里照抄是对的：它模拟的是用户的动作，不是被测的那一侧。
  ② `save_config_now()` 落盘，再新建一个 `Config` + `load_config()`（＝下次启动）。
  ③ **真的构造一个 `FlashProcessManager`**（不起进程，构造函数只读配置），
     看它的 `style_parameters` 里那个参数是几。

⛔⛔ 第一版不是这么写的：我在探针里**抄了一份**读逻辑
（`style_parameters = cfg.flash_style_params` 再扁平取键）。
⭐⭐⭐ 那样写的探针，**修好之后照样报「复现」** —— 它量的是我抄的那份副本，
不是产品。这正是 RN-616 那条教训的翻版（判据把真实现 monkeypatch 掉、
在夹具里抄了一份被测逻辑），而我在同一条链路上又犯了一次。
⇒ **被测的那一侧必须由产品自己执行。**

用法：`python scripts/x4_flash_params_repro.py`
返回 0 = 复现了缺陷；1 = 没复现（＝已修好）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# 隔离：⛔ **不许自己写 `CS2C_CONFIG_DIR`**（RN-031/032，判据
# `test_pristine_config_for_tooling` 当场逮住过本脚本的第一版）——
# 自己写的那种「空目录」会被 `migrate_old_config()` 灌进**开发机上那份个人配置**。
from _pristine_config import use_pristine_config_dir  # noqa: E402

use_pristine_config_dir("cs2customizer_x4_flash_repro", force=True)

import config as config_mod  # noqa: E402
from flash_process_manager import FlashProcessManager  # noqa: E402

#: ⚠ 落盘走的是 `get_config_path()`（读 `CS2C_CONFIG_DIR`），**不是** `self.config_file`
#: —— 第一版拿后者去读文件，得到一个 `FileNotFoundError`。
CFG_PATH = config_mod.get_config_path()

USER_VALUE = 0.77
PARAM = "blur_factor"


def main() -> int:
    cfg = config_mod.Config()
    cfg.config_file = str(CFG_PATH)
    style = cfg.flash_style
    default = cfg.flash_style_params.get(PARAM)
    print(f"当前闪光样式：{style!r}；默认 {PARAM} = {default}")

    # ① 用户在闪光页拖了一次滑块（照 pages/flash_page.py:1268~1277）
    if style not in cfg.flash_style_params:
        cfg.flash_style_params[style] = {}
    cfg.flash_style_params[style][PARAM] = USER_VALUE
    cfg.save_config_now()
    print(f"① 用户把 {PARAM} 拖到 {USER_VALUE}，已落盘")

    on_disk = json.loads(io.open(cfg.config_file, encoding="utf-8").read())
    print(f"   盘上的键：{list(on_disk['flash_style_params'])}")

    # ② 下次启动
    cfg2 = config_mod.Config()
    cfg2.config_file = str(CFG_PATH)
    cfg2.load_config()
    print(f"② 重启后，用户的那一份还在盘上："
          f"{cfg2.flash_style_params.get(style)}")

    # ③ 真的让产品去读（构造函数里就会 load_settings_from_config）
    manager = FlashProcessManager(cfg2)
    got = manager.style_parameters.get(PARAM)
    print(f"③ `FlashProcessManager.style_parameters[{PARAM!r}]` = {got!r}")

    if got == USER_VALUE:
        print(f"\n✅ 没有复现：用户设的 {USER_VALUE} 活过了重启。")
        return 1
    print(f"\n⛔ **复现**：用户设的是 {USER_VALUE}，重启后产品拿到的是 {got!r}。")
    print("   写的一方按「样式名 → 参数表」两层存，读的一方按「参数名 → 值」一层读；")
    print("   ⭐ 而默认值恰好是一层的 ⇒ 全新安装一切正常，只有改过参数的用户才坏。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
