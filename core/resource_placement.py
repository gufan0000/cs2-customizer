# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""用户选了类别之后，把散装文件**摆成目标结构**（2026-09-16）。

全套设计见 `docs/资源导入_设计方案_v1_20260916.md`。这一层是整个功能真正的价值：旧向导只会**原样复制**，
要求包里已经是目标形状，否则报"认不出"。

三个特例（都是"看起来一样、其实不一样"）：

| 类 | 它特殊在哪 |
|---|---|
| `death` | `audio/death/<风格>.mp3` —— **文件本身就是一个风格**，没有风格目录 |
| `round_sounds` | 中间多一层**固定**子事件（8 个），不问就不知道放哪 |
| `c4_sounds` | 三事件共用一个风格目录，靠**文件名关键词**分辨，认不出就**不响** |

⭐⭐ `death` 那条是拿真实资源目录看出来的，不是从代码推的：
`audio/death/` 下躺的是 `death1.mp3`，而隔壁 `kill_sounds/` 下是 `CF/` 这样的目录。
**同一个 `audio/` 根下两种约定**，而 `resource_catalog` 里两者的声明一模一样。

⚠ 只算路径、不碰磁盘。逃逸检查在落盘那一侧还有第二道 ——
**两道独立的检查比一道"更仔细"的强**。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from core.resource_catalog import get_resource_spec

#: 需要「这套素材叫什么名字」的类：目标结构里有一层 `<风格>`。
#:
#: ⚠⚠ 这张表**手验逮到过一次漏**：第一版只列了单层那几类，
#:   把 `gun_sounds` 这种「`<武器>/<风格>/文件`」的漏在外面 ⇒ 摆出来是
#:   `gun_sounds/ak47/AK47.wav`，**少了风格那一层**，页面上一个风格都读不到。
#: ⭐ 带 bucket 不等于不带风格 —— 那五类是 **bucket + 风格两层都有**。
#: ⇒ 现在按「除了三个例外，全都要风格名」来写，例外逐个写明理由：
#:   `death`（平铺，文件即风格）、`crosshair`（平铺文件）、
#:   `utility_guides`（`<地图>/<分组>/`，两层都不是"风格"，见 `_UNSUPPORTED_AUTO`）。
NEEDS_STYLE_NAME = (
    "kill_sounds", "kill_voices", "health_warning", "c4_sounds",
    "flash_images", "flash_audio", "round_sounds", "kill_icons",
    "gun_sounds", "switch_weapons", "reload_sounds",
    "weapon_kill_sounds", "weapon_kill_voices", "grenade_sounds",
)

#: 自动归类**不支持**的类，要老实说出来而不是摆错地方。
#: ⭐ `utility_guides` 的两层是「地图 / 分组」，靠文件名猜不出来，
#:   而猜错了用户是在游戏里才发现的。⇒ 引导他手动放，别假装能自动。
_UNSUPPORTED_AUTO = {
    "utility_guides": "道具瞄点按「地图 / 分组」两层存放，这两层没法从文件名看出来。"
                      "请点「打开资源目录」，按 `utility_guides/<地图>/<分组>/` 自己放一次。",
    "crosshair": "准心文件直接放在 `crosshair/` 下即可，不需要归类。",
}

#: 需要「这是哪把武器 / 哪种投掷物 / 哪个回合事件」的类：目标结构里还有一层分类。
#: ⚠ 这一层**能从文件名猜**（`AK47.wav` → ak47），但猜不中时必须问。
NEEDS_BUCKET = {
    "gun_sounds": "武器",
    "switch_weapons": "武器",
    "reload_sounds": "武器",
    "weapon_kill_sounds": "武器",
    "weapon_kill_voices": "武器",
    "grenade_sounds": "投掷物",
    "round_sounds": "回合事件",
}

#: 回合音效的 8 个子事件目录名。⚠ 这是**固定集合**，不是用户起的名字 ——
#: 产品按目录名去找音频，写错一个字就是那一档永远不响。
ROUND_BUCKETS = (
    "start", "action", "win", "lose", "mvp",
    "match_start", "match_end", "halftime",
)

#: C4 三事件靠**文件名关键词**命中。⚠ 这张表抄自 `core/audio/special_events.py`
#: 的 `filename_tokens`，⭐ **它是"装进去了但不响"的唯一分界线**：
#: `find_audio_by_tokens` 一个都没命中就返回 None，**不回落、直接不响**。
C4_EVENT_TOKENS = {
    "安放": ("planted", "install", "bomb", "下包", "安放", "植入"),
    "拆除": ("defused", "defuse", "拆除", "拆包"),
    "爆炸": ("exploded", "explode", "boom", "爆炸"),
}

_WEAPON_HINT = re.compile(r"[A-Za-z0-9]{2,}")


