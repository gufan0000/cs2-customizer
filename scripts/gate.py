# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-194：本机跑离屏审计的入口 —— **让 `$?` 重新可信**。

## 为什么需要它

三道离屏审计（排版 / 焦点 / 对比度）都驱动 Qt，而 Qt/keyboard/音频在解释器
退出期还会跑析构，**退出码在那一段路上两个方向都被洗过**（来历见
`_audit_verdict.py` 开头）。RN-092 当年把裁定从退出码里搬了出来，CI 侧
（`.github/verdict.ps1`）从此读裁定行、不读退出码。

**本机这一侧一直没有对应物**，于是收工时还是 `echo $?`。2026-08-22 实测：

    同一台机器、同一棵树，完整档排版审计跑 9 次
    → 3 次退出码 127，而同一次输出里的裁定行是 `RESULT layout rc=0`
    → 其中至少一次能证明 `os._exit(0)` 已经执行到了

⇒ 那 3 次会被读成「排版审计失败」，而审计其实全绿。**假红也是错的判据**：
它教人忽略这道门。

## 怎么用

    python scripts/gate.py layout               # 完整档
    python scripts/gate.py layout --compact     # 多余的参数原样透传
    python scripts/gate.py focus
    python scripts/gate.py contrast
    python scripts/gate.py all                  # 三道全跑，任一红即红

本脚本自己不碰 Qt，所以**它的退出码是干净的**：0 = 裁定绿，1 = 裁定红或
根本没拿到裁定行（与 CI 同一条规矩：读不到裁定 = 失败，不是"大概过了"）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# ⚠ 审计的输出里有 ✓/✗ 和大量中文，而 Windows 控制台默认是 GBK：
# 不改编码的话 `sys.stdout.write` 直接 UnicodeEncodeError，于是这道**本来
# 用来消灭假红的门，自己变成一个新的假红**（实测：连跑三次全是 exit 1）。
# 审计脚本自己早就有这一行，转发它的输出当然也要有。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _audit_verdict import parse_verdict  # noqa: E402

#: 审计名 → 脚本。**名字必须与脚本自己 `deliver("<名>", …)` 里报的一致**，
#: 判据 `test_the_local_gate_covers_every_audit` 会拿 AST 去对。
AUDITS: dict[str, str] = {
    "layout": "layout_overflow_audit.py",
    "focus": "tab_order_audit.py",
    "contrast": "ui_contrast_audit.py",
    # RN-511（2026-09-04 批 46）：搜索索引同步也是一道**阻断级**的门，
    # 从批 45 起就在 CI 里，却一直不在本机入口里 —— 于是本机只能靠 `echo $?`，
    # 而这个进程的退出码实测被洗成过 -1073740791（0xC0000409）。
    "search_index": "build_search_index.py",
}

#: 有的门禁脚本**不是「跑起来就是审计」**：它还有别的模式（生成 / 统计 / 交叉核对），
#: 只有某个开关下才是门。⭐ 少给这个开关不是「少测一点」，是**本机那一跑会去改产品文件**
#: （`build_search_index.py` 不带 `--check` 就直接重写 `core/search_index.json`），
#: 而且不打裁定行 ⇒ 门当场判「没有结论」。判据钉在
#: `tests/test_ci_gates_read_the_verdict_line.py`。
DEFAULT_ARGS: dict[str, list[str]] = {
    "search_index": ["--check"],
}


def run_one(name: str, extra: list[str], echo: bool = True) -> int:
    """跑一道门，返回 0/1。**裁定取自输出，退出码只当辅助信号。**"""
    script = HERE / AUDITS[name]
    cmd = [sys.executable, str(script), *DEFAULT_ARGS.get(name, []), *extra]
    proc = subprocess.run(  # noqa: S603  自己仓里的脚本，argv 形式不过 shell
        cmd, cwd=str(HERE.parent), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if echo:
        sys.stdout.write(out)
        sys.stdout.flush()

    rc = parse_verdict(out, name)
    if rc is None:
        print(f"!! [{name}] 输出里没有 `RESULT {name} rc=<n>` —— "
              f"审计没活到交裁定那一步，按失败处理"
              f"（进程退出码 {proc.returncode}，但那个数不作数）")
        return 1
    if rc != 0:
        print(f"!! [{name}] 裁定为红：RESULT {name} rc={rc}")
        return 1
    if proc.returncode != 0:
        # ⭐ 这正是 RN-194 那件事。报出来但**不改裁定** —— 记录它出现的频次，
        # 免得以后又变成"没现形不等于没有"。
        print(f"   [{name}] 裁定绿；⚠ 进程退出码是 {proc.returncode}，"
              f"与裁定不一致（RN-194：Qt 退出期改写，裁定为准）")
    else:
        print(f"   [{name}] 裁定绿")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="本机离屏审计入口（读裁定行，不读退出码）")
    ap.add_argument("name", choices=[*AUDITS, "all"])
    ap.add_argument("extra", nargs=argparse.REMAINDER,
                    help="原样透传给审计脚本的参数，如 --compact")
    args = ap.parse_args()

    extra = [a for a in args.extra if a != "--"]
    if args.name == "all":
        if extra:
            print("!! `all` 不接受透传参数：三道门的参数各不相同")
            return 2
        worst = 0
        for name in AUDITS:
            worst = max(worst, run_one(name, []))
        return worst
    return run_one(args.name, extra)


if __name__ == "__main__":
    # 本脚本不碰 Qt，退出码干净，可以正常 `sys.exit`。
    sys.exit(main())
