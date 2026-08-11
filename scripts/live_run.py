#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真机启动-观察-优雅退出 自动化跑测（R2 起使用）。

为什么需要它:启动时序与退出耗时只能在真实运行里观察,但手工开关软件既慢又
不可复现,而且会把用户真实配置/日志搅乱。本脚本:

- 用**隔离的配置、日志与 CS2 游戏目录**跑(拷贝用户配置,只改 close_action=exit
  让关窗可自动化),用户真实的 %LOCALAPPDATA%\\FanTool 与真实游戏目录都不受影响;
- 跑够指定秒数后,枚举该进程的顶层窗口并 PostMessage(WM_CLOSE)——这是唯一能真正
  触发 Qt closeEvent 的方式(实测 taskkill 与 Process.CloseMainWindow 都不行,
  前者不走 Qt 事件循环,后者命中的是控制台窗口);
- 兜底强杀,绝不留下孤儿进程。

用法:
    python scripts/live_run.py                  # 跑 1 次,每次 45 秒
    python scripts/live_run.py --runs 3
    python scripts/live_run.py --seconds 60
    python scripts/live_run.py --keep           # 保留隔离目录(默认保留,便于事后分析)

跑完后用探针出数:
    python scripts/ui_perf_probe.py --logs <脚本打印的日志目录>

⚠️ 会真的启动软件:准心覆盖窗会出现在屏幕上、GSI 会占 127.0.0.1:3000、
音频设备会被初始化。若配置里开了全局热键,它们在这几十秒内是生效的。

⚠️ `--real-game-dir` 会让本次跑测写你**真实的** CS2 游戏目录(fanpai.cfg 等)。
    只有在专门验证"cfg 是否真的落到游戏目录"时才用它,默认不要开。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# PowerShell：枚举指定 PID 的可见顶层窗口并发 WM_CLOSE。
# 用 PostMessage 而不是 SendMessage —— 后者会阻塞直到窗口处理完，
# 而我们正要测量的就是"处理这条关闭消息要多久"。
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


