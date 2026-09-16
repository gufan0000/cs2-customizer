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


# ------------------------------------- 扫描报告的寿命不许超过它那个源

@pytest.fixture
def wizard(qapp, monkeypatch, tmp_path):
    """页面实例。⚠ 必须拦掉模态框，否则页面测试会**卡死**（KI 那批的教训）。

    ⛔⛔ 资源根必须**每个用例一个新目录**。第一版没做这件事，
    于是页面用的是 `%TEMP%/cs2customizer_test_config/resources` —— 那是一个
    **跨次持久**的目录（RN-646）。表现是：第一次跑全绿，第二次跑
    「撤销按钮没出现」红，因为文件已经在那儿了 ⇒ 整包变成"冲突跳过"、
    `copied` 为空 ⇒ 不给撤销。
    ⭐⭐⭐ **一条判据的结果取决于上一次运行留下的文件，它就不是判据** ——
    而它能假绿也能假红，两种都发生过。
    """
    from PySide6.QtWidgets import QMessageBox

    import pages.audio_import_wizard_page as mod

    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: 0)
    page = mod.AudioImportWizardPage()
    root = tmp_path / "resources"
    root.mkdir(parents=True, exist_ok=True)
    page.resources_root = str(root)
    page.audio_root = str(root / "audio")
    yield page
    page.deleteLater()


def test_a_refused_source_does_not_leave_the_previous_plan_armed(wizard, tmp_path):
    """⛔⛔ 一次**失败的扫描**必须把上一次的报告作废。

    端到端实测（沙箱真导入）逮到的：先导一个包成功，再喂一个 `.tar.gz` ——
    它被正确拒绝、错误也报了，而紧接着"导入"却说「导入完成：成功 1」，
    **把上一个包又导了一遍**（落进了另一个风格目录）。

    ⭐⭐⭐ 每一层单独看都对：拒绝是对的、报错是对的、导入也照着报告干了活；
    错在**报告的寿命没有跟源绑定**。
    ⚠ 而这一刀单元判据一条都没红 —— 每条判据都只扫一次，
    而这个缺陷只在**第二次**才出现。

    ⚠ 这里把"打不开"直接做成 `_open_import_source` 返回 None
    （那正是 `.tar.gz` 走的那条路），为的是不在判据里起真的后台线程与进度框。
    """
    wizard._scan_report = {"summary": {"recognized_count": 1}}
    wizard._scan_report_source = "上一个包.zip"
    wizard.source_edit.setText(str(tmp_path / "打不开的.tar.gz"))
    wizard._open_import_source = lambda: None       # 认得出、打不开
    wizard._scan_source()
    assert wizard._scan_report is None, (
        "被拒绝的源没有清掉上一次的报告 —— 这时点「导入」会把上一个包再导一遍")
    assert wizard._scan_report_source == ""


def test_a_plan_belongs_to_the_path_it_was_made_for(wizard):
    """⛔ 同一个缺陷的另一张脸：**改了路径但没重扫**。

    ⭐ 所以判据钉的不是"失败要清理"，而是那个不变式本身：
    **报告必须属于输入框里现在这个路径。**
    """
    wizard.source_edit.setText("C:/下载/AK47枪声替换包.zip")
    wizard._scan_report = {"summary": {}}
    wizard._scan_report_source = "C:/下载/AK47枪声替换包.zip"
    assert not wizard._scan_is_stale()

    wizard.source_edit.setText("C:/下载/击杀音效包.zip")
    assert wizard._scan_is_stale(), "路径换了，报告必须跟着作废"


def test_no_report_is_not_the_same_as_a_stale_one(wizard):
    """⚠ "还没扫"不算"过期" —— 混成一件事会让首次导入多走一次无谓的作废。"""
    wizard.source_edit.setText("C:/下载/随便.zip")
    wizard._invalidate_scan()
    assert not wizard._scan_is_stale()


