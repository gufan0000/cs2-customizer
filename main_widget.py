#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
CS2 Customizer 2.0 - Widget版本
主入口文件
"""

import time as _boot_time

_BOOT_T0 = _boot_time.perf_counter()  # 启动相位计时起点(必须先于一切重 import)

import sys
import os
import multiprocessing
import ctypes
import threading
import traceback
import re
from datetime import datetime
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


APP_NAME = "CS2Customizer"
# 版本无关：AUMID 应跨版本稳定，避免任务栏固定/归类随版本丢失（原来硬编码 2_1_0 与实际版本不一致）
APP_USER_MODEL_ID = "CS2Customizer.App"


def _resolve_runtime_log_dir() -> Path:
    """优先写入 AppData，避免在 EXE 目录下创建 logs。

    必须与 `core/utils/logger.LoggerManager._resolve_log_dir()` 保持同一套口径，
    包括认 `CS2C_LOG_DIR` 覆盖。R4 实测发现两处不一致：logger 认这个变量、
    这里不认，于是 `scripts/live_run.py` 声称"隔离运行、不碰用户真实目录"，
    实际每跑一次都往用户真实的 `%LOCALAPPDATA%\\CS2Customizer\\logs\\native_crash.log`
    追加一次会话记录。诊断文件写错地方，比不写更糟——它会污染真实的崩溃取证材料。
    """
    override_dir = os.environ.get("CS2C_LOG_DIR")
    if override_dir:
        return Path(override_dir)
    appdata_dir = os.environ.get("LOCALAPPDATA")
    if appdata_dir:
        return Path(appdata_dir) / APP_NAME / "logs"
    return Path("logs")


# ==================== 原生崩溃栈捕获（faulthandler）====================
# 背景：极少数机器崩在 ucrtbase.dll / 0xc0000409（abort/fail-fast），进程静默
# 消失、无 Python 异常。abort() 会 raise SIGABRT——faulthandler 能在进程死前把
# 触发 abort 的那行 Python 调用栈（全线程）dump 到文件，让原生崩溃变得可诊断。
# 必须尽早启用（先于一切重 import），才能覆盖导入期/启动期的原生崩溃。
_FAULT_LOG_FP = None


#: 已知良性的首次机会异常（UP-088）。
#: `0x8001010d` = RPC_E_CANTCALLOUT_ININPUTSYNCCALL。实测（`scripts/probe_r9b_splash.py`）：
#: **每个进程第一次显示顶层窗口时必出一条**，与闪屏无关——换裸 QWidget、加 Qt.Tool、
#: 关掉无障碍桥、连开两个窗口，结论都一样（连开两个也只出一次 ⇒ 一次性 COM 初始化）。
#: faulthandler 记的是**首次机会**异常，Windows 自己会处理掉它，进程不受影响
#: （退出码 0、优雅关闭）。压不住它，但可以不让它把真崩溃淹了。
_BENIGN_FIRST_CHANCE = ("0x8001010d",)

#: 压缩后最多保留多少个"有内容"的会话块。超出丢最旧的，并在头部写明丢了多少——
#: 静默截断会被读成"历史就这么多"。
_CRASH_LOG_KEEP_BLOCKS = 200

_SESSION_MARK = "===== 会话启动"
_COMPACT_MARK = "===== 已压缩"

# 读回上一轮压缩头里的计数，做累计——否则每启动一次就多一段说明，
# 堆到最后又是一堆噪声，跟压缩本身的目的正相反。
_RE_EMPTY_COUNT = re.compile(r"丢弃空会话块 (\d+) 个")
_RE_BENIGN_COUNT = re.compile(r"折叠良性首次机会异常 (\d+) 次")
_RE_BENIGN_RANGE = re.compile(r"：(.+?) → (.+?)$")


def _compact_native_crash_log(path: Path) -> None:
    """开新会话前压缩 `native_crash.log`（UP-088）。

    **为什么需要**：这个文件是给人翻的取证材料，但它的信噪比一直是坏的——
    一次启动会写 **3 条**"会话启动"横幅（主进程 + 两个子进程），其中两条永远是空的；
    主进程那条后面还必跟一条良性的 `0x8001010d`。实测用户机上 103 条横幅里
    只有 13 条真带故障，而那 13 条里 6 条是这个良性异常。真正值得看的
    7 条 access violation 就埋在这堆东西里。

    压缩规则（**只删噪声，不删证据**）：
      - 空会话块（只有横幅没有任何故障）→ 丢弃，只在头部记个数；
      - 只含良性首次机会异常的块 → 折叠成一行计数，保留首末时间；
      - 其余一律原样保留。

    安全性：先写临时文件再 `os.replace` 原子替换；必须在以 append 模式打开
    句柄**之前**调用；任何异常都吞掉——诊断设施坏了也不能让软件起不来。
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return

    try:
        lines = text.splitlines()
        blocks: list[list[str]] = []
        preamble: list[str] = []
        for line in lines:
            if line.startswith(_SESSION_MARK):
                blocks.append([line])
            elif blocks:
                blocks[-1].append(line)
            else:
                preamble.append(line)

        kept: list[list[str]] = []
        empty_count = 0
        benign_count = 0
        benign_first = benign_last = ""

        # 上一轮压缩留下的头部要**吸收进来**，不能原样留着——否则每启动一次就
        # 多一段"已压缩"说明，堆到最后又是一堆噪声，跟这个函数的目的正相反。
        # 做法是把旧头里的计数加到本轮里，最终只留一段累计的说明。
        leftovers: list[str] = []
        for line in preamble:
            if line.startswith(_COMPACT_MARK):
                continue                      # 旧的压缩标题行，丢掉
            if not line.startswith("#"):
                leftovers.append(line)        # 不是压缩说明 ⇒ 是真的日志内容
                continue
            m = _RE_EMPTY_COUNT.search(line)
            if m:
                empty_count += int(m.group(1))
            m = _RE_BENIGN_COUNT.search(line)
            if m:
                benign_count += int(m.group(1))
                span = _RE_BENIGN_RANGE.search(line)
                if span:
                    benign_first = benign_first or span.group(1).strip()
                    benign_last = span.group(2).strip()
            # 其余 # 开头的说明行（如保留上限）不累计，直接丢弃

        # 文件开头真正属于日志内容的部分（老版本留下的）一律保留
        if any(ln.strip() for ln in leftovers):
            kept.append(leftovers)

        for block in blocks:
            body = "\n".join(block[1:])
            if not body.strip():
                empty_count += 1
                continue
            has_fault = "fatal exception" in body
            only_benign = has_fault and all(
                (tag in body) for tag in _BENIGN_FIRST_CHANCE
            ) and body.count("fatal exception") == 1
            if only_benign:
                benign_count += 1
                # 只剥两端的 "====="，别把 "pid=1234" 里的等号也剥了
                stamp = block[0][len(_SESSION_MARK):].strip().rstrip("=").strip()
                benign_first = benign_first or stamp
                benign_last = stamp
                continue
            kept.append(block)

        dropped_old = max(0, len(kept) - _CRASH_LOG_KEEP_BLOCKS)
        if dropped_old:
            kept = kept[-_CRASH_LOG_KEEP_BLOCKS:]

        if not (empty_count or benign_count or dropped_old):
            return  # 没有可压的东西，别动文件

        header = [
            f"{_COMPACT_MARK} {datetime.now():%Y-%m-%d %H:%M:%S}（累计）=====",
            f"# 丢弃空会话块 {empty_count} 个（只有启动横幅、没有任何故障）",
        ]
        if benign_count:
            header.append(
                f"# 折叠良性首次机会异常 {benign_count} 次"
                f"（{'/'.join(_BENIGN_FIRST_CHANCE)}，每进程首个窗口必出一条，"
                f"见 UP-088）：{benign_first} → {benign_last}"
            )
        if dropped_old:
            header.append(f"# 因超出保留上限丢弃最旧的有内容块 {dropped_old} 个")
        header.append("")

        # 每块末尾的空行要削掉再统一补一个：不削的话，每压一轮就多留一行，
        # 空行也会像压缩标题一样逐轮增殖。
        def _trim(block: list[str]) -> str:
            while block and not block[-1].strip():
                block = block[:-1]
            return "\n".join(block)

        out = "\n".join(header + [_trim(b) + "\n" for b in kept]) + "\n"
        # **原地重写**，不用「临时文件 + os.replace」。
        # 原子替换会换掉 inode，而本进程和各子进程都以 append 模式握着这个文件的句柄，
        # 替换之后那些句柄指向的是已被删除的旧 inode——之后真崩溃了，dump 会写进
        # 一个谁也看不到的地方。append 模式每次都写到"当前文件末尾"，
        # 所以原地截断重写不会打乱任何一个已有句柄。
        with open(path, "r+", encoding="utf-8") as fp:
            fp.seek(0)
            fp.write(out)
            fp.truncate()
    except Exception:
        pass


