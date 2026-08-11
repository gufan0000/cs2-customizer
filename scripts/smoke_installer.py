# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""安装态冒烟：把安装包真的装一遍、跑一遍、卸一遍，再确认卸干净了。

**为什么不能直接装正式安装包**：正式包的 `AppId` 与开发机上已装的版本相同，
且 `UsePreviousAppDir=yes` —— 双击下去就是把开发机现装的版本**覆盖升级**掉，
注册表卸载项、开始菜单、桌面快捷方式全被改写。那是真升级，不是冒烟。

所以这里用同一份 `installer.iss` 现编一个**隔离变体**：换 AppId、换安装目录、
换开始菜单组名、不建桌面图标。除这四处外与正式包**逐字相同**（同样的 [Files] /
[Icons] / [Registry] / [Code]），所以打包、铺文件、建快捷方式、卸载清理这些
逻辑测的都是真的。

跑完会核对三件"公共状态"没被动过：开发机原有的卸载注册表项、开机自启值、
桌面快捷方式。

    python scripts/smoke_installer.py

退出码：0=全部判据通过，1=有判据未通过。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ISS = ROOT / "build_tools" / "installer.iss"
SMOKE_ISS = ROOT / "build_tools" / "installer_smoketest.iss"
SMOKE_APPID = "{{71FC196A-0F18-4608-B746-0983A65518E4}}"
SMOKE_DIRNAME = r"{localappdata}\CS2CustomizerInstallSmoke\{#AppName}"
SMOKE_GROUP = "{#AppName} 安装冒烟"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "CS2Customizer"
UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def find_iscc() -> Path | None:
    for p in ISCC_CANDIDATES:
        if p.is_file():
            return p
    which = shutil.which("iscc")
    return Path(which) if which else None


# ============================================================================
# QA-018：注册表读数的**通道**可能不可信
# ============================================================================
# 2026-08-10 实测：本脚本如果跑在 MSIX/Helium 容器里（比如自动化助手的沙箱），
# `winreg` 读到的是**写时复制的影子副本**，不是真机那份。当时我据此报了一条
# 「覆盖安装后卸载注册表版本号不刷新」的产品缺陷，**整条证据链自洽、结论全错**。
#
# 对本脚本的影响要分成两半看，混在一起想就会想岔：
#
#   A. **冒烟自己建/删的键**（SMOKE_APPID 那一把）。安装器是本进程 spawn 的，
#      跟本进程在同一个容器里，它的写入落进同一份影子。所以「已登记 / 已删除」
#      这两条**必须继续用 winreg 读**——同上下文才对得上。换成容器外读反而全错。
#
#   B. **开发机原有的状态**（ CS2 Customizer 真实卸载项、开机自启值）。这是**真机事实**，
#      影子里那份可能是几个月前的旧快照。「原封不动」这句话要成立，
#      必须拿容器外的真值来对。
#
# 还有一件必须说破的事：在容器里跑时，安装器**根本够不到真实注册表**，
# 于是「没动你的机器」是被沙箱隔离保证的，**不是被安装器的良好行为保证的**。
# 判据打勾的理由和它声称的理由不是一回事 —— 这种情况要如实打印出来，
# 而不是印一个干净的 ✓ 让人以为验过了。
#
# 通道自检怎么做：先用 winreg 往 HKCU 写一个一次性标记，再让**容器外**的进程
# 回读。读得到 ⇒ 两边同一份 hive，winreg 可信；读不到 ⇒ 确认被影子化；
# 逃逸根本起不来 ⇒ 通道未知，相关判据一律记「未测」，不许算通过。

PROBE_KEY = r"Software\CS2CustomizerSmokeProbe"

_PS_DUMP = """param($OutPath)
$res = @{}
try {
  $res.probe = (Get-ItemProperty -Path 'HKCU:\\Software\\CS2CustomizerSmokeProbe' -Name marker -ErrorAction Stop).marker
} catch { $res.probe = '' }
try {
  $res.run = [string](Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name 'CS2Customizer' -ErrorAction Stop).'CS2Customizer'
} catch { $res.run = $null }
$un = @{}
Get-ChildItem 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall' -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
  $d = [string]$p.DisplayName
  if ($d -like '*CS2 Customizer*' -or $d -like '*CS2Customizer*') {
    $un[$_.PSChildName] = @($d, [string]$p.DisplayVersion, [string]$p.InstallLocation)
  }
}
$res.uninstall = $un
$res | ConvertTo-Json -Depth 5 | Set-Content -Path $OutPath -Encoding UTF8
"""


