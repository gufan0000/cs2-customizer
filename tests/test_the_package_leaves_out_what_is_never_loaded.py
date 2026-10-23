# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 133 瘦身：安装目录里两样「打进来却永远不会被加载」的东西不再打包。
批 129 体检表（10-03）：安装目录 260MB，其中两份 OpenSSL（Qt TLS 插件那份 6.8MB 产品用不到）、Tcl/Tk 约 3MB
（产品里只有一个缺 pywin32 时的兜底弹窗用 Tk）。真打包后的「没了 / Python 的 ssl 还在」由 verify_onedir_tree 守。"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from build_tools import build_release

ROOT = Path(__file__).resolve().parents[1]


def _product_files():
    skip = {"tests", "scripts", "build_tools", "release", "build", "dist", ".build", "docs", ".venv", "venv"}
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).parts
        if rel[0] in skip or rel[0] == ".claude" or rel[0].startswith(("cfg-cs2customizer_backup", ".")):
            continue
        yield p


def test_no_product_module_imports_tk():
    users = []
    files = list(_product_files())
    assert len(files) >= 150, f"只扫到 {len(files)} 个产品文件（分母空了，这条必然全绿）"
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(n.split(".")[0] in ("tkinter", "_tkinter") for n in names):
                users.append(f"{p.relative_to(ROOT)}:{node.lineno}")
    assert not users, f"产品代码又 import 了 tkinter（打包已排除它，运行到这里会 ImportError）：{users}"


def test_the_spec_drops_the_unused_binaries_and_tk(tmp_path):
    spec = build_release.build_spec_text(stage_dir=tmp_path, app_name="CS2Customizer", mode="onedir", upx_enabled=False,
                                         runtime_modules=[], local_modules=[], console_enabled=False,
                                         windowed_traceback=False)
    compile(spec, "<spec>", "exec")
    assert "a.binaries = [b for b in a.binaries if os.path.basename(b[0]).lower() not in _drop]" in spec
    assert "'tkinter'" in spec and "'_tkinter'" in spec
    for keep in ("libssl-3.dll", "libcrypto-3.dll"):
        assert keep not in build_release.DROP_BINARIES, f"{keep} 是 Python 自己 HTTPS 用的，不许瘦掉"


def test_the_pywin32_fallback_still_shows_a_message(monkeypatch):
    import crosshair_animation

    shown = []
    import ctypes

    monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", lambda *a: shown.append(a) or 1, raising=False)
    crosshair_animation.show_win32_error()
    assert shown and "pywin32" in shown[0][1]


@pytest.mark.parametrize("suffix", ["-3.dll", "-3-x64.dll"])
def test_pruning_preserves_the_python_ssl_imports(tmp_path, monkeypatch, suffix):
    import _ssl
    from PyInstaller.depend import bindepend

    required = {"libssl" + suffix, "libcrypto" + suffix}
    sources = {name: str(Path(_ssl.__file__).with_name(name)) for name in required}
    monkeypatch.setattr(bindepend, "get_imports", lambda _: set(sources.items()))
    spec = build_release.build_spec_text(stage_dir=tmp_path, app_name="CS2Customizer", mode="onedir",
                                        upx_enabled=False, runtime_modules=[], local_modules=[],
                                        console_enabled=False, windowed_traceback=False)
    snippet = spec[spec.index("_drop ="):spec.index("pyz = PYZ")]
    names = sorted(required | set(build_release.DROP_BINARIES) | {"needed.pyd"})
    analysis = SimpleNamespace(binaries=[(name, "/source/" + name, "BINARY") for name in names])
    exec(compile(snippet, "<spec-pruning>", "exec"), {"a": analysis, "os": os})
    assert {item[0] for item in analysis.binaries} == required | {"needed.pyd"}
    assert {name: path for name, path, _ in analysis.binaries if name in required} == sources


@pytest.mark.parametrize("source", [None, "/unrelated-software/libssl-3-x64.dll"])
def test_pruning_rejects_missing_or_external_python_ssl_source(tmp_path, monkeypatch, source):
    from PyInstaller.depend import bindepend

    monkeypatch.setattr(bindepend, "get_imports", lambda _: {("libssl-3-x64.dll", source)})
    spec = build_release.build_spec_text(stage_dir=tmp_path, app_name="CS2Customizer", mode="onedir",
                                        upx_enabled=False, runtime_modules=[], local_modules=[],
                                        console_enabled=False, windowed_traceback=False)
    snippet = spec[spec.index("_drop ="):spec.index("pyz = PYZ")]
    with pytest.raises(RuntimeError, match="Python SSL dependency"):
        exec(compile(snippet, "<spec-pruning>", "exec"), {"a": SimpleNamespace(binaries=[]), "os": os})


@pytest.mark.parametrize("suffix", ["-3.dll", "-3-x64.dll"])
def test_onedir_checks_the_actual_ssl_dependency_names(tmp_path, monkeypatch, suffix):
    internal = tmp_path / "_internal"
    for directory in ("resources", "PySide6", "core"):
        (internal / directory).mkdir(parents=True, exist_ok=True)
    for file in ("python313.dll", "core/search_index.json", "libssl" + suffix, "libcrypto" + suffix):
        (internal / file).write_bytes(b"synthetic")
    (tmp_path / "test.exe").write_bytes(b"synthetic")
    required = {"libssl" + suffix, "libcrypto" + suffix}
    monkeypatch.setattr(build_release, "ssl_binary_dependencies", lambda _: required)
    build_release.verify_onedir_tree(tmp_path, "test", require_obfuscation=False)
    (internal / ("libcrypto" + suffix)).unlink()
    with pytest.raises(RuntimeError, match="SSL"):
        build_release.verify_onedir_tree(tmp_path, "test", require_obfuscation=False)
