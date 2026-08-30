# SPDX-License-Identifier: GPL-3.0-or-later
import pygame
import threading
import time
import os
import random
from typing import Optional, Dict, List, Callable, Set
import json
from config import config, get_app_data_dir
from core.utils.logger import get_logger

# 音频标签读取
try:
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    mutagen_available = True
except ImportError:
    mutagen_available = False
    logger = get_logger("MusicPlayer")
    logger.warning("警告: mutagen未安装，无法读取音频标签信息")


def is_remote_track_path(path: str) -> bool:
    """本播放器只播本地文件，网络地址一律不接受（历史配置里可能残留在线曲目）"""
    return str(path or "").strip().lower().startswith(("http://", "https://"))


LEGACY_PLAY_MODE_MAP = {
    "sequential": "sequence",
    "random": "shuffle",
    "single": "repeat_one",
    "loop": "repeat_all",
}

PLAY_MODE_LABELS = {
    "sequence": "顺序播放",
    "shuffle": "随机播放",
    "repeat_one": "单曲循环",
    "repeat_all": "列表循环",
}


def normalize_music_play_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    normalized = LEGACY_PLAY_MODE_MAP.get(normalized, normalized)
    if normalized in PLAY_MODE_LABELS:
        return normalized
    return "sequence"

class MusicPlayer:
    """音乐播放器核心类"""
    
    def __init__(self):
        self.logger = get_logger()  # 初始化logger
        pygame.init()
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        
        self.is_playing = False
        self.is_paused = False
        self.current_track = None
        self.current_index = -1
        self.volume = config.music_volume
        self.base_volume = config.music_volume
        self.temp_volume = None
        
        # 手动时间跟踪（因为 pygame.mixer.music.get_pos() 不可靠）
        self.play_start_time = None  # 播放开始的时间
        self.play_start_position = 0.0  # 播放开始的位置（用于 seek）
        self.pause_start_time = None  # 暂停开始的时间
        self.total_pause_time = 0.0  # 累计暂停时长
        
        # 播放列表管理
        self.current_playlist_name = config.music_current_playlist
        self._ensure_default_playlists()  # 确保有默认播放列表
        self.playlist = self._load_playlist()
        
        # 收藏列表（存储音轨的唯一标识）
        self.favorites = self._load_favorites()
        
        self.play_mode = normalize_music_play_mode(config.music_play_mode)
        if self.play_mode != config.music_play_mode:
            config.music_play_mode = self.play_mode
            config.save_config()
        
        self.on_track_change = None
        self.on_state_change = None
        self.on_progress_update = None
        self.on_playlist_update = None
        self.on_playlist_change = None  # 新增：播放列表切换回调
        
        self.progress_thread = None
        self.stop_progress = False
        
        self.fade_thread = None
        self.stop_fade = False
        
        self._apply_effective_volume()
        
        # 播放结束检测相关
        self.end_check_thread = None
        self.stop_end_check = False
        self._track_end_lock = threading.Lock()
        self._last_track_end_time = 0
        
        # 播放状态跟踪
        self.track_start_time = 0
        self.track_expected_end_time = 0
        # restore_state 后首次 resume 需要跳转到保存位置的显式标志。
        # 旧实现用 "play_start_position>0 且 total_pause_time==0" 推断，
        # 会误伤 seek 后暂停再恢复的场景（倒退回 seek 点）
        self._pending_restore_seek = False
        
        # 调试模式
        self.debug_mode = True  # 开启详细日志

        # 恢复上次的播放状态(曲目和进度)
        self.restore_state()

    def _clamp_volume(self, volume: float) -> float:
        return max(0.0, min(1.0, float(volume)))

    def _get_effective_volume(self) -> float:
        if self.temp_volume is not None:
            return self._clamp_volume(self.temp_volume)
        return self._clamp_volume(self.base_volume)

    def _apply_effective_volume(self) -> float:
        actual_volume = self._get_effective_volume()
        pygame.mixer.music.set_volume(actual_volume)
        return actual_volume

    def _resolve_track_audio_path(self, track: Optional[Dict]) -> Optional[str]:
        if not isinstance(track, dict):
            return None

        resolved_path = str(track.get("_resolved_path", "") or "").strip()
        if resolved_path and os.path.isfile(resolved_path):
            return resolved_path

        raw_path = str(track.get("path", "") or "").strip()
        if not raw_path:
            return None

        # 只认磁盘上真实存在的文件；网络地址（旧配置残留）一律判为不可用，
        # 交由上层走"加载失败→下一首"的既有链路
        return raw_path if os.path.isfile(raw_path) else None

    def _ensure_default_playlists(self):
        """确保有默认的播放列表"""
        if not config.music_playlists:
            config.music_playlists = {}
        
        # 确保有默认播放列表
        if "默认" not in config.music_playlists:
            config.music_playlists["默认"] = []
        
        # 确保有收藏播放列表
        if "收藏" not in config.music_playlists:
            config.music_playlists["收藏"] = []
        
        # 如果当前播放列表不存在，切换到默认
        if self.current_playlist_name not in config.music_playlists:
            self.current_playlist_name = "默认"
            config.music_current_playlist = "默认"
        
        config.save_config()
    
    def _load_favorites(self) -> Set[str]:
        """加载收藏列表"""
        favorites_file = os.path.join(get_app_data_dir(), "music_favorites.json")
        try:
            if os.path.exists(favorites_file):
                with open(favorites_file, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
        except Exception as e:
            self.logger.error(f"加载收藏列表失败: {e}")
        return set()
    
    def _save_favorites(self):
        """保存收藏列表"""
        favorites_file = os.path.join(get_app_data_dir(), "music_favorites.json")
        try:
            with open(favorites_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.favorites), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存收藏列表失败: {e}")
    
    def _get_track_id(self, track: Dict) -> str:
        """获取音轨的唯一标识"""
        # 使用路径和标题的组合作为唯一标识
        return f"{track.get('path', '')}|{track.get('title', '')}"
    
    def is_favorite(self, track: Dict) -> bool:
        """检查音轨是否被收藏"""
        return self._get_track_id(track) in self.favorites
    
    def toggle_favorite(self, track: Dict):
        """切换收藏状态"""
        track_id = self._get_track_id(track)
        if track_id in self.favorites:
            self.favorites.remove(track_id)
            # 如果在收藏播放列表中，也要移除
            if "收藏" in config.music_playlists:
                favorites_playlist = config.music_playlists["收藏"]
                # 查找并移除相同的音轨
                for i, t in enumerate(favorites_playlist):
                    if self._get_track_id(t) == track_id:
                        favorites_playlist.pop(i)
                        break
        else:
            self.favorites.add(track_id)
            # 同时添加到收藏播放列表
            if "收藏" in config.music_playlists:
                # 避免重复添加
                favorites_playlist = config.music_playlists["收藏"]
                if not any(self._get_track_id(t) == track_id for t in favorites_playlist):
                    favorites_playlist.append(track.copy())
        
        self._save_favorites()
        config.save_config()
        
        # 如果当前在收藏播放列表，需要更新
        if self.current_playlist_name == "收藏":
            self.playlist = self._load_playlist()
            if self.on_playlist_update:
                self.on_playlist_update()
    
    def create_playlist(self, name: str) -> bool:
        """创建新播放列表"""
        if name in config.music_playlists:
            return False  # 已存在
        
        config.music_playlists[name] = []
        config.save_config()
        return True
    
    def delete_playlist(self, name: str) -> bool:
        """删除播放列表"""
        if name in ["默认", "收藏"]:
            return False  # 不能删除默认和收藏列表
        
        if name not in config.music_playlists:
            return False
        
        del config.music_playlists[name]
        
        # 如果删除的是当前播放列表，切换到默认
        if self.current_playlist_name == name:
            self.switch_playlist("默认")
        
        config.save_config()
        return True
    
    def rename_playlist(self, old_name: str, new_name: str) -> bool:
        """重命名播放列表"""
        if old_name in ["默认", "收藏"] or new_name in config.music_playlists:
            return False
        
        if old_name not in config.music_playlists:
            return False
        
        config.music_playlists[new_name] = config.music_playlists[old_name]
        del config.music_playlists[old_name]
        
        # 如果重命名的是当前播放列表
        if self.current_playlist_name == old_name:
            self.current_playlist_name = new_name
            config.music_current_playlist = new_name
        
        config.save_config()
        return True
    
    def switch_playlist(self, name: str):
        """切换播放列表"""
        if name not in config.music_playlists:
            return
        
        # 如果切换到的是同一个播放列表，则不做任何操作
        if name == self.current_playlist_name:
            self._debug_log(f"已经在播放列表 '{name}' 中，无需切换")
            return
        
        # 保存当前播放状态
        if self.is_playing:
            self.stop()
        
        self.current_playlist_name = name
        config.music_current_playlist = name
        self.playlist = self._load_playlist()
        self.current_index = -1
        # 同步清掉旧列表的保存索引/进度，否则控制栏会用旧索引到新列表取曲
        config.music_current_index = -1
        config.music_current_position = 0.0

        config.save_config()
        
        if self.on_playlist_change:
            self.on_playlist_change(name)
        if self.on_playlist_update:
            self.on_playlist_update()
    
    def get_all_playlists(self) -> List[str]:
        """获取所有播放列表名称"""
        return list(config.music_playlists.keys())
    
    def export_playlist(self, playlist_name: str = None, file_path: str = None) -> bool:
        """导出播放列表为M3U格式"""
        if playlist_name is None:
            playlist_name = self.current_playlist_name
        
        if playlist_name not in config.music_playlists:
            return False
        
        if file_path is None:
            file_path = os.path.join(get_app_data_dir(), f"{playlist_name}.m3u")
        
        try:
            playlist = config.music_playlists[playlist_name]
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                for track in playlist:
                    duration = track.get('duration', -1)
                    title = track.get('title', 'Unknown')
                    artist = track.get('artist', 'Unknown')
                    path = track.get('path', '')
                    
                    f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                    f.write(f"{path}\n")
            return True
        except Exception as e:
            self.logger.error(f"导出播放列表失败: {e}")
            return False
    
    def import_playlist(self, file_path: str, playlist_name: str = None) -> bool:
        """导入M3U格式的播放列表"""
        try:
            if not os.path.exists(file_path):
                return False
            
            # 如果没有指定名称，使用文件名
            if playlist_name is None:
                playlist_name = os.path.splitext(os.path.basename(file_path))[0]
            
            # 确保播放列表名称唯一
            base_name = playlist_name
            counter = 1
            while playlist_name in config.music_playlists:
                playlist_name = f"{base_name} ({counter})"
                counter += 1
            
            imported_tracks = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                if line.startswith('#EXTINF:'):
                    # 解析信息行
                    info_parts = line[8:].split(',', 1)
                    duration = int(info_parts[0]) if info_parts[0] != '-1' else 0
                    
                    if len(info_parts) > 1:
                        # 尝试分离艺术家和标题
                        title_info = info_parts[1]
                        if ' - ' in title_info:
                            artist, title = title_info.split(' - ', 1)
                        else:
                            artist = "未知艺术家"
                            title = title_info
                    else:
                        artist = "未知艺术家"
                        title = "未知标题"
                    
                    # 下一行应该是文件路径
                    i += 1
                    if i < len(lines):
                        path = lines[i].strip()
                        if path and not path.startswith('#'):
                            # M3U 里可能夹带在线地址，本播放器播不了，直接丢弃而不是
                            # 塞进列表当"永远加载失败"的死条目
                            if is_remote_track_path(path):
                                self.logger.warning(f"导入播放列表时跳过在线曲目: {path}")
                            else:
                                track = {
                                    "type": "local",
                                    "path": path,
                                    "title": title,
                                    "artist": artist,
                                    "duration": duration
                                }
                                imported_tracks.append(track)
                elif line and not line.startswith('#'):
                    # 没有信息行的文件路径
                    path = line
                    if is_remote_track_path(path):
                        self.logger.warning(f"导入播放列表时跳过在线曲目: {path}")
                    else:
                        title = os.path.splitext(os.path.basename(path))[0]
                        track = {
                            "type": "local",
                            "path": path,
                            "title": title,
                            "artist": "未知艺术家",
                            "duration": 0
                        }
                        imported_tracks.append(track)

                i += 1
            
            if imported_tracks:
                config.music_playlists[playlist_name] = imported_tracks
                config.save_config()
                return True

        except Exception as e:
            self.logger.error(f"导入播放列表失败: {e}")

        return False
    
    def move_track(self, from_index: int, to_index: int):
        """移动音轨位置（用于拖拽排序）"""
        if 0 <= from_index < len(self.playlist) and 0 <= to_index < len(self.playlist):
            track = self.playlist.pop(from_index)
            self.playlist.insert(to_index, track)
            
            # 更新当前播放索引
            if self.current_index == from_index:
                self.current_index = to_index
            elif from_index < self.current_index <= to_index:
                self.current_index -= 1
            elif to_index <= self.current_index < from_index:
                self.current_index += 1
            
            self._save_playlist()
    
    def copy_track_to_playlist(self, track: Dict, target_playlist: str):
        """复制音轨到其他播放列表"""
        if target_playlist not in config.music_playlists:
            return False
        
        config.music_playlists[target_playlist].append(track.copy())
        config.save_config()
        
        # 如果复制到当前播放列表，更新显示
        if target_playlist == self.current_playlist_name:
            self.playlist = self._load_playlist()
            if self.on_playlist_update:
                self.on_playlist_update()
        
        return True
    
    def remove_tracks(self, indices: List[int]):
        """批量删除音轨"""
        # 从大到小排序，避免删除时索引变化
        indices = sorted(indices, reverse=True)
        
        for index in indices:
            if 0 <= index < len(self.playlist):
                if index == self.current_index:
                    self.stop()
                elif index < self.current_index:
                    self.current_index -= 1
                
                self.playlist.pop(index)
        
        self._save_playlist()
        config.music_current_index = self.current_index
        config.save_config()
    
    def _debug_log(self, message):
        """调试日志"""
        if self.debug_mode:
            self.logger.debug(f"[音乐播放器] {message}")
        
    def _load_playlist(self):
        if self.current_playlist_name in config.music_playlists:
            return config.music_playlists[self.current_playlist_name].copy()
        return []
        
    def _save_playlist(self):
        config.music_playlists[self.current_playlist_name] = self.playlist.copy()
        config.save_config()
        if self.on_playlist_update:
            self.on_playlist_update()

    def _start_end_check_thread(self):
        """启动播放结束检测线程 - 完全重写的版本"""
        # 如果已有检测线程在运行，先停止它
        if self.end_check_thread and self.end_check_thread.is_alive():
            self.stop_end_check = True
            self.end_check_thread.join(timeout=0.5)
            
        self.stop_end_check = False
        
        def check_end():
            self._debug_log("播放结束检测线程启动")
            consecutive_not_busy = 0
            
            while not self.stop_end_check:
                try:
                    # 只在播放状态下检测
                    if not self.is_playing or self.is_paused:
                        time.sleep(0.1)
                        continue
                    
                    current_time = time.time()
                    
                    # 方法1: 检查 pygame.mixer.music.get_busy()
                    is_busy = pygame.mixer.music.get_busy()
                    
                    if not is_busy:
                        consecutive_not_busy += 1
                        self._debug_log(f"音乐不在播放 (连续 {consecutive_not_busy} 次)")
                        
                        # 如果连续多次检测到不在播放，认为已结束
                        if consecutive_not_busy >= 3:  # 300ms
                            self._debug_log("确认音乐已结束 (get_busy = False)")
                            self._handle_track_end()
                            break
                    else:
                        # 重置计数
                        if consecutive_not_busy > 0:
                            self._debug_log("音乐恢复播放，重置计数")
                        consecutive_not_busy = 0
                        
                        # 方法2（兜底）: 检查是否超过预期结束时间。
                        # duration 元数据可能偏小（M3U 里写的粗略值），容差取 5s，
                        # 避免 get_busy 仍为 True 的正常播放被提前判结束而连跳
                        if self.track_expected_end_time > 0:
                            if current_time > self.track_expected_end_time + 5.0:
                                self._debug_log(f"已超过预期结束时间 {self.track_expected_end_time:.1f}")
                                self._handle_track_end()
                                break
                    
                    # 每100ms检查一次
                    time.sleep(0.1)
                    
                except Exception as e:
                    self._debug_log(f"检测线程错误: {e}")
                    time.sleep(0.1)
                    
            self._debug_log("播放结束检测线程退出")
            
        self.end_check_thread = threading.Thread(target=check_end, daemon=True, name="MusicEndCheck")
        self.end_check_thread.start()
        
    def _handle_track_end(self):
        """处理曲目结束 - 线程安全版本"""
        # 检查是否太快重复触发
        current_time = time.time()
        if current_time - self._last_track_end_time < 1.0:  # 1秒内不重复触发
            self._debug_log("忽略重复的结束事件")
            return
            
        # 尝试获取锁
        if not self._track_end_lock.acquire(blocking=False):
            self._debug_log("已在处理曲目结束，跳过")
            return
            
        try:
            self._last_track_end_time = current_time
            self._debug_log(f"处理曲目结束，播放模式: {self.play_mode}")
            
            # 停止检测线程
            self.stop_end_check = True
            
            # 确保音乐停止
            pygame.mixer.music.stop()
            
            if not self.playlist:
                self._debug_log("播放列表为空，停止播放")
                self.stop()
                return
            
            # 根据播放模式决定下一步
            # 使用定时器在新线程中执行，避免线程冲突
            if self.play_mode == "repeat_one":
                self._debug_log("单曲循环模式，重新播放当前曲目")
                threading.Timer(0.2, self.play_current).start()
            else:
                self._debug_log("切换到下一首")
                threading.Timer(0.2, self.next).start()
                
        finally:
            # 立即释放锁
            self._track_end_lock.release()
            
    def play(self, index: Optional[int] = None):
        if not self.playlist:
            # 不内置任何曲目，首次运行播放列表就是空的，等用户自己导入本地文件
            self.logger.warning("播放列表为空，请先添加本地音乐文件。")
            return
            
        if index is not None:
            if 0 <= index < len(self.playlist):
                self.current_index = index
                self._play_track(self.playlist[self.current_index])
            else:
                self.logger.error(f"无效的播放索引: {index}")
        else:
            if self.is_playing and self.is_paused:
                self.resume()
            elif not self.is_playing:
                if self.current_index < 0:
                    self.current_index = 0
                if 0 <= self.current_index < len(self.playlist):
                    self._play_track(self.playlist[self.current_index])
            
    def play_current(self):
        if 0 <= self.current_index < len(self.playlist):
            self._play_track(self.playlist[self.current_index])
            
    def _play_track(self, track: Dict):
        try:
            self._debug_log(f"准备播放: {track.get('title', 'Unknown')}")
            
            # RN-195：这里是 play / play_current / next / previous / 自动续播
            # 的**唯一汇合点** —— 通知挂在这儿，就不用挂到每一个入口上，
            # 而漏掉任何一个入口都意味着"用户放着音乐却没有控制条"。
            # 放在最前面而不是加载成功之后：控制条本来就要负责显示「[加载中...]」
            # （下面那个 on_track_change），它得先存在。
            notify_playback_started()

            # 停止当前播放
            self.stop_progress = True
            self.stop_end_check = True
            
            # 取消之前的加载任务
            self.cancel_loading()
            
            # 确保音乐完全停止
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                # 等待停止
                timeout = 0.5
                start_time = time.time()
                while pygame.mixer.music.get_busy() and time.time() - start_time < timeout:
                    time.sleep(0.01)
                self._debug_log("已停止之前的播放")
            
            # 等待线程结束
            if self.progress_thread and self.progress_thread.is_alive():
                if threading.current_thread() != self.progress_thread:
                    self.progress_thread.join(timeout=0.5)
            
            if self.end_check_thread and self.end_check_thread.is_alive():
                if threading.current_thread() != self.end_check_thread:
                    self.end_check_thread.join(timeout=0.5)
            
            # 更新UI状态为加载中
            if self.on_track_change:
                # 创建一个临时track对象，添加加载状态
                loading_track = track.copy()
                loading_track['title'] = f"[加载中...] {track.get('title', 'Unknown')}"
                self.on_track_change(loading_track)
            
            # 启动异步加载
            self.loader_thread = MusicLoaderThread(self, track)
            self.loader_thread.start()

        except Exception as e:
            self.logger.error(f"准备播放失败: {e}", exc_info=True)
            # 延迟调用next避免立即触发
            threading.Timer(0.5, self.next).start()

    def cancel_loading(self):
        """取消当前的加载任务"""
        if hasattr(self, 'loader_thread') and self.loader_thread and self.loader_thread.is_alive():
            self.loader_thread.cancel()
            self.loader_thread.join(timeout=0.5)
            self.loader_thread = None
            self._debug_log("已取消之前的加载任务")

    def _on_track_loaded(self, track: Dict, audio_path: str):
        """当音轨加载完成时调用"""
        try:
            # 再次检查是否已被取消（虽然线程内部有检查，但双重保险）
            if hasattr(self, 'loader_thread') and self.loader_thread and self.loader_thread.is_cancelled:
                return

            self._debug_log(f"音频加载完成: {audio_path}")
            
            # 加载音频到Pygame
            pygame.mixer.music.load(audio_path)
            
            # 开始播放
            pygame.mixer.music.play()
            self.is_playing = True
            self.is_paused = False
            self.current_track = {**track, "_resolved_path": audio_path}
            
            # 记录播放开始时间和预期结束时间
            self.track_start_time = time.time()
            duration = track.get('duration', 0)
            if duration > 0:
                self.track_expected_end_time = self.track_start_time + duration
                self._debug_log(f"预期结束时间: {self.track_expected_end_time:.1f} (时长: {duration}秒)")
            else:
                self.track_expected_end_time = 0
                self._debug_log("未知时长")
            
            # 初始化手动时间跟踪
            self.play_start_time = time.time()
            self.play_start_position = 0.0
            self.pause_start_time = None
            self.total_pause_time = 0.0
            
            self._apply_effective_volume()
            
            config.music_is_playing = True
            config.music_current_index = self.current_index
            config.save_config()
            
            # 通知UI更新（恢复正常标题）
            if self.on_track_change:
                self.on_track_change(track)
            if self.on_state_change:
                self.on_state_change(True, False)
                
            # 启动进度更新
            self._start_progress_update()
            # 启动播放结束检测
            self._start_end_check_thread()
            
            self._debug_log(f"播放已开始: {track.get('title', 'Unknown')}")

        except pygame.error as e:
            self.logger.error(f"Pygame播放错误: {e}")
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            except Exception:
                pass
            self.stop()
        except Exception as e:
            self.logger.error(f"播放失败: {e}", exc_info=True)
            # 延迟调用next
            threading.Timer(0.5, self.next).start()

    def _on_track_load_error(self, track: Dict, error: str):
        """当音轨加载失败时调用"""
        self.logger.error(f"音频加载失败: {track.get('title', 'Unknown')} - {error}")
        # 延迟后尝试下一首
        threading.Timer(0.5, self.next).start()


        
    def stop(self):
        self._debug_log("停止播放")
        
        # 停止所有检测线程
        self.stop_progress = True
        self.stop_end_check = True
        
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        config.music_is_playing = False
        
        if self.on_state_change:
            self.on_state_change(False, False)
            
    def next(self):
        if not self.playlist:
            self.logger.info("[下一首] 播放列表为空")
            return
            
        previous_index = self.current_index
        
        if self.play_mode == "shuffle":
            if len(self.playlist) > 1:
                new_index = self.current_index
                while new_index == self.current_index:
                    new_index = random.randint(0, len(self.playlist) - 1)
                self.current_index = new_index
            else:
                self.current_index = 0
        elif self.play_mode == "repeat_all":
            self.current_index = (self.current_index + 1) % len(self.playlist)
        else:  # sequence mode
            self.current_index += 1
            if self.current_index >= len(self.playlist):
                if self.play_mode == "sequence":
                    # 顺序播放模式，播放到最后一首后停止
                    self.current_index = len(self.playlist) - 1
                    self.stop()
                    self.logger.info("[下一首] 顺序播放已到最后一首，停止播放")
                    return
                else:
                    self.current_index = 0
                    
        # 确保索引有效
        self.current_index = max(0, min(self.current_index, len(self.playlist) - 1))
        
        self._debug_log(f"切换曲目: {previous_index} -> {self.current_index}")
        
        if self.current_index != previous_index or (len(self.playlist) == 1 and self.play_mode == "repeat_all"):
            self.play(self.current_index)
        elif not self.is_playing:
            self.stop()

    def previous(self):
        if not self.playlist:
            self.logger.info("播放列表为空")
            return
            
        previous_index = self.current_index
        
        if self.play_mode == "shuffle":
            if len(self.playlist) > 1:
                new_index = self.current_index
                while new_index == self.current_index:
                    new_index = random.randint(0, len(self.playlist) - 1)
                self.current_index = new_index
            else:
                self.current_index = 0
        else:
            self.current_index -= 1
            if self.current_index < 0:
                self.current_index = len(self.playlist) - 1
                
        if self.current_index != previous_index:
            self.play(self.current_index)
        
    def set_volume(self, volume: float, temporary: bool = False):
        volume = self._clamp_volume(volume)
        if temporary:
            self.temp_volume = volume
        else:
            self.base_volume = volume
            self.volume = volume
            config.music_volume = volume
            config.save_config()
            
        self._apply_effective_volume()
        
    def reset_temp_volume(self):
        self.temp_volume = None
        self._apply_effective_volume()
        
    def cancel_fade(self) -> bool:
        """取消挂起的音量淡变（连同其完成回调）。返回是否真的取消了一个进行中的淡变。

        联动状态切换（死亡打断存活侧淡出、关闭联动开关）时必须先取消旧淡变，
        否则"淡出到0再暂停"的回调会在新状态生效后才触发，把音乐错误暂停。
        """
        if self.fade_thread and self.fade_thread.is_alive():
            self.stop_fade = True
            if getattr(self, "_fade_cancel", None) is not None:
                self._fade_cancel.set()
            self.fade_thread.join(timeout=0.2)
            return True
        return False

    def fade_volume(
        self,
        target_volume: float,
        duration: float,
        callback: Optional[Callable] = None,
        temporary: Optional[bool] = None,
    ):
        # v2.2.1: 旧实现 join() 无超时——该函数由GSI处理线程调用（存活/死亡联动），
        # 淡变线程一旦卡住会阻塞整条GSI事件链路。改为：每次淡变持有独立的取消事件，
        # 新淡变只需取消旧事件即可接管，最多等 0.2s，绝不无限等待。
        if self.fade_thread and self.fade_thread.is_alive():
            self.stop_fade = True
            if getattr(self, "_fade_cancel", None) is not None:
                self._fade_cancel.set()
            self.fade_thread.join(timeout=0.2)

        self.stop_fade = False
        cancel_event = threading.Event()
        self._fade_cancel = cancel_event
        target_volume = self._clamp_volume(target_volume)
        duration = max(0.0, float(duration))

        def fade():
            start_volume = pygame.mixer.music.get_volume()
            start_time = time.time()

            while not (self.stop_fade or cancel_event.is_set()) and duration > 0:
                elapsed = time.time() - start_time
                if elapsed >= duration:
                    break

                progress = elapsed / duration
                current_volume = start_volume + (target_volume - start_volume) * progress
                pygame.mixer.music.set_volume(current_volume)
                time.sleep(0.02)

            if not (self.stop_fade or cancel_event.is_set()):
                if temporary is True:
                    self.temp_volume = target_volume
                elif temporary is False:
                    self.base_volume = target_volume
                    self.volume = target_volume
                pygame.mixer.music.set_volume(
                    self._get_effective_volume() if temporary is not None else target_volume
                )
                if callback:
                    callback()
                    
        self.fade_thread = threading.Thread(target=fade, daemon=True, name="MusicFade")
        self.fade_thread.start()
        
    def set_play_mode(self, mode: str):
        normalized_mode = normalize_music_play_mode(mode)
        if normalized_mode in ["sequence", "shuffle", "repeat_one", "repeat_all"]:
            self.play_mode = normalized_mode
            config.music_play_mode = normalized_mode
            config.save_config()
            self._debug_log(f"播放模式切换为: {normalized_mode}")
            
    def add_track(self, track: Dict):
        if "title" not in track:
            track["title"] = os.path.basename(track["path"])
        if "artist" not in track:
            track["artist"] = "未知艺术家"
        if "duration" not in track:
            track["duration"] = self._get_track_duration(track)
            
        self.playlist.append(track)
        self._save_playlist()
        
    def update_track_info(self, index: int, updates: Dict):
        """更新音轨信息"""
        if 0 <= index < len(self.playlist):
            self.playlist[index].update(updates)
            self._save_playlist()
            
            # 如果更新的是当前播放的音轨，触发更新
            if index == self.current_index and self.on_track_change:
                self.on_track_change(self.playlist[index])
        
    def remove_track(self, index: int):
        if 0 <= index < len(self.playlist):
            was_current = index == self.current_index
            if was_current:
                self.stop()
            elif index < self.current_index:
                self.current_index -= 1

            # 必须先删再定位下一首：旧实现在 pop 之前调 next()，
            # sequence 模式会先把"待删除的那首"重新播一遍，索引随后错位
            self.playlist.pop(index)
            self._save_playlist()

            if was_current:
                if self.playlist:
                    # 播放接替删除位置的曲目；删的是末位则回到开头
                    self.current_index = index - 1 if index < len(self.playlist) else -1
                    self.next()
                else:
                    self.current_index = -1

            config.music_current_index = self.current_index
            config.save_config()
            
    def clear_playlist(self):
        self.stop()
        self.playlist.clear()
        self.current_index = -1
        self._save_playlist()

    def restore_playlist(self, tracks):
        """把当前列表整体还原成 `tracks`（**撤销专用**，RN-457）。

        ⚠⚠ 2026-08-31 实测：两处「删除」的撤销回调原来直接改
        `config.music_playlists[...]`，而那是**下游** ——
        真源是 `self.playlist`，它由 `_save_playlist()` **单向**写进 config。
        于是点完撤销：**config 回到 5 首，`player.playlist` 和屏幕都停在 4 首**。

        ⭐⭐⭐ 这比「撤销没用」更坏：它是**撤销半成功**。
        用户看到什么都没发生，以为撤销坏了；而那首歌其实躺在配置里，
        下次启动会自己回来 —— 而在此之前，**任何一次删除都会把它再覆盖掉**
        （`_save_playlist` 拿 `self.playlist` 整个盖过去）。

        ⭐ **撤销必须写在真源上；写在下游的撤销，会安静地把内存和磁盘拆成两份。**

        ⛔ 不碰 `config.music_current_index`：那个键同时决定**底部控制条建不建**
        （`playback_has_ever_started`，RN-195）。在这里顺手清它，等于让一次撤销
        把老用户的播放控制面整个撤掉。
        """
        self.playlist = [dict(track) for track in (tracks or [])]
        if self.current_index >= len(self.playlist):
            self.current_index = len(self.playlist) - 1
        self._save_playlist()


    def _get_track_duration(self, track: Dict) -> int:
        if not mutagen_available:
            return 0
        try:
            if track["type"] == "local":
                path = track["path"]
                if path.lower().endswith('.mp3'):
                    audio = MP3(path)
                elif path.lower().endswith('.flac'):
                    audio = FLAC(path)
                elif path.lower().endswith(('.m4a', '.mp4')):
                    audio = MP4(path)
                else:
                    return 0
                return int(audio.info.length)
        except Exception:
            return 0
            
    def _start_progress_update(self):
        if self.progress_thread and self.progress_thread.is_alive():
            self.stop_progress = True
            self.progress_thread.join(timeout=0.5)
            
        self.stop_progress = False
        self.progress_start_time = time.time()
        self.progress_pause_time = 0
        self.last_pause_start = None
        
        def update_progress():
            while not self.stop_progress and self.is_playing:
                try:
                    if not self.is_paused:
                        current_time = time.time()
                        # 从暂停恢复：把这段暂停时长累计进去，否则进度含暂停时间会跳变
                        if self.last_pause_start is not None:
                            self.progress_pause_time += current_time - self.last_pause_start
                            self.last_pause_start = None
                        elapsed = current_time - self.progress_start_time - self.progress_pause_time
                        
                        if self.on_progress_update and self.current_track:
                            duration = self.current_track.get("duration", 0)
                            
                            if duration == 0 and self.current_track["type"] == "local":
                                duration = self._get_track_duration(self.current_track)
                                if duration > 0:
                                    self.current_track["duration"] = duration
                            
                            if duration > 0:
                                if elapsed <= duration:
                                    self.on_progress_update(elapsed, duration)
                            else:
                                self.on_progress_update(elapsed, 0)
                    else:
                        if self.last_pause_start is None:
                            self.last_pause_start = time.time()
                    
                    time.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"进度更新出错: {e}")
                    break
            self._debug_log("进度更新线程结束")

        self.progress_thread = threading.Thread(target=update_progress, daemon=True, name="MusicProgress")
        self.progress_thread.start()
        
    def pause(self):
        if self.is_playing and not self.is_paused:
            pygame.mixer.music.pause()
            self.is_paused = True
            # 记录暂停开始时间
            self.pause_start_time = time.time()
            if self.on_state_change:
                self.on_state_change(True, True)
            self._debug_log("已暂停")
                
    def resume(self):
        if self.is_playing and self.is_paused:
            # 检查是否需要先跳转到保存的位置（仅 restore_state 之后的首次恢复）
            if self._pending_restore_seek and self.play_start_position > 0:
                self._pending_restore_seek = False
                # 这是从恢复状态后第一次播放，需要跳转到正确位置
                saved_position = self.play_start_position
                self._debug_log(f"首次恢复播放，先跳转到保存的位置: {saved_position:.1f}秒")

                file_path = self._resolve_track_audio_path(self.current_track)
                if not file_path:
                    self.logger.error("[音乐播放器] 恢复播放失败: 当前曲目路径不可用")
                    return
                
                # 停止旧的线程
                self.stop_progress = True
                self.stop_end_check = True
                
                # 停止当前播放
                pygame.mixer.music.stop()
                
                # 重新从正确位置开始播放
                if self.current_track:
                    pygame.mixer.music.load(file_path)
                    pygame.mixer.music.play(start=saved_position)
                    self._apply_effective_volume()
                    
                    # 重置时间跟踪（从当前时间开始，位置已经正确）
                    self.play_start_time = time.time()
                    self.play_start_position = saved_position  # 更新到实际播放位置
                    self.total_pause_time = 0.0
                    self.pause_start_time = None
                    # 结束检测的预期时间也要按恢复位置重算
                    duration = (self.current_track or {}).get("duration", 0)
                    self.track_start_time = time.time() - saved_position
                    self.track_expected_end_time = (
                        self.track_start_time + duration if duration > 0 else 0
                    )
                    
                    self.is_paused = False
                    if self.on_state_change:
                        self.on_state_change(True, False)
                    
                    # 重置线程标志
                    self.stop_progress = False
                    self.stop_end_check = False
                    
                    # 启动进度更新和结束检测
                    self._start_progress_update()
                    self._start_end_check_thread()
                    
                    self._debug_log(f"已从{saved_position:.1f}秒恢复播放")
            else:
                # 正常的 unpause（不是从恢复状态）
                # 累计暂停时长
                if self.pause_start_time is not None:
                    pause_duration = time.time() - self.pause_start_time
                    self.total_pause_time += pause_duration
                    self.pause_start_time = None
                    
                pygame.mixer.music.unpause()
                self.is_paused = False
                if self.on_state_change:
                    self.on_state_change(True, False)
                self._debug_log("已恢复播放")
            
    def get_playlist(self) -> List[Dict]:
        return self.playlist.copy()
    
    def get_position(self):
        """获取当前播放位置(秒)"""
        try:
            if self.is_playing and self.current_index >= 0:
                if self.play_start_time is not None:
                    # 使用手动时间跟踪计算播放位置
                    if self.is_paused and self.pause_start_time is not None:
                        # 暂停状态:使用暂停开始时的位置
                        elapsed = self.pause_start_time - self.play_start_time - self.total_pause_time
                    else:
                        # 播放状态:实时计算
                        elapsed = time.time() - self.play_start_time - self.total_pause_time
                    
                    current = self.play_start_position + elapsed
                    return max(0, current)
            return 0
        except Exception as e:
            self._debug_log(f"获取播放位置失败: {e}")
            return 0
    
    def get_progress(self):
        """获取播放进度（当前位置，总时长）秒"""
        try:
            if self.is_playing and self.current_index >= 0:
                if self.current_index < len(self.playlist):
                    track = self.playlist[self.current_index]
                    duration = track.get('duration', 0)
                    
                    if duration > 0 and self.play_start_time is not None:
                        # 使用手动时间跟踪计算播放进度
                        if self.is_paused and self.pause_start_time is not None:
                            # 暂停状态：使用暂停开始时的位置
                            elapsed = self.pause_start_time - self.play_start_time - self.total_pause_time
                        else:
                            # 播放状态：实时计算
                            elapsed = time.time() - self.play_start_time - self.total_pause_time
                        
                        current = self.play_start_position + elapsed
                        current = max(0, min(current, duration))
                        return (current, duration)
            return (0, 0)
        except Exception as e:
            self.logger.error(f"获取播放进度失败: {e}")
            return (0, 0)
    
    def get_current_track(self):
        """获取当前播放的曲目信息"""
        try:
            if self.current_index >= 0 and self.current_index < len(self.playlist):
                return self.playlist[self.current_index]
            return None
        except Exception:
            return None
    
    def seek(self, position_seconds):
        """跳转到指定位置（秒）"""
        try:
            if not self.is_playing:
                return
            
            track = self.current_track or self.get_current_track()
            if not track:
                return
            
            duration = track.get('duration', 0)
            if duration <= 0:
                return
            
            # 确保位置在有效范围内
            position_seconds = max(0, min(position_seconds, duration))
            
            # 更新时间跟踪
            self.play_start_time = time.time()
            self.play_start_position = position_seconds
            self.total_pause_time = 0.0
            self.pause_start_time = None
            self._pending_restore_seek = False  # 手动 seek 覆盖恢复位置
            # 结束检测的预期结束时间必须随 seek 重算，否则向前跳转后
            # 墙钟越过旧预期时间会被误判"已结束"提前切歌
            self.track_start_time = time.time() - position_seconds
            self.track_expected_end_time = (
                self.track_start_time + duration if duration > 0 else 0
            )

            # pygame.mixer.music.set_pos() 只支持某些格式，而且不够精确
            # 更可靠的方法是重新加载并从指定位置开始
            file_path = self._resolve_track_audio_path(track)
            if not file_path:
                self.logger.error("[音乐播放器] 跳转失败: 当前曲目路径不可用")
                return
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play(start=position_seconds)
            self._apply_effective_volume()

            # 重载后 pygame 处于播放态；若原先是暂停态需同步状态机并通知 UI
            if self.is_paused:
                self.is_paused = False
                if self.on_state_change:
                    self.on_state_change(True, False)

            self.logger.info(f"[音乐播放器] 跳转到: {position_seconds:.1f}秒")
        except Exception as e:
            self.logger.error(f"[音乐播放器] 跳转失败: {e}")
        
    def save_state(self):
        """保存当前播放状态（使用可靠的位置计算）"""
        try:
            # 使用 get_position() 而不是 get_pos()，因为后者不可靠
            position_sec = self.get_position()
            if position_sec is None:
                position_sec = 0.0
            
            config.music_current_index = self.current_index
            config.music_current_position = position_sec
            config.save_config()
            
            self._debug_log(f"保存播放状态: 曲目#{self.current_index}, 位置{position_sec:.1f}秒")
        except Exception as e:
            self.logger.error(f"保存播放状态失败: {e}")
        
    def restore_state(self):
        """恢复上次保存的播放状态(曲目和进度,但始终为暂停状态)"""
        self._debug_log("开始恢复播放状态...")
        
        # 检查是否有有效的播放列表和曲目索引
        if not self.playlist:
            self._debug_log("播放列表为空,跳过状态恢复")
            return
            
        if config.music_current_index < 0 or config.music_current_index >= len(self.playlist):
            self._debug_log(f"无效的曲目索引: {config.music_current_index}, 播放列表大小: {len(self.playlist)}")
            return
        
        # 恢复曲目索引
        self.current_index = config.music_current_index
        track = self.playlist[self.current_index]
        track_name = track.get('name', 'Unknown')
        self._debug_log(f"恢复曲目 #{self.current_index}: {track_name}")
        
        # 直接加载曲目到指定位置(不播放)
        try:
            file_path = self._resolve_track_audio_path(track)
            if not file_path:
                self._debug_log("恢复状态跳过：当前曲目的本地文件已不存在")
                return
            position = config.music_current_position if config.music_current_position > 0 else 0
            
            self._debug_log(f"加载曲目到位置: {position:.1f}秒(暂停状态)")
            
            # 加载音乐文件
            pygame.mixer.music.load(file_path)
            self._apply_effective_volume()
            
            # 先正常播放（从头开始）
            pygame.mixer.music.play()
            # 立即暂停
            pygame.mixer.music.pause()
            
            self._debug_log(f"音乐已加载并暂停（将在恢复播放时跳转到{position:.1f}秒）")
            
            # 设置正确的状态
            self.is_playing = True  # 曲目已加载并"播放"(虽然是暂停的)
            self.is_paused = True   # 处于暂停状态
            self.current_track = {**track, "_resolved_path": file_path}  # 设置当前曲目
            
            # 更新时间跟踪（关键：使用保存的位置作为起始位置）
            self.play_start_time = time.time()
            self.play_start_position = position  # 使用实际保存的位置
            self.total_pause_time = 0.0
            self.pause_start_time = time.time()
            
            # 通知UI更新（先通知曲目变化，再通知状态变化）
            if self.on_track_change:
                self.on_track_change(track)
            
            if self.on_state_change:
                self.on_state_change(True, True)  # is_playing=True, is_paused=True
            
            self._debug_log(f"✓ 曲目已加载到{position:.1f}秒并暂停")
            
        except Exception as e:
            self._debug_log(f"恢复状态失败: {e}")
                
    def cleanup(self):
        self._debug_log("清理资源")
        self.stop()
        self.stop_progress = True
        self.stop_fade = True
        self.stop_end_check = True
        time.sleep(0.1)
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

