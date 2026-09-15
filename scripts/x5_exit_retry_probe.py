# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X5 探针：**RN-622 的重试定时器在退出那一刻还挂着，会怎样。**

这是我批 86 自己引进来的机制，所以由我自己查一遍（批 87 计划第 ③ 条）。

## 被问的那件事

RN-622 把「写盘失败 ⇒ 记一行 ERROR 就放弃」改成了「⇒ 重排进防抖队列，过 1/2/3 秒再写」。
⭐ 而**「过一会儿再写」是一句关于未来的承诺**，退出路径正是把未来拿走的那一刻：

  · 退出清理表第 17 步 `save_config_now()` 失败 ⇒ 排一个 1 秒后的 `threading.Timer`
  · 第 18 步跑完、`closeEvent` 返回、事件循环退出、解释器开始收尾
  · `atexit` 的 `_atexit_flush` 看到 `_save_timer` 非空 ⇒ 取消它、**同步再写一次**
  · 那一次要是又失败呢？它会**在解释器收尾期间再起一个 daemon 线程**，
    而那个线程永远等不到它的 1 秒。

## ⛔ 这支探针不许自己抄一份判断逻辑（RN-616）

被测的那一侧必须由产品自己执行：
  · 失败**不是** mock 出来的 —— 探针在**同一进程里真的把 `config.json` 攥住不放**，
    于是 Windows 上 `os.replace` 真的抛 `WinError 5`，走的是产品自己的 `except`；
  · 「有没有落盘」不由探针判断 —— 由**父进程重新读一遍磁盘上的 json** 判断。
⭐ 否则「复现了」这个读数既可能是缺陷、也可能是我抄错了一份逻辑，两者输出一样。

用法（父进程自己跑自己，见 `main`）：
    python scripts/x5_exit_retry_probe.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: 探针改的那一项。挑一个纯标量、没有任何副作用消费者的键。
PROBE_KEY = "music_current_position"
PROBE_VALUE = 1234.5

#: 三条臂。名字就是子进程的 argv[1]。
PATH_NORMAL = "normal"          # 正常退出：事件循环返回 → 解释器收尾 → atexit 跑
PATH_WATCHDOG = "watchdog"      # 15s 看门狗：落盘之后直接 os._exit(0)
PATH_WATCHDOG_OLD = "watchdog_no_sync_retry"  # ⭐ 阳性对照：同上，但把同步重试关掉
#: （`attempts=1` 等价于 RN-624 之前的行为：失败就排一个等不到的 Timer）

#: 占用窗口。⭐ 必须是**瞬时**的 —— 这一族缺陷（RN-613/622/624）的全部前提就是
#: 「杀毒/索引抓一下就放」。长期占用那是磁盘坏了，不该靠重试解决。
HOLD_SECONDS = 0.3

#: 探针和产品之间的接口：退出清理表第 17 步实际调的方法名。
#: ⛔ 探针不许抄产品的逻辑（RN-616），但**必须钉住这个接口** ——
#:   否则产品换了入口，探针会安安静静地去量一个已经没人走的调用点，
#:   并且继续报「复现了」。上一版就是这么坏的：它写死 `save_config_now()`，
#:   而 RN-624 把第 17 步换成了 `save_config_on_exit()`。
EXIT_SAVE_METHOD = "save_config_on_exit"


def _child(mode: str) -> int:
    """子进程：**让产品自己走一遍退出写盘**，然后按 mode 决定怎么死。"""
    from scripts._pristine_config import use_pristine_config_dir

    use_pristine_config_dir(f"x5_exit_retry_{mode}", force=True)

    import config as config_mod

    cfg = config_mod.Config()
    path = config_mod.get_config_path()
    # ⭐ 路径由**子进程报上来**，父进程不自己算一遍 —— 算第二遍就是又抄一份逻辑，
    #   而两份逻辑一旦分叉，父进程会去读一个根本没人写过的文件并报「丢了」。
    print(f"[child:{mode}] CONFIG_PATH={path}", flush=True)

    # 先把基线写干净，确认这条路本来是通的
    setattr(cfg, PROBE_KEY, 0.0)
    cfg.save_config_now()
    assert json.loads(Path(path).read_text(encoding="utf-8"))[PROBE_KEY] == 0.0

    # ⭐ 真的攥住它 —— 不 mock。Windows 上这一把会让 os.replace 抛 WinError 5。
    #   并在 HOLD_SECONDS 之后**自动放开**：模拟杀毒/索引扫完就走。
    holder = open(path, "r+", encoding="utf-8")
    threading.Timer(HOLD_SECONDS, holder.close).start()

    setattr(cfg, PROBE_KEY, PROBE_VALUE)
    # ← 退出清理表第 17 步干的就是这件事。方法名由 EXIT_SAVE_METHOD 钉住。
    saver = getattr(cfg, EXIT_SAVE_METHOD)
    ok = saver(attempts=1) if mode == PATH_WATCHDOG_OLD else saver()

    print(f"[child:{mode}] 第 17 步返回 {ok}；_save_timer="
          f"{cfg._save_timer is not None}，剩余重试={cfg._save_retries_left}",
          flush=True)

    if mode in (PATH_WATCHDOG, PATH_WATCHDOG_OLD):
        # 看门狗：落盘之后 `os._exit(0)`。⚠ 它**不跑 atexit** —— 这正是要量的那一刀。
        os._exit(0)
    return 0    # 正常返回 ⇒ 解释器收尾 ⇒ atexit ⇒ _atexit_flush


