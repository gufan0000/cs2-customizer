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
from core.resource_readback import (
    bucket_problem,
    layout_of,
    layout_warning,
    normalize_bucket,
    numbered_slots,
    renumber,
    style_name_problem,
)

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
    # ⚠⚠ 一个文件只许命中**一个**事件，而且要命中**最像的那个**。
    #   原来是按 `C4_EVENT_TOKENS` 的字典顺序逐个试、先中先得，而「安放」
    #   的 tokens 里有一个很泛的 `bomb` ⇒ 实测
    #   `detect_c4_events(["bomb_defused.mp3", "bomb_exploded.mp3"])`
    #   把「安放」也算成已就位（命中的还是那个**拆除**的文件），
    #   于是 missing 为空、**该报的「安放那一声不会响」一个字都没报**。
    # ⭐⭐ 一条很泛的关键词会把它旁边那几条的判断一起吃掉 ——
    #   而这里的产出正是"不会响"的唯一预警，漏报等于没有预警。
    # ⇒ 改成：每个文件挑**最长的那条命中 token**（越长越specific），
    #   同一个文件不再重复认领第二个事件。
    found: Dict[str, str] = {}
    taken: set = set()
    for name in filenames:
        low = str(name or "").lower()
        best_event, best_len = "", 0
        for event, tokens in C4_EVENT_TOKENS.items():
            if event in found:
                continue
            for token in tokens:
                text = str(token).lower()
                if text and text in low and len(text) > best_len:
                    best_event, best_len = event, len(text)
        if best_event and name not in taken:
            found[best_event] = name
            taken.add(name)
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
    # ⚠ 路径里的**类目录**（`kill_sounds/` / `audio/`）不是风格层，
    #   它是这一类的目标根。原来没排除它 ⇒ `kill_sounds/1.mp3` 被当成
    #   「风格叫 kill_sounds」，落成 `audio/kill_sounds/kill_sounds/1.mp3`，
    #   而用户填的风格名被整个丢掉。
    # ⭐ 一段路径既可能是"结构"也可能是"内容"，分不清就会把结构当成内容。
    parts = [p for p in parts if not _is_structural_layer(p)]
    if len(parts) < needed:
        return None
    return parts[len(parts) - needed:] if needed else []


_STRUCTURAL_LAYERS = None


