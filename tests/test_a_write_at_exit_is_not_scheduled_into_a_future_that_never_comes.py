# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-624（批 87 · X5）：**重试是一句关于未来的承诺，而退出正是把未来拿走的那一刻。**

RN-622（上一批）把「写盘失败 ⇒ 记一行 ERROR 就放弃」改成了
「⇒ 排一个 1 秒后的 `threading.Timer`，过一会儿再写」。运行期这是对的。

⭐⭐⭐ 而退出路径上，「过一会儿」这三个字的兑现概率，取决于是谁在关这个进程：

| 退出路径 | 排好的 daemon Timer 会怎样 |
|---|---|
| 正常退出 | atexit 的 `_atexit_flush` 看到它、取消它、同步再写一次 ⇒ **兜住了** |
| 15s 看门狗 | `os._exit(0)` **不跑 atexit** ⇒ 连同线程一起蒸发 ⇒ **丢** |
| `taskkill /f` | 什么都不跑（`core/shutdown.py` 的文档自己写明不覆盖） |

⇒ 修法不是「多重试几次」（RN-622 已经那么干过了，而那正是这条的来路），
是**把退出路径上的重试改成同步的**：`Config.save_config_on_exit()`。

## 实测（`scripts/x5_exit_retry_probe.py`，三条臂，真的攥住 config.json 不 mock）

  · normal                     ⇒ 读回 1234.5 ✅
  · watchdog + 同步重试**关**  ⇒ 读回 0.0 ⛔   ← 阳性对照（= RN-624 之前的行为）
  · watchdog + 同步重试**开**  ⇒ 读回 1234.5 ✅

⭐ 阳性对照和被测项只差 `attempts=1` 这一个开关，别的一模一样。

## ⛔ 这份判据刻意避开的坑

