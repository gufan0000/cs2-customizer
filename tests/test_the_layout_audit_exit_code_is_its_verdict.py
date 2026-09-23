# SPDX-License-Identifier: GPL-3.0-or-later
"""排版审计的进程退出码必须等于它自己打出的裁定行。

⭐⭐ 2026-09-23 实测：完整/紧凑两档都是「`RESULT layout rc=0` 打完 → 退出码 139」，
   5/5 与 3/3。机制：`_audit_verdict.deliver` 用 `os._exit`，Windows 上它走
   `ExitProcess`、照样发 `DLL_PROCESS_DETACH`，而 Python 收尾被跳过、`QApplication`
   和整窗控件都还活着 ⇒ `Qt6Gui.dll` 卸载时析构全局对象撞上访问违例
   （向量化异常处理器抓到的模块）。最小复现（20 个控件）不崩 —— 要审计那一整张对象图。
⇒ 修在 `deliver`：`TerminateProcess` 自己，不发 DETACH。

⚠ 裁定仍以裁定行为准（RN-092/194，`scripts/gate.py` 就这么读）；这条量的是
  「退出码这个辅助信号别说谎」—— 本地直接看 `$?` 的人、以及任何只认退出码的调用方。
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from _audit_verdict import parse_verdict  # noqa: E402


def _env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # 走真门禁那条路：原生平台 + WA_DontShowOnScreen（审计自己钉），不走 conftest 的 offscreen
    env.pop("QT_QPA_PLATFORM", None)
    # 同 test_audit_can_see_every_page：别继承 conftest 那份跨用例累积的配置目录
    env.pop("CS2C_CONFIG_DIR", None)
    env.pop("CS2C_LOG_DIR", None)
    # ⚠ conftest 为 pytest 进程关掉了启动期源码备份；真门禁（bash / gate.py）不带它。
    #   实测它改变崩溃的**概率**：不带 8/8 崩，带着 1/2 —— 第一版判据继承了它，
    #   在修复前的树上照样绿（证不了任何事）。⇒ 按真门禁的环境跑。
    env.pop("CS2C_SKIP_SOURCE_BACKUP", None)
    return env


def test_the_layout_audit_exits_with_its_own_verdict(tmp_path):
    # ⚠ 不让它落到 `use_pristine_config_dir` 的固定目录 `%TEMP%/cs2customizer_layout_audit`：
    #   那个目录每次启动先整个删掉，并行的另一路（或正在跑门禁的人）会被掀掉。
    #   ⇒ 自带一份，播种方式与那个函数一致。
    from _pristine_config import PLACEHOLDER

    env = _env()
    (tmp_path / "config").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config" / "config.json").write_text(PLACEHOLDER, encoding="utf-8")
    env["CS2C_CONFIG_DIR"] = str(tmp_path / "config")
    env["CS2C_LOG_DIR"] = str(tmp_path / "logs")
    proc = subprocess.run(
        [sys.executable, "scripts/layout_overflow_audit.py"],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    verdict = parse_verdict(out, "layout")
    assert verdict is not None, (
        f"审计没活到交裁定那一步（退出码 {proc.returncode}）—— 这条判据没有分母：\n{out[-1500:]}")
    assert proc.returncode == verdict, (
        f"裁定行是 rc={verdict}，进程退出码却是 {proc.returncode} —— "
        "退出期又有东西改写了它（139 = 访问违例，多半是 Qt DLL 卸载时析构；"
        "`deliver` 最后那一下应当是 TerminateProcess，不是 os._exit）")


def test_deliver_does_not_walk_the_process_shutdown_path(tmp_path):
    """机制判据（确定性的那一条）：`deliver` 退出时不许走进程关闭路径。

    ⭐ 上一条是端到端的，但崩溃是**竞态**：修复前的树上，bash 起 11/11 崩、
      Python 子进程起 2/3、pytest 里起 1/3 —— 单跑一次证不了回退。
    ⇒ 直接量「走没走那条路」：`ExitProcess`（`os._exit` 背后）经 `LdrShutdownProcess`
      先跑 FLS 回调、再发 DLL 卸载；`TerminateProcess` 两样都不跑。
      注册一个 FLS 回调、让它落一个标记文件 —— 修复前 3/3 落、修复后 0/3。
    """
    if sys.platform != "win32":
        import pytest
        pytest.skip("FLS / DLL 卸载是 Windows 的事")
    marker = tmp_path / "shutdown_path_ran"
    probe = tmp_path / "fls_probe.py"
    probe.write_text(
        "import ctypes, ctypes.wintypes as wt, os, sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from _audit_verdict import deliver\n"
        "k32 = ctypes.WinDLL('kernel32')\n"
        "CB = ctypes.WINFUNCTYPE(None, ctypes.c_void_p)\n"
        "@CB\n"
        "def _on_shutdown(_):\n"
        f"    os.close(os.open({str(marker)!r}, os.O_CREAT | os.O_WRONLY))\n"
        "k32.FlsAlloc.argtypes = [CB]\n"
        "k32.FlsAlloc.restype = wt.DWORD\n"
        "k32.FlsSetValue.argtypes = [wt.DWORD, ctypes.c_void_p]\n"
        "idx = k32.FlsAlloc(_on_shutdown)\n"
        "assert idx != 0xFFFFFFFF\n"
        "assert k32.FlsSetValue(idx, ctypes.c_void_p(1))\n"
        "print('ARMED', flush=True)\n"
        "deliver('probe', 0)\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, env=_env())
    assert "ARMED" in proc.stdout, f"探针没装上 FLS 回调（分母为空）：\n{proc.stdout}{proc.stderr}"
    assert parse_verdict(proc.stdout, "probe") == 0, proc.stdout
    assert not marker.exists(), (
        "deliver 退出时走了进程关闭路径（FLS 回调跑了 ⇒ 接下来就是每个 DLL 的卸载例程）—— "
        "排版审计正是在那一段里被 Qt6Gui 的析构撞成退出码 139。"
        "最后那一下应当是 TerminateProcess，不是 os._exit")


def test_deliver_passes_a_red_verdict_through_unchanged(tmp_path):
    """反方向：红的裁定也要原样变成退出码（别修成一律 0）。"""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from _audit_verdict import deliver\n"
        "deliver('probe', 3)\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, env=_env())
    assert parse_verdict(proc.stdout, "probe") == 3, proc.stdout
    assert proc.returncode == 3, f"deliver('probe', 3) 的退出码是 {proc.returncode}"