def _is_structural_layer(part: str) -> bool:
    """这一层是不是**类目录**（产品的目标结构），而不是用户起的名字。"""
    global _STRUCTURAL_LAYERS
    if _STRUCTURAL_LAYERS is None:
        from core.resource_catalog import RESOURCE_SPECS

        names = {"audio", "resources"}
        for spec in RESOURCE_SPECS:
            names.add(str(spec.key).lower())
            for piece in str(spec.target_rel_root).split("/"):
                if piece:
                    names.add(piece.lower())
        _STRUCTURAL_LAYERS = names
    return str(part or "").strip().lower() in _STRUCTURAL_LAYERS


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
        # ⚠ 这条分支**提前 return**，所以撞点检查要在这里再叫一次 ——
        #   而 death 恰恰是最容易撞的一类（不同风格目录下的同名文件全平铺到一层）。
        #   ⭐ 「提前 return 绕过了收尾检查」是这一族缺陷的常见形态。
        _warn_if_two_files_land_on_one(plan)
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
    # ⚠⚠ 而**用户答过之后也不算数**：原来只在 `not bucket` 时清空，
    #   于是用户在弹窗里选了 `win`，第二轮 `covered` 成真、走「源路径原样搬」，
    #   `outer_layer` 补进来的外壳名把它顶掉 ⇒ 实测落成
    #   `audio/round_sounds/回合音效包/胜利/1.mp3`，产品永远不会读这个目录。
    # ⭐⭐ **用户明确回答过的东西，不许再被推断出来的东西覆盖。**
    if spec_key == "round_sounds":
        from_source = {path: None for path in paths}
    covered = all(value is not None for value in from_source.values())

    # ── ② 源路径不够层时：先按文件名猜，猜不出再问 ──
    if not covered and spec_key in NEEDS_BUCKET and spec_key != "round_sounds" and not bucket:
        # ⚠⚠ 这里原来写的是「**一个都猜不出**才问」，于是只要有一个文件猜得出，
        #   其余猜不出的那些就一路走到下面的 `_clean_name("")` ⇒ 兜底成
        #   **「新风格」当武器目录**。实测：`["沙漠之鹰.wav", "ak47.wav"]` ⇒
        #   `audio/gun_sounds/新风格/默认/沙漠之鹰.wav`，而产品按武器代号找目录，
        #   这一套**永远不会响**，且全程零提示。
        # ⭐⭐ 「有一个能猜出来」不等于「这一包都能猜出来」—— 分母不是同一个。
        blind = [p for p in paths
                 if not guess_bucket_from_filename(p.rsplit("/", 1)[-1])]
        if blind:
            plan.questions.append({
                "field": "bucket",
                "label": f"这套素材属于哪一个{NEEDS_BUCKET[spec_key]}？",
                "choices": [],
                "why": (f"这 {len(blind)} 个文件的名字里看不出来"
                        f"（例如 {os.path.basename(blind[0])}），"
                        f"而这一层决定它进哪个目录 —— 放错了进游戏不会响。"),
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

    # ── 特例四：击杀图标有一条**专用导入链路**，这里只能照搬文件 ──
    if spec_key == "kill_icons":
        plan.warnings.extend(_kill_icon_caveats(paths))

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

    # ── 落盘前最后一问：**产品会不会去读这个位置** ──
    #   ⭐⭐⭐ 这一步以前完全没有，于是「导入成功」和「进游戏能响」之间
    #   没有任何东西连着。实测：`清脆/爆头.mp3` 这种包导进去报成功、
    #   设置页里看得见「清脆」，而产品找的是 `1.*`~`5.*`，一个都找不到。
    renamed, dropped = _renumber_if_needed(spec_key, paths, plan)
    _warn_if_the_product_will_not_look_there(spec_key, spec, bucket, style,
                                             covered, from_source, plan)

    for path in paths:
        if path in dropped:
            continue
        base = renamed.get(path) or path.rsplit("/", 1)[-1]
        parts = [root]
        source_layers = from_source.get(path)
        if covered and source_layers:
            # ⭐ 源路径已经是对的形状，原样搬过去 —— 用户没填的东西不要替他编。
            #   ⚠ 但 bucket 那一层要归一成产品认的 id（`AK47` ⇒ `ak47`）：
            #     产品按小写代号找目录，大小写在 Windows 上碰巧能撞对、换个盘就不行。
            cleaned = [_clean_name(layer) for layer in source_layers]
            if spec_key in NEEDS_BUCKET and cleaned:
                cleaned[0] = normalize_bucket(spec_key, cleaned[0])
            parts.extend(cleaned)
        elif spec_key in NEEDS_BUCKET:
            chosen = bucket or guess_bucket_from_filename(base)
            parts.append(normalize_bucket(spec_key, _clean_name(chosen)))
        if not (covered and source_layers) and spec_key in NEEDS_STYLE_NAME:
            parts.append(style)
        parts.append(base)
        plan.placements.append(Placement(path, "/".join(parts), spec_key))

    _warn_if_two_files_land_on_one(plan)
    return plan


def _renumber_if_needed(spec_key, paths, plan):
    """编号制的类：替用户把文件名摆成 `1`~`5`，并把这件事说出来。

    ⭐ 这正是用户要的「软件自己归类」—— 把「你得自己改名」退回给用户，
    等于这个功能只做了一半。
    """
    layout = layout_of(spec_key)
    if layout not in ("numbered", "single"):
        return {}, set()
    slots = numbered_slots(spec_key) or 1
    by_dir = {}
    for path in paths:
        by_dir.setdefault(path.rsplit("/", 1)[0] if "/" in path else "", []).append(path)
    renamed, dropped = {}, set()
    by_meaning = True
    for group in by_dir.values():
        # ⚠ 按**风格目录**分别编号：两个风格各自从 1 开始，
        #   整包一起编会让第二个风格从 4 开始、产品照样找不到 1~3。
        numbering = renumber(group, slots)
        renamed.update(numbering.mapping)
        dropped.update(numbering.dropped)
        if numbering.mapping and not numbering.by_meaning:
            by_meaning = False
    spec = get_resource_spec(spec_key)
    label = spec.label if spec else spec_key
    plan.warnings.extend(layout_warning(spec_key, label, renamed, sorted(dropped),
                                        by_meaning=by_meaning))
    return renamed, dropped


def _warn_if_the_product_will_not_look_there(spec_key, spec, bucket, style,
                                             covered, from_source, plan):
    """武器名 / 回合事件名 / 风格名 —— 产品读不到的，**明说，不猜**。"""
    checked = set()
    if bucket:
        checked.add(str(bucket))
    if covered:
        for layers in from_source.values():
            if layers and spec_key in NEEDS_BUCKET:
                checked.add(str(layers[0]))
    for value in sorted(checked):
        problem = bucket_problem(spec_key, value)
        if problem:
            plan.warnings.append(problem)
    if spec_key in NEEDS_STYLE_NAME and style and not covered:
        problem = style_name_problem(style)
        if problem:
            plan.warnings.append(f"风格名「{style}」产品收不下：{problem}。")


#: 击杀图标一个风格该有的等级。⚠ 产品按 `<等级>.png` + `<等级>.json` 成对读。
_KILL_ICON_LEVELS = ("1", "2", "3", "4", "5")
_KILL_ICON_ENTRY_RE = re.compile(r"^([1-5])(hs)?\.(png|json)$", re.IGNORECASE)


def _kill_icon_caveats(paths):
    """击杀图标包走统一链路时，**说清它和专用导入器的差别**。

    ⭐⭐⭐ 统一链路做的是 `shutil.copy2`，而击杀图标的专用导入器
    （`core/kill_icon_pack.import_pack` → `kill_icon_import.convert_to_style`）
    对每个等级还要做三件这里做不了的事：
    ① **补 `hold_seconds`** —— 单帧素材没有它只会在屏幕上闪 **0.03 秒**
       （KI-4 之前就是这个表现，而且零提示）；
    ② **钳 `fps`** 到合法范围；
    ③ **验 json 是不是本产品的图集格式**，不是就重新打图集
       （`1.gif`、`3/` 逐帧目录这些"松散包"全靠这一步）。
    ⇒ 这里不复刻那条链路（复刻出来的那份从复刻完就开始漂，见 RN-002），
      而是**如实说出差别**，并把用户指到那条真正能处理它的入口。
    """
    names = [str(p).rsplit("/", 1)[-1] for p in paths]
    entries = {}
    loose = []
    for name in names:
        match = _KILL_ICON_ENTRY_RE.match(name)
        if match:
            entries.setdefault(match.group(1), set()).add(match.group(3).lower())
        elif name.lower() not in ("style.json", "cs2customizer_pack.json"):
            loose.append(name)
    lines = []
    half = sorted(level for level, kinds in entries.items()
                  if kinds != {"png", "json"})
    if half:
        lines.append(
            f"这套图标里 {'、'.join(half)} 杀只有半套文件（缺 .png 或 .json），"
            f"那几个等级进游戏不会显示。")
    missing = [level for level in _KILL_ICON_LEVELS if level not in entries]
    if entries and missing:
        lines.append(
            f"这套图标缺 {'、'.join(missing)} 杀的素材 —— "
            f"打到那几个等级时不会有图标弹出来。")
    if loose:
        lines.append(
            f"包里有 {len(loose)} 个不是 `1.png`/`1.json` 这种标准条目的文件"
            f"（{'、'.join(loose[:3])}{'…' if len(loose) > 3 else ''}）。"
            f"这个页面只会原样搬运，不会替你打图集 —— "
            f"这类包请改用「击杀图标」页里的素材导入，那条路会做格式转换。")
    if entries and not loose:
        lines.append(
            "击杀图标这里只做原样搬运：包里 json 的播放参数会照搬。"
            "如果导完之后图标一闪而过或者不动，请改用「击杀图标」页的素材导入，"
            "那条路会补齐播放参数。")
    return lines


def _warn_if_two_files_land_on_one(plan):
    """两个源文件算出同一个落点 ⇒ 后一个盖掉前一个，而计数会报两个。

    ⭐ 实测：`风格甲/death.mp3` 与 `风格乙/death.mp3` 选「被击杀音效」
    都落到 `audio/death/death.mp3`。
    """
    seen = {}
    clashes = []
    for item in plan.placements:
        key = item.target_rel_path.lower()
        if key in seen:
            clashes.append((seen[key], item.source, item.target_rel_path))
        else:
            seen[key] = item.source
    if clashes:
        first = clashes[0]
        plan.warnings.append(
            f"有 {len(clashes)} 组文件会落到同一个位置（例如 "
            f"`{first[0]}` 和 `{first[1]}` 都落到 `{first[2]}`），"
            f"后一个会盖掉前一个。请先把它们改成不同的文件名。")