不 monkeypatch `_do_save_config` 自己 —— 被测的就是它（RN-616）。
造「写盘失败」只能从它依赖的那一层（`core.io_validation.os.replace`）下手，
和 RN-622 那份判据同一个做法。
"""
from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest

import config as C

ROOT = Path(__file__).resolve().parents[1]

#: `replace_with_retry` 自己会试 5 次；再多失败一次就把退避用尽。
_EXHAUSTS_THE_BACKOFF = 6


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "logs"))
    obj = C.Config()
    obj.config_file = str(tmp_path / "config.json")
    obj.save_config_now()
    yield obj
    with obj._save_lock:
        if obj._save_timer is not None:
            obj._save_timer.cancel()
            obj._save_timer = None


class _ReplaceThatFailsNTimes:
    """前 n 次把 `os.replace` 打成 PermissionError，之后放行真实现。"""

    def __init__(self, n, real):
        self.left, self.real, self.attempts = n, real, 0

    def __call__(self, src, dst):
        self.attempts += 1
        if self.left > 0:
            self.left -= 1
            raise PermissionError(13, "拒绝访问（判据造的）")
        return self.real(src, dst)


def _install_failing_replace(monkeypatch, fail_times):
    import core.io_validation as io_val

    fake = _ReplaceThatFailsNTimes(fail_times, io_val.os.replace)
    monkeypatch.setattr(io_val.os, "replace", fake)
    return fake


def _on_disk(cfg):
    return json.loads(Path(cfg.config_file).read_text(encoding="utf-8"))


# ------------------------------------------------------- 行为：退出路径不排队

def test_a_transient_lock_at_exit_is_survived_without_scheduling_anything(cfg, monkeypatch):
    """瞬时占用 ⇒ 同步重试当场把它写进去，且**不留下任何定时器**。

    ⭐ 「不留下定时器」是这一条的要害，不是顺带的：留下了就等于又把结果
    押在「这个进程还能活到那时候」上，而调用它的正是准备 `os._exit` 的那一位。
    """
    _install_failing_replace(monkeypatch, _EXHAUSTS_THE_BACKOFF)
    cfg.kill_sound_enabled = not _on_disk(cfg)["kill_sound_enabled"]

    assert cfg.save_config_on_exit() is True, (
        "退出时写盘失败了一次就放弃了 —— 而占用是瞬时的，再试一次就能成。")
    assert cfg._save_timer is None, (
        "退出路径上排了一个定时器。调用它的那一位下一行就是 `os._exit(0)`，"
        "那一刀连 atexit 都不跑 —— 这个定时器永远等不到它的那一秒。")
    assert _on_disk(cfg)["kill_sound_enabled"] == cfg.kill_sound_enabled


def test_the_exit_retry_budget_is_bounded_and_it_says_so(cfg, monkeypatch):
    """⛔ 看门狗开火的前提是清理已经卡了 15 秒 —— 它的职责是**保证关得掉**。

    所以这一档必须有上限，而且上限要小。这里量两样：真的会停，且停在预算内。
    """
    fake = _install_failing_replace(monkeypatch, 10 ** 6)   # 永远失败
    cfg.kill_sound_enabled = not _on_disk(cfg)["kill_sound_enabled"]

    t0 = time.monotonic()
    assert cfg.save_config_on_exit() is False
    elapsed = time.monotonic() - t0

    assert cfg._save_timer is None, "都放弃了还排了个定时器。"
    budget = C._EXIT_SAVE_ATTEMPTS * (C._EXIT_SAVE_DELAY_S + 1.0)
    assert elapsed < budget, (
        f"退出时同步重试花了 {elapsed:.2f}s，超过 {budget:.2f}s 的预算 —— "
        "看门狗正等着关掉这个进程，它不能被写盘无限期拖住。")
    assert fake.attempts >= C._EXIT_SAVE_ATTEMPTS, (
        f"只试了 {fake.attempts} 次 `os.replace`，"
        f"说明 {C._EXIT_SAVE_ATTEMPTS} 轮同步重试没有真的跑完。")


def test_the_exiting_flag_is_restored_even_when_every_attempt_fails(cfg, monkeypatch):
    """⛔ `_exiting` 是个开关，留在 True 上就等于**永久关掉运行期的重试**。

    同一个 Config 实例在测试里会被反复用；产品里托盘「进托盘」之后窗口还能再开。
    """
    _install_failing_replace(monkeypatch, 10 ** 6)
    cfg.save_config_on_exit()
    assert cfg._exiting is False, (
        "`_exiting` 没还原 —— 之后每一次运行期写盘失败都不会再排重试了，"
        "而那正是 RN-622 修好的那件事。")


def test_the_runtime_path_still_schedules_a_retry(cfg, monkeypatch):
    """阳性对照：不在退出路径上时，RN-622 那条异步重试**必须还在**。

    ⭐ 少了这一支，上面三条可以靠「把重试整个删掉」全部变绿。
    """
    _install_failing_replace(monkeypatch, _EXHAUSTS_THE_BACKOFF)
    cfg.kill_sound_enabled = not _on_disk(cfg)["kill_sound_enabled"]
    cfg._do_save_config()
    assert cfg._save_timer is not None, (
        "运行期写盘失败之后没有排重试 —— RN-622 被改没了。")


# ------------------------------------------------------- 接线：三个调用点

def _calls_in(qualname: str, src: str) -> set[str]:
    """取某个函数体里所有 `xxx.name()` 的方法名。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == qualname:
            return {n.func.attr for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    raise AssertionError(f"找不到函数 {qualname}")


@pytest.mark.parametrize("where, fn, src_file", [
    ("15s 看门狗", "_watchdog_fire", "gui_widget.py"),
    ("atexit 兜底", "_atexit_flush", "config.py"),
])
def test_every_exit_path_saver_is_the_synchronous_one(where, fn, src_file):
    """⭐⭐⭐ 这一支才是守住 RN-624 的那一支。

    上面那些行为判据量的是 `save_config_on_exit` 本身对不对；
    **而缺陷是「退出路径调的是另一个方法」** —— 那个方法自己一点毛病没有。
    ⭐ 一个正确的函数被从错误的地方调用，在任何行为判据下都是绿的。
    """
    src = (ROOT / src_file).read_text(encoding="utf-8")
    calls = _calls_in(fn, src)
    assert "save_config_on_exit" in calls, (
        f"{where}（{src_file}::{fn}）没走同步落盘。它现在调的是 {sorted(calls)}。")
    assert "save_config_now" not in calls, (
        f"{where} 还在调 `save_config_now()` —— 它失败时排一个 1 秒后的 daemon Timer，"
        "而这条路上根本没有那一秒。")


def test_the_shutdown_table_saves_the_config_synchronously():
    """退出清理表第 17 步「落盘配置」同上。"""
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Tuple) and len(node.elts) == 2
                and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value == "落盘配置"):
            got = ast.unparse(node.elts[1])
            assert "save_config_on_exit" in got, (
                f"退出清理表的「落盘配置」这一步现在是 {got} —— 见本文件开头那张表。")
            return
    raise AssertionError("退出清理表里找不到「落盘配置」这一步。")
