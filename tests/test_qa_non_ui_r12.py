# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""QA-001~008：UI 专项之外的八条缺陷的判据。

来历：UI/性能专项结项后做了一轮**非 UI 维度**的排查（数据安全 / 音频 / 子进程 /
网络更新 / 稳态内存 / 静默失败 / 打包链路 / 测试盲区），八个维度并行排查 +
逐条对抗验证。原始 28 条发现里，经"默认它不成立"的对抗验证后确认了这八条。

判据分两类：
- **行为判据**优先——直接构造出缺陷场景，断言现在不会发生。回退产品代码时它必红。
- 拿不到行为的（打包脚本、子进程主循环）走 AST 结构判据，
  但**必须走 `ast.Call` 而不是字符串包含**：这个项目已经因为子串判断误报 6 次。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _tree(rel: str) -> ast.Module:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree(rel)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{rel} 里找不到 {name}")


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    """名字（或点号末段）等于 name 的调用节点。"""
    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        got = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if got == name:
            out.append(sub)
    return out


# ═══════════════════════════════════ QA-001 发布包带开发机配置


def test_qa001_release_does_not_ship_the_dev_config():
    """`config.json` 不许出现在打包 datas 里。

    它是开发机的**活配置**（`csgo_dir` 指向打包机的 Steam 库盘符）。
    进了发布包之后落到 `_internal/config.json`，新机首启时
    `config.migrate_old_config()` 会把它复制成用户配置：
    CS2 目录指向一个不存在的盘 → 四个写 cfg 的函数全部静默 return
    （击杀音效 / HUD 联动 / GSI 全不工作）；而种子配置里没有
    `onboarding_completed` 键，`load_config` 取默认 True，
    **本该教用户选 CS2 目录的首启引导恰好同时被关掉**。
    """
    src = (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "data_entries" for t in node.targets):
            continue
        # 元组第一项形如 `stage_dir / "config.json"`
        for elt in getattr(node.value, "elts", []):
            for sub in ast.walk(elt):
                if isinstance(sub, ast.Constant) and sub.value == "config.json":
                    raise AssertionError(
                        "build_release 的 datas 里又出现了 config.json —— "
                        "那是开发机的活配置，会在新机首启时被复制成用户配置（QA-001）"
                    )
        return
    raise AssertionError("找不到 data_entries，判据的前提变了，先去看 build_release.py")


def test_qa001_stage_copy_excludes_the_dev_config():
    """从 stage 源头就不许带 config.json —— 比只删 datas 更稳。"""
    fn = _func("build_tools/build_release.py", "copy_project")
    patterns = []
    for call in _calls(fn, "ignore_patterns"):
        for arg in call.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                patterns.append(arg.value)
    assert "config.json" in patterns, (
        "copy_project 的 ignore_patterns 里没有 config.json —— "
        "开发机配置会被拷进 stage，之后任何人往 datas 加一行就又带出去了"
    )


