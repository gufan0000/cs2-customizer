# SPDX-License-Identifier: GPL-3.0-or-later
"""安装包构建步骤（build_release.build_installer / ISCC 定位）。

背景：2.2.3 发版时因为只在 PATH 和 Program Files 里找 ISCC.exe，误判成"没装
Inno Setup、安装包做不了"，实际它装在 %LOCALAPPDATA%\\Programs 下。这批用例锁住
定位逻辑和三道前置判断，让同样的误判不会再以"沉默失败"的形式出现。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_build_release():
    # build_tools 不是包，按路径直接加载模块。
    module_path = PROJECT_ROOT / "build_tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_release = _load_build_release()


# ---------------------------------------------------------------- ISCC 定位


def test_inno_roots_include_localappdata_programs(monkeypatch):
    """用户级安装（仅为我安装）落在 %LOCALAPPDATA%\\Programs —— 就是被漏掉的那个。"""
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")

    roots = build_release.inno_setup_roots()

    assert Path(r"C:\Users\someone\AppData\Local\Programs") in roots
    assert Path(r"C:\Program Files") in roots
    assert Path(r"C:\Program Files (x86)") in roots


def test_inno_roots_skip_unset_env(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")

    assert build_release.inno_setup_roots() == [Path(r"C:\Program Files (x86)")]


def test_find_iscc_locates_user_level_install(tmp_path, monkeypatch):
    """PATH 上没有、但用户目录里装了 —— 必须能找到（这正是 2.2.3 踩的坑）。"""
    programs = tmp_path / "Local" / "Programs"
    iscc = programs / "Inno Setup 6" / "ISCC.exe"
    iscc.parent.mkdir(parents=True)
    iscc.write_text("stub", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: None)

    assert build_release.find_tool("iscc") == str(iscc)


def test_find_iscc_prefers_path_when_available(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: r"D:\onpath\ISCC.exe")

    assert build_release.find_tool("iscc") == r"D:\onpath\ISCC.exe"


def test_find_iscc_prefers_newer_major_version(tmp_path, monkeypatch):
    programs = tmp_path / "Programs"
    for version in ("5", "6"):
        target = programs / f"Inno Setup {version}" / "ISCC.exe"
        target.parent.mkdir(parents=True)
        target.write_text("stub", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: None)

    assert build_release.find_tool("iscc") == str(programs / "Inno Setup 6" / "ISCC.exe")


def test_find_iscc_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: None)

    assert build_release.find_tool("iscc") is None


# ------------------------------------------------------------ build_installer


STUB_ISS = "\n".join([
    "; stub",
    "OutputDir=..\\release\\installer",
    "OutputBaseFilename=CS2 Customizer 安装包_{#AppVersion}",
])


@pytest.fixture
def staged(tmp_path):
    """一个刚好能过前置检查的最小项目树。"""
    (tmp_path / "build_tools").mkdir()
    (tmp_path / "build_tools" / "installer.iss").write_text(STUB_ISS, encoding="utf-8")
    (tmp_path / "release" / "CS2 Customizer 9.9.9").mkdir(parents=True)
    return tmp_path


# ------------------------------------------------- 产物名由 installer.iss 说了算


def test_expected_path_follows_iss_declaration(tmp_path):
    """换了品牌/命名风格（开源版是 CS2Customizer-Setup-X）也要跟着走，不能写死。"""
    iss = tmp_path / "installer.iss"
    iss.write_text(
        "OutputDir=..\\release\\installer\nOutputBaseFilename=CS2Customizer-Setup-{#AppVersion}\n",
        encoding="utf-8",
    )

    result = build_release.expected_installer_path(iss, "3.1.4")

    assert result.name == "CS2Customizer-Setup-3.1.4.exe"
    assert result.parent == (tmp_path.parent / "release" / "installer").resolve()


def test_expected_path_rejects_iss_without_output_name(tmp_path):
    iss = tmp_path / "installer.iss"
    iss.write_text("OutputDir=..\\release\\installer\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="OutputBaseFilename"):
        build_release.expected_installer_path(iss, "1.0.0")


def test_real_iss_output_name_is_derivable():
    """仓库里真实的 installer.iss 必须能被解析出产物名（改了排版别把它弄哑）。"""
    iss = PROJECT_ROOT / "build_tools" / "installer.iss"
    result = build_release.expected_installer_path(iss, "9.9.9")

    assert result.name.endswith("9.9.9.exe")
    assert result.parent.name == "installer"


def test_installer_reports_where_it_searched(staged, monkeypatch):
    """找不到编译器时，报错必须**点名找过哪些地方** —— 否则又会被读成"没装"。"""
    monkeypatch.setattr(build_release, "find_tool", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    with pytest.raises(RuntimeError) as exc:
        build_release.build_installer(staged, "9.9.9", "CS2 Customizer 9.9.9")

    message = str(exc.value)
    assert r"C:\Users\someone\AppData\Local\Programs" in message
    assert "ISCC.exe" in message


def test_installer_rejects_missing_onedir_before_invoking_iscc(staged, monkeypatch):
    """源目录不在就该自己先拦下，而不是把一句路径错误甩给 Inno。"""
    calls = []
    monkeypatch.setattr(build_release, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(build_release, "find_tool", lambda _name: r"C:\fake\ISCC.exe")

    with pytest.raises(RuntimeError, match="onedir 产物不存在"):
        build_release.build_installer(staged, "1.0.0", "CS2 Customizer 1.0.0")

    assert calls == [], "前置未通过时不应该调起 ISCC"


def test_installer_passes_version_from_caller(staged, monkeypatch):
    """/DAppVersion 必须来自传入版本号 —— 这是防"打出上一版安装包"的关键一环。"""
    recorded = {}

    def fake_run(cmd, cwd=None, check=True):
        recorded["cmd"] = cmd
        out = staged / "release" / "installer" / "CS2 Customizer 安装包_9.9.9.exe"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 2048)

    monkeypatch.setattr(build_release, "run", fake_run)
    monkeypatch.setattr(build_release, "find_tool", lambda _name: r"C:\fake\ISCC.exe")

    result = build_release.build_installer(staged, "9.9.9", "CS2 Customizer 9.9.9")

    assert "/DAppVersion=9.9.9" in recorded["cmd"]
    assert recorded["cmd"][0] == r"C:\fake\ISCC.exe"
    assert result.name == "CS2 Customizer 安装包_9.9.9.exe"


def test_installer_fails_when_output_missing(staged, monkeypatch):
    """ISCC 退出码 0 但产物不在 —— 不能当成功报出去。"""
    monkeypatch.setattr(build_release, "run", lambda *a, **k: None)
    monkeypatch.setattr(build_release, "find_tool", lambda _name: r"C:\fake\ISCC.exe")

    with pytest.raises(RuntimeError, match="产物不在"):
        build_release.build_installer(staged, "9.9.9", "CS2 Customizer 9.9.9")


# ------------------------------------------------------------- installer.iss


def test_iss_has_no_stale_version_fallback():
    """installer.iss 不得再有写死的版本兜底常量（会静默打出上一版安装包）。"""
    text = (PROJECT_ROOT / "build_tools" / "installer.iss").read_text(encoding="utf-8")

    assert "#error" in text, "漏传 /DAppVersion 时必须响亮失败"
    assert "#define AppVersion" not in text, "兜底常量会随版本腐烂，只能由外部传入"
