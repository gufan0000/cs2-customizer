"""
统一日志管理器
用于记录应用程序运行日志，方便调试和问题追踪
"""
import logging
import sys
import io
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

# 脱敏过滤器：可选加载，失败时静默退化为旧行为，绝不阻塞 logger 启动。
try:
    from .log_filter import SensitiveFilter as _SensitiveFilter
except Exception:  # pragma: no cover - 极端情况降级
    _SensitiveFilter = None

APP_NAME = "FanTool"

# ==================== 文件日志级别与保留策略（UP-004）====================
# 背景:文件 handler 原先硬编码 DEBUG 且无开关。GSI 在游戏中每秒产生数十条 DEBUG
# （武器切换在 knife/主武器间反复横跳,每次都走完整 handler 链并写盘），这是主线程
# 同步 I/O 的稳定来源之一；同时日志只按文件大小轮转、不按天数清理，实测已累积
# 37 个文件 36MB 且会无限涨。
#
# 现在:文件日志默认 INFO；需要排查 GSI 问题时用下面任一方式开回 DEBUG——
#   1) 配置项 debug_file_log = true（%LOCALAPPDATA%\FanTool\config.json）
#   2) 环境变量 FANPAI_DEBUG_LOG=1（临时排障，不改配置）
# 注意:logger 不能 import config（config.py 第 1 行就 import 本模块，会循环依赖），
# 因此这里直接读 JSON，且任何异常都退化为默认值，绝不阻塞日志系统启动。
_LOG_RETENTION_DAYS = 14


def _resolve_config_dir_for_log() -> str:
    """与 config.get_config_dir() 同口径，但不 import config（避免循环依赖）。"""
    override_dir = os.environ.get("FANPAI_CONFIG_DIR")
    if override_dir:
        return override_dir
    appdata_dir = os.environ.get("LOCALAPPDATA")
    if appdata_dir:
        return os.path.join(appdata_dir, APP_NAME)
    return ""


