# SPDX-License-Identifier: GPL-3.0-or-later
import os
import platform
import re

from core import crosshair_reset
from core.utils.logger import get_logger

logger = get_logger("CfgUtils")

# Windows Registry (for Steam path lookup)
if platform.system() == "Windows":
    try:
        import winreg
    except ImportError:
        winreg = None
else:
    winreg = None

# GSI 配置文件内容
# P2.3: 端口自适应——3000 被第三方占用时自动改用 3001-3010（见 gsi_server），
# 这里按 config.gsi_port 动态生成 uri，保证 CS2 推送端口与服务器监听端口一致。
CFG_TEMPLATE = """
"PyGSI"
{{
    "uri"               "http://127.0.0.1:{port}/"
    "timeout"           "0.5"
    "buffer"            "0.01"
    "throttle"          "0.0"
    "heartbeat"         "15.0"
    "data"
    {{
        "provider"            "1"
        "map"                 "1"
        "round"               "1"
        "player_id"           "1"
        "player_state"        "1"
        "player_weapons"      "1"
        "player_match_stats"  "1"
        "allplayers_id"       "1"
        "allplayers_state"    "1"
        "allplayers_match_stats" "1"
        "bomb"                "1"
    }}
}}
"""


def get_active_gsi_port() -> int:
    """读取当前应使用的 GSI 端口（config.gsi_port，默认 3000）。"""
    try:
        from config import config as _config

        port = int(getattr(_config, "gsi_port", 3000) or 3000)
        if 1024 <= port <= 65535:
            return port
    except Exception:
        pass
    return 3000


def build_cfg_content(port: int = None) -> str:
    """按端口生成 GSI cfg 文本；port 缺省时取 config.gsi_port。"""
    return CFG_TEMPLATE.format(port=int(port or get_active_gsi_port()))


# 兼容旧引用：默认端口版本（动态内容请用 build_cfg_content()）
CFG_CONTENT = CFG_TEMPLATE.format(port=3000)

# cs2customizer.cfg 文件内容（静音覆盖已改为运行时 Ducking）
CS2C_CFG_CONTENT = """
// CS2 Customizer CFG配置文件

echo "CS2 Customizer CFG配置文件已加载"
"""

def get_steam_path_windows():
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Valve\Steam") as key:
            path = winreg.QueryValueEx(key, "InstallPath")[0]
            if os.path.exists(path):
                return path
    except (FileNotFoundError, OSError):
        pass

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam") as key:
            path = winreg.QueryValueEx(key, "InstallPath")[0]
            if os.path.exists(path):
                return path
    except (FileNotFoundError, OSError):
        pass

    # "仅当前用户"方式安装的 Steam 不写 HKLM，只在 HKCU 有 SteamPath
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path = winreg.QueryValueEx(key, "SteamPath")[0]
            path = os.path.normpath(path)
            if os.path.exists(path):
                return path
    except (FileNotFoundError, OSError):
        pass

    return None


def _normalize_path(value: str) -> str:
    if not value:
        return ""
    # Steam VDF often stores escaped backslashes.
    value = value.replace("\\\\", "\\").strip().strip('"')
    return os.path.normpath(value)


def _iter_steam_library_paths(steam_root: str):
    """Yield Steam library roots (including default root)."""
    seen = set()

    root = _normalize_path(steam_root)
    if root and os.path.isdir(root):
        seen.add(root)
        yield root

    library_vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if not os.path.isfile(library_vdf):
        return

    text = ""
    for enc in ("utf-8", "utf-16", "gbk"):
        try:
            with open(library_vdf, "r", encoding=enc, errors="ignore") as f:
                text = f.read()
            if text:
                break
        except Exception:
            continue
    if not text:
        return

    candidates = set()

    # Newer format: "path" "D:\\SteamLibrary"
    for m in re.finditer(r'"path"\s*"([^"]+)"', text, flags=re.IGNORECASE):
        candidates.add(_normalize_path(m.group(1)))

    # Older format: "1" "D:\\SteamLibrary"
    for m in re.finditer(r'"\d+"\s*"([^"]+)"', text):
        candidates.add(_normalize_path(m.group(1)))

    for path in candidates:
        if not path or path in seen:
            continue
        if os.path.isabs(path) and os.path.isdir(path):
            seen.add(path)
            yield path


def find_cs2_install_dir():
    """Find CS2 install directory across Steam default and library folders."""
    steam_roots = []

    if platform.system() == "Windows":
        reg_path = get_steam_path_windows()
        if reg_path:
            steam_roots.append(reg_path)

    for env_key in ("SteamPath", "SteamRoot"):
        env_val = os.environ.get(env_key)
        if env_val:
            steam_roots.append(env_val)

    # Preserve order while removing duplicates.
    ordered_roots = []
    seen_roots = set()
    for root in steam_roots:
        norm = _normalize_path(root)
        if norm and norm not in seen_roots:
            seen_roots.add(norm)
            ordered_roots.append(norm)

    game_folder_candidates = [
        "Counter-Strike Global Offensive",
        "Counter-Strike 2",
    ]

    for steam_root in ordered_roots:
        for library_root in _iter_steam_library_paths(steam_root):
            for game_folder in game_folder_candidates:
                cs2_dir = os.path.join(library_root, "steamapps", "common", game_folder)
                if os.path.isdir(cs2_dir):
                    return cs2_dir

    return None