def _enable_faulthandler() -> None:
    global _FAULT_LOG_FP
    try:
        import faulthandler

        log_dir = _resolve_runtime_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        crash_path = log_dir / "native_crash.log"
        # 只在**主进程**压一次。子进程是 multiprocessing spawn 重新 import 本模块起来的，
        # 会把这段再跑一遍；环境变量随 spawn 继承下去，于是子进程自动跳过。
        # （不这么做的话，闪光/击杀图标子进程会在主进程已经握着句柄之后再压一次。）
        if not os.environ.get("_CS2C_CRASHLOG_COMPACTED"):
            _compact_native_crash_log(crash_path)
            os.environ["_CS2C_CRASHLOG_COMPACTED"] = "1"
        # 追加模式常开：文件句柄需在进程生命周期内保持存活，faulthandler 才能写入
        _FAULT_LOG_FP = open(crash_path, "a", encoding="utf-8", buffering=1)
        try:
            # 带上 PID：一次启动有主进程和多个子进程各写一条，不标 PID 分不清谁是谁
            _FAULT_LOG_FP.write(
                f"\n{_SESSION_MARK} {datetime.now():%Y-%m-%d %H:%M:%S} pid={os.getpid()} =====\n"
            )
            _FAULT_LOG_FP.flush()
        except Exception:
            pass
        faulthandler.enable(file=_FAULT_LOG_FP, all_threads=True)
    except Exception:
        # 诊断设施本身绝不能影响启动
        pass


_enable_faulthandler()


def _set_windows_app_user_model_id() -> None:
    """确保 Windows 任务栏正确归类并显示应用图标。"""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _resolve_icon_path() -> Path | None:
    """解析运行时图标路径（源码模式 + PyInstaller 模式）。"""
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "icon.ico")
        candidates.append(Path(meipass) / "myicon.ico")

    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "icon.ico")
    candidates.append(script_dir / "myicon.ico")
    candidates.append(Path.cwd() / "icon.ico")
    candidates.append(Path.cwd() / "myicon.ico")

    for path in candidates:
        if path.exists():
            return path
    return None


def _resolve_splash_path() -> Path | None:
    """解析运行时启动图路径（源码模式 + PyInstaller 模式）。"""
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "splash.png")

    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "splash.png")
    candidates.append(Path.cwd() / "splash.png")

    for path in candidates:
        if path.exists():
            return path
    return None


def _is_onefile_bundle() -> bool:
    """onefile 打包版才带 PyInstaller 的 Tk 闪屏(pyi_splash 模块)。
    onedir(安装包形态)与源码运行都取不到,需要 Qt 自绘启动图。"""
    try:
        import pyi_splash  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _show_qt_splash(app):
    """在主窗构建前显示一张 Qt 启动图，返回 QSplashScreen(或 None)。
    仅在非 onefile(onedir 安装版 / 源码)时显示——onefile 已有 Tk 闪屏，避免重复。"""
    if _is_onefile_bundle():
        return None
    try:
        splash_path = _resolve_splash_path()
        if not splash_path:
            return None
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QSplashScreen
        from PySide6.QtCore import Qt

        pixmap = QPixmap(str(splash_path))
        if pixmap.isNull():
            return None
        splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
        splash.show()
        app.processEvents()
        return splash
    except Exception:
        return None


def _safe_console_print(message: str) -> None:
    """在 --windowed 场景下安全输出，不依赖 sys.stdout.buffer。"""
    stream = sys.stdout or sys.stderr
    if stream is None:
        return
    try:
        stream.write(f"{message}\n")
        stream.flush()
    except Exception:
        pass


