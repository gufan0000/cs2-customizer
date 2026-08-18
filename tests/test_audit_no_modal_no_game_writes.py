# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-070~073：离屏工装既不许挂死在模态框上，也不许写用户的游戏目录。

## 这一批是怎么被发现的（不是读代码读出来的）

顺手把 `scripts/` 纳入 lint 时发现它**整个目录被 ruff 排除**（19226 行 / 64 支
脚本零 lint），跟着两条实锤掉出来：

1. `ui_perf_probe.py` 用 `sys.stdout.reconfigure` 但全文没有 `import sys`，
   抛的 NameError 被 `except Exception: pass` 一口吞掉 ⇒ 整块 UTF-8 兜底
   **恒失效**。该脚本打 ✅×5 / ❌×3 / ⚠×1，GBK 控制台上本该必崩（RN-071）。
2. `bench_page_build` 整跑**从来没跑完过**：faulthandler 抓到栈停在
   `advanced_page.py` 的 `QMessageBox.information` —— 页面在**构造期**弹模态框，
   离屏下不可见但照样阻塞（RN-072）。同一段代码还在动用户真实的
   `Steam/.../csgo/cfg/`：GSI cfg、cs2customizer.cfg、autoexec.cfg 三个文件。
   它只在 `config.csgo_dir` 为空时触发，而**隔离配置永远是空的**
   ⇒ 这条在工装里必然踩、在真机上几乎不踩。

## 三条判据的分工

- **配置层**：ruff 不许再整目录排除 `scripts`（否则上面第 1 条那种一秒能查出来
  的东西会继续躺着）。
- **代码层**：四个写 cfg 的函数都要有那道门；产品代码不许自己打开审计闸门。
- **行为层**（最重要）：把 27 页全构造一遍，`blocked_dialogs()` 必须是空的 ——
  **构造期弹框 = 整支离屏脚本挂死**，这条不该靠逐页发现。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

#: UP-091：这两个文件损坏到 `py_compile` 都过不去（基线导入事故，进来时就是坏的），
#: 处置要用户拍板。它们是**唯一**允许被 lint 排除的东西，且只准按文件名排除。
_UP091 = ("scripts/bootstrap_tutorial_content.py",
          "scripts/capture_web_tutorial_screenshots.py")


# ==================================================== 一、配置层（RN-070）

def test_lint_does_not_blindfold_the_whole_scripts_directory():
    """`scripts/` 不许整目录从 lint 里排除。

    ⚠ 这条要防的不是"代码风格不统一"，是**门禁自己有盲区**：
    `scripts/` 里躺着排版审计、焦点巡检、搜索索引生成器、回退验证 ——
    整个工装层。CI 把 `ruff check .` 当 lint 门禁，而它一个字都没看。
    实测代价：一条 F821（`sys` 未定义）在里面躺了很久，而它一秒就能查出来。
    """
    import tomllib

    text = (REPO / "ruff.toml").read_text(encoding="utf-8")
    conf = tomllib.loads(text)
    excluded = list(conf.get("exclude", [])) + list(conf.get("extend-exclude", []))
    assert "scripts" not in excluded, (
        "ruff.toml 又把整个 scripts/ 排除了（RN-070）。"
        f"要排除的话只准按文件名排除那两个已知损坏的：{_UP091}")
    for name in _UP091:
        assert name in text, (
            f"{name} 是 UP-091 的已知损坏文件（py_compile 都过不去），"
            "un-exclude scripts/ 之后必须按文件名单独排除，否则 lint 会被语法错刷屏")