def find_cfg_path(cfg_filename="gamestate_integration_cs2customizer.cfg"):
    cs2_dir = find_cs2_install_dir()
    if not cs2_dir:
        return None
    return os.path.join(cs2_dir, "game", "csgo", "cfg", cfg_filename)


def ensure_cfg_exists(csgo_dir, cfg_filename="gamestate_integration_cs2customizer.cfg"):
    """确保游戏内 GSI cfg 存在且内容为最新。

    ⚠ `csgo_dir` 要的是 **CS2 安装根目录**（里面有 `game/csgo/cfg/`），
    不是 cfg 文件本身的路径。`find_cfg_path()` 返回的是**文件全路径**，
    别拿它来喂这个函数 —— GSI 端口自适应那条路就这么传错过（QA-003）。

    QA-003：本函数以前**恒返回 None**，且把写盘异常吞在内部只记 error，
    于是调用方无从判断成败，只能盲写一句「已重写」的成功日志。
    现在返回 bool：True = cfg 已就位且内容最新，False = 没做成。
    老调用方忽略返回值也不受影响。
    """
    if not csgo_dir:
        logger.warning("CS:GO directory not set. Cannot create CFG file.")
        return False

    if not os.path.isdir(csgo_dir):
        # 用 isdir 而不是 exists：传进来一个**文件**路径时 exists 为真，
        # 会一路走到 `makedirs(<文件>/game/csgo/cfg)` 才炸，报错还指不到真因。
        logger.warning(f"CS2 目录不存在或不是目录: {csgo_dir}")
        return False

    cfg_path = os.path.join(csgo_dir, "game", "csgo", "cfg", cfg_filename)
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        # P2.3: cfg 内容按当前生效端口生成（端口自适应后会自动覆写为新端口）
        desired_content = build_cfg_content()
        # 检查文件内容是否一致
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
            if existing_content.strip() != desired_content.strip():
                logger.info(f"Overwriting existing GSI configuration file at: {cfg_path}")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(desired_content)
            else:
                logger.info(f"GSI configuration file is up-to-date at: {cfg_path}")
        else:
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(desired_content)
            logger.info(f"GSI configuration file created at: {cfg_path}")
        return True
    except Exception as e:
        logger.error(f"Error creating/checking GSI configuration file: {e}")
        return False

def ensure_cs2customizer_cfg_exists(csgo_dir):
    """如果 cs2customizer.cfg 不存在，通过统一编译器创建"""
    if not csgo_dir or not os.path.exists(csgo_dir):
        logger.warning(f"CS2 目录无效或不存在: {csgo_dir}")
        return

    cs2customizer_cfg_path = os.path.join(csgo_dir, "game", "csgo", "cfg", "cs2customizer.cfg")
    if not os.path.exists(cs2customizer_cfg_path):
        try:
            from config import config
            from core.cfg_compiler import write_cs2customizer_cfg
            write_cs2customizer_cfg(config)
            logger.info(f"cs2customizer.cfg created via compiler at: {cs2customizer_cfg_path}")
        except Exception as e:
            logger.error(f"Error creating cs2customizer.cfg via compiler: {e}")
    else:
        logger.info(f"cs2customizer.cfg already exists at: {cs2customizer_cfg_path}")

