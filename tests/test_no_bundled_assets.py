# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""「包内不带任何素材」这条前提下的判据。

来历：开源版把 resources/ 整个删掉了（第三方游戏素材有版权），但仓库里 133 个
测试**没有一个读仓库真实的素材状态** —— 全部自己 mkdir 出一套目录再断言。
于是"干净安装的机器上 5 个必需目录根本不会被创建""onedir 打包必然失败"
这类缺陷一条都抓不到：测试全绿，因为分母里压根没有"真实仓库"这一项。

这里补的三类判据：
1. **行为判据**：在"包内无素材"的前提下真跑一遍资源迁移，断言资源体检 ok。
   把 resource_manager 的清单驱动建目录改回"源目录存在才建"，这条必红。
2. **仓库状态判据**：resources/ 必须是空骨架 —— 既不能真的消失（onedir 打包
   要靠它生成 _internal/resources），也不能混进素材文件。
3. **打包门禁判据**：--without-bundled-assets 的正反两面，以及 onedir/onefile
   两条校验路径的对称性（历史上 onedir 硬炸、onefile 静默出一个空壳 exe）。
"""
from __future__ import annotations

import ast
import importlib.util
import os
import threading
import types
from pathlib import Path

import pytest

import resource_manager
from config import config
from core.audio.audio_resource_health import REQUIRED_AUDIO_DIRS
from core.resource_catalog import RESOURCE_SPECS
from core.resource_health import collect_resource_system_health
from resource_manager import ResourceManager

ROOT = Path(__file__).resolve().parents[1]

# 素材文件后缀。仓库里出现任何一个就说明有人把第三方素材提交进来了。
ASSET_SUFFIXES = (
    ".mp3", ".wav", ".ogg", ".flac", ".m4a",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif",
)


# ═══════════════════════════════ ① 无素材时的资源迁移


def _neutralize_config(monkeypatch) -> None:
    """把所有"引用某个风格"的配置项按到中性值。

    这样体检报告里剩下的唯一变量就是**目录在不在** —— 判据要量的正是它。
    """
    for key in (
        "death_sound_style", "c4_sound_style", "health_warning_style",
        "round_start_style", "round_action_style", "round_win_style",
        "round_lose_style", "round_mvp_style",
    ):
        monkeypatch.setattr(config, key, "0", raising=False)
    for key in (
        "grenade_sound_styles", "weapon_switch_sounds", "weapon_reload_sounds",
        "weapon_kill_sounds", "weapon_kill_voices",
    ):
        monkeypatch.setattr(config, key, {}, raising=False)
    for key in ("kill_icon_enabled", "flash_enabled", "flash_audio_enabled", "crosshair_enabled"):
        monkeypatch.setattr(config, key, False, raising=False)


def _run_migration_into(tmp_path, monkeypatch):
    """把 AppData 与"包内资源"都重定向到 tmp，然后真跑一次 copy_resources_to_appdata。

    包内资源指向一个**空目录** —— 这就是"发布包里一个素材都没有"的前提。
    """
    app_data = tmp_path / "appdata"
    empty_package = tmp_path / "package"   # 模拟 _MEIPASS：存在，但里面什么都没有
    app_data.mkdir()
    empty_package.mkdir()

    def fake_app_data_path(relative_path):
        return str(app_data / relative_path.replace("/", os.sep).replace("\\", os.sep))

    def fake_exe_resource_path(relative_path):
        return str(empty_package / relative_path.replace("/", os.sep).replace("\\", os.sep))

    monkeypatch.setattr(resource_manager, "get_app_data_dir", lambda: str(app_data))
    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(fake_app_data_path))
    monkeypatch.setattr(ResourceManager, "get_exe_resource_path", staticmethod(fake_exe_resource_path))
    # 进程内一次性守卫：别的测试可能已经把它点亮了，这里换一套干净的
    monkeypatch.setattr(resource_manager, "_RESOURCE_COPY_LOCK", threading.Lock())
    monkeypatch.setattr(resource_manager, "_RESOURCE_COPY_DONE", threading.Event())
    monkeypatch.setattr(resource_manager, "_RESOURCE_COPY_STARTED", False)
    monkeypatch.setattr(ResourceManager, "_migration_failures", [], raising=False)

    ResourceManager.copy_resources_to_appdata()
    return app_data


def test_clean_install_without_any_bundled_asset_is_healthy(tmp_path, monkeypatch):
    """干净安装 + 零素材 → 资源体检必须是绿的。

    以前这里是黄的：目录创建走"包内源目录存在才建"，而开源版包内没有源目录，
    于是 kill_sounds / kill_voices / death / c4_sounds / health_warning 五个
    必需目录永远不存在 → summary.ok 恒 False → 首页系统状态开局就是黄灯、
    audio_health_check.py 退出码恒为 1。而这跟用户有没有素材毫无关系。
    """
    _neutralize_config(monkeypatch)
    _run_migration_into(tmp_path, monkeypatch)

    report = collect_resource_system_health()
    summary = report["summary"]

    assert summary["missing_directories"] == 0, (
        "缺失目录: "
        + ", ".join(report["audio"]["missing_directories"] + report["visual"]["missing_directories"])
    )
    assert summary["ok"] is True
    assert ResourceManager._migration_failures == []


def test_required_audio_dirs_are_all_created(tmp_path, monkeypatch):
    """逐个点名 12 个必需音频目录 —— 汇总数字对得上不代表每一个都在。

    同时兼作**清单漂移**的哨兵：REQUIRED_AUDIO_DIRS 与 resource_catalog 是两份
    清单，建目录只认后者。有人只往前者加一条，这里就会红。
    """
    _neutralize_config(monkeypatch)
    app_data = _run_migration_into(tmp_path, monkeypatch)

    audio_root = app_data / "resources" / "audio"
    missing = [rel for rel in REQUIRED_AUDIO_DIRS if not (audio_root / rel).is_dir()]
    assert missing == [], f"这些必需音频目录没有被创建: {missing}"

    for spec in RESOURCE_SPECS:
        target = app_data / "resources" / spec.target_rel_root.replace("/", os.sep)
        assert target.is_dir(), f"资源清单里的 {spec.key} 目录没有被创建: {target}"


def test_migration_marker_is_written_without_any_asset(tmp_path, monkeypatch):
    """无素材时"迁移完成"标记必须写得下、且下次启动能命中。

    标记的关键文件清单以前钉着两个具体 mp3（C4-1.mp3 / 我方还剩一人.mp3）。
    素材不随仓库分发之后那两个文件永远不会出现 → 判据恒不成立 →
    每次启动都白跑一遍完整资源扫描，B3 那条启动优化等于没有。
    """
    _neutralize_config(monkeypatch)
    app_data = _run_migration_into(tmp_path, monkeypatch)

    assert (app_data / resource_manager.MIGRATION_MARKER_FILENAME).is_file()
    assert ResourceManager._should_skip_migration() is True, (
        "写完标记后仍判定需要完整迁移 —— 关键路径清单又钉到了不存在的素材上"
    )


def test_no_empty_gun_style_directories_are_created(tmp_path, monkeypatch):
    """枪声只建到"武器"那一层，不预建风格目录。

    起源 / 弃王 / 奇点 / 塑水宗 / 天界 这些风格名是被删素材包的产物，
    凭空建出来只会让用户选中一个"点了没声音"的空风格。
    """
    _neutralize_config(monkeypatch)
    app_data = _run_migration_into(tmp_path, monkeypatch)

    gun_root = app_data / "resources" / "audio" / "gun_sounds"
    assert gun_root.is_dir()
    assert any(child.is_dir() for child in gun_root.iterdir()), "武器目录一个都没建"

    stray = [
        str(style.relative_to(gun_root))
        for weapon in gun_root.iterdir() if weapon.is_dir()
        for style in weapon.iterdir() if style.is_dir()
    ]
    assert stray == [], f"凭空建出了空的枪声风格目录: {stray}"


# ═══════════════════════════════ ② 仓库真实状态


def test_repository_ships_an_empty_resources_skeleton():
    """resources/ 必须存在，且必须是空的。

    两个方向都要挡：
    - 目录消失 → build_release 的 datas 不再生成 _internal/resources，
      onedir 产物校验直接 RuntimeError（默认的 onefile 更糟：静默出空壳）。
    - 混进素材 → 第三方版权文件被随仓库分发出去。
    """
    resources = ROOT / "resources"
    assert resources.is_dir(), (
        "resources/ 目录不见了 —— onedir 打包会因为缺 _internal/resources 而失败。"
        "保留一个只含 .gitkeep 的空骨架即可。"
    )
    assert (resources / ".gitkeep").is_file(), "resources/ 缺 .gitkeep，空目录进不了 git"

    leaked = [
        str(path.relative_to(ROOT))
        for path in resources.rglob("*")
        if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES
    ]
    assert leaked == [], f"仓库里混进了素材文件（第三方版权，不随仓库分发）: {leaked}"


# ═══════════════════════════════ ③ 打包门禁


def _build_release_module():
    spec = importlib.util.spec_from_file_location(
        "_build_release_no_assets", ROOT / "build_tools" / "build_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_onedir_tree(tmp_path, *, with_resources: bool) -> Path:
    folder = tmp_path / "CS2 Customizer 9.9.9"
    internal = folder / "_internal"
    (internal / "PySide6").mkdir(parents=True)
    (internal / "core").mkdir()
    (internal / "core" / "search_index.json").write_text("{}", encoding="utf-8")
    (internal / "python313.dll").write_bytes(b"x")
    (folder / "CS2 Customizer.exe").write_bytes(b"x")
    if with_resources:
        (internal / "resources").mkdir()
    return folder


def test_onedir_gate_rejects_missing_resources_by_default(tmp_path):
    """默认（要带素材）时缺 _internal/resources 必须炸。"""
    mod = _build_release_module()
    folder = _fake_onedir_tree(tmp_path, with_resources=False)

    with pytest.raises(RuntimeError, match="resources"):
        mod.verify_onedir_tree(folder, "CS2 Customizer", require_obfuscation=False)


def test_onedir_gate_accepts_missing_resources_when_declared(tmp_path, monkeypatch):
    """显式声明"这次不带素材"时，同一棵树必须放行。"""
    mod = _build_release_module()
    # 归档复核依赖外部工具，这里只量资源这一条，直接短路掉
    monkeypatch.setattr(mod, "find_tool", lambda name: None)
    folder = _fake_onedir_tree(tmp_path, with_resources=False)

    mod.verify_onedir_tree(
        folder, "CS2 Customizer", require_obfuscation=False, require_bundled_assets=False
    )


def _patch_archive_viewer(mod, monkeypatch, entries):
    monkeypatch.setattr(mod, "find_tool", lambda name: "pyi-archive_viewer")
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=0, stdout="\n".join(entries)),
    )


def test_onefile_gate_is_symmetric_with_onedir(tmp_path, monkeypatch):
    """onefile 归档缺素材同样要炸 —— 别再留"onedir 炸 / onefile 静默"的不对称。

    默认模式就是 onefile（build_release 的 --mode default）。以前它只校验
    Python 模块、完全不看资源，于是资源缺失时会安静地产出一个没有任何素材的 exe。
    """
    mod = _build_release_module()
    exe = tmp_path / "CS2 Customizer.exe"
    exe.write_bytes(b"x")

    _patch_archive_viewer(mod, monkeypatch, list(mod.CRITICAL_ARCHIVE_MODULES))
    with pytest.raises(RuntimeError, match="resources"):
        mod.verify_onefile_archive(exe, require_bundled_assets=True)

    # 声明了不带素材 → 放行
    mod.verify_onefile_archive(exe, require_bundled_assets=False)

    # 归档里真有资源条目 → 放行（两种路径分隔符都要认）
    for asset_entry in ("resources/audio/kill_sounds/x.mp3", "resources\\audio\\kill_sounds\\x.mp3"):
        _patch_archive_viewer(mod, monkeypatch, list(mod.CRITICAL_ARCHIVE_MODULES) + [asset_entry])
        mod.verify_onefile_archive(exe, require_bundled_assets=True)


def test_build_cli_exposes_and_wires_the_flag():
    """开关存在还不够，得真接到两条校验路径上。

    走 AST 而不是字符串包含：这个项目已经因为子串判断误报过多次。
    """
    src = (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    flags = [
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]
    assert "--without-bundled-assets" in flags, "打包脚本没有声明 --without-bundled-assets"

    main_fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    wired = set()
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name not in ("verify_onedir_tree", "verify_onefile_archive"):
            continue
        if any(kw.arg == "require_bundled_assets" for kw in node.keywords):
            wired.add(name)
    assert wired == {"verify_onedir_tree", "verify_onefile_archive"}, (
        f"main() 里没把 require_bundled_assets 传给两条校验路径，只接上了: {sorted(wired)}"
    )


def test_prebuild_test_target_exists():
    """打包前跑的那个 pytest 目标必须真的存在。

    原先钉的是 tests/test_update_runtime.py —— 在线更新链路随开源裁剪删掉之后
    文件也没了，于是每一次不加 --skip-tests 的构建都会直接挂在 pytest 上。
    """
    src = (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    targets = [
        arg.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        for arg in ast.walk(node)
        if isinstance(arg, ast.Constant)
        and isinstance(arg.value, str)
        and arg.value.startswith("tests/")
    ]
    assert targets, "build_release 里找不到打包前的 pytest 目标，判据前提变了"
    for target in targets:
        assert (ROOT / target).is_file(), f"打包前要跑的测试文件不存在: {target}"
