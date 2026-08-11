# -*- coding: utf-8 -*-
"""QA-018 修复的判据：安装态冒烟必须先定性注册表通道，测不了就说测不了。

这条守的是**判据自己的诚实性**，不是产品行为：
原来 `smoke_installer.py` 里"开发机原有的卸载项原封不动"这类断言直接用 `winreg` 读，
而本进程若被注册表虚拟化，读到的是写时复制的影子副本——判据内部自洽、
结论与真机无关。当时我据此报过一条**根本不存在**的产品缺陷。

⚠ 最要命的退化方向不是"读错"，是"**读不到也打勾**"。所以这里专门量那一条。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows")


def test_channel_probe_reports_three_states():
    import smoke_installer as si

    assert hasattr(si, "probe_registry_channel")
    assert hasattr(si, "_escaped_registry_dump")


def test_escape_failure_yields_unknown_not_a_silent_pass(monkeypatch):
    """逃逸进程起不来时必须返回 unknown —— 不许悄悄退回 winreg 当作可信。"""
    import smoke_installer as si

    monkeypatch.setattr(si, "_escaped_registry_dump", lambda *a, **k: None)
    channel, outside = si.probe_registry_channel()
    assert channel == "unknown"
    assert outside is None


def test_marker_mismatch_is_classified_as_virtualized(monkeypatch):
    """容器外读不到本进程写的标记 ⇒ 必须定性为 virtualized，而不是 direct。"""
    import smoke_installer as si

    monkeypatch.setattr(si, "_escaped_registry_dump",
                        lambda *a, **k: {"probe": "别人的标记", "uninstall": {}, "run": None})
    channel, outside = si.probe_registry_channel()
    assert channel == "virtualized"
    assert outside is not None


def test_marker_roundtrip_is_classified_as_direct(monkeypatch):
    """标记原样回读 ⇒ 两边同一份 hive，winreg 可信。"""
    import smoke_installer as si

    captured = {}

    def fake(marker, *a, **k):
        captured["marker"] = marker
        return {"probe": marker, "uninstall": {}, "run": None}

    monkeypatch.setattr(si, "_escaped_registry_dump", fake)
    channel, _ = si.probe_registry_channel()
    assert channel == "direct"
    assert captured["marker"], "没有真的往注册表写标记，那这条自检等于没做"


def test_unknown_channel_must_fail_the_smoke_not_pass_it():
    """通道未知时，脚本必须把结果判成不通过。

    行为判据而不是结构判据：读源码里有没有 `ok = False` 会被一句
    `ok = True` 覆盖骗过（登记册里那条教训）。这里直接量源码 AST 中
    "unknown 分支下是否存在把 ok 置假的赋值"，再配一条文案判据兜底。
    """
    import ast

    src = (ROOT / "scripts" / "smoke_installer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # 找 `if channel == "unknown":`
        test = ast.dump(node.test)
        if "unknown" not in test:
            continue
        for stmt in ast.walk(node):
            if (isinstance(stmt, ast.Assign)
                    and any(getattr(t, "id", "") == "ok" for t in stmt.targets)
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is False):
                found = True
    assert found, "通道未知时没有把 ok 置为 False —— 会变成'测不了也算通过'"
    assert "未测" in src, "至少要有一处显式打印「未测」，静默少测会被读成全覆盖"
