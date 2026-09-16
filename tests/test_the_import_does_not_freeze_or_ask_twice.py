# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""导入既不冻界面，也不把用户已经回答过的东西再问一遍（2026-09-16）。

## 这条判据是核查逼出来的

用户的原话有两句是**可以量**的：
「官网的资源可以更方便兼容」和「类似击杀图标那边便利的操作」。
核查（拿真实形状的包跑一遍）当场量出三件没做到的事：

| 量到的 | 根因 |
|---|---|
| 官网击杀图标包还在问"这套风格叫什么" | 包里 `style.json` 写着 `name`，没用上 |
| 中文目录名 `击杀音效/清脆/1.mp3` 认不出，英文的认得出 | **17 个中文 label 一个都没进 spec 查找表** |
| 每个官网包都要点一次确定 | `needs_user` 定成「不是 certain 就问」，而包名信号全在 `likely` 档 |

⭐⭐⭐ 第三条是**设计判断错了**，不是 bug：我原来的理由是
「likely 也要过一眼，它能错」。而拿用户的话一比就站不住——
防静默的位置应该是**结果可见**（报告里写清凭什么），不是事前拦一道，
那只是把一次点击强加给每一个用户。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_import_does_not_freeze_or_ask_twice.py`）
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

from core.resource_identify import CERTAIN, LIKELY, UNSURE, identify_groups
from core.resource_import_source import open_source, sweep_stale_temp_dirs
from core.resource_import_wizard import (
    apply_resource_import_plan,
    plan_from_decisions,
    prepare_decisions,
)


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return str(path)


def _import(zip_path, resources_root, picks=None):
    """走产品自己那条链路。⭐ 判据**不许**自己抄一份流程 ——
    抄出来的那份从抄完的那一刻就开始漂（核查时正是这么被绊了一次）。"""
    source = open_source(zip_path)
    try:
        prepared = prepare_decisions(source)
        decisions = list(prepared["decided"])
        for group in prepared["unsure"]:
            if picks:
                decisions.append({
                    "paths": group.paths, "spec_key": picks["spec_key"],
                    "style_name": picks.get("style_name", prepared["default_style"]),
                    "bucket": picks.get("bucket", ""),
                })
        report = plan_from_decisions(source, decisions, str(resources_root))
        apply_resource_import_plan(report, dry_run=False)
        return prepared, report
    finally:
        source.cleanup()


def _landed(root):
    found = []
    for walk_root, _dirs, files in os.walk(str(root)):
        for name in files:
            rel = os.path.relpath(os.path.join(walk_root, name), str(root))
            found.append(rel.replace("\\", "/"))
    return sorted(found)


# ------------------------------------------------- 不再问已经回答过的

def test_a_pack_manifest_name_is_used_as_the_style_name(tmp_path):
    """⭐ 击杀图标包是社区站**唯一**有规范的一类，它的 `style.json` 带着 `name`。
    再问一遍"这套叫什么"，就是把用户填过的东西又问一次。"""
    resources = tmp_path / "res"
    resources.mkdir()
    meta = json.dumps({"frame_width": 10, "frame_height": 10, "frames": 1})
    zip_path = _zip(tmp_path / "天使传说级武器.zip", {
        "style.json": json.dumps({"name": "天使传说", "pack_version": 1},
                                 ensure_ascii=False),
        "1.png": b"\x89PNG" + b"\0" * 32, "1.json": meta,
        "2.png": b"\x89PNG" + b"\0" * 32, "2.json": meta,
    })
    prepared, _report = _import(zip_path, resources)
    assert not prepared["unsure"], "官网的图标包不该还要问"
    landed = _landed(resources)
    assert landed and all(path.startswith("kill_icons/天使传说/") for path in landed), landed


def test_the_pack_filename_is_the_fallback_style_name(tmp_path):
    """没有清单时，包名就是作者起的名字 —— 比让用户从零想一个强。"""
    resources = tmp_path / "res"
    resources.mkdir()
    zip_path = _zip(tmp_path / "CF爆头 击杀音效.zip", {"1.mp3": b"x", "2.mp3": b"x"})
    prepared, _report = _import(zip_path, resources)
    assert prepared["default_style"] == "CF爆头 击杀音效"


# ------------------------------------------------- 中文目录名

@pytest.mark.parametrize("folder, expect", [
    ("击杀音效", "kill_sounds"),
    ("击杀语音", "kill_voices"),
    ("枪声替换", "gun_sounds"),
    ("kill_sounds", "kill_sounds"),
])
def test_a_chinese_folder_name_is_recognised_too(folder, expect):
    """⚠⚠ `build_spec_lookup()` 只收英文 key / 目录名 / 别名，
    **17 个中文 label 一个都不在里面** —— 于是英文路径认得出、
    而中文用户最自然的写法认不出。

    ⭐ 这是拿真实写法喂进去才看见的：英文那条走得通，
    让人以为"路径规则没问题"，而这个产品的用户打的包是中文目录名。
    """
    groups = identify_groups([f"{folder}/清脆/1.mp3"], source_name="合集.zip")
    assert len(groups) == 1
    assert groups[0].confidence == CERTAIN, f"{folder} 没被当成类目录名认出来"
    assert groups[0].preselect.spec_key == expect


def test_chinese_and_english_folders_can_mix_in_one_pack(tmp_path):
    resources = tmp_path / "res"
    resources.mkdir()
    zip_path = _zip(tmp_path / "大合集.zip", {
        "击杀音效/清脆/1.mp3": b"x",
        "kill_voices/低沉/1.mp3": b"x",
    })
    prepared, _report = _import(zip_path, resources)
    assert not prepared["unsure"]
    assert _landed(resources) == [
        "audio/kill_sounds/清脆/1.mp3",
        "audio/kill_voices/低沉/1.mp3",
    ]


# ------------------------------------------------- likely 不再拦人

def test_a_likely_group_is_not_stopped_for_confirmation():
    """⭐⭐⭐ 本文件最重要的一条：`likely` **不拦人**。

    官网包的主力信号是包名词典，那一档全是 `likely`；
    按旧定义（`!= CERTAIN` 就问）每个官网包都要点一次确定 ——
    与「官网资源更方便兼容」直接冲突。
    """
    groups = identify_groups(["AK47/默认/1.wav"], source_name="全枪枪声替换.zip")
    group = groups[0]
    assert group.confidence == LIKELY
    assert not group.needs_user, (
        "有把握的猜测还要拦一道 —— 那只是把一次点击强加给每个用户。"
    )


def test_an_unsure_group_still_stops():
    """反面守卫：真拿不准的**必须**停下来问，否则就是静默猜。"""
    groups = identify_groups(["AK47/默认/1.wav"], source_name="素材.zip")
    assert groups[0].confidence == UNSURE
    assert groups[0].needs_user


def test_every_automatic_decision_says_why(tmp_path):
    """⭐ `likely` 不再弹窗拦人 ⇒ 防静默的位置全在这一行上：
    报告里必须逐条写清**凭什么**归到这一类。"""
    resources = tmp_path / "res"
    resources.mkdir()
    zip_path = _zip(tmp_path / "全枪枪声替换 v2.zip", {"AK47/默认/1.wav": b"x"})
    prepared, report = _import(zip_path, resources)
    assert prepared["decided"]
    for item in prepared["decided"]:
        assert item.get("why"), f"自动归类没说凭什么：{item}"
        assert "枪声" in item["why"]
    for item in report["recognized"]:
        assert item.get("why"), "落盘报告里也要带着理由，用户看的是这一份"


# ------------------------------------------------- 后台与残留

def test_the_extraction_reports_progress_and_can_be_cancelled(tmp_path):
    """⭐ 「类似击杀图标那边便利的操作」= 后台跑 + 进度 + 取消。

    这里测的是**底层能力**（`open_source` 收不收这两个钩子），
    UI 那一层由页面冒烟覆盖。
    """
    zip_path = _zip(tmp_path / "包.zip", {f"a/{i}.wav": b"x" * 64 for i in range(12)})
    seen = []
    source = open_source(zip_path, progress=lambda d, t, s: seen.append((d, t)))
    source.cleanup()
    assert seen, "一条进度都没报 —— 界面上就只能是一个转圈"
    assert seen[-1][0] == seen[-1][1], f"最后一条进度不是满的：{seen[-1]}"

    with pytest.raises(Exception) as caught:
        open_source(zip_path, should_cancel=lambda: True)
    assert "取消" in str(caught.value) or caught.type.__name__ == "ImportCancelled"


def test_a_killed_process_leaves_nothing_behind_forever(tmp_path, monkeypatch):
    """⭐⭐ `cleanup()` 管得住"忘了调"，管不住"进程被杀"——那一刻它根本没机会跑。
    ⇒ 下一次导入时把上次的残留收掉。⚠ 阈值是故意留的：
    同一台机器上可能有**两个**导入同时在跑，扫掉人家正在用的目录会让那边当场崩。
    """
    import tempfile

    stale = os.path.join(tempfile.gettempdir(), "cs2customizer_import_pretend_stale")
    os.makedirs(stale, exist_ok=True)
    try:
        # 刚建出来的不许扫
        assert sweep_stale_temp_dirs() == 0 or os.path.isdir(stale)
        assert os.path.isdir(stale), "刚建出来的目录被扫了 —— 可能扫掉别人正在用的"
        # 谎报一个很晚的"现在"，它就该被收掉
        cleaned = sweep_stale_temp_dirs(now=os.path.getmtime(stale) + 10 * 3600)
        assert cleaned >= 1
        assert not os.path.isdir(stale)
    finally:
        if os.path.isdir(stale):
            os.rmdir(stale)
