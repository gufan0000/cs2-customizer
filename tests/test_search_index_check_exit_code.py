# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""`build_search_index.py --check` 的**退出码**判据（2026-08-14）。

背景是一次真实的静默放行：新增 fun_afterlife 页之后跑 `--check`，脚本把
「索引与代码不同步 / 新增 24 条」一字不差地打印了出来，**进程却按 0 退出**。
文案是给人看的，退出码才是给 CI 看的——两者不一致时，门禁等于不存在。

缺陷不在 `_emit` 的 return（那里一直是 1），而在它**后面**那段收尾：
`teardown()` 走产品自己的窗口关闭链路，那条路上有两处会替脚本决定退出码——
`gui_widget._run_shutdown_steps` 的 15s 看门狗 `os._exit(0)`，
以及 `core/shutdown` 信号处理器兜底的 `sys.exit(0)`（SystemExit 不是
Exception，`teardown` 的 `except Exception` 兜不住，会绕过 `sys.exit(main())`）。
两条都只在**特定收尾路径**上触发，所以它是间歇的——更该用判据钉死。

**判据分两层，缺一层都不算钉住**：

* 函数层：`_emit` / `main()` 的返回值对不对。快，但它证明不了"进程真按这个码退出"
  ——这次的缺陷恰恰就发生在返回值正确之后。
* 进程层：真起一个子进程，读它的 `returncode`。这才是 CI 实际读的那个数。
  子进程里把两条重通道（`build` / `teardown`）替换成桩，所以不建 27 个页面、
  不碰 Qt，整个文件 1 秒内跑完。

（本项目测试逐文件跑：`python -m pytest tests/test_search_index_check_exit_code.py`）
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_search_index as bsi  # noqa: E402


# ---------------------------------------------------------------- 夹具

def _fake_payload(items=(("basic", "观战静音"),)):
    """一个形状够用的最小 payload：`_emit` 只碰 items 和整体序列化结果。"""
    return {
        "schema": 1,
        "generated_by": "scripts/build_search_index.py",
        "pages": {"basic": "基础设置"},
        "coverage": {"runtime_pages": ["basic"], "static_pages": ["basic"],
                     "runtime_skipped": [], "total_pages": 1},
        "generic_dropped": [],
        "items": [{"page": p, "text": t, "card": "", "tab": "",
                   "kind": "check", "src": "runtime"} for p, t in items],
    }


class _Args:
    def __init__(self, check=True, stats=False, cross_check=False):
        self.check = check
        self.stats = stats
        self.cross_check = cross_check
        self.include_unsafe = False


@pytest.fixture()
def index_at(tmp_path, monkeypatch):
    """把 OUT_PATH 指到临时文件，绝不碰真的 core/search_index.json。"""
    path = tmp_path / "search_index.json"
    monkeypatch.setattr(bsi, "OUT_PATH", path)

    def write(payload):
        path.write_text(bsi.dumps(payload), encoding="utf-8")
        return path

    write.path = path
    return write


# ---------------------------------------------------------------- 函数层

def test_in_sync_is_zero(index_at):
    payload = _fake_payload()
    index_at(payload)
    assert bsi._emit(_Args(), payload, [], [], set()) == 0


def test_drift_is_one(index_at):
    """磁盘上少一条 = 不同步。这正是"改了页面文案没重跑生成器"的形状。"""
    index_at(_fake_payload([("basic", "观战静音")]))
    fresh = _fake_payload([("basic", "观战静音"), ("basic", "按地图切换预设")])
    assert bsi._emit(_Args(), fresh, [], [], set()) == 1


def test_missing_index_file_is_one(index_at, tmp_path, monkeypatch):
    monkeypatch.setattr(bsi, "OUT_PATH", tmp_path / "nope.json")
    assert bsi._emit(_Args(), _fake_payload(), [], [], set()) == 1


def test_environment_failure_is_two(monkeypatch, capsys):
    """没 PySide6 / 起不来 QApplication ⇒ 2，**不能**跟"不同步"共用 1。

    共用的话 CI 上一条 traceback 退出码 1 看起来就跟真漂移一样，
    把人往"去重跑生成器"上引，而生成器在那台机器上根本跑不起来。
    """
    def _boom(*_a, **_k):
        raise bsi.EnvironmentUnavailable("PySide6 不可用：no module")

    monkeypatch.setattr(bsi, "build", _boom)
    monkeypatch.setattr(sys, "argv", ["build_search_index.py", "--check"])
    assert bsi.main() == 2
    assert "环境不满足" in capsys.readouterr().out


