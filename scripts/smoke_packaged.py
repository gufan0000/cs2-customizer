# -*- coding: utf-8 -*-
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
foreach ($w in $found) { [WClose]::PostMessage($w.H, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
"""


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
    script = _CLOSE_PS.replace("__PID__", str(pid))
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
        cands = sorted(ROOT.glob("release/*/*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        cands = [c for c in cands if "unins" not in c.name.lower()]
        if not cands:
            print("!! 找不到打包产物，请先跑 build_tools/build_release.py --mode onedir")
            return 1
        exe = cands[0]
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
        titles = _close_windows(proc.pid)
        print(f"  命中窗口: {titles or '（无可见顶层窗口）'}")
        try:
            proc.wait(timeout=60)
            exit_ok = True
            print(f"  进程已退出，退出码 {proc.returncode}，总耗时 {time.perf_counter() - t0:.1f}s")
        except subprocess.TimeoutExpired:
            print("  !! 60s 内没退出，强杀")
            proc.kill()
            proc.wait(timeout=30)

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