def _run(mode: str):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__)), "--child", mode],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )
    cfg_path = None
    for ln in (proc.stdout or "").splitlines():
        print("   " + ln)
        if "CONFIG_PATH=" in ln:
            cfg_path = ln.split("CONFIG_PATH=", 1)[1].strip()
    err = (proc.stderr or "").strip()
    if err:
        print("   [stderr] " + err.splitlines()[-1])

    if cfg_path is None:
        return "⛔ 子进程没报出配置路径", proc.returncode
    path = Path(cfg_path)
    if not path.exists():
        return None, proc.returncode
    try:
        got = json.loads(path.read_text(encoding="utf-8")).get(PROBE_KEY)
    except Exception as exc:
        return f"⛔ 读不出来：{exc}", proc.returncode
    return got, proc.returncode


def _assert_interface_still_matches() -> None:
    """钉住探针与产品之间那个接口：第 17 步真的在调 `EXIT_SAVE_METHOD` 吗。

    ⭐⭐⭐ 这一段是本批现场换来的：探针第一版写死 `save_config_now()`，
    而 RN-624 把第 17 步换成了 `save_config_on_exit()` ——
    于是它去量一个**已经没人走的调用点**，并且一字不差地继续报「复现了」。
    ⇒ **探针不抄产品的逻辑（RN-616），但必须钉住自己和产品之间的那个接口。**
    """
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    import ast

    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Tuple) and len(node.elts) == 2
                and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value == "落盘配置"):
            got = ast.unparse(node.elts[1])
            if EXIT_SAVE_METHOD in got:
                print(f"✅ 接口核对：第 17 步 = {got}")
                return
            raise SystemExit(
                f"⛔ 第 17 步现在是 {got}，而探针量的是 {EXIT_SAVE_METHOD}() —— "
                "先把 EXIT_SAVE_METHOD 改对，再看下面的读数。")
    raise SystemExit("⛔ 退出清理表里找不到「落盘配置」这一步。")


def main() -> int:
    print("=" * 72)
    print("X5 探针 · 重试定时器撞上退出（RN-622 → RN-624）")
    print("=" * 72)
    _assert_interface_still_matches()
    results = {}
    for mode in (PATH_NORMAL, PATH_WATCHDOG_OLD, PATH_WATCHDOG):
        print(f"\n── 退出路径：{mode} ──")
        got, rc = _run(mode)
        landed = (got == PROBE_VALUE)
        results[mode] = landed
        print(f"   磁盘上读到 {PROBE_KEY} = {got!r}（期望 {PROBE_VALUE}）"
              f" ⇒ {'✅ 落盘了' if landed else '⛔ 丢了'}（子进程 rc={rc}）")

    print("\n" + "=" * 72)
    old, new = results.get(PATH_WATCHDOG_OLD), results.get(PATH_WATCHDOG)
    if not old and new:
        print("⇒ ✅ RN-624 成立且已修好：**同一条看门狗路径**，关掉同步重试就丢、"
              "开着就落盘。⭐ 阳性对照与被测项只差这一个开关，别的一模一样。")
    elif old and new:
        print("⇒ ⚠ 阳性对照**也落盘了** —— 那这一轮什么都没证明："
              "占用窗口可能太短，或者产品在别处又兜了一次。先修对照再看结论。")
    else:
        print(f"⇒ ⛔ 读数反常：对照={old} 被测={new}，回去看子进程日志。")
    if not results.get(PATH_NORMAL):
        print("⇒ ⛔ 而**正常退出这条路也没兜住** —— 那是比看门狗更严重的一件事。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        raise SystemExit(_child(sys.argv[2]))
    raise SystemExit(main())
