# SPDX-License-Identifier: GPL-3.0-or-later
"""准心快速回正的 CFG 语义——**全仓唯一一份**。

为什么单独开一个模块：这套语义原本抄在两个地方，而且**两边写反了**。
`core/cfg_compiler.compile_viewmodel` 输出的静息值是 `cl_crosshair_recoil 1`，
`core/hud/rule_compiler.compile_cfg_rules` 输出的是 `0`。用户开不开 HUD 运行时
刷新，会得到隐蔽性完全相反的两份 cfg —— 这不是风格差异，是有一边写错了。

## 隐蔽性靠的是什么（改这个文件前必须先懂这一条）

CS2 把"队友和 demo 看到的你的准心设置"在**对局开始那一刻**快照下来，整局不再
更新。所以只要保证 `cl_crosshair_recoil` 在**回合开始的瞬间是 0**，之后你在局内
把它开成 1，别人和录像里都看不到——而你自己是实打实生效的。

「按下开火置 1、松开置 0」这个手感设计，恰好天然满足上面这个条件：不开火的时候
永远是 0，而回合开始的瞬间你不可能在开火（冻结期开不了枪）。也就是说**隐蔽性
不需要为手感做任何妥协**，两者是同一个实现。

反过来，任何"在开火之外的地方把它置 1"的写法都会破坏隐蔽性。原来那行独立的
`cl_crosshair_recoil 1` 就是这样：exec 发生在游戏启动（autoexec）或手动 exec，
此后值一直是 1，直到你**第一次开火并松开**才变 0 —— 所以从启动游戏到首次开火
之间的每一个回合，跟随对队友和 demo 全程可见。进服先站着看局势的人会连暴露好几局。

`tests/test_crosshair_reset_cfg.py` 盯着这件事：它扫描**编译产物**而不是源码，
任何"把 cl_crosshair_recoil 置 1 且不在 +开火 alias 内部"的行一律判红。这样以后
不管谁改哪条路径、加第三条路径，写出泄漏都会被逮住。

## 关闭时为什么是重定义 alias 而不是 bind 回去

CS2 退出时会把 bind 存进 config.cfg，但 **alias 不存**。所以用户一旦启用过，
`bind mouse1 +quickrepos_attack` 会长期留在他自己的 config.cfg 里。在软件里点
"关闭"如果只是不再输出这一段，那个 bind 还在，功能实际没关掉。

修法是关闭时把 alias **重定义成直通**（`alias +quickrepos_attack "+attack"`）。
比 `bind mouse1 +attack` 好在两点：
- 不去动用户的按键绑定（他可能压根没把开火放在 mouse1 上）
- 顺手治好"stale bind 指向不存在的 alias"——那种情况下开火键是个死键，开不了枪

⚠ 唯一治不了的情况是 `exec cs2customizer.cfg` 整个没跑到（autoexec 被删/换了账号）：
那时 alias 根本不存在，指向它的 bind 就是死键。cfg 内部无解，只能在文档里给
一条自救命令。
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence

#: 跟随后坐力的 convar。只有这一个地方写它的名字。
RECOIL_CVAR = "cl_crosshair_recoil"

#: 开火 alias 名。存量用户的 config.cfg 里可能已经存着指向它的 bind，
#: **改名等于把那些用户的开火键变成死键**，别改。
PRIMARY_ALIAS = "quickrepos_attack"
SECONDARY_ALIAS = "quickrepos_attack2"

#: 历史上 HUD 路径用过的另一个名字。两条路径以前各绑各的 alias，切换 HUD 开关
#: 会在用户 config.cfg 里留下指向它的 stale bind。关闭态一并定义成直通把它治好。
LEGACY_ALIASES = ("fp_hud_mouse1",)

DEFAULT_ATTACK_KEY = "mouse1"
DEFAULT_SECONDARY_KEY = "mouse2"


#: 绝大多数可绑按键的名字：mouse1 / mwheelup / kp_enter / F1 / a / 5 / uparrow…
_PLAIN_KEY = re.compile(r"^[A-Za-z0-9_]+$")
#: 标点类按键（CS2 里这些都能绑），只允许**单个字符**
_PUNCT_KEYS = frozenset("[]\\',.-=`/")


def _sanitize_key(key: str, fallback: str) -> str:
    """按键必须是单个合法 token，**不合法就退回默认值，绝不"清洗后凑合用"**。

    以前的写法是把引号/分号删掉再拼回去。`mouse1"; quit; //` 会被清成
    `mouse1quit//` —— 分号没了所以不会执行 quit，看着像"防住了"，但 `//` 在
    cfg 里是行注释：`bind mouse1quit// +quickrepos_attack` 等于**把自己这行
    注释掉**，开火键静默没绑上。清洗产生的是一个语法合法、语义错误的键名，
    比直接拒绝危险得多。
    """
    token = str(key or "").strip()
    if _PLAIN_KEY.match(token):
        return token
    if len(token) == 1 and token in _PUNCT_KEYS:
        return token
    return fallback


def resolve_attack_key(config_obj) -> str:
    return _sanitize_key(
        getattr(config_obj, "crosshair_reset_attack_key", DEFAULT_ATTACK_KEY),
        DEFAULT_ATTACK_KEY,
    )


def resolve_secondary_key(config_obj) -> str:
    return _sanitize_key(
        getattr(config_obj, "crosshair_reset_secondary_key", DEFAULT_SECONDARY_KEY),
        DEFAULT_SECONDARY_KEY,
    )


def secondary_enabled(config_obj) -> bool:
    return bool(getattr(config_obj, "crosshair_reset_secondary_enabled", False))


def _alias(name: str, action: str, recoil_value, extras: Sequence[str]) -> str:
    parts = [action]
    if recoil_value is not None:
        parts.append(f"{RECOIL_CVAR} {recoil_value}")
    parts.extend(e for e in extras if e)
    return f'alias {name} "{"; ".join(parts)}"'


def build_attack_alias_lines(
    config_obj,
    *,
    recoil: bool,
    extra_press: Iterable[str] = (),
    extra_release: Iterable[str] = (),
    emit_bind: bool = True,
) -> List[str]:
    """开火键 alias 的**唯一**生成入口。

    `recoil=True`  → 带回正层：按下置 1、松开置 0，并写死静息值 0。
    `recoil=False` → 直通：只有 `+attack`/`-attack`（加上 extras）。
                     既用于"功能关闭时修复残留 bind"，也用于"HUD 要搭车刷新但
                     用户没开回正"——这两种情况要输出的东西逐字相同。

    `extra_press` / `extra_release` 给 HUD 路径塞 `exec cs2customizer_hud_runtime.cfg`。
    做成参数而不是让 HUD 路径自己抄一遍 alias，是这个模块存在的全部理由。
    """
    press_extras = tuple(extra_press)
    release_extras = tuple(extra_release)
    lines: List[str] = []

    if recoil:
        # 静息值必须是 0：回合开始那一刻别人快照到的就是这个值。
        # ⚠ 这里**永远不能**写 1，见模块 docstring。
        lines.append(f"{RECOIL_CVAR} 0")

    lines.append(_alias(f"+{PRIMARY_ALIAS}", "+attack", 1 if recoil else None, press_extras))
    lines.append(_alias(f"-{PRIMARY_ALIAS}", "-attack", 0 if recoil else None, release_extras))

    if emit_bind:
        lines.append(f"bind {resolve_attack_key(config_obj)} +{PRIMARY_ALIAS}")

    if recoil and secondary_enabled(config_obj):
        # 副开火（R8 左轮的右键是真开火）。默认关：CFG 没有计数器，两个键同时
        # 按住时先松开的那个会把值提前清成 0。实战里"边喷边点右键"不是打法，
        # 所以代价可接受，但别默认替用户开。
        lines.append(_alias(f"+{SECONDARY_ALIAS}", "+attack2", 1, press_extras))
        lines.append(_alias(f"-{SECONDARY_ALIAS}", "-attack2", 0, release_extras))
        lines.append(f"bind {resolve_secondary_key(config_obj)} +{SECONDARY_ALIAS}")
    else:
        # 副开火没开（或整个功能关着）时把它摊平，否则上次启用留下的 mouse2
        # bind 还带着回正层。**不输出 cl_crosshair_recoil 的任何取值**——关掉
        # 本功能不代表用户想把这个 convar 设成 0，有人就是喜欢全程跟随，
        # 我们只撤自己加的那层。
        lines.append(_alias(f"+{SECONDARY_ALIAS}", "+attack2", None, ()))
        lines.append(_alias(f"-{SECONDARY_ALIAS}", "-attack2", None, ()))

    # 老 alias 名一律定义成直通，**两个分支都发**。
    # 用户 config.cfg 里可能存着 `bind mouse1 +fp_hud_mouse1`（老版本 HUD 路径
    # 绑的名字）。我们下面那条 bind 会覆盖它，所以正常情况用不上这两行；
    # 但万一覆盖没生效，有定义就只是"少了回正"，没定义就是**开火键变死键**。
    # 两行的代价换掉一整类"点了开不了枪"，值。
    for legacy in LEGACY_ALIASES:
        lines.append(_alias(f"+{legacy}", "+attack", None, press_extras))
        lines.append(_alias(f"-{legacy}", "-attack", None, release_extras))

    return lines


# ---------------------------------------------------------------------------
# 谁把我们的 alias 抢走了（2026-08-18，用户实录）
# ---------------------------------------------------------------------------
#
# 用户报「准星跟随没效果」，查下来根因不在本仓：他的 `autoexec.cfg` 是
#
#     exec cs2customizer.cfg          ← 我们
#     exec FastShoot/setup
#     exec cs2customizer.cfg   ← 开源版 CS2 Customizer ，**最后执行**
#
# 而 `cs2customizer.cfg` 里有一模一样的
# `alias +quickrepos_attack "+attack; exec cs2customizer_hud_runtime.cfg"`
# —— 全文 `cl_crosshair_recoil` 出现 **0 次**（开源版是功能子集，没这个功能）。
# 同名 alias，**后 exec 的赢**，于是我们那两行被原样覆盖，功能静默死掉、零报错。
#
# ⭐ 要害：**开源版是从本仓裁出来的，两个产品共用同一套 alias 名字空间。**
# 而上面写着 `PRIMARY_ALIAS` 改名等于把存量用户的开火键变成死键 ——
# **这个碰撞不能靠改名躲过去**，只能靠 ① 保证我们最后 exec ② 检测到就说出来。
#
# 同一类风险对任何第三方 cfg 工具都成立（这台机器上还有 FastShoot / f5e）。

#: 我们会定义、因而可能被别人重定义的全部 alias 名。
OWNED_ALIASES = (PRIMARY_ALIAS, SECONDARY_ALIAS, *LEGACY_ALIASES)

_EXEC_RE = re.compile(r"^\s*exec\s+([^\s/;]+(?:/[^\s;]+)?)", re.I | re.M)


def exec_order(autoexec_text: str) -> List[str]:
    """按出现顺序列出 `autoexec.cfg` 里 exec 的目标（去掉 .cfg 后缀）。"""
    out = []
    for raw in _EXEC_RE.findall(autoexec_text or ""):
        name = raw.strip().strip('"').strip("'")
        if name.lower().endswith(".cfg"):
            name = name[:-4]
        out.append(name)
    return out


def _defines_our_alias(text: str) -> List[str]:
    hits = []
    for name in OWNED_ALIASES:
        # `alias +quickrepos_attack ...` / `alias "-quickrepos_attack" ...`
        if re.search(rf'^\s*alias\s+"?[+-]{re.escape(name)}"?\s', text or "", re.I | re.M):
            hits.append(name)
    return hits


def find_alias_overriders(autoexec_text: str, read_cfg, our_cfg: str = "cs2customizer") -> List[dict]:
    """找出**排在我们后面**、且重定义了我们 alias 的 cfg。

    `read_cfg(name)` 由调用方提供：给 cfg 名（不带后缀），返回文本或 None。
    这样本模块不碰文件系统，判据可以直接喂字典进来。

    返回 `[{"cfg": 名字, "aliases": [被抢的 alias]}]`，**顺序即 exec 顺序**。
    列表非空 = 我们那份准心回正语义在游戏里是死的。
    """
    order = exec_order(autoexec_text)
    if our_cfg not in order:
        return []
    after = order[order.index(our_cfg) + 1:]
    found = []
    for name in after:
        if name == our_cfg:
            continue
        stolen = _defines_our_alias(read_cfg(name) or "")
        if stolen:
            found.append({"cfg": name, "aliases": stolen})
    return found


#: 挪动之后留下的印记。**它同时是"我已经挪过一次了"的持久记录**——
#: 存在 autoexec 自己身上，而不是软件配置里：换配置目录、重装、甚至换一台
#: 机器复制 cfg 过去，这个事实都跟着文件走，而它约束的本来就是这个文件。
MOVED_MARK = "CS2C-AUTOEXEC-ORDERED"


def rewrite_autoexec_with_us_last(autoexec_text: str, our_cfg: str = "cs2customizer") -> str:
    """把 `exec cs2customizer.cfg` 挪到所有 exec 的**最后**，其余内容一字不动。

    只在我们确实不是最后一个 exec 时才改；已经在最后就原样返回
    （**别每次启动都重写用户的文件**）。

    ⚠ **RN-099：最多只挪一次。** 2026-08-19 实测到的事故——
    这段代码同步到开源版之后，**两个产品都会"把自己挪到最后"**，
    于是谁最后启动谁赢，两边**永久互相争抢最后一位**，每次启动都静默改用户的文件。
    我给 RN-095 写这条时只想着"要排在别人后面"，完全没想到**别人就是我们
    自己的另一个产品，跑的还是同一份代码**。

    ⭐ 这是 RN-095 那条教训只修了一半的证据：**alias 名字空间共用**这件事我认了，
    但**"抢最后一位"这个策略也被共用了**这件事没认。
    ⇒ 凡是往共享资源里写"我要占据某个唯一位置"的逻辑，都要先问一句：
      **如果对面跑的是同一份代码，会发生什么？**

    收敛规则：挪的时候留下 `MOVED_MARK` 印记；再看到自己不是最后一位时**不再挪**，
    改为把冲突说出来（由 `cfg_utils.ensure_cs2customizer_exec_is_last` 记日志）。
    这样每个产品最多挪一次，局面必定收敛——代价是"谁最后挪谁赢"，
    但那比无限翻转好得多，而且用户能从日志里看到该自己删哪一行。
    """
    order = exec_order(autoexec_text)
    if our_cfg not in order or order[-1] == our_cfg:
        return autoexec_text
    if MOVED_MARK in (autoexec_text or ""):
        return autoexec_text        # 已经挪过一次，不参与抢位（RN-099）

    ours = re.compile(rf'^\s*exec\s+"?{re.escape(our_cfg)}(?:\.cfg)?"?\s*$', re.I)
    kept = [ln for ln in (autoexec_text or "").splitlines() if not ours.match(ln)]
    while kept and not kept[-1].strip():
        kept.pop()
    kept.append("")
    kept.append(f"// CS2 Customizer ：本行必须排在其他 exec 之后 —— 同名 alias 后执行的生效 [{MOVED_MARK}]")
    kept.append("// ⚠ 只会自动挪这一次。之后若又有别的 cfg 排到后面，软件只会在日志里提醒，")
    kept.append("//   不再改这个文件 —— 否则两个都会挪的程序会永久互相抢最后一位（RN-099）。")
    kept.append(f"exec {our_cfg}.cfg")
    return "\n".join(kept) + "\n"
