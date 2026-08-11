#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FanTool release builder.

Goals:
1. Keep full feature compatibility.
2. Minimize package size without removing required runtime modules.
3. Raise reverse-engineering cost with optional PyArmor obfuscation.
"""

from __future__ import annotations

import argparse
import ast
import codecs
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from packaging.version import InvalidVersion, Version


# 注意：当前 PyArmor 为 trial 版，对超大文件（如 122KB 的 gui_widget.py）
# 会 "out of license"，故 gui_widget 不纳入混淆目标；要混淆它需购买
# PyArmor 正式授权或改用 Nuitka（见 docs 打包说明）。
# 仅混淆项目根目录的 .py（子目录混淆会改变 pyarmor_runtime 布局，风险高）。
#
# 账号 / 授权 / 在线更新三条链路的模块已随开源版一并删除，不再是混淆目标。
DEFAULT_OBFUSCATE_TARGETS = [
    # —— 入口 ——
    "main_widget.py",
    # —— 原有核心目标 ——
    "gsi_server.py",
    "gsi_handler_kills.py",
    "gsi_handler_sounds.py",
    "gsi_handler_special.py",
    "resource_manager.py",
]

BASE_HIDDEN_IMPORTS = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "pygame",
    "PIL",
    "PIL.Image",
    "PIL.ImageQt",
    "flask",
    "requests",
    "numpy",
    "pynput",
    "pynput.keyboard",
    # v5 Phase 5: icon 系统
    "qtawesome",
    "qtpy",
]

EXCLUDES = [
    "matplotlib",
    "matplotlib.pyplot",
    "pandas",
    "scipy",
    "sklearn",
    "cv2",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "torch",
    "tensorflow",
    "seaborn",
    "OpenGL",
    "OpenGL_accelerate",
    "clr",
    "clr_loader",
    "pythonnet",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtDBus",
]

LOCAL_MODULE_EXCLUDES = {
    "__init__",
    "main_widget",
}

CRITICAL_LOCAL_MODULES = [
    "gui_widget",
    "config",
    "resource_manager",
]

# 归档校验：确认这些模块确实被打进包里（明文或混淆均可，只校验存在性）
CRITICAL_ARCHIVE_MODULES = [
    "main_widget",
    "gui_widget",
    "gsi_server",
    "resource_manager",
]

# onefile 归档里资源条目的前缀。PyInstaller 把 datas 的目标名按 os.sep 规范化，
# 所以两种分隔符都要认（打包机是 Windows，但判据不该依赖这一点）。
BUNDLED_ASSET_PREFIXES = ("resources/", "resources\\")

MIN_PYINSTALLER_SPLASH_CENTER = (6, 21, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FanTool release package")
    parser.add_argument(
        "--mode",
        choices=["onefile", "onedir"],
        default="onefile",
        help="PyInstaller output mode",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run PyInstaller",
    )
    parser.add_argument(
        "--no-obfuscate",
        action="store_true",
        help="Skip PyArmor obfuscation",
    )
    # 2.1.3: strict 默认关——当前 PyArmor 为 trial 版，联网校验偶发 "out of license"，
    # strict 默认开会让 build 因偶发失败而频繁挂掉。改为默认关 + 失败醒目警告 +
    # 自动重试（见 obfuscate）。买正式授权后建议用 --strict-obfuscation 强约束。
    #
    # ⚠ 2.2.2 实测修正「偶发」这个说法（此前一直是推测，没量过）：
    #   trial 的 "out of license" 对**超限文件是确定性的**，重试多少次都一样。
    #   把 main_widget.py 按顶层语句边界截断后逐档试：
    #     21414 / 28541 / 42241 字节 → 成功（42241 这档连打 3 次全成）
    #     45977 / 80085 字节         → 全部 out of license（全量连打 4 次全败）
    #   但**不是按原文件字节数**卡的：gsi_handler_kills.py 有 50962 字节却能过，
    #   说明限额落在编译后的代码对象规模上，UI 密集的 main_widget.py 特别吃亏。
    #   ⇒ 自动重试只对小文件的网络抖动有意义；main_widget.py 这类超限文件，
    #     唯一出路是买正式授权或把文件拆小，别浪费时间重跑。
    parser.add_argument(
        "--strict-obfuscation",
        dest="strict_obfuscation",
        action="store_true",
        default=False,
        help="Fail build if any obfuscation target fails (recommended once PyArmor is licensed)",
    )
    # QA-008: `--strict-obfuscation` 是"**当场**炸"，默认关是因为 trial 版偶发失败会
    # 让 build 频繁挂掉——这个理由成立。但它留下了另一个洞：不 strict 时失败只打印
    # 一行警告，构建照样 exit 0，**明文文件就这么随安装包发出去了**（2.2.1 实际发生过：
    # 9 个目标里 main_widget.py 回退明文，运行时目录还在，所有门禁全绿）。
    # 所以补一道"**收尾**才判"的闸门：重试都走完了还有失败 → 构建以非零码结束，
    # 除非操作者显式加这个开关表示"我知道这次有明文，就这么发"。
    parser.add_argument(
        "--allow-plaintext-fallback",
        dest="allow_plaintext_fallback",
        action="store_true",
        default=False,
        help="允许带着「混淆失败已回退为明文」的文件完成构建（默认不允许，构建会失败）",
    )
    # 2.1.3: UPX 改为默认关闭——UPX 加壳是杀软/SmartScreen 误报的主要来源之一，
    # 发布版宁可大几十 MB 也要换信任度。需要时用 --upx 显式开启。
    parser.add_argument(
        "--upx",
        dest="use_upx",
        action="store_true",
        default=False,
        help="Enable UPX compression (default: off; UPX is a common AV false-positive source)",
    )
    # 开源版不内置素材（resources/ 在仓库里只是个带 .gitkeep 的空骨架）。
    # 骨架还在时打包链路一切照旧；但只要有人把它清掉、或用别的方式裁剪产物，
    # 就得显式声明"这次就是不带素材"，否则产物校验会拦下来。
    parser.add_argument(
        "--without-bundled-assets",
        dest="without_bundled_assets",
        action="store_true",
        default=False,
        help="产物不含 resources/ 素材（跳过资源存在性断言；onedir/onefile 同时放宽）",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip pre-build packaging sanity tests",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only prepare staging/spec, do not run PyInstaller",
    )
    parser.add_argument(
        "--debug-console",
        action="store_true",
        help="Build with console window enabled for runtime traceback capture",
    )
    parser.add_argument(
        "--show-windowed-traceback",
        action="store_true",
        help="Enable PyInstaller windowed traceback popup (off by default in release builds)",
    )
    return parser.parse_args()


def run(cmd: List[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"[CMD] {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
    )


def parse_pyinstaller_version(version: str) -> tuple[int, int, int]:
    try:
        parsed = Version(version)
    except InvalidVersion as exc:
        raise RuntimeError(
            f"onefile splash positioning requires PyInstaller >= 6.21.0; "
            f"found invalid version {version!r}"
        ) from exc
    if parsed.is_prerelease or parsed.is_devrelease:
        raise RuntimeError(
            f"onefile splash positioning requires PyInstaller >= 6.21.0; "
            f"found non-final version {version}"
        )
    return parsed.major, parsed.minor, parsed.micro


def require_splash_center_support(version: str) -> None:
    if parse_pyinstaller_version(version) < MIN_PYINSTALLER_SPLASH_CENTER:
        raise RuntimeError(
            f"onefile splash positioning requires PyInstaller >= 6.21.0; found {version}"
        )


def _diagnostic_summary(detail: str | None, limit: int = 300) -> str:
    summary = " ".join((detail or "").split())
    if len(summary) > limit:
        return summary[: limit - 3] + "..."
    return summary


def query_pyinstaller_version(python_executable: str) -> str:
    command = [
        python_executable,
        "-c",
        "import PyInstaller; print(PyInstaller.__version__)",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = _diagnostic_summary(exc.stderr) or _diagnostic_summary(exc.stdout)
        if not detail:
            detail = "no diagnostic output"
        raise RuntimeError(
            f"Failed to query PyInstaller with {python_executable!r}; "
            f"exit code {exc.returncode}: {detail}"
        ) from exc
    except OSError as exc:
        detail = _diagnostic_summary(str(exc)) or "unknown operating system error"
        raise RuntimeError(
            f"Failed to query PyInstaller with {python_executable!r}: {detail}"
        ) from exc
    return result.stdout.strip()


def build_pyinstaller_command(
    python_executable: str,
    spec_path: Path,
    work_path: Path,
    dist_path: Path,
    upx_path: str | Path | None,
    require_splash_center: bool,
) -> List[str]:
    if require_splash_center:
        version = query_pyinstaller_version(python_executable)
        require_splash_center_support(version)

    command = [
        python_executable,
        "-m",
        "PyInstaller",
        str(spec_path),
        "--noconfirm",
        "--clean",
        "--workpath",
        str(work_path),
        "--distpath",
        str(dist_path),
    ]
    if upx_path:
        command.extend(["--upx-dir", str(Path(upx_path).parent)])
    return command


def read_version(config_file: Path) -> str:
    text = config_file.read_text(encoding="utf-8")
    match = re.search(r'^\s*VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Cannot parse VERSION from config.py")
    return match.group(1).strip()


def find_tool(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    if name.lower() == "upx":
        script_dir = Path(__file__).resolve().parent
        candidates = [
            script_dir / "upx" / "upx.exe",
            script_dir.parent / ".tools" / "upx" / "upx.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    return None


def copy_project(project_root: Path, stage_dir: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        ".build",
        ".pytest_cache",
        ".tmp_baseline_*",
        "__pycache__",
        "tests",
        "logs",
        "release",
        "artifacts",
        "output",
        "tmp_pyarmor_test_*",
        "pyarmor.bug.log",
        "*.pyc",
        "*.pyo",
        "_eval_*.py",
        "_offscreen_pages",
        "*.pem",
        "*.key",
        # 2.1.3: 进一步排除非运行期产物，避免污染 stage / 拖慢打包
        "_refactor_snapshots",
        "_archive_*",
        ".fuse_hidden*",
        # QA-001: **开发机的活配置绝不能进 stage**。
        # 仓库根的 config.json 是开发者自己在用的那一份（csgo_dir 指向开发机的
        # Steam 库盘符）。它以前被 datas 打进发布包，落到 `_internal/config.json`；
        # 新机首启时 `config.migrate_old_config()` 看到"程序目录旁有配置、用户目录没有"，
        # 就 `shutil.copy2` 把它原样复制成用户配置 —— 于是：
        #   ① CS2 目录指向一个用户机器上不存在的盘 → 四个写 cfg 的函数全部静默 return，
        #      击杀音效 / HUD 联动 / GSI 全不工作；
        #   ② 种子配置里没有 `onboarding_completed` 键，`load_config` 取默认值 True，
        #      **本该教用户"第一步选 CS2 目录"的首启引导恰好同时被关掉**；
        #   ③ 开发者的一堆开关（枪声风格、快捷键、音量、主题）变成别人的"出厂默认"。
        # 从源头挡掉，比只删 datas 更稳 —— 以后谁再往 datas 里加一行也带不出去。
        "config.json",
    )
    shutil.copytree(project_root, stage_dir, ignore=ignore)


def strip_utf8_bom(file_path: Path) -> bool:
    raw = file_path.read_bytes()
    if not raw.startswith(codecs.BOM_UTF8):
        return False
    file_path.write_bytes(raw[len(codecs.BOM_UTF8) :])
    return True


def obfuscate(stage_dir: Path, project_root: Path, strict: bool) -> List[str]:
    pyarmor = find_tool("pyarmor")
    if not pyarmor:
        msg = "pyarmor is not installed"
        if strict:
            raise RuntimeError(msg)
        print(f"[WARN] {msg}, continue without obfuscation")
        return list(DEFAULT_OBFUSCATE_TARGETS)

    # 对单文件做有限重试。
    #
    # ⚠ 别指望它救 "out of license"。原注释写的是"偶发…消化抖动"，
    #   QA-009 实测把这条推翻了：**超限文件的失败是确定性的，不是抖动**——
    #   `main_widget.py` 连打 4 次全败，截到 42241 字节后连打 3 次全成。
    #   而且限额不按原文件字节数卡（`gsi_handler_kills.py` 50962 字节能过），
    #   卡的是编译后代码对象规模。⇒ **超限文件重跑构建是白烧时间**，
    #   出路只有买授权 / 拆文件 / `--allow-plaintext-fallback`。
    #   重试留着是为了另一种失败模式（联网校验的网络抖动），那个确实是随机的。
    max_attempts = 3
    failed: List[str] = []
    for rel in DEFAULT_OBFUSCATE_TARGETS:
        target = stage_dir / rel
        if not target.exists():
            continue
        if strip_utf8_bom(target):
            print(f"[INFO] Stripped UTF-8 BOM for {rel} (stage copy)")

        ok = False
        for attempt in range(1, max_attempts + 1):
            print(f"[INFO] Obfuscating {rel} (attempt {attempt}/{max_attempts})")
            cmd = [pyarmor, "gen", "-O", str(stage_dir), str(target)]
            result = run(cmd, check=False)
            if result.returncode == 0:
                ok = True
                break
            print(f"[WARN] PyArmor returned {result.returncode} on {rel}")
            if attempt < max_attempts:
                import time as _t

                _t.sleep(3)

        if not ok:
            failed.append(rel)
            # 混淆失败时回退到明文源，保证功能不受影响（仅失去该文件的混淆保护）。
            shutil.copy2(project_root / rel, target)
            if strict:
                raise RuntimeError(f"PyArmor failed on {rel} after {max_attempts} attempts")

    if failed:
        print("=" * 60)
        print("[WARN] 以下文件混淆失败，已回退为明文打包（功能正常，但无混淆保护）:")
        print("       " + ", ".join(failed))
        print("       原因通常是 PyArmor trial 版授权限制；建议购买正式授权后重打。")
        print("=" * 60)
    else:
        print("[INFO] 全部混淆目标处理成功")
    return failed


def py_list(items: Iterable[str], indent: int = 4) -> str:
    prefix = " " * indent
    rows = [f"{prefix}{item!r}," for item in items]
    if not rows:
        return "[]"
    return "[\n" + "\n".join(rows) + "\n]"


def collect_local_hidden_imports(project_root: Path, stage_dir: Path) -> List[str]:
    local_modules: set[str] = {
        py_file.stem
        for py_file in stage_dir.glob("*.py")
        if py_file.is_file() and py_file.stem not in LOCAL_MODULE_EXCLUDES
    }

    seed_files = ["main_widget.py"] + list(DEFAULT_OBFUSCATE_TARGETS)
    discovered: set[str] = set()
    parse_failures: List[str] = []

    for rel in seed_files:
        src = project_root / rel
        if not src.exists():
            continue
        try:
            source = src.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(src))
        except Exception:
            parse_failures.append(rel)
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod in local_modules:
                        discovered.add(mod)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                if mod in local_modules:
                    discovered.add(mod)

    if parse_failures:
        print("[WARN] Failed to parse source files for hidden-import discovery:", ", ".join(parse_failures))
        discovered.update(local_modules)

    for mod in CRITICAL_LOCAL_MODULES:
        if (stage_dir / f"{mod}.py").exists():
            discovered.add(mod)

    return sorted(discovered)


def build_spec_text(
    stage_dir: Path,
    app_name: str,
    mode: str,
    upx_enabled: bool,
    runtime_modules: List[str],
    local_modules: List[str],
    console_enabled: bool,
    windowed_traceback: bool,
) -> str:
    datas: List[str] = []
    data_entries = [
        (stage_dir / "resources", "resources"),
        (stage_dir / "icon.ico", "."),
        (stage_dir / "myicon.ico", "."),
        # splash.png 也随包分发：onefile 用 PyInstaller Splash 显示;
        # onedir(安装包形态)无 Tk 闪屏,由 main_widget 用 QSplashScreen 显示同一张图
        (stage_dir / "splash.png", "."),
        # QA-001: 这里原本有 `(stage_dir / "config.json", ".")`，已删除。
        # 理由见 copy_project 的 ignore_patterns —— 那是开发机的活配置，不是出厂默认。
        # 真正的出厂默认在 `config.py` 的 `Config.__init__` 里，不需要随包带文件。
        # launcher_config.json 留着：它只有 preferred_version / auto_launch，是通用的。
        (stage_dir / "launcher_config.json", "."),
        # 设置搜索的项级索引（S2）。是**只读静态资源**，不是配置——
        # 它不会被 migrate_old_config 复制成用户配置，与 QA-001 那条链无关。
        # 但它必须真进包：PyInstaller 只把 .py 收进 PYZ，包内的 .json 不会自动带上，
        # 漏了的话开发机搜索一切正常、装完只剩页级搜索，是典型的假绿。
        # 所以下面 verify_onedir_tree 的正向清单里也钉了一条。
        (stage_dir / "core" / "search_index.json", "core"),
    ]
    for src, dst in data_entries:
        if src.exists():
            datas.append(f"({str(src)!r}, {dst!r})")
        else:
            # 这里原来是静默跳过。缺 resources/ 时它跟 verify_onedir_tree 的硬断言
            # 撞在一起：onedir 直接 RuntimeError，onefile 却一路绿到底。
            # 断言的不对称已在 verify_* 里修掉，这行是让"少带了什么"当场看得见。
            print(f"[WARN] data entry missing, not bundled: {src}")

    hidden = list(BASE_HIDDEN_IMPORTS)
    hidden.extend(runtime_modules)
    hidden.extend(local_modules)
    hidden = list(dict.fromkeys(hidden))

    # 2.2.0: 启动闪屏(splash.png 在项目根;bootloader 0.2s 内出画面,
    # 主窗 show 后由 main_widget 的 pyi_splash.close() 收场)
    splash_png = stage_dir / "splash.png"
    splash_enabled = mode == "onefile" and splash_png.exists()
    stable_splash_class = """class StableSplash(Splash):
    def generate_script(self):
        script = super().generate_script()
        package_marker = "package require Tk"
        raise_marker = "raise ."
        package_count = script.count(package_marker)
        raise_count = script.count(raise_marker)
        if package_count != 1 or raise_count != 1:
            raise RuntimeError(
                "Unexpected PyInstaller splash template: expected exactly one "
                f"{package_marker!r} and one {raise_marker!r}, found "
                f"{package_count} and {raise_count}"
            )
        script = script.replace(
            package_marker,
            package_marker + "\\nwm withdraw .",
            1,
        )
        script = script.replace(
            raise_marker,
            "update idletasks\\nwm deiconify .\\n" + raise_marker,
            1,
        )
        with open(self.script_name, "w", encoding="utf-8") as script_file:
            script_file.write(script)
        return script

