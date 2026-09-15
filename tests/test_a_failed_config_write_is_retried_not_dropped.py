# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-622：`replace_with_retry` **退避用尽之后**那一格，此前一个字都没动。

## 这条是怎么被量出来的（RN-617 查到第三次的副产物）

RN-617 立案时写的是「快照恢复与防抖保存之间没有共享锁 ⇒ 盘上会出现新旧混杂的配置」。
批 85 两次随机复现都失败（窗口只有几十微秒）。本批不再赛跑，改成**编排时序**
（`scripts/x4_probe_restore_race_orchestrated.py`）：把 `_load_plain` 包一层，
在 `load_config` 走到第 6 段时按住，让 `_do_save_config` 在另一线程整段跑完再放行。

编排当场成功了，而**跑出来的不是 RN-617 预言的那件事**：

  ⭐⭐⭐ `load_config` 的 `with open(config_path) as f:` **包住了 500 行赋值**，
  读句柄全程开着（实测整个 `load_config` 中位 **0.6 ms**）。
  Windows 上，另一个句柄开着时 `os.replace` 必然 `WinError 5` ⇒
  **那份「新旧混杂」的配置根本落不了盘**。

⇒ RN-617 说的坏结局**在 Windows 上结构性地发生不了**，而它是被一个**顺带的**
副作用挡住的（没有人是为了这个才那么写 `with` 的）。
⭐ 但真正的代价换了个样子露出来：**那一次保存被整个丢掉了** ——
`replace_with_retry` 五次退避（实测 267 ms）全撞在同一个句柄上，
然后走 `except`：记一行日志、删掉临时文件、**什么都不做**。

⭐⭐⭐ **RN-613 把「一次就放弃」改成了「五次才放弃」——而「放弃」那一格的代码一个字没改。**
落到用户身上还是那句话：「改了设置，重启又变回去了」（RN-613 / RN-619 同款症状）。

## 这份判据刻意避开的坑

⛔ 不 monkeypatch `_do_save_config` 自己 —— 被测的就是它（RN-616 的教训）。
   要造「写盘失败」，只能从**它依赖的那一层**（`os.replace`）下手。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import config as C


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "logs"))
    obj = C.Config()
    obj.config_file = str(tmp_path / "config.json")
    obj.save_config_now()
    yield obj
    # 别把定时器留给下一个用例（重试是真的会排 Timer 的）
    with obj._save_lock:
        if obj._save_timer is not None:
            obj._save_timer.cancel()
            obj._save_timer = None


class _ReplaceThatFailsNTimes:
    """前 n 次把 `os.replace` 打成 PermissionError，之后放行真实现。

    ⚠ 打的是 `core.io_validation` 里那个 `os` —— `replace_with_retry` 就住在那儿；
    打 `config.os` 没用（`config.py` 是 `from core.io_validation import replace_with_retry`）。
    """

    def __init__(self, n, real):
        self.left = n
        self.real = real
        self.attempts = 0

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


