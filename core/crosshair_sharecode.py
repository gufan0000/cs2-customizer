# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""CS2 准心分享码（`CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx`）↔ CS2 Customizer 准心设置（批 130）。

编码规格按公开实现 akiver/csgo-sharecode（MIT）自己写；样例码也取自它的测试（判据里逐条对）。
- 25 个字符 = 一个 18 字节大整数的 57 进制（字母表去掉了易混的 I l 0 1 g），字符低位在前；
- byte0 = 其余 17 字节之和 & 0xFF（校验）；byte1 = 版本。
- **2026-09-23 那次 CS2 更新**把准心改成按像素：版本 1 → 3 / 4；游戏本身已不认 ≤2 的码。
  v3/v4 的 gap / length / thickness 是像素，`screen_height` 是出码那台机器的屏高。

CS2 Customizer 这边只换算「能对上的那几样」：样式（十字 / 点 / 圆 / T）、颜色、透明度、粗细、长度、间隙、描边、中心点。
跟随后坐力、动态分离那几项 CS2 Customizer 的叠加准心没有，导入时在 `notes` 里说清楚丢了什么。
"""
from __future__ import annotations

import re

ALPHABET = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789"
_PATTERN = re.compile(r"^CSGO(-?[\w]{5}){5}$")
_SPLIT_ALPHA_STEPS = 20          # 分离透明度按 0.05 一档存
_SPLIT_RATIO_STEPS = 100         # 分离尺寸比按 0.01 一档存
_OUTER_ALPHA_MIN_STEPS = 6       # 外圈透明度从 0.3（6 档）起存

#: v3/v4 的样式号（游戏设置里的下拉顺序）
STYLE_NAMES = {0: "动态十字", 1: "动态圆", 2: "动态十字（经典）", 3: "静态圆", 4: "静态十字",
               5: "静态十字（射击反馈）", 6: "只有点", 7: "动态四角", 8: "静态方框"}


class ShareCodeError(ValueError):
    """码本身不对（格式 / 校验 / 版本）。`str(e)` 是给玩家看的一句话。"""


# ---------------------------------------------------------------------------
# 字符串 ↔ 18 字节
# ---------------------------------------------------------------------------
def _to_bytes(code: str) -> list[int]:
    code = (code or "").strip()
    if not _PATTERN.match(code):
        raise ShareCodeError("这不是一个分享码（应形如 CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx）")
    body = code[4:].replace("-", "")
    n = 0
    for ch in reversed(body):
        i = ALPHABET.find(ch)
        if i < 0:
            raise ShareCodeError(f"分享码里有游戏不会用的字符「{ch}」")
        n = n * len(ALPHABET) + i
    if n >= 1 << 144:
        raise ShareCodeError("分享码超出长度（抄错了几位？）")
    return list(n.to_bytes(18, "big"))


def _to_code(data: list[int]) -> str:
    n = int.from_bytes(bytes(b & 0xFF for b in data), "big")
    chars = []
    for _ in range(25):
        n, r = divmod(n, len(ALPHABET))
        chars.append(ALPHABET[r])
    s = "".join(chars)
    return "CSGO-" + "-".join(s[i:i + 5] for i in range(0, 25, 5))


def _int8(b: int) -> int:
    return b - 256 if b >= 128 else b


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


# ---------------------------------------------------------------------------
# 解码 / 编码（字段名与公开实现一致，便于对样例）
# ---------------------------------------------------------------------------
def decode(code: str) -> dict:
    b = _to_bytes(code)
    if b[0] != sum(b[1:]) % 256:
        raise ShareCodeError("这不是准心分享码，或抄错了几位（校验对不上）")
    version = b[1]
    if version == 1:
        return {
            "version": 1, "gap": _int8(b[2]) / 10, "outline": b[3] / 2,
            "red": b[4], "green": b[5], "blue": b[6], "alpha": b[7],
            "splitDistance": b[8] & 7, "followRecoil": bool((b[8] >> 4) & 8),
            "fixedCrosshairGap": _int8(b[9]) / 10, "color": b[10] & 7, "outlineEnabled": bool(b[10] & 8),
            "innerSplitAlpha": (b[10] >> 4) / 10, "outerSplitAlpha": (b[11] & 0xF) / 10,
            "splitSizeRatio": (b[11] >> 4) / 10, "thickness": b[12] / 10,
            "centerDotEnabled": bool((b[13] >> 4) & 1), "deployedWeaponGapEnabled": bool((b[13] >> 4) & 2),
            "alphaEnabled": bool((b[13] >> 4) & 4), "tStyleEnabled": bool((b[13] >> 4) & 8),
            "style": (b[13] & 0xF) >> 1, "length": b[14] / 10,
        }
    if version not in (3, 4):
        raise ShareCodeError(f"不认识的准心分享码版本（{version}）")
    bits = b[10] | (b[11] << 8) | (b[12] << 16) | (b[13] << 24)
    out = {
        "version": version, "style": b[2] & 0xF, "followRecoil": bool(b[2] & 0x10),
        "centerDotEnabled": bool(b[2] & 0x40), "tStyleEnabled": bool(b[2] & 0x80),
        "red": b[3], "green": b[4], "blue": b[5], "alpha": b[6],
        "gap": b[7], "length": b[8], "dynamicSpreadLimit": b[9],
        "splitDistance": bits & 0x7F,
        "innerSplitAlpha": ((bits >> 7) & 0x1F) / _SPLIT_ALPHA_STEPS,
        "outerSplitAlpha": (((bits >> 12) & 0xF) + _OUTER_ALPHA_MIN_STEPS) / _SPLIT_ALPHA_STEPS,
        "splitSizeRatio": ((bits >> 16) & 0x7F) / _SPLIT_RATIO_STEPS,
        "thickness": (bits >> 23) & 0x1F,
        "screenHeight": b[14] | (b[15] << 8),
    }
    if version == 3:
        out["outlineEnabled"] = bool(b[2] & 0x20)
    else:
        out["outlineMode"] = (b[13] >> 4) & 3
    return out


def encode(xh: dict) -> str:
    """只出 v3 / v4（游戏现在只认这两种）。"""
    version = int(xh.get("version", 4))
    if version not in (3, 4):
        raise ShareCodeError("只能生成 v3 / v4 的准心分享码")
    inner = round(_clamp(xh.get("innerSplitAlpha", 1.0), 0, 1) * _SPLIT_ALPHA_STEPS)
    outer = round(_clamp(xh.get("outerSplitAlpha", 0.3), 0.3, 1) * _SPLIT_ALPHA_STEPS) - _OUTER_ALPHA_MIN_STEPS
    ratio = round(_clamp(xh.get("splitSizeRatio", 0.0), 0, 1) * _SPLIT_RATIO_STEPS)
    bits = (int(_clamp(xh.get("splitDistance", 0), 0, 127)) | (inner << 7) | (outer << 12) | (ratio << 16)
            | (int(_clamp(xh.get("thickness", 1), 0, 31)) << 23))
    h = int(_clamp(xh.get("screenHeight", 0), 0, 65535))
    max_style = 7 if version == 3 else 8
    b2 = (int(_clamp(xh.get("style", 4), 0, max_style)) | (bool(xh.get("followRecoil")) << 4)
          | (bool(xh.get("centerDotEnabled")) << 6) | (bool(xh.get("tStyleEnabled")) << 7))
    data = [0, version, b2] + [int(_clamp(xh.get(k, d), 0, 255)) for k, d in
                               (("red", 0), ("green", 255), ("blue", 0), ("alpha", 255),
                                ("gap", 0), ("length", 0), ("dynamicSpreadLimit", 255))]
    data += [bits & 0xFF, (bits >> 8) & 0xFF, (bits >> 16) & 0xFF, (bits >> 24) & 0xFF, h & 0xFF, h >> 8, 0, 0]
    if version == 3:
        data[2] |= bool(xh.get("outlineEnabled")) << 5
    else:
        data[13] |= int(_clamp(xh.get("outlineMode", 0), 0, 2)) << 4
    data[0] = sum(data) & 0xFF
    return _to_code(data)


# ---------------------------------------------------------------------------
# 和 CS2 Customizer 准心设置互转
# ---------------------------------------------------------------------------
_DOT_STYLES = {6}
_CIRCLE_STYLES = {1, 3}


def _scale(screen_height: int, target_height: int) -> float:
    return (target_height / screen_height) if screen_height and target_height else 1.0


def to_cs2customizer(code: str, target_height: int = 0) -> tuple[dict, list[str]]:
    """分享码 → CS2 Customizer 配置键（只含要改的那些）+ 给玩家看的「丢了什么」说明。

    `target_height`：这台机器游戏所在屏的高（像素）；码里记的出码屏高不同时按比例缩放（同游戏的做法）。"""
    xh = decode(code)
    if xh["version"] == 1:
        raise ShareCodeError("这是 9 月 23 日 CS2 更新之前的旧分享码，游戏已经不认了；请在游戏里重新导出一次再粘贴")
    notes: list[str] = []
    k = _scale(xh["screenHeight"], target_height)
    style_no = xh["style"]
    if style_no in _DOT_STYLES:
        style = "dot"
    elif style_no in _CIRCLE_STYLES:
        style = "circle"
    elif xh["tStyleEnabled"]:
        style = "t_shape"
    else:
        style = "crosshair"
    if style_no in (0, 1, 2, 5, 7):
        notes.append(f"游戏里是「{STYLE_NAMES.get(style_no, style_no)}」； CS2 Customizer 的叠加准心不会随开枪扩散，按静止时的样子画")
    if style_no == 8:
        notes.append("「静态方框」 CS2 Customizer 没有，按十字画")
    if xh["followRecoil"]:
        notes.append("「跟随后坐力」 CS2 Customizer 的叠加准心做不到（它固定在屏幕中心）")
    thick = max(1, round(xh["thickness"] * k))
    gap = max(0, round(xh["gap"] * k))
    length = max(1, round(xh["length"] * k))
    outline = (xh.get("outlineMode", 0) if xh["version"] == 4 else int(xh.get("outlineEnabled", False)))
    if outline == 2:
        notes.append("「半描边」 CS2 Customizer 没有，按全描边画")
    cfg = {
        "crosshair_style": style,
        "crosshair_color_custom": "#{:02X}{:02X}{:02X}".format(xh["red"], xh["green"], xh["blue"]),
        "crosshair_alpha": int(xh["alpha"]),
        "crosshair_thickness": thick,
        "crosshair_gap": gap,
        "crosshair_size": 2 * (gap + length),
        "crosshair_outline": 1 if outline else 0,
        "crosshair_dot": bool(xh["centerDotEnabled"]) and style != "dot",
    }
    if k != 1.0:
        notes.append(f"码是在 {xh['screenHeight']} 像素高的屏上做的，已按你的屏（{target_height}）等比缩放")
    return cfg, notes


def from_cs2customizer(cfg, screen_height: int = 0) -> str:
    """CS2 Customizer 当前准心 → v4 分享码。`cfg` 是 config 对象或同名键的 dict。"""
    get = (cfg.get if isinstance(cfg, dict) else lambda k, d=None: getattr(cfg, k, d))
    style = get("crosshair_style", "crosshair")
    if style == "custom":
        raise ShareCodeError("自绘像素的准心没法变成游戏分享码（游戏只认十字 / 点 / 圆）")
    from crosshair_overlay import resolve_color   # 名字色 / #RRGGBB 的唯一解析处

    alpha = int(get("crosshair_alpha", 255) or 255)
    c = resolve_color(get("crosshair_color_custom", "") or get("crosshair_color", "green"), alpha)
    size = int(get("crosshair_size", 20) or 20)
    gap = int(get("crosshair_gap", 0) or 0)
    xh = {
        "version": 4,
        "style": {"dot": 6, "circle": 3}.get(style, 4),
        "tStyleEnabled": style == "t_shape",
        "centerDotEnabled": bool(get("crosshair_dot", False)),
        "followRecoil": False,
        "red": c.red(), "green": c.green(), "blue": c.blue(), "alpha": alpha,
        "gap": gap, "length": max(0, size // 2 - gap),
        "thickness": int(get("crosshair_thickness", 2) or 1),
        "outlineMode": 1 if int(get("crosshair_outline", 0) or 0) > 0 else 0,
        "dynamicSpreadLimit": 255, "splitDistance": 0, "innerSplitAlpha": 1.0,
        "outerSplitAlpha": 0.3, "splitSizeRatio": 0.0, "screenHeight": int(screen_height or 0),
    }
    return encode(xh)
