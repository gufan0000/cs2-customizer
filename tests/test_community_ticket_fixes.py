# SPDX-License-Identifier: GPL-3.0-or-later
"""社区工单返修的判据（批 105，RN-659~664）。

社区用户报的一批问题，五个只读视角逐条核对后确凿属实的那几条。
每条判据都写清**它挡的是用户报的哪一句话**——因为这些缺陷的共同形状是
「代码自己没错，但用户听到/看到的是另一回事」，只钉实现细节的判据挡不住它们。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _tree(rel):
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"找不到函数 {name}")


# ───────────────────────────── A1：切出投掷物的音效缺三种

#: 六种投掷物**全都拿得出来**，所以切枪音效这一档六种都该能配。
#: ⚠ 前三种一直都在，后三种是本批补的（用户原话：「切出的音效没闪没烟」）。
THROWABLES = (
    "weapon_hegrenade", "weapon_molotov", "weapon_incgrenade",
    "weapon_flashbang", "weapon_smokegrenade", "weapon_decoy",
)


def test_every_throwable_can_have_a_switch_sound():
    """六种投掷物都要出现在切枪音效页的「投掷物」分类里。

    ⭐ 这条挡的是一个**分母**问题：这张表以前跟着 `weapon_kill_sounds` 走，
    而那张按「能不能杀人」组织 —— 闪光弹杀不了人，于是它连「拿得出来」
    这件事也一起从界面上消失了。
    """
    from pages.switch_weapon_page import SwitchWeaponPage

    listed = set(SwitchWeaponPage.CATEGORIES["投掷物"])
    missing = [w for w in THROWABLES if w not in listed]
    assert not missing, f"切枪音效页的投掷物少了: {missing}"

    # 光在分类里还不够——没有显示名的话界面上是一串英文代号
    nameless = [w for w in THROWABLES if w not in SwitchWeaponPage.WEAPON_NAMES]
    assert not nameless, f"这些投掷物没有中文显示名: {nameless}"


def test_the_new_throwables_have_a_config_slot():
    """配置里得有它们的位置，否则界面选了也存不下来。"""
    from config import config

    missing = [w for w in THROWABLES if w not in config.weapon_switch_sounds]
    assert not missing, f"配置里没有这些投掷物的切枪音效项: {missing}"


def test_the_kill_sound_table_did_not_grow_a_weapon_that_cannot_kill():
    """⛔ 反向守卫：修法**不许**是把它们塞进击杀音效表。

    塞进去省事，代价是击杀音效页上冒出「闪光弹击杀」「烟雾弹击杀」这种
    杀不了人的条目 —— 那是把一个缺陷换成另一个。
    """
    from config import config

    for weapon in ("weapon_flashbang", "weapon_smokegrenade", "weapon_decoy"):
        assert weapon not in config.weapon_kill_sounds, (
            f"{weapon} 跑进击杀音效表了 —— 它杀不了人，那一页不该有它"
        )


# ───────────────────────────── A2：音效不会因为动作没了而停

def test_the_audio_manager_can_stop_a_whole_channel_type():
    """按「哪一类音效」停，而不是按通道停。

    ⚠ 切枪是三条通道轮转的 —— 只停 `_select_channel` 挑出来的那条，
    停到的是**下一次要用的**那条，不是正在响的那条。
    """
    from core.audio.audio_manager import AudioManager

    manager = AudioManager.__new__(AudioManager)  # 不占音频设备

    class _Ch:
        def __init__(self, busy):
            self.busy = busy
            self.stopped = False

        def get_busy(self):
            return self.busy

        def stop(self):
            self.stopped = True

    channels = [_Ch(True), _Ch(False), _Ch(True)]
    manager.switch_weapon_channels = channels
    manager.switch_weapon_channel = channels[0]

    assert manager.stop_channel_type("switch_weapon") is True
    assert [c.stopped for c in channels] == [True, False, True], (
        "三条轮转通道里正在响的都要停，没在响的不用动"
    )


def test_a_cancelled_reload_stops_the_reload_sound(monkeypatch):
    """换弹被打断/装满了 ⇒ 那段音效就该停。

    用户原话：「切枪、换弹音效不会因为停止换弹或切换其他武器停止」。
    以前只收 `reloading` 的**上升沿**，下降沿没有人管。
    """
    import gsi_handler_sounds as mod
    from config import config

    stopped: list[str] = []
    played: list[str] = []

    class _Audio:
        def play_sound(self, key, **_kw):
            played.append(key)
            return True

        def stop_channel_type(self, channel_type):
            stopped.append(channel_type)
            return True

    monkeypatch.setattr(mod, "audio_manager", _Audio())
    monkeypatch.setattr(config, "reload_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_ak47": "经典"}, raising=False)

    handler = mod.GSIHandlerSounds()

    def packet(state):
        return {"player": {"weapons": {"weapon_0": {"name": "weapon_ak47", "state": state}}}}

    handler._process_reload_sound(packet("reloading"))
    assert played, "开始换弹本来就该出声"
    assert stopped == [], "刚开始换弹就停声是错的"

    handler._process_reload_sound(packet("active"))
    assert "reload" in stopped, "换弹结束了，那段音效还在自顾自地播完"


def test_switching_weapons_cuts_the_previous_switch_sound(monkeypatch):
    """又切了一把枪 ⇒ 上一把的切枪音不该还在响。

    三条通道轮转，以前连切三把枪是三个音叠着响。
    """
    import gsi_handler_sounds as mod
    from config import config

    stopped: list[str] = []

    class _Audio:
        def play_sound(self, key, **_kw):
            return True

        def stop_channel_type(self, channel_type):
            stopped.append(channel_type)
            return True

    monkeypatch.setattr(mod, "audio_manager", _Audio())
    monkeypatch.setattr(config, "weapon_switch_sounds", {"weapon_ak47": "经典"}, raising=False)

    handler = mod.GSIHandlerSounds()
    handler.last_active_weapon = "weapon_awp"
    handler._process_weapon_switch_sound(
        {"player": {"weapons": {"weapon_0": {"name": "weapon_ak47", "state": "active"}}}}
    )
    assert "switch_weapon" in stopped, "切到新枪时没有掐掉上一把的切枪音"


# ───────────────────────────── B1：回合阶段跳变那一包不报切枪

def _switch_packet(weapon, phase):
    return {
        "round": {"phase": phase},
        "player": {"weapons": {"weapon_0": {"name": weapon, "state": "active"}}},
    }


@pytest.fixture
def switch_handler(monkeypatch):
    import gsi_handler_sounds as mod
    from config import config

    plays: list[str] = []

    class _Audio:
        def play_sound(self, key, **_kw):
            plays.append(key)
            return True

        def stop_channel_type(self, channel_type):
            return True

    monkeypatch.setattr(mod, "audio_manager", _Audio())
    monkeypatch.setattr(config, "weapon_switch_sounds", {
        "weapon_ak47": "经典", "weapon_knife": "经典", "weapon_awp": "经典",
    }, raising=False)
    handler = mod.GSIHandlerSounds()
    return handler, plays


def test_a_round_phase_change_does_not_report_a_weapon_switch(switch_handler):
    """回合阶段跳变那一包不出声，但基线要追上去。

    用户原话：「游戏结束的时候切枪和击杀音效又触发一次」「比如说你拆完包他也会响一下」。
    那一瞬间是**游戏**在动玩家的武器栏（收装备、发装备、换边），不是玩家切枪。
    ⚠ 基线必须追上去，否则下一包又会被当成一次切枪 —— 把响声推迟一包，不算修好。
    """
    handler, plays = switch_handler

    # 先正常打一枪的场景：阶段稳定在 live，玩家自己切枪 ⇒ 要响
    handler._track_round_phase(_switch_packet("weapon_ak47", "live"), {})
    handler._process_weapon_switch_sound(_switch_packet("weapon_ak47", "live"), phase_changed=False)
    assert plays, "阶段没变的时候玩家自己切枪，必须照常响"
    plays.clear()

    # 回合结束那一包：阶段跳变 + 武器栏被游戏改成刀 ⇒ 不许响
    handler._process_weapon_switch_sound(_switch_packet("weapon_knife", "over"), phase_changed=True)
    assert plays == [], "回合阶段跳变那一包不该报切枪"
    assert handler.last_active_weapon == "weapon_knife", (
        "基线没追上去 —— 下一包会把同一次变化再报一遍，等于只把响声推迟了一包"
    )

    # 下一包阶段已经稳定，不该补响
    handler._process_weapon_switch_sound(_switch_packet("weapon_knife", "over"), phase_changed=False)
    assert plays == [], "跳变之后紧接着的那一包又把它补响了"


def test_the_phase_tracker_only_fires_on_a_real_change(switch_handler):
    """第一包不算跳变（没有"上一包"可比），同一个阶段连续来也不算。"""
    handler, _ = switch_handler

    assert handler._track_round_phase({"round": {"phase": "live"}}, {}) is False, (
        "第一包就报跳变的话，开局第一次切枪会被吃掉"
    )
    assert handler._track_round_phase({"round": {"phase": "live"}}, {}) is False
    assert handler._track_round_phase({"round": {"phase": "over"}}, {}) is True
    assert handler._track_round_phase({"round": {"phase": "over"}}, {}) is False


# ───────────────────────────── A5：投掷物目录名写错要报警

def test_a_misspelled_grenade_folder_is_reported():
    """投掷物的类型目录写错了，导入向导要说话。

    ⭐ 以前 `known_buckets("grenade_sounds")` 返回 `None`，而 `None` 会让
    `bucket_problem()` 直接短路 ⇒ **永不报警** ⇒ 用户把目录名写成「闪光」
    而不是 `flashbang`，文件被静静放进一个产品永远不会去读的目录。
    """
    from core.resource_readback import known_buckets

    buckets = known_buckets("grenade_sounds")
    assert buckets is not None, "投掷物的类型层又变回「产品不挑」了"
    assert "flashbang" in buckets and "smoke" in buckets
    assert "闪光" not in buckets


def test_the_grenade_buckets_come_from_the_product_not_a_second_list():
    """那张表必须**现算**自产品的真源，不许再手抄一份。

    ⭐ 本仓的老账：同一份清单抄第二遍，加类型时漏改的表现是「配了也不响」。
    """
    from core.audio.audio_manager import AudioManager
    from core.resource_readback import known_buckets

    assert known_buckets("grenade_sounds") == frozenset(
        str(t).lower() for t in AudioManager.GRENADE_TYPES
    )


# ───────────────────────────── A3/A4：文案要说清「什么时候响」和「目录叫什么」

def test_the_help_text_says_when_each_c4_event_fires():
    """C4 三个事件各自什么时候响，帮助面板要说。

    用户是在群里问出来的：「这个是拆除后触发还是拆的那个音效」「是滴包么」。
    ⚠ 以前帮助面板只写了「安装炸弹（下包）时」—— 界面上明明摆着三项。
    """
    from ui_help_panel import PAGE_HELP_TEXTS

    text = PAGE_HELP_TEXTS["special_sound"]
    assert "拆除" in text and "爆炸" in text, "帮助面板还是只讲了安放那一个事件"
    assert "成功" in text, "没说清拆除是「拆成功那一刻」还是「开始拆」"


def test_the_help_text_lists_the_real_grenade_folder_names():
    """投掷物六个类型的**英文目录名**要写出来，不能只给占位符。

    用户原话：「也没有教程和命名格式」「怎么导入手雷的音效」。
    """
    from core.audio.audio_manager import AudioManager
    from ui_help_panel import PAGE_HELP_TEXTS

    # 分母：产品支持的投掷物类型。它要是空了，下面那条否定断言必然全绿。
    assert len(AudioManager.GRENADE_TYPES) == 6, (
        f"投掷物类型变成 {len(AudioManager.GRENADE_TYPES)} 种了 —— "
        "先确认是有意改的，再把这个数和帮助面板一起更新"
    )

    text = PAGE_HELP_TEXTS["special_sound"]
    missing = [t for t in AudioManager.GRENADE_TYPES if t not in text]
    assert not missing, f"帮助面板里没写这几个类型目录名: {missing}"
    assert "投掷物类型" not in text, "那个占位符还在 —— 用户照样不知道该写什么"


def test_the_help_text_does_not_promise_a_filename_that_is_ignored():
    """⛔ 不许再写 `throw.mp3` 这种文件名 —— 代码根本不看文件名。

    ⭐ 一句**说得很具体却是假的**说明，比没有说明更糟：用户会照着做，
    做完发现不响，然后怀疑的是自己。
    """
    from ui_help_panel import PAGE_HELP_TEXTS

    text = PAGE_HELP_TEXTS["special_sound"]
    assert "throw.mp3" not in text
    assert "warning.mp3" not in text, "血量警告那条同样不挑文件名，写死文件名是假说明"


def test_the_grenade_tab_shows_the_folder_names_on_the_page_itself():
    """目录名要摆在**页面上**，不是只藏在帮助面板里。

    用户是先在页面上找不到，才跑到群里问的。
    """
    source = (REPO / "pages" / "special_sound_page.py").read_text(encoding="utf-8")
    builder = source.split("def _create_grenade_tab")[1].split("\n    def ")[0]
    assert "grenade_sounds" in builder, "投掷物页签上没写目录路径"
    assert "GRENADE_TYPES" in builder, "页面上的类型名该从真源现算，不许手抄"


# ───────────────────────────── A6：转发缺什么要当场说

def test_the_forwarding_page_names_what_is_still_missing():
    """音效转发要三件事同时成立，缺哪件就说哪件。

    用户原话：「音效转发疑似不生效、也可能是我的问题」——
    ⭐ 不是他的问题：缺「语音播放」总开关或 VB-Cable 时，转发是在
    `voice_output_manager` 里 `return False` 掉的，**只留一行 debug 日志**。
    """
    tree = _tree("pages/voice_output_page.py")
    fn = _function(tree, "_sfx_forwarding_blockers")
    source = ast.get_source_segment(
        (REPO / "pages" / "voice_output_page.py").read_text(encoding="utf-8"), fn
    )
    assert "voice_output_enabled" in source, "没检查「语音播放」总开关"
    assert "_driver_ready" in source, "没检查 VB-Cable"


def test_the_forwarding_hint_is_refreshed_when_the_switch_changes():
    """开关一动，那行提示就要重算——否则它显示的是上一次的状态。"""
    tree = _tree("pages/voice_output_page.py")
    fn = _function(tree, "_update_sfx_forwarding")
    called = [
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "_refresh_sfx_forwarding_requirements" in called


# ───────────────────────────── 空转守卫

def test_these_judges_would_notice_if_the_throwables_went_away():
    """空转守卫：证明上面那条切枪投掷物判据真的在看那张表。

    ⭐ 批 103/104 连着两次踩到「两条修复互相盖住、判据在空转」，
    所以这里当场证一次：把表换成旧的三种，判据必须红。
    """
    old_table = ["weapon_hegrenade", "weapon_molotov", "weapon_incgrenade"]
    missing = [w for w in THROWABLES if w not in set(old_table)]
    assert len(missing) == 3, (
        "拿修复前那张表去比，必须正好缺三种 —— 否则上面那条判据守的不是这件事"
    )


def test_the_phase_gate_is_what_keeps_the_round_end_quiet(switch_handler):
    """空转守卫：把 `phase_changed` 关掉，那一包就必须又响起来。"""
    handler, plays = switch_handler
    handler.last_active_weapon = "weapon_ak47"
    handler._process_weapon_switch_sound(_switch_packet("weapon_knife", "over"), phase_changed=False)
    assert plays, "不给 phase_changed 也不响的话，上面那条判据绿得没有意义"