def _write_bootstrap_crash(exc_type, exc_value, exc_tb) -> None:
    """尽早记录未捕获异常，覆盖导入期和启动期故障。"""
    try:
        log_dir = _resolve_runtime_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        crash_file = log_dir / f"bootstrap_crash_{ts}.log"
        crash_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_file.write_text(crash_text, encoding="utf-8")
        _safe_console_print(f"[FATAL] 未捕获异常，详情已写入: {crash_file.resolve()}")
    except Exception:
        # 启动期兜底，避免异常处理再次抛错导致静默退出
        pass


_ORIGINAL_EXCEPTHOOK = sys.excepthook


def _bootstrap_excepthook(exc_type, exc_value, exc_tb):
    _write_bootstrap_crash(exc_type, exc_value, exc_tb)
    try:
        if _ORIGINAL_EXCEPTHOOK:
            _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_tb)
    except Exception:
        pass


sys.excepthook = _bootstrap_excepthook


if hasattr(threading, "excepthook"):
    _ORIGINAL_THREAD_EXCEPTHOOK = threading.excepthook

    def _bootstrap_thread_excepthook(args):
        _write_bootstrap_crash(args.exc_type, args.exc_value, args.exc_traceback)
        try:
            if _ORIGINAL_THREAD_EXCEPTHOOK:
                _ORIGINAL_THREAD_EXCEPTHOOK(args)
        except Exception:
            pass

    threading.excepthook = _bootstrap_thread_excepthook


# ==================== 显示层加固：首次渲染原生崩溃兜底 ====================
# 背景：极少数机器在 window.show()（主窗首次绘制到屏幕）瞬间原生崩溃——
# 多为显卡驱动/DWM 渲染路径不兼容，或分数 DPI 缩放触发 Qt 渲染异常。
# 这类崩溃不走 Python 异常（excepthook 抓不到），进程直接消失、无报错。
# 策略：
#   1) 渲染前写哨兵、渲染成功后删除；下次启动若哨兵仍在＝上次死在渲染，
#      自动切「软件渲染兼容模式」并持久记住，实现「第二次启动自愈」。
#   2) 兼容模式亦可手动开启：--safe / CS2C_SAFE_MODE=1 / safe_mode.flag。
# 正常机器永不崩在此步，哨兵每次都清掉，兼容模式永不触发——对绝大多数用户零影响。


def _app_data_dir() -> Path:
    appdata_dir = os.environ.get("LOCALAPPDATA")
    if appdata_dir:
        return Path(appdata_dir) / APP_NAME
    return Path(".")


def _render_sentinel_path() -> Path:
    return _app_data_dir() / "render_attempt.flag"


def _safe_render_pref_path() -> Path:
    return _app_data_dir() / "safe_render.on"


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_safe_mode_requested() -> bool:
    """兼容模式是否被显式请求：命令行 / 环境变量 / 标志文件 / 持久偏好。"""
    try:
        for arg in sys.argv[1:]:
            if str(arg).lower() in ("--safe", "--safe-mode", "/safe"):
                return True
        if str(os.environ.get("CS2C_SAFE_MODE", "")).strip().lower() in ("1", "true", "yes", "on"):
            return True
        for marker in (_exe_dir() / "safe_mode.flag", _app_data_dir() / "safe_mode.flag", _safe_render_pref_path()):
            try:
                if marker.exists():
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _mark_render_start() -> None:
    """window.show() 前落哨兵——渲染崩溃后它会残留，成为下次启动的自愈线索。"""
    try:
        path = _render_sentinel_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    except Exception:
        pass


def _mark_render_ok() -> None:
    """窗口成功可见——清掉哨兵，表示本次渲染健康。"""
    try:
        _render_sentinel_path().unlink(missing_ok=True)  # type: ignore[call-arg]
    except Exception:
        pass


def _persist_safe_render_pref() -> None:
    try:
        path = _safe_render_pref_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("auto-enabled after render crash\n", encoding="utf-8")
    except Exception:
        pass


def _apply_display_hardening(logger=None):
    """在 QApplication 构造前应用显示层加固。返回 (safe_mode, auto_recovered)。
    任何一步失败都吞掉，绝不因加固本身把用户挡在门外。"""
    def _log(msg):
        if logger:
            try:
                logger.info(msg)
            except Exception:
                pass

    # 高 DPI 取整策略：规避分数缩放（如 1707x912）下的 Qt 渲染异常。
    # 可用 CS2C_DPI_ROUNDING 覆盖；默认 PassThrough（贴合 Windows 实际缩放，
    # 避免 Qt 二次取整与后备缓冲尺寸不一致）。对整数缩放用户为无感操作。
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt

        policy_name = str(os.environ.get("CS2C_DPI_ROUNDING", "PassThrough")).strip()
        policy_map = {
            "PassThrough": Qt.HighDpiScaleFactorRoundingPolicy.PassThrough,
            "Round": Qt.HighDpiScaleFactorRoundingPolicy.Round,
            "Floor": Qt.HighDpiScaleFactorRoundingPolicy.Floor,
            "Ceil": Qt.HighDpiScaleFactorRoundingPolicy.Ceil,
            "RoundPreferFloor": Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor,
        }
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            policy_map.get(policy_name, Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        )
        _log(f"显示加固：高DPI取整策略={policy_name}")
    except Exception as exc:
        _log(f"高DPI取整策略设置失败(忽略): {exc}")

    # 判定是否进入兼容模式：显式请求，或上次启动死在渲染（哨兵残留）。
    explicit = _is_safe_mode_requested()
    auto_recovered = False
    if not explicit:
        try:
            if _render_sentinel_path().exists():
                auto_recovered = True
                _persist_safe_render_pref()  # 持久记住，避免正常/崩溃反复横跳
                _log("显示加固：检测到上次启动在渲染阶段异常退出，本次自动切换兼容(软件渲染)模式")
        except Exception:
            pass

    safe_mode = explicit or auto_recovered
    if safe_mode:
        try:
            # 兼容模式 = 一揽子最大化兼容，覆盖首次渲染原生崩溃的两类主因：
            #   1) 显卡驱动/DWM：软件渲染 + 关 GPU + 关 DPI 缩放
            #      （等效 Windows「替代高DPI→应用程序」）
            #   2) 字体(DirectWrite) abort：强制 FreeType 字体引擎，绕开系统字体栈
            #      —— 用户实测崩在 ucrtbase.dll/0xc0000409(abort)，正是此类的典型特征
            # setdefault 保留用户已显式设置的值。
            os.environ.setdefault("QT_OPENGL", "software")
            os.environ.setdefault("QSG_RHI_BACKEND", "software")
            os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
            os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
            from PySide6.QtCore import Qt, QCoreApplication

            try:
                QCoreApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
            except Exception:
                pass
            os.environ["CS2C_SAFE_MODE_ACTIVE"] = "1"
            _log("显示加固：🛡️ 兼容模式已启用（软件渲染 / 关GPU / 关DPI缩放 / FreeType字体）")
        except Exception as exc:
            _log(f"兼容模式应用失败(忽略): {exc}")

    return safe_mode, auto_recovered


