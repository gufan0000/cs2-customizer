# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""落盘之前问一句：**产品到底会不会去读这个位置**（2026-09-17）。

## 这一层存在的理由

识别、归类、落盘三层都只管把文件**摆成目标结构**，而「目标结构对不对」
取决于产品那头**怎么找** —— 而那套规则散在三个互不相识的地方：

| 产品那头的规则 | 真源 | 摆错了的表现 |
|---|---|---|
| 击杀音效/语音**只按 `1`~`5` 的文件名找** | `core/audio/style_creator.CATEGORY_TEMPLATES` | 风格出现在下拉框里，**进游戏一声不响** |
| 枪声替换只认 20 个**小写武器 id** | `core/gun_sound_profiles.GUN_SOUND_WEAPON_TYPES` | `沙漠之鹰/` 这种目录永远不会被读到 |
| 回合音效只认 8 个**固定事件目录名** | `resource_placement.ROUND_BUCKETS` | 那一档永远不响 |
| 风格名有保留字与非法字符 | `style_creator.validate_style_name` | 目录建得出来、产品当它不存在 |

⭐⭐⭐ **谁都没有回头看一眼** —— 于是「导入成功」和「进游戏能响」之间
没有任何东西连着。实测：一个 `清脆/爆头.mp3`「清脆/双杀.mp3」的击杀音效包
导进去报成功、设置页里看得见「清脆」这个风格，而
`AudioManager._load_range` 找的是 `1.*`~`5.*`，**一个都找不到**。

## 两种处置，分得很清

- **能替用户摆对的就摆对**（编号制 ⇒ 按名字排序重命名成 `1`~`5`）——
  这正是用户要的「软件自己归类」，不是把难题退回给他。
- **摆不对的就明说**（武器名不在产品的表里）—— ⛔ 不许猜：
  猜错一个武器名，用户是**进游戏之后**才发现的，而那时他已经不记得导过什么。

⛔ 这里**不新建任何一张表**。四条规则全部从产品自己的真源现读，
   照抄一份的代价见 RN-002：只要还有第二份副本，修好一份就等于没修。
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

#: `CATEGORY_TEMPLATES` 是按**自己的类别键**（`kill_sound`）索引的，
#: 而这条链路用的是 spec key（`kill_sounds`）。两边的桥是**目标根目录**，
#: 它在两边都是逐字相同的字符串 —— 比再写一张对照表可靠。
_LAYOUT_CACHE: Optional[Dict[str, Tuple[str, int]]] = None


def _layout_table() -> Dict[str, Tuple[str, int]]:
    """`{目标根目录: (layout, max_files)}`，从产品自己的模板表现算。"""
    global _LAYOUT_CACHE
    if _LAYOUT_CACHE is None:
        from core.audio.style_creator import CATEGORY_TEMPLATES

        table: Dict[str, Tuple[str, int]] = {}
        for template in CATEGORY_TEMPLATES.values():
            entry = (template.layout, int(template.max_files))
            table[template.root] = entry
            if template.weapon_root:
                # ⚠ 武器专属根（`weapon_kill_sounds`）用的是**同一套**命名规则，
                #   产品那头也是同一个 `_load_range`。
                table[template.weapon_root] = entry
        _LAYOUT_CACHE = table
    return _LAYOUT_CACHE


def layout_of(spec_key: str) -> str:
    """这一类的文件名规矩：`numbered` / `single` / `flat` / `free`。

    `free` 表示产品那头不挑文件名（闪光图片、道具瞄点这些按目录扫）。
    """
    return _layout_table().get(str(spec_key or ""), ("free", 0))[0]


def numbered_slots(spec_key: str) -> int:
    """编号制最多几个槽（产品只找到这个数为止）。"""
    return _layout_table().get(str(spec_key or ""), ("free", 0))[1]


#: 哪几类的 bucket 层是**产品的固定集合**，以及它的真源。
#: ⭐⭐ RN-662：`grenade_sounds` 以前不在这里，旧注释说它「没有固定表」——**那是错的**，
#: 产品读的就是 `AudioManager.GRENADE_TYPES` 这个六元组。返回 `None` 会让
#: `bucket_problem()` 短路 ⇒ 目录名写错**永不报警**，文件静静躺在产品不读的地方。
#: ⭐ 「按目录扫」和「没有固定表」是两件事 —— 扫的是风格层，类型层一直是固定的。
def known_buckets(spec_key: str) -> Optional[frozenset]:
    """这一类的 bucket 层只许是哪些值；`None` 表示产品不挑。"""
    key = str(spec_key or "")
    if key == "round_sounds":
        from core.resource_placement import ROUND_BUCKETS

        return frozenset(ROUND_BUCKETS)
    if key == "grenade_sounds":
        from core.audio.audio_manager import AudioManager

        return frozenset(str(t).lower() for t in AudioManager.GRENADE_TYPES)
    if key in ("gun_sounds", "switch_weapons", "reload_sounds",
               "weapon_kill_sounds", "weapon_kill_voices"):
        from core.gun_sound_profiles import GUN_SOUND_WEAPON_TYPES

        return frozenset(str(w).lower() for w in GUN_SOUND_WEAPON_TYPES)
    return None


