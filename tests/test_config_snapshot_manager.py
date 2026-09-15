# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path

from core import config_snapshot_manager as snap_mod
#: ⚠ 批 84（RN-613）：退避重试搬到了 `core/io_validation.py`（全仓共用一份），
#: 所以下面两条要打的桩在**它**身上，不在快照模块身上。
#: ⭐ 调用点仍走 `snap_mod._replace_with_retry` —— 那是同一个函数对象，
#:   这样一并验到「快照模块确实接的是共用的那一份」。
from core import io_validation as io_val


def test_snapshot_create_list_restore_prune(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({"a": 1}, ensure_ascii=False), encoding="utf-8")

    class _CfgObj:
        def __init__(self):
            self.loaded = False

        def save_config_now(self):
            return None

        def load_config(self):
            self.loaded = True

    cfg_obj = _CfgObj()
    monkeypatch.setattr(snap_mod, "config", cfg_obj)
    monkeypatch.setattr(snap_mod, "get_config_dir", lambda: str(cfg_dir))
    monkeypatch.setattr(snap_mod, "get_config_path", lambda: str(cfg_file))

    snap1 = snap_mod.create_snapshot("test1")
    assert snap1.snapshot_id
    assert Path(snap1.file_path).exists()

    cfg_file.write_text(json.dumps({"a": 2}, ensure_ascii=False), encoding="utf-8")
    snap2 = snap_mod.create_snapshot("test2")
    assert snap2.snapshot_id != snap1.snapshot_id

    items = snap_mod.list_snapshots()
    assert len(items) >= 2

    restored = snap_mod.restore_snapshot(snap1.snapshot_id)
    assert restored.ok is True
    assert cfg_obj.loaded is True

    removed = snap_mod.prune_snapshots(max_keep=1)
    assert removed >= 1


# ------------------------------------------------------------------ QA-024
# Windows 上 `os.replace` 会被瞬时占用打断（Defender 实时扫描 / Windows Search /
# 网盘同步客户端都会短暂持有刚写完的文件），抛 PermissionError [WinError 5]。
#
# 这条不是推测出来的：本仓库的快照判据在同一台机器上连跑 25 遍会红 2 遍（8%），
# 失败点全在写索引那一句 replace 上。落到用户身上是——他点「恢复设置」，
# 产品先给他建一份"后悔药"快照，写索引时正好撞上扫描，**那份快照就丢了**，
# 而它恰恰是这次恢复唯一的退路。

def test_replace_with_retry_survives_transient_permission_error(monkeypatch):
    """瞬时 PermissionError 必须被退避重试穿过去，而不是让调用方失败。"""
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:            # 前两次模拟被扫描器占住
            raise PermissionError(5, "拒绝访问")
        return None                    # 第三次放行；这里只数重试次数，不动磁盘

    monkeypatch.setattr(io_val.os, "replace", flaky)
    monkeypatch.setattr(io_val.time, "sleep", lambda _s: None)   # 别真等

    snap_mod._replace_with_retry("a", "b")
    assert calls["n"] == 3, f"没有重试到成功，只调了 {calls['n']} 次 replace"


def test_replace_with_retry_still_raises_when_it_never_frees_up(monkeypatch):
    """一直失败就必须**抛出去**。

    重试是为了穿过几十毫秒的扫描窗口，不是把"真的没权限写"藏起来——
    藏起来的结果是快照静默不落盘，而 UI 还告诉用户"已备份"。
    """
    def always_denied(src, dst):
        raise PermissionError(5, "拒绝访问")

    monkeypatch.setattr(io_val.os, "replace", always_denied)
    monkeypatch.setattr(io_val.time, "sleep", lambda _s: None)

    try:
        snap_mod._replace_with_retry("a", "b")
    except PermissionError:
        return
    raise AssertionError("一直被拒还是成功返回了，调用方会以为写成功了")


def test_no_file_in_the_product_calls_os_replace_without_the_retry():
    """**全仓**：`os.replace` 只许出现在那个退避重试的函数里。

    ⭐⭐⭐ 这条判据批 84（RN-613）**把分母从一个文件放宽到了整个产品**，
    而放宽的理由就是它自己漏掉的那条缺陷：
    它原来只扫 `config_snapshot_manager.py`，于是
    **`config.py` 的 `_do_save_config` 裸调 `os.replace` 一直没人管** ——
    而那是**主配置**的写盘点，比快照要紧得多：撞上 Defender 的扫描窗口就
    记一行日志、删掉临时文件、静默丢掉用户刚改的那一项。
    ⚠ 那 8% 的失败率是这个文件自己量出来的（见模块头），
    ⭐⭐ **量到了、修好了手上这一处、然后把尺子也只对着这一处。**

    ⇒ 现在的规矩只有一句：**`os.replace` 只许出现在 `replace_with_retry` 里面。**
    （`build_tools/make_installer_assets.py` 自带的那份同名函数也算数 ——
    判的是**函数名**不是文件名，所以将来谁再抄一份也照样合规。）

    用 AST 找调用 —— 本项目的判据纪律是「判断调用永远走 AST」，
    字符串匹配会被注释和字符串字面量骗过去。
    """
    import ast
    from pathlib import Path as _Path

    from _denominator import must_scan

    root = _Path(snap_mod.__file__).resolve().parents[1]
    skip_parts = {".build", "__pycache__", "output", "node_modules",
                  ".git", ".claude", "release"}

    def os_replace_lines(node_root) -> set[int]:
        found = set()
        for node in ast.walk(node_root):
            func = getattr(node, "func", None)
            if (isinstance(node, ast.Call)
                    and isinstance(func, ast.Attribute) and func.attr == "replace"
                    and isinstance(func.value, ast.Name) and func.value.id == "os"):
                found.add(node.lineno)
        return found

    scanned, leaked, helpers = [], [], 0
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        parts = set(path.relative_to(root).parts)
        if parts & skip_parts or any("_manual_backup" in p or p.startswith("_archive")
                                     for p in parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        scanned.append(rel)
        allowed = set()
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name.lstrip("_") == "replace_with_retry":
                allowed |= os_replace_lines(fn)
                helpers += 1
        leaked += [f"{rel}:{ln}" for ln in sorted(os_replace_lines(tree) - allowed)]

    must_scan(scanned, "扫过的 .py 文件", least=200)
    assert helpers, (
        "全仓找不到任何 `replace_with_retry` —— 这条判据的落点没了，"
        "它会对着一个不存在的例外永远绿下去。")
    assert not leaked, (
        "这些地方直接调了 os.replace，没走退避重试：\n  " + "\n  ".join(leaked)
        + "\n⇒ Windows 上它有 ~8% 的概率被 Defender / 索引服务的扫描窗口打断"
          "（本文件模块头有实测数）。改成 "
          "`from core.io_validation import replace_with_retry`。")

