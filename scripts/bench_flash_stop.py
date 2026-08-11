#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""闪光子进程 start→stop 耗时基准（UP-007 的验收工具）。

为什么单独做一个:退出冻结在完整 App 里表现不稳定(受页面构建时序影响,有时
触发有时不触发),光看整体退出耗时会误判。这个脚本只起停闪光子进程本身,
把变量隔离掉,结果高度可复现。

实测(2026-08-08,同机同条件,各 8 次):
    修复前: 中位 2019ms —— 8/8 次全部卡满 process.join(timeout=2.0),
            即子进程**每次**都没能自己退出,只能靠父进程 terminate();
    修复后: 中位   79ms —— 子进程正常自行退出。

根因:FlashEffectProcess.shutdown() 跑在命令线程上,却在那里调 pygame.quit()。
主循环此时很可能正卡在 display.flip()/blit 中途,SDL 显示被并发拆掉,进程挂住。
修法:shutdown() 只置 is_running=False,pygame.quit() 交给主循环退出后自己做。

用法:
    python scripts/bench_flash_stop.py              # 5 次，每次存活 3 秒
    python scripts/bench_flash_stop.py 8 3

⚠️ 会真的创建全屏透明置顶窗口(每次几秒),但不注册热键、不占 GSI 端口。
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 隔离配置与日志目录，绝不碰用户真实数据
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_tmp = Path(tempfile.gettempdir()) / "cs2customizer_flashbench"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("CS2C_LOG_DIR", str(_tmp / "logs"))

from config import config  # noqa: E402
from flash_process_manager import FlashProcessManager  # noqa: E402

# 超过这个值基本可以断定子进程没自己退出（父进程的 join 超时是 2.0 秒）
_SUSPECT_MS = 1500


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    alive = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0

    costs = []
    for i in range(runs):
        mgr = FlashProcessManager(config)
        mgr.start_process(2560, 1440)
        time.sleep(alive)  # 让子进程真的渲染一会儿再停
        t0 = time.perf_counter()
        mgr.stop_process()
        cost = (time.perf_counter() - t0) * 1000
        costs.append(cost)
        flag = "  ⚠ 疑似走了强制终止" if cost >= _SUSPECT_MS else ""
        print(f"  第{i + 1}次: {cost:.0f}ms{flag}", flush=True)
        time.sleep(0.5)

    med = statistics.median(costs)
    slow = sum(1 for c in costs if c >= _SUSPECT_MS)
    print(f"\n中位 {med:.0f}ms | 最大 {max(costs):.0f}ms | 最小 {min(costs):.0f}ms")
    print(f"疑似强制终止: {slow}/{runs} 次")
    if slow:
        print("\n❌ 子进程没能自行退出——检查 FlashEffectProcess.shutdown() 是否又在")
        print("   命令线程里调了 pygame.quit()（见本文件头部的根因说明）。")
        return 1
    print("\n✅ 子进程均正常自行退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