def _wait_until(pred, timeout=12.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _on_disk(cfg):
    return json.loads(Path(cfg.config_file).read_text(encoding="utf-8"))


#: `replace_with_retry` 自己会试 5 次；再多失败一次就把退避用尽。
_EXHAUSTS_THE_BACKOFF = 6


def test_a_write_that_exhausts_the_backoff_is_retried_and_eventually_lands(
    cfg, monkeypatch
):
    """退避用尽 ⇒ 必须排一次「过一会儿再来」，而且那一次要真的把值写进去。"""
    _install_failing_replace(monkeypatch, _EXHAUSTS_THE_BACKOFF)

    cfg.kill_sound_enabled = not _on_disk(cfg)["kill_sound_enabled"]
    want = cfg.kill_sound_enabled
    cfg._do_save_config()          # 第一趟：必然失败（退避 5 次全被打掉）

    assert _on_disk(cfg)["kill_sound_enabled"] != want, "（前提）第一趟确实没写进去"
    assert cfg._save_timer is not None, (
        "写盘失败之后没有排重试 —— 这次改动就丢了。\n"
        "⭐ `replace_with_retry` 只把「一次就放弃」变成「五次才放弃」，"
        "放弃那一格要由这里兜住。")

    assert _wait_until(lambda: _on_disk(cfg)["kill_sound_enabled"] == want), (
        f"重试排了，但值始终没落盘（盘上仍是 "
        f"{_on_disk(cfg)['kill_sound_enabled']}，想写的是 {want}）")


def test_without_the_retry_the_change_would_simply_be_gone(cfg, monkeypatch):
    """⭐ 阳性对照：证明上一条的绿来自重试，而不是「反正它自己会好」。

    把重试额度按成 0（＝ RN-622 之前的行为），同样的失败次数之后，
    盘上必须**还是旧值**，并且**不许**有定时器在排队。
    """
    _install_failing_replace(monkeypatch, _EXHAUSTS_THE_BACKOFF)
    cfg._save_retries_left = 0

    before = _on_disk(cfg)["kill_sound_enabled"]
    cfg.kill_sound_enabled = not before
    cfg._do_save_config()

    assert _on_disk(cfg)["kill_sound_enabled"] == before, (
        "（前提）这一轮本来就该失败")
    assert cfg._save_timer is None, "额度用尽还在排重试 —— 上限是假的"
    time.sleep(0.4)
    assert _on_disk(cfg)["kill_sound_enabled"] == before, (
        "⛔ 这就是 RN-622 之前的结局：用户刚改的那一项静默消失")


def test_the_retry_budget_is_bounded(cfg, monkeypatch):
    """磁盘真的坏了的时候，不许变成一条永不停的定时器链。"""
    fake = _install_failing_replace(monkeypatch, 10_000)  # 永远失败
    monkeypatch.setattr(C, "_SAVE_RETRY_DELAY_S", 0.05)   # 别让判据真的等 6 秒

    cfg.kill_sound_enabled = not cfg.kill_sound_enabled
    cfg._do_save_config()
    # ⚠ 不能只等 `_save_timer is None`：两趟之间它会被 RN-616 那段清一下再重排，
    #   于是「暂时是 None」和「不再重排了」在那个条件上读数相同。
    assert _wait_until(
        lambda: cfg._save_retries_left == 0 and cfg._save_timer is None,
        timeout=25,
    ), f"重试没有停下来（还剩 {cfg._save_retries_left} 次）—— 额度上限没起作用"
    # 每一趟 = `replace_with_retry` 的 5 次；总趟数 = 1 + 额度
    expected_rounds = 1 + C._SAVE_RETRIES_ON_FAILURE
    assert fake.attempts <= expected_rounds * 5 + 5, (
        f"试的次数（{fake.attempts}）超出了额度能解释的范围")


def test_a_successful_write_restores_the_budget(cfg, monkeypatch):
    """写成功要把额度还原 —— 否则第二次遇到扫描窗口时就没有重试了。"""
    _install_failing_replace(monkeypatch, _EXHAUSTS_THE_BACKOFF)
    cfg.kill_sound_enabled = not cfg.kill_sound_enabled
    want = cfg.kill_sound_enabled
    cfg._do_save_config()
    assert _wait_until(lambda: _on_disk(cfg)["kill_sound_enabled"] == want)
    assert _wait_until(
        lambda: cfg._save_retries_left == C._SAVE_RETRIES_ON_FAILURE), (
        f"写成功之后额度还是 {cfg._save_retries_left}，没还原")


def test_the_retry_does_not_deadlock_on_the_save_lock(cfg, monkeypatch):
    """⛔ 重排定时器时**不许**调 `save_config()`。

    `_save_lock` 是不可重入的 `threading.Lock()`，而失败分支正握着它 ⇒
    调 `save_config()` 会当场死锁（RN-617 排除掉的那条修法同款）。
    这条用「在别的线程里跑，超时即判死锁」来量，而不是读源码。
    """
    _install_failing_replace(monkeypatch, _EXHAUSTS_THE_BACKOFF)
    cfg.kill_sound_enabled = not cfg.kill_sound_enabled

    done = threading.Event()
    t = threading.Thread(target=lambda: (cfg._do_save_config(), done.set()))
    t.daemon = True
    t.start()
    assert done.wait(8), (
        "`_do_save_config` 的失败分支没在 8 秒内返回 —— 极可能是把 "
        "`_save_lock` 又要了一遍（它不可重入）")


def test_load_config_holding_the_file_open_is_what_makes_this_reachable():
    """⭐ 把「为什么这条会发生」钉成判据，而不是留在注释里。

    `load_config` 的 `with open(...)` 包住了整段赋值 ⇒ 读句柄开着的时间 ≈ 整个
    `load_config`；这期间任何 `os.replace` 在 Windows 上都会 `WinError 5`。
    ⚠ 哪天有人把这个 `with` 收窄（那是件好事），这条会红 —— 那时要回头确认：
    RN-617 说的「新旧混杂落盘」**会不会因此变得可达**（现在挡住它的是这个句柄，
    而那纯属顺带，没有人是为了这个才这么写的）。
    """
    import ast
    import io

    src = io.open(Path(C.__file__).with_name("config.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "load_config")
    withs = [n for n in ast.walk(fn)
             if isinstance(n, ast.With)
             and any(isinstance(it.context_expr, ast.Call)
                     and getattr(it.context_expr.func, "id", "") == "open"
                     for it in n.items)]
    assert withs, "`load_config` 里找不到 `with open(...)` —— 这条判据的前提变了"
    span = max(w.end_lineno - w.lineno for w in withs)
    assert span > 100, (
        f"`load_config` 的 `with open(...)` 只剩 {span} 行了（曾经 400+）。\n"
        "⇒ 这是件好事，但请回头确认 RN-617「恢复期间落下新旧混杂的配置」"
        "会不会因此变得可达 —— 此前挡住它的正是这个一直开着的读句柄。")
