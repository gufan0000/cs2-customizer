# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X4（启动链路）的**开档盘点**：启动顺序、外部效应、以及「写在注释里的顺序契约」。

## 为什么这份和 X1/X3 那两份又不是同一种东西

X1 量的是「谁在 `win.xxx` 上取名字」（一个类的方法与属性面）；
X3 量的是「谁 import 了这个模块的哪个名字」（模块级函数面）。
**X4 两样都不是** —— `main_widget` 几乎没有人 import（实测见 `--json` 的 `importers`），
它的契约不是「名字」，是**顺序**和**副作用**：

  · `_apply_display_hardening` 必须在 `QApplication()` 之前，晚一行就完全不生效；
  · `apply_font_scale` 必须在 `MainWindow()` 之前；
  · 单实例守卫必须在常驻度量埋点之前，否则第二个进程会往第一个进程的日志里
    插一段伪造会话；
  · …

⭐⭐⭐ **而这些约束现在只以「注释」的形式存在。**
一条被判据守着的顺序契约，和一条只写在注释里的顺序契约，
**在源码上长得一模一样** —— 两者都是一行中文加一行代码。
这份盘点的全部意义就是把这两者分开：先把契约逐条列出来（本脚本），
再逐条做破坏验证（`x4_order_breaker.py`），用「破坏之后有没有判据变红」定性。

## 怎么量的（三条自查）

⚠ ① **顺序契约只认「实际会失效」的那种**，不认「读起来像建议」的。
   判定靠人（本脚本只负责把候选行捞出来并标注），**不靠关键字自动定性** ——
   `必须` 这两个字在这个文件里出现 20 次，其中多数是「必须吞掉异常」这类
   与顺序无关的纪律。⭐ 自动定性会给出一个看起来很饱满、而实际掺了水的分母。
⚠ ② **外部效应要按「什么时候发生」分三档**：import 期 / `main()` 同步段 /
   `QTimer` 与线程的异步段。⭐ 同一个 `open(..., "w")`，在 import 期是
   「打包脚本一 collect_submodules 就会触发」，在异步段只是普通的后台写盘 ——
   **同一段代码，危险程度差三个数量级，而 grep 读数完全相同**（UP-004 那条注释
   记的正是这件事：日志清理放进 `Logger.__init__` 会被打包机触发并删掉历史日志）。
⚠ ③ **排掉 `.build/` / `_backup` / `_archive` / `.claude/worktrees/`**（X3 同款）。

用法：
    python scripts/x4_boot_contract.py            # 人读
    python scripts/x4_boot_contract.py --json     # 机器读
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

#: X4 层的文件。splash 没有独立模块，它整段住在 `main_widget.py` 里。
LAYER = {
    "main_widget": ROOT / "main_widget.py",
    "background_loader": ROOT / "background_loader.py",
}

#: 扫「谁 import 了 X4」时要排掉的目录（X3 同款；worktree 是别的会话或回退验证的副本）。
EXCLUDE_PARTS = (".build", "_backup", "_archive", "output", "worktrees", "__pycache__")