def test_teardown_raising_systemexit_cannot_launder_the_code(index_at, monkeypatch):
    """收尾里的 `sys.exit(0)` 不许把 1 冲掉。

    SystemExit 继承 BaseException，`teardown()` 原来的 `except Exception`
    兜不住它——它会一路穿出 main()，`sys.exit(main())` 根本轮不到执行。
    """
    index_at(_fake_payload([("basic", "观战静音")]))
    fresh = _fake_payload([("basic", "观战静音"), ("basic", "按地图切换预设")])

    monkeypatch.setattr(bsi, "build", lambda *a, **k: (fresh, [], [], set(), ("win", "app")))
    monkeypatch.setattr(bsi, "teardown", lambda _h: sys.exit(0))
    monkeypatch.setattr(sys, "argv", ["build_search_index.py", "--check"])
    assert bsi.main() == 1


def test_teardown_calling_os_exit_zero_gets_our_code(monkeypatch):
    """收尾里的 `os._exit(0)`（退出看门狗）必须被改判成脚本自己的码。

    这条是行为判据：真让桩去调 `os._exit(0)`，看落到底层的参数是几。
    断言"源码里有那个 lambda"会被一句 `pass` 骗过。
    """
    seen = []
    monkeypatch.setattr(bsi.os, "_exit", lambda status: seen.append(status))
    monkeypatch.setattr(bsi, "teardown", lambda _h: bsi.os._exit(0))

    bsi._teardown_guarded(("win", "app"), 1)
    assert seen == [1], f"看门狗的 0 没被改判：{seen}"


def test_teardown_never_asks_the_user_what_to_do(monkeypatch):
    """收尾不许走产品的"关闭时问一下"分支——那是个真的模态框，会把脚本挂住。

    2026-08-14 现场：`--check` 结论都打印完了，进程停在一个标题「关闭 CS2 Customizer 」
    的可见窗口上不退。对门禁来说"没有退出码"和"退出码错了"一样坏。
    走不走这条分支取决于托盘图标建没建好，所以它是间歇的——更要钉死。
    """
    class _FakeWin:
        _force_exit = False
        closed = False

        def close(self):
            assert self._force_exit, "close() 之前没置 _force_exit，会弹模态框问用户"
            self.closed = True

        def deleteLater(self):
            pass

    class _FakeApp:
        def processEvents(self):
            pass

    win = _FakeWin()
    bsi.teardown((win, _FakeApp()))
    assert win._force_exit is True
    assert win.closed is True


def test_teardown_that_hangs_still_exits_with_our_code(monkeypatch):
    """清理卡死时，超时兜底必须带着**既得结论**退出，而不是无限等。"""
    seen = []
    monkeypatch.setattr(bsi.os, "_exit", lambda status: seen.append(status))
    monkeypatch.setattr(bsi, "TEARDOWN_TIMEOUT_SEC", 0.2)

    started = threading.Event()

    def _hang(_h):
        started.set()
        time.sleep(2.0)          # 模拟停在模态框/阻塞的清理步骤上

    monkeypatch.setattr(bsi, "teardown", _hang)
    bsi._teardown_guarded(("win", "app"), 1)
    assert started.is_set()
    assert seen and seen[0] == 1, f"超时兜底没带上退出码：{seen}"


def test_timeout_is_wider_than_the_product_watchdog():
    """兜底超时要明显宽于产品自己那条 15s 退出看门狗。

    压得比它窄，正常清理会被我们先杀掉——看起来就像"清理总是超时"，
    真正的清理步骤（停 GSI 服务、落盘）反而永远跑不完。
    """
    assert bsi.TEARDOWN_TIMEOUT_SEC > 15.0


def test_guard_puts_os_exit_back(monkeypatch):
    """接管是临时的：清理跑完必须把 os._exit 还回去，别污染同进程后续代码。"""
    sentinel = object()
    monkeypatch.setattr(bsi.os, "_exit", sentinel)
    monkeypatch.setattr(bsi, "teardown", lambda _h: None)

    bsi._teardown_guarded(("win", "app"), 1)
    assert bsi.os._exit is sentinel


# ---------------------------------------------------------------- 进程层

