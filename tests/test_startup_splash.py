import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from build_tools import build_release, make_installer_assets
from scripts import verify_splash_stability as splash_verifier
from scripts.verify_splash_stability import (
    center_offset,
    descendant_pids,
    rect_is_stable,
    same_monitor,
    select_reasonable_window,
    summarize_run,
)


def test_rect_is_stable_accepts_one_pixel_jitter():
    assert rect_is_stable([(100, 200, 700, 560), (101, 199, 701, 559)])


def test_rect_is_stable_rejects_drift_over_tolerance():
    assert not rect_is_stable([(100, 200, 700, 560), (102, 200, 702, 560)])


def test_center_offset_supports_negative_coordinate_monitor():
    assert center_offset((-1700, 200, -1100, 560), (-1920, 0, 0, 1080)) == (-440, -160)


def test_same_monitor_rejects_different_handles():
    assert not same_monitor(123, 456)


def test_summary_uses_monitor_bounds_not_work_area_for_centering():
    target = {
        "handle": 77,
        "rcMonitor": (-1920, 0, 0, 1080),
        "rcWork": (-1920, 40, 0, 1080),
    }
    actual = {
        "handle": 77,
        "rcMonitor": (-1920, 0, 0, 1080),
        "rcWork": (-1920, 0, 0, 1040),
    }
    samples = [(-1260, 360, -660, 720), (-1261, 360, -661, 720)]

    summary = summarize_run(samples, target, actual, main_window_visible=True)

    assert summary["center_offset_xy"] == (-1, 0)
    assert summary["center_offset_px"] == 1
    assert summary["max_drift_px"] == 1
    assert summary["passed"] is True


def test_summary_fails_for_monitor_handle_mismatch():
    target = {"handle": 77, "rcMonitor": (0, 0, 1920, 1080), "rcWork": (0, 0, 1920, 1040)}
    actual = {"handle": 88, "rcMonitor": (0, 0, 1920, 1080), "rcWork": (0, 0, 1920, 1040)}

    summary = summarize_run([(660, 360, 1260, 720)], target, actual, main_window_visible=True)

    assert summary["same_monitor"] is False
    assert summary["passed"] is False


@pytest.mark.parametrize(
    "samples",
    [
        [(924, 476, 1124, 676), (924, 476, 1124, 676)],
        [(724, 396, 1324, 756), (924, 476, 1124, 676)],
    ],
)
def test_summary_rejects_unexpected_splash_dimensions(samples):
    monitor = {
        "handle": 77,
        "rcMonitor": (0, 0, 2048, 1152),
        "rcWork": (0, 0, 2048, 1104),
    }

    summary = summarize_run(samples, monitor, monitor, main_window_visible=True)

    assert summary["passed"] is False


def test_descendant_pids_follows_recursive_parent_links():
    parents = {101: 100, 102: 101, 103: 999, 104: 102}

    assert descendant_pids(100, parents) == {101, 102, 104}


def test_select_reasonable_window_uses_first_visible_top_level_candidate():
    windows = [
        {"hwnd": 1, "pid": 100, "visible": False, "rect": (0, 0, 600, 360)},
        {"hwnd": 2, "pid": 999, "visible": True, "rect": (0, 0, 600, 360)},
        {"hwnd": 3, "pid": 100, "visible": True, "rect": (10, 20, 610, 380)},
        {"hwnd": 4, "pid": 100, "visible": True, "rect": (0, 0, 1, 1)},
    ]

    assert select_reasonable_window(windows, {100})["hwnd"] == 3


def test_capture_uses_window_handle_when_available(monkeypatch, tmp_path):
    calls = []

    class CapturedImage:
        def save(self, path):
            calls.append(("save", path))

    def fake_grab(**kwargs):
        calls.append(("grab", kwargs))
        return CapturedImage()

    monkeypatch.setattr(splash_verifier.ImageGrab, "grab", fake_grab)
    output = tmp_path / "window.png"

    splash_verifier._capture(output, (10, 20, 610, 380), hwnd=1234)

    assert calls[0] == ("grab", {"window": 1234})
    assert calls[1] == ("save", output)


def _build_spec(stage_dir: Path, mode: str) -> str:
    return build_release.build_spec_text(
        stage_dir=stage_dir,
        app_name="FanTool",
        mode=mode,
        upx_enabled=False,
        runtime_modules=[],
        local_modules=[],
        console_enabled=False,
        windowed_traceback=False,
    )