@dataclass
class Placement:
    """一个文件该去哪。`target_rel_path` 相对资源根。"""

    source: str
    target_rel_path: str
    spec_key: str


@dataclass
class PlacementPlan:
    """一组文件的落位方案，外加"还缺什么才能算好"。"""

    placements: List[Placement] = field(default_factory=list)
    #: 还需要用户回答的问题：`[{"field": "style_name", "label": "这套风格叫什么"}]`
    questions: List[Dict] = field(default_factory=list)
    #: 不阻塞、但用户该知道的（⭐ 仿击杀图标「缺等级只提示不拦」）。
    warnings: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.questions and bool(self.placements)


def _clean_name(name: str) -> str:
    """当目录名用的清洗。⛔ 不许留下路径分隔符或 `..`（它们会变成目录层级）。"""
    text = str(name or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = text.replace("..", "_").strip(". ")
    return text or "新风格"


def guess_bucket_from_filename(filename: str) -> str:
    """从 `AK47.wav` 猜出 `ak47`。猜不出返回空串。

    ⭐ 只做**最朴素**的一件事：取文件名主干里的字母数字段。
    ⛔ 不在这里查武器表 —— 那份表在 `core/gun_sound_profiles.py`，
    而「这个词是不是一把真枪」该由调用方拿真表去判。
    **一个猜测函数不该假装自己知道全集。**
    """
    stem = os.path.splitext(str(filename or "").rsplit("/", 1)[-1])[0]
    match = _WEAPON_HINT.search(stem)
    return match.group(0).lower() if match else ""


def detect_c4_events(filenames: Sequence[str]) -> Dict[str, str]:
    """这堆文件里，C4 的三个事件各命中了哪一个文件。

    ⭐ 这个函数的产出是给**落盘前预检**用的：没命中的事件就是
    "装进去了但不会响"，要在复制之前讲出来。
    """
    found: Dict[str, str] = {}
    for name in filenames:
        low = str(name or "").lower()
        for event, tokens in C4_EVENT_TOKENS.items():
            if event in found:
                continue
            if any(str(token).lower() in low for token in tokens):
                found[event] = name
    return found


def layers_needed(spec_key: str) -> int:
    """这一类的目标结构里，文件名之前还有几层目录。

    `kill_sounds` = 1（风格）、`gun_sounds` = 2（武器 + 风格）、`death` = 0（平铺）。
    """
    return (1 if spec_key in NEEDS_BUCKET else 0) + (1 if spec_key in NEEDS_STYLE_NAME else 0)


def _layers_from_source(path: str, needed: int):
    """源路径自带的目录层。`AK47/默认/1.wav` 且需要 2 层 ⇒ `["AK47", "默认"]`。

    ⭐⭐ 这个函数是端到端手验逼出来的：第一版只看**文件名**猜武器，
    于是碰到 `AK47/默认/1.wav` 这种**结构已经对了、只是缺最外层类目录**的包，
    反而去问用户"属于哪一把武器"——而那一包里每个文件的武器都不一样，
    这个问题根本没有正确答案。
    ⚠ 而这正是**官网包最常见的形态**（社区站不规定结构，作者一般照着
    自己资源目录的样子打包）。

    层数不够返回 None（交给上面去问用户）；层数多余时取**最靠近文件的那几层**。
    """
    parts = str(path).split("/")[:-1]
    if len(parts) < needed:
        return None
    return parts[len(parts) - needed:] if needed else []


def plan_placements(
    spec_key: str,
    paths: Sequence[str],
    style_name: str = "",
    bucket: str = "",
    outer_layer: str = "",
) -> PlacementPlan:
    """把 `paths` 摆进 `spec_key` 的目标结构。

    `paths` 是包内相对路径（已剥壳）。缺什么就往 `questions` 里放什么，
    **不替用户编一个默认值** —— 编出来的风格名会变成他资源库里一个莫名其妙的目录。

    `outer_layer` 是**被剥掉的那层外壳名**。
    ⭐⭐⭐ 它存在的理由是端到端手验逼出来的第二刀：剥壳规则
    （「单层且所有文件都在里面」，与社区站 `pack_validate.php` 一致）
    在音效包上会把**风格目录本身**当成外壳剥掉 —— `风格甲/1.mp3` 剥完只剩
    `1.mp3`，风格名当场丢了，而用户明明已经在包里写好了。
    ⚠ 这条规则对击杀图标是对的（那里风格名另给），对音效包是错的。
    ⇒ 剥照剥（否则真外壳处理不了），但**剥掉的名字要带下来**，
    层数不够时优先拿它补。
    """
    plan = PlacementPlan()
    spec = get_resource_spec(spec_key)
    if spec is None:
        plan.warnings.append(f"不认识的资源类别：{spec_key}")
        return plan

    paths = [str(p).replace("\\", "/") for p in paths if str(p or "").strip()]
    if not paths:
        return plan

    root = spec.target_rel_root

    # ── 自动归类不支持的：老实说，别摆错地方 ──
    if spec_key in _UNSUPPORTED_AUTO and spec_key != "crosshair":
        plan.warnings.append(_UNSUPPORTED_AUTO[spec_key])
        return plan
    if spec_key == "crosshair":
        for path in paths:
            plan.placements.append(
                Placement(path, f"{root}/{path.rsplit('/', 1)[-1]}", spec_key))
        return plan

    # ── 特例一：被击杀音效是**平铺文件**，文件本身就是一个风格 ──
    if spec_key == "death":
        for path in paths:
            base = path.rsplit("/", 1)[-1]
            plan.placements.append(Placement(path, f"{root}/{base}", spec_key))
        plan.warnings.append(
            "被击杀音效是一个文件一个风格（不建风格目录）——"
            f"导入后会在设置页看到 {len(paths)} 个新风格，名字就是文件名。"
        )
        return plan

    # ── 特例二：回合音效要先知道是哪个子事件 ──
    if spec_key == "round_sounds" and bucket not in ROUND_BUCKETS:
        plan.questions.append({
            "field": "bucket",
            "label": "这套素材是哪一个回合事件的？",
            "choices": list(ROUND_BUCKETS),
            "why": "回合音效按事件分目录存放，放错目录那一档就不会响。",
        })

    # ── ① 源路径自带层级就直接用（官网包最常见的形态）──
    needed = layers_needed(spec_key)
    outer = str(outer_layer or "").strip()
    from_source = {}
    for path in paths:
        layers = _layers_from_source(path, needed)
        if layers is None and outer:
            # ⭐ 拿被剥掉的外壳补一层再试 —— 它多半就是风格名。
            layers = _layers_from_source(f"{outer}/{path}", needed)
        from_source[path] = layers
    # ⚠ 回合音效的第一层是**固定集合**里的名字（产品只认 `win`，
    #   而用户目录里可能叫"胜利"）⇒ 源路径里的目录名不算数，那一层永远要问。
    if spec_key == "round_sounds" and not bucket:
        from_source = {path: None for path in paths}
    covered = all(value is not None for value in from_source.values())

    # ── ② 源路径不够层时：先按文件名猜，猜不出再问 ──
    if not covered and spec_key in NEEDS_BUCKET and spec_key != "round_sounds" and not bucket:
        guessed = {guess_bucket_from_filename(p) for p in paths}
        guessed.discard("")
        if not guessed:
            plan.questions.append({
                "field": "bucket",
                "label": f"这套素材属于哪一个{NEEDS_BUCKET[spec_key]}？",
                "choices": [],
                "why": "文件名里看不出来，而这一层决定它进哪个目录。",
            })

    # ⚠ 判据逮到：`not style_name` 对 `"   "` 是 False —— 全空白会一路走到
    #   `_clean_name`，被它的兜底变成"新风格"。⭐ **一个兜底默认值放错了位置，
    #   就把"该问用户"变成了"静默编一个"**，而用户是在资源库里看到一个
    #   叫「新风格」的目录时才发现的。⇒ 判空要先 strip。
    if not covered and spec_key in NEEDS_STYLE_NAME and not str(style_name or "").strip():
        plan.questions.append({
            "field": "style_name",
            "label": "这套风格叫什么名字？",
            "choices": [],
            "why": "风格名就是设置页下拉框里显示的那一项。",
        })

    if plan.questions:
        return plan

    style = _clean_name(style_name)

    # ── 特例三：C4 三事件共用一个风格目录，落盘前先报"哪一声会缺" ──
    if spec_key == "c4_sounds":
        found = detect_c4_events([p.rsplit("/", 1)[-1] for p in paths])
        missing = [event for event in C4_EVENT_TOKENS if event not in found]
        if missing:
            plan.warnings.append(
                "这套素材里认不出「" + "」「".join(missing) + "」那一声："
                "C4 靠**文件名里的关键词**分辨三个事件，认不出来的那一档进游戏不会响。"
                "可以先导入，再把对应文件改名（比如带上「拆除」两个字）。"
            )

    for path in paths:
        base = path.rsplit("/", 1)[-1]
        parts = [root]
        source_layers = from_source.get(path)
        if covered and source_layers:
            # ⭐ 源路径已经是对的形状，原样搬过去 —— 用户没填的东西不要替他编。
            parts.extend(_clean_name(layer) for layer in source_layers)
        elif spec_key in NEEDS_BUCKET:
            chosen = bucket or guess_bucket_from_filename(base)
            parts.append(_clean_name(chosen))
        if not (covered and source_layers) and spec_key in NEEDS_STYLE_NAME:
            parts.append(style)
        parts.append(base)
        plan.placements.append(Placement(path, "/".join(parts), spec_key))

    return plan
