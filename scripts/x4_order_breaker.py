# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X4：把 `main()` 里**写在注释里的顺序契约**逐条真的破坏掉，看有没有判据变红。

## 为什么需要它

`x4_boot_contract.py` 数出「10 条顺序契约里有 8 条被判据**提到过**」——
⭐⭐⭐ 而「提到过」离「守着」差得很远：`test_render_hardening.py` 直接调
`_apply_display_hardening()` 验它的返回值，**一个字都没管它在不在
`QApplication()` 之前** —— 而这条契约的全部内容就是那个位置。

⭐ 更硬的一条事实：**没有任何判据调用过 `main_widget.main()`**（AST 扫全仓测试，
`main()` 722 行、要真的 QApplication + 主窗）。⇒ 结构上，`main()` 内部的顺序
只可能被**读源码文本**的判据抓住，而这种判据全仓只有三个，管的分别是
UP-008 回退说明、PRELOAD_POOL 内容、闪屏脚本里的 Tk 语句顺序。

**本脚本不推理，只破坏。** 一次把九条全部违反，跑一遍全量：
  · 全绿 ⇒ **这一族一条都没人守**（一次测量拿到全家的结论）；
  · 变红 ⇒ 逐条二分，红的那条是真有人守着。

## ⛔ 它会真的改产品文件

同 RN-093 的纪律：① **别给它加 `timeout`**（到点 = 在任意中间态被砍断）；
② 它跑着的时候**不许并行跑测试**。它会先把原文备份到 `<file>.x4bak`，
`--restore` 还原；启动时若发现残留备份，**先自动还原再干活**。

用法：
    python scripts/x4_order_breaker.py --list
    python scripts/x4_order_breaker.py --break all      # 九条一起破
    python scripts/x4_order_breaker.py --break hardening_before_qapp
    python scripts/x4_order_breaker.py --restore
