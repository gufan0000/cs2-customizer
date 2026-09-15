# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X8 的**产物快照**：编译出来的 `cs2customizer.cfg` 逐字长什么样。

## 为什么冻的是产物，不是代码

D5 是**冻结档**（`后续批次规划_20260903.md` §5）：X6 / X7 / X8 这三条
**只有进游戏才验得出来**，所以本批不动刀，要的是「之后没人悄悄改它」的证据。
⭐ 而 X8 有一样别的层没有的东西：**它有一个会离开本进程、进到 CS2 里去的产物。**
契约快照管的是「谁在调哪个名字」；这一份管的是**那几行文本本身**——
一个 `cl_righthand` 写错、一条 bind 少了引号，判据全绿而游戏里当场出事。

## 怎么量的（三条自查）

⚠ ① **必须用全新配置目录**（`use_pristine_config_dir`）。用本机那份真配置的话，
   冻下来的是**我这台机器的键位**，别人跑一次就红，而且那份 diff 里会有个人设置。
⚠ ② **要有不止一个场景**。只冻默认档，等于只冻了「所有功能都关着」那一版 ——
   而 `SECTION_ORDER` 里五段有三段在默认档下是空的。⭐ 空的那几段正是最容易被改坏
   而没人看见的（它们在默认输出里本来就不出现）。
⚠ ③ **逐字冻，不冻摘要**。行数 / 段数 / 哈希都能在内容变了的同时保持不变；
   而这份产物小到可以整篇存下来（默认档实测几十行），没有理由只存摘要。

用法：
    python scripts/x8_cfg_output_snapshot.py
    python scripts/x8_cfg_output_snapshot.py --write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tests" / "baselines" / "x8_cfg_output.json"

#: 场景表。每一项 = (名字, {配置项: 值})。
#: ⭐ 挑的是**会让某一段从空变成非空**的开关 —— 见自查②。
#: ⛔ 这几个键名**不是猜的**：是从 `cfg_compiler` 里那几处 `getattr(config_obj, ...)`
#:   读出来的。第一版我按印象写了 `viewmodel_enabled` / `hud_color_enabled` 之类，
#:   `Config` 上**一个都没有** —— 下面那道 `hasattr` 断言当场逮住。
#:   ⭐ 没有它的话 `setattr` 会安静地新建一个属性，产物照旧是默认档，
#:   而这份快照会声称自己冻了五个场景。
SCENARIOS: list[tuple[str, dict]] = [
    ("默认档", {}),
    ("准心回正开", {"crosshair_reset_enabled": True}),
    ("viewmodel 预设两条", {"viewmodel_presets": [
        {"name": "hi", "key": "F1", "fov": 68, "x": 2.0, "y": 2.0, "z": -1.0},
        {"name": "lo", "key": "F2", "fov": 60, "x": 1.0, "y": 1.0, "z": -2.0},
    ]}),
    # 出厂那一档：同步键默认是 SCROLLLOCK，和默认预设的 F5~F9 不撞。
    ("放大镜同步开·出厂键", {"magnifier": {"sensitivity_sync_enabled": True}}),
    # ⭐ 阳性对照：**故意**把同步键设成 F5 —— 默认预设 1 就绑着 F5。
    #   这一档冻的是「`check_bind_conflicts` 真的会响」；它一旦不响，
    #   上面那几档「没有冲突」就不再说明任何事（NONE ≠ 通过）。
    ("放大镜同步开·故意撞 F5", {"magnifier": {"sensitivity_sync_enabled": True,
                                               "sync_trigger_key": "F5"}}),
    ("准心回正 + viewmodel 同开", {
        "crosshair_reset_enabled": True,
        "viewmodel_presets": [
            {"name": "solo", "key": "F3", "fov": 68, "x": 2.0, "y": 2.0, "z": -1.0}],
    }),
]


def build() -> dict:
    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from _pristine_config import use_pristine_config_dir

    use_pristine_config_dir("cs2customizer_x8_cfg_output", force=True)

    import config as config_mod
    from core import cfg_compiler

    scenes = {}
    for name, overrides in SCENARIOS:
        cfg = config_mod.Config()
        unknown = [k for k in overrides if not hasattr(cfg, k)]
        assert not unknown, (
            f"场景「{name}」里这几个配置项在 `Config` 上不存在：{unknown} —— "
            "配置项被改名了，这份快照量的是一个不存在的场景。")
        for k, v in overrides.items():
            setattr(cfg, k, v)
        text, conflicts = cfg_compiler.compile_all(cfg)
        scenes[name] = {
            "行数": len(text.splitlines()),
            "冲突": conflicts,
            "正文": text.splitlines(),
        }

    #: ⛔ 空转守卫：所有场景产出同一份文本 ⇒ 这张场景表没起作用，
    #:   而「每一段都被冻住了」这句话就成了假的。
    bodies = {json.dumps(v["正文"], ensure_ascii=False) for v in scenes.values()}
    assert len(bodies) > 1, (
        f"{len(SCENARIOS)} 个场景产出了**同一份** cfg —— 这张场景表没有区分力，"
        "冻下来等于只冻了默认档。先确认那几个开关名还对不对。")

    #: ⛔⛔ 第二道守卫：冲突检测必须**至少响一次、也至少不响一次**。
    #:   只响不停 ⇒ 它可能恒真；一次不响 ⇒ 它可能已经死了，
    #:   而「所有场景都没有冲突」和「检测器坏了」在这份快照里长得一模一样。
    fired = [n for n, v in scenes.items() if v["冲突"]]
    quiet = [n for n, v in scenes.items() if not v["冲突"]]
    assert fired and quiet, (
        f"冲突检测在这批场景里{'从不响' if not fired else '从不安静'}"
        f"（响：{fired}；不响：{quiet}）—— 场景表里必须同时有撞键和不撞键的档。")

    return {
        "_说明": "编译出来的 cs2customizer.cfg 逐字内容。改动它 = 改动进到 CS2 里的东西。",
        "段顺序": list(cfg_compiler.SECTION_ORDER),
        "场景数": len(scenes),
        "场景": scenes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    data = build()
    print(f"段顺序：{data['段顺序']}")
    for name, s in data["场景"].items():
        print(f"  {name:<14} {s['行数']:>3} 行"
              + (f"  ⚠ 冲突 {s['冲突']}" if s["冲突"] else ""))

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                  sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n已写入 {OUT.relative_to(ROOT)}")
    else:
        print("\n（没给 --write，什么都没写）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
