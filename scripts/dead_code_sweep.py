# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""死码三源扫描（DoD 第 9 条③ / 总纲注三里那个「还款工具」）。

总纲把三笔 LOC 欠账的到期批次钉在「**死码三源扫描那一批，也就是还款工具到货
的那一批**」，而在批 80 之前**那件工具从来没被造出来** —— 到期日钉在一件没人
着手的事情上。这个文件就是把它造出来。

⭐⭐⭐ 立账时没有人问过一句：**这件工具能不能产出足够的还款额。**
本脚本先回答那个问题（出数），再谈账怎么处理。

## 三源（此前无定义，这里把它定下来）

| 源 | 问的是什么 | 怎么判 |
|---|---|---|
| ① **零引用的名字** | 模块级的函数 / 类 / 常量，定义了但全仓没人用 | AST 取定义，再全仓数「非定义处的出现次数」 |
| ② **零引用的模块** | 整个 `.py` 从来没被 import 过 | AST 取所有 import 目标，比对产品文件清单 |
| ③ **死参数** | 形参进来了，函数体里一次都没读 | AST：形参名不在函数体的 `Name` / `Attribute` 里 |

⛔ **三源都只出「确证项」的候选，不出结论。** 动态取用（`getattr`、
配置里写字符串、QSS 里按名字选、`__all__` 再导出）这四条路 AST 看不见 ——
所以本脚本的产出是**待核实清单**，逐条开文件确认之前不许删。
⭐ 本仓红线 2 的同款：查「有没有 X」要用比它更硬的手段，而这里**没有**更硬的手段，
   于是它只能是怀疑清单。

## ⭐⭐⭐ 实测产出率（批 80 逐条核实，**下次用它之前先读这一段**）

源② 报了 5 个零引用模块共 **998 行**，逐个开文件核下来只有 **248 行（25%）**能还：

| 模块 | 行 | 核实结果 |
|---|---|---|
| `core/audio/audio_import_wizard.py` | 248 | ✅ **真死码** —— 功能泛化搬家到 `core/resource_import_wizard.py`，旧实现留在原地 |
| `core/cloud/config_sync.py` | 405 | ❌ **未完成功能**：模块头自己写着「MVP · 纯逻辑核心，网络与磁盘读写由调用方完成」—— 而那个调用方从来没写 |
| `audio_event_audit.py` | 264 | ❌ **活着**：`AUDIO_RUNTIME_ACCEPTANCE.md` 里文档化的人工验收命令行工具 |
| `request_admin.py` | 64 | ⚠ 死码属实，但 `docs/quality/README.md` 有一条既有裁定「判为 none（不清理）」 |
| `audio_health_check.py` | 17 | ❌ **活着**：README / 打包说明里写着 `python audio_health_check.py` |

⇒ 三条 AST 结构上看不见的「引用」，每一条都在这五个里出现了：
**文档里写着命令行入口**、**调用方还没写**、**另一份文档里有一条不清理的裁定**。

⭐⭐⭐ 而最值得记的一条：`config_sync` 那种模块**它的单测会一直绿** ——
**在任何「有没有测试」的检查里它都健康，在任何「有没有人用」的检查里它都是死的。**

## 两个已知会把结论整体带偏的坑

1. ⛔ **`.claude/` 下可能挂着另一个会话的 git worktree 副本**（RN-561 实测有）。
   不跳过的话每个文件被数两遍 ⇒ **「有没有引用」永远答「有」** ——
   ⭐ 这类污染只朝一个方向失效，而那个方向正好让本脚本一无所获。
2. ⛔ **分桶必须和判据一致**，别再自己写一份（批 78 原话）。
   ⇒ 直接 import `tests/test_the_size_promises_are_watched.py` 的
   `_product_files()` / `SKIP_DIRS`，它和总纲 §15 第 9 条①逐字对齐。

