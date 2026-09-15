# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X5（退出链路）的**开档盘点**：退出清理表、外部效应、以及「谁在最后一刀之前没跑完」。

## 这一层和 X4 的区别：契约从「代码位置」变成了「一张表」

X4 的顺序契约散在 `main()` 的 722 行里，是「第 N 行必须在第 M 行之前」；
要量它得比 AST 作用域 + 行号（RN-620 的教训）。

**X5 不一样**：退出顺序整个写在 `gui_widget._run_shutdown_steps` 的
`steps = [...]` 这一个列表字面量里，**顺序即契约，而且契约是数据**。
注释里还写着理由（UP-035「先退订配置重载广播，否则总线握着已析构窗口」、
UP-055「不能走 `self.audio_manager`，那是惰性属性」）。
⇒ 盘点这一层不需要比行号，只需要**把表读出来**。

## ⭐ 但 X5 多了一样 X4 没有的东西：**一条会被砍断的时间线**

启动没有截止时间；退出有三条，而且**一条比一条硬**：

  · `_run_shutdown_steps` 的 **15s 看门狗** ⇒ `os._exit(0)`
  · `os._exit` **不跑 atexit**（`config._atexit_flush` / `game_audio_ducker.close`）
  · `taskkill /f` 连 `closeEvent` 都不跑（`core/shutdown.py` 自己的文档写明不覆盖）

⇒ 本盘点的核心读数不是「有几步」，是 **「哪几步只活在最长的那条时间线上」**。
一步排得越靠后，它被砍掉的概率越高，而**表上看不出这件事**。

## 怎么量的（三条自查）

⚠ ① **「有判据提到这个符号」不是「有判据守着这件事」**（RN-620）。
   本脚本的 `judges` 一栏是**下界**：它只回答「哪个判据文件里出现过这个名字」，
   **不回答「那个判据会不会在这件事坏掉时变红」**。定性靠 `x5_step_shuffler.py`
   的破坏验证，不靠这张表。
⚠ ② **外部效应按「谁能观察到」分档**，不按调用长相分：
   写盘（下次启动能观察到）/ 游戏内状态（**退出之后仍然留在 CS2 里**）/
   子进程（退出之后仍然在任务管理器里）/ 纯内存（谁也观察不到）。
   ⭐ 只有前三档在「被砍断」时会留下痕迹，第四档砍了等于没砍。
⚠ ③ **排掉 `.build/` / `_backup` / `_archive` / `.claude/worktrees/`**（X3/X4 同款）。

用法：
    python scripts/x5_shutdown_contract.py            # 人读
    python scripts/x5_shutdown_contract.py --json     # 机器读
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

#: X5 层的文件。退出链路没有一个独立模块 —— 这本身就是一条读数：
#: 它散在「专职模块 + 主窗的一段 + 配置层的一个钩子」三处。
LAYER = {
    "core/shutdown.py": ROOT / "core" / "shutdown.py",
}

#: 退出段寄居在别的层里的那几处（不计入「层内行数」，但必须一起盘）。
TENANTS = [
    ("gui_widget.py", "MainWindow.closeEvent"),
    ("gui_widget.py", "MainWindow._run_shutdown_steps"),
    ("config.py", "Config._atexit_flush"),
    ("config.py", "Config._register_atexit_flush"),
]

EXCLUDE_PARTS = (".build", "_backup", "_archive", "output", "worktrees", "__pycache__")

#: 外部效应的分档。
#: ⛔⛔ **只自动判我能判准的两档，其余一律 `?待人判`。**
#: 第一版我写了四档并给每档一串关键字（`cleanup` / `stop` / `恢复` …），
#: 结果 18 步里 14 步被判成「游戏内状态」——因为退出路径上**每一步都叫 cleanup**。
#: ⭐⭐⭐ 那张表看起来最饱满的时候，正是它什么都没说的时候（RN-615 的分母教训，
#: 我在本文件自己的文档里刚引用过它，然后在下面二十行处犯了同一个错）。
EFFECT_DISK = "写盘"           # 调了 save/flush —— 能确定
EFFECT_CFG = "改配置"          # 给 self.config.X 赋值 —— 能确定，且**依赖第 17 步落盘**
EFFECT_UNKNOWN = "?待人判"     # 跨模块调用，展开不到；不猜

_DISK_HINTS = ("save_config", "flush(", "json.dump", "write_text", "os.replace")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _func_node(tree: ast.AST, qualname: str):
    """按 `Class.method` 或 `func` 取节点。找不到返回 None。"""
    parts = qualname.split(".")
    scope = tree
    for i, name in enumerate(parts):
        want = (ast.FunctionDef, ast.AsyncFunctionDef) if i == len(parts) - 1 else (ast.ClassDef,)
        found = None
        for node in ast.iter_child_nodes(scope):
            if isinstance(node, want) and getattr(node, "name", None) == name:
                found = node
                break
        if found is None:
            return None
        scope = found
    return scope


