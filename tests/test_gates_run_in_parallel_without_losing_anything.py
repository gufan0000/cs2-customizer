# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""并行化的门禁**不许因为并行而少测一条**（批 47）。

## 背景

批 43~46 实测：一批的 Bash 墙钟 9.98 h 里 **8.03 h 是前台 `sleep`** —— 等全量测试
（12~13 分钟 × 每批 1~5 次）、等回退验证（30~36 分钟）、等 CI（14~20 分钟）。
⇒ 批 47 把两台门禁改成并行。**并行不许换来任何一条少测的判据**，这个文件就是那道保险。

## 这里守的三件事

1. **分片是一个划分**：每片互不重叠、并起来等于全集。
   ⭐ 切错了不会报错，只会**静默少验几条断点**——而报告上看起来一切正常。
2. **每个工作槽位有自己的 TEMP 根**。`tests/conftest.py` 把配置目录、日志目录、
   游戏沙箱钉在 `gettempdir()` 下的**固定名**上（RN-141 / RN-473，为的是可复现），
   几个 pytest 进程同时跑必然互相覆盖。
3. **驱动不许给子进程 `timeout`**（RN-093）：到点是「在任意中间态被砍断」，
   而回退验证跑着的时候产品文件正被改坏着。
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "build_tools" / "run_tests.py"
REVERT = REPO / "scripts" / "revert_verify.py"
DRIVER = REPO / "scripts" / "revert_verify_parallel.py"


def _load_revert_module():
    spec = importlib.util.spec_from_file_location("_rv_for_test", REVERT)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


# ---------------------------------------------------------------- 1. 划分


@pytest.mark.parametrize("n", [2, 3, 4, 6, 8])
def test_sharding_is_a_partition_of_every_breakpoint(n):
    """分片必须**互不重叠、并起来等于全集** —— 切错了只会静默少验。

    分母：`revert_verify.REVERTS` 全部断点，不是某个名单。

    ⚠⚠ **这条判据的第一版是假绿的，而且是破坏验证当场逮出来的**（批 47）：
    第一版在测试里自己写 `items[i-1::n]` 再断言它是个划分 —— 那等于断言
    「我在测试里写的这行是对的」，**恒真**；把产品代码那一行改坏成
    `items[: len//n]`（每片都跑前几条）之后，判据 **5 passed 纹丝不动**。
    ⭐⭐⭐ **一条判据如果把被测的逻辑在测试里重写一遍，它测的就是自己的那一份。**
    ⇒ 现在调的是产品代码里的 `shard_items()`，改坏它这条必红。
    """
    mod = _load_revert_module()
    items = mod.REVERTS
    assert items, "REVERTS 是空的 —— 这条判据的分母没了"

    shards = [mod.shard_items(items, i, n) for i in range(1, n + 1)]
    seen = [{id(r) for r in s} for s in shards]

    union = set().union(*seen)
    assert union == {id(r) for r in items}, (
        f"分成 {n} 片之后，{len(items) - len(union)} 条断点**一片都没分到** —— "
        "它们会被静默跳过，而汇总行照样打得出来。")

    for a in range(n):
        for b in range(a + 1, n):
            dup = seen[a] & seen[b]
            assert not dup, (
                f"第 {a+1} 片与第 {b+1} 片重叠 {len(dup)} 条：同一条断点被验两遍，"
                "而别处必然少验 —— 总数却仍然对得上。")


def test_the_shard_flag_slices_before_the_expensive_checks():
    """`--shard` 必须切在**失效体检之前**，否则每片都要把 collect 重跑一遍。

    481 条判据各 `--collect-only` 一次要 7 分钟；切在后面的话 6 片就是 42 分钟，
    并行等于白并。
    """
    src = REVERT.read_text(encoding="utf-8")
    cut = src.index("items = shard_items(items, shard_i, shard_n)")
    health = src.index('print("失效体检：锚点还在不在、判据名还在不在")')
    assert cut < health, (
        "`--shard` 的切片跑到失效体检后面去了 —— 每一片都会重跑一遍全量 collect。")


# ---------------------------------------------------- 2. 每个槽位一个 TEMP


CONFTEST = REPO / "tests" / "conftest.py"


