# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-508：体检报告说的是用户的话，而且**不带本机用户名**。

## 缺陷

外审四轮 24 发 ×3 收敛到同一族：`audio_health` 那块「体检报告」是**整块英文日志**
（`[Resource Health]` / `ok: False` / `missing_directories: 17` / `invalid_config_refs`），
后面跟着一串 `C:\\Users\\<用户名>\\AppData\\...` 的绝对路径（6/6 三轮稳定）。

⭐⭐⭐ **这不是「说错了」（RN-410 那族），是「没翻译」** —— 屏幕上摆的是给写代码的人
看的词。它长得像一个正常功能，所以既有的文案判据一条都没响：那些判据管的是
「说的话对不对」，而这里的问题是**这句话根本不是说给用户听的**。

⚠ 还有一面是**隐私**：这份报告有一颗「导出报告」按钮，导出的 `.txt` 是要发给别人的，
而它逐字带着本机 Windows 用户名。

## 这里守的三件事

1. **屏幕上那份报告里不许再出现内部记号**（英文小节名、蛇形键名）。
2. **不许出现本机用户目录**（用户名不许出现在报告里）。
3. **词表的分母是扫出来的**：代码里 `_make_issue(...)` 用到的每一个配置项基名、
   每一个 reason，都必须翻得出中文。谁新加一种，谁自动进分母 ——
   ⭐ 同 RN-483 / RN-511 那两次：按名单划分母，第一个不在名单上的违规者
   天生在守卫看不见的地方。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.health_report_text import (  # noqa: E402
    CONFIG_KEY_LABELS,
    REASON_LABELS,
    label_for_key,
    label_for_reason,
    relative_path,
    shorten_path,
)
from core.resource_health import format_resource_system_health  # noqa: E402

HEALTH_SOURCES = (
    REPO / "core" / "resource_health.py",
    REPO / "core" / "audio" / "audio_resource_health.py",
)

#: 内部记号：出现在**给用户看的报告**里就是缺陷。
INTERNAL_MARKS = (
    "[Resource Health]", "[Audio Health]", "[Visual Resource Health]",
    "checked_at:", "audio_root:", "resource_root:", "ok:",
    "missing_directories", "invalid_config_refs", "empty_style_dirs",
    "invalid_refs:", "incomplete_styles:", "gsi_cfg:",
)


def _sample_report() -> dict:
    """一份**每一支都踩到**的报告：只走 happy path 的样本证明不了渲染分支。"""
    la = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    aroot = os.path.join(la, "CS2Customizer", "resources", "audio")
    vroot = os.path.join(la, "CS2Customizer", "resources")
    return {
        "checked_at": "2026-09-05T00:49:11",
        "summary": {"ok": False, "missing_directories": 3,
                    "invalid_config_refs": 2, "empty_style_dirs": 1},
        "audio": {
            "audio_root": aroot,
            "summary": {"ok": False, "missing_directories": 2,
                        "invalid_config_refs": 2, "empty_style_dirs": 1},
            "missing_directories": [os.path.join(aroot, "kill_sounds"),
                                    os.path.join(aroot, "round_sounds", "start")],
            "invalid_config_refs": [
                {"key": "round_start_style", "value": "经典",
                 "expected_path": os.path.join(aroot, "round_sounds", "start", "经典"),
                 "reason": "style directory missing"},
                {"key": "weapon_switch_sounds.ak47", "value": "老式",
                 "expected_path": os.path.join(aroot, "switch_weapons", "老式"),
                 "reason": "style directory has no supported audio files"},
            ],
            "incomplete_styles": [
                {"kind": "kill_voice", "style": "解说", "missing_levels": [3, 4, 5],
                 "referenced_by": ["ak47", "m4a1"],
                 "style_dir": os.path.join(aroot, "kill_voices", "解说")},
            ],
            "gsi_cfg": {"status": "missing", "detail": "还没写入 CS2 的 GSI 配置文件"},
        },
        "visual": {
            "resource_root": vroot,
            "summary": {"ok": False, "missing_directories": 1,
                        "invalid_config_refs": 0, "empty_style_dirs": 0},
            "missing_directories": [os.path.join(vroot, "kill_icons")],
            "invalid_config_refs": [],
        },
    }


# ------------------------------------------------- 1. 不许再摆内部记号


def test_the_report_shown_to_users_has_no_internal_jargon():
    text = format_resource_system_health(_sample_report())
    assert text.strip(), "报告是空的 —— 这条判据的分母没了"
    hits = [m for m in INTERNAL_MARKS if m in text]
    assert not hits, (
        f"体检报告里还摆着内部记号：{hits}\n"
        "这块文本有两个出口（屏幕上的「体检报告」+ 导出的 .txt），两个都是给人看的。\n"
        f"当前报告：\n{text[:600]}")


def test_the_report_actually_says_something_in_chinese():
    """空转守卫：上面那条只要报告是空串就恒绿。"""
    text = format_resource_system_health(_sample_report())
    for must in ("资源体检报告", "音效资源", "画面资源", "少了", "设置指着找不到的东西"):
        assert must in text, f"报告里找不到「{must}」—— 渲染多半整段没跑到"


# ----------------------------------------------------------- 2. 隐私