def setup_autoexec(csgo_dir):
    """处理 autoexec.cfg 文件"""
    if not csgo_dir or not os.path.exists(csgo_dir):
        logger.warning(f"CS2 目录无效或不存在: {csgo_dir}")
        return

    autoexec_path = os.path.join(csgo_dir, "game", "csgo", "cfg", "autoexec.cfg")
    exec_command = "exec cs2customizer.cfg"

    try:
        # 统一 utf-8：默认走系统区域编码（中文 Windows 为 GBK），
        # 已有 UTF-8 的 autoexec 会解码失败 → 判存失败 → 每次启动重复追加
        if os.path.exists(autoexec_path):
            with open(autoexec_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if exec_command not in content:
                    with open(autoexec_path, "a", encoding="utf-8") as f:
                        f.write("\n" + exec_command + "\n")
                    logger.info(f"Added '{exec_command}' to autoexec.cfg")
                else:
                    logger.info(f"autoexec.cfg already contains '{exec_command}'")
        else:
            with open(autoexec_path, "w", encoding="utf-8") as f:
                f.write(exec_command + "\n")
            logger.info(f"Created autoexec.cfg and added '{exec_command}'")

        # ⚠ 2026-08-18：**排在后面的同名 alias 会把我们的整段覆盖掉。**
        # 用户实录：`exec cs2customizer.cfg`（开源版）排在我们后面，
        # 用一模一样的 `+quickrepos_attack` 覆盖了我们的准心回正，
        # 而它全文没有 `cl_crosshair_recoil` ⇒ 准星跟随静默失效、零报错。
        # alias 名不能改（存量用户的 config.cfg 里存着指向它的 bind，
        # 改名 = 开火键变死键，见 core/crosshair_reset 的模块说明），
        # 所以只能保证**我们最后 exec**，并且把仍然存在的冲突说出来。
        ensure_cs2customizer_exec_is_last(csgo_dir)
    except Exception as e:
        logger.error(f"Error handling autoexec.cfg: {e}")


def detect_alias_conflicts(csgo_dir):
    """列出排在我们后面、且重定义了我们 alias 的 cfg。

    返回 `[{"cfg": 名字, "aliases": [...]}]`；空列表 = 没人抢。
    **只读**，不改任何文件。
    """
    cfg_dir = os.path.join(csgo_dir or "", "game", "csgo", "cfg")
    autoexec_path = os.path.join(cfg_dir, "autoexec.cfg")
    if not os.path.exists(autoexec_path):
        return []

    def _read(name):
        path = os.path.join(cfg_dir, name if name.lower().endswith(".cfg") else name + ".cfg")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read()
        except OSError:
            return None

    try:
        with open(autoexec_path, "r", encoding="utf-8", errors="ignore") as fh:
            autoexec_text = fh.read()
    except OSError:
        return []
    return crosshair_reset.find_alias_overriders(autoexec_text, _read)


def ensure_cs2customizer_exec_is_last(csgo_dir):
    """把 `exec cs2customizer.cfg` 挪到 autoexec 的最后，并把残余冲突记进日志。

    返回 True 表示确实改写了 autoexec。已经在最后就不动文件
    —— **别每次启动都重写用户自己的文件**。
    """
    autoexec_path = os.path.join(csgo_dir or "", "game", "csgo", "cfg", "autoexec.cfg")
    if not os.path.exists(autoexec_path):
        return False
    try:
        with open(autoexec_path, "r", encoding="utf-8", errors="ignore") as fh:
            original = fh.read()
    except OSError as exc:
        logger.error(f"读 autoexec.cfg 失败: {exc}")
        return False

    rewritten = crosshair_reset.rewrite_autoexec_with_us_last(original)
    moved = rewritten != original
    if moved:
        try:
            with open(autoexec_path, "w", encoding="utf-8") as fh:
                fh.write(rewritten)
            logger.info("已把 'exec cs2customizer.cfg' 挪到 autoexec.cfg 末尾"
                        "（同名 alias 后执行的生效，排在前面等于被后面的 cfg 覆盖）")
        except OSError as exc:
            logger.error(f"写 autoexec.cfg 失败: {exc}")
            return False

    # 挪到最后仍可能有人在**别处**抢（比如用户手工 exec）。剩下的说出来。
    for hit in detect_alias_conflicts(csgo_dir):
        logger.warning(
            f"⚠ {hit['cfg']}.cfg 重定义了 {', '.join(hit['aliases'])} "
            f"—— 它排在 cs2customizer.cfg 之后，准心快速回正/准星跟随会被它覆盖掉。"
            f"请在 autoexec.cfg 里把 'exec {hit['cfg']}.cfg' 移到 'exec cs2customizer.cfg' 之前，"
            f"或者删掉它。")
    return moved


def ensure_hud_cfg_exists(csgo_dir):
    """创建初始 cs2customizer_hud_runtime.cfg（HUD统一规则运行时）"""
    if not csgo_dir or not os.path.exists(csgo_dir):
        return
    hud_cfg_path = os.path.join(csgo_dir, "game", "csgo", "cfg", "cs2customizer_hud_runtime.cfg")
    try:
        os.makedirs(os.path.dirname(hud_cfg_path), exist_ok=True)
        if not os.path.exists(hud_cfg_path):
            with open(hud_cfg_path, "w", encoding="utf-8") as f:
                f.write("cl_hud_color 0\n")
            logger.info(f"cs2customizer_hud_runtime.cfg created at: {hud_cfg_path}")
    except Exception as e:
        logger.error(f"Error creating cs2customizer_hud_runtime.cfg: {e}")


# 确保所有CFG文件存在
def ensure_all_cfg(csgo_dir):
    ensure_cfg_exists(csgo_dir)       # 确保 GSI 配置文件存在
    ensure_cs2customizer_cfg_exists(csgo_dir) # 确保 cs2customizer.cfg 存在
    ensure_hud_cfg_exists(csgo_dir)   # 确保 cs2customizer_hud.cfg 存在
    setup_autoexec(csgo_dir)          # 处理 autoexec.cfg
