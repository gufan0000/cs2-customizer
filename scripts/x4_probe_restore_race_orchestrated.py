# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-617 第三次复现：**不再赛跑，改成编排时序**。

## 前两次为什么没复现（批 85 在册）

① 后台线程紧循环 `save_config()` 300 轮 —— ⭐⭐⭐ **结构上够不到那个窗口**：
   `save_config` 每次都 `cancel()` 掉上一个 timer 再排一个新的，那个 timer 几乎从没到过点。
② 改成对准窗口（排一个 timer、睡到它快到点、再进 `load_config`）60 轮，仍 0 次。
   窗口在代码上确实存在，但对齐宽度只有几十微秒量级，**随机撞不到**。

⭐⭐⭐ **一个造不出敌对时序的复现脚本，和一个证明缺陷不存在的复现脚本，输出一模一样。**
⇒ 这一次不靠概率：在 `load_config` **走到一半**的那一刻，**强制**让保存跑完整一遍。

## 怎么编排（只加一层包装，不改任何被测逻辑）

`load_config` 把 187 个键分 26 段赋给 `self`，每段一次 `self._load_plain(...)`。
把 `_load_plain` 包一层：走到第 N 段时按住 —— 此刻实例上**前 N 段是新值、
后面全是旧值** —— 然后让 `_do_save_config` 在另一个线程完整跑一遍、写盘、返回，
再放 `load_config` 继续。

⚠ 这是**真实时序的一个特例**，不是新造的场景：`_do_save_config` 由防抖 timer 在
自己的线程里调，而 `load_config` 全程不持 `_save_lock`（那把锁只出现在
`save_config` / `save_config_now` / `_do_save_config` 里）—— 两者可以这样交叠。
编排只是把「几十微秒的对齐」变成「必然发生」。

⛔⛔ 顺手记住批 85 排除掉的那条路：`_save_lock` 是不可重入的 `threading.Lock()`，
而 `load_config` 末尾经 `_run_schema_migrations` 会调 `_do_save_config` ⇒
**让 `load_config` 全程持锁会当场死锁在主配置加载路径上。**

用法：`python scripts/x4_probe_restore_race_orchestrated.py [--at N]`
返回 0 = 复现了混合态；1 = 没复现。
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# ⛔ 不许自己写 `CS2C_CONFIG_DIR`（RN-031/032）—— 见 `_pristine_config.py`。
from _pristine_config import use_pristine_config_dir  # noqa: E402

_TMP = use_pristine_config_dir("cs2customizer_x4_race_probe", force=True)

import config as config_mod  # noqa: E402

CFG_PATH = _TMP / "config.json"

#: 两个**不在同一段** `_load_plain` 里的布尔配置项 —— 只有分处两段，
#: 「前半新、后半旧」才可能在盘上同时出现。
EARLY_KEY = "kill_sound_enabled"
LATE_KEY = "music_cache_enabled"


