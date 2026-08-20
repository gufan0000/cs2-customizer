# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""视觉工装取样的是**哪一种用户看见的画面**（RN-134）。

## 缺陷

翻新工程从开工到 P2 收尾，**每一个视觉工装都写着 `config.ui_expert_mode = True`**。
产品默认是 `False` —— 于是十七轮外审、十六页像素基线、每一次排版审计，
看的全是**绝大多数用户根本看不到的专家视图**。

咬到的是 RN-133：调试卡片明明已经收进专家模式，**改完复跑外审还在报它**。

## 根因（这一条比缺陷本身值钱）

专家模式在工装里同时兜着两件**完全不同**的事：

  (a) **可达性** —— 6 个专家页在普通模式下没有导航入口，`show_page()` 命中就 return；
  (b) **视图** —— 顺带把每一页都换成专家视图。

十六处 `show_page(pid, animated=False)` **一处都没带 force**，全靠 (a) 兜着。
⇒ 那行 `= True` **谁也质疑不了**：拿掉它工装当场少拍 6 页，看起来就是"不能拿掉"。

⭐ **一个开关同时兜着两件事的时候，它就没法被质疑了。** 得先拆开，才谈得上选。

## 判据

四条，各挡一段：

  ① 工装不许再无条件开专家模式（**允许名单要写理由**）；
  ② 视觉工装换页必须走 `_ui_mode.goto()`（一律 force）—— 否则拿掉 ① 之后
     那 6 页会**静默拍成上一页**，不报错，只是图张冠李戴；
  ③ 两种模式下**只有申报过的页**长得不一样 —— 将来谁给第三页加了模式门控，
     这条会红，逼他要么去掉、要么把那一页的两种视图都锁进基线；
  ④ ③ 的反面守卫：探针真的分得清两种模式（不然 ③ 恒绿，等于没有）。
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

#: 拿来做"画面对不对"结论的工装。它们的取样模式错了，结论就整批作废。
VISUAL_HARNESSES = (
    "ui_shot_capture.py",        # 外审截图 —— 错了等于十七轮全审的另一个软件
    "layout_overflow_audit.py",  # 排版审计
    "renovation_baseline.py",    # 结构投影
    "page_fingerprint.py",       # 结构指纹
)

#: 允许无条件开专家模式的地方，**每一条都要有理由**。
#: 空着理由的条目 = 没想清楚，判据会当它不存在。
EXPERT_ON_PURPOSE = {
    "build_search_index.py":
        "搜索索引必须收进专家页，否则普通用户搜到的条目会比专家少一截 —— "
        "而索引是离线生成、两种模式共用一份的。",
    "v5_visual_baseline.py":
        "V5 时代的整窗基线，专门比「专家视图」这一档；它有自己的 EXPERT_PAGES 名单。",
    "v5_full_smoke.py": "冒烟要把 27 页全建一遍，够不着就少建 6 页。",
    "v5_perf_check.py": "同上，耗时要覆盖全部页面。",
    "v5_themes_smoke.py": "同上。",
    "build_cs2customizer_local_manual.py":
        "本地手册要给专家页也出图文，普通模式下那几页进不去。",
    "probe_search_popup_render.py": "一次性探针，专查搜索浮层。",
    "r9_visual_evidence.py": "R9 时期的一次性取证脚本，留档用，不再当判据。",
}


#: UP-091：这两个文件**连语法都不合法**（基线导入事故，进来时中文就是不可逆乱码），
#: `ruff.toml` 与 `test_audit_no_modal_no_game_writes.py` 里已经把它们钉死。
#: 本判据要 AST 扫全目录，必然撞上它们 ——
#: ⚠ **不能默默跳过**：默默跳过就是给"把文件弄坏"开了一条绕过判据的路。
#: 所以这里正面断言"扫不动的就只有这两个"，多一个就红。
_UP091_UNPARSEABLE = frozenset({
    "bootstrap_tutorial_content.py",
    "capture_web_tutorial_screenshots.py",
})


