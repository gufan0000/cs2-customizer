# SPDX-License-Identifier: GPL-3.0-or-later
import os
import threading
import time
import queue
import sounddevice as sd
import soundfile as sf
import numpy as np
from typing import Optional, List
import pygame
import keyboard
from core.utils.logger import get_logger

class VoiceOutputManager:
    """语音输出管理器（支持混音和智能PTT会话）"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.vb_cable_device_id = None
        self.default_speaker_id = None
        # QA-017: 本地监听专用的输出目标。见 detect_devices 末尾的说明。
        # 与 default_speaker_id 分开是刻意的——后者代表"启动时的默认扬声器"，
        # 还被日志和别处引用，重新定义它会牵连一片。
        self.local_monitor_device_id = None
        self.default_microphone_id = None
        self.is_initialized = False
        self.playback_queue = queue.Queue()
        self.is_playing = False
        
        self.current_playback_protocol_thread = None # 新的播放协议线程
        self.local_playback_threads_lock = threading.Lock()
        self.ptt_key_pressed = False
        self.ptt_lease_counter = 0
        self.ptt_lock = threading.Lock()
        self.mixer_sample_rate: Optional[int] = None

        # --- START: 新增部分 (智能兜底机制) ---
        self.robust_release_timer: Optional[threading.Timer] = None
        self.robust_release_lock = threading.Lock()
        # --- END: 新增部分 ---

        # 麦克风静音引用计数：重叠转发时 B 路结束不能把仍在转发的 A 路
        # 提前解除静音（布尔标志会互相抢跑），归零才真正 unmute
        self._mute_refcount = 0
        self._mute_lock = threading.Lock()
        # 当前独占播放的取消令牌（stop_playback 只取消它，不影响重叠转发）
        self._current_cancel_event = None
        
        # 麦克风监听相关
        self.microphone_passthrough_active = False
        self.passthrough_thread = None
        self.selected_microphone_id = None
        self.mic_buffer = queue.Queue(maxsize=10)  # 麦克风缓冲区
        
        # 新增麦克风静音标志，用于自动模式
        self.mute_microphone = False
        self.mute_lock = threading.Lock()
        
        # 音频设置（优化延迟）
        self.preferred_rate = 48000  # 首选采样率
        self.vb_cable_rate = None   # VB-Cable实际采样率
        self.channels = 2  # 单声道输出到虚拟麦更稳
        self.chunk_size = 960  # 48k下一帧20ms
        self.latency = 'low'  # 低延迟模式
        
        # 设备信息缓存
        self.devices_info = {}
        self.microphone_devices = []
        
        # 混音相关
        self.mix_lock = threading.Lock()
        self.current_mix_audio = None
        self.mix_position = 0
        
        # 播放控制（新增）
        self.current_playback_lock = threading.Lock()
        self.stop_playback_flag = False
        self.local_playback_threads = []  # 本地播放线程列表
        
        # 初始化检测
        self.detect_devices()
    
    def detect_devices(self) -> bool:
        """检测音频设备"""
        try:
            devices = sd.query_devices()
            self.devices_info = {}
            self.microphone_devices = []
            
            try:
                default_input = sd.query_devices(kind='input')
                default_output = sd.query_devices(kind='output')
                default_input_id = devices.index(default_input) if default_input else None
                default_output_id = devices.index(default_output) if default_output else None
            except Exception:
                default_input_id = None
                default_output_id = None
            
            for idx, device in enumerate(devices):
                device_name = device['name']
                self.devices_info[idx] = {
                    'name': device_name,
                    'input_channels': device['max_input_channels'],
                    'output_channels': device['max_output_channels'],
                    'samplerate': device['default_samplerate']
                }
                
                if self.vb_cable_device_id is None and 'CABLE Input' in device_name and device['max_output_channels'] > 0:
                    supported_rate = self.test_vb_cable_sample_rates(idx)
                    if supported_rate:
                        self.vb_cable_device_id = idx
                        self.vb_cable_rate = supported_rate
                        self.logger.info(f"[初始化] 已锁定VB-Cable设备: {device_name} (ID: {idx}) @ {self.vb_cable_rate}Hz")
                
                if device['max_output_channels'] > 0 and 'CABLE' not in device_name:
                    if idx == default_output_id:
                        self.default_speaker_id = idx
                    elif self.default_speaker_id is None:
                        self.default_speaker_id = idx
                
                if device['max_input_channels'] > 0 and 'CABLE' not in device_name:
                    # UP-028: 记下 hostapi。同一支麦在 MME/WASAPI/DirectSound 下会
                    # 各出现一次、名字完全相同,只靠 name 分不开(实测 25 个设备里有 4 条同名)。
                    self.microphone_devices.append({
                        'id': idx, 'name': device_name,
                        'hostapi': device.get('hostapi'),
                        'channels': device['max_input_channels'],
                    })
                    if idx == default_input_id:
                        self.default_microphone_id = idx
                    elif self.default_microphone_id is None:
                        self.default_microphone_id = idx
            
            # QA-017: 给"本地监听"挑一个能**跟随系统默认输出**的目标。
            # PortAudio 在进程内只枚举一次设备（全仓也没有 _terminate/_initialize），
            # 所以 default_speaker_id 是启动那一刻冻结下来的**具体物理设备**索引。
            # 用户中途换耳机（拔耳机回音箱、插上 USB/蓝牙）之后：旧设备还在但已非默认
            # → 监听持续从旧设备出声，用户戴着耳机听不到；旧设备已拔掉 → 开流抛异常，
            # 被吞成一条日志，界面毫无提示。
            # MME 的 WAVE_MAPPER（「Microsoft 声音映射器 - Output」）是个伪设备，
            # 每次开流时才解析到"当时的 Windows 默认"，正好解决这件事。
            # 按**位置**认而不是按名字认——名字随系统语言变。
            # 整段自带 try：这里任何异常都不许影响 VB-Cable 检测结果
            # （外层 except 会把它伪装成"未检测到设备"，直接把语音功能整个关掉）。
            try:
                mapper_id = self._find_wave_mapper_output(devices)
                default_out_name = ""
                if default_output_id is not None and 0 <= default_output_id < len(devices):
                    default_out_name = str(devices[default_output_id].get('name', ''))
                if 'CABLE' in default_out_name:
                    # 用户把虚拟麦设成了系统默认输出。这时**不能**走映射器：
                    # 映射器会解析到 CABLE，同一段音频被写进虚拟麦两遍，
                    # 队友听到叠加/回声，用户本地反而彻底没声。
                    # 也不能退回 default_speaker_id —— 它在这条路径上恰好也会落到
                    # 映射器（循环里 'CABLE' not in name 只排除了 CABLE 本身，
                    # 映射器名字不含 CABLE，又排在物理设备前面）。
                    # 只能显式挑一台**既不是 CABLE 也不是映射器**的物理输出。
                    self.local_monitor_device_id = self._first_physical_output(
                        devices, exclude=mapper_id)
                    self.logger.info(
                        "[初始化] 系统默认输出是 CABLE，本地监听改走物理设备: "
                        f"{self.local_monitor_device_id}")
                else:
                    self.local_monitor_device_id = mapper_id
            except Exception as exc:
                self.logger.warning(f"[初始化] 本地监听设备探测失败，沿用默认扬声器: {exc}")
                self.local_monitor_device_id = None

            if self.default_microphone_id is not None:
                self.logger.info(f"[初始化] 默认麦克风: {self.devices_info[self.default_microphone_id]['name']}")
            if self.default_speaker_id is not None:
                self.logger.info(f"[初始化] 默认扬声器: {self.devices_info[self.default_speaker_id]['name']}")
            if self.local_monitor_device_id is not None:
                self.logger.info(
                    f"[初始化] 本地监听走声音映射器: "
                    f"{self.devices_info[self.local_monitor_device_id]['name']} "
                    f"(ID: {self.local_monitor_device_id})")
            
            if self.vb_cable_device_id is not None:
                self.is_initialized = True
                return True
            else:
                self.logger.warning("[初始化] 未找到可用的VB-Cable设备")
                return False
            
        except Exception as e:
            self.logger.error(f"[初始化] 检测设备失败: {e}")
            return False
    
    def _find_wave_mapper_output(self, devices) -> Optional[int]:
        """找 MME 的 WAVE_MAPPER 输出伪设备（QA-017）。

        **按位置认，不按名字认** —— 「Microsoft 声音映射器 - Output」这个名字
        随系统语言变，中文/英文/日文机器上各不相同。
        PortAudio 里 MME 这个 hostapi 的设备列表中，第一个有输出通道的就是映射器。
        找不到就返回 None（调用方会退回旧行为）。
        """
        try:
            hostapis = sd.query_hostapis()
        except Exception:
            return None
        for api in hostapis:
            if str(api.get('name', '')).upper() != 'MME':
                continue
            for idx in api.get('devices', []) or []:
                if 0 <= idx < len(devices) and devices[idx].get('max_output_channels', 0) > 0:
                    return int(idx)
        return None

    def _first_physical_output(self, devices, exclude=None) -> Optional[int]:
        """第一台既不是 CABLE、也不是映射器的真实输出设备（QA-017）。"""
        for idx, device in enumerate(devices):
            if idx == exclude:
                continue
            if device.get('max_output_channels', 0) <= 0:
                continue
            if 'CABLE' in str(device.get('name', '')):
                continue
            return int(idx)
        return None

    def test_vb_cable_sample_rates(self, device_id: int) -> Optional[int]:
        test_rates = [48000, 44100, 22050, 16000, 8000]
        for rate in test_rates:
            try:
                test_stream = sd.OutputStream(device=device_id, samplerate=rate, channels=2, blocksize=128, dtype='float32')
                test_stream.close()
                return rate
            except Exception:
                continue
        return None
    
    def is_vb_cable_installed(self) -> bool:
        self.detect_devices()
        return self.vb_cable_device_id is not None
    
    def get_device_name(self, device_id: int) -> str:
        return self.devices_info.get(device_id, {}).get('name', "Unknown Device")
    
    DEFAULT_MIC_KEY = "默认"

    def get_microphone_list(self) -> List[str]:
        return ["默认"] + [mic['name'] for mic in self.microphone_devices]

    def get_microphone_entries(self) -> List[dict]:
        """UP-028: 带**稳定标识**的麦克风列表，供下拉框使用。

        原来下拉框只列 `name`，而同一支麦在不同 hostapi(MME/WASAPI/DirectSound)
        下会重复出现且名字一模一样——实测 25 个设备里 4 条完全同名。
        恢复选择时用的 `findText()` 只认第一条，于是**用户选的设备下次启动会被换掉**，
        而且用户完全没法在界面上把它们区分开。

        每项返回:
          id      —— sounddevice 索引(会话内有效，跨重启可能变，所以不能拿来存)
          name    —— 原始设备名
          label   —— 展示文案，同名的补 `(2)` `(3)` 序号
          key     —— 持久化用的稳定标识 `name|hostapi|同名序号`
        """
        entries = [{
            "id": None, "name": self.DEFAULT_MIC_KEY,
            "label": self.DEFAULT_MIC_KEY, "key": self.DEFAULT_MIC_KEY,
        }]
        seen = {}
        for mic in self.microphone_devices:
            name = mic.get("name", "")
            hostapi = mic.get("hostapi")
            n = seen.get((name, hostapi), 0)
            seen[(name, hostapi)] = n + 1
            occurrence = sum(1 for e in entries if e["name"] == name)
            entries.append({
                "id": mic.get("id"),
                "name": name,
                "hostapi": hostapi,
                # 只有真的重名才加序号,不给唯一设备平白加个"(1)"
                "label": name if occurrence == 0 else f"{name} ({occurrence + 1})",
                "key": f"{name}|{hostapi}|{n}",
            })
        return entries

    def get_microphone_id_by_key(self, key: str) -> Optional[int]:
        """按 `get_microphone_entries()` 的 key 精确取设备 id。

        找不到时**不**猜：返回 None 让调用方决定是回退默认还是提示用户。
        （旧的 `get_microphone_id_by_name` 会做子串模糊匹配，那正是"选了 A 结果
        用上 B"的来源之一。）
        """
        if not key or key == self.DEFAULT_MIC_KEY:
            return self.default_microphone_id
        for entry in self.get_microphone_entries():
            if entry["key"] == key:
                return entry["id"] if entry["id"] is not None else self.default_microphone_id
        return None

    def get_microphone_id_by_name(self, name: str) -> Optional[int]:
        """按名字取设备 id（旧接口，保留兼容）。

        ⚠️ 同名设备只会命中第一条——这正是 UP-028。新代码请用
        `get_microphone_id_by_key()`；这里只为读旧配置留一条退路。
        """
        if name == self.DEFAULT_MIC_KEY:
            return self.default_microphone_id
        for mic in self.microphone_devices:
            if mic['name'] == name:
                return mic['id']
        for mic in self.microphone_devices:
            if name in mic['name'] or mic['name'] in name:
                return mic['id']
        return self.default_microphone_id
    
    def get_mixer_sample_rate(self) -> int:
        """缓存并返回pygame混音器的采样率，避免频繁查询"""
        if self.mixer_sample_rate:
            return self.mixer_sample_rate
        mixer_info = pygame.mixer.get_init()
        if mixer_info:
            self.mixer_sample_rate = mixer_info[0]
            return self.mixer_sample_rate
        fallback = self.vb_cable_rate or self.preferred_rate or 44100
        self.mixer_sample_rate = int(fallback)
        self.logger.info(f"[混音器] pygame.mixer未初始化，使用回退采样率 {self.mixer_sample_rate}Hz")
        return self.mixer_sample_rate
    
    def resample_audio(self, audio_data: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        if from_rate == to_rate:
            return audio_data
        try:
            from scipy import signal
            return signal.resample_poly(audio_data, to_rate, from_rate, axis=0)
        except ImportError:
            ratio = to_rate / from_rate
            new_length = int(len(audio_data) * ratio)
            indices = np.linspace(0, len(audio_data) - 1, new_length)
            if len(audio_data.shape) == 2:
                resampled = np.zeros((new_length, audio_data.shape[1]))
                for ch in range(audio_data.shape[1]):
                    resampled[:, ch] = np.interp(indices, np.arange(len(audio_data)), audio_data[:, ch])
                return resampled
            else:
                return np.interp(indices, np.arange(len(audio_data)), audio_data)

    def _resample_block(self, audio_data, from_rate, to_rate):
        try:
            from scipy import signal
            return signal.resample_poly(audio_data, to_rate, from_rate, axis=0)
        except Exception:
            ratio = to_rate / from_rate
            new_length = int(max(1, round(len(audio_data) * ratio)))
            idx = np.linspace(0, len(audio_data) - 1, new_length)
            if audio_data.ndim == 2:
                out = np.zeros((new_length, audio_data.shape[1]), dtype=audio_data.dtype)
                base = np.arange(len(audio_data))
                for ch in range(audio_data.shape[1]):
                    out[:, ch] = np.interp(idx, base, audio_data[:, ch]).astype(audio_data.dtype)
                return out
            else:
                base = np.arange(len(audio_data))
                return np.interp(idx, base, audio_data).astype(audio_data.dtype)

    def init_streaming_resampler(self, from_rate, to_rate, channels):
        self._sr_from = from_rate
        self._sr_to = to_rate
        self._sr_channels = channels
        self._sr_buf = np.zeros((0, channels), dtype=np.float32)
        self._sr_keep = max(int(from_rate * 0.02), 256)

    def resample_audio_streaming(self, audio_data, from_rate, to_rate):
        if audio_data.ndim == 1:
            audio_data = audio_data.reshape(-1, 1)
        if not hasattr(self, '_sr_from') or self._sr_from != from_rate or self._sr_to != to_rate or self._sr_channels != audio_data.shape[1]:
            self.init_streaming_resampler(from_rate, to_rate, audio_data.shape[1])
        x = audio_data.astype(np.float32)
        if len(self._sr_buf) > 0:
            x = np.vstack([self._sr_buf, x])
        keep_in = min(self._sr_keep, len(x))
        y = self._resample_block(x, from_rate, to_rate)
        keep_out = int(round(keep_in * (to_rate / from_rate)))
        y_out = y[:-keep_out] if keep_out > 0 and len(y) > keep_out else np.zeros((0, x.shape[1]), dtype=y.dtype)
        self._sr_buf = x[-keep_in:].copy()
        return y_out
    
    def start_microphone_passthrough(self, mic_name: str = "默认"):
        """mic_name 既接受 `get_microphone_entries()` 的 key，也接受旧的纯设备名。

        UP-028: 先按 key 精确匹配（同名设备唯一可分辨的途径），
        匹配不到再退回按名字模糊匹配，读旧配置不至于失灵。
        """
        if not self.is_initialized:
            return False
        if self.microphone_passthrough_active:
            self.stop_microphone_passthrough()
        device_id = self.get_microphone_id_by_key(mic_name)
        if device_id is None:
            device_id = self.get_microphone_id_by_name(mic_name)
        self.selected_microphone_id = device_id
        if self.selected_microphone_id is None:
            return False
        self.microphone_passthrough_active = True
        success_flag = {'value': False}
        def passthrough_worker():
            input_stream, output_stream = None, None
            try:
                mic_info = sd.query_devices(self.selected_microphone_id)
                mic_rate = int(mic_info['default_samplerate'])
                output_rate = self.vb_cable_rate
                if output_rate is None: raise Exception("VB-Cable 采样率未知")
                input_channels = min(mic_info['max_input_channels'], 2)
                output_channels = 2
                input_stream = sd.InputStream(device=self.selected_microphone_id, channels=input_channels, samplerate=mic_rate, blocksize=self.chunk_size, latency='low', dtype='float32')
                blocksize_out = int(self.chunk_size * output_rate / mic_rate) if mic_rate != output_rate else self.chunk_size
                output_stream = sd.OutputStream(device=self.vb_cable_device_id, channels=output_channels, samplerate=output_rate, blocksize=blocksize_out, latency='low', dtype='float32')
                input_stream.start()
                output_stream.start()
                success_flag['value'] = True
                while self.microphone_passthrough_active:
                    try:
                        audio_data, _ = input_stream.read(self.chunk_size)
                        with self.mute_lock:
                            if self.mute_microphone:
                                audio_data = np.zeros_like(audio_data)
                        if mic_rate != output_rate:
                            audio_data = self.resample_audio_streaming(audio_data, mic_rate, output_rate)
                        current_channels = audio_data.shape[1] if len(audio_data.shape) > 1 else 1
                        if current_channels != output_channels:
                            if current_channels == 1 and output_channels == 2:
                                audio_data = np.column_stack((audio_data, audio_data))
                            elif current_channels == 2 and output_channels == 1:
                                audio_data = np.mean(audio_data, axis=1, keepdims=True)
                        if self.current_mix_audio is not None:
                            with self.mix_lock:
                                frames = len(audio_data)
                                end_pos = min(self.mix_position + frames, len(self.current_mix_audio))
                                audio_chunk = self.current_mix_audio[self.mix_position:end_pos]
                                self.mix_position = end_pos
                                if self.mix_position >= len(self.current_mix_audio):
                                    self.current_mix_audio = None
                                    self.mix_position = 0
                                if len(audio_chunk) > 0:
                                    if len(audio_chunk.shape) == 1: audio_chunk = audio_chunk.reshape(-1, 1)
                                    if audio_chunk.shape[1] != audio_data.shape[1]:
                                        if audio_chunk.shape[1] == 1 and audio_data.shape[1] == 2:
                                            audio_chunk = np.column_stack((audio_chunk, audio_chunk))
                                        elif audio_chunk.shape[1] == 2 and audio_data.shape[1] == 1:
                                            audio_chunk = np.mean(audio_chunk, axis=1, keepdims=True)
                                    if len(audio_chunk) < len(audio_data):
                                        padding = np.zeros((len(audio_data) - len(audio_chunk), audio_data.shape[1]))
                                        audio_chunk = np.vstack((audio_chunk, padding))
                                    elif len(audio_chunk) > len(audio_data):
                                        audio_chunk = audio_chunk[:len(audio_data)]
                                    audio_data = audio_data * 0.6 + audio_chunk * 0.4
                        audio_data = np.clip(audio_data, -1.0, 1.0)
                        output_stream.write(audio_data.astype('float32'))
                    except Exception as e:
                        if self.microphone_passthrough_active:
                            self.logger.error(f"[麦克风穿透] 音频处理错误: {e}")
                            time.sleep(0.01)
            except Exception as e:
                self.logger.error(f"[麦克风穿透] 启动麦克风直通失败: {e}")
            finally:
                if input_stream: input_stream.stop(); input_stream.close()
                if output_stream: output_stream.stop(); output_stream.close()
                self.microphone_passthrough_active = False
        self.passthrough_thread = threading.Thread(target=passthrough_worker, daemon=True, name="VoicePassthrough")
        self.passthrough_thread.start()
        time.sleep(0.5)
        return success_flag['value']
    
    def stop_microphone_passthrough(self):
        self.microphone_passthrough_active = False
        if hasattr(self, 'passthrough_thread') and self.passthrough_thread and self.passthrough_thread.is_alive():
            self.passthrough_thread.join(timeout=1.0)
        self.passthrough_thread = None
        while not self.mic_buffer.empty():
            try: self.mic_buffer.get_nowait()
            except queue.Empty: break
    
    def set_microphone_mute(self, mute: bool):
        with self.mute_lock:
            self.mute_microphone = mute
        self.logger.info(f"[麦克风] 麦克风已设置为: {'静音' if mute else '取消静音'}")

    # --- START: 修改部分 ---
    def play_audio_with_ptt_protocol(self, audio_path: Optional[str] = None, sound_obj: Optional[pygame.mixer.Sound] = None, 
                                     volume: float = 1.0, mode: str = "覆盖", also_local: bool = True,
                                     ptt_key: Optional[str] = None, ptt_delay: int = 500,
                                     allow_overlap: bool = False, use_robust_release: bool = False) -> bool:
        """
        核心播放协议方法，处理所有类型的播放请求。
        新增 allow_overlap 和 use_robust_release 参数。
        """
    # --- END: 修改部分 ---
        if not self.is_initialized:
            self.logger.warning("[播放协议] 系统未初始化")
            return False
        if not audio_path and not sound_obj:
            self.logger.warning("[播放协议] 未提供音频源")
            return False

        if not allow_overlap:
            self.stop_playback()
            if self.current_playback_protocol_thread and self.current_playback_protocol_thread.is_alive():
                self.current_playback_protocol_thread.join(timeout=0.1)
            # 确保 flag 在新播放前被重置。
            # 注意：仅独占播放需要重置；重叠播放(allow_overlap=True)不得重置，
            # 否则会"取消"一次正在进行的 stop_playback，让本应停止的播放继续写设备。
            with self.current_playback_lock:
                self.stop_playback_flag = False

        # 每次播放独立的取消令牌：旧实现全部读共享 stop_playback_flag，
        # 音板触发的 stop_playback 会把毫不相干的击杀音效转发拦腰掐断
        cancel_event = threading.Event()
        if not allow_overlap:
            self._current_cancel_event = cancel_event

        def playback_worker():
            thread_id = threading.current_thread().ident
            audio_data, sample_rate, duration = None, None, 0
            # 只有真正 press 过才能在 finally 里释放租约：音频加载阶段抛异常时
            # 无条件 release 会误减其他并发转发路的租约，把别人的开麦键切断
            ptt_acquired = False
            try:
                if sound_obj:
                    sound_array = pygame.sndarray.array(sound_obj)
                    audio_data = sound_array.astype(np.float32) / 32768.0
                    if len(audio_data.shape) == 1:
                        audio_data = np.column_stack((audio_data, audio_data))
                    sample_rate = self.get_mixer_sample_rate()
                    duration = sound_obj.get_length()
                elif audio_path and os.path.exists(audio_path):
                    audio_data, sample_rate = sf.read(audio_path, dtype='float32')
                    if len(audio_data.shape) == 1:
                        audio_data = np.column_stack((audio_data, audio_data))
                    duration = self.get_sound_duration(audio_path)
                if audio_data is None:
                    raise ValueError("无法加载音频数据")
                audio_data *= volume

                self.logger.info(f"[播放协议] 线程{thread_id} 开始播放，时长={duration:.2f}秒, mode={mode}, PTT key={ptt_key}, allow_overlap={allow_overlap}")

                # --- START: 修改部分 (取消旧兜底计时器) ---
                if ptt_key and use_robust_release:
                    self.cancel_robust_release() # 如果有新的转发请求，取消旧的兜底
                # --- END: 修改部分 ---

                if ptt_key and ptt_delay > 0:
                    time.sleep(ptt_delay / 1000.0)
                if ptt_key:
                    self.press_ptt_key(ptt_key)
                    ptt_acquired = True
                
                # --- START: 修改部分 (强制覆盖模式静音) ---
                # 覆盖和自动模式都应该在播放时静音麦克风
                should_mute = mode in ["覆盖", "自动"]
                if mode == "混音":
                    self._play_with_mix_data(audio_data, sample_rate, also_local, cancel_event=cancel_event)
                    # 混音模式需要等待，因为音频是异步播放的
                    if duration > 0:
                        wait_time = duration + 0.2
                        deadline = time.time() + wait_time
                        while time.time() < deadline:
                            if cancel_event.is_set():
                                break
                            time.sleep(0.03)
                else: # 覆盖, 自动, 或其他未知模式
                    self._play_file_data(
                        audio_data, sample_rate, also_local,
                        auto_mode=should_mute, cancel_event=cancel_event,
                    )
                    # _play_file_data 是同步的，播放完成后直接返回，无需额外等待
                # --- END: 修改部分 ---
            except Exception as e:
                self.logger.error(f"[播放协议] 线程{thread_id} 播放协议出错: {e}")
            finally:
                self.logger.info(f"[播放协议] 线程{thread_id} 播放结束，准备释放PTT键，use_robust_release={use_robust_release}")
                time.sleep(0.1)
                if ptt_key and ptt_acquired:
                    self.release_ptt_key(ptt_key)

                    # --- START: 修改部分 (根据类型选择兜底机制) ---
                    if use_robust_release:
                        # 音效转发使用新的智能兜底
                        self.logger.info(f"[播放协议] 线程{thread_id} 安排智能兜底释放")
                        self.schedule_robust_release(ptt_key)
                    else:
                        # 音板播放使用旧的独立兜底
                        self.logger.info(f"[播放协议] 线程{thread_id} 启动独立兜底释放")
                        self.start_robust_release_protocol(ptt_key, independent=True)
                    # --- END: 修改部分 ---

        playback_thread = threading.Thread(target=playback_worker, daemon=True, name="VoicePlayback")
        if not allow_overlap:
            self.current_playback_protocol_thread = playback_thread
        playback_thread.start()
        return True

    # --- START: 修改部分 (为音效转发创建专用入口) ---
    def play_pygame_sound_to_voice(self, sound_obj: pygame.mixer.Sound, volume: float = 1.0) -> bool:
        """
        播放pygame音效到语音频道 (供AudioManager调用)，强制使用覆盖模式和零延迟。
        这是专门为音效转发设计的入口。
        支持快速连续音效：新音效会自动刷新PTT释放时间，不会重复按键。
        """
        from config import config
        # v2.1.1: 检查"语音播放"主开关 — 此前用户在 UI 上关闭"语音播放"
        # 写入 config.voice_output_enabled=False 但运行时从未检查, 自动转发仍在跑
        if not getattr(config, "voice_output_enabled", False):
            self.logger.debug("[音效转发] voice_output_enabled=False, 跳过自动转发")
            return False
        self.logger.info("[音效转发] play_pygame_sound_to_voice 被调用")
        self.logger.info(f"[音效转发] is_initialized={self.is_initialized}")
        self.logger.info(f"[音效转发] VB-Cable device_id={self.vb_cable_device_id}")
        self.logger.info(f"[音效转发] PTT enabled={config.voice_output_ptt_enabled}, key={config.voice_output_ptt_key}")
        
        result = self.play_audio_with_ptt_protocol(
            sound_obj=sound_obj,
            volume=volume,
            mode="覆盖",  # 强制覆盖模式，确保麦克风静音
            also_local=config.voice_output_also_local,
            ptt_key=config.voice_output_ptt_key if config.voice_output_ptt_enabled else None,
            ptt_delay=0,  # 强制零延迟
            allow_overlap=True,  # 允许与其他音效共存，不会互相打断
            use_robust_release=True  # 使用智能兜底：自动刷新释放时间，避免冲突
        )
        self.logger.info(f"[音效转发] play_audio_with_ptt_protocol 返回: {result}")
        return result
    # --- END: 修改部分 ---

    def press_ptt_key(self, ptt_key):
        with self.ptt_lock:
            self.ptt_lease_counter += 1
            if not self.ptt_key_pressed:
                try:
                    keyboard.press(ptt_key)
                    self.ptt_key_pressed = True
                    self.logger.info(f"[PTT] ✓ 按下开麦键: {ptt_key} (租约数: {self.ptt_lease_counter})")
                except Exception as e:
                    self.logger.error(f"[PTT] ✗ 按下开麦键失败: {e}")
                    self.ptt_lease_counter -= 1
            else:
                self.logger.info(f"[PTT] 键已按下，复用会话 (租约数: {self.ptt_lease_counter}) ← 快速连续音效")

    def release_ptt_key(self, ptt_key):
        with self.ptt_lock:
            if self.ptt_lease_counter > 0:
                self.ptt_lease_counter -= 1
            self.logger.info(f"[PTT] 释放租约 (剩余: {self.ptt_lease_counter})")
            if self.ptt_lease_counter == 0 and self.ptt_key_pressed:
                try:
                    keyboard.release(ptt_key)
                    self.ptt_key_pressed = False
                    self.logger.info(f"[PTT] ✓ 释放开麦键: {ptt_key}")
                except Exception as e:
                    self.logger.error(f"[PTT] ✗ 释放开麦键失败: {e}")
                    self.ptt_key_pressed = False

    def force_release_ptt_key(self, ptt_key: Optional[str] = None):
        self.logger.info("[PTT] 正在强制释放PTT键并重置状态...")
        from config import config
        key_to_release = ptt_key if ptt_key else config.voice_output_ptt_key
        with self.ptt_lock:
            if self.ptt_key_pressed:
                try:
                    keyboard.release(key_to_release)
                    self.logger.info(f"[PTT] 强制释放开麦键: {key_to_release}")
                except Exception as e:
                    self.logger.error(f"[PTT] 强制释放开麦键失败: {e}")
            self.ptt_key_pressed = False
            self.ptt_lease_counter = 0

    # --- START: 修改部分 (新的智能兜底机制实现) ---
    def _robust_release_worker(self, ptt_key):
        """智能兜底协议的工作函数 (由计时器触发)。"""
        self.logger.info("[PTT] [智能兜底] 计时器触发，开始执行释放协议...")
        try:
            for i in range(3):
                time.sleep(0.3)
                with self.ptt_lock:
                    if self.ptt_lease_counter > 0:
                        self.logger.info("[PTT] [智能兜底] 检测到新的播放租约，中止释放协议。")
                        return
                    if not self.ptt_key_pressed:
                        self.logger.info("[PTT] [智能兜底] 键已释放，无需兜底。")
                        return
                    # release 必须在锁内执行：若在锁外，新音效刚 press 并递增租约后，
                    # 兜底仍可能误放刚按下的键（竞态）
                    keyboard.release(ptt_key)
                    # 物理键已弹起，状态必须同步清掉：否则清状态前来的新转发
                    # 会走"复用会话"分支不再补按，音效带着关闭的麦克风播出
                    self.ptt_key_pressed = False
            self.logger.info("[PTT] [智能兜底] 协议执行完毕。")
        except Exception as e:
            self.logger.error(f"[PTT] [智能兜底] 执行过程中发生错误: {e}")

    def schedule_robust_release(self, ptt_key):
        """安排（或重置）智能兜底释放计时器。"""
        with self.robust_release_lock:
            # 如果已有计时器，先取消
            if self.robust_release_timer and self.robust_release_timer.is_alive():
                self.robust_release_timer.cancel()
                self.logger.info("[PTT] [智能兜底] ⟳ 刷新释放时间：取消旧计时器")
            
            # 创建并启动新的计时器，1秒后执行
            self.robust_release_timer = threading.Timer(1.0, self._robust_release_worker, args=[ptt_key])
            self.robust_release_timer.daemon = True
            self.robust_release_timer.start()
            self.logger.info("[PTT] [智能兜底] ⏰ 安排新的释放计时器（1秒后执行）")

    def cancel_robust_release(self):
        """取消待执行的智能兜底释放计时器。"""
        with self.robust_release_lock:
            if self.robust_release_timer and self.robust_release_timer.is_alive():
                self.robust_release_timer.cancel()
                self.logger.info("[PTT] [智能兜底] 新的播放请求已取消释放计时器。")

    def start_robust_release_protocol(self, ptt_key, independent=False):
        """启动独立的守护线程来执行兜底释放协议。"""
        if not independent:
            return # 这个函数现在只给音板用
            
        def _independent_worker():
            try:
                # 缩短延迟：3次释放，每次间隔0.2秒，总共0.6秒
                for i in range(3):
                    time.sleep(0.2)
                    with self.ptt_lock:
                        # 有新租约说明有新的播放正按着键，中止兜底避免误放
                        if self.ptt_lease_counter > 0:
                            self.logger.info("[PTT] [独立兜底] 检测到新的播放租约，中止释放协议。")
                            return
                        keyboard.release(ptt_key)
                        # 同智能兜底：物理弹起立即同步状态，防"复用会话"不补按
                        self.ptt_key_pressed = False
                self.logger.info("[PTT] [独立兜底] 协议执行完毕。")
            except Exception as e:
                self.logger.error(f"[PTT] [独立兜底] 执行过程中发生错误: {e}")
        
        release_thread = threading.Thread(target=_independent_worker, daemon=True, name="VoiceKeyRelease")
        release_thread.start()
    # --- END: 修改部分 ---

    def _play_with_mix_data(self, audio_data: np.ndarray, sample_rate: int, also_local: bool, cancel_event=None):
        try:
            target_rate = self.vb_cable_rate
            if target_rate is None: raise Exception("混音目标采样率未知")
            if sample_rate != target_rate:
                audio_data = self.resample_audio(audio_data, sample_rate, target_rate)
            with self.mix_lock:
                self.current_mix_audio = audio_data
                self.mix_position = 0
            if also_local:
                self._play_data_locally(audio_data, target_rate, cancel_event=cancel_event)
        except Exception as e:
            self.logger.error(f"[混音播放] 混音播放数据失败: {e}")

    def _play_data_locally(self, audio_data, sample_rate, cancel_event=None):
        def _write_all(device_id):
            stream = sd.OutputStream(device=device_id, samplerate=sample_rate, channels=2, blocksize=self.chunk_size, latency='low', dtype='float32')
            stream.start()
            for i in range(0, len(audio_data), self.chunk_size):
                if cancel_event is not None and cancel_event.is_set():
                    break
                chunk = audio_data[i:min(i + self.chunk_size, len(audio_data))]
                stream.write(chunk)
            stream.stop()
            stream.close()

        def play_local_thread():
            # QA-017: 优先走声音映射器 —— 每次开流才解析到"当时的 Windows 默认输出"，
            # 用户中途换耳机能自动跟随。映射器不可用时才退回启动时冻结的那台设备。
            primary = self.local_monitor_device_id
            if primary is None:
                primary = self.default_speaker_id
            try:
                try:
                    _write_all(primary)
                except Exception:
                    if primary == self.default_speaker_id:
                        raise
                    # 映射器开流失败（少见）：再试一次启动时那台，别直接哑掉
                    self.logger.warning("[本地播放] 声音映射器开流失败，退回默认扬声器")
                    _write_all(self.default_speaker_id)
            except Exception as e:
                self.logger.error(f"[本地播放] 本地播放失败: {e}")
            finally:
                with self.local_playback_threads_lock:
                    if threading.current_thread() in self.local_playback_threads:
                        self.local_playback_threads.remove(threading.current_thread())
        thread = threading.Thread(target=play_local_thread, daemon=True, name="VoiceLocalPlay")
        with self.local_playback_threads_lock:
            self.local_playback_threads.append(thread)
        thread.start()

    def _acquire_mic_mute(self):
        with self._mute_lock:
            self._mute_refcount += 1
            if self._mute_refcount == 1:
                self.set_microphone_mute(True)

    def _release_mic_mute(self):
        with self._mute_lock:
            if self._mute_refcount > 0:
                self._mute_refcount -= 1
            if self._mute_refcount == 0:
                self.set_microphone_mute(False)

    def _play_file_data(self, audio_data: np.ndarray, sample_rate: int, also_local: bool, auto_mode: bool = False, cancel_event=None):
        was_passthrough_active = self.microphone_passthrough_active
        self.logger.info(f"[播放数据] passthrough_active={was_passthrough_active}, auto_mode={auto_mode}, 将静音麦克风={'是' if (was_passthrough_active and auto_mode) else '否'}")
        if was_passthrough_active and auto_mode:
            self._acquire_mic_mute()
        vb_stream = None
        try:
            target_rate = self.vb_cable_rate
            if target_rate is None: raise Exception("播放目标采样率未知")
            if sample_rate != target_rate:
                audio_data = self.resample_audio(audio_data, sample_rate, target_rate)
            vb_info = sd.query_devices(self.vb_cable_device_id)
            output_channels = min(vb_info['max_output_channels'], 2)
            if audio_data.shape[1] != output_channels:
                if output_channels == 1:
                    audio_data = np.mean(audio_data, axis=1, keepdims=True)
                elif output_channels == 2 and audio_data.shape[1] == 1:
                    audio_data = np.column_stack((audio_data, audio_data))
            vb_stream = sd.OutputStream(device=self.vb_cable_device_id, samplerate=target_rate, channels=output_channels, blocksize=self.chunk_size, latency=self.latency, dtype='float32')
            vb_stream.start()
            if also_local:
                self._play_data_locally(audio_data, target_rate, cancel_event=cancel_event)

            # 写入所有音频数据
            start_time = time.time()
            for i in range(0, len(audio_data), self.chunk_size):
                if cancel_event is not None and cancel_event.is_set():
                    break
                chunk = audio_data[i:i + self.chunk_size]
                vb_stream.write(chunk)
            write_time = time.time() - start_time
            
            # 计算实际播放时长
            actual_duration = len(audio_data) / target_rate
            self.logger.info(f"[播放数据] 数据写入耗时={write_time:.2f}秒, 音频实际时长={actual_duration:.2f}秒")
            
            # write() 会阻塞直到数据被消费，所以写入时间应该接近播放时间
            # 如果写入很快完成，说明数据还在缓冲区，需要等待
            remaining_time = actual_duration - write_time
            if remaining_time > 0:
                self.logger.info(f"[播放数据] 等待缓冲区播放完成，剩余时间={remaining_time:.2f}秒")
                time.sleep(remaining_time + 0.1)
        except Exception as e:
            self.logger.error(f"[播放数据] 播放数据失败: {e}")
        finally:
            if vb_stream: vb_stream.stop(); vb_stream.close()
            if was_passthrough_active and auto_mode:
                self.logger.info("[播放数据] 释放麦克风静音引用")
                self._release_mic_mute()
    
    def get_sound_duration(self, audio_file: str) -> float:
        try:
            return sf.info(audio_file).duration
        except Exception:
            return 0.0
    
    def stop_playback(self):
        with self.current_playback_lock:
            self.stop_playback_flag = True
        # 只取消"当前独占播放"的令牌；重叠转发（击杀音效等）各持独立令牌不受影响
        current_cancel = getattr(self, "_current_cancel_event", None)
        if current_cancel is not None:
            current_cancel.set()
        with self.mix_lock:
            self.current_mix_audio = None
            self.mix_position = 0
        # 全停路径：静音引用计数一并清零再解除静音
        with self._mute_lock:
            self._mute_refcount = 0
        self.set_microphone_mute(False)
        while not self.playback_queue.empty():
            try: self.playback_queue.get_nowait()
            except queue.Empty: break
        with self.local_playback_threads_lock:
            threads_copy = self.local_playback_threads[:]
        for thread in threads_copy:
            if thread.is_alive():
                thread.join(timeout=0.1)
        with self.local_playback_threads_lock:
            self.local_playback_threads.clear()
        if self.current_playback_protocol_thread and self.current_playback_protocol_thread.is_alive():
            self.current_playback_protocol_thread.join(timeout=0.5)
        with self.current_playback_lock:
            self.is_playing = False
            self.stop_playback_flag = False
        self.logger.info("[播放控制] 播放已停止")
    
    def cleanup(self):
        self.stop_playback()
        self.stop_microphone_passthrough()
        if self.current_playback_protocol_thread and self.current_playback_protocol_thread.is_alive():
            self.current_playback_protocol_thread.join(timeout=1.0)
        with self.local_playback_threads_lock:
            threads_copy = self.local_playback_threads[:]
        for thread in threads_copy:
            if thread.is_alive():
                thread.join(timeout=0.5)
        with self.local_playback_threads_lock:
            self.local_playback_threads.clear()

# 全局实例
_voice_output_manager = None

def get_voice_output_manager() -> VoiceOutputManager:
    """获取全局语音输出管理器实例"""
    global _voice_output_manager
    if _voice_output_manager is None:
        _voice_output_manager = VoiceOutputManager()
    return _voice_output_manager
