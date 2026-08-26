# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-188：**先量全站每一页有几颗主按钮，再谈规则。**

## 为什么是一支脚本而不是一条判据

RN-188 立案时写死了顺序，原话：

> ⚠ **不能直接上全站铁规**：本仓有刻意让同一个动作在卡里和底栏各出现一次的设计
> （RN-078 的 `viewmodel`「保存到CFG」，两处同名是判过的），一条全站硬判据会当场
> 诬告它。⇒ 要先**量分布**再定规则……
> ⭐ 顺序不能反 —— **先立规则后量分布，等于让规则去决定证据**。

所以这一支只**报数**，不判对错。逐条定性之后，例外表和判据才有依据可写。

## 它量的是什么，不量什么（⭐ 分母要说清楚）

- 量：产品默认（普通模式、全新配置）下，每一页 `objectName == "primaryButton"`
  且 `isVisibleTo(page)` 为真的按钮。
- ⛔ **只量这一个状态。** 同一页在别的状态下可能多长出一颗 —— RN-186 就是
  「空库时引导卡和底栏各一颗紫」，而它在有库的状态下不成立。
  ⚠ 全新配置对音效家族**恰好就是空库态**（所以下面能看到「去社区拿一套…」），
  但对别的页不是。**这是已知且被声明的分母缺口**，别把这份数读成「全状态覆盖」。
- ⛔ **不量专家模式**（RN-134：默认按普通模式取样）。
- ⚠ `isVisible()` 在离屏窗口上恒为 False，所以看的是 `isVisibleTo(page)`。
- ⚠⚠ **有些页的数是时序相关的，这支脚本量不准。** `audio_health` 的主按钮要等
  `_run_health_check()` 起的**后台线程**把报告送回来才配置 —— 本脚本扫到 **0 颗**，
  而 `tests/test_one_primary_button_per_screen.py`（多抽了几次 `processEvents`）
  扫到 **1 颗**。⭐⭐ **两次测量同一件事得到两个数，那个差值就是被测对象里
  我还没看见的一个自由度。** ⇒ 这类页由那支判据用 AST 从**规则**上钉住
  （每条分支都必须 `configure_primary`），**不靠这里的数**。

用法:
    python scripts/primary_button_census.py            # 报数
    python scripts/primary_button_census.py --json H:/tmp/census.json
退出码永远 0 —— **它是一次测量，不是一道门。**
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ui_mode  # noqa: E402
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_primary_census")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _audit_neutralize import (  # noqa: E402
    apply as neutralize_apply,
    enable_audit_mode,
    unsafe_pages,
)

enable_audit_mode()

PRIMARY_OBJECT_NAME = "primaryButton"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default="", help="把结果另存一份 JSON")
    ap.add_argument("--expert", action="store_true",
                    help="按专家模式取样（默认普通模式，见 RN-134）")
    args = ap.parse_args()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from _audit_sandbox import sandbox_external_writes  # noqa: E402

    sandbox_external_writes()
    _ui_mode.apply(__import__("config").config, args.expert)

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    app.processEvents()

    import _audit_music_bar as _mbar
    print("   " + _mbar.pin(win, app, _mbar.MODE_PRISTINE))

    config = __import__("config").config
    page_ids = list(win._page_names.keys())
    total = len(page_ids)
    neutralize_apply(config, page_ids)
    skipped = sorted(p for p in page_ids if p in unsafe_pages())
    page_ids = [p for p in page_ids if p not in skipped]

    rows = []
    for pid in page_ids:
        try:
            _ui_mode.goto(win, pid)
            app.processEvents()
            page = win.pages.get(pid)
            if page is None:
                rows.append((pid, None, []))
                continue
            texts = [
                b.text().strip()
                for b in page.findChildren(QAbstractButton)
                if b.objectName() == PRIMARY_OBJECT_NAME and b.isVisibleTo(page)
            ]
            rows.append((pid, len(texts), texts))
        except Exception as exc:                      # noqa: BLE001
            rows.append((pid, "ERR", [repr(exc)[:60]]))

    print(f"\n== 全站主按钮普查 ｜ 界面 {_ui_mode.describe(args.expert)} ｜ "
          f"覆盖 {len(page_ids)}/{total} 页 ==")
    if skipped:
        print(f"   ⚠ 跳过（构造即起设备，中和表也中和不了）: {skipped}")

    for pid, count, texts in sorted(rows, key=lambda r: (r[1] != 0 and r[1] is not None
                                                        and r[1] or 0) * -1):
        mark = ""
        if count == 0:
            mark = "   ← 一颗都没有"
        elif isinstance(count, int) and count > 1:
            mark = "   ←← 同屏多颗"
        print(f"   {pid:22s} {count}  {texts}{mark}")

    multi = [r for r in rows if isinstance(r[1], int) and r[1] > 1]
    zero = [r for r in rows if r[1] == 0]
    print(f"\n   同屏 >1 颗: {len(multi)} 页 —— {[r[0] for r in multi]}")
    print(f"   一颗都没有: {len(zero)} 页 —— {[r[0] for r in zero]}")
    print("\n   ⛔ 这份数只覆盖**产品默认状态**。同一页在别的状态下可能多长一颗"
          "（RN-186 就是空库那一态）。别把它读成全状态覆盖。")

    if args.json.strip():
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"expert": args.expert, "skipped": skipped,
             "pages": [{"page": p, "count": c, "texts": t} for p, c, t in rows]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n   → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
