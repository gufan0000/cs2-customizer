"""
Unified compiler for cs2customizer.cfg — single source of truth.

All sections are compiled from config state and assembled in a fixed order.
Only this module should write to cs2customizer.cfg.
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Optional, Tuple

from core.hud.rule_compiler import (
    build_hud_rules_block,
    compile_cfg_rules,
    has_hud_runtime_refresh,
)
from core.magnifier_sensitivity import DEFAULT_SYNC_TRIGGER_KEY
from core.utils.logger import get_logger

logger = get_logger("CfgCompiler")

SECTION_ORDER = ["header", "viewmodel", "magnifier_runtime", "hud_rules", "footer"]


def get_cs2customizer_cfg_path(csgo_dir: str) -> Optional[str]:
    if not csgo_dir:
        return None
    return os.path.join(csgo_dir, "game", "csgo", "cfg", "cs2customizer.cfg")


# ── Section compilers ──


def _sanitize_cfg_text(text: str) -> str:
    """移除会破坏 alias/bind 引号结构或注入命令的字符（双引号、分号、换行）。

    预设名称是自由文本输入；若用户输入了 `"` 或 `;`，直接拼进 alias 会让
    生成的 cs2customizer.cfg 语法错乱甚至执行额外命令。这里统一做保守过滤。
    """
    return (
        str(text)
        .replace('"', "")
        .replace(";", "")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def _sanitize_bind_key(key: str) -> str:
    """绑定按键应为单个 token：去掉引号/分号/空白，避免破坏 bind 行。"""
    return _sanitize_cfg_text(key).replace(" ", "").replace("\t", "")


def _coerce_number(value, default: float, lo: float, hi: float) -> str:
    """数值字段强制转 float 并钳制范围。

    x/y/z/fov 可能来自云同步或 .cs2customizer 分享包，若是 `"0; quit"` 这类
    字符串会被原样拼进 alias 形成 console 命令注入，必须数值化。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = default
    if num != num or num in (float("inf"), float("-inf")):  # NaN/Inf
        num = default
    num = max(lo, min(hi, num))
    return f"{num:g}"


def _compile_header() -> str:
    return "// CS2 Customizer CFG配置文件 (auto-generated)"


def _compile_footer() -> str:
    return 'echo "CS2 Customizer CFG配置文件已加载"'


def compile_mute(_config_obj) -> str:
    return ""


def compile_viewmodel(config_obj) -> str:
    parts: List[str] = ["// -- Viewmodel Settings (CS2 Customizer) --"]

    # 准心回正：如果 HUD 运行时刷新已启用，mouse1 由 HUD rules 段合并处理
    crosshair_enabled = getattr(config_obj, "crosshair_reset_enabled", False)
    hud_handles_mouse1 = has_hud_runtime_refresh(config_obj)

    if crosshair_enabled and not hud_handles_mouse1:
        parts.append("")
        parts.append("// == Crosshair Quick Reset ==")
        parts.append("cl_crosshair_recoil 1")
        parts.append('alias +quickrepos_attack "+attack; cl_crosshair_recoil 1"')
        parts.append('alias -quickrepos_attack "-attack; cl_crosshair_recoil 0"')
        parts.append("bind mouse1 +quickrepos_attack")
        parts.append('echo "Crosshair quick reset enabled"')

    presets = getattr(config_obj, "viewmodel_presets", [])
    if presets:
        parts.append("")
        parts.append("// == Viewmodel Presets ==")
        for i, preset in enumerate(presets):
            name = _sanitize_cfg_text(preset.get("name", f"preset{i + 1}")) or f"preset{i + 1}"
            key = _sanitize_bind_key(preset.get("key", ""))
            fov = _coerce_number(preset.get("fov", 68), 68, 1, 179)
            x = _coerce_number(preset.get("x", 2.0), 2.0, -10, 10)
            y = _coerce_number(preset.get("y", 2.0), 2.0, -10, 10)
            z = _coerce_number(preset.get("z", -1.0), -1.0, -10, 10)
            cmd = (
                f'alias viewmodel_{i + 1} "viewmodel_offset_x {x};'
                f" viewmodel_offset_y {y}; viewmodel_offset_z {z};"
                f' viewmodel_fov {fov}; echo {name}"'
            )
            parts.append(cmd)
            if key:
                parts.append(f"bind {key} viewmodel_{i + 1}")

        count = len(presets)
        parts.append("")
        parts.append("// Cycle switch")
        parts.append("alias viewmodel_cycle viewmodel_cycle_1")
        for i in range(count):
            next_i = (i + 1) % count
            parts.append(
                f'alias viewmodel_cycle_{i + 1} "viewmodel_{i + 1};'
                f' alias viewmodel_cycle viewmodel_cycle_{next_i + 1}"'
            )
        cycle_key = _sanitize_bind_key(getattr(config_obj, "viewmodel_cycle_key", "CAPSLOCK")) or "CAPSLOCK"
        parts.append(f"bind {cycle_key} viewmodel_cycle")

    return "\n".join(parts)


