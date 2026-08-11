# -*- coding: utf-8 -*-
"""QA-001 存量纠正在**打包产物**上的端到端验证。

单测证明的是 `Config._repair_seeded_config` 这个方法的逻辑；它证明不了
冻结产物里这条路径真的会被走到（PyArmor 混淆 + PyInstaller 冻结 + 真实
启动顺序，任何一环出岔子，方法再对也白搭）。这里直接拿 exe 跑两遍：

  受害者档：种子配置的指纹 —— csgo_dir 指向本机不存在的路径 + 没有
            onboarding_completed 键 + 没纠正标记。
            期望：启动后 csgo_dir 被清空、onboarding_completed=False、
                  纠正标记落盘、日志里有 QA-001 那条 warning。

  对照档：  正常用户 —— csgo_dir 指向本机真实存在的目录 + 有
            onboarding_completed=True。
            期望：**一个字都不许改**（不误伤），且不留纠正标记。

两档都跑隔离目录，用户真实的 %LOCALAPPDATA%\\FanTool 不受影响。
关窗用 PostMessage(WM_CLOSE)（同 smoke_packaged.py），超时兜底 taskkill，
保证不留孤儿进程。

    python scripts/verify_qa001_repair_packaged.py --exe "release/帆派助手2.2.2/帆派助手.exe"

退出码：0=两档都符合预期；1=有一档不符。
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
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from smoke_packaged import _close_windows, _read_log  # noqa: E402

FLAG = "seeded_config_repaired_qa001"
# 本机一定不存在的盘符路径，模拟"从打包机抄来的 csgo_dir"
BOGUS_DIR = r"Z:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive"


def _seed(work: Path, data: dict) -> dict:
    cfg_dir, log_dir = work / "config", work / "logs"
    for d in (cfg_dir, log_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    env = dict(os.environ)
    env["FANPAI_CONFIG_DIR"] = str(cfg_dir)
    env["FANPAI_LOG_DIR"] = str(log_dir)
    return env


def _run(exe: Path, env: dict, seconds: int) -> tuple[dict, str]:
    proc = subprocess.Popen(
        [str(exe)], cwd=str(exe.parent), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"    已启动 pid={proc.pid}，观察 {seconds}s …")
    time.sleep(seconds)
    titles = _close_windows(proc.pid)
    print(f"    命中窗口: {titles}")
    try:
        proc.wait(timeout=45)
        print(f"    进程退出，退出码 {proc.returncode}")
    except subprocess.TimeoutExpired:
        print("    !! WM_CLOSE 后 45s 未退出，taskkill 兜底")
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
    cfg_path = Path(env["FANPAI_CONFIG_DIR"]) / "config.json"
    try:
        result = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"    !! 读回配置失败: {exc}")
        result = {}
    return result, _read_log(Path(env["FANPAI_LOG_DIR"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="QA-001 存量纠正的打包产物验证")
    ap.add_argument("--exe", required=True)
    ap.add_argument("--seconds", type=int, default=35)
    ap.add_argument("--workdir", default="")
    args = ap.parse_args()

    exe = Path(args.exe)
    if not exe.is_file():
        print(f"!! exe 不存在: {exe}")
        return 1

    base = Path(args.workdir) if args.workdir else \
        Path(os.environ.get("TEMP", "/tmp")) / "fanpai_qa001_e2e"

    # 用仓库根那份真实的开发机配置当种子（就是当年被打进包里的那一份）
    dev_cfg_path = ROOT / "config.json"
    dev_cfg = {}
    if dev_cfg_path.is_file():
        try:
            dev_cfg = json.loads(dev_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            dev_cfg = {}
    print(f"种子来源: {dev_cfg_path}（{len(dev_cfg)} 个键）")

    ok = True

    # ---------- 受害者档 ----------
    print("\n[1/2] 受害者档：csgo_dir 指向本机不存在的路径 + 无 onboarding_completed")
    victim = dict(dev_cfg)
    victim["csgo_dir"] = BOGUS_DIR
    victim.pop("onboarding_completed", None)
    victim.pop(FLAG, None)
    victim["close_action"] = "exit"      # 仅为自动化关窗，不影响纠正的三条判据
    env = _seed(base / "victim", victim)
    after, log = _run(exe, env, args.seconds)

    # ⚠ 判据要盯"纠正发生了没有"，不能盯"会话结束时的状态"。
    # 第一版判据写成 `csgo_dir == ""` 和 `onboarding_completed is False`，全红了——
    # 但产品是对的：纠正清空 csgo_dir 之后引导弹了出来，引导在这 35 秒里自动探测到
    # 本机真实的 CS2 目录并回填，关窗时把 onboarding_completed 置了 True。
    # 那是**理想结果**，判据却把它读成失败。改成盯纠正本身 + 盯"引导真的弹了"，
    # 并对终态只要求"要么空、要么是本机真实存在的目录"（绝不能是死路径）。
    final_dir = str(after.get("csgo_dir", "")).strip()
    # 这三条做过「回退即变红」验证：把 _repair_seeded_config 改成直接 return
    # 重打一个产物跑，三条**全部翻红**。它们是真判据。
    checks = [
        ("纠正标记已落盘", after.get(FLAG) is True),
        ("日志里有 QA-001 纠正 warning", "QA-001" in log),
        ("首次使用引导真的弹了出来", "首次使用引导已弹出" in log),
    ]
    for name, passed in checks:
        print(f"    {'✓' if passed else '✘'} {name}")
        ok = ok and passed

    # ⚠ 下面两条**不是判据**，只是现象记录。同一次回退验证里它俩在"修复被删掉"的
    # 产物上照样是绿的 —— 因为启动时的 CS2 目录自动探测本来就会把 csgo_dir 覆盖掉，
    # 跟纠正逻辑在不在没关系。留着看现象可以，拿它当判据就是自欺。
    for name, passed in [
        ("csgo_dir 不再是那个假路径", after.get("csgo_dir") != BOGUS_DIR),
        ("终态 csgo_dir 要么为空、要么在本机真实存在",
         final_dir == "" or os.path.isdir(final_dir)),
    ]:
        print(f"    {'·' if passed else '·'} {name}: {passed} （非鉴别性，仅记录）")

    # ---------- 对照档 ----------
    print("\n[2/2] 对照档：正常用户（csgo_dir 真实存在 + 已走完引导）——必须一个字都不改")
    # 扮演"用户自己的 CS2 目录"：必须真实存在，且**绝不能用仓库根** ——
    # 软件会老老实实往 <csgo_dir>/game/csgo/cfg/ 写五个 cfg，指向仓库就等于往仓库拉屎
    # （第一版就这么写的，跑完在仓库根留下一个 game/ 目录）。改用隔离目录。
    fake_cs2 = base / "fake_cs2"
    (fake_cs2 / "game" / "csgo" / "cfg").mkdir(parents=True, exist_ok=True)
    real_dir = str(fake_cs2)
    normal = dict(dev_cfg)
    normal["csgo_dir"] = real_dir
    normal["onboarding_completed"] = True
    normal.pop(FLAG, None)
    normal["close_action"] = "exit"
    env = _seed(base / "normal", normal)
    after2, log2 = _run(exe, env, args.seconds)

    checks2 = [
        ("csgo_dir 原样保留", after2.get("csgo_dir") == real_dir),
        ("onboarding_completed 仍为 True", after2.get("onboarding_completed") is True),
        ("没有留下纠正标记", after2.get(FLAG) is not True),
        ("日志里没有 QA-001 纠正 warning", "QA-001" not in log2),
        ("没有把引导弹给正常用户", "首次使用引导已弹出" not in log2),
    ]
    for name, passed in checks2:
        print(f"    {'✓' if passed else '✘'} {name}")
        ok = ok and passed

    print()
    print("== QA-001 存量纠正在打包产物上成立（受害者被救，正常用户不受影响）=="
          if ok else "== QA-001 存量纠正验证未通过 ==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