_DRIVER = r"""
import json, os, sys
sys.path.insert(0, r"{scripts}")
import build_search_index as bsi

bsi.OUT_PATH = __import__("pathlib").Path(r"{index}")

PAYLOAD = json.loads(r'''{payload}''')
bsi.build = lambda *a, **k: (PAYLOAD, [], [], set(), ("win", "app"))
{build_override}
bsi.teardown = {teardown}

sys.argv = ["build_search_index.py", "--check"]

# ⚠ 这里**不能**写死 `bsi._hard_exit(bsi.main())`。回退验证时（把脚本换回修复前
# 的版本）那个名字不存在，驱动会以 AttributeError 崩掉、退出码正好是 1 ——
# 于是所有"期望 1"的用例都会**因为崩溃而变绿**，判据整片失效。
# 改成：有硬退出助手就用它，没有就退回经典的 `sys.exit(main())` 入口写法。
# 这样每条用例都是因为**自己那件事**红的，而不是因为驱动对不上号。
code = bsi.main()
sys.stdout.flush()
_hard = getattr(bsi, "_hard_exit", None)
if _hard is not None:
    _hard(code)
sys.exit(code)
"""


def _run_driver(tmp_path, on_disk, fresh, teardown_src, build_override=""):
    """起真子进程跑完整 main()+退出路径，返回 (returncode, 输出)。

    两条重通道被替换成桩，所以不建 Qt 窗口——但 `_emit`、`_teardown_guarded`、
    `_hard_exit` 全是真的，退出码走的就是 CI 读到的那条路。
    """
    index = tmp_path / "search_index.json"
    if on_disk is not None:
        index.write_text(bsi.dumps(on_disk), encoding="utf-8")
    src = _DRIVER.format(
        scripts=ROOT / "scripts",
        index=index,
        payload=json.dumps(fresh, ensure_ascii=False),
        teardown=teardown_src,
        build_override=build_override,
    )
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(src), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(driver)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def test_process_exit_code_is_zero_when_in_sync(tmp_path):
    payload = _fake_payload()
    code, out = _run_driver(tmp_path, payload, payload, "lambda _h: None")
    assert code == 0, out
    assert "索引与代码同步" in out


def test_process_exit_code_is_one_when_drifted(tmp_path):
    """本文件的**主判据**：不同步时进程真的按 1 退出。

    这是 2026-08-14 那次静默放行的原样复现：文案打印正确、退出码却是 0。
    """
    on_disk = _fake_payload([("basic", "观战静音")])
    fresh = _fake_payload([("basic", "观战静音"), ("basic", "按地图切换预设")])
    code, out = _run_driver(tmp_path, on_disk, fresh, "lambda _h: None")
    assert "索引与代码不同步" in out
    assert code == 1, f"打印了不同步却按 {code} 退出——CI 会静默放行\n{out}"


def test_process_exit_code_survives_the_shutdown_watchdog(tmp_path):
    """收尾里 `os._exit(0)`（产品的 15s 退出看门狗）不能把 1 洗成 0。"""
    on_disk = _fake_payload([("basic", "观战静音")])
    fresh = _fake_payload([("basic", "观战静音"), ("basic", "按地图切换预设")])
    code, out = _run_driver(tmp_path, on_disk, fresh, "lambda _h: os._exit(0)")
    assert code == 1, f"退出看门狗把不同步洗成了 {code}\n{out}"


def test_process_exit_code_survives_systemexit_in_teardown(tmp_path):
    """收尾里 `sys.exit(0)`（信号处理器兜底）同样不能把 1 洗成 0。"""
    on_disk = _fake_payload([("basic", "观战静音")])
    fresh = _fake_payload([("basic", "观战静音"), ("basic", "按地图切换预设")])
    code, out = _run_driver(tmp_path, on_disk, fresh, "lambda _h: sys.exit(0)")
    assert code == 1, f"teardown 里的 SystemExit 把退出码改成了 {code}\n{out}"


def test_process_exit_code_is_two_when_environment_is_unavailable(tmp_path):
    payload = _fake_payload()
    code, out = _run_driver(
        tmp_path, payload, payload, "lambda _h: None",
        build_override='def _boom(*a, **k):\n'
                       '    raise bsi.EnvironmentUnavailable("PySide6 不可用")\n'
                       'bsi.build = _boom',
    )
    assert code == 2, f"环境不满足应当是 2，实际 {code}\n{out}"


def test_docstring_contract_matches_the_constants():
    """模块 docstring 里写的那行退出码约定，必须和代码里的常量对得上。

    这次的缺陷就是"声明与实现不符"，所以声明本身也拉进判据。
    """
    doc = bsi.__doc__ or ""
    assert "0=成功/已同步, 1=--check 下不同步, 2=环境不满足" in doc
    assert (bsi.EXIT_OK, bsi.EXIT_DRIFT, bsi.EXIT_ENV) == (0, 1, 2)