def test_every_script_that_uses_sys_imports_it():
    """RN-071：用了 `sys.X` 就必须 `import sys`。

    这条判的是**兜底把自己的失败也兜掉了**这一类：
    `try: sys.stdout.reconfigure(...) except Exception: pass` ——
    缺 import 时抛的是 NameError，也被同一个 `except` 吃掉，
    于是"我加了 UTF-8 兜底"这句话是假的，而且永远不会有人看见它假。
    """
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.as_posix().endswith(_UP091):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue          # UP-091 那两个，另有处置
        uses = any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                   and n.value.id == "sys" for n in ast.walk(tree))
        if not uses:
            continue
        imported = any(
            (isinstance(n, ast.Import) and any(a.name == "sys" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "sys")
            for n in ast.walk(tree))
        if not imported:
            offenders.append(path.name)
    assert not offenders, f"这些脚本用了 sys 却没 import：{offenders}（RN-071）"


# ==================================================== 二、代码层（RN-072）

def test_the_game_dir_exit_has_exactly_one_mechanism():
    """游戏目录这条出口只准有**一份**实现，就是 `_audit_sandbox`（UP-090）。

    ⚠ 这条是我自己差点犯的错立的案：我一度在 `cfg_utils` 里加了一个
    `game_dir_writes_disabled()` 禁写闸门，并让 `enable_audit_mode()` 打开它。
    那是**第三份**同类机制，而且比既有的差 —— 禁写会让 `csgo_dir` 留空，
    页面于是走「未配置 CS2 目录」分支，文案和布局跟着变，
    **等于把被审计对象改掉了**（`_audit_sandbox` 的注释里早就写明这一点，
    所以它选的是重定向到一个真实存在的空目录，而不是禁写）。
    ⇒ 判据在此，防的是下一次有人（包括我）再造一份。
    """
    banned = "CS2C_NO_GAME_DIR_WRITES"
    hits = []
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith((".build/", ".claude/")) or rel == "tests/" + Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if banned not in text:
            continue
        # ⚠ 走 AST 只认**代码里的字符串常量**，不认注释 ——
        # 第一版是纯文本比对，当场被 `_audit_neutralize.py` 里那条
        # 「我一度想这么干，是错的」的说明性注释判红。
        # 本仓同一个教训第四次出现：**判"有没有被用"永远走 AST，不看文本。**
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        if any(isinstance(n, ast.Constant) and n.value == banned for n in ast.walk(tree)):
            hits.append(rel)
    assert not hits, (
        f"又出现了第二套「禁写游戏目录」机制：{hits}。"
        "游戏目录这条出口只走 scripts/_audit_sandbox.sandbox_external_writes()（UP-090）—— "
        "它刻意选重定向而非禁写，理由是禁写会改变被审计页面的分支")


def test_audit_mode_opens_the_hotkey_gate_and_says_where_game_writes_go():
    """`enable_audit_mode()` 开热键闸门；游戏目录那条要**指路**到既有机制。

    热键闸门刻意不复用 `CS2C_SAFE_MODE_ACTIVE` —— 那个在真实运行里
    也会被打开（原生崩溃后的安全模式），复用等于给用户关掉音板热键。
    """
    text = (REPO / "scripts" / "_audit_neutralize.py").read_text(encoding="utf-8")
    assert "CS2C_NO_GLOBAL_HOTKEYS" in text, "审计闸门少了热键那道（RN-059）"
    assert "_audit_sandbox" in text, (
        "中和表里要写明游戏目录那条出口走 `_audit_sandbox`（UP-090）—— "
        "不写，下一个人（包括我）就会在这里再造一份禁写闸门")
    assert 'os.environ["CS2C_SAFE_MODE_ACTIVE"]' not in text, (
        "别复用安全模式那个变量当审计闸门 —— 它在真实崩溃后也会开")


# ==================================================== 三、行为层（RN-072 / 073）

@pytest.fixture()
def audit_gates(monkeypatch):
    """把中和层都打开，和离屏脚本里的顺序一致。"""
    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    import _audit_neutralize as neu

    neu._BLOCKED.clear()
    neu.block_modal_dialogs()
    yield neu
    # 这一层动的是**类属性**，不还原会漏进同一轮的其它用例（那会把真缺陷藏起来）
    neu.unblock_modal_dialogs()
    neu._BLOCKED.clear()


def test_the_modal_gate_records_instead_of_swallowing(qapp, audit_gates):
    """闸门是**发现通道**，不是消音器：挡下来还要说清是谁想弹。

    如果只是让它返回个默认值就算了，那么"某页构造期弹框"这件事
    会从挂死变成静默通过 —— 缺陷等于被判据自己藏起来了。
    """
    from PySide6.QtWidgets import QMessageBox

    ret = QMessageBox.information(None, "t", "t")
    assert ret == QMessageBox.StandardButton.Ok
    assert audit_gates.blocked_dialogs() == ["QMessageBox.information"], (
        "模态框被挡下了却没记账 —— 那就查不出是哪一页弹的")
    # 问答框必须返回"否"：工装绝不能替用户按下"确定"
    assert QMessageBox.question(None, "t", "t") == QMessageBox.StandardButton.No


@pytest.fixture()
def game_dir_sandbox():
    """走既有机制（UP-090）把游戏目录出口沙箱化，收尾还原。

    ⚠ 收尾**必须**还原配置落盘：`sandbox_external_writes()` 把 config 的三个
    落盘入口换成 no-op，在脚本里无所谓（跑完就退），在 pytest 里它会活到会话
    结束，于是**后面别的文件**里验存盘的用例莫名变红（QA-025）。
    """
    import _audit_sandbox as sbx

    sbx._SANDBOX_DIR = None            # 同一进程里可能已被别的用例调过
    sandbox = sbx.sandbox_external_writes(verbose=False)
    yield sandbox
    sbx.restore_config_persistence()
    sbx._SANDBOX_DIR = None


def test_advanced_page_builds_without_a_dialog_or_a_real_game_dir_write(
        qapp, audit_gates, game_dir_sandbox, monkeypatch):
    """RN-072 的行为判据：`advanced` 页构造完，既没弹框也没碰**真实**游戏目录。

    走的是 UP-090 那套沙箱（把 `csgo_dir` 指到一个真实存在的空目录），
    **不是**禁写 —— 禁写会让页面走「未配置」分支，等于把被审计对象改掉了。
    """
    import cfg_utils
    import config as config_mod

    assert str(config_mod.config.csgo_dir) == str(game_dir_sandbox), (
        "沙箱没生效：csgo_dir 不是沙箱目录，这条判据量的不是想量的东西")

    wrote = []
    monkeypatch.setattr(cfg_utils, "ensure_all_cfg", lambda d: wrote.append(str(d)))
    from pages.advanced_page import AdvancedPage

    page = AdvancedPage()
    try:
        outside = [d for d in wrote if str(game_dir_sandbox) not in d]
        assert not outside, f"构造 advanced 页往沙箱之外写了：{outside}（RN-072）"
        assert not audit_gates.blocked_dialogs(), (
            f"构造 advanced 页弹了模态框：{audit_gates.blocked_dialogs()} —— "
            "离屏下这个框不可见但照样阻塞，整支脚本会挂死在这里")
    finally:
        page.deleteLater()


def test_without_the_sandbox_the_first_run_flow_really_fires(qapp, monkeypatch):
    """空转守卫的另一半：不沙箱化时那条首次运行流程**必须**真的跑起来。

    没有这一条，上面那条判据可能只是因为"这台机器没装 CS2"而恒绿 ——
    而它恰恰是那次挂死 + 写真实游戏目录的成因，必须能被复现出来。
    """
    import cfg_utils
    import config as config_mod

    monkeypatch.setattr(config_mod.config, "csgo_dir", "", raising=False)
    if not cfg_utils.find_cfg_path():
        pytest.skip("这台机器上找不到 CS2 安装目录，本条守卫无从生效")

    calls = []
    import pages.advanced_page as adv

    monkeypatch.setattr(config_mod.config, "save_config", lambda *a, **kw: None)
    monkeypatch.setattr(cfg_utils, "ensure_all_cfg", lambda d: calls.append(str(d)))
    monkeypatch.setattr(adv.QMessageBox, "information",
                        staticmethod(lambda *a, **kw: calls.append("dialog")))
    page = adv.AdvancedPage()
    try:
        assert "dialog" in calls, (
            f"不沙箱化时也没弹框（calls={calls}）—— 那么上面那条判据是恒绿的，等于没量。"
            "而实测里正是这个框让离屏脚本挂死（faulthandler 抓到栈在 advanced_page 的 "
            "QMessageBox.information）")
    finally:
        page.deleteLater()


@pytest.fixture()
def bench_module(monkeypatch, tmp_path):
    """安全地 import `bench_page_build`。

    ⚠ 它在模块级会调 `use_pristine_config_dir()`，**当场改写
    `CS2C_CONFIG_DIR` / `CS2C_LOG_DIR`** —— 在 pytest 进程里直接 import
    等于把这一轮后面所有用例的配置目录挪走（RN-031/032 那个坑的第四次露头）。
    所以先用 monkeypatch 占住这两个键，teardown 时连脚本的改动一起还原。
    """
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "log"))
    import bench_page_build as bench

    return bench