#: ⭐ **顺序契约的分母由人给，不由关键字给**（见模块头自查①）。
#: 每条 = (键, 注释所在行, 一句话说清「谁必须在谁之前」, 违反后的现象)。
#: ⚠ 加一条之前先把那一行打开读一遍 —— RN-588 那条。
ORDER_CONTRACTS = [
    ("boot_t0_before_imports", 10,
     "`_BOOT_T0 = perf_counter()` 必须在一切重 import 之前",
     "启动相位计时的零点被算晚，所有相位读数整体偏小，而报表照样出得来"),
    ("faulthandler_early", 61,
     "`_enable_faulthandler()` 必须先于一切重 import",
     "导入期/启动期的原生崩溃没有栈，崩了只剩一个静默退出"),
    ("compact_before_append", 101,
     "`_compact_native_crash_log()` 必须在以 append 打开崩溃日志句柄**之前**",
     "压缩写的是临时文件再 os.replace，句柄已开则替换掉的是另一个 inode，"
     "此后整轮的崩溃记录写进一个没人读的旧文件"),
    ("hardening_before_qapp", 1124,
     "`_apply_display_hardening()` 必须在 `QApplication()` 构造之前",
     "高DPI取整策略与软件渲染属性只在构造前设置才生效 ⇒ "
     "上一轮渲染崩溃后的自愈**整条失效**，用户卡在崩溃循环里"),
    ("font_scale_before_window", 1138,
     "`apply_font_scale()` 必须在 `MainWindow()` 构建与主题首次应用之前",
     "字号缩放设置对已建好的控件不生效，界面按默认字号画出来"),
    ("monitors_after_single_instance", 1176,
     "常驻度量埋点必须在单实例守卫**之后**",
     "用户重复双击图标时，第二个进程会往正在运行那个实例的当天日志里"
     "插一段伪造会话，`ui_perf_probe` 按横幅切会话 ⇒ 真实长会话被从中间截断"),
    ("monitors_before_window", 1180,
     "常驻度量埋点必须在 `MainWindow()` 构建**之前**",
     "主窗构建那 1.9~5.0 秒是启动期最大的一段主线程停顿，"
     "探测器晚起就把它整段漏掉（度量报表照常出，只是少了最大的那一块）"),
    ("idle_watcher_before_preload", 1195,
     "`start_idle_watcher()` 必须在页面预载开始之前",
     "预载退化为无门控 ⇒ 卡顿治理整个失效，⭐ 而现象和「没改过」一模一样"),
    ("log_maintenance_explicit", 1218,
     "过期日志清理必须**显式调用**，不许放进 `Logger.__init__`",
     "变成 import 副作用 ⇒ 打包脚本 collect_submodules(\"core\") 会触发它，"
     "删掉打包机上的历史日志"),
    ("known_pages_within_pool", 1540,
     "`top_pages(known_pages=...)` 必须限定在 `PRELOAD_POOL` 内",
     "频次榜含 music 等「构造即起线程/设备」的页 ⇒ 静默预载会打开音频设备"),
]


# ----------------------------------------------------------------- 外部效应

#: 外部效应的判定表：调用名 → 档。⭐ 只认调用，不认字符串里出现过这个词。
EFFECT_CALLS = {
    "open": "写/读文件",
    "os.replace": "写文件",
    "os.remove": "写文件",
    "os.makedirs": "写文件",
    "Thread": "起线程",
    "QTimer.singleShot": "排定时器",
    "start": "起线程/服务",
    "QApplication": "建 Qt 应用",
    "sys.exit": "退进程",
    "freeze_support": "多进程",
}


