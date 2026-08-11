#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量四个武器音效页的方法重复度（UP-057 第二阶段用）。

为什么要脚本：登记册里"四个音效页 90% 雷同"是**估计值**，实测下来是 35%。
估计值会把工作量和收益都算错，所以每次动这块之前重新量一遍。

做法：AST 取出每个类的方法体源码，两两做 difflib 相似度。
同时报**结构相似度**（把标识符抹掉只留语法骨架）——两个方法可能逻辑一样、
只是变量名和配置键不同，那种才是真正能抽的。
"""
from __future__ import annotations

import argparse
import ast
import difflib
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "pages"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_FILES = [
    "kill_sound_page.py", "kill_voice_page.py",
    "switch_weapon_page.py", "reload_sound_page.py",
    "death_sound_page.py", "special_sound_page.py",
]


def _methods(path: Path) -> dict[str, tuple[str, int]]:
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = "\n".join(lines[item.lineno - 1: item.end_lineno])
                out[item.name] = (body, item.end_lineno - item.lineno + 1)
    return out


def _skeleton(src: str) -> str:
    """抹掉标识符和字面量，只留语法骨架——两段代码"结构一样、名字不同"时这个才高。"""
    try:
        tree = ast.parse(src.strip())
    except SyntaxError:
        try:
            tree = ast.parse("class _C:\n" + "\n".join("    " + ln for ln in src.splitlines()))
        except SyntaxError:
            return src
    parts = []
    for node in ast.walk(tree):
        parts.append(type(node).__name__)
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lines", type=int, default=20)
    ap.add_argument("--min-ratio", type=float, default=0.6)
    args = ap.parse_args()

    tables = {name: _methods(PAGES / name) for name in DEFAULT_FILES
              if (PAGES / name).exists()}

    everywhere: dict[str, list[tuple[str, str, int]]] = {}
    for fname, methods in tables.items():
        for mname, (body, n) in methods.items():
            if n >= args.min_lines:
                everywhere.setdefault(mname, []).append((fname, body, n))

    print(f"{'方法名':<28}{'出现页数':>8}{'平均行数':>9}{'文本相似':>9}{'结构相似':>9}")
    rows = []
    for mname, occ in sorted(everywhere.items()):
        if len(occ) < 2:
            continue
        avg = sum(n for _, _, n in occ) / len(occ)
        text_ratios, struct_ratios = [], []
        for (_, a, _), (_, b, _) in combinations(occ, 2):
            text_ratios.append(difflib.SequenceMatcher(None, a, b).ratio())
            struct_ratios.append(
                difflib.SequenceMatcher(None, _skeleton(a), _skeleton(b)).ratio())
        t = sum(text_ratios) / len(text_ratios)
        s = sum(struct_ratios) / len(struct_ratios)
        if max(t, s) < args.min_ratio:
            continue
        rows.append((mname, len(occ), avg, t, s))

    rows.sort(key=lambda r: -(r[1] * r[2] * r[2]))
    for mname, cnt, avg, t, s in rows:
        print(f"{mname:<28}{cnt:>8}{avg:>9.1f}{t:>8.0%}{s:>9.0%}")

    total = sum(int(avg) * (cnt - 1) for _, cnt, avg, _, _ in rows)
    print(f"\n若全部抽到基类，理论可省 ≈ {total} 行（按「每处平均行数 × (处数-1)」估）")
    print("⚠ 这是**上限**，不是可达值：凡是碰风格目录的方法都受制于四页不统一的风格模型。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