def _identifying_names() -> set[str]:
    """本机能把这份报告认回到「谁」的那些名字。

    ⚠⚠ 这个函数的第一版只取 `USERNAME`，而**它未必等于用户目录名**：
    本机实测 `USERNAME=gufan`，而路径里是 `C:\\Users\\21108\\...` ——
    于是判据在一份**真的带着用户目录名**的报告上照样绿（破坏验证当场逮到）。
    ⭐⭐ **要盯的是「路径里那一段」，不是「账号叫什么」。**
    """
    names = set()
    for var in ("USERNAME", "USER"):
        value = (os.environ.get(var) or "").strip()
        if len(value) >= 3:
            names.add(value)
    for var in ("USERPROFILE", "HOME"):
        value = (os.environ.get(var) or "").strip()
        if value:
            leaf = os.path.basename(os.path.normpath(value))
            if len(leaf) >= 3:
                names.add(leaf)
    return names


def test_the_report_never_carries_the_local_user_name():
    """⚠ 「导出报告」导出的东西是要发给别人的。"""
    text = format_resource_system_health(_sample_report())
    lowered = text.lower()
    leaked = sorted(n for n in _identifying_names() if n.lower() in lowered)
    assert not leaked, (
        f"体检报告里带着能认出本机的名字 {leaked} —— "
        "而这份报告有一颗「导出报告」按钮，导出的东西是要发给别人的。")
    # ⚠ 这一段的第一版拿大写的针去扎小写的草堆（`"C:\\Users\\" not in text.lower()`），
    #   **那行断言恒真**。⭐ 大小写不一致的比较不会报错，只会永远通过。
    for mark in ("c:\\users\\", "c:/users/", "/home/", "\\appdata\\"):
        assert mark not in lowered, f"报告里还有本机绝对路径（{mark}）"


def test_shorten_path_replaces_the_user_directory():
    la = os.environ.get("LOCALAPPDATA")
    if not la:
        pytest.skip("这台机器没有 LOCALAPPDATA")
    got = shorten_path(os.path.join(la, "CS2Customizer", "resources"))
    assert got.startswith("%LOCALAPPDATA%"), got
    assert la.lower() not in got.lower()


def test_relative_path_keeps_paths_outside_the_root_visible():
    """⭐ 根目录外面的路径**不许静默丢掉** —— 那会把一条真问题变成看不见。"""
    la = os.environ.get("LOCALAPPDATA") or str(Path.home())
    outside = os.path.join(la, "Somewhere", "else.wav")
    got = relative_path(outside, os.path.join(la, "CS2Customizer"))
    assert got and "else.wav" in got, got


# -------------------------------------- 3. 词表的分母是从代码里扫出来的


def _issue_vocabulary() -> tuple[set[str], set[str]]:
    """扫 `_make_issue(key, value, path, reason)` 的第 1、4 个实参。

    key 取**点号前那一段**（`grenade_sound_styles.flashbang` → `grenade_sound_styles`）；
    f-string 里那两个是变量（`{event.config_attr}` / `{key}`），单独处理。
    """
    keys, reasons = set(), set()
    for path in HEALTH_SOURCES:
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "_make_issue"
                    and len(node.args) == 4):
                continue
            key_node, _v, _p, reason_node = node.args
            if isinstance(key_node, ast.Constant):
                keys.add(str(key_node.value).split(".")[0])
            elif isinstance(key_node, ast.JoinedStr):
                # f"{key}.{weapon}" / f"grenade_sound_styles.{grenade_type}"
                head = key_node.values[0]
                if isinstance(head, ast.Constant):
                    keys.add(str(head.value).split(".")[0])
            if isinstance(reason_node, ast.Constant):
                reasons.add(str(reason_node.value))
    return keys, reasons


def test_every_reason_the_code_can_emit_has_chinese():
    _keys, reasons = _issue_vocabulary()
    assert reasons, "一个 reason 都没扫到 —— 识别器瞎了，而不是真的没有"
    missing = sorted(r for r in reasons if r not in REASON_LABELS)
    assert not missing, (
        f"这些原因会打到用户脸上，却没有中文：{missing}\n"
        f"⇒ 补进 `core/health_report_text.REASON_LABELS`。")


def test_every_static_config_key_the_code_can_emit_has_chinese():
    keys, _reasons = _issue_vocabulary()
    assert keys, "一个配置项基名都没扫到 —— 识别器瞎了"
    known = set(CONFIG_KEY_LABELS)
    try:
        from core.audio.special_events import SOUND_EVENTS
        known |= {e.config_attr for e in SOUND_EVENTS}
    except Exception:  # pragma: no cover - 派生子集里可能没有这个模块
        pass
    missing = sorted(k for k in keys if k not in known)
    assert not missing, (
        f"这些配置项名会原样打给用户看，却没有中文：{missing}\n"
        "⇒ 补进 `CONFIG_KEY_LABELS`（事件类的走 `SOUND_EVENTS` 那个真源，别在这儿抄）。")


def test_the_event_labels_come_from_the_single_source():
    """⭐ 事件类的中文名**不许在词表里抄第二份** —— 抄了就会各自漂移。"""
    from core.audio.special_events import SOUND_EVENTS
    duplicated = sorted({e.config_attr for e in SOUND_EVENTS} & set(CONFIG_KEY_LABELS))
    assert not duplicated, (
        f"这些事件的名字在 `CONFIG_KEY_LABELS` 里被抄了第二份：{duplicated}\n"
        "⇒ 删掉，`label_for_key()` 已经从 `SOUND_EVENTS` 读了。")
    sample = SOUND_EVENTS[0]
    assert label_for_key(sample.config_attr) == sample.label


def test_an_unknown_key_is_handed_over_as_is_not_faked():
    """认不出来的键**原样交出去**，不许假装认识（那会造出一个错的中文名）。"""
    assert label_for_key("some_key_nobody_registered") == "some_key_nobody_registered"
    assert label_for_reason("brand new reason") == "brand new reason"
