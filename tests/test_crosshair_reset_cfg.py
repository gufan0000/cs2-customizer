# SPDX-License-Identifier: GPL-3.0-or-later
"""准心快速回正的 cfg 产物判据。

这一组判据的形状是刻意的：**扫描 `compile_all()` 编译出来的文本**，而不是断言
源码里有没有某一行。原因是这个功能有两条编译路径（viewmodel / HUD rules），
2026-08-15 之前它们对 `cl_crosshair_recoil` 的静息值写法**正好相反**，而当时
两边各自的单元测试都是绿的——因为每个测试只盯着自己那条路径"有没有按自己
以为的方式输出"。判据必须落在最终产物上，才可能发现"两条路径互相矛盾"。

`test_no_recoil_leak_in_compiled_cfg` 是其中的核心：它不关心谁生成的、生成在
哪一段，只问一件事——**产物里有没有"在开火之外把 cl_crosshair_recoil 置 1"**。
新增第三条路径也会被它扫到。
"""

import re

import pytest

from core.cfg_compiler import compile_all, compile_viewmodel
from core.crosshair_reset import PRIMARY_ALIAS, SECONDARY_ALIAS
from core.hud.rule_compiler import compile_cfg_rules
from core.hud.rule_model import get_default_hud_rules


class _Cfg:
    pass


def _build(**overrides):
    cfg = _Cfg()
    cfg.csgo_dir = r"C:\cs2"
    cfg.hud_rules_enabled = False
    cfg.hud_rules_profile = "balanced_default"
    cfg.hud_runtime_sync_mode = "safe"
    cfg.hud_rules = get_default_hud_rules("balanced_default")
    cfg.crosshair_reset_enabled = True
    cfg.crosshair_reset_attack_key = "mouse1"
    cfg.crosshair_reset_secondary_enabled = False
    cfg.crosshair_reset_secondary_key = "mouse2"
    cfg.viewmodel_presets = []
    cfg.viewmodel_cycle_key = "CAPSLOCK"
    cfg.magnifier = {"sensitivity_sync_enabled": False}
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ── 泄漏判据 ────────────────────────────────────────────────────────────

#: 一行里出现「把 recoil 置 1」
_SET_ONE = re.compile(r"cl_crosshair_recoil\s+1\b")
#: 一行是「按下开火的 alias 定义」——只有这种行里出现置 1 才是合法的
_PRESS_ALIAS = re.compile(r"^\s*alias\s+\+\S+\s+\"[^\"]*\+attack2?\b", re.IGNORECASE)


def find_recoil_leaks(cfg_text: str):
    """返回所有「在开火之外把 cl_crosshair_recoil 置 1」的行。

    这就是判据本身，独立成函数是为了能拿手写的坏文本直接回验它有效
    （见 test_leak_detector_catches_known_bad_shapes）。
    """
    leaks = []
    for line in cfg_text.splitlines():
        if not _SET_ONE.search(line):
            continue
        if _PRESS_ALIAS.match(line):
            continue
        leaks.append(line.strip())
    return leaks


def test_no_recoil_leak_in_compiled_cfg():
    """开火之外置 1 = 队友和 demo 全程可见。四种开关组合都不许出现。"""
    for hud in (False, True):
        for secondary in (False, True):
            cfg = _build(
                hud_rules_enabled=hud,
                crosshair_reset_secondary_enabled=secondary,
            )
            content, _ = compile_all(cfg)
            assert find_recoil_leaks(content) == [], (
                f"hud={hud} secondary={secondary} 编译产物里有回正泄漏"
            )


