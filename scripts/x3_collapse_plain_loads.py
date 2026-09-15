# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X3 关档减重：把 `load_config` 里**连续成片**的机械读折叠成一次调用。

## 它折叠什么，以及为什么这样是安全的

只认这一种形状，且**键名与属性名必须同名**（批 84 盘点实测：188 条机械读里
不同名的是 **0** 条）：

    self.X = config_data.get("X", self.X)

它与 `if "X" in config_data: setattr(self, "X", config_data["X"])` **逐字等价** ——
`.get(k, 默认)` 在键存在时返回存下来的值（哪怕它是 `None`），键不存在时返回默认。

⛔ **只折叠「连续的、同一层级的、同一个父节点下的」那些**。
⭐⭐⭐ 这一条是要害：`load_config` 里机械读和**非机械逻辑**（迁移、归一化、
条件分支）是交错的，而其中一些非机械逻辑会读刚赋过的属性。
把所有机械读提到一处会改变它们相对于那些逻辑的顺序 ——
**而顺序变了之后，行为是不是还一样，没有任何东西会告诉我。**
⇒ 按「连续片段」折叠，片段之间的相对顺序一个字都不动。

## 怎么验它没改行为

`scripts/x3_save_load_roundtrip.py` 两臂（身份往返 + 改一个值）跑改前改后各一遍，
两次输出必须**逐字相同**。⛔ 只跑判据不够：判据覆盖不到 236 个配置项里的大多数。

