# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""这一坨文件是什么资源？——三级漏斗（2026-09-16，资源导入统一化）。

背景与全套设计见 `docs/资源导入_设计方案_v1_20260916.md`。这里只记**本模块特有**的两件事：

⭐⭐⭐ **"认不出"不是异常，是常态。** 12 类音频共用扩展名，其中 5 类连结构都一样
（`<武器>/<风格>/*.音频`），社区站又明写除击杀图标外没有目录规范。
⇒ 输出不是"是/否"，是**带置信度的猜测 + 给用户看的证据**：
`certain` 直接落盘 / `likely` 预选好让人扫一眼 / `unsure` 必须问且要摆出证据。

⭐ 四个信号，旧实现只用了第一个：路径里的 spec 目录名（最硬）、**包名**
（杠杆最大：官网下载名就是「资源标题.zip」，不改站端就能吃掉官网包）、
清单文件、结构与内容特征。

⚠ 本模块**只读、纯函数**，判据能直接喂假数据跑。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from core.resource_catalog import RESOURCE_SPECS, ResourceSpec, build_spec_lookup

#: 通用清单文件名。击杀图标那份叫 `style.json`（已成既成事实，不动它）。
MANIFEST_NAMES = ("cs2customizer_pack.json", "style.json")

#: 置信度三档。⚠ 顺序有意义：`_rank` 按这个排。
CERTAIN = "certain"
LIKELY = "likely"
UNSURE = "unsure"
_RANK = {CERTAIN: 0, LIKELY: 1, UNSURE: 2}


#: 品类词典：**包名里出现这些词就算命中**。
#:
#: ⭐⭐ 匹配规则是**最长优先**，这条不是优化是正确性：
#:   「武器击杀音效」含「击杀音效」、「击杀语音」含「击杀」。
#:   按出现顺序匹配会把 `weapon_kill_sounds` 判成 `kill_sounds`。
#:
#: ⚠ 词是**从玩家怎么说**来的，不是从 `ResourceSpec.label` 抄的 ——
#:   label 是给设置页看的书面语（"投掷物音效"），而社区站标题里写的是
#:   "手雷音效包""道具音"。两边都要收。
#: ⛔ 别往这里加太泛的词（"音效""包""cs2"）：它们会让每个包都命中同一类，
#:   而**一个总是命中的信号等于没有信号**。
CATEGORY_WORDS: Dict[str, tuple] = {
    "weapon_kill_sounds": ("武器击杀音效", "分枪击杀音效", "按枪击杀音效"),
    "weapon_kill_voices": ("武器击杀语音", "分枪击杀语音"),
    "kill_sounds": ("击杀音效", "击杀音", "杀敌音效", "killsound", "kill_sound", "击杀声"),
    "kill_voices": ("击杀语音", "报杀", "killvoice", "kill_voice", "语音包"),
    "death": ("被击杀音效", "死亡音效", "阵亡音效", "被杀音效", "deathsound"),
    "switch_weapons": ("切枪音效", "切枪", "换枪音效", "switchweapon"),
    "reload_sounds": ("换弹音效", "换弹", "装弹音效", "reload"),
    "grenade_sounds": ("投掷物音效", "道具音效", "手雷音效", "grenade"),
    "c4_sounds": ("c4音效", "c4", "下包音效", "拆包音效", "炸弹音效"),
    "health_warning": ("血量警告", "残血提示", "低血量", "血量提示"),
    "round_sounds": ("回合音效", "回合结算", "开局音效", "胜负音效"),
    "gun_sounds": ("枪声替换", "枪声", "枪音", "gunsound", "开枪音效"),
    "flash_images": ("闪光图片", "闪光图", "自定闪光", "flashimage"),
    "flash_audio": ("闪光音频", "闪光音效", "flashaudio"),
    "kill_icons": ("击杀图标", "killicon", "kill_icon", "图标包"),
    "utility_guides": ("道具瞄点", "投掷点位", "道具点位", "瞄点", "身位图"),
    "crosshair": ("准心", "准星", "crosshair"),
}

#: 那五类共用「`<武器>/<风格>/*.音频`」，结构上**分不开**。
#: ⭐ 它们必须一起摆给用户，不能替他挑一个 —— 挑错了是静默的（文件进了错目录，
#:   页面上那一类就是空的，而用户以为导进去了）。
WEAPON_SHAPED = (
    "gun_sounds", "switch_weapons", "reload_sounds",
    "weapon_kill_sounds", "weapon_kill_voices",
)

#: 单层「`<风格>/*.音频`」也同构：击杀音效 / 击杀语音 / 血量警告 / C4。
STYLE_SHAPED = ("kill_sounds", "kill_voices", "health_warning", "c4_sounds")

