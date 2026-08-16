# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import shutil
import sys
import threading
from datetime import datetime

from config import VERSION, get_app_data_dir
from core.resource_catalog import RESOURCE_SPECS
from core.utils.logger import get_logger

logger = get_logger(__name__)

_RESOURCE_COPY_LOCK = threading.Lock()
_RESOURCE_COPY_DONE = threading.Event()
_RESOURCE_COPY_STARTED = False

AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac", ".m4a")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

# 必需资源根目录清单（相对 AppData）。
# 单一事实来源钉在 core/resource_catalog.RESOURCE_SPECS 上，因为资源体检
# （core/audio/audio_resource_health.REQUIRED_AUDIO_DIRS 与
# core/resource_health.collect_visual_resource_health）量的就是这批目录。
# 两边同源，才不会再出现"体检要求存在的目录压根没人负责创建"。
REQUIRED_RESOURCE_ROOTS = tuple(f"resources/{spec.target_rel_root}" for spec in RESOURCE_SPECS)

# --- B3: 资源迁移标志 ---
# 同版本重启时跳过完整资源扫描；任何异常都降级走完整流程（安全默认）
MIGRATION_MARKER_FILENAME = ".resources_migrated"
# schema 用于本迁移逻辑自身的版本号。如果未来我修改了哪些资源需迁移、
# 关键检查清单，bump 这个数字可以让所有老用户重跑一次迁移。
# 2 起：判据由"具体素材文件"改为"目录骨架"（见下）。
MIGRATION_MARKER_SCHEMA = 2
# 只检查极少数"迁移必然产出"的路径。任一缺失就强制完整迁移——
# 保护用户手动删除 AppData 后仍能自动恢复。
#
# 这里原本钉的是两个具体 mp3（C4-1.mp3 / 我方还剩一人.mp3）。素材不随本仓库分发
# 之后那两个文件永远不会出现在 AppData → 判据恒不成立 → 每次启动都白跑一遍完整
# 资源扫描，B3 这条启动优化等于没有。所以改成钉**目录骨架**：它由
# ensure_required_resource_directories() 无条件创建，与用户有没有导入素材无关。
MIGRATION_CRITICAL_FILES = (
    "resources/audio/kill_sounds",
    "resources/audio/gun_sounds",
    "resources/kill_icons",
    "resources/crosshair",
)

