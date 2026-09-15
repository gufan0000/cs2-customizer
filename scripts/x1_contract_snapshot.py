# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X1（主窗骨架）的**契约快照**：`MainWindow` 上有哪些名字是外面真的依赖着的。

## 为什么需要它

`gui_widget.py` 5073 行，`MainWindow` 一个类 4958 行 / 169 个方法 / 115 个 `self` 属性。
动它之前得先知道：**改哪个名字会把别人弄断。**

实测（本脚本产出）：284 个名字里，**84 个**被 `gui_widget.py` 之外的代码引用；
而其中 **41 个是下划线开头的** —— ⭐⭐ **「私有」这个约定在这里保护不了任何人**：
改名、挪走、删掉其中任何一个，调用方当场断，而**没有任何东西看着这件事**。

⇒ 把这 84 个名字冻成一份快照，配一条判据（`tests/test_x1_contract_is_frozen.py`）。
X1 动刀时，改一个契约名就必须**同时更新快照**，那一步会逼人回答「谁在用它、都改了吗」。

## 怎么量的（两条自查，都是踩出来的）

⚠ ① **不能统计 `X.attr` 里的任何 X**：第一版这么干，于是 `logger` / `config` /
   `__init__` / `resizeEvent` 被算成了「主窗的契约」—— 它们只是**同名**。
   ⇒ 只算**接收者看起来是主窗**的那些访问（`win` / `main_window` / `self.window()` …）。
   ⭐ 宁可漏，不可把别人的同名属性算进来 —— 一份虚胖的契约会把真正该冻的东西淹掉。
⚠ ② **要排掉 `.claude/worktrees/`**：那是别的会话（或回退验证）的工作树副本，
   不排的话每个名字都被多数一遍，文件数直接翻倍。

用法：`python scripts/x1_contract_snapshot.py [--write]`
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "gui_widget.py"
OUT = ROOT / "tests" / "baselines" / "x1_contract.json"

#: 接收者叫这些名字时，认为它是主窗。
WINDOW_NAMES = {"win", "window", "main_window", "mw", "_win", "main_win",
                "real_window", "app_window"}
WINDOW_ATTRS = {"main_window", "window", "_win", "main_win"}
SKIP_PREFIX = (".build", "release/", "build_tools/oss_sync/", ".claude/")


def main_window_names() -> tuple[set[str], set[str]]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    methods = {n.name for n in cls.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    attrs = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) \
                        and getattr(target.value, "id", None) == "self":
                    attrs.add(target.attr)
    return methods, attrs


def _receiver_is_window(value) -> bool:
    if isinstance(value, ast.Name):
        return value.id in WINDOW_NAMES
    if isinstance(value, ast.Attribute):
        return value.attr in WINDOW_ATTRS
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Attribute) and func.attr in {"window", "parent"}:
            return True
        if isinstance(func, ast.Name) and func.id == "MainWindow":
            return True
    if isinstance(value, ast.Subscript):
        return _receiver_is_window(value.value)
    return False


def collect() -> dict:
    methods, attrs = main_window_names()
    names = methods | attrs
    assert len(names) > 150, f"只从 MainWindow 解析出 {len(names)} 个名字 —— 解析器坏了"

    users: dict[str, Counter] = defaultdict(Counter)
    scanned = 0
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "gui_widget.py" or rel.startswith(SKIP_PREFIX):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanned += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in names \
                    and _receiver_is_window(node.value):
                users[node.attr][rel] += 1
    assert scanned > 300, f"只扫到 {scanned} 个 .py —— 分母塌了"

    contract = {
        name: sorted(files)
        for name, files in sorted(users.items()) if files
    }
    # ⭐⭐⭐ 2026-09-06 批 60：**把「谁在依赖」分开记。**
    #   原来只有一个「下划线开头却被依赖 = 41」，而那 41 里
    #   **产品/脚本只占 7 个，其余 41 个是判据**（批 57~60 写的那几支专门测私有链路）。
    #   ⚠ 两者的风险完全不同：
    #     · 产品代码从外面伸手进主窗拿私有属性 —— 那是**动刀时的雷区**；
    #     · 判据贴着实现测私有方法 —— 那本来就是判据该干的事，改名时它当场红，
    #       而那正是我们要的信号，不是要消灭的耦合。
    #   ⇒ 混在一个数里，棘轮就只能松到没意义（或者紧到逼人删判据）。
    private = sorted(n for n in contract if n.startswith("_"))
    by_product = sorted(
        n for n in private
        if any(not f.startswith("tests/") for f in contract[n]))
    return {
        "_说明": "MainWindow 上被 gui_widget.py 之外的代码依赖的名字。改名/删除前先看这里。",
        "总名字数": len(names),
        "契约名字数": len(contract),
        "下划线开头却被依赖": private,
        "其中产品或脚本在依赖": by_product,
        "扫描文件数": scanned,
        "契约": contract,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写入快照文件")
    args = ap.parse_args()
    data = collect()
    # ⚠ GBK 控制台吃不下 ⇒ 之类的字，输出回退成 ASCII 安全形式。
    line = ("MainWindow names=%d -> contract=%d (underscore-but-depended=%d)"
            % (data["总名字数"], data["契约名字数"],
               len(data["下划线开头却被依赖"])))
    print(line)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print("已写入", OUT)
    else:
        print("（没给 --write，什么都没写）")
