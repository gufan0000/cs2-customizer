# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R9-A（UP-090）：审计脚本不许写到用户真实的 CS2 游戏目录。

**背景**：审计脚本一直隔离了配置目录和日志目录，于是"隔离"这件事看上去是做到了。
但 `config.csgo_dir` 不受那两个环境变量管——它是**自动探测**的：隔离配置是空的，
探测器就去扫用户真机上的 CS2 安装。排版审计构建放大镜页时，
`_ensure_sensitivity_support_files_if_needed()` 于是往真实游戏目录写了 `cs2customizer.cfg`，
内容还是**默认配置**编译出来的，把用户原有的 bind 覆盖掉。

实测证据（R9-A）：`<CS2 安装目录>\\cfg\\cs2customizer.cfg` 被写成 2007 字节的默认版，
而用户真实配置应生成 2075 字节。这不是这次才发生的——审计跑过多少轮就发生过多少轮，
而且**每一轮审计都是绿的**，因为副作用不在任何判据的视野里。

本文件盯的就是这个盲区：**新写一个会建页的脚本，忘了沙箱化，测试要红。**
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
SANDBOX_CALL = "sandbox_external_writes"


@pytest.fixture(autouse=True)
def _never_leave_config_unsavable():
    """兜底：本文件里任何用例都不许把「配置能不能落盘」这个进程级开关留在关着的状态。

    `sandbox_external_writes()` 会把 config 的三个落盘入口换成 no-op（QA-025）。
    在审计脚本里这没问题——跑完就退进程；但在 pytest 里它会活到会话结束，
    于是**后面某个别的文件**里验存盘的用例莫名其妙变红，单跑那个文件却是绿的。
    用例自己 finally 里也还了一次，这条是防下一个人忘。
    """
    yield
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import _audit_sandbox
    except ImportError:  # pragma: no cover
        return
    _audit_sandbox.restore_config_persistence()

#: 会建页、但**故意**不沙箱化的脚本，必须写明理由。
#: 空理由 = 不算豁免，测试照样红——豁免要有代价，否则名单会无声地变长。
EXEMPT = {
    # 开源裁剪移除了两条豁免（build_cs2customizer_local_manual.py /
    # capture_desktop_tutorial_screenshots.py）——那两个文档工具脚本本身已不在仓库里。
    # 名单只许减不许增，见 test_exemptions_are_not_stale。
    "bench_startup_path.py":
        "父进程不建页；建页在 _CHILD 那段子进程脚本字符串里，"
        "父进程 AST 看不到它的调用。由 test_bench_startup_child_script_sandboxes 单独盯",
}

#: 本来就跑不起来的脚本（既有问题，与 UP-090 无关，另记 UP-091）。
#: 列在这里是为了让本测试的失败信号保持干净，不是为了掩盖它们。
BROKEN_ALREADY = {
    "bootstrap_tutorial_content.py",
    "capture_web_tutorial_screenshots.py",
}


def _constructs(src: str, name: str) -> bool:
    """源码里有没有**真正构造** `name`（AST 找 Call，不是子串匹配）。

    ⚠ 这里原本是逐行 `re.search(r"\\bMainWindow\\(", line)`，回归测试时被自己的
    注释骗了一次：给 `live_run.py` 的文档字符串里写了「判据找的是 MainWindow( 构造点」
    这句话，探测器就把它当成建页脚本了。同一个教训第三次出现——
    **判断"调用/构造"永远走 AST，不要看文本**。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
    return False


def _builds_pages_directly(src: str) -> bool:
    """不建 `MainWindow`、直接建单个页类的脚本也算「会建页」。

    ⚠ RN-072：这一条是补出来的，代价是量出来的 —— `bench_page_build.py`
    用 `importlib.import_module("pages.xxx_page")` + `getattr` 动态构造页面，
    **一次都没构造 MainWindow**，于是它整支落在探测器视野之外，
    在真实的 `Steam/.../csgo/cfg/` 里写了 GSI cfg / cs2customizer.cfg / autoexec.cfg。
    ⇒ 判据写完要问的不是"它绿不绿"，而是**"它的分母是多少"**。

    两条信号（任一即算）：
      · 源码里出现 `pages.` 这个模块命名空间（含字符串常量形式的动态 import）
      · 构造了一个名字以 `Page` 结尾的类
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.startswith("pages."):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pages"):
            return True
        if isinstance(node, ast.Import) and any(
                a.name.startswith("pages.") for a in node.names):
            return True
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else "")
            if name.endswith("Page") and name != "Page":
                return True
    return False