用法：

    python scripts/dead_code_sweep.py                # 三源全跑，出汇总
    python scripts/dead_code_sweep.py --source names # 只跑一源
    python scripts/dead_code_sweep.py --verbose      # 逐条列出来
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: ── 既有裁定豁免表（RN-603，批 81）─────────────────────────────────
#: ⭐⭐⭐ DoD 第 9 条③ 写着「死码三源扫描 **0 确证项**」，而本仓另有一条既有裁定
#: 逐字写着某个模块「死代码属实，但清理它不产生用户价值，**判为 none**」——
#: **两份裁定各写各的文档，谁都没看见谁**；而三笔 LOC 欠账的唯一合法还款来源
#: 又正是死码清理 ⇒ **还款计划整个建立在一件本仓已经裁定「不做」的事情上。**
#:
#: ⇒ 裁定（批 81）：不改条文，改读法 —— 第 9 条③ 读作
#:   「0 确证项，**或**每条确证项在这张表里有一行点名那条既有裁定」。
#: ⛔ 进这张表的门槛只有一条：**指得出出处**（文件:行号），且那行字今天还在。
#:   ⚠ 不许写「以后再说」「暂不清理」这类没有出处的理由 —— 那是 RN-545
#:   那句「注释里的缓期」，没人看着它到期。
EXEMPT_MODULES = {
    #: ⚠ 路径在**仓根**，不是 `core/` —— 第一版我写的是 `core/request_admin.py`，
    #:   而那条判据**首跑当场逮到**：豁免表点着一个不存在的文件。
    #:   ⭐ 一条指向不存在文件的豁免，和一条真豁免，在表里长得一模一样。
    "request_admin.py": (
        "docs/quality/README.md",
        "死代码属实，但清理它不产生用户价值，判为 none",
        "既有裁定（README:593）：两个模块全仓零引用，但清理不产生用户价值 ⇒ 判为 none",
    ),
    # 批 93（E2）：批 80 逐个开文件核实过的三个「零引用模块」，裁定落在 docs/quality/README.md。
    "audio_event_audit.py": (
        "AUDIO_RUNTIME_ACCEPTANCE.md",
        "python audio_event_audit.py --minutes 30 --show-lines 8",
        "文档化的人工验收命令行工具 —— 入口写在验收文档里，AST 看不见",
    ),
    "audio_health_check.py": (
        "README.md",
        "命令行体检：`python audio_health_check.py`",
        "README 里写着的命令行入口",
    ),
    "core/cloud/config_sync.py": (
        "docs/quality/README.md",
        "未完成功能，不是死码：留着等云同步开工时接上，或整体撤",
        "模块头写着「网络与磁盘读写由调用方完成」，而调用方从来没写（批 80 核实）",
    ),
}
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

#: ⭐ 分桶与文件遍历**复用判据自己的那一份**，不写第二份（批 78 的教训）。
from test_the_size_promises_are_watched import (  # noqa: E402
    _product_files, _count, SKIP_DIRS,
)

#: 这些名字即使零引用也不算死码 —— 它们是被框架/协议按名字调用的。
_PROTOCOL = {
    "main", "__all__", "__version__",
}
_DUNDER_PREFIX = "__"

#: Qt 的信号槽、事件回调按名字被基类调用；配置项按字符串取。
_QT_CALLBACK_PREFIX = (
    "event", "paint", "mouse", "key", "resize", "close", "show", "hide",
    "drag", "drop", "wheel", "focus", "enter", "leave", "context",
)


def _read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def _reference_files() -> list[Path]:
    """**引用面** —— 谁可能用到这些名字。⚠ 它和「行数分子」不是同一个集合。

    ⛔⛔ 批 80 第一版直接拿判据的 `_product_files()` 当引用面，而那个分桶是
    给「算行数」用的（`pages/` `core/` `widgets/` + 根目录扁平层）——
    **`dialogs/` 整个目录不在里面**，于是 6 个在 `dialogs/` 里被真实调用的符号
    （`export_pack` / `KillIconLevelGrid` / `rename_style` / `delete_style` /
    `list_style_files` / `columns_for_width`）被报成了「零引用」。

    ⭐⭐⭐ **一份夹具能不能用，取决于你要量什么**（批 26 原话）——
    我拿一把量行数的尺子去量引用面，而两者少了一个 2845 行的目录。
    ⇒ 引用面取**全仓源码**，只跳过明确的噪音目录。
    """
    out = []
    skip = SKIP_DIRS - {"tests", "scripts", "build_tools", "tools", "docs"}
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames
                       if d not in skip and not d.startswith("_manual_backup")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath) / fn)
    return out


def _tree(p: Path):
    try:
        return ast.parse(_read(p))
    except SyntaxError:
        return None


# ── 源① 零引用的名字 ────────────────────────────────────────────────────

def _module_level_names(tree, path):
    """模块级定义的函数 / 类 / 常量。⚠ 只取模块级 —— 类里的方法另有调用面。"""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.name, node.lineno, _span(node)))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.append((t.id, node.lineno, _span(node)))
    return out