def _dotted(node: ast.AST) -> str:
    """把 `a.b.c(...)` 的被调方还原成 'a.b.c'；取不到就返回 ''。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _phase_of(lineno: int, main_node: ast.FunctionDef | None,
              async_lines: set[int]) -> str:
    """这一行的效应发生在哪一档（见模块头自查②）。"""
    if lineno in async_lines:
        return "异步段"
    if main_node is not None and main_node.lineno <= lineno <= main_node.end_lineno:
        return "main() 同步段"
    return "import 期"


def scan_effects(path: Path) -> list[dict]:
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines()

    main_node = next(
        (n for n in tree.body
         if isinstance(n, ast.FunctionDef) and n.name == "main"), None)

    # 异步段 = 被 QTimer.singleShot / Thread(target=) / Signal.connect 引用到的
    # 那些函数的函数体。⭐ 这一步不做就会把「后台线程里的写盘」误报成 import 期。
    async_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name.endswith("singleShot") and len(node.args) >= 2:
            async_names.add(_dotted(node.args[1]))
        if name.endswith(".connect") and node.args:
            async_names.add(_dotted(node.args[0]))
        if name in ("Thread", "threading.Thread"):
            for kw in node.keywords:
                if kw.arg == "target":
                    async_names.add(_dotted(kw.value))

    async_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in async_names:
            async_lines.update(range(node.lineno, node.end_lineno + 1))

    out: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        kind = None
        for needle, label in EFFECT_CALLS.items():
            if name == needle or name.endswith("." + needle):
                kind = label
                break
        if kind is None:
            continue
        out.append({
            "line": node.lineno,
            "call": name,
            "kind": kind,
            "phase": _phase_of(node.lineno, main_node, async_lines),
            "src": lines[node.lineno - 1].strip()[:90],
        })
    return sorted(out, key=lambda d: d["line"])


# ----------------------------------------------------------------- 谁 import 它

def scan_importers() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {k: [] for k in LAYER}
    for p in ROOT.rglob("*.py"):
        if any(part in EXCLUDE_PARTS for part in p.parts):
            continue
        if p.resolve() in {v.resolve() for v in LAYER.values()}:
            continue
        try:
            tree = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                if m in hits:
                    hits[m].append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return {k: sorted(set(v)) for k, v in hits.items()}


# ----------------------------------------- 顺序契约：有没有判据**提到**过它

#: 只是**下限**：判据没提到这个符号，就一定抓不住它；提到了也不代表守着顺序。
#: ⭐ 真正的定性靠 `x4_order_breaker.py` 的破坏验证，本栏只用来决定先破坏哪几条。
CONTRACT_SYMBOLS = {
    "boot_t0_before_imports": ["_BOOT_T0"],
    "faulthandler_early": ["_enable_faulthandler", "faulthandler"],
    "compact_before_append": ["_compact_native_crash_log"],
    "hardening_before_qapp": ["_apply_display_hardening"],
    "font_scale_before_window": ["apply_font_scale"],
    "monitors_after_single_instance": ["start_jank_monitor", "ensure_single_instance"],
    "monitors_before_window": ["start_jank_monitor", "start_mem_monitor"],
    "idle_watcher_before_preload": ["start_idle_watcher"],
    "log_maintenance_explicit": ["start_maintenance"],
    "known_pages_within_pool": ["known_pages", "PRELOAD_POOL"],
}


def scan_judges() -> dict[str, list[str]]:
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    texts = {p.name: io.open(p, encoding="utf-8", errors="replace").read() for p in tests}
    out: dict[str, list[str]] = {}
    for key, syms in CONTRACT_SYMBOLS.items():
        out[key] = sorted(
            name for name, text in texts.items()
            if any(s in text for s in syms)
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict = {"layer": {}, "contracts": [], "importers": scan_importers()}

    for name, path in LAYER.items():
        src = io.open(path, encoding="utf-8").read()
        effects = scan_effects(path)
        report["layer"][name] = {
            "lines": len(src.splitlines()),
            "effects": effects,
        }

    judges = scan_judges()
    for key, line, what, harm in ORDER_CONTRACTS:
        report["contracts"].append({
            "key": key, "line": line, "what": what, "harm": harm,
            "judges_mentioning": judges[key],
        })

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    total = sum(v["lines"] for v in report["layer"].values())
    print(f"\n{'='*74}\nX4 · 启动链路 —— 开档盘点\n{'='*74}")
    print(f"层内行数：{total}")
    for name, v in report["layer"].items():
        print(f"  · {name:<20} {v['lines']:>5} 行")

    print(f"\n谁 import 了这一层（排除 {', '.join(EXCLUDE_PARTS)}）：")
    for name, who in report["importers"].items():
        print(f"  · {name:<20} {len(who):>3} 个文件"
              + (f"：{', '.join(who[:6])}" if who else "（没有人，它是入口）"))

    print("\n外部效应（按档分）：")
    for name, v in report["layer"].items():
        by_phase: dict[str, int] = {}
        for e in v["effects"]:
            by_phase[e["phase"]] = by_phase.get(e["phase"], 0) + 1
        print(f"  · {name}: " + " / ".join(f"{k} {n}" for k, n in sorted(by_phase.items())))
    print("\n  ⚠ import 期的效应逐条列出（这一档最贵，见模块头自查②）：")
    for name, v in report["layer"].items():
        for e in v["effects"]:
            if e["phase"] == "import 期":
                print(f"    {name}:{e['line']:<5} [{e['kind']}] {e['src']}")

    print(f"\n顺序契约 {len(ORDER_CONTRACTS)} 条 —— 有多少条有判据**提到过**："
          "（⭐ 只是下限，定性靠破坏验证）")
    for c in report["contracts"]:
        n = len(c["judges_mentioning"])
        flag = "  " if n else "⛔"
        print(f"  {flag} {c['key']:<34} 行{c['line']:<6} 判据提到 {n:>2} 个")
        if n:
            print(f"       {', '.join(c['judges_mentioning'][:4])}")
    zero = [c["key"] for c in report["contracts"] if not c["judges_mentioning"]]
    print(f"\n  ⛔ **一个判据都没提到**的：{len(zero)} / {len(ORDER_CONTRACTS)}"
          + (f" —— {', '.join(zero)}" if zero else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
