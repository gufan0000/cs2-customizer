# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""回退验证的并行驱动（批 47）。

`revert_verify.py` 一条断点要「改坏产品文件 → 跑判据 → 还原」，481 条串行要 36 分钟，
而**一批里它要跑好几次**。这支驱动把断点分成 N 片并行跑。

⭐⭐ **它并行的办法不是「几个进程同时改同一棵树」——那必然互相踩。**
每一片跑在自己的 **git worktree 副本**上：

  · `revert_verify.py` 的 `ROOT` 是 `Path(__file__).resolve().parent.parent` 推导的，
    所以副本里的那一份天然把 `ROOT` 指向副本根，改坏/还原/快照目录全落在副本里。
  · ⇒ **主工作树一个字节都不会被动**。这也顺带解决了 RN-093 那条
    「它跑着的时候不许并行跑测试」——那条针对的是主树不可信，而现在主树没被碰。
    ⚠ 但 `CLAUDE.md` 的口径先按保守写，等跑过几批确认副本不漏东西再放宽。

⚠ **不给子进程 `timeout`**（RN-093）：到点是「在任意中间态被砍断」，不是「停下」。

裁定：**少一片汇总行 = 失败**（同 RN-511：没走到判定就死的，一行裁定都没有 ⇒ 按失败算）。

用法：
    python scripts/revert_verify_parallel.py                 # 全量 481 条
    python scripts/revert_verify_parallel.py --only RN       # 只跑 RN 组
    python scripts/revert_verify_parallel.py --jobs 4
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent import futures
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_verdict import announce  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(tempfile.gettempdir()) / "cs2customizer_rv_shards"

#: 汇总行：`回退验证：343/343 条判据成功逮住它要防的缺陷`
SUMMARY_RE = re.compile(r"^回退验证：(\d+)/(\d+) 条判据")
#: 基线不绿时它根本不打汇总行，而是打这个 —— 要单独认出来，否则会误报成「片死了」
BASELINE_BAD = "❌ 基线就不绿"
STALE_RE = re.compile(r"^⚠ (\d+)/(\d+) 条断点已失效")
MISSED_RE = re.compile(r"^\[\d+/\d+\] ❌ (.+)$")