def test_leak_detector_catches_known_bad_shapes():
    """回退验证：把真出现过/容易写出的错法喂进去，判据必须翻红。

    第一条就是 2026-08-15 之前 `compile_viewmodel` 真实输出的那一行。
    """
    bad_samples = [
        "cl_crosshair_recoil 1",                                   # 历史真实泄漏
        "  cl_crosshair_recoil 1  ",                               # 带缩进
        'alias -quickrepos_attack "-attack; cl_crosshair_recoil 1"',  # 松开置 1（写反）
        'alias fp_setup "cl_crosshair_recoil 1"',                   # 藏进别的 alias
        'bind F5 "cl_crosshair_recoil 1"',                          # 绑到别的键
    ]
    for sample in bad_samples:
        assert find_recoil_leaks(sample), f"判据漏掉了坏样本: {sample}"

    good_samples = [
        'alias +quickrepos_attack "+attack; cl_crosshair_recoil 1"',
        'alias +quickrepos_attack2 "+attack2; cl_crosshair_recoil 1"',
        'alias +quickrepos_attack "+attack; cl_crosshair_recoil 1; exec cs2customizer_hud_runtime.cfg"',
        "cl_crosshair_recoil 0",
    ]
    for sample in good_samples:
        assert not find_recoil_leaks(sample), f"判据误伤了好样本: {sample}"


# ── 静息值 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("hud", [False, True])
def test_resting_value_is_zero_when_enabled(hud):
    """启用时必须显式写一次静息 0：用户 config.cfg 里可能存着上次的 1。"""
    cfg = _build(hud_rules_enabled=hud)
    content, _ = compile_all(cfg)
    assert "cl_crosshair_recoil 0" in content


def test_two_paths_agree_on_resting_value():
    """两条路径以前对静息值写反了（viewmodel 写 1、HUD 写 0）。

    现在它们共用一个生成器，这条判据保证的是"共用"这件事没被人绕过。
    """
    viewmodel_only = compile_viewmodel(_build(hud_rules_enabled=False))
    hud_lines = "\n".join(compile_cfg_rules(_build(hud_rules_enabled=True)))
    for text in (viewmodel_only, hud_lines):
        assert "cl_crosshair_recoil 0" in text
        assert find_recoil_leaks(text) == []


# ── 关闭路径 ────────────────────────────────────────────────────────────


def test_disabled_still_emits_passthrough_alias():
    """关掉开关必须真的关掉。

    CS2 存 bind 不存 alias，所以启用过的用户 config.cfg 里长期留着
    `bind mouse1 +quickrepos_attack`。以前关闭时这一段整个不输出，那个 bind
    还活着 —— 用户点了"关闭"，功能照跑。
    """
    cfg = _build(crosshair_reset_enabled=False, hud_rules_enabled=False)
    content = compile_viewmodel(cfg)
    assert f'alias +{PRIMARY_ALIAS} "+attack"' in content
    assert f'alias -{PRIMARY_ALIAS} "-attack"' in content
    assert f'alias +{SECONDARY_ALIAS} "+attack2"' in content
    # 关闭态不去动用户的按键绑定：他可能压根没把开火放在 mouse1 上
    assert "bind mouse1" not in content
    # 也不替用户决定 recoil 该是几——只撤掉自己加的那层
    assert "cl_crosshair_recoil" not in content


def test_disabled_heals_legacy_hud_alias():
    """老版本 HUD 路径绑的是 fp_hud_mouse1，切换开关会留下指向它的 stale bind。"""
    cfg = _build(crosshair_reset_enabled=False, hud_rules_enabled=False)
    content = compile_viewmodel(cfg)
    assert 'alias +fp_hud_mouse1 "+attack"' in content


def test_disabled_clears_secondary_layer():
    """副开火启用过再关闭，mouse2 上的回正层也要摊平。"""
    cfg = _build(
        crosshair_reset_enabled=False,
        crosshair_reset_secondary_enabled=True,
        hud_rules_enabled=False,
    )
    content = compile_viewmodel(cfg)
    assert f'alias +{SECONDARY_ALIAS} "+attack2"' in content
    assert "cl_crosshair_recoil" not in content


# ── 开火键可配置 ────────────────────────────────────────────────────────


def test_attack_key_is_configurable():
    cfg = _build(crosshair_reset_attack_key="mouse4")
    content = compile_viewmodel(cfg)
    assert f"bind mouse4 +{PRIMARY_ALIAS}" in content
    assert "bind mouse1" not in content


