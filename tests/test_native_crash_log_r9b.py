# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R9-B（UP-088）：`native_crash.log` 的压缩不许弄丢证据。

**这个改动的风险方向是反的**——它的目的是让真崩溃更容易被看见，
但它做的事是**删文件里的内容**。所以判据的重心不在"噪声删干净了没有"，
而在"**证据一条都没少**"。下面每一条都是冲着"压缩把不该删的删了"去的。

背景（实测数据，见 UP-088）：用户机上 103 条会话横幅里只有 13 条真带故障，
其中 6 条是良性的 `0x8001010d`（每进程第一次显示窗口必出，与闪屏无关，
`scripts/probe_r9b_splash.py` 换六种窗口标志都照出），真正值得看的
7 条 access violation 就埋在这堆东西里。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

MARK = "===== 会话启动"

EMPTY_SESSION = f"""
{MARK} 2026-08-09 10:00:00 pid=111 =====
"""

BENIGN_SESSION = f"""
{MARK} 2026-08-09 10:01:00 pid=222 =====
Windows fatal exception: code 0x8001010d

Current thread 0x00001111 (most recent call first):
  File "main_widget.py", line 157 in _show_qt_splash
  File "main_widget.py", line 1058 in main
"""

REAL_CRASH = f"""
{MARK} 2026-08-09 10:02:00 pid=333 =====
Windows fatal exception: access violation

Current thread 0x00002222 (most recent call first):
  File "audio_manager.py", line 42 in play_sound
  File "gsi_handler_kills.py", line 88 in on_kill
"""

ANOTHER_REAL = f"""
{MARK} 2026-08-09 10:03:00 pid=444 =====
Fatal Python error: Segmentation fault

Current thread 0x00003333 (most recent call first):
  File "flash_process.py", line 923 in shutdown
"""


@pytest.fixture
def compact():
    """只把待测函数抠出来，不 import 整个 main_widget（那会拉起一大票重模块）。"""
    spec = importlib.util.spec_from_file_location("_mw_r9b", REPO / "main_widget.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_mw_r9b"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"main_widget 无法在测试环境导入: {exc}")
    finally:
        sys.modules.pop("_mw_r9b", None)
    return module._compact_native_crash_log


def _write(tmp_path: Path, *chunks: str) -> Path:
    p = tmp_path / "native_crash.log"
    p.write_text("".join(chunks), encoding="utf-8")
    return p


# ==================================================== 证据一条都不能少


def test_real_crash_blocks_survive_compaction(compact, tmp_path):
    """核心判据：真故障块必须原样保留。

    回退验证：把 `_compact_native_crash_log` 里那句 `kept.append(block)` 删掉，
    本条立刻变红。
    """
    p = _write(tmp_path, EMPTY_SESSION, REAL_CRASH, BENIGN_SESSION, ANOTHER_REAL)
    compact(p)
    out = p.read_text(encoding="utf-8")

    assert "access violation" in out
    assert "play_sound" in out and "on_kill" in out
    assert "Segmentation fault" in out
    assert "flash_process.py" in out


def test_a_session_with_both_benign_and_real_faults_is_kept_whole(compact, tmp_path):
    """同一个会话里既有良性异常又有真崩溃时，**整块保留**。

    折叠规则只认"这一块里唯一的故障就是良性那条"，多一条就不折叠——
    否则一次真崩溃会因为前面那条无害的 0x8001010d 被顺手抹掉。
    """
    mixed = BENIGN_SESSION + "\nWindows fatal exception: access violation\n" \
                             "  File \"audio_manager.py\", line 7 in decode\n"
    p = _write(tmp_path, mixed)
    compact(p)
    out = p.read_text(encoding="utf-8")

    assert "access violation" in out
    assert "decode" in out


def test_unknown_exception_codes_are_never_collapsed(compact, tmp_path):
    """只折叠**白名单里**那一个异常码。没见过的码一律当真崩溃留着。"""
    unknown = EMPTY_SESSION.replace("pid=111", "pid=555") + \
        "Windows fatal exception: code 0xdeadbeef\n  File \"x.py\", line 1 in f\n"
    p = _write(tmp_path, unknown)
    compact(p)
    out = p.read_text(encoding="utf-8")
    assert "0xdeadbeef" in out


# ==================================================== 噪声确实被压掉了


def test_empty_sessions_are_dropped_but_counted(compact, tmp_path):
    """空横幅要清掉——但要**报出清了几个**，静默截断会被读成"历史就这么多"。"""
    p = _write(tmp_path, EMPTY_SESSION, EMPTY_SESSION, EMPTY_SESSION, REAL_CRASH)
    compact(p)
    out = p.read_text(encoding="utf-8")

    assert out.count(MARK) == 1, "三条空横幅应当只剩真故障那一条"
    assert "丢弃空会话块 3 个" in out


def test_benign_first_chance_is_collapsed_with_time_range(compact, tmp_path):
    """良性异常折叠成一行计数，并保留首末时间——保留证据，去掉体积。"""
    later = BENIGN_SESSION.replace("10:01:00", "11:30:00")
    p = _write(tmp_path, BENIGN_SESSION, later, REAL_CRASH)
    compact(p)
    out = p.read_text(encoding="utf-8")

    # 折叠 = 那两块的**栈**没了，只剩头部一行计数
    assert "_show_qt_splash" not in out, "良性块的栈应当被折叠掉"
    assert out.count(MARK) == 1, "只该剩下真崩溃那一块"
    assert "折叠良性首次机会异常 2 次" in out
    assert "10:01:00" in out and "11:30:00" in out