def _escaped_registry_dump(marker: str, timeout_s: int = 40) -> dict | None:
    """让**容器外**的进程读一遍注册表。返回 None 表示逃逸没起来。

    `explorer.exe` 本来就在容器外，由它 ShellExecute 起的进程也在容器外。
    在没有容器的普通机器上这条路同样能跑通，只是绕了一圈——所以不需要
    先判断"我在不在容器里"再决定走不走，直接跑，用标记回读来定性。
    """
    import json
    import tempfile
    import time

    tmp = Path(tempfile.mkdtemp(prefix="cs2customizer_regprobe_"))
    out, ps1, bat = tmp / "out.json", tmp / "dump.ps1", tmp / "run.bat"
    try:
        # BOM：脚本里有中文（Run 值名、DisplayName 过滤），PowerShell 要靠 BOM 认 UTF-8
        ps1.write_text(_PS_DUMP, encoding="utf-8-sig")
        bat.write_text(
            '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass '
            f'-WindowStyle Hidden -File "{ps1}" "{out}"\r\n',
            encoding="ascii",
        )
        subprocess.run(["explorer.exe", str(bat)], capture_output=True, timeout=20)
        for _ in range(timeout_s * 2):
            if out.is_file() and out.stat().st_size > 0:
                time.sleep(0.3)      # 等它写完
                try:
                    return json.loads(out.read_text(encoding="utf-8-sig"))
                except Exception:
                    pass
            time.sleep(0.5)
        return None
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def probe_registry_channel() -> tuple[str, dict | None]:
    """定性本进程的注册表读数可不可信。

    返回 ("direct" | "virtualized" | "unknown", 容器外读到的真值 or None)。
    """
    marker = f"smoke-{os.getpid()}-{int(Path(__file__).stat().st_mtime)}"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PROBE_KEY) as key:
            winreg.SetValueEx(key, "marker", 0, winreg.REG_SZ, marker)
    except OSError:
        return "unknown", None
    try:
        outside = _escaped_registry_dump(marker)
        if outside is None:
            return "unknown", None
        return ("direct" if outside.get("probe") == marker else "virtualized"), outside
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, PROBE_KEY)
        except OSError:
            pass


