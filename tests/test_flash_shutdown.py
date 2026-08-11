# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""闪光子进程关闭路径回归测试（UP-007）。

固化两件事，防止有人把根因改回去：

1. `FlashEffectProcess.shutdown()` 绝不能调 `pygame.quit()`。
   它跑在**命令线程**上，而主循环此时可能正卡在 `display.flip()`/`blit` 中途；
   在那里销毁 SDL 显示会让子进程挂住不退，父进程只能等 `join(timeout=2.0)`
   超时后 `terminate()`——用户感知就是"点 X 之后界面冻约 3 秒"。
   隔离实测（各 8 次）：改回去 = 中位 2019ms 且 8/8 次卡满超时；
   正确写法 = 中位 79ms。

2. 主循环退出后必须自己调 `pygame.quit()`，否则 SDL 资源不释放。

这里用源码级断言而不是真起子进程：起进程会创建全屏置顶窗口、耗时数秒，
不适合放进每次都跑的单元测试。真机定量验收用 scripts/bench_flash_stop.py。
"""
from __future__ import annotations

import ast
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "flash_process.py"


def _find_func(cls_name: str, func_name: str) -> ast.FunctionDef:
    """取某个类里某个方法的 AST 节点。

    刻意用 AST 而不是文本匹配：本文件的注释与 docstring 里就写着
    `pygame.quit()` / `pygame.Surface(` 这些字样（用来解释为什么不能那么写），
    文本匹配会把说明文字当成真实调用，白白误报。
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == func_name:
                    return sub
    raise AssertionError(f"没找到 {cls_name}.{func_name}")


def _calls_in(node: ast.AST) -> set:
    """收集节点内所有形如 `a.b()` 的调用，返回 {"a.b", ...}。"""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            owner = sub.func.value
            if isinstance(owner, ast.Name):
                out.add(f"{owner.id}.{sub.func.attr}")
    return out


def test_shutdown_does_not_call_pygame_quit():
    """命令线程里销毁 SDL 显示 = 子进程挂住不退 = 用户点 X 冻 3 秒。"""
    fn = _find_func("FlashEffectProcess", "shutdown")
    assert "pygame.quit" not in _calls_in(fn), (
        "shutdown() 跑在命令线程上，绝不能在这里调 pygame.quit()。"
        "主循环可能正卡在渲染中途，SDL 被并发拆掉会让子进程挂住。"
        "正确做法：只置 is_running=False，quit 交给主循环退出后自己做。"
    )
    # 必须仍然置停运行标志，否则主循环永远不结束
    assigns = [
        t.attr for n in ast.walk(fn) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Attribute)
    ]
    assert "is_running" in assigns, "shutdown() 必须置停 is_running"


def test_main_loop_cleans_up_pygame():
    """主循环退出后必须自己释放 SDL。"""
    fn = _find_func("FlashEffectProcess", "main_loop")
    assert "pygame.quit" in _calls_in(fn), (
        "main_loop 跳出循环后必须调 pygame.quit() 释放 SDL —— "
        "它是唯一能保证'此刻不会再有渲染调用'的位置。"
    )


def test_manager_sends_shutdown_before_waiting():
    """父进程必须先发关闭命令再等待，否则白等。"""
    mgr_src = (Path(__file__).resolve().parent.parent
               / "flash_process_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(mgr_src)
    stop_src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "stop_process":
            stop_src = ast.get_source_segment(mgr_src, node) or ""
            break
    assert stop_src, "没找到 stop_process"

    idx_send = stop_src.find('"shutdown"')
    idx_join = stop_src.find("_monitor_thread.join")
    assert idx_send != -1, "stop_process 必须发送 shutdown 命令"
    assert idx_join != -1, "stop_process 应当等待监控线程"
    assert idx_send < idx_join, (
        "必须先把 shutdown 命令发出去再 join 监控线程。"
        "顺序反了的话，join 那最多 2 秒里子进程根本不知道要退出，纯属白等。"
    )


def test_scratch_surface_is_reused():
    """UP-012：全屏 Surface 必须复用，不能每帧新建。

    2560×1440×4 ≈ 14.7MB，120fps 下就是约 1.7GB/s 的分配/回收 churn，
    闪光弹炸开那一瞬间正好掉帧。
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))

    # 真实的 pygame.Surface(...) 调用（不含注释/docstring 里的说明文字）
    creations = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Surface"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "pygame"
    ]
    assert len(creations) <= 1, (
        f"仍有 {len(creations)} 处真实的 pygame.Surface() 调用；"
        "全屏画布应当全部走 _scratch_surface() 复用"
    )

    reuse = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_scratch_surface"
    ]
    assert len(reuse) >= 9, f"只有 {len(reuse)} 处走复用，9 处风格效果都应改过来"