def _load_stable_splash(spec: str, base_class: type) -> type:
    module = ast.parse(spec)
    class_node = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "StableSplash"
        ),
        None,
    )
    assert class_node is not None, "onefile spec must define StableSplash"
    namespace = {"Splash": base_class}
    exec(compile(ast.Module(body=[class_node], type_ignores=[]), "<spec>", "exec"), namespace)
    return namespace["StableSplash"]


def _run_stable_splash_transform(tmp_path: Path, spec: str, source_script: str) -> str:
    class FakeSplash:
        def generate_script(self):
            Path(self.script_name).write_text(source_script, encoding="utf-8")
            return source_script

    stable_splash = _load_stable_splash(spec, FakeSplash)
    instance = stable_splash.__new__(stable_splash)
    instance.script_name = str(tmp_path / "Splash-00_script.tcl")
    result = instance.generate_script()
    written = Path(instance.script_name).read_text(encoding="utf-8")
    assert result == written
    return written


def _is_args_attribute(node, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "args"
        and node.attr == attribute
    )


def _find_main_build_wiring(source: str):
    module = ast.parse(source)
    main_function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    dry_run_if = next(
        node
        for node in main_function.body
        if isinstance(node, ast.If) and _is_args_attribute(node.test, "dry_run")
    )
    dry_run_return = next(
        node
        for statement in dry_run_if.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Return)
    )
    build_call = next(
        node
        for node in ast.walk(main_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_pyinstaller_command"
    )
    return dry_run_return, build_call


def test_onefile_spec_configures_centered_stable_splash(tmp_path):
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "splash.png").write_bytes(b"png")

    spec = _build_spec(stage_dir, "onefile")

    assert "class StableSplash(Splash):" in spec
    assert "splash = StableSplash(" in spec
    assert "text_pos=None" in spec
    assert "minify_script=True" in spec
    assert "always_on_top=False" in spec
    assert "center='active'" in spec
    assert "    splash,\n    splash.binaries,\n    a.binaries," in spec


def test_stable_splash_hides_root_until_layout_is_ready(tmp_path):
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "splash.png").write_bytes(b"png")
    spec = _build_spec(stage_dir, "onefile")
    source_script = """package require Tk
canvas .canvas -width 600 -height 360
pack .canvas
wm geometry . +724+396
raise .
"""

    script = _run_stable_splash_transform(tmp_path, spec, source_script)

    assert script.count("wm withdraw .") == 1
    assert script.count("update idletasks") == 1
    assert script.count("wm deiconify .") == 1
    assert (
        script.index("wm withdraw .")
        < script.index("canvas .canvas")
        < script.index("pack .canvas")
        < script.index("update idletasks")
        < script.index("wm deiconify .")
        < script.index("raise .")
    )


@pytest.mark.parametrize(
    "source_script",
    [
        "canvas .canvas\npack .canvas\nraise .\n",
        "package require Tk\npackage require Tk\ncanvas .canvas\nraise .\n",
        "package require Tk\ncanvas .canvas\npack .canvas\n",
        "package require Tk\ncanvas .canvas\nraise .\nraise .\n",
    ],
)
def test_stable_splash_rejects_unexpected_pyinstaller_template(
    tmp_path, source_script
):
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "splash.png").write_bytes(b"png")
    spec = _build_spec(stage_dir, "onefile")

    with pytest.raises(RuntimeError, match="PyInstaller splash template"):
        _run_stable_splash_transform(tmp_path, spec, source_script)


def test_onedir_spec_never_contains_splash(tmp_path):
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "splash.png").write_bytes(b"png")

    spec = _build_spec(stage_dir, "onedir")

    assert "StableSplash" not in spec
    assert "Splash(" not in spec
    assert "splash.binaries" not in spec


def test_onedir_spec_bundles_splash_png_as_data(tmp_path):
    """onedir 无 PyInstaller Tk 闪屏，但仍要把 splash.png 打进包，
    供 main_widget 的 Qt QSplashScreen 在安装版启动时显示同一张图。"""
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "splash.png").write_bytes(b"png")

    spec = _build_spec(stage_dir, "onedir")

    assert "splash.png" in spec


def test_parse_pyinstaller_version_returns_numeric_tuple():
    assert build_release.parse_pyinstaller_version("6.21.1") == (6, 21, 1)