def _span(node) -> int:
    """这个定义占几行（还款额要按行数算，不是按个数）。"""
    end = getattr(node, "end_lineno", None)
    return (end - node.lineno + 1) if end else 1


def sweep_names(files, texts, verbose=False):
    """⚠⚠ **引用面放宽会消掉假阳性，同时也消掉一整类真阳性。**

    第一版引用面只含产品分桶（漏了 `dialogs/`）⇒ 6 个真被调用的符号被误报。
    放宽到全仓（含 `tests/`）之后 30 项降到 16 项 —— 但代价是：
    **「只被自己的单测吊着」那一类死码从此报不出来**，
    而本批唯一还成的那 248 行（`core/audio/audio_import_wizard.py`）正是那个形状。
    ⭐⭐⭐ **一个能消除假阳性的口径，往往同时消除了某一类真阳性 ——
    而报告上只看得见前者。**
    ⇒ 留 `--strict`：只拿产品面当引用面，专门找那一类；两个面的结论要分开读。
    """
    defined = {}          # name -> (path, lineno, span)
    for p in files:
        tree = _tree(p)
        if tree is None:
            continue
        # ⛔ 带装饰器的定义：框架按注册表调用（`@flask_app.route` 那种），
        #   显式调用点结构上就不存在 —— `gsi_server.game_state_update` 就是这么被误报的。
        decorated = {n.name for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef)) and n.decorator_list}
        for name, lineno, span in _module_level_names(tree, p):
            if name in decorated:
                continue
            if name in _PROTOCOL or name.startswith(_DUNDER_PREFIX):
                continue
            if name.lower().startswith(_QT_CALLBACK_PREFIX):
                continue
            defined.setdefault(name, (p, lineno, span))

    hits = defaultdict(int)
    for p, text in texts.items():
        for name in defined:
            n = text.count(name)
            if n:
                hits[name] += n

    dead = []
    for name, (p, lineno, span) in defined.items():
        # 定义处自己至少出现 1 次；> 1 说明别处用到了。
        if hits[name] <= 1:
            dead.append((name, p, lineno, span))
    return sorted(dead, key=lambda r: -r[3])


# ── 源② 零引用的模块 ────────────────────────────────────────────────────

