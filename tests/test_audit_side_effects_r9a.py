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


def _page_building_scripts() -> dict[str, str]:
    """找出所有会构造 MainWindow 的脚本，返回 {文件名: 源码}。"""
    out = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name.startswith("_") or path.name in BROKEN_ALREADY:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if _constructs(src, "MainWindow"):
            out[path.name] = src
    return out


def test_there_are_page_building_scripts_to_check():
    """自检：如果这个探测器一个脚本都找不到，后面几条判据就是空转。"""
    found = _page_building_scripts()
    assert len(found) >= 8, f"只找到 {len(found)} 个建页脚本，探测器多半失灵了"


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
    finally:
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
    """
    import importlib.util
    import json as _json
    import tempfile

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
    allowed = (Path(tempfile.gettempdir()).resolve(), Path(tmp_path).resolve())
    assert any(root == resolved or root in resolved.parents for root in allowed), (
        f"真机跑测的 csgo_dir 指向了临时目录之外：{csgo_dir}\n"
        "跑一次 live_run.py 就会改写那里的 cs2customizer.cfg（UP-093）"
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