# 全局播放器实例
music_player = None

def get_music_player() -> MusicPlayer:
    global music_player
    if music_player is None:
        music_player = MusicPlayer()
    return music_player


# ==================== RN-195：「放过音乐」这件事的唯一真相源 ====================
# 音乐控制条原本由 `QTimer.singleShot(8000, ...)` **无条件**建出来，一出现就
# 永久吃掉内容区 42px（实测：完整档 750→708、紧凑档 650→608）。改成"放过才建"
# 之后，"放没放过"这个判断被三处用到（启动那一发、后台阶段那一发、量图工装），
# ⇒ 只能有一份。

_playback_started_listeners: List[Callable[[], None]] = []


def add_playback_started_listener(callback: Callable[[], None]) -> None:
    """注册「有音乐真的开始播了」的监听者。

    ⚠ **不能复用 `player.on_track_change`** —— 那是**单槽**的（音乐控制条自己
    占着，见 `music_control_bar._bind_player_callbacks`），而这里的监听者恰恰
    要在控制条**还不存在**的时候被叫醒。
    """
    if callback not in _playback_started_listeners:
        _playback_started_listeners.append(callback)


def remove_playback_started_listener(callback: Callable[[], None]) -> None:
    if callback in _playback_started_listeners:
        _playback_started_listeners.remove(callback)


