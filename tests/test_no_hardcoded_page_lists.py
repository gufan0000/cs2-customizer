# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-002：「构造即占设备的页面」这份名单，全仓只许有一份。

**这类缺陷的特征是「抄的时候是对的」**——三份副本刚抄完时逐字相同，
判据全绿，谁也看不出问题。它要等到**产品那份变了**才发作，而那时
没有任何东西会提醒你还有三份没跟着变。

2026-08-16 的 CI 连红就是这么来的：一条侧栏判据自己抄了名单
（实为把 28 页全构造了一遍），runner 上 `music` 那项断言失败；
本机拿探针复现时**直接卡死在音乐页**。见 `docs/quality/README.md` 与
`core/page_traits.py` 的注释。

判据只做一件事：**扫源码，找"又抄了一份"**。
真相源是 `core.page_traits.DEVICE_OWNING_PAGES`，它不依赖 Qt，
任何脚本都能零成本导入，没有"抄一份更省事"的借口。

**判定规则**：一个字符串集合/列表/元组，若成员 ≥3 个且**全部**是设备页 ——
那它只可能是这份名单的副本。
· 含设备页也含别的页的放行：如 `icon_provider` 的 28 页图标表、
  `bench_page_build.PAGE_SPECS` 的全页规格表，它们是全集不是副本。
· **字典键整体放行**：审计侧的「中和」表长这样（页 → 要按下的配置开关），
  它们天然只列设备页的一个子集，是策略不是副本。
  代价说明白：字典形状的副本本判据抓不到。实际没有那种写法——名单都是集合。

**首跑战果（2026-08-17）**：摸底以为有 3 份副本，判据一跑抓出 **9 份**，
且其中 **3 份已经漂了**（`page_fingerprint` 与 `r9_visual_evidence` 各少一页、
`tab_order_audit` 只剩三页）。**这类东西不会自己喊疼，只能靠判据扫。**
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from core.page_traits import DEVICE_OWNING_PAGES
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent

#: 豁免清单。**理由必须写**——空理由不算豁免（见 test_exemptions_carry_a_reason）。
#: 这是仓库既有约定（同 `test_tab_scroll_and_button_width_r10.PAGE_LEVEL_SCROLL`）：
#: 豁免本身也会腐烂，写不出理由的豁免多半就是懒。
ALLOWED = {
    "core/page_traits.py": "真相源本身就定义在这里，它当然「全是设备页」。",
    "scripts/r9_visual_evidence.py":
        "R9 的一次性取证脚本，那 5 页是**当时**「页头迁移了但从没拍过」的历史快照。"
        "改成从真相源派生会让它跟着未来的名单变，等于篡改历史证据的口径。冻结不动。",
}

#: 一个集合里凑够这么多设备页、且再无别的页，就判定为副本。
_COPY_THRESHOLD = 3


