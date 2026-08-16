# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R8a 惰性导入回归（UP-055 / UP-056 / UP-061）。

守的是一件很容易悄悄退化的事：**show 前的关键路径上不能出现 pygame / requests**。
只要有人在某个模块顶层重新写一句 `import pygame`，或在 `MainWindow.__init__` 里
提前碰一下音频管理器，几百毫秒就会无声无息地回到启动路径上——
而所有功能测试仍然全绿，因为功能确实没坏。

⚠️ 这类断言**必须在子进程里做**：pytest 主进程收集阶段就会 import 一堆模块，
   pygame 早被别的用例拉起来了，在主进程里查 `sys.modules` 只会得到假结果。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 子进程脚本：构造 MainWindow（不上屏）后报告哪些重模块被加载了
_PROBE = r"""
import json, os, sys, tempfile
from pathlib import Path

os.environ["CS2C_SAFE_MODE_ACTIVE"] = "1"
_tmp = Path(tempfile.gettempdir()) / "cs2customizer_lazy_probe"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ["CS2C_CONFIG_DIR"] = str(_tmp / "config")
os.environ["CS2C_LOG_DIR"] = str(_tmp / "logs")
sys.path.insert(0, r"__ROOT__")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

app = QApplication.instance() or QApplication([])
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

WATCH = ("pygame", "numpy", "requests", "urllib3", "pkg_resources")

import gui_widget
after_import = [m for m in WATCH if m in sys.modules]

win = gui_widget.MainWindow(auto_background_preload=False)
win.setAttribute(Qt.WA_DontShowOnScreen, True)
win.show()
app.processEvents()
after_show = [m for m in WATCH if m in sys.modules]

win.close()
win.deleteLater()
app.processEvents()
print("RESULT " + json.dumps({"after_import": after_import, "after_show": after_show}))
""".replace("__ROOT__", str(ROOT).replace("\\", "\\\\"))


@pytest.fixture(scope="module")
def probe_result():
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(ROOT), capture_output=True, text=True, errors="replace", timeout=600,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    pytest.fail(f"探针子进程没有输出结果:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")


def test_importing_gui_widget_pulls_no_heavy_modules(probe_result):
    """`import gui_widget` 本身不该拖进任何重模块。

    改前实测：pygame 611.9ms（其中 pkg_resources 314.8 + numpy 204.6）
    + requests 319.8ms，合计占 `import gui_widget` 总耗时的 69%。
    """
    assert probe_result["after_import"] == [], (
        f"import gui_widget 拖进了 {probe_result['after_import']}"
    )


def test_showing_main_window_pulls_no_heavy_modules(probe_result):
    """到 show 为止也不能拖进——否则只是把成本从 import 挪到构造函数。

    这正是 R8a 第一版改动的实际结果：`import gui_widget` 从 762ms 降到 114ms
    看着很漂亮，但 MainWindow 构造从 596ms 涨到 1217ms，到 show 的总账
    1555ms → 1528ms，净收益落在噪声里。所以判据必须落在**总账**上。
    """
    assert probe_result["after_show"] == [], (
        f"到 show 为止拖进了 {probe_result['after_show']}"
    )


def test_lazy_module_defers_import_until_attribute_access():
    from core.utils.lazy_module import LazyModule, lazy_module

    # 挑一个正常不会被提前导入的标准库模块
    name = "wave"
    sys.modules.pop(name, None)
    proxy = lazy_module(name, __name__)
    assert isinstance(proxy, LazyModule)
    assert name not in sys.modules, "建代理时就不该导入"

    assert proxy.Wave_read is not None  # 首次属性访问触发
    assert name in sys.modules


def test_lazy_module_returns_real_module_if_already_loaded():
    """已经加载过就别再绕一层代理。"""
    import json as real_json

    from core.utils.lazy_module import lazy_module

    assert lazy_module("json", __name__) is real_json


def test_lazy_module_truthiness_does_not_trigger_import():
    """`if pygame:` 这种真值判断不该把整个模块拉起来。

    ⚠ 这条用例的第一版是**空的**：只断言 `bool(proxy) is True` + 模块未加载，
    而把 `__bool__` 整个删掉之后 Python 会退回默认真值（对象恒为真），
    `__getattr__` 根本不会被触发——回退被测代码它照样绿。
    对抗复核指出后改成直接断言那个方法确实是本类实现的。
    """
    from core.utils.lazy_module import LazyModule, lazy_module

    name = "sunau"
    sys.modules.pop(name, None)
    proxy = lazy_module(name, __name__)
    assert type(proxy).__bool__ is LazyModule.__bool__, "LazyModule 必须自己实现 __bool__"
    assert bool(proxy) is True
    assert name not in sys.modules