@pytest.mark.parametrize(
    "junk",
    [
        'mouse1"; quit; //',   # 注入尝试
        "   ",                  # 空白
        "mouse 1",              # 带空格
        "a;b",                  # 命令分隔符
        "//",                   # 纯注释符
        "",
    ],
)
def test_attack_key_rejects_junk_and_falls_back(junk):
    """非法键名必须**退回默认**，不能清洗后凑合用。

    清洗的危险在于产物语法合法、语义错误：`mouse1"; quit; //` 洗成
    `mouse1quit//` 之后，`//` 把整行 bind 注释掉，开火键静默没绑上。
    """
    content = compile_viewmodel(_build(crosshair_reset_attack_key=junk))
    assert f"bind mouse1 +{PRIMARY_ALIAS}" in content
    assert "quit" not in content
    bind_lines = [ln for ln in content.splitlines() if ln.startswith("bind ")]
    assert all("//" not in ln for ln in bind_lines)


@pytest.mark.parametrize("key", ["mouse1", "mouse5", "mwheelup", "kp_enter", "f", "3", "["])
def test_attack_key_accepts_real_key_names(key):
    content = compile_viewmodel(_build(crosshair_reset_attack_key=key))
    assert f"bind {key} +{PRIMARY_ALIAS}" in content


def test_secondary_covers_attack2_when_enabled():
    cfg = _build(crosshair_reset_secondary_enabled=True)
    content = compile_viewmodel(cfg)
    assert f'alias +{SECONDARY_ALIAS} "+attack2; cl_crosshair_recoil 1"' in content
    assert f"bind mouse2 +{SECONDARY_ALIAS}" in content


def test_secondary_absent_by_default():
    content = compile_viewmodel(_build())
    assert "attack2; cl_crosshair_recoil" not in content


# ── alias 必须先于 bind ─────────────────────────────────────────────────


def test_alias_defined_before_bind():
    """bind 指向未定义的 alias = 开火键变死键。顺序不能倒。"""
    for hud in (False, True):
        content, _ = compile_all(_build(hud_rules_enabled=hud))
        lines = content.splitlines()
        alias_at = next(
            i for i, ln in enumerate(lines) if ln.startswith(f"alias +{PRIMARY_ALIAS} ")
        )
        bind_at = next(
            i for i, ln in enumerate(lines) if ln.startswith("bind ") and PRIMARY_ALIAS in ln
        )
        assert alias_at < bind_at, f"hud={hud} 时 bind 出现在 alias 之前"


# ── HUD 搭车刷新 ────────────────────────────────────────────────────────


def test_hud_refresh_rides_along_in_same_alias():
    """HUD 运行时刷新要和回正共用一个 alias，不能各绑各的。"""
    lines = compile_cfg_rules(_build(hud_rules_enabled=True))
    text = "\n".join(lines)
    press = [ln for ln in lines if ln.startswith(f"alias +{PRIMARY_ALIAS} ")]
    assert len(press) == 1
    assert "+attack" in press[0]
    assert "cl_crosshair_recoil 1" in press[0]
    assert "exec cs2customizer_hud_runtime.cfg" in press[0]
    # 开火键只能被绑一次，否则后一条覆盖前一条、行为取决于顺序
    assert text.count("bind mouse1 ") == 1


def test_hud_without_reset_still_refreshes_but_no_recoil():
    lines = compile_cfg_rules(
        _build(hud_rules_enabled=True, crosshair_reset_enabled=False)
    )
    text = "\n".join(lines)
    assert "exec cs2customizer_hud_runtime.cfg" in text
    assert "cl_crosshair_recoil" not in text


def test_viewmodel_defers_to_hud_when_hud_active():
    """两条路径都绑开火键的话会互相覆盖，必须只有一条出手。"""
    cfg = _build(hud_rules_enabled=True)
    content = compile_viewmodel(cfg)
    assert "bind mouse1" not in content
    full, warnings = compile_all(cfg)
    assert full.count("bind mouse1 ") == 1
    assert warnings == []