def _steps_table(src: str):
    """读出 `_run_shutdown_steps` 里的 `steps = [...]`。

    ⚠ 返回的是**源码顺序**，而源码顺序就是执行顺序 —— 这一层没有 X4 那个
    「定义在前、执行在后」的回调陷阱（RN-620），因为这张表是**数据**，
    它被一个平铺的 for 循环按下标跑掉。这句话本身要被判据钉住（见
    `test_the_shutdown_order_is_a_table_not_a_suggestion.py`）。
    """
    tree = ast.parse(src)
    fn = _func_node(tree, "MainWindow._run_shutdown_steps")
    if fn is None:
        return []
    lines = src.splitlines()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        if not (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "steps"):
            continue
        if not isinstance(node.value, ast.List):
            continue
        out = []
        for idx, elt in enumerate(node.value.elts, 1):
            if not (isinstance(elt, ast.Tuple) and len(elt.elts) == 2):
                continue
            name_node, fn_node = elt.elts
            name = name_node.value if isinstance(name_node, ast.Constant) else ast.unparse(name_node)
            # 这一步之前紧挨着的注释块 = 写下来的顺序理由
            reason = []
            ln = elt.lineno - 2  # 0-based 的上一行
            while ln >= 0 and lines[ln].strip().startswith("#"):
                reason.insert(0, lines[ln].strip().lstrip("#").strip())
                ln -= 1
            out.append({
                "no": idx,
                "name": name,
                "target": ast.unparse(fn_node),
                "line": elt.lineno,
                "reason": " ".join(reason),
            })
        return out
    return []


def _resolve_target_body(src: str, target: str) -> str:
    """把步骤的目标解析成「它真正会跑的那段源码」，用于定外部效应的档。

    ⚠ 目标有两种长相：`self._foo`（绑定方法）和 `lambda: self.bar.baz()`。
    lambda 的情况**不能只看 lambda 那一行** —— 那一行只写着调用，
    真正的效应在被调的那个方法体里。这里对本模块内能找到的方法做一层展开；
    展开不到的（跨模块，如 `self.gsi_server.stop()`）如实标 `?`，
    ⭐ **不猜** —— RN-615 的分母教训：猜出来的分母看起来最饱满。
    """
    tree = ast.parse(src)
    bodies = [target]
    for name in sorted(set(_self_methods(target))):
        node = _func_node(tree, f"MainWindow.{name}")
        if node is not None:
            bodies.append(ast.get_source_segment(src, node) or "")
    return "\n".join(bodies)


def _self_methods(expr: str):
    """从 `self._foo` / `lambda: self._bar(x)` 里捞出本类方法名。"""
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    out = []
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                and sub.value.id == "self"):
            out.append(sub.attr)
    return out