@pytest.mark.parametrize("path,what", [
    (RUNNER, "全量测试驱动"),
    (DRIVER, "回退验证并行驱动"),
])
def test_each_parallel_worker_gets_its_own_config_and_log_dir(path, what):
    """并行的每一路都必须带上 `CS2C_TEST_WORKER`。

    ⚠ 这条不是「配置洁癖」：`conftest.py` 把 `cs2customizer_test_config` 与
    `cs2customizer_test_logs` 钉在 `gettempdir()` 下的固定名上（RN-141 要的可复现）。
    不隔离就是几个进程同时读写同一份 `config.json`，而症状会是**别的判据随机红**，
    根本不指向这里。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if not isinstance(tgt, ast.Subscript):
                    continue
                key = tgt.slice
                # env["CS2C_TEST_WORKER"] = ... 或 env[WORKER_ENV] = ...
                if (isinstance(key, ast.Constant) and key.value == "CS2C_TEST_WORKER") \
                        or (isinstance(key, ast.Name) and key.id == "WORKER_ENV"):
                    ok = True
    assert ok, (
        f"{what}（{path.name}）没有给每一路传 `CS2C_TEST_WORKER`，"
        "几路会共用 conftest 那两个固定目录。")


def test_the_game_sandbox_path_is_never_per_worker():
    """⛔ 游戏沙箱那条路径**不许**跟着工作槽位变。

    ⚠⚠ 这条是批 47 拿一次等价验收红换来的：我第一版图省事，直接给每一路换掉
    `TEMP/TMP/TMPDIR`（`gettempdir()` 一变，conftest 那三个目录**一起搬家**）。
    结果 `advanced` 页的结构指纹当场对不上 —— 因为那条沙箱路径
    **被高级设置页原样显示在屏幕上**（「当前使用的 CS2 目录：…」），指纹钉着它。
    ⭐⭐ **换隔离手段之前，先问这个路径会不会被人看见。**
    看得见的路径是产品的一部分，不是环境细节。

    ⇒ 隔离只加在配置目录和日志目录上，沙箱几路共用。
    """
    src = CONFTEST.read_text(encoding="utf-8")
    tree = ast.parse(src)
    suffixed = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        if name not in ("_cs2customizer_test_cfg_dir", "_cs2customizer_test_log_dir",
                        "_cs2customizer_game_sandbox"):
            continue
        seg = ast.get_source_segment(src, node.value) or ""
        suffixed[name] = "_cs2customizer_worker" in seg

    assert set(suffixed) == {"_cs2customizer_test_cfg_dir", "_cs2customizer_test_log_dir",
                             "_cs2customizer_game_sandbox"}, (
        f"conftest 里这三个目录变量对不上了，认出来的是 {sorted(suffixed)} —— "
        "改了名字就等于把这条判据的分母抽掉了。")
    assert suffixed["_cs2customizer_test_cfg_dir"], "配置目录没加工作槽位后缀，并行会互相覆盖"
    assert suffixed["_cs2customizer_test_log_dir"], "日志目录没加工作槽位后缀，并行会互相覆盖"
    assert not suffixed["_cs2customizer_game_sandbox"], (
        "游戏沙箱加上了工作槽位后缀 —— 那条路径显示在 `advanced` 页上，"
        "一变结构指纹立刻对不上（批 47 实测）。它必须几路共用。")


def test_no_parallel_driver_moves_the_whole_temp_root(request):
    """两个驱动都不许再去换 `TEMP/TMP/TMPDIR` —— 那会连沙箱一起搬走。

    上一条守的是 conftest 那一端；这一条守的是驱动那一端。
    两端都要守：只守一端的话，另一端换个写法就能绕过去。
    """
    for path in (RUNNER, DRIVER):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value in ("TEMP", "TMP", "TMPDIR")):
                    pytest.fail(
                        f"{path.name} 在改 {tgt.slice.value} —— `gettempdir()` 一变，"
                        "conftest 的游戏沙箱会跟着搬家，而那条路径显示在 `advanced` 页上。"
                        "隔离请只用 `CS2C_TEST_WORKER`。")


def test_serial_mode_stays_byte_for_byte_the_old_behaviour():
    """`--jobs 1` 必须**不换 TEMP、不起线程池** —— 它是出问题时的退路。

    退路要是也跟着变了，就没有可对照的基准了。
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert "if jobs == 1:" in src, "`--jobs 1` 没有单独的串行分支"
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_worker_env")
    # slot is None ⇒ return None（原样继承环境）
    first = fn.body[1] if len(fn.body) > 1 else fn.body[0]
    assert isinstance(first, ast.If) and any(
        isinstance(s, ast.Return) and isinstance(s.value, ast.Constant)
        and s.value.value is None for s in first.body), (
        "`_worker_env(None)` 不再返回 None —— 串行档也被换了 TEMP，"
        "那它就不是「和以前一样」的退路了。")


# ------------------------------------------ 3. 拿墙钟当判据的不许被并行挤