def test_the_two_fields_are_only_ever_cleared_together():
    """棘轮：`_scan_report` 不许在 `_invalidate_scan` 之外被单独赋 None。

    ⭐⭐ 两个必须一起动的字段散在四处各自赋值，正是本轮修掉的那种
    "各自列举、谁也不管谁" —— 而它下一次出问题时长得和这次一模一样。
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "pages" / "audio_import_wizard_page.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Attribute)
                    and target.attr == "_scan_report"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                offenders.append(node.lineno)
    # ⭐ 分母：这个文件里**本来就该有** `self._scan_report = ...` 的赋值
    #   （`_invalidate_scan` 里一处清空、`_scan_unified` 里一处赋新报告）。
    #   一个都没扫到说明抽取器瞎了，而"分母为空"和"真的没问题"在报告上一模一样。
    assert len(offenders) >= 2, (
        f"只扫到 {len(offenders)} 处 `self._scan_report` 赋值 —— "
        f"抽取器多半瞎了，这条棘轮在空转")
    inside = {n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_invalidate_scan"
              for n in ast.walk(n) if isinstance(n, ast.Assign)}
    stray = sorted(set(offenders) - inside)
    # `_scan_unified` 里那一处是**赋新报告**，不是清空 —— 放行。
    stray = [line for line in stray
             if "None" in source.splitlines()[line - 1]]
    assert not stray, (
        f"这些行单独把 `_scan_report` 设成了 None（第 {stray} 行）：\n"
        f"⇒ 一律改成 `self._invalidate_scan()`，"
        f"否则 `_scan_report_source` 会留着上一个路径。")


# ------------------------------------- 撤销按钮要活过这一次导入

def test_the_undo_button_survives_the_import_that_created_it(wizard, tmp_path):
    """⛔⛔ 上一轮做的撤销功能，在真 UI 里**用户根本点不到**。

    `_run_import` 原来是：先 `notice_bar.show_message(..., undo_callback=...)`
    挂出撤销按钮，**紧接着** `if not dry_run: self._scan_source()` ——
    而 `_scan_unified` 第一件事就是 `notice_bar.clear()`。
    实测（沙箱端到端）：导完之后提示条上是一片空白，撤销按钮 `isHidden()` 为真。

    ⭐⭐⭐ 我上一轮的沙箱测试之所以"通过"，是因为脚本**直接点了那个已经被
    隐藏的按钮** —— 能用代码点到，不等于用户点得到。
    ⚠ 那次自动重扫还有另外两重代价：结果必然是"全是冲突"（文件刚落进去），
    以及拿不准的包会**再弹一次确认框**。⇒ 改成不重扫，只作废报告。
    """
    packed = tmp_path / "清脆 击杀音效包.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        for index in (1, 2):
            archive.writestr(f"清脆/{index}.mp3", b"ID3" + b"\0" * 32)

    wizard.source_edit.setText(str(packed))
    wizard._scan_source()
    assert wizard._scan_report, "扫描就没出报告，判据的前提不成立"
    wizard.dry_run_checkbox.setChecked(False)
    wizard._run_import()

    assert wizard.notice_bar.label.text(), (
        "导完之后提示条是空的 —— 「导入完成」被随后的自动重扫擦掉了")
    assert "导入完成" in wizard.notice_bar.label.text()
    assert not wizard.notice_bar.undo_btn.isHidden(), (
        "撤销按钮被藏起来了 —— 这个功能对用户等于不存在")


def test_a_real_import_does_not_silently_rescan_the_same_pack(wizard, tmp_path):
    """⛔ 导完立刻重扫 ⇒ 屏幕上一片"冲突"，而那是**导入成功**的表现。

    ⭐ 报告作废即可（下次点导入自然会重扫），不必当场再扫一遍。
    """
    packed = tmp_path / "低沉 击杀音效包.zip"
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("低沉/1.mp3", b"ID3" + b"\0" * 32)

    scans = {"n": 0}
    original = wizard._scan_unified

    def counted():
        scans["n"] += 1
        return original()

    wizard._scan_unified = counted
    wizard.source_edit.setText(str(packed))
    wizard._scan_source()
    wizard.dry_run_checkbox.setChecked(False)
    wizard._run_import()
    wizard._scan_unified = original

    assert scans["n"] == 1, f"导入之后又扫了一遍（共 {scans['n']} 次）"
    assert wizard._scan_report is None, "落盘之后那份报告就不该再算数了"
