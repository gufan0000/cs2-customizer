# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""打包产物冒烟（R8a 起使用，计划书 §6「打包冒烟」的自动化实现）。

**为什么必须在打包产物上跑**：PyArmor 只混淆根目录 `.py`，PyInstaller 的
hiddenimports 只扫种子文件一层 AST —— 惰性导入 / 新增模块 / 改子进程这三类改动
存在「源码跑得好好的，打包版一启动就炸」的真实风险。源码测试再绿也证明不了这件事。

跑什么（口径同 05 §6）：**启动 / GSI / 音频 / 闪光**，外加 R8a 关心的
「惰性导入的模块在冻结环境里能不能真的加载」。

    python scripts/smoke_packaged.py --exe "release/CS2 Customizer 2.2.1/CS2 Customizer.exe"
    python scripts/smoke_packaged.py --seconds 60

⚠️ **会真的启动软件**：主窗口上屏、准心覆盖窗可能出现、GSI 占 127.0.0.1:3000、
音频设备被初始化、配置里开着的全局热键在这段时间内生效。
配置与日志走**隔离目录**（拷贝用户配置并把 close_action 改成 exit 以便自动关闭），
用户真实的 %LOCALAPPDATA%\\CS2Customizer 不受影响。

退出码：0=全部判据通过，1=有判据未通过。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 与 live_run.py 同一套：PostMessage(WM_CLOSE) 是唯一能真正触发 Qt closeEvent 的方式
# （taskkill 不走 Qt 事件循环，Process.CloseMainWindow 命中的是控制台窗口）。
_CLOSE_PS = r"""
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WClose {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
}
'@
$target = __PID__
$found = @()
[WClose]::EnumWindows({ param($h,$l)
  $p = 0
  [WClose]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null
  if ($p -eq $target -and [WClose]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder 256
    [WClose]::GetWindowText($h, $sb, 256) | Out-Null
    $script:found += [pscustomobject]@{ H = $h; T = $sb.ToString() }
  }
  return $true
}, [IntPtr]::Zero) | Out-Null
foreach ($w in $found) { Write-Output ("WINDOW`t{0}`t{1}" -f $w.H, $w.T) }
if (__POST__ -eq 1) { foreach ($w in $found) { [WClose]::PostMessage($w.H, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null } }
"""


def _visible_windows(pid: int) -> list:
    """只列不关：这个 pid 名下有几个可见顶层窗口（RN-645 用它认「谁才是应用」）。"""
    script = _CLOSE_PS.replace("__PID__", str(pid)).replace("__POST__", "0")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=60,
        ).stdout
    except Exception:
        return []
    return [ln.split("\t")[2] for ln in out.splitlines()
            if ln.startswith("WINDOW\t") and len(ln.split("\t")) >= 3]


def _prepare_env(work: Path) -> dict:
    cfg_dir = work / "config"
    log_dir = work / "logs"
    for d in (cfg_dir, log_dir):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)

    real = os.environ.get("LOCALAPPDATA")
    src = Path(real) / "CS2Customizer" / "config.json" if real else None
    data = {}
    if src and src.is_file():
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    # 关窗默认是 ask（弹对话框问进托盘还是退出），自动化必须改掉
    data["close_action"] = "exit"
    (cfg_dir / "config.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    env = dict(os.environ)
    env["CS2C_CONFIG_DIR"] = str(cfg_dir)
    env["CS2C_LOG_DIR"] = str(log_dir)
    return env


def _close_windows(pid: int) -> list:
    script = _CLOSE_PS.replace("__PID__", str(pid)).replace("__POST__", "1")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=60,
        ).stdout
    except Exception as exc:
        print(f"  发送 WM_CLOSE 失败: {exc}")
        return []
    return [ln.split("\t")[2] for ln in out.splitlines()
            if ln.startswith("WINDOW\t") and len(ln.split("\t")) >= 3]


def _children_of(pid: int) -> list[int]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' "
         "| Select-Object -ExpandProperty ProcessId) -join ','"],
        capture_output=True, text=True, errors="replace", timeout=60,
    ).stdout
    return [int(x) for x in out.strip().split(",") if x.strip().isdigit()]


