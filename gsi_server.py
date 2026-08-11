# SPDX-License-Identifier: GPL-3.0-or-later
from queue import Queue, Empty
import os
import socket
import threading
import time
from flask import Flask, request, jsonify
from core.utils.logger import get_logger

logger = get_logger("GSIServer")

# --- Flask App ---
flask_app = Flask(__name__)
data_queue = Queue(maxsize=100)  # 限制队列大小防止内存泄漏

# 模块级变量：Flask 启动错误信息
_startup_error = None

# P2.3: 端口自适应——首选 config.gsi_port(默认3000)，被第三方占用时顺延 3001-3010。
_PORT_CANDIDATE_RANGE = list(range(3000, 3011))
_active_port = 3000


def get_active_port() -> int:
    """当前 GSI 服务器实际监听的端口。"""
    return _active_port


def _port_bindable(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _select_port(exclude=None) -> int:
    """优先用配置端口；占用则在候选段里找第一个可绑定端口；全占返回 -1。

    exclude: 本次启动流程中已尝试失败的端口（TOCTOU 抢占后不再重试同一个）。
    """
    exclude = exclude or set()
    try:
        from config import config as _config

        preferred = int(getattr(_config, "gsi_port", 3000) or 3000)
    except Exception:
        preferred = 3000
    candidates = [preferred] + [p for p in _PORT_CANDIDATE_RANGE if p != preferred]
    for port in candidates:
        if port in exclude:
            continue
        if _port_bindable(port):
            return port
    return -1


def _persist_port_change(port: int):
    """端口与配置不一致时：写回 config 并重生成游戏内 GSI cfg，保证两端一致。"""
    try:
        from config import config as _config

        if int(getattr(_config, "gsi_port", 3000) or 3000) == port:
            return
        _config.gsi_port = int(port)
        _config.save_config()
        logger.warning(f"GSI 端口已自适应切换到 {port}（原端口被占用），配置已更新")
        try:
            # ⚠ QA-003：这里原本是 `csgo_dir = find_cfg_path()`，
            # 而 `find_cfg_path()` 返回的是 **cfg 文件的全路径**，
            # `ensure_cfg_exists()` 要的却是 **CS2 安装根目录** —— 类型对不上。
            # 后果：重写 100% 失败（要么早退，要么去 `<cfg文件>/game/csgo/cfg/` 下建目录），
            # 而下面那句成功日志是**无条件打印**的，于是日志谎报「已按新端口重写」。
            # 用户这边：服务器监听 3001，游戏 cfg 里还写着 3000，
            # GSI 数据被推给占着 3000 的那个第三方程序 —— 击杀音效 / 闪光 / HUD / 道具
            # 全部无反应，而状态条显示「运行中」、日志说 cfg 已更新，排障会被带偏。
            from cfg_utils import ensure_cfg_exists, find_cs2_install_dir

            csgo_root = str(getattr(_config, "csgo_dir", "") or "").strip()
            if not csgo_root or not os.path.isdir(csgo_root):
                csgo_root = find_cs2_install_dir()
            if csgo_root:
                # 按返回值如实记日志，不再盲写成功
                if ensure_cfg_exists(csgo_root):
                    logger.warning("游戏内 GSI cfg 已按新端口重写；若 CS2 正在运行，需重启游戏生效")
                else:
                    logger.error(
                        "按新端口重写 GSI cfg **失败**（目录 %r）。"
                        "游戏仍会把数据推给旧端口，音效/闪光/HUD 都不会响应；"
                        "请在高级设置里重新选择 CS2 目录，或重启本软件。", csgo_root
                    )
            else:
                logger.error(
                    "端口已切到 %d，但找不到 CS2 安装目录，游戏内 GSI cfg 没能重写。"
                    "请在高级设置里选择 CS2 目录。", port
                )
        except Exception:
            logger.exception("按新端口重写 GSI cfg 失败（可在高级设置重新选择目录触发）")
    except Exception:
        logger.exception("持久化 GSI 端口失败（忽略）")

# v2.2.1: 丢包可观测——队列满丢弃是静默的，一旦处理线程卡顿导致持续丢包
# （可能丢掉 round_kills 归零等关键状态边沿），需要在日志里看得见。
_dropped_packets = 0
_last_drop_report = 0.0
_drop_stats_lock = threading.Lock()


def _record_drop():
    global _dropped_packets, _last_drop_report
    # Flask threaded=True 下多个请求线程并发进入，计数读改写需要加锁
    with _drop_stats_lock:
        _dropped_packets += 1
        now = time.time()
        if _last_drop_report == 0.0:
            # 首个丢包只启动统计窗口，避免把"1个"误报成一分钟累计
            _last_drop_report = now
            return
        if now - _last_drop_report >= 60.0:
            logger.warning(f"GSI队列已满，近一分钟累计丢弃 {_dropped_packets} 个数据包（处理线程可能卡顿）")
            _dropped_packets = 0
            _last_drop_report = now


@flask_app.route('/', methods=['POST'])
def game_state_update():
    data = request.get_json()
    if data:
        try:
            # 非阻塞放入，队列满时丢弃最旧数据
            data_queue.put_nowait(data)
        except Exception:
            # 队列满，丢弃最旧的数据并放入新数据
            try:
                data_queue.get_nowait()
                data_queue.put_nowait(data)
                _record_drop()
            except Exception:
                # 并发下 get 与 put 之间队列又被填满：新包被丢，也要计入统计
                _record_drop()
    return jsonify({'status': 'success'})

def run_flask():
    global _startup_error, _active_port
    # 探测可绑定与真正 bind 之间存在 TOCTOU 窗口（第三方进程可抢占端口），
    # 单个端口启动失败时顺延重选，而不是直接放弃
    attempted = set()
    for _attempt in range(3):
        port = _select_port(exclude=attempted)
        if port < 0:
            _startup_error = "GSI服务器端口 3000-3010 全部被占用，请关闭占用程序后重启软件"
            logger.error(_startup_error)
            return
        attempted.add(port)
        _active_port = port
        _persist_port_change(port)
        try:
            logger.info(f"GSI 服务器监听 127.0.0.1:{port}")
            flask_app.run(debug=False, port=port, threaded=True, use_reloader=False)
            return  # 正常退出（stop）
        except OSError:
            logger.exception(f"端口 {port} 启动失败，尝试下一候选端口")
    _startup_error = "GSI服务器连续多次端口启动失败，请关闭其他 CS2 Customizer 实例后重启软件"
    logger.error(_startup_error)

class GSIServer:
    def __init__(self):
        self.flask_thread = None
        self.data_queue = data_queue
        self.handlers = []
        self._running = False
        self.startup_error = None

    def add_handler(self, handler):
        """添加一个GSI数据处理器"""
        self.handlers.append(handler)

    def start_flask(self, wait: bool = False):
        """启动Flask服务器。

        UP-011: 原先无条件 time.sleep(0.5) 等着看有没有启动失败——这 0.5 秒是
        实打实卡在调用方线程上的,而 start_flask 在启动链路里由 GUI 线程调用,
        用户会感知到界面冻半秒。现在默认不等,改由调用方稍后用 check_startup_error()
        回查(见 gui_widget 的延迟校验)。

        Args:
            wait: 兼容旧行为。仅供命令行/测试等确实需要同步结果的场景使用,
                  GUI 线程绝不要传 True。
        """
        global _startup_error
        _startup_error = None
        self.flask_thread = threading.Thread(target=run_flask, daemon=True, name="GSIFlask")
        self.flask_thread.start()
        if wait:
            time.sleep(0.5)
            self.check_startup_error()

    def check_startup_error(self) -> str | None:
        """回查 Flask 是否启动失败（可反复调用，幂等）。

        返回错误信息；没有错误返回 None。
        """
        global _startup_error
        if _startup_error:
            self.startup_error = _startup_error
            logger.error(self.startup_error)
            return self.startup_error
        return None

    def process_data(self):
        """处理接收到的GSI数据"""
        self._running = True
        while self._running:
            try:
                data = self.data_queue.get(timeout=0.1)
                for handler in self.handlers:
                    try:
                        handler.process_data(data)
                    except Exception as e:
                        logger.error(f"Handler error: {handler.__class__.__name__}: {e}", exc_info=True)
            except Empty:
                pass
            except Exception as e:
                logger.error(f"Error processing data: {e}", exc_info=True)

    def stop(self):
        """停止数据处理循环"""
        self._running = False

    def start(self):
        """启动GSI服务器"""
        self.start_flask()
        process_thread = threading.Thread(target=self.process_data, daemon=True, name="GSIDataProcess")
        process_thread.start()
