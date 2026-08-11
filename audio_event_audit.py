"""Audit runtime audio events from latest CS2Customizer log file.

Usage:
    python audio_event_audit.py
    python audio_event_audit.py --minutes 30 --show-lines 8
    python audio_event_audit.py --require kill_events --require voice_events
"""

from __future__ import annotations

import argparse
import os
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List


CATEGORY_KEYWORDS: "OrderedDict[str, tuple[str, ...]]" = OrderedDict(
    [
        ("kill_events", ("kill-", "[击杀诊断]", "[鍑绘潃璇婃柇]")),
        ("voice_events", ("voice-",)),
        (
            "gun_events",
            (
                "awp-",
                "deagle-",
                "usp-",
                "revolver-",
                "ssg08-",
                "scar20-",
                "g3sg1-",
                "nova-",
                "mag7-",
                "sawedoff-",
                "awp fired",
                "deagle fired",
                "usp fired",
                "revolver fired",
                "ssg08 fired",
                "scar-20 fired",
                "g3sg1 fired",
                "nova fired",
                "mag-7 fired",
                "sawed-off fired",
            ),
        ),
        ("switch_events", ("switch-",)),
        ("reload_events", ("reload-",)),
        ("death_events", ("death-",)),
        ("grenade_events", ("grenade-",)),
        ("c4_events", ("c4-planted-",)),
        ("health_events", ("health-warning-",)),
        ("round_events", ("round-start-", "round-action-", "round-win-", "round-lose-", "round-mvp-")),
        ("audio_health", ("[AudioHealth]",)),
        (
            "warnings",
            (
                "[WARNING]",
                "warning:",
                "VB-Cable",
            ),
        ),
        (
            "errors",
            (
                "[ERROR]",
                "Traceback",
                "Exception:",
                "RuntimeError",
                "Audio not loaded",
                "Load failed",
                "Play failed",
                "播放失败",
                "加载失败",
                "初始化失败",
            ),
        ),
    ]
)


def _resolve_log_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CS2Customizer" / "logs"
    return Path("logs")