_BUCKET_ALIAS_CACHE: Optional[Dict[str, str]] = None


def _bucket_aliases() -> Dict[str, str]:
    """武器的别名 → 规范 id。**全部从产品自己的档案表现算**。

    ⭐ 只收两种有据可查的写法：档案里的 `display_name`（`AK-47` / `Desert Eagle`）
    和它去掉分隔符的形态。⛔ 不收社区黑话（「沙鹰」「大狙」）——
    那种表一旦开头就会越长越歪，而**猜错一个武器名，用户是进游戏才发现的**。
    认不出的一律走 `bucket_problem()` 明说，不猜。
    """
    global _BUCKET_ALIAS_CACHE
    if _BUCKET_ALIAS_CACHE is None:
        from core.gun_sound_profiles import GUN_SOUND_PROFILE_LIST

        table: Dict[str, str] = {}
        for profile in GUN_SOUND_PROFILE_LIST:
            canonical = str(profile.gun_type).lower()
            for raw in (profile.gun_type, profile.display_name):
                text = str(raw or "").strip().lower()
                if not text:
                    continue
                table[text] = canonical
                table[text.replace("-", "").replace(" ", "").replace("_", "")] = canonical
        _BUCKET_ALIAS_CACHE = table
    return _BUCKET_ALIAS_CACHE


def normalize_bucket(spec_key: str, raw: str) -> str:
    """把用户写的 bucket 归一成产品认的那个 id；归一不了原样返回。

    ⭐ 归一是**大小写与分隔符**层面的（`AK47` / `AK-47` ⇒ `ak47`），
    到此为止。语义层面的猜测（`沙漠之鹰` ⇒ `deagle`）不做 —— 见 `_bucket_aliases`。
    """
    text = str(raw or "").strip()
    if not text:
        return text
    allowed = known_buckets(spec_key)
    if allowed is None:
        return text
    lowered = text.lower()
    if lowered in allowed:
        return lowered
    return _bucket_aliases().get(
        lowered,
        _bucket_aliases().get(
            lowered.replace("-", "").replace(" ", "").replace("_", ""), text))


def bucket_problem(spec_key: str, bucket: str) -> Optional[str]:
    """这个 bucket 产品读不读得到？读不到就返回一句能照着做的话。"""
    allowed = known_buckets(spec_key)
    if allowed is None:
        return None
    value = str(bucket or "").strip()
    if not value:
        return None          # 空值由归类器那头的"要问用户"管，不在这里重复报
    if value.lower() in allowed:
        return None
    sample = "、".join(sorted(allowed)[:8])
    if str(spec_key) == "round_sounds":
        return (f"「{value}」不是产品认识的回合事件目录名，导进去那一档不会响。"
                f"只认这 8 个：{'、'.join(sorted(allowed))}。")
    return (f"「{value}」不是产品认识的武器目录名，导进去这一套不会响。"
            f"产品按 CS2 的武器代号找目录（{sample} 等 {len(allowed)} 个），"
            f"请把这一层目录改成对应代号再导一次。")


def style_name_problem(name: str) -> Optional[str]:
    """风格名产品收不收？⛔ 走产品自己的校验，不在这里另写一套。"""
    from core.audio.style_creator import validate_style_name

    return validate_style_name(name)


#: 编号 N 的含义是**本回合第 N 杀**（`_load_range` 按 1~5 找，`N-headshot` 是
#: 第 N 杀的爆头变体）。所以「按名字排序」是错的：`单杀/双杀/三杀/四杀/五杀`
#: 按码位排出来是 三/五/单/双/四 —— **5/5 全部错位**，而且还跟用户说「已替你重命名」
#: （2026-09-17 隔壁会话拿真函数跑出来的；`single/double/triple/quad/ace` 同样 4/5 错）。
#: ⇒ 先按**名字里的击杀数**排；名字里看不出来的才退回文件名顺序，并且**明说**。
#: ⛔ 这张表只收「第 N 杀」的叫法，不收「爆头 / 收割 / 连杀」这类不是次数的词。
_RANK_WORDS_CN: Tuple[Tuple[str, int], ...] = (
    ("单杀", 1), ("一杀", 1), ("首杀", 1),
    ("双杀", 2), ("二杀", 2), ("两杀", 2),
    ("三杀", 3), ("叁杀", 3),
    ("四杀", 4), ("肆杀", 4),
    ("五杀", 5), ("伍杀", 5), ("团灭", 5),
)
_RANK_WORDS_EN: Dict[str, int] = {
    "single": 1, "first": 1, "one": 1,
    "double": 2, "second": 2, "two": 2,
    "triple": 3, "third": 3, "three": 3,
    "quad": 4, "quadra": 4, "quadruple": 4, "fourth": 4, "four": 4,
    "ace": 5, "penta": 5, "quintuple": 5, "fifth": 5, "five": 5,
}
_HEADSHOT_MARKS = ("headshot", "爆头")