def _scripts():
    return sorted(p for p in SCRIPTS.glob("*.py") if p.name != "_ui_mode.py")


def _parse(path):
    """解析一支脚本；解析不了就返回 None（调用方必须自己处理，见下面那条判据）。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except SyntaxError:
        return None


def test_the_scan_is_not_blinded_by_broken_files():
    """扫不动的文件**只许是 UP-091 那两个**。

    ⭐ 一条"遇到解析不了的就跳过"的判据，等于宣布：**把文件弄坏就能绕过我。**
    所以扫描范围要正面钉死，而不是靠 try/except 静默收敛。
    """
    unparseable = {p.name for p in _scripts() if _parse(p) is None}
    # 断言的是**子集**不是相等：开源仓的排除清单里没有 UP-091 那两个文件，
    # 写成相等就会在那边当场红 —— 而那条红跟被判的事情毫无关系。
    # ⭐ 判据要落在「这次裁定说的那件事」上，不是它在某个仓库里的具体长相（RN-133 的教训）。
    extra = unparseable - _UP091_UNPARSEABLE
    assert not extra, (
        f"scripts/ 里多了解析不了的文件：{sorted(extra)}\n"
        "它们本文件的所有 AST 判据都扫不到 —— 那就是盲区。\n"
        "（UP-091 那两个是历史损坏、已在册；除它们之外一个都不许有。）")


def _assigns_expert_true(tree) -> bool:
    """AST 找 `<任意>.ui_expert_mode = True` —— 不用 grep：注释和字符串会骗人。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and node.value.value is True):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Attribute) and tgt.attr == "ui_expert_mode":
                return True
    return False


def test_visual_harnesses_sample_the_product_default():
    """① 工装不许再无条件开专家模式。"""
    offenders = []
    for path in _scripts():
        tree = _parse(path)
        if tree is None or not _assigns_expert_true(tree):
            continue
        reason = EXPERT_ON_PURPOSE.get(path.name, "")
        if not reason.strip():
            offenders.append(path.name)
    assert not offenders, (
        f"这些工装把 ui_expert_mode 写死成 True，却没申报理由：{offenders}\n"
        "产品默认是普通模式。工装拍的要是**用户看得见的画面** —— "
        "写死成专家视图，等于整批结论审的是另一个软件（RN-134）。\n"
        "真要审专家视图就走 `--expert`；真有非开不可的理由，"
        "写进本文件的 EXPERT_ON_PURPOSE 并说清为什么。")


def test_the_allowlist_does_not_rot():
    """允许名单里的文件必须还在，而且**真的还在开专家模式**。

    名单最容易的腐烂方式不是"多了一条"，是"那条早就不需要了却没人删" ——
    留着的空条目会替下一个人把门开着。

    ⚠ **"这个仓里没有这支脚本"不算腐烂**：开源版的排除清单本来就少几支
    （实测少 `build_cs2customizer_local_manual.py`）。按"文件不在就报腐烂"写，
    这条判据搬到开源仓当场红，而那条红跟被判的事情毫无关系。
    """
    stale, present = [], 0
    for name, reason in EXPERT_ON_PURPOSE.items():
        assert reason.strip(), f"{name} 的豁免理由是空的"
        path = SCRIPTS / name
        if not path.exists():
            continue          # 这个仓没有这支脚本，没什么可豁免的
        present += 1
        tree = _parse(path)
        if tree is None or not _assigns_expert_true(tree):
            stale.append(f"{name}（已经不开专家模式了，这条豁免该删）")
    assert not stale, f"专家模式豁免名单已腐烂：{stale}"
    assert present, (
        "豁免名单里**一支脚本都不存在** —— 多半是 scripts/ 被挪了位置，"
        "那样上面那条「不许无条件开专家模式」也就什么都扫不到了。")