CLOCK = re.compile(r"\b(perf_counter|monotonic|time\.time)\s*\(|\b\w*_ms\s*\(")


def _wall_clock_test_files() -> dict[str, list[str]]:
    """扫出所有「自己测了一段时间、又拿它去比阈值」的测试文件。

    ⭐ **分母是扫出来的，不是我记得的那几个** —— 谁新写一条这样的断言，
    谁自动进这个分母（同 RN-483 / RN-511 那两次的教训：按名单划分母，
    第一个不在名单上的违规者天生在守卫看不见的地方）。

    只认「函数里有时钟调用 **且** 有 `<` / `<=` 断言」的；
    只断言常量的（`cfg.duck_release_ms == 120`）不算 —— 那不受 CPU 争用影响。
    """
    out: dict[str, list[str]] = {}
    for p in sorted((REPO / "tests").glob("test_*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")):
                continue
            if not CLOCK.search(ast.get_source_segment(src, fn) or ""):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)
                        and any(isinstance(o, (ast.Lt, ast.LtE)) for o in node.test.ops)):
                    out.setdefault(p.name, []).append(fn.name)
                    break
    return out


#: ⚠ RN-525：**不是只有时钟阈值判据怕挤。**
#: 拿多份**子进程 UI 快照**互相比的判据同样怕：子进程要和别的 pytest 抢 CPU，
#: 快照就可能停在不同的时刻。这个记号是精确的闭集（实测 2 个文件）。
SUBPROCESS_SNAPSHOT_MARK = "_structure_via_subprocess"


def _subprocess_snapshot_files() -> set[str]:
    """真的**调用**了它的文件，不是「提到了这个名字」的文件。

    ⚠ 第一版用子串匹配，于是**这个判据文件自己**（源码里写着那个记号）
    也进了分母，当场自指报红。⭐ 一条按记号划分母的判据，最先撞上的
    往往是**写着那个记号的判据自己**。⇒ 走 AST 认调用。
    """
    out = set()
    for path in (REPO / "tests").glob("test_*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and (getattr(node.func, "attr", None) == SUBPROCESS_SNAPSHOT_MARK
                         or getattr(node.func, "id", None) == SUBPROCESS_SNAPSHOT_MARK)):
                out.add(path.name)
                break
    return out