#: 单层「`<名>/*.图片`」同构：闪光图片 / 道具瞄点。
IMAGE_SHAPED = ("flash_images", "utility_guides")

_KILL_ICON_ENTRY = re.compile(r"^([1-5])(hs)?\.(png|json)$", re.IGNORECASE)
_AUDIO_EXT = (".mp3", ".wav", ".ogg")
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


@dataclass
class Guess:
    """一个猜测。`evidence` 是**给用户看的**，不是日志。"""

    spec_key: str
    label: str
    confidence: str
    evidence: List[str] = field(default_factory=list)


def style_name_from_manifest(manifest) -> str:
    """清单文件里写好的风格名。

    ⭐⭐ 击杀图标包（社区站**唯一**有规范的一类）的 `style.json` 带着 `name`，
    而核查时发现导入还在问"这套风格叫什么名字" —— 用户明明已经在包里写过了。
    ⚠ 这一条直接影响「官网资源更方便兼容」那个要求：官网包该一句都不问。
    """
    if not isinstance(manifest, dict):
        return ""
    for key in ("style_name", "name", "title"):
        value = str(manifest.get(key) or "").strip()
        if value:
            return value
    return ""


@dataclass
class Group:
    """一坨同构的文件。⭐ 用户对着**组**选一次，不是对着文件选 N 次。"""

    #: 包内相对路径（已剥壳）。
    paths: List[str]
    #: 形状指纹。相同指纹的下一次可以直接套用上次的选择（学习表的键）。
    shape: str
    #: 按置信度排好的猜测；第一个就是 UI 该预选的那个。
    guesses: List[Guess] = field(default_factory=list)
    #: 这一组共同的目录前缀，用来在 UI 上说"这些文件都在 X 下"。
    common_dir: str = ""

    @property
    def confidence(self) -> str:
        return self.guesses[0].confidence if self.guesses else UNSURE

    @property
    def needs_user(self) -> bool:
        """要不要**拦住用户问一句**。只有拿不准才问。

        ⚠ 第一版写的是 `!= CERTAIN`，于是 `likely` 也弹窗 ——
        而官网包的主力信号（包名词典）全落在 `likely` 档，
        ⇒ **每一个官网包都要点一次确定**，与「官网资源更方便兼容」直接冲突。
        ⭐ `likely` 会不会错？会。防它的位置是**结果可见**（报告里逐条列出
        「凭什么归到这一类」），不是事前拦一道 —— 那只是把一次点击
        强加给每个用户，而真会去核对的人本来就会看报告。
        """
        return self.confidence == UNSURE

    @property
    def preselect(self):
        """UI 该预先选中的那一项；拿不准时是 **None**。

        ⭐⭐ 这个属性存在的理由是手验逮到的一件事：`guesses[0]` 在 `unsure` 档
        也是一个具体类别（候选表的第一个），UI 照着它预选就等于**替用户瞎猜**，
        而用户看到一个已选好的下拉框会默认它是对的。
        ⇒ 拿不准就**一个都不选**，逼出那一次真实的选择。
        """
        if self.confidence == UNSURE or not self.guesses:
            return None
        return self.guesses[0]


def _norm(text: str) -> str:
    """归一化用于词典匹配：小写、去掉分隔符与空白。

    ⭐ 去分隔符是必需的：`kill_sound` / `kill-sound` / `kill sound` 是同一个词，
    而官网标题里三种写法都有。
    """
    return re.sub(r"[\s_\-·.、，,]+", "", str(text or "").lower())


def match_category_words(name: str) -> List[tuple]:
    """包名 → `[(spec_key, 命中的词), ...]`，**最长的词排前面**。

    ⚠ 只返回命中，不做取舍 —— 取舍是 `identify_groups` 的事，
    因为它还要结合结构（光靠名字命中"击杀音效"但里面全是图片，那就该降档）。
    """
    haystack = _norm(name)
    if not haystack:
        return []
    hits = []
    for key, words in CATEGORY_WORDS.items():
        for word in words:
            if _norm(word) and _norm(word) in haystack:
                hits.append((key, word))
    hits.sort(key=lambda item: len(_norm(item[1])), reverse=True)
    return hits


def _spec(key: str) -> ResourceSpec | None:
    return next((item for item in RESOURCE_SPECS if item.key == key), None)


def _label(key: str) -> str:
    spec = _spec(key)
    return spec.label if spec else key


