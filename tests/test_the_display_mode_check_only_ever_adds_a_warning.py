# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-434：读 CS2 显示模式这件事，**只许加强警告，永不许撤销它**。

RN-429 那一批只做了「说」不做「查」，理由是三个未解问题（选哪份 cs2_video.txt /
映射没文档 / 读不到说什么）。批 72 没有把三个问题答完 —— 答完不了：
我看不见 CS2 的设置界面，手上两次读数还是两个不同的状态
（2026-09-03 记的 `1+0`，批 72 读到 `0+1`），中间没有任何一次带标注的地面真值。

⭐⭐⭐ 落地靠的是**换一个不需要答完就能成立的形状**：代价的方向是不对称的。

| 真实状态 | 读成 | 后果 |
|---|---|---|
| 独占全屏 | 无边框（误判） | 那句本来正确的警告**被撤掉了** ⇒ 玩家配完进游戏一片空白 |
| 无边框 | 独占全屏（误判） | 多一句「去改成无边框」—— 那正是他本来就该在的档 |

⇒ 只有 `exclusive` 这一档允许改措辞；**其余一切**（无边框 / 窗口化 / 读不到 /
几个账号读数不一致 / 环境变量是垃圾值）都必须原样输出通用那句话。
本文件的判据就是逐格钉这张表。