def test_every_subprocess_snapshot_judge_runs_alone():
    """⭐ 拿子进程快照互相比的判据，也必须独占这台机器。

    ⚠ 这条是批 50 由**并行全量偶发红**逼出来的：`test_ui_mode_sampling` 串行
    248/248 绿、单跑连过两次，并行全量里 `hud_color` 同模式复跑差 2 处。
    ⭐⭐ RN-518 那条判据一声没响 —— 它的分母是「函数里有时钟调用 + `<` 断言」，
    而这一类**不带那个记号**。（同 RN-483/511/521/522：按记号划分母，
    不带那个记号的天生看不见。）
    """
    src = (REPO / "build_tools" / "run_tests.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    listed = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "SERIAL_TAIL"):
            listed = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    assert listed is not None, "`run_tests.py` 里找不到 `SERIAL_TAIL`"

    found = _subprocess_snapshot_files()
    assert found, (
        f"一个用 `{SUBPROCESS_SNAPSHOT_MARK}` 的文件都没扫到 —— "
        "多半是识别器瞎了，而不是真的没有（历史上有 2 个）。")
    missing = sorted(found - listed)
    assert not missing, (
        "这些判据拿子进程快照互相比，却没进 `SERIAL_TAIL`：\n  "
        + "\n  ".join(missing)
        + "\n⇒ 并行时它们的子进程会和别的 pytest 抢 CPU，"
          "快照可能停在不同的时刻（批 50 实测：并行全量偶发红、串行全量全绿）。")


def test_every_wall_clock_judge_runs_alone():
    """⭐⭐⭐ 拿墙钟当判据的文件必须进 `SERIAL_TAIL`，否则并行会把它压红。

    ⚠⚠ 这条是批 47 首推之后 **CI 当场红**换来的：
    `test_search_stays_within_frame_budget` 报「最慢的查询要 **14.2ms**」（上限 12ms）——
    **代码一个字没改**，变的是它旁边还跑着另一个 pytest 进程，而 CI 的 runner 只有 2 核。
    ⭐⭐ 本机 16 核跑 6 路**没争出来**，等价验收全绿 ——
        「在我的机器上测不出来」不是「不存在」，是「我的机器不够挤」。
    ⛔ 修法不许是「把上限抬高」：那是拿判据的灵敏度换我的速度。
    """
    src = (REPO / "build_tools" / "run_tests.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    listed = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "SERIAL_TAIL"):
            listed = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    assert listed is not None, "`run_tests.py` 里找不到 `SERIAL_TAIL` —— 这条判据没了分母"

    found = _wall_clock_test_files()
    assert found, ("一个拿墙钟比阈值的判据都没扫到 —— 多半是识别器瞎了，"
                   "而不是真的一个都没有（历史上至少有 4 个）。")

    missing = {f: fns for f, fns in found.items() if f not in listed}
    assert not missing, (
        "这些文件拿墙钟去比阈值，却没进 `run_tests.py` 的 `SERIAL_TAIL`：\n  "
        + "\n  ".join(f"{f} ← {', '.join(fns)}" for f, fns in sorted(missing.items()))
        + "\n⇒ 并行跑的时候它们会和别的 pytest 进程抢 CPU，量出来的数说明不了代码好坏。"
          "\n（批 47 实测：CI 2 核上 12ms 的预算量成 14.2ms，红得毫无道理。）")

    stale = sorted(f for f in listed if not (REPO / "tests" / f).exists())
    assert not stale, (
        f"`SERIAL_TAIL` 里这些文件已经不存在了：{stale} —— "
        "点名清单会在被点名者消失时安静缩短，而不是变红。")


def test_the_serial_tail_really_runs_after_the_pool_drains():
    """串行尾巴必须跑在**池子排空之后** —— 它得独占这台机器，否则等于没排。

    ⚠⚠ 这条的第一版是**假绿**的（批 47 当场逮到）：它比的是
    `src.index("for tf in tail:") > src.index("futures.as_completed")`，
    也就是**文本先后**。而把尾巴整段挪进 `with` 块里之后，那行文本**仍然靠后**
    —— 破坏验证 1 passed 纹丝不动。
    ⭐⭐ **「在它后面」和「在它外面」是两件事，而文本位置只看得见前者。**
    ⇒ 改成走 AST 看**块结构**：那个 `for` 不许是 `with ThreadPoolExecutor` 的后代。
    """
    src = (REPO / "build_tools" / "run_tests.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    pools = [n for n in ast.walk(tree)
             if isinstance(n, ast.With)
             and "ThreadPoolExecutor" in (ast.get_source_segment(src, n.items[0].context_expr) or "")]
    assert len(pools) == 1, f"认出 {len(pools)} 个线程池 with 块（要求恰好 1 个）"

    def tail_loops(node):
        return [n for n in ast.walk(node)
                if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                and isinstance(n.iter, ast.Name) and n.iter.id == "tail"]

    all_loops = tail_loops(tree)
    assert all_loops, "找不到跑串行尾巴的那个 `for ... in tail` —— 这条判据没了对象"

    inside = tail_loops(pools[0])
    assert not inside, (
        "串行尾巴跑在线程池的 `with` 块**里面** —— 那会儿别的 pytest 进程还在跑，"
        "而这些文件量的正是墙钟。（批 47：CI 2 核上 12ms 的预算被挤成 14.2ms。）")


# ------------------------------------------------------- 4. 不许 timeout


def test_the_parallel_driver_never_puts_a_timeout_on_a_shard():
    """RN-093：回退验证跑着时产品文件是被改坏的，`timeout` 到点等于**在中间态砍断**。

    驱动自己也不许给子进程加 —— 加了就是把那条老教训在新入口上重犯一遍。
    """
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"):
            names = {kw.arg for kw in node.keywords}
            # 只管跑分片那一发：它的 cwd 是副本树
            if "env" in names:
                assert "timeout" not in names, (
                    "并行驱动给分片子进程加了 `timeout`（RN-093）：到点是"
                    "「在任意中间态被砍断」，而那一刻产品文件正被改坏着。")


def test_a_shard_without_a_summary_line_is_a_failure():
    """⭐ 少一片汇总行 = 失败（同 RN-511）。

    一片跑到一半被杀，它打过的 ✅ 全都还在日志里，看着像「跑过了」；
    只有「汇总行在不在」能区分「跑完了」和「死在中途」。
    """
    src = DRIVER.read_text(encoding="utf-8")
    assert 'caught"] is None' in src or "caught'] is None" in src, (
        "驱动不再检查「这一片有没有汇总行」")
    assert "没有汇总行" in src and "按失败处理" in src, (
        "少一片汇总行现在不按失败处理了 —— 那就洗得成假绿了")

    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    src_main = ast.get_source_segment(src, main) or ""
    assert "if (missing or all_missed) else 0" in src_main.replace("\n", " "), (
        "裁定不再把 `missing`（缺汇总行的片）算进红里")