def read_manifest(paths: Sequence[str], read_text) -> Dict:
    """包里有没有清单文件。`read_text(相对路径) -> str | None` 由调用方给。

    ⭐ 注入读取函数而不是收一个目录：这样 zip 不用先解压到磁盘就能探，
    和 `kill_icon_pack.probe_pack`「只读、不写任何文件」是同一条纪律。
    """
    for path in paths:
        base = path.rsplit("/", 1)[-1].lower()
        if base not in MANIFEST_NAMES:
            continue
        try:
            raw = read_text(path)
        except Exception:
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _shape_of(paths: Sequence[str]) -> str:
    """这一坨长什么样。⭐ 指纹要**粗**：它是"下次还问不问"的键，
    太细就永远命中不了，太粗就会把不同的东西并成一类。

    形如 `dir1/audio`、`dir2/audio`、`flat/image`、`killicon`。
    """
    if not paths:
        return "empty"
    if all(_KILL_ICON_ENTRY.match(p.rsplit("/", 1)[-1]) for p in paths):
        return "killicon"
    depths = {p.count("/") for p in paths}
    exts = {os.path.splitext(p)[1].lower() for p in paths}
    if exts <= set(_AUDIO_EXT):
        family = "audio"
    elif exts <= set(_IMAGE_EXT):
        family = "image"
    elif exts <= {".xchr", ".json"}:
        family = "crosshair"
    else:
        family = "mixed"
    depth = min(depths) if depths else 0
    return ("flat" if depth == 0 else f"dir{depth}") + "/" + family


def _common_dir(paths: Sequence[str]) -> str:
    dirs = {p.rsplit("/", 1)[0] if "/" in p else "" for p in paths}
    return dirs.pop() if len(dirs) == 1 else ""


#: 中文目录名 → spec key。⚠⚠ **`build_spec_lookup()` 只收英文 key / 目录名 / 别名，
#: 17 个中文 label 一个都不在里面** —— 于是 `kill_sounds/清脆/1.mp3` 认得出，
#: 而中文用户最自然的 `击杀音效/清脆/1.mp3` **认不出**。
#: ⭐⭐⭐ 这是核查时拿真实写法喂进去才看见的：英文路径走得通，
#: 让人以为"路径规则работает"，而产品的用户是中文玩家，他们打的包是中文目录名。
#: ⛔ 不去改 `resource_catalog.build_spec_lookup`：那张表是导入向导与同步面的共用契约
#: （X12 层契约冻着它），在这里加一层映射的影响面小得多。
_LABEL_TO_KEY = {spec.label: spec.key for spec in RESOURCE_SPECS}


def _spec_key_in_path(path: str) -> str:
    """路径里有没有 spec 目录名（英文 key / 目录名 / 别名 / **中文 label**）。"""
    lookup = build_spec_lookup()
    for part in path.split("/"):
        bare = part.strip()
        spec = lookup.get(bare.lower())
        if spec:
            return spec.key
        if bare in _LABEL_TO_KEY:
            return _LABEL_TO_KEY[bare]
    return ""


def remembered_key(shape: str, memory) -> str:
    """这个形状上次被归成了哪一类。`memory` 是 `{形状: spec_key}`。"""
    if not isinstance(memory, dict):
        return ""
    key = str(memory.get(str(shape or "")) or "").strip()
    return key if _spec(key) else ""


def identify_groups(
    paths: Sequence[str],
    source_name: str = "",
    manifest: Dict | None = None,
    memory: Dict | None = None,
) -> List[Group]:
    """把一包文件分成几组，每组带排好序的猜测。

    `paths` 是**已剥壳**的包内相对路径；`source_name` 是压缩包名或文件夹名。
    """
    paths = [str(p).replace("\\", "/") for p in paths if str(p or "").strip()]
    # ⚠ 判据逮到：清单文件**自己不是素材**，让它参与分组会凭空多出一组
    #   （`cs2customizer_pack.json` 是 `flat/mixed`，和真正的素材不同形状）。
    # ⭐ 它是**元数据**，读完就该退场 —— 留在清单里只会让用户看到一组
    #   "这一个 json 是什么资源？"的莫名其妙的提问。
    paths = [p for p in paths if p.rsplit("/", 1)[-1].lower() not in MANIFEST_NAMES]
    if not paths:
        return []

    manifest = manifest or {}
    manifest_key = str(manifest.get("category") or manifest.get("spec_key") or "").strip()
    # 清单里若写了类别、且那个类别真实存在 ⇒ 整包一组，certain。
    if manifest_key and _spec(manifest_key):
        return [Group(
            paths=list(paths),
            shape=_shape_of(paths),
            common_dir=_common_dir(paths),
            guesses=[Guess(manifest_key, _label(manifest_key), CERTAIN,
                           [f"包里的清单文件写明了类别：{_label(manifest_key)}"])],
        )]

    # ① 路径里带 spec 目录名的，各自按 spec 归组（这一档是 certain）。
    by_spec: Dict[str, List[str]] = {}
    rest: List[str] = []
    for path in paths:
        key = _spec_key_in_path(path)
        (by_spec.setdefault(key, []) if key else rest).append(path)

    groups: List[Group] = []
    for key, items in by_spec.items():
        groups.append(Group(
            paths=items,
            shape=_shape_of(items),
            common_dir=_common_dir(items),
            guesses=[Guess(key, _label(key), CERTAIN,
                           [f"路径里带着 {_label(key)} 的目录名"])],
        ))

    if not rest:
        return groups

    # ② 剩下的按"形状"归组，再拿包名与结构给猜测。
    shaped: Dict[str, List[str]] = {}
    for path in rest:
        shaped.setdefault(_shape_of([path]), []).append(path)

    name_hits = match_category_words(source_name)
    for shape, items in shaped.items():
        group = _guess_for_shape(shape, items, name_hits, source_name)
        # ⭐ 上次对同样形状做过的选择，这次直接用 —— 但**降一档记在证据里**，
        #   让用户在报告里看得见"这是照上次办的"，而不是无声地照办。
        learned = remembered_key(shape, memory)
        if learned and group.confidence == UNSURE:
            group.guesses = [Guess(
                learned, _label(learned), LIKELY,
                ["上次同样结构的素材你归成了这一类"] + list(group.guesses[0].evidence
                                                          if group.guesses else []),
            )] + [g for g in group.guesses if g.spec_key != learned]
        groups.append(group)
    return groups