def _show_page_calls_missing_force(tree) -> list[int]:
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "show_page"):
            continue
        forced = any(
            kw.arg == "force" and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords)
        if not forced:
            bad.append(node.lineno)
    return bad


def test_visual_harnesses_reach_pages_without_relying_on_the_mode():
    """② 换页一律 force —— 不带 force 的失败方式是**静默拍成上一页**。"""
    offenders = {}
    for name in VISUAL_HARNESSES:
        path = SCRIPTS / name
        tree = _parse(path)
        assert tree is not None, f"{name} 解析不了 —— 视觉工装不许是坏文件"
        bad = _show_page_calls_missing_force(tree)
        if bad:
            offenders[name] = bad
    assert not offenders, (
        f"这些视觉工装里有不带 force 的 show_page：{offenders}\n"
        "普通模式下 6 个专家页没有导航入口，`show_page` 会**静默 return** —— "
        "工装于是拿着上一页的窗口继续拍/继续量，不报错，只是图张冠李戴。\n"
        "走 `scripts/_ui_mode.goto(win, pid)`（它一律 force）。")


# --------------------------------------------------------------------------
# ③④ 两种模式的实际差异 —— 这两条要真的建窗口，慢（两趟各 ~8 秒）。
# --------------------------------------------------------------------------

#: 申报过"两种模式下长得不一样"的页。**加页要连同理由一起加。**
MODE_SENSITIVE_PAGES = {
    "basic": "首页有界面模式下拉本身，外加专家模式才出现的两颗工具入口。",
    "advanced": "「内部调试」卡片按 RN-133 收进了专家模式。",
}


def _baseline_module():
    spec = importlib.util.spec_from_file_location(
        "_rb_for_ui_mode", SCRIPTS / "renovation_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def _both_modes():
    sys.path.insert(0, str(SCRIPTS))
    rb = _baseline_module()
    normal = rb._structure_via_subprocess(["all"], expert=False)
    expert = rb._structure_via_subprocess(["all"], expert=True)
    assert normal and expert, "两种模式都得取到东西，否则下面两条判据全是空转"
    return normal, expert


def _pages_that_differ(normal, expert):
    sys.path.insert(0, str(SCRIPTS))
    from _page_structure import diff

    out = {}
    for pid in sorted(set(normal) & set(expert)):
        d = diff(normal[pid], expert[pid])
        if d:
            out[pid] = d
    return out


def test_only_declared_pages_look_different_in_expert_mode(_both_modes):
    """③ 两种模式下只有申报过的页长得不一样。"""
    normal, expert = _both_modes
    differ = _pages_that_differ(normal, expert)
    undeclared = {p: len(d) for p, d in differ.items()
                  if p not in MODE_SENSITIVE_PAGES}
    assert not undeclared, (
        f"这些页在两种界面模式下长得不一样，却没申报：{undeclared}\n"
        "基线只锁了普通模式那一份 —— 没申报就意味着这一页的专家视图**没有任何人看着**。\n"
        "要么去掉这一页的模式门控，要么写进 MODE_SENSITIVE_PAGES 并给它专门的判据。")


def test_the_probe_can_actually_tell_the_two_modes_apart(_both_modes):
    """④ ③ 的反面守卫。

    ③ 是一条"没有坏消息就算过"的判据 —— 这种判据最容易的死法是**恒绿**：
    子进程悄悄两趟都跑成同一个模式，差异集永远是空，它照样通过。
    所以这里正面钉住：申报过的那两页**必须真的看得出差别**。
    """
    normal, expert = _both_modes
    differ = _pages_that_differ(normal, expert)
    blind = sorted(set(MODE_SENSITIVE_PAGES) - set(differ))
    assert not blind, (
        f"这些页申报了随模式变，探针却看不出差别：{blind}\n"
        "要么模式门控没了（那就把它从 MODE_SENSITIVE_PAGES 删掉），"
        "要么两趟取样其实跑成了同一个模式 —— 后者会让上一条判据恒绿。")