def _coerce(value: str):
    """把 --set 的字符串值转成 JSON 里该有的类型。"""
    low = value.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _prepare_env(work: Path, overrides=None, real_game_dir: bool = False) -> dict:
    """建隔离目录，拷贝用户配置并改 close_action=exit。

    `overrides` 是 R8b-E 加的：验证一个**配置门控**的特性（比如准心渲染器）
    只能在真机跑里验，而那要求能改隔离副本里的开关。
    它还有个安全用途——把会打扰前台的开关按下去：用户真实配置里
    `magnifier_enabled=True`，原样拷过去意味着跑测这几十秒里
    **全局热键会劫持鼠标右键**。

    ⚠ `csgo_dir` 是隔离的**第三个出口**（UP-090）。上面两个环境变量管不到它：
    它是**存在配置里的一条路径**，而本函数恰恰把用户配置整个拷了过来，
    于是每跑一次真机测试，软件就往用户真实的 CS2 目录写一次 `fanpai.cfg`。
    R9 修 UP-090 时只堵了「进程内建页」的审计脚本，漏了这里——
    因为判据找的是 `MainWindow(` 构造点，而本脚本是**起子进程**跑整个软件的（UP-093）。
    """
    cfg_dir = work / "config"
    log_dir = work / "logs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    real = os.environ.get("LOCALAPPDATA")
    src = Path(real) / "FanTool" / "config.json" if real else None
    data = {}
    if src and src.is_file():
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    # 关窗默认是 "ask"（弹对话框问进托盘还是退出），自动化跑测必须改掉
    data["close_action"] = "exit"

    if real_game_dir:
        print(f"  ⚠ --real-game-dir：本次会写你真实的游戏目录 {data.get('csgo_dir')!r}")
    else:
        # 指向一个**真实存在**的沙箱目录，不能置空——置空会让页面走
        # 「未配置 CS2 目录」分支，UI 文案和行为跟着变，等于把被测对象改掉了。
        game_dir = work / "game_dir"
        (game_dir / "game" / "csgo" / "cfg").mkdir(parents=True, exist_ok=True)
        data["csgo_dir"] = str(game_dir)

    for key, value in (overrides or {}).items():
        data[key] = value
        print(f"  隔离配置覆盖: {key} = {value!r}")
    (cfg_dir / "config.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    env = dict(os.environ)
    env["FANPAI_CONFIG_DIR"] = str(cfg_dir)
    env["FANPAI_LOG_DIR"] = str(log_dir)
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
    titles = []
    for line in out.splitlines():
        if line.startswith("WINDOW\t"):
            parts = line.split("\t")
            if len(parts) >= 3:
                titles.append(parts[2])
    return titles


def run_once(env: dict, seconds: int, idx: int) -> bool:
    print(f"\n===== 第 {idx} 次 =====")
    proc = subprocess.Popen(
        [sys.executable, "main_widget.py"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"  已启动 PID={proc.pid}，观察 {seconds}s...")
    for _ in range(seconds):
        if proc.poll() is not None:
            print(f"  ⚠ 进程提前退出，退出码 {proc.returncode}")
            return False
        time.sleep(1)

    titles = _close_windows(proc.pid)
    print(f"  已向 {len(titles)} 个窗口发送 WM_CLOSE: {', '.join(titles) or '(无)'}")

    for _ in range(30):  # 最多等 30 秒走完退出链路
        if proc.poll() is not None:
            print(f"  ✅ 优雅退出，退出码 {proc.returncode}")
            return True
        time.sleep(1)

    print("  ⚠ 30 秒未退出，强制结束（退出链路数据本次不可用）")
    try:
        proc.kill()
        proc.wait(timeout=10)
    except Exception:
        pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="帆派助手 真机跑测")
    ap.add_argument("--runs", type=int, default=1, help="跑几次")
    ap.add_argument("--seconds", type=int, default=45, help="每次观察多少秒")
    ap.add_argument("--workdir", default="", help="隔离目录（默认临时目录下 fanpai_live）")
    ap.add_argument("--clean", action="store_true", help="开跑前清空隔离目录")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    metavar="KEY=VALUE",
                    help="覆盖隔离配置里的一项（可重复）。例：--set crosshair_renderer=qt")
    ap.add_argument("--real-game-dir", action="store_true",
                    help="不隔离 CS2 游戏目录，直接写用户真实的那个（默认隔离，见 UP-093）")
    args = ap.parse_args()

    overrides = {}
    for item in args.overrides:
        if "=" not in item:
            print(f"⚠ 忽略无法解析的 --set: {item}")
            continue
        key, _, value = item.partition("=")
        overrides[key.strip()] = _coerce(value)

    import tempfile

    work = Path(args.workdir) if args.workdir else Path(tempfile.gettempdir()) / "fanpai_live"
    if args.clean and work.exists():
        shutil.rmtree(work, ignore_errors=True)

    env = _prepare_env(work, overrides, real_game_dir=args.real_game_dir)
    print(f"隔离配置: {env['FANPAI_CONFIG_DIR']}")
    print(f"隔离日志: {env['FANPAI_LOG_DIR']}")
    if args.real_game_dir:
        print("⚠ 游戏目录**未隔离**：本次跑测会写你真实 CS2 目录里的 fanpai.cfg")
    else:
        print(f"隔离游戏目录: {work / 'game_dir'}")
        print("（用户真实的 %LOCALAPPDATA%\\FanTool 与真实 CS2 目录都不受影响）")

    ok = 0
    for i in range(1, args.runs + 1):
        if run_once(env, args.seconds, i):
            ok += 1
        if i < args.runs:
            time.sleep(3)  # 让上一次的子进程/端口彻底释放

    print(f"\n完成 {ok}/{args.runs} 次干净退出")
    print("\n出数：")
    print(f'  python scripts/ui_perf_probe.py --logs "{env["FANPAI_LOG_DIR"]}"')
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