def _guess_for_shape(
    shape: str,
    items: List[str],
    name_hits: List[tuple],
    source_name: str,
) -> Group:
    """给一组同形状的文件排猜测。⭐ 这里是整个模块唯一"拿不准"的地方，
    所以每条猜测都必须带上它凭什么 —— 用户是看着 evidence 做决定的。
    """
    group = Group(paths=items, shape=shape, common_dir=_common_dir(items))
    style_count = len({p.split("/")[0] for p in items if "/" in p})
    evidence_common = [f"共 {len(items)} 个文件"]
    if group.common_dir:
        evidence_common.append(f"都在 `{group.common_dir}/` 下")
    if style_count > 1:
        evidence_common.append(f"分成 {style_count} 个子目录")

    # 击杀图标是唯一有硬结构的一类：`1~5[hs].png/json`。
    if shape == "killicon":
        group.guesses = [Guess("kill_icons", _label("kill_icons"), LIKELY,
                               ["文件名是 1~5（含 hs 爆头变体）的图标编号"] + evidence_common)]
        return group

    candidates = _candidates_for_shape(shape)
    # 包名命中且命中的类在候选里 ⇒ 升到 likely 并排到最前。
    ranked: List[Guess] = []
    # ⚠ 手验逮到：`match_category_words` 对同一类可能命中**多个词**
    #   （"CF爆头音效 击杀音效包" 同时命中「击杀音效」和「击杀音」），
    #   照单全收会让同一个类在备选里出现两次。⭐ 命中越多说明证据越强，
    #   不是候选越多 —— 按类去重，留最长的那个词当证据。
    hit_once = {}
    for key, word in name_hits:
        if key not in hit_once:
            hit_once[key] = word
    for key, word in hit_once.items():
        if key in candidates:
            ranked.append(Guess(key, _label(key), LIKELY,
                                [f"包名里有「{word}」"] + evidence_common))
    seen = {item.spec_key for item in ranked}
    for key in candidates:
        if key in seen:
            continue
        ranked.append(Guess(key, _label(key), UNSURE, list(evidence_common)))

    if not ranked:
        # 形状完全认不出（混合扩展名之类）。⭐ 仍然要给一个可选清单，
        #   否则用户除了放弃没有别的动作可做。
        ranked = [Guess(spec.key, spec.label, UNSURE, list(evidence_common))
                  for spec in RESOURCE_SPECS]
    group.guesses = sorted(ranked, key=lambda item: _RANK[item.confidence])
    return group


def _candidates_for_shape(shape: str) -> List[str]:
    """这个形状**可能**是哪几类。⭐ 宁可多给几个让用户挑，
    也不要替他缩成一个 —— 缩错了是静默的。
    """
    if shape.startswith("dir2/") and shape.endswith("audio"):
        return list(WEAPON_SHAPED) + ["round_sounds", "grenade_sounds"]
    if shape.startswith("dir1/") and shape.endswith("audio"):
        return list(STYLE_SHAPED) + list(WEAPON_SHAPED)
    if shape.startswith("flat/") and shape.endswith("audio"):
        # ⚠ `death` 是唯一"平铺文件就是一个风格"的类（`audio/death/xxx.mp3`），
        #   其余音频类平铺进来都得先归到某个风格目录下。
        return ["death"] + list(STYLE_SHAPED)
    if shape.endswith("image"):
        return list(IMAGE_SHAPED) + ["kill_icons"]
    if shape.endswith("crosshair"):
        return ["crosshair"]
    return []
