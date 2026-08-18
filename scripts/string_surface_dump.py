# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""字符串引用面：**静态 import 图看不见的那半个仓库**。

删代码之前要回答的问题是"还有谁会用到它"。`import` 图能回答一半，
**另一半是靠字符串连起来的**，它一条边都画不出来：

    config.getattr("kill_icon_enabled")      设置键
    win.show_page("crosshair")               页面 id
    btn.setObjectName("modeToggleButton")    QSS 选择器靠它选中
    PAGE_HELP_TEXTS["kill_sound"]            帮助文案键
    search_index.json 里的用户说法             搜到了就要跳得过去
    alias fp_recoil_on                       CFG 里的别名（**改名即失效**）

这些名字被删/改名时，**没有任何东西会报错**——功能只是安静地不再工作。
本仓的历史事故基本都长这样：QSS 规则从写下那天起就没生效过、
`get_page_icon()` 查不到静默返回空图标、`data:` URI 的图永远不显示。

所以「删除安全梯」的 L1 要求三源一致：import 图说没人用、
vulture 说没人用、**再加这里说没人用**。三个都说没有，才敢直接删。

用法：
    python scripts/string_surface_dump.py --query kill_icon_enabled   # 谁提到过它
    python scripts/string_surface_dump.py --surfaces                  # 各类引用面概览
    python scripts/string_surface_dump.py --dump out.json             # 全量落盘
退出码：0=正常；--query 找不到任何引用时也返回 0（"没人用"是有效答案，不是错误）。
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _tracked(*patterns: str) -> list[Path]:
    """只看 **git 跟踪** 的文件。

    ⚠ 不能用 rglob：`.build/` 下压着十几份历史发布快照。2026-08-17 被坑过一次——
    拿 grep 查「某文案改没改」，活代码明明改了，却被 `.build/` 里的旧副本
    报成"还没改"。**在这个仓库里，扫全仓等于扫历史。**
    """
    out = subprocess.run(["git", "ls-files", *patterns],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise SystemExit("拿不到 git 跟踪清单：本脚本拒绝退化成扫全仓（会扫进 .build 的历史快照）")
    return [ROOT / line for line in out.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------- 采集

def _collect_python(index: dict, surfaces: dict) -> None:
    for path in _tracked("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            # ① 所有字符串字面量 —— 全量引用面的底座
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                # 长文案不进索引：它们是段落不是标识符，进来只会把索引撑爆
                if 0 < len(text) <= 80:
                    index[text].append(f"{rel}:{node.lineno}")
                continue

            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            attr = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else None)
            first = node.args[0] if node.args else None
            literal = first.value if (isinstance(first, ast.Constant)
                                      and isinstance(first.value, str)) else None

            # ② objectName —— QSS 靠它选中控件，改名 = 样式静默失效
            if attr == "setObjectName" and literal:
                surfaces["objectName"][literal].append(f"{rel}:{node.lineno}")
            # ③ 动态取设置键 —— getattr(config, "xxx") 这类 import 图完全看不见
            elif attr in ("getattr", "hasattr", "setattr") or (
                    isinstance(fn, ast.Name) and fn.id in ("getattr", "hasattr", "setattr")):
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                        and isinstance(node.args[1].value, str):
                    surfaces["动态属性名"][node.args[1].value].append(f"{rel}:{node.lineno}")
            # ④ 切页 —— 页面 id 的主要用法
            elif attr in ("show_page", "is_page_loaded") and literal:
                surfaces["页面id"][literal].append(f"{rel}:{node.lineno}")

        # ⑤ config.xxx 的属性访问 = 设置键（本仓设置是 config 上的属性）
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "config":
                surfaces["设置键"][node.attr].append(f"{rel}:{node.lineno}")


def _collect_json(index: dict, surfaces: dict) -> None:
    for path in _tracked("*.json"):
        rel = path.relative_to(ROOT).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        def walk(obj):
            if isinstance(obj, str):
                if 0 < len(obj) <= 80:
                    index[obj].append(f"{rel}")
                    if "search_index" in rel:
                        surfaces["搜索词条"][obj].append(rel)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    walk(k)
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(data)


def build() -> tuple[dict, dict]:
    index: dict[str, list[str]] = defaultdict(list)
    surfaces: dict[str, dict[str, list[str]]] = {
        name: defaultdict(list) for name in
        ("objectName", "设置键", "动态属性名", "页面id", "搜索词条")
    }
    _collect_python(index, surfaces)
    _collect_json(index, surfaces)
    return index, surfaces


# ---------------------------------------------------------------- 出口

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="查一个名字：谁提到过它")
    ap.add_argument("--surfaces", action="store_true", help="各类引用面概览")
    ap.add_argument("--dump", help="全量落盘为 JSON")
    args = ap.parse_args()

    index, surfaces = build()

    if args.query:
        name = args.query
        hits = index.get(name, [])
        print(f"== 「{name}」的字符串引用面 ==")
        if not hits:
            print("  （字符串层零引用）")
            print("\n  ⚠ 这只是三源之一。**别只凭这一条就删** —— 还要 import 图与 vulture "
                  "也说没人用（删除安全梯 L1）。\n"
                  "  另：拼接出来的名字（f\"{prefix}_enabled\"）本脚本看不见，"
                  "那种情况一律降到 L2 人工追。")
        else:
            for h in hits:
                print(f"  {h}")
        for cat, table in surfaces.items():
            if name in table:
                print(f"  [{cat}] " + ", ".join(table[name][:6]))
        return 0

    if args.surfaces:
        print("== 引用面概览 ==")
        for cat, table in surfaces.items():
            print(f"  {cat:<10} {len(table):>5} 个不同名字")
        print(f"  {'字符串总数':<10} {len(index):>5} 个不同字面量")
        return 0

    if args.dump:
        out = Path(args.dump)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "strings": {k: v for k, v in index.items()},
            "surfaces": {c: {k: v for k, v in t.items()} for c, t in surfaces.items()},
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"落盘 {out}（{len(index)} 个字面量）")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