"""
from __future__ import annotations

import argparse
import ast
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main_widget.py"
LOGGER = ROOT / "core" / "utils" / "logger.py"

#: 每条破坏 = (键, 目标文件, 要移动的整段原文, 插到谁之后, **搬完应该落在谁的函数体里**)。
#: ⭐ 一律用**整段原文**做锚，不要行号 —— 前一条破坏会把后面所有行号顶掉。
#: ⚠ 每一条都是「搬家」，不是「删除」：删掉是另一种缺陷，而契约说的是**位置**。
#:
#: ⛔⛔ 最后那一栏（`expect_scope`）是本脚本第一版**没有**的，而它当场骗了我一次：
#: `idle_watcher` 那条要把代码搬进 `on_all_completed` 回调，我照文本插在
#: `_boot_phase("后台资源全就绪")` 之后 —— 那一行缩进 8 格，而搬过去的整段缩进 4 格。
#: ⇒ 那段 4 格的 `try:` **把回调的函数体在这里截断了**，自己落回 `main` 的直线代码，
#: 还顺手把回调原来的 `window.start_idle_preload()` 吞进了自己的 `except` 分支。
#: ⭐⭐⭐ `ast.parse` 说它合法、脚本打印了「💥 已破坏」，而跑出来的是**第三个程序** ——
#: 既不是原来的，也不是我想要的那种违反。（判据当时是绿的，而**判据是对的**。）
#: ⇒ 两条修法：① 搬家时按落点的缩进**重排缩进**；② 搬完用 AST **核对它落在了谁的体内**。
#: ⭐⭐ **一个破坏脚本，必须检查自己声称做到的那件事** —— 否则「没抓住」这个读数，
#: 既可能是判据漏了，也可能是我根本没破坏成功，而两者的输出一模一样。
BREAKS: dict[str, tuple[Path, str, str, str | None]] = {}


def _reg(key: str, path: Path, block: str, after: str,
         expect_scope: str | None = None) -> None:
    """block 从原处删掉，按 after 那一行的缩进重排后插到它之后。

    `expect_scope` = 搬完之后，block 第一行该落在哪个函数体里
    （`<module>` = 模块级）。`None` 表示这条不是搬家（原地替换）。
    """
    BREAKS[key] = (path, block, after, expect_scope)


MODULE_SCOPE = "<module>"


def _scope_map(src: str) -> dict[int, str]:
    """行号 → 最内层函数名。⭐ 和判据用的是同一套算法（`ast.walk` 外层先到）。"""
    scopes: dict[int, str] = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for ln in range(node.lineno, node.end_lineno + 1):
                scopes[ln] = node.name
    return scopes


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _reindent(block: str, target: int) -> str:
    """把整段的基准缩进移到 `target`，段内的相对缩进保持不变。"""
    lines = block.split("\n")
    base = min((_indent_of(ln) for ln in lines if ln.strip()), default=0)
    delta = target - base
    if delta == 0:
        return block
    out = []
    for ln in lines:
        if not ln.strip():
            out.append(ln)
        elif delta > 0:
            out.append(" " * delta + ln)
        else:
            out.append(ln[min(-delta, _indent_of(ln)):])
    return "\n".join(out)


# ① 计时零点挪到重 import 之后 ⇒ 所有启动相位读数整体偏小，报表照常出
_reg(
    "boot_t0_before_imports", MAIN,
    "_BOOT_T0 = _boot_time.perf_counter()  # 启动相位计时起点(必须先于一切重 import)\n",
    "from pathlib import Path\n",
    MODULE_SCOPE,
)

# ② faulthandler 挪到全部重 import 之后 ⇒ 导入期原生崩溃不再有栈
_reg(
    "faulthandler_early", MAIN,
    "_enable_faulthandler()\n",
    "from core.io_validation import replace_with_retry\n",
    MODULE_SCOPE,
)

# ③ 压缩挪到 append 句柄打开之后 ⇒ 替换掉的是另一个 inode，此后的崩溃写进旧文件
_reg(
    "compact_before_append", MAIN,
    '        if not os.environ.get("_CS2C_CRASHLOG_COMPACTED"):\n'
    "            _compact_native_crash_log(crash_path)\n"
    '            os.environ["_CS2C_CRASHLOG_COMPACTED"] = "1"\n',
    '        _FAULT_LOG_FP = open(crash_path, "a", encoding="utf-8", buffering=1)\n',
    "_enable_faulthandler",
)

# ④ 显示层加固挪到 QApplication 之后 ⇒ 高DPI/软件渲染属性整条不生效
_reg(
    "hardening_before_qapp", MAIN,
    "    _safe_mode, _auto_recovered = _apply_display_hardening(logger)\n",
    "    app = QApplication(sys.argv)\n",
    "main",
)

# ⑤ 字号缩放挪到主窗构建之后 ⇒ 已建好的控件不会跟着变
_reg(
    "font_scale_before_window", MAIN,
    "    try:\n"
    "        from ui_design_system import apply_font_scale\n"
    '        apply_font_scale(getattr(config, "ui_font_scale", 1.0))\n'
    "    except Exception as _fs_exc:\n"
    '        logger.warning(f"字号缩放应用失败(已回退默认): {_fs_exc}")\n',
    "    window = MainWindow(auto_background_preload=False)\n",
    "main",
)

# ⑥ 卡顿探测挪到单实例守卫之前 ⇒ 第二个进程往第一个进程的日志里插伪造会话
_reg(
    "monitors_after_single_instance", MAIN,
    "    try:\n"
    "        from core.utils.jank_monitor import start_jank_monitor\n"
    "        start_jank_monitor(app, t0=_BOOT_T0)\n"
    "    except Exception:\n"
    "        pass  # 诊断设施绝不能影响启动\n",
    "    _install_qt_message_handler(logger)\n",
    "main",
)

# ⑦ 内存探测挪到主窗构建之后 ⇒ 启动期最大那段停顿被整段漏掉
_reg(
    "monitors_before_window", MAIN,
    "    try:\n"
    "        from core.utils.mem_monitor import start_mem_monitor\n"
    "        start_mem_monitor(app, t0=_BOOT_T0)\n"
    "    except Exception:\n"
    "        pass\n",
    "    window = MainWindow(auto_background_preload=False)\n",
    "main",
)

# ⑧ 空闲侦测器挪到「后台资源全就绪」回调里 ⇒ 预载全程无门控（真正的乱序，不是晚一拍）
_reg(
    "idle_watcher_before_preload", MAIN,
    "    try:\n"
    "        from core.utils.idle_watcher import start_idle_watcher\n"
    "        start_idle_watcher(app)\n"
    "    except Exception as _iw_exc:\n"
    '        # 不能静默:装不上就意味着预载退化为"无门控",卡顿治理整个失效,\n'
    '        # 而现象和"没改过"一模一样,排查时会完全找不到线索。\n'
    '        logger.warning(f"空闲侦测器安装失败，预载将退化为无让路模式: {_iw_exc}")\n',
    '        _boot_phase("后台资源全就绪")\n',
    "on_all_completed",
)

# ⑨ 频次榜不再限定在预载池内 ⇒ music 等设备页可能被静默预载打开
_reg(
    "known_pages_within_pool", MAIN,
    "                frequent = [p for p in top_pages(4, known_pages=set(PRELOAD_POOL))]\n",
    "",  # 空 after = 原地替换成下面这行（特判，见 apply）
)
REPLACE_INSTEAD = {
    "known_pages_within_pool": "                frequent = [p for p in top_pages(4)]\n",
}


def _backup_path(p: Path) -> Path:
    return p.with_suffix(p.suffix + ".x4bak")


def restore(quiet: bool = False) -> int:
    n = 0
    for p in {MAIN, LOGGER}:
        bak = _backup_path(p)
        if bak.exists():
            io.open(p, "w", encoding="utf-8", newline="").write(
                io.open(bak, encoding="utf-8", newline="").read())
            bak.unlink()
            n += 1
            if not quiet:
                print(f"↩ 已还原 {p.name}")
    if not quiet and n == 0:
        print("（没有残留备份）")
    return n


def apply(keys: list[str]) -> int:
    restore(quiet=True)  # ⭐ 先收拾上一轮的残留，别在已破坏的文本上再破坏一次

    touched = {BREAKS[k][0] for k in keys}
    for p in touched:
        bak = _backup_path(p)
        io.open(bak, "w", encoding="utf-8", newline="").write(
            io.open(p, encoding="utf-8", newline="").read())

    ok = 0
    for key in keys:
        path, block, after, expect_scope = BREAKS[key]
        raw = io.open(path, encoding="utf-8", newline="").read()
        eol = "\r\n" if "\r\n" in raw else "\n"
        body = raw.replace(eol, "\n")

        insert_pos = -1
        if key in REPLACE_INSTEAD:
            if body.count(block) != 1:
                print(f"⛔ {key}: 锚点出现 {body.count(block)} 次，跳过")
                continue
            body = body.replace(block, REPLACE_INSTEAD[key], 1)
        else:
            if body.count(block) != 1:
                print(f"⛔ {key}: 要搬的那段出现 {body.count(block)} 次，跳过")
                continue
            if body.count(after) != 1:
                print(f"⛔ {key}: 落点出现 {body.count(after)} 次，跳过")
                continue
            moved = _reindent(block, _indent_of(after))
            body = body.replace(block, "", 1)
            body = body.replace(after, after + moved, 1)
            # ⚠ 落点行号只能**从插入位置算**，不能去 `body.index(搬过去那段的第一行)`：
            #   第一行往往就是 `    try:` 这种满文件都是的东西 —— 第一版那么写，
            #   于是五条全都去核对了 `_compact_native_crash_log` 里的另一个 `try:`，
            #   ⭐ 报出来的是「缩进对不上」，而真实情况是**我核对错了对象**。
            insert_pos = body.index(after) + len(after)

        try:
            ast.parse(body)
        except SyntaxError as exc:
            print(f"⛔ {key}: 破坏后语法不合法（{exc}），跳过")
            continue

        # ⭐ 后置核对：搬完之后它到底落在谁的函数体里（见 BREAKS 上面那段）
        if expect_scope is not None:
            line_no = body[:insert_pos].count("\n") + 1
            got = _scope_map(body).get(line_no, MODULE_SCOPE)
            if got != expect_scope:
                print(f"⛔ {key}: 搬完之后落在 `{got}` 里，而我要的是 `{expect_scope}`"
                      "（缩进对不上 ⇒ 这不是我想造的那种违反），跳过")
                continue

        io.open(path, "w", encoding="utf-8", newline="").write(body.replace("\n", eol))
        ok += 1
        print(f"💥 {key}")

    print(f"\n已破坏 {ok} / {len(keys)} 条。"
          f"\n⚠ 现在**不要提交**。跑完全量后用 --restore 还原。")
    return 0 if ok == len(keys) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--break", dest="brk", default=None)
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    if args.list:
        for k in BREAKS:
            print(f"  {k}")
        return 0
    if args.restore:
        restore()
        return 0
    if args.brk:
        keys = list(BREAKS) if args.brk == "all" else args.brk.split(",")
        bad = [k for k in keys if k not in BREAKS]
        if bad:
            print(f"⛔ 不认识：{bad}")
            return 2
        return apply(keys)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