def _find_latest_log(log_dir: Path) -> Path | None:
    if not log_dir.is_dir():
        return None
    files = sorted(log_dir.glob("cs2customizer_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_timestamp(line: str) -> datetime | None:
    if len(line) < 21 or not line.startswith("["):
        return None
    try:
        return datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _contains_any(line: str, keywords: Iterable[str]) -> bool:
    lower = line.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def _read_tail_lines(path: Path, max_lines: int) -> List[str]:
    with path.open("r", encoding="utf-8", errors="replace") as file_obj:
        lines = file_obj.read().splitlines()
    if max_lines > 0 and len(lines) > max_lines:
        return lines[-max_lines:]
    return lines


def _collect_matches(lines: List[str], since: datetime | None) -> Dict[str, List[str]]:
    matches: Dict[str, List[str]] = {name: [] for name in CATEGORY_KEYWORDS}
    for line in lines:
        ts = _parse_timestamp(line)
        if since and ts and ts < since:
            continue
        for category, keywords in CATEGORY_KEYWORDS.items():
            if _contains_any(line, keywords):
                matches[category].append(line)
    return matches


def _detect_file_log_level(lines: List[str]) -> str | None:
    """从日志行里读出这份文件是以什么级别写的（UP-004 起 logger 每次启动都会打这行）。

    取**最后一个**标记：一个日志文件里可能有多次会话，我们关心最近那次的级别。
    返回 "DEBUG" / "INFO" / None（老版本日志没有这个标记）。
    """
    for line in reversed(lines):
        if "[日志] 文件日志级别" in line:
            if "DEBUG" in line.split("文件日志级别", 1)[1]:
                return "DEBUG"
            return "INFO"
    return None


def _detect_level_from_file(path: Path) -> str | None:
    """整文件扫级别标记，不受 --max-lines 尾部窗口限制。

    标记只在会话开头写一行，而实测单日日志已达 28867 行、默认只扫尾部 20000 行，
    标记必然落在窗口外——不整文件扫的话这个检测形同虚设。
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fp:
            return _detect_file_log_level(fp.read().splitlines())
    except Exception:
        return None


def _print_level_warning(level: str | None):
    """INFO 级日志上做音频审计会大量漏事件——必须显式告知，不能静默给出误导性的 0。

    实测（2026-03 的真实日志）：kill- 事件 89% 只在 DEBUG，grenade- 事件 100% 只在 DEBUG。
    """
    if level == "DEBUG":
        return
    print("")
    if level == "INFO":
        print("!! 警告：这份日志是 INFO 级写入的，音频事件大量缺失（kill-/grenade- 等主要是 DEBUG 级）。")
    else:
        print("!! 提示：未能确定这份日志的写入级别（可能是 2.2.1 及更早版本）。")
    print("   下面的计数会明显偏低，不能据此判断'音效没触发'。")
    print("   开启方式（任选其一）：")
    print("     1) 【推荐】设环境变量 CS2C_DEBUG_LOG=1 后启动软件，复现一次即可")
    print("     2) 先【完全退出软件】（否则退出时会把内存里的旧值写回去覆盖掉），")
    print("        再改 %LOCALAPPDATA%\\CS2Customizer\\config.json 设 \"debug_file_log\": true，然后启动")


def _print_report(log_file: Path, lines: List[str], since: datetime | None, matches: Dict[str, List[str]], show_lines: int):
    print("[Audio Event Audit]")
    print(f"log_file: {log_file}")
    print(f"lines_scanned: {len(lines)}")
    # 级别标记只在会话开头写一行,必须整文件扫,不能受 --max-lines 尾窗口限制
    _print_level_warning(_detect_level_from_file(log_file))
    print(f"time_filter: since {since.strftime('%Y-%m-%d %H:%M:%S') if since else 'none'}")
    print("")
    print("counts:")
    for category in CATEGORY_KEYWORDS:
        print(f"- {category}: {len(matches[category])}")

    if show_lines <= 0:
        return

    for category in CATEGORY_KEYWORDS:
        print("")
        print(f"[{category}] last {show_lines} line(s)")
        sample = matches[category][-show_lines:]
        if not sample:
            print("(no match)")
            continue
        for line in sample:
            print(line)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit runtime audio events from CS2Customizer logs.")
    parser.add_argument("--log-file", default="", help="Optional explicit log file path.")
    parser.add_argument("--minutes", type=int, default=20, help="Only include logs from last N minutes. Use 0 to disable.")
    parser.add_argument("--max-lines", type=int, default=20000, help="Max tail lines to scan from the log file.")
    parser.add_argument("--show-lines", type=int, default=6, help="How many matched lines to show per category.")
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        choices=list(CATEGORY_KEYWORDS.keys()),
        help="Require category to have at least one match. Can be repeated.",
    )
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="Exit with non-zero if any errors category match exists.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.log_file:
        log_file = Path(args.log_file)
    else:
        log_dir = _resolve_log_dir()
        log_file = _find_latest_log(log_dir)
        if not log_file:
            print(f"[Audio Event Audit] no log file found under: {log_dir}")
            return 2

    if not log_file.is_file():
        print(f"[Audio Event Audit] log file not found: {log_file}")
        return 2

    lines = _read_tail_lines(log_file, max_lines=max(0, int(args.max_lines)))
    since = None
    if args.minutes and args.minutes > 0:
        since = datetime.now() - timedelta(minutes=int(args.minutes))

    matches = _collect_matches(lines, since=since)
    _print_report(log_file, lines, since, matches, show_lines=max(0, int(args.show_lines)))

    missing = [category for category in args.require if not matches.get(category)]
    if missing:
        print("")
        print(f"[Audio Event Audit] missing required categories: {', '.join(missing)}")
        return 3

    if args.fail_on_errors and matches.get("errors"):
        print("")
        print("[Audio Event Audit] errors detected in selected log window.")
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