class ResourceManager:
    """管理应用资源文件，确保从EXE复制到AppData目录"""
    
    @staticmethod
    def get_exe_resource_path(relative_path):
        """获取打包后EXE中的资源路径"""
        try:
            base_path = sys._MEIPASS  # PyInstaller 打包模式
        except AttributeError:
            base_path = os.path.dirname(os.path.abspath(__file__))  # 正常运行模式
        
        # 统一使用系统路径分隔符
        rel_path = relative_path.replace('/', os.sep).replace('\\', os.sep)
        return os.path.join(base_path, rel_path)
    
    @staticmethod
    def get_app_data_path(relative_path):
        """获取AppData中的资源路径"""
        # 统一使用系统路径分隔符
        rel_path = relative_path.replace('/', os.sep).replace('\\', os.sep)
        return os.path.join(get_app_data_dir(), rel_path)
    
    @staticmethod
    def ensure_directory(directory):
        """确保目录存在。"""
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            return True
        return False

    @staticmethod
    def _directory_has_files(directory):
        """递归判断目录下是否已有任意文件。"""
        if not os.path.isdir(directory):
            return False
        for _root, _dirs, files in os.walk(directory):
            if files:
                return True
        return False

    @staticmethod
    def _merge_directory(src_dir, dst_dir):
        """将资源目录合并到 AppData，保留已有目录结构。"""
        if not os.path.isdir(src_dir):
            return False
        os.makedirs(os.path.dirname(dst_dir), exist_ok=True)
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
        return True

    @staticmethod
    def _copy_file_if_missing(src_path, dst_path):
        if not os.path.isfile(src_path) or os.path.isfile(dst_path):
            return False
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        return True

    @staticmethod
    def _merge_directory_missing_only(src_dir, dst_dir):
        """逐文件补齐缺失的内置资源，绝不覆盖已存在文件（保护用户自定义/改动）。

        用于目标目录已有内容的升级场景：旧逻辑"目录非空即整体跳过"会让
        新版本新增的内置音效/图标永远无法下发给老用户。返回补齐的文件数。
        """
        if not os.path.isdir(src_dir):
            return 0
        copied = 0
        for root, _dirs, files in os.walk(src_dir):
            rel = os.path.relpath(root, src_dir)
            target_root = dst_dir if rel == "." else os.path.join(dst_dir, rel)
            for name in files:
                if ResourceManager._copy_file_if_missing(
                    os.path.join(root, name), os.path.join(target_root, name)
                ):
                    copied += 1
        return copied

    @staticmethod
    def ensure_required_resource_directories():
        """无条件创建全部必需资源根目录，返回本次新建的相对路径列表。

        为什么不再"源目录存在才建"：本仓库不内置任何素材，包内 resources/ 只是空
        骨架。按旧逻辑 kill_sounds / kill_voices / death / c4_sounds / health_warning
        这 5 个目录在干净安装的机器上永远不会出现，于是资源体检恒报缺失 →
        首页系统状态开局就是黄灯、audio_health_check.py 退出码恒为 1。
        而这跟用户有没有素材毫无关系，纯粹是目录没人建。
        """
        created = []
        for rel_root in REQUIRED_RESOURCE_ROOTS:
            try:
                if ResourceManager.ensure_directory(ResourceManager.get_app_data_path(rel_root)):
                    created.append(rel_root)
            except Exception:
                # 与 QA-005 同口径：建不出来不挡启动，但必须留痕并阻止写「迁移完成」标记
                ResourceManager._note_migration_failure(rel_root)
        return created

    @staticmethod
    def migrate_legacy_flat_audio_files():
        """兼容旧版散落音频布局，把包内平铺的音频归位到新版目录结构。

        只负责"拷文件"：目录骨架由 ensure_required_resource_directories() 无条件建好。
        以前这两件事挤在一个函数里，开头的 `源目录不存在就 return` 顺手把
        death / c4_sounds / health_warning 的创建也一起早退掉了。
        风格子目录（default）不预建——空风格目录只会让用户点了没声音。
        """
        src_audio_root = ResourceManager.get_exe_resource_path("resources/audio")
        if not os.path.isdir(src_audio_root):
            return

        death_dir = ResourceManager.get_app_data_path("resources/audio/death")
        c4_style_dir = ResourceManager.get_app_data_path("resources/audio/c4_sounds/default")
        health_style_dir = ResourceManager.get_app_data_path("resources/audio/health_warning/default")
        # "我方还剩艺人" 是早期错字文件名的迁就 token，文件已改回"我方还剩一人"，移除
        health_tokens = ("我方还剩", "还剩一名敌人")

        try:
            for name in os.listdir(src_audio_root):
                src_path = os.path.join(src_audio_root, name)
                lower_name = name.lower()
                if not os.path.isfile(src_path) or not lower_name.endswith(AUDIO_EXTENSIONS):
                    continue
                stem, _ext = os.path.splitext(name)
                if lower_name.startswith("death"):
                    target_dir = death_dir
                elif lower_name.startswith("c4"):
                    target_dir = c4_style_dir
                elif any(token in stem for token in health_tokens):
                    target_dir = health_style_dir
                else:
                    continue
                # _copy_file_if_missing 自己建父目录：有东西要拷才有必要存在风格目录
                ResourceManager._copy_file_if_missing(src_path, os.path.join(target_dir, name))
        except Exception as e:
            logger.warning(f"旧音频结构兼容迁移失败: {e}")

    @staticmethod
    def ensure_flash_images_directory():
        """确保闪光图片目录存在"""
        flash_dir = ResourceManager.get_app_data_path("resources/flash_images")
        ResourceManager.ensure_directory(flash_dir)
        
        # 创建默认样式目录
        default_dir = os.path.join(flash_dir, "default")
        ResourceManager.ensure_directory(default_dir)
        
        return flash_dir

    @staticmethod
    def ensure_flash_audio_directory():
        """确保闪光音频根目录存在（不创建默认风格目录）"""
        flash_audio_dir = ResourceManager.get_app_data_path("resources/flash_audio")
        ResourceManager.ensure_directory(flash_audio_dir)
        return flash_audio_dir

    @staticmethod
    def ensure_crosshair_directory():
        """确保准心资源根目录存在"""
        crosshair_dir = ResourceManager.get_app_data_path("resources/crosshair")
        ResourceManager.ensure_directory(crosshair_dir)
        return crosshair_dir
    
    @staticmethod
    def ensure_gun_sounds_directory():
        """确保枪声目录存在"""
        gun_sounds_dir = ResourceManager.get_app_data_path("resources/audio/gun_sounds")
        ResourceManager.ensure_directory(gun_sounds_dir)

        # 与枪声页/扫描器同源(SUPPORTED_GUN_SOUND_WEAPON_TYPES,18种)：
        # 旧版这里硬编码只建 10 种,导致 glock/p250/fiveseven 等 8 把枪在枪声页
        # 扫不到目录、"打开音频资源"打开不到路径、无法配置枪声。
        try:
            from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_WEAPON_TYPES
            gun_types = list(SUPPORTED_GUN_SOUND_WEAPON_TYPES)
        except Exception:
            gun_types = [
                "glock", "usp", "hkp2000", "p250", "fiveseven", "elite",
                "deagle", "revolver", "tec9", "awp", "ssg08", "scar20",
                "g3sg1", "nova", "xm1014", "mag7", "sawedoff", "taser",
            ]

        # 只建到"武器"这一层。风格目录由用户导入素材时产生：
        # 以前这里按武器硬编码预建风格名（起源/弃王/奇点/塑水宗/天界/默认），
        # 那些名字本身就是随包分发的素材包的产物。没有素材还把它们建出来，
        # 用户在文件管理器里看到一堆空目录，选中后点试听没有任何声音。
        for gun_type in gun_types:
            ResourceManager.ensure_directory(os.path.join(gun_sounds_dir, gun_type))

        return gun_sounds_dir
    
    @staticmethod
    def ensure_kill_icons_directory():
        """确保击杀图标目录存在"""
        kill_icons_dir = ResourceManager.get_app_data_path("resources/kill_icons")
        ResourceManager.ensure_directory(kill_icons_dir)
        
        # 创建默认风格目录
        default_style_dir = os.path.join(kill_icons_dir, "默认")
        ResourceManager.ensure_directory(default_style_dir)
        
        # 为每个击杀数创建子目录（用于多图片格式）
        for i in range(1, 6):
            kill_dir = os.path.join(default_style_dir, str(i))
            ResourceManager.ensure_directory(kill_dir)
        
        return kill_icons_dir

    @staticmethod
    def get_kill_icon_style_dir(style_name):
        return ResourceManager.get_app_data_path(f"resources/kill_icons/{style_name}")

    @staticmethod
    def get_kill_icon_metadata_path(style_name, kills):
        style_dir = ResourceManager.get_kill_icon_style_dir(style_name)
        return os.path.join(style_dir, f"{kills}.json")

    @staticmethod
    def get_kill_icon_sprite_sheet_paths(style_name, kills, variant=""):
        """图集与配置的路径。`variant` 是可选覆写后缀（如爆头专用 `hs`）。

        变体文件名是 `<等级><变体>.png`（`3hs.png`），**不是**新开一层目录：
        存量风格目录里已经有 `1.png` / `1/` 两种含义的条目，再加一层子目录
        会和"逐帧目录"这种老格式撞名。缺省 `variant=""` 时路径与 KI-1 之前
        逐字节相同，存量素材不受影响。
        """
        style_dir = ResourceManager.get_kill_icon_style_dir(style_name)
        suffix = str(variant or "")
        return (
            os.path.join(style_dir, f"{kills}{suffix}.png"),
            os.path.join(style_dir, f"{kills}{suffix}.json"),
        )

    @staticmethod
    def _directory_has_images(directory):
        if not os.path.isdir(directory):
            return False
        for name in os.listdir(directory):
            full_path = os.path.join(directory, name)
            if os.path.isfile(full_path) and name.lower().endswith(IMAGE_EXTENSIONS):
                return True
        return False

    @staticmethod
    def get_kill_icon_legacy_frames_dir(style_name, kills):
        style_dir = ResourceManager.get_kill_icon_style_dir(style_name)
        style_level_dir = os.path.join(style_dir, str(kills))
        if ResourceManager._directory_has_images(style_level_dir):
            return style_level_dir

        if style_name == "默认":
            legacy_dir = ResourceManager.get_app_data_path(f"resources/kill1-{kills}")
            if ResourceManager._directory_has_images(legacy_dir):
                return legacy_dir
        return None

    @staticmethod
    def has_kill_icon_level_assets(style_name, kills):
        sprite_path, json_path = ResourceManager.get_kill_icon_sprite_sheet_paths(style_name, kills)
        if os.path.isfile(sprite_path) and os.path.isfile(json_path):
            return True
        return ResourceManager.get_kill_icon_legacy_frames_dir(style_name, kills) is not None

    @staticmethod
    def style_has_kill_icons(style_name):
        return any(ResourceManager.has_kill_icon_level_assets(style_name, kills) for kills in range(1, 6))

    @staticmethod
    def list_kill_icon_styles():
        styles = []
        icons_dir = ResourceManager.get_app_data_path("resources/kill_icons")
        if os.path.isdir(icons_dir):
            for item in os.listdir(icons_dir):
                # 点号开头的是内部目录（KI-5 的回收站 `.trash`），不是风格。
                # 它本来也过不了 style_has_kill_icons，这里显式挡一道更省得再想。
                if item.startswith("."):
                    continue
                item_path = os.path.join(icons_dir, item)
                if os.path.isdir(item_path) and ResourceManager.style_has_kill_icons(item):
                    styles.append(item)
        if not styles and any(
            ResourceManager._directory_has_images(ResourceManager.get_app_data_path(f"resources/kill1-{kills}"))
            for kills in range(1, 6)
        ):
            styles.append("默认")
        return styles
    
    @staticmethod
    def ensure_utility_guides_directory():
        """确保道具瞄点目录存在"""
        utility_dir = ResourceManager.get_app_data_path("resources/utility_guides")
        ResourceManager.ensure_directory(utility_dir)
        
        # CS2地图列表
        CS2_MAPS = [
            # 活跃地图池
            "de_dust2",      # 荒漠迷城
            "de_mirage",     # 炙热沙城
            "de_inferno",    # 炼狱小镇
            "de_nuke",       # 核子危机
            "de_overpass",   # 死亡游乐园
            "de_vertigo",    # 殒命大厦
            "de_ancient",    # 远古遗迹
            "de_anubis",     # 阿努比斯
            
            # 预备图池
            "de_train",      # 列车停放站
            "de_cache",      # 死城之谜
            "cs_office",     # 办公室
            "cs_italy",      # 意大利
        ]
        
        # 为每个地图创建目录
        for map_name in CS2_MAPS:
            map_dir = os.path.join(utility_dir, map_name)
            ResourceManager.ensure_directory(map_dir)
            
            # 创建示例文件夹（用户可以删除或重命名）
            example_folders = [
                "T-A点进攻",
                "T-B点进攻",
                "CT-A点防守",
                "CT-B点防守",
                "通用道具"
            ]
            
            # 只为de_dust2创建示例文件夹作为参考
            if map_name == "de_dust2":
                for folder in example_folders:
                    folder_path = os.path.join(map_dir, folder)
                    ResourceManager.ensure_directory(folder_path)
                    
                    # 创建说明文件
                    readme_path = os.path.join(folder_path, "使用说明.txt")
                    if not os.path.exists(readme_path):
                        with open(readme_path, 'w', encoding='utf-8') as f:
                            f.write("道具图片命名格式：\n")
                            f.write("站位图片：道具名_站位.jpg\n")
                            f.write("瞄准图片：道具名_瞄准.jpg\n\n")
                            f.write("例如：\n")
                            f.write("Xbox烟_站位.jpg\n")
                            f.write("Xbox烟_瞄准.jpg\n\n")
                            f.write("支持jpg和png格式")
        
        return utility_dir
    
    # --- B3: 迁移标志辅助方法 ---
    @staticmethod
    def _get_migration_marker_path():
        return os.path.join(get_app_data_dir(), MIGRATION_MARKER_FILENAME)

    @staticmethod
    def _read_migration_marker():
        """读取迁移标志文件；任何异常都返回 None（视为未迁移）。"""
        try:
            path = ResourceManager._get_migration_marker_path()
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _write_migration_marker():
        """写入迁移完成标志。失败静默，不影响主流程。"""
        try:
            path = ResourceManager._get_migration_marker_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {
                "schema": MIGRATION_MARKER_SCHEMA,
                "version": VERSION,
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"资源迁移标志写入失败（不影响功能）: {e}")

    @staticmethod
    def _should_skip_migration():
        """判断是否可以跳过完整资源扫描。

        跳过条件（全满足才跳过）：
        1. 标志文件存在且可解析
        2. schema 与当前代码一致
        3. version 与当前版本一致
        4. 关键资源目录仍存在（防用户手动清空 AppData）

        任一条件不满足都返回 False → 走完整迁移流程（安全默认）。
        """
        try:
            marker = ResourceManager._read_migration_marker()
            if marker is None:
                return False
            if marker.get("schema") != MIGRATION_MARKER_SCHEMA:
                return False
            if marker.get("version") != VERSION:
                return False
            for rel in MIGRATION_CRITICAL_FILES:
                # 只关心"这条路径还在不在"（用户手动清空 AppData 的场景），
                # 是目录还是文件无所谓，所以用 exists 而不是 isdir。
                if not os.path.exists(ResourceManager.get_app_data_path(rel)):
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    def copy_resources_to_appdata():
        """首次运行时复制所有资源到 AppData（进程内只执行一次）"""
        global _RESOURCE_COPY_STARTED

        if _RESOURCE_COPY_DONE.is_set():
            return

        with _RESOURCE_COPY_LOCK:
            if _RESOURCE_COPY_DONE.is_set():
                return
            if _RESOURCE_COPY_STARTED:
                should_wait = True
            else:
                _RESOURCE_COPY_STARTED = True
                should_wait = False

        if should_wait:
            _RESOURCE_COPY_DONE.wait()
            return

        try:
            # B3: 标志文件快速路径。失败时降级走完整流程。
            try:
                if ResourceManager._should_skip_migration():
                    logger.info("资源迁移标志命中，跳过完整扫描")
                    return
            except Exception as e:
                logger.warning(f"资源迁移标志检查异常（走完整流程）: {e}")

            ResourceManager._migration_failures = []
            ResourceManager._copy_resources_to_appdata_impl()

            # QA-005: 只有**真的一个目录都没失败**才写「迁移完成」标记。
            # 以前是无条件写：某个目录复制炸了 → 静默吞掉 → 标记照写 →
            # 标记按版本号命中 → 同版本内永不重试 → 内置音效永久缺失。
            failures = list(getattr(ResourceManager, "_migration_failures", []) or [])
            if failures:
                logger.error(
                    "[资源迁移] %d 个目录复制失败：%s。**不写迁移完成标记**，"
                    "下次启动会重试。若持续失败，请检查 %%LOCALAPPDATA%%\\CS2Customizer 的"
                    "磁盘空间与写入权限（内置音效可能不完整）。",
                    len(failures), ", ".join(failures),
                )
            else:
                try:
                    ResourceManager._write_migration_marker()
                except Exception:
                    logger.warning("[资源迁移] 写迁移完成标记失败，下次启动会重跑一次迁移")
        finally:
            _RESOURCE_COPY_DONE.set()

    #: QA-005: 本次迁移里复制失败的目录。非空 → 不写「迁移完成」标记，下次启动重试。
    _migration_failures: list = []

    @staticmethod
    def _note_migration_failure(rel_dir):
        """记一次目录复制失败：写日志 + 计入失败清单（不抛，不挡启动）。"""
        try:
            logger.exception("[资源迁移] 目录复制失败: %s", rel_dir)
            ResourceManager._migration_failures.append(str(rel_dir))
        except Exception:
            pass

    @staticmethod
    def _copy_resources_to_appdata_impl():
        """建好 AppData 的资源目录骨架，并把包内自带的素材（如果有）下发过去。"""
        # 静默执行，不打印日志（避免混乱启动日志）

        # 确保目标根目录存在
        app_data_root = get_app_data_dir()
        if not os.path.exists(app_data_root):
            os.makedirs(app_data_root, exist_ok=True)

        # ① 目录骨架：清单驱动、无条件创建。
        # 放在最前面，这样后面任何一步出错都不会连累"目录该在"这件事。
        ResourceManager.ensure_required_resource_directories()

        # ② 素材下发：只有包内真的带了素材才会发生。
        # 本仓库不分发第三方素材，正常情况下这一整段是空转——它留给
        # 自行往 resources/ 里放素材再打包的分发者。
        resource_dirs = list(REQUIRED_RESOURCE_ROOTS)

        # 处理旧的gif资源目录（如果存在）
        for i in range(1, 6):
            for style in [1]:  # 只迁移风格1
                old_dir = f"resources/kill{style}-{i}"
                resource_dirs.append(old_dir)

        for rel_dir in resource_dirs:
            # 源目录 (EXE内)
            src_dir = ResourceManager.get_exe_resource_path(rel_dir)
            # 目标目录 (AppData)
            dst_dir = ResourceManager.get_app_data_path(rel_dir)

            # 源不存在是**常态**而非异常（没有内置素材）。目录骨架已在 ① 建好，
            # 这里不再兼职建目录——以前那份"哪些目录该建"的手写白名单就是漏了
            # kill_sounds / kill_voices / death / c4_sounds / health_warning 的地方。
            if not os.path.isdir(src_dir):
                continue

            if not ResourceManager._directory_has_files(dst_dir):
                try:
                    ResourceManager._merge_directory(src_dir, dst_dir)
                except Exception:
                    # ⚠ QA-005：这里原来是 `pass  # 静默处理` —— 连一行日志都没有。
                    # 而外层照样会写「迁移完成」标记，标记按版本号命中就整体跳过，
                    # 于是**同一个版本内永不重试**：内置音效目录空着，用户点试听没声音，
                    # 日志里一个字都查不到。复制失败不该挡启动，但**必须留痕**。
                    ResourceManager._note_migration_failure(rel_dir)
                continue

            # 目录已有内容（升级场景）：逐文件补齐新增的内置资源，不覆盖既有文件。
            # 本路径仅在版本升级时到达（迁移标记按 VERSION 命中即整体跳过）
            try:
                copied = ResourceManager._merge_directory_missing_only(src_dir, dst_dir)
                if copied:
                    logger.info(f"[资源迁移] {rel_dir} 补齐 {copied} 个新增内置文件")
            except Exception:
                ResourceManager._note_migration_failure(rel_dir)   # QA-005，同上

        # 确保特殊武器目录存在
        knife_dir = ResourceManager.get_app_data_path("resources/audio/switch_weapons/weapon_knife")
        ResourceManager.ensure_directory(knife_dir)
        
        taser_dir = ResourceManager.get_app_data_path("resources/audio/switch_weapons/weapon_taser")
        ResourceManager.ensure_directory(taser_dir)
        
        # 确保回合音效子目录存在
        round_sounds_dir = ResourceManager.get_app_data_path("resources/audio/round_sounds")
        ResourceManager.ensure_directory(round_sounds_dir)
        
        for subdir in ["start", "action", "win", "lose", "mvp"]:
            subdir_path = os.path.join(round_sounds_dir, subdir)
            ResourceManager.ensure_directory(subdir_path)
        
        # 确保准心资源目录存在
        ResourceManager.ensure_crosshair_directory()

        # 确保闪光图片默认目录存在
        ResourceManager.ensure_flash_images_directory()

        # 确保闪光音频目录存在（不自动创建空风格）
        ResourceManager.ensure_flash_audio_directory()
        
        # 确保枪声目录及子目录存在
        ResourceManager.ensure_gun_sounds_directory()
        
        # 确保击杀图标目录存在
        ResourceManager.ensure_kill_icons_directory()
        
        # 确保道具瞄点目录存在
        ResourceManager.ensure_utility_guides_directory()
        ResourceManager.migrate_legacy_flat_audio_files()

        # 迁移旧击杀图标文件
        ResourceManager.migrate_old_kill_icons()

        # 已删除 migrate_gun_sounds()：它把 `resources/gun audio` 下几个写死名字的
        # wav（awp1 / Desert Eagle1 / usp1…）搬进同样写死的中文风格目录。
        # 那些文件名和风格名都是随包分发的素材包的产物，本仓库不分发素材，
        # 留着只会凭空造出一批空风格目录。
        # 资源检查完成（静默）

    @staticmethod
    def migrate_old_kill_icons():
        """迁移旧的击杀图标到新结构"""
        # 创建默认风格目录
        default_style_dir = ResourceManager.get_app_data_path("resources/kill_icons/默认")
        ResourceManager.ensure_directory(default_style_dir)
        
        # 尝试迁移旧的图标文件
        for kills in range(1, 6):
            # 旧路径格式：resources/kill1-1/
            old_dir = ResourceManager.get_app_data_path(f"resources/kill1-{kills}")
            if os.path.exists(old_dir):
                # 新路径格式：resources/kill_icons/默认/1/
                new_dir = os.path.join(default_style_dir, str(kills))
                
                # 如果新目录不存在或为空，则迁移
                if not os.path.exists(new_dir) or not os.listdir(new_dir):
                    try:
                        if os.path.exists(new_dir):
                            shutil.rmtree(new_dir)
                        shutil.copytree(old_dir, new_dir)
                        pass  # 静默处理
                    except Exception:
                        pass  # 静默处理
