# -*- coding: utf-8 -*-
"""版本号四处同步的判据。

**为什么需要它**：抬版本号要手工改四个文件，而在此之前**没有任何判据看着这件事**——
漏改任何一处，1450 条用例全都不会红，构建也照常通过。发现的时候通常已经在用户机器上了。

    config.py                  VERSION —— 真源，build_release.py 正则读它定产物目录名
    version_info.txt           exe 文件属性（右键→详细信息）
    build_tools/installer.iss  安装包文件名与安装目录名
    README.md                  标题 + 更新日志小节

四处漏改的后果不同，但都不会被现有测试逮到：
- 漏 version_info.txt → 装上去右键看属性还是旧版本号，排障时会误导人
- 漏 installer.iss    → 安装包名字和安装目录还是旧版本，升级会装进另一个目录
- 漏 README.md        → 发布文案的原始素材失真

2026-08-11 建立（发布 2.2.2 时补的空缺，见 docs/发布流程.md）。

**判据的量法**：以 `config.py` 的 `VERSION` 为唯一真源，其余三处都必须由它推导得出。
不写死任何具体版本号——写死的话，下次抬版本这个文件自己就得改，那它就不是判据了。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CONFIG_PY = ROOT / "config.py"
VERSION_INFO = ROOT / "version_info.txt"
INSTALLER_ISS = ROOT / "build_tools" / "installer.iss"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def version() -> str:
    """真源：config.py 的 VERSION。"""
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', _read(CONFIG_PY), re.MULTILINE)
    assert m, "config.py 里找不到 VERSION —— 真源没了，其余判据无从谈起"
    return m.group(1)


def test_config_version_is_wellformed(version):
    """真源本身必须是 X.Y.Z 三段数字。"""
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"config.py 的 VERSION = {version!r} 不是 X.Y.Z 形式。"
        "version_info.txt 的四元组和 installer.iss 都按这个形状推导。"
    )


# ---------------------------------------------------------------- version_info.txt

def test_version_info_tuples_match(version):
    """filevers / prodvers 必须是 (X, Y, Z, 0)。"""
    expected = "(" + ", ".join(version.split(".")) + ", 0)"
    text = _read(VERSION_INFO)
    for field in ("filevers", "prodvers"):
        m = re.search(rf"{field}\s*=\s*(\([^)]*\))", text)
        assert m, f"version_info.txt 里找不到 {field}"
        assert m.group(1) == expected, (
            f"version_info.txt 的 {field} = {m.group(1)}，应为 {expected}（由 config.py VERSION={version} 推出）"
        )


def test_version_info_strings_match(version):
    """四个 StringStruct 必须与 VERSION 一致。

    FileVersion / ProductVersion 用四段（X.Y.Z.0），
    OriginalFilename / ProductName 用三段并带产品名前缀。
    """
    text = _read(VERSION_INFO)
    expected = {
        "FileVersion": f"{version}.0",
        "ProductVersion": f"{version}.0",
        "OriginalFilename": f"帆派助手{version}.exe",
        "ProductName": f"帆派助手{version}",
    }
    for key, want in expected.items():
        m = re.search(rf"StringStruct\(u'{key}',\s*u'([^']*)'\)", text)
        assert m, f"version_info.txt 里找不到 StringStruct {key}"
        assert m.group(1) == want, f"version_info.txt 的 {key} = {m.group(1)!r}，应为 {want!r}"


def test_version_info_has_no_stray_version(version):
    """version_info.txt 里**不允许出现**任何非当前版本的点分数字。

    这是四条里最强的一条：前两条要我把每个字段都枚举出来，枚举漏了就白搭；
    这条不枚举，直接扫全文——只要有一处没跟着抬，立刻红。

    该文件已实测确认只含版本号一种点分数字（无浮点常量、无其他版本引用），
    所以全文扫零误报。config.py 不能这么扫（满篇浮点数），
    installer.iss 也不能（第 7 行"与 2.1.3 降权方向一致"是正当的历史引用）。
    """
    allowed = {version, f"{version}.0"}
    found = set(re.findall(r"\d+(?:\.\d+)+", _read(VERSION_INFO)))
    stray = found - allowed
    assert not stray, (
        f"version_info.txt 里有没跟着抬的版本号: {sorted(stray)}（当前 VERSION={version}）"
    )


# ---------------------------------------------------------------- installer.iss

def test_installer_iss_appversion_matches(version):
    """#define AppVersion 是安装包文件名与安装目录名的来源，必须与 VERSION 一致。

    漏改的后果最重：装到 `帆派助手<旧版本>` 目录，升级变成并存两份。
    """
    m = re.search(r'#define\s+AppVersion\s+"([^"]+)"', _read(INSTALLER_ISS))
    assert m, "installer.iss 里找不到 #define AppVersion"
    assert m.group(1) == version, (
        f"installer.iss 的 AppVersion = {m.group(1)!r}，config.py VERSION = {version!r}"
    )


def test_installer_iss_header_comments_match(version):
    """文件头两行注释里的版本号也要跟着抬。

    只挑"声明本脚本版本"的那两处（首行的括号、次行的 /DAppVersion=），
    不碰正文里引用其他版本的说明文字——那些是正当的历史引用。
    """
    text = _read(INSTALLER_ISS)
    checks = [
        (r"安装脚本\((\d+\.\d+\.\d+)", "首行标题注释"),
        (r"/DAppVersion=(\d+\.\d+\.\d+)", "编译命令注释"),
    ]
    for pattern, label in checks:
        m = re.search(pattern, text)
        assert m, f"installer.iss 的{label}里找不到版本号（格式变了？）"
        assert m.group(1) == version, (
            f"installer.iss {label}写着 {m.group(1)}，应为 {version}"
        )


# ---------------------------------------------------------------- README.md / CHANGELOG.md

def test_readme_title_matches():
    """README 首行标题必须是项目名。

    开源化时这条判据换了落点：闭源版把版本号写在 README 标题里（`# 帆派助手 2.2.2`），
    开源项目的 README 是落地页，标题该是项目名；版本号归 CHANGELOG.md 管
    （见下一条）。判据要防的东西没变——只是"当前版本写在哪"变了。
    """
    first_line = _read(README).splitlines()[0]
    assert "CS2 Customizer" in first_line, (
        f"README.md 首行 {first_line!r} 不是项目名标题"
    )


def test_changelog_has_section_for_current_version(version):
    """CHANGELOG.md 里必须有当前版本的小节。

    格式为 Keep a Changelog 的 `## [X.Y.Z] - YYYY-MM-DD`。
    抬版本号却忘了写 changelog，发布时就没有可抄的内容——
    这正是闭源版发 2.2.0 / 2.2.1 时踩过的坑。
    """
    text = _read(CHANGELOG)
    versions = re.findall(r"^##\s*\[([^\]]+)\]", text, re.MULTILINE)
    assert version in versions, (
        f"CHANGELOG.md 里没有 `## [{version}]` 小节，现有小节: {versions[:6]}"
    )
