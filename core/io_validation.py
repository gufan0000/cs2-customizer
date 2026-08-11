# -*- coding: utf-8 -*-
"""用户导入文件的校验(2026-06-13)。

对标 .fanpai 分享文件已有的"安全红线"，把同一套严谨度推广到其它导入：
JSON 导入限大小、校验顶层类型、逐字段校验类型再赋值(防损坏/恶意文件污染配置
或 OOM)；音频导入限大小并拒绝明显的非音频(可执行/压缩包等改名文件)。
纯逻辑、无 Qt 依赖，便于单测。
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

MAX_IMPORT_JSON_BYTES = 2 * 1024 * 1024        # 配置类 JSON 上限 2MB
MAX_AUDIO_IMPORT_BYTES = 64 * 1024 * 1024      # 单个音频导入上限 64MB

# 明显非音频的文件头(可执行/压缩包/文档/脚本)——命中即拒，避免改名文件混入资源目录。
# 用"拒绝已知坏"而非"要求已知好",防止误杀编码冷门但合法的音频。
_NON_AUDIO_MAGICS: Tuple[bytes, ...] = (
    b"MZ",            # Windows PE 可执行
    b"\x7fELF",       # ELF 可执行
    b"PK\x03\x04",    # zip/jar/office
    b"PK\x05\x06",    # 空 zip
    b"Rar!",          # rar
    b"%PDF",          # pdf
    b"\xca\xfe\xba\xbe",  # Mach-O / java class
    b"<!DO",          # html
    b"<htm",
    b"#!",            # 脚本 shebang
)


def load_json_checked(path: str, max_bytes: int = MAX_IMPORT_JSON_BYTES) -> Dict:
    """读取并基本校验 JSON：限大小 + 顶层必须是对象。失败抛 ValueError。"""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError(f"无法读取文件: {exc}") from exc
    if size > max_bytes:
        raise ValueError(f"文件过大({size} 字节,上限 {max_bytes})")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("文件内容不是 JSON 对象")
    return data


def validate_voice_config(data: Dict) -> Tuple[bool, Dict, List[str]]:
    """校验语音输出导入配置。返回 (ok, 已清洗的config键值, 错误列表)。
    只接受类型正确的字段；出现任何类型错误即整份拒绝(ok=False)。"""
    errors: List[str] = []
    cleaned: Dict = {}
    if not isinstance(data, dict):
        return False, {}, ["配置文件格式不正确(应为 JSON 对象)"]

    if "slots" in data:
        if isinstance(data["slots"], (list, dict)):
            cleaned["voice_output_slots"] = data["slots"]
        else:
            errors.append("slots 字段类型不正确")
    for key, cfg_key in (
        ("stop_key", "voice_output_stop_key"),
        ("ptt_key", "voice_output_ptt_key"),
        ("mode", "voice_output_mode"),
    ):
        if key in data:
            if isinstance(data[key], str):
                cleaned[cfg_key] = data[key]
            else:
                errors.append(f"{key} 字段应为字符串")
    if "ptt_enabled" in data:
        if isinstance(data["ptt_enabled"], bool):
            cleaned["voice_output_ptt_enabled"] = data["ptt_enabled"]
        else:
            errors.append("ptt_enabled 字段应为布尔值")
    if "volume" in data:
        v = data["volume"]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cleaned["voice_output_volume"] = float(v)
        else:
            errors.append("volume 字段应为数字")

    if errors:
        return False, {}, errors
    if not cleaned:
        return False, {}, ["没有可导入的有效字段"]
    return True, cleaned, []


def validate_crosshair_import(data: Dict) -> Tuple[bool, Dict, List[str]]:
    """校验准心导入文件。返回 (ok, 已清洗的config键值, 错误列表)。"""
    if not isinstance(data, dict):
        return False, {}, ["文件格式不正确(应为 JSON 对象)"]
    if "crosshair_data" not in data:
        return False, {}, ["缺少 crosshair_data 字段"]
    cd = data["crosshair_data"]
    if not isinstance(cd, (list, dict, str)):
        return False, {}, ["crosshair_data 字段类型不正确"]
    return True, {"crosshair_custom_data": cd}, []


def audio_import_rejection_reason(
    path: str, max_bytes: int = MAX_AUDIO_IMPORT_BYTES
) -> Optional[str]:
    """音频导入的安全闸：超大或明显非音频则返回拒绝原因；可导入返回 None。"""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return f"无法读取文件: {exc}"
    if size > max_bytes:
        return f"文件过大({size // 1024 // 1024}MB,上限 {max_bytes // 1024 // 1024}MB)"
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError as exc:
        return f"无法读取文件: {exc}"
    for magic in _NON_AUDIO_MAGICS:
        if head.startswith(magic):
            return "不是音频文件(疑似可执行文件/压缩包等改名)"
    return None
