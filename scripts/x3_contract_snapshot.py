# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X3（配置层）的**契约快照**：配置层上有哪些名字是外面真的依赖着的。

## 为什么需要它，以及为什么它和 X1 那份不是同一种东西

X1 的契约面是**一个类的方法与属性**（`MainWindow` 4958 行），所以
`x1_contract_snapshot.py` 量的是「谁在 `win.xxx` 上取名字」。
X3 不是那个形状：`config.py` 是**模块级**的（一个 `Config` 类 + 一堆模块函数
+ 一堆常量），而三个配套模块（`config_reload_bus` / `io_validation` /
`config_snapshot_manager`）是纯函数面。
⭐⭐ **同样叫「契约快照」，两条链路量的根本不是一回事** —— 所以这份不是把 X1 那份
「通用化」得来的，是照 X3 自己的形状重写的。
（共享层规划 §二-9 设想过一个 `--target` 通用版；实测两边的接收者判定没有公共部分：
X1 靠「接收者名字像主窗」，X3 靠「import 了哪个模块」。硬做通用只会让两边都变糊。）

## 怎么量的（三条自查，两条是从 X1 那份继承的教训）

⚠ ① **`config.` 开头的属性访问不算数**：产品里到处是 `self.config.xxx`，
   而 `self.config` 大多是 `Config` 实例 —— 那是**实例契约**，要单独一栏。
   模块级名字只认 `from config import X` / `import config` + `config.X`。
⚠ ② **排掉 `.build/` / `_manual_backup*` / `output/` / `.claude/worktrees/`**：
   worktree 是别的会话或回退验证的副本，不排的话每个名字被多数一遍。
   （X2 盘点第一版把 `.build/` 数进去，绕过面虚报成 632 文件 —— **宁可漏，不可虚胖**。）
⚠ ③ **`Config` 实例属性要按「有没有默认值」分两类**：有默认值的是配置项（数百个，
   它们的契约是**键名**，归 schema 那一栏），没有的是内部状态。
   把两者混在一起数，会得到一个虚胖到没法用的契约面。

用法：`python scripts/x3_contract_snapshot.py [--write]`
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "baselines" / "x3_contract.json"

#: X3 层的四个文件。键 = 外面 import 时写的模块名。
LAYER = {
    "config": ROOT / "config.py",
    "core.config_reload_bus": ROOT / "core" / "config_reload_bus.py",
    "core.io_validation": ROOT / "core" / "io_validation.py",
    "core.config_snapshot_manager": ROOT / "core" / "config_snapshot_manager.py",
}

SKIP_PARTS = {".build", "__pycache__", "output", "node_modules", ".git"}
SKIP_PREFIX = ("release/", "build_tools/oss_sync/", ".claude/")


def _skip(rel: str) -> bool:
    parts = set(Path(rel).parts)
    if parts & SKIP_PARTS:
        return True
    if any("_manual_backup" in p or p.startswith("_archive") for p in parts):
        return True
    return rel.startswith(SKIP_PREFIX)


def live_py_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if not _skip(rel):
            out.append(p)
    return sorted(out)


def module_surface(path: Path) -> dict:
    """模块级的公开名字：函数、类、常量。下划线开头的也收 —— X1 实测
    284 个名字里 41 个下划线名被外部引用，**「私有」这个约定保护不了任何人**。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs, classes, consts = [], [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts.append(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            consts.append(node.target.id)
    return {"functions": sorted(funcs), "classes": sorted(classes),
            "constants": sorted(consts)}


def config_instance_surface() -> dict:
    """`Config` 类：方法，以及 `self.x = ...` 里**在 `__init__` 外**赋的那些
    （`__init__` 里的绝大多数是配置项默认值，契约是键名不是属性名 —— 见自查③）。"""
    tree = ast.parse(LAYER["config"].read_text(encoding="utf-8"))
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "Config"), None)
    if cls is None:
        return {"methods": [], "init_keys": [], "other_attrs": []}
    methods = sorted(n.name for n in cls.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    init_keys, other = set(), set()
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bucket = init_keys if n.name == "__init__" else other
            for sub in ast.walk(n):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Attribute) \
                                and getattr(t.value, "id", None) == "self":
                            bucket.add(t.attr)
    return {"methods": methods, "init_keys": sorted(init_keys),
            "other_attrs": sorted(other - init_keys)}


def importers() -> dict:
    """谁 import 了 X3 的模块，以及从里面取了哪些名字。"""
    by_module: dict[str, dict[str, set]] = {
        m: {"files": set(), "names": Counter()} for m in LAYER}
    alias_hits: dict[str, Counter] = defaultdict(Counter)

    for path in live_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in {p.relative_to(ROOT).as_posix() for p in LAYER.values()}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        # 模块别名 -> 模块名（`import config` / `import config as cfg`）
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in LAYER:
                        aliases[a.asname or a.name.split(".")[0]] = a.name
                        by_module[a.name]["files"].add(rel)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in LAYER:
                    by_module[mod]["files"].add(rel)
                    for a in node.names:
                        by_module[mod]["names"][a.name] += 1
        # `config.X` 这种取名
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                mod = aliases.get(node.value.id)
                if mod:
                    by_module[mod]["names"][node.attr] += 1
                    alias_hits[mod][rel] += 1
    return {m: {"files": sorted(v["files"]),
                "names": dict(sorted(v["names"].items()))}
            for m, v in by_module.items()}


def build() -> dict:
    surfaces = {m: module_surface(p) for m, p in LAYER.items()}
    used = importers()
    inst = config_instance_surface()

    # 「被外部真的用到的模块级名字」= 定义面 ∩ 使用面
    contract = {}
    for m, s in surfaces.items():
        defined = set(s["functions"]) | set(s["classes"]) | set(s["constants"])
        contract[m] = sorted(defined & set(used[m]["names"]))

    return {
        "loc": {m: len(p.read_text(encoding="utf-8").splitlines())
                for m, p in LAYER.items()},
        "surface": surfaces,
        "config_instance": inst,
        "external_use": used,
        "contract": contract,
        "contract_total": sum(len(v) for v in contract.values()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    data = build()

    total_loc = sum(data["loc"].values())
    print(f"X3 层行数合计 {total_loc}")
    for m, n in data["loc"].items():
        print(f"  {m:32s} {n:5d}")
    print()
    for m in LAYER:
        s = data["surface"][m]
        print(f"{m}: 定义 函数 {len(s['functions'])} / 类 {len(s['classes'])} / "
              f"常量 {len(s['constants'])}  ⇒ 外部真用到 {len(data['contract'][m])}"
              f"（{len(data['external_use'][m]['files'])} 个文件 import）")
    inst = data["config_instance"]
    print(f"\nConfig 实例：方法 {len(inst['methods'])} / "
          f"__init__ 里的配置项 {len(inst['init_keys'])} / "
          f"其它属性 {len(inst['other_attrs'])}")
    print(f"\n契约名合计 {data['contract_total']}")

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                  sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n已写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
