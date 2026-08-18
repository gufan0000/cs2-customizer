# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""全局热键注册中心（P2.1，2026-06-10）。

背景：此前开镜放大 / 语音输出音板 / 道具瞄点 / 枪声兜底 四个功能域各自直接
调用 keyboard / mouse 库（≥8 个注册点），互相不知道对方绑了什么键——
同键双绑会双触发，音板的 suppress=True 还会全局吞键，用户无法自查。

本模块做三件事：
1. **1:1 包装**底层 keyboard/mouse 调用（语义与直接调用完全一致，零行为差异）；
2. 维护一张**全局绑定表**（谁、什么类型、哪个键、是否吞键）；
3. 提供 **find_conflicts()** 供 UI 在用户改键时给出"该键已被 XX 使用"的提示，
   以及 **list_bindings()** 供高级设置页展示总览。

设计约束：
- 线程安全（绑定可能发生在 UI 线程与工作线程）；
- 底层库 import 失败时所有 API 安全降级（注册返回 None、查询返回空）；
- 卸载支持按 token 或按 owner 批量。
"""
from __future__ import annotations

import itertools
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.utils.logger import get_logger

logger = get_logger("HotkeyRegistry")

try:
    import keyboard as _keyboard
except Exception:  # pragma: no cover - 环境缺库时降级
    _keyboard = None
try:
    import mouse as _mouse
except Exception:  # pragma: no cover
    _mouse = None

_lock = threading.RLock()
_token_seq = itertools.count(1)


def hotkeys_disabled() -> bool:
    """这个进程是否**一律不注册真实全局热键**（RN-059）。

    只由环境变量 `CS2C_NO_GLOBAL_HOTKEYS=1` 打开，**产品代码任何地方都不设它**，
    只有离屏审计/判据脚本设。

    ## 为什么需要一道显式闸门，而不是继续逐页想办法

    翻新工程的离屏工装长期把 6 个页面整个跳过（`DEVICE_OWNING_PAGES`），
    理由写的是"构造即注册全局热键、会劫持用户的鼠标右键"。
    2026-08-17 在 `keyboard` / `mouse` 库边界上架探针实测（全新隔离配置）：

        flash / viewmodel / voice_output / music / magnifier / kill_icon
        —— 六页**全部**：新增热键绑定 0 条、库调用 0 次、可见窗口 0 个

    因为热键是按**用户配置里已有的绑定**注册的，而隔离配置里什么都没有。
    ⇒ 那条理由在离屏场景下**基本不成立**，代价是 `flash`(1507 行) /
      `viewmodel`(823) / `voice_output`(1935) 三页被全部 5 支脚本跳过，
      **合计 4265 行界面从来没有排版审计、没有指纹基线、没有截图、没有焦点巡检**。

    但"实测这一次没注册"不等于"以后也不会"——只要审计跑在一份**有**绑定的配置上
    就会真注册。所以这里不靠推理，给一个**保证**：闸门一开，
    `register_*` 一律只记账不挂钩，`list_bindings()` 照常能查（UI 冲突提示不受影响）。

    ⚠ **故意不复用 `CS2C_SAFE_MODE_ACTIVE`**：那个变量在**真实运行**里也会被
    `main_widget` 打开（上次原生崩溃后的兼容模式），而那种情况下热键必须照常工作。
    复用它等于给真实用户偷偷关掉音板热键。
    """
    return os.environ.get("CS2C_NO_GLOBAL_HOTKEYS") == "1"


@dataclass
class _Binding:
    token: int
    owner: str
    kind: str          # "key" / "hook" / "mouse" / "interest"
    key: str           # 标准化键名；hook 用 "*"；interest 可多条逐键展开
    suppress: bool
    note: str = ""
    handles: List[Any] = field(default_factory=list)  # (lib, handle) 对


_bindings: Dict[int, _Binding] = {}


def _norm_key(key) -> str:
    return str(key or "").strip().lower()


def _new_token() -> int:
    return next(_token_seq)


def register_key(
    owner: str,
    key: str,
    on_press: Optional[Callable] = None,
    on_release: Optional[Callable] = None,
    note: str = "",
) -> Optional[int]:
    """注册具体按键（等价 keyboard.on_press_key / on_release_key）。"""
    if hotkeys_disabled():
        # RN-059：闸门开着 —— 只记账，不向 keyboard/mouse 挂任何钩子。
        with _lock:
            token = _new_token()
            _bindings[token] = _Binding(
                token, str(owner), "key", _norm_key(key), False,
                (note or "") + "（审计模式：未真正挂钩）", [])
        return token
    if _keyboard is None:
        logger.warning("keyboard 库不可用，register_key 跳过")
        return None
    nkey = _norm_key(key)
    if not nkey:
        return None
    handles: List[Any] = []
    try:
        if on_press is not None:
            handles.append(("kb", _keyboard.on_press_key(nkey, on_press)))
        if on_release is not None:
            handles.append(("kb", _keyboard.on_release_key(nkey, on_release)))
    except Exception:
        # 回滚已挂的一半
        for lib, h in handles:
            try:
                _keyboard.unhook(h)
            except Exception:
                pass
        logger.exception(f"register_key 失败: {owner} / {nkey}")
        return None
    with _lock:
        token = _new_token()
        _bindings[token] = _Binding(token, str(owner), "key", nkey, False, note, handles)
    logger.debug(f"热键注册: {owner} key={nkey}")
    return token


def register_hotkey(
    owner: str,
    hotkey: str,
    callback: Callable,
    suppress: bool = False,
    note: str = "",
) -> Optional[int]:
    """注册组合热键（等价 keyboard.add_hotkey，支持 'ctrl+alt+x' 形式）。"""
    if hotkeys_disabled():
        # RN-059：闸门开着 —— 只记账，不向 keyboard/mouse 挂任何钩子。
        with _lock:
            token = _new_token()
            _bindings[token] = _Binding(
                token, str(owner), "hotkey", _norm_key(hotkey), bool(suppress),
                (note or "") + "（审计模式：未真正挂钩）", [])
        return token
    if _keyboard is None:
        logger.warning("keyboard 库不可用，register_hotkey 跳过")
        return None
    nkey = _norm_key(hotkey)
    if not nkey:
        return None
    try:
        handle = _keyboard.add_hotkey(nkey, callback, suppress=bool(suppress))
    except Exception:
        logger.exception(f"register_hotkey 失败: {owner} / {nkey}")
        return None
    with _lock:
        token = _new_token()
        _bindings[token] = _Binding(token, str(owner), "hotkey", nkey, bool(suppress), note, [("kb_hotkey", handle)])
    logger.debug(f"组合热键注册: {owner} hotkey={nkey} suppress={suppress}")
    return token


def register_hook(
    owner: str,
    callback: Callable,
    suppress: bool = False,
    interest_keys: Iterable[str] = (),
    note: str = "",
) -> Optional[int]:
    """注册全键盘 hook（等价 keyboard.hook）。

    interest_keys: hook 内部真正关心的键（仅用于冲突检测/总览，可空）。
    """
    if hotkeys_disabled():
        # RN-059：闸门开着 —— 只记账，不向 keyboard/mouse 挂任何钩子。
        with _lock:
            token = _new_token()
            _bindings[token] = _Binding(
                token, str(owner), "hook", "*", bool(suppress),
                (note or "") + "（审计模式：未真正挂钩）", [])
        return token
    if _keyboard is None:
        logger.warning("keyboard 库不可用，register_hook 跳过")
        return None
    try:
        handle = _keyboard.hook(callback, suppress=bool(suppress))
    except Exception:
        logger.exception(f"register_hook 失败: {owner}")
        return None
    keys = ",".join(sorted({_norm_key(k) for k in interest_keys if _norm_key(k)})) or "*"
    with _lock:
        token = _new_token()
        _bindings[token] = _Binding(token, str(owner), "hook", keys, bool(suppress), note, [("kb", handle)])
    logger.debug(f"键盘hook注册: {owner} keys={keys} suppress={suppress}")
    return token


def register_mouse(
    owner: str,
    button: str,
    on_press: Optional[Callable] = None,
    on_release: Optional[Callable] = None,
    note: str = "",
) -> Optional[int]:
    """注册鼠标按键（等价 mouse.on_button down/up）。"""
    if hotkeys_disabled():
        # RN-059：闸门开着 —— 只记账，不向 keyboard/mouse 挂任何钩子。
        with _lock:
            token = _new_token()
            _bindings[token] = _Binding(
                token, str(owner), "mouse", f"mouse:{_norm_key(button)}", False,
                (note or "") + "（审计模式：未真正挂钩）", [])
        return token
    if _mouse is None:
        logger.warning("mouse 库不可用，register_mouse 跳过")
        return None
    nbtn = _norm_key(button)
    if not nbtn:
        return None
    handles: List[Any] = []
    try:
        if on_press is not None:
            handles.append(("ms", _mouse.on_button(on_press, buttons=(nbtn,), types=("down",))))
        if on_release is not None:
            handles.append(("ms", _mouse.on_button(on_release, buttons=(nbtn,), types=("up",))))
    except Exception:
        for lib, h in handles:
            try:
                _mouse.unhook(h)
            except Exception:
                pass
        logger.exception(f"register_mouse 失败: {owner} / {nbtn}")
        return None
    with _lock:
        token = _new_token()
        _bindings[token] = _Binding(token, str(owner), "mouse", f"mouse:{nbtn}", False, note, handles)
    logger.debug(f"鼠标键注册: {owner} button={nbtn}")
    return token


def declare_interest(owner: str, keys: Iterable[str], note: str = "") -> Optional[int]:
    """仅声明关心的键（不挂任何底层钩子），用于冲突检测与总览。

    适用于"已有一个大 hook、内部自行判键"的功能域更新键位时同步注册表。
    """
    norm = sorted({_norm_key(k) for k in keys if _norm_key(k)})
    if not norm:
        return None
    with _lock:
        token = _new_token()
        _bindings[token] = _Binding(token, str(owner), "interest", ",".join(norm), False, note, [])
    return token


def unregister(token: Optional[int]) -> None:
    if token is None:
        return
    with _lock:
        binding = _bindings.pop(int(token), None)
    if not binding:
        return
    for lib, handle in binding.handles:
        try:
            if lib == "kb" and _keyboard is not None:
                _keyboard.unhook(handle)
            elif lib == "kb_hotkey" and _keyboard is not None:
                _keyboard.remove_hotkey(handle)
            elif lib == "ms" and _mouse is not None:
                _mouse.unhook(handle)
        except Exception:
            # unhook 失败常见于库已整体 unhook_all，安全忽略
            pass
    logger.debug(f"热键注销: {binding.owner} {binding.kind}={binding.key}")


def unregister_owner(owner: str) -> int:
    """注销某 owner 的全部绑定，返回数量。"""
    with _lock:
        tokens = [t for t, b in _bindings.items() if b.owner == str(owner)]
    for t in tokens:
        unregister(t)
    return len(tokens)


# 修饰键不参与组合键的构成键匹配：否则 ctrl+a 与 ctrl+b 会在 ctrl 上误报冲突
_MODIFIER_KEYS = {
    "ctrl", "alt", "shift", "windows", "win",
    "left ctrl", "right ctrl", "left alt", "right alt", "left shift", "right shift",
}

# 游戏常用键：被 suppress 会破坏游戏操作，绝不能拦截——
#  · 修饰键(ctrl/shift/alt)被 keyboard 库扣住等组合判定，导致该键"按下要过一会才生效"(全局延迟)
#  · 移动/动作键(wasd/space/e/r…)被吞则游戏里按了没反应
# CS 默认键位为准，覆盖绝大多数实战操作。
_GAME_CRITICAL_KEYS = {
    # 修饰键（延迟元凶）
    "ctrl", "alt", "shift", "win", "windows",
    "left ctrl", "right ctrl", "left alt", "right alt", "left shift", "right shift",
    # 移动
    "w", "a", "s", "d", "space",
    # 高频动作
    "e", "r", "q", "f", "g", "c", "v", "b", "x", "z", "t", "tab", "enter",
    # 武器槽
    "1", "2", "3", "4", "5", "6", "7",
}


def hotkey_has_game_critical_key(hotkey: str) -> bool:
    """热键是否包含游戏常用键。这类热键不应以 suppress 方式注册——
    修饰键会被扣住产生按键延迟，移动/动作键会被吞导致游戏内按了没反应。"""
    nkey = _norm_key(hotkey) or ""
    parts = [p.strip() for p in nkey.split("+") if p.strip()]
    return any(p in _GAME_CRITICAL_KEYS for p in parts)


def _expand_combo(key: str) -> List[str]:
    """组合热键（ctrl+alt+x）额外拆出非修饰构成键参与冲突匹配：
    否则查询单键 x 时匹配不到 "ctrl+alt+x" 整串，组合与单键冲突漏报。"""
    keys = [key]
    if "+" in key:
        keys.extend(part for part in key.split("+") if part and part not in _MODIFIER_KEYS)
    return keys


def _binding_keys(binding: _Binding) -> List[str]:
    if binding.kind == "hook" and binding.key == "*":
        return []
    keys: List[str] = []
    for k in binding.key.split(","):
        if not k or k == "*":
            continue
        keys.extend(_expand_combo(k))
    return keys


def _query_keys(key: str) -> List[str]:
    nkey = _norm_key(key)
    if not nkey:
        return []
    return _expand_combo(nkey)


def find_conflicts(key: str, exclude_owner: str = "") -> List[str]:
    """查询某键被哪些其他功能域占用（含 interest 声明）。返回去重 owner 列表。

    组合键按构成键匹配：查询 "ctrl+alt+x" 会与已占用 "x" 的功能域报冲突，反之亦然。
    """
    query = _query_keys(key)
    if not query:
        return []
    owners: List[str] = []
    with _lock:
        for b in _bindings.values():
            if exclude_owner and b.owner == str(exclude_owner):
                continue
            bound = _binding_keys(b)
            if any(q in bound for q in query):
                if b.owner not in owners:
                    owners.append(b.owner)
    return owners


def list_bindings() -> List[dict]:
    """当前全部绑定（总览用），按 owner 排序。"""
    with _lock:
        rows = [
            {
                "owner": b.owner,
                "kind": b.kind,
                "key": b.key,
                "suppress": b.suppress,
                "note": b.note,
            }
            for b in _bindings.values()
        ]
    return sorted(rows, key=lambda r: (r["owner"], r["kind"], r["key"]))