def sweep_modules(files, texts, verbose=False):
    stems = {p.stem: p for p in files}
    imported = set()
    for p in files:
        tree = _tree(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.update(node.module.split("."))
                for a in node.names:
                    imported.add(a.name)
    dead = []
    for stem, p in stems.items():
        if stem in imported:
            continue
        # ⚠ 入口文件按名字被外部调起（打包脚本、快捷方式），不算死。
        if stem.startswith("main") or stem == "__init__":
            continue
        dead.append((stem, p, 1, _count(p)))
    return sorted(dead, key=lambda r: -r[3])


def exemption_for(path) -> tuple | None:
    """这个模块有没有一条既有裁定罩着它？（RN-603）

    ⭐ 豁免**不减少行数、不进还款额** —— 它只回答 DoD 第 9 条③ 那句
    「0 确证项」：一条有出处的既有裁定，和「还没查」不是一回事。
    """
    return EXEMPT_MODULES.get(path.relative_to(REPO).as_posix())


# ── 源③ 死参数 ──────────────────────────────────────────────────────────

def sweep_params(files, texts, verbose=False):
    """⚠⚠ **这一源在一个 Qt 应用里结构上产出不了还款额，别指望它。**

    第一版报 43 项，逐条看下去**绝大多数是框架定的签名**：
    `paintEvent(event)` / `eventFilter(obj)` / `_graceful_exit_handler(frame)`
    （`signal.signal` 要求 `(signum, frame)`）—— 形参没读是**正常**的，
    删掉当场破坏协议。⭐ 「没人读这个形参」和「这个形参可以去掉」是两件事。
    ⇒ 排除掉协议签名之后剩下的才值得看，而那时它只剩个位数。
    """
    dead = []
    for p in files:
        tree = _tree(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # ⛔ 框架回调 / 信号槽：签名不归我们定。
            if node.name.lower().startswith(_QT_CALLBACK_PREFIX):
                continue
            if node.decorator_list:      # @Slot / @property / @override 之类
                continue
            body_names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            body_names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            args = node.args
            formals = [a.arg for a in (args.posonlyargs + args.args + args.kwonlyargs)]
            for a in formals:
                if a in ("self", "cls") or a.startswith("_"):
                    continue
                if a not in body_names:
                    dead.append((f"{node.name}({a})", p, node.lineno, 1))
    return sorted(dead, key=lambda r: str(r[1]))


SOURCES = {"names": sweep_names, "modules": sweep_modules, "params": sweep_params}
TITLES = {"names": "① 零引用的名字", "modules": "② 零引用的模块",
          "params": "③ 死参数"}


def _dedupe(rows_by_source: dict) -> dict:
    """⛔⛔ **三源会重复计数，而且是朝着「还款额看起来更大」那个方向。**

    一个模块整体死掉，它里面的名字当然也零引用、它的参数当然也没人读 ——
    于是同样几行会被源①②③各数一遍。批 80 第一版合计报「约 1607 行」，
    而 `core/audio/audio_import_wizard.py` 那 248 行在里面被数了**两遍**
    （整模块一次 + 里面两个函数 176 行一次）。

    ⭐⭐⭐ **一个会重复计数的还款额，和真的能还那么多，长得一模一样** ——
    而它失效的方向正好是我希望的那个方向。
    ⇒ 源②优先（粒度最粗），①③ 落在已判死模块里的一律剔除。
    """
    dead_files = {r[1] for r in rows_by_source.get("modules", ())}
    for key in ("names", "params"):
        if key in rows_by_source:
            rows_by_source[key] = [r for r in rows_by_source[key]
                                   if r[1] not in dead_files]
    return rows_by_source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES), action="append")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="只拿产品面当引用面 —— 专门找「只被自己的单测吊着」那一类")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = _product_files()
    # ⛔ 引用面 != 行数分子（见 _reference_files 的注释）
    ref = _product_files() if args.strict else _reference_files()
    texts = {p: _read(p) for p in ref}
    total_lines = sum(_count(p) for p in files)
    print(f"产品代码：{len(files)} 个文件 / {total_lines} 行"
          f"（分桶与判据同源）\n")

    # ⛔ 先把三源都算出来再去重 —— 顺序是「②模块」优先（见 `_dedupe`）。
    wanted = args.source or sorted(SOURCES)
    rows_by_source = {k: SOURCES[k](files, texts, args.verbose)
                      for k in set(wanted) | {"modules"}}
    rows_by_source = _dedupe(rows_by_source)

    grand = 0
    for key in ("modules", "names", "params"):
        if key not in wanted:
            continue
        rows = rows_by_source[key]
        lines = sum(r[3] for r in rows)
        # ⛔ 源③ **不计入还款额**：排除掉框架回调之后剩下的仍然几乎全是协议签名
        #   （combo 的 `currentIndexChanged` 槽、`sizeHint(index)` 重写、
        #    抽象基类的 `resolve(url)`、基类桩方法）。它是一份**提示**，不是钱。
        #   ⭐ 「没人读这个形参」和「这个形参可以去掉」是两件事。
        if key != "params":
            grand += lines
        print(f"{TITLES[key]}：{len(rows)} 项 / 约 {lines} 行")
        for name, p, lineno, span in (rows if args.verbose else rows[:12]):
            rel = p.relative_to(REPO).as_posix()
            ex = exemption_for(p) if key == "modules" else None
            tag = f"  ⚖ 既有裁定豁免（{ex[0]}：{ex[1]}）" if ex else ""
            print(f"    {span:>4} 行  {rel}:{lineno}  {name}{tag}")
        if not args.verbose and len(rows) > 12:
            print(f"    …… 其余 {len(rows) - 12} 项（--verbose 全列）")
        print()

    exempt = [p for _, p, _, _ in rows_by_source.get("modules", ())
              if exemption_for(p)]
    print(f"还款额候选（①②，**不是确证项**）：约 {grand} 行")
    if exempt:
        print(f"   ⚖ 其中 {len(exempt)} 项有既有裁定豁免（RN-603，总纲 §15 注五）："
              + "、".join(p.relative_to(REPO).as_posix() for p in exempt))
        print("     DoD 第 9 条③ 读作「0 确证项，**或**每条确证项在 "
              "EXEMPT_MODULES 里有一行点名既有裁定」。")
    print("   ③ 死参数只作提示，不计入 —— 排除框架回调后剩下的仍几乎全是协议签名。")
    print("⛔ 逐条开文件核实之前不许删 —— 动态取用 AST 看不见（见模块文档）。")


if __name__ == "__main__":
    main()