def _writes_config(body: str) -> bool:
    """这一步会不会给 `self.config.X` 赋值。

    ⭐ 这是本盘点最值钱的一栏：**改配置的步骤依赖第 17 步「落盘配置」把它写出去**，
    于是「改配置的步骤必须排在落盘之前」是一条**没有人写下来的顺序契约** ——
    它连注释都没有，比 X4 那九条还隐蔽（那九条至少写在注释里）。
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Attribute)
                    and t.value.attr == "config" and isinstance(t.value.value, ast.Name)
                    and t.value.value.id == "self"):
                return True
    return False


def _classify(body: str, target: str) -> list[str]:
    tags = []
    if any(h in body for h in _DISK_HINTS):
        tags.append(EFFECT_DISK)
    if _writes_config(body):
        tags.append(EFFECT_CFG)
    if body.strip() == target.strip():
        tags.append(EFFECT_UNKNOWN)
    return tags or [EFFECT_UNKNOWN]


def _atexit_registrants():
    """全仓扫 `atexit.register(...)`。

    ⭐ atexit 是 **LIFO**：**后注册的先跑**。而注册顺序取决于**对象什么时候被建出来**，
    不取决于谁写在文件前面 —— 所以这张表只给出「有几个」，
    真实顺序要靠运行期量（`x5_atexit_order_probe.py`）。
    """
    out = []
    for py in sorted(ROOT.rglob("*.py")):
        if any(part in EXCLUDE_PARTS for part in py.parts):
            continue
        try:
            src = _read(py)
        except Exception:
            continue
        if "atexit.register" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "atexit"):
                out.append({
                    "file": str(py.relative_to(ROOT)).replace("\\", "/"),
                    "line": node.lineno,
                    "callback": ast.unparse(node.args[0]) if node.args else "?",
                })
    return out


def _watchdog_does(src: str) -> list[str]:
    """看门狗开火时到底做了什么 —— 用来算它和整张表的**差集**。"""
    tree = ast.parse(src)
    outer = _func_node(tree, "MainWindow._run_shutdown_steps")
    if outer is None:
        return []
    for node in ast.walk(outer):
        if isinstance(node, ast.FunctionDef) and node.name == "_watchdog_fire":
            seg = ast.get_source_segment(src, node) or ""
            return [ln.strip() for ln in seg.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
    return []


def _judges_mentioning(symbols):
    """哪个判据文件里出现过这些名字。

    ⛔⛔ **这是下界，不是覆盖率**（RN-620）：X4 实测九条顺序契约里八条
    「有判据提到」，而一次全违反跑全量 **0 红**。
    这一栏唯一的用途是**给破坏验证排优先级**，不许当结论用。
    """
    tests = ROOT / "tests"
    hits = {}
    for py in sorted(tests.glob("*.py")):
        try:
            src = _read(py)
        except Exception:
            continue
        for sym in symbols:
            if sym and sym in src:
                hits.setdefault(sym, []).append(py.name)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    gui_src = _read(ROOT / "gui_widget.py")
    steps = _steps_table(gui_src)
    for st in steps:
        body = _resolve_target_body(gui_src, st["target"])
        st["effects"] = _classify(body, st["target"])

    watchdog = _watchdog_does(gui_src)
    registrants = _atexit_registrants()

    symbols = sorted({m for st in steps for m in _self_methods(st["target"])})
    symbols += ["_run_shutdown_steps", "_watchdog_fire", "_atexit_flush"]
    judges = _judges_mentioning(symbols)

    layer_lines = {k: len(_read(v).splitlines()) for k, v in LAYER.items()}

    #: ⭐ 读数一：**没有人写下来的那条顺序契约** —— 改配置的步骤必须排在落盘之前。
    cfg_writers = [st["no"] for st in steps if EFFECT_CFG in st["effects"]]
    disk_steps = [st["no"] for st in steps if EFFECT_DISK in st["effects"]]
    last_disk = max(disk_steps) if disk_steps else 0
    cfg_after_disk = [n for n in cfg_writers if n > last_disk]

    #: ⭐ 读数二：**只活在最长那条时间线上的步骤**。
    #: 看门狗只补 `save_config_now()`，其余每一步在超时路径上都不跑。
    watchdog_saves = any("save_config_now" in ln for ln in watchdog)
    watchdog_covers = [st["no"] for st in steps
                       if watchdog_saves and "save_config_now" in st["target"]]
    orphaned = [st for st in steps if st["no"] not in watchdog_covers]

    data = {
        "layer_lines": layer_lines,
        "tenants": [f"{f}::{q}" for f, q in TENANTS],
        "steps": steps,
        "config_writer_steps": cfg_writers,
        "disk_steps": disk_steps,
        "config_writers_after_last_disk_step": cfg_after_disk,
        "watchdog_body": watchdog,
        "watchdog_covers_steps": watchdog_covers,
        "steps_lost_on_timeout": [st["no"] for st in orphaned],
        "atexit_registrants": registrants,
        "judges_mentioning": judges,
    }

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("=" * 72)
    print("X5 · 退出链路 · 开档盘点")
    print("=" * 72)
    print(f"\n层内行数：{layer_lines}")
    print(f"寄居在别的层里的退出段：{len(TENANTS)} 处")
    for f, q in TENANTS:
        print(f"    · {f} :: {q}")

    print(f"\n退出清理表：**{len(steps)} 步**（`gui_widget._run_shutdown_steps`）")
    print(f"{'#':>3}  {'步骤':<16} {'外部效应':<22} {'写下来的理由':<6} 判据提到")
    print("-" * 72)
    for st in steps:
        ms = _self_methods(st["target"])
        j = sum(len(judges.get(m, [])) for m in ms)
        print(f"{st['no']:>3}  {st['name']:<16} {'/'.join(st['effects']):<22} "
              f"{'有' if st['reason'] else '—':<6} {j if j else '—'}")

    print("\n⭐ 没有人写下来的那条契约：**改配置的步骤必须排在落盘之前**")
    print(f"    改配置的步骤：{cfg_writers or '—'}；落盘的步骤：{disk_steps or '—'}")
    print(f"    排在最后一次落盘（#{last_disk}）之后还改配置的："
          f"{cfg_after_disk or '无 —— 当下为真，而无人守着'}")

    print(f"\n15s 看门狗开火时做的事（{len(watchdog)} 行）：")
    for ln in watchdog:
        print(f"    {ln}")
    print(f"\n⛔ **超时路径上一步都不跑的步骤**：{len(orphaned)} / {len(steps)} 步"
          f"（看门狗只补 save_config_now）")
    for st in orphaned:
        print(f"    {st['no']:>3} {st['name']}（{'/'.join(st['effects'])}）")

    print(f"\natexit 注册者：{len(registrants)} 个（LIFO，后注册的先跑）")
    for r in registrants:
        print(f"    · {r['file']}:{r['line']} → {r['callback']}")

    print("\n⚠ 「判据提到」一栏是**下界**，不是覆盖率（RN-620）。"
          "定性靠 x5_step_shuffler.py 的破坏验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