def _write(payload: dict) -> None:
    payload = dict(payload)
    payload["config_schema_version"] = config_mod.CONFIG_SCHEMA_VERSION
    io.open(CFG_PATH, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", type=int, default=6,
                    help="在第几次 `_load_plain` 之后按住（默认 6）")
    args = ap.parse_args()

    cfg = config_mod.Config()
    cfg.config_file = str(CFG_PATH)

    # 盘上是「快照」：两个键都是 True
    _write({EARLY_KEY: True, LATE_KEY: True})
    # 内存里是「用户刚改过的当前状态」：两个键都是 False
    setattr(cfg, EARLY_KEY, False)
    setattr(cfg, LATE_KEY, False)
    print(f"快照（盘上）：{EARLY_KEY}=True  {LATE_KEY}=True")
    print(f"当前（内存）：{EARLY_KEY}=False {LATE_KEY}=False")

    saved = threading.Event()
    released = threading.Event()
    calls = {"n": 0}
    real_load_plain = type(cfg)._load_plain

    def wrapped(self, data, *keys):
        real_load_plain(self, data, *keys)
        calls["n"] += 1
        if calls["n"] == args.at and not saved.is_set():
            # 此刻：前 N 段已是快照值，后面还是内存里的当前值
            print(f"\n⏸ `load_config` 走到第 {args.at} 段 —— "
                  f"此刻 {EARLY_KEY}={getattr(self, EARLY_KEY)} "
                  f"/ {LATE_KEY}={getattr(self, LATE_KEY)}")

            def do_save():
                # 防抖 timer 到点后走的就是这个函数（它自己会取 `_save_lock`）
                self._do_save_config()
                saved.set()

            t = threading.Thread(target=do_save, name="DebounceSave")
            t.start()
            saved.wait(10)
            t.join(10)
            print("▶ 保存已整段跑完，放 `load_config` 继续")
            released.set()

    type(cfg)._load_plain = wrapped
    try:
        cfg.load_config()
    finally:
        type(cfg)._load_plain = real_load_plain

    if not saved.is_set():
        print(f"\n⚠ 第 {args.at} 段没走到（`_load_plain` 只被调了 {calls['n']} 次）"
              " —— 换个 --at 再试。这一轮**不算证据**。")
        return 1

    on_disk = json.loads(io.open(CFG_PATH, encoding="utf-8").read())
    early, late = on_disk.get(EARLY_KEY), on_disk.get(LATE_KEY)
    print(f"\n盘上最终：{EARLY_KEY}={early}  {LATE_KEY}={late}")
    print(f"内存最终：{EARLY_KEY}={getattr(cfg, EARLY_KEY)} "
          f"/ {LATE_KEY}={getattr(cfg, LATE_KEY)}")

    if early is True and late is True:
        print("\n✅ 盘上全是快照值 —— **没有**混合态。")
        print("   根因已查明：`load_config` 的 `with open(...)` 包住了整段赋值，"
              "读句柄全程开着 ⇒ 这期间 `os.replace` 在 Windows 上必然 `WinError 5`，"
              "那份混杂的配置**落不了盘**。")
        print("   ⚠ 挡住它的是一个**顺带的**副作用，没有人是为了这个才那么写的。")
        # 但那一次被挡掉的保存去哪了？
        # RN-622 之前：**整个丢掉**（记一行 ERROR、删临时文件、什么都不做）。
        # 现在：重排，1 秒后再写一遍。
        # ⚠ **在「恢复快照」这个场景里，丢掉它其实是无害的** —— 用户点恢复，
        #   要的就是让快照盖掉刚才那次改动；等重试到点时 `load_config` 早已跑完，
        #   `self` 上已经是快照值，于是它写回去的和盘上的**一模一样**。
        # ⭐⭐⭐ 所以这支探针**证不了 RN-622 的价值** —— 它只证得了
        #   「那次写盘确实被挡掉了」。真正的代价在**另一条**链路上：
        #   `config_reload_bus` 触发的重载、或任何不是用户主动要覆盖的 `load_config`，
        #   那时被挡掉的是用户刚改的设置，而它不会被任何东西补回来。
        #   ⇒ 那一条由判据 `tests/test_a_failed_config_write_is_retried_not_dropped.py`
        #     直接量（造一次必然失败的 `os.replace`，看值到底落没落盘）。
        peak = 0          # ⚠ 记**峰值**：写成功会把额度还原，只看结束那一刻永远是 0
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            with cfg._save_lock:
                pending = cfg._save_timer is not None
                peak = max(
                    peak,
                    config_mod._SAVE_RETRIES_ON_FAILURE - cfg._save_retries_left)
            if peak > 0 and not pending:
                break
            time.sleep(0.2)
        if peak > 0:
            print(f"\n⭐ 那次写盘失败后排了重试并自己补上了（RN-622 在起作用；"
                  f"峰值用掉 {peak} 次额度，写成功后已还原）。")
        else:
            print("\n⚠ 没看到重试被排上 —— 请确认 RN-622 还在。")
        return 1
    if early is False and late is False:
        print("\n✅ 盘上全是「当前值」—— 保存整段跑在 load 之前，也不是混合态。")
        return 1
    print(f"\n⛔ **复现**：盘上是**新旧混杂**的（{EARLY_KEY}={early} / {LATE_KEY}={late}）。")
    print("   用户点「恢复」，界面报「恢复成功」，而磁盘上是一份两边都不是的配置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
