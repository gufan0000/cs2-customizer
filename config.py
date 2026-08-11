# SPDX-License-Identifier: GPL-3.0-or-later
from core.utils.logger import get_logger
import atexit
import json
import os
import shutil
import sys
import threading
from core.hud.rule_model import (
    get_default_hud_rules,
    has_runtime_enabled_rules,
    normalize_hud_rules,
    normalize_profile,
    normalize_runtime_refresh_key,
    normalize_sync_mode,
)
from core.gun_sound_profiles import (
    GUN_SOUND_PROFILE_LIST,
    is_gun_sound_master_enabled,
    resolve_gun_sound_style,
    sync_legacy_gun_sound_flags,
)

# 应用程序信息
APP_NAME = "CS2Customizer"
CONFIG_FILENAME = "config.json"
VERSION = "2.2.2"

# P4.2: 配置 schema 版本。与软件 VERSION 解耦——只在"配置结构/语义发生需要
# 迁移的变化"时 +1，并在 CONFIG_MIGRATIONS 注册对应迁移函数。
# 旧配置文件读入后会从其记录的版本逐级迁移到 CONFIG_SCHEMA_VERSION。
CONFIG_SCHEMA_VERSION = 1

# 迁移函数表：{from_version: callable(config_obj, raw_config_dict)}。
# 例：未来 v1->v2 把某字段语义改了，就写 def _migrate_1_to_2(cfg, raw): ...
# 然后 CONFIG_MIGRATIONS = {1: _migrate_1_to_2} 并把 CONFIG_SCHEMA_VERSION 设为 2。
# 当前 v0->v1 无破坏性结构变化（新增字段都靠 getattr 默认值向后兼容），故为空。
CONFIG_MIGRATIONS = {}

# 局内视角默认预设（单一数据源）：config 与 viewmodel 页面共用，
# 避免 UI 与 config 各维护一套默认值导致分叉。
DEFAULT_VIEWMODEL_PRESETS = [
    {"name": "预设1", "x": 2.0, "y": 2.0, "z": -1.0, "fov": 68, "key": "F5"},
    {"name": "预设2", "x": -2.0, "y": -2.0, "z": -2.0, "fov": 54, "key": "F6"},
    {"name": "预设3", "x": 1.5, "y": 2.0, "z": 2.0, "fov": 68, "key": "F7"},
    {"name": "预设4", "x": -2.0, "y": -2.0, "z": -2.0, "fov": 68, "key": "F8"},
    {"name": "预设5", "x": 2.0, "y": -2.0, "z": 0.0, "fov": 54, "key": "F9"},
]

SCREEN_EFFECT_PRESET_VALUES = (
    "lite_competitive",
    "impact_sparks",
    "frenzy_kill",
    "blue_storm",
    "neon_pulse",
    "toxic_surge",
    "amber_overdrive",
    "frost_shock",
)
DEFAULT_SCREEN_EFFECT_PRESET = "impact_sparks"
SCREEN_EFFECT_PLAY_MODE_VALUES = ("steady", "streak", "chaos")
DEFAULT_SCREEN_EFFECT_PLAY_MODE = "streak"
DEFAULT_GUN_SOUND_DUCK_RATIO = 0.18
DEFAULT_GUN_SOUND_DUCK_ATTACK_MS = 0
DEFAULT_GUN_SOUND_DUCK_RELEASE_MS = 120

logger = get_logger("Config")


def normalize_screen_effect_preset(value, fallback=DEFAULT_SCREEN_EFFECT_PRESET):
    key = ""
    if isinstance(value, str):
        key = value.strip().lower()
    if key in SCREEN_EFFECT_PRESET_VALUES:
        return key
    return fallback


def normalize_screen_effect_play_mode(value, fallback=DEFAULT_SCREEN_EFFECT_PLAY_MODE):
    key = ""
    if isinstance(value, str):
        key = value.strip().lower()
    if key in SCREEN_EFFECT_PLAY_MODE_VALUES:
        return key
    return fallback


def infer_screen_effect_preset_from_legacy(intensity, thickness, duration_ms, headshot_boost):
    try:
        intensity = max(0.05, min(1.0, float(intensity)))
    except Exception:
        intensity = 0.35
    try:
        thickness = max(2.0, min(80.0, float(thickness)))
    except Exception:
        thickness = 12.0
    try:
        duration_ms = max(80.0, min(2500.0, float(duration_ms)))
    except Exception:
        duration_ms = 260.0
    try:
        headshot_boost = max(1.0, min(3.0, float(headshot_boost)))
    except Exception:
        headshot_boost = 1.25

    score = (
        intensity * 0.55
        + (thickness / 80.0) * 0.20
        + min(1.0, duration_ms / 420.0) * 0.15
        + min(1.0, (headshot_boost - 1.0) / 1.2) * 0.10
    )
    if score <= 0.30:
        return "lite_competitive"
    if score >= 0.58:
        return "frenzy_kill"
    return DEFAULT_SCREEN_EFFECT_PRESET


def normalize_gun_sound_duck_ratio(value, fallback=DEFAULT_GUN_SOUND_DUCK_RATIO):
    try:
        numeric = float(value)
    except Exception:
        return fallback
    return max(0.0, min(1.0, numeric))


def normalize_gun_sound_duck_time_ms(value, fallback):
    try:
        numeric = int(float(value))
    except Exception:
        return fallback
    return max(0, min(2000, numeric))


def normalize_gun_sound_hold_duration(value, fallback):
    try:
        numeric = float(value)
    except Exception:
        return fallback
    return max(0.0, min(5.0, numeric))

def get_config_dir():
    """获取配置文件目录"""
    # 测试隔离 / 自定义部署：允许用 CS2C_CONFIG_DIR 覆盖配置目录，
    # 避免在真实机器上跑测试时把夹具值写进用户的 %LOCALAPPDATA%\CS2Customizer\config.json。
    override_dir = os.environ.get('CS2C_CONFIG_DIR')
    if override_dir:
        os.makedirs(override_dir, exist_ok=True)
        return override_dir
    # 使用 AppData\Local 目录
    appdata_dir = os.environ.get('LOCALAPPDATA')
    if not appdata_dir:
        # 如果无法获取 LOCALAPPDATA 环境变量，回退到程序目录
        return os.path.dirname(os.path.abspath(__file__))
    
    # 创建应用程序配置目录
    config_dir = os.path.join(appdata_dir, APP_NAME)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    
    return config_dir

def get_config_path():
    """获取配置文件的完整路径"""
    return os.path.join(get_config_dir(), CONFIG_FILENAME)