""" if splash_enabled else ""
    splash_decl = (
        f"splash = StableSplash({str(splash_png)!r}, binaries=a.binaries, datas=a.datas,\n"
        "                text_pos=None, minify_script=True, always_on_top=False,\n"
        "                center='active')\n"
        if splash_enabled else ""
    )
    splash_exe_args = "    splash,\n    splash.binaries,\n" if splash_enabled else ""

    onefile_block = f"""
{splash_decl}
exe = EXE(
    pyz,
    a.scripts,
{splash_exe_args}    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name={app_name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx={upx_enabled},
    console={console_enabled},
    disable_windowed_traceback={not windowed_traceback},
    icon={str(stage_dir / 'icon.ico')!r},
    version={str(stage_dir / 'version_info.txt')!r},
    uac_admin=False,
)
"""

    onedir_block = f"""
{splash_decl}
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={app_name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx={upx_enabled},
    console={console_enabled},
    disable_windowed_traceback={not windowed_traceback},
    icon={str(stage_dir / 'icon.ico')!r},
    version={str(stage_dir / 'version_info.txt')!r},
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx={upx_enabled},
    upx_exclude=[],
    name={app_name!r},
)
"""

    block = onefile_block if mode == "onefile" else onedir_block

    return f"""# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

def safe_collect(package_name):
    try:
        return collect_submodules(package_name)
    except Exception:
        return []

hiddenimports = {py_list(hidden)}
hiddenimports += safe_collect("pages")
hiddenimports += safe_collect("dialogs")
hiddenimports += safe_collect("widgets")
hiddenimports += safe_collect("core")

excludes = {py_list(EXCLUDES)}
datas = [
{chr(10).join(f"    {item}," for item in datas)}
]

a = Analysis(
    [{str(stage_dir / 'main_widget.py')!r}],
    pathex=[{str(stage_dir)!r}],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    # Do not use -OO: stripping docstrings breaks numpy/pygame import chain.
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
{stable_splash_class}
{block}
"""


def verify_onefile_archive(exe_path: Path, require_bundled_assets: bool = False) -> None:
    """校验 onefile 归档里的关键 Python 模块（可选：连素材一起校验）。

    `require_bundled_assets` 默认 False，因为 onedir 形态下资源在 `_internal/` 而
    不在 exe 归档里（那条由 verify_onedir_tree 负责）。真正的 onefile 构建必须传
    True —— 否则会留下一个很难看的不对称：**onedir 缺资源就炸，onefile 缺资源
    却一声不吭地产出一个没有任何素材的 exe**，而 onefile 恰好是默认模式。
    """
    viewer = find_tool("pyi-archive_viewer")
    if not viewer:
        print("[WARN] pyi-archive_viewer not found, skip archive verification")
        return

    cmd = [viewer, "-b", "-r", str(exe_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False,
                            encoding="utf-8", errors="replace")
    stdout = result.stdout or ""
    if result.returncode != 0 or not stdout.strip():
        print("[WARN] archive verification produced no output, skip strict verification")
        return

    lines = {line.strip() for line in stdout.splitlines() if line.strip()}
    missing = [name for name in CRITICAL_ARCHIVE_MODULES if name not in lines]
    if missing:
        raise RuntimeError(
            "Archive verification failed, missing critical modules: " + ", ".join(missing)
        )
    if require_bundled_assets and not any(
        line.startswith(BUNDLED_ASSET_PREFIXES) for line in lines
    ):
        raise RuntimeError(
            "Archive verification failed: 归档里没有任何 resources/ 条目 —— "
            "产出的会是一个没有素材的 exe。"
            "\n  —— 若本次就是要发不带素材的包，请显式加 --without-bundled-assets。"
        )
    print("[INFO] Archive verification passed:", ", ".join(CRITICAL_ARCHIVE_MODULES))


def verify_onedir_tree(
    folder: Path,
    app_name: str,
    require_obfuscation: bool = True,
    require_bundled_assets: bool = True,
) -> None:
    """onedir 产物校验(2.2.0):exe + _internal 关键件齐全才算打包成功。

    与 verify_onefile_archive 同级守门:混淆运行时/资源/Qt 任何一项缺失,
    都意味着包是坏的,宁可在打包机上炸也不能发出去。
    """
    exe = folder / f"{app_name}.exe"
    internal = folder / "_internal"
    checks = [
        ("主程序 exe", exe.is_file()),
        ("_internal 目录", internal.is_dir()),
        # S2: 设置搜索的项级索引。缺了不会崩，搜索会静默退回只有页级——
        # 「装完之后搜不到具体开关」这种事在开发机上永远复现不出来。
        ("设置搜索项级索引", (internal / "core" / "search_index.json").is_file()),
        ("PySide6 运行库", (internal / "PySide6").is_dir()),
        ("python 主 dll", bool(list(internal.glob("python3*.dll")))),
    ]
    if require_bundled_assets:
        # 这一条只在"这次要带素材"时成立。仓库里的 resources/ 是个只有 .gitkeep
        # 的空骨架，datas 照样能生成 _internal/resources；真把骨架清掉了，
        # 就该显式用 --without-bundled-assets 声明，而不是让断言无声地拦下构建。
        checks.append(("resources 资源", (internal / "resources").is_dir()))
    if require_obfuscation:
        # ⚠ QA-008：这一条只能证明"**至少有一个**目标混淆成功"（运行时目录被生成出来了），
        # **证明不了每个目标都成功**。2.2.1 那次构建 9 个目标里 `main_widget.py`
        # 因 PyArmor trial "out of license" 失败、按设计回退成明文，另外 8 个成功
        # → 运行时目录在 → 这道闸门通过 → 构建 exit 0 → **明文入口文件随安装包出货**。
        # 逐文件的账由 `obfuscate()` 的**返回值**记（哪些回退成了明文），
        # 一路传到 `main()` 末尾那道收尾闸门：有回退且没加
        # `--allow-plaintext-fallback` 就让构建失败。这里只保留运行时目录这条粗筛。
        # （原注释说交给 `verify_obfuscation_manifest()` —— **那个函数全仓不存在**，
        #  照着它去找会以为有一道并不存在的门禁。）
        checks.append(("PyArmor 运行时", bool(list(internal.glob("pyarmor_runtime*")))))
    missing = [name for name, ok in checks if not ok]
    if missing:
        raise RuntimeError("onedir 校验失败,缺失: " + ", ".join(missing))

    # QA-001: 反向断言 —— 有些东西**不许出现在产物里**。
    # 光有"缺什么就炸"的正向清单不够：config.json 是"多了才坏"，缺了反而是对的。
    # 打包时删一行很容易，下次有人为了别的目的又加回来同样容易，所以钉一道门。
    forbidden = [
        ("开发机配置 config.json", internal / "config.json"),
        ("开发机配置 config.json（根目录）", folder / "config.json"),
    ]
    leaked = [name for name, path in forbidden if path.exists()]
    if leaked:
        raise RuntimeError(
            "onedir 校验失败,产物里混进了不该带的东西: " + ", ".join(leaked)
            + "\n  —— 它会在新机首启时被 config.migrate_old_config() 复制成用户配置，"
            "把 CS2 目录写成打包机的路径，并让首启引导被跳过（QA-001）。"
        )
    # 嵌入 PYZ 的纯 Python 关键模块用 archive viewer 复核(与 onefile 同口径)。
    # onedir 的资源在 _internal/ 而不在 exe 归档里，所以这里不要求归档带素材。
    verify_onefile_archive(exe, require_bundled_assets=False)
    print("[INFO] onedir tree verification passed:", folder)


def main() -> int:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    config_file = project_root / "config.py"

    version = read_version(config_file)
    app_name = f"帆派助手{version}"  # 发布产物目录名:带版本号,保留历史
    exe_name = "帆派助手"  # C4 修复:打包出的 exe 固定名(不带版本),使开机自启/快捷方式路径跨版本稳定
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_root = project_root / ".build" / f"release-{stamp}"
    stage_dir = work_root / "stage"
    pyi_work_dir = work_root / "pyinstaller_work"
    dist_dir = work_root / "dist"
    release_dir = project_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Project root: {project_root}")
    print(f"[INFO] Version: {version}")
    print(f"[INFO] Mode: {args.mode}")
    print(f"[INFO] Work root: {work_root}")

    if not args.skip_tests:
        # 打包前的最小体检：原先跑的 tests/test_update_runtime.py 已随在线更新链路删除，
        # 留着会让每次不加 --skip-tests 的构建直接挂在 pytest 上。
        # 换成"无内置素材"这条 —— 它量的正是本脚本和 resource_manager 的这条链。
        run([args.python, "-m", "pytest", "-q", "tests/test_no_bundled_assets.py"], cwd=project_root)

    copy_project(project_root, stage_dir)

    obfuscation_failures: List[str] = []
    if not args.no_obfuscate:
        # ⚠ QA-008：这里原本把 `obfuscate()` 的返回值**丢掉了**。
        # 它返回的是"哪些文件混淆失败、已回退成明文"的清单，而唯一的下游门禁
        # `verify_onedir_tree` 只查 `pyarmor_runtime*` 目录在不在 ——
        # 那只能证明"至少一个成功"，单个文件回退它一点都看不出来。
        # 2.2.1 就是这么把明文的 main_widget.py 随安装包发出去、构建还报绿的。
        obfuscation_failures = obfuscate(
            stage_dir, project_root, strict=args.strict_obfuscation
        ) or []
    else:
        print("[INFO] Skip obfuscation by user option")

    runtime_modules = [d.name for d in stage_dir.glob("pyarmor_runtime_*") if d.is_dir()]
    if runtime_modules:
        print("[INFO] PyArmor runtime modules:", ", ".join(runtime_modules))
    else:
        print("[WARN] No PyArmor runtime modules detected")

    if args.use_upx:
        upx_path = find_tool("upx")
        upx_enabled = upx_path is not None
        if upx_enabled:
            print(f"[INFO] UPX detected: {upx_path}")
        else:
            print("[WARN] UPX requested but not found, compression disabled")
    else:
        upx_path = None
        upx_enabled = False
        print("[INFO] UPX disabled by default (release policy: fewer AV false positives)")

    local_hidden_imports = collect_local_hidden_imports(project_root, stage_dir)
    print(f"[INFO] Local hidden imports collected: {len(local_hidden_imports)}")
    for mod in CRITICAL_LOCAL_MODULES:
        if mod not in local_hidden_imports:
            if (stage_dir / f"{mod}.py").exists():
                print(f"[WARN] Critical module not added to hidden imports: {mod}")
            else:
                print(f"[WARN] Critical module file missing in stage: {mod}.py")

    spec_text = build_spec_text(
        stage_dir=stage_dir,
        app_name=exe_name,
        mode=args.mode,
        upx_enabled=upx_enabled,
        runtime_modules=runtime_modules,
        local_modules=local_hidden_imports,
        console_enabled=args.debug_console,
        windowed_traceback=args.show_windowed_traceback,
    )
    spec_path = work_root / f"build_{args.mode}.spec"
    spec_path.write_text(spec_text, encoding="utf-8")
    print(f"[INFO] Spec generated: {spec_path}")

    if args.dry_run:
        print("[INFO] Dry run mode, stop before PyInstaller build")
        return 0

    pyinstaller_cmd = build_pyinstaller_command(
        args.python,
        spec_path,
        pyi_work_dir,
        dist_dir,
        upx_path,
        require_splash_center=args.mode == "onefile",
    )

    run(pyinstaller_cmd, cwd=project_root)

    if args.mode == "onefile":
        artifact = dist_dir / f"{exe_name}.exe"
        if not artifact.exists():
            raise RuntimeError(f"Build finished but artifact missing: {artifact}")
        # 发布目录里保留带版本号的文件名(留历史);onedir 安装态内 exe 为固定名
        release_artifact = release_dir / f"{app_name}.exe"
        shutil.copy2(artifact, release_artifact)
    else:
        artifact = dist_dir / exe_name
        if not artifact.exists():
            raise RuntimeError(f"Build finished but artifact missing: {artifact}")
        release_artifact = release_dir / app_name
        if release_artifact.exists():
            shutil.rmtree(release_artifact)
        shutil.copytree(artifact, release_artifact)

    if release_artifact.is_file():
        verify_onefile_archive(
            release_artifact,
            require_bundled_assets=not args.without_bundled_assets,
        )
        size_mb = release_artifact.stat().st_size / (1024 * 1024)
        print(f"[DONE] Output: {release_artifact} ({size_mb:.2f} MB)")
    else:
        verify_onedir_tree(
            release_artifact,
            exe_name,
            require_obfuscation=not args.no_obfuscate,
            require_bundled_assets=not args.without_bundled_assets,
        )
        total_mb = sum(f.stat().st_size for f in release_artifact.rglob("*") if f.is_file()) / (1024 * 1024)
        print(f"[DONE] Output folder: {release_artifact} ({total_mb:.0f} MB)")

    # QA-008: 收尾闸门——重试都走完了还有回退成明文的文件，就不该悄悄发出去。
    # 报告落盘一份，方便事后复核"这个包里到底哪些是明文"。
    if obfuscation_failures:
        report = release_dir / f"obfuscation_fallback_{version}_{stamp}.txt"
        try:
            report.write_text(
                "以下文件混淆失败、已回退为明文打包：\n" + "\n".join(obfuscation_failures) + "\n",
                encoding="utf-8",
            )
        except Exception:
            report = None
        print("=" * 70)
        print(f"[FAIL] {len(obfuscation_failures)} 个文件以**明文**形式进了发布产物:")
        print("       " + ", ".join(obfuscation_failures))
        if report:
            print(f"       报告: {report}")
        if args.allow_plaintext_fallback:
            print("       --allow-plaintext-fallback 已开启，按你的要求继续发布。")
            print("=" * 70)
            return 0
        print("       构建判定为失败。")
        print("       ⚠ 别急着重跑：2.2.2 实测过，PyArmor trial 的 'out of license' 对**大文件是确定性的**，")
        print("          重试 N 次也是同一个结果（main_widget.py 连打 4 次全败；截到 42KB 连打 3 次全成）。")
        print("          只有小文件的偶发抖动才值得重跑。")
        print("       出路：① 买 PyArmor 正式授权（一劳永逸）；")
        print("             ② 把超限文件拆小到限额以下；")
        print("             ③ 确认这次可以带明文发 → 加 --allow-plaintext-fallback 重来。")
        print("=" * 70)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
