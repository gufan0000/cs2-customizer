import json
import os
import tempfile
import threading
import time

from config import config
from core.hud.rule_compiler import get_cfg_paths, get_initial_runtime_color, write_runtime_cfg
from core.hud.rule_model import HUD_COLORS, has_runtime_enabled_rules
from core.hud.runtime_engine import RuntimeHudEngine
from core.utils.logger import get_logger


class GSIHandlerHudColor:
    """统一HUD规则运行时处理器：根据GSI状态写入 fanpai_hud_runtime.cfg"""

    def __init__(self):
        self.logger = get_logger("GSIHandlerHudColor")
        self.engine = RuntimeHudEngine(config.hud_rules, profile=config.hud_rules_profile)
        self.current_color = -1

        self._cfg_path = None
        self._last_write_time = 0.0
        self._min_write_interval = 0.05
        self._rules_signature = None

        self._last_data = None
        # QA-004: 最后一次收到 GSI 推送的时刻。0 = 从没收到过。
        self._last_data_ts = 0.0
        self._effect_timer = None
        self._effect_stop = threading.Event()
        # GSI处理线程(_tick)与效果线程(_effect_loop)共享 current_color/_last_write_time
        # 并写同一cfg文件，必须互斥，否则并发判断"颜色已变"会重复/乱序写
        self._write_lock = threading.Lock()
        # engine.evaluate 内含大量可变状态(previous_*/_event_until等)，
        # 两个线程交错调用会产生虚假/漏检的事件边沿，同样需要互斥
        self._engine_lock = threading.Lock()

        self.logger.info("[HUD规则] 运行时处理器已初始化")

    def _get_cfg_path(self):
        csgo_dir = (config.csgo_dir or "").strip()
        if not csgo_dir:
            self._cfg_path = None
            return None

        _, runtime_cfg_path = get_cfg_paths(csgo_dir)
        if self._cfg_path != runtime_cfg_path:
            self._cfg_path = runtime_cfg_path
        return self._cfg_path

    def _refresh_rules_if_needed(self):
        try:
            signature = json.dumps(
                {
                    "profile": config.hud_rules_profile,
                    "rules_enabled": config.hud_rules_enabled,
                    "sync_mode": config.hud_runtime_sync_mode,
                    "rules": config.hud_rules,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        except Exception:
            signature = str(id(config.hud_rules))

        if signature != self._rules_signature:
            self._rules_signature = signature
            self.engine.set_rules(config.hud_rules, profile=config.hud_rules_profile)
            self.logger.info("[HUD规则] 已应用最新规则配置")

    def process_data(self, data):
        if not config.hud_rules_enabled:
            return
        if config.hud_runtime_sync_mode != "safe":
            return
        if not has_runtime_enabled_rules(config.hud_rules):
            return

        self._refresh_rules_if_needed()
        self._last_data = data
        # QA-004: 记下"最后一次真正收到 GSI 推送"的时刻。
        # 效果线程靠它判断游戏还在不在推数据（见 `_effect_loop`）。
        self._last_data_ts = time.time()
        self._tick(data)
        self._ensure_effect_timer()

    def _tick(self, data):
        now = time.time()
        with self._engine_lock:
            output = self.engine.evaluate(data, now=now)
        if output.color is None:
            return
        self._maybe_write_color(output.color, now)

    def _maybe_write_color(self, color, now):
        """检查-写入合并为一个临界区，供 GSI 线程与效果线程共用。"""
        with self._write_lock:
            if (
                color != self.current_color
                and (now - self._last_write_time) >= self._min_write_interval
            ):
                self._write_runtime_cfg(color)
                self.current_color = color
                self._last_write_time = now

    def _ensure_effect_timer(self):
        if self._effect_timer and self._effect_timer.is_alive():
            return
        self._effect_stop.clear()
        t = threading.Thread(target=self._effect_loop, daemon=True)
        t.start()
        self._effect_timer = t

    #: 多久收不到 GSI 推送就认为游戏不在跑了，效果线程退出等下次唤醒。
    _DATA_STALE_SECONDS = 3.0

    def _effect_loop(self):
        """后台循环：每100ms重新evaluate，驱动效果颜色切换。

        ⚠ QA-004：退出判据原本是「连续 30 次 `output.color is None`」，
        而这个条件**永远不成立** —— `default_color` 默认是 0，
        `_pick_candidate` 在 `default_color >= 0` 时会无条件塞一个 default 候选，
        所以 `output.color` 恒非 None，`idle_count` 一次都涨不上去。
        后果：游戏关掉之后，这个线程仍以**最后一帧 GSI 快照**每 100ms 重新求值，
        直到软件退出；若那一帧恰好是低血量/炸弹已安装这类 blink/pulse 状态，
        还会持续重写 CFG —— 写的是游戏没在跑时没人读的文件，纯空转 + 无效磁盘写。

        改成按「**GSI 还在不在推数据**」判断：这才是原注释想表达的
        「等下次 GSI 推送再启动」。数据陈旧 = 游戏没在跑 = 该退出。
        """
        while not self._effect_stop.wait(0.1):
            data = self._last_data
            if data is None:
                break
            # 游戏已经不推数据了：再算下去也只是拿同一帧反复求值
            if time.time() - self._last_data_ts >= self._DATA_STALE_SECONDS:
                self.logger.debug("[HUD规则] GSI 已停止推送，效果线程退出（等下次推送再唤醒）")
                break
            try:
                now = time.time()
                with self._engine_lock:
                    output = self.engine.evaluate(data, now=now)
                if output.color is not None:
                    self._maybe_write_color(output.color, now)
            except Exception as e:
                self.logger.debug(f"[HUD规则] 效果循环异常: {e}")
                continue

    def stop(self):
        self._effect_stop.set()
        if self._effect_timer:
            self._effect_timer.join(timeout=1.0)
            self._effect_timer = None
        # 写回默认颜色
        try:
            cfg_path = self._get_cfg_path()
            if cfg_path:
                default_color = get_initial_runtime_color(config)
                write_runtime_cfg(cfg_path, default_color)
                self.logger.info("[HUD规则] 已恢复默认HUD颜色")
        except Exception as e:
            self.logger.warning(f"[HUD规则] 恢复默认颜色失败: {e}")

    def _write_runtime_cfg(self, color_value):
        cfg_path = self._get_cfg_path()
        if not cfg_path:
            return
        try:
            cfg_dir = os.path.dirname(cfg_path)
            os.makedirs(cfg_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=cfg_dir, prefix="hud_runtime_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(f"cl_hud_color {color_value}\n")
                os.replace(tmp_path, cfg_path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
            color_name = HUD_COLORS.get(color_value, ("未知", "#000000"))[0]
            self.logger.debug(f"[HUD规则] 写入运行时颜色: {color_value} ({color_name})")
        except Exception as e:
            # B4: 写 CFG 失败是用户可感知问题，附加堆栈便于诊断
            self.logger.exception(f"[HUD规则] 写入运行时CFG失败: {e}")