def _tracked_python_files() -> list[Path]:
    """git 跟踪的 .py **加上"未跟踪但未被 .gitignore 排除"的 .py**。

    ⚠ 不能用 `rglob("*.py")`：`.build/` 下压着十几份历史发布快照，
    里面全是旧代码。2026-08-17 就被它坑过一次——拿 grep 找「某文案改没改」，
    活代码明明已经改了，却被 `.build/` 里的旧副本报成"还没改"。

    ⭐ RN-062：**光看"已跟踪"是个洞，而且时机最要命。**
    2026-08-17 回退验证逮到这条判据假绿：副本被注进**新建的**
    `scripts/_audit_neutralize.py`，判据一声不响 —— 新文件还没 `git add`。
    而"刚抽出来的共享模块"正是最可能引入副本的地方，判据偏偏在那个窗口里瞎。
    加上 `--others --exclude-standard` 就补上了，`.build/` 依旧被
    `.gitignore` 挡在外面，所以上面那条顾虑仍然满足。
    """
    def _ls(*args) -> list[str]:
        out = subprocess.run(["git", "ls-files", *args],
                             cwd=REPO, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(out.stderr[:200])
        return [line for line in out.stdout.splitlines() if line.strip()]

    try:
        files = _ls("*.py") + _ls("--others", "--exclude-standard", "*.py")
        if files:
            return [REPO / line for line in dict.fromkeys(files)]
    except Exception:
        pass
    pytest.skip("拿不到 git 文件清单，跳过（不静默放行：宁可跳过也不假绿）")


def _string_groups(tree: ast.AST):
    """产出源码里每一处「字符串字面量凑成的集合」→ (行号, {字符串})。

    走 AST 不走正则：正则会被注释、docstring 和跨行拼接骗到。
    **字典不看**——理由见模块 docstring 的判定规则。
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            continue
        names = {e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if names:
            yield getattr(node, "lineno", 0), names


def test_device_owning_page_list_has_exactly_one_copy():
    offenders = []
    must_scan(DEVICE_OWNING_PAGES, "DEVICE_OWNING_PAGES（设备页名单）", least=2)
    for path in must_scan(_tracked_python_files(), "git 在管的 *.py", least=100):
        rel = path.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for lineno, names in _string_groups(tree):
            hits = names & DEVICE_OWNING_PAGES
            if len(hits) >= _COPY_THRESHOLD and names <= DEVICE_OWNING_PAGES:
                offenders.append(f"{rel}:{lineno} → {sorted(names)}")

    assert not offenders, (
        "又有人把「构造即占设备的页面」名单抄了一份。\n"
        "这份名单全仓只许有一份，在 core/page_traits.py（不依赖 Qt，随便导）。\n"
        "抄出来的副本不会跟着产品变，等发作时已经是 CI 红或本机卡死。\n"
        "副本出现在：\n  " + "\n  ".join(offenders)
    )


def test_exemptions_carry_a_reason():
    """豁免必须写理由。**空理由不算豁免**。

    没有这一条的话，下一个人被判据拦住时最省事的做法就是把文件名往 ALLOWED 里一塞——
    判据于是变成一张许愿单，红不了也就没用了。
    """
    for path, reason in ALLOWED.items():
        assert reason and reason.strip(), f"{path} 的豁免没写理由"
        assert len(reason.strip()) >= 8, f"{path} 的豁免理由太短，说不清为什么: {reason!r}"


def test_product_reads_the_single_source():
    """产品自己也得读那一份，不能在 `__init__` 里重新写一遍。

    没有这一条的话，把 `gui_widget` 改回硬编码、同时保持脚本引用真相源，
    上面那条判据照样绿 —— 而那正是最坏的情形：**两份都在，还各说各话。**
    """
    src = (REPO / "gui_widget.py").read_text(encoding="utf-8")
    assert "DEVICE_OWNING_PAGES" in src, (
        "gui_widget 没有引用 core.page_traits.DEVICE_OWNING_PAGES —— "
        "产品要么自己抄了一份，要么名单被挪走了没同步这条判据"
    )

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Attribute)]
        if not any(t.attr == "_preload_skip_pages" for t in targets):
            continue
        # 赋的必须是从真相源来的东西，不能是字面量集合
        assert not isinstance(node.value, (ast.Set, ast.List, ast.Tuple)), (
            f"gui_widget.py:{node.lineno} 又把名单写成字面量了；"
            "应当 set(DEVICE_OWNING_PAGES)"
        )


def test_instance_copy_does_not_share_state_with_the_source():
    """产品拿的必须是**拷贝**，不能是真相源本身。

    共享同一个可变对象的话，任何一处 `.add()` 都会改到全局；
    真相源用 frozenset 已经挡了一层，这里再确认产品侧拿到的是可独立演化的副本。
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import gui_widget

    app = QApplication.instance() or QApplication([])
    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        assert win._preload_skip_pages == set(DEVICE_OWNING_PAGES), "内容必须一致"
        assert win._preload_skip_pages is not DEVICE_OWNING_PAGES, "必须是拷贝"
        win._preload_skip_pages.add("__probe__")
        assert "__probe__" not in DEVICE_OWNING_PAGES, "改实例那份不许污染真相源"
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
