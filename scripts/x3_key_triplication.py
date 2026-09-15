# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X3 盘点：**同一批配置键，在 `config.py` 里被拼写了几遍。**

`Config` 三个巨型方法占了 2071 行里的 1468 行（71%）：
`__init__`（默认值）/ `load_config`（从 json 读）/ `_do_save_config`（写回 json）。
它们讲的是同一张键表 —— 这份脚本量的是**它们讲得一不一致**。

⭐ 为什么这个数是 X3 的靶心：DoD 第 9 条②要求 X3 关档时名下产品代码**净减**，
而「三份平行拼写」是这一层唯一一处结构性冗余（其余都是真逻辑）。
⚠ 但 LOC 不是唯一的理由，甚至不是主要理由 —— **三份手写的键表会漂**：
只在两份里出现的键，就是一条「存得进去读不出来」或「读得出来存不下去」的静默缺陷。
⇒ 所以这份脚本的第一产出是**差集**，第二产出才是行数。

⚠ 量法自查：`load_config` 里还有大量**非机械**的行（迁移、修复、条件分支），
不能把整段都算成「可折叠」。只有形如
`self.X = config_data.get("X", self.X)` 且键名与属性名**同名**的那些才算。

用法：`python scripts/x3_key_triplication.py`
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "config.py"


def _cls() -> ast.ClassDef:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    return next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "Config")


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    return next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def init_defaults(cls) -> dict[str, str]:
    """`__init__` 里 `self.X = <literal>` 的那些（X -> 字面值的源码）。"""
    out = {}
    for node in ast.walk(_method(cls, "__init__")):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Attribute) and getattr(t.value, "id", None) == "self":
                out[t.attr] = ast.unparse(node.value)
    return out


def mechanical_loads(cls) -> dict[str, str]:
    """`self.X = config_data.get("K", self.X)` ⇒ {X: K}。只收这一种形状。"""
    out = {}
    for node in ast.walk(_method(cls, "load_config")):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        t, v = node.targets[0], node.value
        if not (isinstance(t, ast.Attribute)
                and getattr(t.value, "id", None) == "self"):
            continue
        if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                and v.func.attr == "get" and len(v.args) == 2):
            continue
        key, dflt = v.args
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        # 兜底必须是 self.<同一个属性>，否则就不是「机械读」
        if not (isinstance(dflt, ast.Attribute)
                and getattr(dflt.value, "id", None) == "self"
                and dflt.attr == t.attr):
            continue
        out[t.attr] = key.value
    return out


def mechanical_saves(cls) -> dict[str, str]:
    """`_do_save_config` 里 `"K": self.X` 这种字典项 ⇒ {X: K}。"""
    out = {}
    for node in ast.walk(_method(cls, "_do_save_config")):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if isinstance(v, ast.Attribute) and getattr(v.value, "id", None) == "self":
                out[v.attr] = k.value
    return out


def main() -> int:
    cls = _cls()
    d, ld, sv = init_defaults(cls), mechanical_loads(cls), mechanical_saves(cls)
    body = SRC.read_text(encoding="utf-8").splitlines()

    def span(name):
        m = _method(cls, name)
        return m.end_lineno - m.lineno + 1

    print(f"config.py 共 {len(body)} 行；三个巨型方法占 "
          f"{span('__init__') + span('load_config') + span('_do_save_config')} 行")
    print(f"  __init__          {span('__init__'):5d} 行 · 默认值 {len(d)} 个")
    print(f"  load_config       {span('load_config'):5d} 行 · **机械读** {len(ld)} 条")
    print(f"  _do_save_config   {span('_do_save_config'):5d} 行 · **机械写** {len(sv)} 条")

    all_attrs = set(d) | set(ld) | set(sv)
    three = set(d) & set(ld) & set(sv)
    print(f"\n涉及属性合计 {len(all_attrs)}；**三处都有** {len(three)}")

    # ⭐ 真正值钱的是差集：只在两处出现的键 = 一条静默的单向缺陷
    load_no_save = sorted(set(ld) - set(sv))
    save_no_load = sorted(set(sv) - set(ld))
    no_default = sorted((set(ld) | set(sv)) - set(d))
    print(f"\n⚠ 读得出来但**存不回去** {len(load_no_save)} 个：")
    print("   " + (", ".join(load_no_save) or "（无）"))
    print(f"\n⚠ 存得进去但**读不出来** {len(save_no_load)} 个：")
    print("   " + (", ".join(save_no_load) or "（无）"))
    print(f"\n⚠ 有读/写但 `__init__` 里**没有默认值** {len(no_default)} 个：")
    print("   " + (", ".join(no_default) or "（无）"))

    # 键名与属性名不同名的（折叠时必须逐个保住）
    renamed = sorted(k for k in three if ld[k] != k or sv[k] != k)
    print(f"\n键名与属性名**不同名** {len(renamed)} 个（折叠时逐个保住）：")
    print("   " + (", ".join(f"{k}→{ld.get(k)}/{sv.get(k)}" for k in renamed) or "（无）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
