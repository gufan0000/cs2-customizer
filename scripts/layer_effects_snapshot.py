# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""**模块形状**的链路外部效应快照：`import` 这个模块的那一瞬间，它对外面做了什么。

## 为什么问的是 import 期，而不是「跑起来做了什么」

X1 那份（`x1_effects_snapshot.py`）建一个主窗再录 —— 因为主窗的效应在**构造**时发生。
D4 这四条（X9 搜索 / X10 热键 / X12 资源 / X13 utils）没有「构造入口」这个东西，
它们是一堆被别人 import 的模块。⭐ 而 X4 那一批量出来的结论直接适用：

  **同一个 `open(..., "w")`，在 import 期是「打包机一 collect_submodules 就会触发」，
  在函数体里只是普通的后台写盘 —— 同一段代码，危险程度差三个数量级。**

`core/utils/logger.py` 的注释里逐字记着这件事（UP-004：日志清理放进 `Logger.__init__`
被打包机触发、删掉了历史日志）。⇒ 这一层要冻的正是「import 期都干了什么」。

## ⛔ 每个模块必须在**全新子进程**里 import

第一版我打算在一个进程里挨个 import —— **那量的是「第一个 import 的模块干了什么」**：
后面每一个都命中 `sys.modules` 缓存，读数全是 0，而那个 0 和「它真的很干净」
在快照里长得一模一样。⇒ 一个模块一个子进程，谁都不沾谁的光。

## ⛔⛔ 而每个模块要跑**两遍**，冻的是第二遍

⭐⭐⭐ 第一版只跑一遍，量出来「`import resource_manager` 会写 `config.json.tmp`」——
看上去是一条很重的缺陷（UP-004 同款：一个模块光是被 import 就改写用户配置）。
**实测不是**：探针用的是全新配置目录，那一次写是**首次运行落出厂配置**，
本来就该发生；同一个目录跑第二遍，配置相关的写盘是 **0**。
⇒ **一次读数分不出「首次引导」和「每次都干」，而两者在快照里长得一模一样。**
现在跑两遍：**第二遍进基线**（稳态），第一遍多出来的那些记在 `首次引导` 一栏里，
⛔ 不删掉 —— 删了下一个人会重新发现一遍，并且同样先当成缺陷。

## 拦哪几条出口

定时器（`threading.Timer` —— import 期通常还没有 QApplication）、线程、子进程、
写盘、以及**注册全局热键**（这一层有 X10，那是它的主业）。

用法：
    python scripts/layer_effects_snapshot.py --layer X13
    python scripts/layer_effects_snapshot.py --layer X13 --write
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from layer_contract_snapshot import LAYERS  # noqa: E402

#: 子进程里跑的那段。⭐ 它必须**自包含**：父进程的任何状态都不会传过来。
CHILD = r'''
# -*- coding: utf-8 -*-
"""在全新解释器里 import 一个模块，把 import 期的外部效应打成 JSON。"""
import builtins
import json
import os
import subprocess
import sys
import threading

ROOT, MODULE = sys.argv[1], sys.argv[2]        # argv[3] = "1" 表示这是第一遍
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _pristine_config import use_pristine_config_dir   # noqa: E402

# ⛔⛔ `use_pristine_config_dir` **无条件 `rmtree`** —— `force` 只决定
#   「外面已经设过 CS2C_CONFIG_DIR 时要不要抢」，不决定要不要清空。
#   ⭐ 我的第一版「第二遍传 force=False」因此量的还是**第一遍**（目录又被清空了），
#   而读数和真正的稳态写盘一模一样。⇒ 第二遍必须**自己先把环境变量设好**，
#   让它走「外面定了就听外面的」那条早退路径。
_name = "cs2customizer_layer_effects_" + MODULE.replace(".", "_")
_dir = os.path.join(os.environ.get("TEMP") or "/tmp", _name)
if sys.argv[3] == "1":
    use_pristine_config_dir(_name, force=True)
else:
    os.environ["CS2C_CONFIG_DIR"] = os.path.join(_dir, "config")
    os.environ["CS2C_LOG_DIR"] = os.path.join(_dir, "logs")
    assert os.path.exists(os.environ["CS2C_CONFIG_DIR"]), (
        "第二遍找不到第一遍留下的配置目录 —— 那就不是稳态，是又一次首次运行")

seen = {"定时器": [], "线程": [], "进程": [], "写盘": []}

_real_timer = threading.Timer


class _Timer(_real_timer):
    def start(self):
        seen["定时器"].append({"间隔s": self.interval,
                               "目标": getattr(self.function, "__qualname__", "?")[:60]})
        return super().start()


threading.Timer = _Timer

_real_thread_start = threading.Thread.start


def _thread_start(self):
    t = getattr(self, "_target", None)
    seen["线程"].append({"名字": self.name,
                         "目标": getattr(t, "__qualname__", str(t))[:60],
                         "守护": bool(self.daemon)})
    return _real_thread_start(self)


threading.Thread.start = _thread_start

for _attr in ("Popen", "run", "call", "check_output"):
    if hasattr(subprocess, _attr):
        def _mk(name, fn):
            def wrapper(*a, **kw):
                seen["进程"].append({"接口": name, "命令": str(a[0])[:80] if a else ""})
                return fn(*a, **kw)
            return wrapper
        setattr(subprocess, _attr, _mk(_attr, getattr(subprocess, _attr)))

_real_open = builtins.open


def _guarded_open(file, mode="r", *a, **kw):
    if any(m in str(mode) for m in ("w", "a", "x", "+")):
        seen["写盘"].append(os.path.basename(str(file))[:60])
    return _real_open(file, mode, *a, **kw)


builtins.open = _guarded_open

err = ""
try:
    __import__(MODULE)
except Exception as exc:                      # noqa: BLE001
    err = f"{type(exc).__name__}: {exc}"[:200]
finally:
    builtins.open = _real_open

alive = sorted(t.name for t in threading.enumerate()
               if t is not threading.main_thread() and t.is_alive())

print("<<<JSON>>>" + json.dumps({
    "模块": MODULE,
    "import 失败": err,
    "起定时器": seen["定时器"],
    "起线程": [t["名字"] for t in seen["线程"]],
    "起子进程": sorted({p["命令"] for p in seen["进程"]}),
    "写盘文件名": sorted(set(seen["写盘"])),
    "import 完还活着的线程": alive,
}, ensure_ascii=False))
'''