class Config:
    def __init__(self):
        # 防抖保存定时器
        self._save_timer = None
        self._save_lock = threading.Lock()
        self._load_error = None  # 配置加载错误信息
        self._atexit_registered = False  # A3: atexit 注册保护（避免重复注册）

        # 基础功能开关
        self.kill_sound_enabled = True
        self.kill_voice_enabled = False  # 默认不启用击杀语音
        self.cfg_check_enabled = True
        self.mode = "1. 官匹竞技"
        self.csgo_dir = ""
        self.kill_icon_enabled = False
        self.debug_mode = False
        
        # 额外功能开关
        self.gun_sound_enabled = False  # 默认不启用枪声替换总开关
        
        # 枪声设置
        self.awp_enabled = False
        self.awp_style = "不启用"
        self.deagle_enabled = False
        self.deagle_style = "不启用"
        self.usp_enabled = False
        self.usp_style = "不启用"

        # 击杀图标设置
        self.kill_icon_style = "默认"  # 击杀图标风格
        
        # 击杀图标位置和大小设置
        self.kill_icon_offset_x = 0      # X轴偏移（像素）
        self.kill_icon_offset_y = 0      # Y轴偏移（像素）  
        self.kill_icon_scale = 1.0       # 缩放比例（0.5-2.0）
        self.kill_icon_base_width = 350  # 基准宽度
        self.kill_icon_base_height = 250 # 基准高度
        
        # 击杀图标FPS设置
        self.kill_icon_fps_1 = 30  # 1杀FPS
        self.kill_icon_fps_2 = 30  # 2杀FPS
        self.kill_icon_fps_3 = 30  # 3杀FPS
        self.kill_icon_fps_4 = 30  # 4杀FPS
        self.kill_icon_fps_5 = 30  # 5杀FPS
        
        # 新增武器配置
        self.revolver_enabled = False
        self.revolver_style = "不启用"
        self.ssg08_enabled = False
        self.ssg08_style = "不启用"
        self.scar20_enabled = False
        self.scar20_style = "不启用"
        self.g3sg1_enabled = False
        self.g3sg1_style = "不启用"
        self.nova_enabled = False
        self.nova_style = "不启用"
        self.mag7_enabled = False
        self.mag7_style = "不启用"
        self.sawedoff_enabled = False
        self.sawedoff_style = "不启用"
        
        # 枪声静音时长设置
        self.awp_mute_duration = 0.5
        self.deagle_mute_duration = 0.4
        self.usp_mute_duration = 0.2
        self.revolver_mute_duration = 0.4
        self.ssg08_mute_duration = 0.4
        self.scar20_mute_duration = 0.4
        self.g3sg1_mute_duration = 0.4
        self.nova_mute_duration = 0.3
        self.mag7_mute_duration = 0.3
        self.sawedoff_mute_duration = 0.3
        self.gun_sound_ducking_enabled = True
        self.gun_sound_duck_ratio = DEFAULT_GUN_SOUND_DUCK_RATIO
        self.gun_sound_duck_attack_ms = DEFAULT_GUN_SOUND_DUCK_ATTACK_MS
        self.gun_sound_duck_release_ms = DEFAULT_GUN_SOUND_DUCK_RELEASE_MS
        self.gun_sound_duck_fallback_hotkey_mode = True
        self.gun_sound_duck_target_processes = ["cs2.exe", "csgo.exe"]
        for profile in GUN_SOUND_PROFILE_LIST:
            setattr(self, profile.legacy_enabled_key, False)
            setattr(
                self,
                profile.style_key,
                resolve_gun_sound_style(getattr(self, profile.style_key, "0")),
            )
            setattr(
                self,
                profile.mute_duration_key,
                normalize_gun_sound_hold_duration(
                    getattr(self, profile.mute_duration_key, profile.default_mute_duration),
                    profile.default_mute_duration,
                ),
            )
            setattr(
                self,
                profile.duck_ratio_key,
                normalize_gun_sound_duck_ratio(
                    getattr(self, profile.duck_ratio_key, DEFAULT_GUN_SOUND_DUCK_RATIO),
                    DEFAULT_GUN_SOUND_DUCK_RATIO,
                ),
            )
        
        # 死亡音效设置
        self.death_sound_enabled = False
        self.death_sound_style = "0"
        
        # 观战和玩家ID设置
        self.spectator_mode_mute = True  # 默认开启观战模式静音
        self.player_steamid = ""  # 玩家的steamid
        
        # 放大功能
        self.magnifier_enabled = False  # 默认不启用开镜放大
        self.magnifier = {
            "zoom_factor": 2.0,
            "hotkey": "右键",
            "primary_hotkey": "右键",
            "secondary_hotkey": "右键",
            "trigger_mode": "长按触发",
            "zoom_settings": {},
            "sensitivity_sync_enabled": False,
            "base_sensitivity": 1.0,
            "sensitivity_multiplier": 0.82,
            "sync_trigger_key": "SCROLLLOCK",
        }
        
        # 特殊音效启用开关
        self.grenade_sound_enabled = False  # 默认不启用投掷物音效
        self.c4_sound_enabled = False  # 默认不启用C4音效
        
        # 特殊音效风格设置
        self.grenade_sound_styles = {
            "hegrenade": "0",
            "flashbang": "0",
            "smoke": "0",
            "molotov": "0",
            "incgrenade": "0",
            "decoy": "0"
        }
        self.c4_sound_style = "0"
        
        # 回合音效设置
        self.round_sound_enabled = False  # 默认不启用回合音效
        self.round_start_style = "0"      # 回合开始音效风格
        self.round_action_style = "0"     # 行动开始音效风格
        self.round_win_style = "0"        # 回合胜利音效风格
        self.round_lose_style = "0"       # 回合失败音效风格
        self.round_mvp_style = "0"        # MVP音效风格
        self.round_sound_volume = 1.0     # 回合音效独立音量设置
        
        # 血量警告功能
        self.health_warning_enabled = False  # 默认不启用血量警告
        self.health_warning_threshold = 20   # 默认血量阈值20
        self.health_warning_style = "0"      # 默认音效风格
        
        # 准心设置
        self.crosshair_enabled = False    # 默认不启用准心
        self.crosshair_size = 20
        self.crosshair_thickness = 2      # 默认粗细为2
        self.crosshair_color = "green"
        self.crosshair_style = "crosshair"
        self.crosshair_custom_data = []   # 存储自定义准心的像素数据
        self.crosshair_animation = "none" # 准心动画设置
        self.crosshair_kill_effect = "none" # 准心击杀联动设置
        self.crosshair_reset_enabled = False  # 准心快速回正开关
        # 准心渲染器（R8b / UP-054）："qt" 透明置顶窗 ｜ "pygame" 老实现（保留一个发布周期）。
        # 换成 Qt 是为了消掉老实现「主线程建窗、工作线程刷新」这个违反 Win32
        # 窗口线程亲和性的根因——那是「原生崩溃只能靠兼容模式跳过准心」的来源。
        #
        # R8b-E 翻默认值前跑过 22 项真窗口验收（scripts/verify_r8b_live.py）：
        # 物理几何偏差 0px、五个扩展样式齐全、点击穿透实测（WindowFromPoint 打屏幕
        # 正中不命中准心）、Z 序高于非置顶全屏窗口、全程不抢前台焦点、
        # 4 样式/6 色/9 动画/10 联动逐帧有像素、隐藏+显示 4.2ms（老实现重建一次 916ms）。
        # 外加整软件真机跑测 + pygame 对照组，两边日志零错误、native_crash 内容一致。
        #
        # 出问题就把这里改回 "pygame"，或在 config.json 里加 "crosshair_renderer": "pygame"。
        self.crosshair_renderer = "qt"

        # 闪光效果设置
        self.flash_enabled = False       # 默认不启用闪光效果
        self.flash_bg_color = "white"    # 默认白色背景
        self.flash_max_opacity = 0.75    # 默认不透明度75%
        self.flash_image_style = "none"  # 默认不使用图片
        self.flash_image_opacity = 0.5   # 默认图片不透明度50%
        self.flash_image_position = (0.5, 0.5)  # 默认居中(x, y)
        self.flash_image_size = (0.3, 0.3)      # 默认图片大小(宽度, 高度)
        
        # 闪光样式设置
        self.flash_style = "standard"        # 闪光样式: standard, blur, rainbow 等
        self.flash_style_params = {          # 样式参数
            "pulse_speed": 8.0,
            "pulse_intensity": 0.15,
            "blur_factor": 0.3,
            "blur_layers": 5,
            "halo_intensity": 0.8,
            "halo_size": 0.75,
            "color_cycle_speed": 2.0,
            "color_intensity": 0.3
        }
        self.flash_fade_in_enabled = True    # 是否开启淡入效果
        self.flash_fade_out_enabled = True   # 是否开启淡出效果
        
        # 闪光图片轮换设置
        self.flash_image_rotation = "none"   # 图片轮换模式: none(不轮换), random(随机), sequence(顺序)
        self.flash_current_image_index = 0   # 当前显示的图片索引(用于顺序模式)
        
        # 闪光音频设置
        self.flash_audio_enabled = False     # 默认不启用闪光音频
        self.flash_audio_style = "none"      # 闪光音频风格
        self.flash_audio_rotation = "none"   # 音频轮换模式：none(不轮换), random(随机), sequence(顺序)
        self.flash_audio_volume = 1.0        # 闪光音频音量
        self.flash_current_audio_index = 0   # 当前音频索引(用于顺序模式)
        self.flash_audio_auto_stop = True    # 默认闪光结束时自动停止音频
        
        # 切枪音效设置
        self.switch_weapon_sound_enabled = False  # 默认不启用切枪音效
        self.weapon_switch_sounds = {}            # 存储武器切换音效配置
        
        # 换弹音效设置
        self.reload_sound_enabled = False  # 默认不启用换弹音效
        self.weapon_reload_sounds = {}     # 存储武器换弹音效配置
        
        # 音量控制设置
        self.volume = 1.0  # 默认为最大音量

        # 分类音量：各音效类型相对主音量的独立倍率（0.0~1.0），默认 1.0（不衰减）。
        # 例如把"切枪音效"调小、"击杀音效"保持最大，互不影响。
        self.category_volumes = {
            "kill_sound": 1.0,      # 击杀音效
            "kill_voice": 1.0,      # 击杀语音
            "gun_sound": 1.0,       # 枪声替换
            "switch_weapon": 1.0,   # 切枪音效
            "reload_sound": 1.0,    # 换弹音效
            "death_sound": 1.0,     # 被击杀音效
            "special_sound": 1.0,   # 特殊音效（手雷/C4/血量警告）
        }

        # 响度归一：把不同作者发布的素材响度拉到接近水平，缓解"有的炸耳、有的几乎听不见"。
        # 默认关闭（属增强功能；开启后才会在加载音频时做一次轻量 RMS 分析）。
        self.audio_loudness_normalize_enabled = False
        self.audio_loudness_target = 0.2  # 目标 RMS（0~1，相对满幅），保守默认值

        # 窗口大小配置
        self.window_width = 900
        self.window_height = 520
        # 对标主流：默认记住窗口大小与位置（高级设置可关）
        self.use_saved_size = True
        self.compact_mode = False  # 紧凑模式（小窗口，侧边栏隐藏）
        self.ui_font_scale = 1.0  # 界面字号缩放档位:1.0/1.1/1.25(R1-1,非法值回正 1.0)
        # UP-004: 文件日志级别开关。默认 False=INFO;排查 GSI 问题时开为 True 回到
        # DEBUG。注意 core/utils/logger.py 是直接读 config.json 的(它不能 import
        # config,会循环依赖),所以本项改完需重启才生效。
        self.debug_file_log = False
        self.nav_frequent_enabled = True  # 侧栏「常用」动态分组(R1-6,重启生效)
        self.map_preset_enabled = False  # 按地图自动切预设(R2-4,默认关)
        self.map_preset_rules = {}  # {map_name: {"bundle": {...}, "saved_at": ts}}
        self.osd_enabled = True  # 游戏内 OSD 提示(R2-3)
        self.osd_corner = "bottom_right"  # OSD 位置:top_left/top_right/bottom_left/bottom_right
        self.usage_report_enabled = False  # 匿名使用统计(R3-3,默认关,opt-in)
        self.usage_install_id = ""  # 匿名安装ID(uuid4 hex,首次开启时生成)
        self.usage_last_sent_ts = 0.0  # 上次上报时间(24h 限一条)  # 更新公告弹出策略：False=每次启动都弹(默认)，True=仅在有新版本时弹
        # P3.2 崩溃日志自愿上报："ask"=发现新崩溃时询问(默认) / "never"=永不询问
        self.crash_report_prompt = "ask"
        self.crash_report_last_ts = 0.0  # 已处理过的崩溃日志最大 mtime（避免重复询问）
        # P2.3 GSI 端口（默认 3000；被占用时服务器自适应切换并写回此字段）
        self.gsi_port = 3000
        # P4.2 配置 schema 版本（新装/无此字段的旧配置按 0 处理 → 走全部迁移）
        self.config_schema_version = CONFIG_SCHEMA_VERSION
        # P4.1 首次使用引导：默认 False=全新安装会弹引导；
        # 读取已有配置文件时若缺此字段 → 视为老用户 → 置 True 豁免（见 load_config）
        self.onboarding_completed = False
        # 系统集成（对标主流，2026-06-10）：
        # 关闭主窗口行为："ask"=首次询问并可记住 / "tray"=最小化到托盘 / "exit"=直接退出
        self.close_action = "ask"
        # 窗口几何记忆（[x, y, w, h]，空=按分辨率自动）；use_saved_size 为总开关（上方已声明）
        self.window_geometry = []

        # 主题设置
        self.theme_mode = "黑夜模式"  # 默认使用黑夜模式（旧字段，兼容）
        self.ui_theme = "dark"  # 新UI主题字段: dark/light
        
        # 持枪视角设置
        self.viewmodel_cycle_key = "CAPSLOCK"  # 默认循环切换键
        self.viewmodel_presets = [dict(p) for p in DEFAULT_VIEWMODEL_PRESETS]
        
        # 自动切换设置
        self.viewmodel_auto_switch_enabled = False
        self.viewmodel_auto_switch_key = "V"
        self.viewmodel_auto_switch_interval = 3.0

        # HUD颜色设置
        # Phase1-1.4: hud_color_enabled 与 hud_rules_enabled 为同一概念，
        # 已合并——hud_color_enabled 改为类 property 别名（见 load_config 上方），
        # 单一数据源为 hud_rules_enabled（默认值在下方声明）。
        self.hud_color_mode = "static"        # "static" / "dynamic"
        self.hud_color_static = 0             # 静态颜色值 0-10
        self.hud_color_refresh_key = "w"      # 动态模式刷新键
        self.hud_color_dynamic_map = {
            "default": {"color": 0, "effect": "solid", "alt_color": -1},
            "round_start": {"color": -1, "effect": "solid", "alt_color": -1},
            "round_live": {"color": -1, "effect": "solid", "alt_color": -1},
            "kill": {"color": 8, "effect": "solid", "alt_color": -1},
            "headshot_kill": {"color": 7, "effect": "flash", "alt_color": 1},
            "multi_kill": {"color": 8, "effect": "blink", "alt_color": 1},
            "death": {"color": 5, "effect": "solid", "alt_color": -1},
            "low_health": {"color": 5, "effect": "blink", "alt_color": 6},
            "bomb_planted": {"color": 6, "effect": "solid", "alt_color": -1},
            "round_win": {"color": -1, "effect": "solid", "alt_color": -1},
            "round_lose": {"color": -1, "effect": "solid", "alt_color": -1},
            "weapon_rifle": {"color": -1, "effect": "solid", "alt_color": -1},
            "weapon_sniper": {"color": -1, "effect": "solid", "alt_color": -1},
            "weapon_pistol": {"color": -1, "effect": "solid", "alt_color": -1},
            "weapon_knife": {"color": -1, "effect": "solid", "alt_color": -1},
        }
        self.hud_color_low_health_threshold = 20
        self.hud_color_kill_duration = 3.0
        self.hud_color_death_duration = 5.0
        self.hud_color_multi_kill_duration = 4.0
        self.hud_color_headshot_duration = 3.0

        # HUD统一规则引擎（V1）
        self.hud_rules_version = 1
        self.hud_rules_enabled = True
        self.hud_rules_profile = "balanced_default"
        self.hud_rules = get_default_hud_rules(self.hud_rules_profile)
        self.hud_runtime_sync_mode = "safe"
        self.hud_runtime_refresh_key = "w"
        self.hud_keymap_enabled = {str(i): False for i in range(1, 10)}

        # 屏幕特效设置
        self.screen_effects_enabled = False
        self.screen_edge_flash_enabled = True
        self.screen_effects_preset = DEFAULT_SCREEN_EFFECT_PRESET
        self.screen_effects_play_mode = DEFAULT_SCREEN_EFFECT_PLAY_MODE
        self.screen_edge_flash_color = "red"
        self.screen_edge_flash_intensity = 0.35
        self.screen_edge_flash_thickness = 12
        self.screen_edge_flash_duration_ms = 260
        self.screen_edge_flash_headshot_boost = 1.25

        # 武器击杀音效配置
        self.weapon_kill_sounds = {
            # 手枪
            "weapon_usp_silencer": "0",
            "weapon_hkp2000": "0", 
            "weapon_glock": "0",
            "weapon_p250": "0",
            "weapon_fiveseven": "0",
            "weapon_cz75a": "0",
            "weapon_elite": "0",
            "weapon_deagle": "0",
            "weapon_revolver": "0",
            "weapon_tec9": "0",
            # 冲锋枪
            "weapon_mac10": "0",
            "weapon_mp9": "0",
            "weapon_mp7": "0",
            "weapon_ump45": "0",
            "weapon_p90": "0",
            "weapon_bizon": "0",
            "weapon_mp5sd": "0",
            # 步枪
            "weapon_ak47": "0",
            "weapon_m4a1": "0",
            "weapon_m4a1_silencer": "0",
            "weapon_famas": "0",
            "weapon_galilar": "0",
            "weapon_aug": "0",
            "weapon_sg556": "0",
            # 狙击枪
            "weapon_awp": "0",
            "weapon_ssg08": "0",
            "weapon_scar20": "0",
            "weapon_g3sg1": "0",
            # 霰弹枪
            "weapon_nova": "0",
            "weapon_xm1014": "0",
            "weapon_mag7": "0",
            "weapon_sawedoff": "0",
            # 机枪
            "weapon_m249": "0",
            "weapon_negev": "0",
            # 近战
            "weapon_knife": "0",
            "weapon_taser": "0",
            # 手雷/道具
            "weapon_hegrenade": "0",
            "weapon_molotov": "0",
            "weapon_incgrenade": "0"
        }
        
        # 武器击杀语音配置
        self.weapon_kill_voices = {}
        
        # 初始化所有武器的语音设置
        for weapon in self.weapon_kill_sounds.keys():
            self.weapon_kill_voices[weapon] = "0"  # 默认不使用特定语音
            
        # 初始化所有武器的切枪音效设置
        for weapon in self.weapon_kill_sounds.keys():
            self.weapon_switch_sounds[weapon] = "0"  # 默认不使用切枪音效
            
        # 复制武器击杀音效配置作为初始配置，但排除近战武器和手雷/道具
        for weapon in self.weapon_kill_sounds.keys():
            # 跳过近战武器和手雷/道具
            if weapon not in ["weapon_knife", "weapon_taser", "weapon_hegrenade", "weapon_molotov", "weapon_incgrenade"]:
                self.weapon_reload_sounds[weapon] = "0"  # 默认不使用换弹音效
        
        # 音乐播放器设置
        self.music_enabled = False  # 默认不启用音乐播放器
        self.music_show_player = True  # 显示底部播放栏
        self.music_volume = 0.5  # 音乐音量
        self.music_play_mode = "sequence"  # 播放模式: sequence/shuffle/repeat_one/repeat_all
        
        # 游戏联动设置
        self.music_game_link_enabled = True  # 启用游戏状态联动
        self.music_death_action = "play"  # 死亡时动作: play/none
        self.music_death_volume_custom = False  # 是否使用自定义死亡音量
        self.music_death_volume = 1.0  # 死亡时音量
        self.music_revive_action = "lower"  # 复活时动作: pause/lower/keep
        self.music_revive_volume = 0.2  # 复活时降低的音量
        self.music_fade_enabled = True  # 启用淡入淡出
        self.music_fade_in_duration = 0.5  # 淡入时长
        self.music_fade_out_duration = 0.3  # 淡出时长
        
        # 播放列表
        self.music_current_playlist = "默认"
        self.music_playlists = {
            "默认": []  # 播放列表数据
        }
        self.music_current_index = -1
        self.music_current_position = 0
        self.music_is_playing = False
        
        # 播放栏UI状态
        # 默认折叠以节省屏幕空间（v2.2 起）；老用户的 config.json 里若已有此字段，
        # 加载时会覆盖默认值，不影响其原有习惯
        self.music_bar_expanded = False  # 播放栏展开/收起状态
        
        # URL缓存设置
        self.music_cache_enabled = True
        self.music_default_song_added = False
        
        # 道具瞄点设置 - 修改默认值
        self.utility_guide_enabled = False  # 默认不启用道具瞄点
        self.utility_guide_hotkey = "="  # 修改默认快捷键为 "=" 键
        self.utility_guide_mode = "toggle"  # 修改默认显示模式为 toggle（切换）
        self.utility_guide_opacity = 0.9  # 图片透明度
        self.utility_guide_scale = 1.0  # 图片缩放
        self.utility_guide_position_x = 0  # X轴偏移
        self.utility_guide_position_y = 0  # Y轴偏移
        self.utility_guide_menu_opacity = 0.8  # 菜单透明度
        self.utility_guide_display_duration = 10  # 图片显示时长（秒，切换模式下）
        
        # 道具瞄点排序设置
        self.utility_sort_mode = "frequency"  # 排序模式：frequency/recent/manual
        self.utility_decay_days = 30  # 使用记录衰减天数
        self.utility_min_usage = 1  # 最少使用次数才参与排序
        
        # 语音输出设置（新增）
        self.voice_output_enabled = False  # 默认不启用语音播放
        self.voice_output_volume = 1.0  # 语音输出音量
        self.voice_output_mode = "覆盖"  # 播放模式: 覆盖/混音
        self.voice_output_also_local = True  # 是否同时本地播放
        self.voice_output_slots = {}  # 音板槽位数据
        self.voice_output_stop_key = None  # 中断快捷键（新增）
        
        # --- START: 修改部分 ---
        self.voice_output_ptt_enabled = True # 自动开麦功能开关
        self.voice_output_ptt_key = "v"      # 自动开麦的按键
        self.voice_output_ptt_delay = 500    # 自动开麦的延迟
        self.voice_output_microphone = ""    # 选中的麦克风名称（空 = 系统默认）
        # --- END: 修改部分 ---
        
        # 音效转发设置 (新增)
        self.sfx_forwarding_enabled = False  # 音效转发总开关
        self.sfx_forwarding_options = {      # 各类音效的独立开关
            "kill_sound": True,
            "kill_voice": True,
            "switch_weapon": False,
            "reload_sound": False,
            "gun_sound": False,
            "death_sound": False,
            "special_sound": False, # 包含C4和投掷物
            "round_sound": False
        }
        # 默认界面模式：普通（新手）
        self.ui_expert_mode = False
        self.config_snapshot_auto_before_risky_ops = True
        self.config_snapshot_max_keep = 20
        self.audio_policy_profile = "kill_preempt_v1"
        self.audio_event_timeline_enabled = True
        
        # 迁移旧配置（如果存在）
        self.migrate_old_config()

        # 加载配置
        self.load_config()

        # A3: 注册 atexit flush，兜底 taskkill/异常退出/SIGINT 等场景
        # （closeEvent 已调 save_config_now()，atexit 是第二道防线）
        self._register_atexit_flush()

    def _register_atexit_flush(self):
        """注册进程退出前的 flush，保证防抖 timer 未触发时改动不丢。

        仅注册一次。注册失败时静默，绝不影响启动。
        """
        if self._atexit_registered:
            return
        try:
            atexit.register(self._atexit_flush)
            self._atexit_registered = True
        except Exception:
            # 注册失败（极罕见）不影响 config 正常工作
            pass

    def _atexit_flush(self):
        """进程退出钩子：若防抖 timer 中有待写改动，同步 flush 到磁盘。"""
        try:
            with self._save_lock:
                has_pending = self._save_timer is not None
                if has_pending:
                    try:
                        self._save_timer.cancel()
                    except Exception:
                        pass
                    self._save_timer = None
            if has_pending:
                # 释放锁后再调用 _do_save_config（它内部会重新加锁）
                self._do_save_config()
        except Exception:
            # 退出钩子里严禁抛异常，否则影响 Python 解释器清理
            pass

    def _normalize_gun_sound_profile_values(self):
        for profile in GUN_SOUND_PROFILE_LIST:
            setattr(
                self,
                profile.style_key,
                resolve_gun_sound_style(getattr(self, profile.style_key, "0")),
            )
            setattr(
                self,
                profile.mute_duration_key,
                normalize_gun_sound_hold_duration(
                    getattr(self, profile.mute_duration_key, profile.default_mute_duration),
                    profile.default_mute_duration,
                ),
            )
            setattr(
                self,
                profile.duck_ratio_key,
                normalize_gun_sound_duck_ratio(
                    getattr(
                        self,
                        profile.duck_ratio_key,
                        getattr(self, "gun_sound_duck_ratio", profile.default_duck_ratio),
                    ),
                    getattr(self, "gun_sound_duck_ratio", profile.default_duck_ratio),
                ),
            )
            setattr(
                self,
                profile.legacy_enabled_key,
                bool(getattr(self, profile.legacy_enabled_key, False)),
            )

    def _normalize_gun_sound_config(self, config_data: dict | None = None):
        self._normalize_gun_sound_profile_values()
        has_master_flag = isinstance(config_data, dict) and "gun_sound_enabled" in config_data
        if not has_master_flag and is_gun_sound_master_enabled(self):
            self.gun_sound_enabled = True
        sync_legacy_gun_sound_flags(self)
        self._normalize_gun_sound_ducking_config(config_data)

    def _normalize_gun_sound_ducking_config(self, config_data: dict | None = None):
        self.gun_sound_ducking_enabled = bool(getattr(self, "gun_sound_ducking_enabled", True))
        self.gun_sound_duck_ratio = normalize_gun_sound_duck_ratio(
            getattr(self, "gun_sound_duck_ratio", DEFAULT_GUN_SOUND_DUCK_RATIO),
            DEFAULT_GUN_SOUND_DUCK_RATIO,
        )
        self.gun_sound_duck_attack_ms = normalize_gun_sound_duck_time_ms(
            getattr(self, "gun_sound_duck_attack_ms", DEFAULT_GUN_SOUND_DUCK_ATTACK_MS),
            DEFAULT_GUN_SOUND_DUCK_ATTACK_MS,
        )
        self.gun_sound_duck_release_ms = normalize_gun_sound_duck_time_ms(
            getattr(self, "gun_sound_duck_release_ms", DEFAULT_GUN_SOUND_DUCK_RELEASE_MS),
            DEFAULT_GUN_SOUND_DUCK_RELEASE_MS,
        )
        self.gun_sound_duck_fallback_hotkey_mode = bool(
            getattr(self, "gun_sound_duck_fallback_hotkey_mode", True)
        )

        processes = getattr(self, "gun_sound_duck_target_processes", ["cs2.exe", "csgo.exe"])
        if not isinstance(processes, (list, tuple, set)):
            processes = ["cs2.exe", "csgo.exe"]
        normalized_processes = []
        for process_name in processes:
            name = str(process_name).strip()
            if name:
                normalized_processes.append(name)
        self.gun_sound_duck_target_processes = normalized_processes or ["cs2.exe", "csgo.exe"]

    def migrate_old_config(self):
        """迁移旧目录中的配置文件（如果存在）。

        这条迁移是给**源码运行 / 老版本就地升级**用的：早年配置存在程序目录旁，
        后来改存 `%LOCALAPPDATA%\\CS2Customizer\\`，所以启动时把旧的搬过来一次。

        ⚠ **QA-001：冻结态一律不迁。**
        打包后的程序目录（`_MEIPASS` / `_internal`）里那份 `config.json` 天然不是
        用户的配置，而是**打包机上的那一份**。发布包曾经把开发机的活配置带了进去，
        于是每台新机器首启都会把它复制成自己的配置：CS2 目录指向打包机的盘符、
        `onboarding_completed` 缺键取默认 True 导致首启引导被跳过。
        打包侧已经从 stage 和 datas 两处拿掉了它（`build_release.py`），
        这里再加一道运行时安全带 —— 两边都堵住，将来任何一侧回退都不会重演。
        """
        if getattr(sys, "frozen", False):
            return

        old_config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILENAME)
        new_config_path = get_config_path()

        # 如果旧配置存在且新配置不存在，则复制
        if os.path.exists(old_config_path) and not os.path.exists(new_config_path):
            try:
                shutil.copy2(old_config_path, new_config_path)
                logger.info(f"已将配置文件从 {old_config_path} 迁移到 {new_config_path}")
            except Exception as e:
                logger.error(f"迁移配置文件失败: {e}")

    #: QA-001 一次性纠正的标记键。写进配置后不再重复纠正，
    #: 免得用户之后**故意**把 csgo_dir 留空时被反复弹引导。
    _SEED_REPAIR_FLAG = "seeded_config_repaired_qa001"

    def _repair_seeded_config(self, config_data):
        """把「被发布包里那份开发机配置写脏」的用户配置纠正回来（QA-001）。

        判据要足够窄，只打中真正的受害者，别误伤正常用户：

        1. 还没纠正过（`_SEED_REPAIR_FLAG` 不在配置里）；
        2. `csgo_dir` **非空**但**指向一个不存在的路径** —— 正常用户要么没配（空），
           要么配的是自己机器上真实存在的目录。只有"从别人机器上抄来的路径"
           才会既非空又不存在；
        3. 配置里**没有** `onboarding_completed` 键 —— 这是种子配置的指纹。
           自己走完引导的用户，这个键一定被写进去了。

        三条同时成立才动手：清空那个假目录，并让首启引导重新弹一次。
        用户走完引导就会把 `csgo_dir` 指到自己的 CS2，功能随之恢复。
        """
        try:
            if not isinstance(config_data, dict):
                return
            if config_data.get(self._SEED_REPAIR_FLAG):
                return
            if "onboarding_completed" in config_data:
                return          # 走过引导的真实用户，不碰
            stale_dir = str(config_data.get("csgo_dir") or "").strip()
            if not stale_dir or os.path.isdir(stale_dir):
                return          # 没配 或 配的是真目录 —— 都不是受害者

            self.csgo_dir = ""
            self.onboarding_completed = False
            setattr(self, self._SEED_REPAIR_FLAG, True)
            logger.warning(
                "检测到 CS2 目录 %r 在本机不存在，且配置来自安装包自带的种子配置"
                "（QA-001）。已清空该路径并重新开启首次使用引导，"
                "请在引导里重新选择你的 CS2 安装目录。", stale_dir
            )
        except Exception:
            # 纠正失败绝不能挡住启动：最坏情况是维持现状，用户仍可手动改目录。
            logger.exception("QA-001 种子配置纠正失败，已跳过")

    def migrate_hud_legacy_to_rules(self, config_data=None):
        """
        将旧 HUD 字段迁移到统一规则引擎结构。
        若已存在 hud_rules，则仅做归一化。
        """
        try:
            self.hud_rules_profile = normalize_profile(self.hud_rules_profile)
            self.hud_runtime_sync_mode = normalize_sync_mode(self.hud_runtime_sync_mode)
            self.hud_runtime_refresh_key = normalize_runtime_refresh_key(self.hud_runtime_refresh_key)

            has_new_rules = (
                isinstance(config_data, dict)
                and isinstance(config_data.get("hud_rules"), dict)
            )

            if has_new_rules:
                self.hud_rules = normalize_hud_rules(self.hud_rules, profile=self.hud_rules_profile)
            else:
                migrated = get_default_hud_rules(self.hud_rules_profile)

                if isinstance(self.hud_color_static, int) and self.hud_color_static >= 0:
                    migrated["default_color"] = self.hud_color_static

                legacy_map = self.hud_color_dynamic_map if isinstance(self.hud_color_dynamic_map, dict) else {}

                event_map = {
                    "kill": "kill",
                    "headshot_kill": "headshot_kill",
                    "multi_kill": "multi_kill",
                    "death": "death",
                    "low_health": "low_health",
                }
                state_map = {
                    "bomb_planted": "bomb_planted",
                    "round_win": "round_win",
                    "round_lose": "round_lose",
                    "weapon_rifle": "weapon_rifle",
                    "weapon_sniper": "weapon_sniper",
                    "weapon_pistol": "weapon_pistol",
                    "weapon_knife": "weapon_knife",
                    "round_live": "round_live",
                    "round_start": "round_start",
                }

                for legacy_key, new_key in event_map.items():
                    entry = legacy_map.get(legacy_key, {})
                    if isinstance(entry, dict):
                        color = entry.get("color", -1)
                        migrated["event_rules"][new_key]["enabled"] = isinstance(color, int) and color >= 0
                        migrated["event_rules"][new_key]["main"] = color if isinstance(color, int) else migrated["event_rules"][new_key]["main"]
                        migrated["event_rules"][new_key]["effect"] = entry.get("effect", migrated["event_rules"][new_key]["effect"])
                        migrated["event_rules"][new_key]["alt"] = entry.get("alt_color", migrated["event_rules"][new_key]["alt"])

                for legacy_key, new_key in state_map.items():
                    entry = legacy_map.get(legacy_key, {})
                    if isinstance(entry, dict):
                        color = entry.get("color", -1)
                        migrated["state_rules"][new_key]["enabled"] = isinstance(color, int) and color >= 0
                        migrated["state_rules"][new_key]["main"] = color if isinstance(color, int) else migrated["state_rules"][new_key]["main"]
                        migrated["state_rules"][new_key]["effect"] = entry.get("effect", migrated["state_rules"][new_key]["effect"])
                        migrated["state_rules"][new_key]["alt"] = entry.get("alt_color", migrated["state_rules"][new_key]["alt"])

                default_entry = legacy_map.get("default", {})
                if isinstance(default_entry, dict):
                    default_color = default_entry.get("color", migrated["default_color"])
                    if isinstance(default_color, int) and default_color >= 0:
                        migrated["default_color"] = default_color

                migrated["event_rules"]["kill"]["duration_ms"] = int(max(0.0, float(self.hud_color_kill_duration)) * 1000)
                migrated["event_rules"]["headshot_kill"]["duration_ms"] = int(max(0.0, float(self.hud_color_headshot_duration)) * 1000)
                migrated["event_rules"]["multi_kill"]["duration_ms"] = int(max(0.0, float(self.hud_color_multi_kill_duration)) * 1000)
                migrated["event_rules"]["death"]["duration_ms"] = int(max(0.0, float(self.hud_color_death_duration)) * 1000)
                migrated["event_rules"]["low_health"]["threshold"] = int(self.hud_color_low_health_threshold)

                self.hud_runtime_refresh_key = normalize_runtime_refresh_key(self.hud_color_refresh_key or self.hud_runtime_refresh_key)
                self.hud_rules_enabled = bool(self.hud_color_enabled) or bool(self.hud_rules_enabled)
                self.hud_rules = normalize_hud_rules(migrated, profile=self.hud_rules_profile)

            normalized_keys = {}
            key_rules = self.hud_rules.get("key_rules", {})
            for i in range(1, 10):
                key = str(i)
                entry = key_rules.get(key, {})
                normalized_keys[key] = bool(entry.get("enabled", False))
            self.hud_keymap_enabled = normalized_keys

            self.hud_rules_version = self.hud_rules.get("version", self.hud_rules_version)
        except Exception as e:
            logger.error(f"HUD 规则迁移失败，回退默认配置: {e}")
            self.hud_rules_profile = "balanced_default"
            self.hud_rules = get_default_hud_rules(self.hud_rules_profile)
            self.hud_rules_version = self.hud_rules.get("version", 1)
            self.hud_rules_enabled = True
            self.hud_runtime_sync_mode = "safe"
            self.hud_runtime_refresh_key = "w"
            self.hud_keymap_enabled = {str(i): False for i in range(1, 10)}

    @property
    def hud_color_enabled(self):
        """兼容别名（Phase1-1.4 合并）：与 hud_rules_enabled 同一概念。

        历史上是两个独立字段、靠页面手工镜像同步；现在读写都直通
        hud_rules_enabled，旧配置文件里的 hud_color_enabled 键仍可读取迁移。
        """
        return self.hud_rules_enabled

    @hud_color_enabled.setter
    def hud_color_enabled(self, value):
        self.hud_rules_enabled = bool(value)

    def load_config(self):
        """从新位置加载配置"""
        config_path = get_config_path()
        config_data = None
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

                # 基础设置
                self.kill_sound_enabled = config_data.get("kill_sound_enabled", self.kill_sound_enabled)
                self.kill_voice_enabled = config_data.get("kill_voice_enabled", self.kill_voice_enabled)
                self.cfg_check_enabled = config_data.get("cfg_check_enabled", self.cfg_check_enabled)
                self.mode = config_data.get("mode", self.mode)
                self.csgo_dir = config_data.get("csgo_dir", self.csgo_dir)
                self.kill_icon_enabled = config_data.get("kill_icon_enabled", self.kill_icon_enabled)
                self.debug_mode = config_data.get("debug_mode", self.debug_mode)
                
                # 额外功能开关
                self.gun_sound_enabled = config_data.get("gun_sound_enabled", self.gun_sound_enabled)
                
                # 枪声相关设置
                self.awp_enabled = config_data.get("awp_enabled", self.awp_enabled)
                self.awp_style = config_data.get("awp_style", self.awp_style)
                self.deagle_enabled = config_data.get("deagle_enabled", self.deagle_enabled)
                self.deagle_style = config_data.get("deagle_style", self.deagle_style)
                self.usp_enabled = config_data.get("usp_enabled", self.usp_enabled)
                self.usp_style = config_data.get("usp_style", self.usp_style)
                
                # 击杀图标设置
                self.kill_icon_style = config_data.get("kill_icon_style", self.kill_icon_style)
                self.kill_icon_offset_x = config_data.get("kill_icon_offset_x", self.kill_icon_offset_x)
                self.kill_icon_offset_y = config_data.get("kill_icon_offset_y", self.kill_icon_offset_y)
                self.kill_icon_scale = config_data.get("kill_icon_scale", self.kill_icon_scale)
                self.kill_icon_base_width = config_data.get("kill_icon_base_width", self.kill_icon_base_width)
                self.kill_icon_base_height = config_data.get("kill_icon_base_height", self.kill_icon_base_height)
                
                # 击杀图标FPS设置
                self.kill_icon_fps_1 = config_data.get("kill_icon_fps_1", self.kill_icon_fps_1)
                self.kill_icon_fps_2 = config_data.get("kill_icon_fps_2", self.kill_icon_fps_2)
                self.kill_icon_fps_3 = config_data.get("kill_icon_fps_3", self.kill_icon_fps_3)
                self.kill_icon_fps_4 = config_data.get("kill_icon_fps_4", self.kill_icon_fps_4)
                self.kill_icon_fps_5 = config_data.get("kill_icon_fps_5", self.kill_icon_fps_5)

                # 新增武器配置
                self.revolver_enabled = config_data.get("revolver_enabled", self.revolver_enabled)
                self.revolver_style = config_data.get("revolver_style", self.revolver_style)
                self.ssg08_enabled = config_data.get("ssg08_enabled", self.ssg08_enabled)
                self.ssg08_style = config_data.get("ssg08_style", self.ssg08_style)
                self.scar20_enabled = config_data.get("scar20_enabled", self.scar20_enabled)
                self.scar20_style = config_data.get("scar20_style", self.scar20_style)
                self.g3sg1_enabled = config_data.get("g3sg1_enabled", self.g3sg1_enabled)
                self.g3sg1_style = config_data.get("g3sg1_style", self.g3sg1_style)
                self.nova_enabled = config_data.get("nova_enabled", self.nova_enabled)
                self.nova_style = config_data.get("nova_style", self.nova_style)
                self.mag7_enabled = config_data.get("mag7_enabled", self.mag7_enabled)
                self.mag7_style = config_data.get("mag7_style", self.mag7_style)
                self.sawedoff_enabled = config_data.get("sawedoff_enabled", self.sawedoff_enabled)
                self.sawedoff_style = config_data.get("sawedoff_style", self.sawedoff_style)
                
                # 枪声静音时长设置
                self.awp_mute_duration = config_data.get("awp_mute_duration", self.awp_mute_duration)
                self.deagle_mute_duration = config_data.get("deagle_mute_duration", self.deagle_mute_duration)
                self.usp_mute_duration = config_data.get("usp_mute_duration", self.usp_mute_duration)
                self.revolver_mute_duration = config_data.get("revolver_mute_duration", self.revolver_mute_duration)
                self.ssg08_mute_duration = config_data.get("ssg08_mute_duration", self.ssg08_mute_duration)
                self.scar20_mute_duration = config_data.get("scar20_mute_duration", self.scar20_mute_duration)
                self.g3sg1_mute_duration = config_data.get("g3sg1_mute_duration", self.g3sg1_mute_duration)
                self.nova_mute_duration = config_data.get("nova_mute_duration", self.nova_mute_duration)
                self.mag7_mute_duration = config_data.get("mag7_mute_duration", self.mag7_mute_duration)
                self.sawedoff_mute_duration = config_data.get("sawedoff_mute_duration", self.sawedoff_mute_duration)
                for profile in GUN_SOUND_PROFILE_LIST:
                    setattr(
                        self,
                        profile.legacy_enabled_key,
                        config_data.get(profile.legacy_enabled_key, getattr(self, profile.legacy_enabled_key, False)),
                    )
                    setattr(
                        self,
                        profile.style_key,
                        config_data.get(profile.style_key, getattr(self, profile.style_key, "0")),
                    )
                    setattr(
                        self,
                        profile.mute_duration_key,
                        config_data.get(
                            profile.mute_duration_key,
                            getattr(self, profile.mute_duration_key, profile.default_mute_duration),
                        ),
                    )
                    setattr(
                        self,
                        profile.duck_ratio_key,
                        config_data.get(
                            profile.duck_ratio_key,
                            getattr(
                                self,
                                profile.duck_ratio_key,
                                getattr(self, "gun_sound_duck_ratio", profile.default_duck_ratio),
                            ),
                        ),
                    )
                self.gun_sound_ducking_enabled = config_data.get("gun_sound_ducking_enabled", self.gun_sound_ducking_enabled)
                self.gun_sound_duck_ratio = config_data.get("gun_sound_duck_ratio", self.gun_sound_duck_ratio)
                self.gun_sound_duck_attack_ms = config_data.get("gun_sound_duck_attack_ms", self.gun_sound_duck_attack_ms)
                self.gun_sound_duck_release_ms = config_data.get("gun_sound_duck_release_ms", self.gun_sound_duck_release_ms)
                self.gun_sound_duck_fallback_hotkey_mode = config_data.get(
                    "gun_sound_duck_fallback_hotkey_mode",
                    self.gun_sound_duck_fallback_hotkey_mode,
                )
                self.gun_sound_duck_target_processes = config_data.get(
                    "gun_sound_duck_target_processes",
                    self.gun_sound_duck_target_processes,
                )
                
                # 死亡音效设置
                self.death_sound_enabled = config_data.get("death_sound_enabled", self.death_sound_enabled)
                self.death_sound_style = config_data.get("death_sound_style", self.death_sound_style)
                
                # 观战模式和玩家ID设置
                self.spectator_mode_mute = config_data.get("spectator_mode_mute", self.spectator_mode_mute)
                self.player_steamid = config_data.get("player_steamid", self.player_steamid)
                
                # 放大功能设置
                self.magnifier_enabled = config_data.get("magnifier_enabled", self.magnifier_enabled)
                if "magnifier" in config_data:
                    self.magnifier = config_data.get("magnifier", self.magnifier)
                
                # 特殊音效设置
                self.grenade_sound_enabled = config_data.get("grenade_sound_enabled", self.grenade_sound_enabled)
                self.c4_sound_enabled = config_data.get("c4_sound_enabled", self.c4_sound_enabled)
                
                # 特殊音效风格设置
                if "grenade_sound_styles" in config_data:
                    grenade_styles = config_data["grenade_sound_styles"]
                    if isinstance(grenade_styles, dict):
                        for grenade_type, style in grenade_styles.items():
                            if grenade_type in self.grenade_sound_styles:
                                self.grenade_sound_styles[grenade_type] = style
                self.c4_sound_style = config_data.get("c4_sound_style", self.c4_sound_style)
                
                # 回合音效设置
                self.round_sound_enabled = config_data.get("round_sound_enabled", self.round_sound_enabled)
                self.round_start_style = config_data.get("round_start_style", self.round_start_style)
                self.round_action_style = config_data.get("round_action_style", self.round_action_style)
                self.round_win_style = config_data.get("round_win_style", self.round_win_style)
                self.round_lose_style = config_data.get("round_lose_style", self.round_lose_style)
                self.round_mvp_style = config_data.get("round_mvp_style", self.round_mvp_style)
                self.round_sound_volume = config_data.get("round_sound_volume", self.round_sound_volume)
                
                # 血量警告设置
                self.health_warning_enabled = config_data.get("health_warning_enabled", self.health_warning_enabled)
                self.health_warning_threshold = config_data.get("health_warning_threshold", self.health_warning_threshold)
                self.health_warning_style = config_data.get("health_warning_style", self.health_warning_style)
                
                # 切枪音效设置
                self.switch_weapon_sound_enabled = config_data.get("switch_weapon_sound_enabled", self.switch_weapon_sound_enabled)
                
                # 换弹音效设置
                self.reload_sound_enabled = config_data.get("reload_sound_enabled", self.reload_sound_enabled)
                
                # 音量设置
                # 钳制到 0-1，避免历史脏配置（如存成 100）导致首页显示 10000%
                try:
                    self.volume = max(0.0, min(1.0, float(config_data.get("volume", self.volume))))
                except (TypeError, ValueError):
                    self.volume = 1.0

                # 分类音量（逐键校验 + 夹紧 0~1，兼容旧配置缺键）
                loaded_cat = config_data.get("category_volumes")
                if isinstance(loaded_cat, dict):
                    for _k in self.category_volumes:
                        try:
                            _v = float(loaded_cat.get(_k, self.category_volumes[_k]))
                        except (TypeError, ValueError):
                            _v = self.category_volumes[_k]
                        self.category_volumes[_k] = max(0.0, min(1.0, _v))

                # 响度归一设置
                self.audio_loudness_normalize_enabled = bool(
                    config_data.get("audio_loudness_normalize_enabled", self.audio_loudness_normalize_enabled)
                )
                try:
                    self.audio_loudness_target = max(
                        0.02, min(1.0, float(config_data.get("audio_loudness_target", self.audio_loudness_target)))
                    )
                except (TypeError, ValueError):
                    pass

                # 窗口大小设置
                self.window_width = config_data.get("window_width", self.window_width)
                self.window_height = config_data.get("window_height", self.window_height)
                self.use_saved_size = config_data.get("use_saved_size", self.use_saved_size)
                self.compact_mode = config_data.get("compact_mode", self.compact_mode)
                from ui_design_system import normalize_font_scale
                self.ui_font_scale = normalize_font_scale(config_data.get("ui_font_scale", self.ui_font_scale))
                self.debug_file_log = bool(config_data.get("debug_file_log", self.debug_file_log))
                self.nav_frequent_enabled = bool(config_data.get("nav_frequent_enabled", self.nav_frequent_enabled))
                self.map_preset_enabled = bool(config_data.get("map_preset_enabled", self.map_preset_enabled))
                _mpr = config_data.get("map_preset_rules", self.map_preset_rules)
                self.map_preset_rules = _mpr if isinstance(_mpr, dict) else {}
                self.osd_enabled = bool(config_data.get("osd_enabled", self.osd_enabled))
                _osd_c = str(config_data.get("osd_corner", self.osd_corner) or "bottom_right")
                self.osd_corner = _osd_c if _osd_c in ("top_left", "top_right", "bottom_left", "bottom_right") else "bottom_right"
                self.usage_report_enabled = bool(config_data.get("usage_report_enabled", self.usage_report_enabled))
                self.usage_install_id = str(config_data.get("usage_install_id", self.usage_install_id) or "")
                try:
                    self.usage_last_sent_ts = float(config_data.get("usage_last_sent_ts", self.usage_last_sent_ts) or 0.0)
                except (TypeError, ValueError):
                    self.usage_last_sent_ts = 0.0
                _crp = str(config_data.get("crash_report_prompt", self.crash_report_prompt) or "ask")
                self.crash_report_prompt = _crp if _crp in ("ask", "never") else "ask"
                try:
                    self.crash_report_last_ts = max(0.0, float(config_data.get("crash_report_last_ts", self.crash_report_last_ts)))
                except (TypeError, ValueError):
                    self.crash_report_last_ts = 0.0
                try:
                    _gsi_port = int(config_data.get("gsi_port", self.gsi_port))
                    self.gsi_port = _gsi_port if 1024 <= _gsi_port <= 65535 else 3000
                except (TypeError, ValueError):
                    self.gsi_port = 3000
                # P4.1: 能读到配置文件=非全新安装；缺字段则默认 True 豁免老用户
                self.onboarding_completed = bool(config_data.get("onboarding_completed", True))
                # QA-001 存量纠正：装过 2.2.0/2.2.1 的机器，配置已经被发布包里那份
                # 开发机 config.json 写脏了 —— `csgo_dir` 指向打包机的盘符，
                # 而"有配置文件"又让上面这行把首启引导豁免掉。两个错误叠在一起：
                # 功能不工作，且唯一会教用户怎么修的入口被关了。
                # 光在打包侧删掉源头，救不了已经装过的人，所以这里做一次性纠正。
                self._repair_seeded_config(config_data)
                _ca = str(config_data.get("close_action", self.close_action) or "ask")
                self.close_action = _ca if _ca in ("ask", "tray", "exit") else "ask"
                _wg = config_data.get("window_geometry", self.window_geometry)
                if (
                    isinstance(_wg, (list, tuple)) and len(_wg) == 4
                    and all(isinstance(v, (int, float)) for v in _wg)
                ):
                    self.window_geometry = [int(v) for v in _wg]
                else:
                    self.window_geometry = []
                
                # 主题设置
                self.theme_mode = config_data.get("theme_mode", self.theme_mode)
                self.ui_theme = config_data.get("ui_theme", self.ui_theme)
                
                # 兼容性处理：如果 ui_theme 不存在但 theme_mode 存在，进行转换
                if "ui_theme" not in config_data and "theme_mode" in config_data:
                    # 将旧的中文主题名转换为新的英文主题名
                    if self.theme_mode == "白天模式":
                        self.ui_theme = "light"
                    else:
                        self.ui_theme = "dark"
                
                # 准心设置
                self.crosshair_enabled = config_data.get("crosshair_enabled", self.crosshair_enabled)
                self.crosshair_size = config_data.get("crosshair_size", self.crosshair_size)
                self.crosshair_thickness = config_data.get("crosshair_thickness", self.crosshair_thickness)
                self.crosshair_color = config_data.get("crosshair_color", self.crosshair_color)
                self.crosshair_style = config_data.get("crosshair_style", self.crosshair_style)
                self.crosshair_custom_data = config_data.get("crosshair_custom_data", self.crosshair_custom_data)
                self.crosshair_animation = config_data.get("crosshair_animation", self.crosshair_animation)
                self.crosshair_kill_effect = config_data.get("crosshair_kill_effect", self.crosshair_kill_effect)
                self.crosshair_reset_enabled = config_data.get("crosshair_reset_enabled", self.crosshair_reset_enabled)
                self.crosshair_renderer = config_data.get("crosshair_renderer", self.crosshair_renderer)
                
                # 闪光效果设置
                self.flash_enabled = config_data.get("flash_enabled", self.flash_enabled)
                self.flash_bg_color = config_data.get("flash_bg_color", self.flash_bg_color)
                self.flash_max_opacity = config_data.get("flash_max_opacity", self.flash_max_opacity)
                self.flash_image_style = config_data.get("flash_image_style", self.flash_image_style)
                self.flash_image_opacity = config_data.get("flash_image_opacity", self.flash_image_opacity)
                self.flash_image_position = config_data.get("flash_image_position", self.flash_image_position)
                self.flash_image_size = config_data.get("flash_image_size", self.flash_image_size)
                
                # 闪光样式设置
                self.flash_style = config_data.get("flash_style", self.flash_style)
                self.flash_style_params = config_data.get("flash_style_params", self.flash_style_params)
                self.flash_fade_in_enabled = config_data.get("flash_fade_in_enabled", self.flash_fade_in_enabled)
                self.flash_fade_out_enabled = config_data.get("flash_fade_out_enabled", self.flash_fade_out_enabled)
                
                # 闪光图片轮换设置
                self.flash_image_rotation = config_data.get("flash_image_rotation", self.flash_image_rotation)
                self.flash_current_image_index = config_data.get("flash_current_image_index", self.flash_current_image_index)
                
                # 闪光音频设置
                self.flash_audio_enabled = config_data.get("flash_audio_enabled", self.flash_audio_enabled)
                self.flash_audio_style = config_data.get("flash_audio_style", self.flash_audio_style)
                self.flash_audio_rotation = config_data.get("flash_audio_rotation", self.flash_audio_rotation)
                self.flash_audio_volume = config_data.get("flash_audio_volume", self.flash_audio_volume)
                self.flash_current_audio_index = config_data.get("flash_current_audio_index", self.flash_current_audio_index)
                self.flash_audio_auto_stop = config_data.get("flash_audio_auto_stop", self.flash_audio_auto_stop)
                
                # 持枪视角设置
                self.viewmodel_cycle_key = config_data.get("viewmodel_cycle_key", self.viewmodel_cycle_key)
                if "viewmodel_presets" in config_data:
                    self.viewmodel_presets = config_data["viewmodel_presets"]
                
                # 自动切换设置
                self.viewmodel_auto_switch_enabled = config_data.get("viewmodel_auto_switch_enabled", self.viewmodel_auto_switch_enabled)
                self.viewmodel_auto_switch_key = config_data.get("viewmodel_auto_switch_key", self.viewmodel_auto_switch_key)
                self.viewmodel_auto_switch_interval = config_data.get("viewmodel_auto_switch_interval", self.viewmodel_auto_switch_interval)

                # HUD颜色设置
                self.hud_color_enabled = config_data.get("hud_color_enabled", self.hud_color_enabled)
                self.hud_color_mode = config_data.get("hud_color_mode", self.hud_color_mode)
                self.hud_color_static = config_data.get("hud_color_static", self.hud_color_static)
                self.hud_color_refresh_key = config_data.get("hud_color_refresh_key", self.hud_color_refresh_key)
                if "hud_color_dynamic_map" in config_data and isinstance(config_data["hud_color_dynamic_map"], dict):
                    saved_map = config_data["hud_color_dynamic_map"]
                    for key, val in saved_map.items():
                        if isinstance(val, int):
                            # 兼容V1旧格式：int → dict
                            self.hud_color_dynamic_map[key] = {"color": val, "effect": "solid", "alt_color": -1}
                        elif isinstance(val, dict) and key in self.hud_color_dynamic_map:
                            self.hud_color_dynamic_map[key].update(val)
                self.hud_color_low_health_threshold = config_data.get("hud_color_low_health_threshold", self.hud_color_low_health_threshold)
                self.hud_color_kill_duration = config_data.get("hud_color_kill_duration", self.hud_color_kill_duration)
                self.hud_color_death_duration = config_data.get("hud_color_death_duration", self.hud_color_death_duration)
                self.hud_color_multi_kill_duration = config_data.get("hud_color_multi_kill_duration", self.hud_color_multi_kill_duration)
                self.hud_color_headshot_duration = config_data.get("hud_color_headshot_duration", self.hud_color_headshot_duration)

                # HUD统一规则引擎配置
                self.hud_rules_version = config_data.get("hud_rules_version", self.hud_rules_version)
                self.hud_rules_enabled = config_data.get("hud_rules_enabled", self.hud_rules_enabled)
                self.hud_rules_profile = config_data.get("hud_rules_profile", self.hud_rules_profile)
                self.hud_runtime_sync_mode = config_data.get("hud_runtime_sync_mode", self.hud_runtime_sync_mode)
                self.hud_runtime_refresh_key = config_data.get("hud_runtime_refresh_key", self.hud_runtime_refresh_key)
                if isinstance(config_data.get("hud_rules"), dict):
                    self.hud_rules = config_data.get("hud_rules")
                if isinstance(config_data.get("hud_keymap_enabled"), dict):
                    for i in range(1, 10):
                        k = str(i)
                        self.hud_keymap_enabled[k] = bool(config_data["hud_keymap_enabled"].get(k, self.hud_keymap_enabled[k]))

                # 屏幕特效设置
                self.screen_effects_enabled = config_data.get("screen_effects_enabled", self.screen_effects_enabled)
                self.screen_edge_flash_enabled = config_data.get("screen_edge_flash_enabled", self.screen_edge_flash_enabled)
                self.screen_edge_flash_color = config_data.get("screen_edge_flash_color", self.screen_edge_flash_color)
                self.screen_edge_flash_intensity = config_data.get("screen_edge_flash_intensity", self.screen_edge_flash_intensity)
                self.screen_edge_flash_thickness = config_data.get("screen_edge_flash_thickness", self.screen_edge_flash_thickness)
                self.screen_edge_flash_duration_ms = config_data.get("screen_edge_flash_duration_ms", self.screen_edge_flash_duration_ms)
                self.screen_edge_flash_headshot_boost = config_data.get("screen_edge_flash_headshot_boost", self.screen_edge_flash_headshot_boost)
                if "screen_effects_preset" in config_data:
                    self.screen_effects_preset = normalize_screen_effect_preset(
                        config_data.get("screen_effects_preset"),
                        self.screen_effects_preset,
                    )
                else:
                    self.screen_effects_preset = infer_screen_effect_preset_from_legacy(
                        self.screen_edge_flash_intensity,
                        self.screen_edge_flash_thickness,
                        self.screen_edge_flash_duration_ms,
                        self.screen_edge_flash_headshot_boost,
                    )
                self.screen_effects_play_mode = normalize_screen_effect_play_mode(
                    config_data.get("screen_effects_play_mode", self.screen_effects_play_mode),
                    self.screen_effects_play_mode,
                )

                # 武器击杀音效配置
                if "weapon_kill_sounds" in config_data:
                    weapon_sounds = config_data["weapon_kill_sounds"]
                    if isinstance(weapon_sounds, dict):
                        for weapon, style in weapon_sounds.items():
                            if weapon in self.weapon_kill_sounds:
                                self.weapon_kill_sounds[weapon] = style
                                
                # 武器击杀语音配置
                if "weapon_kill_voices" in config_data:
                    weapon_voices = config_data["weapon_kill_voices"]
                    if isinstance(weapon_voices, dict):
                        for weapon, style in weapon_voices.items():
                            if weapon in self.weapon_kill_voices:
                                self.weapon_kill_voices[weapon] = style
                                
                # 武器切换音效配置
                if "weapon_switch_sounds" in config_data:
                    weapon_switch_sounds = config_data["weapon_switch_sounds"]
                    if isinstance(weapon_switch_sounds, dict):
                        for weapon, style in weapon_switch_sounds.items():
                            if weapon in self.weapon_switch_sounds:
                                self.weapon_switch_sounds[weapon] = style
                                
                # 武器换弹音效配置
                if "weapon_reload_sounds" in config_data:
                    weapon_reload_sounds = config_data["weapon_reload_sounds"]
                    if isinstance(weapon_reload_sounds, dict):
                        for weapon, style in weapon_reload_sounds.items():
                            if weapon in self.weapon_reload_sounds:
                                self.weapon_reload_sounds[weapon] = style
                
                # 音乐播放器设置
                self.music_enabled = config_data.get("music_enabled", self.music_enabled)
                self.music_show_player = config_data.get("music_show_player", self.music_show_player)
                self.music_volume = config_data.get("music_volume", self.music_volume)
                self.music_play_mode = config_data.get("music_play_mode", self.music_play_mode)
                
                # 游戏联动设置
                self.music_game_link_enabled = config_data.get("music_game_link_enabled", self.music_game_link_enabled)
                self.music_death_action = config_data.get("music_death_action", self.music_death_action)
                self.music_death_volume_custom = config_data.get("music_death_volume_custom", self.music_death_volume_custom)
                self.music_death_volume = config_data.get("music_death_volume", self.music_death_volume)
                self.music_revive_action = config_data.get("music_revive_action", self.music_revive_action)
                self.music_revive_volume = config_data.get("music_revive_volume", self.music_revive_volume)
                self.music_fade_enabled = config_data.get("music_fade_enabled", self.music_fade_enabled)
                self.music_fade_in_duration = config_data.get("music_fade_in_duration", self.music_fade_in_duration)
                self.music_fade_out_duration = config_data.get("music_fade_out_duration", self.music_fade_out_duration)
                
                # 播放列表
                self.music_current_playlist = config_data.get("music_current_playlist", self.music_current_playlist)
                self.music_playlists = config_data.get("music_playlists", self.music_playlists)
                self.music_current_index = config_data.get("music_current_index", self.music_current_index)
                self.music_current_position = config_data.get("music_current_position", self.music_current_position)
                self.music_is_playing = config_data.get("music_is_playing", self.music_is_playing)
                self.music_bar_expanded = config_data.get("music_bar_expanded", self.music_bar_expanded)
                self.music_cache_enabled = config_data.get("music_cache_enabled", self.music_cache_enabled)
                self.music_default_song_added = config_data.get("music_default_song_added", self.music_default_song_added)
                
                # 道具瞄点设置
                self.utility_guide_enabled = config_data.get("utility_guide_enabled", self.utility_guide_enabled)
                self.utility_guide_hotkey = config_data.get("utility_guide_hotkey", self.utility_guide_hotkey)
                self.utility_guide_mode = config_data.get("utility_guide_mode", self.utility_guide_mode)
                self.utility_guide_opacity = config_data.get("utility_guide_opacity", self.utility_guide_opacity)
                self.utility_guide_scale = config_data.get("utility_guide_scale", self.utility_guide_scale)
                self.utility_guide_position_x = config_data.get("utility_guide_position_x", self.utility_guide_position_x)
                self.utility_guide_position_y = config_data.get("utility_guide_position_y", self.utility_guide_position_y)
                self.utility_guide_menu_opacity = config_data.get("utility_guide_menu_opacity", self.utility_guide_menu_opacity)
                self.utility_guide_display_duration = config_data.get("utility_guide_display_duration", self.utility_guide_display_duration)
                
                # 道具瞄点排序设置
                self.utility_sort_mode = config_data.get("utility_sort_mode", self.utility_sort_mode)
                self.utility_decay_days = config_data.get("utility_decay_days", self.utility_decay_days)
                self.utility_min_usage = config_data.get("utility_min_usage", self.utility_min_usage)
                
                # 语音输出设置（新增）
                self.voice_output_enabled = config_data.get("voice_output_enabled", self.voice_output_enabled)
                self.voice_output_volume = config_data.get("voice_output_volume", self.voice_output_volume)
                self.voice_output_mode = config_data.get("voice_output_mode", self.voice_output_mode)
                self.voice_output_also_local = config_data.get("voice_output_also_local", self.voice_output_also_local)
                self.voice_output_slots = config_data.get("voice_output_slots", self.voice_output_slots)
                self.voice_output_stop_key = config_data.get("voice_output_stop_key", self.voice_output_stop_key)  # 加载中断快捷键

                # --- START: 修改部分 ---
                self.voice_output_ptt_enabled = config_data.get("voice_output_ptt_enabled", self.voice_output_ptt_enabled)
                self.voice_output_ptt_key = config_data.get("voice_output_ptt_key", self.voice_output_ptt_key)
                self.voice_output_ptt_delay = config_data.get("voice_output_ptt_delay", self.voice_output_ptt_delay)
                self.voice_output_microphone = str(config_data.get("voice_output_microphone", self.voice_output_microphone) or "")
                # --- END: 修改部分 ---

                # 音效转发设置 (新增)
                self.sfx_forwarding_enabled = config_data.get("sfx_forwarding_enabled", self.sfx_forwarding_enabled)
                if "sfx_forwarding_options" in config_data and isinstance(config_data["sfx_forwarding_options"], dict):
                    # 使用update方法，只更新存在的键，保留新增的默认键
                    self.sfx_forwarding_options.update(config_data["sfx_forwarding_options"])
                self.ui_expert_mode = bool(config_data.get("ui_expert_mode", self.ui_expert_mode))
                self.config_snapshot_auto_before_risky_ops = bool(
                    config_data.get(
                        "config_snapshot_auto_before_risky_ops",
                        self.config_snapshot_auto_before_risky_ops,
                    )
                )
                # QA-010: 这里原来是**裸 int()**，是 load_config 里 20 个数值转换中
                # 唯一一个没兜底的（其余 19 个要么有局部 except (TypeError, ValueError)，
                # 要么像 window_geometry 那样有 isinstance 前置校验）。
                # 后果不是"这个值不对"，而是**整个软件起不来**：
                # 模块级 `config = Config()` 在 import 时就跑 load_config，
                # 而下面那个 except 只兜 (FileNotFoundError, JSONDecodeError, KeyError)，
                # ValueError/TypeError 一路冒泡到 import config —— 没界面、没提示、
                # 没自愈，用户只能自己去 %LOCALAPPDATA%\CS2Customizer\config.json 手改或删掉。
                # 实测：值为 "abc" → ValueError；值为 {"a":1} → TypeError；
                #       ""/[]/null/"20"/20 靠后面的 `or 20` 侥幸兜住。
                # 顺手把范围也钳住：负数/0 会让 prune_snapshots 把快照全删光。
                try:
                    _snap_keep = int(
                        config_data.get("config_snapshot_max_keep", self.config_snapshot_max_keep) or 20
                    )
                    self.config_snapshot_max_keep = _snap_keep if 1 <= _snap_keep <= 1000 else 20
                except (TypeError, ValueError):
                    self.config_snapshot_max_keep = 20
                self.audio_policy_profile = str(
                    config_data.get("audio_policy_profile", self.audio_policy_profile) or "kill_preempt_v1"
                )
                self.audio_event_timeline_enabled = bool(
                    config_data.get("audio_event_timeline_enabled", self.audio_event_timeline_enabled)
                )

        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            self._load_error = f"配置文件加载失败，已恢复默认设置: {e}"
            logger.error(f"加载配置失败: {e}。使用默认值。")
            # 损坏(非缺失)的配置先隔离备份,保留用户数据与排障线索,再写默认
            if not isinstance(e, FileNotFoundError):
                try:
                    if os.path.exists(config_path):
                        import time as _t
                        quarantine = f"{config_path}.corrupt-{_t.strftime('%Y%m%d_%H%M%S')}"
                        os.replace(config_path, quarantine)
                        logger.warning(f"损坏配置已隔离为: {quarantine}")
                except OSError as _qe:
                    logger.warning(f"隔离损坏配置失败(忽略): {_qe}")
            # 如果配置文件不存在或无效，保存一份默认配置
            self._do_save_config()
        finally:
            self._normalize_gun_sound_config(config_data)
            self.migrate_hud_legacy_to_rules(config_data)
            # P4.2: schema 版本迁移（在所有字段读入后执行）
            self._run_schema_migrations(config_data)

    # ---------------- P4.2: 配置 schema 迁移框架 ----------------

    def _run_schema_migrations(self, config_data):
        """把旧版配置逐级迁移到 CONFIG_SCHEMA_VERSION。

        - 无 config_schema_version 字段的历史配置按版本 0 处理；
        - 迁移函数注册在 CONFIG_MIGRATIONS（dict: from_version -> 方法名/可调用）；
        - 任一迁移异常都被隔离（记录后继续），绝不让迁移把配置带崩。
        迁移完成后把 self.config_schema_version 提升到最新，下次保存即写回。
        """
        try:
            if isinstance(config_data, dict):
                from_version = int(config_data.get("config_schema_version", 0) or 0)
            else:
                from_version = CONFIG_SCHEMA_VERSION  # 无文件=新装，已是最新
        except (TypeError, ValueError):
            from_version = 0

        version = from_version
        while version < CONFIG_SCHEMA_VERSION:
            migrate = CONFIG_MIGRATIONS.get(version)
            if migrate is None:
                break  # 没有对应迁移则停在当前版本，避免空转
            try:
                migrate(self, config_data if isinstance(config_data, dict) else {})
                logger.info(f"配置 schema 迁移完成: v{version} -> v{version + 1}")
            except Exception:
                logger.exception(f"配置 schema 迁移失败: v{version} -> v{version + 1}（已跳过）")
            version += 1

        self.config_schema_version = CONFIG_SCHEMA_VERSION
        if from_version != CONFIG_SCHEMA_VERSION and isinstance(config_data, dict):
            # 有过迁移→立即落盘固化新版本号
            try:
                self._do_save_config()
            except Exception:
                logger.exception("迁移后保存配置失败（忽略）")

    def save_config(self):
        """防抖保存配置（500ms内多次调用只执行一次实际写入）"""
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.5, self._do_save_config)
            self._save_timer.daemon = True
            self._save_timer.start()

    def save_config_now(self):
        """立即保存配置（用于程序退出等需要确保写入的场景）"""
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self._do_save_config()

    def _do_save_config(self):
        """保存配置到新位置（原子写入）"""
        config_path = get_config_path()

        # 确保目录存在
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        tmp_path = config_path + ".tmp"

        # 持有锁进行序列化，防止并发修改导致数据不一致
        with self._save_lock:
            try:
                self._normalize_gun_sound_config()
                with open(tmp_path, "w", encoding="utf-8") as f:
                    payload = {
                    # 基础设置
                    "kill_sound_enabled": self.kill_sound_enabled,
                    "kill_voice_enabled": self.kill_voice_enabled,
                    "cfg_check_enabled": self.cfg_check_enabled,
                    "mode": self.mode,
                    "csgo_dir": self.csgo_dir,
                    "kill_icon_enabled": self.kill_icon_enabled,
                    "debug_mode": self.debug_mode,
            "ui_font_scale": self.ui_font_scale,
            "debug_file_log": self.debug_file_log,
            "nav_frequent_enabled": self.nav_frequent_enabled,
            "map_preset_enabled": self.map_preset_enabled,
            "map_preset_rules": self.map_preset_rules,
            "osd_enabled": self.osd_enabled,
            "osd_corner": self.osd_corner,
            "usage_report_enabled": self.usage_report_enabled,
            "usage_install_id": self.usage_install_id,
            "usage_last_sent_ts": self.usage_last_sent_ts,
                    "crash_report_prompt": self.crash_report_prompt,
                    "crash_report_last_ts": self.crash_report_last_ts,
                    "gsi_port": self.gsi_port,
                    "config_schema_version": self.config_schema_version,
                    "onboarding_completed": self.onboarding_completed,
                    # QA-001: 纠正只做一次。不落盘的话，用户若真心想把 csgo_dir 留空，
                    # 每次启动都会被重新弹一次引导。
                    self._SEED_REPAIR_FLAG: bool(getattr(self, self._SEED_REPAIR_FLAG, False)),
                    "close_action": self.close_action,
                    "window_geometry": self.window_geometry,
                    
                    # 额外功能开关
                    "gun_sound_enabled": self.gun_sound_enabled,
                    
                    # 枪声相关设置
                    "awp_enabled": self.awp_enabled,
                    "awp_style": self.awp_style,
                    "deagle_enabled": self.deagle_enabled,
                    "deagle_style": self.deagle_style,
                    "usp_enabled": self.usp_enabled,
                    "usp_style": self.usp_style,

                    # 击杀图标设置
                    "kill_icon_style": self.kill_icon_style,
                    "kill_icon_offset_x": self.kill_icon_offset_x,
                    "kill_icon_offset_y": self.kill_icon_offset_y,
                    "kill_icon_scale": self.kill_icon_scale,
                    "kill_icon_base_width": self.kill_icon_base_width,
                    "kill_icon_base_height": self.kill_icon_base_height,
                    
                    # 击杀图标FPS设置
                    "kill_icon_fps_1": self.kill_icon_fps_1,
                    "kill_icon_fps_2": self.kill_icon_fps_2,
                    "kill_icon_fps_3": self.kill_icon_fps_3,
                    "kill_icon_fps_4": self.kill_icon_fps_4,
                    "kill_icon_fps_5": self.kill_icon_fps_5,
                    
                    # 新增武器配置
                    "revolver_enabled": self.revolver_enabled,
                    "revolver_style": self.revolver_style,
                    "ssg08_enabled": self.ssg08_enabled,
                    "ssg08_style": self.ssg08_style,
                    "scar20_enabled": self.scar20_enabled,
                    "scar20_style": self.scar20_style,
                    "g3sg1_enabled": self.g3sg1_enabled,
                    "g3sg1_style": self.g3sg1_style,
                    "nova_enabled": self.nova_enabled,
                    "nova_style": self.nova_style,
                    "mag7_enabled": self.mag7_enabled,
                    "mag7_style": self.mag7_style,
                    "sawedoff_enabled": self.sawedoff_enabled,
                    "sawedoff_style": self.sawedoff_style,
                    
                    # 枪声静音时长设置
                    "awp_mute_duration": self.awp_mute_duration,
                    "deagle_mute_duration": self.deagle_mute_duration,
                    "usp_mute_duration": self.usp_mute_duration,
                    "revolver_mute_duration": self.revolver_mute_duration,
                    "ssg08_mute_duration": self.ssg08_mute_duration,
                    "scar20_mute_duration": self.scar20_mute_duration,
                    "g3sg1_mute_duration": self.g3sg1_mute_duration,
                    "nova_mute_duration": self.nova_mute_duration,
                    "mag7_mute_duration": self.mag7_mute_duration,
                    "sawedoff_mute_duration": self.sawedoff_mute_duration,
                    "gun_sound_ducking_enabled": self.gun_sound_ducking_enabled,
                    "gun_sound_duck_ratio": self.gun_sound_duck_ratio,
                    "gun_sound_duck_attack_ms": self.gun_sound_duck_attack_ms,
                    "gun_sound_duck_release_ms": self.gun_sound_duck_release_ms,
                    "gun_sound_duck_fallback_hotkey_mode": self.gun_sound_duck_fallback_hotkey_mode,
                    "gun_sound_duck_target_processes": self.gun_sound_duck_target_processes,
                    
                    # 死亡音效设置
                    "death_sound_enabled": self.death_sound_enabled,
                    "death_sound_style": self.death_sound_style,
                    
                    # 观战模式和玩家ID设置
                    "spectator_mode_mute": self.spectator_mode_mute,
                    "player_steamid": self.player_steamid,
                    
                    # 放大功能设置
                    "magnifier_enabled": self.magnifier_enabled,
                    "magnifier": self.magnifier,
                    
                    # 特殊音效设置
                    "grenade_sound_enabled": self.grenade_sound_enabled,
                    "c4_sound_enabled": self.c4_sound_enabled,
                    "grenade_sound_styles": self.grenade_sound_styles,
                    "c4_sound_style": self.c4_sound_style,
                    
                    # 回合音效设置
                    "round_sound_enabled": self.round_sound_enabled,
                    "round_start_style": self.round_start_style,
                    "round_action_style": self.round_action_style,
                    "round_win_style": self.round_win_style,
                    "round_lose_style": self.round_lose_style,
                    "round_mvp_style": self.round_mvp_style,
                    "round_sound_volume": self.round_sound_volume,
                    
                    # 血量警告设置
                    "health_warning_enabled": self.health_warning_enabled,
                    "health_warning_threshold": self.health_warning_threshold,
                    "health_warning_style": self.health_warning_style,
                    
                    # 切枪音效设置
                    "switch_weapon_sound_enabled": self.switch_weapon_sound_enabled,
                    "weapon_switch_sounds": self.weapon_switch_sounds,
                    
                    # 换弹音效设置
                    "reload_sound_enabled": self.reload_sound_enabled,
                    "weapon_reload_sounds": self.weapon_reload_sounds,
                    
                    # 音量设置
                    "volume": self.volume,
                    "category_volumes": self.category_volumes,
                    "audio_loudness_normalize_enabled": self.audio_loudness_normalize_enabled,
                    "audio_loudness_target": self.audio_loudness_target,

                    # 窗口大小设置
                    "window_width": self.window_width,
                    "window_height": self.window_height,
                    "use_saved_size": self.use_saved_size,
                    "compact_mode": self.compact_mode,
                    
                    # 主题设置
                    "theme_mode": self.theme_mode,
                    "ui_theme": self.ui_theme,
                    
                    # 准心设置
                    "crosshair_enabled": self.crosshair_enabled,
                    "crosshair_size": self.crosshair_size,
                    "crosshair_thickness": self.crosshair_thickness,
                    "crosshair_color": self.crosshair_color,
                    "crosshair_style": self.crosshair_style,
                    "crosshair_custom_data": self.crosshair_custom_data,
                    "crosshair_animation": self.crosshair_animation,
                    "crosshair_kill_effect": self.crosshair_kill_effect,
                    "crosshair_reset_enabled": self.crosshair_reset_enabled,
                    "crosshair_renderer": self.crosshair_renderer,
                    
                    # 闪光效果设置
                    "flash_enabled": self.flash_enabled,
                    "flash_bg_color": self.flash_bg_color,
                    "flash_max_opacity": self.flash_max_opacity,
                    "flash_image_style": self.flash_image_style,
                    "flash_image_opacity": self.flash_image_opacity,
                    "flash_image_position": self.flash_image_position,
                    "flash_image_size": self.flash_image_size,
                    
                    # 闪光样式设置
                    "flash_style": self.flash_style,
                    "flash_style_params": self.flash_style_params,
                    "flash_fade_in_enabled": self.flash_fade_in_enabled,
                    "flash_fade_out_enabled": self.flash_fade_out_enabled,
                    
                    # 闪光图片轮换设置
                    "flash_image_rotation": self.flash_image_rotation,
                    "flash_current_image_index": self.flash_current_image_index,
                    
                    # 闪光音频设置
                    "flash_audio_enabled": self.flash_audio_enabled,
                    "flash_audio_style": self.flash_audio_style,
                    "flash_audio_rotation": self.flash_audio_rotation,
                    "flash_audio_volume": self.flash_audio_volume,
                    "flash_current_audio_index": self.flash_current_audio_index,
                    "flash_audio_auto_stop": self.flash_audio_auto_stop,
                    
                    # 持枪视角设置
                    "viewmodel_cycle_key": self.viewmodel_cycle_key,
                    "viewmodel_presets": self.viewmodel_presets,
                    
                    # 自动切换设置
                    "viewmodel_auto_switch_enabled": self.viewmodel_auto_switch_enabled,
                    "viewmodel_auto_switch_key": self.viewmodel_auto_switch_key,
                    "viewmodel_auto_switch_interval": self.viewmodel_auto_switch_interval,

                    # HUD颜色设置
                    "hud_color_enabled": self.hud_color_enabled,
                    "hud_color_mode": self.hud_color_mode,
                    "hud_color_static": self.hud_color_static,
                    "hud_color_refresh_key": self.hud_color_refresh_key,
                    "hud_color_dynamic_map": self.hud_color_dynamic_map,
                    "hud_color_low_health_threshold": self.hud_color_low_health_threshold,
                    "hud_color_kill_duration": self.hud_color_kill_duration,
                    "hud_color_death_duration": self.hud_color_death_duration,
                    "hud_color_multi_kill_duration": self.hud_color_multi_kill_duration,
                    "hud_color_headshot_duration": self.hud_color_headshot_duration,

                    # HUD统一规则引擎配置
                    "hud_rules_version": self.hud_rules_version,
                    "hud_rules_enabled": self.hud_rules_enabled,
                    "hud_rules_profile": self.hud_rules_profile,
                    "hud_rules": self.hud_rules,
                    "hud_runtime_sync_mode": self.hud_runtime_sync_mode,
                    "hud_runtime_refresh_key": self.hud_runtime_refresh_key,
                    "hud_keymap_enabled": self.hud_keymap_enabled,

                    # 屏幕特效设置
                    "screen_effects_enabled": self.screen_effects_enabled,
                    "screen_edge_flash_enabled": self.screen_edge_flash_enabled,
                    "screen_effects_preset": normalize_screen_effect_preset(
                        self.screen_effects_preset,
                        DEFAULT_SCREEN_EFFECT_PRESET,
                    ),
                    "screen_effects_play_mode": normalize_screen_effect_play_mode(
                        self.screen_effects_play_mode,
                        DEFAULT_SCREEN_EFFECT_PLAY_MODE,
                    ),
                    "screen_edge_flash_color": self.screen_edge_flash_color,
                    "screen_edge_flash_intensity": self.screen_edge_flash_intensity,
                    "screen_edge_flash_thickness": self.screen_edge_flash_thickness,
                    "screen_edge_flash_duration_ms": self.screen_edge_flash_duration_ms,
                    "screen_edge_flash_headshot_boost": self.screen_edge_flash_headshot_boost,

                    # 武器音效配置
                    "weapon_kill_sounds": self.weapon_kill_sounds,
                    "weapon_kill_voices": self.weapon_kill_voices,
                    
                    # 音乐播放器设置
                    "music_enabled": self.music_enabled,
                    "music_show_player": self.music_show_player,
                    "music_volume": self.music_volume,
                    "music_play_mode": self.music_play_mode,
                    
                    # 游戏联动设置
                    "music_game_link_enabled": self.music_game_link_enabled,
                    "music_death_action": self.music_death_action,
                    "music_death_volume_custom": self.music_death_volume_custom,
                    "music_death_volume": self.music_death_volume,
                    "music_revive_action": self.music_revive_action,
                    "music_revive_volume": self.music_revive_volume,
                    "music_fade_enabled": self.music_fade_enabled,
                    "music_fade_in_duration": self.music_fade_in_duration,
                    "music_fade_out_duration": self.music_fade_out_duration,
                    
                    # 播放列表
                    "music_current_playlist": self.music_current_playlist,
                    "music_playlists": self.music_playlists,
                    "music_current_index": self.music_current_index,
                    "music_current_position": self.music_current_position,
                    "music_is_playing": self.music_is_playing,
                    "music_bar_expanded": self.music_bar_expanded,
                    "music_cache_enabled": self.music_cache_enabled,
                    "music_default_song_added": self.music_default_song_added,
                    
                    # 道具瞄点设置
                    "utility_guide_enabled": self.utility_guide_enabled,
                    "utility_guide_hotkey": self.utility_guide_hotkey,
                    "utility_guide_mode": self.utility_guide_mode,
                    "utility_guide_opacity": self.utility_guide_opacity,
                    "utility_guide_scale": self.utility_guide_scale,
                    "utility_guide_position_x": self.utility_guide_position_x,
                    "utility_guide_position_y": self.utility_guide_position_y,
                    "utility_guide_menu_opacity": self.utility_guide_menu_opacity,
                    "utility_guide_display_duration": self.utility_guide_display_duration,
                    
                    # 道具瞄点排序设置
                    "utility_sort_mode": self.utility_sort_mode,
                    "utility_decay_days": self.utility_decay_days,
                    "utility_min_usage": self.utility_min_usage,
                    
                    # 语音输出设置（新增）
                    "voice_output_enabled": self.voice_output_enabled,
                    "voice_output_volume": self.voice_output_volume,
                    "voice_output_mode": self.voice_output_mode,
                    "voice_output_also_local": self.voice_output_also_local,
                    "voice_output_slots": self.voice_output_slots,
                    "voice_output_stop_key": self.voice_output_stop_key,  # 保存中断快捷键
                    
                    # --- START: 修改部分 ---
                    "voice_output_ptt_enabled": self.voice_output_ptt_enabled,
                    "voice_output_ptt_key": self.voice_output_ptt_key,
                    "voice_output_ptt_delay": self.voice_output_ptt_delay,
                    "voice_output_microphone": self.voice_output_microphone,
                    # --- END: 修改部分 ---
                    
                    # 音效转发设置 (新增)
                    "sfx_forwarding_enabled": self.sfx_forwarding_enabled,
                    "sfx_forwarding_options": self.sfx_forwarding_options,
                    "ui_expert_mode": self.ui_expert_mode,
                    "config_snapshot_auto_before_risky_ops": self.config_snapshot_auto_before_risky_ops,
                    "config_snapshot_max_keep": self.config_snapshot_max_keep,
                    "audio_policy_profile": self.audio_policy_profile,
                    "audio_event_timeline_enabled": self.audio_event_timeline_enabled,
                }
                    payload.update(
                        {
                            profile.legacy_enabled_key: getattr(self, profile.legacy_enabled_key, False)
                            for profile in GUN_SOUND_PROFILE_LIST
                        }
                    )
                    payload.update(
                        {
                            profile.style_key: getattr(self, profile.style_key, "0")
                            for profile in GUN_SOUND_PROFILE_LIST
                        }
                    )
                    payload.update(
                        {
                            profile.mute_duration_key: getattr(
                                self,
                                profile.mute_duration_key,
                                profile.default_mute_duration,
                            )
                            for profile in GUN_SOUND_PROFILE_LIST
                        }
                    )
                    payload.update(
                        {
                            profile.duck_ratio_key: getattr(
                                self,
                                profile.duck_ratio_key,
                                getattr(self, "gun_sound_duck_ratio", profile.default_duck_ratio),
                            )
                            for profile in GUN_SOUND_PROFILE_LIST
                        }
                    )
                    json.dump(payload, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())  # 落盘后再替换:防断电留下残缺文件
                # 原子替换（Windows NTFS 上 os.replace 是原子的）
                os.replace(tmp_path, config_path)
            except Exception as e:
                logger.error(f"保存配置失败: {e}")
                # 清理临时文件
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            
    def reset_player_steamid(self):
        """重置玩家steamid"""
        self.player_steamid = ""
        self.save_config()
        logger.info("已重置玩家SteamID，将在下次检测到玩家数据时自动记录。")

    def get_all_hotkeys(self):
        """返回所有已配置的快捷键及其功能名"""
        hotkeys = {}
        mapping = {
            self.viewmodel_cycle_key: "持枪动作切换",
            self.viewmodel_auto_switch_key: "持枪自动切换",
            self.utility_guide_hotkey: "道具瞄点",
            self.voice_output_stop_key: "语音输出中断",
            self.voice_output_ptt_key: "语音自动开麦",
        }
        for key, func in mapping.items():
            if key:
                normalized = key.strip().lower()
                if normalized:
                    hotkeys[normalized] = func

        if (
            self.hud_rules_enabled
            and self.hud_runtime_sync_mode == "safe"
            and has_runtime_enabled_rules(self.hud_rules)
        ):
            refresh_key = normalize_runtime_refresh_key(self.hud_runtime_refresh_key)
            hotkeys[refresh_key] = "HUD运行时刷新"
        return hotkeys

    def check_hotkey_conflict(self, key, current_function):
        """检查快捷键是否与其他功能冲突，返回冲突的功能名或 None"""
        if not key:
            return None
        normalized = key.strip().lower()
        all_keys = self.get_all_hotkeys()
        if normalized in all_keys and all_keys[normalized] != current_function:
            return all_keys[normalized]
        return None
        

# 提供一个获取应用数据目录的函数
def get_app_data_dir(subfolder=None):
    """获取应用数据目录，可指定子文件夹"""
    base_dir = get_config_dir()
    if subfolder:
        directory = os.path.join(base_dir, subfolder)
        if not os.path.exists(directory):
            os.makedirs(directory)
        return directory
    return base_dir

# 全局配置实例
config = Config()