def test_repeated_compaction_accumulates_instead_of_stacking_headers(compact, tmp_path):
    """连压三轮，头部只许有**一段**说明，且计数是累计的。

    第一版就栽在这：每轮压缩都在文件顶上新加一段"已压缩"说明，旧的原样留着，
    于是启动 N 次就有 N 段说明——正是这个函数要消灭的那种噪声。
    实测跑两轮真机就看出来了。
    """
    p = _write(tmp_path, EMPTY_SESSION, BENIGN_SESSION, REAL_CRASH)
    compact(p)
    # 第二轮：再追加一批噪声（模拟又启动了一次）
    with p.open("a", encoding="utf-8") as fp:
        fp.write(EMPTY_SESSION + EMPTY_SESSION + BENIGN_SESSION.replace("10:01:00", "12:00:00"))
    compact(p)
    # 第三轮
    with p.open("a", encoding="utf-8") as fp:
        fp.write(EMPTY_SESSION)
    compact(p)

    out = p.read_text(encoding="utf-8")
    assert out.count("===== 已压缩") == 1, f"压缩说明堆积了：\n{out[:400]}"
    assert "\n\n\n" not in out, "空行在逐轮增殖"
    assert "丢弃空会话块 4 个" in out, f"空块计数没累计：\n{out[:400]}"
    assert "折叠良性首次机会异常 2 次" in out
    # 证据仍在
    assert "access violation" in out and "play_sound" in out


def test_session_stamp_keeps_the_pid_readable(compact, tmp_path):
    """折叠说明里的时间戳要带上可读的 `pid=NNN`，别把等号剥掉。"""
    p = _write(tmp_path, BENIGN_SESSION, REAL_CRASH)
    compact(p)
    out = p.read_text(encoding="utf-8")
    assert "pid=222" in out


def test_nothing_to_compact_leaves_the_file_untouched(compact, tmp_path):
    """没有噪声可压时**一个字节都不许动**——每次启动都重写一遍纯属自找风险。"""
    p = _write(tmp_path, REAL_CRASH, ANOTHER_REAL)
    before = p.read_bytes()
    compact(p)
    assert p.read_bytes() == before


def test_missing_or_empty_file_is_a_no_op(compact, tmp_path):
    """文件不存在 / 是空的，都不许抛异常，也不许凭空造出文件。"""
    missing = tmp_path / "nope.log"
    compact(missing)
    assert not missing.exists()

    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    compact(empty)
    assert empty.read_text(encoding="utf-8") == ""


def test_garbage_input_does_not_raise(compact, tmp_path):
    """诊断设施坏了也不能让软件起不来：喂进去乱七八糟的东西也只能安静返回。"""
    p = tmp_path / "native_crash.log"
    p.write_bytes(b"\x00\x01\x02 not utf-8 \xff\xfe garbage without any session mark")
    compact(p)  # 不抛就算过


def test_leading_content_without_a_session_mark_is_preserved(compact, tmp_path):
    """老版本在第一条横幅之前写过东西，那段不能因为"不属于任何块"被丢掉。"""
    p = _write(tmp_path, "老格式的遗留内容\n重要栈帧\n", EMPTY_SESSION, REAL_CRASH)
    compact(p)
    out = p.read_text(encoding="utf-8")
    assert "老格式的遗留内容" in out
    assert "重要栈帧" in out


# ==================================================== 上限要说出来


def test_block_cap_reports_what_it_dropped(compact, tmp_path):
    """超出保留上限时丢最旧的，并在头部写明丢了多少个。"""
    spec = importlib.util.spec_from_file_location("_mw_cap", REPO / "main_widget.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cap = module._CRASH_LOG_KEEP_BLOCKS

    many = "".join(
        REAL_CRASH.replace("10:02:00", f"10:02:{i:02d}") for i in range(cap + 5)
    )
    p = _write(tmp_path, many)
    compact(p)
    out = p.read_text(encoding="utf-8")

    assert "因超出保留上限丢弃最旧的有内容块 5 个" in out
    assert out.count(MARK) == cap


def test_subprocesses_do_not_compact(compact, tmp_path):
    """压缩必须只在主进程发生一次。

    子进程是 multiprocessing spawn 重新 import main_widget 起来的，会把
    `_enable_faulthandler` 再跑一遍。如果它们也压，就会在主进程已经握着
    append 句柄之后重写文件。判据盯的是"那道环境变量闸门还在"。
    """
    src = (REPO / "main_widget.py").read_text(encoding="utf-8")
    assert "_CS2C_CRASHLOG_COMPACTED" in src
    # 闸门必须**包住**压缩调用，而不是只出现在文件某处
    idx_guard = src.index("_CS2C_CRASHLOG_COMPACTED")
    idx_call = src.index("_compact_native_crash_log(crash_path)")
    assert idx_guard < idx_call, "环境变量闸门必须在压缩调用之前"