def _install_qt_message_handler(logger) -> None:
    """把 Qt 自身的 qDebug/qWarning/qCritical/qFatal 路由进日志文件。
    关键价值：qFatal() 会 abort() 进程（表现为 ucrtbase.dll / 0xc0000409），
    其致命原因原本只写 stderr——windowed 打包下彻底丢失。接管后能在崩溃前
    把真正的致命信息落到日志，让"静默消失"变成可诊断。"""
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def _handler(mode, context, message):
            try:
                text = str(message)
                if mode == QtMsgType.QtFatalMsg:
                    logger.error(f"[Qt致命/即将abort] {text}")
                    # 额外落一份崩溃文件，突出可见
                    _write_bootstrap_crash(RuntimeError, RuntimeError(f"Qt fatal: {text}"), None)
                elif mode == QtMsgType.QtCriticalMsg:
                    logger.error(f"[Qt严重] {text}")
                elif mode == QtMsgType.QtWarningMsg:
                    logger.warning(f"[Qt警告] {text}")
                else:
                    logger.debug(f"[Qt] {text}")
            except Exception:
                pass

        qInstallMessageHandler(_handler)
    except Exception as exc:
        try:
            logger.warning(f"Qt消息处理器安装失败(忽略): {exc}")
        except Exception:
            pass


# 权限策略（2.1.3 强制管理员重构）：
# 默认以普通权限启动，不再在启动时自动提权——实测普通权限即可使用
# 全屏放大与全局热键（详见 core/utils/elevation.py 模块说明）。
# 仅当放大镜初始化失败或游戏以管理员运行时，由 UI 引导用户
# 「以管理员身份重启」（高级设置页 / 开镜放大页）。
from core.utils.elevation import is_admin

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from core.utils.logger import get_logger

# GSI相关导入

# 资源管理


# 道具瞄点

# 版本信息
from config import VERSION, config


# LoadingDialog 已移除 - 使用快速启动策略


# ---------------- 启动相位计时(2.2.0 体验轮) ----------------
# 口径:_BOOT_T0 在文件最顶部(先于一切重 import);bootloader 段由外部测量。
# 每相位一行日志,毫秒级——优化前先看清钱花在哪。
_BOOT_LAST = [_BOOT_T0]


def _boot_phase(name: str) -> None:
    try:
        now = _boot_time.perf_counter()
        step = (now - _BOOT_LAST[0]) * 1000
        total = (now - _BOOT_T0) * 1000
        _BOOT_LAST[0] = now
        get_logger().info(f"[启动相位] {name}: +{step:.0f}ms (累计 {total:.0f}ms)")
    except Exception:
        pass