def _page_building_scripts() -> dict[str, str]:
    """找出所有会建页的脚本，返回 {文件名: 源码}。

    「会建页」= 构造 `MainWindow`（整窗）**或**直接构造单个页类（见
    `_builds_pages_directly`）。后半条是 RN-072 补的：只认 MainWindow 时，
    `bench_page_build.py` 这种动态建页的脚本是隐形的。
    """
    out = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name.startswith("_") or path.name in BROKEN_ALREADY:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if _constructs(src, "MainWindow") or _builds_pages_directly(src):
            out[path.name] = src
    return out


def test_there_are_page_building_scripts_to_check():
    """自检：如果这个探测器一个脚本都找不到，后面几条判据就是空转。"""
    found = _page_building_scripts()
    assert len(found) >= 8, f"只找到 {len(found)} 个建页脚本，探测器多半失灵了"


def test_the_detector_also_sees_scripts_that_build_pages_without_mainwindow():
    """RN-072：探测器必须能看见"不建整窗、只建单页"的脚本。

    空转守卫写成**点名**的形式：`bench_page_build.py` 是那个出事的脚本，
    它必须在名单里。只断言"总数够多"是不够的 —— 上一版就是那么绿的。
    """
    found = _page_building_scripts()
    assert "bench_page_build.py" in found, (
        "探测器看不见 bench_page_build.py（它动态构造单个页类，不建 MainWindow）—— "
        "而它正是在用户真实 CS2 目录里写过文件的那一支（RN-072）")


