#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量 `widgets/` 组件的真实采用率（UP-047 用）。

为什么要专门写个脚本：R7 与 R8 各有一次把这件事量错了——
- 一次是拿"代码路径存在"当"有实例"（`IconLabel` 在 `if icon:` 分支里，但全站没人传 icon）；
- 一次是只 grep `SettingsCard(`，漏掉了真正的入口 `SettingsCard.make(...)` 这个类方法，
  于是得出"零采用"的结论，与事实正相反。

所以这里按 **AST** 统计三类事实，分开报，不混：
  1. 直接构造 `Comp(...)`
  2. 工厂调用 `Comp.make(...)` / `Comp.create(...)`
  3. 手搓等价物：`setObjectName("card")` 的 QFrame（`SettingsCard` 的替代品）

只看 `pages/` 与 `dialogs/`（`widgets/` 内部互相引用不算采用）。
"""
from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ("pages", "dialogs")
COMPONENTS = (
    "PageHeader",
    "SettingsRow",
    "SettingsCard",
    "PageActionBar",
    "IconLabel",
    "StatusChip",
)
FACTORY_NAMES = {"make", "create", "build"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _iter_files():
    for d in TARGET_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            yield p


def scan():
    direct = Counter()
    factory = Counter()
    per_file = {}
    handmade = Counter()

    for path in _iter_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        hits = Counter()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # Comp(...)
            if isinstance(fn, ast.Name) and fn.id in COMPONENTS:
                direct[fn.id] += 1
                hits[fn.id] += 1
            # Comp.make(...)
            elif (
                isinstance(fn, ast.Attribute)
                and fn.attr in FACTORY_NAMES
                and isinstance(fn.value, ast.Name)
                and fn.value.id in COMPONENTS
            ):
                factory[fn.value.id] += 1
                hits[fn.value.id] += 1
            # xxx.setObjectName("card")
            elif (
                isinstance(fn, ast.Attribute)
                and fn.attr == "setObjectName"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "card"
            ):
                handmade[rel] += 1
        if hits:
            per_file[rel] = hits
    return direct, factory, per_file, handmade


def main() -> int:
    direct, factory, per_file, handmade = scan()
    print("=" * 64)
    print("组件采用率（只统计 pages/ 与 dialogs/）")
    print("=" * 64)
    print(f"{'组件':<16}{'直接构造':>10}{'工厂调用':>10}{'合计':>8}")
    for comp in COMPONENTS:
        d, f = direct[comp], factory[comp]
        print(f"{comp:<16}{d:>10}{f:>10}{d + f:>8}")

    total_handmade = sum(handmade.values())
    print()
    print(f"手搓 QFrame#card（SettingsCard 的替代品）：{total_handmade} 处，"
          f"分布在 {len(handmade)} 个文件")
    for rel, n in handmade.most_common():
        print(f"    {n:>3}  {rel}")

    print()
    print("已采用组件的文件：")
    for rel, hits in sorted(per_file.items()):
        detail = "  ".join(f"{k}×{v}" for k, v in sorted(hits.items()))
        print(f"    {rel:<40} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