def notify_playback_started() -> None:
    """通告「开始播放」。

    ⚠ **可能跑在加载线程/结束检测线程上**（自动续播走 `_handle_track_end → next`），
    监听者自己负责切回主线程再碰 Qt 控件。
    ⚠ 单个监听者抛异常不许影响别人，更不许把播放本身带崩。
    """
    for callback in list(_playback_started_listeners):
        try:
            callback()
        except Exception:
            get_logger("MusicPlayer").exception("播放开始通知失败（不影响播放）")


def playback_has_ever_started() -> bool:
    """这台机器上放过音乐没有。

    两个来源都要看，缺一个就会在某段窗口里答错：
      · **本会话**：`play()` 一进来就同步写 `current_index`，而配置要等曲目
        加载完成（`_on_track_loaded`）才写 —— 只看配置，会在"按下播放 →
        加载完成"这段窗口里说没放过；
      · **跨会话**：上次退出时存着播到第几首。

    ⭐ **认不出来的值一律算「放过」。** 这个判断的两个失效方向**不对称**：
    误判成「没放过」= 把用户唯一的播放控制面整个拿掉（`pages/music_page.py`
    自己一个播放控件都没有，暂停/下一首/音量全在控制条上）；误判成「放过」
    = 多占 42px。分不出类的时候，选那个只会难看、不会致残的方向。
    """
    player = music_player
    if player is not None:
        try:
            if int(getattr(player, "current_index", -1)) >= 0:
                return True
        except (TypeError, ValueError):
            return True
    try:
        return int(getattr(config, "music_current_index", -1)) >= 0
    except (TypeError, ValueError):
        return True