def _calls_sandbox(src: str) -> bool:
    """源码里有没有**真正调用**沙箱函数。

    ⚠ 不能用 `"sandbox_external_writes" in src` 来判断——`from ... import
    sandbox_external_writes` 这行本身就含这个名字，于是「删掉调用、留着 import」
    这种最典型的回退方式检不出来。R9-A 写这条判据时第一版正是这么错的，
    做回退验证才发现它是假绿的。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == SANDBOX_CALL:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == SANDBOX_CALL:
                return True
    return False


def test_every_page_building_script_sandboxes_the_game_dir():
    """核心判据。回退验证：从 layout_overflow_audit.py 删掉那次调用，本条立刻变红。"""
    missing = [
        name for name, src in _page_building_scripts().items()
        if not _calls_sandbox(src) and name not in EXEMPT
    ]
    assert not missing, (
        "这些脚本会建页却没沙箱化 CS2 目录，跑一次就会覆盖用户游戏配置：\n  "
        + "\n  ".join(missing)
        + f"\n修法：在构造 MainWindow 之前 `from _audit_sandbox import {SANDBOX_CALL}` 并调用。"
    )


def test_bench_startup_child_script_sandboxes():
    """`bench_startup_path.py` 把子进程脚本存成一个字符串 `_CHILD`。

    这是豁免名单里唯一「真的会建页」的一条，所以不能只是豁免了事——
    这里把那个字符串抠出来单独解析，确认它自己调了沙箱，且能 import 到它
    （子进程的 sys.path 必须含 scripts/，否则 import 直接炸，整个基准跑不了）。
    """
    src = (SCRIPTS / "bench_startup_path.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    child = next(
        (n.value.value if isinstance(n.value, ast.Constant) else n.value.func.value.value
         for n in ast.walk(tree)
         if isinstance(n, ast.Assign)
         and any(isinstance(t, ast.Name) and t.id == "_CHILD" for t in n.targets)),
        None,
    )
    assert isinstance(child, str) and child.strip(), "抠不出 _CHILD 子进程脚本"
    assert _calls_sandbox(child), "子进程脚本没有调用沙箱"
    assert '"scripts"' in child or "'scripts'" in child, (
        "子进程的 sys.path 里没有 scripts/，`from _audit_sandbox import ...` 会直接 ImportError"
    )


def test_exemptions_all_carry_a_reason():
    """豁免必须写理由，且理由不能是空字符串或占位符。"""
    for name, reason in EXEMPT.items():
        assert reason and len(reason.strip()) >= 10, f"{name} 的豁免理由太敷衍：{reason!r}"


def _builds_pages_anywhere(src: str) -> bool:
    """建页判断的**宽口径**：模块自己建，或它内嵌的子进程脚本字符串里建。

    `bench_startup_path.py` 属于后者——它的 `MainWindow(` 在 `_CHILD` 那个
    三引号字符串里，模块 AST 只看见一个 Constant。豁免名单的陈旧检查得认这一种，
    否则一改成 AST 探测，这条豁免就会被判成"陈年垃圾"而误删。
    """
    if _constructs(src, "MainWindow"):
        return True
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "MainWindow" not in node.value:
                continue
            if _constructs(node.value, "MainWindow"):
                return True
    return False


def test_exemptions_are_not_stale():
    """豁免名单里的文件得真的存在、且真的会建页——否则是陈年垃圾。"""
    for name in EXEMPT:
        assert (SCRIPTS / name).exists(), f"豁免名单里的 {name} 已不存在，请删掉这条"
        src = (SCRIPTS / name).read_text(encoding="utf-8", errors="replace")
        assert _builds_pages_anywhere(src), f"{name} 已经不建页了，豁免可以删掉"


def test_sandbox_redirects_csgo_dir_to_an_existing_temp_dir():
    """沙箱本身要真的生效：改掉 csgo_dir、指向一个真实存在的目录、且幂等。

    指向**存在的**目录很关键——如果置空，页面会走「未配置 CS2 目录」分支，
    UI 文案和布局跟着变，等于把被审计对象本身改掉了。
    """
    sys.path.insert(0, str(SCRIPTS))
    try:
        import _audit_sandbox
    except ImportError:  # pragma: no cover
        pytest.skip("拿不到 scripts/_audit_sandbox.py")

    from config import config

    original = getattr(config, "csgo_dir", "")
    saved_state = _audit_sandbox._SANDBOX_DIR
    _audit_sandbox._SANDBOX_DIR = None
    try:
        sandbox = _audit_sandbox.sandbox_external_writes(verbose=False)
        assert Path(config.csgo_dir) == sandbox
        assert sandbox.is_dir()
        assert (sandbox / "game" / "csgo" / "cfg").is_dir()
        # 幂等：再调一次不会换目录
        assert _audit_sandbox.sandbox_external_writes(verbose=False) == sandbox
        # 沙箱同时会掐掉配置落盘（QA-025），这里顺手确认一下
        assert _audit_sandbox._SAVES_BLOCKED, "沙箱没掐配置落盘"
    finally:
        # ⚠ 落盘入口必须还回去。它是**进程级**的副作用：不还的话，同一次
        # pytest 里后面任何验「改了配置能存回去」的用例都会红，而且红在
        # 别的文件里——单跑那个文件反而是绿的，最难查的那种。
        # tests/test_logger_policy.py::test_config_field_persists 已经这么中过一次。
        _audit_sandbox.restore_config_persistence()
        _audit_sandbox._SANDBOX_DIR = saved_state
        config.csgo_dir = original
        if str(SCRIPTS) in sys.path:
            sys.path.remove(str(SCRIPTS))


def test_the_test_suite_itself_does_not_point_at_a_real_game_dir():
    """判据的判据：**测试套件自己**也不许指向用户真实的 CS2 目录。

    R9-A 实测：`cs2customizer_test_config/config.json` 里持久化着
    `csgo_dir=<CS2 安装目录>`，于是每跑一次 pytest，建页的测试就往用户
    真机的游戏目录写一次 `cs2customizer.cfg`。全绿了几十轮，因为没人看着这件事。

    回退验证：把 conftest 里那段按 csgo_dir 的代码删掉、并让隔离配置里
    重新存回一个真实路径，本条立刻变红。
    """
    import tempfile

    from config import config

    csgo_dir = str(getattr(config, "csgo_dir", "") or "")
    if not csgo_dir:
        return  # 空值本身不写任何东西，安全

    tmp_root = Path(tempfile.gettempdir()).resolve()
    resolved = Path(csgo_dir).resolve()
    assert tmp_root in resolved.parents or resolved == tmp_root, (
        f"测试环境的 csgo_dir 指向了临时目录之外：{csgo_dir}\n"
        "跑一次 pytest 就会改写那里的 cs2customizer.cfg。见 tests/conftest.py 的 UP-090 段。"
    )


def _app_launching_scripts() -> dict[str, str]:
    """找出**起子进程跑整个软件**的脚本（而不是进程内建页的）。

    R9 修 UP-090 时漏了这一类：上面那个探测器找的是 `MainWindow(` 构造点，
    而 `live_run.py` 是 `subprocess.Popen([sys.executable, "main_widget.py"])`，
    压根没有构造点，于是它安安静静地在判据视野之外写了很多轮用户的真实游戏目录。

    ⚠ 第一版是文本匹配（源码里同时出现 `"main_widget.py"` 和 `Popen`），
    当场就误报了：`scripts/revert_verify_r9.py` 把 `"main_widget.py"` 当作
    **待改文件名**列在表里，又用 `subprocess.run` 去跑 pytest，于是被判成
    "起子进程跑整个软件"。**同一个教训第四次**——这里只认
    `subprocess.Popen([..., "main_widget.py"])` 这种真正把它当可执行目标的调用。
    """
    launchers = {"Popen", "run", "call", "check_call", "check_output"}
    out = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name in BROKEN_ALREADY:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else \
                fn.id if isinstance(fn, ast.Name) else ""
            if name not in launchers:
                continue
            argv = node.args[0]
            if not isinstance(argv, (ast.List, ast.Tuple)):
                continue
            if any(isinstance(e, ast.Constant) and e.value == "main_widget.py"
                   for e in argv.elts):
                out[path.name] = src
                break
    return out


def test_app_launching_scripts_are_known():
    """自检：这类脚本目前只有 live_run.py 一个。多出来一个就要跟着加行为判据。"""
    assert set(_app_launching_scripts()) == {"live_run.py"}, (
        f"起子进程跑整个软件的脚本变了：{sorted(_app_launching_scripts())}\n"
        "新增的那个也必须隔离 csgo_dir，并在这里补一条行为判据。"
    )


def test_live_run_sandboxes_the_game_dir_by_default(tmp_path):
    """行为判据（UP-093）：默认跑测写出来的隔离配置，csgo_dir 必须指向临时目录。

    这条不看源码文本，直接调 `_prepare_env` 看它**实际写出**的 config.json——
    结构判据（"源码里有没有出现 csgo_dir"）太好骗了。

    回退验证：把 `_prepare_env` 里那段 `data["csgo_dir"] = ...` 删掉，本条立刻变红。

    ⚠ 2026-08-16 这条被回退验证台逮出是**假绿**的。原来只要求 csgo_dir
    「落在某个临时目录下面」，而 `_prepare_env` 会先把用户真实配置整个拷过来——
    用户那份配置的 csgo_dir 当时**恰好也是一个临时路径**
    （`%TEMP%\\cs2customizer_audit_game_sandbox`，见 test_audit_never_persists_config：
    审计把沙箱路径写进了用户真实配置）。于是删掉赋值那行，判据照样绿。
    现在改成**逐字比对它该指到的那个目录**：拷过来的值不管长什么样都不算数。
    """
    import importlib.util
    import json as _json

    spec = importlib.util.spec_from_file_location("_live_run", SCRIPTS / "live_run.py")
    live_run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_run)

    env = live_run._prepare_env(tmp_path)
    written = _json.loads(
        (Path(env["CS2C_CONFIG_DIR"]) / "config.json").read_text(encoding="utf-8")
    )
    csgo_dir = str(written.get("csgo_dir") or "")
    assert csgo_dir, "csgo_dir 被置空了——页面会走「未配置 CS2 目录」分支，等于改掉了被测对象"

    resolved = Path(csgo_dir).resolve()
    expected = (Path(tmp_path) / "game_dir").resolve()
    assert resolved == expected, (
        f"真机跑测的 csgo_dir 不是本次建的沙箱目录：\n  实际 {resolved}\n  应为 {expected}\n"
        "只要不是这个目录，跑一次 live_run.py 就可能改写别处的 cs2customizer.cfg（UP-093）"
    )
    assert (resolved / "game" / "csgo" / "cfg").is_dir(), (
        "沙箱游戏目录的 game/csgo/cfg 没建出来，写 cfg 时会走异常分支"
    )


def test_live_run_can_still_opt_into_the_real_game_dir(tmp_path):
    """隔离要有正门：专门验证「cfg 是否真落到游戏目录」时得能关掉隔离。

    没有这条的话，隔离一上，那个验证场景就永远做不了了，
    下一个人会直接把隔离删掉——而不是加个开关。
    """
    import importlib.util
    import json as _json

    spec = importlib.util.spec_from_file_location("_live_run2", SCRIPTS / "live_run.py")
    live_run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_run)

    env = live_run._prepare_env(tmp_path / "real", real_game_dir=True)
    written = _json.loads(
        (Path(env["CS2C_CONFIG_DIR"]) / "config.json").read_text(encoding="utf-8")
    )
    sandbox = str((tmp_path / "real" / "game_dir").resolve())
    assert str(written.get("csgo_dir") or "") != sandbox, (
        "--real-game-dir 没生效，隔离目录仍然被强加了"
    )


# ==================================================================== 沙箱的下半截
#
# UP-090 只做了上半截（把 csgo_dir 改成沙箱路径），而那**只是内存里的值**。
# 审计跑起来之后有三条路会把整份配置写回磁盘：准心页建页时被信号连带触发的
# save_config、放大镜页 cleanup 里的 save_settings、以及 closeEvent 的
# save_config_now。于是沙箱路径被刻进用户真实的 config.json——
# 实测中招：用户的 CS2 目录变成了 `%TEMP%\cs2customizer_audit_game_sandbox`。

_PERSIST_DRIVER = r'''
import hashlib, json, os, pathlib, sys, time
sys.path.insert(0, os.path.join(os.environ["CS2C_REPO"], "scripts"))
sys.path.insert(0, os.environ["CS2C_REPO"])

from config import config
cfg_path = pathlib.Path(os.environ["CS2C_CONFIG_DIR"]) / "config.json"
# 基线取在 import 之后：加载时如果发生过 schema 迁移，config 会立刻落盘固化
# 新版本号——那是设计好的行为，与审计副作用无关，不该算到这条判据头上。
baseline = hashlib.sha256(cfg_path.read_bytes()).hexdigest()

from _audit_sandbox import sandbox_external_writes
sandbox_external_writes(verbose=False)

# 把审计过程中真实发生过的三条落盘路各走一遍
config.save_config()          # 防抖入口（准心页建页时被信号触发）
config.save_config_now()      # 同步入口（closeEvent 的退出步骤）
config._atexit_flush()        # 兜底入口（防抖 timer 没到点就退出时）
config._do_save_config()      # 真正写盘的那个：防抖 timer、atexit、schema 迁移
                              # 都直接调它，不经过上面两个公开入口

time.sleep(0.8)               # 等过 500ms 防抖窗口，让漏网的 timer 有机会写盘
print(json.dumps({"csgo_dir_in_memory": config.csgo_dir, "baseline": baseline}))
'''


def test_audit_never_persists_config(tmp_path):
    """行为判据：审计沙箱化之后，**配置文件一个字节都不许变**。

    判据必须是"文件没被改写"而不是"csgo_dir 还对"——因为写回去的是整份配置，
    被带走的不止 csgo_dir 一个键。

    ⚠ 隔离配置里的 csgo_dir 必须指向一个**真实存在**的目录：config 加载时会
    校验这条路径，指向不存在的目录会被直接置空（那是另一条设计好的行为），
    于是判据变成红的、但红的原因是假的。
    """
    import hashlib
    import json as _json
    import os
    import subprocess

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    game = tmp_path / "real_cs2"
    (game / "game" / "csgo" / "cfg").mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        _json.dumps({"csgo_dir": str(game), "close_action": "exit"},
                    ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    driver = tmp_path / "drive_sandbox.py"
    driver.write_text(_PERSIST_DRIVER, encoding="utf-8")

    env = dict(os.environ)
    env["CS2C_REPO"] = str(REPO)
    env["CS2C_CONFIG_DIR"] = str(cfg_dir)
    env["CS2C_LOG_DIR"] = str(log_dir)
    env["CS2C_AUDIT_SANDBOX_DIR"] = str(tmp_path / "audit_sandbox")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(driver)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=180,
    )
    assert proc.returncode == 0, f"驱动脚本没跑成：\n{proc.stdout}\n{proc.stderr}"

    # 沙箱确实生效了（否则下面"文件没变"就成了空判据）
    reported = _json.loads(proc.stdout.strip().splitlines()[-1])
    assert reported["csgo_dir_in_memory"] == str(tmp_path / "audit_sandbox"), (
        "沙箱压根没改 csgo_dir，本条判据失去意义"
    )

    after = (cfg_dir / "config.json").read_bytes()
    assert hashlib.sha256(after).hexdigest() == reported["baseline"], (
        "沙箱化之后配置又被写回磁盘了。写进去的是整份配置，其中 csgo_dir 是沙箱临时目录——"
        "用户的 CS2 目录会被改成一个 %TEMP% 路径，软件下次启动就往那儿写 cfg。\n"
        f"现在文件里是：{_json.loads(after.decode('utf-8')).get('csgo_dir')!r}"
    )


def test_audit_scripts_at_least_parse():
    """已知有两个脚本连语法都不过（UP-091）。这条把「已知」钉住：

    数量只许减不许增——再多一个解析不了的脚本，说明有人提交了压根没跑过的代码。
    """
    broken = []
    for path in sorted(SCRIPTS.glob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            broken.append(path.name)
    assert set(broken) <= BROKEN_ALREADY, (
        f"新增了解析不了的脚本: {sorted(set(broken) - BROKEN_ALREADY)}"
    )