def read_run_value() -> str | None:
    """本进程（= 安装器所在上下文）看到的自启值。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except OSError:
        return None


def read_uninstall_entries() -> dict:
    """返回 {子键名: (DisplayName, DisplayVersion, InstallLocation)}，只取 CS2 Customizer 相关的。"""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINST_KEY) as root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, name) as sub:
                        def get(v):
                            try:
                                return winreg.QueryValueEx(sub, v)[0]
                            except OSError:
                                return ""
                        disp = get("DisplayName")
                        if "CS2 Customizer" in str(disp) or "CS2Customizer" in str(disp):
                            out[name] = (disp, get("DisplayVersion"), get("InstallLocation"))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def make_smoke_iss() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    orig = text
    # 替换串里有反斜杠和 {#...}，必须用 lambda 交付原文，别让 re 当转义/组引用解析
    def sub1(pattern: str, value: str, src: str) -> str:
        return re.sub(pattern, lambda _m: value, src, count=1, flags=re.M)

    text = sub1(r"^AppId=.*$", f"AppId={SMOKE_APPID}", text)
    text = sub1(r"^DefaultDirName=.*$", f"DefaultDirName={SMOKE_DIRNAME}", text)
    text = sub1(r"^DefaultGroupName=.*$", f"DefaultGroupName={SMOKE_GROUP}", text)
    text = sub1(r"^OutputBaseFilename=.*$",
                "OutputBaseFilename=CS2Customizer-Setup-{#AppVersion}_smoketest", text)
    changed = sum(1 for a, b in zip(orig.splitlines(), text.splitlines()) if a != b)
    if changed != 4:
        raise RuntimeError(f"隔离变体只应改 4 行，实际改了 {changed} 行 —— iss 结构变了，脚本要更新")
    SMOKE_ISS.write_text(text, encoding="utf-8")


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description="安装态冒烟")
    ap.add_argument("--version", default="", help="版本号；留空自动从 config.py 读")
    ap.add_argument("--seconds", type=int, default=45, help="装完后跑多少秒")
    args = ap.parse_args()

    version = args.version
    if not version:
        m = re.search(r'^\s*VERSION\s*=\s*"([^"]+)"',
                      (ROOT / "config.py").read_text(encoding="utf-8"), re.M)
        if not m:
            print("!! 读不出 VERSION")
            return 1
        version = m.group(1)

    onedir = ROOT / "release" / f"CS2 Customizer{version}"
    if not onedir.is_dir():
        print(f"!! 找不到 onedir 产物: {onedir}")
        return 1

    iscc = find_iscc()
    if not iscc:
        print("!! 找不到 ISCC.exe（Inno Setup 6）")
        return 1

    install_dir = Path(os.environ["LOCALAPPDATA"]) / "CS2CustomizerInstallSmoke" / "CS2 Customizer"
    group_dir = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows"
                 / "Start Menu" / "Programs" / "CS2 Customizer 安装冒烟")
    user_data = Path(os.environ["LOCALAPPDATA"]) / "CS2Customizer"
    desktop_lnk = Path.home() / "Desktop" / "CS2 Customizer.lnk"

    print(f"版本      : {version}")
    print(f"ISCC      : {iscc}")
    print(f"隔离安装到: {install_dir}")

    # ---- 先把注册表读数的通道定性了，再谈快照（QA-018）----
    channel, outside_before = probe_registry_channel()
    if channel == "direct":
        print("注册表通道: 直连真机 hive（标记回读成功），winreg 读数可信")
    elif channel == "virtualized":
        print("注册表通道: ⚠ **本进程被注册表虚拟化**（容器外读不到本进程写的标记）。")
        print("            冒烟自建键仍用 winreg 读（与安装器同上下文，对得上）；")
        print("            真机原有状态改用容器外读数比对。")
        print("            另注意：此时安装器**够不到真实注册表**，")
        print("            「没动你的机器」是沙箱隔离保证的，不是安装器行为保证的。")
    else:
        print("注册表通道: ⚠ **无法定性**（逃逸进程没跑起来）。")
        print("            所有关于真机注册表的判据本次一律记「未测」，不算通过。")

    # ---- 公共状态快照（卸完必须原封不动）----
    before_run = read_run_value()
    before_uninst = read_uninstall_entries()
    before_lnk = (desktop_lnk.stat().st_mtime, desktop_lnk.stat().st_size) \
        if desktop_lnk.is_file() else None
    before_cfg = (user_data / "config.json")
    before_cfg_stat = (before_cfg.stat().st_size, before_cfg.stat().st_mtime) \
        if before_cfg.is_file() else None
    print(f"快照      : 自启值={before_run!r}｜ CS2 Customizer 卸载项 {len(before_uninst)} 个｜"
          f"桌面快捷方式={'有' if before_lnk else '无'}")

    ok = True
    setup_exe = None
    try:
        print("\n[1/6] 现编隔离变体安装包")
        make_smoke_iss()
        p = run([str(iscc), f"/DAppVersion={version}", str(SMOKE_ISS)], cwd=str(ROOT))
        if p.returncode != 0:
            print((p.stdout or "")[-1500:])
            print("!! 编译失败")
            return 1
        setup_exe = ROOT / "release" / "installer" / f"CS2Customizer-Setup-{version}_smoketest.exe"
        if not setup_exe.is_file():
            print(f"!! 编译成功但找不到产物: {setup_exe}")
            return 1
        print(f"      → {setup_exe.name}（{setup_exe.stat().st_size/1024/1024:.1f} MB）")

        print("\n[2/6] 静默安装（不建桌面图标）")
        p = run([str(setup_exe), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                 "/NORESTART", "/TASKS="])
        print(f"      安装程序退出码 {p.returncode}")

        print("\n[3/6] 核对安装结果")
        exe = install_dir / "CS2 Customizer.exe"
        checks = [
            ("安装目录已建立", install_dir.is_dir()),
            ("主程序 exe 在位", exe.is_file()),
            ("_internal 目录在位", (install_dir / "_internal").is_dir()),
            ("**装出来的目录里没有 config.json**",
             not (install_dir / "_internal" / "config.json").exists()
             and not (install_dir / "config.json").exists()),
            ("开始菜单组已建立", group_dir.is_dir()),
            ("没有偷建桌面快捷方式（原有的没被改）",
             (desktop_lnk.stat().st_mtime, desktop_lnk.stat().st_size) == before_lnk
             if before_lnk else not desktop_lnk.exists()),
            ("卸载注册表项已登记",
             any(k not in before_uninst for k in read_uninstall_entries())),
        ]
        for name, passed in checks:
            print(f"      {'✓' if passed else '✘'} {name}")
            ok = ok and passed

        if exe.is_file():
            print("\n[4/6] 跑装出来的那份（复用打包冒烟的判据）")
            p = run([sys.executable, "scripts/smoke_packaged.py",
                     "--exe", str(exe), "--seconds", str(args.seconds)],
                    cwd=str(ROOT), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            tail = (p.stdout or "").strip().splitlines()
            for ln in tail[-14:]:
                print("      " + ln)
            print(f"      冒烟退出码 {p.returncode}")
            ok = ok and p.returncode == 0
        else:
            ok = False

        print("\n[5/6] 静默卸载")
        unins = install_dir / "unins000.exe"
        if unins.is_file():
            p = run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
            print(f"      卸载程序退出码 {p.returncode}")
            # Inno 卸载器会 spawn 自身副本后立即返回，等目录真的消失
            import time
            for _ in range(60):
                if not install_dir.exists():
                    break
                time.sleep(1)
        else:
            print("      ✘ 找不到卸载程序")
            ok = False
    finally:
        if SMOKE_ISS.exists():
            SMOKE_ISS.unlink()
        if setup_exe and setup_exe.is_file():
            setup_exe.unlink()
        print("\n      （已清理临时 iss 与临时安装包）")

    print("\n[6/6] 核对卸载干净 + 公共状态没被动过")
    after_uninst = read_uninstall_entries()

    # 冒烟自建键：与安装器同上下文（winreg）比对——这一半的通道天然是对的
    final = [
        ("安装目录已删除", not install_dir.exists()),
        ("开始菜单组已删除", not group_dir.exists()),
        ("冒烟的卸载注册表项已删除",
         set(after_uninst) == set(before_uninst)),
        ("**用户配置被保留**（设计如此）",
         before_cfg_stat is None or
         (before_cfg.is_file() and
          (before_cfg.stat().st_size, before_cfg.stat().st_mtime) == before_cfg_stat)),
        ("桌面快捷方式原封不动",
         ((desktop_lnk.stat().st_mtime, desktop_lnk.stat().st_size) == before_lnk)
         if before_lnk else not desktop_lnk.exists()),
    ]
    for name, passed in final:
        print(f"      {'✓' if passed else '✘'} {name}")
        ok = ok and passed

    # 真机原有状态：必须拿容器外的真值对，对不上就如实说测不了（QA-018）
    print("      ---- 以下三条关于**真机**注册表，走独立通道 ----")
    if channel == "unknown":
        # ⚠ 这里绝不能印 ✓。静默少测会被读成"全都覆盖了"，
        # 而"我确认没动你的机器"是本脚本最该负责的一句话。
        for name in ("开发机原有的卸载项原封不动", "开机自启值原封不动"):
            print(f"      ⚠ 未测 {name}（注册表通道无法定性，本次不作结论）")
        ok = False
    elif channel == "direct":
        for name, passed in (("开发机原有的卸载项原封不动", after_uninst == before_uninst),
                             ("开机自启值原封不动", read_run_value() == before_run)):
            print(f"      {'✓' if passed else '✘'} {name}（直连真机）")
            ok = ok and passed
    else:
        outside_after = _escaped_registry_dump("n/a")
        if outside_after is None or outside_before is None:
            print("      ⚠ 未测 真机注册表（虚拟化已确认，但卸载后那次逃逸没起来）")
            ok = False
        else:
            for name, before, after in (
                ("开发机原有的卸载项原封不动",
                 outside_before.get("uninstall"), outside_after.get("uninstall")),
                ("开机自启值原封不动",
                 outside_before.get("run"), outside_after.get("run")),
            ):
                passed = before == after
                print(f"      {'✓' if passed else '✘'} {name}（容器外真值比对）")
                ok = ok and passed
            print("      ℹ 提醒：本次安装器跑在容器内，物理上够不到真实注册表——")
            print("        上面两条成立是**沙箱隔离**的功劳，不足以证明安装器本身规矩。")

    print()
    print("== 安装态冒烟全部通过 ==" if ok else "== 安装态冒烟未通过 ==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
