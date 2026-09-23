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
import os
import threading
import time
from pathlib import Path

import pytest

import config as C


#: 单例排着的防抖保存会落进本用例目录 —— 冲刷挪到了共用件，conftest 每个用例前调一次。
#: ⚠ `self.config_file` 是判据自己挂的属性，产品不读它；产品只认 `get_config_path()`。
from _config_isolation import flush_config_singletons_pending_save as _flush_the_singletons_pending_save  # noqa: E402


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

    `landed`：真的 replace 成功落到 `target` 上时置位。判据等它，**不去轮询盘上的文件**。
    ⛔ 以前是 `_wait_until(lambda: _on_disk(cfg)...)` 每 20ms 打开一次**产品正在
       os.replace 的那个文件** —— Windows 上两边互撞：读句柄开着时 replace 被拒
       （扰动了被测对象），replace 进行时读又被拒（判据自己红）。
       并行 6 路连跑 120 次复现 9 次 PermissionError（2026-09-23，全在轮询那一行）。
    """

    def __init__(self, n, real, target=None, owner=None):
        self.owner = owner
        self.left = n
        self.real = real
        self.attempts = 0
        self.target = os.path.normcase(os.path.abspath(target)) if target else None
        self.landed = threading.Event()
        self.log = []          # 每一次 replace：哪个线程、带的是什么值、结果 —— 红了时贴出来

    def __call__(self, src, dst):
        writer = _which_config_is_writing(self.owner)
        entry = {"thread": threading.current_thread().name, "value": _peek(src), "writer": writer}
        self.log.append(entry)
        if self.owner is not None and writer != _OWNER:
            # 别的写者：不许吃判据造的失败、也不许冒充「被测对象落盘了」，照实放行并记账
            entry["result"] = "foreign, passed through"
            return self.real(src, dst)
        self.attempts += 1
        if self.left > 0:
            self.left -= 1
            entry["result"] = "injected failure"
            raise PermissionError(13, "拒绝访问（判据造的）")
        try:
            result = self.real(src, dst)
        except OSError as e:
            entry["result"] = f"real {type(e).__name__}"
            raise
        entry["result"] = "ok"
        if self.target is None or os.path.normcase(os.path.abspath(dst)) == self.target:
            self.landed.set()
        return result


def _peek(src):
    try:
        return json.loads(Path(src).read_text(encoding="utf-8")).get("kill_sound_enabled")
    except Exception as e:                       # 诊断用，读不到也别影响被测路径
        return f"<unreadable {type(e).__name__}>"


_OWNER = "被测 cfg"


def _which_config_is_writing(owner):
    """沿调用栈找正在写盘的那个 Config 实例（`_do_save_config` 帧里的 self）。"""
    import sys

    f = sys._getframe(1)
    while f is not None:
        if f.f_code.co_name == "_do_save_config":
            obj = f.f_locals.get("self")
            if owner is not None and obj is owner:
                return _OWNER
            if obj is getattr(C, "config", None):
                return "模块单例 config.config"
            return f"别的 Config id={id(obj)}"
        f = f.f_back
    return "不是 _do_save_config"


def _install_failing_replace(monkeypatch, fail_times, target=None, owner=None):
    import core.io_validation as io_val

    fake = _ReplaceThatFailsNTimes(fail_times, io_val.os.replace, target=target, owner=owner)
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
    """⚠ 只在**没有写盘正在进行**时调（见 _ReplaceThatFailsNTimes.landed）。"""
    return json.loads(Path(cfg.config_file).read_text(encoding="utf-8"))


def _on_disk_after_landing(cfg, fake, timeout=12.0):
    """等产品那次真的 replace 落盘，再读**一次**盘上的值。

    落盘之后不会再有并发写，所以这一次读不和被测对象互撞。仍给外部扫描程序
    （杀软/索引）留 1 秒有界重试 —— 那是判据控制不了的；超过 1 秒照样抛出，
    不会把一个持续打不开的文件读成「没问题」。
    """
    assert fake.landed.wait(timeout), (
        f"{timeout}s 内产品没有一次成功的 replace 落到 {cfg.config_file} —— 重试没把值写进去")
    deadline = time.monotonic() + 1.0
    while True:
        try:
            return _on_disk(cfg)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


#: `replace_with_retry` 自己会试 5 次；再多失败一次就把退避用尽。
_EXHAUSTS_THE_BACKOFF = 6


def test_a_write_that_exhausts_the_backoff_is_retried_and_eventually_lands(
    cfg, monkeypatch
):
    """退避用尽 ⇒ 必须排一次「过一会儿再来」，而且那一次要真的把值写进去。"""
    fake = _install_failing_replace(
        monkeypatch, _EXHAUSTS_THE_BACKOFF, target=cfg.config_file, owner=cfg)

    cfg.kill_sound_enabled = not _on_disk(cfg)["kill_sound_enabled"]
    want = cfg.kill_sound_enabled
    cfg._do_save_config()          # 第一趟：必然失败（退避 5 次全被打掉）

    assert _on_disk(cfg)["kill_sound_enabled"] != want, "（前提）第一趟确实没写进去"
    assert cfg._save_timer is not None, (
        "写盘失败之后没有排重试 —— 这次改动就丢了。\n"
        "⭐ `replace_with_retry` 只把「一次就放弃」变成「五次才放弃」，"
        "放弃那一格要由这里兜住。")

    landed = _on_disk_after_landing(cfg, fake)["kill_sound_enabled"]
    assert landed == want, (
        f"重试写盘了，但落下的不是这次的改动（盘上是 {landed}，想写的是 {want}）\n"
        f"每次 replace 的账：{fake.log}")


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
    fake = _install_failing_replace(
        monkeypatch, _EXHAUSTS_THE_BACKOFF, target=cfg.config_file, owner=cfg)
    cfg.kill_sound_enabled = not cfg.kill_sound_enabled
    want = cfg.kill_sound_enabled
    cfg._do_save_config()
    assert _on_disk_after_landing(cfg, fake)["kill_sound_enabled"] == want
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


def test_the_singletons_pending_save_cannot_land_in_this_tests_directory(tmp_path, monkeypatch):
    """模块单例排着的防抖保存，不许在 setenv 之后到点、写进用例的目录。

    ⭐ 夹具里 `_flush_the_singletons_pending_save()` 守的就是这件事；去掉它，
      第一个用例只会**偶尔**红（取决于单例的 0.5s 定时器赶没赶上）—— 回退验证
      证不了一件偶尔发生的事，所以这里把时序钉死：先排一个保存，再切目录，
      等过防抖时长，看它落没落进来。
    """
    C.config.save_config()                      # 单例排一个 0.5s 的防抖保存
    _flush_the_singletons_pending_save()
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    time.sleep(1.2)                             # 比防抖时长多出一倍余量
    assert not (tmp_path / "config.json").exists(), (
        "单例的防抖保存在切目录之后到点，把它的状态写进了本用例的 config.json —— "
        "_do_save_config 写的是 get_config_path()（调用时读环境变量），不是 self.config_file")


def test_no_poll_here_opens_the_file_the_product_is_replacing():
    """判据自己的轮询不许打开产品正在 os.replace 的那个文件。

    ⭐ 这份判据量的正是「句柄开着 ⇒ os.replace 被拒」（见下一条）—— 而它自己的
      `_wait_until(lambda: _on_disk(cfg)...)` 就是那样一个句柄：轮询时两边互撞，
      判据间歇红（并行 6 路 120 次里 9 次），还顺手扰动了被测的重试。
    ⇒ 等写盘用 `fake.landed`，落盘后再读一次（`_on_disk_after_landing`）。
    """
    import ast
    import inspect
    import sys

    tree = ast.parse(inspect.getsource(sys.modules[__name__]))
    offenders, scanned = [], 0
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_wait_until"):
            continue
        scanned += 1
        for arg in call.args[:1]:
            if any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_on_disk"
                   for n in ast.walk(arg)):
                offenders.append(call.lineno)
    # 分母：本文件还有两处 _wait_until（等额度，不碰盘）。一处都没扫到 = 扫描器坏了，别算通过
    assert scanned >= 2, f"只扫到 {scanned} 处 _wait_until —— 扫描器没看见东西，下面的「没有」不算数"
    assert not offenders, (
        f"第 {offenders} 行在 _wait_until 里轮询 _on_disk —— 读句柄会和产品的 "
        "os.replace 互撞（判据间歇红 + 扰动被测对象）。改用 fake.landed。")


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