def _default_jobs() -> int:
    return min(6, max(1, (os.cpu_count() or 2) // 2))


def _dirty_files() -> list[str]:
    """工作树里相对 HEAD 有差别的文件（含未跟踪、不含被忽略的）。"""
    out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"],
                         cwd=str(ROOT), capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    files = []
    for rec in out.split("\0"):
        if len(rec) > 3:
            files.append(rec[3:])
    return files


def make_worktree(dst: Path) -> None:
    """建一份等于**当前工作树**（不是 HEAD）的副本。

    ⭐ 必须等于当前工作树，不是 HEAD —— 这正是 RN-510 那条教训：
    `git archive HEAD` 读的是已提交树，于是门禁量的是**上一个版本**。
    回退验证要验的是我**现在**改出来的东西。
    """
    # ⚠ 别加 `--no-checkout`：那样索引是空的，随后 `git checkout .` 会报
    # 「pathspec '.' did not match any file(s)」—— 批 47 第一版就是这么挂的。
    # 让 `worktree add` 正常检出 HEAD（43 MB，几秒），再把工作树的改动覆盖上去。
    subprocess.run(["git", "worktree", "add", "--detach", str(dst), "HEAD"],
                   cwd=str(ROOT), check=True, capture_output=True)
    for rel in _dirty_files():
        src, dest = ROOT / rel, dst / rel
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        elif dest.exists():
            dest.unlink()


#: ⭐⭐⭐ 批 47 实测：**一份「只是把仓库复制过去」的副本，不是一个等价的环境。**
#: 有 12 条判据读的是**仓库外的兄弟目录** `CS2 Customizer_翻新工程/`（登记册 / 页面清单 /
#: 档案 / 总纲）。副本建在临时目录里，那个兄弟目录不在 ⇒ 它们
#: `pytest.skip("同级目录里没有翻新工程")` —— 而 **skip 读作绿**：
#: 基线绿、改坏之后还绿 ⇒ 12 条断点全被报成「没逮住」。
#: ⭐ 逮到它的是回退验证本身（断点报了红），**不是那 12 条判据** ——
#:   它们在副本里从头到尾一声没吭。
#: ⇒ 副本的父目录里要放一份这个目录，6 片共用、只读。
SIBLING_DIRS = ("CS2 Customizer_翻新工程",)


def stage_siblings(base: Path) -> list[str]:
    """把判据要读的**仓库外兄弟目录**复制到副本的父目录里。

    返回实际放进去的目录名，供调用方核对（一个都没放进去多半是路径变了）。
    """
    staged = []
    for name in SIBLING_DIRS:
        src = ROOT.parent / name
        if not src.is_dir():
            continue
        shutil.copytree(src, base / name, dirs_exist_ok=True)
        staged.append(name)
    return staged


def drop_worktree(dst: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(dst)],
                   cwd=str(ROOT), capture_output=True)
    shutil.rmtree(dst, ignore_errors=True)


def run_shard(i: int, n: int, only: str, tree: Path) -> dict:
    """跑第 i 片，返回解析结果。**不给 timeout**（RN-093）。"""
    log = LOG_DIR / f"shard_{i}.txt"
    cmd = [sys.executable, "scripts/revert_verify.py", "--shard", f"{i}/{n}"]
    if only:
        cmd += ["--only", only]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # 每片一个配置/日志目录后缀，理由同 `run_tests.py`：conftest 把它们钉在
    # `gettempdir()` 下的固定名上，几片同时跑会互相覆盖。
    # ⛔ 只加后缀、**不换 TEMP** —— 游戏沙箱那条路径显示在 `advanced` 页上，
    #    指纹钉着它（批 47 第一版换 TEMP，等价验收当场红）。
    env["CS2C_TEST_WORKER"] = f"_rv{i}"

    r = subprocess.run(cmd, cwd=str(tree), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    log.write_text(text, encoding="utf-8")

    caught = total = None
    stale = 0
    missed, baseline_bad = [], False
    for ln in text.splitlines():
        m = SUMMARY_RE.match(ln)
        if m:
            caught, total = int(m.group(1)), int(m.group(2))
        s = STALE_RE.match(ln)
        if s:
            stale = int(s.group(1))
        mi = MISSED_RE.match(ln)
        if mi:
            missed.append(mi.group(1))
        if BASELINE_BAD in ln:
            baseline_bad = True
    return dict(i=i, rc=r.returncode, caught=caught, total=total, stale=stale,
                missed=missed, baseline_bad=baseline_bad, log=str(log))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=_default_jobs())
    ap.add_argument("--only", default="", help="原样转交给 revert_verify.py")
    ap.add_argument("--keep-trees", action="store_true", help="跑完不删副本（查问题用）")
    args = ap.parse_args()
    n = max(1, args.jobs)

    shutil.rmtree(LOG_DIR, ignore_errors=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.gettempdir()) / "cs2customizer_rv_trees"
    shutil.rmtree(base, ignore_errors=True)

    t0 = time.time()
    trees = [base / f"t{i}" for i in range(1, n + 1)]
    print(f"建 {n} 份工作树副本…", flush=True)
    for t in trees:
        make_worktree(t)
    staged = stage_siblings(base)
    missing = [s for s in SIBLING_DIRS if s not in staged]
    if missing:
        # 不静默继续：少一个兄弟目录 = 那一族判据在副本里全程 skip，而 skip 读作绿。
        print(f"❌ 副本旁边缺这些判据要读的目录：{missing}（在 {ROOT.parent} 下没找到）")
        for t in trees:
            drop_worktree(t)
        announce("revert_verify", 1)
        return 1
    print(f"   已把 {staged} 放到副本旁边（那 12 条账本判据要读它）", flush=True)

    results = []
    try:
        with futures.ThreadPoolExecutor(max_workers=n) as pool:
            futs = {pool.submit(run_shard, i, n, args.only, trees[i - 1]): i
                    for i in range(1, n + 1)}
            for fut in futures.as_completed(futs):
                res = fut.result()
                results.append(res)
                if res["caught"] is None:
                    why = "基线就不绿" if res["baseline_bad"] else "没有汇总行"
                    print(f"  第 {res['i']}/{n} 片 ❌ {why}（rc={res['rc']}）"
                          f" 日志：{res['log']}", flush=True)
                else:
                    print(f"  第 {res['i']}/{n} 片 ✅ {res['caught']}/{res['total']}"
                          f"{'，失效 %d' % res['stale'] if res['stale'] else ''}",
                          flush=True)
    finally:
        if not args.keep_trees:
            for t in trees:
                drop_worktree(t)

    # ---- 裁定 ----
    # ⭐ **少一片汇总行 = 失败。** 同 RN-511：一片跑到一半被杀，它打过的 ✅ 都还在
    # 日志里，看起来「跑过了」；只有「汇总行在不在」能区分「跑完了」和「死在中途」。
    print("\n" + "=" * 78)
    missing = [r["i"] for r in results if r["caught"] is None]
    caught = sum(r["caught"] or 0 for r in results)
    total = sum(r["total"] or 0 for r in results)
    stale = sum(r["stale"] for r in results)
    all_missed = [m for r in results for m in r["missed"]]
    print(f"回退验证（{n} 片并行）：{caught}/{total} 条判据成功逮住它要防的缺陷"
          f"，耗时 {time.time() - t0:.0f}s")
    if stale:
        print(f"⚠ 失效断点合计 {stale} 条（各片日志里有名单）")
    for m in all_missed:
        print(f"❌ 没逮住：{m}")
    for i in missing:
        print(f"❌ 第 {i}/{n} 片没有汇总行 —— 它没跑完，结论未知，按失败处理")

    rc = 1 if (missing or all_missed) else 0
    announce("revert_verify", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