def _one_pass(module: str, first: bool) -> dict:
    # ⛔ 落在 `%TEMP%`，**不落在 `scripts/`** —— 那是个会被 `oss_sync --accept-new`
    #   当成「新增文件」的目录，而一个新文件从「不存在」到「公开可见」中间没有任何一步会失败。
    child = Path(tempfile.gettempdir()) / "_cs2customizer_layer_effects_child.py"
    child.write_text(CHILD, encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(child), str(ROOT), module, "1" if first else "0"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=180)
    for line in (proc.stdout or "").splitlines():
        if line.startswith("<<<JSON>>>"):
            return json.loads(line[len("<<<JSON>>>"):])
    return {"模块": module, "import 失败": f"子进程没吐出读数（rc={proc.returncode}）："
                                       + (proc.stderr or "")[-160:]}


def _run_one(module: str) -> dict:
    """跑两遍，**第二遍进基线**；第一遍多出来的记成「首次引导」。见模块文档。"""
    boot = _one_pass(module, first=True)
    steady = _one_pass(module, first=False)
    if steady.get("import 失败"):
        return steady
    only_first = sorted(set(boot.get("写盘文件名") or [])
                        - set(steady.get("写盘文件名") or []))
    steady["首次引导才写的文件"] = only_first
    return steady


def build(layer_name: str) -> dict:
    mods = sorted(LAYERS[layer_name]["modules"])
    rows = [_run_one(m) for m in mods]
    #: ⭐ 空转守卫：一个模块都 import 不进来的话，下面每一栏都是 0，
    #:   而那个 0 和「这一层很干净」在快照里长得一模一样。
    ok = [r for r in rows if not r.get("import 失败")]
    assert ok, (f"{layer_name} 的 {len(mods)} 个模块**一个都没 import 成功** —— "
                f"这份快照量的不是产品，是环境。第一条错：{rows[0].get('import 失败')}")
    return {
        "_说明": "import 期的外部效应。每个模块一个全新子进程，谁都不沾谁的 sys.modules。",
        "模块数": len(mods),
        "import 成功": len(ok),
        "逐模块": rows,
        "import 期起过定时器的模块": sorted(r["模块"] for r in ok if r["起定时器"]),
        "import 期起过线程的模块": sorted(r["模块"] for r in ok if r["起线程"]),
        "import 期起过子进程的模块": sorted(r["模块"] for r in ok if r["起子进程"]),
        "import 期写过盘的模块": sorted(r["模块"] for r in ok if r["写盘文件名"]),
        # ⭐ 单列一栏：这些写盘**只在首次运行发生**（落出厂配置之类），不是稳态效应。
        #   ⛔ 不许把它合进上一栏 —— 合进去等于把「首次引导」冻成「每次都干」。
        "只在首次引导发生的写盘": {r["模块"]: r["首次引导才写的文件"]
                                    for r in ok if r.get("首次引导才写的文件")},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", required=True, choices=sorted(LAYERS))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    data = build(args.layer)
    print(f"{args.layer}：{data['import 成功']}/{data['模块数']} 个模块 import 成功")
    for key in ("import 期起过定时器的模块", "import 期起过线程的模块",
                "import 期起过子进程的模块", "import 期写过盘的模块"):
        mark = "⛔" if data[key] else "  "
        print(f"{mark} {key}：{data[key] or '无'}")
    for r in data["逐模块"]:
        if r.get("写盘文件名"):
            print(f"     · {r['模块']}: {r['写盘文件名']}")
    if data["只在首次引导发生的写盘"]:
        print(f"⭐ 只在**首次引导**发生（不是稳态效应）："
              f"{data['只在首次引导发生的写盘']}")
    for r in data["逐模块"]:
        if r.get("import 失败"):
            print(f"   ⚠ {r['模块']} import 失败：{r['import 失败']}")

    if args.write:
        out = ROOT / "tests" / "baselines" / f"{args.layer.lower()}_effects.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                  sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n已写入 {out.relative_to(ROOT)}")
    else:
        print("\n（没给 --write，什么都没写）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