def _want_debug_file_log() -> bool:
    """是否把文件日志开到 DEBUG。读不到就返回 False（默认 INFO）。"""
    env = os.environ.get("FANPAI_DEBUG_LOG", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        import json

        config_dir = _resolve_config_dir_for_log()
        if not config_dir:
            return False
        path = os.path.join(config_dir, "config.json")
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as fp:
            return bool(json.load(fp).get("debug_file_log", False))
    except Exception:
        return False


def _purge_old_logs(log_dir: Path, keep_days: int = _LOG_RETENTION_DAYS) -> int:
    """删除 keep_days 天前的日志与崩溃转储，返回删除数量。

    只清本程序自己产生的文件名模式，不碰目录里的其它东西。
    """
    import time as _time

    cutoff = _time.time() - keep_days * 86400
    removed = 0
    for pattern in ("fanpai_*.log", "fanpai_*.log.*", "bootstrap_crash_*.log"):
        for path in log_dir.glob(pattern):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                continue  # 单个文件删不掉（被占用等）不影响其余
    return removed


class Logger:
    """日志管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化日志系统"""
        if self._initialized:
            return
        
        # 创建日志目录
        self.log_dir = self._resolve_log_dir()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建根logger
        # 根 logger 保持 DEBUG：具体放行到哪一级由各 handler 自己决定，
        # 这样开发时挂个 DEBUG handler 依然能拿到全部记录。
        self.logger = logging.getLogger("FanPai")
        self.logger.setLevel(logging.DEBUG)

        # 清除已有的handler（避免重复）
        self.logger.handlers.clear()

        # UP-004: 文件日志级别默认 INFO，可由配置/环境变量开回 DEBUG
        self._debug_file_log = _want_debug_file_log()
        file_level = logging.DEBUG if self._debug_file_log else logging.INFO

        # 创建文件handler（带轮转）
        log_file = self.log_dir / f"fanpai_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(file_level)
        
        # 创建控制台handler（处理Windows编码问题）
        # 注意：PyInstaller --windowed 模式下，sys.stdout / sys.stderr 可能为 None
        console_stream = self._get_console_stream()
        console_handler = None
        if console_stream is not None:
            console_handler = logging.StreamHandler(console_stream)
            console_handler.setLevel(logging.INFO)
        
        # 创建格式器
        file_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_formatter = logging.Formatter('[%(levelname)s] %(message)s')
        
        # 设置格式器
        file_handler.setFormatter(file_formatter)
        if console_handler is not None:
            console_handler.setFormatter(console_formatter)

        # 接入脱敏过滤器（若加载失败，这两步 no-op，保持旧行为）
        if _SensitiveFilter is not None:
            try:
                file_handler.addFilter(_SensitiveFilter())
                if console_handler is not None:
                    console_handler.addFilter(_SensitiveFilter())
            except Exception:
                # 过滤器初始化异常不能阻塞日志系统
                pass

        # 添加handler
        self.logger.addHandler(file_handler)
        if console_handler is not None:
            self.logger.addHandler(console_handler)
        
        self._initialized = True
        
        # 记录启动信息
        self.info("=" * 60)
        self.info("帆派助手 - 现代版 (PySide6 Widget)")
        self.info("=" * 60)
        self.info(f"日志文件: {log_file.absolute()}")
        # 这一行必须每次都打:audio_event_audit.py 靠它判断本份日志是不是 DEBUG 级,
        # 否则在 INFO 级日志上做音频事件审计会静默漏掉大量 DEBUG 事件而不自知。
        if self._debug_file_log:
            self.info("[日志] 文件日志级别 = DEBUG（排障模式）")
        else:
            self.info("[日志] 文件日志级别 = INFO（如需音频事件审计请开启 debug_file_log）")

    def start_maintenance(self):
        """显式启动日志维护（清理过期文件）。

        UP-004 复核结论:清理绝不能是 import 的副作用。原先放在 __init__ 里,
        任何 import 到 core 包的进程都会触发——包括 build_release.py 生成 spec 时的
        collect_submodules("core"),于是每跑一次打包就把打包机 14 天前的日志删光;
        测试护栏在打包场景下也不生效。现在改为由 main_widget.main() 显式调用一次,
        只有真正启动软件才清理。
        """
        self._start_log_purge()

    def _start_log_purge(self):
        """后台清理 14 天前的日志文件（失败不影响任何功能）。"""
        # 双保险:测试进程一律不清理。即便某个测试忘了设 FANPAI_LOG_DIR,
        # 也不会误删用户的真实历史日志。
        if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
            return
        try:
            import threading

            def _run():
                try:
                    removed = _purge_old_logs(self.log_dir)
                    if removed:
                        self.info(f"[日志] 已清理 {removed} 个过期日志文件")
                except Exception:
                    pass

            threading.Thread(target=_run, daemon=True, name="LogPurge").start()
        except Exception:
            pass

    @staticmethod
    def _resolve_log_dir() -> Path:
        """优先写入 AppData，避免在 EXE 目录生成 logs 文件夹。

        FANPAI_LOG_DIR 覆盖用于测试隔离:否则跑测试会往用户真实日志目录写入,
        且 UP-004 的过期清理会真的删掉用户的历史日志(已经发生过一次)。
        与 FANPAI_CONFIG_DIR 同一套思路。
        """
        override_dir = os.environ.get("FANPAI_LOG_DIR")
        if override_dir:
            return Path(override_dir)
        appdata_dir = os.environ.get("LOCALAPPDATA")
        if appdata_dir:
            return Path(appdata_dir) / APP_NAME / "logs"
        return Path("logs")

    @staticmethod
    def _get_console_stream():
        """获取可用的控制台输出流；窗口模式下可能返回 None。"""
        stream = sys.stdout or sys.stderr
        if stream is None:
            return None

        # 普通终端下优先使用底层buffer并统一UTF-8输出
        try:
            buffer = getattr(stream, "buffer", None)
            if buffer is not None:
                return io.TextIOWrapper(
                    buffer,
                    encoding='utf-8',
                    errors='replace',
                    line_buffering=True,
                )
        except Exception:
            pass

        return stream
    
    def debug(self, msg, *args, **kwargs):
        """调试级别日志"""
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg, *args, **kwargs):
        """信息级别日志"""
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        """警告级别日志"""
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        """错误级别日志"""
        self.logger.error(msg, *args, **kwargs)
    
    def exception(self, msg, *args, **kwargs):
        """异常级别日志（包含堆栈信息）"""
        self.logger.exception(msg, *args, **kwargs)
    
    def get_logger(self, name):
        """获取子logger"""
        return logging.getLogger(f"FanPai.{name}")


# 全局logger实例
_logger_instance = None


def get_logger(name=None):
    """
    获取logger实例
    
    Args:
        name: logger名称（可选）
        
    Returns:
        Logger实例或子logger
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    
    if name:
        return _logger_instance.get_logger(name)
    return _logger_instance


# 便捷函数
def debug(msg, *args, **kwargs):
    """调试日志"""
    get_logger().debug(msg, *args, **kwargs)


def info(msg, *args, **kwargs):
    """信息日志"""
    get_logger().info(msg, *args, **kwargs)


def warning(msg, *args, **kwargs):
    """警告日志"""
    get_logger().warning(msg, *args, **kwargs)


def error(msg, *args, **kwargs):
    """错误日志"""
    get_logger().error(msg, *args, **kwargs)


def exception(msg, *args, **kwargs):
    """异常日志"""
    get_logger().exception(msg, *args, **kwargs)


if __name__ == "__main__":
    # 测试日志系统
    logger = get_logger()
    
    logger.debug("这是调试信息")
    logger.info("这是普通信息")
    logger.warning("这是警告信息")
    logger.error("这是错误信息")
    
    try:
        1 / 0
    except Exception:
        logger.exception("捕获异常")
    
    print(f"\n日志已写入: {logger.log_dir.absolute()}")