def compile_magnifier_runtime(config_obj) -> str:
    magnifier_settings = getattr(config_obj, "magnifier", {}) or {}
    if not isinstance(magnifier_settings, dict):
        return ""

    if not magnifier_settings.get("sensitivity_sync_enabled", False):
        return ""

    sync_key = _sanitize_bind_key(
        str(magnifier_settings.get("sync_trigger_key", DEFAULT_SYNC_TRIGGER_KEY) or DEFAULT_SYNC_TRIGGER_KEY)
    ).upper() or DEFAULT_SYNC_TRIGGER_KEY.upper()
    parts: List[str] = [
        "// -- Magnifier Sensitivity Sync (CS2 Customizer) --",
        f'bind {sync_key} "exec cs2customizer_magnifier_runtime.cfg"',
        'echo "Magnifier sensitivity sync enabled"',
    ]
    return "\n".join(parts)


def compile_hud_rules(config_obj) -> str:
    lines = compile_cfg_rules(config_obj)
    if not lines:
        return ""
    return build_hud_rules_block(lines).rstrip("\n")


# ── Bind conflict detection ──


def _parse_binds(section_name: str, content: str) -> List[Tuple[str, str, str]]:
    """Parse 'bind KEY ...' lines. Returns [(key_lower, full_line, section_name)]."""
    results = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("bind "):
            tokens = stripped.split(None, 2)
            if len(tokens) >= 2:
                key = tokens[1].strip('"').lower()
                results.append((key, stripped, section_name))
    return results


def check_bind_conflicts(sections: Dict[str, str]) -> List[str]:
    all_binds: Dict[str, List[Tuple[str, str]]] = {}
    for name, content in sections.items():
        if not content:
            continue
        for key, line, sec in _parse_binds(name, content):
            all_binds.setdefault(key, []).append((sec, line))

    warnings = []
    for key, entries in all_binds.items():
        section_names = {e[0] for e in entries}
        if len(section_names) > 1:
            involved = ", ".join(f"{s}" for s in sorted(section_names))
            warnings.append(f"按键 '{key}' 被多个功能绑定: {involved}")
    return warnings


# ── Assembly & write ──


def compile_all(config_obj) -> Tuple[str, List[str]]:
    """Compile all sections. Returns (full_content, bind_warnings)."""
    sections = {
        "header": _compile_header(),
        "viewmodel": compile_viewmodel(config_obj),
        "magnifier_runtime": compile_magnifier_runtime(config_obj),
        "hud_rules": compile_hud_rules(config_obj),
        "footer": _compile_footer(),
    }
    warnings = check_bind_conflicts(sections)

    parts = []
    for name in SECTION_ORDER:
        text = sections.get(name, "")
        if text:
            parts.append(text)
    return "\n\n".join(parts) + "\n", warnings


def write_cs2customizer_cfg(config_obj) -> List[str]:
    """Compile and atomically write cs2customizer.cfg. Returns bind conflict warnings."""
    csgo_dir = getattr(config_obj, "csgo_dir", "") or ""
    cfg_path = get_cs2customizer_cfg_path(csgo_dir.strip())
    if not cfg_path:
        logger.warning("csgo_dir 未配置，跳过写入 cs2customizer.cfg")
        return []

    content, warnings = compile_all(config_obj)
    for w in warnings:
        logger.warning(f"[CFG冲突] {w}")

    cfg_dir = os.path.dirname(cfg_path)
    os.makedirs(cfg_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=cfg_dir, prefix="cs2customizer_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, cfg_path)
        logger.info(f"cs2customizer.cfg 已写入: {cfg_path}")
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    return warnings