def _rank_of(stem: str, slots: int) -> Optional[int]:
    """名字里写的是第几杀；看不出来或有歧义就 `None`。"""
    low = stem.lower()
    ranks = set()
    for word, rank in _RANK_WORDS_CN:
        if word in stem:
            ranks.add(rank)
    for word in re.findall(r"[a-z]+", low):
        if word in _RANK_WORDS_EN:
            ranks.add(_RANK_WORDS_EN[word])
    for digits in re.findall(r"\d+", low):
        ranks.add(int(digits))
    ranks = {r for r in ranks if 1 <= r <= slots}
    return ranks.pop() if len(ranks) == 1 else None


def _is_headshot_variant(stem: str) -> bool:
    low = stem.lower()
    return any(mark in low for mark in _HEADSHOT_MARKS)


class Numbering:
    """`renumber()` 的结果：`mapping` 原名→新名、`dropped` 放不下的、
    `by_meaning` 是不是按名字里的击杀数排的（否则是按文件名顺序，要明说）。"""

    __slots__ = ("mapping", "dropped", "by_meaning")

    def __init__(self, mapping: Dict[str, str], dropped: List[str], by_meaning: bool):
        self.mapping = mapping
        self.dropped = dropped
        self.by_meaning = by_meaning

    def __iter__(self):
        # 兼容 `mapping, dropped = renumber(...)` 这种两元解包。
        yield self.mapping
        yield self.dropped


def renumber(paths: Sequence[str], slots: int) -> "Numbering":
    """编号制：把文件重命名成 `1` / `2` / …（`N-headshot` 为爆头变体）。

    两档，**每一档都必须对同一个包的两次导入给出同一个结果**
    （按包里的条目顺序「先到先得」会让结果取决于打包工具，
    同 `kill_icon_pack._collect_loose_items` 那条已经踩过的坑）：

    1. 每个名字都能读出「第几杀」且互不撞号 ⇒ **按击杀数**编。
       已经叫 `1`~`N` / `N-headshot` 的官网包（最常见的形态）走的也是这一档：
       算出来的目标名和原名相同 ⇒ 不进 `mapping`，**原样不动**。
       ⚠ 第一版另有一道「纯数字才算已编号」的前置判断，`1-headshot.mp3` 过不了它，
       整包被重排成 1/2/3/4 —— 一个作者编好的包就这么被拆散。那道判断和这一档互相兜着，
       单独撤掉哪个都不红（RN-002 形态）⇒ 删掉，只留这一档。
    2. 否则按文件名排序编 —— 这是猜，`layout_warning` 会把这件事说出来。
    """
    names = sorted(str(p) for p in paths)
    stems = [os.path.splitext(os.path.basename(n))[0] for n in names]

    ranked = [(_rank_of(s, slots), _is_headshot_variant(s)) for s in stems]
    keys = [(r, hs) for r, hs in ranked]
    if all(r is not None for r, _ in ranked) and len(set(keys)) == len(keys):
        mapping = {}
        for name, (rank, hs) in zip(names, ranked):
            ext = os.path.splitext(name)[1]
            target = f"{rank}{'-headshot' if hs else ''}{ext}"
            if target != os.path.basename(name):     # 本来就叫对的不算「改了名」
                mapping[name] = target
        return Numbering(mapping, [], True)

    mapping: Dict[str, str] = {}
    dropped: List[str] = []
    for index, name in enumerate(names, start=1):
        if index > slots:
            dropped.append(name)
            continue
        ext = os.path.splitext(name)[1]
        mapping[name] = f"{index}{ext}"
    return Numbering(mapping, dropped, False)


def layout_warning(spec_key: str, label: str, renamed: Dict[str, str],
                   dropped: Sequence[str], by_meaning: bool = True) -> List[str]:
    """把重命名/丢弃这件事讲给用户听。⭐ 替他做了就要说，不许静默；
    **猜的就要说是猜的**（按文件名顺序编号时，1~5 对应第几杀全靠运气）。"""
    lines: List[str] = []
    if renamed:
        sample = "、".join(f"{os.path.basename(k)} → {v}"
                           for k, v in list(renamed.items())[:3])
        more = f" 等 {len(renamed)} 个" if len(renamed) > 3 else ""
        slots = numbered_slots(spec_key)
        if by_meaning:
            lines.append(
                f"{label}是按 1~{slots} 的文件名播放的（1 = 单杀 … {slots} = 五杀），"
                f"已经按名字里的击杀数替你重命名：{sample}{more}。"
                f"（原来的名字产品不会读，导进去也不会响。）")
        else:
            lines.append(
                f"{label}是按 1~{slots} 的文件名播放的（1 = 单杀 … {slots} = 五杀），"
                f"这些名字里看不出是第几杀，先按文件名顺序编成了：{sample}{more}。"
                f"顺序不对的话，导入后到这个风格的文件夹里把 1~{slots} 改过来。")
    if dropped:
        lines.append(
            f"{label}一个风格最多 {numbered_slots(spec_key)} 个文件，"
            f"多出来的 {len(dropped)} 个没有导入："
            f"{'、'.join(os.path.basename(d) for d in dropped[:4])}"
            f"{' 等' if len(dropped) > 4 else ''}。")
    return lines