def main():
    logger = get_logger()
    _boot_phase("imports就绪")
    logger.info("=" * 60)
    logger.info(f"CS2 Customizer {VERSION} - Widget版 (PySide6) - 快速启动模式")
    logger.info(f"权限模式: {'管理员' if is_admin() else '普通用户（默认）'}")
    logger.info("=" * 60)

    _set_windows_app_user_model_id()

    # 显示层加固：必须在 QApplication 构造前——高DPI取整策略/软件渲染属性
    # 只有构造前设置才生效。返回是否处于兼容模式（含上次渲染崩溃后的自愈）。
    _safe_mode, _auto_recovered = _apply_display_hardening(logger)

    # 创建应用
    # 注意：Qt6 默认启用高 DPI 支持，无需手动设置
    # AA_EnableHighDpiScaling 和 AA_UseHighDpiPixmaps 在 Qt6 中已废弃
    app = QApplication(sys.argv)
    app.setApplicationName("CS2 Customizer")
    app.setOrganizationName("CS2Customizer")
    # 尽早接管 Qt 消息：捕获 window.show() 首次渲染时可能的 qFatal(abort) 原因
    _install_qt_message_handler(logger)
    _boot_phase("QApplication")

    # R1-1: 界面字号缩放——必须在 MainWindow 构建/主题首次应用前生效
    try:
        from ui_design_system import apply_font_scale
        apply_font_scale(getattr(config, "ui_font_scale", 1.0))
    except Exception as _fs_exc:
        logger.warning(f"字号缩放应用失败(已回退默认): {_fs_exc}")

    # R3-3: 匿名使用统计(默认关;开启时启动 60s 后后台发送,24h 限一条)
    try:
        from core.usage_reporter import schedule_startup_report
        schedule_startup_report(60)
    except Exception as _ur_exc:
        logger.warning(f"使用统计调度失败(忽略): {_ur_exc}")

    # 2.2.0: 开机自启升级自愈——exe 名带版本号,覆盖升级后注册表指向旧路径,启动时自查重写
    try:
        from core.utils.autostart import refresh_if_enabled
        refresh_if_enabled()
    except Exception as _as_exc:
        logger.warning(f"自启自愈检查失败(忽略): {_as_exc}")

    # ==================== D2: 单实例互斥锁 ====================
    # 设计：锁机制任何异常都默认放行，绝不把用户锁在门外
    try:
        from core.single_instance import ensure_single_instance
        _si_ok, _si_lock, _si_msg = ensure_single_instance()
        if not _si_ok:
            QMessageBox.information(None, "CS2 Customizer", _si_msg)
            logger.info("检测到已有 CS2 Customizer 实例在运行，当前进程退出")
            sys.exit(0)
        # 把锁挂到 app 上，整个进程生命周期保持强引用
        if _si_lock is not None:
            app._cs2customizer_single_instance_lock = _si_lock  # type: ignore[attr-defined]
            logger.info("✅ 单实例锁已获取")
    except Exception as _si_exc:
        logger.warning(f"单实例检测异常（已放行）: {_si_exc}")

    # ==================== 常驻度量埋点（UP-002 / UP-003）====================
    # 位置有讲究,必须同时满足两条:
    # 1. 在单实例守卫之后。否则用户重复双击图标时,第二个进程会往"正在运行的那个
    #    实例"的当天日志里插入一段伪造会话(横幅 + 一行内存采样)才被挡掉退出,
    #    ui_perf_probe 按横幅切会话,真实的长会话会被从中间截断、内存斜率算错。
    # 2. 在 MainWindow 构建之前。主窗构建那 1.9~5.0 秒是启动期最大的一段主线程
    #    停顿,原先探测器在 window.show() 之后才起,恰好把它整段漏掉。
    # 传入 _BOOT_T0 让"启动后 Xs"与[启动相位]共用同一条时间轴。
    try:
        from core.utils.jank_monitor import start_jank_monitor
        start_jank_monitor(app, t0=_BOOT_T0)
    except Exception:
        pass  # 诊断设施绝不能影响启动

    try:
        from core.utils.mem_monitor import start_mem_monitor
        start_mem_monitor(app, t0=_BOOT_T0)
    except Exception:
        pass

    # UP-005/D-12: 用户空闲侦测器。静默预载靠它判断"现在能不能干后台活",
    # 用户一有输入就让路。必须在页面预载开始前装好。
    try:
        from core.utils.idle_watcher import start_idle_watcher
        start_idle_watcher(app)
    except Exception as _iw_exc:
        # 不能静默:装不上就意味着预载退化为"无门控",卡顿治理整个失效,
        # 而现象和"没改过"一模一样,排查时会完全找不到线索。
        logger.warning(f"空闲侦测器安装失败，预载将退化为无让路模式: {_iw_exc}")

    # UP-008（本轮回退，2026-08-07）：曾在此起后台线程预热 GSI 组件 import
    # （实测那批 import 合计 1695ms，正是"窗口画出来了却冻 1.5 秒"的直接来源）。
    # 对抗式复核实测推翻了这个做法，三条理由：
    #   1. gsi_handler_kills.py:8 是模块级 `audio_manager = get_runtime_audio_manager()`，
    #      顺着 AudioManager.__init__:109 直接 pygame.mixer.init() ——预热线程等于把
    #      **音频设备初始化搬到后台守护线程**，设备归属与回调线程亲和性都变了。
    #      对一个以音频为核心的软件，这个风险不能在没有真机验证的情况下上线。
    #   2. 这批模块还会拉入 pygame/SDL，与 window.show() 首次渲染并发，正是本仓库
    #      记录在案的原生崩溃路径（CS2C_SAFE_MODE_ACTIVE 兼容模式因此存在）。
    #   3. 复核实测 show() 之前只剩约 80ms 余量，join 超时兜底反而可能变成静默冻结。
    # UP-008 真正需要的是结构性改法（把 GSI 构造异步化 / 让 audio_manager 惰性初始化），
    # 不是抢跑 import。已退回问题清单，留待带真机验证的轮次再做。

    # UP-004: 过期日志清理。必须显式调用——放在 Logger.__init__ 里会变成 import
    # 副作用,连打包脚本 collect_submodules("core") 都会触发并删掉打包机的历史日志。
    try:
        logger.start_maintenance()
    except Exception:
        pass

    # ==================== D1: 信号兼容的优雅退出 ====================
    # SIGTERM / SIGINT 时触发 Qt 顶级窗口 close()，让已有 closeEvent 执行
    # 异常时自动降级为 Python 默认行为（SIGINT → KeyboardInterrupt，SIGTERM → 直接退）
    try:
        from core.shutdown import install_signal_handlers
        if install_signal_handlers():
            logger.info("✅ 优雅退出信号处理器已安装")
    except Exception as _sd_exc:
        logger.warning(f"优雅退出处理器安装异常（已降级）: {_sd_exc}")

    icon_path = _resolve_icon_path()
    app_icon = QIcon()
    if icon_path:
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
        logger.info(f"应用图标已加载: {icon_path}")
    else:
        logger.warning("未找到 icon.ico/myicon.ico，任务栏图标可能显示异常")

    # 启动图：onedir 安装版无 Tk 闪屏，用 Qt 自绘同一张 splash.png 顶住主窗构建的空窗期
    _qt_splash = _show_qt_splash(app)

    # ==================== 阶段 1: 快速显示主窗口 ====================
    logger.info("🚀 阶段 1: 快速显示主窗口...")
    
    # 立即创建主窗口（懒加载）
    # 2.2.0 启动提速:GSI/Flask/资源管理器的 import(相位实测 ~630ms)原先卡在
    # 窗口显示之前,但它们 300ms 后的后台阶段才用到——整块移到 show 之后。
    from gui_widget import MainWindow

    window = MainWindow(auto_background_preload=False)
    _boot_phase("主窗构建")
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)

    # 首次渲染哨兵：show() 若原生崩溃（显卡驱动/DWM），哨兵残留，
    # 下次启动 _apply_display_hardening 据此自动切兼容模式。成功可见即清除。
    _mark_render_start()

    # 立即显示窗口（用户可见！）
    window.show()
    QApplication.processEvents()
    _mark_render_ok()
    _boot_phase("窗口可见")
    if _safe_mode:
        logger.info(f"🛡️ 当前处于兼容(软件渲染)模式 (自愈触发={_auto_recovered})")

    # 2.2.0: 闪屏关闭——窗口已可见,品牌闪屏退场
    # onefile: 关闭 PyInstaller Tk 闪屏
    try:
        import pyi_splash  # type: ignore  # noqa: F401

        pyi_splash.close()
    except Exception:
        pass
    # onedir/源码: 关闭 Qt 启动图（淡出交接到主窗）
    if _qt_splash is not None:
        try:
            _qt_splash.finish(window)
        except Exception:
            try:
                _qt_splash.close()
            except Exception:
                pass

    logger.info("✅ 主窗口已显示")

    # 卡顿探测器已在 QApplication 创建后启动(UP-002),此处不再重复。

    # ==================== 阶段 2 & 3: 后台加载 ====================
    # 初始化GSI组件（后台加载器会用到;import 移到此处见上方注释）
    from gsi_server import GSIServer
    from gsi_handler_kills import GSIHandlerKills
    from gsi_handler_sounds import GSIHandlerSounds
    from gsi_handler_special import GSIHandlerSpecial
    from gsi_handler_flash import GSIHandlerFlash
    from gsi_handler_stats import GSIHandlerStats
    from gsi_handler_music import GSIHandlerMusic
    from gsi_handler_utility import GSIHandlerUtility
    from gsi_handler_hud_color import GSIHandlerHudColor
    from resource_manager import ResourceManager  # noqa: F401  (后续阶段使用)

    _boot_phase("GSI组件import")
    gsi_server = GSIServer()
    gsi_handler_kills = GSIHandlerKills()
    gsi_handler_sounds = GSIHandlerSounds()
    gsi_handler_special = GSIHandlerSpecial()
    gsi_handler_flash = GSIHandlerFlash()
    gsi_handler_stats = GSIHandlerStats(window)
    gsi_handler_music = GSIHandlerMusic()
    gsi_handler_utility = GSIHandlerUtility()
    gsi_handler_hud_color = GSIHandlerHudColor()
    
    # 保存GSI服务器引用
    window.gsi_server = gsi_server
    
    # 准备GSI组件字典
    gsi_components = {
        'server': gsi_server,
        'handlers': {
            'kills': gsi_handler_kills,
            'sounds': gsi_handler_sounds,
            'special': gsi_handler_special,
            'flash': gsi_handler_flash,
            'stats': gsi_handler_stats,
            'music': gsi_handler_music,
            'utility': gsi_handler_utility,
            'hud_color': gsi_handler_hud_color,
        }
    }
    window.gsi_handlers = gsi_components['handlers']
    
    # 创建后台加载器（只负责音频扫描等非UI任务）
    from background_loader import BackgroundLoader
    bg_loader = BackgroundLoader(window, gsi_components)
    
    # 连接后台加载信号
    def on_stage_started(stage_id, stage_name):
        logger.info(f"📦 {stage_name} 开始...")
    
    def on_stage_completed(stage_id):
        logger.info(f"✓ {stage_id} 完成")
        # 2.2.0 卡顿治理:音乐控制栏在音频阶段完成后创建——pygame 已被
        # 工作线程 import 热过,主线程创建为轻操作(原 0.3s 时创建实测卡 320ms)
        if str(stage_id) == "stage2":
            try:
                QTimer.singleShot(0, window._create_music_control_bar)
            except Exception:
                pass
    
    def on_all_completed():
        logger.info("🎉 所有资源加载完成！")
        _boot_phase("后台资源全就绪")
        # 2.2.0: 空闲预构建常用页——后台资源就绪后,趁空闲把高频页提前建好,切页零等待
        try:
            window.start_idle_preload()
        except Exception:
            logger.exception("空闲预构建启动失败(不影响使用)")
    
    def on_error(stage_id, error_msg):
        logger.error(f"后台加载错误 ({stage_id}): {error_msg}")
    
    # 在主线程中连接GSI组件
    def connect_gsi_components():
        """2.2.0 卡顿治理:原先此处同帧连建 flash/magnifier/utility 三页
        (flash 还要 spawn 子进程),实测一次性冻结主线程 ~1.3s——
        改为 QTimer 切片逐页构建,建完再做连接,帧间留出交互响应窗。"""
        _gsi_pending = ['flash', 'magnifier', 'utility']

        def _build_next_then_connect():
            if getattr(window, "_is_closing", False):
                return
            if _gsi_pending:
                pid = _gsi_pending[0]
                try:
                    # UP-015: ensure_page_loaded 在"用户正在切页"时返回 False。
                    # 这里绝不能 pop 掉就走——这三页是 flash/magnifier/utility,
                    # 下面的 _connect_gsi_now 用 is_page_loaded 做守卫,页没建成
                    # 就会静默跳过 handler 连接,导致自定闪光/开镜放大/道具瞄点
                    # 整个会话都不生效。让路重试,页留在队首。
                    if window.ensure_page_loaded(pid) is False:
                        QTimer.singleShot(300, _build_next_then_connect)
                        return
                except Exception:
                    logger.exception(f"GSI 前置页 {pid} 构建失败(继续)")
                _gsi_pending.pop(0)
                QTimer.singleShot(120, _build_next_then_connect)
                return
            _connect_gsi_now()

        _build_next_then_connect()

    def _connect_gsi_now():
        try:
            logger.info("连接GSI组件...")
            handlers = gsi_components['handlers']
            
            # 连接击杀图标播放器
            if hasattr(window, 'kill_icon_player'):
                handlers['kills'].set_image_player(window.kill_icon_player)
            
            # 连接准心组件（击杀联动）
            if hasattr(window, 'crosshair_animation') and hasattr(window.crosshair_animation, 'register_kill_handler'):
                window.crosshair_animation.register_kill_handler(handlers['kills'])
                logger.info("  ✓ 准心击杀联动已连接")
            
            # 连接闪光组件
            if window.is_page_loaded('flash'):
                handlers['flash'].set_flash_component(window.pages['flash'])
                logger.info("  ✓ 自定闪光已连接")
            
            # 连接放大器组件
            if window.is_page_loaded('magnifier'):
                handlers['sounds'].set_magnifier_component(window.pages['magnifier'])
                logger.info("  ✓ 开镜放大已连接")
            
            # 连接道具瞄点。2.2.0 卡顿治理:UtilityDisplay 构建(加载地图资源)
            # 实测 ~0.9s,从连接帧拆出独立帧;晚一拍接上不影响功能——
            # GSI 事件在 display 就位前由 handler 安全忽略。
            def _connect_utility_later():
                try:
                    if window.is_page_loaded('utility'):
                        from utility_display import UtilityDisplay
                        utility_display = UtilityDisplay()
                        window.pages['utility'].set_utility_display(utility_display)
                        window.pages['utility'].set_gsi_handler(handlers['utility'])
                        handlers['utility'].set_utility_components(
                            utility_display=utility_display,
                            gui_component=window.pages['utility']
                        )
                        logger.info("  ✓ 道具瞄点已连接(延迟帧)")
                except Exception:
                    logger.exception("道具瞄点延迟连接失败")

            QTimer.singleShot(250, _connect_utility_later)
            
            # R2-4: 按地图自动切预设(默认关,预设中心开)
            try:
                from core.presets.map_rules import MapPresetHandler

                gsi_server.add_handler(MapPresetHandler())
                logger.info("  ✓ 地图预设联动已注册")
            except Exception as _mp_exc:
                logger.warning(f"地图预设联动注册失败: {_mp_exc}")

            # 添加所有处理器到GSI服务器
            for handler in handlers.values():
                gsi_server.add_handler(handler)
            
            # 启动GSI服务器
            # UP-011: start() 不再在调用线程 sleep 0.5 秒等启动结果,改为 1 秒后
            # 异步回查——这个函数由 GUI 线程执行,那半秒是用户能感知到的界面冻结。
            gsi_server.start()

            def _verify_gsi_then_refresh():
                gsi_server.check_startup_error()
                # UP-009 配套：状态条定时刷新已放宽到 15 秒，但"GSI 起没起来"是
                # 用户立刻要看的状态（起不来意味着游戏内什么音效都不会有）。
                # 这里主动推一次，不能让人等最多 15 秒才知道启动失败。
                try:
                    window._refresh_system_status_strip()
                except Exception:
                    pass

            QTimer.singleShot(1000, _verify_gsi_then_refresh)
            logger.info("  ✓ GSI服务器已启动")
            
        except Exception as e:
            logger.error(f"GSI组件连接失败: {e}", exc_info=True)
    
    bg_loader.stage_started.connect(on_stage_started)
    bg_loader.stage_completed.connect(on_stage_completed)
    bg_loader.all_completed.connect(on_all_completed)
    bg_loader.error_occurred.connect(on_error)
    bg_loader.connect_gsi_requested.connect(connect_gsi_components)
    
    # 在主线程中分批加载页面（避免阻塞事件循环）
    def load_pages_in_main_thread():
        try:
            logger.info("📦 阶段 3: 静默加载页面...")

            # ==================== UP-005 / D-12 ====================
            # 旧做法:11 个页面无条件每 200ms 建一个,每页 200~640ms 主线程不可切,
            # 于是启动后 2.3~9.4 秒连续卡顿(实测卡顿与建页严格 1:1 对应)。
            # 2.2.0 把间隔 50→200ms 只是拉宽缝隙,单次停顿照旧。
            #
            # 新做法分两段:
            #   立即队列 = 频次 top4。这几页用户最可能马上点进去,值得用启动期
            #              那点卡顿换"点过去已经是现成页"。
            #   空闲队列 = 其余页。只在「窗口可见 且 用户已 10 秒没操作」时才建,
            #              一有输入立刻让路;托盘隐藏时全停。
            # 用户点到还没建的冷页时走既有骨架屏,体验不变。
            PRELOAD_POOL = [
                # P0: 高优先级页面
                'crosshair', 'kill_sound', 'kill_voice',
                # P1: 次要功能
                'death_sound', 'gun_sound', 'switch_weapon', 'reload_sound',
                # P2: 低优先级
                'special_sound',
            ]

            # UP-014 修正:viewmodel / voice_output 确实在 _preload_skip_pages 里
            # (构造即起线程/热键/设备),不该混进"静默预载"。但**不能简单删掉**——
            # 复核实证:这两页的构造函数正是「音板全局热键注册」(voice_output_page)
            # 与「局内视角自动切换线程」(viewmodel_page)的唯一启动点,删了等于把这
            # 两个已开启的功能悄悄关掉,直到用户手动打开对应页面才恢复。
            # 所以单独列一条"功能激活队列":排在最后、必定会建(不受空闲门控约束,
            # 否则用户一直操作就永远激活不了),但仍对切页让路。
            FEATURE_ACTIVATION_PAGES = ['viewmodel', 'voice_output']

            # 按本机使用频次重排——你最常用的页最先就绪。
            # ⚠️ known_pages 必须限定在 PRELOAD_POOL 内:频次榜可能含 music 等
            # "构造即起线程/设备"的页,不许混入静默预载。
            frequent = []
            try:
                from core.page_usage_tracker import top_pages

                frequent = [p for p in top_pages(4, known_pages=set(PRELOAD_POOL))]
            except Exception:
                pass

            if frequent:
                immediate = frequent
                logger.info(f"[静默加载] 立即队列(频次优先): {', '.join(immediate)}")
            else:
                # 没有频次数据(新用户/刚重置)时退化为固定 P0 前三
                immediate = PRELOAD_POOL[:3]
                logger.info(f"[静默加载] 立即队列(默认): {', '.join(immediate)}")
            idle_queue = [p for p in PRELOAD_POOL if p not in immediate]
            feature_queue = list(FEATURE_ACTIVATION_PAGES)

            IDLE_THRESHOLD_S = 10.0   # 用户静默这么久才认为"可以干点后台活"
            YIELD_RETRY_MS = 300      # 用户在操作 → 让路,过一会儿再看

            try:
                from core.utils.idle_watcher import get_idle_watcher
                idle_watcher = get_idle_watcher()
            except Exception:
                idle_watcher = None
            if idle_watcher is None:
                logger.warning(
                    "[静默加载] 未取到空闲侦测器，空闲队列将不做让路（退化为旧行为）"
                )

            state = {"i": 0, "audio_started": False}

            def _start_audio_preload():
                """音频预载不再等所有页面建完——空闲队列可能长时间不推进。"""
                if state["audio_started"]:
                    return
                state["audio_started"] = True
                logger.info("准备启动音频预加载...")
                QTimer.singleShot(300, lambda: bg_loader.start())

            def load_immediate():
                """立即队列:一页一页建,间隔 200ms 留响应窗。"""
                # 退出后必须立刻停:否则 ensure_page_loaded 一直返回 False,
                # 下面的让路重试会每 300ms 空转下去。
                if getattr(window, "_is_closing", False):
                    return
                if state["i"] < len(immediate):
                    page_id = immediate[state["i"]]
                    try:
                        # UP-015: 用户正在切页时 ensure_page_loaded 返回 False,
                        # 原地等一下再来,不推进游标(这一页还没建)。
                        if window.ensure_page_loaded(page_id) is False:
                            QTimer.singleShot(YIELD_RETRY_MS, load_immediate)
                            return
                    except Exception:
                        logger.exception(f"加载页面 {page_id} 失败")
                    state["i"] += 1
                    if state["i"] < len(immediate):
                        QTimer.singleShot(200, load_immediate)
                    else:
                        logger.info(f"✅ 立即队列完成（{len(immediate)} 页）")
                        _start_audio_preload()
                        # 功能激活页优先于空闲队列:它们关系到功能生不生效,
                        # 不是"提前建好省点切页时间"那种可有可无的优化。
                        if feature_queue:
                            QTimer.singleShot(800, load_feature_pages)
                        if idle_queue:
                            logger.info(
                                f"[静默加载] 其余 {len(idle_queue)} 页转入空闲队列"
                                f"（窗口可见且 {IDLE_THRESHOLD_S:.0f}s 无操作才建）"
                            )
                            QTimer.singleShot(1000, load_when_idle)
                else:
                    _start_audio_preload()

            def load_feature_pages():
                """功能激活队列:必定会建完，只对切页让路，不受空闲门控约束。

                这两页构造时会注册音板全局热键、拉起视角自动切换线程——它们是
                功能开关的实际生效点，不能因为"用户一直在操作"就永远不建。
                间隔放到 1.5 秒，把两次构建摊开，不制造连续卡顿。
                """
                if getattr(window, "_is_closing", False):
                    return
                if not feature_queue:
                    return
                pid = feature_queue[0]
                try:
                    if window.ensure_page_loaded(pid) is False:
                        QTimer.singleShot(YIELD_RETRY_MS, load_feature_pages)
                        return
                except Exception:
                    logger.exception(f"功能激活页 {pid} 构建失败")
                feature_queue.pop(0)
                logger.info(f"[功能激活] {pid} 已就绪")
                if feature_queue:
                    QTimer.singleShot(1500, load_feature_pages)

            def load_when_idle():
                """空闲队列:只在用户没在操作、窗口可见时才建一页。"""
                if not idle_queue:
                    logger.info("✅ 空闲队列已全部就绪")
                    return
                try:
                    if getattr(window, "_is_closing", False):
                        return
                    # 托盘隐藏/最小化 = 用户根本没在看,建了也不会马上用,还白占 CPU
                    if not window.isVisible() or window.isMinimized():
                        QTimer.singleShot(3000, load_when_idle)
                        return
                    # 用户正在操作 → 让路
                    if idle_watcher is not None and not idle_watcher.is_idle(IDLE_THRESHOLD_S):
                        QTimer.singleShot(YIELD_RETRY_MS, load_when_idle)
                        return

                    page_id = idle_queue[0]
                    try:
                        # UP-015: 用户正在切页 → 让路,这一页留在队首下次再建
                        if window.ensure_page_loaded(page_id) is False:
                            QTimer.singleShot(YIELD_RETRY_MS, load_when_idle)
                            return
                    except Exception:
                        logger.exception(f"加载页面 {page_id} 失败")
                    idle_queue.pop(0)
                    # 建完一页后立刻回头再判一次空闲,不连着硬推
                    QTimer.singleShot(500, load_when_idle)
                except Exception:
                    logger.exception("空闲预载调度异常")

            load_immediate()

        except Exception as e:
            logger.error(f"主线程页面加载失败: {e}", exc_info=True)
    
    # ==================== 阶段 1.5: 静默资源迁移（后台）====================
    def start_resource_migration():
        """在后台静默迁移资源，不阻塞UI"""
        def migrate_resources():
            try:
                logger.info("📦 后台资源迁移开始...")
                ResourceManager.copy_resources_to_appdata()
                logger.info("✓ 资源迁移完成")
            except Exception as e:
                logger.warning(f"资源迁移失败（非致命错误）: {e}")
        
        from threading import Thread
        thread = Thread(target=migrate_resources, daemon=True)
        thread.start()

    # 立即启动资源迁移（UI显示后立即进行）
    QTimer.singleShot(10, start_resource_migration)

    # ==================== 阶段 1.6: 启动期GSI配置自检（后台）====================
    def start_startup_gsi_cfg_check():
        """启动时检查并补齐 GSI/CFG 相关文件，避免首开漏配。"""
        def ensure_gsi_cfg():
            try:
                from cfg_utils import find_cs2_install_dir, ensure_all_cfg

                cs2_dir = (getattr(config, "csgo_dir", "") or "").strip()
                if not cs2_dir or not os.path.isdir(cs2_dir):
                    detected = find_cs2_install_dir()
                    if not detected:
                        logger.warning("[GSIConfig] 未检测到 CS2 目录，跳过启动期配置检查")
                        return
                    cs2_dir = detected
                    config.csgo_dir = detected
                    config.save_config()
                    logger.info(f"[GSIConfig] 自动检测并写入 CS2 目录: {detected}")

                ensure_all_cfg(cs2_dir)
                gsi_cfg_path = os.path.join(
                    cs2_dir,
                    "game",
                    "csgo",
                    "cfg",
                    "gamestate_integration_cs2customizer.cfg",
                )
                if os.path.isfile(gsi_cfg_path):
                    logger.info(f"[GSIConfig] 已确认 GSI 配置文件: {gsi_cfg_path}")
                else:
                    logger.warning(f"[GSIConfig] GSI 配置文件写入失败或不存在: {gsi_cfg_path}")
            except Exception as e:
                logger.error(f"[GSIConfig] 启动期配置检查失败: {e}", exc_info=True)

        from threading import Thread
        thread = Thread(target=ensure_gsi_cfg, daemon=True, name="StartupGsiCfgCheck")
        thread.start()

    QTimer.singleShot(20, start_startup_gsi_cfg_check)

    # ==================== 阶段 3: 静默后台加载 ====================
    # 启动页面加载流程（延迟200ms）
    # 注意：音频预加载会在页面加载完成后自动启动
    # 2.2.0 卡顿治理:预载起点 200ms→1500ms——用户刚打开的头 1.5 秒
    # 是交互黄金期(看首页/点开关),完全留白;预载卡顿挪到浏览稳定期。
    QTimer.singleShot(1500, load_pages_in_main_thread)  # 主线程加载页面
    
    logger.info("应用启动成功!")
    logger.info("提示: 按 Ctrl+C 可以安全退出")
    
    # 运行应用
    exit_code = app.exec()
    
    # 清理后台加载器
    if bg_loader.isRunning():
        bg_loader.cancel()
        bg_loader.wait(1000)  # 等待最多1秒
    
    logger.info(f"应用正常退出，退出码: {exit_code}")
    
    return exit_code

if __name__ == "__main__":
    # 添加对PyInstaller打包的多进程支持
    multiprocessing.freeze_support()
    sys.exit(main())