用法：`python scripts/x3_collapse_plain_loads.py [--apply]`
"""
from __future__ import annotations

import argparse
import ast
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "config.py"
MIN_RUN = 3          # 少于这么多条就不折叠（折了反而不省行，还更难读）
PER_LINE = 6         # 一行放几个键名


def _is_plain_load(node) -> str | None:
    """是 `self.X = config_data.get("X", self.X)` 就返回 X，否则 None。"""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
        return None
    t, v = node.targets[0], node.value
    if not (isinstance(t, ast.Attribute) and getattr(t.value, "id", None) == "self"):
        return None
    if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
            and v.func.attr == "get" and len(v.args) == 2
            and isinstance(v.func.value, ast.Name)
            and v.func.value.id == "config_data"):
        return None
    key, dflt = v.args
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        return None
    if not (isinstance(dflt, ast.Attribute)
            and getattr(dflt.value, "id", None) == "self"
            and dflt.attr == t.attr):
        return None
    return t.attr if key.value == t.attr else None   # ⛔ 不同名的不折


def _runs(body: list) -> list[tuple[int, int, list[str]]]:
    """同一个 body 里连续的机械读片段 ⇒ [(起 idx, 止 idx, 键名)]。

    ⛔ **两条语句之间只要隔着东西（空行或注释），就断开。**
    ⭐⭐⭐ 这一条不是洁癖：`load_config` 里那 182 条机械读是按
    「基础设置 / 枪声相关设置 / 击杀图标设置 / ……」分段的，
    **段落注释是唯一告诉读者这一片在讲什么的东西**。
    不断开的话，第一段就会把 63 行里的十几条段落注释一起吃掉 ——
    ⚠ **那就成了「为了行数删可读性」，而那正是这条 DoD 条款明确不要的东西**
    （总纲：不许逼出「为了行数删功能」）。
    ⇒ 按段折叠，注释原样留在每段上面。
    """
    out, cur, prev_end = [], [], None
    for i, node in enumerate(body):
        key = _is_plain_load(node)
        broken = prev_end is not None and node.lineno > prev_end + 1
        if key is not None and not broken:
            cur.append((i, key))
            prev_end = node.end_lineno
            continue
        if len(cur) >= MIN_RUN:
            out.append((cur[0][0], cur[-1][0], [k for _, k in cur]))
        cur = [(i, key)] if key is not None else []
        prev_end = node.end_lineno if key is not None else None
    if len(cur) >= MIN_RUN:
        out.append((cur[0][0], cur[-1][0], [k for _, k in cur]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    raw = io.open(SRC, encoding="utf-8", newline="").read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.replace(eol, "\n").split("\n")
    tree = ast.parse(raw.replace(eol, "\n"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Config")
    fn = next(n for n in cls.body
              if isinstance(n, ast.FunctionDef) and n.name == "load_config")

    # 在 load_config 内部的**每一个** body 上找连续片段
    edits = []          # (起行, 止行, 缩进, 键名)
    for node in ast.walk(fn):
        for attr in ("body", "orelse", "finalbody"):
            body = getattr(node, attr, None)
            if not isinstance(body, list):
                continue
            for i0, i1, keys in _runs(body):
                a, b = body[i0], body[i1]
                indent = " " * a.col_offset
                edits.append((a.lineno, b.end_lineno, indent, keys))

    edits.sort(key=lambda e: e[0])
    total = sum(len(k) for *_, k in edits)
    saved = 0
    for a, b, indent, keys in edits:
        packed = []
        for i in range(0, len(keys), PER_LINE):
            packed.append(", ".join(f'"{k}"' for k in keys[i:i + PER_LINE]))
        new = [f"{indent}self._load_plain(config_data,"]
        for j, chunk in enumerate(packed):
            # ⛔⛔ 续行末尾那个逗号**不能省**。第一版写的是 `tail = ")" if 末行 else ""`，
            #   于是续行之间没有逗号 —— 而 Python 会把相邻的字符串字面量**悄悄拼起来**：
            #   `"kill_icon_enabled"` + `"debug_mode"` ⇒ `"kill_icon_enableddebug_mode"`。
            # ⭐⭐⭐ 语法合法、`ruff` 全绿、判据也全绿，而**16 个配置项从此读不回来**。
            #   逮住它的是 `x3_save_load_roundtrip.py` 的第二臂（改一个值再读回来）——
            #   ⭐⭐ **一个「少了个逗号」的错误，在这门语言里不是语法错误，是语义错误。**
            tail = ")" if j == len(packed) - 1 else ","
            new.append(f"{indent}                 {chunk}{tail}")
        saved += (b - a + 1) - len(new)
    print(f"连续片段 {len(edits)} 段，覆盖机械读 {total} 条；预计省 **{saved}** 行")
    for a, b, _, keys in edits[:6]:
        print(f"  行 {a}~{b}：{len(keys)} 条 —— {keys[0]} … {keys[-1]}")
    if len(edits) > 6:
        print(f"  …… 另 {len(edits) - 6} 段")

    if not args.apply:
        print("\n（干跑。加 --apply 才落盘）")
        return 0

    for a, b, indent, keys in sorted(edits, key=lambda e: e[0], reverse=True):
        packed = []
        for i in range(0, len(keys), PER_LINE):
            packed.append(", ".join(f'"{k}"' for k in keys[i:i + PER_LINE]))
        new = [f"{indent}self._load_plain(config_data,"]
        for j, chunk in enumerate(packed):
            # ⛔⛔ 续行末尾那个逗号**不能省**。第一版写的是 `tail = ")" if 末行 else ""`，
            #   于是续行之间没有逗号 —— 而 Python 会把相邻的字符串字面量**悄悄拼起来**：
            #   `"kill_icon_enabled"` + `"debug_mode"` ⇒ `"kill_icon_enableddebug_mode"`。
            # ⭐⭐⭐ 语法合法、`ruff` 全绿、判据也全绿，而**16 个配置项从此读不回来**。
            #   逮住它的是 `x3_save_load_roundtrip.py` 的第二臂（改一个值再读回来）——
            #   ⭐⭐ **一个「少了个逗号」的错误，在这门语言里不是语法错误，是语义错误。**
            tail = ")" if j == len(packed) - 1 else ","
            new.append(f"{indent}                 {chunk}{tail}")
        lines[a - 1:b] = new
    io.open(SRC, "w", encoding="utf-8", newline="").write(
        "\n".join(lines).replace("\n", eol))
    print(f"\n✅ 已折叠 {len(edits)} 段 / {total} 条机械读")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
