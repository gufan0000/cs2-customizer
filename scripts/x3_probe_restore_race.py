# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-617 复现探针：快照恢复 与 防抖保存 之间有没有共享锁？

## 立案说的是什么

`config_snapshot_manager.restore_snapshot` 直接改写 `config.json`，再调
`config.load_config()`；而 `load_config` **全程不持有 `Config._save_lock`**
（那把锁只在 `save_config` / `save_config_now` / `_do_save_config` 里）。
⇒ 用户点「恢复」前 500ms 内改过别的设置时，那个还没到点的防抖 timer 会
在另一线程里边读 `self` 上的属性边拼 payload，而此刻 `load_config` 正在
逐个覆写它们 ⇒ 拼出一份**新旧混杂**的配置盖掉刚恢复好的文件。

## ⛔ 为什么要有这个脚本

立案那一行逐字写着「**未实测复现**」。按红线 2，**结它之前必须先造出一次失败** ——
⭐ 一条只靠读代码推出来的竞态，和一条真的会发生的竞态，在代码上长得一模一样，
而**只有复现分得开它们**。造不出来就改判「不成立」，并把这个探针留在原地当阳性对照。
（同 RN-553 那次：按「沙箱里躺着陈年 cfg」造敌对状态复现不了，
换成**持续写入的进程**才当场复现。）

用法：`python scripts/x3_probe_restore_race.py [--rounds 200]`
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from _pristine_config import use_pristine_config_dir  # noqa: E402

use_pristine_config_dir("cs2customizer_x3_race")

import config as C  # noqa: E402

#: 拿两个**互相独立**的普通配置项当标记：恢复之后盘上要么两个都是旧值、
#: 要么两个都是新值；**一个新一个旧 = 混杂**，那就是立案说的那件事。
A, B = "kill_sound_enabled", "cfg_check_enabled"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=200)
    args = ap.parse_args()

    cfg = C.config
    path = Path(C.get_config_path())
    mixed, errors = [], []

    # ⚠⚠ 第一版的造法是**结构上够不到那个窗口的**：写盘线程在紧循环里调
    #    `save_config()`，而它每次都会 `cancel()` 掉上一个 timer 再排一个新的
    #    ⇒ 那个 timer **几乎从来没有到过点**，也就从来没有在 `load_config`
    #    跑着的时候拼过 payload。300 轮 0 次「复现」，量的是我的造法，不是产品。
    # ⭐⭐⭐ **一个造不出敌对时序的复现脚本，和一个证明缺陷不存在的复现脚本，
    #    输出一模一样。**
    # ⇒ 改成对准窗口：排一个 timer，等到它**快要到点**，再进 `load_config`。
    # （第一版那个后台写盘线程已撤 —— 见上）

    import time
    for i in range(args.rounds):
        # ① 内存里两个标记都置 False，排一个防抖 timer（500ms 后拼 payload 写盘）
        setattr(cfg, A, False)
        setattr(cfg, B, False)
        try:
            cfg.save_config()
        except Exception as exc:                       # noqa: BLE001
            errors.append(repr(exc))
        # ② 等到它快到点
        time.sleep(0.495)
        # ③ 此刻造一份「两个标记都是 True」的快照文件并 load —— 正是 restore 那两步
        snap = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        snap[A] = True
        snap[B] = True
        snap["config_schema_version"] = C.CONFIG_SCHEMA_VERSION
        path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        cfg.load_config()                 # ← 不持 `_save_lock`
        # ④ 让那个 timer 跑完，再看盘上是什么
        time.sleep(0.2)
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        if on_disk.get(A) != on_disk.get(B):
            mixed.append((i, on_disk.get(A), on_disk.get(B)))

    print(f"跑了 {args.rounds} 轮；写盘线程报错 {len(errors)} 次")
    print(f"⛔ **新旧混杂** {len(mixed)} 次")
    if mixed:
        for i, a, b in mixed[:5]:
            print(f"   第 {i} 轮：{A}={a} / {B}={b}")
        print("⇒ RN-617 复现成功：恢复之后盘上出现了两个标记不一致的状态。")
    else:
        print("⇒ 本轮**没有复现**。⛔ 按红线 2，这不足以结掉 RN-617，"
              "也不足以证明它不存在 —— 只能说这个造法逮不到它。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
