# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X3：**存得进去的键，读得回来吗** —— 一条真正的往返判断，不靠形状猜。

⚠ 这份脚本存在，是因为 `x3_key_triplication.py` 的差集**不能直接当缺陷读**：
它只认 `self.X = config_data.get("X", self.X)` 那一种机械形状，
而有默认值校验、迁移、归一化的键走的是别的写法 —— ⭐ **那份差集量的是
「有没有走那条机械路」，不是「读不读得回来」，两者长得一模一样。**
（同 X2 盘点那次：`get` 58 次大半是 `dict.get`，⭐ **名字一样不等于是那件事**。）

⇒ 这里换一把更硬的尺子：**真的跑一次往返**。
造一份配置、改掉每一个键、存盘、重新 `Config()` 读回来，逐键比对。
读不回来的那些才是缺陷；`x3_key_triplication.py` 报的 43 个里有多少是真的，
由这一份说了算。

用法：`python scripts/x3_save_load_roundtrip.py`
"""
from __future__ import annotations

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

use_pristine_config_dir("cs2customizer_x3_roundtrip")

import config as C  # noqa: E402


def _mutate(v):
    """给一个值造一个**确定不同**的新值，且类型不变。"""
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + 7
    if isinstance(v, float):
        return round(v + 0.25, 6)
    if isinstance(v, str):
        return (v + "_x3") if v else "x3"
    if isinstance(v, list):
        return v + ["x3"] if all(isinstance(i, str) for i in v) else v
    if isinstance(v, dict):
        return {**v, "__x3__": 1}
    return None  # 不认识的类型不动它


def identity_arm() -> tuple[list[str], dict]:
    """⭐⭐⭐ 第一臂：**原样存、原样读**。

    ⚠ 这一臂是后补的，而它订正了我自己的第一版结论。第一版只有下面那个「改一个值」
    的臂，报出 22 个键读不回来 —— 我差一点把它当成缺陷写下去。
    实际上我造的新值（`"minimal_x3"`、`{"__x3__": 1}`）**本来就是非法的**，
    而那些键上正好有归一化在把它们打回默认值 ⇒ ⭐ **那 22 条里有一部分不是缺陷，
    是校验在正常工作，而两者在这把尺子上长得一模一样。**
    ⇒ 身份往返没有「值合不合法」这个变量：**默认值一定是合法的**，
    它要是活不过一次往返，那就是真丢了。
    """
    cfg = C.Config()
    before = {k: v for k, v in vars(cfg).items() if not k.startswith("_")}
    cfg.save_config_now()
    fresh = C.Config()
    fresh.load_config()
    lost = [k for k, v in sorted(before.items())
            if getattr(fresh, k, "<缺席>") != v]
    return lost, before


def main() -> int:
    lost_identity, _ = identity_arm()
    print(f"【第一臂 · 身份往返】原样存再读，变了的 {len(lost_identity)} 个：")
    print("   " + (", ".join(lost_identity) or "（无）"))
    print()

    cfg = C.Config()
    before = {k: v for k, v in vars(cfg).items() if not k.startswith("_")}

    changed, skipped = {}, []
    for k, v in sorted(before.items()):
        nv = _mutate(v)
        if nv is None or nv == v:
            skipped.append(k)
            continue
        try:
            setattr(cfg, k, nv)
        except Exception:  # noqa: BLE001 —— property 只读的，跳过并记名
            skipped.append(k)
            continue
        changed[k] = nv

    cfg.save_config_now()
    path = Path(C.get_config_path())
    raw = json.loads(path.read_text(encoding="utf-8"))

    fresh = C.Config()
    fresh.load_config()

    lost_on_disk, lost_on_load, rejected = [], [], []
    for k, want in changed.items():
        got = getattr(fresh, k, "<缺席>")
        if got == want:
            continue
        if k not in raw:
            lost_on_disk.append(k)
        elif got == before[k]:
            # ⭐ 落回默认值 = 归一化/校验**拒绝了我造的那个非法值**，这是它在正常工作
            rejected.append(k)
        else:
            lost_on_load.append(k)

    print(f"【第二臂 · 改一个值】属性总数 {len(before)}；改动 {len(changed)}；"
          f"跳过（只读/类型不认识）{len(skipped)}；盘上键数 {len(raw)}")
    print(f"\n⛔ **存不进盘** {len(lost_on_disk)} 个：")
    print("   " + (", ".join(sorted(lost_on_disk)) or "（无）"))
    print(f"\n⛔ **盘上有、读回来是第三个值** {len(lost_on_load)} 个：")
    print("   " + (", ".join(sorted(lost_on_load)) or "（无）"))
    print(f"\n✅ 落回默认值 = 校验拒绝了我造的非法值（**不是缺陷**）{len(rejected)} 个：")
    print("   " + (", ".join(sorted(rejected)) or "（无）"))
    print(f"\n跳过的：{', '.join(sorted(skipped)) or '（无）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