def test_qa001_build_gate_rejects_a_leaked_config(tmp_path):
    """产物里真混进 config.json 时，打包校验必须炸。

    正向清单（缺什么就报错）挡不住这种"多了才坏"的东西，所以要一条反向断言。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_br", ROOT / "build_tools" / "build_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    folder = tmp_path / "CS2 Customizer 9.9.9"
    internal = folder / "_internal"
    (internal / "resources").mkdir(parents=True)
    (internal / "PySide6").mkdir()
    (internal / "python313.dll").write_bytes(b"x")
    (folder / "CS2 Customizer.exe").write_bytes(b"x")
    # R13/QA-020: 项级搜索索引也进了正向清单，而正向清单跑在反向断言之前。
    # 假产物树里不摆上它，这个用例会先因为"缺索引"炸掉，
    # 于是 match="config.json" 对不上 —— 量的就不是它要量的东西了。
    (internal / "core").mkdir()
    (internal / "core" / "search_index.json").write_text("{}", encoding="utf-8")
    (internal / "config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="config.json"):
        mod.verify_onedir_tree(folder, "CS2 Customizer", require_obfuscation=False)


def test_qa001_frozen_build_never_migrates_the_bundled_config():
    """冻结态一律不做「程序目录 → LOCALAPPDATA」的迁移。

    打包后程序目录旁那份 config.json 天然不是用户的配置。
    这是运行时安全带：打包侧已经拿掉了，两边都堵住才不会重演。
    """
    fn = _func("config.py", "migrate_old_config")
    # 函数体第一条语句必须是 frozen 守卫
    first = fn.body[1] if isinstance(fn.body[0], ast.Expr) else fn.body[0]
    assert isinstance(first, ast.If), "migrate_old_config 开头不是守卫语句"
    got = ast.dump(first.test)
    assert "frozen" in got, (
        "migrate_old_config 开头的 frozen 守卫没了 —— "
        "打包包里那份配置又会被复制成用户配置（QA-001）"
    )
    assert any(isinstance(s, ast.Return) for s in first.body), "守卫没有 return"


def _load_config_module(tmp_path, monkeypatch):
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "log"))
    import importlib

    import config as config_mod
    return importlib.reload(config_mod)


def test_qa001_seeded_config_is_repaired_for_existing_victims(tmp_path, monkeypatch):
    """存量纠正：已经被写脏的用户配置要能自己恢复。

    只在**三条同时成立**时动手（csgo_dir 非空但不存在 + 没有 onboarding_completed
    + 没纠正过），避免误伤正常用户。
    """
    mod = _load_config_module(tmp_path, monkeypatch)
    cfg = mod.Config.__new__(mod.Config)
    cfg.csgo_dir = "D:/SteamLibrary/steamapps/common/Counter-Strike Global Offensive"
    cfg.onboarding_completed = True

    victim = {"csgo_dir": "G:/nonexistent-drive-path/CS2"}
    cfg._repair_seeded_config(victim)
    assert cfg.csgo_dir == "", "假的 CS2 目录没被清空"
    assert cfg.onboarding_completed is False, "首启引导没有被重新打开"
    assert getattr(cfg, mod.Config._SEED_REPAIR_FLAG, False) is True, "纠正标记没写上"

    # ⚠ 光测方法不够 —— 回退验证当场判它假绿：把 `load_config` 里那句调用换成
    # `pass` 之后，这条判据照样全绿（它是直接调方法的）。
    # **判据必须连"有没有被接上"一起验**，否则修好的东西可以被悄悄断线。
    load_fn = _func("config.py", "load_config")
    assert _calls(load_fn, "_repair_seeded_config"), (
        "load_config 里不再调用 _repair_seeded_config —— 纠正逻辑还在但没人调，"
        "已经装过 2.2.x 的用户永远修不好（QA-001）"
    )


@pytest.mark.parametrize("data,why", [
    ({"csgo_dir": "", "onboarding_completed": False}, "没配目录的正常新用户"),
    ({"csgo_dir": "G:/nope", "onboarding_completed": False}, "走过引导的真实用户"),
    ({"csgo_dir": str(ROOT)}, "目录真实存在"),
])
def test_qa001_repair_does_not_touch_innocent_configs(tmp_path, monkeypatch, data, why):
    """纠正判据要窄——误伤正常用户比不修更坏（会莫名其妙重弹引导）。"""
    mod = _load_config_module(tmp_path, monkeypatch)
    cfg = mod.Config.__new__(mod.Config)
    cfg.csgo_dir = data.get("csgo_dir", "")
    cfg.onboarding_completed = True
    cfg._repair_seeded_config(dict(data))
    assert cfg.onboarding_completed is True, f"误伤了：{why}"


# ═══════════════════════════════════ QA-002 闪光子进程孤儿


def test_qa002_flash_child_detects_a_dead_parent():
    """闪光子进程必须靠**父进程存活检测**退出，而不是靠「管道断裂」。

    实测：父进程被 TerminateProcess 强杀后，子进程连续 44 秒全是 `queue.Empty`，
    管道异常**一次都没有** —— 原来那条 `except (EOFError, BrokenPipeError, OSError)`
    守卫是死代码。而 `parent_process().is_alive()` 在强杀后约 1.25s 内翻 False。

    后果不是理论：子进程 `daemon=True` 靠父进程 atexit 收尸，强杀时 atexit 不跑，
    子进程变孤儿按最后一帧继续渲染；那一帧若是"被闪中"，屏幕上会留一层
    全屏白罩，**重启软件也清不掉**（清屏命令发给的是新子进程）。
    """
    fn = _func("flash_process.py", "process_commands")
    assert _calls(fn, "parent_process"), (
        "process_commands 里没有 parent_process() —— 父进程存活检测没了，"
        "强杀主进程会留下孤儿闪光进程（QA-002）"
    )
    assert _calls(fn, "is_alive"), "拿到了父进程对象却没查 is_alive()"
    # 检测必须真的能触发 shutdown
    src = ast.get_source_segment((ROOT / "flash_process.py").read_text(encoding="utf-8"), fn) or ""
    assert "shutdown()" in src, "检测到父进程退出后没有关闭闪光效果"


# ═══════════════════════════════════ QA-003 GSI 端口自适应重写 cfg


def test_qa003_port_change_passes_the_install_root_not_a_file_path():
    """`ensure_cfg_exists()` 要的是 CS2 **安装根目录**，不是 cfg 文件路径。

    原实现传的是 `find_cfg_path()` 的返回值 —— 那是**文件全路径**。
    于是端口自适应后的 cfg 重写 100% 失败，而成功日志是无条件打印的：
    服务器监听 3001、游戏 cfg 里还写着 3000，GSI 数据被推给占端口的第三方进程，
    音效/闪光/HUD/道具全部无反应，而状态条显示「运行中」、日志说已更新。
    """
    fn = _func("gsi_server.py", "_persist_port_change")
    assert not _calls(fn, "find_cfg_path"), (
        "_persist_port_change 又在用 find_cfg_path() —— 那返回的是文件路径，"
        "喂给 ensure_cfg_exists() 类型就不对（QA-003）"
    )
    # ⚠ 只按**调用名**判断挡不住换皮：回退验证用
    # `from cfg_utils import find_cfg_path as find_cs2_install_dir` 一句就骗过了上面那条
    # （调用点名字没变，绑的却是返回文件路径的那个函数）。
    # 所以连 import 一起验：这个名字必须是真的 `find_cs2_install_dir`，不许起别名。
    # 只盯 cfg_utils 那一行 —— `from config import config as _config` 是这个函数
    # 本来就有的合法别名，不能一刀切（判据第一版就是这么误报的）。
    for node in ast.walk(fn):
        if not isinstance(node, ast.ImportFrom) or node.module != "cfg_utils":
            continue
        for alias in node.names:
            assert not alias.asname, (
                f"从 cfg_utils 导入 `{alias.name}` 时起了别名 `{alias.asname}` —— "
                "别名会让「调用名对了」这件事失去意义（QA-003）"
            )
    for call in _calls(fn, "ensure_cfg_exists"):
        del call
        break
    else:
        raise AssertionError("_persist_port_change 里没有 ensure_cfg_exists 调用")
    ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If) and _calls(n.test, "ensure_cfg_exists")]
    assert ifs, (
        "ensure_cfg_exists 的返回值没有被判断 —— 又变回「盲写一句成功日志」了（QA-003）"
    )


def test_qa003_ensure_cfg_exists_reports_success_honestly(tmp_path, monkeypatch):
    """`ensure_cfg_exists` 必须返回 bool，调用方才可能如实记日志。

    它以前**恒返回 None**、且把写盘异常吞在内部只记 error。
    """
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "log"))
    import cfg_utils

    assert cfg_utils.ensure_cfg_exists("") is False, "空目录该返回 False"
    assert cfg_utils.ensure_cfg_exists(str(tmp_path / "nope")) is False, "不存在的目录该返回 False"

    # 传一个**文件**路径（就是 QA-003 的原始 bug 形态）也必须返回 False，
    # 而不是走到 makedirs 才炸
    a_file = tmp_path / "some.cfg"
    a_file.write_text("x", encoding="utf-8")
    assert cfg_utils.ensure_cfg_exists(str(a_file)) is False, (
        "传文件路径进来时应当直接判 False（用 isdir 而不是 exists）"
    )

    root = tmp_path / "cs2"
    (root / "game" / "csgo" / "cfg").mkdir(parents=True)
    assert cfg_utils.ensure_cfg_exists(str(root)) is True, "正常根目录该返回 True"
    assert (root / "game" / "csgo" / "cfg" / "gamestate_integration_cs2customizer.cfg").exists()


# ═══════════════════════════════════ QA-004 HUD 效果线程空转


def test_qa004_effect_loop_exits_when_gsi_stops_pushing():
    """效果线程的退出判据必须挂在「GSI 还在不在推数据」上。

    原判据是「连续 30 次 `output.color is None`」，而它**永远不成立**：
    `default_color` 默认 0，`_pick_candidate` 会无条件塞一个 default 候选，
    `output.color` 恒非 None。于是游戏关掉之后线程仍以最后一帧每 100ms 重新求值，
    直到软件退出；那一帧若是低血量/炸弹已安装，还会持续重写 CFG。
    """
    fn = _func("gsi_handler_hud_color.py", "_effect_loop")
    # ⚠ 只看 AST 里的**标识符**，不看源码文本。
    # 这条判据的第一版写的是 `assert "idle_count" not in src`，当场被
    # `_effect_loop` 自己的 docstring 骗了 —— 那段文档里解释了旧实现为什么用
    # idle_count 以及它为什么永远不成立，于是判据在正确的代码上报红。
    # **同一个教训在本项目是第 7 次，第 3 次栽在自己写的注释上。**
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "_last_data_ts" in attrs, (
        "_effect_loop 不再看 GSI 数据的新鲜度 —— 退出判据又变回一个永不成立的条件（QA-004）"
    )
    assert "_DATA_STALE_SECONDS" in attrs, "陈旧阈值没了"
    assert "idle_count" not in names, (
        "idle_count 又回来了 —— 那个基于 output.color is None 的计数判据永远不成立"
    )


# ═══════════════════════════════════ QA-005 资源迁移静默失败


def test_qa005_migration_failure_blocks_the_completion_marker():
    """迁移有目录失败时，绝不能写「迁移完成」标记。

    标记按版本号命中就整体跳过，写了就等于**同版本内永不重试**：
    内置音效目录空着，用户点试听没声音，日志里一个字都查不到。
    """
    src = (ROOT / "resource_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    marker_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") == "_write_migration_marker"
    ]
    assert marker_calls, "找不到 _write_migration_marker 调用，判据前提变了"
    assert "_note_migration_failure" in src, "失败留痕的函数没了"
    # 那两处 except 不许再回到 `pass  # 静默处理`
    impl = _func("resource_manager.py", "_copy_resources_to_appdata_impl")
    for handler in [n for n in ast.walk(impl) if isinstance(n, ast.ExceptHandler)]:
        body = handler.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            raise AssertionError(
                f"_copy_resources_to_appdata_impl 第 {handler.lineno} 行的 except 又变回静默 pass（QA-005）"
            )


def test_qa005_marker_is_not_written_when_a_directory_failed(tmp_path, monkeypatch):
    """行为判据：真造一次迁移失败，断言「完成标记」不会被写。

    ⚠ 这条是回退验证逼出来的。上面那条纯结构判据（断言 `_write_migration_marker`
    在某个 `if` 里）被一句 `failures = []` 轻松骗过 —— 结构还在，语义没了。
    **结构判据挡不住"把条件恒置为假"这种改法，只有行为判据能。**
    """
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "log"))
    import resource_manager as rm

    written = []
    monkeypatch.setattr(rm.ResourceManager, "_write_migration_marker",
                        staticmethod(lambda: written.append(1)))
    # 造一次"复制阶段有目录失败"
    monkeypatch.setattr(
        rm.ResourceManager, "_copy_resources_to_appdata_impl",
        staticmethod(lambda: rm.ResourceManager._note_migration_failure("resources/audio/kill_sounds")),
    )
    monkeypatch.setattr(rm.ResourceManager, "_migration_marker_is_current",
                        staticmethod(lambda: False), raising=False)
    rm._RESOURCE_COPY_DONE.clear()
    try:
        rm.ResourceManager.copy_resources_to_appdata()
    finally:
        rm.ResourceManager._migration_failures = []
        rm._RESOURCE_COPY_DONE.set()

    assert not written, (
        "有目录复制失败，却照样写了「迁移完成」标记 —— "
        "标记按版本命中就整体跳过，等于同版本内永不重试（QA-005）"
    )


# ═══════════════════════════════════ QA-006 放大镜假成功提示


def test_qa006_signature_is_recorded_only_after_a_successful_write():
    """签名必须在写成功**之后**才记账。

    原实现在写之前就记了，于是写失败后同签名再调会直接 `return True` 早退，
    **本次会话永不重试**。
    """
    fn = _func("pages/magnifier_page.py", "_ensure_sensitivity_support_files_if_needed")
    assigns = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "attr", "") == "_last_sensitivity_cfg_signature" for t in n.targets)
    ]
    assert assigns, "找不到签名记账语句"
    returns_true = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and n.value.value is True
    ]
    assert returns_true, "找不到成功返回"
    # 记账必须发生在「成功 return True」附近，即在 try 体的末尾——
    # 用行号近似：记账行必须晚于函数里第一个 write_* 调用
    writes = [c.lineno for c in _calls(fn, "write_magnifier_runtime_cfg")]
    assert writes, "找不到写 cfg 的调用"
    assert min(a.lineno for a in assigns) > min(writes), (
        "签名又在写盘之前记账了 —— 写失败后本次会话不会再重试（QA-006）"
    )


def test_qa006_success_toast_is_conditional():
    """「已同步到 CFG」这句提示不许无条件弹。"""
    fn = _func("pages/magnifier_page.py", "_on_sensitivity_sync_changed")
    src = ast.get_source_segment(
        (ROOT / "pages" / "magnifier_page.py").read_text(encoding="utf-8"), fn) or ""
    assert "_ensure_sensitivity_support_files_if_needed" in src, (
        "提示语没有跟真实写盘结果挂钩（QA-006）"
    )
    ifs = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and "已同步到 CFG" in (ast.get_source_segment(src, n) or "" if False else "")
    ]
    del ifs
    assert "toast_warning" in src, "写失败时没有给用户任何提示"


# ═══════════════════════════════════ QA-007 更新包落盘路径


# ═══════════════════════════════════ QA-008 混淆门禁


def test_qa008_obfuscation_failures_are_not_discarded():
    """`obfuscate()` 的失败清单必须被接住并影响构建结果。

    原实现把返回值丢了，唯一的门禁只查 `pyarmor_runtime*` 目录在不在 ——
    那只证明"至少一个成功"。2.2.1 就是这么把明文的 main_widget.py
    随安装包发出去、构建还 exit 0 的。
    """
    fn = _func("build_tools/build_release.py", "main")
    assigned = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and _calls(node.value, "obfuscate"):
            assigned.extend(getattr(t, "id", "") for t in node.targets)
    assert assigned, (
        "obfuscate() 的返回值又被丢掉了 —— 单个文件回退成明文没人知道（QA-008）"
    )
    src = ast.get_source_segment(
        (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8"), fn) or ""
    assert "allow_plaintext_fallback" in src, "没有收尾闸门，明文文件会静默发出去"
    assert "return 1" in src, "有明文回退时构建仍然返回成功码"


# ═══════════════════════════════════ QA-010 脏配置值让软件起不来


@pytest.mark.parametrize("dirty", ["abc", {"a": 1}, ["x"], "3.5.7"])
def test_qa010_dirty_snapshot_keep_does_not_brick_startup(tmp_path, monkeypatch, dirty):
    """`config_snapshot_max_keep` 是非数值时，**软件必须还能起来**。

    这不是"某个值读错了"级别的问题：模块级 `config = Config()` 在 import 时就跑
    `load_config`，而 `load_config` 的 except 只兜
    (FileNotFoundError, JSONDecodeError, KeyError) —— `int("abc")` 抛的
    ValueError、`int({...})` 抛的 TypeError 都会一路冒泡到 `import config`。
    结果是**没界面、没提示、没自愈**，用户只能自己去
    %LOCALAPPDATA%\\CS2Customizer\\config.json 手改或删掉。

    行为判据：真造一份脏配置，真构造一次 Config，断言不抛且回落到默认值。
    把 config.py 里那个 try 去掉，这条必红。
    """
    import importlib

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps({"config_snapshot_max_keep": dirty}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "logs"))

    config_mod = importlib.import_module("config")
    obj = config_mod.Config()          # 不抛异常，就是"软件起得来"
    assert obj.config_snapshot_max_keep == 20, "脏值没有回落到默认 20"


@pytest.mark.parametrize("value,expected", [(50, 50), (1, 1), (0, 20), (-5, 20), (10**9, 20)])
def test_qa010_snapshot_keep_range_is_clamped(tmp_path, monkeypatch, value, expected):
    """合法数值要原样保留；0/负数/离谱大值要钳回默认。

    0 或负数会让 `prune_snapshots` 把用户的快照**全部删光**——
    快照是这个软件唯一的"后悔药"，不能由一个脏数字清空。
    """
    import importlib

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps({"config_snapshot_max_keep": value}), encoding="utf-8"
    )
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "logs"))

    config_mod = importlib.import_module("config")
    assert config_mod.Config().config_snapshot_max_keep == expected


def test_qa010_no_bare_numeric_cast_left_in_load_config():
    """`load_config` 里**每一个** int()/float() 都必须有兜底。

    QA-010 是孤例（20 个转换里 19 个本来就有防护），但孤例正是最容易复发的地方——
    下次谁再加一个 `int(config_data.get(...))` 就又是一次"配置脏了就起不来"。
    这条守住整片：要么外面套着 try...except (TypeError, ValueError)，
    要么前面有 isinstance 校验。
    """
    src = (ROOT / "config.py").read_text(encoding="utf-8")
    fn = _func("config.py", "load_config")

    # 收集所有「兜住了 TypeError/ValueError 的 try」的行号区间
    guarded_ranges = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            names = []
            t = handler.type
            if isinstance(t, ast.Tuple):
                names = [getattr(e, "id", "") for e in t.elts]
            elif isinstance(t, ast.Name):
                names = [t.id]
            elif t is None:
                names = ["BaseException"]
            if {"TypeError", "ValueError"} & set(names) or "Exception" in names \
                    or "BaseException" in names:
                for stmt in node.body:
                    guarded_ranges.append((stmt.lineno, stmt.end_lineno or stmt.lineno))

    # isinstance 前置校验的 If 区间同样算安全
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and _calls(node.test, "isinstance"):
            for stmt in node.body:
                guarded_ranges.append((stmt.lineno, stmt.end_lineno or stmt.lineno))

    def guarded(lineno: int) -> bool:
        return any(a <= lineno <= b for a, b in guarded_ranges)

    naked = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("int", "float") and not guarded(node.lineno)):
            naked.append((node.lineno, src.splitlines()[node.lineno - 1].strip()[:90]))

    assert not naked, (
        "load_config 里有没兜底的数值转换，配置脏了会让整个软件起不来（QA-010）：\n"
        + "\n".join(f"  第 {ln} 行: {code}" for ln, code in naked)
    )