def test_no_registered_page_pops_a_dialog_while_being_built(qapp, audit_gates,
                                                            bench_module):
    """RN-073 的行为判据：把**全表**页面构造一遍，一个模态框都不许有。

    这条替代不了"整跑一次 bench"，但它把那次挂死的成因锁住了：
    只要有任何一页在构造期弹框，离屏脚本就会挂死在那一页，
    而在此之前**建页耗时基线从来没跑完过全表**（历史产物只有 18 页）。

    覆盖面就是 `bench_page_build.PAGE_SPECS`（`basic` 内联在主窗里，没有独立类）。
    """
    import importlib

    import config as config_mod

    bench = bench_module
    bench.neutralize_apply(config_mod.config, {pid for pid, _, _ in bench.PAGE_SPECS})
    assert len(bench.PAGE_SPECS) >= 26, "空转守卫：清单缩水了，这条判据没在量全表"

    built, failed = [], []
    for page_id, module_path, class_name in bench.PAGE_SPECS:
        before = len(audit_gates.blocked_dialogs())
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
            page = cls(*bench._CTOR_ARGS.get(page_id, tuple)())
        except Exception as exc:            # 构造失败另有判据管，这里只管弹框
            failed.append(f"{page_id}: {type(exc).__name__}")
            continue
        if len(audit_gates.blocked_dialogs()) > before:
            built.append(f"{page_id} → {audit_gates.blocked_dialogs()[before:]}")
        page.deleteLater()
        page.setParent(None)

    assert not built, (
        f"这些页在**构造期**弹模态框：{built}（RN-072 / RN-073）。"
        "离屏下框不可见但照样阻塞 —— 一页弹框 = 整支离屏脚本挂死")
    assert not failed, f"这些页构造直接失败：{failed}"


def test_bench_reports_blocked_dialogs_instead_of_hiding_them(bench_module):
    """挡下来的框要出现在 bench 的输出里，否则这层闸门就成了消音器。"""
    text = bench_module.render(
        {"x": {"中位ms": 1.0, "最小ms": 1.0, "最大ms": 1.0, "样本数": 1,
               "构造期模态框": ["QMessageBox.information"]}})
    assert "构造期弹了模态框" in text and "QMessageBox.information" in text, (
        "bench 把构造期弹框吃掉了 —— 闸门必须同时是发现通道（RN-072）")