⚠ 还钉一条**决定论**：这份读数来自机器状态，与 `account`（RN-472）、
`audio_health`（RN-146）同族 —— 同一份代码在两台机器上会出不同的字。
工装侧钉在 `_audit_neutralize.enable_audit_mode()`，测试侧钉在 `conftest.py`。
⭐ 而「钉一档」这个动作本身刚在 RN-571 上摔过：**钉 = 把它推到那个状态，
不是「碰巧它就是那样」** ⇒ 环境变量是唯一入口，设了就一个文件都不读。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_display_mode_check_only_ever_adds_a_warning.py`）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

#: 通用那句话的**逐字**样子。改它要连同 RN-429 的裁定一起改，不许顺手改。
GENERIC_HEAD = "⚠ 先去 CS2 把显示模式选成「无边框窗口化」"


@pytest.fixture
def pinned(monkeypatch):
    from core import cs2_video_mode as vm

    def _pin(value):
        if value is None:
            monkeypatch.delenv(vm.MODE_ENV, raising=False)
        else:
            monkeypatch.setenv(vm.MODE_ENV, value)
        return vm

    return _pin


@pytest.mark.parametrize("pin, expect", [
    ("exclusive", True),
    ("borderless", False),
    ("windowed", False),
    ("unknown", False),
    ("EXCLUSIVE", True),            # 大小写不该改变结论
    ("垃圾值", False),               # ⭐ 认不出的值必须落到「不知道」那一侧
])
def test_only_exclusive_fullscreen_earns_the_specific_wording(pinned, pin, expect):
    vm = pinned(pin)
    assert vm.overlay_is_invisible_now() is expect, (
        f"钉 {pin!r} 时 `overlay_is_invisible_now()` 应为 {expect}。\n"
        f"⭐ 只有**确证**独占全屏才允许改措辞；一切别的情况（含读不到、"
        f"读数不一致、认不出的值）都要落到通用那一档。\n"
        f"⛔ 把不确定读成「无边框」，代价是把那句本来正确的警告撤掉。")


def test_an_empty_pin_means_not_pinned_and_it_goes_to_disk(monkeypatch):
    """空串 = **没钉** —— 它必须真的落到扫盘那条路上去。

    ⚠⚠ 批 73 补正：这一格原来混在上面那张参数表里写作 `("", False)`。
    可上面每一格的前提都是「钉住 ⇒ 一个文件都不读」，而**空串恰恰是不钉**：
    它会真的去读这台机器的 `userdata/*/730/local/cfg/cs2_video.txt`，
    于是那一格的结论由**跑测试的机器**决定 ——
    本机今天读到 `0+1`（无边框）所以碰巧绿，而同一台机器 2026-09-03 记的是 `1+0`
    （独占全屏），那一天它会红，且红得跟被测改动毫无关系。
    ⭐⭐⭐ **一个绿在「这台机器碰巧是这样」上的用例，和一个真的钉住了的用例，
      在测试报告上长得一模一样。**
    ⇒ 拆出来单独写，并**把盘也钉住**：这样它验的是「空串会不会去查盘」这件事本身。
    """
    import cfg_utils

    from core import cs2_video_mode as vm

    monkeypatch.setenv(vm.MODE_ENV, "")
    monkeypatch.setattr(cfg_utils, "get_steam_path_windows", lambda: "C:/steam")
    monkeypatch.setattr(vm, "_readings", lambda root: [vm.MODE_EXCLUSIVE])
    assert vm.overlay_is_invisible_now() is True, (
        "空串没有落到扫盘那条路上 —— 那它就不是「没钉」，"
        "而上面那张参数表的前提（钉住 ⇒ 一个文件都不读）也就不成立了")

    monkeypatch.setattr(vm, "_readings", lambda root: [vm.MODE_BORDERLESS])
    assert vm.overlay_is_invisible_now() is False, (
        "同样是空串，盘上读到无边框却仍说独占全屏 —— 这条路根本没在读盘")


def test_a_root_with_brackets_still_gets_read(tmp_path, monkeypatch):
    """⭐ Steam 装在带方括号的路径下时，`glob` 会把 `[SSD]` 当**字符类**。

    不 `glob.escape` 的话匹配整个落空 ⇒ 一份读数都没有 ⇒ 恒回 `None`。
    ⚠ 失败方向是安全的（照常出通用提示），但它**静默** ——
    那些玩家永远拿不到具体那句话，而没有任何地方会说一声。
    """
    from core import cs2_video_mode as vm

    root = tmp_path / "Games [SSD]" / "Steam"
    cfg = root / "userdata" / "12345" / "730" / "local" / "cfg"
    cfg.mkdir(parents=True)
    (cfg / "cs2_video.txt").write_text(
        '"setting.fullscreen"\t\t"1"\n"setting.nowindowborder"\t\t"0"',
        encoding="utf-8")

    assert vm._readings(str(root)) == [vm.MODE_EXCLUSIVE], (
        "带方括号的 Steam 根目录读不出来 —— `glob.escape` 掉了？")


@pytest.mark.parametrize("exclusive_now", [False, True])
def test_both_wordings_still_say_how_and_what_happens_otherwise(exclusive_now):
    """两档都必须把「怎么做」和「否则会怎样」说全 —— `REQUIRED_WORDS` 一视同仁。

    ⭐ 语序是批 18 实测出来的：动作在前、后果在后，
    「他知不知道该干什么」从 57% → 100%。加了检测不许把这个语序丢掉。
    """
    from widgets.overlay_requirement import (REQUIRED_WORDS,
                                             overlay_requirement_text)

    text = overlay_requirement_text("准心", exclusive_now=exclusive_now)
    for word in REQUIRED_WORDS:
        assert word in text, (
            f"exclusive_now={exclusive_now} 那一档少了「{word}」：{text}")
    assert text.index("无边框窗口") < text.index("独占全屏"), (
        f"动作要在后果前面（批 18 实测 57% → 100%）：{text}")


def test_the_generic_wording_is_byte_identical_to_before_the_check(pinned):
    """⭐ 加检测**不许顺手改掉没检测时那句话** —— 那会把 RN-429 的验收一起改掉。"""
    from widgets.overlay_requirement import overlay_requirement_text

    pinned("unknown")
    assert overlay_requirement_text("击杀图标").startswith(GENERIC_HEAD), (
        "通用那一档的开头变了。它是 RN-429 裁定过的原话，"
        "改它要连那条裁定一起改。")
    assert overlay_requirement_text("击杀图标", exclusive_now=False) == \
        overlay_requirement_text("击杀图标"), "默认档必须等于通用档"


def test_a_pinned_reading_never_touches_the_disk(pinned, monkeypatch):
    """钉了档就**一个文件都不读** —— 否则「钉住」只是「碰巧」（RN-571）。"""
    vm = pinned("exclusive")
    called = []
    monkeypatch.setattr(vm, "_readings",
                        lambda root: called.append(root) or [])
    assert vm.detect_display_mode() == vm.MODE_EXCLUSIVE
    assert not called, (
        "钉了档还去扫盘 —— 那么这台机器的真实状态仍然能influence 结论，"
        "而这正是 RN-571 那一跤：钉的是「推到那个状态」，不是「碰巧就是」。")


def test_readings_that_disagree_are_read_as_unknown(pinned, monkeypatch):
    """一台机器上有 3 个 Steam 账号 —— **不一致就当没读到**，不许挑一份。"""
    vm = pinned(None)
    monkeypatch.setattr(vm, "_readings", lambda root: [
        vm.MODE_EXCLUSIVE, vm.MODE_BORDERLESS])
    import cfg_utils

    monkeypatch.setattr(cfg_utils, "get_steam_path_windows", lambda: "C:/steam")
    assert vm.detect_display_mode() is None, (
        "三份读数不一致时挑了一份 —— 没有可靠依据能挑（RN-429 的第 ① 个未解问题）")

    monkeypatch.setattr(vm, "_readings", lambda root: [])
    assert vm.detect_display_mode() is None, "一份都没读到时必须是「不知道」"


@pytest.mark.parametrize("text, expect", [
    ('"setting.fullscreen"\t\t"1"\n"setting.nowindowborder"\t\t"0"', "exclusive"),
    ('"setting.fullscreen"\t\t"0"\n"setting.nowindowborder"\t\t"1"', "borderless"),
    ('"setting.fullscreen"\t\t"1"\n"setting.nowindowborder"\t\t"1"', "borderless"),
    ('"setting.fullscreen"\t\t"0"\n"setting.nowindowborder"\t\t"0"', "windowed"),
    ('"setting.fullscreen"\t\t"1"', None),          # 缺一个键 ⇒ 不知道
    ("", None),
])
def test_the_undocumented_mapping_is_written_down_and_only_here(text, expect):
    """映射没有文档 ⇒ 它必须只有**一处**实现，且每一格都被钉住。

    ⚠ 这条判据不能证明映射是对的（我没有地面真值）。它证明的是
    **映射改了会有人知道** —— 而映射只被允许决定「说得具体不具体」，
    不被允许决定「要不要警告」（上面那条判据钉的就是这件事）。
    """
    from core import cs2_video_mode as vm

    assert vm._mode_of(text) == expect


#: 这两个键名一出现，就说明那里在自己解释 `cs2_video.txt`。
_SETTING_KEYS = ("setting.fullscreen", "setting.nowindowborder")

#: 允许出现这两个键名的地方：真源本身 + 钉它的判据（就是本文件）。
_MAPPING_HOMES = {
    "core/cs2_video_mode.py",
    "tests/test_the_display_mode_check_only_ever_adds_a_warning.py",
}


def test_the_mapping_really_is_the_only_one():
    """⭐⭐⭐ 上面那条的**名字**说「它必须只有一处实现」，而它的函数体只有一行断言。

    ⚠ 批 73 补正：那条用例叫 `..._and_only_here`、docstring 也写着「只有**一处**实现」，
    可它从头到尾没有任何唯一性检查 —— 有人在别处（某个页面、某个工装）再写一份
    `fullscreen/nowindowborder → 档位` 的映射，它满分通过。
    ⭐ **一条判据的名字承诺的，可以比它的函数体做的多** —— 而读报告的人信的是名字。
    ⇒ 按「只许加强」补上检查，不是把名字改小。
    """
    offenders = []
    scanned = 0
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        # ⭐ `.claude/worktrees/` 底下是整个仓的一份副本（RN-561）——
        #   不跳过它，每个文件会被数两遍，而这种污染**只朝「有」的方向失效**。
        if any(part in rel for part in
               ("__pycache__", ".build/", "_manual_backup", "artifacts/",
                ".claude/")):
            continue
        if rel in _MAPPING_HOMES:
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        if all(key in src for key in _SETTING_KEYS):
            offenders.append(rel)
    # ⭐⭐ 分母守卫：一空它必然全绿，而「分母为空」和「真的没问题」
    #   在测试报告上一模一样 —— 这正是本批反复撞到的那件事。
    assert scanned >= 200, (
        f"只扫到 {scanned} 个 .py —— 这个仓有 400+ 个，多半是排除规则把仓扫空了")
    assert not offenders, (
        f"这些地方也在自己解释 `cs2_video.txt` 的那两个键：{offenders}\n"
        f"⇒ 那个映射**没有文档**（模块头 ②），所以它只能有一处实现。"
        f"两处会各自漂，而漂了不会有任何声响。")


def test_the_toolchain_pins_this_reading(monkeypatch):
    """⚠ 工装必须钉档，否则截图/审计的字随机器而变（同 RN-472 / RN-146）。"""
    from core.cs2_video_mode import MODE_ENV

    src = (REPO / "scripts" / "_audit_neutralize.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "enable_audit_mode")
    pinned = [n for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and n.value == MODE_ENV]
    assert pinned, (
        f"`enable_audit_mode()` 没有钉 {MODE_ENV} —— 于是同一份代码在两台机器上"
        f"出的字不一样，而那正是 RN-472 / RN-146 已经踩过两次的坑。")

    conf = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert MODE_ENV in conf, (
        f"`tests/conftest.py` 没有钉 {MODE_ENV} —— "
        f"跑测试的机器要是正在独占全屏，一批文案判据会莫名其妙地红。")

    # ⭐⭐⭐ **第三道：基线采集那条路刻意不走 `enable_audit_mode()`**
    #   （`renovation_baseline.structure_of` 的注释明写「这一行不能换成它」），
    #   而 structure.json 恰恰存着覆盖层前提那句文案。
    #   ⚠ 第一版我只钉了工装和 conftest 两道，漏了这一道 ——
    #   ⭐ **一个装在共用入口里的闸门，够不着刻意绕开那个入口的调用方。**
    baseline = (REPO / "scripts" / "renovation_baseline.py").read_text(encoding="utf-8")
    assert MODE_ENV in baseline, (
        f"`scripts/renovation_baseline.py` 没有钉 {MODE_ENV} —— "
        f"于是在一台 CS2 正处于独占全屏的机器上，crosshair / kill_icon / "
        f"screen_effects 三页的 structure.json 会采到另一句文案。")