class MusicLoaderThread(threading.Thread):
    """音乐加载线程

    只播本地文件后这里已无耗时操作，但保留独立线程：
    上层 _play_track 的"加载中"提示、cancel_loading 的取消语义都挂在它身上
    """
    def __init__(self, player, track):
        super().__init__()
        self.player = player
        self.track = track
        self.is_cancelled = False
        self.daemon = True

    def run(self):
        try:
            if self.is_cancelled:
                return

            audio_path = self.player._resolve_track_audio_path(self.track)

            if self.is_cancelled:
                return

            if audio_path:
                # 在主线程中调用播放（虽然Pygame mixer是线程安全的，但为了保险起见，
                # 或者如果后续有UI操作，这里直接调用也是可以的，因为_on_track_loaded主要操作mixer和变量）
                # 注意：如果是在Qt环境中，最好使用信号槽回到主线程。
                # 但这里是纯Python逻辑层，直接调用即可。
                self.player._on_track_loaded(self.track, audio_path)
            else:
                self.player._on_track_load_error(
                    self.track, f"本地文件不存在: {self.track.get('path', '')}"
                )

        except Exception as e:
            if not self.is_cancelled:
                self.player._on_track_load_error(self.track, str(e))

    def cancel(self):
        self.is_cancelled = True
