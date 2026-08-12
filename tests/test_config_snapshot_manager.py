# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path

from core import config_snapshot_manager as snap_mod


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

    monkeypatch.setattr(snap_mod.os, "replace", flaky)
    monkeypatch.setattr(snap_mod.time, "sleep", lambda _s: None)   # 别真等

    snap_mod._replace_with_retry("a", "b")
    assert calls["n"] == 3, f"没有重试到成功，只调了 {calls['n']} 次 replace"


def test_replace_with_retry_still_raises_when_it_never_frees_up(monkeypatch):
    """一直失败就必须**抛出去**。

    重试是为了穿过几十毫秒的扫描窗口，不是把"真的没权限写"藏起来——
    藏起来的结果是快照静默不落盘，而 UI 还告诉用户"已备份"。
    """
    def always_denied(src, dst):
        raise PermissionError(5, "拒绝访问")

    monkeypatch.setattr(snap_mod.os, "replace", always_denied)
    monkeypatch.setattr(snap_mod.time, "sleep", lambda _s: None)

    try:
        snap_mod._replace_with_retry("a", "b")
    except PermissionError:
        return
    raise AssertionError("一直被拒还是成功返回了，调用方会以为写成功了")


def test_index_write_and_restore_both_go_through_the_retry():
    """索引写入与恢复替换**都**要走重试，不能只修一处。

    用 AST 找 `os.replace(` 的直接调用——本项目的判据纪律是"判断调用永远走 AST"，
    字符串匹配会被注释和字符串字面量骗过去。
    """
    import ast
    from pathlib import Path as _Path

    def os_replace_lines(root) -> set[int]:
        found = set()
        for node in ast.walk(root):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "replace"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                found.add(node.lineno)
        return found

    tree = ast.parse(_Path(snap_mod.__file__).read_text(encoding="utf-8"))
    # 允许的那两处在 `_replace_with_retry` 内部（重试循环 + 最后一次不吞异常的）
    inside_helper = {
        line
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef) and fn.name == "_replace_with_retry"
        for line in os_replace_lines(fn)
    }
    assert inside_helper, "_replace_with_retry 里已经不调 os.replace 了，这条判据的落点变了"
    leaked = sorted(os_replace_lines(tree) - inside_helper)
    assert not leaked, (
        f"这些行直接调了 os.replace 而没走重试：{leaked}。"
        "Windows 上它会被 Defender 的扫描窗口打断，见 _replace_with_retry 的说明。"
    )