def test_lazy_module_rebinds_every_alias():
    """代理解析后要回填**所有**指向它的名字，不能只改第一个。"""
    import types

    from core.utils.lazy_module import LazyModule

    owner = types.ModuleType("_lazy_alias_owner")
    sys.modules["_lazy_alias_owner"] = owner
    try:
        proxy = LazyModule("wave", "_lazy_alias_owner")
        owner.first = proxy
        owner.second = proxy
        proxy.Wave_read  # 触发解析
        import wave

        assert owner.first is wave
        assert owner.second is wave, "只回填了第一个别名"
    finally:
        sys.modules.pop("_lazy_alias_owner", None)


def test_lazy_module_dotted_name_does_not_invent_globals():
    """点号模块名的兜底不能凭空造出一个顶层名字。"""
    import types

    from core.utils.lazy_module import LazyModule

    owner = types.ModuleType("_lazy_dotted_owner")
    sys.modules["_lazy_dotted_owner"] = owner
    try:
        # 故意不把代理挂到 owner 上：走"找不到任何匹配名字"的分支
        proxy = LazyModule("email.utils", "_lazy_dotted_owner")
        assert proxy.formatdate is not None
        assert not hasattr(owner, "email"), "不该凭空造出名为 email 的全局名"
    finally:
        sys.modules.pop("_lazy_dotted_owner", None)


def test_core_audio_lazy_exports_still_work():
    """UP-055 把 core.audio 改成 PEP 562 惰性导出，公开名字必须照常可用。"""
    import core.audio as audio_pkg

    for name in audio_pkg.__all__:
        assert hasattr(audio_pkg, name), f"core.audio 少了导出 {name}"

    with pytest.raises(AttributeError):
        audio_pkg.definitely_not_a_real_export


def test_peek_runtime_audio_manager_never_creates():
    """退出清理用的 peek 不能把管理器创建出来。"""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s');"
         "from core.audio.runtime_audio import peek_runtime_audio_manager;"
         "assert peek_runtime_audio_manager() is None;"
         "assert 'pygame' not in sys.modules;"
         "print('OK')" % str(ROOT).replace("\\", "\\\\")],
        cwd=str(ROOT), capture_output=True, text=True, errors="replace", timeout=300,
    )
    assert "OK" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"


def test_worker_loops_do_not_busy_poll():
    """UP-061：pygame 子进程的主循环不能再用 sleep(0.001) 空转。

    判据落在"有没有阻塞等待"上，而不是"源码里有没有那行字"——
    所以同时要求出现阻塞 get 的调用。

    KI-1（2026-08-15）把 `kill_icon_player.py` 从这张表里摘掉了：它的
    pygame 子进程整个不存在了（改成主进程 Qt 叠加层），**连空转的循环
    都没有了**——这比"改成阻塞等待"更彻底，不是判据放松。
    还在表里的 `utility_display.py` 仍是子进程，判据照旧。
    """
    for filename in ("utility_display.py",):
        source = (ROOT / filename).read_text(encoding="utf-8")
        # 剥掉注释行，避免命中解释这件事的说明文字
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert "time.sleep(0.001)" not in body, f"{filename} 仍在 1000Hz 空转"
        assert "command_queue.get(" in body, f"{filename} 没有改成阻塞等待"
        assert "_queue.Empty" in body, f"{filename} 缺少超时分支"
        # 唤醒频率必须挂在"窗口是否可见"上。只挂 pygame_initialized 的话，
        # 首次显示后它永远为真，"空闲 5Hz"就成了永远达不到的空话（等于把
        # 1000Hz 空转换成了 60Hz 空转）。判据落在 timeout 表达式本身上。
        match = re.search(r"command_queue\.get\(\s*timeout=([^)]*(?:\([^)]*\))?[^)]*)\)", body)
        assert match, f"{filename} 找不到带 timeout 的阻塞 get"
        assert "window_visible" in match.group(1), (
            f"{filename} 的唤醒节奏没挂在 window_visible 上: {match.group(1).strip()}"
        )


def test_ci_workflow_uses_only_job_level_contexts():
    """CI 工作流的 job 级 `env` 不能引用 step 级才有的上下文。

    R8a 在 `jobs.<id>.env` 里写了 `${{ runner.temp }}` —— GitHub 的
    context availability 表里 `jobs.<job_id>.env` 只允许
    github / needs / strategy / matrix / vars / secrets / inputs，**不含 runner**。
    后果不是"这个作业红了"，而是**整个 workflow 文件校验失败、一个作业都不调度**，
    连原本守着全量回归的 test 作业一起静默失效——正是最坏的那种"门看着在，其实没在守"。
    """
    import yaml

    ALLOWED = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs", "env"}
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "没有找到任何 workflow 文件"

    bad = []
    for path in workflows:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (data.get("jobs") or {}).items():
            for key, value in (job.get("env") or {}).items():
                for ctx in re.findall(r"\$\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\.", str(value)):
                    if ctx not in ALLOWED:
                        bad.append(f"{path.name}:{job_name}.env.{key} 用了 `{ctx}` 上下文")
    assert not bad, "job 级 env 引用了不可用的上下文：" + "; ".join(bad)