#: RN-645：应用自己会再起子进程（`multiprocessing` 的 fork 助手带这个开关），它们不是应用。
FORK_HELPER_MARK = "--multiprocessing-fork"


def _child_processes(pid: int) -> list[tuple[int, str]]:
    """(子进程 pid, 命令行) —— 命令行是分辨「引导→应用」和「应用→助手」的唯一依据。"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' "
         "| ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
        capture_output=True, text=True, errors="replace", timeout=60,
    ).stdout
    rows = []
    for ln in out.splitlines():
        head, _, cmd = ln.partition("\t")
        if head.strip().isdigit():
            rows.append((int(head), cmd or ""))
    return rows


def _resolve_app_pid(parent_pid: int, wait_seconds: float = 20.0) -> int:
    """⭐⭐⭐ RN-636（批 93）：**onefile 产物的主窗不在我起的那个进程里。**

    PyInstaller onefile 先起一个引导进程（解包），再起一个**同名子进程**跑真正的
    应用；`Popen` 交回来的 pid 是引导进程的。批 92 实测：拿它去 EnumWindows
    ⇒ 「无可见顶层窗口」，WM_CLOSE 发给了空气；随后 `proc.kill()` 只打印了一句
    「强杀」，**两个进程都还活着**，主窗留在用户桌面上、GSI 端口继续占着。
    ⇒ 起动后等子进程出现（onefile 解包要几秒），拿**子进程**当应用；
      等不到（onedir 没有子进程）就用原 pid。

    ⭐⭐ RN-645（批 96）：**「第一个子进程」不是应用的充分条件。** 批 96 实测 onedir 产物：
    应用自己起了一个 `--multiprocessing-fork` 助手，上面那条把它当成了应用 ⇒ 「无可见顶层窗口」，
    WM_CLOSE 又发给了空气 —— 和 RN-636 同一个症状、相反的方向（那次是父，这次是子）。
    ⇒ 认应用只认一件事：**谁名下有可见顶层窗口**；候选 = 父 + 非助手子进程，等窗口出现为止；
      都等不到才退回「第一个非助手子进程 / 父」。
    """
    deadline = time.perf_counter() + wait_seconds
    while time.perf_counter() < deadline:
        kids = [pid for pid, cmd in _child_processes(parent_pid) if FORK_HELPER_MARK not in cmd]
        windows = {pid: _visible_windows(pid) for pid in kids + [parent_pid]}
        chosen = _choose_app_pid(parent_pid, kids, windows)
        if chosen is not None:
            return chosen
        time.sleep(0.5)
    kids = [pid for pid, cmd in _child_processes(parent_pid) if FORK_HELPER_MARK not in cmd]
    return kids[0] if kids else parent_pid


#: PyInstaller onefile 的启动画面是一个 Tk 窗口，标题就叫 "tk"，住在**引导进程**名下。
#: 批 96 实测：按「谁有可见窗口」认应用，0.8s 时引导进程已经有这扇窗 ⇒ 把引导进程当成了应用。
SPLASH_TITLES = {"tk"}


def _choose_app_pid(parent_pid: int, kids: list[int], windows: dict) -> int | None:
    """纯判断，不碰进程：谁是应用。返回 None = 还没法定（再等）。

    规则：① 子进程（非 fork 助手）名下有**非启动画面**的可见窗口 ⇒ 它；
          ② 没有子进程、而父进程有非启动画面的可见窗口 ⇒ 父（onedir 的形状）；
          ③ 其余 ⇒ 还没法定。⚠ 有子进程但都还没窗口时**不许**退回父 —— 那正是 RN-636 的错法。
    """
    def real(pid):
        return [w for w in windows.get(pid, []) if w.strip().lower() not in SPLASH_TITLES]
    for pid in kids:
        if real(pid):
            return pid
    if not kids and real(parent_pid):
        return parent_pid
    return None


def _descendants(pid: int) -> list[int]:
    """整棵子树（子、孙…）。RN-645：善后按树核对，不按两个 pid。"""
    out, todo = [], [pid]
    while todo:
        cur = todo.pop()
        kids = _children_of(cur)
        out.extend(kids)
        todo.extend(kids)
    return out


def _still_alive(pids: list[int]) -> list[int]:
    """⛔ 杀完必须回头看一眼 —— 批 91 那三次「静音的清理」的教训。"""
    if not pids:
        return []
    ids = ",".join(str(p) for p in pids)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Process -Id {ids} -ErrorAction SilentlyContinue "
         "| Select-Object -ExpandProperty Id) -join ','"],
        capture_output=True, text=True, errors="replace", timeout=60,
    ).stdout
    return [int(x) for x in out.strip().split(",") if x.strip().isdigit()]


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _read_log(log_dir: Path) -> str:
    parts = []
    for path in sorted(log_dir.glob("*.log")):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return "\n".join(parts)


# 判据：(名称, 正则, 是否必须命中)
CHECKS = [
    ("启动完成", r"GUI初始化完成", True),
    ("主窗相位埋点", r"\[主窗相位\]", True),
    ("音频子系统", r"音频|audio|Audio", True),
    ("GSI 服务", r"GSI|gsi", True),
    ("退出链路走完", r"退出清理完成", True),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="打包产物冒烟")
    ap.add_argument("--exe", default="", help="打包产物 exe 路径；留空自动找 release/ 下最新的")
    ap.add_argument("--seconds", type=int, default=60, help="观察多少秒")
    ap.add_argument("--workdir", default="", help="隔离目录")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else None
    if exe is None:
        # ⚠ QA/RN（2026-08-18 实际踩到）：`release/*/*.exe` 会把
        # **`release/installer/CS2 Customizer 安装包_2.2.4.exe` 一起捞进来**，
        # 而它按 mtime 恰好是最新的（安装包在应用产物之后生成）。
        # 于是这个脚本启动的是**安装程序**：等 UAC 等到超时、探不到窗口、
        # 日志 0 字符，然后 7 条判据一起红——看起来像"打包版起不来"，
        # 实际上一个字都没测到。更坏的是它真的在用户机器上拉起了安装器。
        # ⇒ 自动挑选一律排除 installer 目录；挑中的还必须**同名目录里带 _internal**
        #   （onedir 产物的形状），否则宁可报错也不瞎跑。
        cands = sorted(ROOT.glob("release/*/*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        cands = [c for c in cands
                 if "unins" not in c.name.lower()
                 and c.parent.name.lower() != "installer"
                 and "安装包" not in c.name
                 and (c.parent / "_internal").is_dir()]
        # RN-645：onefile 产物直接躺在 release/ 根下（`release/CS2 Customizer 2.2.4.exe`），
        # 原来的挑选只看 onedir 的形状，于是刚打出来的 onefile 永远轮不到、跑的是一个月前的 onedir。
        cands += [c for c in ROOT.glob("release/*.exe")
                  if "unins" not in c.name.lower() and "安装包" not in c.name]
        cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if not cands:
            print("!! 找不到打包产物（onedir：release/<名字>/<名字>.exe 且同级有 _internal；或 onefile：release/*.exe）")
            print("   请先跑 build_tools/build_release.py --mode onefile")
            return 1
        exe = cands[0]
        print(f"[自动挑选] {exe}")
    if not exe.is_file():
        print(f"!! exe 不存在: {exe}")
        return 1

    work = Path(args.workdir) if args.workdir else Path(os.environ.get("TEMP", "/tmp")) / "cs2customizer_pkg_smoke"
    env = _prepare_env(work)
    log_dir = Path(env["CS2C_LOG_DIR"])

    print(f"产物   : {exe}")
    print(f"隔离配置: {env['CS2C_CONFIG_DIR']}")
    print(f"隔离日志: {env['CS2C_LOG_DIR']}")
    print(f"观察   : {args.seconds}s\n")

    port_before = _port_busy(3000)
    if port_before:
        print("!! 127.0.0.1:3000 启动前就被占用，GSI 判据将不可信")

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(exe)], cwd=str(exe.parent), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"已启动 pid={proc.pid}")
    app_pid = _resolve_app_pid(proc.pid)
    print(f"  应用进程 pid={app_pid}" + ("（onefile 子进程）" if app_pid != proc.pid else "（同一进程）"))

    gsi_seen = False
    deadline = time.perf_counter() + args.seconds
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            print(f"!! 进程在观察期内自行退出，退出码 {proc.returncode}")
            break
        if not gsi_seen and not port_before and _port_busy(3000):
            gsi_seen = True
            print(f"  [{time.perf_counter() - t0:5.1f}s] GSI 已监听 127.0.0.1:3000")
        time.sleep(1.0)

    alive = proc.poll() is None
    exit_ok = False
    if alive:
        print(f"\n[{time.perf_counter() - t0:5.1f}s] 发送 WM_CLOSE …")
        # RN-645：善后要核对的是**整棵树**（引导 + 应用 + 应用自己起的助手），在它们都还活着时先记下来 ——
        # 引导进程一死，孙进程会被 Windows 改挂到别处，事后再找就找不到了（批 96 实测：一个漏掉的应用
        # 实例占着 3000 端口活了 5 分钟，下一轮冒烟的应用一看「已有实例」就退出，两条判据因此假绿）。
        tree = sorted({proc.pid, app_pid} | set(_descendants(proc.pid)))
        titles = _close_windows(app_pid)
        print(f"  命中窗口: {titles or '（无可见顶层窗口）'}")
        try:
            proc.wait(timeout=60)
            exit_ok = True
            print(f"  进程已退出，退出码 {proc.returncode}，总耗时 {time.perf_counter() - t0:.1f}s")
        except subprocess.TimeoutExpired:
            print("  !! 60s 内没退出，强杀")
            proc.kill()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        # ⛔ 无论走哪条路，回头核对：引导进程和应用进程一个都不许留在用户机器上。
        leftovers = _still_alive(sorted({proc.pid, app_pid} | set(tree)))
        if leftovers:
            print(f"  !! 还活着：{leftovers} ⇒ Stop-Process -Force")
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Stop-Process -Force -ErrorAction SilentlyContinue -Id "
                            + ",".join(str(p) for p in leftovers)],
                           capture_output=True, timeout=60)
            time.sleep(1.0)
            leftovers = _still_alive(leftovers)
            if leftovers:
                print(f"  !!! 杀不掉：{leftovers} —— 这是真事故，不是日志问题")
                exit_ok = False

    time.sleep(1.5)
    log = _read_log(log_dir)

    print(f"\n== 判据（日志 {len(log)} 字符）==")
    failures = []
    for name, pattern, required in CHECKS:
        hit = re.search(pattern, log) is not None
        mark = "✓" if hit else ("✗" if required else "-")
        print(f"  {mark} {name}")
        if required and not hit:
            failures.append(name)

    print(f"  {'✓' if gsi_seen else '✗'} GSI 端口 3000 实际监听")
    if not gsi_seen and not port_before:
        failures.append("GSI 端口监听")

    print(f"  {'✓' if exit_ok else '✗'} 优雅退出（WM_CLOSE 后自行结束）")
    if not exit_ok:
        failures.append("优雅退出")

    errors = [ln for ln in log.splitlines() if "[ERROR]" in ln or "Traceback" in ln]
    # 惰性导入最可能的爆法：冻结环境里 importlib 找不到模块
    import_errors = [ln for ln in log.splitlines()
                     if re.search(r"(ModuleNotFoundError|ImportError|No module named)", ln)]
    print(f"  {'✓' if not import_errors else '✗'} 无导入错误（{len(import_errors)} 条）")
    if import_errors:
        failures.append("导入错误")
        for ln in import_errors[:10]:
            print(f"      {ln.strip()[:160]}")

    print(f"\n  ERROR 行数: {len(errors)}")
    for ln in errors[:15]:
        print(f"    {ln.strip()[:160]}")

    print()
    if failures:
        print(f"== 冒烟未通过：{', '.join(failures)} ==")
        return 1
    print("== 冒烟全部通过 ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
