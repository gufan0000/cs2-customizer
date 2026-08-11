"""Verify the packaged Windows splash-to-main-window transition."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PIL import ImageGrab

RectTuple = tuple[int, int, int, int]
EXPECTED_SPLASH_SIZE = (600, 360)


def _rect_tuple(rect: Sequence[int]) -> RectTuple:
    return tuple(int(value) for value in rect)  # type: ignore[return-value]


def _handle_value(handle: object) -> int | None:
    if isinstance(handle, Mapping):
        handle = handle.get("handle")
    if handle is None:
        return None
    value = getattr(handle, "value", handle)
    return int(value) if value is not None else None


def _max_drift(samples: Sequence[Sequence[int]]) -> int:
    if not samples:
        return 0
    return max(max(values) - min(values) for values in zip(*samples))


def rect_is_stable(samples: Sequence[Sequence[int]], tolerance: int = 1) -> bool:
    """Return whether every rectangle edge stays within ``tolerance`` pixels."""
    return bool(samples) and _max_drift(samples) <= tolerance


def center_offset(rect: Sequence[int], monitor_rect: Sequence[int]) -> tuple[int, int]:
    """Return signed window-center offset from the monitor center."""
    left, top, right, bottom = _rect_tuple(rect)
    mon_left, mon_top, mon_right, mon_bottom = _rect_tuple(monitor_rect)
    return (
        (left + right - mon_left - mon_right) // 2,
        (top + bottom - mon_top - mon_bottom) // 2,
    )


def same_monitor(expected: object, actual: object) -> bool:
    expected_handle = _handle_value(expected)
    return expected_handle is not None and expected_handle == _handle_value(actual)


def summarize_run(
    samples: Sequence[Sequence[int]],
    target_monitor: Mapping[str, object],
    actual_monitor: Mapping[str, object] | None,
    main_window_visible: bool,
) -> dict[str, object]:
    actual_monitor = actual_monitor or {}
    offset = center_offset(samples[-1], target_monitor["rcMonitor"]) if samples else (0, 0)
    max_drift = _max_drift(samples)
    monitor_matches = same_monitor(target_monitor, actual_monitor)
    center_distance = max(abs(offset[0]), abs(offset[1]))
    splash_sizes = sorted(
        {(rect[2] - rect[0], rect[3] - rect[1]) for rect in samples}
    )
    expected_dimensions = splash_sizes == [EXPECTED_SPLASH_SIZE]
    passed = bool(
        samples
        and monitor_matches
        and max_drift <= 1
        and center_distance <= 8
        and expected_dimensions
        and main_window_visible
    )
    return {
        "same_monitor": monitor_matches,
        "max_drift_px": max_drift,
        "center_offset_xy": offset,
        "center_offset_px": center_distance,
        "expected_splash_size": EXPECTED_SPLASH_SIZE,
        "splash_sizes": splash_sizes,
        "expected_dimensions": expected_dimensions,
        "main_window_visible": bool(main_window_visible),
        "passed": passed,
    }


def descendant_pids(root_pid: int, parent_by_pid: Mapping[int, int]) -> set[int]:
    descendants: set[int] = set()
    frontier = {root_pid}
    while frontier:
        children = {
            pid
            for pid, parent in parent_by_pid.items()
            if parent in frontier and pid not in descendants and pid != root_pid
        }
        descendants.update(children)
        frontier = children
    return descendants


def select_reasonable_window(
    windows: Iterable[Mapping[str, object]], pids: set[int]
) -> Mapping[str, object] | None:
    for window in windows:
        left, top, right, bottom = _rect_tuple(window["rect"])  # type: ignore[arg-type]
        if (
            int(window["pid"]) in pids
            and bool(window["visible"])
            and right - left >= 100
            and bottom - top >= 50
        ):
            return window
    return None


if sys.platform == "win32":
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    MONITOR_DEFAULTTONEAREST = 2

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(RECT), wintypes.DWORD]
    user32.MonitorFromRect.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


def _win_error(call: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), f"{call} failed")


def _as_rect(rect: RECT) -> RectTuple:
    return (rect.left, rect.top, rect.right, rect.bottom)


def _monitor_info(handle: object) -> dict[str, object]:
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        raise _win_error("GetMonitorInfoW")
    return {
        "handle": _handle_value(handle),
        "rcMonitor": _as_rect(info.rcMonitor),
        "rcWork": _as_rect(info.rcWork),
    }


def _target_monitor() -> dict[str, object]:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise _win_error("GetCursorPos")
    handle = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    info = _monitor_info(handle)
    info["cursor"] = (point.x, point.y)
    return info


def _monitor_for_rect(rect_tuple: Sequence[int]) -> dict[str, object]:
    rect = RECT(*_rect_tuple(rect_tuple))
    handle = user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONEAREST)
    return _monitor_info(handle)


def _process_parents() -> dict[int, int]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if _handle_value(snapshot) == INVALID_HANDLE_VALUE:
        raise _win_error("CreateToolhelp32Snapshot")
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _windows() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        rect = RECT()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            results.append(
                {
                    "hwnd": int(hwnd),
                    "pid": int(pid.value),
                    "visible": bool(user32.IsWindowVisible(hwnd)),
                    "rect": _as_rect(rect),
                }
            )
        return True

    callback = callback_type(collect)
    if not user32.EnumWindows(callback, 0):
        raise _win_error("EnumWindows")
    return results


def _window_state(hwnd: int) -> dict[str, object] | None:
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    rect = RECT()
    pid = wintypes.DWORD()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"hwnd": hwnd, "pid": int(pid.value), "visible": True, "rect": _as_rect(rect)}


def _capture(path: Path, rect: Sequence[int], hwnd: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hwnd is not None:
        image = ImageGrab.grab(window=hwnd)
    else:
        image = ImageGrab.grab(bbox=_rect_tuple(rect), all_screens=True)
    image.save(path)


def _terminate_started_tree(process: subprocess.Popen[bytes], recorded_pids: set[int]) -> None:
    protected = {0, os.getpid()}
    if process.pid not in protected and process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    live_pids = set(_process_parents())
    for pid in sorted(recorded_pids & live_pids - protected - {process.pid}, reverse=True):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )


def _run_once(exe: Path, run_dir: Path, run_number: int) -> dict[str, object]:
    target = _target_monitor()
    monitor_rect = target["rcMonitor"]
    started = time.monotonic()
    process = subprocess.Popen([str(exe)], cwd=exe.parent)
    recorded_pids: set[int] = set()
    samples: list[dict[str, object]] = []
    splash_hwnd: int | None = None
    splash_closed_at: float | None = None
    main_first_at: float | None = None
    main_stable_at: float | None = None
    actual_monitor: dict[str, object] | None = None
    main_window: Mapping[str, object] | None = None
    main_samples: list[RectTuple] = []
    main_stable_since: float | None = None
    screenshot_paths = {
        name: run_dir / f"run_{run_number:02d}_{name}.png"
        for name in ("splash_first", "splash_last", "transition", "main_first", "main_stable")
    }
    try:
        deadline = started + 45.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            parents = _process_parents()
            recorded_pids.update(descendant_pids(process.pid, parents))
            windows = _windows()

            if splash_hwnd is None and not samples:
                splash = select_reasonable_window(windows, {process.pid})
                if splash:
                    splash_hwnd = int(splash["hwnd"])
                    rect = _rect_tuple(splash["rect"])  # type: ignore[arg-type]
                    samples.append({"t": now - started, "rect": rect})
                    actual_monitor = _monitor_for_rect(rect)
                    _capture(screenshot_paths["splash_first"], rect, splash_hwnd)
                    _capture(screenshot_paths["splash_last"], rect, splash_hwnd)
            elif splash_hwnd is not None and splash_closed_at is None:
                splash = _window_state(splash_hwnd)
                if splash:
                    rect = _rect_tuple(splash["rect"])  # type: ignore[arg-type]
                    samples.append({"t": now - started, "rect": rect})
                    actual_monitor = _monitor_for_rect(rect)
                    _capture(screenshot_paths["splash_last"], rect, splash_hwnd)
                else:
                    splash_closed_at = now - started
                    _capture(screenshot_paths["transition"], monitor_rect)  # type: ignore[arg-type]

            if splash_closed_at is not None and main_stable_at is None:
                candidate = select_reasonable_window(
                    (window for window in windows if window["hwnd"] != splash_hwnd),
                    recorded_pids | {process.pid},
                )
                if candidate:
                    candidate_rect = _rect_tuple(candidate["rect"])  # type: ignore[arg-type]
                    if main_window is None or candidate["hwnd"] != main_window["hwnd"]:
                        main_window = candidate
                        main_samples = [candidate_rect]
                        main_stable_since = now
                        main_first_at = now - started
                        _capture(
                            screenshot_paths["main_first"],
                            candidate_rect,
                            int(candidate["hwnd"]),
                        )
                    else:
                        main_samples.append(candidate_rect)
                        if not rect_is_stable(main_samples, tolerance=1):
                            main_samples = [candidate_rect]
                            main_stable_since = now
                        elif main_stable_since is not None and now - main_stable_since >= 0.5:
                            main_stable_at = now - started
                            _capture(
                                screenshot_paths["main_stable"],
                                candidate_rect,
                                int(candidate["hwnd"]),
                            )
                            break
            time.sleep(0.05)
    finally:
        _terminate_started_tree(process, recorded_pids)

    rect_samples = [sample["rect"] for sample in samples]
    result = summarize_run(
        rect_samples,  # type: ignore[arg-type]
        target,
        actual_monitor,
        main_window_visible=main_stable_at is not None,
    )
    result.update(
        {
            "run": run_number,
            "target_monitor": target,
            "actual_monitor": actual_monitor,
            "samples": samples,
            "first_rect": rect_samples[0] if rect_samples else None,
            "last_rect": rect_samples[-1] if rect_samples else None,
            "splash_close_timestamp": splash_closed_at,
            "main_first_timestamp": main_first_at,
            "main_stable_timestamp": main_stable_at,
            "recorded_descendant_pids": sorted(recorded_pids),
            "screenshots": {name: str(path) for name, path in screenshot_paths.items()},
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"run_{run_number:02d}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path, help="Packaged executable path")
    parser.add_argument("--runs", type=int, default=3, help="Number of launches")
    parser.add_argument("--output", required=True, type=Path, help="Evidence output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if sys.platform != "win32":
        print("verify_splash_stability.py requires Windows", file=sys.stderr)
        return 2
    exe = args.exe.resolve()
    if not exe.is_file():
        print(f"Executable does not exist: {exe}", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2
    output = args.output.resolve()
    results = [_run_once(exe, output, run_number) for run_number in range(1, args.runs + 1)]
    summary = {
        "exe": str(exe),
        "runs": results,
        "passed": all(bool(result["passed"]) for result in results),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