@pytest.mark.parametrize("version", ["6.20.0", "6.19.0", "5.13.2"])
def test_splash_center_support_rejects_old_pyinstaller(version):
    with pytest.raises(RuntimeError, match=r"PyInstaller >= 6\.21\.0"):
        build_release.require_splash_center_support(version)


@pytest.mark.parametrize(
    "version",
    ["6.21.0rc1", "6.21.0.dev1", "6.21.0 garbage", "not-a-version"],
)
def test_splash_center_support_rejects_non_final_or_invalid_versions(version):
    with pytest.raises(RuntimeError, match=r"PyInstaller >= 6\.21\.0"):
        build_release.require_splash_center_support(version)


@pytest.mark.parametrize("version", ["6.21.0", "6.21.1", "7.0.0"])
def test_splash_center_support_accepts_supported_pyinstaller(version):
    build_release.require_splash_center_support(version)


def test_splash_center_minimum_version_is_pinned():
    assert build_release.MIN_PYINSTALLER_SPLASH_CENTER == (6, 21, 0)


def test_query_pyinstaller_version_uses_requested_interpreter(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return build_release.subprocess.CompletedProcess(command, 0, stdout="6.21.1\n")

    monkeypatch.setattr(build_release.subprocess, "run", fake_run)

    version = build_release.query_pyinstaller_version("custom-python")

    assert version == "6.21.1"
    command, kwargs = calls[0]
    assert command[:2] == ["custom-python", "-c"]
    assert "import PyInstaller" in command[2]
    assert kwargs == {"capture_output": True, "text": True, "check": True}


def test_query_pyinstaller_version_reports_stderr_and_exit_code(monkeypatch):
    def failed_run(command, **_kwargs):
        raise build_release.subprocess.CalledProcessError(
            7,
            command,
            output="less useful stdout",
            stderr="ModuleNotFoundError: No module named 'PyInstaller'",
        )

    monkeypatch.setattr(build_release.subprocess, "run", failed_run)

    with pytest.raises(RuntimeError) as exc_info:
        build_release.query_pyinstaller_version("broken-python")

    message = str(exc_info.value)
    assert "broken-python" in message
    assert "exit code 7" in message
    assert "ModuleNotFoundError" in message
    assert "less useful stdout" not in message


def test_query_pyinstaller_version_falls_back_to_stdout(monkeypatch):
    def failed_run(command, **_kwargs):
        raise build_release.subprocess.CalledProcessError(
            1,
            command,
            output="stdout diagnostic",
            stderr="  ",
        )

    monkeypatch.setattr(build_release.subprocess, "run", failed_run)

    with pytest.raises(RuntimeError, match="stdout diagnostic"):
        build_release.query_pyinstaller_version("python")


def test_query_pyinstaller_version_wraps_os_error(monkeypatch):
    def failed_run(_command, **_kwargs):
        raise OSError("executable not found")

    monkeypatch.setattr(build_release.subprocess, "run", failed_run)

    with pytest.raises(RuntimeError) as exc_info:
        build_release.query_pyinstaller_version("missing-python")

    message = str(exc_info.value)
    assert "missing-python" in message
    assert "executable not found" in message


def test_query_pyinstaller_version_truncates_long_diagnostics(monkeypatch):
    def failed_run(command, **_kwargs):
        raise build_release.subprocess.CalledProcessError(
            1,
            command,
            stderr="x" * 1000 + "SENTINEL",
        )

    monkeypatch.setattr(build_release.subprocess, "run", failed_run)

    with pytest.raises(RuntimeError) as exc_info:
        build_release.query_pyinstaller_version("python")

    message = str(exc_info.value)
    assert len(message) < 500
    assert "SENTINEL" not in message


def test_build_command_fails_before_returning_for_old_pyinstaller(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "query_pyinstaller_version", lambda _python: "6.20.0")

    with pytest.raises(RuntimeError, match=r"PyInstaller >= 6\.21\.0"):
        build_release.build_pyinstaller_command(
            "python",
            tmp_path / "app.spec",
            tmp_path / "work",
            tmp_path / "dist",
            None,
            require_splash_center=True,
        )


def test_build_command_skips_version_query_when_not_required(monkeypatch, tmp_path):
    def unexpected_query(_python):
        raise AssertionError("onedir command must not query PyInstaller version")

    monkeypatch.setattr(build_release, "query_pyinstaller_version", unexpected_query)

    command = build_release.build_pyinstaller_command(
        "python",
        tmp_path / "app.spec",
        tmp_path / "work",
        tmp_path / "dist",
        None,
        require_splash_center=False,
    )

    assert command == [
        "python",
        "-m",
        "PyInstaller",
        str(tmp_path / "app.spec"),
        "--noconfirm",
        "--clean",
        "--workpath",
        str(tmp_path / "work"),
        "--distpath",
        str(tmp_path / "dist"),
    ]


def test_build_command_accepts_supported_version_and_upx(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "query_pyinstaller_version", lambda _python: "6.21.0")
    upx_path = tmp_path / "upx" / "upx.exe"

    command = build_release.build_pyinstaller_command(
        "python",
        tmp_path / "app.spec",
        tmp_path / "work",
        tmp_path / "dist",
        upx_path,
        require_splash_center=True,
    )

    assert command[-2:] == ["--upx-dir", str(upx_path.parent)]


def test_main_uses_build_command_boundary_after_dry_run_guard():
    source = Path(build_release.__file__).read_text(encoding="utf-8")
    dry_run_return, build_call = _find_main_build_wiring(source)
    requirement = next(
        keyword.value
        for keyword in build_call.keywords
        if keyword.arg == "require_splash_center"
    )

    assert dry_run_return.lineno < build_call.lineno
    assert isinstance(requirement, ast.Compare)
    assert _is_args_attribute(requirement.left, "mode")
    assert len(requirement.ops) == 1
    assert isinstance(requirement.ops[0], ast.Eq)
    assert len(requirement.comparators) == 1
    assert isinstance(requirement.comparators[0], ast.Constant)
    assert requirement.comparators[0].value == "onefile"


def test_build_requirements_pin_supported_pyinstaller_range():
    project_root = Path(build_release.__file__).resolve().parent.parent

    assert (project_root / "requirements-build.txt").read_text(encoding="utf-8") == (
        "PyInstaller>=6.21,<7\n"
    )


def test_packaging_guide_uses_pinned_build_requirements():
    """构建说明必须让人装到**钉过版本**的构建依赖，且不许残留旧版本号。

    开源化后原「打包说明.md」已移除（它停在 2.0.1 的 onefile 形态，
    且主体是反向工程防护策略），构建说明的落点改成 README 的「构建发布包」章节。
    判据要防的东西没变：有人照着文档 `pip install pyinstaller` 装到不兼容版本，
    而 onefile 闪屏定位需要 >= 6.21（build_release.py:150 有硬断言）。
    """
    project_root = Path(build_release.__file__).resolve().parent.parent
    guide = (project_root / "README.md").read_text(encoding="utf-8")
    reqs = (project_root / "requirements-build.txt").read_text(encoding="utf-8")

    assert "requirements-build.txt" in guide, "构建章节没让人用钉版本的 requirements-build.txt"
    assert "PyInstaller>=6.21" in reqs.replace(" ", ""), "requirements-build.txt 没钉住 PyInstaller 下限"
    assert "6.11.1" not in guide, "构建说明里残留了已被取代的 PyInstaller 版本号"


def _count_near_color(image, box, color, tolerance=24):
    crop = image.crop(box)
    return sum(
        all(abs(channel - expected) <= tolerance for channel, expected in zip(pixel, color))
        for y in range(crop.height)
        for x in range(crop.width)
        for pixel in (crop.getpixel((x, y)),)
    )


def test_splash_branding_constants_are_exact():
    assert make_installer_assets.SPLASH_TITLE == "帆派助手"
    assert make_installer_assets.SPLASH_STATUS == "正在启动…"
    assert make_installer_assets.SPLASH_SIZE == (600, 360)


def test_compose_splash_outputs_opaque_rgb_without_forbidden_magenta(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "splash.png"
    Image.new("RGBA", (900, 600), (255, 0, 255, 128)).save(source)

    make_installer_assets.compose_splash(source, output)

    with Image.open(output) as splash:
        splash.load()
        assert splash.mode == "RGB"
        assert splash.size == make_installer_assets.SPLASH_SIZE
        assert all(
            splash.getpixel((x, y)) != (255, 0, 255)
            for y in range(splash.height)
            for x in range(splash.width)
        )


def test_compose_splash_renders_title_and_status_inside_safe_boxes(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "splash.png"
    Image.new("RGB", (900, 600), (12, 12, 18)).save(source)

    make_installer_assets.compose_splash(source, output)

    with Image.open(output) as splash:
        splash.load()
        draw = ImageDraw.Draw(splash)
        title_font, status_font = make_installer_assets._splash_fonts()
        bold_font_names = {
            path.name.casefold()
            for path in make_installer_assets.CJK_BOLD_FONT_CANDIDATES
        }
        regular_font_names = {
            path.name.casefold()
            for path in make_installer_assets.CJK_REGULAR_FONT_CANDIDATES
        }
        title_bbox = draw.textbbox(
            make_installer_assets.SPLASH_TITLE_POSITION,
            make_installer_assets.SPLASH_TITLE,
            font=title_font,
            anchor="mm",
        )
        status_bbox = draw.textbbox(
            make_installer_assets.SPLASH_STATUS_POSITION,
            make_installer_assets.SPLASH_STATUS,
            font=status_font,
            anchor="mm",
        )
        title_pixels = _count_near_color(
            splash,
            make_installer_assets.TITLE_SAFE_BOX,
            make_installer_assets.TEXT,
        )
        status_pixels = _count_near_color(
            splash,
            make_installer_assets.STATUS_SAFE_BOX,
            make_installer_assets.SUBTEXT,
        )

    assert Path(title_font.path).name.casefold() in bold_font_names
    assert Path(status_font.path).name.casefold() in regular_font_names
    assert _box_contains(make_installer_assets.TITLE_SAFE_BOX, title_bbox)
    assert _box_contains(make_installer_assets.STATUS_SAFE_BOX, status_bbox)
    assert title_pixels >= 300
    assert status_pixels >= 100


def test_compose_splash_missing_source_preserves_existing_output(tmp_path):
    output = tmp_path / "splash.png"
    original = b"existing splash content"
    output.write_bytes(original)

    with pytest.raises(FileNotFoundError):
        make_installer_assets.compose_splash(tmp_path / "missing.png", output)

    assert output.read_bytes() == original
    assert list(tmp_path.glob(".*splash*.tmp.png")) == []


def _box_contains(outer, inner):
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def test_font_loader_rejects_missing_cjk_fonts_with_clear_error(monkeypatch):
    missing = (Path("missing-cjk-font.ttf"),)
    monkeypatch.setattr(make_installer_assets, "CJK_BOLD_FONT_CANDIDATES", missing)

    with pytest.raises(RuntimeError) as exc_info:
        make_installer_assets._font(34, bold=True)

    message = str(exc_info.value)
    assert "missing-cjk-font.ttf" in message
    assert "CJK" in message
    assert "install" in message.casefold()


def test_compose_splash_retries_transient_windows_replace_error(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "splash.png"
    Image.new("RGB", (900, 600), (12, 12, 18)).save(source)
    real_replace = make_installer_assets.os.replace
    calls = []
    delays = []

    def flaky_replace(source_path, output_path):
        calls.append((source_path, output_path))
        if len(calls) == 1:
            raise PermissionError("scanner briefly locked the output")
        real_replace(source_path, output_path)

    monkeypatch.setattr(make_installer_assets.os, "replace", flaky_replace)
    monkeypatch.setattr(make_installer_assets.time, "sleep", delays.append)

    make_installer_assets.compose_splash(source, output)

    assert len(calls) == 2
    assert delays and sum(delays) < 0.5
    with Image.open(output) as splash:
        splash.verify()
    assert list(tmp_path.glob("*.tmp.png")) == []


def test_compose_splash_exhausted_replace_retries_preserve_output(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "splash.png"
    Image.new("RGB", (900, 600), (12, 12, 18)).save(source)
    original = b"existing splash content"
    output.write_bytes(original)

    def locked_replace(_source_path, _output_path):
        raise PermissionError("output remains locked")

    monkeypatch.setattr(make_installer_assets.os, "replace", locked_replace)
    monkeypatch.setattr(make_installer_assets.time, "sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="output remains locked"):
        make_installer_assets.compose_splash(source, output)

    assert output.read_bytes() == original
    assert list(tmp_path.glob("*.tmp.png")) == []


def test_compose_splash_supports_eight_concurrent_writers(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "splash.png"
    Image.new("RGB", (900, 600), (12, 12, 18)).save(source)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(make_installer_assets.compose_splash, source, output)
            for _ in range(8)
        ]
        for future in futures:
            future.result()

    with Image.open(output) as splash:
        splash.verify()
    assert list(tmp_path.glob("*.tmp.png")) == []
